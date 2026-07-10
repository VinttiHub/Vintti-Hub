"""Detalle del mes — Sales GMRR / MRR Staffing Outbound (AE).

Para el mes seleccionado (filtro `mes` = 'YYYY-MM'), lista los contratos Staffing
ACTIVOS ese mes (canal Outbound, AE) con su salary/fee efectivo y labels ya
formateados ("$...") para mostrar el monto en la lista del month-detail.
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
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    mes = (
        _parse_date(filters.get("mes"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("fecha"))
    )

    sql = """
        WITH params AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_ini,
          (COALESCE(DATE_TRUNC('month', %(mes)s::date)::date, DATE_TRUNC('month', CURRENT_DATE)::date)
            + INTERVAL '1 month - 1 day')::date AS fin_mes
        ),
        hires AS (
          SELECT
            h.candidate_id, h.account_id, h.opportunity_id,
            a.client_name, COALESCE(c.name,'') AS candidate_name,
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
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND h.candidate_id IS NOT NULL AND h.account_id IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ),
        activos AS (
          SELECT h.* FROM hires h CROSS JOIN params p
          WHERE h.start_d IS NOT NULL AND h.start_d <= p.fin_mes
            AND (h.end_d IS NULL OR h.end_d >= p.fin_mes)
        ),
        marked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY candidate_id, account_id
            ORDER BY start_d DESC NULLS LAST, opportunity_id DESC) AS rn
          FROM activos
        ),
        eff AS (
          SELECT m.client_name, m.candidate_name,
            CASE WHEN m.rn=1 THEN COALESCE(su.salary::numeric, m.hire_salary) ELSE m.hire_salary END AS salary,
            CASE WHEN m.rn=1 THEN COALESCE(su.fee::numeric, m.hire_fee) ELSE m.hire_fee END AS fee
          FROM marked m CROSS JOIN params p
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = m.candidate_id AND s.date IS NOT NULL AND s.date::date <= p.fin_mes
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su ON TRUE
        )
        SELECT
          client_name,
          candidate_name,
          '$' || TO_CHAR((salary + fee), 'FM999,999,999') AS gmrr_label,
          '$' || TO_CHAR(fee, 'FM999,999,999')            AS fee_label,
          (salary + fee)::bigint AS gmrr
        FROM eff
        ORDER BY gmrr DESC, client_name;
    """

    return sql, {"mes": mes, "ae_leads": AE_LEADS}


DATASET = {
    "key": "sales_mrr_staffing_ae_month_detail",
    "label": "Sales GMRR / MRR — Staffing Outbound (AE) · detalle del mes",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "gmrr_label", "label": "GMRR", "type": "string"},
        {"key": "fee_label", "label": "Fee Vintti", "type": "string"},
    ],
    "measures": [
        {"key": "gmrr", "label": "GMRR", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
