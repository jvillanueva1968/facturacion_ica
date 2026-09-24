from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "database_connected" in body


def test_root_serves_ui():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Facturación" in r.text or "app()" in r.text


def test_calcular_dv():
    r = client.get("/api/v1/nit/calcular-dv/800197268")
    assert r.status_code == 200
    assert r.json()["dv"] == "4"


def test_nit_validar_dv_ok():
    r = client.post("/api/v1/nit/validar", json={"nit": "800197268", "dv": "4"})
    assert r.status_code == 200
    assert r.json()["valido"] is True
    assert r.json()["mensaje"] == "DV coincide"


def test_nit_validar_dv_embebido():
    r = client.post("/api/v1/nit/validar", json={"nit": "8001972684", "dv": "4"})
    assert r.status_code == 200
    body = r.json()
    assert body["nit"] == "800197268"
    assert body["valido"] is True


def test_nit_validar_vacio():
    r = client.post("/api/v1/nit/validar", json={"nit": ""})
    assert r.status_code == 400


def test_auth_jwt_emite_token():
    r = client.post("/api/v1/auth/jwt", params={"subject": "tester"})
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert body["sub"] == "tester"


def test_upload_rechaza_tipo():
    r = client.post(
        "/api/v1/upload",
        files={"file": ("mal.txt", b"hola", "text/plain")},
    )
    # 400 tipo no permitido, o 401 si auth forzado — nunca 500
    assert r.status_code in (400, 401, 413, 429)


def test_status_uuid_invalido_es_404():
    r = client.get("/api/v1/status/loadtest-none")
    assert r.status_code == 404


def test_status_uuid_desconocido_es_404():
    r = client.get("/api/v1/status/00000000-0000-4000-8000-000000000000")
    assert r.status_code == 404


def test_comprobante_uuid_invalido_es_404():
    r = client.get("/api/v1/comprobantes/not-a-uuid")
    assert r.status_code == 404


def test_pdf_demo_genera_bytes_validos():
    import base64

    from app.services.pdf_service import demo_pdf_base64

    b64 = demo_pdf_base64(
        numero_factura="DEMO-TEST1",
        cufe="C1",
        nit="800197268-4",
        razon_social="EMPRESA (X)",
        valor_total="150000",
    )
    raw = base64.b64decode(b64)
    assert raw.startswith(b"%PDF-1.4")
    assert b"DEMO-TEST1" in raw
    assert raw.rstrip().endswith(b"%%EOF")


def test_imprimir_demo_ok_y_pdf_download():
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.db.session import get_db

    fake_row = MagicMock(
        id="22222222-3333-4444-5555-666666666666",
        numero_factura="DEMO-PDF-1",
        cufe="CUFE-PDF",
        nit_pagador="800197268",
        dv_pagador="4",
        nombre_razon_social="PDF TEST",
        valor_total="1000",
        pdf_base64=None,
    )
    fake_repo = MagicMock()
    fake_repo.get_by_numero = AsyncMock(return_value=fake_row)
    fake_repo.save_pdf = AsyncMock(return_value=fake_row)

    async def _fake_db():
        yield MagicMock()

    with patch("app.api.facturar.FacturaRepo", lambda session: fake_repo):
        app.dependency_overrides[get_db] = _fake_db
        try:
            r = client.post("/api/v1/facturar/imprimir/DEMO-PDF-1")
            assert r.status_code == 200
            body = r.json()
            assert body["success"] is True
            assert body["pdf_base64"]
            fake_repo.save_pdf.assert_awaited()

            fake_row.pdf_base64 = body["pdf_base64"]
            r2 = client.get("/api/v1/facturar/DEMO-PDF-1/pdf")
            assert r2.status_code == 200
            assert r2.headers["content-type"].startswith("application/pdf")
            assert r2.content.startswith(b"%PDF")
        finally:
            app.dependency_overrides.pop(get_db, None)
