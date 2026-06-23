"""Objetivo 2 · KR1 — SQLs generados por BDRs en la semana (#).

SQL = una cuenta entra al CRM (`account.creation_date`), misma definición que
`sql_leads_windows`. "Por BDRs" = origen Outbound (`where_come_from='outbound'`)
y owner AE (`account_manager` ∈ {Mariano, Bahía}). Ventana = semana calendario
COMPLETA previa (Lun–Dom). Devuelve también la semana en curso (WTD) y la
previa, como contexto.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def _parse_date(value):
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or datetime.utcnow().date())
    this_monday = corte - timedelta(days=corte.weekday())
    # `week` = lunes de la semana clickeada; default = semana en curso (Lun → corte).
    wk = _parse_date(filters.get("week"))
    if wk:
        week_ini = wk
        week_fin = min(wk + timedelta(days=6), corte)
    else:
        week_ini, week_fin = this_monday, corte

    sql = """
        SELECT
          COUNT(*)::int AS count,
          %(week_label)s::text AS week_label
        FROM account a
        WHERE a.sql_meeting_date IS NOT NULL  -- R1: ancla = meeting real
          AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
          AND LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(ae_leads)s
          AND a.sql_meeting_date BETWEEN %(week_ini)s::date AND %(week_fin)s::date;
    """
    return sql, {
        "ae_leads": AE_LEADS,
        "week_ini": week_ini, "week_fin": week_fin,
        "week_label": week_ini.strftime("%d/%m"),
    }


DATASET = {
    "key": "kr_sql_bdr_week",
    "label": "Obj2 KR1 · SQLs por BDRs (semana completa)",
    "dimensions": [],
    "measures": [
        {"key": "count", "label": "SQLs (semana)", "type": "number"},
    ],
    "dimensions_extra": [{"key": "week_label", "label": "Semana", "type": "string"}],
    "default_filters": {},
    "query": query,
}
