from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    BackgroundTasks,
    Depends,
)
import asyncio
import re
from uuid import UUID, uuid4
from pathlib import Path
from typing import Optional
import aiofiles
import structlog
from sqlalchemy.exc import DBAPIError, DataError, StatementError
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from datetime import date
from decimal import Decimal, InvalidOperation

from app.models.schemas import (
    UploadResponse,
    DatosExtraidos,
    ComprobanteOut,
    ReextraerIn,
    FormaPago,
)
from app.core.deps import require_operator, require_viewer
from app.core.progress import emit_stage, progress_hub
from app.core.rate_limit import limiter
from app.services.ocr_service import OCRService
from app.services.llm_service import LLMService
from app.services.nit_validator import validar_nit_snri, normalizar_nit_dv
from app.services.snri_client import SNRIClient
from app.services.extraction import (
    PerfilExtraccionData,
    campos_faltantes,
    detectar_perfil,
    extraer_campos,
)
from app.config import get_settings
from app.db.session import get_db, SessionLocal
from app.db.repositories import ComprobanteRepo, PerfilRepo

router = APIRouter()
settings = get_settings()
logger = structlog.get_logger()

ocr_service = OCRService(
    tesseract_cmd=settings.tesseract_cmd,
    lang=settings.tesseract_lang,
    dpi=settings.ocr_dpi,
    min_conf=settings.ocr_min_conf,
)
llm_service = LLMService()
snri_client = SNRIClient()


async def _cargar_perfiles(session) -> list[PerfilExtraccionData]:
    rows = await PerfilRepo(session).list_all(solo_activos=True)
    return [PerfilExtraccionData.from_row(r) for r in rows]


def _resolver_perfil(
    perfiles: list[PerfilExtraccionData],
    perfil_id: Optional[str],
    texto: str,
) -> Optional[PerfilExtraccionData]:
    if perfil_id:
        for p in perfiles:
            if p.id == perfil_id or p.codigo == perfil_id:
                return p
    return detectar_perfil(texto, perfiles)


def _datos_desde_campos(
    campos: dict,
    perfil: PerfilExtraccionData,
    nit_pref: Optional[str],
    dv_pref: Optional[str],
) -> DatosExtraidos:
    """Perfil sin respaldo LLM: arma DatosExtraidos solo con los campos del perfil."""
    valor = campos.get("valor_total") or "0"
    try:
        valor_total = Decimal(valor)
    except InvalidOperation:
        valor_total = Decimal("0")
    fecha_iso = campos.get("fecha") or ""
    try:
        fecha = date.fromisoformat(fecha_iso) if fecha_iso else date.today()
    except ValueError:
        fecha = date.today()
    forma = (campos.get("forma_pago") or "CONSIGNACION").upper()
    if forma not in {"CONSIGNACION", "TRANSFERENCIA", "CHEQUE_GERENCIA", "PSE", "DATAFONO"}:
        forma = "CONSIGNACION"
    return DatosExtraidos(
        forma_pago=forma,
        servicios=[{"descripcion": campos.get("forma_pago") or "SERVICIO", "valor": valor}],
        nit_pagador=nit_pref or campos.get("nit_pagador") or "",
        dv_pagador=dv_pref,
        fecha_transaccion=fecha,
        valor_total=valor_total,
        numero_referencia=campos.get("numero_referencia") or "",
        banco=campos.get("banco"),
        convenio=campos.get("convenio"),
        ubicacion=campos.get("ubicacion"),
        autenticacion=campos.get("autenticacion"),
        perfil_codigo=perfil.codigo,
        campos_perfil=campos,
    )


def _fusionar_datos(
    base: DatosExtraidos,
    campos: dict,
    perfil: PerfilExtraccionData,
) -> DatosExtraidos:
    """Campos extraídos por regex del perfil tienen prioridad sobre el LLM."""
    dump = base.model_dump()
    for campo, valor in campos.items():
        if campo in ("nit_pagador", "dv_pagador"):
            continue
        if campo == "fecha_transaccion":
            continue
        if campo == "fecha":
            try:
                dump["fecha_transaccion"] = date.fromisoformat(valor)
            except ValueError:
                pass
            continue
        if campo == "forma_pago":
            v_fp = str(valor).strip().upper()
            if v_fp in {m.value for m in FormaPago}:
                dump["forma_pago"] = v_fp
            else:
                logger.warning("forma_pago_ignorada", valor=valor, motivo="fuera_de_catalogo")
            continue
        if campo == "valor_total":
            try:
                dump["valor_total"] = Decimal(valor)
            except InvalidOperation:
                pass
        elif campo in dump:
            dump[campo] = valor
    dump["perfil_codigo"] = perfil.codigo
    dump["campos_perfil"] = campos
    faltantes = campos_faltantes(perfil, campos)
    if faltantes:
        dump.setdefault("campos_perfil", {})
        dump["campos_perfil"]["_faltantes"] = faltantes
    return DatosExtraidos(**dump)


