from __future__ import annotations

from datetime import date, datetime


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
        or datetime.utcnow().date()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # SQL → Close Win (funnel completo). "SQL" = account creada (creation_date) en la
    # ventana, con account_manager ∈ M+B (mismo criterio que SQL→Deep Dive y
    # sql_funnel_30d_detail). Numerador = la account tiene una opp en Close Win.
    # Canal = where_come_from. Window por creation_date.
    sql = """
        WITH acc AS (
          SELECT
            a.account_id,
            a.creation_date AS sql_d,
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            EXISTS (
              SELECT 1 FROM opportunity o
              WHERE o.account_id = a.account_id AND TRIM(o.opp_stage) = 'Close Win'
            ) AS won
          FROM account a
          WHERE a.creation_date IS NOT NULL
            AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
            AND (%(desde)s::date IS NULL OR a.creation_date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR a.creation_date <= %(hasta)s::date)
        ),
        cur AS (
          SELECT * FROM acc
          WHERE sql_d BETWEEN (%(corte)s::date - INTERVAL '29 days')::date AND %(corte)s::date
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales')::int             AS sales_sql,
          COUNT(*) FILTER (WHERE channel='sales' AND won)::int     AS sales_win,
          ROUND(COUNT(*) FILTER (WHERE channel='sales' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1) AS sales_pct,

          COUNT(*) FILTER (WHERE channel='marketing')::int            AS mkt_sql,
          COUNT(*) FILTER (WHERE channel='marketing' AND won)::int    AS mkt_win,
          ROUND(COUNT(*) FILTER (WHERE channel='marketing' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1) AS mkt_pct,

          COUNT(*) FILTER (WHERE channel='referrals')::int            AS ref_sql,
          COUNT(*) FILTER (WHERE channel='referrals' AND won)::int    AS ref_win,
          ROUND(COUNT(*) FILTER (WHERE channel='referrals' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1) AS ref_pct,

          COUNT(*)::int                       AS total_sql,
          COUNT(*) FILTER (WHERE won)::int     AS total_win,
          ROUND(COUNT(*) FILTER (WHERE won)::numeric * 100.0
                / NULLIF(COUNT(*), 0), 1)     AS total_pct
        FROM cur;
    """

    return sql, {"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_clientwin_30d",
    "label": "SQL → Close Win (funnel completo, 30d, AE)",
    "dimensions": [],
    "measures": [
        {"key": "sales_sql", "label": "Sales · SQLs", "type": "number"},
        {"key": "sales_win", "label": "Sales · Close Win", "type": "number"},
        {"key": "sales_pct", "label": "Sales · SQL→Win %", "type": "percent"},
        {"key": "mkt_sql", "label": "Marketing · SQLs", "type": "number"},
        {"key": "mkt_win", "label": "Marketing · Close Win", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · SQL→Win %", "type": "percent"},
        {"key": "ref_sql", "label": "Referrals · SQLs", "type": "number"},
        {"key": "ref_win", "label": "Referrals · Close Win", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · SQL→Win %", "type": "percent"},
        {"key": "total_sql", "label": "Total · SQLs", "type": "number"},
        {"key": "total_win", "label": "Total · Close Win", "type": "number"},
        {"key": "total_pct", "label": "Total · SQL→Win %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
