# Plan de Implementación - Sistema de Facturación Automatizada ICA (SNRI + SIGMA)

## Resumen Ejecutivo

Aplicación web para automatizar el proceso de facturación del ICA:
1. **Carga de comprobantes** (imágenes/PDF) → OCR + LLM extrae datos
2. **Validación NIT** (algoritmo DIAN Módulo 11 + SNRI)
3. **Creación factura SNRI** (SOAP/Zeep con certificado .p12)
4. **Registro en SIGMA** (API REST PHP → Oracle 19c)

---

## Stack Tecnológico

| Capa | Tecnología |
|------|------------|
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Frontend | HTML5, Alpine.js, Vanilla JS |
| OCR | Tesseract + OpenCV preprocessing |
| IA/LLM | Ollama (local) / OpenRouter (cloud) |
| SOAP | Zeep + requests-pkcs12 (cert .p12) |
| BD Local | PostgreSQL (auditoría) + Redis (cache) |
| Storage | MinIO / Local filesystem |
| Contenedores | Docker + docker-compose |

---

## Estructura del Proyecto

```
facturacion_ica/
├── app/
│   ├── main.py                 # FastAPI app + lifespan
│   ├── config.py               # Pydantic Settings
│   ├── models/
│   │   └── schemas.py          # Pydantic models (WSDL-based)
│   ├── services/
│   │   ├── snri_client.py      # Cliente Zeep tipado (CORE)
│   │   ├── nit_validator.py    # Módulo 11 DIAN
│   │   ├── ocr_service.py      # Tesseract + OpenCV
│   │   ├── llm_service.py      # Ollama/OpenRouter
│   │   └── sigma_client.py     # HTTP client PHP
│   ├── api/
│   │   ├── upload.py           # POST /upload
│   │   ├── facturar.py         # POST /facturar (simple/detalle)
│   │   ├── validate.py         # POST /nit/validar
│   │   └── catalogos.py        # GET /catalogos/*
│   └── utils/
├── wsdl/
│   └── WS_FACTURACION.wsdl     # WSDL real descargado (82KB)
├── certs/
│   └── cliente.p12             # Certificado ICA (pendiente)
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml
├── tests/
│   └── test_wsdl.py
├── pyproject.toml
└── .env.example
```

---

## Flujo de Trabajo Completo

```
Usuario → Frontend (drag&drop)
    ↓
POST /api/v1/upload → Background Task
    ↓
OCR (Tesseract + OpenCV) → Texto crudo
    ↓
LLM (Ollama) → JSON estructurado (DatosExtraidos)
    ↓
Validar NIT (Módulo 11 + SNRI E_ConsultaTercero)
    ↓
Si no existe → F_CrearTercero
    ↓
M_CrearFactura (1 servicio) / M_CrearFacturaAlterna (múltiples)
    ↓
Respuesta: NumeroFactura, CUFE, IdFactura
    ↓
P_ImprimirFactura → PDF base64
    ↓
POST /api/facturas/registrar (PHP SIGMA) → Oracle staging
    ↓
Frontend: Success + PDF download
```

---

## Operaciones SNRI Críticas (WSDL Real)

| Operación | Descripción | Uso |
|-----------|-------------|-----|
| `A_InicioTransaccion` | Obtener token (requerido) | **PRIMERO siempre** |
| `R_ConsultaFormasPago` | Catálogo formas pago | Cache inicio |
| `B_ConsultaBancos` | Catálogo bancos | Cache inicio |
| `D_ConsultaServicio` | Servicios ICA facturables | Cache inicio |
| `C_ConsultaSeccional` | Seccionales ICA | Cache inicio |
| `H_ConsultaTipoDocumentos` | Tipos doc (1=NIT, 2=CC...) | Cache inicio |
| `L_ConsultaTiposPersona` | 1=Natural, 2=Jurídica | Cache inicio |
| `I_ConsultaDepartamentos` | Deptos DANE | Cache inicio |
| `J_ConsultaCiudades` | Ciudades por depto | Cache inicio |
| `E_ConsultaTercero` | Verificar NIT existe | Validación |
| `F_CrearTercero` | Crear si no existe | Pre-factura |
| `M_CrearFactura` | Factura simple (1 servicio) | **Principal** |
| `M_CrearFacturaAlterna` | Factura detalle (múltiples) | Múltiples servicios |
| `P_ImprimirFactura` | PDF base64 | Entrega usuario |
| `V_Ping` | Health check | Monitoreo |

---

## Modelo de Datos Factura (Basado en WSDL)

```python
# Campos OBLIGATORIOS (todos string en SOAP):
token: str                          # De A_InicioTransaccion
id_proyecto: str                    # Código proyecto ICA (asignado)
id_seccional: str                   # De C_ConsultaSeccional
id_entidad: str                     # Entidad/empresa
id_tercero: str                     # NIT SIN DV
id_tipo_documento: int              # 1=NIT, 2=CC, 3=CE, 4=PP, 5=TI
id_tipo_persona: int                # 1=Natural, 2=Jurídica
gran_contribuyente: int             # 0/1
autorretenedor: int                 # 0/1
regimen_comun: int                  # 0/1
regimen_simplificado: int           # 0/1
nro_identificacion: str             # NIT CON DV (ej: "900123456-7")
nombre_razon_social: str
id_departamento: int                # Código DANE
id_ciudad: int                      # Código DANE
direccion_principal: str
telefono: str (opcional)
email: str (opcional)
id_forma_pago: str                  # De R_ConsultaFormasPago
id_banco: str                       # De B_ConsultaBancos
numero_consignacion: str            # Referencia única pago
fecha_consignacion: str             # YYYY-MM-DD
id_servicio: str                    # De D_ConsultaServicio
valor: str                          # Valor unitario (string: "150000.00")
cantidad: str                       # Cantidad (string: "1")
valor_total: str                    # Total (string: "150000.00")
observaciones: str (opcional)
ticket_id: str (opcional, PSE)
```

