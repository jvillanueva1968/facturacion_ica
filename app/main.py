import logging
import structlog
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from app.config import get_settings
from app.api import upload, facturar, validate, catalogos
from app.core.deps import require_auth, require_viewer
from app.core.rate_limit import install_rate_limit, limiter
from app.core.security import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, VALID_ROLES, create_access_token, normalize_roles
from app.services.snri_client import SNRIClient
from app.services.sigma_client import SigmaClient
from app.db.session import init_db, engine

settings = get_settings()
STATIC_DIR = Path(__file__).parent / "static"

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logging.basicConfig(
    format="%(message)s",
    level=logging.INFO if settings.environment == "production" else logging.DEBUG,
)

snri_client = SNRIClient()
sigma_client = SigmaClient()


db_ready = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_ready
    logger = structlog.get_logger()
    logger.info("starting_up", environment=settings.environment)

    try:
        await init_db()
        db_ready = True
        logger.info("database_initialized")
    except Exception as e:
        db_ready = False
        logger.error("database_init_failed", error=str(e))

    try:
        snri_available = await snri_client.validar_disponibilidad()
        logger.info("snri_connection_test", available=snri_available)
    except Exception as e:
        logger.warning("snri_connection_test_failed", error=str(e))

    yield

    logger.info("shutting_down")
    await sigma_client.close()
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else ["https://tu-dominio.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

install_rate_limit(app)

app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(facturar.router, prefix="/api/v1", tags=["facturacion"])
app.include_router(validate.router, prefix="/api/v1", tags=["validacion"])
app.include_router(catalogos.router, prefix="/api/v1", tags=["catalogos"])


@app.post("/api/v1/auth/jwt", tags=["auth"])
@limiter.limit("10/minute")
async def emitir_jwt(
    request: Request,
    subject: str = "operator",
    roles: str = "operator",
    user: dict = Depends(require_auth),
):
    """Emite JWT de la app con roles (viewer|operator|admin).

    En producción el caller debe estar autenticado; para otorgar `admin`
    el caller debe ser admin. En dev no exige token.
    """
    requested = [r.strip().lower() for r in roles.split(",") if r.strip()]
    unknown = [r for r in requested if r not in VALID_ROLES]
    if unknown:
        raise HTTPException(400, f"Roles inválidos: {unknown}. Válidos: {sorted(VALID_ROLES)}")
    role_list = normalize_roles(requested)

    if ROLE_ADMIN in role_list and ROLE_ADMIN not in normalize_roles(user.get("roles")):
        raise HTTPException(403, "Solo un admin puede otorgar rol admin")

    token = create_access_token(subject, roles=role_list)
    return {
        "access_token": token,
        "token_type": "bearer",
        "sub": subject,
        "roles": role_list,
    }


@app.get("/api/v1/auth/me", tags=["auth"])
async def auth_me(user: dict = Depends(require_viewer)):
    return {"sub": user.get("sub"), "roles": user.get("roles", [])}

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health_check():
    database_connected = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        database_connected = True
    except Exception:
        database_connected = False

    return {
        "status": "ok",
        "version": "0.1.0",
        "snri_wsdl_loaded": snri_client.client is not None,
        "database_connected": database_connected,
    }


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index))
    return {"message": "Facturación ICA SNRI API", "docs": "/docs"}