import json
import logging
import re
import httpx
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
_RE_VALOR = re.compile(
    r"(?:VALOR(?:\s+TOTAL)?|TOTAL(?:\s+A\s+PAGAR)?)\D{0,20}(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)",
    re.I,
)
_RE_REF = re.compile(
    r"(?:REFERENCIA|CONSIGNACI[OÓ]N|TRANSFERENCIA|N[ÚU]MERO(?:\s+DE)?\s+(?:OPERACI[OÓ]N|TRANSACCI[OÓ]N))"
    r"\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{3,19})",
    re.I,
)
_RE_FECHA_ISO = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


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
    m = _RE_VALOR.search(ocr_text)
    if m:
        hints.append(f"valor_total={m.group(1)}")
    m = _RE_REF.search(ocr_text)
    if m:
        hints.append(f"numero_referencia={m.group(1)}")
    return "\n".join(hints) if hints else "(ninguno)"


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
            return DatosExtraidos(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.error(f"Error parseando respuesta LLM: {e}\nRespuesta: {json_str[:500]}")
            raise ValueError(f"Respuesta LLM inválida: {e}")