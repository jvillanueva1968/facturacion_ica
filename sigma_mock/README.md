# Mock local de SIGMA (PHP) - NO usar en producción

Endpoint espejo de la API SIGMA real: `POST /api/facturas/registrar` con header `X-API-Token`.

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/health` | Health check (sin token) |
| POST | `/api/facturas/registrar` | Registrar factura (idempotente por `numero_referencia`) |
| GET | `/api/facturas/consultar?numero_referencia=...` | Consultar por referencia |

Header obligatorio (excepto health): `X-API-Token: dev-sigma-token`

## Docker (standalone)

```bash
docker build -t facturacion-sigma-mock sigma_mock
docker run -d --name facturacion-sigma-mock -p 8080:80 \
  -e SIGMA_API_TOKEN=dev-sigma-token \
  facturacion-sigma-mock

# Si la API ya corre en docker, conectar a la misma red con alias DNS:
docker network connect --alias sigma-mock <red_facturacion> facturacion-sigma-mock
```

## docker-compose

El servicio se llama `sigma-mock` y la API apunta a `http://sigma-mock/api`
con `SIGMA_API_TOKEN=dev-sigma-token`.

```bash
docker-compose up -d sigma-mock
```

## Smoke test

```bash
curl -s http://localhost:8080/api/health
curl -s -X POST http://localhost:8080/api/facturas/registrar \
  -H 'Content-Type: application/json' \
  -H 'X-API-Token: dev-sigma-token' \
  -d '{"numero_referencia":"123456","valor_total":150000}'
curl -s -H 'X-API-Token: dev-sigma-token' \
  'http://localhost:8080/api/facturas/consultar?numero_referencia=123456'
```
