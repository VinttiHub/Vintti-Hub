"""Motor canónico de MRR Staffing (TODO Staffing, sin scope) para el NRR.

Mismo motor que `mrr_history.py` / `_ae_mrr_staffing.py` (dedup de opp primaria por
candidato+cuenta + salario efectivo vía `salary_updates`), pero SIN filtro de scope
(el NRR es sobre todo Staffing, igual que el GMRR de Management). Existe para que el
"MRR inicial" del NRR reconcilie EXACTO con el GMRR de Management (R5 / R4).

- `HIRES_FULL_CTE`: CTE `hires_full` con todos los hires Staffing + campos para NRR.
- `unit_snapshot(name, dexpr, where_extra=None)`: genera los CTE que terminan en
  `{name}` = (candidate_id, account_id, opportunity_id, salary, fee) = MRR efectivo por
  unidad (candidato,cuenta) a la fecha `dexpr` (una expresión SQL de fecha, p.ej.
  "%(win_ini)s::date"). Requiere que `hires_full` ya exista en el WITH.

  `where_extra` cambia QUÉ hires entran, sin tocar cómo se valúan. Por defecto son los
  activos a `dexpr` (el snapshot de siempre). El NRR lo usa para valuar los upsells, que
  se cuentan por `opp_close_date` dentro de la ventana y por lo tanto pueden no estar
  activos a ninguna fecha (el hire todavía no arrancó, o ya se cayó) — ver
  `_nrr_decomp.py`. Con la cláusula de actividad esos upsells se valuarían en cero.
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
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND (
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                ELSE NULLIF(ho.start_date::text, '')::date
              END
            ) IS NOT NULL
        )
"""


def unit_snapshot(name: str, dexpr: str, where_extra: str | None = None) -> str:
    """CTE de MRR efectivo por (candidato, cuenta) a la fecha `dexpr`.

    `where_extra` reemplaza el filtro de población (por defecto: activos a `dexpr`).
    """
    poblacion = where_extra or (
        f"h.start_d <= {dexpr} AND (h.end_d IS NULL OR h.end_d >= {dexpr})"
    )
    return f"""
        {name}_opps AS (
          SELECT DISTINCT ON (h.opportunity_id, h.candidate_id)
            h.opportunity_id, h.candidate_id, h.account_id, h.start_d,
            h.salary AS hs, h.fee AS hf
          FROM hires_full h
          WHERE {poblacion}
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
          SELECT m.candidate_id, m.account_id, m.opportunity_id, m.rn,
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
            -- Desempate por update_id DESC: candidate-details.js crea DOS salary_updates
            -- con la MISMA fecha al editar el Hire (blur de Salary con el Fee vacio
            -- graba fee 0, y despues el blur de Fee graba el valor real). Con ASC este
            -- fallback tomaba la fila de fee 0 y subvaluaba el MRR Fee en silencio.
            ORDER BY s.date::date ASC, s.update_id DESC LIMIT 1
          ) se ON TRUE
        ),
        {name} AS (
          SELECT candidate_id, account_id,
            MAX(opportunity_id) FILTER (WHERE rn = 1) AS opportunity_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM {name}_eff
          GROUP BY candidate_id, account_id
        )
    """


def unit_snapshot_monthly(name: str, dcol: str, where_extra: str | None = None) -> str:
    """`unit_snapshot()` pero para una serie: un snapshot por cada fila de `meses`.

    Requiere que `hires_full` y `meses` ya existan en el WITH. `dcol` es la columna de
    `meses` que hace de fecha del snapshot (`prev_end` para el inicio de la ventana del
    mes, `fin_mes` para el cierre). Termina en
    `{name}(mes, candidate_id, account_id, opportunity_id, salary, fee)`.
    """
    poblacion = where_extra or (
        f"h.start_d <= m.{dcol} AND (h.end_d IS NULL OR h.end_d >= m.{dcol})"
    )
    return f"""
        {name}_opps AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, m.{dcol} AS d,
            h.opportunity_id, h.candidate_id, h.account_id, h.start_d,
            h.salary AS hs, h.fee AS hf
          FROM meses m
          JOIN hires_full h ON {poblacion}
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        {name}_marked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY mes, candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn
          FROM {name}_opps
        ),
        {name}_eff AS (
          SELECT sm.mes, sm.candidate_id, sm.account_id, sm.opportunity_id, sm.rn,
            CASE WHEN sm.rn = 1
              THEN COALESCE(sr.salary::numeric, se.salary::numeric, sm.hs)
              ELSE sm.hs END AS salary,
            CASE WHEN sm.rn = 1
              THEN COALESCE(sr.fee::numeric, se.fee::numeric, sm.hf)
              ELSE sm.hf END AS fee
          FROM {name}_marked sm
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = sm.candidate_id
              AND s.date IS NOT NULL AND s.date::date <= sm.d
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) sr ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = sm.candidate_id AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id DESC LIMIT 1
          ) se ON TRUE
        ),
        {name} AS (
          SELECT mes, candidate_id, account_id,
            MAX(opportunity_id) FILTER (WHERE rn = 1) AS opportunity_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM {name}_eff
          GROUP BY mes, candidate_id, account_id
        )
    """
