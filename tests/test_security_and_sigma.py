import json
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.security import create_access_token, decode_access_token
from app.models.schemas import DatosExtraidos, FormaPago, SNRIFacturaResponse
from app.services.llm_service import LLMService
from app.services.nit_validator import normalizar_nit_dv, validar_nit_completo
from app.services.sigma_client import SigmaClient


def test_jwt_roundtrip():
    token = create_access_token("operador-1", expires_minutes=5)
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "operador-1"


def test_jwt_invalid():
    assert decode_access_token("token.falso.aqui") is None


def test_nit_completo():
    assert validar_nit_completo("800197268-4")
    assert not validar_nit_completo("800197268-9")


def test_normalizar_embebido():
    assert normalizar_nit_dv("8001972684", "4") == ("800197268", "4")


def test_llm_parse_ok():
    svc = LLMService()
    raw = json.dumps(
        {
            "forma_pago": "CONSIGNACION",
            "servicios": [{"codigo": "ICA-1", "nombre": "Derecho", "valor": "1000"}],
            "nit_pagador": "8001972684",
            "dv_pagador": "4",
            "fecha_transaccion": "2026-09-20",
            "valor_total": "150000",
            "numero_referencia": "REF-1",
        }
    )
    datos = svc._parse_response(raw)
    assert datos.nit_pagador == "800197268"
    assert datos.valor_total == Decimal("150000")
    assert datos.forma_pago == FormaPago.CONSIGNACION


def test_llm_parse_invalid():
    svc = LLMService()
    with pytest.raises(ValueError):
        svc._parse_response("no-es-json")


@pytest.mark.asyncio
async def test_sigma_registrar_success():
    client = SigmaClient()
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"success": True, "id": "abc"}
    client.client = AsyncMock()
    client.client.post.return_value = mock_resp

    result = await client.registrar_factura({"numero_referencia": "R1", "valor_total": 10})
    assert result["success"] is True
    client.client.post.assert_awaited_once()
    client.client.post.assert_awaited_with(
        f"{client.base_url}/facturas/registrar",
        json={"numero_referencia": "R1", "valor_total": 10},
    )
    await client.close()


@pytest.mark.asyncio
async def test_sigma_registrar_http_error():
    client = SigmaClient()
    client.client = AsyncMock()
    client.client.post.side_effect = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("POST", "http://x"),
        response=httpx.Response(500),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.registrar_factura({"numero_referencia": "R2"})
    await client.close()


def test_snri_response_model():
    r = SNRIFacturaResponse(success=True, numero_factura="DEMO-1", errores=[])
    assert r.success
    assert r.errores == []