@router.post("/upload", response_model=UploadResponse)
@limiter.limit("10/minute")
async def upload_comprobante(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    nit_pagador: Optional[str] = Form(default=None),
    dv_pagador: Optional[str] = Form(default=None),
    perfil_id: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
    user: dict = Depends(require_operator),
):
    if file.content_type not in settings.allowed_mimes:
        raise HTTPException(400, f"Tipo de archivo no permitido: {file.content_type}")

    content = await file.read()
    if len(content) > settings.max_file_size:
        raise HTTPException(413, f"Archivo muy grande. Máximo {settings.max_file_size/1024/1024}MB")

    nit_pref = (nit_pagador or "").strip() or None
    dv_pref = (dv_pagador or "").strip() or None
    if nit_pref:
        nit_pref, dv_embed = normalizar_nit_dv(nit_pref, dv_pref)
        dv_pref = dv_pref or dv_embed

    task_id = str(uuid4())
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]+", "_", Path(file.filename or "upload.bin").name)[:120]
    file_path = upload_dir / f"{task_id}_{safe_name}"

    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)

    repo = ComprobanteRepo(db)
    await repo.create(
        task_id=task_id,
        filename=file.filename,
        mime_type=file.content_type,
        file_size=len(content),
        status="processing",
    )

    background_tasks.add_task(
        procesar_documento, task_id, file_path, nit_pref, dv_pref, perfil_id
    )

    logger.info(
        "archivo_recibido",
        task_id=task_id,
        filename=file.filename,
        size=len(content),
        nit_pref=nit_pref,
    )
    await emit_stage(task_id, "received", mensaje="Archivo recibido, procesando...")

    return UploadResponse(
        task_id=task_id,
        status="processing",
        mensaje="Archivo recibido, procesando..."
    )


def aplicar_identificacion_pref(
    datos: DatosExtraidos,
    nit_pref: Optional[str],
    dv_pref: Optional[str],
) -> DatosExtraidos:
    """El comprobante no trae NIT: el NIT digitado antes del upload manda."""
    if not nit_pref:
        return datos
    datos.nit_pagador = nit_pref
    if dv_pref:
        datos.dv_pagador = dv_pref
    return DatosExtraidos(**datos.model_dump())


