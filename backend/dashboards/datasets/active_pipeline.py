from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


# Stages excluded from "pipeline" — must match the legacy filter in
# docs/assets/js/dashboard.js:20-24 so this matches the existing
# "Opportunities — Pipeline" table on Management Metrics.
# NOTE: `%` doubled to `%%` so psycopg2's pyformat parameter substitution
# doesn't interpret SQL ILIKE wildcards as format placeholders.
PIPELINE_EXCLUDE_STAGES_SQL = """
  AND opp_stage IS NOT NULL
  AND TRIM(opp_stage) <> ''
  AND opp_stage NOT ILIKE '%%deep dive%%'
  AND opp_stage NOT ILIKE '%%nda sent%%'
  AND opp_stage NOT ILIKE '%%close%%win%%'
  AND opp_stage NOT ILIKE '%%close%%lost%%'
"""


def _parse_date(value: str | None) -> date | None:
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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )

    sql = f"""
        WITH params AS (
          SELECT
            %(corte)s::date                                AS corte_d,
            (%(corte)s::date - INTERVAL '29 days')::date   AS cr_ini
        ),
        pipeline AS (
          SELECT
            o.opp_model,
            o.opp_type,
            COALESCE(o.expected_revenue, 0)::numeric AS exp_rev
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE TRUE
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            {PIPELINE_EXCLUDE_STAGES_SQL}
        ),
        closed AS (
          SELECT
            o.opp_model,
            TRIM(o.opp_stage) AS stage
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          CROSS JOIN params p
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost', 'Close Lost')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND o.opp_close_date IS NOT NULL
            AND NULLIF(o.opp_close_date::text, '')::date >= p.cr_ini
            AND NULLIF(o.opp_close_date::text, '')::date <= p.corte_d
            AND LOWER(COALESCE(TRIM(o.opp_sales_lead), '')) IN (
              'bahia@vintti.com',
              'mariano@vintti.com',
              'lara@vintti.com'
            )
        ),
        win_rates AS (
          SELECT
            COUNT(*) FILTER (WHERE stage = 'Close Win')::numeric
              / NULLIF(COUNT(*) FILTER (
                  WHERE stage IN ('Close Win', 'Closed Lost', 'Close Lost')
                ), 0)                                                                AS win_rate_total,
            COUNT(*) FILTER (WHERE stage = 'Close Win' AND opp_model = 'Staffing')::numeric
              / NULLIF(COUNT(*) FILTER (
                  WHERE stage IN ('Close Win', 'Closed Lost', 'Close Lost')
                    AND opp_model = 'Staffing'
                ), 0)                                                                AS win_rate_staffing,
            COUNT(*) FILTER (WHERE stage = 'Close Win' AND opp_model = 'Recruiting')::numeric
              / NULLIF(COUNT(*) FILTER (
                  WHERE stage IN ('Close Win', 'Closed Lost', 'Close Lost')
                    AND opp_model = 'Recruiting'
                ), 0)                                                                AS win_rate_recruiting
          FROM closed
        ),
        agg AS (
          SELECT
            COUNT(*)::int                                                            AS pipeline_count,
            COUNT(*) FILTER (WHERE opp_model = 'Staffing')::int                      AS pipeline_count_staffing,
            COUNT(*) FILTER (WHERE opp_model = 'Recruiting')::int                    AS pipeline_count_recruiting,
            COUNT(*) FILTER (WHERE opp_type  = 'New')::int                           AS pipeline_count_new,
            COUNT(*) FILTER (WHERE opp_type  = 'Replacement')::int                   AS pipeline_count_replacement,
            COALESCE(SUM(exp_rev), 0)::bigint                                        AS pipeline_revenue
          FROM pipeline
        )
        SELECT
          (SELECT corte_d FROM params)                              AS corte,
          a.pipeline_count,
          a.pipeline_count_staffing,
          a.pipeline_count_recruiting,
          a.pipeline_count_new,
          a.pipeline_count_replacement,
          a.pipeline_revenue,
          ROUND((a.pipeline_revenue::numeric * COALESCE(w.win_rate_total, 0)), 0)::bigint
                                                                    AS pipeline_revenue_weighted,
          ROUND(COALESCE(w.win_rate_total, 0) * 100, 2)::float      AS win_rate_total_pct,
          ROUND(COALESCE(w.win_rate_staffing, 0) * 100, 2)::float   AS win_rate_staffing_pct,
          ROUND(COALESCE(w.win_rate_recruiting, 0) * 100, 2)::float AS win_rate_recruiting_pct
        FROM agg a
        CROSS JOIN win_rates w;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "active_pipeline",
    "label": "Active Pipeline (count + weighted revenue)",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "pipeline_count", "label": "Opps abiertas", "type": "number"},
        {"key": "pipeline_count_staffing", "label": "Opps abiertas — Staffing", "type": "number"},
        {"key": "pipeline_count_recruiting", "label": "Opps abiertas — Recruiting", "type": "number"},
        {"key": "pipeline_count_new", "label": "Opps abiertas — New", "type": "number"},
        {"key": "pipeline_count_replacement", "label": "Opps abiertas — Replacement", "type": "number"},
        {"key": "pipeline_revenue", "label": "Pipeline revenue (bruto)", "type": "currency"},
        {"key": "pipeline_revenue_weighted", "label": "Pipeline revenue (weighted CR 30d)", "type": "currency"},
        {"key": "win_rate_total_pct", "label": "Win rate global 30d", "type": "percent"},
        {"key": "win_rate_staffing_pct", "label": "Win rate Staffing 30d", "type": "percent"},
        {"key": "win_rate_recruiting_pct", "label": "Win rate Recruiting 30d", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
