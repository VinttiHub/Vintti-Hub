"""SQL → NDA Sent · global, all-time (account-based).

Definition (as confirmed by user 2026-05-15):
  - Denominator (SQL): every account in the CRM `account` table.
  - Numerator   (NDA): accounts that have at least one opportunity with
                       `nda_signature_or_start_date` populated.
                       (No `nda_sent_date` field exists, so we use the
                       signed date as proxy for "NDA reached its target".)

Returns:
  - Snapshot (single row): all-time account-level ratio.
  - Monthly cumulative (rows by month):  at end of each month, what % of
    accounts that existed by then had signed an NDA.

This module exposes TWO datasets registered separately:
  - `sql_to_nda_overall_snapshot`  — single row, all-time KPI.
  - `sql_to_nda_overall_history`   — monthly cumulative time series.
"""
from __future__ import annotations


def _query_snapshot(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH all_accounts AS (
          SELECT COUNT(DISTINCT a.account_id)::int AS account_count
          FROM account a
        ),
        accounts_with_nda AS (
          SELECT COUNT(DISTINCT o.account_id)::int AS nda_accounts
          FROM opportunity o
          WHERE NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
            AND o.account_id IS NOT NULL
        )
        SELECT
          aa.account_count                                                            AS sql_count,
          awn.nda_accounts                                                            AS nda_sent_count,
          ROUND(
            CASE WHEN aa.account_count = 0 THEN NULL
                 ELSE 100.0 * awn.nda_accounts::numeric / aa.account_count END, 2
          )::float                                                                    AS sql_to_nda_sent_pct
        FROM all_accounts aa
        CROSS JOIN accounts_with_nda awn;
    """
    return sql, {}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Cumulative monthly view. For each month M, count:
    #   - accounts that "existed" by end of M (proxy: first opp_date in opportunity
    #     OR hubspot_synced_at — fall back to all accounts when no proxy date)
    #   - accounts whose first NDA signed date is <= end of M
    sql = """
        WITH account_first_seen AS (
          -- For each account, take the earliest date we can attach to it.
          -- Fallback: NULL → account exists in 'all time' bucket.
          SELECT
            a.account_id,
            LEAST(
              (SELECT MIN(NULLIF(o.nda_signature_or_start_date::text,'')::date)
               FROM opportunity o WHERE o.account_id = a.account_id),
              (SELECT MIN(NULLIF(o.opp_close_date::text,'')::date)
               FROM opportunity o WHERE o.account_id = a.account_id)
            ) AS first_seen_d
          FROM account a
        ),
        account_first_nda AS (
          SELECT
            o.account_id,
            MIN(NULLIF(o.nda_signature_or_start_date::text,'')::date) AS first_nda_d
          FROM opportunity o
          WHERE NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
            AND o.account_id IS NOT NULL
          GROUP BY o.account_id
        ),
        bounds AS (
          SELECT
            COALESCE(DATE_TRUNC('month', MIN(first_seen_d))::date,
                     DATE_TRUNC('month', CURRENT_DATE)::date) AS first_month,
            DATE_TRUNC('month', CURRENT_DATE)::date           AS last_month
          FROM account_first_seen
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS mes_fin
          FROM bounds b,
               generate_series(b.first_month, b.last_month, INTERVAL '1 month') gs
        )
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM-DD')                                                AS mes,
          (SELECT COUNT(*)::int FROM account_first_seen afs
           WHERE afs.first_seen_d IS NULL OR afs.first_seen_d <= m.mes_fin)           AS sql_count,
          (SELECT COUNT(*)::int FROM account_first_nda afn
           WHERE afn.first_nda_d <= m.mes_fin)                                        AS nda_sent_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM account_first_seen afs
                    WHERE afs.first_seen_d IS NULL OR afs.first_seen_d <= m.mes_fin) = 0
                THEN NULL
              ELSE 100.0
                   * (SELECT COUNT(*) FROM account_first_nda afn
                      WHERE afn.first_nda_d <= m.mes_fin)::numeric
                   / (SELECT COUNT(*) FROM account_first_seen afs
                      WHERE afs.first_seen_d IS NULL OR afs.first_seen_d <= m.mes_fin)
            END, 2
          )::float                                                                    AS sql_to_nda_sent_pct
        FROM meses m
        ORDER BY m.mes;
    """
    return sql, {}


SNAPSHOT_DATASET = {
    "key": "sql_to_nda_overall_snapshot",
    "label": "SQL → NDA Sent · global all-time (accounts CRM)",
    "dimensions": [],
    "measures": [
        {"key": "sql_count", "label": "Accounts in CRM", "type": "number"},
        {"key": "nda_sent_count", "label": "Accounts with NDA signed", "type": "number"},
        {"key": "sql_to_nda_sent_pct", "label": "% SQL → NDA Sent", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sql_to_nda_overall_history",
    "label": "SQL → NDA Sent · cumulative monthly (accounts CRM)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "Accounts (cum.)", "type": "number"},
        {"key": "nda_sent_count", "label": "Accounts with NDA (cum.)", "type": "number"},
        {"key": "sql_to_nda_sent_pct", "label": "% SQL → NDA Sent (cum.)", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

# Backward-compat alias so __init__.py can use DATASET.
DATASET = SNAPSHOT_DATASET
