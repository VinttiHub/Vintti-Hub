"""Motor canónico de MRR Staffing (TODO Staffing, sin scope) para el NRR.

Mismo motor que `mrr_history.py` / `_ae_mrr_staffing.py` (dedup de opp primaria por
candidato+cuenta + salario efectivo vía `salary_updates`), pero SIN filtro de scope
(el NRR es sobre todo Staffing, igual que el GMRR de Management). Existe para que el
"MRR inicial" del NRR reconcilie EXACTO con el GMRR de Management (R5 / R4).

- `HIRES_FULL_CTE`: CTE `hires_full` con todos los hires Staffing + campos para NRR.
- `unit_snapshot(name, dexpr)`: genera los CTE que terminan en `{name}` =
  (candidate_id, account_id, salary, fee) = MRR efectivo por unidad (candidato,cuenta)
  a la fecha `dexpr` (una expresión SQL de fecha, p.ej. "%(win_ini)s::date").
  Requiere que `hires_full` ya exista en el WITH.
"""
from __future__ import annotations


HIRES_FULL_CTE = """
        hires_full AS (
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
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee,    0)::numeric AS fee,
            TRIM(COALESCE(ho.inactive_reason::text, '')) AS inactive_reason,
            o.opp_close_date::date AS opp_close_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND (
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                ELSE NULLIF(ho.start_date::text, '')::date
              END
            ) IS NOT NULL
        )
"""


def unit_snapshot(name: str, dexpr: str) -> str:
    """CTE de MRR efectivo por (candidato, cuenta) a la fecha `dexpr`."""
    return f"""
        {name}_opps AS (
          SELECT DISTINCT ON (h.opportunity_id, h.candidate_id)
            h.opportunity_id, h.candidate_id, h.account_id, h.start_d,
            h.salary AS hs, h.fee AS hf
          FROM hires_full h
          WHERE h.start_d <= {dexpr}
            AND (h.end_d IS NULL OR h.end_d >= {dexpr})
          ORDER BY h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        {name}_marked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn
          FROM {name}_opps
        ),
        {name}_eff AS (
          SELECT m.candidate_id, m.account_id,
            CASE WHEN m.rn = 1
              THEN COALESCE(sr.salary::numeric, se.salary::numeric, m.hs)
              ELSE m.hs END AS salary,
            CASE WHEN m.rn = 1
              THEN COALESCE(sr.fee::numeric, se.fee::numeric, m.hf)
              ELSE m.hf END AS fee
          FROM {name}_marked m
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = m.candidate_id
              AND s.date IS NOT NULL AND s.date::date <= {dexpr}
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) sr ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = m.candidate_id AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id ASC LIMIT 1
          ) se ON TRUE
        ),
        {name} AS (
          SELECT candidate_id, account_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM {name}_eff
          GROUP BY candidate_id, account_id
        )
    """
