"""Las tres queries del reporte de comisiones AE.

Grano: una fila por OPORTUNIDAD en Staffing/Recruiting (asi esta la spec), una
fila por HIRE en el bloque M3 (la comision se descuenta por candidato caido).

Gotchas del repo que estan replicados a proposito y no hay que "limpiar":
  * `AND COALESCE(a.vintti_internal, FALSE) = FALSE` en los tres bloques.
  * R17: `hire_opportunity` junta filas fantasma del formulario publico de
    reference checks; nacen sin `carga_active` ni `start_date`. El CTE `hires`
    las filtra. Nunca borrarlas de la tabla.
  * `opp_close_date` / `start_date` / `end_date` NO son `date` puro: castear
    siempre con `NULLIF(x::text, '')::date`.
  * `TRIM(o.opp_stage)`: la data tiene espacios.
  * Un signo de porcentaje literal en el SQL (hasta en un comentario) rompe
    psycopg2 con "argument formats can't be mixed". No escribir ninguno.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from dashboards.datasets._now import today_ar
from dashboards.datasets._sales_scope import sales_leads


def month_bounds(period: str | None = None) -> tuple[date, date]:
    """(primer dia, ultimo dia) del mes a reportar.

    `period` es 'YYYY-MM'. Sin periodo se usa el MES VENCIDO respecto de hoy en
    hora Argentina: el reporte corre el dia 1 y levanta el mes que se cerro.
    """
    parsed = _parse_period(period)
    if parsed is None:
        hoy = today_ar()
        primero_de_este_mes = hoy.replace(day=1)
        ultimo_del_anterior = primero_de_este_mes - timedelta(days=1)
        parsed = ultimo_del_anterior.replace(day=1)
    fin = parsed.replace(day=monthrange(parsed.year, parsed.month)[1])
    return parsed, fin


def _parse_period(period: str | None) -> date | None:
    raw = str(period or "").strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) >= 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (TypeError, ValueError):
        return None
    return None


# --------------------------------------------------------------------------- #
# CTE compartido: los hires REALES (filtro R17), con las fechas ya casteadas.
# --------------------------------------------------------------------------- #
_HIRES_CTE = """
    hires AS (
      SELECT
        ho.opportunity_id,
        ho.candidate_id,
        ho.account_id,
        COALESCE(ho.setup_fee, 0)::numeric AS setup_fee,
        COALESCE(ho.fee, 0)::numeric       AS fee,
        COALESCE(ho.revenue, 0)::numeric   AS revenue,
        COALESCE(ho.salary, 0)::numeric    AS salary,
        ho.computer,
        NULLIF(TRIM(COALESCE(ho.inactive_reason, '')), '') AS inactive_reason,
        CASE
          WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
          ELSE NULLIF(ho.start_date::text, '')::date
        END AS start_d,
        CASE
          WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
          WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
          ELSE ho.end_date::date
        END AS end_d,
        CASE
          WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
            THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
          ELSE NULL
        END AS buyout_d
      FROM hire_opportunity ho
      WHERE ho.carga_active IS NOT NULL
         OR NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
    )
"""

# Scope comun de una opp cerrada del mes, para un AE del scope Sales.
_CLOSED_IN_MONTH = """
      AND TRIM(o.opp_stage) = 'Close Win'
      AND COALESCE(a.vintti_internal, FALSE) = FALSE
      AND TRIM(LOWER(COALESCE(o.opp_sales_lead, ''))) = ANY(%(sales_leads)s)
      AND NULLIF(o.opp_close_date::text, '')::date
          BETWEEN %(mes_ini)s::date AND %(mes_fin)s::date
