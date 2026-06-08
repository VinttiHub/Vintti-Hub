"""Marketing · Eficiencia por canal — COHORTE POR SQL, por origin / período.

Una fila por canal (origin = account.where_come_from, sin outbound, '(Sin origen)'
aparte). TODAS las columnas describen LAS MISMAS cuentas: las que entraron al CRM
(SQL = account.creation_date) dentro del período (semana / mes / q / anio, default
'mes'). Para esa cohorte, medimos qué pasó con ellas (outcomes acumulados a hoy):

  - sqls        → tamaño de la cohorte (cuentas que entraron en el período).
  - clients     → cuántas de esas cuentas se volvieron cliente (≥1 Close Win, ever).
  - net_rev     → fee de Vintti (Staffing ho.fee + Recruiting ho.revenue) de los
                  Close Win de esas cuentas.
  - close_rate  → win rate de lo DECIDIDO dentro de la cohorte: Close Win ÷
                  (Close Win + solo Closed Lost). + ratio "won/decided".
  - cltv_months → vida promedio real en meses (Staffing) de esas cuentas.

Por construcción: clients ≤ sqls, decididos ≤ sqls → la fila es internamente
consistente. OJO: cohortes recientes (semana/mes) se ven inmaduras porque los deals
tardan meses en cerrar; mirá Q / Año para conversión madura.

NO incluye MQLs ni CAC: no hay etapa MQL en el CRM ni data de gasto de marketing
por canal en la base, así que no se pueden calcular hoy.
"""
from __future__ import annotations

from .mkt_sqls_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, label = period_bounds(filters)
    sql = """
        WITH cohort AS (
          SELECT a.account_id,
                 COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
          FROM account a
          WHERE a.creation_date IS NOT NULL
            AND a.creation_date::date BETWEEN %(ini)s::date AND %(fin)s::date
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
        ),
        -- Resultado de oportunidades por cuenta de la cohorte (acumulado a hoy)
        opp_agg AS (
          SELECT c.account_id,
                 BOOL_OR(TRIM(o.opp_stage) = 'Close Win')                          AS won,
                 BOOL_OR(TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost'))         AS decided
          FROM cohort c
          JOIN opportunity o ON o.account_id = c.account_id
          GROUP BY c.account_id
        ),
        -- Net revenue por cuenta de la cohorte (fees de Close Win)
        rev_per_opp AS (
          SELECT c.account_id, o.opportunity_id, o.opp_model,
                 COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                                   ELSE COALESCE(ho.fee, 0) END), 0)::numeric AS rev
          FROM cohort c
          JOIN opportunity o ON o.account_id = c.account_id
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
          WHERE TRIM(o.opp_stage) = 'Close Win' AND o.opp_model IN ('Staffing', 'Recruiting')
          GROUP BY c.account_id, o.opportunity_id, o.opp_model
        ),
        rev_per_acct AS (
          SELECT account_id, SUM(rev)::numeric AS net_rev
          FROM rev_per_opp GROUP BY account_id
        ),
        -- Vida (meses) por cuenta de la cohorte (Staffing)
        hires AS (
          SELECT c.account_id,
                 CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                      ELSE NULLIF(ho.start_date::text, '')::date END AS start_d,
                 CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                      WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
                      ELSE ho.end_date::date END AS end_d
          FROM cohort c
          JOIN hire_opportunity ho ON ho.account_id = c.account_id
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE TRIM(o.opp_stage) = 'Close Win' AND o.opp_model = 'Staffing'
        ),
        life_per_acct AS (
          SELECT account_id,
                 (DATE_PART('year',  AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) * 12
                + DATE_PART('month', AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) + 1)::int AS lifetime_months
          FROM hires
          WHERE start_d IS NOT NULL
          GROUP BY account_id
        ),
        joined AS (
          SELECT c.origin, c.account_id,
                 COALESCE(oa.won, false)     AS won,
                 COALESCE(oa.decided, false) AS decided,
                 COALESCE(ra.net_rev, 0)     AS net_rev,
                 la.lifetime_months
          FROM cohort c
          LEFT JOIN opp_agg      oa ON oa.account_id = c.account_id
          LEFT JOIN rev_per_acct ra ON ra.account_id = c.account_id
          LEFT JOIN life_per_acct la ON la.account_id = c.account_id
        )
        SELECT
          origin,
          COUNT(*)::int                                              AS sqls,
          COUNT(*) FILTER (WHERE won)::int                           AS clients,
          ROUND(SUM(net_rev))::bigint                                AS net_rev,
          ROUND(AVG(lifetime_months) FILTER (WHERE lifetime_months IS NOT NULL), 1)::float AS cltv_months,
          ROUND(COUNT(*) FILTER (WHERE won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE decided), 0), 1)::float AS close_rate,
          (COUNT(*) FILTER (WHERE won)::text || '/'
           || COUNT(*) FILTER (WHERE decided)::text)                 AS ratio,
          %(label)s::text                                            AS period_label
        FROM joined
        GROUP BY origin
        ORDER BY sqls DESC, clients DESC, net_rev DESC, origin;
    """
    return sql, {"ini": ini, "fin": fin, "label": label}


DATASET = {
    "key": "mkt_efficiency_by_channel",
    "label": "Marketing · Eficiencia por canal (cohorte por SQL, período)",
    "dimensions": [
        {"key": "origin", "label": "Canal", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "sqls", "label": "SQLs", "type": "number"},
        {"key": "clients", "label": "Clients", "type": "number"},
        {"key": "net_rev", "label": "Net rev.", "type": "currency"},
        {"key": "cltv_months", "label": "CLTV (meses)", "type": "number"},
        {"key": "close_rate", "label": "Tasa cierre", "type": "percent"},
        {"key": "ratio", "label": "CW / Total", "type": "string"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
