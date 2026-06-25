"""Obj2 KR1 detalle · SQLs outbound creados en la semana completa previa (Lun–Dom)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar


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
             or today_ar())
    this_monday = corte - timedelta(days=corte.weekday())
    # `week` = lunes de la semana clickeada; default = semana en curso (Lun → corte).
    wk = _parse_date(filters.get("week"))
    if wk:
        week_ini, week_fin = wk, min(wk + timedelta(days=6), corte)
    else:
        week_ini, week_fin = this_monday, corte

    sql = """
        -- R1: ancla SQL = fecha real del meeting (sql_meeting_date), estricto: solo cuentas con reunión real.
        SELECT
          a.client_name,
          TO_CHAR(a.sql_meeting_date, 'YYYY-MM-DD') AS creation_date,
          COALESCE(a.account_manager, '')              AS account_manager
        FROM account a
        WHERE a.sql_meeting_date IS NOT NULL
          AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
          AND LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(ae_leads)s
          AND a.sql_meeting_date BETWEEN %(week_ini)s::date AND %(week_fin)s::date
        ORDER BY creation_date DESC, a.client_name;
    """
    return sql, {"ae_leads": AE_LEADS, "week_ini": week_ini, "week_fin": week_fin}


DATASET = {
    "key": "kr_sql_bdr_week_detail",
    "label": "Obj2 KR1 detalle · SQLs outbound (semana)",
    "dimensions": [
        {"key": "client_name", "label": "Cuenta", "type": "string"},
        {"key": "creation_date", "label": "Creación (SQL)", "type": "date"},
        {"key": "account_manager", "label": "Owner", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
