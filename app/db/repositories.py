from __future__ import annotations

from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Comprobante, Factura, FacturaDetalle, AuditLog


def _dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


class ComprobanteRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        task_id: str,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        file_size: Optional[int] = None,
        status: str = "processing",
    ) -> Comprobante:
        row = Comprobante(
            task_id=task_id,
            filename=filename,
            mime_type=mime_type,
            file_size=file_size,
            status=status,
            errores=[],
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def get_by_task_id(self, task_id: str) -> Optional[Comprobante]:
        result = await self.session.execute(
            select(Comprobante).where(Comprobante.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def update_ocr(
        self,
        task_id: str,
        *,
        texto: str,
        confianza: float,
        paginas: int,
    ) -> Optional[Comprobante]:
        row = await self.get_by_task_id(task_id)
        if not row:
            return None
        row.texto_ocr = texto
        row.confianza_ocr = _dec(confianza)
        row.paginas = paginas
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def update_datos(
        self,
        task_id: str,
        *,
        datos: dict,
        status: str = "completed",
        errores: Optional[list] = None,
        nit_validado: Optional[bool] = None,
        nit_mensaje: Optional[str] = None,
    ) -> Optional[Comprobante]:
        row = await self.get_by_task_id(task_id)
        if not row:
            return None
        row.datos_extraidos = datos
        row.status = status
        if errores is not None:
            row.errores = errores
        if nit_validado is not None:
            row.nit_validado = nit_validado
        if nit_mensaje is not None:
            row.nit_mensaje = nit_mensaje
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def mark_failed(self, task_id: str, error: str) -> Optional[Comprobante]:
        row = await self.get_by_task_id(task_id)
        if not row:
            return None
        row.status = "failed"
        row.errores = (row.errores or []) + [error]
        await self.session.commit()
        await self.session.refresh(row)
        return row


class FacturaRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        comprobante_id: Optional[str],
        nit_pagador: str,
        dv_pagador: Optional[str] = None,
        nombre_razon_social: Optional[str] = None,
        nro_identificacion: Optional[str] = None,
        id_proyecto: Optional[str] = None,
        id_seccional: Optional[str] = None,
        id_entidad: Optional[str] = None,
        id_forma_pago: Optional[str] = None,
        id_banco: Optional[str] = None,
        numero_consignacion: Optional[str] = None,
        fecha_consignacion: Optional[date] = None,
        valor_total: Optional[Decimal] = None,
        observaciones: Optional[str] = None,
        ticket_id: Optional[str] = None,
        detalles: Optional[list[dict]] = None,
        estado_snri: str = "pendiente",
    ) -> Factura:
        factura = Factura(
            comprobante_id=comprobante_id,
            nit_pagador=nit_pagador,
            dv_pagador=dv_pagador,
            nombre_razon_social=nombre_razon_social,
            nro_identificacion=nro_identificacion,
            id_proyecto=id_proyecto,
            id_seccional=id_seccional,
            id_entidad=id_entidad,
            id_forma_pago=id_forma_pago,
            id_banco=id_banco,
            numero_consignacion=numero_consignacion,
            fecha_consignacion=fecha_consignacion,
            valor_total=_dec(valor_total),
            observaciones=observaciones,
            ticket_id=ticket_id,
            estado_snri=estado_snri,
            errores_snri=[],
            sigma_synced=False,
        )
        for d in detalles or []:
            factura.detalles.append(
                FacturaDetalle(
                    id_servicio=str(d.get("id_servicio", "")),
                    codigo=d.get("codigo"),
                    descripcion=d.get("descripcion") or d.get("nombre"),
                    valor=_dec(d.get("valor")),
                    cantidad=_dec(d.get("cantidad"), Decimal("1")),
                    valor_total=_dec(d.get("valor_total") or d.get("valor")),
                )
            )
        self.session.add(factura)
        await self.session.commit()
        await self.session.refresh(factura)
        return factura

    async def get(self, factura_id: str) -> Optional[Factura]:
        result = await self.session.execute(
            select(Factura)
            .options(selectinload(Factura.detalles))
            .where(Factura.id == factura_id)
        )
        return result.scalar_one_or_none()

    async def get_by_numero(self, numero_factura: str) -> Optional[Factura]:
        result = await self.session.execute(
            select(Factura)
            .options(selectinload(Factura.detalles))
            .where(Factura.numero_factura == numero_factura)
        )
        return result.scalar_one_or_none()

    async def get_emitida_by_consignacion(
        self, numero_consignacion: str
    ) -> Optional[Factura]:
        if not numero_consignacion:
            return None
        result = await self.session.execute(
            select(Factura)
            .options(selectinload(Factura.detalles))
            .where(
                Factura.numero_consignacion == numero_consignacion,
                Factura.estado_snri == "emitida",
            )
            .order_by(Factura.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def update_snri_result(
        self,
        factura_id: str,
        *,
        success: bool,
        numero_factura: Optional[str] = None,
        id_factura_snri: Optional[str] = None,
        cufe: Optional[str] = None,
        errores: Optional[list] = None,
        sigma_synced: bool = False,
        sigma_response: Optional[dict] = None,
    ) -> Optional[Factura]:
        row = await self.get(factura_id)
        if not row:
            return None
        row.estado_snri = "emitida" if success else "error"
        if numero_factura:
            row.numero_factura = numero_factura
        if id_factura_snri:
            row.id_factura_snri = id_factura_snri
        if cufe:
            row.cufe = cufe
        if errores is not None:
            row.errores_snri = errores
        row.sigma_synced = sigma_synced
        if sigma_response is not None:
            row.sigma_response = sigma_response
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def save_pdf(self, factura_id: str, pdf_base64: str) -> Optional[Factura]:
        row = await self.get(factura_id)
        if not row:
            return None
        row.pdf_base64 = pdf_base64
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_recent(self, limit: int = 50) -> list[Factura]:
        result = await self.session.execute(
            select(Factura)
            .options(selectinload(Factura.detalles))
            .order_by(Factura.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class AuditRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def log(
        self,
        *,
        accion: str,
        entidad: Optional[str] = None,
        entidad_id: Optional[str] = None,
        actor: Optional[str] = None,
        detalle: Optional[dict] = None,
        ip: Optional[str] = None,
    ) -> AuditLog:
        row = AuditLog(
            accion=accion,
            entidad=entidad,
            entidad_id=entidad_id,
            actor=actor,
            detalle=detalle or {},
            ip=ip,
        )
        self.session.add(row)
        await self.session.commit()
        return row
