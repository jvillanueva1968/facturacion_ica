# Sistema de Facturación Automatizada ICA - Guía Local

## Prerrequisitos

- Docker Desktop instalado y corriendo
- Git (opcional)
- Certificado `.p12` del ICA (para pruebas reales SNRI)
- Credenciales `A_InicioTransaccion` del ICA

---

## 1. Configuración Inicial

```bash
cd facturacion_ica

# Copiar variables de entorno
cp .env.example .env

# Editar .env con tus valores reales:
# - SNRI_CERT_PASSWORD=password_del_certificado
# - SIGMA_API_TOKEN=token_php_sigma
# - APP_SECRET_KEY=generar_con_openssl_rand_base64_32
```

### Generar APP_SECRET_KEY
```bash
# Linux/Mac/Git Bash
openssl rand -base64 32

# PowerShell
[Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
```

---

## 2. Certificado ICA (CRÍTICO)

```bash
# Colocar certificado en carpeta certs (solo lectura en contenedor)
cp /ruta/a/tu/certificado.p12 certs/cliente.p12

# Verificar permisos (Linux/Mac)
chmod 600 certs/cliente.p12
```

**Sin certificado**: La API levantará pero SNRI rechazará peticiones autenticadas.

---

## 3. Levantar Stack Completo

```bash
cd docker

# Primera vez (construye imágenes ~5-10 min)
docker-compose up -d --build

# Ver logs
docker-compose logs -f api

# Verificar salud
curl http://localhost:8000/health
```

### Servicios Disponibles

| Servicio | URL | Credenciales |
|----------|-----|--------------|
| **UI Web** | http://localhost:8000 | - |
| **API FastAPI** | http://localhost:8000/docs | - |
| **Ollama (LLM)** | http://localhost:11434 | - |
| **PostgreSQL** | localhost:5432 | postgres/postgres |
| **Redis** | localhost:6379 | - |
| **MinIO Console** | http://localhost:9001 | minioadmin/minioadmin |
| **SIGMA mock** | http://localhost:8080 | `X-API-Token: dev-sigma-token` |

### Modo demo (sin certificado SNRI)

Con `SNRI_DEMO_MODE=true` (default en `.env` de dev), `POST /api/v1/facturar/simple|detalle`
emite un número `DEMO-…` sin token SNRI y sincroniza con el mock SIGMA
(`sigma_synced=true` en `/api/v1/facturas`). Para facturación real, poner
`SNRI_DEMO_MODE=false` y cargar `certs/cliente.p12` + credenciales ICA.

---

## 4. Descargar Modelo LLM (Ollama)

```bash
# En otra terminal
docker exec facturacion-ollama ollama pull llama3.2:3b

# Verificar
docker exec facturacion-ollama ollama list
```

---

## 5. Probar Conectividad SNRI (Sin Credenciales)

```bash
# Health check básico
curl http://localhost:8000/health

# Verificar WSDL cargado
curl http://localhost:8000/health | jq .snri_wsdl_loaded

# Test V_Ping (no requiere token)
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"id_proyecto": 0}'  # Fallará sin credenciales reales
```

---

## 6. Probar Con Credenciales ICA (REAL)

```bash
# 1. Obtener token
TOKEN_RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{
    "id_proyecto": TU_ID_PROYECTO,
    "username": "TU_USUARIO",
    "password": "TU_PASSWORD"
  }')

echo $TOKEN_RESPONSE | jq .

# 2. Extraer token
TOKEN=$(echo $TOKEN_RESPONSE | jq -r .token)

# 3. Probar catálogos
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/catalogos/todos | jq .

# 4. Probar validación NIT
curl -X POST http://localhost:8000/api/v1/nit/validar-snri \
  -H "Content-Type: application/json" \
  -d '{"nit": "900123456", "dv": "7"}' | jq .

# 5. Probar factura simple (requiere datos válidos de catálogos)
curl -X POST http://localhost:8000/api/v1/facturar/simple \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "id_proyecto": "TU_ID",
    "id_seccional": "TU_SECCIONAL",
    "id_entidad": "TU_ENTIDAD",
    "nit_pagador": "900123456",
    "dv_pagador": "7",
    "nombre_razon_social": "EMPRESA PRUEBA SAS",
    "id_tipo_documento": 1,
    "id_tipo_persona": 2,
    "gran_contribuyente": 0,
    "autorretenedor": 0,
    "regimen_comun": 1,
    "regimen_simplificado": 0,
    "id_departamento": 11,
    "id_ciudad": 11001,
    "direccion_principal": "CALLE 123 #45-67",
    "telefono": "6011234567",
    "email": "test@empresa.com",
    "id_forma_pago": "CONSIGNACION",
    "id_banco": "1001",
    "numero_consignacion": "TEST-2024-001",
    "fecha_consignacion": "2024-01-15",
    "id_servicio": "SERV-001",
    "valor": "100000.00",
    "cantidad": "1",
    "valor_total": "100000.00"
  }' | jq .
```

---

