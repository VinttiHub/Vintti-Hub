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
        _parse_date(filters.get("fecha_candidate_churn"))
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
        candidatos AS (
          SELECT
            ho.candidate_id,
            COALESCE(c.name, '') AS candidate_name,
            ho.account_id,
            COALESCE(a.client_name, '') AS client_name,
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
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          LEFT JOIN account a    ON a.account_id  = ho.account_id
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
        ),
        meses_filtrado AS (
          SELECT
            mo.mes_pick AS mes,
            (mo.mes_pick + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM mes_objetivo mo
          WHERE (%(desde)s::date IS NULL OR mo.mes_pick >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR mo.mes_pick <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        activos_inicio_detalle AS (
          SELECT m.mes, m.fin_mes, c.*
          FROM meses_filtrado m
          JOIN candidatos c
            ON c.start_d IS NOT NULL
           AND c.start_d <= m.mes
           AND (c.end_d IS NULL OR c.end_d >= m.mes)
        ),
        altas_mes_detalle AS (
          SELECT m.mes, m.fin_mes, c.*
          FROM candidatos c
          JOIN meses_filtrado m
            ON c.start_d IS NOT NULL
           AND DATE_TRUNC('month', c.start_d)::date = m.mes
        ),
        bajas_mes_detalle AS (
          SELECT
            d.mes, d.fin_mes,
            d.candidate_id, d.candidate_name, d.client_name, d.start_d, d.end_d,
            CASE
              WHEN d.buyout_d IS NOT NULL AND d.buyout_d >= DATE_TRUNC('month', d.end_d)
                THEN 'Baja – Buyout (Conversión)'
              ELSE 'Baja – Real'
            END AS estado
          FROM activos_inicio_detalle d
          WHERE d.end_d IS NOT NULL
            AND d.end_d >= d.mes
            AND d.end_d <= d.fin_mes
        ),
        starts_y_bajas_mes AS (
          SELECT
            m.mes, m.fin_mes,
            c.candidate_id, c.candidate_name, c.client_name, c.start_d, c.end_d,
            (CASE
              WHEN c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d)
                THEN 'Baja – Buyout (Conversión)'
              ELSE 'Baja – Real'
            END) || ' (Start+End mismo mes)' AS estado
          FROM meses_filtrado m
          JOIN candidatos c
            ON c.start_d IS NOT NULL
           AND c.end_d IS NOT NULL
           AND c.start_d >= m.mes AND c.start_d <= m.fin_mes
           AND c.end_d   >= m.mes AND c.end_d   <= m.fin_mes
        ),
        all_rows AS (
          SELECT mes, candidate_id, candidate_name, client_name, start_d, end_d,
                 'Activo al inicio'::text AS estado
          FROM activos_inicio_detalle
          UNION ALL
          SELECT mes, candidate_id, candidate_name, client_name, start_d, end_d, estado
          FROM bajas_mes_detalle
          UNION ALL
          SELECT mes, candidate_id, candidate_name, client_name, start_d, end_d, estado
          FROM starts_y_bajas_mes
          UNION ALL
          SELECT mes, candidate_id, candidate_name, client_name, start_d, end_d,
                 'Alta en el mes'::text AS estado
          FROM altas_mes_detalle
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM') AS mes,
          client_name,
          candidate_name,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_d,
          TO_CHAR(end_d,   'YYYY-MM-DD') AS end_d,
          estado
        FROM all_rows
        ORDER BY
          mes,
          CASE
            WHEN estado = 'Alta en el mes'                  THEN 3
            WHEN estado = 'Activo al inicio'                THEN 2
            WHEN estado LIKE 'Baja% (Start+End mismo mes)'  THEN 1
            WHEN estado LIKE 'Baja%'                        THEN 0
            ELSE -1
          END DESC,
          client_name,
          candidate_name;
    """

    return sql, {"mes": mes, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "candidate_churn_month_detail",
    "label": "Candidatos (Staffing) — Detalle del mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
        {"key": "end_d", "label": "End", "type": "date"},
        {"key": "estado", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