---

## Validación NIT - Algoritmo DIAN Módulo 11

```python
PESOS_DIAN = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]

def calcular_dv_nit(nit: str) -> str:
    # Invertir, multiplicar por pesos, sumar, módulo 11
    # Residuo 0/1 → DV = residuo; sino DV = 11 - residuo
```

---

## Despliegue Local (Docker)

```bash
# 1. Configurar variables
cp .env.example .env
# Editar .env con: SNRI_CERT_PASSWORD, SIGMA_API_TOKEN, APP_SECRET_KEY

# 2. Colocar certificado .p12 en certs/cliente.p12

# 3. Levantar stack
cd docker
docker-compose up -d --build

# 4. Verificar
curl http://localhost:8000/health
# Docs: http://localhost:8000/docs

# 5. Descargar modelo LLM (si usa Ollama)
docker exec facturacion-ollama ollama pull llama3.2:3b
```

**Servicios incluidos:**
- UI: http://localhost:8000
- API: http://localhost:8000/docs
- SIGMA mock: http://localhost:8080
- Ollama: http://localhost:11434
- PostgreSQL: localhost:5432
- Redis: localhost:6379
- MinIO: http://localhost:9000 (console: 9001)

---

## Próximos Pasos (Orden de Prioridad)

### Semana 1: Core SNRI (BLOQUEANTE)
- [ ] Obtener certificado `.p12` de TI ICA
- [ ] Obtener credenciales entorno pruebas (id_proyecto, username, pass)
- [ ] Probar `A_InicioTransaccion` contra endpoint real
- [ ] Cargar catálogos y validar códigos propios
- [ ] Probar `E_ConsultaTercero` / `F_CrearTercero`
- [ ] Probar `M_CrearFactura` end-to-end
- [ ] Probar `P_ImprimirFactura` → PDF válido

### Semana 2: OCR + LLM Pipeline
- [x] Optimizar preprocesamiento OpenCV para comprobantes colombianos (básico)
- [ ] Prompt engineering LLM con muestras reales (50+ docs)
- [ ] Métricas de precisión extracción (>95% campos clave)
- [x] API `/upload` + background processing + status polling

### Semana 3: Integración SIGMA + Frontend
- [x] Mock PHP `/api/facturas/registrar` (idempotencia + token) — pendiente endpoint real del equipo PHP
- [x] Idempotencia por `numero_referencia` / `numero_consignacion` (mock SIGMA + app: devuelve factura emitida existente, índice único parcial)
- [x] Frontend Alpine.js: identificación NIT/DV **antes** del upload, revisión OCR, validación, facturación (5 pasos)
- [x] WebSocket para progreso tiempo real (`/api/v1/ws/status/{task_id}`, fallback polling)
- [x] Descarga PDF factura (`POST /facturar/imprimir/{n}` + `GET /facturar/{n}/pdf`, demo local / SNRI real)

### Semana 4: Hardening
- [x] JWT Auth + Bearer (dev opcional / prod obligatorio) + endpoint `/auth/jwt`
- [x] Rate limiting (slowapi): upload/facturar/NIT/JWT
- [x] Logs estructurados (structlog) + auditoría (tabla `audit_log`)
- [x] Tests carga + stress (`scripts/load_test.py`, sin `/facturar`)
- [x] Documentación OpenAPI + README local; pytest unit + API tests en imagen
- [x] RBAC (viewer/operator/admin + jerarquía + tests `test_rbac.py`)

---

## Requisitos Críticos del ICA (Pendientes)

| Requisito | Estado | Responsable |
|-----------|--------|-------------|
| Certificado cliente `.p12` | ❌ Pendiente | TI ICA |
| Credenciales `A_InicioTransaccion` | ❌ Pendiente | TI ICA |
| `id_proyecto`, `id_seccional`, `id_entidad` propios | ❌ Pendiente | ICA Negocio |
| Catálogo servicios aplicables a tu caso | ❌ Pendiente | ICA Negocio |
| Endpoint PHP SIGMA `/api/facturas/registrar` | 🟡 Mock listo (`sigma_mock/`), falta endpoint real | Equipo PHP |
| Whitelist IP servidor producción | ❌ Pendiente | Infraestructura ICA |

---

## Seguridad

- **Variables de entorno**: `.env` solo local, Docker secrets en prod
- **Certificado .p12**: Volume montado read-only, `chmod 600`
- **Rate limiting**: Redis-backed (100 req/min/IP)
- **Auditoría**: Structlog JSON con `request_id`, `user_id`, acción, resultado
- **PII/NIT**: Encriptación en reposo (Fernet) si se almacena
- **TLS**: Obligatorio en producción (no HTTP)

---

## Métricas de Éxito

| Métrica | Target |
|---------|--------|
| Precisión OCR+LLM (campos clave) | >95% |
| Tiempo factura SNRI (p95) | <5 seg |
| Disponibilidad API | 99.5% |
| Facturas duplicadas (mismo N° consignación) | 0 |
| Tiempo total upload→factura | <30 seg |

---

## Contactos Clave

| Rol | Nombre | Acción Requerida |
|-----|--------|------------------|
| TI ICA (WSDL/Cert) | - | Entregar .p12 + credenciales pruebas |
| Negocio ICA (Códigos) | - | id_proyecto, seccional, entidad, servicios |
| Equipo PHP SIGMA | - | Crear endpoint `/api/facturas/registrar` |
| Infraestructura | - | Whitelist IP, VPN acceso SNRI |