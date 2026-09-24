from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import BaseModel
from typing import List, Optional
from decimal import Decimal
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import (
    SNRIFacturaSimpleRequest,
    SNRIFacturaDetalleRequest,
    SNRIFacturaResponse,
    FacturaDetalle,
    FacturaImpresaResponse,
    FormaPago,
    FacturaOut,
)
from app.core.deps import require_operator, require_viewer
from app.core.rate_limit import limiter
from app.services.snri_client import SNRIClient
from app.services.sigma_client import SigmaClient
from app.services.nit_validator import validar_nit_snri
from app.services.pdf_service import demo_pdf_base64
from app.config import get_settings
from app.db.session import get_db
from app.db.repositories import FacturaRepo, AuditRepo
import structlog
from fastapi import Request

router = APIRouter()
snri_client = SNRIClient()
sigma_client = SigmaClient()
logger = structlog.get_logger()
settings = get_settings()


class FacturaSimpleInput(BaseModel):
    id_proyecto: str
    id_seccional: str
    id_entidad: str
    nit_pagador: str
    dv_pagador: str
    nombre_razon_social: str
    id_tipo_documento: int = 1
    id_tipo_persona: int = 2
    gran_contribuyente: int = 0
    autorretenedor: int = 0
    regimen_comun: int = 1
    regimen_simplificado: int = 0
    id_departamento: int
    id_ciudad: int
    direccion_principal: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    id_forma_pago: str
    id_banco: str
    numero_consignacion: str
    fecha_consignacion: str
    id_servicio: str
    valor: str
    cantidad: str
    valor_total: str
    observaciones: Optional[str] = None
    ticket_id: Optional[str] = None


class FacturaDetalleInput(BaseModel):
    id_proyecto: str
    id_seccional: str
    id_entidad: str
    nit_pagador: str
    dv_pagador: str
    nombre_razon_social: str
    id_tipo_documento: int = 1
    id_tipo_persona: int = 2
    gran_contribuyente: int = 0
    autorretenedor: int = 0
    regimen_comun: int = 1
    regimen_simplificado: int = 0
    id_departamento: int
    id_ciudad: int
    direccion_principal: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    id_forma_pago: str
    id_banco: str
    numero_consignacion: str
    fecha_consignacion: str
    observaciones: Optional[str] = None
    ticket_id: Optional[str] = None
    detalles: List[FacturaDetalle]


@router.get("/facturas", response_model=List[FacturaOut])
async def listar_facturas(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_viewer),
):
    repo = FacturaRepo(db)
    return await repo.list_recent(limit=limit)


@router.get("/facturas/{factura_id}", response_model=FacturaOut)
async def obtener_factura(
    factura_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_viewer),
):
    repo = FacturaRepo(db)
    row = await repo.get(factura_id)
    if not row:
        raise HTTPException(404, "Factura no encontrada")
    return row


def _respuesta_emitida(factura) -> SNRIFacturaResponse:
    return SNRIFacturaResponse(
        success=True,
        numero_factura=factura.numero_factura,
        id_factura=factura.id_factura_snri,
        cufe=factura.cufe,
        errores=[
            {
                "codigo": "DUPLICADO",
                "mensaje": (
                    "Factura ya emitida para esta numero_consignacion; "
                    "se devuelve la existente (idempotente)."
                ),
            }
        ],
    )


