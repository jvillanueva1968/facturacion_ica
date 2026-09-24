#!/usr/bin/env bash
# test_local_setup.sh - Verificación rápida del entorno local

set -e

echo "🔍 Verificando entorno local..."
echo ""

# 1. Verificar Docker
echo "1. Docker Desktop:"
docker version --format '{{.Server.Version}}' | head -1
docker compose version
echo "   ✓ Docker OK"
echo ""

# 2. Verificar archivos críticos
echo "2. Archivos críticos:"
[ -f "../wsdl/WS_FACTURACION.wsdl" ] && echo "   ✓ WSDL existe ($(wc -c < ../wsdl/WS_FACTURACION.wsdl) bytes)" || echo "   ✗ WSDL NO ENCONTRADO"
[ -f "../.env" ] && echo "   ✓ .env existe" || echo "   ⚠ .env NO EXISTE (copiar .env.example)"
[ -f "../certs/cliente.p12" ] && echo "   ✓ Certificado .p12 existe" || echo "   ⚠ Certificado .p12 NO ENCONTRADO (requerido para SNRI real)"
echo ""

# 3. Verificar contenedores
echo "3. Estado contenedores:"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""

# 4. Health checks
echo "4. Health checks:"
for service in api ollama db redis minio; do
  status=$(docker inspect --format='{{.State.Health.Status}}' facturacion-$service 2>/dev/null || echo "no-healthcheck")
  echo "   $service: $status"
done
echo ""

# 5. Test API básica
echo "5. Test API:"
if curl -s -f http://localhost:8000/health > /dev/null; then
  health=$(curl -s http://localhost:8000/health)
  echo "   ✓ API responde"
  echo "   $health" | jq . 2>/dev/null || echo "   $health"
else
  echo "   ✗ API NO RESPONDE en localhost:8000"
fi
echo ""

# 6. Test WSDL en contenedor
echo "6. Test WSDL en contenedor API:"
docker compose exec -T api python -c "
from zeep import Client
c = Client('/app/wsdl/WS_FACTURACION.wsdl')
ops = [op for op in dir(c.service) if not op.startswith('_')]
print(f'   ✓ WSDL carga: {len(ops)} operaciones')
print(f'   ✓ M_CrearFactura: {\"M_CrearFactura\" in ops}')
print(f'   ✓ A_InicioTransaccion: {\"A_InicioTransaccion\" in ops}')
"
echo ""

# 7. Test Ollama
echo "7. Test Ollama:"
if curl -s -f http://localhost:11434/api/tags > /dev/null; then
  models=$(curl -s http://localhost:11434/api/tags | jq -r '.models[].name' 2>/dev/null | head -5)
  echo "   ✓ Ollama responde"
  echo "   Modelos: $models"
else
  echo "   ⚠ Ollama no responde (puede estar descargando modelo)"
fi
echo ""

echo "✅ Verificación completada"
echo ""
echo "📋 Próximos pasos:"
echo "   1. Si falta .env: cp .env.example .env && editar"
echo "   2. Si falta certificado: colocar en certs/cliente.p12"
echo "   3. Si todo OK: probar autenticación SNRI con credenciales ICA"
echo "   4. Ver docs: http://localhost:8000/docs"