from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
from app.core.deps import require_viewer
from app.core.rate_limit import limiter
from app.services.nit_validator import (
    validar_nit_snri,
    calcular_dv_nit,
    normalizar_nit_dv,
)
from app.services.snri_client import SNRIClient
import structlog

router = APIRouter()
snri_client = SNRIClient()
logger = structlog.get_logger()


class NITValidateRequest(BaseModel):
    nit: str
    dv: Optional[str] = None


class NITValidateResponse(BaseModel):
    valido: bool
    nit: str
    dv_calculado: Optional[str] = None
    dv_ingresado: Optional[str] = None
    mensaje: str
    datos_snri: Optional[dict] = None


@router.post("/nit/validar", response_model=NITValidateResponse)
@limiter.limit("60/minute")
async def validar_nit(request: Request, body: NITValidateRequest, user: dict = Depends(require_viewer)):
    nit_limpio, dv_limpio = normalizar_nit_dv(body.nit, body.dv)

    if not nit_limpio:
        raise HTTPException(400, "NIT vacío")

    if body.dv is None and len(''.join(filter(str.isdigit, body.nit))) >= 10:
        dv_calculado = calcular_dv_nit(nit_limpio)
        valido = dv_limpio == dv_calculado
        return NITValidateResponse(
            valido=valido,
            nit=nit_limpio,
            dv_calculado=dv_calculado,
            dv_ingresado=dv_limpio,
            mensaje="DV coincide" if valido else "DV no coincide",
        )

    dv_calculado = calcular_dv_nit(nit_limpio)

    if body.dv or dv_limpio:
        dv_ingresado = dv_limpio or body.dv
        valido = dv_ingresado == dv_calculado
        mensaje = "DV coincide" if valido else "DV no coincide"
        return NITValidateResponse(
            valido=valido,
            nit=nit_limpio,
            dv_calculado=dv_calculado,
            dv_ingresado=dv_ingresado,
            mensaje=mensaje
        )

    return NITValidateResponse(
        valido=True,
        nit=nit_limpio,
        dv_calculado=dv_calculado,
        mensaje="DV calculado correctamente"
    )


@router.post("/nit/validar-snri", response_model=NITValidateResponse)
@limiter.limit("30/minute")
async def validar_nit_con_snri(request: Request, body: NITValidateRequest, user: dict = Depends(require_viewer)):
    nit_limpio, dv_limpio = normalizar_nit_dv(body.nit, body.dv)

    if not nit_limpio:
        raise HTTPException(400, "NIT vacío")

    dv = dv_limpio or body.dv or calcular_dv_nit(nit_limpio)

    resultado = await validar_nit_snri(nit_limpio, dv, snri_client)

    return NITValidateResponse(
        valido=resultado["valido"],
        nit=nit_limpio,
        dv_calculado=dv,
        dv_ingresado=body.dv,
        mensaje=resultado["mensaje"],
        datos_snri=resultado.get("datos")
    )


@router.get("/nit/calcular-dv/{nit}")
async def calcular_dv_endpoint(nit: str):
    nit_limpio = ''.join(filter(str.isdigit, nit))
    if not nit_limpio:
        raise HTTPException(400, "NIT inválido")
    dv = calcular_dv_nit(nit_limpio)
    return {"nit": nit_limpio, "dv": dv, "nit_completo": f"{nit_limpio}-{dv}"}