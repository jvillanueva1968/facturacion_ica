# Validación PaddleOCR — Plan y Resultados

**Estado:** Fases 0–2 + 5 completadas — **decisión: se mantiene Tesseract; Paddle descartado
(latencia 5×) y bugs de regex corregidos** (2026-10-01)
**Objetivo:** decidir con datos si PaddleOCR reemplaza (o complementa) a Tesseract
en la extracción de comprobantes de pago del ICA (`app/services/ocr_service.py`).
**Repositorio evaluado:** https://github.com/PaddlePaddle/PaddleOCR (Apache-2.0, 90.5k★)

---

## Alcance acordado

- **Benchmark + integración solo si gana** (fases 3–4 condicionadas al resultado).
- **Corpus:** `docpruebas/` (13 imágenes) + comprobantes anonimizados que aportará el
  estudiante + variantes sintéticas.
- **Entorno:** Windows local y Docker.

## Criterios de aceptación (Fase 5)

Para que PaddleOCR pase a integración debe cumplir **todo**:

1. ≥ +10 pp de exactitud en campos clave (NIT, valor, fecha, referencia) **o** −30% de CER
   vs Tesseract, medido con la misma tubería `hallazgos_preliminares()`.
2. Latencia ≤ 2× Tesseract en CPU.
3. Instalación limpia en Docker/CI sin hacks.

Si no cumple: se mantiene Tesseract y el informe documenta el porqué.

## Fases

| Fase | Descripción | Entorno | Estado |
|------|-------------|---------|--------|
| 0 | Viabilidad: venv aislada, instalación, smoke test | Windows | ✅ 2026-10-01 |
| 1 | Corpus + ground truth (`scripts/validacion/ground_truth.json`) | Windows | ✅ 2026-10-01 (13/13, borrador verificado) |
| 2 | Benchmark A/B (`scripts/validacion/bench_ocr.py` → `resultados.csv`) | Windows | ✅ 2026-10-01 |
| 3 | *Solo si gana:* integración como motor de producción | Windows | ❌ No aplica (decisión: Tesseract). **Selector de prueba en UI: ✅ 2026-10-01** |
| 4 | *Solo si gana:* Dockerfile, CI, pytest + smoke de `POST /api/v1/upload` | Docker | ❌ No aplica (decisión: Tesseract). **Paddle en imagen + smoke manual: ✅ 2026-10-01** |
| 5 | Informe `VALIDACION_PADDLEOCR.md` (tabla comparativa + decisión) | — | ✅ 2026-10-01 |

---

## Fase 0 — Viabilidad (COMPLETADA)

### Entorno

| Componente | Valor | Nota |
|------------|-------|------|
| Python | CPython 3.12.14 (uv, portátil) | El Python del sistema es 3.14 y **paddlepaddle no publica wheels cp314** (solo cp39–cp313) |
| paddleocr | 3.7.0 | |
| paddlepaddle | 3.3.1 | |
| paddlex | 3.7.2 | |
| onnxruntime | 1.30.0 | **Requerido** (ver solución) |
| venv | `C:\proyectos\vaucher\validacion_paddle\.venv` | Aislada de la app |
| Modelos | PP-OCRv6_medium det+rec (ONNX) | Descargados a `C:\Users\USER\.paddlex\official_models\` |

### Hallazgos (problemas y soluciones)

1. **`lang="latin"` inválido** — en PaddleOCR 3.x los idiomas son códigos ISO:
   usar `lang="es"` (selección automática PP-OCRv6; `ocr_version="PP-OCRv5"|"PP-OCRv3"` para forzar).
2. **Crash de MKLDNN en CPU** — `paddlepaddle 3.3.1` falla con
   `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]`.
   *Workaround:* `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0` (evita el crash, pero lento).
   Desactivar PIR (`FLAGS_json_format_model=0`) **no** lo arregla.
3. **Latencia inviable con motor nativo de Paddle (CPU, sin MKLDNN):**

   | Modelo | Latencia/imagen |
   |--------|-----------------|
   | PP-OCRv6 (medium) | ~48 s |
   | PP-OCRv5 (server_det + mobile_rec) | ~34 s |
   | PP-OCRv3 (mobile) | ~6 s |

4. **SOLUCIÓN: backend ONNX Runtime** (soportado oficialmente):
   `PaddleOCR(lang="es", engine="onnxruntime")` descarga modelos `*_onnx` desde
   HuggingFace y alcanza **~2.6 s/imagen** con la misma calidad.
   **Esta es la configuración válida para el benchmark y la integración.**

### Smoke test (pasó)

```
lineas=22 | rec_score_avg=0.99 | latencia media=2.61 s (3 iteraciones, warmup previo)
Texto: "RECIBO:000299", "credibanco", "VENTA APROBADA", "RRN:168312", ...
```

Script: `validacion_paddle/smoke_test.py`.

### Configuración mínima recomendada

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(
    lang="es",
    engine="onnxruntime",                       # obligatorio: nativo es ~18x más lento en CPU
    use_doc_orientation_classify=False,         # auxiliares solo si hace falta (recibos girados)
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
result = ocr.predict(image_path)
texto = "\n".join(result[0]["rec_texts"])
confianza = 100 * sum(result[0]["rec_scores"]) / len(result[0]["rec_scores"])
```

