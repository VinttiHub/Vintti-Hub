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

    # SQL → Deep Dive conversion. "SQL generada" = account created (account.creation_date),
    # channel = account.where_come_from (Outbound→Sales, Referral→Referrals, resto→Marketing).
    # "Avanzó a Deep Dive" = la account tiene al menos una opp con deep_dive_date no nulo.
    # Window = fecha de creación de la account (cohorte). Delta vs los 30d previos.
    # M+B: account.account_manager ∈ (mariano, bahia) — owner a nivel account.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH acc AS (
          -- R1: ancla SQL = fecha real del meeting (sql_meeting_date), estricto: solo cuentas con reunión real.
          SELECT
            a.account_id,
            a.sql_meeting_date AS sql_d,
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            EXISTS (
              SELECT 1 FROM opportunity o
              WHERE o.account_id = a.account_id
                AND NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
            ) AS reached_dd
          FROM account a
          WHERE a.sql_meeting_date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
            AND (%(desde)s::date IS NULL OR a.sql_meeting_date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR a.sql_meeting_date <= %(hasta)s::date)
        ),
        cur AS (
          SELECT * FROM acc
          WHERE sql_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ),
        prev_rate AS (
          SELECT ROUND(
            COUNT(*) FILTER (WHERE reached_dd)::numeric * 100.0 / NULLIF(COUNT(*), 0), 1
          ) AS prev_total_pct
          FROM acc
          WHERE sql_d BETWEEN (%(corte)s::date - INTERVAL '59 days')::date
                          AND (%(corte)s::date - INTERVAL '30 days')::date
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales')::int                       AS sales_sqls,
          COUNT(*) FILTER (WHERE channel='sales' AND reached_dd)::int        AS sales_dd,
          ROUND(COUNT(*) FILTER (WHERE channel='sales' AND reached_dd)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1)     AS sales_pct,

          COUNT(*) FILTER (WHERE channel='marketing')::int                   AS mkt_sqls,
          COUNT(*) FILTER (WHERE channel='marketing' AND reached_dd)::int    AS mkt_dd,
          ROUND(COUNT(*) FILTER (WHERE channel='marketing' AND reached_dd)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1) AS mkt_pct,

          COUNT(*) FILTER (WHERE channel='referrals')::int                   AS ref_sqls,
          COUNT(*) FILTER (WHERE channel='referrals' AND reached_dd)::int    AS ref_dd,
          ROUND(COUNT(*) FILTER (WHERE channel='referrals' AND reached_dd)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1) AS ref_pct,

          COUNT(*)::int                              AS total_sqls,
          COUNT(*) FILTER (WHERE reached_dd)::int    AS total_dd,
          ROUND(COUNT(*) FILTER (WHERE reached_dd)::numeric * 100.0
                / NULLIF(COUNT(*), 0), 1)            AS total_pct,
          pr.prev_total_pct,
          ROUND(
            COUNT(*) FILTER (WHERE reached_dd)::numeric * 100.0 / NULLIF(COUNT(*), 0)
            - COALESCE(pr.prev_total_pct, 0), 1
          ) AS total_pct_delta
        FROM cur
        CROSS JOIN prev_rate pr
        GROUP BY pr.prev_total_pct;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_deepdive_30d",
    "label": "SQL → Deep Dive por canal (30d)",
    "dimensions": [],
    "measures": [
        {"key": "sales_sqls", "label": "Sales · SQLs", "type": "number"},
        {"key": "sales_dd", "label": "Sales · Deep Dive", "type": "number"},
        {"key": "sales_pct", "label": "Sales · SQL→DD %", "type": "percent"},
        {"key": "mkt_sqls", "label": "Marketing · SQLs", "type": "number"},
        {"key": "mkt_dd", "label": "Marketing · Deep Dive", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · SQL→DD %", "type": "percent"},
        {"key": "ref_sqls", "label": "Referrals · SQLs", "type": "number"},
        {"key": "ref_dd", "label": "Referrals · Deep Dive", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · SQL→DD %", "type": "percent"},
        {"key": "total_sqls", "label": "Total · SQLs", "type": "number"},
        {"key": "total_dd", "label": "Total · Deep Dive", "type": "number"},
        {"key": "total_pct", "label": "Total · SQL→DD %", "type": "percent"},
        {"key": "prev_total_pct", "label": "Total · SQL→DD % (30d previos)", "type": "percent"},
        {"key": "total_pct_delta", "label": "Total · Δ SQL→DD (pp)", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
