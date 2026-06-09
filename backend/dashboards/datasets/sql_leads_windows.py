"""SQL Sales — leads count by window (Last week / WTD / Last month / MTD).

Source: local CRM (`account` table). An account is considered an "SQL" the
moment it lands in the CRM, so we use `account.creation_date` as the SQL
event date. This is the same definition the Marketing tab uses.

Windows are aligned with `new_opps_am_windows` so both sides of the funnel
agree on what "Last week / WTD / Last month / MTD" mean.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


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
    # Ventanas de CALENDARIO (last week / WTD / last month / MTD) → siempre
    # relativas a HOY. NO siguen el filtro CORTE (solo las cards de 30d lo siguen).
    corte = datetime.utcnow().date()

    # Windows (mirror sql_leads_windows._windows):
    #   last_week  = previous full calendar week (Mon-Sun)
    #   wtd        = this week's Monday -> today
    #   last_month = previous full calendar month
    #   mtd        = 1st of this month -> today
    this_week_monday = corte - timedelta(days=corte.weekday())
    prev_week_sunday = this_week_monday - timedelta(days=1)
    prev_week_monday = prev_week_sunday - timedelta(days=6)

    month_start = corte.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    lw_ini, lw_fin = prev_week_monday, prev_week_sunday
    wt_ini, wt_fin = this_week_monday, corte
    lm_ini, lm_fin = last_month_start, last_month_end
    mt_ini, mt_fin = month_start,      corte

    sql = """
        SELECT
          %(corte)s::date AS corte,
          COUNT(*) FILTER (WHERE a.creation_date::date BETWEEN %(lw_ini)s::date AND %(lw_fin)s::date)::int
            AS sql_last_week,
          COUNT(*) FILTER (WHERE a.creation_date::date BETWEEN %(wt_ini)s::date AND %(wt_fin)s::date)::int
            AS sql_wtd,
          COUNT(*) FILTER (WHERE a.creation_date::date BETWEEN %(lm_ini)s::date AND %(lm_fin)s::date)::int
            AS sql_last_month,
          COUNT(*) FILTER (WHERE a.creation_date::date BETWEEN %(mt_ini)s::date AND %(mt_fin)s::date)::int
            AS sql_mtd
        FROM account a
        WHERE a.creation_date IS NOT NULL
          AND a.creation_date::date >= LEAST(%(lw_ini)s::date, %(lm_ini)s::date);
    """

    return sql, {
        "corte": corte,
        "lw_ini": lw_ini, "lw_fin": lw_fin,
        "wt_ini": wt_ini, "wt_fin": wt_fin,
        "lm_ini": lm_ini, "lm_fin": lm_fin,
        "mt_ini": mt_ini, "mt_fin": mt_fin,
    }


DATASET = {
    "key": "sql_leads_windows",
    "label": "SQL Sales — Leads por ventana (CRM accounts)",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "sql_last_week",  "label": "Last week",  "type": "number"},
        {"key": "sql_wtd",        "label": "WTD",        "type": "number"},
        {"key": "sql_last_month", "label": "Last month", "type": "number"},
        {"key": "sql_mtd",        "label": "MTD",        "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