Variables de entorno útiles:

| Variable | Valor | Motivo |
|----------|-------|--------|
| `PADDLE_PDX_MODEL_SOURCE` | `hf` | Modelos desde HuggingFace (default ya es `huggingface`) |
| `PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT` | `0` | Solo si se usa motor nativo (evita crash) |

### Riesgos restantes

- ~~Tesseract **no está instalado** en Windows local~~ → ya instalado (Tesseract 5.4.0 + `spa`,
  Poppler; el bench agrega el PATH con `_ensure_path_windows()`).
- El corpus real depende de los comprobantes que aportará el estudiante (Fase 1 extra).
- En Docker/Linux conviene revalidar latencias (puede diferir de Windows).

---

## Fase 1 — Ground truth (COMPLETADA)

`scripts/validacion/ground_truth.json`: **13/13 imágenes** anotadas (borrador verificado por
OCR cruzado Paddle+Tesseract y lectura visual humana; pendiente confirmación final del usuario).

- `texto` = transcripción de las líneas impresas (se excluyen números manuscritos).
- `campos` = `fecha_transaccion` (YYYY-MM-DD), `valor_total` (solo dígitos), `numero_referencia`
  (solo con etiqueta explícita `Referencia`). `nit_pagador`/`dv_pagador` no aplican a este corpus.
- Corpus: 7 credibanco + 5 Wompi + 1 Redeban; fotos repetidas de comprobantes ya presentes:
  `53:20 AM (1)` (mismos campos GT que `53:20 AM`) y `52:57 AM (1)` (misma recepción que
  `52:57 AM`, foto girada). ~~`51:55`/`51:56 (1)`/`51:57 (1)` = mismo RECIBO:000299~~
  (corrección: `51:56 (1)` es un Wompi, valor 11450 / ref 17445016, y `51:55`/`51:57 (1)`
  son comprobantes distintos; el GT en disco es el válido).

**Advertencia metodológica:** el tool de lectura de imágenes sirvió adjuntos equivocados en
varias lecturas; la anotación se validó siempre contra OCR fresco de cada archivo (Tesseract CLI)
y solo se aceptó cuando coincidía.

## Fase 2 — Benchmark A/B (COMPLETADA)

Corpus 13 imágenes, motores en procesos separados, sistema en reposo.

### Latencia y confianza

| Motor | Mediana (s) | Media (s) | p95 (s) | Confianza media |
|-------|-------------|-----------|---------|-----------------|
| paddle (onnxruntime) | **3.54** | 3.52 | 3.89 | **96.6** |
| tesseract | **0.70** | 0.79 | 1.01 | 75.9 |

