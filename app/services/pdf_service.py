from __future__ import annotations

import base64
from datetime import datetime, timezone


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def demo_pdf_base64(
    *,
    numero_factura: str,
    cufe: str = "",
    nit: str = "",
    razon_social: str = "",
    valor_total: str = "",
    fecha: str = "",
) -> str:
    now = fecha or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "FACTURA DE DEMOSTRACION - SNRI ICA (no valida fiscalmente)",
        f"Numero: {numero_factura}",
        f"CUFE: {cufe or 'N/A'}",
        f"NIT: {nit or 'N/A'}",
        f"Beneficiario: {razon_social or 'N/A'}",
        f"Valor total: {valor_total or 'N/A'}",
        f"Generado: {now}",
        "Modo SNRI_DEMO_MODE=true — reemplazar por P_ImprimirFactura en produccion.",
    ]
    content_ops = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
    for i, line in enumerate(lines):
        if i:
            content_ops.append("T*")
        content_ops.append(f"({_pdf_escape(line)}) Tj")
    content_ops.append("ET")
    stream = "\n".join(content_ops).encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode()
        out += body
        out += b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n"
    ).encode()
    return base64.b64encode(bytes(out)).decode("ascii")
