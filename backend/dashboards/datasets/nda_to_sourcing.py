"""NDA Sent → Sourcing (Mariano + Bahia).

Reinterpretation:
  - Denominator (NDA sent): opps whose `nda_sent_date` falls in the window
    (last 30 days for snapshot; bucketed monthly for history).
  - Numerator (reached sourcing): of those, how many have
    `nda_signature_or_start_date IS NOT NULL` (i.e. the NDA was actually
    signed, so the opp progressed past NDA Sent into the active funnel).
  - Filter: opp_hr_lead or opp_sales_lead in (Mariano, Bahia).

Field names are preserved (`nda_sent_count`, `sourcing_count`,
`nda_sent_to_sourcing_pct`) so the existing dashboard bindings keep working.
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
            NULLIF(o.nda_sent_date::text, '')::date                AS sent_d,
            NULLIF(o.nda_signature_or_start_date::text, '')::date  AS signed_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opportunity_id IS NOT NULL
            AND NULLIF(o.nda_sent_date::text, '') IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(a.account_manager)) = ANY(%(sales_leads)s)
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
          %(win_ini)s::date                                                           AS ventana_desde,
          %(win_fin)s::date                                                           AS ventana_hasta,
          COUNT(*) FILTER (WHERE sent_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date)::int
                                                                                      AS nda_sent_count,
          COUNT(*) FILTER (
            WHERE sent_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
              AND signed_d IS NOT NULL
          )::int                                                                      AS sourcing_count,
          ROUND(
            CASE
              WHEN COUNT(*) FILTER (WHERE sent_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date) = 0
                THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE sent_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                  AND signed_d IS NOT NULL
              )::numeric
              / NULLIF(COUNT(*) FILTER (WHERE sent_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date), 0)
            END, 2
          )::float                                                                    AS nda_sent_to_sourcing_pct
        FROM base;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = _BASE_CTE + """
        SELECT
          TO_CHAR(DATE_TRUNC('month', sent_d)::date, 'YYYY-MM-DD')                     AS mes,
          COUNT(*)::int                                                                AS nda_sent_count,
          COUNT(*) FILTER (WHERE signed_d IS NOT NULL)::int                            AS sourcing_count,
          ROUND(
            CASE
              WHEN COUNT(*) = 0 THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (WHERE signed_d IS NOT NULL)::numeric
                          / NULLIF(COUNT(*), 0)
            END, 2
          )::float                                                                     AS nda_sent_to_sourcing_pct
        FROM base
        GROUP BY DATE_TRUNC('month', sent_d)
        ORDER BY DATE_TRUNC('month', sent_d);
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "nda_to_sourcing_snapshot",
    "label": "NDA Sent → Sourcing · 30d (sent_date → signed)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "nda_sent_count", "label": "NDA sent (last 30d, M+B)", "type": "number"},
        {"key": "sourcing_count", "label": "Of those, NDA signed", "type": "number"},
        {"key": "nda_sent_to_sourcing_pct", "label": "% NDA Sent → Sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "nda_to_sourcing_history",
    "label": "NDA Sent → Sourcing · monthly (sent_date → signed)",
    "dimensions": [
        {"key": "mes", "label": "Mes (NDA sent)", "type": "date"},
    ],
    "measures": [
        {"key": "nda_sent_count", "label": "NDA sent in month (M+B)", "type": "number"},
        {"key": "sourcing_count", "label": "Of those, NDA signed", "type": "number"},
        {"key": "nda_sent_to_sourcing_pct", "label": "% NDA Sent → Sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
