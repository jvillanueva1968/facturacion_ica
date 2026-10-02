# Docker en local — Configuración y tecnología

Guía de referencia del stack Docker local: servicios, tecnologías, volúmenes y operación.
Archivo fuente: `docker/docker-compose.yml` + `docker/Dockerfile`.

---

## 1. Orquestación

- **Docker Compose v2** — archivo único `docker/docker-compose.yml` (build context `..`).
- **1 red bridge:** `facturacion-net` (todos los servicios se comunican por nombre de servicio).
- **Volúmenes:** `pg-data`, `redis-data`, `ollama-data`, `minio-data`, `paddle-models`,
  `paddle-hf-cache` + bind mounts del código (`../app`, `../wsdl`, `../tests`), `./uploads`
  y `../certs` (solo lectura).
- **Hot-reload:** el código queda montado en el contenedor y uvicorn corre con `--reload`,
  así que cambios en Python/HTML se reflejan sin reconstruir la imagen.

## 2. Servicios (6)

| Servicio | Imagen/base | Tecnología | Puerto | Función |
|---|---|---|---|---|
| **api** | `python:3.11-slim` (build propio) | FastAPI + Uvicorn, SQLAlchemy 2 async + asyncpg, Pydantic v2 | 8000 | UI web, API, `/docs`, `/metrics`, WebSocket de progreso |
| **db** | `postgres:15-alpine` | PostgreSQL 15 | 5432 | Esquema por `create_all` + seed de perfiles al arrancar |
| **redis** | `redis:7-alpine` | Redis 7 | 6379 | Progreso de tareas y rate-limit |
| **ollama** | `ollama/ollama` | Ollama + `llama3.2:3b` (reserva **GPU NVIDIA** en compose) | 11434 | LLM de respaldo en la extracción |
| **minio** | `quay.io/minio/minio` | Almacenamiento S3-compatible | 9000 / 9001 | Objetos (facturas/adjuntos) |
| **sigma-mock** | `php:8.4-apache` | PHP 8.4 + Apache (mock del servicio SIGMA) | 8080 | Simulación de SIGMA |

## 3. Imagen `api` (Dockerfile) — capas de tecnología

1. **Sistema:** `tesseract-ocr` + `tesseract-ocr-spa` (OCR), `poppler-utils` (PDF→imagen),
   libgl/glib/gcc, **Oracle Instant Client 21.12** (para `oracledb`).
2. **Dependencias Python** (`pyproject.toml`, poetry):
   - Web/API: `fastapi`, `uvicorn`, `pydantic`, `slowapi` (rate-limit), `prometheus-fastapi-instrumentator` (`/metrics`), `structlog`.
   - Persistencia: `sqlalchemy[asyncio]`, `asyncpg` (PostgreSQL), `redis`.
   - OCR/documentos: `pytesseract`, `opencv-python-headless`, `pillow`, `pdf2image`, `pypdf`.
   - SNRI/SOAP: `zeep` (WSDL local `wsdl/`), `requests-pkcs12` (certificado `certs/cliente.p12`), `oracledb`.
   - Seguridad: `python-jose[cryptography]` (JWT), `passlib[bcrypt]`.
   - Extras: `httpx`, `aiofiles`, `tenacity`, `python-dotenv`.
3. **Motor OCR alterno (pruebas A/B):** `paddlepaddle==3.3.1`, `paddleocr==3.7.0`,
   `onnxruntime`. El selector **"Motor OCR"** de la UI elige Tesseract o Paddle por carga;
   los modelos PP-OCRv6 (~134 MB) se descargan al volumen `paddle-models` en la primera
   corrida con Paddle.
4. **Seguridad:** proceso como `appuser` (uid 1000); `certs/` montado solo lectura.
5. **CMD:** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.

## 4. Configuración de entorno (2 archivos `.env`)

