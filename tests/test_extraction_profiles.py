from app.services.extraction import (
    CAMPOS_CATALOGO,
    PERFILES_SEED,
    PerfilExtraccionData,
    campos_faltantes,
    detectar_perfil,
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
