"""Ventana efectiva compartida para las cards de 30d.

Prioridad de filtros:  Desde/Hasta  >  Mes  >  rolling de `days` (default 30d).
  - Si hay Desde y/o Hasta → ese rango (Desde=apertura, Hasta=cierre; si falta uno
    se completa con un extremo abierto / el corte).
  - Si hay Mes (YYYY-MM) → el MES CALENDARIO COMPLETO (1ro al último día).
  - Si no hay nada → ventana rodante de `days` terminando en `corte` (hoy).

Default (sin filtros) == comportamiento histórico: (corte-(days-1), corte).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from ._now import today_ar


def _pd(value):
    if value is None or value == "":
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def window_bounds(filters: dict | None, days: int = 30) -> tuple[date, date]:
    filters = filters or {}
    corte = (_pd(filters.get("corte")) or _pd(filters.get("cutoff"))
             or _pd(filters.get("hasta")) or today_ar())  # R11: hoy en ARG (UTC-3)
    desde = _pd(filters.get("desde"))
    hasta = _pd(filters.get("hasta"))
    mes = _pd(filters.get("mes"))

    if desde or hasta:
        return (desde or date(1900, 1, 1)), (hasta or corte)
    if mes:
        first = date(mes.year, mes.month, 1)
        last = date(mes.year, mes.month, monthrange(mes.year, mes.month)[1])
        return first, last
    return corte - timedelta(days=days - 1), corte
