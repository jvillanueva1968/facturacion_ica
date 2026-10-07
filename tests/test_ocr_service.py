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
    assert "valor_total=150000" in h


def test_hallazgos_valor_prefiere_valor_total():
    from app.services.llm_service import hallazgos_preliminares

    texto = "SUBTOTAL: 140.000\nIVA: 10.000\nVALOR TOTAL: $1.500.000,00\n"
    h = hallazgos_preliminares(texto)
    assert "valor_total=1500000" in h


def test_hallazgos_preliminares_vacio():
    from app.services.llm_service import hallazgos_preliminares

    assert hallazgos_preliminares("sin datos utiles") == "(ninguno)"


def test_hallazgos_no_confunde_sfnv03_con_valor():
    from app.services.llm_service import hallazgos_preliminares

    texto = "TOTAL (COP):\nVER: SFNV03_CA3\n$11.450\n"
    h = hallazgos_preliminares(texto)
    assert "valor_total=11450" in h
    assert "valor_total=3" not in h


def test_hallazgos_fecha_con_mes_en_texto():
    from app.services.llm_service import hallazgos_preliminares

    texto = "Monto: $8.800,00 Fecha SEP 18 2026 - 09:22:47\n"
    h = hallazgos_preliminares(texto)
    assert "fecha_transaccion=2026-09-18" in h
    assert "valor_total=8800" in h


def test_hallazgos_ref_corta_redeban():
    from app.services.llm_service import hallazgos_preliminares

    texto = "Pago aprobado\nREF:000000000001045048358\n"
    h = hallazgos_preliminares(texto)
    assert "numero_referencia=000000000001045048358" in h


def test_hallazgos_no_falso_positivo_en_palabras_con_ref():
    from app.services.llm_service import hallazgos_preliminares

    assert hallazgos_preliminares("CACHE REFRESH OK 12345") == "(ninguno)"


def test_normalizar_valor():
    from app.services.llm_service import normalizar_valor

    assert normalizar_valor("$150.000,00") == "150000"
    assert normalizar_valor("1.500.000,50") == "1500000.5"
    assert normalizar_valor("1,500,000.50") == "1500000.5"
    assert normalizar_valor("150000") == "150000"
    assert normalizar_valor("150000.25") == "150000.25"
    assert normalizar_valor(None) == ""
    assert normalizar_valor("") == ""


def test_parse_response_normaliza_montos():
    from app.services.llm_service import LLMService
    from decimal import Decimal

    raw = (
        '{"forma_pago": "CONSIGNACION", "servicios": [{"codigo": "1", "valor": "1.500.000"}],'
        ' "nit_pagador": "800197268", "fecha_transaccion": "2026-09-23",'
        ' "valor_total": "$1.500.000,00", "numero_referencia": "REF1"}'
    )
    datos = LLMService()._parse_response(raw)
    assert datos.valor_total == Decimal("1500000")
    assert datos.servicios[0]["valor"] == "1500000"


def test_parse_response_total_desde_servicios():
    from app.services.llm_service import LLMService
    from decimal import Decimal

    raw = (
        '{"forma_pago": "CONSIGNACION",'
        ' "servicios": [{"codigo": "1", "valor": "100000"}, {"codigo": "2", "valor": "50000"}],'
        ' "nit_pagador": "800197268", "fecha_transaccion": "2026-09-23",'
        ' "valor_total": "", "numero_referencia": "REF1"}'
    )
    datos = LLMService()._parse_response(raw)
    assert datos.valor_total == Decimal("150000")


def _crudo_fecha(fecha: str) -> str:
    return (
        '{"forma_pago": "CONSIGNACION", "servicios": [], "nit_pagador": "800197268",'
        f' "fecha_transaccion": "{fecha}", "valor_total": "150000",'
        ' "numero_referencia": "REF1"}'
    )


def test_parse_response_fecha_iso_con_hora():
    from datetime import date
    from app.services.llm_service import LLMService

    datos = LLMService()._parse_response(_crudo_fecha("2026-09-17T10:33:00"))
    assert datos.fecha_transaccion == date(2026, 9, 17)


def test_parse_response_fecha_ilegible_usa_respaldo_ocr():
    from datetime import date
    from app.services.llm_service import LLMService

    datos = LLMService()._parse_response(
        _crudo_fecha("1185192020"), fecha_fallback=date(2026, 9, 23)
    )
    assert datos.fecha_transaccion == date(2026, 9, 23)


def test_parse_response_fecha_ilegible_sin_respaldo_falla_claro():
    from app.services.llm_service import LLMService

    with pytest.raises(ValueError, match="fecha_transaccion ilegible"):
        LLMService()._parse_response(_crudo_fecha("1185192020"))


def test_datos_extraidos_normaliza_fecha_en_string():
    from datetime import date
    from decimal import Decimal

    from pydantic import ValidationError

    from app.models.schemas import DatosExtraidos

    kwargs = dict(
        forma_pago="CONSIGNACION",
        servicios=[],
        nit_pagador="800197268",
        valor_total=Decimal("150000"),
        numero_referencia="REF1",
    )
    datos = DatosExtraidos(fecha_transaccion="2026-09-17T10:33:00", **kwargs)
    assert datos.fecha_transaccion == date(2026, 9, 17)
    with pytest.raises(ValidationError, match="fecha_transaccion ilegible"):
        DatosExtraidos(fecha_transaccion="1185192020", **kwargs)


