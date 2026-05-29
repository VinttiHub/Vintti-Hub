"""Breakdown per contractor of Gross MRR Staffing al corte (hoy) — AEs only.

Lista cada hire Staffing activo HOY cuyo `opp_sales_lead` ∈ {Mariano, Bahia}.
Cada fila aporta `salary + fee` (= GMRR mensual). La suma de la columna `gmrr`
es el último mes (`monthly_gmrr` actual) de `gmrr_ae_history`.

Usado en el drawer del card "Gross MRR Staffing YTD" del tab AE.
"""
from __future__ import annotations

from datetime import date, datetime


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


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
    # `corte` = end of selected month, sent by refetchMonthAwareElements when
    # the user clicks a point on the YTD line chart. Defaults to today.
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH hires AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            COALESCE(c.name, '')                                          AS candidate_name,
            COALESCE(a.client_name, '')                                   AS client_name,
            COALESCE(o.opp_sales_lead, '')                                AS opp_sales_lead,
            COALESCE(ho.salary, 0)::numeric                               AS salary,
            COALESCE(ho.fee, 0)::numeric                                  AS fee,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active
              ELSE NULLIF(ho.start_date::text, '')::date
            END                                                           AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END                                                           AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o      ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN candidates c  ON c.candidate_id   = ho.candidate_id
          LEFT JOIN account a     ON a.account_id     = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND ho.candidate_id IS NOT NULL
        )
        SELECT
          h.candidate_name,
          h.client_name,
          h.opp_sales_lead,
          h.salary::float                       AS salary,
          h.fee::float                          AS fee,
          (h.salary + h.fee)::float             AS gmrr,
          TO_CHAR(h.start_d, 'YYYY-MM-DD')      AS start_date
        FROM hires h
        WHERE h.start_d IS NOT NULL
          AND h.start_d <= %(corte)s::date
          AND (h.end_d IS NULL OR h.end_d >= %(corte)s::date)
        ORDER BY gmrr DESC NULLS LAST, h.candidate_name;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "corte": corte,
    }


DATASET = {
    "key": "gmrr_ae_detail",
    "label": "Gross MRR Staffing — Detalle contractors activos (M+B)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "start_date", "label": "Start", "type": "date"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee", "type": "currency"},
        {"key": "gmrr", "label": "GMRR mensual", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