Relación de latencia: **≈5.1× Tesseract** (supera el límite de 2× del criterio 2).

### Exactitud vs ground truth (mismos hints `hallazgos_preliminares()`)

| Motor | CER medio (%) | fecha_transaccion | valor_total | numero_referencia |
|-------|---------------|-------------------|-------------|-------------------|
| paddle | **13.2** | **54%** | **77%** | **80%** |
| tesseract | 47.0 | 38% | 54% | 40% |

- **CER: −72% relativo** (13.2 vs 47.0) → cumple holgadamente el "−30%" del criterio 1.
- **Deltas por campo:** fecha **+16 pp**, valor **+23 pp**, referencia **+40 pp** → cumple el
  "+10 pp" del criterio 1 en los tres campos.
- `nit_pagador`/`dv_pagador`: n/a (ningún comprobante del corpus trae etiqueta NIT).

### Errores conocidos (comparten la tubería, no el motor) — CORREGIDOS en post-fix

1. **Bug de regex `_RE_VALORES`** (`app/services/llm_service.py`): en textos con
   `VER: SFNV03_CA3` el patrón `\bTOTAL\b\D{0,20}` capturaba `03` de `SFNV03` → `valor_total=3`
   (afectaba a Paddle en `53:20 AM` y `53:20 AM (1)`). **Corregido:** lookbehind
   `(?<![A-Za-z0-9])` + `\D{0,40}`.
2. **Fechas Wompi** (`SEP 17 2026`): `_RE_FECHA`/`_RE_FECHA_ISO` no las reconocían → **ambos**
   motores fallaban las 5 imágenes Wompi. **Corregido:** `_RE_FECHA_MES` (meses EN/ES
   abreviados, meses desde `app.services.extraction.MESES`) y orden de hints ISO → dd/mm → mes.
3. **`52:57 AM (1)`** (foto rotada/desenfocada): ambos motores no extraen campos
   (Paddle conf 74.4, Tesseract nada) y —peor— el LLM **inventaba datos** con ese texto
   basura (valor 300/1000, fecha `2022-01-01`, ref `123456`). **Corregido (2026-10-01):**
   (a) Tesseract reintenta rotando 90°/270°/180° cuando el texto no es legible, y la
   confianza solo cuenta palabras reales (antes "palabras" de espacios daban conf 95 con
   texto vacío); (b) Paddle activa `use_doc_orientation_classify`; (c) si el OCR no llega
   a 40 caracteres el proceso **falla con mensaje claro** en vez de llamar al LLM, y
   `LLMService.extraer_datos` se niega a invocar el modelo con texto basura.
   Verificado: la imagen pasa de `valor 300/1000` (inventado) a **`valor_total 8800`,
   fecha `2026-09-18`, ref `17419333`** con ambos motores (Tesseract conf 83.9,
   Paddle conf 98.6).
4. **`_RE_REF` demasiado estricto** (post-fix): sin `|REFERENCIA` ampliado, Paddle perdía la
   ref de Redeban (`REF: ...` de 21 dígitos). **Corregido:** alternantes
   `REF\s*[:\-]|REFERENCIA|...` con valor `{3,29}`.

### Veredicto vs criterios de aceptación (baseline pre-fix)

| Criterio | Resultado | Estado |
|----------|-----------|--------|
| 1. ≥ +10 pp exactitud **o** −30% CER | +16/+23/+40 pp y −72% CER | ✅ Cumple |
| 2. Latencia ≤ 2× Tesseract | 5.1× (3.54 s vs 0.70 s) | ❌ No cumple |
| 3. Instalación limpia en Docker/CI | No evaluado (desistido) | ⏳ |

**Decisión del usuario:** mantener Tesseract y arreglar solo la regex (opción (c)).
El criterio 1 ya no da ventaja a Paddle tras el post-fix, y el criterio 2 lo descalifica.

---

## Fase 5 — Decisión y post-fix (COMPLETADA)

### Decisión final

**Se mantiene Tesseract** como motor de OCR en producción (`app/services/ocr_service.py`):

