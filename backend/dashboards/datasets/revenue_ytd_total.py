from __future__ import annotations

from datetime import date, datetime


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
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH params AS (
          SELECT
            %(corte)s::date AS corte_d,
            DATE_TRUNC('year', %(corte)s::date)::date AS year_start,
            (%(corte)s::date - INTERVAL '1 year')::date AS corte_py,
            DATE_TRUNC('year', (%(corte)s::date - INTERVAL '1 year'))::date AS year_start_py
        ),
        periods AS (
          SELECT 'curr'::text AS period, corte_d AS corte_e, year_start AS year_start_e FROM params
          UNION ALL
          SELECT 'py'::text   AS period, corte_py, year_start_py FROM params
        ),
        meses AS (
          SELECT
            p.period,
            DATE_TRUNC('month', gs)::date AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM periods p,
               generate_series(p.year_start_e, p.corte_e, INTERVAL '1 month') gs
        ),
        staffing_hires AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            ho.opportunity_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary,0)::numeric AS salary,
            COALESCE(ho.fee,0)::numeric AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
        ),
        -- Same salary_updates logic as cohort_by_contractor: primary opp per
        -- (period, mes, candidate, account) gets the salary_updates override,
        -- secondaries keep their stored hire_opportunity values.
        opps_in_month AS (
          SELECT DISTINCT ON (m.period, m.mes, h.opportunity_id, h.candidate_id)
            m.period, m.mes, m.fin_mes,
            h.opportunity_id, h.candidate_id, h.account_id,
            h.start_d, h.salary AS hire_salary, h.fee AS hire_fee
          FROM meses m
          JOIN staffing_hires h
            ON h.start_d IS NOT NULL
           AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.period, m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        opps_marked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (
              PARTITION BY period, mes, candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn_primary
          FROM opps_in_month
        ),
        effective_per_opp AS (
          SELECT
            om.period, om.mes, om.candidate_id, om.account_id,
            CASE
              WHEN om.rn_primary = 1
                THEN COALESCE(su_recent.salary::numeric, su_earliest.salary::numeric, om.hire_salary)
              ELSE om.hire_salary
            END AS salary,
            CASE
              WHEN om.rn_primary = 1
                THEN COALESCE(su_recent.fee::numeric, su_earliest.fee::numeric, om.hire_fee)
              ELSE om.hire_fee
            END AS fee
          FROM opps_marked om
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee
            FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id
              AND s.date IS NOT NULL
              AND s.date::date <= om.fin_mes
            ORDER BY s.date::date DESC, s.update_id DESC
            LIMIT 1
          ) su_recent ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee
            FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id
              AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id ASC
            LIMIT 1
          ) su_earliest ON TRUE
        ),
        effective_in_month AS (
          SELECT period, mes, candidate_id, account_id,
                 SUM(salary)::numeric AS salary,
                 SUM(fee)::numeric    AS fee
          FROM effective_per_opp
          GROUP BY period, mes, candidate_id, account_id
        ),
        staffing_mrr AS (
          SELECT period, mes, SUM(salary + fee)::numeric AS mrr_mes
          FROM effective_in_month
          GROUP BY period, mes
        ),
        staffing_ytd AS (
          SELECT
            COALESCE(SUM(CASE WHEN period = 'curr' THEN mrr_mes END), 0)::numeric AS revenue_staffing_ytd,
            COALESCE(SUM(CASE WHEN period = 'py'   THEN mrr_mes END), 0)::numeric AS revenue_staffing_ytd_py
          FROM staffing_mrr
        ),
        recruiting_ytd AS (
          SELECT
            COALESCE(SUM(CASE
              WHEN o.opp_close_date >= p.year_start
               AND o.opp_close_date <= p.corte_d  THEN ho.revenue END), 0)::numeric AS revenue_recruiting_ytd,
            COALESCE(SUM(CASE
              WHEN o.opp_close_date >= p.year_start_py
               AND o.opp_close_date <= p.corte_py THEN ho.revenue END), 0)::numeric AS revenue_recruiting_ytd_py
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          CROSS JOIN params p
          WHERE o.opp_model = 'Recruiting'
            AND TRIM(o.opp_stage) = 'Close Win'   -- R10: solo revenue de opps ganadas
            AND o.opp_close_date IS NOT NULL
            AND o.opp_close_date >= p.year_start_py
            AND o.opp_close_date <= p.corte_d
        )
        SELECT
          (SELECT corte_d       FROM params)            AS corte,
          (SELECT year_start    FROM params)            AS year_start,
          (SELECT corte_py      FROM params)            AS corte_py,
          (SELECT year_start_py FROM params)            AS year_start_py,
          s.revenue_staffing_ytd::bigint                AS revenue_staffing_ytd,
          s.revenue_staffing_ytd_py::bigint             AS revenue_staffing_ytd_py,
          r.revenue_recruiting_ytd::bigint              AS revenue_recruiting_ytd,
          r.revenue_recruiting_ytd_py::bigint           AS revenue_recruiting_ytd_py,
          (s.revenue_staffing_ytd + r.revenue_recruiting_ytd)::bigint       AS revenue_total_ytd,
          (s.revenue_staffing_ytd_py + r.revenue_recruiting_ytd_py)::bigint AS revenue_total_ytd_py,
          CASE WHEN s.revenue_staffing_ytd_py = 0 THEN NULL
               ELSE ((s.revenue_staffing_ytd - s.revenue_staffing_ytd_py)
                     / ABS(s.revenue_staffing_ytd_py)::numeric) * 100
          END AS revenue_staffing_ytd_yoy_pct,
          CASE WHEN r.revenue_recruiting_ytd_py = 0 THEN NULL
               ELSE ((r.revenue_recruiting_ytd - r.revenue_recruiting_ytd_py)
                     / ABS(r.revenue_recruiting_ytd_py)::numeric) * 100
          END AS revenue_recruiting_ytd_yoy_pct,
          CASE WHEN (s.revenue_staffing_ytd_py + r.revenue_recruiting_ytd_py) = 0 THEN NULL
               ELSE (((s.revenue_staffing_ytd + r.revenue_recruiting_ytd)
                      - (s.revenue_staffing_ytd_py + r.revenue_recruiting_ytd_py))
                     / ABS(s.revenue_staffing_ytd_py + r.revenue_recruiting_ytd_py)::numeric) * 100
          END AS revenue_total_ytd_yoy_pct
        FROM staffing_ytd s, recruiting_ytd r;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "revenue_ytd_total",
    "label": "Revenue YTD — Staffing + Recruiting",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
        {"key": "year_start", "label": "Año desde", "type": "date"},
        {"key": "corte_py", "label": "Corte PY", "type": "date"},
        {"key": "year_start_py", "label": "Año PY desde", "type": "date"},
    ],
    "measures": [
        {"key": "revenue_staffing_ytd", "label": "Revenue Staffing YTD", "type": "currency"},
        {"key": "revenue_staffing_ytd_py", "label": "Revenue Staffing YTD (PY)", "type": "currency"},
        {"key": "revenue_staffing_ytd_yoy_pct", "label": "Revenue Staffing YoY %", "type": "percent"},
        {"key": "revenue_recruiting_ytd", "label": "Revenue Recruiting YTD", "type": "currency"},
        {"key": "revenue_recruiting_ytd_py", "label": "Revenue Recruiting YTD (PY)", "type": "currency"},
        {"key": "revenue_recruiting_ytd_yoy_pct", "label": "Revenue Recruiting YoY %", "type": "percent"},
        {"key": "revenue_total_ytd", "label": "Revenue Total YTD", "type": "currency"},
        {"key": "revenue_total_ytd_py", "label": "Revenue Total YTD (PY)", "type": "currency"},
        {"key": "revenue_total_ytd_yoy_pct", "label": "Revenue Total YoY %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