def test_extraer_datos_pasa_fecha_del_ocr_como_respaldo(monkeypatch):
    import asyncio
    from datetime import date
    from decimal import Decimal

    from app.models.schemas import DatosExtraidos
    from app.services.llm_service import LLMService

    svc = LLMService()
    svc.provider = "ollama"
    capturado = {}

    async def _fake(prompt, fecha_fallback=None):
        capturado["prompt"] = prompt
        capturado["fecha_fallback"] = fecha_fallback
        return DatosExtraidos(
            forma_pago="CONSIGNACION",
            servicios=[],
            nit_pagador="800197268",
            fecha_transaccion=date(2026, 9, 23),
            valor_total=Decimal("150000"),
            numero_referencia="E2E-UI-777",
        )

    monkeypatch.setattr(svc, "_call_ollama", _fake)
    texto = (
        "COMPROBANTE DE CONSIGNACION\nBANCO: BBVA\nFECHA: 23/09/2026\n"
        "NIT PAGADOR: 8001972684\nVALOR TOTAL: $150.000,00\n"
    )
    datos = asyncio.run(svc.extraer_datos(texto))
    assert datos.fecha_transaccion == date(2026, 9, 23)
    assert capturado["fecha_fallback"] == date(2026, 9, 23)
    assert "fecha_transaccion=2026-09-23" in capturado["prompt"]


def test_run_ocr_ignora_palabras_en_blanco(monkeypatch):
    import numpy as np
    import pytesseract

    from app.services.ocr_service import OCRService

    # Fotos rotadas: Tesseract devuelve "palabras" de espacios con conf 95
    data = {
        "text": ["  ", "\n", ""],
        "conf": [95, 95, 95],
        "block_num": [1, 1, 1],
        "par_num": [1, 1, 1],
        "line_num": [1, 1, 1],
    }
    monkeypatch.setattr(pytesseract, "image_to_data", lambda *a, **k: data)
    svc = OCRService()
    texto, conf = svc._run_ocr(np.zeros((10, 10), dtype=np.uint8), svc.config_psm4)
    assert texto == ""
    assert conf == 0.0


def test_extract_text_foto_rotada_90_recupera_texto(tmp_path):
    from PIL import Image

    receipt = _make_receipt(tmp_path)
    rot = tmp_path / "comprobante_rotado_90.png"
    Image.open(receipt).rotate(90, expand=True).save(rot)

    svc = OCRService(lang="spa", dpi=72)
    texto, confianza, paginas = svc.extract_text(rot)
    assert paginas == 1
    assert confianza > 0
    assert "800197268" in texto.replace(" ", "") or "E2E-UI-777" in texto.replace(" ", "")


def test_paddle_usa_orientacion_de_documento(monkeypatch):
    import sys
    import types

    from app.services.paddle_ocr_service import PaddleOCRService

    capturado = {}

    class _FakePaddleOCR:
        def __init__(self, **kwargs):
            capturado.update(kwargs)

    fake = types.ModuleType("paddleocr")
    fake.PaddleOCR = _FakePaddleOCR
    monkeypatch.setitem(sys.modules, "paddleocr", fake)

    svc = PaddleOCRService()
    svc._get_engine()
    assert capturado["use_doc_orientation_classify"] is True
    assert capturado["engine"] == "onnxruntime"


def test_extraer_datos_bloquea_texto_insuficiente(monkeypatch):
    import asyncio

    from app.services.llm_service import LLMService

    svc = LLMService()
    llamadas = []

    async def _no_llamar(prompt):
        llamadas.append(prompt)
        raise AssertionError("no debe invocar el LLM con texto basura")

    monkeypatch.setattr(svc, "_call_ollama", _no_llamar)
    monkeypatch.setattr(svc, "_call_openrouter", _no_llamar)

    with pytest.raises(ValueError, match="insuficiente"):
        asyncio.run(svc.extraer_datos(""))
    with pytest.raises(ValueError, match="insuficiente"):
        asyncio.run(svc.extraer_datos("   \n  "))
    assert llamadas == []


def test_procesar_documento_falla_si_ocr_vacio(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from app.api import upload as upload_mod

    archivo = tmp_path / "foto_rotada.jpg"
    archivo.write_bytes(b"fake")

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    fake_svc = MagicMock()
    fake_svc.extract_text = MagicMock(return_value=("", 0.0, 1))

    repo = MagicMock()
    repo.update_ocr = AsyncMock()
    repo.mark_failed = AsyncMock()

    eventos = []

    async def _emit(task_id, event, **kw):
        eventos.append((event, kw))

    monkeypatch.setattr(upload_mod, "_servicio_ocr", lambda m: (fake_svc, "tesseract"))
    monkeypatch.setattr(upload_mod, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(upload_mod, "ComprobanteRepo", lambda s: repo)
    monkeypatch.setattr(upload_mod, "emit_stage", _emit)

    asyncio.run(upload_mod.procesar_documento("task-sin-texto", archivo))

    assert not archivo.exists()
    fallidos = [kw for ev, kw in eventos if ev == "failed"]
    assert fallidos, "el procesamiento debe fallar con OCR vacío"
    assert "texto suficiente" in fallidos[0]["mensaje"]
    assert repo.mark_failed.await_count == 1
    assert "texto suficiente" in repo.mark_failed.await_args.args[1]
