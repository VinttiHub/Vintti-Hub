"""Motor canonico de MRR Staffing para las cards del tab Account Management.

Mismo pipeline que `_ae_mrr_staffing.py` / `mrr_history.py` (dedup de opp primaria
por candidato+cuenta + salary efectivo via `salary_updates`), con dos diferencias:

  1. **Scope por Account Manager**: se queda con los hires cuya cuenta tiene
     `account.account_manager` cargado, y arrastra esa columna hasta el detalle.
     No se hardcodea nadie: hoy todas las cuentas son de Lara porque `account_manager`
     se reasigna al AM post-venta al pasar a "Active Client"
     (`docs/assets/js/crm.js` + `account-details.js`), pero con dos AMs la card
     no necesita reescribirse. Filtro opcional `%(am)s` ('' = todos).

  2. **Exclusion M3 del AE**: una vacante vendida por un AE (Mariano/Bahia) recien
     entra al AM a los 3 meses del Close Win. La decision es por VACANTE
     (cada opp corre su propio reloj), anclada en `opportunity.opp_close_date`, y
     las vacantes que NO vendio un AE entran de una.

     **La regla se evalua mes a mes, no una sola vez "a hoy"**: contra `fin_mes` en
     la serie y contra `corte_d` en el snapshot. Si se evaluara contra CURRENT_DATE
     la linea historica mentiria — un hire cerrado en enero apareceria ya en el GMRR
     de enero en vez de aparecer recien en abril, y el delta MoM no significaria nada.

     El corte de la serie es `fin_mes` PELADO, sin clamp a hoy. Es la convencion del
     resto del dashboard — un punto mensual es el run-rate AL CIERRE del mes — y es lo
     que hace que la card cuadre con su propio drawer: el detalle es `data-month-aware`,
     o sea que pide `corte = fin de mes`, no hoy. Clampear a hoy daba $240.4K en la card
     contra $245.0K en el total del drawer (medido el 2026-09-21).

     `close_d IS NULL` cuenta como del AM: esconder plata por un dato faltante es
     peor que adelantarla (hoy son 0 de los 94 hires activos, pero puede pasar).

Los hires en M3 **no se filtran, se marcan** (`am_owned`) y se agregan aparte. Asi
vale la invariante `GMRR del AM + M3 pendiente = GMRR de todas las cuentas con AM`,
que es lo
que hace verificable el numero: si en vez de eso se filtraran antes del dedup, el
`rn_primary` de un par (candidato, cuenta) con una opp adentro y otra afuera podria
cambiar de opp y las dos mitades no sumarian el total.

Tres plantillas (named params, estilo psycopg2 `%(...)s`):
  - HISTORY_CTE   -> `monthly(mes, monthly_gmrr, monthly_fee, active_contractors,
                    active_accounts, m3_gmrr, m3_fee, m3_contractors)`.
                    Params: %(ae_leads)s, %(am)s, %(period_start)s, %(period_end)s
  - ANCHOR_CTE    -> `a_mrr(kind, gmrr, fee, m3_gmrr, m3_fee, m3_contractors)` al dia
                    del corte y 30 dias antes, para
                    el modo-corte de las cards (se concatena DESPUES de HISTORY_CTE,
                    porque reusa su CTE `hires`).
                    Params: %(ae_leads)s, %(corte)s, %(corte_prev)s
  - SNAPSHOT_CTE  -> `eff(candidate_id, account_id, candidate_name, client_name,
                    account_manager, sales_lead, start_d, close_d, salary, fee,
                    am_owned)` —
                    una fila por opp activa al corte.
                    Params: %(ae_leads)s, %(am)s, %(corte)s

GMRR = salary + fee; MRR = fee solo. Cada archivo elige la columna en su SELECT.
"""
from __future__ import annotations

from ._sales_scope import sales_leads


def ae_leads() -> tuple[str, ...]:
    """Los AEs (M+B) como tupla, que es lo que necesita `IN %(ae_leads)s`."""
    return tuple(sales_leads())


