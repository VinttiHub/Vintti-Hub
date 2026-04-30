from __future__ import annotations

from datetime import date


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH hires AS (
          SELECT
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange::text), '') IS NOT NULL
                THEN TO_DATE(NULLIF(TRIM(ho.buyout_daterange::text), '') || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(ho.start_date::text,'') IS NOT NULL
            )
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM hires),
            COALESCE((SELECT MAX(end_d) FROM hires), CURRENT_DATE),
            interval '1 month'
          ) gs
        ),
        meses_filtrado AS (
          SELECT *
          FROM meses m
          WHERE (%(desde)s::date IS NULL OR m.mes >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR m.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        activos_mes AS (
          SELECT DISTINCT
            m.mes,
            h.account_id
          FROM meses_filtrado m
          JOIN hires h
            ON h.start_d <= (m.mes + interval '1 month - 1 day')::date
           AND COALESCE(h.end_d, DATE '9999-12-31') >= m.mes
        ),
        activos_agg AS (
          SELECT mes, COUNT(DISTINCT account_id) AS clientes_activos
          FROM activos_mes
          GROUP BY 1
        ),
        ultima_baja_raw AS (
          SELECT account_id, MAX(end_d) AS fecha_baja
          FROM hires
          WHERE end_d IS NOT NULL
          GROUP BY 1
        ),
        cuentas_con_activos_posteriores AS (
          SELECT DISTINCT ub.account_id
          FROM ultima_baja_raw ub
          JOIN hires h
            ON h.account_id = ub.account_id
           AND COALESCE(h.end_d, DATE '9999-12-31') > ub.fecha_baja
        ),
        ultima_baja AS (
          SELECT *
          FROM ultima_baja_raw
          WHERE account_id NOT IN (SELECT account_id FROM cuentas_con_activos_posteriores)
        ),
        buyout_por_cuenta AS (
          SELECT account_id, MAX(buyout_d) AS buyout_d
          FROM hires
          WHERE buyout_d IS NOT NULL
          GROUP BY 1
        ),
        bajas_clasificadas AS (
          SELECT
            ub.account_id,
            ub.fecha_baja,
            CASE
              WHEN b.buyout_d IS NOT NULL
               AND b.buyout_d >= DATE_TRUNC('month', ub.fecha_baja)
              THEN 'buyout'
              ELSE 'real'
            END AS baja_tipo
          FROM ultima_baja ub
          LEFT JOIN buyout_por_cuenta b ON b.account_id = ub.account_id
        ),
        bajas_mes AS (
          SELECT
            m.mes,
            COUNT(*) FILTER (WHERE bc.baja_tipo = 'real')::int   AS bajas_real,
            COUNT(*) FILTER (WHERE bc.baja_tipo = 'buyout')::int AS bajas_buyout
          FROM meses_filtrado m
          JOIN activos_mes am ON am.mes = m.mes
          JOIN bajas_clasificadas bc
            ON bc.account_id = am.account_id
           AND bc.fecha_baja >= m.mes
           AND bc.fecha_baja <  (m.mes + INTERVAL '1 month')
          GROUP BY 1
        ),
        resumen AS (
          SELECT
            m.mes,
            COALESCE(a.clientes_activos, 0)::int AS clientes_activos,
            COALESCE(b.bajas_real, 0)::int       AS bajas_real,
            COALESCE(b.bajas_buyout, 0)::int     AS bajas_buyout
          FROM meses_filtrado m
          LEFT JOIN activos_agg a ON a.mes = m.mes
          LEFT JOIN bajas_mes   b ON b.mes = m.mes
        )
        SELECT
          TO_CHAR(mes::date, 'YYYY-MM-DD') AS mes,
          TO_CHAR((mes + interval '1 month - 1 day')::date, 'YYYY-MM-DD') AS mes_fin,
          clientes_activos,
          bajas_real,
          bajas_buyout,
          (bajas_real + bajas_buyout)::int AS bajas_total_staffing,
          ROUND((bajas_real::numeric / NULLIF(clientes_activos, 0)) * 100, 2)::float AS churn_real_pct,
          ROUND((bajas_buyout::numeric / NULLIF(clientes_activos, 0)) * 100, 2)::float AS buyout_pct,
          ROUND(((bajas_real + bajas_buyout)::numeric / NULLIF(clientes_activos, 0)) * 100, 2)::float AS churn_total_staffing_pct
        FROM resumen
        ORDER BY mes;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "client_churn_history",
    "label": "Churn mensual de clientes (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "clientes_activos", "label": "Clientes activos", "type": "number"},
        {"key": "bajas_real", "label": "Bajas reales", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas buyout", "type": "number"},
        {"key": "bajas_total_staffing", "label": "Bajas total Staffing", "type": "number"},
        {"key": "churn_real_pct", "label": "Churn real %", "type": "percent"},
        {"key": "buyout_pct", "label": "Buyout %", "type": "percent"},
        {"key": "churn_total_staffing_pct", "label": "Churn total Staffing %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
