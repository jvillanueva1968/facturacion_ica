import uuid

from fastapi.testclient import TestClient

from app.core import deps
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app

client = TestClient(app)

VALID_BODY = {
    "codigo": "",
    "nombre": "Perfil de prueba",
    "detect_keywords": ["prueba-test"],
    "campos": {
        "valor_total": {"regex": r"TOTAL\s*:\s*\$?\s*([\d.,]+)", "requerido": True, "orden": 1},
        "fecha": {"regex": r"(\d{2}/\d{2}/\d{4})", "requerido": True, "orden": 2},
    },
    "llm_respaldo": True,
    "activo": True,
    "es_default": False,
}


def _headers(roles):
    return {"Authorization": f"Bearer {create_access_token('tester', roles=roles)}"}


def _body(**campos):
    body = dict(VALID_BODY)
    body["codigo"] = f"test-{uuid.uuid4().hex[:8]}"
    body.update(campos)
    return body


def test_lista_perfiles_incluye_seed():
    with client as c:
        r = c.get("/api/v1/perfiles")
        assert r.status_code == 200, r.text
        perfiles = r.json()
        codigos = {p["codigo"] for p in perfiles}
        assert "credibanco-pos" in codigos
        assert "wompi-bancolombia" in codigos
        assert "redeban-bancolombia" in codigos
        defaults = [p for p in perfiles if p["es_default"]]
        assert len(defaults) == 1


def test_crear_actualizar_eliminar_perfil():
    body = _body()
    with client as c:
        r = c.post("/api/v1/perfiles", json=body)
        assert r.status_code == 201, r.text
        perfil = r.json()
        assert perfil["codigo"] == body["codigo"]
        assert perfil["campos"]["valor_total"]["requerido"] is True

        r = c.put(f"/api/v1/perfiles/{perfil['id']}", json=dict(body, nombre="Renombrado"))
        assert r.status_code == 200, r.text
        assert r.json()["nombre"] == "Renombrado"

        r = c.delete(f"/api/v1/perfiles/{perfil['id']}")
        assert r.status_code == 204

        r = c.get("/api/v1/perfiles")
        assert body["codigo"] not in {p["codigo"] for p in r.json()}


def test_crear_perfil_codigo_invalido():
    with client as c:
        r = c.post("/api/v1/perfiles", json=_body(codigo="Codigo INVALIDO!"))
        assert r.status_code == 400


def test_crear_perfil_regex_invalida():
    with client as c:
        r = c.post("/api/v1/perfiles", json=_body(campos={
            "valor_total": {"regex": "([unclosed", "requerido": True},
        }))
        assert r.status_code == 400
        assert "Regex" in r.json()["detail"]


def test_crear_perfil_campo_desconocido():
    with client as c:
        r = c.post("/api/v1/perfiles", json=_body(campos={
            "campo_inventado": {"regex": "X"},
        }))
        assert r.status_code == 400
        assert "campo_inventado" in r.json()["detail"]


def test_crear_perfil_duplicado():
    body = _body()
    with client as c:
        r = c.post("/api/v1/perfiles", json=body)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        try:
            r = c.post("/api/v1/perfiles", json=body)
            assert r.status_code == 409
        finally:
            c.delete(f"/api/v1/perfiles/{pid}")


def test_marcar_default_y_restaurar():
    body = _body()
    with client as c:
        r = c.post("/api/v1/perfiles", json=body)
        assert r.status_code == 201, r.text
        pid = r.json()["id"]
        try:
            r = c.put(f"/api/v1/perfiles/{pid}/default")
            assert r.status_code == 200, r.text
            assert r.json()["es_default"] is True

            r = c.get("/api/v1/perfiles")
            defaults = [p for p in r.json() if p["es_default"]]
            assert len(defaults) == 1 and defaults[0]["id"] == pid
        finally:
            r = c.get("/api/v1/perfiles")
            original = next(p for p in r.json() if p["codigo"] == "credibanco-pos")
            c.put(f"/api/v1/perfiles/{original['id']}/default")
            c.delete(f"/api/v1/perfiles/{pid}")


