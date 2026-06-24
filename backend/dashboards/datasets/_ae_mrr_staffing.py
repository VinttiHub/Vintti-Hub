"""Motor canónico de MRR Staffing para las cards del tab AE (M+B).

R4 del audit: antes `gmrr_ae_*` y `mrr_fee_ae_*` hacían `SUM(salary+fee)` PLANO
sobre un LEFT JOIN de hires — sin dedup de opp primaria y sin `salary_updates`.
Eso (a) doble-contaba a un candidato con 2 hires paralelos y (b) mostraba el
salario viejo del hire, ignorando los aumentos. Sus docstrings prometían cuadrar
con `mrr_history.py` pero no lo hacían.

Acá vive el motor canónico — el MISMO de `mrr_history.py`:
  1. `hires`            : hire_opportunity Staffing del scope AE (opp_sales_lead
                          ∈ M+B) y YTD (opp_close_date ≥ year_start).
  2. dedup por opp      : DISTINCT ON (mes/corte, opportunity_id, candidate_id).
  3. opp primaria       : ROW_NUMBER() PARTITION BY (..., candidate_id, account_id)
                          → la opp más reciente por (candidato, cuenta) es la primaria.
  4. salary efectivo    : a la primaria se le aplica el `salary_updates` más reciente
                          ≤ fecha de corte (o el más antiguo como baseline); las opps
                          secundarias (paralelas) mantienen su salary/fee del hire,
                          porque salary_updates es por candidato y aplicarlo a N opps
                          paralelas multi-contaría.
  5. sumar              : SUM por (candidato, cuenta).

Dos plantillas (named params, estilo psycopg2 `%(...)s`):
  - HISTORY_CTE   → produce `monthly(mes, monthly_gmrr, monthly_fee,
                    active_contractors, active_accounts)` sobre la serie mensual.
                    Params: %(ae_leads)s, %(year_start)s, %(period_end)s
  - SNAPSHOT_CTE  → produce `eff(candidate_id, account_id, candidate_name,
                    client_name, opp_sales_lead, start_d, salary, fee)` — una fila
                    por opp activa al corte (la suma reconcilia con el último mes).
                    Params: %(ae_leads)s, %(year_start)s, %(corte)s

GMRR = salary + fee; Fee = fee solo. Cada archivo elige la columna en su SELECT.
"""
from __future__ import annotations

AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


# Serie mensual: termina en `monthly` (con monthly_gmrr y monthly_fee).
HISTORY_CTE = """
        hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee, 0)::numeric    AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
            -- YTD: solo deals cuya Close Win fue este año (a partir del 1 de enero).
            AND NULLIF(o.opp_close_date::text, '')::date >= %(year_start)s::date
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM generate_series(%(year_start)s::date, %(period_end)s::date, INTERVAL '1 month') gs
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
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY mes, candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn_primary
          FROM opps_in_month
        ),
        effective_per_opp AS (
          SELECT
            om.mes, om.candidate_id, om.account_id,
            CASE WHEN om.rn_primary = 1
              THEN COALESCE(su_recent.salary::numeric, su_earliest.salary::numeric, om.hire_salary)
              ELSE om.hire_salary END AS salary,
            CASE WHEN om.rn_primary = 1
              THEN COALESCE(su_recent.fee::numeric, su_earliest.fee::numeric, om.hire_fee)
              ELSE om.hire_fee END AS fee
          FROM opps_marked om
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id
              AND s.date IS NOT NULL AND s.date::date <= om.fin_mes
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su_recent ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id ASC LIMIT 1
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
        monthly AS (
          SELECT
            m.mes,
            COALESCE(SUM(e.salary + e.fee), 0)::numeric AS monthly_gmrr,
            COALESCE(SUM(e.fee), 0)::numeric            AS monthly_fee,
            COUNT(DISTINCT e.candidate_id)::int         AS active_contractors,
            COUNT(DISTINCT e.account_id)::int           AS active_accounts
          FROM meses m
          LEFT JOIN effective_in_month e ON e.mes = m.mes
          GROUP BY m.mes
        )
"""


# Snapshot al corte: termina en `eff` (una fila por opp activa al corte).
SNAPSHOT_CTE = """
        params AS (SELECT %(corte)s::date AS corte_d),
        hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            ho.account_id,
            COALESCE(c.name, '')           AS candidate_name,
            COALESCE(a.client_name, '')    AS client_name,
            COALESCE(o.opp_sales_lead, '') AS opp_sales_lead,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary, 0)::numeric AS hire_salary,
            COALESCE(ho.fee, 0)::numeric    AS hire_fee
          FROM hire_opportunity ho
          JOIN opportunity o      ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN candidates c  ON c.candidate_id   = ho.candidate_id
          LEFT JOIN account a     ON a.account_id     = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
            -- YTD: solo deals cuya Close Win fue este año (a partir del 1 de enero).
            AND NULLIF(o.opp_close_date::text, '')::date >= %(year_start)s::date
        ),
        activos AS (
          SELECT h.* FROM hires h CROSS JOIN params p
          WHERE h.start_d IS NOT NULL
            AND h.start_d <= p.corte_d
            AND (h.end_d IS NULL OR h.end_d >= p.corte_d)
        ),
        marked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn_primary
          FROM activos
        ),
        eff AS (
          SELECT
            m.candidate_id, m.account_id,
            m.candidate_name, m.client_name, m.opp_sales_lead, m.start_d,
            CASE WHEN m.rn_primary = 1
              THEN COALESCE(su_recent.salary::numeric, su_earliest.salary::numeric, m.hire_salary)
              ELSE m.hire_salary END AS salary,
            CASE WHEN m.rn_primary = 1
              THEN COALESCE(su_recent.fee::numeric, su_earliest.fee::numeric, m.hire_fee)
              ELSE m.hire_fee END AS fee
          FROM marked m CROSS JOIN params p
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = m.candidate_id
              AND s.date IS NOT NULL AND s.date::date <= p.corte_d
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su_recent ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = m.candidate_id AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id ASC LIMIT 1
          ) su_earliest ON TRUE
        )
"""
