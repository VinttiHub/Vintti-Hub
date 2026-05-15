"""Sourcing → Close Win · cohort by sourcing.since_sourcing month (M+B).

Definition (per user 2026-05-15):
  - Denominator: opps that appear in the `sourcing` table
                 AND `opp_sales_lead IN (Mariano, Bahia)` in opportunity.
  - Numerator:   subset of those opps where `opp_close_date` is populated
                 AND `opp_stage = 'Close Win'`.

Snapshot (30d): cohort = opps whose `sourcing.since_sourcing` falls in
the last 30 days.

Monthly history: each month M is its own cohort (opps that entered
Sourcing in month M). NOT cumulative.
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
        cohort AS (
          SELECT DISTINCT s.opportunity_id
          FROM sourcing s
          JOIN opportunity o ON o.opportunity_id = s.opportunity_id
          CROSS JOIN ventana v
          WHERE s.opportunity_id IS NOT NULL
            AND s.since_sourcing IS NOT NULL
            AND s.since_sourcing::date BETWEEN v.win_ini AND v.win_fin
            AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
        ),
        won AS (
          SELECT DISTINCT o.opportunity_id
          FROM opportunity o
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
        )
        SELECT
          (SELECT win_ini FROM ventana)                                           AS ventana_desde,
          (SELECT win_fin FROM ventana)                                           AS ventana_hasta,
          (SELECT COUNT(*)::int FROM cohort)                                      AS sourcing_count,
          (SELECT COUNT(*)::int FROM cohort c
           WHERE c.opportunity_id IN (SELECT opportunity_id FROM won))            AS close_win_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.opportunity_id IN (SELECT opportunity_id FROM won))::numeric
                / (SELECT COUNT(*) FROM cohort)
            END, 2
          )::float                                                                AS sourcing_to_close_win_pct;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH cohort AS (
          SELECT DISTINCT
            s.opportunity_id,
            DATE_TRUNC('month', s.since_sourcing::date)::date AS mes
          FROM sourcing s
          JOIN opportunity o ON o.opportunity_id = s.opportunity_id
          WHERE s.opportunity_id IS NOT NULL
            AND s.since_sourcing IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
        ),
        won AS (
          SELECT DISTINCT o.opportunity_id
          FROM opportunity o
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
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
          TO_CHAR(m.mes, 'YYYY-MM-DD')                                            AS mes,
          (SELECT COUNT(*)::int FROM cohort c WHERE c.mes = m.mes)                AS sourcing_count,
          (SELECT COUNT(*)::int FROM cohort c
           WHERE c.mes = m.mes
             AND c.opportunity_id IN (SELECT opportunity_id FROM won))            AS close_win_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.mes = m.mes
                     AND c.opportunity_id IN (SELECT opportunity_id FROM won))::numeric
                / (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes)
            END, 2
          )::float                                                                AS sourcing_to_close_win_pct
        FROM meses m
        ORDER BY m.mes;
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "sourcing_to_close_win_snapshot",
    "label": "Sourcing → Close Win · cohort 30d (Mariano + Bahia)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sourcing_count", "label": "Sourcing entries (30d, M+B)", "type": "number"},
        {"key": "close_win_count", "label": "Of those, Close Win", "type": "number"},
        {"key": "sourcing_to_close_win_pct", "label": "% Sourcing → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sourcing_to_close_win_history",
    "label": "Sourcing → Close Win · cohort by month (Mariano + Bahia)",
    "dimensions": [
        {"key": "mes", "label": "Mes (since_sourcing)", "type": "date"},
    ],
    "measures": [
        {"key": "sourcing_count", "label": "Sourcing entries in month (M+B)", "type": "number"},
        {"key": "close_win_count", "label": "Of those, Close Win", "type": "number"},
        {"key": "sourcing_to_close_win_pct", "label": "% Sourcing → Close Win", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
