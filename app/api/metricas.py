"""Métricas de operación (dashboard UI) calculadas desde la base de datos."""

from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_viewer
from app.core.rate_limit import limiter
from app.db.models import Comprobante, Factura, PerfilExtraccion
from app.db.session import get_db

router = APIRouter()


@router.get("/metricas")
@limiter.limit("30/minute")
async def metricas(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_viewer),
):
    por_status_rows = (await db.execute(
        select(Comprobante.status, func.count()).group_by(Comprobante.status)
    )).all()
    por_status = {status: int(n) for status, n in por_status_rows}

    hoy = date.today()
    desde_14 = hoy - timedelta(days=13)
    desde_30 = hoy - timedelta(days=29)

    hoy_n = int((await db.execute(
        select(func.count()).where(func.date(Comprobante.created_at) == hoy)
    )).scalar() or 0)

    facturas = int((await db.execute(select(func.count(Factura.id)))).scalar() or 0)
    facturas_hoy = int((await db.execute(
        select(func.count(Factura.id)).where(func.date(Factura.created_at) == hoy)
    )).scalar() or 0)

    confianza_avg, tiempo_avg = (await db.execute(
        select(
            func.avg(Comprobante.confianza_ocr),
            func.avg(func.extract("epoch", Comprobante.updated_at - Comprobante.created_at)),
        ).where(Comprobante.status == "completed")
    )).one()

    dias_rows = (await db.execute(
        select(
            func.date(Comprobante.created_at),
            Comprobante.status,
            func.count(),
        )
        .where(Comprobante.created_at >= desde_14)
        .group_by(func.date(Comprobante.created_at), Comprobante.status)
        .order_by(func.date(Comprobante.created_at))
    )).all()
    por_dia: dict = {}
    for dia, status, n in dias_rows:
        key = dia.isoformat() if hasattr(dia, "isoformat") else str(dia)
        bucket = por_dia.setdefault(key, {"fecha": key, "total": 0, "exitosos": 0})
        bucket["total"] += int(n)
        if status == "completed":
            bucket["exitosos"] += int(n)
    # completa días sin comprobantes (14 días)
    por_dia_lista = []
    for i in range(14):
        fecha = (desde_14 + timedelta(days=i))
        key = fecha.isoformat()
        por_dia_lista.append(por_dia.get(key, {"fecha": key, "total": 0, "exitosos": 0}))

    # agrupación en Python: perfil_id es VARCHAR en comprobantes e ID UUID en perfiles
    conteo_porperfil = (await db.execute(
        select(Comprobante.perfil_id, func.count()).group_by(Comprobante.perfil_id)
    )).all()
    perfiles_map = {
        p.id: p
        for p in (await db.execute(select(PerfilExtraccion))).scalars().all()
    }
    por_perfil: dict = {}
    for perfil_id, n in conteo_porperfil:
        perfil = perfiles_map.get(perfil_id)
        clave = perfil.codigo if perfil else "sin_perfil"
        bucket = por_perfil.setdefault(
            clave,
            {
                "codigo": clave,
                "nombre": perfil.nombre if perfil else "Sin perfil asignado",
                "total": 0,
            },
        )
        bucket["total"] += int(n)

    fallos_rows = (await db.execute(
        select(Comprobante.datos_extraidos)
        .where(
            Comprobante.datos_extraidos.is_not(None),
            Comprobante.created_at >= desde_30,
        )
        .limit(500)
    )).scalars().all()
    faltantes: Counter = Counter()
    for datos in fallos_rows:
        campos = (datos or {}).get("campos_perfil") or {}
        for campo in campos.get("_faltantes") or []:
            faltantes[campo] += 1

    total_comp = sum(por_status.values())
    exitosos = por_status.get("completed", 0)
    fallidos = por_status.get("failed", 0)

    return {
        "totales": {
            "comprobantes": total_comp,
            "hoy": hoy_n,
            "exitosos": exitosos,
            "fallidos": fallidos,
            "procesando": por_status.get("processing", 0),
            "tasa_exito_pct": round(100.0 * exitosos / total_comp, 1) if total_comp else None,
            "facturas": facturas,
            "facturas_hoy": facturas_hoy,
        },
        "calidad": {
            "confianza_promedio": round(float(confianza_avg or 0), 1),
            "tiempo_promedio_seg": round(float(tiempo_avg or 0), 1),
        },
        "por_dia": por_dia_lista,
        "por_perfil": sorted(por_perfil.values(), key=lambda p: -p["total"]),
        "campos_faltantes": [
            {"campo": campo, "veces": veces}
            for campo, veces in faltantes.most_common(8)
        ],
    }
