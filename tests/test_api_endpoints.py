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
