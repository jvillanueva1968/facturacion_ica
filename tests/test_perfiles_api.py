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

def test_ui_incluye_config_y_perfiles():
    from fastapi.testclient import TestClient
    from app.main import app

    r = TestClient(app).get("/")
    assert r.status_code == 200
    html = r.text
    assert "Configuración" in html
    assert "Perfil de extracción" in html
    assert "Re-extraer con perfil" in html
    assert "camposPerfil()" in html
    assert "perfil_id" in html
    assert "perfiles/catalogo/campos" in html
    assert "xfd.append" not in html


def test_ui_envia_perfil_id_en_upload():
    from fastapi.testclient import TestClient
    from app.main import app

    html = TestClient(app).get("/").text
    assert "fd.append('perfil_id'" in html
    assert "reextrayendo" in html
    assert "guardandoPerfil" in html

def test_ui_bindings_referencian_estado_existente():
    """Ningun binding raiz (x-model/x-for/x-show) puede usar un identificador inexistente en el JS."""
    import re as _re

    from fastapi.testclient import TestClient
    from app.main import app

    html = TestClient(app).get("/").text
    js = _re.search(r"(?s)<script>(.*)</script>", html).group(1)

    props = set(_re.findall(r"(?m)^\s{4}([a-zA-Z_]\w*)\s*[:\(]", js))
    props |= set(_re.findall(r"(?m)^\s{4}get\s+([a-zA-Z_]\w*)", js))
    props |= {"status", "step", "config", "dragging", "error"}

    # variables declaradas por x-for en el propio HTML
    scope_vars = set(_re.findall(r'x-for="\(?([\w,\s]+?)\)?\s+(?:in|of)\s+', html))
    declared = set()
    for v in scope_vars:
        declared |= {t.strip() for t in v.split(",") if t.strip()}

    roots = set()
    for m in _re.finditer(r'x-model="([\w]+)', html):
        roots.add(m.group(1))
    for m in _re.finditer(r'x-for="\w[\w,]*\s+in\s+([\w]+)', html):
        roots.add(m.group(1))
    for m in _re.finditer(r'x-show="([\w]+)(?:\s|&)', html):
        roots.add(m.group(1))

    roots -= declared
    missing = sorted(r for r in roots if r not in props)
    assert not missing, f"Bindings con identificador inexistente: {missing}"

def test_ui_otra_identificacion_limpia_estado():
    from fastapi.testclient import TestClient
    from app.main import app

    html = TestClient(app).get("/").text
    assert 'otraIdentificacion()' in html
    assert 'otraCarga()' in html
    assert '@click="step=1"' not in html
    assert 'resetResultados()' in html

def test_fusionar_datos_fecha_perfil_prioriza():
    from datetime import date
    from decimal import Decimal

    from app.api.upload import _fusionar_datos
    from app.models.schemas import DatosExtraidos
    from app.services.extraction import PerfilExtraccionData

    base = DatosExtraidos(
        forma_pago="DATAFONO",
        servicios=[{"descripcion": "SERVICIO", "valor": "1500000.50"}],
        nit_pagador="8001972688",
        dv_pagador="4",
        fecha_transaccion=date(2026, 1, 1),
        valor_total=Decimal("1500000.50"),
        numero_referencia="336609608",
    )
    perfil = PerfilExtraccionData(
        codigo="credibanco-pos",
        nombre="Credibanco POS",
        campos={"fecha": {"regex": r"(\d{1,2}/\d{1,2}/\d{4})", "requerido": True, "orden": 2}},
    )
    out = _fusionar_datos(base, {"fecha": "2026-09-18"}, perfil)
    assert str(out.fecha_transaccion) == "2026-09-18"

    out2 = _fusionar_datos(base, {"fecha": "xx/yy/zzzz"}, perfil)
    assert str(out2.fecha_transaccion) == "2026-01-01"


def test_ui_fecha_usa_fecha_transaccion():
    from fastapi.testclient import TestClient
    from app.main import app

    html = TestClient(app).get("/").text
    assert "campoFormKey(c.campo)" in html
    assert "campoFormKey(campo)" in html
    assert 'x-model="form[c.campo]"' not in html
