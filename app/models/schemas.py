from pydantic import BaseModel, Field, validator, model_validator, ConfigDict
from typing import Optional, List, Literal
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from app.services.nit_validator import normalizar_nit_dv


class FormaPago(str, Enum):
    CONSIGNACION = "CONSIGNACION"
    TRANSFERENCIA = "TRANSFERENCIA"
    CHEQUE_GERENCIA = "CHEQUE_GERENCIA"
    PSE = "PSE"
    DATAFONO = "DATAFONO"


class TipoDocumento(int, Enum):
    NIT = 1
    CC = 2
    CE = 3
    PP = 4
    TI = 5


class TipoPersona(int, Enum):
    NATURAL = 1
    JURIDICA = 2


class SNRIFormaPago(BaseModel):
    id_forma_pago: str
    descripcion: str


class SNRIBanco(BaseModel):
    id_banco: str
    nombre: str


class SNRIServicio(BaseModel):
    id_servicio: str
    codigo: str
    descripcion: str
    valor: Optional[str] = None


class SNRISeccional(BaseModel):
    id_seccional: str
    nombre: str


class SNRIDepartamento(BaseModel):
    id_departamento: int
    nombre: str


class SNRICiudad(BaseModel):
    id_ciudad: int
    nombre: str
    id_departamento: int


class SNRITipoDocumento(BaseModel):
    id_tipo_documento: int
    descripcion: str


class SNRITipoPersona(BaseModel):
    id_tipo_persona: int
    descripcion: str


class FacturaDetalle(BaseModel):
    id_servicio: str
    valor: str
    cantidad: str
    valor_total: str


class SNRIFacturaBase(BaseModel):
    token: str
    id_proyecto: str
    id_seccional: str
    id_entidad: str
    id_tercero: str
    id_tipo_documento: int
    id_tipo_persona: int
    gran_contribuyente: int
    autorretenedor: int
    regimen_comun: int
    regimen_simplificado: int
    nro_identificacion: str
    nombre_razon_social: str
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


class SNRIFacturaSimpleRequest(SNRIFacturaBase):
    id_servicio: str
    valor: str
    cantidad: str
    valor_total: str


class SNRIFacturaDetalleRequest(SNRIFacturaBase):
    detalles: List[FacturaDetalle]
    id_servicio: Optional[str] = None
    valor: Optional[str] = None
    cantidad: Optional[str] = None
    valor_total: Optional[str] = None


class SNRIFacturaResponse(BaseModel):
    numero_factura: Optional[str] = None
    id_factura: Optional[str] = None
    cufe: Optional[str] = None
    success: bool
    errores: List[dict] = []


class TerceroResponse(BaseModel):
    id_tercero: Optional[int] = None
    nro_identificacion: Optional[str] = None
    nombre_razon_social: Optional[str] = None
    id_tipo_documento: Optional[int] = None
    id_tipo_persona: Optional[int] = None
    gran_contribuyente: Optional[int] = None
    autorretenedor: Optional[int] = None
    regimen_comun: Optional[int] = None
    regimen_simplificado: Optional[int] = None
    id_departamento: Optional[int] = None
    id_ciudad: Optional[int] = None
    direccion_principal: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    success: bool
    errores: List[dict] = []


class TerceroCreateRequest(BaseModel):
    token: str
    id_tipo_documento: int
    id_tipo_persona: int
    gran_contribuyente: int
    autorretenedor: int
    regimen_comun: int
    regimen_simplificado: int
    nro_identificacion: str
    nombre_razon_social: str
    id_departamento: int
    id_ciudad: int
    direccion_principal: str
    telefono: Optional[str] = None
    email: Optional[str] = None
    representante_legal: Optional[str] = None
    primernombre: Optional[str] = None
    segundonombre: Optional[str] = None
    primerapellido: Optional[str] = None
    segundoapellido: Optional[str] = None


class InicioTransaccionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id_proyecto: int
    username: Optional[str] = None
    pass_: Optional[str] = Field(default=None, alias="pass")
    ip: Optional[str] = None
    proceso: Optional[str] = None


class TokenResponse(BaseModel):
    token: str
    success: bool
    errores: List[dict] = []


class OCRResultado(BaseModel):
    texto: str
    confianza_promedio: float
    paginas: int


class DatosExtraidos(BaseModel):
    forma_pago: FormaPago
    servicios: List[dict]
    nit_pagador: str
    dv_pagador: Optional[str] = None
    fecha_transaccion: date
    valor_total: Decimal
    numero_referencia: str
    banco: Optional[str] = None
    tipo_documento: Optional[str] = None
    numero_documento: Optional[str] = None

    @model_validator(mode="after")
    def _normalizar_nit(self):
        nit, dv = normalizar_nit_dv(self.nit_pagador, self.dv_pagador)
        if nit:
            self.nit_pagador = nit
        if dv:
            self.dv_pagador = dv
        return self


class UploadResponse(BaseModel):
    task_id: str
    status: Literal["processing", "completed", "failed"]
    mensaje: Optional[str] = None
    datos: Optional[DatosExtraidos] = None
    errores: List[str] = []
    progress: Optional[int] = None
    stage: Optional[str] = None
    confianza_ocr: Optional[float] = None
    paginas: Optional[int] = None
    nit_validado: Optional[bool] = None
    nit_mensaje: Optional[str] = None
    texto_ocr: Optional[str] = None


class FacturaImpresaResponse(BaseModel):
    success: bool
    pdf_base64: Optional[str] = None
    errores: List[dict] = []


class HealthResponse(BaseModel):
    status: str
    version: str
    snri_wsdl_loaded: bool
    database_connected: bool
    redis_connected: bool


class FacturaOut(BaseModel):
    id: str
    numero_factura: Optional[str] = None
    cufe: Optional[str] = None
    nit_pagador: str
    dv_pagador: Optional[str] = None
    nombre_razon_social: Optional[str] = None
    valor_total: Optional[Decimal] = None
    estado_snri: Optional[str] = None
    sigma_synced: bool = False
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ComprobanteOut(BaseModel):
    id: str
    task_id: str
    filename: Optional[str] = None
    status: str
    confianza_ocr: Optional[Decimal] = None
    paginas: Optional[int] = None
    texto_ocr: Optional[str] = None
    datos_extraidos: Optional[dict] = None
    nit_validado: Optional[bool] = None
    nit_mensaje: Optional[str] = None
    errores: Optional[list] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)