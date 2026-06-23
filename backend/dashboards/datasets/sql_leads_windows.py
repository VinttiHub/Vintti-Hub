"""SQL Sales — leads count by window (Last week / WTD / Last month / MTD).

Source: local CRM (`account` table). SQL SALES = solo Outbound (where_come_from =
'outbound') y owner ∈ {Mariano, Bahía} — los SQL generados por Sales, no inbound. El
SQL se ancla ESTRICTO por la fecha REAL del meeting (`account.sql_meeting_date`, =
meeting_date___time de HubSpot): solo cuentan las que tuvieron la reunión de calificación
(sin fallback a creation_date). (Antes contaba TODAS las cuentas por creation_date crudo,
sin filtrar canal/owner.) Ver audit R1.

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

    # SQL SALES = solo Outbound (los SQL generados por Sales, no inbound/marketing) y
    # owner ∈ {Mariano, Bahía} (regla del tab Sales). Ancla = fecha real del meeting
    # (sql_meeting_date), estricto: solo cuentas con reunión real.
    sql = """
        WITH sql_acc AS (
          SELECT a.sql_meeting_date AS sql_d
          FROM account a
          WHERE a.sql_meeting_date IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
            AND LOWER(TRIM(COALESCE(a.account_manager, ''))) IN ('mariano@vintti.com', 'bahia@vintti.com')
        )
        SELECT
          %(corte)s::date AS corte,
          COUNT(*) FILTER (WHERE sql_d BETWEEN %(lw_ini)s::date AND %(lw_fin)s::date)::int
            AS sql_last_week,
          COUNT(*) FILTER (WHERE sql_d BETWEEN %(wt_ini)s::date AND %(wt_fin)s::date)::int
            AS sql_wtd,
          COUNT(*) FILTER (WHERE sql_d BETWEEN %(lm_ini)s::date AND %(lm_fin)s::date)::int
            AS sql_last_month,
          COUNT(*) FILTER (WHERE sql_d BETWEEN %(mt_ini)s::date AND %(mt_fin)s::date)::int
            AS sql_mtd
        FROM sql_acc
        WHERE sql_d >= LEAST(%(lw_ini)s::date, %(lm_ini)s::date);
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
