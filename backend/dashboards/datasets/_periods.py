"""Ventana efectiva compartida para las cards de 30d.

Prioridad de filtros:  Desde/Hasta  >  Mes  >  rolling de `dias`/`days` (default 30d).
  - Si hay Desde y/o Hasta → ese rango (Desde=apertura, Hasta=cierre; si falta uno
    se completa con un extremo abierto / el corte).
  - Si hay Mes (YYYY-MM) → el MES CALENDARIO COMPLETO (1ro al último día).
  - Si no hay nada → ventana rodante terminando en `corte` (hoy), de largo
    `filters["dias"]` (o `days`) si viene, si no del `days` que pase el llamador.
    `dias` es un override genérico por filtro; hoy ningún chart lo setea (lo usaba el
    toggle 30/90/180 del funnel, ya retirado), pero se deja porque es la vía para
    pedir una ventana rodante distinta sin tocar los datasets.

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

    # Largo de la ventana rodante por filtro. Se ignora si hay Desde/Hasta o Mes,
    # que son más específicos.
    raw_dias = filters.get("dias", filters.get("days"))
    try:
        dias = int(str(raw_dias).strip())
    except (TypeError, ValueError):
        dias = None
    if dias and dias > 0:
        days = dias

    if desde or hasta:
        return (desde or date(1900, 1, 1)), (hasta or corte)
    if mes:
        first = date(mes.year, mes.month, 1)
        last = date(mes.year, mes.month, monthrange(mes.year, mes.month)[1])
        return first, last
    return corte - timedelta(days=days - 1), corte


def prev_window_bounds(filters: dict | None, days: int = 30) -> tuple[date, date]:
    """Ventana inmediatamente anterior, del MISMO largo que window_bounds().

    Antes cada dataset hardcodeaba `corte-59d .. corte-30d`, lo que solo era correcto
    con la ventana de 30d: con un rango Desde/Hasta de otro tamaño el delta comparaba
    contra un período que no correspondía. Esto la deriva del largo real de la ventana.
    """
    ini, fin = window_bounds(filters, days=days)
    largo = (fin - ini).days + 1
    return ini - timedelta(days=largo), ini - timedelta(days=1)
