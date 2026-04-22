from __future__ import annotations


def query(_filters: dict, *_args, **_kwargs) -> tuple[str, tuple]:
    sql = """
        WITH recruiting_revenue AS (
          SELECT COALESCE(SUM(h.revenue), 0)::bigint AS total
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          WHERE lower(o.opp_model) LIKE 'recruiting%%'
            AND h.start_date >= (CURRENT_DATE - INTERVAL '30 days')
        ),
        active_staffing AS (
          SELECT COUNT(DISTINCT h.candidate_id) AS c
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          WHERE h.end_date IS NULL
            AND lower(o.opp_model) LIKE 'staffing%%'
        ),
        active_recruiting AS (
          SELECT COUNT(DISTINCT h.candidate_id) AS c
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          WHERE h.end_date IS NULL
            AND lower(o.opp_model) LIKE 'recruiting%%'
        ),
        ltv AS (
          SELECT COALESCE(AVG(months_active), 0)::numeric(10,2) AS months
          FROM (
            SELECT h.candidate_id,
                   EXTRACT(YEAR FROM age(COALESCE(h.end_date::timestamp, NOW()), h.start_date::timestamp)) * 12
                 + EXTRACT(MONTH FROM age(COALESCE(h.end_date::timestamp, NOW()), h.start_date::timestamp)) AS months_active
            FROM hire_opportunity h
            JOIN opportunity o ON o.opportunity_id = h.opportunity_id
            WHERE lower(o.opp_model) LIKE 'staffing%%'
              AND h.start_date IS NOT NULL
          ) sub
        )
        SELECT
          (SELECT total  FROM recruiting_revenue) AS recruiting_revenue_30d,
          (SELECT c      FROM active_staffing)    AS active_staffing,
          (SELECT c      FROM active_recruiting)  AS active_recruiting,
          (SELECT months FROM ltv)                AS ltv_months;
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