@router.post("/facturar/simple", response_model=SNRIFacturaResponse)
@limiter.limit("20/minute")
async def crear_factura_simple(
    input_data: FacturaSimpleInput,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
    user: dict = Depends(require_operator),
):
    if not snri_client.token and not settings.snri_demo_mode:
        raise HTTPException(400, "Token SNRI no disponible. Autentíquese primero.")

    nit_result = await validar_nit_snri(input_data.nit_pagador, input_data.dv_pagador, snri_client)
    if not nit_result["valido"]:
        raise HTTPException(400, f"NIT inválido: {nit_result['mensaje']}")

    factura_repo = FacturaRepo(db)
    audit_repo = AuditRepo(db)

    existente = await factura_repo.get_emitida_by_consignacion(
        input_data.numero_consignacion
    )
    if existente:
        logger.info(
            "factura_duplicada_consignacion",
            numero_consignacion=input_data.numero_consignacion,
            numero_factura=existente.numero_factura,
        )
        return _respuesta_emitida(existente)

    local_factura = await factura_repo.create(
        comprobante_id=None,
        nit_pagador=input_data.nit_pagador,
        dv_pagador=input_data.dv_pagador,
        nombre_razon_social=input_data.nombre_razon_social,
        nro_identificacion=f"{input_data.nit_pagador}-{input_data.dv_pagador}",
        id_proyecto=input_data.id_proyecto,
        id_seccional=input_data.id_seccional,
        id_entidad=input_data.id_entidad,
        id_forma_pago=input_data.id_forma_pago,
        id_banco=input_data.id_banco,
        numero_consignacion=input_data.numero_consignacion,
        fecha_consignacion=date.fromisoformat(input_data.fecha_consignacion)
        if input_data.fecha_consignacion
        else None,
        valor_total=Decimal(input_data.valor_total),
        observaciones=input_data.observaciones,
        ticket_id=input_data.ticket_id,
        detalles=[
            {
                "id_servicio": input_data.id_servicio,
                "valor": input_data.valor,
                "cantidad": input_data.cantidad,
                "valor_total": input_data.valor_total,
            }
        ],
        estado_snri="enviada",
    )

    if settings.snri_demo_mode and not snri_client.token:
        response = SNRIFacturaResponse(
            success=True,
            numero_factura=f"DEMO-{local_factura.id[:8].upper()}",
            id_factura=f"DEMO-{local_factura.id[:8].upper()}",
            cufe=f"DEMO-CUFE-{local_factura.id[:8].upper()}",
            errores=[],
        )
    else:
        request = SNRIFacturaSimpleRequest(
            token=snri_client.token,
            id_proyecto=input_data.id_proyecto,
            id_seccional=input_data.id_seccional,
            id_entidad=input_data.id_entidad,
            id_tercero=input_data.nit_pagador,
            id_tipo_documento=input_data.id_tipo_documento,
            id_tipo_persona=input_data.id_tipo_persona,
            gran_contribuyente=input_data.gran_contribuyente,
            autorretenedor=input_data.autorretenedor,
            regimen_comun=input_data.regimen_comun,
            regimen_simplificado=input_data.regimen_simplificado,
            nro_identificacion=f"{input_data.nit_pagador}-{input_data.dv_pagador}",
            nombre_razon_social=input_data.nombre_razon_social,
            id_departamento=input_data.id_departamento,
            id_ciudad=input_data.id_ciudad,
            direccion_principal=input_data.direccion_principal,
            telefono=input_data.telefono,
            email=input_data.email,
            id_forma_pago=input_data.id_forma_pago,
            id_banco=input_data.id_banco,
            numero_consignacion=input_data.numero_consignacion,
            fecha_consignacion=input_data.fecha_consignacion,
            id_servicio=input_data.id_servicio,
            valor=input_data.valor,
            cantidad=input_data.cantidad,
            valor_total=input_data.valor_total,
            observaciones=input_data.observaciones,
            ticket_id=input_data.ticket_id,
        )
        response = await snri_client.crear_factura_simple(request)

    sigma_synced = False
    sigma_response = None
    if response.success:
        try:
            sigma_response = await sigma_client.registrar_factura({
                "numero_factura_snri": response.numero_factura,
                "cufe": response.cufe,
                "nit_facturar": input_data.nit_pagador,
                "dv_facturar": input_data.dv_pagador,
                "forma_pago": input_data.id_forma_pago,
                "servicios": [{
                    "id_servicio": input_data.id_servicio,
                    "valor": input_data.valor,
                    "cantidad": input_data.cantidad,
                    "valor_total": input_data.valor_total,
                }],
                "fecha_factura": input_data.fecha_consignacion,
                "valor_total": float(input_data.valor_total),
                "numero_referencia": input_data.numero_consignacion,
                "banco": input_data.id_banco,
            })
            sigma_synced = True
        except Exception as e:
            logger.error("error_registrando_sigma", error=str(e))
            response.errores.append({
                "codigo": "SIGMA_WARNING",
                "mensaje": f"No se registró en SIGMA: {str(e)}",
            })

    await factura_repo.update_snri_result(
        local_factura.id,
        success=response.success,
        numero_factura=response.numero_factura,
        id_factura_snri=response.id_factura,
        cufe=response.cufe,
        errores=response.errores,
        sigma_synced=sigma_synced,
        sigma_response=sigma_response if isinstance(sigma_response, dict) else None,
    )

    await audit_repo.log(
        accion="crear_factura_simple",
        entidad="factura",
        entidad_id=local_factura.id,
        detalle={
            "numero_factura": response.numero_factura,
            "success": response.success,
            "nit": input_data.nit_pagador,
        },
    )

    return response


