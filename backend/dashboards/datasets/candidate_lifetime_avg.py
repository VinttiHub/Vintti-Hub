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
    desde = _parse_date(filters.get("desde")) or _parse_date(filters.get("from"))
    hasta = _parse_date(filters.get("hasta")) or _parse_date(filters.get("to"))

    sql = """
        WITH candidatos AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(CAST(ho.start_date AS TEXT), '') IS NOT NULL
                THEN NULLIF(CAST(ho.start_date AS TEXT), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR CAST(ho.end_date AS TEXT) = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(CAST(ho.start_date AS TEXT), '') IS NOT NULL
            )
            AND o.opp_model = 'Staffing'
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM candidatos),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM candidatos),
            interval '1 month'
          ) gs
          WHERE (%(desde)s::date IS NULL OR DATE_TRUNC('month', gs)::date >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR DATE_TRUNC('month', gs)::date <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        activos_mes AS (
          SELECT
            m.mes,
            c.account_id,
            c.candidate_id
          FROM meses m
          JOIN candidatos c
            ON c.start_d < (m.mes + interval '1 month')
           AND (c.end_d IS NULL OR c.end_d >= m.mes)
          GROUP BY 1, 2, 3
        ),
        duracion_candidato_cliente AS (
          SELECT
            account_id,
            candidate_id,
            COUNT(*) AS active_months
          FROM activos_mes
          GROUP BY 1, 2
        )
        SELECT
          AVG(active_months)::numeric(10, 0) AS promedio_meses_por_candidato_en_cliente,
          COUNT(*)                           AS n_candidato_cliente
        FROM duracion_candidato_cliente;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "candidate_lifetime_avg",
    "label": "Candidate Lifetime — Average Months per (candidate, client) (Staffing)",
    "dimensions": [],
    "measures": [
        {"key": "promedio_meses_por_candidato_en_cliente", "label": "Promedio meses por candidato en cliente", "type": "number"},
        {"key": "n_candidato_cliente", "label": "N (candidato × cliente)", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
