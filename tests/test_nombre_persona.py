from app.models.schemas import componer_nombre_persona, dividir_nombre_en_partes


def test_tipo_2_usa_razon_social():
    assert componer_nombre_persona(
        2,
        nombre_razon_social="EMPRESA PRUEBA SAS",
        primer_nombre="JUAN",
        primer_apellido="PEREZ",
    ) == "EMPRESA PRUEBA SAS"


def test_tipo_1_usa_nombres_y_apellidos():
    assert componer_nombre_persona(
        1,
        nombre_razon_social="IGNACIO BOHORQUEZ PAEZ",
        primer_nombre="IGNACIO",
        segundo_nombre=None,
        primer_apellido="BOHORQUEZ",
        segundo_apellido="PAEZ",
    ) == "IGNACIO BOHORQUEZ PAEZ"


def test_tipo_1_sin_partes_cae_a_razon():
    assert componer_nombre_persona(1, nombre_razon_social="SOLO NOMBRE") == "SOLO NOMBRE"


def test_dividir_nombre_tres_tokens():
    p = dividir_nombre_en_partes("IGNACIO BOHORQUEZ PAEZ")
    assert p["primer_nombre"] == "IGNACIO"
    assert p["segundo_nombre"] is None
    assert p["primer_apellido"] == "BOHORQUEZ"
    assert p["segundo_apellido"] == "PAEZ"


def test_dividir_nombre_dos_tokens():
    p = dividir_nombre_en_partes("MARIA GARCIA")
    assert p["primer_nombre"] == "MARIA"
    assert p["primer_apellido"] == "GARCIA"
    assert p["segundo_apellido"] is None


def test_parse_tercero_persona_natural_parte_nombre():
    from app.services.snri_client import SNRIClient

    class Item:
        Id = 312792
        NitCc = "93361223"
        Nombre = "IGNACIO  BOHORQUEZ PAEZ"
        Id_tipo_doc = "1"
        Tipo_Documento = "CEDULA"
        TIPO_PERSONA = "Personas Naturales"
        GRAN_CONTRIBUYENTE = "NO"
        AUTORRETENEDOR = "NO"
        REGIMEN_COMUN = "NO"
        REGIMEN_SIMPLIFICADO = "SI"
        ID_DEPARTAMENTO = "17"
        ID_CIUDAD = "1095"
        DireccionPrincipal = ""
        TELEFONO = "6017944492"
        EMAIL = "N/A"

    class Resp:
        Success = True
        Result = type("R", (), {"ConsultasE": [Item()]})()

    c = SNRIClient.__new__(SNRIClient)
    out = c._parse_tercero_response(Resp(), "93361223")
    assert out.success
    assert out.id_tipo_persona == 1
    assert out.primer_nombre == "IGNACIO"
    assert out.primer_apellido == "BOHORQUEZ"
    assert out.segundo_apellido == "PAEZ"
    assert componer_nombre_persona(
        out.id_tipo_persona,
        out.nombre_razon_social,
        out.primer_nombre,
        out.segundo_nombre,
        out.primer_apellido,
        out.segundo_apellido,
    ) == "IGNACIO BOHORQUEZ PAEZ"


def test_ui_expone_tipo_persona_y_nombres():
    from fastapi.testclient import TestClient
    from app.main import app

    r = TestClient(app).get("/")
    html = r.text
    assert "id_tipo_persona" in html
    assert "primer_apellido" in html
    assert "segundo_apellido" in html
    assert "Razón social" in html
    assert "nombreCompuesto" in html
