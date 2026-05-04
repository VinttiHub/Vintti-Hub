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
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(ho.start_date::text, '') IS NOT NULL
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
        activos_inicio AS (
          SELECT DISTINCT
            m.mes,
            h.account_id
          FROM meses_filtrado m
          JOIN hires h
            ON h.start_d <= m.mes
           AND COALESCE(h.end_d, DATE '9999-12-31') >= m.mes
        ),
        activos_fin AS (
          SELECT DISTINCT
            m.mes,
            h.account_id
          FROM meses_filtrado m
          JOIN hires h
            ON h.start_d <= (m.mes + interval '1 month - 1 day')::date
           AND COALESCE(h.end_d, DATE '9999-12-31') >= (m.mes + interval '1 month - 1 day')::date
        ),
        inicio_agg AS (
          SELECT mes, COUNT(DISTINCT account_id)::int AS clientes_activos_inicio
          FROM activos_inicio
          GROUP BY 1
        ),
        fin_agg AS (
          SELECT mes, COUNT(DISTINCT account_id)::int AS clientes_activos_fin
          FROM activos_fin
          GROUP BY 1
        ),
        retenidos_agg AS (
          SELECT
            ai.mes,
            COUNT(DISTINCT ai.account_id)::int AS clientes_retenidos
          FROM activos_inicio ai
          JOIN activos_fin af
            ON af.mes = ai.mes
           AND af.account_id = ai.account_id
          GROUP BY 1
        )
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM-DD')                         AS mes,
          TO_CHAR((m.mes + interval '1 month - 1 day')::date, 'YYYY-MM-DD') AS mes_fin,
          COALESCE(i.clientes_activos_inicio, 0)               AS clientes_activos_inicio,
          COALESCE(f.clientes_activos_fin, 0)                  AS clientes_activos_fin,
          COALESCE(r.clientes_retenidos, 0)                    AS clientes_retenidos,
          ROUND(
            (COALESCE(f.clientes_activos_fin, 0)::numeric
             / NULLIF(COALESCE(i.clientes_activos_inicio, 0), 0)) * 100
          , 2)::float                                          AS grr_pct,
          ROUND(
            (COALESCE(r.clientes_retenidos, 0)::numeric
             / NULLIF(COALESCE(i.clientes_activos_inicio, 0), 0)) * 100
          , 2)::float                                          AS crr_pct,
          ROUND(
            ((COALESCE(i.clientes_activos_inicio, 0) - COALESCE(r.clientes_retenidos, 0))::numeric
             / NULLIF(COALESCE(i.clientes_activos_inicio, 0), 0)) * 100
          , 2)::float                                          AS churn_inicio_pct
        FROM meses_filtrado m
        LEFT JOIN inicio_agg    i ON i.mes = m.mes
        LEFT JOIN fin_agg       f ON f.mes = m.mes
        LEFT JOIN retenidos_agg r ON r.mes = m.mes
        ORDER BY m.mes;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "crr_history",
    "label": "CRR & GRR mensual (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "clientes_activos_inicio", "label": "Activos inicio", "type": "number"},
        {"key": "clientes_activos_fin", "label": "Activos fin", "type": "number"},
        {"key": "clientes_retenidos", "label": "Retenidos", "type": "number"},
        {"key": "grr_pct", "label": "GRR % (fin/inicio)", "type": "percent"},
        {"key": "crr_pct", "label": "CRR % (retenidos/inicio)", "type": "percent"},
        {"key": "churn_inicio_pct", "label": "Churn inicio %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
