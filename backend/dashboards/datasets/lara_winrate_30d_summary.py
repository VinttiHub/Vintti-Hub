from __future__ import annotations

from datetime import date, datetime


LARA_EMAIL = "lara@vintti.com"


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


def _norm_stage(value) -> str:
    if not value:
        return "Close Win"
    raw = str(value).strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Close Win"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    stage = _norm_stage(filters.get("opp_stage"))

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date                                AS cutoff_d,
            (%(corte)s::date - INTERVAL '30 days')::date   AS win_ini,
            %(corte)s::date                                AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            TRIM(o.opp_stage) AS opp_stage,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          CROSS JOIN ventana v
          WHERE o.opportunity_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND (
              TRIM(LOWER(o.opp_sales_lead)) = %(lara)s
              OR TRIM(LOWER(o.opp_hr_lead)) = %(lara)s
            )
            AND NULLIF(o.opp_close_date::text, '')::date BETWEEN v.win_ini AND v.win_fin
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text, '')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text, '')::date <= %(hasta)s::date)
        )
        SELECT
          TO_CHAR(MIN(v.cutoff_d), 'YYYY-MM-DD')                                     AS cutoff,
          COUNT(*)::int                                                              AS total_closed,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int                       AS close_win,
          COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::int                     AS closed_lost,
          ROUND(
            CASE
              WHEN %(stage)s = 'Closed Lost' THEN
                100.0 * COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::numeric
                / NULLIF(COUNT(*), 0)
              ELSE
                100.0 * COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::numeric
                / NULLIF(COUNT(*), 0)
            END,
            2
          )::float                                                                   AS conversion_30d_pct
        FROM base
        CROSS JOIN ventana v;
    """

    return sql, {
        "lara": LARA_EMAIL,
        "corte": corte,
        "desde": desde,
        "hasta": hasta,
        "stage": stage,
    }


DATASET = {
    "key": "lara_winrate_30d_summary",
    "label": "Win Rate Re contrataciones (Lara) — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "total_closed", "label": "Total cerradas", "type": "number"},
        {"key": "close_win", "label": "Close Win", "type": "number"},
        {"key": "closed_lost", "label": "Closed Lost", "type": "number"},
        {"key": "conversion_30d_pct", "label": "Conversión 30d %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
