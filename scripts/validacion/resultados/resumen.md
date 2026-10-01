# Resumen benchmark OCR (Tesseract vs PaddleOCR)

Corpus: 13 archivos | motores: ['paddle', 'tesseract'] (procesos separados)

| Motor | n | Latencia mediana (s) | media (s) | p95 (s) | Confianza media |
|-------|---|----------------------|-----------|---------|-----------------|
| paddle | 13 | 3.42 | 3.64 | 3.94 | 96.6 |
| tesseract | 13 | 0.62 | 0.67 | 0.70 | 75.9 |

## Acuerdo entre motores (13 imágenes con ambos)

| Campo | Coinciden / Presentes | % acuerdo |
|-------|----------------------|-----------|
| fecha_transaccion | 8/12 | 67% |
| valor_total | 7/12 | 58% |
| numero_referencia | 2/5 | 40% |

## Accuracy vs ground truth

| Motor | CER medio (%) || nit_pagador | dv_pagador | fecha_transaccion | valor_total | numero_referencia |
|-------|---------------||---|---|---|---|---|
| paddle | 13.2 || n/a | n/a | 92% | 92% | 80% |
| tesseract | 47.0 || n/a | n/a | 62% | 54% | 40% |
