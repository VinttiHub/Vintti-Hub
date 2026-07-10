from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # One row per account (SQL) created in the current 30d window, with its channel
    # and whether it advanced to Deep Dive. Same definition as sql_to_deepdive_30d.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        -- R1: ancla SQL = fecha real del meeting (sql_meeting_date), estricto: solo cuentas con reunión real.
        SELECT
          TO_CHAR(a.sql_meeting_date, 'YYYY-MM-DD') AS sql_date,
          CASE
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'Sales'
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'Referrals'
            ELSE 'Marketing'
          END AS channel,
          a.client_name,
          COALESCE(NULLIF(TRIM(a.where_come_from), ''), 'NA') AS lead_source,
          CASE WHEN EXISTS (
            SELECT 1 FROM opportunity o
            WHERE o.account_id = a.account_id
              AND NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
          ) THEN 'Deep Dive' ELSE '—' END AS status
        FROM account a
        WHERE a.sql_meeting_date IS NOT NULL
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND a.sql_meeting_date BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND (%(desde)s::date IS NULL OR a.sql_meeting_date >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR a.sql_meeting_date <= %(hasta)s::date)
        ORDER BY channel, sql_date DESC, a.client_name;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_deepdive_30d_detail",
    "label": "SQL → Deep Dive — Detalle de SQLs (30d)",
    "dimensions": [
        {"key": "sql_date", "label": "SQL date", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cuenta", "type": "string"},
        {"key": "lead_source", "label": "Origen", "type": "string"},
        {"key": "status", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