"""


def _params(mes_ini: date, mes_fin: date) -> dict:
    return {
        "sales_leads": sales_leads(),
        "mes_ini": mes_ini,
        "mes_fin": mes_fin,
    }


# --------------------------------------------------------------------------- #
# 1. STAFFING
# --------------------------------------------------------------------------- #
def staffing(mes_ini: date, mes_fin: date) -> tuple[str, dict]:
    """Opps de Staffing cerradas en el mes, agregadas por oportunidad.

    El JOIN a `hires` es LEFT a proposito: una Close Win del mes que todavia no
    tiene el hire cargado tiene que APARECER con fees en cero y `hire_count` 0,
    no desaparecer del reporte. Ese hueco es justamente lo que hay que corregir
    antes de liquidar.
    """
    sql = "WITH " + _HIRES_CTE + """
        SELECT
          o.opportunity_id,
          COALESCE(a.client_name, '')                                     AS client_name,
          COALESCE(o.opp_position_name, '')                               AS opp_position_name,
          TO_CHAR(NULLIF(o.opp_close_date::text, '')::date, 'DD/MM/YYYY') AS close_date,
          COALESCE(SUM(h.setup_fee), 0)::float                            AS setup_fee,
          COALESCE(SUM(h.fee), 0)::float                                  AS fee,
          CASE WHEN TRIM(COALESCE(o.opp_type, '')) = 'Replacement'
               THEN 'Si' ELSE 'No' END                                    AS is_replacement,
          CASE WHEN BOOL_OR(LOWER(TRIM(COALESCE(h.computer, ''))) = 'yes')
               THEN 'Si' ELSE 'No' END                                    AS equipment,
          LOWER(TRIM(COALESCE(o.opp_sales_lead, '')))                     AS ae,
          COALESCE(STRING_AGG(DISTINCT c.name, ', '), '')                 AS candidates,
          COUNT(h.opportunity_id)::int                                    AS hire_count
        FROM opportunity o
        LEFT JOIN hires h        ON h.opportunity_id = o.opportunity_id
        LEFT JOIN account a      ON a.account_id     = o.account_id
        LEFT JOIN candidates c   ON c.candidate_id   = h.candidate_id
        WHERE o.opp_model = 'Staffing'
    """ + _CLOSED_IN_MONTH + """
        GROUP BY o.opportunity_id, a.client_name, o.opp_position_name,
                 o.opp_close_date, o.opp_type, o.opp_sales_lead
        ORDER BY NULLIF(o.opp_close_date::text, '')::date,
                 a.client_name, o.opp_position_name;
    """
    return sql, _params(mes_ini, mes_fin)


# --------------------------------------------------------------------------- #
# 2. RECRUITING
# --------------------------------------------------------------------------- #
def recruiting(mes_ini: date, mes_fin: date) -> tuple[str, dict]:
    """Opps de Recruiting cerradas en el mes.

    En Recruiting el fee vive en `hire_opportunity.revenue`, no en `fee`: es la
    misma columna que en Staffing guarda otra cosa, y el front la desdobla por
    `opp_model` (ver routes/candidates_routes.py y recruiting_window_summary).
    """
    sql = "WITH " + _HIRES_CTE + """
        SELECT
          o.opportunity_id,
          COALESCE(a.client_name, '')                                     AS client_name,
          COALESCE(o.opp_position_name, '')                               AS opp_position_name,
          TO_CHAR(NULLIF(o.opp_close_date::text, '')::date, 'DD/MM/YYYY') AS close_date,
          COALESCE(SUM(h.revenue), 0)::float                              AS recruiting_fee,
          CASE WHEN TRIM(COALESCE(o.opp_type, '')) = 'Replacement'
               THEN 'Si' ELSE 'No' END                                    AS is_replacement,
          LOWER(TRIM(COALESCE(o.opp_sales_lead, '')))                     AS ae,
          COALESCE(STRING_AGG(DISTINCT c.name, ', '), '')                 AS candidates,
          COUNT(h.opportunity_id)::int                                    AS hire_count
        FROM opportunity o
        LEFT JOIN hires h        ON h.opportunity_id = o.opportunity_id
        LEFT JOIN account a      ON a.account_id     = o.account_id
        LEFT JOIN candidates c   ON c.candidate_id   = h.candidate_id
        WHERE o.opp_model = 'Recruiting'
    """ + _CLOSED_IN_MONTH + """
        GROUP BY o.opportunity_id, a.client_name, o.opp_position_name,
                 o.opp_close_date, o.opp_type, o.opp_sales_lead
        ORDER BY NULLIF(o.opp_close_date::text, '')::date,
                 a.client_name, o.opp_position_name;
    """
    return sql, _params(mes_ini, mes_fin)


# --------------------------------------------------------------------------- #
# 3. M3 CHURN
# --------------------------------------------------------------------------- #
def m3_churn(mes_ini: date, mes_fin: date, staffing_extra_exists: bool = True):
    """Candidatos que se cayeron DENTRO del mes en sus primeros 3 meses.

    Ancla en `end_d` dentro del mes reportado y no en una ventana trailing de 90
    dias: este reporte sale una vez por mes y no puede volver a cobrar la misma
    baja al mes siguiente.

    Reglas heredadas del dashboard, no inventadas aca:
      * un BUYOUT no es churn — misma clasificacion que
        `candidate_churn_window_summary` / `op_churn_reasons_m3`:
        `buyout_d >= DATE_TRUNC('month', end_d)` lo saca de la poblacion.
      * M3 = `end_d < start_d + INTERVAL '3 months'`, el mismo calculo que la
        columna `churn_m3` de la pagina Staffing (routes/staffing_routes.py),
        y con el mismo override manual `staffing_extra.churn_m3_override`.

    `staffing_extra` la crea al vuelo la seccion Staffing; en una base que nunca
    la tuvo se cae el JOIN, asi que el override se saltea (sin override, el
    calculo automatico manda igual).
    """
    if staffing_extra_exists:
        override_join = """
        LEFT JOIN staffing_extra se
               ON se.candidate_id = h.candidate_id
              AND se.account_id   = h.account_id
        """
        m3_expr = "COALESCE(se.churn_m3_override, h.end_d < (h.start_d + INTERVAL '3 months')::date)"
    else:
        override_join = ""
        m3_expr = "h.end_d < (h.start_d + INTERVAL '3 months')::date"

    sql = "WITH " + _HIRES_CTE + f"""
        SELECT
          o.opportunity_id,
          TRIM(o.opp_model)                                               AS opp_model,
          COALESCE(a.client_name, '')                                     AS client_name,
          COALESCE(o.opp_position_name, '')                               AS opp_position_name,
          COALESCE(c.name, '')                                            AS candidate_name,
          TO_CHAR(NULLIF(o.opp_close_date::text, '')::date, 'DD/MM/YYYY') AS close_date,
          TO_CHAR(h.start_d, 'DD/MM/YYYY')                                AS start_date,
          TO_CHAR(h.end_d,   'DD/MM/YYYY')                                AS end_date,
          h.setup_fee::float                                              AS setup_fee,
          h.fee::float                                                    AS fee,
          h.revenue::float                                                AS recruiting_fee,
          CASE WHEN TRIM(COALESCE(o.opp_type, '')) = 'Replacement'
               THEN 'Si' ELSE 'No' END                                    AS is_replacement,
          CASE WHEN LOWER(TRIM(COALESCE(h.computer, ''))) = 'yes'
               THEN 'Si' ELSE 'No' END                                    AS equipment,
          LOWER(TRIM(COALESCE(o.opp_sales_lead, '')))                     AS ae,
          COALESCE(h.inactive_reason, '')                                 AS inactive_reason
        FROM hires h
        JOIN opportunity o       ON o.opportunity_id = h.opportunity_id
        LEFT JOIN account a      ON a.account_id     = COALESCE(h.account_id, o.account_id)
        LEFT JOIN candidates c   ON c.candidate_id   = h.candidate_id
        {override_join}
        WHERE TRIM(o.opp_model) IN ('Staffing', 'Recruiting')
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND TRIM(LOWER(COALESCE(o.opp_sales_lead, ''))) = ANY(%(sales_leads)s)
          AND h.start_d IS NOT NULL
          AND h.end_d BETWEEN %(mes_ini)s::date AND %(mes_fin)s::date
          AND NOT (h.buyout_d IS NOT NULL
                   AND h.buyout_d >= DATE_TRUNC('month', h.end_d))
          AND {m3_expr}
        ORDER BY h.end_d, a.client_name, c.name;
    """
    return sql, _params(mes_ini, mes_fin)


def staffing_extra_exists(cur) -> bool:
    cur.execute("SELECT to_regclass('public.staffing_extra')")
    row = cur.fetchone()
    value = row[0] if not isinstance(row, dict) else list(row.values())[0]
    return value is not None
