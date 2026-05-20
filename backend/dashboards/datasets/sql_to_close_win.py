"""SQL → Close Win · cohort by account.creation_date (ALL accounts).

Definition:
  - Universe / SQL:   every account with `creation_date` populated.
                      No AE / opp filter — all CRM accounts count.
  - Close Win reached: the account has at least one opp with
                      `opp_stage = 'Close Win'` AND `opp_close_date` is
                      populated AND `opp_close_date >= account.creation_date`
                      (date ordering check).

Snapshot (30d): cohort = accounts created in the last 30 days.
Monthly history: each month M is its own cohort (accounts created in M).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


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
        WITH base AS (
          SELECT
            a.account_id,
            a.creation_date::date AS sql_d,
            -- Earliest Close Win date among this account's opps (any AE)
            (
              SELECT MIN(NULLIF(o.opp_close_date::text, '')::date)
              FROM opportunity o
              WHERE o.account_id = a.account_id
                AND TRIM(o.opp_stage) = 'Close Win'
                AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            ) AS close_win_d
          FROM account a
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
    return sql, {"win_ini": win_ini, "win_fin": corte}


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
    return sql, {}


SNAPSHOT_DATASET = {
    "key": "sql_to_close_win_snapshot",
    "label": "SQL → Close Win · cohort 30d (all CRM accounts)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "Accounts created (30d)", "type": "number"},
        {"key": "close_win_count", "label": "Of those, reached Close Win", "type": "number"},
        {"key": "sql_to_close_win_pct", "label": "% SQL → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sql_to_close_win_history",
    "label": "SQL → Close Win · cohort by month (all CRM accounts)",
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
