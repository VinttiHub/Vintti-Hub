"""Per-contractor breakdown of Gross MRR at a given month (corte).

Lists every Staffing hire that is active at `corte` (last day of the month
chosen via the global month chip). Each row contributes `salary + fee` to
GMRR; the sum of the rows equals `staffing_window_summary.mrr_actual`.

The sibling dataset `staffing_window_summary` exposes the aggregate. This one
exists so the drawer can show the components behind that aggregate.
"""
from __future__ import annotations

from datetime import date, datetime


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d
        ),
        hires AS (
          SELECT
            ho.candidate_id,
            COALESCE(c.name, '') AS candidate_name,
            ho.account_id,
            COALESCE(a.client_name, '') AS client_name,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee, 0)::numeric    AS fee,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          LEFT JOIN account a    ON a.account_id   = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
        )
        SELECT
          h.candidate_name,
          h.client_name,
          h.salary::float                  AS salary,
          h.fee::float                     AS fee,
          (h.salary + h.fee)::float        AS gmrr,
          TO_CHAR(h.start_d, 'YYYY-MM-DD') AS start_date
        FROM hires h
        CROSS JOIN params p
        WHERE h.start_d IS NOT NULL
          AND h.start_d <= p.corte_d
          AND (h.end_d IS NULL OR h.end_d >= p.corte_d)
        ORDER BY (h.salary + h.fee) DESC NULLS LAST, h.candidate_name;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "gmrr_contractors_detail",
    "label": "GMRR — Desglose por contractor (Staffing, snapshot al corte)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "start_date", "label": "Start", "type": "date"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee", "type": "currency"},
        {"key": "gmrr", "label": "GMRR (salary + fee)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
