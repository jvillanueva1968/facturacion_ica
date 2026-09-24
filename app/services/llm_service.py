import json
import logging
import re
import httpx
from decimal import Decimal, InvalidOperation
from typing import Optional
from pydantic import ValidationError
from app.models.schemas import DatosExtraidos, FormaPago
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

PROMPT_EXTRACCION = """
Eres un experto en extracción de datos de comprobantes de pago colombianos (consignaciones, transferencias, cheques de gerencia, PSE, datáfonos).

TAREA: Extrae ÚNICAMENTE los campos solicitados en formato JSON válido. NO agregues explicaciones.

CAMPOS REQUERIDOS:
- forma_pago: "CONSIGNACION" | "DATAFONO" | "TRANSFERENCIA" | "CHEQUE_GERENCIA" | "PSE"
- servicios: array de objetos con claves codigo, nombre, valor
- nit_pagador: solo números (sin DV)
- dv_pagador: dígito de verificación (1 dígito)
- fecha_transaccion: formato YYYY-MM-DD
- valor_total: número decimal
- numero_referencia: string (número de consignación, transferencia, etc.)
- banco: nombre del banco (opcional)
- tipo_documento: "CC" | "NIT" | "CE" | "PP" (opcional)
- numero_documento: número documento identificación (opcional)

REGLAS:
1. Si no encuentras un campo, usa null (no inventes)
2. Valores monetarios: solo números, sin separadores de miles, punto decimal
3. Fechas: normaliza a YYYY-MM-DD
4. Forma de pago: infiere por palabras clave (consignación, transferencia, PSE, datáfono, cheque gerencia)
5. Servicios ICA: busca códigos como "ICA-XXXX", "SERV-XXXX" o nombres de trámites
6. Si HALLAZGOS_PRELIMINARES trae un valor, úsalo como pista de alta prioridad (verifícalo contra el texto)

HALLAZGOS_PRELIMINARES (regex sobre el OCR):
{hints}

TEXTO OCR:
{ocr_text}
"""

_RE_NIT = re.compile(r"NIT\D{0,25}(\d{6,10})(?:\s*[-–]\s*(\d))?", re.I)
_RE_FECHA = re.compile(r"(\d{2})[/\-.](\d{2})[/\-.](\d{4})")
_VALOR_NUM = r"(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)"
_RE_VALORES = (
    re.compile(rf"VALOR\s+TOTAL\D{{0,20}}{_VALOR_NUM}", re.I),
    re.compile(rf"TOTAL\s+A\s+PAGAR\D{{0,20}}{_VALOR_NUM}", re.I),
    re.compile(rf"(?<!SUB)(?<!IVA\s)\bTOTAL\b\D{{0,20}}{_VALOR_NUM}", re.I),
    re.compile(rf"\$\s*({_VALOR_NUM.lstrip('(').rstrip(')')})"),
)
_RE_REF = re.compile(
    r"(?:REFERENCIA|CONSIGNACI[OÓ]N|TRANSFERENCIA|N[ÚU]MERO(?:\s+DE)?\s+(?:OPERACI[OÓ]N|TRANSACCI[OÓ]N))"
    r"\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{3,19})",
    re.I,
)
_RE_FECHA_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def normalizar_valor(raw) -> str:
    """1.500.000,00 / $150.000 / 1,500,000.50 / 150000 → '150000' | '150000.50'."""
    if raw is None:
        return ""
    s = str(raw).strip().replace("$", "").replace(" ", "").replace("\u00a0", "")
    s = re.sub(r"[^\d.,-]", "", s)
    if not s or s in {"-", ","}:
        return ""
    s = s.lstrip("-")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        if re.fullmatch(r"\d+,\d{1,2}", s):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
            s = s.replace(".", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return ""
    if d < 0:
        d = -d
    return format(d.normalize(), "f")


def _extraer_valor(ocr_text: str) -> Optional[str]:
    for rx in _RE_VALORES:
        m = rx.search(ocr_text)
        if m:
            n = normalizar_valor(m.group(1))
            if n:
                return n
    return None


def hallazgos_preliminares(ocr_text: str) -> str:
    """Pistas deterministas baratas antes de llamar al LLM."""
    hints = []
    m = _RE_NIT.search(ocr_text)
    if m:
        hints.append(f"nit_pagador={m.group(1)}" + (f", dv_pagador={m.group(2)}" if m.group(2) else ""))
    m = _RE_FECHA_ISO.search(ocr_text) or _RE_FECHA.search(ocr_text)
    if m:
        if m.re is _RE_FECHA_ISO:
            hints.append(f"fecha_transaccion={m.group(1)}")
        else:
            hints.append(f"fecha_transaccion={m.group(3)}-{m.group(2)}-{m.group(1)}")
    v = _extraer_valor(ocr_text)
    if v:
        hints.append(f"valor_total={v}")
    m = _RE_REF.search(ocr_text)
    if m:
        hints.append(f"numero_referencia={m.group(1)}")
    return "\n".join(hints) if hints else "(ninguno)"


def normalizar_datos_llm(data: dict) -> dict:
    """Normaliza montos del JSON del LLM y rellena valor_total desde servicios si hace falta."""
    if not isinstance(data, dict):
        return data
    v = normalizar_valor(data.get("valor_total"))
    if v:
        data["valor_total"] = v
    total_svcs = Decimal("0")
    hay_svcs = False
    for s in data.get("servicios") or []:
        if not isinstance(s, dict):
            continue
        sv = normalizar_valor(s.get("valor"))
        if sv:
            s["valor"] = sv
            hay_svcs = True
            total_svcs += Decimal(sv)
    if hay_svcs and (not data.get("valor_total")):
        data["valor_total"] = str(total_svcs)
    return data


class LLMService:
    def __init__(self):
        self.provider = settings.llm_provider

    async def extraer_datos(self, ocr_text: str) -> DatosExtraidos:
        prompt = PROMPT_EXTRACCION.format(
            hints=hallazgos_preliminares(ocr_text),
            ocr_text=ocr_text[:8000],
        )

        if self.provider == "ollama":
            return await self._call_ollama(prompt)
        elif self.provider == "openrouter":
            return await self._call_openrouter(prompt)
        else:
            raise ValueError(f"Proveedor LLM no soportado: {self.provider}")

    async def _call_ollama(self, prompt: str) -> DatosExtraidos:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 1024}
                }
            )
            response.raise_for_status()
            result = response.json()
            return self._parse_response(result.get("response", "{}"))

    async def _call_openrouter(self, prompt: str) -> DatosExtraidos:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": settings.openrouter_model,
                    "messages": [
                        {"role": "system", "content": "Eres un extractor de datos preciso. Responde SOLO con JSON válido."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1
                }
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            return self._parse_response(content)

    def _parse_response(self, json_str: str) -> DatosExtraidos:
        try:
            data = json.loads(json_str)
            data = normalizar_datos_llm(data)
            return DatosExtraidos(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Error parseando respuesta LLM: {e}\nRespuesta: {json_str[:500]}")
            raise ValueError(f"Respuesta LLM inválida: {e}")