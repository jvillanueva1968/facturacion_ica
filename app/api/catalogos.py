from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from app.config import get_settings
from app.core.deps import require_operator, require_viewer
from app.core.rate_limit import limiter
from app.services.snri_client import SNRIClient
import structlog

router = APIRouter()
settings = get_settings()
snri_client = SNRIClient()
logger = structlog.get_logger()


class AuthRequest(BaseModel):
    id_proyecto: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    ip: Optional[str] = None
    proceso: Optional[str] = None


@router.post("/auth/token")
@limiter.limit("10/minute")
async def obtener_token(
    request: Request,
    body: AuthRequest | None = None,
    user: dict = Depends(require_operator),
):
    from app.models.schemas import InicioTransaccionRequest

    body = body or AuthRequest()
    id_proyecto = body.id_proyecto or settings.snri_id_proyecto
    username = body.username or settings.snri_username
    password = body.password or settings.snri_password
    ip = body.ip or settings.snri_ip
    proceso = body.proceso if body.proceso is not None else settings.snri_proceso

    if not id_proyecto or not username or not password:
        raise HTTPException(
            400,
            "Faltan credenciales SNRI: envíe id_proyecto/username/password "
            "o configure SNRI_ID_PROYECTO/SNRI_USERNAME/SNRI_PASSWORD en .env",
        )

    auth_request = InicioTransaccionRequest(
        id_proyecto=id_proyecto,
        username=username,
        pass_=password,
        ip=ip or None,
        proceso=proceso or None,
    )
    response = await snri_client.obtener_token(auth_request)
    if not response.success:
        raise HTTPException(401, f"Error autenticando: {response.errores}")
    return {"token": response.token, "success": True}


@router.get("/catalogos/formas-pago")
async def get_formas_pago(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    formas = snri_client._get_formas_pago()
    return {"formas_pago": [f.model_dump() for f in formas]}


@router.get("/catalogos/bancos")
async def get_bancos(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    bancos = snri_client._get_bancos()
    return {"bancos": [b.model_dump() for b in bancos]}


@router.get("/catalogos/servicios")
async def get_servicios(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    servicios = snri_client._get_servicios()
    return {"servicios": [s.model_dump() for s in servicios]}


@router.get("/catalogos/seccionales")
async def get_seccionales(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    seccionales = snri_client._get_seccionales()
    return {"seccionales": [s.model_dump() for s in seccionales]}


@router.get("/catalogos/departamentos")
async def get_departamentos(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    departamentos = snri_client._get_departamentos()
    return {"departamentos": [d.model_dump() for d in departamentos]}


@router.get("/catalogos/ciudades/{id_departamento}")
async def get_ciudades(id_departamento: int, user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    ciudades = snri_client._get_ciudades(id_departamento)
    return {"ciudades": [c.model_dump() for c in ciudades]}


@router.get("/catalogos/tipos-documento")
async def get_tipos_documento(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    tipos = snri_client._get_tipos_documento()
    return {"tipos_documento": [t.model_dump() for t in tipos]}


@router.get("/catalogos/tipos-persona")
async def get_tipos_persona(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    tipos = snri_client._get_tipos_persona()
    return {"tipos_persona": [t.model_dump() for t in tipos]}


@router.get("/catalogos/todos")
async def get_todos_catalogos(user: dict = Depends(require_viewer)):
    if not snri_client.token:
        raise HTTPException(400, "Token no disponible. Autentíquese primero.")
    catalogos = snri_client.get_catalogos()
    return {k: [v.model_dump() for v in vals] for k, vals in catalogos.items()}