@router.post("/facturar/detalle", response_model=SNRIFacturaResponse)
@limiter.limit("20/minute")
async def crear_factura_detalle(
    input_data: FacturaDetalleInput,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
    user: dict = Depends(require_operator),
):
    if not snri_client.token and not settings.snri_demo_mode:
        raise HTTPException(400, "Token SNRI no disponible. Autentíquese primero.")

    nit_result = await validar_nit_snri(input_data.nit_pagador, input_data.dv_pagador, snri_client)
    if not nit_result["valido"]:
        raise HTTPException(400, f"NIT inválido: {nit_result['mensaje']}")

    factura_repo = FacturaRepo(db)
    audit_repo = AuditRepo(db)

    existente = await factura_repo.get_emitida_by_consignacion(
        input_data.numero_consignacion
    )
    if existente:
        logger.info(
            "factura_duplicada_consignacion",
            numero_consignacion=input_data.numero_consignacion,
            numero_factura=existente.numero_factura,
        )
        return _respuesta_emitida(existente)

    local_factura = await factura_repo.create(
        comprobante_id=None,
        nit_pagador=input_data.nit_pagador,
        dv_pagador=input_data.dv_pagador,
        nombre_razon_social=input_data.nombre_razon_social,
        nro_identificacion=f"{input_data.nit_pagador}-{input_data.dv_pagador}",
        id_proyecto=input_data.id_proyecto,
        id_seccional=input_data.id_seccional,
        id_entidad=input_data.id_entidad,
        id_forma_pago=input_data.id_forma_pago,
        id_banco=input_data.id_banco,
        numero_consignacion=input_data.numero_consignacion,
        fecha_consignacion=date.fromisoformat(input_data.fecha_consignacion)
        if input_data.fecha_consignacion
        else None,
        valor_total=sum(Decimal(d.valor_total) for d in input_data.detalles),
        observaciones=input_data.observaciones,
        ticket_id=input_data.ticket_id,
        detalles=[d.model_dump() for d in input_data.detalles],
        estado_snri="enviada",
    )

    if settings.snri_demo_mode and not snri_client.token:
        response = SNRIFacturaResponse(
            success=True,
            numero_factura=f"DEMO-D-{local_factura.id[:8].upper()}",
            id_factura=f"DEMO-D-{local_factura.id[:8].upper()}",
            cufe=f"DEMO-CUFE-D-{local_factura.id[:8].upper()}",
            errores=[],
        )
    else:
        request = SNRIFacturaDetalleRequest(
            token=snri_client.token,
            id_proyecto=input_data.id_proyecto,
            id_seccional=input_data.id_seccional,
            id_entidad=input_data.id_entidad,
            id_tercero=input_data.nit_pagador,
            id_tipo_documento=input_data.id_tipo_documento,
            id_tipo_persona=input_data.id_tipo_persona,
            gran_contribuyente=input_data.gran_contribuyente,
            autorretenedor=input_data.autorretenedor,
            regimen_comun=input_data.regimen_comun,
            regimen_simplificado=input_data.regimen_simplificado,
            nro_identificacion=f"{input_data.nit_pagador}-{input_data.dv_pagador}",
            nombre_razon_social=input_data.nombre_razon_social,
            id_departamento=input_data.id_departamento,
            id_ciudad=input_data.id_ciudad,
            direccion_principal=input_data.direccion_principal,
            telefono=input_data.telefono,
            email=input_data.email,
            id_forma_pago=input_data.id_forma_pago,
            id_banco=input_data.id_banco,
            numero_consignacion=input_data.numero_consignacion,
            fecha_consignacion=input_data.fecha_consignacion,
            observaciones=input_data.observaciones,
            ticket_id=input_data.ticket_id,
            detalles=input_data.detalles,
        )
        response = await snri_client.crear_factura_detalle(request)

    sigma_synced = False
    sigma_response = None
    if response.success:
        try:
            sigma_response = await sigma_client.registrar_factura({
                "numero_factura_snri": response.numero_factura,
                "cufe": response.cufe,
                "nit_facturar": input_data.nit_pagador,
                "dv_facturar": input_data.dv_pagador,
                "forma_pago": input_data.id_forma_pago,
                "servicios": [d.model_dump() for d in input_data.detalles],
                "fecha_factura": input_data.fecha_consignacion,
                "valor_total": sum(float(d.valor_total) for d in input_data.detalles),
                "numero_referencia": input_data.numero_consignacion,
                "banco": input_data.id_banco,
            })
            sigma_synced = True
        except Exception as e:
            logger.error("error_registrando_sigma", error=str(e))
            response.errores.append({
                "codigo": "SIGMA_WARNING",
                "mensaje": f"No se registró en SIGMA: {str(e)}",
            })

    await factura_repo.update_snri_result(
        local_factura.id,
        success=response.success,
        numero_factura=response.numero_factura,
        id_factura_snri=response.id_factura,
        cufe=response.cufe,
        errores=response.errores,
        sigma_synced=sigma_synced,
        sigma_response=sigma_response if isinstance(sigma_response, dict) else None,
    )

    await audit_repo.log(
        accion="crear_factura_detalle",
        entidad="factura",
        entidad_id=local_factura.id,
        detalle={
            "numero_factura": response.numero_factura,
            "success": response.success,
            "nit": input_data.nit_pagador,
            "lineas": len(input_data.detalles),
        },
    )

    return response


