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

    # `window` is accepted for symmetry with recruiting_window_summary but
    # all metrics here are point-in-time snapshots at `corte`, so it is unused.

    # NOTE: mirrors cohort_by_contractor logic at a single corte_d so the
    # GMRR / MRR / Staffing fee avg tiles reconcile with the cohort table:
    #   - Pick all opps active at corte
    #   - Mark "primary" opp per (candidate, account) = latest start_d
    #   - Override primary's salary/fee with salary_updates ≤ corte
    #     (or earliest update as baseline before any update exists)
    #   - Sum across parallel opps per (candidate, account)
    # Secondary opps keep hire_opportunity values (salary_updates is per
    # candidate, not per opp, so applying to N parallel opps would multi-count).
    sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d
        ),
        hires AS (
          SELECT
            ho.opportunity_id,
            ho.account_id,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
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
            candidate_id, account_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM effective_per_opp
          GROUP BY candidate_id, account_id
        ),
        snapshot AS (
          SELECT
            COUNT(DISTINCT candidate_id)::int           AS active_contractors,
            COUNT(DISTINCT account_id)::int             AS active_clients,
            COALESCE(SUM(salary + fee), 0)::numeric     AS mrr_actual,
            COALESCE(SUM(fee), 0)::numeric              AS mrr_fee_total
          FROM effective_per_pair
        )
        SELECT
          (SELECT corte_d FROM params)                          AS corte,
          s.mrr_actual::bigint                                  AS mrr_actual,
          -- GMRR (Gross MRR) a corte = SUM(salary + fee) de los hires Staffing
          -- activos al corte. Es lo mismo que mrr_actual; se expone bajo el
          -- alias gmrr_actual para que el card del drawer lo lea sin cambios.
          s.mrr_actual::bigint                                  AS gmrr_actual,
          ROUND(
            s.mrr_fee_total / NULLIF(s.active_contractors, 0),
            2
          )::float                                              AS staffing_fee_avg,
          s.active_clients,
          s.active_contractors,
          s.mrr_fee_total::bigint                               AS mrr_fee_total
        FROM snapshot s;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "staffing_window_summary",
    "label": "Staffing — Snapshot (GMRR + Fee Avg + actuals)",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
    ],
    "measures": [
        {"key": "mrr_actual", "label": "MRR Actual", "type": "currency"},
        {"key": "gmrr_actual", "label": "GMRR Actual", "type": "currency"},
        {"key": "staffing_fee_avg", "label": "Staffing Fee Avg", "type": "currency"},
        {"key": "active_clients", "label": "Active Clients", "type": "number"},
        {"key": "active_contractors", "label": "Active Contractors", "type": "number"},
        {"key": "mrr_fee_total", "label": "MRR Fee Total", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
