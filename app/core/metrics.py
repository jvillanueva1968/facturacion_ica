"""Métricas Prometheus del sistema (endpoint /metrics)."""

from prometheus_client import Counter, Histogram

PROCESAMIENTO_SEGUNDOS = Histogram(
    name="comprobante_procesamiento_segundos",
    documentation="Tiempo total de procesamiento de un comprobante (OCR + extraccion + NIT)",
    labelnames=["perfil"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0),
)

COMPROBANTES_TOTAL = Counter(
    name="comprobantes_procesados_total",
    documentation="Comprobantes procesados por estado final",
    labelnames=["status"],
)

EXTRACCIONES_TOTAL = Counter(
    name="extracciones_total",
    documentation="Extracciones ejecutadas por perfil de configuracion",
    labelnames=["perfil"],
)

LLM_LLAMADAS_TOTAL = Counter(
    name="llm_llamadas_total",
    documentation="Llamadas al LLM de extraccion de datos",
    labelnames=["resultado"],
)

SNRI_LLAMADAS_TOTAL = Counter(
    name="snri_llamadas_total",
    documentation="Consultas al servicio SNRI (validacion de NIT)",
    labelnames=["resultado"],
)


def observar_procesamiento(status: str, segundos: float, perfil: str = "ninguno") -> None:
    """Registra el resultado y duracion de un procesamiento de comprobante."""
    try:
        PROCESAMIENTO_SEGUNDOS.labels(perfil=perfil or "ninguno").observe(segundos)
        COMPROBANTES_TOTAL.labels(status=status).inc()
    except Exception:
        pass


def observar_extraccion(perfil: str) -> None:
    try:
        EXTRACCIONES_TOTAL.labels(perfil=perfil or "sin_perfil").inc()
    except Exception:
        pass


def observar_llm(resultado: str) -> None:
    try:
        LLM_LLAMADAS_TOTAL.labels(resultado=resultado).inc()
    except Exception:
        pass


def observar_snri(resultado: str) -> None:
    try:
        SNRI_LLAMADAS_TOTAL.labels(resultado=resultado).inc()
    except Exception:
        pass