# Predicado de propiedad: TRUE = ya es del AM. `{cutoff}` es la fecha contra la que
# se mide el reloj de 3 meses (fin de mes en la serie, corte en el snapshot).
_AM_OWNED = """(
              h.sales_lead NOT IN %(ae_leads)s
           OR h.close_d IS NULL
           OR (h.close_d + INTERVAL '3 months')::date <= {cutoff}
            )"""


_HIRES_CTE = """
        hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            ho.account_id,
            TRIM(LOWER(COALESCE(a.account_manager, ''))) AS account_manager,
            TRIM(LOWER(COALESCE(o.opp_sales_lead, '')))  AS sales_lead,
            NULLIF(o.opp_close_date::text, '')::date     AS close_d,
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
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE o.opp_model = 'Staffing'
            AND ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            -- Scope del AM: la cuenta tiene Account Manager asignado.
            AND NULLIF(TRIM(a.account_manager), '') IS NOT NULL
            AND (%(am)s = '' OR TRIM(LOWER(COALESCE(a.account_manager, ''))) = %(am)s)
        )"""


# Serie mensual: termina en `monthly`.
HISTORY_CTE = (
    _HIRES_CTE
    + """,
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM generate_series(%(period_start)s::date, %(period_end)s::date, INTERVAL '1 month') gs
        ),
        opps_in_month AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, m.fin_mes,
            h.opportunity_id, h.candidate_id, h.account_id, h.account_manager,
            h.start_d, h.salary AS hire_salary, h.fee AS hire_fee,
            """
    + _AM_OWNED.format(cutoff="m.fin_mes")
    + """ AS am_owned
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
            om.mes, om.candidate_id, om.account_id, om.account_manager, om.am_owned,
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
            -- Desempate por update_id DESC: candidate-details.js crea DOS salary_updates
            -- con la MISMA fecha al editar el Hire (blur de Salary con el Fee vacio
            -- graba fee 0, y despues el blur de Fee graba el valor real). Con ASC este
            -- fallback tomaba la fila de fee 0 y subvaluaba el MRR Fee en silencio.
            ORDER BY s.date::date ASC, s.update_id DESC LIMIT 1
          ) su_earliest ON TRUE
        ),
        effective_in_month AS (
          SELECT
            mes, candidate_id, account_id, am_owned,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM effective_per_opp
          GROUP BY mes, candidate_id, account_id, am_owned
        ),
        monthly AS (
          SELECT
            m.mes,
            COALESCE(SUM(e.salary + e.fee) FILTER (WHERE e.am_owned), 0)::numeric      AS monthly_gmrr,
            COALESCE(SUM(e.fee)            FILTER (WHERE e.am_owned), 0)::numeric      AS monthly_fee,
            COUNT(DISTINCT e.candidate_id) FILTER (WHERE e.am_owned)::int              AS active_contractors,
            COUNT(DISTINCT e.account_id)   FILTER (WHERE e.am_owned)::int              AS active_accounts,
            COALESCE(SUM(e.salary + e.fee) FILTER (WHERE NOT e.am_owned), 0)::numeric  AS m3_gmrr,
            COALESCE(SUM(e.fee)            FILTER (WHERE NOT e.am_owned), 0)::numeric  AS m3_fee,
            COUNT(DISTINCT e.candidate_id) FILTER (WHERE NOT e.am_owned)::int          AS m3_contractors
          FROM meses m
          LEFT JOIN effective_in_month e ON e.mes = m.mes
          GROUP BY m.mes
        )"""
)