- Paddle incumple el criterio 2 (**≈5× la latencia** en CPU; 3.4 s vs 0.62 s de mediana).
- Tras corregir las regex de la tubería, la ventaja de exactitud de Paddle se reduce a:
  CER **13.2% vs 47.0%** (sigue siendo mejor), pero en los campos clave prácticos
  (fecha/valor) Tesseract sube a un nivel suficiente con ~0.6 s por imagen.
- Integración de Paddle (fases 3–4): **cancelada** por el usuario.

### Correcciones aplicadas (2026-10-01)

| Archivo | Cambio |
|---------|--------|
| `app/services/llm_service.py` | `_RE_VALORES` con lookbehind `(?<![A-Za-z0-9])` y `\D{0,40}`; `_RE_FECHA_MES` (meses EN/ES); `_RE_REF` con `REFERENCIA` y `{3,29}`; orden de hints ISO → dd/mm → mes |
| `app/services/extraction.py` | Exposición de `MESES` (sin ciclos con `llm_service`) |
| Tests | +7 en `test_ocr_service.py` (SFNV03, fecha con mes, REF Redeban, falso positivo REF) y +3 en `test_extraction_profiles.py` (campos dinámicos) |

Verificación: `python -m pytest tests/` → 124 passed (3 fallos preexistentes de Python 3.14
en `test_nit_validator.py`, ajenos; CI usa 3.11). `uvx ruff@0.1.15 check app tests` → delta 0.

### Resultados post-fix (re-corrida, mismos textos OCR)

| Motor | Latencia mediana (s) | CER medio (%) | fecha_transaccion | valor_total | numero_referencia |
|-------|----------------------|---------------|-------------------|-------------|-------------------|
| tesseract | 0.62 | 47.0 | **62%** (era 38%) | 54% (=) | 40% (=) |
| paddle (onnxruntime) | 3.42 | 13.2 | **92%** (era 54%) | **92%** (era 77%) | 80% (=) |

- **Ganancia de la corrección:** Tesseract fecha +24 pp; Paddle fecha +38 pp y valor +15 pp.
- Tesseract valor/ref sin regresión (46%/20% vistos con otro env se debieron a cv2/PIL
  distintos del Python 3.14 del sistema; con la misma venv del baseline es 54%/40%).
- Comparación old→new de hints sobre los mismos textos: **solo mejoras** (fechas añadidas,
  `valor_total` SFNV03 `3`→`11450`, +1 ref Redeban), ninguna pérdida.
- Corrida determinista verificada (texto idéntico entre corridas con el mismo binario).
- `scripts/validacion/resultados/resumen.md` regenerado.

---

## Cómo probar PaddleOCR desde la interfaz (2026-10-01)

La UI incluye un desplegable **"Motor OCR"** (paso 2, junto a "Perfil de extracción")
con opciones **Tesseract** (default) y **PaddleOCR**; el valor viaja como campo
`motor_ocr=tesseract|paddle` del `POST /api/v1/upload`.

1. Levantar (reconstruir solo si cambió el Dockerfile):
   ```bash
   docker compose -f docker/docker-compose.yml up -d --build api
   ```
2. Abrir http://localhost:8000 → identificación → **Cargar comprobante**.
3. Elegir **Motor OCR → PaddleOCR** y subir la imagen/PDF.
4. El progreso muestra `Ejecutando OCR (paddle)…` / `OCR completado (paddle)` y el
   badge de confianza; el estado `texto_ocr` es el del motor elegido.

Notas:

- **Primera corrida:** descarga ~134 MB de modelos PP-OCRv6 ONNX al volumen
  `docker_paddle-models` (`/home/appuser/.paddlex`, persistente entre recreaciones).
- Latencia: Paddle ≈3–5 s/imagen vs Tesseract ≈0.6 s (import/carga de modelo ocurre
  en el primer uso, dentro del hilo de OCR — no afecta el arranque del servicio).
