from app.services.nit_validator import (
    calcular_dv_nit,
    limpiar_cache_nit,
    normalizar_nit_dv,
    validar_nit_completo,
    validar_nit_snri,
)
from app.models.schemas import DatosExtraidos, FormaPago, TerceroResponse
from datetime import date
from decimal import Decimal


def test_calcular_dv_800197268():
    assert calcular_dv_nit("800197268") == "4"


def test_calcular_dv_93361223():
    assert calcular_dv_nit("93361223") == "2"


def test_validar_nit_con_dv():
    assert validar_nit_completo("800197268-4") is True
    assert validar_nit_completo("8001972685") is False


def test_normalizar_nit_sin_dv_embebido():
    assert normalizar_nit_dv("800197268", "4") == ("800197268", "4")


def test_normalizar_nit_con_dv_embebido():
    assert normalizar_nit_dv("8001972684", "4") == ("800197268", "4")
    assert normalizar_nit_dv("8001972684", None) == ("800197268", "4")
    # LLM inventa DV equivocado pero el NIT trae el DV correcto embebido
    assert normalizar_nit_dv("8001972684", "1") == ("800197268", "4")


def test_normalizar_nit_vacio():
    assert normalizar_nit_dv("", "4") == ("", "4")


def test_datos_extraidos_normaliza_nit_llm():
    datos = DatosExtraidos(
        forma_pago=FormaPago.CONSIGNACION,
        servicios=[{"codigo": "ICA-1", "nombre": "Servicio", "valor": "100.00"}],
        nit_pagador="8001972684",
        dv_pagador="4",
        fecha_transaccion=date(2026, 9, 20),
        valor_total=Decimal("150000"),
        numero_referencia="123456",
    )
    assert datos.nit_pagador == "800197268"
    assert datos.dv_pagador == "4"


class _FakeSNRI:
    token = "t"
    last_query = None

    async def consultar_tercero(self, doc: str) -> TerceroResponse:
        _FakeSNRI.last_query = doc
        if doc == "93361223":
            return TerceroResponse(
                id_tercero=312792,
                nro_identificacion="93361223",
                nombre_razon_social="IGNACIO BOHORQUEZ PAEZ",
                success=True,
            )
        return TerceroResponse(success=False, errores=[{"codigo": "1", "mensaje": "no existe"}])


def test_validar_nit_snri_consulta_sin_dv():
    limpiar_cache_nit()
    _FakeSNRI.last_query = None
    import asyncio

    res = asyncio.get_event_loop().run_until_complete(
        validar_nit_snri("93361223", "2", _FakeSNRI())
    )
    assert res["valido"] is True
    assert "IGNACIO" in res["mensaje"]
    assert _FakeSNRI.last_query == "93361223"
    limpiar_cache_nit()


def test_validar_nit_snri_no_existe():
    limpiar_cache_nit()
    import asyncio

    res = asyncio.get_event_loop().run_until_complete(
        validar_nit_snri("99999999", "1", _FakeSNRI())
    )
    # 99999999-1: verificar DV local primero
    if validar_nit_completo("999999991"):
        assert res["valido"] is True
        assert "no existe" in res["mensaje"].lower() or "SNRI" in res["mensaje"]
    else:
        assert res["valido"] is False
    limpiar_cache_nit()
