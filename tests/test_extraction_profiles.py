from app.services.extraction import (
    CAMPOS_CATALOGO,
    PERFILES_SEED,
    PerfilExtraccionData,
    campos_faltantes,
    detectar_perfil,
    es_nombre_campo,
    extraer_campos,
    normalizar_fecha,
    normalizar_valor,
    ordenar_campos,
)


def _perfiles():
    return [PerfilExtraccionData(**dict(s)) for s in PERFILES_SEED]


TEXTO_CREDIBANCO = (
    "RECIBO:000299 17/09/2026 09:35:11\n"
    "credibanco\n"
    "ICA OFC LOCAL ICA GUAMAL\n"
    "VENTA APROBADA\n"
    "AUT: 144730\n"
    "VLR. NETO: $20.259"
)
TEXTO_WOMPI = (
    "Wompi\n"
    "Corresponsal Bancolombia\n"
    "MULTIPAGOS BG GUAMAE\n"
    "cr 6 13 28 brr fundadores,fundadores\n"
    "Monto: $11.450,00\n"
    "Fecha: SEP 17 2026 - 09:24:49\n"
    "Referencia: 17445016\n"
    "Convenio. 72159"
)
TEXTO_REDEBAN = (
    "REDEBAN\n"
    "MULTIPAGAS\n"
    "VALOR $45.000\n"
    "CONVENIO: 700006514\n"
    "RECIBO: 10436686\n"
    "SEP 12 2026"
)


def test_normalizar_valor_casos_colombianos():
    assert normalizar_valor("1.500.000,00") == "1500000"
    assert normalizar_valor("$150.000") == "150000"
    assert normalizar_valor("15.000,50") == "15000.5"
    assert normalizar_valor("20.259") == "20259"


def test_normalizar_valor_internacional_y_basico():
    assert normalizar_valor("1,500,000.50") == "1500000.5"
    assert normalizar_valor("150000") == "150000"
    assert normalizar_valor(None) == ""
    assert normalizar_valor("") == ""


def test_normalizar_fecha_formatos():
    assert normalizar_fecha("17/09/2026") == "2026-09-17"
    assert normalizar_fecha("SEP 18 2026") == "2026-09-18"
    assert normalizar_fecha("2026-09-18") == "2026-09-18"
    assert normalizar_fecha("basura") == ""
    assert normalizar_fecha(None) == ""


def test_parsear_fecha_formatos():
    from datetime import date, datetime

    from app.services.extraction import parsear_fecha

    assert parsear_fecha("2026-09-17") == date(2026, 9, 17)
    assert parsear_fecha("2026-09-17T10:33:00") == date(2026, 9, 17)
    assert parsear_fecha("2026-09-17 10:33:00") == date(2026, 9, 17)
    assert parsear_fecha("2026-9-7") == date(2026, 9, 7)
    assert parsear_fecha("17/09/2026 09:35:11") == date(2026, 9, 17)
    assert parsear_fecha("SEP 17 2026 - 09:24:49") == date(2026, 9, 17)
    assert parsear_fecha("20260917") == date(2026, 9, 17)
    assert parsear_fecha(date(2026, 9, 17)) == date(2026, 9, 17)
    assert parsear_fecha(datetime(2026, 9, 17, 10, 33)) == date(2026, 9, 17)


def test_parsear_fecha_rechaza_valores_ilegibles():
    from app.services.extraction import parsear_fecha

    # Números puros (epoch / referencia) no se interpretan como fecha.
    assert parsear_fecha("1185192020") is None
    assert parsear_fecha(1185192020) is None
    assert parsear_fecha("31/02/2026") is None
    assert parsear_fecha("basura") is None
    assert parsear_fecha("") is None
    assert parsear_fecha(None) is None


def test_detectar_perfil_por_keywords():
    perfiles = _perfiles()
    assert detectar_perfil(TEXTO_CREDIBANCO, perfiles).codigo == "credibanco-pos"
    assert detectar_perfil(TEXTO_WOMPI, perfiles).codigo == "wompi-bancolombia"
    assert detectar_perfil(TEXTO_REDEBAN, perfiles).codigo == "redeban-bancolombia"


def test_detectar_perfil_sin_match():
    assert detectar_perfil("texto sin relacion", _perfiles()) is None
    assert detectar_perfil("", _perfiles()) is None
    assert detectar_perfil("credibanco", []) is None


def test_detectar_perfil_respeta_inactivo():
    perfiles = _perfiles()
    for p in perfiles:
        if p.codigo == "credibanco-pos":
            p.activo = False
    assert detectar_perfil(TEXTO_CREDIBANCO, perfiles) is None


