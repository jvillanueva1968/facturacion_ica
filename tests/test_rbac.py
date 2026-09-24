from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.core.security import (
    ROLE_ADMIN,
    ROLE_OPERATOR,
    ROLE_VIEWER,
    create_access_token,
    decode_access_token,
    has_role,
    normalize_roles,
)
from app.db.session import get_db
from app.main import app

client = TestClient(app)

SIMPLE_BODY = {
    "id_proyecto": "1",
    "id_seccional": "1",
    "id_entidad": "1",
    "nit_pagador": "800197268",
    "dv_pagador": "4",
    "nombre_razon_social": "X",
    "id_departamento": 11,
    "id_ciudad": 11001,
    "direccion_principal": "Calle 1",
    "id_forma_pago": "1",
    "id_banco": "1",
    "numero_consignacion": "RBAC-1",
    "fecha_consignacion": "2026-09-23",
    "id_servicio": "1",
    "valor": "1000",
    "cantidad": "1",
    "valor_total": "1000",
}


def test_normalize_roles_default():
    assert normalize_roles(None) == [ROLE_OPERATOR]
    assert normalize_roles([]) == [ROLE_OPERATOR]
    assert normalize_roles(["admin", "admin", "nope"]) == ["admin"]


def test_has_role_hierarchy():
    viewer = {"roles": ["viewer"]}
    operator = {"roles": ["operator"]}
    admin = {"roles": ["admin"]}
    assert has_role(admin, ROLE_VIEWER)
    assert has_role(admin, ROLE_OPERATOR)
    assert has_role(admin, ROLE_ADMIN)
    assert has_role(operator, ROLE_VIEWER)
    assert has_role(operator, ROLE_OPERATOR)
    assert not has_role(operator, ROLE_ADMIN)
    assert has_role(viewer, ROLE_VIEWER)
    assert not has_role(viewer, ROLE_OPERATOR)
    assert not has_role(viewer, ROLE_ADMIN)


def test_jwt_includes_roles():
    token = create_access_token("u1", roles=["viewer"])
    payload = decode_access_token(token)
    assert payload["roles"] == ["viewer"]


def test_auth_jwt_with_roles_param():
    r = client.post(
        "/api/v1/auth/jwt",
        params={"subject": "lectura", "roles": "viewer"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["roles"] == ["viewer"]
    payload = decode_access_token(body["access_token"])
    assert payload["roles"] == ["viewer"]


def test_auth_jwt_rol_invalido():
    r = client.post(
        "/api/v1/auth/jwt",
        params={"subject": "x", "roles": "superuser"},
    )
    assert r.status_code == 400
    assert "superuser" in r.json()["detail"]


def test_auth_me_dev_admin():
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["sub"] == "dev"
    assert ROLE_ADMIN in body["roles"]


def test_produccion_sin_token_401(monkeypatch):
    from app.core import deps

    monkeypatch.setattr(deps, "auth_enabled", lambda: True)
    r = client.get("/api/v1/facturas")
    assert r.status_code == 401


def test_produccion_token_invalido_401(monkeypatch):
    from app.core import deps

    monkeypatch.setattr(deps, "auth_enabled", lambda: True)
    r = client.get(
        "/api/v1/facturas",
        headers={"Authorization": "Bearer no.valid.jwt"},
    )
    assert r.status_code == 401


def test_produccion_viewer_no_factura_403(monkeypatch):
    from app.core import deps

    monkeypatch.setattr(deps, "auth_enabled", lambda: True)
    tok = create_access_token("v", roles=["viewer"])
    r = client.post(
        "/api/v1/facturar/simple",
        json=SIMPLE_BODY,
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403
    assert "operator" in r.json()["detail"]


def test_produccion_operator_pasa_gate(monkeypatch):
    from app.core import deps
    from app.api import facturar as facturar_mod

    monkeypatch.setattr(deps, "auth_enabled", lambda: True)

    fake_factura = MagicMock()
    fake_factura.id = "11111111-2222-3333-4444-555555555555"
    fake_repo = MagicMock()
    fake_repo.get_emitida_by_consignacion = AsyncMock(return_value=None)
    fake_repo.create = AsyncMock(return_value=fake_factura)
    fake_repo.update_snri_result = AsyncMock(return_value=fake_factura)
    fake_audit = MagicMock()
    fake_audit.log = AsyncMock(return_value=None)

    monkeypatch.setattr(facturar_mod, "FacturaRepo", lambda session: fake_repo)
    monkeypatch.setattr(facturar_mod, "AuditRepo", lambda session: fake_audit)
    monkeypatch.setattr(
        facturar_mod, "sigma_client",
        MagicMock(registrar_factura=AsyncMock(return_value={"success": True})),
    )

    async def _fake_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _fake_db
    try:
        tok = create_access_token("ops", roles=["operator"])
        r = client.post(
            "/api/v1/facturar/simple",
            json=SIMPLE_BODY,
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code not in (401, 403)
        assert r.json().get("success") is True
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_mint_admin_requires_admin(monkeypatch):
    from app.core import deps

    monkeypatch.setattr(deps, "auth_enabled", lambda: True)
    tok_op = create_access_token("ops", roles=["operator"])
    r = client.post(
        "/api/v1/auth/jwt",
        params={"subject": "evil", "roles": "admin"},
        headers={"Authorization": f"Bearer {tok_op}"},
    )
    assert r.status_code == 403

    tok_adm = create_access_token("boss", roles=["admin"])
    r = client.post(
        "/api/v1/auth/jwt",
        params={"subject": "ok", "roles": "admin"},
        headers={"Authorization": f"Bearer {tok_adm}"},
    )
    assert r.status_code == 200
    assert r.json()["roles"] == ["admin"]


def test_facturar_simple_idempotente_consignacion(monkeypatch):
    from app.api import facturar as facturar_mod
    from app.core import deps
    from app.db.session import get_db

    monkeypatch.setattr(deps, "auth_enabled", lambda: True)

    existente = MagicMock(
        numero_factura="DEMO-IDEM1",
        id_factura_snri="DEMO-IDEM1",
        cufe="DEMO-CUFE-IDEM1",
        estado_snri="emitida",
        numero_consignacion="IDEM-CONSIGN-1",
    )
    fake_repo = MagicMock()
    fake_repo.get_emitida_by_consignacion = AsyncMock(return_value=existente)
    fake_repo.create = AsyncMock(
        side_effect=AssertionError("no debe crear factura duplicada")
    )
    fake_audit = MagicMock()
    fake_audit.log = AsyncMock(return_value=None)

    monkeypatch.setattr(facturar_mod, "FacturaRepo", lambda session: fake_repo)
    monkeypatch.setattr(facturar_mod, "AuditRepo", lambda session: fake_audit)

    async def _fake_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = _fake_db
    try:
        tok = create_access_token("ops", roles=["operator"])
        body = dict(SIMPLE_BODY, numero_consignacion="IDEM-CONSIGN-1")
        r = client.post(
            "/api/v1/facturar/simple",
            json=body,
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200
        j = r.json()
        assert j["success"] is True
        assert j["numero_factura"] == "DEMO-IDEM1"
        assert any(e.get("codigo") == "DUPLICADO" for e in j["errores"])
        fake_repo.create.assert_not_awaited()
    finally:
        app.dependency_overrides.pop(get_db, None)
