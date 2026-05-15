"""Sales funnel — SQL → NDA Sent → Sourcing → Close Win (Last 30 days).

Counts opps with `opp_sales_lead IN (mariano@vintti.com, bahia@vintti.com)`
that were active in the last 30 days. "Active in 30d" means the opp has
either `nda_signature_or_start_date` or `opp_close_date` falling in the
window — matches the proxy used by `recruiter_metrics_routes.py:486-489`
for "opportunity created date".

Returns 4 counts + 4 cumulative conversion percentages.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta


SALES_LEADS_DEFAULT = ("mariano@vintti.com", "bahia@vintti.com")


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


def _sales_leads() -> list[str]:
    raw = os.environ.get("DASHBOARD_SALES_AES", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(SALES_LEADS_DEFAULT)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    win_ini = corte - timedelta(days=29)  # 30 days inclusive

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            TRIM(o.opp_stage) AS opp_stage,
            COALESCE(
              NULLIF(o.nda_signature_or_start_date::text, '')::date,
              NULLIF(o.opp_close_date::text, '')::date
            ) AS opp_date,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          WHERE TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            AND o.opp_stage IS NOT NULL
        ),
        scoped AS (
          SELECT b.*
          FROM base b
          CROSS JOIN ventana v
          WHERE b.opp_date BETWEEN v.win_ini AND v.win_fin
        ),
        counts AS (
          SELECT
            COUNT(*)::int                                                                  AS sql_count,
            COUNT(*) FILTER (
              WHERE opp_stage IN ('NDA Sent','Sourcing','Interviewing','Negotiating',
                                  'Close Win','Closed Lost')
            )::int                                                                         AS nda_sent_count,
            COUNT(*) FILTER (
              WHERE opp_stage IN ('Sourcing','Interviewing','Negotiating',
                                  'Close Win','Closed Lost')
            )::int                                                                         AS sourcing_count,
            COUNT(*) FILTER (
              WHERE opp_stage = 'Close Win'
                AND close_d IS NOT NULL
                AND close_d BETWEEN (SELECT win_ini FROM ventana) AND (SELECT win_fin FROM ventana)
            )::int                                                                         AS close_win_count
          FROM scoped
        )
        SELECT
          (SELECT win_ini FROM ventana) AS ventana_desde,
          (SELECT win_fin FROM ventana) AS ventana_hasta,
          sql_count,
          nda_sent_count,
          sourcing_count,
          close_win_count,
          ROUND(CASE WHEN sql_count = 0 THEN NULL
                     ELSE 100.0 * nda_sent_count::numeric / sql_count END, 2)::float       AS sql_to_nda_sent_pct,
          ROUND(CASE WHEN nda_sent_count = 0 THEN NULL
                     ELSE 100.0 * sourcing_count::numeric / nda_sent_count END, 2)::float  AS nda_sent_to_sourcing_pct,
          ROUND(CASE WHEN sourcing_count = 0 THEN NULL
                     ELSE 100.0 * close_win_count::numeric / sourcing_count END, 2)::float AS sourcing_to_close_win_pct,
          ROUND(CASE WHEN sql_count = 0 THEN NULL
                     ELSE 100.0 * close_win_count::numeric / sql_count END, 2)::float      AS sql_to_close_win_pct
        FROM counts;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": corte,
        "sales_leads": _sales_leads(),
    }


DATASET = {
    "key": "sales_funnel_snapshot",
    "label": "Sales funnel — Mariano + Bahia (Last 30d)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL", "type": "number"},
        {"key": "nda_sent_count", "label": "NDA Sent", "type": "number"},
        {"key": "sourcing_count", "label": "Sourcing", "type": "number"},
        {"key": "close_win_count", "label": "Close Win", "type": "number"},
        {"key": "sql_to_nda_sent_pct", "label": "SQL → NDA Sent %", "type": "percent"},
        {"key": "nda_sent_to_sourcing_pct", "label": "NDA Sent → Sourcing %", "type": "percent"},
        {"key": "sourcing_to_close_win_pct", "label": "Sourcing → Close Win %", "type": "percent"},
        {"key": "sql_to_close_win_pct", "label": "SQL → Close Win %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
