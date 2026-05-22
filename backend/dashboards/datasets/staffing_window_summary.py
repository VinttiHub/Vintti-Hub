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

    # `window` is accepted for symmetry with recruiting_window_summary but
    # all metrics here are point-in-time snapshots at `corte`, so it is unused.

    sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d
        ),
        hires AS (
          SELECT
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
        ),
        active_now AS (
          SELECT h.*
          FROM hires h
          CROSS JOIN params p
          WHERE h.start_d IS NOT NULL
            AND h.start_d <= p.corte_d
            AND (h.end_d IS NULL OR h.end_d >= p.corte_d)
        ),
        snapshot AS (
          SELECT
            COUNT(DISTINCT candidate_id)::int           AS active_contractors,
            COUNT(DISTINCT account_id)::int             AS active_clients,
            COALESCE(SUM(salary + fee), 0)::numeric     AS mrr_actual,
            COALESCE(SUM(fee), 0)::numeric              AS mrr_fee_total
          FROM active_now
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
