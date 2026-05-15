"""Sales funnel — monthly history of conversion rates (Mariano + Bahia).

For each month in [min_opp_date, today], counts how many of the AEs' opps
were active in that month (by `COALESCE(nda_signed, close_d)` proxy) and
how many made it past each funnel stage. Returns the 4 conversion %s per
month so the front of the flippable cards can render a line chart.
"""
from __future__ import annotations

import os


SALES_LEADS_DEFAULT = ("mariano@vintti.com", "bahia@vintti.com")


def _sales_leads() -> list[str]:
    raw = os.environ.get("DASHBOARD_SALES_AES", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(SALES_LEADS_DEFAULT)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH base AS (
          SELECT
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
        bounds AS (
          SELECT
            COALESCE(DATE_TRUNC('month', MIN(opp_date))::date,
                     DATE_TRUNC('month', CURRENT_DATE)::date) AS first_month,
            DATE_TRUNC('month', CURRENT_DATE)::date          AS last_month
          FROM base
          WHERE opp_date IS NOT NULL
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS mes_fin
          FROM bounds b,
               generate_series(b.first_month, b.last_month, INTERVAL '1 month') gs
        ),
        per_month AS (
          SELECT
            m.mes,
            COUNT(*) FILTER (WHERE b.opp_date IS NOT NULL)::int                            AS sql_count,
            COUNT(*) FILTER (
              WHERE b.opp_date IS NOT NULL
                AND b.opp_stage IN ('NDA Sent','Sourcing','Interviewing','Negotiating',
                                    'Close Win','Closed Lost')
            )::int                                                                          AS nda_sent_count,
            COUNT(*) FILTER (
              WHERE b.opp_date IS NOT NULL
                AND b.opp_stage IN ('Sourcing','Interviewing','Negotiating',
                                    'Close Win','Closed Lost')
            )::int                                                                          AS sourcing_count,
            COUNT(*) FILTER (
              WHERE b.opp_stage = 'Close Win'
                AND b.close_d IS NOT NULL
                AND b.close_d BETWEEN m.mes AND m.mes_fin
            )::int                                                                          AS close_win_count
          FROM meses m
          LEFT JOIN base b ON b.opp_date BETWEEN m.mes AND m.mes_fin
          GROUP BY m.mes
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                                                       AS mes,
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
        FROM per_month
        ORDER BY mes;
    """
    return sql, {"sales_leads": _sales_leads()}


DATASET = {
    "key": "sales_funnel_history",
    "label": "Sales funnel — monthly (Mariano + Bahia)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
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
