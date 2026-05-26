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
        active_month AS (
          SELECT DISTINCT ON (m.mes, h.candidate_id, h.account_id)
            m.mes,
            h.candidate_id,
            h.account_id,
            h.salary,
            h.fee
          FROM meses m
          JOIN hires h
            ON h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.candidate_id, h.account_id, h.start_d DESC NULLS LAST
        ),
        first_seen AS (
          SELECT candidate_id, account_id, MIN(mes) AS first_mes
          FROM active_month
          GROUP BY candidate_id, account_id
        ),
        last_seen AS (
          SELECT candidate_id, account_id, MAX(mes) AS last_mes
          FROM active_month
          GROUP BY candidate_id, account_id
        )
        SELECT
          TO_CHAR(am.mes, 'YYYY-MM')                      AS mes,
          am.candidate_id::text                           AS candidate_id,
          TRIM(COALESCE(c.name, ''))                      AS candidate_name,
          am.account_id::text                             AS account_id,
          COALESCE(a.client_name, '')                     AS client_name,
          am.salary::bigint                               AS salary,
          am.fee::bigint                                  AS fee,
          (am.salary + am.fee)::bigint                    AS client_payment,
          am.fee::bigint                                  AS vintti_fee,
          TO_CHAR(fs.first_mes, 'YYYY-MM')                AS first_mes,
          TO_CHAR(ls.last_mes, 'YYYY-MM')                 AS last_mes,
          CASE
            WHEN ls.last_mes < (SELECT now_month FROM bounds) THEN 'Churned'
            ELSE 'Active'
          END                                             AS status
        FROM active_month am
        LEFT JOIN candidates c ON c.candidate_id = am.candidate_id
        LEFT JOIN account a    ON a.account_id   = am.account_id
        JOIN first_seen fs ON fs.candidate_id = am.candidate_id AND fs.account_id = am.account_id
        JOIN last_seen  ls ON ls.candidate_id = am.candidate_id AND ls.account_id = am.account_id
        ORDER BY fs.first_mes, am.candidate_id, am.mes;
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
        {"key": "status", "label": "Estado", "type": "string"},
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
