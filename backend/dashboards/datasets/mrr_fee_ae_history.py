"""MRR Staffing YTD per mes — Vintti fee only (sin salario), AEs only.

Espejo de `gmrr_ae_history` pero sumando SOLO `ho.fee` — el margen de Vintti,
no el costo del candidato. Mismo set de hires activos M+B (Mariano + Bahia).

Para cada mes desde 1 de enero del año actual hasta el mes actual:
  - `monthly_fee`     : SUM(fee) de hires Staffing activos al cierre del mes.
  - `cumulative_fee`  : suma corrida desde enero.
  - `total_ytd_fee`   : total acumulado al mes actual (constante en todas las filas).
  - `active_contractors` / `active_accounts`: head-count por mes (mismos valores
    que `gmrr_ae_history` — la base de hires es la misma).
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
            COALESCE(ho.fee, 0)::numeric AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
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
            COALESCE(SUM(h.fee), 0)::numeric AS monthly_fee,
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
          monthly_fee::bigint                                              AS monthly_fee,
          SUM(monthly_fee) OVER (ORDER BY mes)::bigint                     AS cumulative_fee,
          active_contractors,
          active_accounts,
          SUM(monthly_fee) OVER ()::bigint                                 AS total_ytd_fee
        FROM monthly
        ORDER BY mes;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "year_start": year_start,
        "period_end": period_end,
    }


DATASET = {
    "key": "mrr_fee_ae_history",
    "label": "MRR Staffing YTD · Vintti fee only (M+B) — por mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "active_contractors", "label": "Contractors activos", "type": "number"},
        {"key": "active_accounts", "label": "Clientes activos", "type": "number"},
    ],
    "measures": [
        {"key": "monthly_fee", "label": "Fee mensual", "type": "currency"},
        {"key": "cumulative_fee", "label": "Fee acumulado YTD", "type": "currency"},
        {"key": "total_ytd_fee", "label": "Total YTD (fee)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
