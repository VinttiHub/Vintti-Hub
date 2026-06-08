"""Gross MRR Staffing YTD per mes — AEs only (Mariano + Bahia).

Para cada mes desde 1 de enero del año actual hasta el mes actual, devuelve:
  - `monthly_gmrr`     : SUM(salary + fee) de hires Staffing activos al cierre
                         de ese mes, cuyo `opp_sales_lead` ∈ {mariano, bahia}.
  - `cumulative_gmrr`  : suma corrida desde enero hasta ese mes.
  - `active_contractors` / `active_accounts`: head-count en cada mes.
  - `total_ytd`        : total acumulado al mes actual (mismo valor en todas
                         las filas — sirve como hero number en el card).

Activos = hire cuyo `carga_active` (o `start_date` como fallback) ≤ fin de mes
AND `carga_inactive`/`end_date` es NULL o ≥ fin de mes. Misma lógica que
`mrr_history.py` para que los totales cuadren con el resto del dashboard.
"""
from __future__ import annotations

from datetime import date, datetime


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = datetime.utcnow().date()
    year_start = date(today.year, 1, 1)
    period_end = today

    sql = """
        WITH hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee, 0)::numeric    AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            -- YTD: solo deals cuya Close Win fue este año (a partir del 1 de enero).
            AND NULLIF(o.opp_close_date::text, '')::date >= %(year_start)s::date
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM generate_series(%(year_start)s::date, %(period_end)s::date, INTERVAL '1 month') gs
        ),
        monthly AS (
          SELECT
            m.mes,
            COALESCE(SUM(h.salary + h.fee), 0)::numeric  AS monthly_gmrr,
            COUNT(DISTINCT h.candidate_id) FILTER (WHERE h.candidate_id IS NOT NULL)::int AS active_contractors,
            COUNT(DISTINCT h.account_id)   FILTER (WHERE h.account_id   IS NOT NULL)::int AS active_accounts
          FROM meses m
          LEFT JOIN hires h
            ON h.start_d IS NOT NULL
           AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          GROUP BY m.mes
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM')                                          AS mes,
          monthly_gmrr::bigint                                             AS monthly_gmrr,
          SUM(monthly_gmrr) OVER (ORDER BY mes)::bigint                    AS cumulative_gmrr,
          active_contractors,
          active_accounts,
          SUM(monthly_gmrr) OVER ()::bigint                                AS total_ytd
        FROM monthly
        ORDER BY mes;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "year_start": year_start,
        "period_end": period_end,
    }


DATASET = {
    "key": "gmrr_ae_history",
    "label": "Gross MRR Staffing YTD (M+B) — por mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "active_contractors", "label": "Contractors activos", "type": "number"},
        {"key": "active_accounts", "label": "Clientes activos", "type": "number"},
    ],
    "measures": [
        {"key": "monthly_gmrr", "label": "GMRR mensual", "type": "currency"},
        {"key": "cumulative_gmrr", "label": "GMRR acumulado YTD", "type": "currency"},
        {"key": "total_ytd", "label": "Total YTD", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
