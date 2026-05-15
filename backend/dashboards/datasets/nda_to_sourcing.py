"""NDA Sent → Sourcing · cohort by nda_signature_or_start_date month (M+B).

Definition (per user 2026-05-15):
  - Denominator: opportunities with `nda_signature_or_start_date` populated
    AND `opp_sales_lead IN (mariano@vintti.com, bahia@vintti.com)`.
  - Numerator:   subset of those opps that ALSO appear in the `sourcing`
                 table (matched by `opportunity_id`).

Snapshot (30d): cohort = M+B opps whose `nda_signature_or_start_date`
falls in the last 30 days.

Monthly history: each month M is its own cohort (M+B opps with NDA signed
in month M). NOT cumulative — each bar is independent.
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
          SELECT o.opportunity_id
          FROM opportunity o
          CROSS JOIN ventana v
          WHERE NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text, '')::date
                BETWEEN v.win_ini AND v.win_fin
            AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
        ),
        sourced AS (
          SELECT DISTINCT opportunity_id
          FROM sourcing
          WHERE opportunity_id IS NOT NULL
        )
        SELECT
          (SELECT win_ini FROM ventana)                                           AS ventana_desde,
          (SELECT win_fin FROM ventana)                                           AS ventana_hasta,
          (SELECT COUNT(*)::int FROM cohort)                                      AS nda_sent_count,
          (SELECT COUNT(*)::int FROM cohort c
           WHERE c.opportunity_id IN (SELECT opportunity_id FROM sourced))        AS sourcing_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.opportunity_id IN (SELECT opportunity_id FROM sourced))::numeric
                / (SELECT COUNT(*) FROM cohort)
            END, 2
          )::float                                                                AS nda_sent_to_sourcing_pct;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH cohort AS (
          SELECT
            o.opportunity_id,
            DATE_TRUNC('month',
              NULLIF(o.nda_signature_or_start_date::text, '')::date
            )::date AS mes
          FROM opportunity o
          WHERE NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
        ),
        sourced AS (
          SELECT DISTINCT opportunity_id
          FROM sourcing
          WHERE opportunity_id IS NOT NULL
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
          (SELECT COUNT(*)::int FROM cohort c WHERE c.mes = m.mes)                AS nda_sent_count,
          (SELECT COUNT(*)::int FROM cohort c
           WHERE c.mes = m.mes
             AND c.opportunity_id IN (SELECT opportunity_id FROM sourced))        AS sourcing_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes) = 0 THEN NULL
              ELSE 100.0
                * (SELECT COUNT(*) FROM cohort c
                   WHERE c.mes = m.mes
                     AND c.opportunity_id IN (SELECT opportunity_id FROM sourced))::numeric
                / (SELECT COUNT(*) FROM cohort c WHERE c.mes = m.mes)
            END, 2
          )::float                                                                AS nda_sent_to_sourcing_pct
        FROM meses m
        ORDER BY m.mes;
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "nda_to_sourcing_snapshot",
    "label": "NDA Sent → Sourcing · cohort 30d (Mariano + Bahia)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "nda_sent_count", "label": "NDAs signed (M+B, 30d)", "type": "number"},
        {"key": "sourcing_count", "label": "Of those, moved to Sourcing", "type": "number"},
        {"key": "nda_sent_to_sourcing_pct", "label": "% NDA Sent → Sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "nda_to_sourcing_history",
    "label": "NDA Sent → Sourcing · cohort by month (Mariano + Bahia)",
    "dimensions": [
        {"key": "mes", "label": "Mes (NDA signed)", "type": "date"},
    ],
    "measures": [
        {"key": "nda_sent_count", "label": "NDAs signed in month (M+B)", "type": "number"},
        {"key": "sourcing_count", "label": "Of those, moved to Sourcing", "type": "number"},
        {"key": "nda_sent_to_sourcing_pct", "label": "% NDA Sent → Sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
