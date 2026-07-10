"""Sourcing → Close Win · cohort by opp.nda_signature_or_start_date (M+B only).

Definition (per user 2026-05-20):
  - Universe / cohort:  opps with `nda_signature_or_start_date` populated
                        AND `opp_hr_lead` OR `opp_sales_lead` in
                        (mariano@vintti.com, bahia@vintti.com).
  - Close Win reached:  the opp has `opp_stage = 'Close Win'` AND
                        `opp_close_date IS NOT NULL` AND
                        `opp_close_date >= nda_signature_or_start_date`
                        (date ordering check).

Snapshot (30d): cohort = opps whose NDA was signed in the last 30 days.
Monthly history: each month M is its own cohort (opps with NDA signed in M).
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


_BASE_CTE = """
        WITH base AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            TRIM(o.opp_stage) AS opp_stage,
            NULLIF(o.nda_signature_or_start_date::text, '')::date AS nda_d,
            NULLIF(o.opp_close_date::text, '')::date              AS close_d
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE o.opportunity_id IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
            AND (
              TRIM(LOWER(o.opp_hr_lead))    = ANY(%(sales_leads)s)
              OR TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            )
        )
"""


def _query_snapshot(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    win_ini = corte - timedelta(days=29)

    sql = _BASE_CTE + """
        SELECT
          %(win_ini)s::date                                                             AS ventana_desde,
          %(win_fin)s::date                                                             AS ventana_hasta,
          COUNT(*) FILTER (WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date)::int
                                                                                        AS nda_signed_count,
          COUNT(*) FILTER (
            WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
              AND opp_stage = 'Close Win'
              AND close_d IS NOT NULL
              AND close_d >= nda_d
          )::int                                                                        AS close_win_count,
          COUNT(*) FILTER (
            WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
              AND opp_stage = 'Closed Lost'
              AND close_d IS NOT NULL
              AND close_d >= nda_d
          )::int                                                                        AS closed_lost_count,
          -- Kept for backward-compat with the old binding name `sourcing_count`.
          COUNT(*) FILTER (
            WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
              AND opp_stage = 'Close Win'
              AND close_d IS NOT NULL
              AND close_d >= nda_d
          )::int                                                                        AS sourcing_count,
          ROUND(
            CASE
              WHEN COUNT(*) FILTER (WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date) = 0
                THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                  AND opp_stage = 'Close Win'
                  AND close_d IS NOT NULL
                  AND close_d >= nda_d
              )::numeric
              / NULLIF(COUNT(*) FILTER (WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date), 0)
            END, 2
          )::float                                                                      AS sourcing_to_close_win_pct
        FROM base;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = _BASE_CTE + """
        SELECT
          TO_CHAR(DATE_TRUNC('month', nda_d)::date, 'YYYY-MM-DD')                       AS mes,
          COUNT(*)::int                                                                  AS nda_signed_count,
          COUNT(*) FILTER (
            WHERE opp_stage = 'Close Win'
              AND close_d IS NOT NULL
              AND close_d >= nda_d
          )::int                                                                         AS close_win_count,
          COUNT(*) FILTER (
            WHERE opp_stage = 'Closed Lost'
              AND close_d IS NOT NULL
              AND close_d >= nda_d
          )::int                                                                         AS closed_lost_count,
          COUNT(*) FILTER (
            WHERE opp_stage = 'Close Win'
              AND close_d IS NOT NULL
              AND close_d >= nda_d
          )::int                                                                         AS sourcing_count,
          ROUND(
            CASE
              WHEN COUNT(*) = 0 THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE opp_stage = 'Close Win'
                  AND close_d IS NOT NULL
                  AND close_d >= nda_d
              )::numeric
              / NULLIF(COUNT(*), 0)
            END, 2
          )::float                                                                       AS sourcing_to_close_win_pct
        FROM base
        GROUP BY DATE_TRUNC('month', nda_d)
        ORDER BY DATE_TRUNC('month', nda_d);
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "sourcing_to_close_win_snapshot",
    "label": "Sourcing → Close Win · cohort 30d (M+B, NDA-signed opps)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "nda_signed_count", "label": "NDA-signed opps (in window)", "type": "number"},
        {"key": "close_win_count", "label": "Of those, reached Close Win", "type": "number"},
        {"key": "closed_lost_count", "label": "Of those, Closed Lost", "type": "number"},
        {"key": "sourcing_to_close_win_pct", "label": "% NDA-signed → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sourcing_to_close_win_history",
    "label": "Sourcing → Close Win · cohort by month (M+B, NDA-signed opps)",
    "dimensions": [
        {"key": "mes", "label": "Mes (nda_signature_or_start_date)", "type": "date"},
    ],
    "measures": [
        {"key": "nda_signed_count", "label": "NDA-signed opps in month", "type": "number"},
        {"key": "close_win_count", "label": "Of those, reached Close Win", "type": "number"},
        {"key": "closed_lost_count", "label": "Of those, Closed Lost", "type": "number"},
        {"key": "sourcing_to_close_win_pct", "label": "% NDA-signed → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
