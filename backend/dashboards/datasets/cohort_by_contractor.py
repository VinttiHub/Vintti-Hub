"""Cohort by contractor · month-by-month billing (Staffing).

For each (candidate, account) pair, returns one row per month between the
contractor's first start date and the current month. Each row carries:

  - `client_payment` = salary + fee for that month
  - `vintti_fee`     = fee only

Salary changes are reflected automatically: each raise inserts a new
`hire_opportunity` row, and the `DISTINCT ON ... ORDER BY start_d DESC`
clause picks the latest active row per month.

The frontend (`data-bind="cohort"`) pivots these long rows into the wide
table seen on Management Dashboard.
"""
from __future__ import annotations


def query(_filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '') IS NULL THEN NULL
              ELSE NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '')::date
            END AS end_d,
            -- buyout_daterange stored as 'YYYY-MM'; parse to date by appending '-01'.
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
                THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee, 0)::numeric    AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
        ),
        bounds AS (
          SELECT
            MIN(start_d)                                  AS min_start,
            DATE_TRUNC('month', CURRENT_DATE)::date       AS now_month
          FROM hires
          WHERE start_d IS NOT NULL
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM bounds b,
               generate_series(
                 DATE_TRUNC('month', b.min_start)::date,
                 b.now_month,
                 INTERVAL '1 month'
               ) gs
        ),
        -- One row per (mes, opportunity, candidate) — matches the MRR query's
        -- dedup so totals align. Multiple opps for the same candidate at the
        -- same account are kept as separate rows here, then summed below.
        opps_in_month AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes,
            h.candidate_id,
            h.account_id,
            h.salary,
            h.fee
          FROM meses m
          JOIN hires h
            ON h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        -- Sum across multiple parallel opps for the same (mes, candidate, account)
        -- so each cohort row = one contractor at one client and column totals
        -- match the MRR card exactly. Uses hire_opportunity.salary/fee directly
        -- (no salary_updates overlay) — same source of truth as mrr_history.py.
        effective_in_month AS (
          SELECT
            mes,
            candidate_id,
            account_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM opps_in_month
          GROUP BY mes, candidate_id, account_id
        ),
        first_seen AS (
          SELECT candidate_id, account_id, MIN(mes) AS first_mes
          FROM effective_in_month
          GROUP BY candidate_id, account_id
        ),
        last_seen AS (
          SELECT candidate_id, account_id, MAX(mes) AS last_mes
          FROM effective_in_month
          GROUP BY candidate_id, account_id
        ),
        -- Churn classification per (candidate, account):
        --   churn_month_d = month containing the final `end_d`. NULL if any
        --                   hire is still open (no churn yet).
        --   is_buyout     = TRUE when there's a `buyout_daterange` whose month
        --                   is on/after the churn month (matches the logic in
        --                   candidate_churn_window_history.py). Real churn
        --                   otherwise.
        churn_per_pair AS (
          SELECT
            candidate_id,
            account_id,
            CASE
              WHEN SUM(CASE WHEN end_d IS NULL THEN 1 ELSE 0 END) > 0 THEN NULL
              ELSE DATE_TRUNC('month', MAX(end_d))::date
            END AS churn_month_d,
            CASE
              WHEN SUM(CASE WHEN end_d IS NULL THEN 1 ELSE 0 END) > 0 THEN FALSE
              WHEN MAX(buyout_d) IS NOT NULL
                   AND MAX(buyout_d) >= DATE_TRUNC('month', MAX(end_d))
                THEN TRUE
              ELSE FALSE
            END AS is_buyout
          FROM hires
          WHERE candidate_id IS NOT NULL AND account_id IS NOT NULL
          GROUP BY candidate_id, account_id
        ),
        -- Bajas counts per month — IDENTICAL logic to candidate_churn_window_history
        -- with meses=3 (the default window of the chart): cohort = hires that
        -- started in the 3 months ending at m; bajas = cohort members whose
        -- end_d <= m_fin. This way the cohort header stats match the chart.
        churn_window_per_month AS (
          SELECT
            m.mes,
            COUNT(*) FILTER (
              WHERE h.end_d IS NOT NULL
                AND h.end_d <= m.fin_mes
                AND (h.buyout_d IS NULL OR h.buyout_d < DATE_TRUNC('month', h.end_d))
            )::int AS bajas_real_count,
            COUNT(*) FILTER (
              WHERE h.end_d IS NOT NULL
                AND h.end_d <= m.fin_mes
                AND h.buyout_d IS NOT NULL
                AND h.buyout_d >= DATE_TRUNC('month', h.end_d)
            )::int AS buyouts_count
          FROM meses m
          JOIN hires h
            ON h.start_d IS NOT NULL
           AND h.start_d BETWEEN (m.mes - INTERVAL '2 months')::date AND m.fin_mes
          GROUP BY m.mes
        )
        SELECT
          TO_CHAR(em.mes, 'YYYY-MM')                      AS mes,
          em.candidate_id::text                           AS candidate_id,
          TRIM(COALESCE(c.name, ''))                      AS candidate_name,
          em.account_id::text                             AS account_id,
          COALESCE(a.client_name, '')                     AS client_name,
          em.salary::bigint                               AS salary,
          em.fee::bigint                                  AS fee,
          (em.salary + em.fee)::bigint                    AS client_payment,
          em.fee::bigint                                  AS vintti_fee,
          TO_CHAR(fs.first_mes, 'YYYY-MM')                AS first_mes,
          TO_CHAR(ls.last_mes, 'YYYY-MM')                 AS last_mes,
          TO_CHAR(cpp.churn_month_d, 'YYYY-MM')           AS churn_month,
          COALESCE(cpp.is_buyout, FALSE)                  AS is_buyout,
          CASE
            WHEN cpp.churn_month_d IS NULL          THEN 'Active'
            WHEN COALESCE(cpp.is_buyout, FALSE)     THEN 'Buyout'
            ELSE 'Churned'
          END                                             AS status,
          COALESCE(cwpm.bajas_real_count, 0)              AS bajas_real_count,
          COALESCE(cwpm.buyouts_count, 0)                 AS buyouts_count
        FROM effective_in_month em
        LEFT JOIN candidates c ON c.candidate_id = em.candidate_id
        LEFT JOIN account a    ON a.account_id   = em.account_id
        JOIN first_seen fs ON fs.candidate_id = em.candidate_id AND fs.account_id = em.account_id
        JOIN last_seen  ls ON ls.candidate_id = em.candidate_id AND ls.account_id = em.account_id
        LEFT JOIN churn_per_pair cpp ON cpp.candidate_id = em.candidate_id AND cpp.account_id = em.account_id
        LEFT JOIN churn_window_per_month cwpm ON cwpm.mes = em.mes
        ORDER BY fs.first_mes, em.candidate_id, em.mes;
    """
    return sql, {}


DATASET = {
    "key": "cohort_by_contractor",
    "label": "Cohort by contractor · monthly billing (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "candidate_id", "label": "Candidate ID", "type": "string"},
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "account_id", "label": "Account ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "first_mes", "label": "Primer mes", "type": "date"},
        {"key": "last_mes", "label": "Último mes activo", "type": "date"},
        {"key": "churn_month", "label": "Mes de baja", "type": "date"},
        {"key": "is_buyout", "label": "Buyout", "type": "boolean"},
        {"key": "status", "label": "Estado", "type": "string"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee", "type": "currency"},
        {"key": "client_payment", "label": "Client payment", "type": "currency"},
        {"key": "vintti_fee", "label": "Vintti fee", "type": "currency"},
        {"key": "bajas_real_count", "label": "Bajas reales (3m)", "type": "number"},
        {"key": "buyouts_count", "label": "Buyouts (3m)", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
