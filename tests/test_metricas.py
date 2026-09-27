from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_endpoint_metricas_estructura():
    with client as c:
        r = c.get("/api/v1/metricas")
        assert r.status_code == 200, r.text
        j = r.json()
        for clave in ("totales", "calidad", "por_dia", "por_perfil", "campos_faltantes"):
            assert clave in j, f"falta {clave}"
        for clave in ("comprobantes", "hoy", "exitosos", "fallidos", "facturas",
                      "tasa_exito_pct"):
            assert clave in j["totales"]
        assert len(j["por_dia"]) == 14
        assert "confianza_promedio" in j["calidad"]
        assert "tiempo_promedio_seg" in j["calidad"]


def test_metrics_prometheus_disponible():
    with client as c:
        c.get("/health")
        r = c.get("/metrics")
        assert r.status_code == 200, r.text
        body = r.text
        assert "comprobantes_procesados_total" in body
        assert "llm_llamadas_total" in body
        assert "snri_llamadas_total" in body
        assert "http_requests_total" in body


def test_ui_boton_y_seccion_metricas():
    html = TestClient(app).get("/").text
    assert "📊 Métricas" in html
    assert "cargarMetricas" in html
    assert "toggleMetricas" in html
    assert 'x-show="metricas"' in html
    assert "kpi-grid" in html
    assert "barraPct" in html
    # los pasos del wizard deben ocultarse cuando la vista de métricas está activa
    assert 'x-show="!config && !metricas"' in html
    assert "!config && step===" not in html
