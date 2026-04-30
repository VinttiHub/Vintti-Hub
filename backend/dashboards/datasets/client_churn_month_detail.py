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
    mes = (
        _parse_date(filters.get("fecha_client_churn"))
        or _parse_date(filters.get("fecha"))
        or _parse_date(filters.get("mes"))
        or _parse_date(filters.get("month"))
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
        ),
        hires AS (
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
        meses_filtrado AS (
          SELECT mo.mes_pick AS mes
          FROM mes_objetivo mo
          WHERE (%(desde)s::date IS NULL OR mo.mes_pick >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR mo.mes_pick <= DATE_TRUNC('month', %(hasta)s::date))
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
            ub.fecha_baja::date AS fecha_baja,
            CASE
              WHEN b.buyout_d IS NOT NULL
               AND b.buyout_d >= DATE_TRUNC('month', ub.fecha_baja)
              THEN 'Churn – Buyout (Conversión)'
              ELSE 'Churn – Real'
            END AS tipo_churn
          FROM ultima_baja ub
          LEFT JOIN buyout_por_cuenta b ON b.account_id = ub.account_id
        ),
        bajas_mes_detalle AS (
          SELECT
            m.mes,
            bc.account_id,
            bc.fecha_baja,
            bc.tipo_churn
          FROM meses_filtrado m
          JOIN activos_mes am ON am.mes = m.mes
          JOIN bajas_clasificadas bc
            ON bc.account_id = am.account_id
           AND bc.fecha_baja >= m.mes
           AND bc.fecha_baja < (m.mes + INTERVAL '1 month')
        )
        SELECT
          TO_CHAR(am.mes, 'YYYY-MM') AS mes,
          a.client_name,
          TO_CHAR(b.fecha_baja, 'YYYY-MM-DD') AS fecha_baja,
          COALESCE(b.tipo_churn, 'Activo') AS estado_cliente_mes
        FROM activos_mes am
        JOIN account a ON a.account_id = am.account_id
        LEFT JOIN bajas_mes_detalle b
          ON b.mes = am.mes
         AND b.account_id = am.account_id
        ORDER BY am.mes, a.client_name;
    """

    return sql, {"mes": mes, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "client_churn_month_detail",
    "label": "Churn de clientes (Staffing) — Detalle del mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "fecha_baja", "label": "Fecha baja", "type": "date"},
        {"key": "estado_cliente_mes", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
