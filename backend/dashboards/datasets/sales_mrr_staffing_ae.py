"""Sales GMRR / MRR — Staffing, canal Outbound, solo AE (snapshot mensual).

Valor recurrente MENSUAL al corte (no acumulado) de los contratos Staffing ACTIVOS
del canal Outbound vendidos por un AE (`opp_sales_lead` ∈ {mariano, bahia}):
  - gmrr     = Σ (salary + fee)  → "Fee total (salario + Vintti)"
  - mrr_fee  = Σ (fee)           → "Fee Vintti only"
Usa el salary/fee efectivo vigente al corte (salary_updates) y dedup de opp primaria
por (candidato, cuenta), igual que el resto de los datasets de MRR.
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


_HIRES_CTE = """
        params AS (SELECT %(corte)s::date AS corte_d),
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
            AND h.candidate_id IS NOT NULL AND h.account_id IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ),
        activos AS (
          SELECT h.* FROM hires h CROSS JOIN params p
          WHERE h.start_d IS NOT NULL AND h.start_d <= p.corte_d
            AND (h.end_d IS NULL OR h.end_d >= p.corte_d)
        ),
        marked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY candidate_id, account_id
            ORDER BY start_d DESC NULLS LAST, opportunity_id DESC) AS rn
          FROM activos
        ),
        eff AS (
          SELECT m.account_id, m.candidate_id, m.client_name, m.candidate_name, m.start_d,
            CASE WHEN m.rn=1 THEN COALESCE(su.salary::numeric, m.hire_salary) ELSE m.hire_salary END AS salary,
            CASE WHEN m.rn=1 THEN COALESCE(su.fee::numeric, m.hire_fee) ELSE m.hire_fee END AS fee
          FROM marked m CROSS JOIN params p
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = m.candidate_id AND s.date IS NOT NULL AND s.date::date <= p.corte_d
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su ON TRUE
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
        WITH {_HIRES_CTE}
        SELECT
          SUM(salary + fee)::bigint        AS gmrr,
          SUM(fee)::bigint                 AS mrr_fee,
          SUM(salary)::bigint              AS salary_total,
          COUNT(DISTINCT account_id)::int  AS account_count,
          COUNT(*)::int                    AS contract_count
        FROM eff;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET = {
    "key": "sales_mrr_staffing_ae",
    "label": "Sales GMRR / MRR — Staffing Outbound (AE, snapshot mensual)",
    "dimensions": [],
    "measures": [
        {"key": "gmrr", "label": "GMRR (salary + fee)", "type": "currency"},
        {"key": "mrr_fee", "label": "MRR Fee Vintti", "type": "currency"},
        {"key": "salary_total", "label": "Salary total", "type": "currency"},
        {"key": "account_count", "label": "Cuentas", "type": "number"},
        {"key": "contract_count", "label": "Contratos", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}


# Detalle por contrato (mismo scope) — para "Ver detalle".
def query_detail(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )
    sql = f"""
        WITH {_HIRES_CTE}
        SELECT
          client_name,
          candidate_name,
          salary::bigint AS salary,
          fee::bigint AS fee,
          (salary + fee)::bigint AS gmrr
        FROM eff
        ORDER BY gmrr DESC, client_name;
    """
    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET_DETAIL = {
    "key": "sales_mrr_staffing_ae_detail",
    "label": "Sales GMRR / MRR — Staffing Outbound (AE) · Detalle por contrato",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee Vintti", "type": "currency"},
        {"key": "gmrr", "label": "GMRR", "type": "currency"},
    ],
    "default_filters": {},
    "query": query_detail,
}
