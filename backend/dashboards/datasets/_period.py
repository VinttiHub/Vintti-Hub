"""Helper de filtro de período para los charts que pueden ser all-time o por mes/rango.

Lee del filtro global del dashboard:
  - `mes` (YYYY-MM o YYYY-MM-DD) → ese mes completo. Tiene prioridad.
  - `desde` / `hasta` (YYYY-MM-DD) → ese rango (cualquiera de los dos opcional).
  - nada seteado → sin filtro (all-time, comportamiento por defecto).

`period_clause(filters, col)` devuelve un fragmento SQL (`" AND col >= ... AND col <= ..."`)
y sus params, listo para concatenar dentro de un WHERE. `col` debe ser una expresión
que ya resuelva a tipo date (castear afuera si la columna es varchar).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ._now import today_ar


def _parse_d(value):
    if not value:
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


def period_bounds(filters: dict) -> tuple[date | None, date | None]:
    """(desde, hasta) según el filtro global, o (None, None) si no hay período."""
    mes = _parse_d(filters.get("mes")) or _parse_d(filters.get("fecha"))
    if mes:
        ini = date(mes.year, mes.month, 1)
        nxt = date(mes.year + 1, 1, 1) if mes.month == 12 else date(mes.year, mes.month + 1, 1)
        return ini, nxt - timedelta(days=1)
    desde = _parse_d(filters.get("desde"))
    hasta = _parse_d(filters.get("hasta"))
    if desde or hasta:
        return desde, hasta
    return None, None


def monthly_range(filters: dict) -> tuple[date, date]:
    """Rango (lo, hi) para charts MENSUALES que pueden recortarse:
    Mes/Desde-Hasta > Corte (ventana rodante 30d) > YTD por defecto.
    Lo usan tanto las barras como sus detalles (para cruzar el mes clickeado)."""
    today = today_ar()  # R11: hoy en ARG (UTC-3)
    desde, hasta = period_bounds(filters)
    corte = _parse_d(filters.get("corte"))
    if desde or hasta:
        hi = hasta or today
        lo = desde or date(hi.year, 1, 1)
    elif corte:
        hi = corte
        lo = corte - timedelta(days=29)
    else:
        hi = today
        lo = date(hi.year, 1, 1)
    return lo, hi


def period_clause(filters: dict, col: str) -> tuple[str, dict]:
    """Fragmento ' AND <col> BETWEEN ...' (vacío si no hay período) + params."""
    desde, hasta = period_bounds(filters)
    clauses, params = [], {}
    if desde:
        clauses.append(f"{col} >= %(p_desde)s")
        params["p_desde"] = desde
    if hasta:
        clauses.append(f"{col} <= %(p_hasta)s")
        params["p_hasta"] = hasta
    return (" AND " + " AND ".join(clauses)) if clauses else "", params