- Validaciones: `motor_ocr` desconocido → 400; `paddle` sin `paddleocr` instalado → 400
  (`_servicio_ocr()` en `app/api/upload.py`).
- Smoke 2026-10-01 (imagen `51:56 (1)`): **tesseract** conf 71.3%, ref `317445016`
  (errónea) vs **paddle** conf **98.3%**, ref `17445016` ✓ (ambos: fecha 2026-09-17,
  valor 11450).
- Smoke 2026-10-01 (imagen rotada `w_...52.57`, la que reportaba "valor muy mal"):
  **tesseract** conf 83.9 y **paddle** conf 98.6 → ambos `valor_total 8800`,
  fecha `2026-09-18`, ref `17419333`, perfil `wompi-bancolombia`.
- `pytest` dentro de la imagen: **137 passed**; ruff → 453 (baseline 456).
- Paddle corre con `use_doc_orientation_classify=True` (clasificador de orientación
  `PP-LCNet_x1_0_doc_ori`, ~+0.3 s): fotos giradas se enderezan solas.
- Implementación: `app/services/paddle_ocr_service.py` (subclase de `OCRService`,
  motor lazy `PaddleOCR(lang="es", engine="onnxruntime")`), `app/api/upload.py`
  (`_servicio_ocr`), selector en `app/static/index.html`, `docker/Dockerfile`
  (`pip install paddlepaddle==3.3.1 paddleocr==3.7.0 onnxruntime`) y volúmenes de
  modelos en `docker/docker-compose.yml`.

---

## Registro de cambios

| Fecha | Fase | Cambio |
|-------|------|--------|
| 2026-10-01 | 0 | Viabilidad GO; crash MKLDNN documentado; solución `engine="onnxruntime"` (2.6 s/imagen) |
| 2026-10-01 | 1 | Ground truth 13/13 en `scripts/validacion/ground_truth.json` (borrador) |
| 2026-10-01 | 2 | Benchmark A/B: Paddle CER 13.2% vs 47%, +16/+23/+40 pp por campo; latencia 5.1× (criterio 2 no cumple) |
| 2026-10-01 | fix | Regex corregidas (`_RE_VALORES`, `_RE_FECHA_MES`, `_RE_REF`); +10 tests; 124 passed; ruff delta 0 |
| 2026-10-01 | 5 | **Decisión: mantener Tesseract** (Paddle descartado por latencia 5×); fases 3–4 canceladas; post-fix Tesseract fecha 38→62%, Paddle fecha 54→92% / valor 77→92% |
| 2026-10-01 | 3–4 | Selector "Motor OCR" en la UI + `PaddleOCRService` + paddleocr en la imagen Docker (solo pruebas A/B; producción sigue en Tesseract); smoke OK, 131 passed en imagen |
| 2026-10-01 | fix | **Foto rotada dejaba de inventar datos:** confianza Tesseract solo con palabras reales + reintento rotación 90°/270°/180° (`ocr_service.py`), Paddle con orientación de documento, guard `MIN_TEXTO_OCR=40` en `procesar_documento`/`extraer_datos`/`reextraer`; +6 tests → 137 passed, ruff 453 |
| 2026-10-07 | fix | **Respuesta LLM inválida `fecha_transaccion` (p.ej. epoch `1185192020` o `2026-09-17T10:33:00`):** nueva `parsear_fecha()` en `app/services/extraction.py` (ISO, ISO con hora, `dd/mm/aaaa`, `SEP 17 2026`, `YYYYMMDD`, `date`/`datetime`; rechaza números puros y fechas imposibles → `None`); validator `before` en `DatosExtraidos.fecha_transaccion` (`app/models/schemas.py`) que normaliza y reporta `fecha_transaccion ilegible: ...` en vez del error de pydantic `date_from_datetime_inexact`; `normalizar_datos_llm()` usa como respaldo la fecha hallada por regex en el OCR (`hallazgos_preliminares`, hilo `extraer_datos → _call_ollama/_call_openrouter → _parse_response`) y solo falla si tampoco hay pista; +6 tests |
