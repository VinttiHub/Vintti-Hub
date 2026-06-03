"""Annual Revenue (Sales · AE + AM) — canal Outbound, acumulado YTD.

Misma lógica que el "Revenue YTD" del Management Dashboard (`revenue_ytd_total`):
  - Staffing  = Σ del MRR mensual (salary + fee de contratos activos, con
                salary_updates) de enero a corte.
  - Recruiting = Σ ho.revenue (one-time) de close wins Recruiting del año.
Pero filtrado al canal Outbound y al book AE+AM:
  account.where_come_from = 'Outbound'  AND
  ( opp_sales_lead ∈ {AEs}  OR  account_manager = {AM} ).

Se parte en Staffing vs Recruiting (suman al total), cada uno con su detalle.
"""
from __future__ import annotations

from datetime import date, datetime


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)


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


# Scope outbound + unión AE/AM (mismo predicado para Staffing y Recruiting).
_SCOPE = """
    LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
    AND (
      TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
      OR TRIM(LOWER(a.account_manager)) IN %(am_leads)s
    )
"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )

    sql = f"""
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
          SELECT 'py'::text AS period, corte_py, year_start_py FROM params
        ),
        meses AS (
          SELECT p.period, DATE_TRUNC('month', gs)::date AS mes,
                 (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM periods p, generate_series(p.year_start_e, p.corte_e, INTERVAL '1 month') gs
        ),
        staffing_hires AS (
          SELECT
            ho.candidate_id, ho.account_id, ho.opportunity_id,
            CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                 ELSE NULLIF(ho.start_date::text,'')::date END AS start_d,
            CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                 WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
                 ELSE ho.end_date::date END AS end_d,
            COALESCE(ho.salary,0)::numeric AS salary,
            COALESCE(ho.fee,0)::numeric AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a ON a.account_id = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL AND ho.account_id IS NOT NULL
            AND {_SCOPE}
        ),
        opps_in_month AS (
          SELECT DISTINCT ON (m.period, m.mes, h.opportunity_id, h.candidate_id)
            m.period, m.mes, m.fin_mes, h.opportunity_id, h.candidate_id, h.account_id,
            h.start_d, h.salary AS hire_salary, h.fee AS hire_fee
          FROM meses m
          JOIN staffing_hires h
            ON h.start_d IS NOT NULL AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.period, m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        opps_marked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY period, mes, candidate_id, account_id
            ORDER BY start_d DESC NULLS LAST, opportunity_id DESC) AS rn_primary
          FROM opps_in_month
        ),
        effective_per_opp AS (
          SELECT om.period, om.mes, om.candidate_id, om.account_id,
            CASE WHEN om.rn_primary = 1
                 THEN COALESCE(su_recent.salary::numeric, su_earliest.salary::numeric, om.hire_salary)
                 ELSE om.hire_salary END AS salary,
            CASE WHEN om.rn_primary = 1
                 THEN COALESCE(su_recent.fee::numeric, su_earliest.fee::numeric, om.hire_fee)
                 ELSE om.hire_fee END AS fee
          FROM opps_marked om
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id AND s.date IS NOT NULL AND s.date::date <= om.fin_mes
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su_recent ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id ASC LIMIT 1
          ) su_earliest ON TRUE
        ),
        staffing_mrr AS (
          SELECT period, SUM(salary + fee)::numeric AS rev
          FROM effective_per_opp GROUP BY period
        ),
        staffing AS (
          SELECT
            COALESCE(SUM(rev) FILTER (WHERE period='curr'), 0)::numeric AS staffing_ytd,
            COALESCE(SUM(rev) FILTER (WHERE period='py'),   0)::numeric AS staffing_ytd_py
          FROM staffing_mrr
        ),
        staffing_cnt AS (
          SELECT COUNT(DISTINCT account_id)::int AS staffing_count
          FROM effective_per_opp WHERE period='curr'
        ),
        recruiting AS (
          SELECT
            COALESCE(SUM(COALESCE(ho.revenue,0)) FILTER (
              WHERE o.opp_close_date >= p.year_start AND o.opp_close_date <= p.corte_d), 0)::numeric AS recruiting_ytd,
            COALESCE(SUM(COALESCE(ho.revenue,0)) FILTER (
              WHERE o.opp_close_date >= p.year_start_py AND o.opp_close_date <= p.corte_py), 0)::numeric AS recruiting_ytd_py,
            COUNT(DISTINCT o.opportunity_id) FILTER (
              WHERE o.opp_close_date >= p.year_start AND o.opp_close_date <= p.corte_d)::int AS recruiting_count
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a ON a.account_id = ho.account_id
          CROSS JOIN params p
          WHERE o.opp_model = 'Recruiting'
            AND o.opp_close_date IS NOT NULL
            AND o.opp_close_date >= p.year_start_py AND o.opp_close_date <= p.corte_d
            AND TRIM(o.opp_stage) = 'Close Win'
            AND {_SCOPE}
        )
        SELECT
          (SELECT corte_d FROM params) AS corte,
          (s.staffing_ytd + r.recruiting_ytd)::bigint        AS total_revenue,
          s.staffing_ytd::bigint                             AS staffing_revenue,
          r.recruiting_ytd::bigint                           AS recruiting_revenue,
          (s.staffing_ytd_py + r.recruiting_ytd_py)::bigint  AS total_revenue_py,
          ROUND(s.staffing_ytd  * 100.0 / NULLIF(s.staffing_ytd + r.recruiting_ytd, 0), 1) AS staffing_pct_of_total,
          ROUND(r.recruiting_ytd * 100.0 / NULLIF(s.staffing_ytd + r.recruiting_ytd, 0), 1) AS recruiting_pct_of_total,
          sc.staffing_count,
          r.recruiting_count,
          (sc.staffing_count + r.recruiting_count)::int      AS total_count,
          CASE WHEN (s.staffing_ytd_py + r.recruiting_ytd_py) = 0 THEN NULL
               ELSE (((s.staffing_ytd + r.recruiting_ytd) - (s.staffing_ytd_py + r.recruiting_ytd_py))
                     / ABS(s.staffing_ytd_py + r.recruiting_ytd_py)::numeric) * 100 END AS total_yoy_pct
        FROM staffing s, staffing_cnt sc, recruiting r;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS, "am_leads": AM_LEADS}


DATASET = {
    "key": "revenue_outbound_ytd",
    "label": "Annual Revenue Sales — Outbound · AE + AM (YTD, Staffing + Recruiting)",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "total_revenue", "label": "Revenue total YTD", "type": "currency"},
        {"key": "staffing_revenue", "label": "Staffing YTD", "type": "currency"},
        {"key": "recruiting_revenue", "label": "Recruiting YTD", "type": "currency"},
        {"key": "total_revenue_py", "label": "Revenue total YTD (PY)", "type": "currency"},
        {"key": "staffing_pct_of_total", "label": "Staffing % del total", "type": "percent"},
        {"key": "recruiting_pct_of_total", "label": "Recruiting % del total", "type": "percent"},
        {"key": "staffing_count", "label": "Cuentas Staffing", "type": "number"},
        {"key": "recruiting_count", "label": "Closes Recruiting", "type": "number"},
        {"key": "total_count", "label": "Total", "type": "number"},
        {"key": "total_yoy_pct", "label": "YoY %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
