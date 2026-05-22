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

    # Net adds (30d) per model = (pipeline_count × CR_30d) − Churn_30d (actual count)
    # Both CR and Churn use the same 30d window so the values match the
    # adjacent KPI tiles (NDA → Close Win 30d, Candidate churn 30d).
    sql = f"""
        WITH params AS (
          SELECT
            %(corte)s::date                                AS corte_d,
            (%(corte)s::date - INTERVAL '29 days')::date   AS win_ini
        ),
        pipeline AS (
          SELECT
            o.opp_model,
            COALESCE(o.expected_fee, 0)::numeric     AS exp_fee,
            COALESCE(o.expected_revenue, 0)::numeric AS exp_rev
          FROM opportunity o
          WHERE TRUE
            {PIPELINE_EXCLUDE_STAGES_SQL}
        ),
        pipeline_counts AS (
          SELECT
            COUNT(*) FILTER (WHERE opp_model = 'Staffing')::int          AS pipe_staffing,
            COUNT(*) FILTER (WHERE opp_model = 'Recruiting')::int        AS pipe_recruiting,
            COALESCE(SUM(exp_fee) FILTER (WHERE opp_model = 'Staffing'), 0)::numeric
                                                                          AS pipe_fee_staffing,
            COALESCE(SUM(exp_rev) FILTER (WHERE opp_model = 'Staffing'), 0)::numeric
                                                                          AS pipe_revenue_staffing
          FROM pipeline
        ),
        closed_30d AS (
          SELECT o.opp_model, TRIM(o.opp_stage) AS stage
          FROM opportunity o
          CROSS JOIN params p
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost', 'Close Lost')
            AND o.opp_close_date IS NOT NULL
            AND NULLIF(o.opp_close_date::text, '')::date >= p.win_ini
            AND NULLIF(o.opp_close_date::text, '')::date <= p.corte_d
        ),
        win_rates_30d AS (
          SELECT
            COUNT(*) FILTER (WHERE stage = 'Close Win')::numeric
              / NULLIF(COUNT(*) FILTER (
                  WHERE stage IN ('Close Win', 'Closed Lost', 'Close Lost')
                ), 0)                                                                AS wr_staffing,
            COUNT(*) FILTER (WHERE stage = 'Close Win')::numeric
              / NULLIF(COUNT(*) FILTER (
                  WHERE stage IN ('Close Win', 'Closed Lost', 'Close Lost')
                ), 0)                                                                AS wr_recruiting
          FROM closed_30d
        ),
        -- Churn (Staffing): CANDIDATE-level bajas, same logic as
        -- candidate_churn_30d_summary.py. Counts distinct candidates whose
        -- end_d falls in the 30d window, excluding buyouts (same-month buyout).
        candidatos_staffing AS (
          SELECT
            ho.candidate_id,
            COALESCE(ho.fee, 0)::numeric    AS fee,
            COALESCE(ho.salary, 0)::numeric AS salary,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text,'') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
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
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
        ),
        activos_inicio AS (
          SELECT DISTINCT c.candidate_id, c.end_d, c.buyout_d
          FROM candidatos_staffing c
          CROSS JOIN params p
          WHERE c.start_d IS NOT NULL
            AND c.start_d <= p.win_ini
            AND (c.end_d IS NULL OR c.end_d >= p.win_ini)
        ),
        bajas_inicio AS (
          SELECT COUNT(DISTINCT a.candidate_id) FILTER (
            WHERE NOT (a.buyout_d IS NOT NULL AND a.buyout_d >= DATE_TRUNC('month', a.end_d))
          )::int AS bajas_real
          FROM activos_inicio a
          CROSS JOIN params p
          WHERE a.end_d IS NOT NULL
            AND a.end_d BETWEEN p.win_ini AND p.corte_d
        ),
        bajas_starts AS (
          SELECT COUNT(DISTINCT c.candidate_id) FILTER (
            WHERE NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
          )::int AS bajas_real
          FROM candidatos_staffing c
          CROSS JOIN params p
          WHERE c.start_d IS NOT NULL
            AND c.end_d   IS NOT NULL
            AND c.start_d BETWEEN p.win_ini AND p.corte_d
            AND c.end_d   BETWEEN p.win_ini AND p.corte_d
        ),
        churn_staffing_30d AS (
          SELECT (
            COALESCE((SELECT bajas_real FROM bajas_inicio), 0)
            + COALESCE((SELECT bajas_real FROM bajas_starts), 0)
          )::numeric AS bajas_real_30d
        ),
        -- Churn rate = bajas / candidatos activos al inicio de la ventana.
        -- Mismo cálculo que candidate_churn_30d_summary.churn_real_pct (la card
        -- "Candidate churn · 30d" de Account Management).
        churn_rate_30d AS (
          SELECT
            (SELECT bajas_real_30d FROM churn_staffing_30d)
              / NULLIF((SELECT COUNT(*)::numeric FROM activos_inicio), 0)
              AS churn_rate
        ),
        -- Fee/revenue lost from Staffing candidates that ended in the 30d window.
        -- Same buyout exclusion as the count above.
        churn_fee_loss_30d AS (
          SELECT
            COALESCE(SUM(c.fee), 0)::numeric              AS churn_fee_loss,
            COALESCE(SUM(c.fee + c.salary), 0)::numeric   AS churn_revenue_loss
          FROM candidatos_staffing c
          CROSS JOIN params p
          WHERE c.end_d IS NOT NULL
            AND c.end_d BETWEEN p.win_ini AND p.corte_d
            AND NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
        ),
        -- LTV (avg months per Staffing client) — same logic as
        -- backend/routes/metrics_routes.py:740-767 (`/management/dashboard`).
        ltv_base AS (
          SELECT
            c.candidate_id,
            c.start_d,
            c.end_d,
            c.account_id
          FROM (
            SELECT
              ho.candidate_id,
              ho.account_id,
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                WHEN NULLIF(ho.start_date::text,'') IS NOT NULL THEN ho.start_date::date
                ELSE NULL
              END AS start_d,
              CASE
                WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
                ELSE ho.end_date::date
              END AS end_d
            FROM hire_opportunity ho
            JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
            WHERE ho.account_id IS NOT NULL
              AND o.opp_model = 'Staffing'
          ) c
          WHERE c.start_d IS NOT NULL
        ),
        ltv_meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM ltv_base),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM ltv_base),
            INTERVAL '1 month'
          ) gs
        ),
        ltv_activos_mes AS (
          SELECT m.mes, b.account_id, COUNT(DISTINCT b.candidate_id) AS activos
          FROM ltv_meses m
          JOIN ltv_base b
            ON b.start_d < (m.mes + INTERVAL '1 month')
           AND (b.end_d IS NULL OR b.end_d >= m.mes)
          GROUP BY 1, 2
        ),
        ltv_duracion AS (
          SELECT account_id, COUNT(*) AS active_months
          FROM ltv_activos_mes
          WHERE activos > 0
          GROUP BY account_id
        ),
        ltv_months AS (
          -- Round to integer to match the legacy /management/dashboard query
          -- (`::numeric(10,0)`). Use the SAME integer for display and for the
          -- net_ltv_* multiplier so they stay consistent.
          SELECT COALESCE(ROUND(AVG(active_months)), 0)::int AS ltv
          FROM ltv_duracion
        ),
        -- Churn (Recruiting): one-time placements; we count Recruiting hires
        -- that ended in the 30d window as the equivalent "churn".
        churn_recruiting_30d AS (
          SELECT COUNT(*)::numeric AS bajas_real_30d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          CROSS JOIN params p
          WHERE o.opp_model = 'Recruiting'
            AND NULLIF(ho.end_date::text, '') IS NOT NULL
            AND NULLIF(ho.end_date::text, '')::date BETWEEN p.win_ini AND p.corte_d
        )
        SELECT
          (SELECT corte_d FROM params)                                                       AS corte,
          pc.pipe_staffing,
          pc.pipe_recruiting,
          ROUND(COALESCE(w.wr_staffing,   0) * 100, 2)::float                                AS wr_staffing_pct,
          ROUND(COALESCE(w.wr_recruiting, 0) * 100, 2)::float                                AS wr_recruiting_pct,
          cs.bajas_real_30d::int                                                             AS churn_staffing_30d,
          cr.bajas_real_30d::int                                                             AS churn_recruiting_30d,
          -- NEW formula: net = pipeline × (CR − churn_rate%)
          -- Stakeholder-requested: subtract the churn RATE (e.g. 5%) instead
          -- of the absolute baja count. Keeps the same multiplier across the
          -- count, fee, revenue and LTV calculations.
          ROUND(
            pc.pipe_staffing   * (COALESCE(w.wr_staffing,   0) - COALESCE(crt.churn_rate, 0))
          )::int                                                                             AS net_adds_staffing,
          ROUND(
            pc.pipe_recruiting * (COALESCE(w.wr_recruiting, 0) - COALESCE(crt.churn_rate, 0))
          )::int                                                                             AS net_adds_recruiting,
          ROUND(COALESCE(crt.churn_rate, 0) * 100, 2)::float                                 AS churn_rate_pct,
          -- Money-based metrics (Staffing only — fee/MRR concept doesn't apply to Recruiting)
          pc.pipe_fee_staffing::bigint                                                       AS pipe_fee_staffing,
          pc.pipe_revenue_staffing::bigint                                                   AS pipe_revenue_staffing,
          cfl.churn_fee_loss::bigint                                                         AS churn_fee_loss_staffing_30d,
          cfl.churn_revenue_loss::bigint                                                     AS churn_revenue_loss_staffing_30d,
          l.ltv::int                                                                         AS ltv_months,
          ROUND(
            pc.pipe_fee_staffing * (COALESCE(w.wr_staffing, 0) - COALESCE(crt.churn_rate, 0))
          )::bigint                                                                          AS net_mrr_fee_staffing_30d,
          ROUND(
            pc.pipe_revenue_staffing * (COALESCE(w.wr_staffing, 0) - COALESCE(crt.churn_rate, 0))
          )::bigint                                                                          AS net_mrr_revenue_staffing_30d,
          -- Net LTV $ = net MRR fee × LTV (months) → total LTV impact in $
          ROUND(
            (
              pc.pipe_fee_staffing * (COALESCE(w.wr_staffing, 0) - COALESCE(crt.churn_rate, 0))
            ) * l.ltv
          )::bigint                                                                          AS net_ltv_fee_staffing_30d
        FROM pipeline_counts pc
        CROSS JOIN win_rates_30d        w
        CROSS JOIN churn_staffing_30d   cs
        CROSS JOIN churn_recruiting_30d cr
        CROSS JOIN churn_fee_loss_30d   cfl
        CROSS JOIN ltv_months           l
        CROSS JOIN churn_rate_30d       crt;
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
        {"key": "wr_staffing_pct", "label": "CR Staffing 30d", "type": "percent"},
        {"key": "wr_recruiting_pct", "label": "CR Recruiting 30d", "type": "percent"},
        {"key": "churn_staffing_30d", "label": "Churn Staffing (30d, count)", "type": "number"},
        {"key": "churn_recruiting_30d", "label": "Churn Recruiting (30d, count)", "type": "number"},
        {"key": "churn_rate_pct", "label": "Churn rate Staffing 30d", "type": "percent"},
        {"key": "net_adds_staffing", "label": "Net adds Staffing (30d)", "type": "number"},
        {"key": "net_adds_recruiting", "label": "Net adds Recruiting (30d)", "type": "number"},
        {"key": "pipe_fee_staffing", "label": "Pipeline Staffing fee ($)", "type": "currency"},
        {"key": "pipe_revenue_staffing", "label": "Pipeline Staffing revenue ($)", "type": "currency"},
        {"key": "churn_fee_loss_staffing_30d", "label": "Fee perdido por churn Staffing 30d", "type": "currency"},
        {"key": "churn_revenue_loss_staffing_30d", "label": "Revenue perdido por churn Staffing 30d", "type": "currency"},
        {"key": "ltv_months", "label": "LTV (avg months per client)", "type": "number"},
        {"key": "net_mrr_fee_staffing_30d", "label": "Net MRR fee Staffing 30d ($/mes)", "type": "currency"},
        {"key": "net_mrr_revenue_staffing_30d", "label": "Net MRR revenue Staffing 30d ($/mes)", "type": "currency"},
        {"key": "net_ltv_fee_staffing_30d", "label": "Net LTV fee Staffing 30d ($)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