def test_eliminar_perfil_inexistente():
    with client as c:
        r = c.delete("/api/v1/perfiles/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


def test_rbac_perfiles(monkeypatch):
    monkeypatch.setattr(deps, "auth_enabled", lambda: True)
    body = _body()
    with client as c:
        r = c.get("/api/v1/perfiles", headers=_headers(["viewer"]))
        assert r.status_code == 200

        r = c.post("/api/v1/perfiles", json=body, headers=_headers(["viewer"]))
        assert r.status_code == 403
        r = c.post("/api/v1/perfiles", json=body, headers=_headers(["operator"]))
        assert r.status_code == 403

        r = c.post("/api/v1/perfiles", json=body, headers=_headers(["admin"]))
        assert r.status_code == 201, r.text
        c.delete(
            f"/api/v1/perfiles/{r.json()['id']}",
            headers=_headers(["admin"]),
        )


def test_seed_perfiles_idempotente():
    with client as c:
        r = c.post("/api/v1/perfiles/seed")
        assert r.status_code == 201, r.text
        assert r.json() == []


def test_catalogo_campos():
    with client as c:
        r = c.get("/api/v1/perfiles/catalogo/campos")
        assert r.status_code == 200
        assert "valor_total" in r.json()["campos"]
        assert "fecha" in r.json()["campos"]


def test_reextraer_sin_perfil_detecta_y_fusiona(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from app.api import upload as upload_mod
    from app.services.extraction import PerfilExtraccionData

    task_id = str(uuid.uuid4())
    perfil = PerfilExtraccionData(
        id="p-credibanco",
        codigo="credibanco-pos",
        nombre="Credibanco POS",
        detect_keywords=["credibanco"],
        campos={
            "valor_total": {"regex": r"VLR\.?\s*NETO\s*[:\s]*\$?\s*([\d.,]+)", "requerido": True, "orden": 1},
            "banco": {"literal": "CREDIBANCO", "requerido": False, "orden": 2},
        },
        llm_respaldo=True,
        activo=True,
        es_default=True,
    )
    row = MagicMock()
    row.task_id = task_id
    row.status = "completed"
    row.texto_ocr = "credibanco\nVENTA APROBADA\nVLR. NETO: $20.259\nRECIBO: 000265"
    row.datos_extraidos = {
        "forma_pago": "CONSIGNACION",
        "servicios": [{"descripcion": "S", "valor": "1000"}],
        "nit_pagador": "800197268",
        "dv_pagador": "4",
        "fecha_transaccion": "2026-09-17",
        "valor_total": "1000",
        "numero_referencia": "X",
    }
    row.confianza_ocr = 80
    row.paginas = 1
    row.errores = []
    row.nit_validado = None
    row.nit_mensaje = None

    fake_crepo = MagicMock()
    fake_crepo.get_by_task_id = AsyncMock(return_value=row)

    async def _update_datos(task_id_arg, **kwargs):
        row.datos_extraidos = kwargs["datos"]
        row.status = kwargs.get("status", row.status)
        return row

    fake_crepo.update_datos = AsyncMock(side_effect=_update_datos)

    fake_prepo = MagicMock()
    fake_prepo.list_all = AsyncMock(return_value=[perfil])

    async def _fake_db():
        yield MagicMock()

    monkeypatch.setattr(upload_mod, "ComprobanteRepo", lambda s: fake_crepo)
    monkeypatch.setattr(upload_mod, "PerfilRepo", lambda s: fake_prepo)
    monkeypatch.setattr(
        upload_mod, "validar_nit_snri",
        AsyncMock(return_value={"valido": True, "mensaje": "ok"}),
    )

    app.dependency_overrides[get_db] = _fake_db
    try:
        with client as c:
            r = c.post(f"/api/v1/comprobantes/{task_id}/reextraer", json={"perfil_id": None})
            assert r.status_code == 200, r.text
            datos = r.json()["datos"]
            assert datos["valor_total"] == "20259"
            assert datos["banco"] == "CREDIBANCO"
            assert datos["nit_pagador"] == "800197268"
            assert datos["perfil_codigo"] == "credibanco-pos"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_reextraer_perfil_no_encontrado(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from app.api import upload as upload_mod

    task_id = str(uuid.uuid4())
    row = MagicMock()
    row.task_id = task_id
    row.texto_ocr = "texto"

    fake_crepo = MagicMock()
    fake_crepo.get_by_task_id = AsyncMock(return_value=row)
    fake_prepo = MagicMock()
    fake_prepo.list_all = AsyncMock(return_value=[])

    async def _fake_db():
        yield MagicMock()

    monkeypatch.setattr(upload_mod, "ComprobanteRepo", lambda s: fake_crepo)
    monkeypatch.setattr(upload_mod, "PerfilRepo", lambda s: fake_prepo)

    app.dependency_overrides[get_db] = _fake_db
    try:
        with client as c:
            r = c.post(
                f"/api/v1/comprobantes/{task_id}/reextraer",
                json={"perfil_id": "inexistente"},
            )
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_upload_acepta_perfil_id(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))

    fake_repo = MagicMock()
    fake_repo.create = AsyncMock(return_value=MagicMock())

    async def _fake_db():
        yield MagicMock()

    with (
        patch("app.api.upload.ComprobanteRepo", lambda session: fake_repo),
        patch("app.api.upload.procesar_documento", AsyncMock()) as mock_proc,
    ):
        app.dependency_overrides[get_db] = _fake_db
        try:
            with client as c:
                r = c.post(
                    "/api/v1/upload",
                    files={"file": ("ok.png", b"\x89PNG\r\n\x1a\n", "image/png")},
                    data={"nit_pagador": "8001972684", "perfil_id": "credibanco-pos"},
                )
                assert r.status_code == 200, r.text
                args = mock_proc.call_args[0]
                assert args[4] == "credibanco-pos"
        finally:
            app.dependency_overrides.pop(get_db, None)
