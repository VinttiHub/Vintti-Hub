from __future__ import annotations


def query(_filters: dict, *_args, **_kwargs) -> tuple[str, tuple]:
    sql = """
        WITH recruiting_revenue AS (
          SELECT COALESCE(SUM(h.revenue::numeric), 0)::bigint AS total
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          WHERE lower(o.opp_model) LIKE 'recruiting%%'
            AND NULLIF(h.start_date, '')::date >= (CURRENT_DATE - INTERVAL '30 days')
        ),
        active_staffing AS (
          SELECT COUNT(DISTINCT h.candidate_id) AS c
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          WHERE (h.end_date IS NULL OR h.end_date = '')
            AND lower(o.opp_model) LIKE 'staffing%%'
        ),
        active_recruiting AS (
          SELECT COUNT(DISTINCT h.candidate_id) AS c
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          WHERE (h.end_date IS NULL OR h.end_date = '')
            AND lower(o.opp_model) LIKE 'recruiting%%'
        ),
        ltv_candidatos AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL
                THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date, '') IS NOT NULL
                THEN NULLIF(ho.start_date, '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL
                THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR ho.end_date = ''
                THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(ho.start_date, '') IS NOT NULL
            )
            AND o.opp_model = 'Staffing'
        ),
        ltv_meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM ltv_candidatos),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM ltv_candidatos),
            interval '1 month'
          ) gs
        ),
        ltv_activos_mes AS (
          SELECT
            m.mes,
            c.account_id,
            COUNT(DISTINCT c.candidate_id) AS activos
          FROM ltv_meses m
          JOIN ltv_candidatos c
            ON c.start_d < (m.mes + interval '1 month')
           AND (c.end_d IS NULL OR c.end_d >= m.mes)
          GROUP BY m.mes, c.account_id
        ),
        ltv_duracion_cliente AS (
          SELECT account_id, COUNT(*) AS active_months
          FROM ltv_activos_mes
          WHERE activos > 0
          GROUP BY account_id
        )
        SELECT
          (SELECT total FROM recruiting_revenue)                            AS recruiting_revenue_30d,
          (SELECT c     FROM active_staffing)                               AS active_staffing,
          (SELECT c     FROM active_recruiting)                             AS active_recruiting,
          (SELECT COALESCE(AVG(active_months), 0)::numeric(10, 0)
             FROM ltv_duracion_cliente)                                     AS ltv_months;
    """
    return sql, ()


DATASET = {
    "key": "management_dashboard",
    "label": "Management Dashboard KPIs",
    "dimensions": [],
    "measures": [
        {"key": "recruiting_revenue_30d", "label": "Recruiting Revenue (30d)", "type": "currency"},
        {"key": "active_staffing", "label": "Active Staffing", "type": "number"},
        {"key": "active_recruiting", "label": "Active Recruiting", "type": "number"},
        {"key": "ltv_months", "label": "LTV Months", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