async def procesar_documento(
    task_id: str,
    file_path: Path,
    nit_pref: Optional[str] = None,
    dv_pref: Optional[str] = None,
    perfil_id: Optional[str] = None,
):
    try:
        logger.info("iniciando_procesamiento", task_id=task_id, nit_pref=nit_pref)
        await emit_stage(task_id, "ocr_start", mensaje="Ejecutando OCR…")

        async with SessionLocal() as session:
            repo = ComprobanteRepo(session)

            texto_ocr, confianza, paginas = await asyncio.to_thread(
                ocr_service.extract_text, file_path
            )
            await repo.update_ocr(task_id, texto=texto_ocr, confianza=confianza, paginas=paginas)
            logger.info("ocr_completado", task_id=task_id, confianza=confianza, paginas=paginas)
            await emit_stage(
                task_id,
                "ocr_done",
                mensaje="OCR completado",
                confianza=confianza,
                texto_ocr=texto_ocr[:8000],
                paginas=paginas,
            )

            perfiles = await _cargar_perfiles(session)
            perfil = _resolver_perfil(perfiles, perfil_id, texto_ocr)
            campos: dict = {}
            if perfil:
                campos = extraer_campos(texto_ocr, perfil)
                logger.info(
                    "perfil_extraccion",
                    task_id=task_id,
                    codigo=perfil.codigo,
                    campos=campos,
                    faltantes=campos_faltantes(perfil, campos),
                )
                await emit_stage(
                    task_id,
                    "perfil",
                    mensaje=f"Perfil: {perfil.nombre}",
                    perfil_codigo=perfil.codigo,
                )

            usou_llm = perfil is None or perfil.llm_respaldo
            datos: Optional[DatosExtraidos] = None
            if usou_llm:
                await emit_stage(task_id, "llm_start", mensaje="Extrayendo datos con LLM…")
                datos = await llm_service.extraer_datos(texto_ocr)
            else:
                await emit_stage(
                    task_id, "llm_start", mensaje="Extrayendo datos por perfil (sin LLM)…"
                )

            if perfil and campos:
                if datos is None:
                    datos = _datos_desde_campos(campos, perfil, nit_pref, dv_pref)
                else:
                    datos = _fusionar_datos(datos, campos, perfil)
            elif perfil:
                if datos is None:
                    datos = _datos_desde_campos({}, perfil, nit_pref, dv_pref)
                else:
                    dump = datos.model_dump()
                    dump["perfil_codigo"] = perfil.codigo
                    dump["campos_perfil"] = {}
                    datos = DatosExtraidos(**dump)
            if datos is None:
                datos = await llm_service.extraer_datos(texto_ocr)

            datos = aplicar_identificacion_pref(datos, nit_pref, dv_pref)
            await repo.update_datos(
                task_id,
                datos=datos.model_dump(mode="json"),
                status="processing",
                perfil_id=perfil.id if perfil else None,
            )
            logger.info("llm_extraccion_completada", task_id=task_id, nit=datos.nit_pagador)
            await emit_stage(
                task_id,
                "llm_done",
                mensaje="Datos extraídos",
                datos=datos.model_dump(mode="json"),
            )

            await emit_stage(task_id, "nit_start", mensaje="Validando NIT…")
            nit_result = await validar_nit_snri(
                datos.nit_pagador, datos.dv_pagador or "", snri_client
            )
            await repo.update_datos(
                task_id,
                datos=datos.model_dump(mode="json"),
                status="completed",
                nit_validado=nit_result.get("valido"),
                nit_mensaje=nit_result.get("mensaje"),
                errores=[],
            )
            logger.info("nit_validado", task_id=task_id, resultado=nit_result)
            await emit_stage(
                task_id,
                "completed",
                mensaje="Completado",
                datos=datos.model_dump(mode="json"),
                errores=[],
                nit_validado=nit_result.get("valido"),
                nit_mensaje=nit_result.get("mensaje"),
                texto_ocr=texto_ocr[:8000],
                confianza=confianza,
                paginas=paginas,
            )

    except Exception as e:
        logger.error("error_procesamiento", task_id=task_id, error=str(e))
        await emit_stage(task_id, "failed", mensaje=str(e), errores=[str(e)])
        try:
            async with SessionLocal() as session:
                await ComprobanteRepo(session).mark_failed(task_id, str(e))
        except Exception as db_err:
            logger.error("error_marking_failed", task_id=task_id, error=str(db_err))
    finally:
        file_path.unlink(missing_ok=True)


def _status_from_row(row, stage_event: Optional[dict] = None) -> UploadResponse:
    datos = None
    if row.datos_extraidos:
        try:
            datos = DatosExtraidos(**row.datos_extraidos)
        except Exception:
            datos = None

    stage_event = stage_event or progress_hub.get_latest(row.task_id) or {}
    progress = stage_event.get("progress")
    if progress is None:
        progress = {"completed": 100, "failed": 100}.get(row.status)
    confianza = stage_event.get("confianza")
    if confianza is None and row.confianza_ocr is not None:
        confianza = float(row.confianza_ocr)
    texto = stage_event.get("texto_ocr") or row.texto_ocr
    if texto:
        texto = str(texto)[:8000]

    return UploadResponse(
        task_id=row.task_id,
        status=row.status,
        mensaje=stage_event.get("mensaje"),
        datos=datos,
        errores=[str(e) for e in (row.errores or stage_event.get("errores") or [])],
        progress=progress,
        stage=stage_event.get("stage"),
        confianza_ocr=confianza,
        paginas=row.paginas,
        nit_validado=row.nit_validado if row.nit_validado is not None else stage_event.get("nit_validado"),
        nit_mensaje=row.nit_mensaje or stage_event.get("nit_mensaje"),
        texto_ocr=texto,
    )


