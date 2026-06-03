"""Detalle Staffing del Revenue Outbound (AE+AM) — contratos activos al corte.

Una fila por hire Staffing ACTIVO al corte, del canal Outbound y book AE+AM, con
su MRR (salary + fee, con override de salary_updates vigente). Sirve para verificar
de qué se compone el MRR Staffing acumulado.
"""
from __future__ import annotations

from datetime import date, datetime


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)


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
            a.client_name, COALESCE(c.name,'') AS candidate_name,
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
          LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
          WHERE o.opp_model = 'Staffing'
            AND h.candidate_id IS NOT NULL AND h.account_id IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND (TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
                 OR TRIM(LOWER(a.account_manager)) IN %(am_leads)s)
        ),
        opps_in_month AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, m.fin_mes, h.opportunity_id, h.candidate_id, h.account_id,
            h.client_name, h.candidate_name, h.start_d,
            h.hire_salary, h.hire_fee
          FROM meses m
          JOIN staffing_hires h
            ON h.start_d IS NOT NULL AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        opps_marked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY mes, candidate_id, account_id
            ORDER BY start_d DESC NULLS LAST, opportunity_id DESC) AS rn_primary
          FROM opps_in_month
        ),
        eff AS (
          SELECT om.candidate_id, om.account_id, om.client_name, om.candidate_name, om.start_d,
            CASE WHEN om.rn_primary=1
                 THEN COALESCE(su.salary::numeric, om.hire_salary) ELSE om.hire_salary END
            + CASE WHEN om.rn_primary=1
                 THEN COALESCE(su.fee::numeric, om.hire_fee) ELSE om.hire_fee END AS mrr_mes
          FROM opps_marked om
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id AND s.date IS NOT NULL AND s.date::date <= om.fin_mes
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su ON TRUE
        )
        SELECT
          client_name,
          candidate_name,
          TO_CHAR(MIN(start_d),'YYYY-MM-DD') AS start_d,
          SUM(mrr_mes)::bigint AS mrr
        FROM eff
        GROUP BY client_name, candidate_name
        ORDER BY mrr DESC, client_name;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS, "am_leads": AM_LEADS}


DATASET = {
    "key": "revenue_outbound_staffing_detail",
    "label": "Revenue Outbound — Detalle Staffing (MRR activo)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
    ],
    "measures": [
        {"key": "mrr", "label": "Aporte YTD (MRR acumulado)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
