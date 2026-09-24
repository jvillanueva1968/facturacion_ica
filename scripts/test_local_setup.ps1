<#
.SYNOPSIS
    Verificación rápida del entorno local para Facturación ICA
#>

Write-Host "🔍 Verificando entorno local..." -ForegroundColor Cyan
Write-Host ""

# 1. Verificar Docker
Write-Host "1. Docker Desktop:" -ForegroundColor Yellow
try {
    $dockerVersion = docker version --format '{{.Server.Version}}' 2>$null | Select-Object -First 1
    Write-Host "   ✓ Docker $dockerVersion" -ForegroundColor Green
    $composeVersion = docker compose version 2>$null
    Write-Host "   ✓ $composeVersion" -ForegroundColor Green
} catch {
    Write-Host "   ✗ Docker no disponible" -ForegroundColor Red
}
Write-Host ""

# 2. Verificar archivos críticos
Write-Host "2. Archivos críticos:" -ForegroundColor Yellow
$wsdlPath = "..\wsdl\WS_FACTURACION.wsdl"
$envPath = "..\.env"
$certPath = "..\certs\cliente.p12"

if (Test-Path $wsdlPath) {
    $size = (Get-Item $wsdlPath).Length
    Write-Host "   ✓ WSDL existe ($size bytes)" -ForegroundColor Green
} else {
    Write-Host "   ✗ WSDL NO ENCONTRADO" -ForegroundColor Red
}

if (Test-Path $envPath) {
    Write-Host "   ✓ .env existe" -ForegroundColor Green
} else {
    Write-Host "   ⚠ .env NO EXISTE (copiar .env.example)" -ForegroundColor Yellow
}

if (Test-Path $certPath) {
    Write-Host "   ✓ Certificado .p12 existe" -ForegroundColor Green
} else {
    Write-Host "   ⚠ Certificado .p12 NO ENCONTRADO (requerido para SNRI real)" -ForegroundColor Yellow
}
Write-Host ""

# 3. Verificar contenedores
Write-Host "3. Estado contenedores:" -ForegroundColor Yellow
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
Write-Host ""

# 4. Health checks
Write-Host "4. Health checks:" -ForegroundColor Yellow
$services = @("api", "ollama", "db", "redis", "minio")
foreach ($service in $services) {
    $containerName = "facturacion-$service"
    try {
        $status = docker inspect --format '{{.State.Health.Status}}' $containerName 2>$null
        if (-not $status) { $status = "no-healthcheck" }
        $color = if ($status -eq "healthy") { "Green" } elseif ($status -eq "unhealthy") { "Red" } else { "Yellow" }
        Write-Host "   $service: $status" -ForegroundColor $color
    } catch {
        Write-Host "   $service: no encontrado" -ForegroundColor Red
    }
}
Write-Host ""

# 5. Test API básica
Write-Host "5. Test API:" -ForegroundColor Yellow
try {
    $health = Invoke-WebRequest -Uri "http://localhost:8000/health" -Method GET -TimeoutSec 5 -ErrorAction Stop
    Write-Host "   ✓ API responde" -ForegroundColor Green
    $health.Content | ConvertFrom-Json | Format-List
} catch {
    Write-Host "   ✗ API NO RESPONDE en localhost:8000" -ForegroundColor Red
}
Write-Host ""

# 6. Test WSDL en contenedor
Write-Host "6. Test WSDL en contenedor API:" -ForegroundColor Yellow
try {
    $result = docker compose exec -T api python -c "
from zeep import Client
c = Client('/app/wsdl/WS_FACTURACION.wsdl')
ops = [op for op in dir(c.service) if not op.startswith('_')]
print(f'OK|{len(ops)}|{\"M_CrearFactura\" in ops}|{\"A_InicioTransaccion\" in ops}')
"
    if ($result -match "OK\|(\d+)\|(\w+)\|(\w+)") {
        $ops = $matches[1]
        $factura = $matches[2]
        $auth = $matches[3]
        Write-Host "   ✓ WSDL carga: $ops operaciones" -ForegroundColor Green
        Write-Host "   ✓ M_CrearFactura: $factura" -ForegroundColor Green
        Write-Host "   ✓ A_InicioTransaccion: $auth" -ForegroundColor Green
    }
} catch {
    Write-Host "   ✗ Error probando WSDL" -ForegroundColor Red
}
Write-Host ""

# 7. Test Ollama
Write-Host "7. Test Ollama:" -ForegroundColor Yellow
try {
    $ollama = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -Method GET -TimeoutSec 5 -ErrorAction Stop
    $models = ($ollama.Content | ConvertFrom-Json).models.name
    Write-Host "   ✓ Ollama responde" -ForegroundColor Green
    Write-Host "   Modelos: $($models -join ', ')" -ForegroundColor Gray
} catch {
    Write-Host "   ⚠ Ollama no responde (puede estar descargando modelo)" -ForegroundColor Yellow
}
Write-Host ""

Write-Host "✅ Verificación completada" -ForegroundColor Cyan
Write-Host ""
Write-Host "📋 Próximos pasos:" -ForegroundColor Cyan
Write-Host "   1. Si falta .env: Copy-Item .env.example .env ; code .env"
Write-Host "   2. Si falta certificado: colocar en certs\cliente.p12"
Write-Host "   3. Si todo OK: probar autenticación SNRI con credenciales ICA"
Write-Host "   4. Ver docs: http://localhost:8000/docs"