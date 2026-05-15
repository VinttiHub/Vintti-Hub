"""SQL → NDA Sent · cohort by account.creation_date.

Definition (per user 2026-05-15):
  - For each month M, cohort = accounts with `creation_date` in M.
  - Of those cohort accounts, how many have an associated opportunity
    with `nda_signature_or_start_date` populated (at any point in time).
  - % = NDA-signed cohort / total cohort.

Snapshot (30d): cohort = accounts with creation_date in last 30 days.
Monthly history: each month is its own cohort (NOT cumulative).
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
        cohort AS (
          SELECT a.account_id
          FROM account a
          CROSS JOIN ventana v
          WHERE a.creation_date IS NOT NULL
            AND a.creation_date::date BETWEEN v.win_ini AND v.win_fin
        ),
        accounts_with_nda AS (
          SELECT DISTINCT account_id
          FROM opportunity
          WHERE NULLIF(nda_signature_or_start_date::text, '') IS NOT NULL
            AND account_id IS NOT NULL
        )
        SELECT
          (SELECT win_ini FROM ventana)                                  AS ventana_desde,
          (SELECT win_fin FROM ventana)                                  AS ventana_hasta,
          (SELECT COUNT(*)::int FROM cohort)                             AS sql_count,
          (SELECT COUNT(*)::int FROM cohort c
           WHERE c.account_id IN (SELECT account_id FROM accounts_with_nda))
                                                                         AS nda_sent_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.account_id IN (SELECT account_id FROM accounts_with_nda))::numeric
                / (SELECT COUNT(*) FROM cohort)
            END, 2
          )::float                                                       AS sql_to_nda_sent_pct;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH accounts_with_nda AS (
          SELECT DISTINCT account_id
          FROM opportunity
          WHERE NULLIF(nda_signature_or_start_date::text, '') IS NOT NULL
            AND account_id IS NOT NULL
        ),
        cohort AS (
          SELECT
            a.account_id,
            DATE_TRUNC('month', a.creation_date)::date AS mes
          FROM account a
          WHERE a.creation_date IS NOT NULL
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
             AND c.account_id IN (SELECT account_id FROM accounts_with_nda))           AS nda_sent_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.mes = m.mes
                     AND c.account_id IN (SELECT account_id FROM accounts_with_nda))::numeric
                / (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes)
            END, 2
          )::float                                                                     AS sql_to_nda_sent_pct
        FROM meses m
        ORDER BY m.mes;
    """
    return sql, {}


SNAPSHOT_DATASET = {
    "key": "sql_to_nda_overall_snapshot",
    "label": "SQL → NDA Sent · cohort (accounts created in last 30d)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "Accounts created (30d)", "type": "number"},
        {"key": "nda_sent_count", "label": "Of those, signed NDA", "type": "number"},
        {"key": "sql_to_nda_sent_pct", "label": "% SQL → NDA Sent", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sql_to_nda_overall_history",
    "label": "SQL → NDA Sent · cohort by month (creation_date)",
    "dimensions": [
        {"key": "mes", "label": "Mes (creation_date)", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "Accounts created in month", "type": "number"},
        {"key": "nda_sent_count", "label": "Of those, signed NDA", "type": "number"},
        {"key": "sql_to_nda_sent_pct", "label": "% SQL → NDA Sent", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
