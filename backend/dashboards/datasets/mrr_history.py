from __future__ import annotations

from datetime import datetime


_ALLOWED_METRICS = {"Revenue", "Fee"}


def _parse_ym(value: str | None) -> datetime | None:
    if not value:
        return None
    parts = str(value).split("-")
    if len(parts) < 2:
        return None
    try:
        return datetime(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, tuple]:
    current_month_start = datetime.utcnow().date().replace(day=1)

    from_dt = _parse_ym(filters.get("from")) or _parse_ym(filters.get("desde")) or datetime(2023, 1, 1)
    to_dt = (
        _parse_ym(filters.get("to"))
        or _parse_ym(filters.get("hasta"))
        or datetime.combine(current_month_start, datetime.min.time())
    )
    if to_dt < from_dt:
        to_dt = from_dt

    metric = (filters.get("metric") or "Revenue").strip()
    if metric not in _ALLOWED_METRICS:
        metric = "Revenue"

    # NOTE: this query mirrors the cohort_by_contractor logic so the line chart
    # totals reconcile with the cohort table. Each month:
    #   - Pick all active opps at fin_mes
    #   - For each (mes, candidate, account), mark the "primary" opp (latest start_d)
    #   - Override the primary opp's salary/fee with salary_updates ≤ fin_mes
    #     (or the earliest update as baseline before the first row)
    #   - Sum across parallel opps for the same (mes, candidate, account)
    # Secondary opps keep their hire_opportunity values because salary_updates
    # is keyed per candidate and applying it to N parallel opps would multi-count.
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
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM generate_series(%s::date, %s::date, INTERVAL '1 month') gs
        ),
        opps_in_month AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, m.fin_mes,
            h.opportunity_id, h.candidate_id, h.account_id,
            h.start_d, h.salary AS hire_salary, h.fee AS hire_fee
          FROM meses m
          JOIN hires h
            ON h.start_d IS NOT NULL
           AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        opps_marked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (
              PARTITION BY mes, candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn_primary
          FROM opps_in_month
        ),
        effective_per_opp AS (
          SELECT
            om.mes, om.candidate_id, om.account_id,
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
              AND s.date::date <= om.fin_mes
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
        effective_in_month AS (
          SELECT
            mes, candidate_id, account_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM effective_per_opp
          GROUP BY mes, candidate_id, account_id
        ),
        candidatos_mes AS (
          SELECT mes, COUNT(DISTINCT candidate_id) AS candidatos_activos
          FROM effective_in_month
          GROUP BY mes
        ),
        mrr_mes AS (
          SELECT
            mes,
            SUM(
              CASE
                WHEN %s = 'Fee' THEN fee
                ELSE (salary + fee)
              END
            )::numeric AS mrr_total
          FROM effective_in_month
          GROUP BY mes
        )
        SELECT
          to_char(m.mes, 'YYYY-MM') AS mes,
          m.mrr_total::bigint        AS mrr_total,
          COALESCE(c.candidatos_activos, 0) AS candidatos_activos,
          ROUND(
            100.0 * (m.mrr_total - LAG(m.mrr_total) OVER (ORDER BY m.mes))
                  / NULLIF(LAG(m.mrr_total) OVER (ORDER BY m.mes), 0),
            2
          ) AS growth_pct
        FROM mrr_mes m
        LEFT JOIN candidatos_mes c USING (mes)
        ORDER BY m.mes;
    """
    return sql, (from_dt.date(), to_dt.date(), metric)


DATASET = {
    "key": "mrr_history",
    "label": "MRR History (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Month", "type": "date"},
    ],
    "measures": [
        {"key": "mrr_total", "label": "MRR Total", "type": "currency"},
        {"key": "candidatos_activos", "label": "Candidatos Activos", "type": "number"},
        {"key": "growth_pct", "label": "Growth %", "type": "percent"},
    ],
    "default_filters": {"metric": "Revenue"},
    "query": query,
}