@router.post("/facturar/imprimir/{numero_factura}", response_model=FacturaImpresaResponse)
@limiter.limit("20/minute")
async def imprimir_factura(
    numero_factura: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
):
    repo = FacturaRepo(db)
    row = await repo.get_by_numero(numero_factura)
    if not row:
        raise HTTPException(404, "Factura no encontrada")

    if settings.snri_demo_mode and not snri_client.token:
        pdf_b64 = demo_pdf_base64(
            numero_factura=numero_factura,
            cufe=row.cufe or "",
            nit=f"{row.nit_pagador}-{row.dv_pagador or ''}",
            razon_social=row.nombre_razon_social or "",
            valor_total=str(row.valor_total or ""),
        )
        await repo.save_pdf(row.id, pdf_b64)
        return FacturaImpresaResponse(success=True, pdf_base64=pdf_b64)

    if not snri_client.token:
        raise HTTPException(400, "Token SNRI no disponible")

    response = await snri_client.imprimir_factura(numero_factura)
    if not response.success:
        raise HTTPException(400, f"Error imprimiendo: {response.errores}")

    if response.pdf_base64:
        await repo.save_pdf(row.id, response.pdf_base64)
    return response


@router.get("/facturar/{numero_factura}/pdf")
async def descargar_pdf_factura(
    numero_factura: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_viewer),
):
    import base64 as b64mod

    repo = FacturaRepo(db)
    row = await repo.get_by_numero(numero_factura)
    if not row:
        raise HTTPException(404, "Factura no encontrada")

    pdf_b64 = row.pdf_base64
    if not pdf_b64:
        if settings.snri_demo_mode and not snri_client.token:
            pdf_b64 = demo_pdf_base64(
                numero_factura=numero_factura,
                cufe=row.cufe or "",
                nit=f"{row.nit_pagador}-{row.dv_pagador or ''}",
                razon_social=row.nombre_razon_social or "",
                valor_total=str(row.valor_total or ""),
            )
            await repo.save_pdf(row.id, pdf_b64)
        elif snri_client.token:
            impresa = await snri_client.imprimir_factura(numero_factura)
            if not impresa.success or not impresa.pdf_base64:
                raise HTTPException(400, f"Sin PDF: {impresa.errores}")
            pdf_b64 = impresa.pdf_base64
            await repo.save_pdf(row.id, pdf_b64)
        else:
            raise HTTPException(400, "PDF no disponible (sin token SNRI ni modo demo)")

    try:
        raw = b64mod.b64decode(pdf_b64)
    except Exception as e:
        raise HTTPException(500, f"PDF corrupto en BD: {e}")

    safe = (numero_factura or "factura").replace("/", "_")
    return Response(
        content=raw,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'},
    )
