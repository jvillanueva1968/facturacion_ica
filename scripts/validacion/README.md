# Validación OCR — Benchmark Tesseract vs PaddleOCR

Plan completo y resultados: [`facturacion_ica/VALIDACION_PADDLEOCR.md`](../../VALIDACION_PADDLEOCR.md).

## Requisitos

- Entorno aislado `validacion_paddle\.venv` (ver `validacion_paddle/README.md`).
- Tesseract 5 + `spa` y Poppler en Windows (`scripts\setup_ocr_windows.ps1`).
- Corpus en `docpruebas/` y/o `scripts/validacion/corpus/` (imágenes/PDF).

## Ejecutar el benchmark

```powershell
cd C:\proyectos\vaucher\facturacion_ica
$env:PYTHONPATH = (Get-Location).Path
C:\proyectos\vaucher\validacion_paddle\.venv\Scripts\python.exe `
    scripts\validacion\bench_ocr.py --engine all
```

Opciones: `--engine tesseract|paddle`, `--limit N`, `--corpus ruta1 ruta2`, `--out DIR`.

## Salidas (`resultados/`)

| Archivo | Contenido |
|---------|-----------|
| `resultados.csv` | 1 fila por imagen×motor: latencia, confianza, campos extraídos |
| `comparacion.csv` | Campos clave motor vs motor (acuerdos/diferencias) |
| `resumen.md` | Latencias, confianza, acuerdo entre motores, accuracy si hay ground truth |
| `textos/` | Texto crudo de cada motor (revisión manual y CER) |

## Ground truth (Fase 1)

Copiar `ground_truth.example.json` → `ground_truth.json` y completar con datos
**verificados a ojo** (solo esos casos se puntúan en CER/accuracy). Mientras no
exista, el benchmark reporta latencia, confianza y acuerdo entre motores.
