from __future__ import annotations

from datetime import date, datetime


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS cutoff_d,
            (%(corte)s::date - INTERVAL '29 days')::date AS win_ini,
            %(corte)s::date AS win_fin
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
        activos_cutoff AS (
          SELECT DISTINCT h.account_id
          FROM ventana v
          JOIN hires h
            ON h.start_d <= v.cutoff_d
           AND COALESCE(h.end_d, DATE '9999-12-31') >= v.cutoff_d
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
              THEN 'buyout'
              ELSE 'real'
            END AS baja_tipo
          FROM ultima_baja ub
          LEFT JOIN buyout_por_cuenta b ON b.account_id = ub.account_id
        ),
        bajas_ventana AS (
          SELECT
            COUNT(*) FILTER (WHERE bc.baja_tipo = 'real')::int   AS bajas_real,
            COUNT(*) FILTER (WHERE bc.baja_tipo = 'buyout')::int AS bajas_buyout
          FROM ventana v
          JOIN bajas_clasificadas bc
            ON bc.fecha_baja >= v.win_ini
           AND bc.fecha_baja <= v.win_fin
        ),
        clientes_activos AS (
          SELECT COUNT(*)::int AS clientes_activos FROM activos_cutoff
        )
        SELECT
          (SELECT cutoff_d FROM ventana) AS cutoff,
          (SELECT win_ini  FROM ventana) AS ventana_desde,
          (SELECT win_fin  FROM ventana) AS ventana_hasta,
          ca.clientes_activos,
          COALESCE(bv.bajas_real, 0)   AS bajas_real,
          COALESCE(bv.bajas_buyout, 0) AS bajas_buyout,
          (COALESCE(bv.bajas_real, 0) + COALESCE(bv.bajas_buyout, 0))::int AS bajas_total_staffing,
          ROUND((COALESCE(bv.bajas_real,0)::numeric / NULLIF(ca.clientes_activos, 0)) * 100, 2)::float AS churn_real_pct,
          ROUND((COALESCE(bv.bajas_buyout,0)::numeric / NULLIF(ca.clientes_activos, 0)) * 100, 2)::float AS buyout_pct,
          ROUND(((COALESCE(bv.bajas_real,0) + COALESCE(bv.bajas_buyout,0))::numeric
                 / NULLIF(ca.clientes_activos, 0)) * 100, 2)::float AS churn_total_staffing_pct
        FROM clientes_activos ca
        LEFT JOIN bajas_ventana bv ON TRUE;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "client_churn_30d_summary",
    "label": "Churn de clientes (Staffing) — Resumen 30 días",
    "dimensions": [
        {"key": "cutoff", "label": "Cutoff", "type": "date"},
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "clientes_activos", "label": "Clientes activos", "type": "number"},
        {"key": "bajas_real", "label": "Bajas Staffing", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas Buyout", "type": "number"},
        {"key": "bajas_total_staffing", "label": "Bajas Staffing + Buyout", "type": "number"},
        {"key": "churn_real_pct", "label": "Churn Staffing %", "type": "percent"},
        {"key": "buyout_pct", "label": "Churn Buyout %", "type": "percent"},
        {"key": "churn_total_staffing_pct", "label": "Churn Staffing + Buyout %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
