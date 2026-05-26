"""SQL → Close Win · funnel-rate, 30d (Mariano + Bahia).

Not a strict cohort — denominator and numerator are independent counts in
the same 30d window, both scoped to Mariano + Bahia (per Sales tab rule
[[project-sales-tab-filter]]):

  - Denominator (SQL): accounts whose `creation_date` falls in the window
    AND that have at least one M+B opp (matches `sql_to_nda_overall`).
  - Numerator (Close Win): M+B opportunities with `opp_stage='Close Win'`
    AND `opp_close_date` in the same window.
  - % = Close Win count / SQL count.

This is a rate, not a cohort: the Close Wins counted in 30d will usually
come from SQLs created earlier (NDA → CW cycle is multi-month). The metric
answers "how is the funnel performing right now — wins out vs new accounts
in?" rather than "what % of fresh SQLs already closed?".

Snapshot: last 30 days. Monthly history: each month evaluated independently.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta


SALES_LEADS_DEFAULT = ("mariano@vintti.com", "bahia@vintti.com")


def _sales_leads() -> list[str]:
    raw = os.environ.get("DASHBOARD_SALES_AES", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(SALES_LEADS_DEFAULT)


def _parse_date(value):
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


def _query_snapshot(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    win_ini = corte - timedelta(days=29)

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        ae_accounts AS (
          SELECT DISTINCT o.account_id
          FROM opportunity o
          WHERE TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            AND o.account_id IS NOT NULL
        ),
        sql_window AS (
          SELECT COUNT(*)::int AS sql_count
          FROM account a
          CROSS JOIN ventana v
          WHERE a.creation_date IS NOT NULL
            AND a.creation_date::date BETWEEN v.win_ini AND v.win_fin
            AND a.account_id IN (SELECT account_id FROM ae_accounts)
        ),
        cw_window AS (
          SELECT COUNT(*)::int AS close_win_count
          FROM opportunity o
          CROSS JOIN ventana v
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text, '')::date BETWEEN v.win_ini AND v.win_fin
            AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
        )
        SELECT
          (SELECT win_ini FROM ventana)                                                  AS ventana_desde,
          (SELECT win_fin FROM ventana)                                                  AS ventana_hasta,
          (SELECT sql_count FROM sql_window)                                             AS sql_count,
          (SELECT close_win_count FROM cw_window)                                        AS close_win_count,
          ROUND(
            CASE
              WHEN (SELECT sql_count FROM sql_window) = 0 THEN NULL
              ELSE 100.0 * (SELECT close_win_count FROM cw_window)::numeric
                          / NULLIF((SELECT sql_count FROM sql_window), 0)
            END, 2
          )::float                                                                       AS sql_to_close_win_pct;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH ae_accounts AS (
          SELECT DISTINCT o.account_id
          FROM opportunity o
          WHERE TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            AND o.account_id IS NOT NULL
        ),
        sql_by_month AS (
          SELECT
            DATE_TRUNC('month', a.creation_date)::date AS mes,
            COUNT(*)::int AS sql_count
          FROM account a
          WHERE a.creation_date IS NOT NULL
            AND a.account_id IN (SELECT account_id FROM ae_accounts)
          GROUP BY DATE_TRUNC('month', a.creation_date)
        ),
        cw_by_month AS (
          SELECT
            DATE_TRUNC('month', NULLIF(o.opp_close_date::text, '')::date)::date AS mes,
            COUNT(*)::int AS close_win_count
          FROM opportunity o
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
          GROUP BY DATE_TRUNC('month', NULLIF(o.opp_close_date::text, '')::date)
        ),
        meses AS (
          SELECT mes FROM sql_by_month
          UNION
          SELECT mes FROM cw_by_month
        )
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM-DD')                              AS mes,
          COALESCE(s.sql_count, 0)::int                             AS sql_count,
          COALESCE(c.close_win_count, 0)::int                       AS close_win_count,
          ROUND(
            CASE
              WHEN COALESCE(s.sql_count, 0) = 0 THEN NULL
              ELSE 100.0 * COALESCE(c.close_win_count, 0)::numeric
                          / NULLIF(s.sql_count, 0)
            END, 2
          )::float                                                  AS sql_to_close_win_pct
        FROM meses m
        LEFT JOIN sql_by_month s ON s.mes = m.mes
        LEFT JOIN cw_by_month  c ON c.mes = m.mes
        ORDER BY m.mes;
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "sql_to_close_win_snapshot",
    "label": "SQL → Close Win · rate 30d (Mariano + Bahia)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL (30d, M+B)", "type": "number"},
        {"key": "close_win_count", "label": "Close Wins (30d, M+B)", "type": "number"},
        {"key": "sql_to_close_win_pct", "label": "% Close Win / SQL", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sql_to_close_win_history",
    "label": "SQL → Close Win · monthly rate (Mariano + Bahia)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL in month (M+B)", "type": "number"},
        {"key": "close_win_count", "label": "Close Wins in month (M+B)", "type": "number"},
        {"key": "sql_to_close_win_pct", "label": "% Close Win / SQL", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
