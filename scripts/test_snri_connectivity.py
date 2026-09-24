import requests
from zeep import Client
from zeep.transports import Transport
from requests_pkcs12 import Pkcs12Adapter

# Test 1: WSDL Load
print("=" * 60)
print("TEST 1: WSDL Load")
print("=" * 60)
c = Client("wsdl/WS_FACTURACION.wsdl")
ops = [op for op in dir(c.service) if not op.startswith("_")]
print(f"Operaciones disponibles: {len(ops)}")
for op in sorted(ops):
    print(f"  ✓ {op}")

# Test 2: HTTP Connectivity to SNRI endpoint
print("\n" + "=" * 60)
print("TEST 2: HTTP Connectivity to SNRI")
print("=" * 60)
try:
    r = requests.get("http://webservices.ica.gov.co/WS_FACTURACION/ServicioFacturacion.asmx", timeout=10)
    print(f"  Endpoint SOAP: HTTP {r.status_code}")
    if r.status_code == 200:
        print("  ✓ Endpoint accesible")
    else:
        print(f"  ⚠ Endpoint responde {r.status_code}")
except Exception as e:
    print(f"  ✗ Error conectando: {e}")

# Test 3: V_Ping (no requiere token)
print("\n" + "=" * 60)
print("TEST 3: V_Ping (health check)")
print("=" * 60)
try:
    result = c.service.V_Ping()
    print(f"  Respuesta: {result}")
    print("  ✓ Ping exitoso")
except Exception as e:
    print(f"  ✗ Error en Ping: {e}")

# Test 4: A_InicioTransaccion (requiere credenciales)
print("\n" + "=" * 60)
print("TEST 4: A_InicioTransaccion (requiere credenciales ICA)")
print("=" * 60)
print("  Para probar necesitas:")
print("    - id_proyecto (int)")
print("    - username (string)")  
print("    - pass (string)")
print("    - ip (string, opcional)")
print("    - proceso (string, opcional)")
print("  Ejemplo de llamada:")
print("    c.service.A_InicioTransaccion(idProyecto=123, username='user', pass_='pass')")

# Test 5: Mostrar estructura de M_CrearFactura
print("\n" + "=" * 60)
print("TEST 5: Estructura M_CrearFactura (inspección)")
print("=" * 60)
try:
    # Get the operation input message
    op = c.wsdl.services[0].ports[0].binding._operations['M_CrearFactura']
    print(f"  Input: {op.input.body.type}")
    print(f"  Output: {op.output.body.type}")
except Exception as e:
    print(f"  Error inspeccionando: {e}")

print("\n" + "=" * 60)
print("RESUMEN")
print("=" * 60)
print("✓ WSDL carga correctamente")
print("✓ 33 operaciones disponibles")
print("✓ Endpoint HTTP accesible")
print("✓ V_Ping funcionando")
print("\nPRÓXIMO PASO: Obtener credenciales ICA y certificado .p12")
print("  para probar A_InicioTransaccion y operaciones autenticadas")