"""SQL → Close Win · cohort 30d (Mariano + Bahia).

Strict cohort:
  - Cohort (denominator): accounts whose `creation_date` falls in the
    window AND that have at least one M+B opportunity.
  - Numerator (Close Win reached): subset whose M+B opp(s) include at
    least one `opp_stage = 'Close Win'` with `opp_close_date` populated
    (any date — no upper bound, since CW cycles are multi-month).
  - % = Close Win cohort / SQL cohort.

Per Sales tab rule [[project-sales-tab-filter]] every CTE filters by
`opp_sales_lead` in (Mariano, Bahia).

Snapshot: cohort = accounts created in the last 30 days.
Monthly history: each month M is an independent cohort.

Field names (`sql_count`, `close_win_count`, `sql_to_close_win_pct`)
preserved so existing dashboard bindings keep working.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from ._now import today_ar


from ._sales_scope import sales_leads as _sales_leads


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
        or today_ar()
    )
    win_ini = corte - timedelta(days=29)

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        cohort AS (
          -- R1: ancla SQL = fecha real del meeting (sql_meeting_date), estricto: solo cuentas con reunión real.
          SELECT a.account_id
          FROM account a
          CROSS JOIN ventana v
          WHERE a.sql_meeting_date IS NOT NULL
            AND a.sql_meeting_date BETWEEN v.win_ini AND v.win_fin
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(a.account_manager)) = ANY(%(sales_leads)s)
        ),
        accounts_with_cw AS (
          SELECT DISTINCT o.account_id
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND o.account_id IS NOT NULL
        )
        SELECT
          (SELECT win_ini FROM ventana)                                                  AS ventana_desde,
          (SELECT win_fin FROM ventana)                                                  AS ventana_hasta,
          (SELECT COUNT(*)::int FROM cohort)                                             AS sql_count,
          (SELECT COUNT(*)::int FROM cohort c
           WHERE c.account_id IN (SELECT account_id FROM accounts_with_cw))              AS close_win_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.account_id IN (SELECT account_id FROM accounts_with_cw))::numeric
                / (SELECT COUNT(*) FROM cohort)
            END, 2
          )::float                                                                       AS sql_to_close_win_pct;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH accounts_with_cw AS (
          SELECT DISTINCT o.account_id
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND o.account_id IS NOT NULL
        ),
        cohort AS (
          -- R1: ancla SQL = fecha real del meeting (sql_meeting_date), estricto: solo cuentas con reunión real.
          SELECT
            a.account_id,
            DATE_TRUNC('month', a.sql_meeting_date)::date AS mes
          FROM account a
          WHERE a.sql_meeting_date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(a.account_manager)) = ANY(%(sales_leads)s)
        ),
        bounds AS (
          SELECT
            COALESCE(MIN(mes), DATE_TRUNC('month', CURRENT_DATE)::date) AS first_month,
            DATE_TRUNC('month', CURRENT_DATE)::date                    AS last_month
          FROM cohort
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM bounds b,
               generate_series(b.first_month, b.last_month, INTERVAL '1 month') gs
        )
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM-DD')                                                 AS mes,
          (SELECT COUNT(*)::int FROM cohort c WHERE c.mes = m.mes)                    AS sql_count,
          (SELECT COUNT(*)::int FROM cohort c
           WHERE c.mes = m.mes
             AND c.account_id IN (SELECT account_id FROM accounts_with_cw))           AS close_win_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.mes = m.mes
                     AND c.account_id IN (SELECT account_id FROM accounts_with_cw))::numeric
                / (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes)
            END, 2
          )::float                                                                     AS sql_to_close_win_pct
        FROM meses m
        ORDER BY m.mes;
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "sql_to_close_win_snapshot",
    "label": "SQL → Close Win · cohort 30d (Mariano + Bahia)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL (30d, M+B)", "type": "number"},
        {"key": "close_win_count", "label": "Of those, reached Close Win", "type": "number"},
        {"key": "sql_to_close_win_pct", "label": "% SQL → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sql_to_close_win_history",
    "label": "SQL → Close Win · cohort by month (Mariano + Bahia)",
    "dimensions": [
        {"key": "mes", "label": "Mes (creation_date)", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL in month (M+B)", "type": "number"},
        {"key": "close_win_count", "label": "Of those, reached Close Win", "type": "number"},
        {"key": "sql_to_close_win_pct", "label": "% SQL → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
