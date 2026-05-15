"""Sourcing → Close Win · Metabase logic (M+B).

Metric (per Metabase query the user provided):
  Of all closed opps (Close Win + Closed Lost) for Mariano/Bahia, the
  % shown defaults to "Close Wins that ALSO had a `sourcing.since_sourcing`
  entry" / "all Close Wins". In other words: ¿qué % de las opps ganadas
  pasaron por sourcing antes de cerrar?

Implementation notes (matching Metabase exactly):
  - Universe: opps with `opp_stage IN ('Close Win', 'Closed Lost')` AND
    `opp_close_date IS NOT NULL`.
  - AE filter: `opp_hr_lead OR opp_sales_lead` IN (Mariano, Bahia).
  - Bucket month by `opp_close_date` (when the opp closed, NOT when it
    entered sourcing).
  - Sourcing per opp: `MIN(since_sourcing)` (first entry into sourcing).

Default conversion % focuses on Close Win (matches the ELSE branch in
the Metabase query). The dataset also returns counts for Closed Lost in
case you want to flip the breakdown.
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
            TRIM(o.opp_stage) AS opp_stage,
            NULLIF(o.opp_close_date::text, '')::date AS close_d,
            MIN(NULLIF(s.since_sourcing::text, '')::date) AS sourcing_d
          FROM opportunity o
          LEFT JOIN sourcing s ON s.opportunity_id = o.opportunity_id
          WHERE o.opportunity_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND (
              TRIM(LOWER(o.opp_hr_lead))    = ANY(%(sales_leads)s)
              OR TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            )
          GROUP BY o.opportunity_id, opp_stage, close_d
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
          COUNT(*) FILTER (WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                             AND opp_stage = 'Close Win')::int                          AS close_win_count,
          COUNT(*) FILTER (WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                             AND opp_stage = 'Closed Lost')::int                        AS closed_lost_count,
          COUNT(*) FILTER (WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                             AND opp_stage = 'Close Win' AND sourcing_d IS NOT NULL)::int
                                                                                        AS sourcing_count,
          COUNT(*) FILTER (WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                             AND opp_stage = 'Closed Lost' AND sourcing_d IS NOT NULL)::int
                                                                                        AS closed_lost_with_sourcing,
          ROUND(
            CASE
              WHEN COUNT(*) FILTER (WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                                      AND opp_stage = 'Close Win') = 0
                THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                  AND opp_stage = 'Close Win' AND sourcing_d IS NOT NULL
              )::numeric
              / NULLIF(COUNT(*) FILTER (
                WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
                  AND opp_stage = 'Close Win'
              ), 0)
            END, 2
          )::float                                                                      AS sourcing_to_close_win_pct
        FROM base;
    """
    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


def _query_history(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = _BASE_CTE + """
        SELECT
          TO_CHAR(DATE_TRUNC('month', close_d)::date, 'YYYY-MM-DD')                     AS mes,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int                          AS close_win_count,
          COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::int                        AS closed_lost_count,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win'  AND sourcing_d IS NOT NULL)::int
                                                                                        AS sourcing_count,
          COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost' AND sourcing_d IS NOT NULL)::int
                                                                                        AS closed_lost_with_sourcing,
          ROUND(
            CASE
              WHEN COUNT(*) FILTER (WHERE opp_stage = 'Close Win') = 0 THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (
                WHERE opp_stage = 'Close Win' AND sourcing_d IS NOT NULL
              )::numeric
              / NULLIF(COUNT(*) FILTER (WHERE opp_stage = 'Close Win'), 0)
            END, 2
          )::float                                                                      AS sourcing_to_close_win_pct
        FROM base
        GROUP BY DATE_TRUNC('month', close_d)
        ORDER BY DATE_TRUNC('month', close_d);
    """
    return sql, {"sales_leads": _sales_leads()}


SNAPSHOT_DATASET = {
    "key": "sourcing_to_close_win_snapshot",
    "label": "Sourcing → Close Win · 30d (Metabase logic · Mariano + Bahia)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "close_win_count", "label": "Close Wins (closed in 30d)", "type": "number"},
        {"key": "closed_lost_count", "label": "Closed Lost (closed in 30d)", "type": "number"},
        {"key": "sourcing_count", "label": "Close Wins with sourcing", "type": "number"},
        {"key": "closed_lost_with_sourcing", "label": "Closed Lost with sourcing", "type": "number"},
        {"key": "sourcing_to_close_win_pct", "label": "% of CW that had sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_snapshot,
}

HISTORY_DATASET = {
    "key": "sourcing_to_close_win_history",
    "label": "Sourcing → Close Win · monthly (Metabase logic · Mariano + Bahia)",
    "dimensions": [
        {"key": "mes", "label": "Mes (opp_close_date)", "type": "date"},
    ],
    "measures": [
        {"key": "close_win_count", "label": "Close Wins (closed in month)", "type": "number"},
        {"key": "closed_lost_count", "label": "Closed Lost (closed in month)", "type": "number"},
        {"key": "sourcing_count", "label": "Close Wins with sourcing", "type": "number"},
        {"key": "closed_lost_with_sourcing", "label": "Closed Lost with sourcing", "type": "number"},
        {"key": "sourcing_to_close_win_pct", "label": "% of CW that had sourcing", "type": "percent"},
    ],
    "default_filters": {},
    "query": _query_history,
}

DATASET = SNAPSHOT_DATASET
