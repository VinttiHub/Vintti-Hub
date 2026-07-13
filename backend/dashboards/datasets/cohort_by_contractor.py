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
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
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
            m.fin_mes,
            h.opportunity_id,
            h.candidate_id,
            h.account_id,
            h.start_d,
            h.salary AS hire_salary,
            h.fee    AS hire_fee
          FROM meses m
          JOIN hires h
            ON h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        -- Mark the primary opp per (mes, candidate, account) = the one with the
        -- latest start_d. salary_updates apply only to the primary opp because
        -- the updates table is per-candidate (no opportunity_id) and applying
        -- to several parallel opps would multi-count the raise.
        opps_marked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (
              PARTITION BY mes, candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn_primary
          FROM opps_in_month
        ),
        -- Effective salary/fee per opp (applies to ALL months, current included):
        --   primary opp   → (1) most recent salary_updates ≤ fin_mes,
        --                   (2) else earliest salary_updates (months BEFORE the
        --                       first update keep that first value as baseline),
        --                   (3) else hire_opportunity.salary/fee
        --   secondary opp → its stored hire_opportunity values
        effective_per_opp AS (
          SELECT
            om.mes,
            om.candidate_id,
            om.account_id,
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
        -- Sum across multiple parallel opps for the same (mes, candidate, account).
        effective_in_month AS (
          SELECT
            mes,
            candidate_id,
            account_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM effective_per_opp
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
        -- Total histórico pagado por el par (candidate, account). Sirve para ocultar
        -- contractors que NUNCA facturaron un peso (ruido: alta+baja sin billing).
        pair_total AS (
          SELECT candidate_id, account_id, SUM(salary + fee) AS total_pago
          FROM effective_in_month
          GROUP BY candidate_id, account_id
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
          -- Flag para marcar (no ocultar) contractors que nunca facturaron un peso.
          CASE WHEN COALESCE(pt.total_pago, 0) = 0 THEN TRUE ELSE FALSE END AS no_billing
        FROM effective_in_month em
        LEFT JOIN candidates c ON c.candidate_id = em.candidate_id
        LEFT JOIN account a    ON a.account_id   = em.account_id
        JOIN first_seen fs ON fs.candidate_id = em.candidate_id AND fs.account_id = em.account_id
        JOIN last_seen  ls ON ls.candidate_id = em.candidate_id AND ls.account_id = em.account_id
        LEFT JOIN churn_per_pair cpp ON cpp.candidate_id = em.candidate_id AND cpp.account_id = em.account_id
        JOIN pair_total pt ON pt.candidate_id = em.candidate_id AND pt.account_id = em.account_id
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
        {"key": "no_billing", "label": "Sin facturación", "type": "boolean"},
    ],
    "measures": [
        {"key": "salary", "label": "Salary", "type": "currency"},
        {"key": "fee", "label": "Fee", "type": "currency"},
        {"key": "client_payment", "label": "Client payment", "type": "currency"},
        {"key": "vintti_fee", "label": "Vintti fee", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
