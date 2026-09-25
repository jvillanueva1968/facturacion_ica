from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    String,
    Text,
    Integer,
    Numeric,
    Boolean,
    DateTime,
    Date,
    ForeignKey,
    JSON,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Comprobante(Base):
    __tablename__ = "comprobantes"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(UUID(as_uuid=False), unique=True, default=_uuid, index=True)
    filename: Mapped[Optional[str]] = mapped_column(String(512))
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="processing", index=True)
    confianza_ocr: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    paginas: Mapped[Optional[int]] = mapped_column(Integer)
    texto_ocr: Mapped[Optional[str]] = mapped_column(Text)
    datos_extraidos: Mapped[Optional[dict]] = mapped_column(JSON)
    perfil_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    nit_validado: Mapped[Optional[bool]] = mapped_column(Boolean)
    nit_mensaje: Mapped[Optional[str]] = mapped_column(Text)
    errores: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    facturas: Mapped[List["Factura"]] = relationship(back_populates="comprobante")


class Factura(Base):
    __tablename__ = "facturas"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    comprobante_id: Mapped[Optional[str]] = mapped_column(
        UUID(as_uuid=False), ForeignKey("comprobantes.id"), index=True
    )
    numero_factura: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    id_factura_snri: Mapped[Optional[str]] = mapped_column(String(64))
    cufe: Mapped[Optional[str]] = mapped_column(String(128))

    id_proyecto: Mapped[Optional[str]] = mapped_column(String(32))
    id_seccional: Mapped[Optional[str]] = mapped_column(String(32))
    id_entidad: Mapped[Optional[str]] = mapped_column(String(32))

    nit_pagador: Mapped[str] = mapped_column(String(32), index=True)
    dv_pagador: Mapped[Optional[str]] = mapped_column(String(4))
    nombre_razon_social: Mapped[Optional[str]] = mapped_column(String(256))
    nro_identificacion: Mapped[Optional[str]] = mapped_column(String(40))

    id_forma_pago: Mapped[Optional[str]] = mapped_column(String(32))
    id_banco: Mapped[Optional[str]] = mapped_column(String(32))
    numero_consignacion: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    fecha_consignacion: Mapped[Optional[date]] = mapped_column(Date)

    valor_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    observaciones: Mapped[Optional[str]] = mapped_column(Text)
    ticket_id: Mapped[Optional[str]] = mapped_column(String(64))

    estado_snri: Mapped[Optional[str]] = mapped_column(String(32), default="pendiente")
    errores_snri: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    sigma_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    sigma_response: Mapped[Optional[dict]] = mapped_column(JSON)

    pdf_base64: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    comprobante: Mapped[Optional[Comprobante]] = relationship(back_populates="facturas")
    detalles: Mapped[List["FacturaDetalle"]] = relationship(
        back_populates="factura", cascade="all, delete-orphan"
    )


class FacturaDetalle(Base):
    __tablename__ = "factura_detalles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    factura_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("facturas.id", ondelete="CASCADE"), index=True
    )
    id_servicio: Mapped[str] = mapped_column(String(64))
    codigo: Mapped[Optional[str]] = mapped_column(String(64))
    descripcion: Mapped[Optional[str]] = mapped_column(String(256))
    valor: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    cantidad: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=1)
    valor_total: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    factura: Mapped[Factura] = relationship(back_populates="detalles")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    actor: Mapped[Optional[str]] = mapped_column(String(128))
    accion: Mapped[str] = mapped_column(String(64), index=True)
    entidad: Mapped[Optional[str]] = mapped_column(String(64))
    entidad_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    detalle: Mapped[Optional[dict]] = mapped_column(JSON)
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogoCache(Base):
    __tablename__ = "catalogos_cache"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    tipo: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PerfilExtraccion(Base):
    __tablename__ = "perfiles_extraccion"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    codigo: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(128))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    es_default: Mapped[bool] = mapped_column(Boolean, default=False)
    detect_keywords: Mapped[list] = mapped_column(JSON, default=list)
    campos: Mapped[dict] = mapped_column(JSON, default=dict)
    llm_respaldo: Mapped[bool] = mapped_column(Boolean, default=True)
    user_sub: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
