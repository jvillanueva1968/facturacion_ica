"""Extracción parametrizada por perfil de comprobante/voucher.

- Detecta el perfil por keywords sobre el texto OCR.
- Extrae SOLO los campos definidos en el perfil (regex o literal).
- Normaliza montos (formato colombiano) y fechas (dd/mm/yyyy o 'SEP 18 2026').
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

CAMPOS_CATALOGO = [
    "valor_total",
    "fecha",
    "numero_referencia",
    "banco",
    "forma_pago",
    "convenio",
    "ubicacion",
    "autenticacion",
]

MESES = {
    "ENE": 1, "JAN": 1, "FEB": 2, "MAR": 3, "ABR": 4, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AGO": 8, "AUG": 8, "SEP": 9,
    "OCT": 10, "NOV": 11, "DIC": 12, "DEC": 12,
}


def normalizar_valor(raw) -> str:
    """1.500.000,00 / $150.000 / 1,500,000.50 / 150000 → '150000' | '150000.5'."""
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


def normalizar_fecha(raw: Optional[str]) -> str:
    """'17/09/2026' | 'SEP 18 2026' | '2026-09-18' → 'YYYY-MM-DD' o ''."""
    if not raw:
        return ""
    s = " ".join(str(raw).split())
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return ""
    m = re.match(r"^([A-Za-záéíóúÁÉÍÓÚ]{3})\s+(\d{1,2})\s+(\d{4})$", s)
    if m:
        mes = MESES.get(m.group(1)[:3].upper())
        if mes:
            return f"{int(m.group(3)):04d}-{mes:02d}-{int(m.group(2)):02d}"
    return ""


@dataclass
class PerfilExtraccionData:
    codigo: str
    nombre: str
    detect_keywords: list = field(default_factory=list)
    campos: dict = field(default_factory=dict)
    llm_respaldo: bool = True
    activo: bool = True
    es_default: bool = False
    id: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "PerfilExtraccionData":
        return cls(
            id=row.id,
            codigo=row.codigo,
            nombre=row.nombre,
            detect_keywords=list(row.detect_keywords or []),
            campos=dict(row.campos or {}),
            llm_respaldo=bool(row.llm_respaldo),
            activo=bool(row.activo),
            es_default=bool(row.es_default),
        )


def detectar_perfil(texto: str, perfiles: list) -> Optional[PerfilExtraccionData]:
    """Score por keywords (case-insensitive). Empate → default."""
    if not texto or not perfiles:
        return None
    lower = texto.lower()
    best: Optional[PerfilExtraccionData] = None
    best_score = 0
    for p in perfiles:
        if not p.activo:
            continue
        score = sum(1 for kw in (p.detect_keywords or []) if kw.lower() in lower)
        if score > best_score or (score > 0 and score == best_score and p.es_default):
            best, best_score = p, score
    return best if best_score > 0 else None


def _capturas(rx: re.Pattern, texto: str) -> Optional[str]:
    m = rx.search(texto)
    if not m:
        return None
    for g in reversed(m.groups()):
        if g is not None and str(g).strip():
            return str(g).strip()
    return m.group(0).strip()


def extraer_campos(texto: str, perfil: PerfilExtraccionData) -> dict:
    """Aplica solo las regex/literales del perfil. Devuelve {campo: valor}."""
    out: dict = {}
    if not texto or not perfil:
        return out
    for campo, cfg in (perfil.campos or {}).items():
        if not isinstance(cfg, dict):
            continue
        valor = ""
        if cfg.get("literal"):
            valor = str(cfg["literal"]).strip()
        elif cfg.get("regex"):
            try:
                rx = re.compile(cfg["regex"], re.I)
            except re.error:
                continue
            captura = _capturas(rx, texto)
            if captura is not None:
                valor = captura
        if not valor:
            continue
        if campo == "valor_total":
            valor = normalizar_valor(valor)
        elif campo == "fecha":
            valor = normalizar_fecha(valor)
        else:
            valor = " ".join(valor.split())
        if valor:
            out[campo] = valor
    return out


def campos_faltantes(perfil: PerfilExtraccionData, campos: dict) -> list:
    """Campos con requerido=true y sin valor."""
    faltan = []
    for campo, cfg in (perfil.campos or {}).items():
        if isinstance(cfg, dict) and cfg.get("requerido") and not campos.get(campo):
            faltan.append(campo)
    return faltan


def ordenar_campos(perfil: PerfilExtraccionData) -> list:
    """[{campo, orden, requerido, regex, literal}] ordenado por `orden`."""
    items = []
    for campo, cfg in (perfil.campos or {}).items():
        if campo not in CAMPOS_CATALOGO:
            continue
        cfg = cfg if isinstance(cfg, dict) else {}
        items.append({
            "campo": campo,
            "orden": int(cfg.get("orden") or 99),
            "requerido": bool(cfg.get("requerido")),
            "regex": cfg.get("regex") or "",
            "literal": cfg.get("literal") or "",
        })
    items.sort(key=lambda x: x["orden"])
    return items


# ---------------------------------------------------------------------------
# Perfiles semilla (analizados sobre las 13 imágenes de C:\proyectos\vaucher\vaucher)
# ---------------------------------------------------------------------------

PERFILES_SEED: list[dict] = [
    {
        "codigo": "credibanco-pos",
        "nombre": "Credibanco POS",
        "detect_keywords": ["credibanco", "venta aprobada", "total (cop)", "criptograma", "vlr. neto"],
        "llm_respaldo": True,
        "campos": {
            "valor_total": {
                "regex": r"(?:TOTAL\s*\(COP\)|VLR\.?\s*NETO|VALOR\s*TOTAL)\s*[:\s]*\$?\s*([\d.,]{3,15})",
                "requerido": True, "orden": 1,
            },
            "fecha": {
                "regex": r"(\d{1,2}/\d{1,2}/\d{4})",
                "requerido": True, "orden": 2,
            },
            "numero_referencia": {
                "regex": r"RECIBO\s*:\s*(\d{3,15})",
                "requerido": False, "orden": 3,
            },
            "banco": {"literal": "CREDIBANCO", "requerido": False, "orden": 4},
            "forma_pago": {"literal": "DATAFONO", "requerido": False, "orden": 5},
            "ubicacion": {
                "regex": r"(?:ICA|CA)\s+[A-Z0-9][A-Z0-9 .\-]{3,45}",
                "requerido": False, "orden": 6,
            },
            "autenticacion": {
                "regex": r"AUT\s*:\s*([A-Z0-9]{3,15})",
                "requerido": False, "orden": 7,
            },
        },
    },
    {
        "codigo": "wompi-bancolombia",
        "nombre": "Wompi / Corresponsal Bancolombia",
        "detect_keywords": ["wompi", "corresponsal"],
        "llm_respaldo": True,
        "campos": {
            "valor_total": {
                "regex": r"Monto\s*:\s*\$?\s*([\d.,]{3,15})",
                "requerido": True, "orden": 1,
            },
            "fecha": {
                "regex": r"Fecha\s*:\s*([A-Za-z]{3}\s+\d{1,2}\s+\d{4})",
                "requerido": True, "orden": 2,
            },
            "numero_referencia": {
                "regex": r"Referencia\s*:\s*(\d{3,15})",
                "requerido": False, "orden": 3,
            },
            "convenio": {
                "regex": r"Convenio\.?\s*:?\s*(\d{3,15})",
                "requerido": False, "orden": 4,
            },
            "banco": {"literal": "BANCOLOMBIA", "requerido": False, "orden": 5},
            "forma_pago": {"literal": "CONSIGNACION", "requerido": False, "orden": 6},
            "ubicacion": {
                "regex": r"(?:cr\s+\d+[^\n]{4,60}|MULTIPAGOS\s+[A-Z0-9][A-Z0-9 .\-]{3,40}|calle\s+[^\n]{2,60})",
                "requerido": False, "orden": 7,
            },
        },
    },
    {
        "codigo": "redeban-bancolombia",
        "nombre": "Redeban / Bancolombia Multipagas",
        "detect_keywords": ["redeban", "multipagas"],
        "llm_respaldo": True,
        "campos": {
            "valor_total": {
                "regex": r"VALOR\s*\$?\s*([\d.,]{3,15})",
                "requerido": True, "orden": 1,
            },
            "fecha": {
                "regex": r"([A-Za-z]{3}\s+\d{1,2}\s+\d{4})",
                "requerido": True, "orden": 2,
            },
            "numero_referencia": {
                "regex": r"RECIBO\s*:\s*(\d{3,15})",
                "requerido": False, "orden": 3,
            },
            "convenio": {
                "regex": r"CONVENIO\s*:\s*(\d{3,15})",
                "requerido": False, "orden": 4,
            },
            "banco": {"literal": "BANCOLOMBIA", "requerido": False, "orden": 5},
            "forma_pago": {"literal": "CONSIGNACION", "requerido": False, "orden": 6},
            "ubicacion": {
                "regex": r"(?:cr\s*\d+[^\n]{2,60}|calle\s+[^\n]{2,60}|av\.?\s+[^\n]{2,60})",
                "requerido": False, "orden": 7,
            },
        },
    },
]
