"""Cohort by client · current-month MRR summary per account (Staffing).

Una fila por cliente (account) con los contractors Staffing activos al cierre del
mes actual. Mirror EXACTO de la lógica de `mrr_history` (salary_updates override
del opp primario, suma de opps paralelas por candidato/cuenta) para que los
totales reconcilien con las cards GMRR (Revenue) y MRR (Fee) del Management
Dashboard.

Columnas:
  - total_employees : COUNT(DISTINCT candidate) activo en la cuenta.
  - gmrr            : SUM(salary + fee)  → lo que paga el cliente (= GMRR Revenue).
  - mrr             : SUM(fee)           → el fee de Vintti (= MRR Fee).
  - margin_pct      : 100 * mrr / gmrr   → margen Vintti sobre el pago del cliente.
  - weight_pct      : 100 * mrr / SUM(mrr) → peso del cliente sobre el MRR total.
"""
from __future__ import annotations

from datetime import date, datetime


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


def _end_of_month(d: date) -> date:
    if d.month == 12:
        nxt = date(d.year + 1, 1, 1)
    else:
        nxt = date(d.year, d.month + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )
    fin_mes = _end_of_month(corte)

    # Mismo cómputo que mrr_history pero a un solo mes (fin_mes) y agrupado por cuenta.
    sql = """
        WITH hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR ho.end_date = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee, 0)::numeric    AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
        ),
        opps_active AS (
          SELECT DISTINCT ON (h.opportunity_id, h.candidate_id)
            h.opportunity_id, h.candidate_id, h.account_id, h.start_d,
            h.salary AS hire_salary, h.fee AS hire_fee
          FROM hires h
          WHERE h.start_d IS NOT NULL
            AND h.start_d <= %(fin_mes)s::date
            AND (h.end_d IS NULL OR h.end_d >= %(fin_mes)s::date)
          ORDER BY h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        opps_marked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (
              PARTITION BY candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn_primary
          FROM opps_active
        ),
        effective_per_opp AS (
          SELECT
            om.candidate_id, om.account_id,
            CASE
              WHEN om.rn_primary = 1
                THEN COALESCE(su_recent.salary::numeric, su_earliest.salary::numeric, om.hire_salary)
              ELSE om.hire_salary
            END AS salary,
            CASE
              WHEN om.rn_primary = 1
                THEN COALESCE(su_recent.fee::numeric, su_earliest.fee::numeric, om.hire_fee)
              ELSE om.hire_fee
            END AS fee
          FROM opps_marked om
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee
            FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id
              AND s.date IS NOT NULL
              AND s.date::date <= %(fin_mes)s::date
            ORDER BY s.date::date DESC, s.update_id DESC
            LIMIT 1
          ) su_recent ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee
            FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id
              AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id ASC
            LIMIT 1
          ) su_earliest ON TRUE
        ),
        effective AS (
          SELECT
            candidate_id, account_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM effective_per_opp
          GROUP BY candidate_id, account_id
        ),
        per_client AS (
          SELECT
            e.account_id,
            COUNT(DISTINCT e.candidate_id)::int AS total_employees,
            SUM(e.salary + e.fee)::numeric      AS gmrr,
            SUM(e.fee)::numeric                 AS mrr
          FROM effective e
          GROUP BY e.account_id
        )
        SELECT
          COALESCE(a.client_name, '—')                          AS client_name,
          pc.total_employees,
          pc.gmrr::float                                        AS gmrr,
          pc.mrr::float                                         AS mrr,
          ROUND(100.0 * pc.mrr / NULLIF(pc.gmrr, 0), 2)::float  AS margin_pct,
          ROUND(100.0 * pc.mrr / NULLIF(SUM(pc.mrr) OVER (), 0), 2)::float AS weight_pct
        FROM per_client pc
        LEFT JOIN account a ON a.account_id = pc.account_id
        WHERE pc.total_employees > 0
        ORDER BY pc.total_employees DESC, pc.mrr DESC NULLS LAST, client_name;
    """

    return sql, {"fin_mes": fin_mes}


DATASET = {
    "key": "cohort_by_client",
    "label": "Cohort by client · MRR summary (Staffing)",
    "dimensions": [
        {"key": "client_name", "label": "Clientes", "type": "string"},
        {"key": "total_employees", "label": "Total empleados", "type": "number"},
    ],
    "measures": [
        {"key": "gmrr", "label": "GMRR", "type": "currency"},
        {"key": "mrr", "label": "MRR", "type": "currency"},
        {"key": "margin_pct", "label": "Margin", "type": "percent"},
        {"key": "weight_pct", "label": "Weight over", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
