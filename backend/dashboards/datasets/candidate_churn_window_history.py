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


def _parse_meses(value) -> int:
    try:
        n = int(str(value).strip())
        if n in (3, 6):
            return n
    except (TypeError, ValueError):
        pass
    return 3


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    meses = _parse_meses(filters.get("meses"))
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH ho AS (
          SELECT *
          FROM (
            SELECT
              h.candidate_id,
              h.account_id,
              NULLIF(h.start_date::text, '')::date AS start_d,
              CASE
                WHEN h.end_date IS NULL OR h.end_date::text = '' THEN NULL
                ELSE h.end_date::date
              END AS end_d,
              CASE
                WHEN NULLIF(TRIM(h.buyout_daterange), '') IS NOT NULL
                  THEN TO_DATE(TRIM(h.buyout_daterange) || '-01', 'YYYY-MM-DD')
                ELSE NULL
              END AS buyout_d
            FROM hire_opportunity h
            JOIN opportunity o ON o.opportunity_id = h.opportunity_id
            WHERE o.opp_model = 'Staffing'
          ) x
          WHERE start_d IS NOT NULL
        ),
        meses_cal AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM (
            SELECT
              DATE_TRUNC('month', MIN(start_d)) AS min_start,
              DATE_TRUNC('month', CURRENT_DATE) AS max_end
            FROM ho
          ) lim,
          LATERAL generate_series(lim.min_start, lim.max_end, interval '1 month') gs
        ),
        ventana AS (
          SELECT
            m.mes,
            (m.mes - ((%(meses)s - 1) || ' months')::interval)::date AS win_ini,
            (m.mes + interval '1 month - 1 day')::date              AS m_fin
          FROM meses_cal m
        ),
        detalle AS (
          SELECT
            v.mes,
            v.win_ini,
            v.m_fin,
            h.candidate_id,
            h.start_d,
            h.end_d,
            h.buyout_d,
            CASE
              WHEN h.end_d IS NOT NULL AND h.end_d <= v.m_fin THEN 'BAJA'
              WHEN COALESCE(h.end_d, DATE '9999-12-31') >= v.m_fin THEN 'ACTIVO'
              ELSE 'FUERA'
            END AS estado_en_m,
            CASE
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.m_fin
                AND h.buyout_d IS NOT NULL
                AND h.buyout_d >= DATE_TRUNC('month', h.end_d)
                THEN 'BAJA_BUYOUT'
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.m_fin
                THEN 'BAJA_REAL'
              ELSE NULL
            END AS baja_tipo
          FROM ventana v
          JOIN ho h
            ON h.start_d BETWEEN v.win_ini AND v.m_fin
        ),
        resumen AS (
          SELECT
            d.mes,
            COUNT(DISTINCT d.candidate_id)                                       AS starts,
            COUNT(*) FILTER (WHERE d.estado_en_m = 'BAJA')                       AS bajas,
            COUNT(*) FILTER (WHERE d.baja_tipo = 'BAJA_REAL')                    AS bajas_real,
            COUNT(*) FILTER (WHERE d.baja_tipo = 'BAJA_BUYOUT')                  AS bajas_buyout,
            COUNT(*) FILTER (WHERE d.estado_en_m = 'ACTIVO')                     AS activos_al_cierre
          FROM detalle d
          WHERE (%(desde)s::date IS NULL OR d.mes >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR d.mes <= DATE_TRUNC('month', %(hasta)s::date))
          GROUP BY d.mes
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                                             AS mes,
          starts::int                                                            AS starts,
          bajas::int                                                             AS bajas,
          bajas_real::int                                                        AS bajas_real,
          bajas_buyout::int                                                      AS bajas_buyout,
          activos_al_cierre::int                                                 AS activos_al_cierre,
          ROUND(100.0 * bajas::numeric / NULLIF(starts, 0), 2)::float            AS churn_pct,
          ROUND(100.0 * bajas_real::numeric / NULLIF(starts, 0), 2)::float       AS churn_real_pct,
          ROUND(100.0 * bajas_buyout::numeric / NULLIF(starts, 0), 2)::float     AS buyout_pct
        FROM resumen
        ORDER BY mes;
    """

    return sql, {"meses": meses, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "candidate_churn_window_history",
    "label": "Churn 3/6 meses (rolling) — Histórico",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "starts", "label": "Starts en ventana", "type": "number"},
        {"key": "bajas", "label": "Bajas total", "type": "number"},
        {"key": "bajas_real", "label": "Bajas reales", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas buyout", "type": "number"},
        {"key": "activos_al_cierre", "label": "Activos al cierre", "type": "number"},
        {"key": "churn_pct", "label": "Churn total %", "type": "percent"},
        {"key": "churn_real_pct", "label": "Churn real %", "type": "percent"},
        {"key": "buyout_pct", "label": "Buyout %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