## 7. Probar Upload OCR + LLM

```bash
# Subir imagen/PDF
curl -X POST http://localhost:8000/api/v1/upload \
  -F "file=@/ruta/a/comprobante.png" | jq .

# Respuesta: {"task_id": "uuid", "status": "processing"}

# Consultar estado (implementar en Redis/BD)
curl http://localhost:8000/api/v1/status/TU_TASK_ID
```

---

## 8. Tests Automatizados

```bash
# pytest ya viene en la imagen api
docker-compose exec api python -m pytest tests/ -v

# Solo WSDL (sin app)
docker run --rm \
  -v "$(pwd)/../wsdl:/wsdl" \
  -v "$(pwd)/../tests:/tests" \
  python:3.11-slim bash -c "pip install zeep pytest -q && python -m pytest /tests/test_wsdl.py -v"

# Load/stress (NO llama /facturar ni crea facturas)
python scripts/load_test.py --base http://localhost:8000 --concurrency 20 --duration 15
# Métricas: RPS, latencia p50/p95/p99, códigos HTTP, 429 de rate-limit
```

---

## 9. Logs y Debugging

```bash
# Logs API
docker-compose logs -f api

# Logs Ollama
docker-compose logs -f ollama

# Entrar al contenedor API
docker-compose exec api bash

# Ver variables de entorno
docker-compose exec api env | grep SNRI
```

---

## 10. Problemas Comunes

| Problema | Solución |
|----------|----------|
| `snri_wsdl_loaded: false` | Verificar `wsdl/WS_FACTURACION.wsdl` existe |
| Error certificado `.p12` | Verificar password en `.env` y archivo en `certs/` |
| Ollama no responde | `docker-compose restart ollama` y esperar healthcheck |
| Puerto 8000 ocupado | Cambiar en `docker-compose.yml` |
| BD no conecta | `docker-compose restart db` y verificar healthcheck |

---

## 11. Auth JWT + RBAC (opcional en dev)

Roles: `viewer` (lectura) < `operator` (upload/facturar) < `admin`.

```bash
# Emitir token con rol (no confundir con token SNRI)
curl -X POST "http://localhost:8000/api/v1/auth/jwt?subject=operador&roles=operator"
# → {"access_token":"...","roles":["operator"]}

# Quién soy
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/auth/me

# Usar en API
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/facturas
```

| Endpoint | Rol mínimo |
|----------|------------|
| `GET /facturas`, catálogos, `POST /nit/validar*` | viewer |
| `POST /upload`, `POST /facturar/*`, `POST /auth/token` (SNRI) | operator |
| otorgar rol `admin` en `/auth/jwt` | admin |

En `ENVIRONMENT=development` + sin `APP_SECRET_KEY`, el Bearer es opcional
(el request se trata como `admin`). En `production` con `APP_SECRET_KEY` seteado,
Bearer es obligatorio. El header se envía desde la UI si guardas el JWT en
`localStorage` clave `ica_jwt`.

Rate limiting (slowapi): 60/min global; upload 10/min; facturar 20/min; emisión JWT y `POST /auth/token` (SNRI) 10/min.

**Idempotencia**: si `numero_consignacion` ya tiene factura `emitida`, `POST /facturar/*` devuelve la existente con `errores[].codigo=DUPLICADO` (no crea fila nueva).

### PDF de la factura

```bash
# POST genera/guarda PDF (demo: PDF local; real: P_ImprimirFactura)
curl -X POST http://localhost:8000/api/v1/facturar/imprimir/DEMO-XXXX

# GET descarga application/pdf (desde BD o al generar)
curl -OJ http://localhost:8000/api/v1/facturar/DEMO-XXXX/pdf
```

En la UI, tras emitir, botón **Descargar PDF**.

### Progreso en tiempo real (WebSocket)

```
ws://localhost:8000/api/v1/ws/status/{task_id}
ws://localhost:8000/api/v1/ws/status/{task_id}?token=JWT   # si auth activo
```

Eventos JSON: `stage` (`received|ocr_start|ocr_done|llm_start|llm_done|nit_start|completed|failed`),
`status`, `progress` (0-100), `mensaje`, `datos`, `nit_validado`, `nit_mensaje`.
La UI se suscribe tras el upload; si el WS no conecta, usa polling `/status/{task_id}`.

---

## 12. Detener y Limpiar

```bash
# Detener
docker-compose down

# Detener + borrar volúmenes (BD, Redis, Ollama)
docker-compose down -v

# Reconstruir todo desde cero
docker-compose down -v && docker-compose up -d --build
```

---

## 13. Flujo de Desarrollo Típico

```bash
# 1. Cambios en código (hot reload activo)
# Editar app/services/snri_client.py → se reinicia solo

# 2. Ver logs en tiempo real
docker-compose logs -f api

# 3. Probar endpoint en Swagger
# http://localhost:8000/docs

# 4. Ejecutar tests
docker-compose exec api python -m pytest tests/ -v

# 5. Commit cambios
git add . && git commit -m "feat: descripción"
```