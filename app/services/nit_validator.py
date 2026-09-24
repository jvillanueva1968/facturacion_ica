from typing import Optional

PESOS_DIAN = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]


def calcular_dv_nit(nit: str) -> str:
    nit_limpio = ''.join(filter(str.isdigit, nit))
    if not nit_limpio:
        raise ValueError("NIT vacío o inválido")

    nit_invertido = nit_limpio[::-1]
    suma = 0
    for i, digito in enumerate(nit_invertido):
        peso = PESOS_DIAN[i % len(PESOS_DIAN)]
        suma += int(digito) * peso

    residuo = suma % 11

    if residuo == 0 or residuo == 1:
        dv = str(residuo)
    else:
        dv = str(11 - residuo)

    return dv


def validar_nit_completo(nit_con_dv: str) -> bool:
    nit_con_dv = nit_con_dv.replace(" ", "").replace("-", "")
    if len(nit_con_dv) < 2:
        return False

    nit = nit_con_dv[:-1]
    dv_ingresado = nit_con_dv[-1]
    dv_calculado = calcular_dv_nit(nit)

    return dv_ingresado == dv_calculado


_nit_cache = {}


async def validar_nit_snri(nit: str, dv: str, snri_client=None) -> dict:
    nit, dv = normalizar_nit_dv(nit, dv)
    cache_key = f"{nit}-{dv}"
    if cache_key in _nit_cache:
        return _nit_cache[cache_key]

    try:
        if not validar_nit_completo(f"{nit}{dv}"):
            resultado = {"valido": False, "mensaje": "DV inválido según algoritmo DIAN", "datos": None}
            _nit_cache[cache_key] = resultado
            return resultado

        if snri_client and snri_client.token:
            tercero = await snri_client.consultar_tercero(f"{nit}{dv}")
            if tercero.success:
                resultado = {
                    "valido": True,
                    "mensaje": "NIT válido y existe en SNRI",
                    "datos": tercero.model_dump()
                }
            else:
                resultado = {
                    "valido": True,
                    "mensaje": "NIT válido (algoritmo) pero no existe en SNRI",
                    "datos": None
                }
        else:
            resultado = {
                "valido": True,
                "mensaje": "NIT válido (validación local algoritmo DIAN)",
                "datos": None
            }

    except Exception as e:
        resultado = {"valido": False, "mensaje": f"Error validando: {str(e)}", "datos": None}

    _nit_cache[cache_key] = resultado
    return resultado


def limpiar_nit(nit: str) -> str:
    return ''.join(filter(str.isdigit, nit))


def normalizar_nit_dv(nit: str, dv: Optional[str] = None) -> tuple[str, str]:
    """Separa NIT base y DV. Tolera NIT con DV ya embebido (p.ej. extracción LLM)."""
    nit_limpio = limpiar_nit(nit or "")
    dv_limpio = limpiar_nit(dv or "")
    if not nit_limpio:
        return "", dv_limpio

    # NIT completo con DV embebido (típico LLM: "8001972684" + dv inventado)
    if len(nit_limpio) >= 9 and validar_nit_completo(nit_limpio):
        base = nit_limpio[:-1]
        emb = nit_limpio[-1]
        if len(base) >= 6:
            if not dv_limpio or not validar_nit_completo(f"{base}{dv_limpio}"):
                return base, emb
            # ambos validan pero difieren → preferir el embebido (es parte del NIT)
            if dv_limpio != emb:
                return base, emb
            return base, emb

    if dv_limpio and nit_limpio.endswith(dv_limpio) and len(nit_limpio) > len(dv_limpio):
        base = nit_limpio[: -len(dv_limpio)]
        if len(base) >= 6 and validar_nit_completo(f"{base}{dv_limpio}"):
            if not validar_nit_completo(f"{nit_limpio}{dv_limpio}") or len(nit_limpio) >= 10:
                return base, dv_limpio

    if not dv_limpio and len(nit_limpio) >= 10:
        base = nit_limpio[:-1]
        dv_embebido = nit_limpio[-1]
        if validar_nit_completo(nit_limpio):
            return base, dv_embebido

    # DV separado inválido pero el NIT con su último dígito sí valida
    if dv_limpio and not validar_nit_completo(f"{nit_limpio}{dv_limpio}"):
        if len(nit_limpio) >= 9 and validar_nit_completo(nit_limpio):
            return nit_limpio[:-1], nit_limpio[-1]

    return nit_limpio, dv_limpio


def formatear_nit_con_dv(nit: str, dv: str) -> str:
    return f"{nit}-{dv}"