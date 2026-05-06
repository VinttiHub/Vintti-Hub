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
        WITH candidatos AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
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
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM candidatos WHERE start_d IS NOT NULL),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM candidatos WHERE start_d IS NOT NULL),
            INTERVAL '1 month'
          ) gs
        ),
        meses_filtrado AS (
          SELECT *
          FROM meses m
          WHERE (%(desde)s::date IS NULL OR m.mes >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR m.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        activos_inicio_detalle AS (
          SELECT
            m.mes,
            m.fin_mes,
            c.candidate_id,
            c.end_d,
            c.buyout_d
          FROM meses_filtrado m
          JOIN candidatos c
            ON c.start_d IS NOT NULL
           AND c.start_d < m.mes
           AND (c.end_d IS NULL OR c.end_d >= m.mes)
        ),
        candidatos_activos AS (
          SELECT mes, COUNT(DISTINCT candidate_id)::int AS activos_inicio
          FROM activos_inicio_detalle
          GROUP BY mes
        ),
        bajas_mes_inicio AS (
          SELECT
            d.mes,
            COUNT(DISTINCT d.candidate_id) FILTER (
              WHERE NOT (
                d.buyout_d IS NOT NULL
                AND d.buyout_d >= DATE_TRUNC('month', d.end_d)
              )
            )::int AS bajas_real,
            COUNT(DISTINCT d.candidate_id) FILTER (
              WHERE d.buyout_d IS NOT NULL
                AND d.buyout_d >= DATE_TRUNC('month', d.end_d)
            )::int AS bajas_buyout
          FROM activos_inicio_detalle d
          WHERE d.end_d IS NOT NULL
            AND d.end_d >= d.mes
            AND d.end_d <= d.fin_mes
          GROUP BY d.mes
        ),
        bajas_mes_starts AS (
          SELECT
            m.mes,
            COUNT(DISTINCT c.candidate_id) FILTER (
              WHERE NOT (
                c.buyout_d IS NOT NULL
                AND c.buyout_d >= DATE_TRUNC('month', c.end_d)
              )
            )::int AS bajas_real,
            COUNT(DISTINCT c.candidate_id) FILTER (
              WHERE c.buyout_d IS NOT NULL
                AND c.buyout_d >= DATE_TRUNC('month', c.end_d)
            )::int AS bajas_buyout
          FROM meses_filtrado m
          JOIN candidatos c
            ON c.start_d IS NOT NULL
           AND c.end_d IS NOT NULL
           AND c.start_d >= m.mes
           AND c.start_d <= m.fin_mes
           AND c.end_d   >= m.mes
           AND c.end_d   <= m.fin_mes
          GROUP BY m.mes
        ),
        resumen AS (
          SELECT
            m.mes,
            COALESCE(a.activos_inicio, 0) AS activos_inicio,
            COALESCE(bi.bajas_real, 0) + COALESCE(bs.bajas_real, 0)     AS bajas_real,
            COALESCE(bi.bajas_buyout, 0) + COALESCE(bs.bajas_buyout, 0) AS bajas_buyout
          FROM meses_filtrado m
          LEFT JOIN candidatos_activos a ON a.mes = m.mes
          LEFT JOIN bajas_mes_inicio  bi ON bi.mes = m.mes
          LEFT JOIN bajas_mes_starts  bs ON bs.mes = m.mes
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD') AS mes,
          activos_inicio,
          (bajas_real + bajas_buyout)::int AS bajas,
          bajas_real::int  AS bajas_real,
          bajas_buyout::int AS bajas_buyout,
          ROUND(((bajas_real + bajas_buyout)::numeric / NULLIF(activos_inicio, 0)) * 100, 2)::float AS churn_pct,
          ROUND((bajas_real::numeric / NULLIF(activos_inicio, 0)) * 100, 2)::float AS churn_real_pct,
          ROUND((bajas_buyout::numeric / NULLIF(activos_inicio, 0)) * 100, 2)::float AS buyout_pct
        FROM resumen
        ORDER BY mes;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "candidate_churn_history",
    "label": "Churn mensual de candidatos (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "activos_inicio", "label": "Activos al inicio", "type": "number"},
        {"key": "bajas", "label": "Bajas total", "type": "number"},
        {"key": "bajas_real", "label": "Bajas reales", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas buyout", "type": "number"},
        {"key": "churn_pct", "label": "Churn total %", "type": "percent"},
        {"key": "churn_real_pct", "label": "Churn real %", "type": "percent"},
        {"key": "buyout_pct", "label": "Buyout %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
