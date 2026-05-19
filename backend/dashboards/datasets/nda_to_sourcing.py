"""NDA Sent → Sourcing · Metabase logic (Mariano + Bahia).

Definition (matches the user's Metabase query exactly):
  - Universe (denominator):
      opps with `opp_stage IN ('NDA Sent', 'Deep Dive', 'Sourcing',
                              'Interviewing', 'Negotiating')`
      (= still-active funnel — excludes Close Win and Closed Lost)
      AND `nda_signature_or_start_date IS NOT NULL`
      AND (`opp_hr_lead` OR `opp_sales_lead`) IN (Mariano, Bahia).
  - Numerator (reached sourcing):
      subset that has `MIN(sourcing.since_sourcing) >= nda_d`
      (date ordering check — sourcing must happen on/after NDA signature).
  - Bucket month: `DATE_TRUNC('month', nda_d)` (NDA signed date).

Snapshot (30d): cohort = opps whose `nda_signature_or_start_date` falls
in the last 30 days. Monthly history: each month M is its own cohort.
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
        WITH base AS (
          SELECT
            o.opportunity_id,
            NULLIF(o.nda_signature_or_start_date::text, '')::date AS nda_d,
            MIN(NULLIF(s.since_sourcing::text, '')::date)         AS sourcing_d
          FROM opportunity o
          LEFT JOIN sourcing s ON s.opportunity_id = o.opportunity_id
          WHERE o.opportunity_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('NDA Sent', 'Deep Dive', 'Sourcing',
                                      'Interviewing', 'Negotiating')
            AND NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
            AND (
              TRIM(LOWER(o.opp_hr_lead))    = ANY(%(sales_leads)s)
              OR TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            )
          GROUP BY o.opportunity_id, nda_d
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
          %(win_ini)s::date                                                           AS ventana_desde,
          %(win_fin)s::date                                                           AS ventana_hasta,
          COUNT(*) FILTER (WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date)::int
                                                                                      AS nda_sent_count,
          COUNT(*) FILTER (
            WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
              AND sourcing_d IS NOT NULL
              AND sourcing_d >= nda_d
          )::int                                                                      AS sourcing_count,
          ROUND(
            CASE
              WHEN COUNT(*) FILTER (WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date) = 0
                THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                  AND sourcing_d IS NOT NULL
                  AND sourcing_d >= nda_d
              )::numeric
              / NULLIF(COUNT(*) FILTER (WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date), 0)
            END, 2
          )::float                                                                    AS nda_sent_to_sourcing_pct
        FROM base;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = _BASE_CTE + """
        SELECT
          TO_CHAR(DATE_TRUNC('month', nda_d)::date, 'YYYY-MM-DD')                     AS mes,
          COUNT(*)::int                                                                AS nda_sent_count,
          COUNT(*) FILTER (
            WHERE sourcing_d IS NOT NULL
              AND sourcing_d >= nda_d
          )::int                                                                       AS sourcing_count,
          ROUND(
            CASE
              WHEN COUNT(*) = 0 THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE sourcing_d IS NOT NULL
                  AND sourcing_d >= nda_d
              )::numeric
              / NULLIF(COUNT(*), 0)
            END, 2
          )::float                                                                     AS nda_sent_to_sourcing_pct
        FROM base
        GROUP BY DATE_TRUNC('month', nda_d)
        ORDER BY DATE_TRUNC('month', nda_d);
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "nda_to_sourcing_snapshot",
    "label": "NDA Sent → Sourcing · 30d (Metabase logic · Mariano + Bahia)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "nda_sent_count", "label": "NDA signed (active funnel, M+B)", "type": "number"},
        {"key": "sourcing_count", "label": "Of those, reached Sourcing", "type": "number"},
        {"key": "nda_sent_to_sourcing_pct", "label": "% NDA Sent → Sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "nda_to_sourcing_history",
    "label": "NDA Sent → Sourcing · monthly (Metabase logic · Mariano + Bahia)",
    "dimensions": [
        {"key": "mes", "label": "Mes (NDA signed)", "type": "date"},
    ],
    "measures": [
        {"key": "nda_sent_count", "label": "NDA signed in month (active, M+B)", "type": "number"},
        {"key": "sourcing_count", "label": "Of those, reached Sourcing", "type": "number"},
        {"key": "nda_sent_to_sourcing_pct", "label": "% NDA Sent → Sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