@router.get("/status/{task_id}", response_model=UploadResponse)
async def get_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    try:
        UUID(task_id)
    except ValueError:
        raise HTTPException(404, "Task no encontrada")

    repo = ComprobanteRepo(db)
    try:
        row = await repo.get_by_task_id(task_id)
    except (DataError, DBAPIError, StatementError) as e:
        logger.warning("status_task_id_invalido", task_id=task_id, error=str(e))
        raise HTTPException(404, "Task no encontrada")
    if not row:
        raise HTTPException(404, "Task no encontrada")

    return _status_from_row(row)


@router.get("/comprobantes/{task_id}", response_model=ComprobanteOut)
async def get_comprobante(task_id: str, db: AsyncSession = Depends(get_db)):
    try:
        UUID(task_id)
    except ValueError:
        raise HTTPException(404, "Comprobante no encontrado")

    repo = ComprobanteRepo(db)
    try:
        row = await repo.get_by_task_id(task_id)
    except (DataError, DBAPIError, StatementError) as e:
        logger.warning("comprobante_task_id_invalido", task_id=task_id, error=str(e))
        raise HTTPException(404, "Comprobante no encontrado")
    if not row:
        raise HTTPException(404, "Comprobante no encontrado")
    return row


@router.post("/comprobantes/{task_id}/reextraer", response_model=UploadResponse)
@limiter.limit("30/minute")
async def reextraer_comprobante(
    request: Request,
    task_id: str,
    body: ReextraerIn,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_operator),
):
    """Re-extrae datos con otro perfil, SIN volver a ejecutar OCR."""
    try:
        UUID(task_id)
    except ValueError:
        raise HTTPException(404, "Comprobante no encontrado")

    repo = ComprobanteRepo(db)
    row = await repo.get_by_task_id(task_id)
    if not row:
        raise HTTPException(404, "Comprobante no encontrado")
    if not row.texto_ocr:
        raise HTTPException(400, "El comprobante no tiene texto OCR para re-extraer")

    perfiles = await _cargar_perfiles(db)
    perfil = None
    if body.perfil_id:
        perfil = next(
            (p for p in perfiles if p.id == body.perfil_id or p.codigo == body.perfil_id),
            None,
        )
        if not perfil:
            raise HTTPException(404, "Perfil no encontrado o inactivo")
    else:
        perfil = _resolver_perfil(perfiles, None, row.texto_ocr)

    campos = extraer_campos(row.texto_ocr, perfil) if perfil else {}

    base = None
    if row.datos_extraidos:
        try:
            base = DatosExtraidos(**row.datos_extraidos)
        except Exception:
            base = None

    nit_pref = base.nit_pagador if base else None
    dv_pref = base.dv_pagador if base else None

    if perfil:
        if base is not None:
            datos = _fusionar_datos(base, campos, perfil)
        else:
            datos = _datos_desde_campos(campos, perfil, nit_pref, dv_pref)
        if base is not None and campos.get("nit_pagador") is None:
            datos = aplicar_identificacion_pref(datos, nit_pref, dv_pref)
    else:
        if base is None:
            datos = await llm_service.extraer_datos(row.texto_ocr)
        else:
            datos = base

    await emit_stage(task_id, "reextract_start", mensaje="Re-extrayendo con perfil…")
    nit_result = await validar_nit_snri(datos.nit_pagador, datos.dv_pagador or "", snri_client)
    await repo.update_datos(
        task_id,
        datos=datos.model_dump(mode="json"),
        status="completed",
        nit_validado=nit_result.get("valido"),
        nit_mensaje=nit_result.get("mensaje"),
        errores=[],
        perfil_id=perfil.id if perfil else None,
    )
    logger.info(
        "reextraccion_completada",
        task_id=task_id,
        perfil=perfil.codigo if perfil else None,
        campos=campos,
    )
    await emit_stage(
        task_id,
        "completed",
        mensaje=f"Re-extraído con perfil {perfil.nombre}" if perfil else "Re-extraído",
        datos=datos.model_dump(mode="json"),
        errores=[],
        nit_validado=nit_result.get("valido"),
        nit_mensaje=nit_result.get("mensaje"),
        texto_ocr=(row.texto_ocr or "")[:8000],
        confianza=float(row.confianza_ocr) if row.confianza_ocr is not None else None,
        paginas=row.paginas,
        perfil_codigo=perfil.codigo if perfil else None,
    )

    return _status_from_row(row)
