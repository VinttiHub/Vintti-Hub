"""New opportunities by AM — count of new opps per window (Last week / WTD / Last month / MTD).

"AM" is interpreted as Lara today (the only Account Manager filtering opps via
`opp_sales_lead` / `opp_hr_lead` in the existing `lara_winrate_*` datasets).
The list is read from `DASHBOARD_AM_EMAILS` env var (comma-separated) and
falls back to `['lara@vintti.com']`.

The opportunity table has no real `created_at` column; the codebase uses
`COALESCE(nda_signature_or_start_date, opp_close_date)` as the "opened on"
proxy (see `recruiter_metrics_routes.py:486-489`). We follow the same
convention here.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta


_DEFAULT_AM_EMAILS = ("lara@vintti.com",)


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


def _am_emails() -> list[str]:
    raw = os.environ.get("DASHBOARD_AM_EMAILS", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(_DEFAULT_AM_EMAILS)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Ventanas de CALENDARIO (last week / WTD / last month / MTD) → siempre
    # relativas a HOY. NO siguen el filtro CORTE (solo las cards de 30d lo siguen).
    corte = datetime.utcnow().date()

    # Windows (consistent with sql_leads_windows._windows):
    #   last_week  = previous full calendar week (Mon-Sun)
    #   wtd        = this week's Monday → today
    #   last_month = previous full calendar month
    #   mtd        = 1st of this month → today
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
        WITH opps AS (
          SELECT
            COALESCE(
              NULLIF(o.nda_signature_or_start_date::text, '')::date,
              NULLIF(o.opp_close_date::text, '')::date
            ) AS opened_d
          FROM opportunity o
          WHERE o.opp_type = 'New'
            AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(am_emails)s)
        )
        SELECT
          %(corte)s::date AS corte,
          COUNT(*) FILTER (WHERE opened_d BETWEEN %(lw_ini)s::date AND %(lw_fin)s::date)::int
            AS opps_last_week,
          COUNT(*) FILTER (WHERE opened_d BETWEEN %(wt_ini)s::date AND %(wt_fin)s::date)::int
            AS opps_wtd,
          COUNT(*) FILTER (WHERE opened_d BETWEEN %(lm_ini)s::date AND %(lm_fin)s::date)::int
            AS opps_last_month,
          COUNT(*) FILTER (WHERE opened_d BETWEEN %(mt_ini)s::date AND %(mt_fin)s::date)::int
            AS opps_mtd
        FROM opps;
    """

    return sql, {
        "corte":     corte,
        "am_emails": _am_emails(),
        "lw_ini": lw_ini, "lw_fin": lw_fin,
        "wt_ini": wt_ini, "wt_fin": wt_fin,
        "lm_ini": lm_ini, "lm_fin": lm_fin,
        "mt_ini": mt_ini, "mt_fin": mt_fin,
    }


DATASET = {
    "key": "new_opps_am_windows",
    "label": "New opportunities by AM — por ventana",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "opps_last_week",  "label": "Last week",  "type": "number"},
        {"key": "opps_wtd",        "label": "WTD",        "type": "number"},
        {"key": "opps_last_month", "label": "Last month", "type": "number"},
        {"key": "opps_mtd",        "label": "MTD",        "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
