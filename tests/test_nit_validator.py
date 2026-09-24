from app.services.nit_validator import (
    calcular_dv_nit,
    normalizar_nit_dv,
    validar_nit_completo,
)
from app.models.schemas import DatosExtraidos, FormaPago
from datetime import date
from decimal import Decimal


def test_calcular_dv_800197268():
    assert calcular_dv_nit("800197268") == "4"


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
