from zeep import Client

c = Client("wsdl/WS_FACTURACION.wsdl")
ops = [op for op in dir(c.service) if not op.startswith("_")]
print(f"Operaciones ({len(ops)}):")
for op in sorted(ops):
    print(f"  - {op}")
# Acceder a los elementos del schema correctamente
elements = c.wsdl.types.schemas[0].elements if hasattr(c.wsdl.types, 'schemas') and c.wsdl.types.schemas else {}
print(f"\nTipos en schema: {len(elements)}")
print("\nPrimeros 15 tipos:")
for k in list(elements.keys())[:15]:
    print(f"  - {k}")