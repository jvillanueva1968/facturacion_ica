from pathlib import Path

import pytest

from app.services.ocr_service import OCRService


def _make_receipt(tmp_path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    W, H = 640, 420
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
        bold = ImageFont.truetype("arialbd.ttf", 22)
        small = ImageFont.truetype("arial.ttf", 14)
    except Exception:
        font = bold = small = ImageFont.load_default()

    d.rectangle([10, 10, W - 10, H - 10], outline="black", width=2)
    d.text((30, 30), "COMPROBANTE DE CONSIGNACION", fill="black", font=bold)
    d.text((30, 70), "BANCO: BBVA", fill="black", font=font)
    d.text((30, 100), "FECHA: 2026-09-23", fill="black", font=font)
    d.text((30, 130), "NIT PAGADOR: 8001972684", fill="black", font=font)
    d.text((30, 160), "NOMBRE: EMPRESA PRUEBA SAS", fill="black", font=font)
    d.text((30, 190), "REFERENCIA: E2E-UI-777", fill="black", font=font)
    d.text((30, 220), "FORMA PAGO: CONSIGNACION", fill="black", font=font)
    d.text((30, 250), "SERVICIO: ICA-1234 Droso de patente", fill="black", font=font)
    d.text((30, 280), "VALOR TOTAL: 150000", fill="black", font=bold)
    d.text((30, 330), "Documento generado para pruebas E2E", fill="gray", font=small)

    out = tmp_path / "comprobante_e2e.png"
    img.save(out)
    return out


def test_extract_text_comprobante_generado(tmp_path):
    receipt = _make_receipt(tmp_path)
    svc = OCRService(lang="spa", dpi=72)
    texto, confianza, paginas = svc.extract_text(receipt)

    assert paginas == 1
    assert confianza > 0
    assert texto
    upper = texto.upper()
    assert "CONSIGNACION" in upper or "COMPROBANTE" in upper
    assert "800197268" in texto.replace(" ", "") or "E2E-UI-777" in texto.replace(" ", "")


def test_extract_text_tipos(tmp_path):
    receipt = _make_receipt(tmp_path)
    svc = OCRService(lang="spa")
    texto, confianza, paginas = svc.extract_text(receipt)
    assert isinstance(texto, str)
    assert isinstance(confianza, float)
    assert isinstance(paginas, int)


def test_preprocess_variants():
    import numpy as np
    from app.services.ocr_service import OCRService

    svc = OCRService()
    img = np.full((400, 600, 3), 240, dtype=np.uint8)
    img[100:120, 50:550] = 30
    v1 = svc.preprocess_image(img, variant=1)
    v2 = svc.preprocess_image(img, variant=2)
    assert v1.shape == v2.shape
    assert v1.dtype == v2.dtype


def _minimal_pdf_with_text(path: Path) -> Path:
    content = b"BT /F1 18 Tf 50 700 Td (COMPROBANTE NIT 8001972684 VALOR TOTAL 150000.00) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    ).encode()
    path.write_bytes(out)
    return path


def test_pdf_con_capa_de_texto_sin_ocr(tmp_path):
    from app.services.ocr_service import OCRService

    pdf = _minimal_pdf_with_text(tmp_path / "texto.pdf")
    svc = OCRService(lang="spa")
    texto, confianza, paginas = svc.extract_text(pdf)
    assert paginas == 1
    assert confianza == 100.0
    assert "8001972684" in texto.replace(" ", "")


def test_hallazgos_preliminares():
    from app.services.llm_service import hallazgos_preliminares

    texto = (
        "BANCO BBVA\nNIT: 800197268-4\nFECHA: 23/09/2026\n"
        "REFERENCIA: E2E-UI-777\nVALOR TOTAL: $150.000,00\n"
    )
    h = hallazgos_preliminares(texto)
    assert "nit_pagador=800197268" in h
    assert "dv_pagador=4" in h
    assert "fecha_transaccion=2026-09-23" in h
    assert "numero_referencia=E2E-UI-777" in h


def test_hallazgos_preliminares_vacio():
    from app.services.llm_service import hallazgos_preliminares

    assert hallazgos_preliminares("sin datos utiles") == "(ninguno)"