| Archivo | Quién lo lee | Contenido |
|---|---|---|
| `./.env` (raíz) | `env_file` del compose → app | `DATABASE_URL`, `SNRI_*` (WSDL, cert, credenciales), `LLM_PROVIDER`, `OLLAMA_*`, `OPENROUTER_API_KEY`, `SIGMA_API_TOKEN`, `SNRI_DEMO_MODE`, `APP_SECRET_KEY`, `UPLOAD_DIR`, `MAX_FILE_SIZE` |
| `docker/.env` | Sustituciones `${...}` del compose | Mismas claves usadas arriba del nivel de servicios (p. ej. `SNRI_CERT_PASSWORD`, `APP_SECRET_KEY`) |

Notas:

- El compose fija `ENVIRONMENT=development`: docs `/docs` y CORS `*` quedan activos
  (correcto en local; en producción hay que cambiarlo).
- `SNRI_DEMO_MODE=true` ejecuta facturación simulada sin certificado.
- **Advertencia:** el `.env` de la raíz está trackeado en git con valores reales; para
  otro entorno hay que regenerar secretos (`APP_SECRET_KEY`, `SIGMA_API_TOKEN`, password DB).

## 5. Operación local

```bash
# Primera vez (construye imágenes ~5-10 min; incluye paddle ~350 MB de descarga)
docker compose -f docker/docker-compose.yml up -d --build

# Estado y salud (healthchecks configurados por servicio)
docker compose -f docker/docker-compose.yml ps

# Logs
docker compose -f docker/docker-compose.yml logs -f api

# Modelo LLM (solo primera vez)
docker compose -f docker/docker-compose.yml exec ollama ollama pull llama3.2:3b
docker compose -f docker/docker-compose.yml exec ollama ollama list

# Tests dentro de la imagen (Python 3.11)
docker compose -f docker/docker-compose.yml exec api python -m pytest tests/ -q

# Reconstruir solo la API tras cambiar Dockerfile/pyproject
docker compose -f docker/docker-compose.yml build api && docker compose -f docker/docker-compose.yml up -d api

# Parar (los datos persisten en volúmenes)
docker compose -f docker/docker-compose.yml down

# Parar y BORRAR datos (BD, Redis, Ollama, MinIO, modelos Paddle)
docker compose -f docker/docker-compose.yml down -v
```

## 6. Checklist de verificación tras levantar

1. `docker compose ps` → todos `healthy` (sigma-mock y ollama sin healthcheck: `running`).
2. `GET http://localhost:8000/health` → `status: ok`, `database_connected: true`.
3. UI en `http://localhost:8000` → flujo de carga responde.
4. Token de prueba: `POST /api/v1/auth/jwt?subject=operador&roles=operator`.
5. Upload de comprobante con **Tesseract** y con **Paddle** (selector en el paso 2).
6. `GET http://localhost:8000/metrics` → métricas Prometheus.
7. `docker compose logs api` sin errores.

## 7. Puertos publicados (local)

| Puerto | Servicio | Notas |
|---|---|---|
| 8000 | api | UI, API, `/docs`, `/metrics`, WebSocket |
| 5432 | db | Accesible desde el host |
| 6379 | redis | |
| 11434 | ollama | API de Ollama |
| 9000 / 9001 | minio | API / consola (`minioadmin/minioadmin`) |
| 8080 | sigma-mock | token `dev-sigma-token` |

**Advertencia:** todos se publican en `0.0.0.0` — aceptable en local; en un servidor
público deben restringirse (bind a `127.0.0.1`, firewall o reverse proxy).

## 8. Puntos de atención

- **Ollama con GPU** exige `nvidia-container-toolkit`; sin él, `docker compose up` falla
  por la reserva de dispositivos del servicio `ollama`.
- **Primera corrida con Paddle** descarga los modelos al volumen `paddle-models`
  (persistente entre recreaciones del contenedor).
- `ENVIRONMENT=development` está fijado en el compose: desactivarlo (junto con `/docs`
  y CORS `*`) si algún día se lleva a producción.
- CI (`.github/workflows/ci.yml`) corre pytest en el runner de Ubuntu **sin** Docker;
  la imagen solo se construye/localmente.
