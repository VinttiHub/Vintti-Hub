from __future__ import annotations

from datetime import date, datetime


# Reuse the same stage exclusion as active_pipeline so both KPIs are consistent.
# `%` doubled to `%%` so psycopg2's pyformat substitution leaves the SQL
# ILIKE wildcards intact.
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
        or datetime.utcnow().date()
    )

    # Net adds expected (30d) per model =
    #   pipeline_count_<model> × win_rate_<model>_90d  −  avg_monthly_churn_<model>_90d
    # Churn avg uses 3 month-buckets (~90 days) of last_baja_real entries by opp_model.
    sql = f"""
        WITH params AS (
          SELECT
            %(corte)s::date                                AS corte_d,
            (%(corte)s::date - INTERVAL '90 days')::date   AS cr_ini
        ),
        pipeline AS (
          SELECT o.opp_model
          FROM opportunity o
          WHERE TRUE
            {PIPELINE_EXCLUDE_STAGES_SQL}
        ),
        pipeline_counts AS (
          SELECT
            COUNT(*) FILTER (WHERE opp_model = 'Staffing')::int   AS pipe_staffing,
            COUNT(*) FILTER (WHERE opp_model = 'Recruiting')::int AS pipe_recruiting
          FROM pipeline
        ),
        closed AS (
          SELECT o.opp_model, TRIM(o.opp_stage) AS stage
          FROM opportunity o
          CROSS JOIN params p
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost', 'Close Lost')
            AND o.opp_close_date IS NOT NULL
            AND NULLIF(o.opp_close_date::text, '')::date >= p.cr_ini
            AND NULLIF(o.opp_close_date::text, '')::date <= p.corte_d
        ),
        win_rates AS (
          SELECT
            COUNT(*) FILTER (WHERE stage = 'Close Win' AND opp_model = 'Staffing')::numeric
              / NULLIF(COUNT(*) FILTER (
                  WHERE stage IN ('Close Win', 'Closed Lost', 'Close Lost')
                    AND opp_model = 'Staffing'
                ), 0)                                                                AS wr_staffing,
            COUNT(*) FILTER (WHERE stage = 'Close Win' AND opp_model = 'Recruiting')::numeric
              / NULLIF(COUNT(*) FILTER (
                  WHERE stage IN ('Close Win', 'Closed Lost', 'Close Lost')
                    AND opp_model = 'Recruiting'
                ), 0)                                                                AS wr_recruiting
          FROM closed
        ),
        -- Churn (Staffing): reuse client_churn_30d_summary "bajas_real" logic,
        -- but aggregate over the last 90 days to derive an avg per 30d window.
        hires_staffing AS (
          SELECT
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange::text), '') IS NOT NULL
                THEN TO_DATE(NULLIF(TRIM(ho.buyout_daterange::text), '') || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND o.opp_model = 'Staffing'
        ),
        ultima_baja_raw AS (
          SELECT account_id, MAX(end_d) AS fecha_baja
          FROM hires_staffing
          WHERE end_d IS NOT NULL
          GROUP BY account_id
        ),
        cuentas_con_activos_posteriores AS (
          SELECT DISTINCT ub.account_id
          FROM ultima_baja_raw ub
          JOIN hires_staffing h
            ON h.account_id = ub.account_id
           AND COALESCE(h.end_d, DATE '9999-12-31') > ub.fecha_baja
        ),
        ultima_baja AS (
          SELECT *
          FROM ultima_baja_raw
          WHERE account_id NOT IN (SELECT account_id FROM cuentas_con_activos_posteriores)
        ),
        buyout_por_cuenta AS (
          SELECT account_id, MAX(buyout_d) AS buyout_d
          FROM hires_staffing
          WHERE buyout_d IS NOT NULL
          GROUP BY account_id
        ),
        churn_staffing_90d AS (
          SELECT
            COUNT(*) FILTER (
              WHERE NOT (b.buyout_d IS NOT NULL AND b.buyout_d >= DATE_TRUNC('month', ub.fecha_baja))
            )::numeric AS bajas_real_90d
          FROM ultima_baja ub
          LEFT JOIN buyout_por_cuenta b ON b.account_id = ub.account_id
          CROSS JOIN params p
          WHERE ub.fecha_baja BETWEEN p.cr_ini AND p.corte_d
        ),
        -- Churn (Recruiting): no recurring contract, so we approximate "churn" as
        -- recruiting placements that ended (end_date) in the last 90 days.
        churn_recruiting_90d AS (
          SELECT COUNT(*)::numeric AS bajas_real_90d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          CROSS JOIN params p
          WHERE o.opp_model = 'Recruiting'
            AND NULLIF(ho.end_date::text, '') IS NOT NULL
            AND NULLIF(ho.end_date::text, '')::date BETWEEN p.cr_ini AND p.corte_d
        )
        SELECT
          (SELECT corte_d FROM params)                                                       AS corte,
          pc.pipe_staffing,
          pc.pipe_recruiting,
          ROUND(COALESCE(w.wr_staffing,   0) * 100, 2)::float                                AS wr_staffing_pct,
          ROUND(COALESCE(w.wr_recruiting, 0) * 100, 2)::float                                AS wr_recruiting_pct,
          ROUND(cs.bajas_real_90d / 3.0, 1)::float                                           AS churn_staffing_avg_30d,
          ROUND(cr.bajas_real_90d / 3.0, 1)::float                                           AS churn_recruiting_avg_30d,
          ROUND(
            (pc.pipe_staffing   * COALESCE(w.wr_staffing,   0)) - (cs.bajas_real_90d / 3.0)
          )::int                                                                             AS net_adds_staffing,
          ROUND(
            (pc.pipe_recruiting * COALESCE(w.wr_recruiting, 0)) - (cr.bajas_real_90d / 3.0)
          )::int                                                                             AS net_adds_recruiting
        FROM pipeline_counts pc
        CROSS JOIN win_rates  w
        CROSS JOIN churn_staffing_90d   cs
        CROSS JOIN churn_recruiting_90d cr;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "pipeline_cr_minus_churn",
    "label": "Pipeline × CR − Churn (Net adds 30d) por modelo",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "pipe_staffing", "label": "Pipeline Staffing", "type": "number"},
        {"key": "pipe_recruiting", "label": "Pipeline Recruiting", "type": "number"},
        {"key": "wr_staffing_pct", "label": "CR Staffing 90d", "type": "percent"},
        {"key": "wr_recruiting_pct", "label": "CR Recruiting 90d", "type": "percent"},
        {"key": "churn_staffing_avg_30d", "label": "Churn Staffing (avg 30d, 90d hist)", "type": "number"},
        {"key": "churn_recruiting_avg_30d", "label": "Churn Recruiting (avg 30d, 90d hist)", "type": "number"},
        {"key": "net_adds_staffing", "label": "Net adds Staffing (30d)", "type": "number"},
        {"key": "net_adds_recruiting", "label": "Net adds Recruiting (30d)", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
