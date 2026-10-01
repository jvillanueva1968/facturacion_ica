<#
.SYNOPSIS
    Instala y verifica el stack OCR local en Windows:
    Tesseract 5 (+ idioma spa), Poppler y dependencias Python (pypdf, pytesseract, opencv, pillow, pdf2image).

.NOTES
    En Docker/CI los binarios ya vienen instalados (docker/Dockerfile, .github/workflows/ci.yml).
    Este script es solo para correr la app y los tests fuera de contenedor.
    Idempotente: se puede ejecutar tantas veces como sea necesario.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\setup_ocr_windows.ps1
#>

$ErrorActionPreference = "Stop"
$script:failures = 0

function Step($msg) { Write-Host "`n$msg" -ForegroundColor Yellow }
function Ok($msg) { Write-Host "   OK $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "   WARN $msg" -ForegroundColor Yellow }
function Bad($msg) { Write-Host "   FAIL $msg" -ForegroundColor Red; $script:failures++ }

Write-Host "Instalando/verificando stack OCR local..." -ForegroundColor Cyan

# El smoke test y los tests importan `app.*`, asi que hay que correr desde la raiz del repo
Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONPATH = (Get-Location).Path

# ---------------------------------------------------------------- Tesseract
Step "1. Tesseract OCR"
$tesseractDir = "C:\Program Files\Tesseract-OCR"
$tesseractExe = Join-Path $tesseractDir "tesseract.exe"

if (-not (Test-Path $tesseractExe)) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id UB-Mannheim.TesseractOCR --silent --accept-package-agreements --accept-source-agreements
        if (Test-Path $tesseractExe) { Ok "Tesseract instalado via winget" }
        else { Bad "winget termino pero $tesseractExe no existe" }
    } else {
        Bad "Tesseract no instalado y no hay winget. Instalar manualmente: https://github.com/UB-Mannheim/tesseract/wiki"
    }
} else {
    Ok "Tesseract ya instalado ($tesseractExe)"
}

# El instalador silencioso NO agrega Tesseract al PATH del usuario
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*Tesseract*") {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";$tesseractDir"), "User")
    Ok "PATH de usuario actualizado con $tesseractDir (abrir terminal nueva para que aplique)"
} else {
    Ok "Tesseract ya esta en el PATH del usuario"
}
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

# El instalador solo trae 'eng'; el app usa lang="spa+eng"
$tessdata = Join-Path $tesseractDir "tessdata"
$spaData = Join-Path $tessdata "spa.traineddata"
if (-not (Test-Path $spaData)) {
    try {
        Invoke-WebRequest -Uri "https://github.com/tesseract-ocr/tessdata_fast/raw/main/spa.traineddata" -OutFile $spaData
        Ok "spa.traineddata descargado ($([math]::Round((Get-Item $spaData).Length/1KB)) KB)"
    } catch {
        Bad "No se pudo descargar spa.traineddata: $($_.Exception.Message)"
    }
} else {
    Ok "spa.traineddata ya presente"
}

if (Test-Path $tesseractExe) {
    $langs = & $tesseractExe --list-langs 2>&1
    foreach ($l in @("eng", "spa")) {
        if ($langs -match "^\s*$l$") { Ok "idioma '$l' disponible" }
        else { Bad "falta el idioma '$l' en $tessdata" }
    }
}

# ---------------------------------------------------------------- Poppler
Step "2. Poppler (pdftoppm, para PDF escaneados)"
$pdftoppm = Get-Command pdftoppm -ErrorAction SilentlyContinue
if (-not $pdftoppm) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id oschwartz10612.Poppler --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        $pdftoppm = Get-Command pdftoppm -ErrorAction SilentlyContinue
        if ($pdftoppm) { Ok "Poppler instalado via winget" }
        else { Bad "Poppler no disponible tras instalarlo" }
    } else {
        Bad "No hay winget. Instalar Poppler y agregarlo al PATH: https://github.com/oschwartz10612/poppler-windows"
    }
} else {
    Ok "pdftoppm disponible ($($pdftoppm.Source))"
}

# ---------------------------------------------------------------- Dependencias Python
Step "3. Dependencias Python (pyproject.toml)"
$needed = @("pytesseract", "cv2", "PIL", "pdf2image", "pypdf")
$prevEAP = $ErrorActionPreference
foreach ($mod in $needed) {
    $ErrorActionPreference = "Continue"
    & python -c "import $mod" 2>$null | Out-Null
    $modExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEAP
    if ($modExit -eq 0) { Ok "import $mod" }
    else { Warn "import $mod fallo -> pip install -e ." }
}

# ---------------------------------------------------------------- Smoke test OCR
Step "4. Smoke test OCR real"
$smokePy = Join-Path $env:TEMP "ocr_smoke_vaucher.py"
$smokeSrc = @'
import glob, os, sys, tempfile
from PIL import Image, ImageDraw
from app.services.ocr_service import OCRService

png = os.path.join(tempfile.gettempdir(), "ocr_smoke.png")
im = Image.new("RGB", (520, 120), "white")
ImageDraw.Draw(im).text((20, 40), "TOTAL 1234.56 COMPROBANTE PAGO", fill="black")
im.save(png)
_, conf, _ = OCRService().extract_text(png)
print("imagen sintetica -> conf=%.1f" % conf)
assert conf >= 40, "confianza baja: %s" % conf

muestras = sorted(glob.glob(os.path.join("..", "docpruebas", "*.jpeg")))
if muestras:
    texto, conf, _ = OCRService().extract_text(muestras[0])
    print("muestra real     -> conf=%.1f | %r" % (conf, texto[:60]))
'@
Set-Content -Path $smokePy -Value $smokeSrc -Encoding UTF8
# En PS 5.1 el stderr nativo con ErrorActionPreference=Stop lanza excepcion: bajarlo solo aqui
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$smokeOut = & python $smokePy 2>&1
$smokeExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($smokeExit -eq 0) {
    $smokeOut | ForEach-Object { Ok $_ }
} else {
    Bad "El smoke test OCR fallo"
    $smokeOut | Select-Object -Last 10 | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }
}
Remove-Item $smokePy -ErrorAction SilentlyContinue

# ---------------------------------------------------------------- Tests
Step "5. Tests del OCR"
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pytest = & python -m pytest tests/test_ocr_service.py -q 2>&1
$pytestExit = $LASTEXITCODE
$ErrorActionPreference = $prevEAP
if ($pytestExit -eq 0) {
    Ok (($pytest | Select-String "passed").Line)
} else {
    Bad "tests/test_ocr_service.py fallo"
    $pytest | Select-Object -Last 15 | ForEach-Object { Write-Host "   $_" -ForegroundColor Red }
}

# ---------------------------------------------------------------- Resumen
Write-Host ""
if ($script:failures -eq 0) {
    Write-Host "Stack OCR listo. Nota: abra una terminal nueva si acaba de instalar Tesseract/Poppler." -ForegroundColor Cyan
} else {
    Write-Host "$($script:failures) verificacion(es) fallida(s)." -ForegroundColor Red
    exit 1
}