def test_extraer_campos_credibanco():
    perfil = detectar_perfil(TEXTO_CREDIBANCO, _perfiles())
    campos = extraer_campos(TEXTO_CREDIBANCO, perfil)
    assert campos["valor_total"] == "20259"
    assert campos["fecha"] == "2026-09-17"
    assert campos["numero_referencia"] == "000299"
    assert campos["banco"] == "CREDIBANCO"
    assert campos["autenticacion"] == "144730"
    assert campos_faltantes(perfil, campos) == []


def test_extraer_campos_wompi():
    perfil = detectar_perfil(TEXTO_WOMPI, _perfiles())
    campos = extraer_campos(TEXTO_WOMPI, perfil)
    assert campos["valor_total"] == "11450"
    assert campos["fecha"] == "2026-09-17"
    assert campos["numero_referencia"] == "17445016"
    assert campos["convenio"] == "72159"
    assert (
        campos["ubicacion"].startswith("cr 6 13")
        or campos["ubicacion"].startswith("MULTIPAGOS")
    )


def test_extraer_campos_redeban():
    perfil = detectar_perfil(TEXTO_REDEBAN, _perfiles())
    campos = extraer_campos(TEXTO_REDEBAN, perfil)
    assert campos["valor_total"] == "45000"
    assert campos["fecha"] == "2026-09-12"
    assert campos["numero_referencia"] == "10436686"
    assert campos["convenio"] == "700006514"
    assert campos_faltantes(perfil, campos) == []


def test_campos_faltantes_requeridos():
    perfil = detectar_perfil("credibanco sin montos", _perfiles())
    campos = extraer_campos("credibanco sin montos", perfil)
    faltan = campos_faltantes(perfil, campos)
    assert "valor_total" in faltan
    assert "fecha" in faltan


def test_ordenar_campos_por_orden():
    perfil = detectar_perfil(TEXTO_WOMPI, _perfiles())
    ordenados = ordenar_campos(perfil)
    campos = [c["campo"] for c in ordenados]
    assert campos[0] == "valor_total"
    assert campos[1] == "fecha"
    assert campos == sorted(campos, key=lambda c: next(
        x["orden"] for x in ordenados if x["campo"] == c
    ))


def test_campos_catalogo_completo():
    assert set(CAMPOS_CATALOGO) == {
        "valor_total", "fecha", "numero_referencia", "banco",
        "forma_pago", "convenio", "ubicacion", "autenticacion",
    }
    for seed in PERFILES_SEED:
        for campo in seed["campos"]:
            assert campo in CAMPOS_CATALOGO


def test_seeds_tienen_campos_requeridos():
    for seed in PERFILES_SEED:
        assert any(
            cfg.get("requerido") for cfg in seed["campos"].values()
        ), seed["codigo"]
        assert seed["detect_keywords"], seed["codigo"]


def test_es_nombre_campo():
    assert es_nombre_campo("valor_total")
    assert es_nombre_campo("numero_tarjeta")
    assert not es_nombre_campo("Campo Malo")
    assert not es_nombre_campo("1abc")
    assert not es_nombre_campo("a")
    assert not es_nombre_campo(123)
    assert not es_nombre_campo(None)


def test_extraer_campos_personalizados():
    perfil = PerfilExtraccionData(
        codigo="custom-test",
        nombre="Custom",
        campos={
            "numero_tarjeta": {
                "regex": r"Tarjeta: (\d{4}\s?\d{4}\s?\d{4}\s?\d{4})",
                "requerido": False, "orden": 1,
            },
            "valor_adicional": {
                "regex": r"Adicional: \$([\d.,]+)",
                "tipo": "numero", "requerido": False, "orden": 2,
            },
            "fecha_pago": {
                "regex": r"Fecha de pago: (\w+ \d{1,2} \d{4})",
                "tipo": "fecha", "requerido": False, "orden": 3,
            },
        },
    )
    texto = (
        "Tarjeta: 4111 1111 1111 1111\n"
        "Adicional: $1.500,00\n"
        "Fecha de pago: SEP 18 2026\n"
    )
    campos = extraer_campos(texto, perfil)
    assert campos["numero_tarjeta"] == "4111 1111 1111 1111"
    assert campos["valor_adicional"] == "1500"
    assert campos["fecha_pago"] == "2026-09-18"


def test_ordenar_campos_incluye_personalizados():
    perfil = PerfilExtraccionData(
        codigo="custom-test",
        nombre="Custom",
        campos={
            "numero_tarjeta": {"regex": r"(\d+)", "label": "N° tarjeta", "orden": 5},
            "valor_total": {"regex": r"(\d+)", "requerido": True, "orden": 1},
        },
    )
    ordenados = ordenar_campos(perfil)
    assert [c["campo"] for c in ordenados] == ["valor_total", "numero_tarjeta"]
    assert ordenados[1]["label"] == "N° tarjeta"
