from typing import List

import re
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin, require_viewer
from app.core.rate_limit import limiter
from app.db.repositories import AuditRepo, PerfilRepo
from app.db.session import get_db
from app.models.schemas import PerfilExtraccionIn, PerfilExtraccionOut
from app.services.extraction import CAMPOS_CATALOGO, PERFILES_SEED

router = APIRouter()
logger = structlog.get_logger()


def _validar(body: PerfilExtraccionIn) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{2,63}", body.codigo):
        raise HTTPException(400, "codigo: minúsculas/dígitos/guiones, 3-64 caracteres")
    if not body.campos:
        raise HTTPException(400, "Debe definir al menos un campo")
    for campo, cfg in body.campos.items():
        if campo not in CAMPOS_CATALOGO:
            raise HTTPException(400, f"Campo desconocido: {campo}. Válidos: {CAMPOS_CATALOGO}")
        if cfg.regex:
            try:
                re.compile(cfg.regex)
            except re.error as e:
                raise HTTPException(400, f"Regex inválida en '{campo}': {e}")
        if not cfg.regex and not cfg.literal:
            raise HTTPException(400, f"Campo '{campo}': requiere regex o literal")


@router.get("/perfiles", response_model=List[PerfilExtraccionOut])
async def listar_perfiles(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_viewer),
):
    return await PerfilRepo(db).list_all()


@router.post("/perfiles", response_model=PerfilExtraccionOut, status_code=201)
@limiter.limit("30/minute")
async def crear_perfil(
    request: Request,
    body: PerfilExtraccionIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    _validar(body)
    repo = PerfilRepo(db)
    if await repo.get_by_codigo(body.codigo):
        raise HTTPException(409, f"Ya existe un perfil con codigo '{body.codigo}'")
    row = await repo.create(
        codigo=body.codigo,
        nombre=body.nombre,
        detect_keywords=body.detect_keywords,
        campos={k: v.model_dump() for k, v in body.campos.items()},
        llm_respaldo=body.llm_respaldo,
        activo=body.activo,
        es_default=body.es_default,
        user_sub=user.get("sub"),
    )
    await AuditRepo(db).log(
        accion="perfil_crear",
        entidad="perfil_extraccion",
        entidad_id=row.id,
        actor=user.get("sub"),
        detalle={"codigo": row.codigo},
        ip=request.client.host if request.client else None,
    )
    return row


@router.put("/perfiles/{perfil_id}", response_model=PerfilExtraccionOut)
@limiter.limit("30/minute")
async def actualizar_perfil(
    request: Request,
    perfil_id: str,
    body: PerfilExtraccionIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    _validar(body)
    repo = PerfilRepo(db)
    existente = await repo.get_by_codigo(body.codigo)
    if existente and existente.id != perfil_id:
        raise HTTPException(409, f"Ya existe un perfil con codigo '{body.codigo}'")
    row = await repo.update(
        perfil_id,
        codigo=body.codigo,
        nombre=body.nombre,
        detect_keywords=body.detect_keywords,
        campos={k: v.model_dump() for k, v in body.campos.items()},
        llm_respaldo=body.llm_respaldo,
        activo=body.activo,
        es_default=body.es_default,
    )
    if not row:
        raise HTTPException(404, "Perfil no encontrado")
    await AuditRepo(db).log(
        accion="perfil_actualizar",
        entidad="perfil_extraccion",
        entidad_id=row.id,
        actor=user.get("sub"),
        detalle={"codigo": row.codigo},
        ip=request.client.host if request.client else None,
    )
    return row


@router.delete("/perfiles/{perfil_id}", status_code=204)
@limiter.limit("30/minute")
async def eliminar_perfil(
    request: Request,
    perfil_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    repo = PerfilRepo(db)
    row = await repo.get(perfil_id)
    if not row:
        raise HTTPException(404, "Perfil no encontrado")
    codigo = row.codigo
    await repo.delete(perfil_id)
    await AuditRepo(db).log(
        accion="perfil_eliminar",
        entidad="perfil_extraccion",
        entidad_id=perfil_id,
        actor=user.get("sub"),
        detalle={"codigo": codigo},
        ip=request.client.host if request.client else None,
    )


@router.put("/perfiles/{perfil_id}/default", response_model=PerfilExtraccionOut)
@limiter.limit("30/minute")
async def marcar_default(
    request: Request,
    perfil_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    repo = PerfilRepo(db)
    row = await repo.get(perfil_id)
    if not row:
        raise HTTPException(404, "Perfil no encontrado")
    for otro in await repo.list_all():
        if otro.id != perfil_id and otro.es_default:
            await repo.update(otro.id, es_default=False)
    row = await repo.update(perfil_id, es_default=True, activo=True)
    await AuditRepo(db).log(
        accion="perfil_default",
        entidad="perfil_extraccion",
        entidad_id=perfil_id,
        actor=user.get("sub"),
        detalle={"codigo": row.codigo},
        ip=request.client.host if request.client else None,
    )
    return row


@router.post("/perfiles/seed", response_model=List[PerfilExtraccionOut], status_code=201)
@limiter.limit("5/minute")
async def seed_perfiles(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_admin),
):
    """Crea los 3 perfiles base (si faltan)."""
    repo = PerfilRepo(db)
    creados = []
    for i, seed in enumerate(PERFILES_SEED):
        if await repo.get_by_codigo(seed["codigo"]):
            continue
        row = await repo.create(
            codigo=seed["codigo"],
            nombre=seed["nombre"],
            detect_keywords=seed["detect_keywords"],
            campos=seed["campos"],
            llm_respaldo=seed["llm_respaldo"],
            es_default=(i == 0),
            user_sub=user.get("sub"),
        )
        creados.append(row)
    await AuditRepo(db).log(
        accion="perfil_seed",
        entidad="perfil_extraccion",
        actor=user.get("sub"),
        detalle={"creados": [r.codigo for r in creados]},
        ip=request.client.host if request.client else None,
    )
    return creados


@router.get("/perfiles/catalogo/campos")
async def catalogo_campos(user: dict = Depends(require_viewer)):
    return {"campos": CAMPOS_CATALOGO}
