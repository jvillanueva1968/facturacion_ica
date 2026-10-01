"""Benchmark A/B: Tesseract (OCRService actual) vs PaddleOCR (onnxruntime).

Uso (desde la raíz de facturacion_ica, con la venv de validacion_paddle):

    set PYTHONPATH=<ruta>\\facturacion_ica
    .venv\\Scripts\\python.exe scripts\\validacion\\bench_ocr.py --engine all

Salidas en scripts/validacion/resultados/:
    resultados.csv   — una fila por imagen×motor (latencia, confianza, campos)
    comparacion.csv  — campos clave motor vs motor (borrador de ground truth)
    resumen.md       — agregados + accuracy/CER si existe ground_truth.json
    textos/<motor>__<imagen>.txt — texto crudo por motor (para revisión/CER)
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORPUS_DEFAULT = [REPO.parent / "docpruebas", Path(__file__).parent / "corpus"]
OUT_DEFAULT = Path(__file__).parent / "resultados"
GROUND_TRUTH = Path(__file__).parent / "ground_truth.json"
CAMPOS = ("nit_pagador", "dv_pagador", "fecha_transaccion", "valor_total", "numero_referencia")
_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".pdf"}

os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "hf")
sys.path.insert(0, str(REPO))


def _ensure_path_windows() -> None:
    """Agrega Tesseract/Poppler al PATH si faltan (el instalador no siempre lo hace)."""
    extra = [r"C:\Program Files\Tesseract-OCR"]
    extra += sorted(
        str(p)
        for p in Path(os.environ.get("LOCALAPPDATA", "")).glob(
            "Microsoft/WinGet/Packages/oschwartz10612.Poppler_*/**/Library/bin"
        )
    )
    path = os.environ.get("PATH", "")
    missing = [d for d in extra if Path(d).is_dir() and d not in path]
    if missing:
        os.environ["PATH"] = path + os.pathsep + os.pathsep.join(missing)


def _parse_hints(hints: str) -> dict:
    campos: dict = {}
    if not hints or hints == "(ninguno)":
        return campos
    for line in hints.splitlines():
        for key, val in re.findall(r"([a-z_]+)=([^,]+)", line):
            campos[key] = val.strip()
    return campos


def build_corpus(dirs: list[Path], limit: int | None) -> list[Path]:
    files: list[Path] = []
    for d in dirs:
        if d.is_dir():
            files += sorted(p for p in d.rglob("*") if p.suffix.lower() in _IMG_EXT)
    if limit:
        files = files[:limit]
    return files


class TesseractEngine:
    name = "tesseract"

    def __init__(self):
        from app.services.ocr_service import OCRService
        from app.services.llm_service import hallazgos_preliminares

        self.hints = hallazgos_preliminares
        self.svc = OCRService(tesseract_cmd=str(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")))

    def run(self, path: Path) -> tuple[str, float, float]:
        t0 = time.perf_counter()
        texto, conf, _ = self.svc.extract_text(path)
        return texto, conf, time.perf_counter() - t0


class PaddleEngine:
    name = "paddle"

    def __init__(self):
        from paddleocr import PaddleOCR
        from app.services.llm_service import hallazgos_preliminares

        self.hints = hallazgos_preliminares
        self.ocr = PaddleOCR(
            lang="es",
            engine="onnxruntime",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def run(self, path: Path) -> tuple[str, float, float]:
        t0 = time.perf_counter()
        result = self.ocr.predict(str(path))
        texto, scores = [], []
        for page in result:
            texto.extend(page.get("rec_texts", []))
            scores.extend(page.get("rec_scores", []))
        conf = 100.0 * sum(scores) / len(scores) if scores else 0.0
        return "\n".join(texto), conf, time.perf_counter() - t0


def _load_ground_truth() -> dict:
    import json

    if GROUND_TRUTH.is_file():
        return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    return {}


def _cer(ref: str, hyp: str) -> float | None:
    if not ref.strip():
        return None
    from rapidfuzz.distance import Levenshtein

    return 100.0 * Levenshtein.normalized_distance(ref, hyp)


def _load_existing(out: Path) -> list[dict]:
    """Filas previas de resultados.csv (para acumular por motor en procesos separados)."""
    path = out / "resultados.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh)]


def _merge_rows(old: list[dict], new: list[dict]) -> list[dict]:
    key = {(r.get("imagen"), r.get("engine")): r for r in old}
    key.update({(r.get("imagen"), r.get("engine")): r for r in new})
    return list(key.values())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", choices=["all", "tesseract", "paddle"], default="all")
    ap.add_argument("--corpus", nargs="*", type=Path, default=CORPUS_DEFAULT)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    _ensure_path_windows()
    files = build_corpus(args.corpus, args.limit)
    if not files:
        print("FAIL: corpus vacío", file=sys.stderr)
        return 1
    print(f"Corpus: {len(files)} archivos")

    engines = []
    if args.engine in ("all", "tesseract"):
        engines.append(TesseractEngine())
    if args.engine in ("all", "paddle"):
        engines.append(PaddleEngine())

    gt = _load_ground_truth()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "textos").mkdir(exist_ok=True)

    rows: list[dict] = []
    for eng in engines:
        for i, path in enumerate(files):
            try:
                texto, conf, secs = eng.run(path)
                if i == 0:  # warmup: la primera corrida incluye carga de modelos/tessdata
                    texto, conf, secs = eng.run(path)
                    print(f"[{eng.name}] warmup incluido en primera imagen ({path.name})")
            except Exception as exc:  # noqa: BLE001 — un fallo no debe matar el benchmark
                print(f"[{eng.name}] ERROR {path.name}: {exc}", file=sys.stderr)
                rows.append({"imagen": path.name, "engine": eng.name, "error": str(exc)})
                continue
            campos = _parse_hints(eng.hints(texto))
            (args.out / "textos" / f"{eng.name}__{path.stem}.txt").write_text(texto, encoding="utf-8")
            row = {
                "imagen": path.name,
                "engine": eng.name,
                "segundos": round(secs, 3),
                "confianza": round(conf, 2),
                "lineas": texto.count("\n") + 1 if texto else 0,
                **campos,
            }
            rows.append(row)
            print(f"[{eng.name}] {path.name}: {secs:.2f}s conf={conf:.1f} campos={list(campos)}")

    # ------------------------------------------------- merge + CSVs + resumen
    merged = _merge_rows(_load_existing(args.out), rows)
    fieldnames = ["imagen", "engine", "segundos", "confianza", "lineas", *CAMPOS, "error"]
    with (args.out / "resultados.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)

    by_image: dict[str, dict] = {}
    for r in merged:
        if not r.get("error"):
            by_image.setdefault(r["imagen"], {})[r["engine"]] = r
    with (args.out / "comparacion.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["imagen", "campo", "tesseract", "paddle", "coincide"])
        for img, engs in sorted(by_image.items()):
            if len(engs) < 2:
                continue
            for campo in CAMPOS:
                a = engs.get("tesseract", {}).get(campo, "")
                b = engs.get("paddle", {}).get(campo, "")
                if a or b:
                    w.writerow([img, campo, a, b, "SI" if a == b else "NO"])

    engine_names = sorted({r["engine"] for r in merged if r.get("engine")})
    lines = ["# Resumen benchmark OCR (Tesseract vs PaddleOCR)", ""]
    lines.append(f"Corpus: {len(files)} archivos | motores: {engine_names} (procesos separados)")
    lines.append("")
    lines.append("| Motor | n | Latencia mediana (s) | media (s) | p95 (s) | Confianza media |")
    lines.append("|-------|---|----------------------|-----------|---------|-----------------|")
    for name in engine_names:
        vals = sorted(
            float(r["segundos"]) for r in merged if r.get("engine") == name and r.get("segundos")
        )
        confs = [
            float(r["confianza"]) for r in merged if r.get("engine") == name and r.get("confianza")
        ]
        if vals:
            p50 = vals[len(vals) // 2]
            p95 = vals[max(0, int(len(vals) * 0.95) - 1)]
            conf = f"{sum(confs)/len(confs):.1f}" if confs else "n/a"
            lines.append(
                f"| {name} | {len(vals)} | {p50:.2f} | {sum(vals)/len(vals):.2f} | {p95:.2f} | {conf} |"
            )
    lines.append("")

    pairs = sum(1 for e in by_image.values() if len(e) == 2)
    acuerdos = {
        campo: sum(
            1
            for e in by_image.values()
            if len(e) == 2 and (e["tesseract"].get(campo) or e["paddle"].get(campo))
            and e["tesseract"].get(campo) == e["paddle"].get(campo)
        )
        for campo in CAMPOS
    }
    presentes = {
        campo: sum(
            1
            for e in by_image.values()
            if len(e) == 2 and (e["tesseract"].get(campo) or e["paddle"].get(campo))
        )
        for campo in CAMPOS
    }
    lines.append(f"## Acuerdo entre motores ({pairs} imágenes con ambos)")
    lines.append("")
    lines.append("| Campo | Coinciden / Presentes | % acuerdo |")
    lines.append("|-------|----------------------|-----------|")
    for campo in CAMPOS:
        p = presentes[campo]
        if p:
            lines.append(f"| {campo} | {acuerdos[campo]}/{p} | {100*acuerdos[campo]/p:.0f}% |")
    lines.append("")

    if gt:
        lines.append("## Accuracy vs ground truth")
        lines.append("")
        lines.append("| Motor | CER medio (%) |" + "".join(f"| {c} " for c in CAMPOS) + "|")
        lines.append("|-------|---------------|" + "".join("|---" for _ in CAMPOS) + "|")
        for name in engine_names:
            cers, aciertos, totales = [], {c: 0 for c in CAMPOS}, {c: 0 for c in CAMPOS}
            for r in merged:
                if r.get("engine") != name:
                    continue
                ref = gt.get(r["imagen"])
                if not ref:
                    continue
                hyp = (args.out / "textos" / f"{name}__{Path(r['imagen']).stem}.txt")
                c = _cer(ref.get("texto", ""), hyp.read_text(encoding="utf-8") if hyp.is_file() else "")
                if c is not None:
                    cers.append(c)
                for campo in CAMPOS:
                    if ref.get("campos", {}).get(campo):
                        totales[campo] += 1
                        if str(ref["campos"][campo]) == str(r.get(campo, "")):
                            aciertos[campo] += 1
            acc = "".join(
                f"| {100*aciertos[c]/totales[c]:.0f}% " if totales[c] else "| n/a "
                for c in CAMPOS
            )
            cer = f"{sum(cers)/len(cers):.1f}" if cers else "n/a"
            lines.append(f"| {name} | {cer} |{acc}|")
        lines.append("")
    else:
        lines.append("_Sin ground_truth.json: faltan CER y accuracy por campo (Fase 1)._")
        lines.append("")

    (args.out / "resumen.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nOK: resultados en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
