-- Esquema inicial Sistema de Facturación ICA (PostgreSQL)
-- Se crea automáticamente en el lifespan con SQLAlchemy create_all.
-- Este archivo queda como referencia / para carga manual.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS comprobantes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    filename VARCHAR(512),
    mime_type VARCHAR(128),
    file_size INTEGER,
    status VARCHAR(32) NOT NULL DEFAULT 'processing',
    confianza_ocr NUMERIC(5,2),
    paginas INTEGER,
    texto_ocr TEXT,
    datos_extraidos JSONB,
    nit_validado BOOLEAN,
    nit_mensaje TEXT,
    errores JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_comprobantes_task_id ON comprobantes (task_id);
CREATE INDEX IF NOT EXISTS ix_comprobantes_status ON comprobantes (status);

CREATE TABLE IF NOT EXISTS facturas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comprobante_id UUID REFERENCES comprobantes(id),
    numero_factura VARCHAR(64) UNIQUE,
    id_factura_snri VARCHAR(64),
    cufe VARCHAR(128),
    id_proyecto VARCHAR(32),
    id_seccional VARCHAR(32),
    id_entidad VARCHAR(32),
    nit_pagador VARCHAR(32) NOT NULL,
    dv_pagador VARCHAR(4),
    nombre_razon_social VARCHAR(256),
    nro_identificacion VARCHAR(40),
    id_forma_pago VARCHAR(32),
    id_banco VARCHAR(32),
    numero_consignacion VARCHAR(64),
    fecha_consignacion DATE,
    valor_total NUMERIC(18,2),
    observaciones TEXT,
    ticket_id VARCHAR(64),
    estado_snri VARCHAR(32) DEFAULT 'pendiente',
    errores_snri JSONB DEFAULT '[]'::jsonb,
    sigma_synced BOOLEAN NOT NULL DEFAULT FALSE,
    sigma_response JSONB,
    pdf_base64 TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_facturas_comprobante_id ON facturas (comprobante_id);
CREATE INDEX IF NOT EXISTS ix_facturas_numero_factura ON facturas (numero_factura);
CREATE INDEX IF NOT EXISTS ix_facturas_nit_pagador ON facturas (nit_pagador);
CREATE INDEX IF NOT EXISTS ix_facturas_numero_consignacion ON facturas (numero_consignacion);

-- Una sola factura emitida por referencia de pago (métrica: 0 duplicadas)
CREATE UNIQUE INDEX IF NOT EXISTS ux_facturas_emitidas_consignacion
    ON facturas (numero_consignacion)
    WHERE estado_snri = 'emitida' AND numero_consignacion IS NOT NULL;

CREATE TABLE IF NOT EXISTS factura_detalles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factura_id UUID NOT NULL REFERENCES facturas(id) ON DELETE CASCADE,
    id_servicio VARCHAR(64) NOT NULL,
    codigo VARCHAR(64),
    descripcion VARCHAR(256),
    valor NUMERIC(18,2) NOT NULL,
    cantidad NUMERIC(18,2) NOT NULL DEFAULT 1,
    valor_total NUMERIC(18,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_factura_detalles_factura_id ON factura_detalles (factura_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor VARCHAR(128),
    accion VARCHAR(64) NOT NULL,
    entidad VARCHAR(64),
    entidad_id VARCHAR(64),
    detalle JSONB,
    ip VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_log_accion ON audit_log (accion);
CREATE INDEX IF NOT EXISTS ix_audit_log_entidad_id ON audit_log (entidad_id);

CREATE TABLE IF NOT EXISTS catalogos_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tipo VARCHAR(64) UNIQUE NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_catalogos_cache_tipo ON catalogos_cache (tipo);
