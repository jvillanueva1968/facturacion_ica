from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends
from uuid import uuid4
from pathlib import Path
import aiofiles
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Request

from app.models.schemas import UploadResponse, DatosExtraidos, ComprobanteOut
from app.core.deps import require_auth
from app.core.rate_limit import limiter
from app.services.ocr_service import OCRService
from app.services.llm_service import LLMService
from app.services.nit_validator import validar_nit_snri
from app.services.snri_client import SNRIClient
from app.config import get_settings
from app.db.session import get_db, SessionLocal
from app.db.repositories import ComprobanteRepo

router = APIRouter()
settings = get_settings()
logger = structlog.get_logger()

ocr_service = OCRService(
    tesseract_cmd=settings.tesseract_cmd,
    lang=settings.tesseract_lang,
    dpi=settings.ocr_dpi
)
llm_service = LLMService()
snri_client = SNRIClient()


@router.post("/upload", response_model=UploadResponse)
@limiter.limit("10/minute")
async def upload_comprobante(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
    user: dict = Depends(require_auth),
):
    if file.content_type not in settings.allowed_mimes:
        raise HTTPException(400, f"Tipo de archivo no permitido: {file.content_type}")

    content = await file.read()
    if len(content) > settings.max_file_size:
        raise HTTPException(413, f"Archivo muy grande. Máximo {settings.max_file_size/1024/1024}MB")

    task_id = str(uuid4())
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{task_id}_{file.filename}"

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

    background_tasks.add_task(procesar_documento, task_id, file_path)

    logger.info("archivo_recibido", task_id=task_id, filename=file.filename, size=len(content))

    return UploadResponse(
        task_id=task_id,
        status="processing",
        mensaje="Archivo recibido, procesando..."
    )


async def procesar_documento(task_id: str, file_path: Path):
    try:
        logger.info("iniciando_procesamiento", task_id=task_id)

        async with SessionLocal() as session:
            repo = ComprobanteRepo(session)

            texto_ocr, confianza, paginas = ocr_service.extract_text(file_path)
            await repo.update_ocr(task_id, texto=texto_ocr, confianza=confianza, paginas=paginas)
            logger.info("ocr_completado", task_id=task_id, confianza=confianza, paginas=paginas)

            datos = await llm_service.extraer_datos(texto_ocr)
            await repo.update_datos(
                task_id,
                datos=datos.model_dump(mode="json"),
                status="processing",
            )
            logger.info("llm_extraccion_completada", task_id=task_id, nit=datos.nit_pagador)

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

    except Exception as e:
        logger.error("error_procesamiento", task_id=task_id, error=str(e))
        try:
            async with SessionLocal() as session:
                await ComprobanteRepo(session).mark_failed(task_id, str(e))
        except Exception as db_err:
            logger.error("error_marking_failed", task_id=task_id, error=str(db_err))
    finally:
        file_path.unlink(missing_ok=True)


@router.get("/status/{task_id}", response_model=UploadResponse)
async def get_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    repo = ComprobanteRepo(db)
    row = await repo.get_by_task_id(task_id)
    if not row:
        raise HTTPException(404, "Task no encontrada")

    datos = None
    if row.datos_extraidos:
        try:
            datos = DatosExtraidos(**row.datos_extraidos)
        except Exception:
            datos = None

    return UploadResponse(
        task_id=row.task_id,
        status=row.status,
        datos=datos,
        errores=row.errores or [],
    )


@router.get("/comprobantes/{task_id}", response_model=ComprobanteOut)
async def get_comprobante(task_id: str, db: AsyncSession = Depends(get_db)):
    repo = ComprobanteRepo(db)
    row = await repo.get_by_task_id(task_id)
    if not row:
        raise HTTPException(404, "Comprobante no encontrado")
    return row
