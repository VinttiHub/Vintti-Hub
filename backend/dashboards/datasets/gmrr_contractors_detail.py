"""Per-contractor breakdown of Gross MRR at a given month (corte).

Lists every Staffing (candidate, account) pair active at `corte` (last day of
the month chosen via the global month chip). Each row carries the effective
salary/fee per the same logic as `cohort_by_contractor`:

  - Primary opp (latest start_d for the pair) uses `salary_updates` ≤ corte
  - Secondary parallel opps keep their `hire_opportunity` values

The sum of the rows equals `staffing_window_summary.mrr_actual`, so the drawer
sub-total reconciles with the GMRR tile and the cohort table.
"""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


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
        or today_ar()
    )

    sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d
        ),
        hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            COALESCE(c.name, '')            AS candidate_name,
            ho.account_id,
            COALESCE(a.client_name, '')     AS client_name,
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
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
        ),
        opps_active AS (
          SELECT DISTINCT ON (h.opportunity_id, h.candidate_id)
            h.opportunity_id, h.candidate_id, h.candidate_name,
            h.account_id, h.client_name, h.start_d,
            h.salary AS hire_salary, h.fee AS hire_fee
          FROM hires h
          CROSS JOIN params p
          WHERE h.start_d IS NOT NULL
            AND h.start_d <= p.corte_d
            AND (h.end_d IS NULL OR h.end_d >= p.corte_d)
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
            om.candidate_id, om.candidate_name,
            om.account_id, om.client_name, om.start_d,
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
          CROSS JOIN params p
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee
            FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id
              AND s.date IS NOT NULL
              AND s.date::date <= p.corte_d
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
        effective_per_pair AS (
          SELECT
            candidate_id, candidate_name,
            account_id, client_name,
            MAX(start_d)         AS start_d,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM effective_per_opp
          GROUP BY candidate_id, candidate_name, account_id, client_name
        )
        SELECT
          candidate_name,
          client_name,
          salary::float                  AS salary,
          fee::float                     AS fee,
          (salary + fee)::float          AS gmrr,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_date
        FROM effective_per_pair
        ORDER BY (salary + fee) DESC NULLS LAST, candidate_name;
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
