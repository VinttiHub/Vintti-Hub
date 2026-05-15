"""SQL → Close Win · cohort by account.creation_date (Mariano + Bahia).

Definition (following the user's Metabase patterns):
  - Universe / SQL:   accounts with `creation_date` populated that have at
                      least one opportunity assigned to Mariano or Bahia
                      (via `opp_hr_lead` OR `opp_sales_lead`).
  - Close Win reached: the account has at least one opp with
                      `opp_stage = 'Close Win'` AND `opp_close_date` is
                      populated AND `opp_close_date >= account.creation_date`
                      (date ordering check, matches the `sourcing_d >= nda_d`
                      pattern in the NDA → Sourcing query).

Snapshot (30d): cohort = accounts created in the last 30 days.
Monthly history: each month M is its own cohort (accounts created in M).
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


_BASE_CTE = """
        WITH ae_accounts AS (
          -- Accounts that have at least one opp owned by Mariano or Bahia
          -- (matched on opp_hr_lead OR opp_sales_lead — same as Metabase).
          SELECT DISTINCT o.account_id
          FROM opportunity o
          WHERE o.account_id IS NOT NULL
            AND (
              TRIM(LOWER(o.opp_hr_lead))    = ANY(%(sales_leads)s)
              OR TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            )
        ),
        base AS (
          SELECT
            a.account_id,
            a.creation_date::date AS sql_d,
            -- Earliest Close Win date among this account's opps (M+B only)
            (
              SELECT MIN(NULLIF(o.opp_close_date::text, '')::date)
              FROM opportunity o
              WHERE o.account_id = a.account_id
                AND TRIM(o.opp_stage) = 'Close Win'
                AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
                AND (
                  TRIM(LOWER(o.opp_hr_lead))    = ANY(%(sales_leads)s)
                  OR TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
                )
            ) AS close_win_d
          FROM account a
          JOIN ae_accounts aa ON aa.account_id = a.account_id
          WHERE a.creation_date IS NOT NULL
        )
"""


def _query_snapshot(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    win_ini = corte - timedelta(days=29)

    sql = _BASE_CTE + """
        SELECT
          %(win_ini)s::date                                                             AS ventana_desde,
          %(win_fin)s::date                                                             AS ventana_hasta,
          COUNT(*) FILTER (WHERE sql_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date)::int
                                                                                        AS sql_count,
          COUNT(*) FILTER (
            WHERE sql_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
              AND close_win_d IS NOT NULL
              AND close_win_d >= sql_d
          )::int                                                                        AS close_win_count,
          ROUND(
            CASE
              WHEN COUNT(*) FILTER (WHERE sql_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date) = 0
                THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE sql_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                  AND close_win_d IS NOT NULL
                  AND close_win_d >= sql_d
              )::numeric
              / NULLIF(COUNT(*) FILTER (WHERE sql_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date), 0)
            END, 2
          )::float                                                                      AS sql_to_close_win_pct
        FROM base;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = _BASE_CTE + """
        SELECT
          TO_CHAR(DATE_TRUNC('month', sql_d)::date, 'YYYY-MM-DD')                       AS mes,
          COUNT(*)::int                                                                  AS sql_count,
          COUNT(*) FILTER (
            WHERE close_win_d IS NOT NULL
              AND close_win_d >= sql_d
          )::int                                                                         AS close_win_count,
          ROUND(
            CASE
              WHEN COUNT(*) = 0 THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE close_win_d IS NOT NULL
                  AND close_win_d >= sql_d
              )::numeric
              / NULLIF(COUNT(*), 0)
            END, 2
          )::float                                                                       AS sql_to_close_win_pct
        FROM base
        GROUP BY DATE_TRUNC('month', sql_d)
        ORDER BY DATE_TRUNC('month', sql_d);
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
        {"key": "sql_count", "label": "Accounts created (30d, M+B)", "type": "number"},
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
        {"key": "sql_count", "label": "Accounts created in month", "type": "number"},
        {"key": "close_win_count", "label": "Of those, reached Close Win", "type": "number"},
        {"key": "sql_to_close_win_pct", "label": "% SQL → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
