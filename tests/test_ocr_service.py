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
