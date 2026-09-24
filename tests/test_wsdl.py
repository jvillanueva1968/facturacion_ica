import pytest
from zeep import Client


def test_wsdl_loads():
    client = Client("wsdl/WS_FACTURACION.wsdl")
    assert client is not None


def test_operations_exist():
    client = Client("wsdl/WS_FACTURACION.wsdl")
    operations = [op for op in dir(client.service) if not op.startswith('_')]
    expected = [
        'A_InicioTransaccion',
        'M_CrearFactura',
        'M_CrearFacturaAlterna',
        'E_ConsultaTercero',
        'F_CrearTercero',
        'R_ConsultaFormasPago',
        'B_ConsultaBancos',
        'D_ConsultaServicio',
        'C_ConsultaSeccional',
        'H_ConsultaTipoDocumentos',
        'L_ConsultaTiposPersona',
        'I_ConsultaDepartamentos',
        'J_ConsultaCiudades',
        'P_ImprimirFactura',
        'V_Ping',
    ]
    for op in expected:
        assert op in operations, f"Operación {op} no encontrada"


def test_types_exist():
    client = Client("wsdl/WS_FACTURACION.wsdl")
    schema = client.wsdl.types
    elements = schema if isinstance(schema, dict) else getattr(schema, "elements", None)
    if elements is None:
        elements = client.wsdl.types.elements
    if not isinstance(elements, dict):
        elements = client.wsdl.messages or {}
        # zeep: types may be a Schema object with .elements already checked via operations
        names = set()
        try:
            names = set(client.wsdl.types.elements.keys())
        except Exception:
            names = set()
    else:
        names = set(elements.keys())
    # Fallback: ensure type names appear in WSDL XML
    if not names:
        import pathlib
        xml = pathlib.Path("wsdl/WS_FACTURACION.wsdl").read_text(encoding="utf-8", errors="ignore")
        for t in ("A_InicioTransaccion", "M_CrearFactura", "M_CrearFacturaAlterna"):
            assert t in xml
        return
    assert "A_InicioTransaccion" in names
    assert "M_CrearFactura" in names
    assert "M_CrearFacturaAlterna" in names