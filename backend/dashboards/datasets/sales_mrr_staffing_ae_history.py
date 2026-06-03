"""Sales GMRR / MRR — Staffing Outbound (AE) · historia mensual (año en curso).

Una fila por mes (ene → corte) con el MRR de ese mes:
  - gmrr    = Σ (salary + fee) de contratos Staffing activos ese mes
  - mrr_fee = Σ (fee)
Scope: canal Outbound + AE (opp_sales_lead ∈ {mariano, bahia}). Misma mecánica de
salary_updates + dedup de opp primaria que el resto. El YTD acumulado del front
se obtiene sumando la columna (reduce=sum).
"""
from __future__ import annotations

from datetime import date, datetime


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d, DATE_TRUNC('year', %(corte)s::date)::date AS year_start
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes,
                 (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM params p, generate_series(p.year_start, p.corte_d, INTERVAL '1 month') gs
        ),
        staffing_hires AS (
          SELECT
            h.candidate_id, h.account_id, h.opportunity_id,
            CASE WHEN h.carga_active IS NOT NULL THEN h.carga_active::date
                 ELSE NULLIF(h.start_date::text,'')::date END AS start_d,
            CASE WHEN h.carga_inactive IS NOT NULL THEN h.carga_inactive::date
                 WHEN NULLIF(h.end_date::text,'') IS NULL THEN NULL
                 ELSE h.end_date::date END AS end_d,
            COALESCE(h.salary,0)::numeric AS hire_salary,
            COALESCE(h.fee,0)::numeric AS hire_fee
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          JOIN account a ON a.account_id = h.account_id
          WHERE o.opp_model = 'Staffing'
            AND h.candidate_id IS NOT NULL AND h.account_id IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ),
        opps_in_month AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, m.fin_mes, h.opportunity_id, h.candidate_id, h.account_id,
            h.start_d, h.hire_salary, h.hire_fee
          FROM meses m
          JOIN staffing_hires h
            ON h.start_d IS NOT NULL AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        opps_marked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY mes, candidate_id, account_id
            ORDER BY start_d DESC NULLS LAST, opportunity_id DESC) AS rn
          FROM opps_in_month
        ),
        eff AS (
          SELECT om.mes,
            CASE WHEN om.rn=1 THEN COALESCE(su.salary::numeric, om.hire_salary) ELSE om.hire_salary END AS salary,
            CASE WHEN om.rn=1 THEN COALESCE(su.fee::numeric, om.hire_fee) ELSE om.hire_fee END AS fee
          FROM opps_marked om
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id AND s.date IS NOT NULL AND s.date::date <= om.fin_mes
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su ON TRUE
        ),
        per_month AS (
          SELECT mes,
            SUM(salary + fee)::bigint AS gmrr,
            SUM(fee)::bigint AS mrr_fee
          FROM eff GROUP BY mes
        )
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM') AS mes,
          COALESCE(pm.gmrr, 0)::bigint    AS gmrr,
          COALESCE(pm.mrr_fee, 0)::bigint AS mrr_fee
        FROM meses m
        LEFT JOIN per_month pm ON pm.mes = m.mes
        ORDER BY m.mes;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET = {
    "key": "sales_mrr_staffing_ae_history",
    "label": "Sales GMRR / MRR — Staffing Outbound (AE) · mensual (año en curso)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "gmrr", "label": "GMRR (salary+fee)", "type": "currency"},
        {"key": "mrr_fee", "label": "MRR Fee Vintti", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