# Anclas run-rate del modo-corte. Se concatena DESPUES de HISTORY_CTE (reusa `hires`).
ANCHOR_CTE = (
    """,
        anchors AS (
          SELECT %(corte)s::date      AS fin, 'cur'::text  AS kind
          UNION ALL
          SELECT %(corte_prev)s::date AS fin, 'prev'::text AS kind
        ),
        a_opps AS (
          SELECT DISTINCT ON (an.kind, h.opportunity_id, h.candidate_id)
            an.kind, an.fin,
            h.opportunity_id, h.candidate_id, h.account_id,
            h.start_d, h.salary AS hire_salary, h.fee AS hire_fee,
            """
    + _AM_OWNED.format(cutoff="an.fin")
    + """ AS am_owned
          FROM anchors an
          JOIN hires h
            ON h.start_d IS NOT NULL
           AND h.start_d <= an.fin
           AND (h.end_d IS NULL OR h.end_d >= an.fin)
          ORDER BY an.kind, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        a_marked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY kind, candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn_primary
          FROM a_opps
        ),
        a_eff_opp AS (
          SELECT
            am.kind, am.candidate_id, am.account_id, am.am_owned,
            CASE WHEN am.rn_primary = 1
              THEN COALESCE(su_recent.salary::numeric, su_earliest.salary::numeric, am.hire_salary)
              ELSE am.hire_salary END AS salary,
            CASE WHEN am.rn_primary = 1
              THEN COALESCE(su_recent.fee::numeric, su_earliest.fee::numeric, am.hire_fee)
              ELSE am.hire_fee END AS fee
          FROM a_marked am
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = am.candidate_id
              AND s.date IS NOT NULL AND s.date::date <= am.fin
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su_recent ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = am.candidate_id AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id DESC LIMIT 1
          ) su_earliest ON TRUE
        ),
        a_eff AS (
          SELECT kind, candidate_id, account_id, am_owned,
            SUM(salary)::numeric AS salary, SUM(fee)::numeric AS fee
          FROM a_eff_opp GROUP BY kind, candidate_id, account_id, am_owned
        ),
        a_mrr AS (
          SELECT kind,
            COALESCE(SUM(salary + fee) FILTER (WHERE am_owned), 0)::numeric     AS gmrr,
            COALESCE(SUM(fee)          FILTER (WHERE am_owned), 0)::numeric     AS fee,
            COALESCE(SUM(salary + fee) FILTER (WHERE NOT am_owned), 0)::numeric AS m3_gmrr,
            COALESCE(SUM(fee)          FILTER (WHERE NOT am_owned), 0)::numeric AS m3_fee,
            COUNT(DISTINCT candidate_id) FILTER (WHERE NOT am_owned)::int       AS m3_contractors
          FROM a_eff GROUP BY kind
        )"""
)


# Snapshot al corte: termina en `eff` (una fila por par activo al corte).
SNAPSHOT_CTE = (
    """
        params AS (SELECT %(corte)s::date AS corte_d),"""
    + _HIRES_CTE
    + """,
        activos AS (
          SELECT h.*, """
    + _AM_OWNED.format(cutoff="p.corte_d")
    + """ AS am_owned
          FROM hires h CROSS JOIN params p
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
        eff_per_opp AS (
          SELECT
            m.candidate_id, m.account_id, m.account_manager, m.sales_lead,
            m.start_d, m.close_d, m.am_owned,
            CASE WHEN m.rn_primary = 1
              THEN COALESCE(su_recent.salary::numeric, su_earliest.salary::numeric, m.salary)
              ELSE m.salary END AS eff_salary,
            CASE WHEN m.rn_primary = 1
              THEN COALESCE(su_recent.fee::numeric, su_earliest.fee::numeric, m.fee)
              ELSE m.fee END AS eff_fee
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
            ORDER BY s.date::date ASC, s.update_id DESC LIMIT 1
          ) su_earliest ON TRUE
        ),
        eff AS (
          SELECT
            e.candidate_id,
            e.account_id,
            COALESCE(c.name, '')        AS candidate_name,
            COALESCE(a.client_name, '') AS client_name,
            e.account_manager,
            e.am_owned,
            MAX(e.sales_lead)      AS sales_lead,
            MAX(e.start_d)         AS start_d,
            MAX(e.close_d)         AS close_d,
            SUM(e.eff_salary)::numeric AS salary,
            SUM(e.eff_fee)::numeric    AS fee
          FROM eff_per_opp e
          LEFT JOIN candidates c ON c.candidate_id = e.candidate_id
          LEFT JOIN account a    ON a.account_id   = e.account_id
          GROUP BY e.candidate_id, e.account_id, c.name, a.client_name,
                   e.account_manager, e.am_owned
        )"""
)
