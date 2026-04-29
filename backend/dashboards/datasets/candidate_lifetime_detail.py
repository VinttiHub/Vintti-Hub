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
            NULLIF(CAST(ho.start_date AS TEXT), '')::date AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR CAST(ho.end_date AS TEXT) = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
            AND NULLIF(CAST(ho.start_date AS TEXT), '') IS NOT NULL
            AND o.opp_model = 'Staffing'
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM candidatos),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM candidatos),
            interval '1 month'
          ) gs
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
        activos_mes_filtrado AS (
          SELECT *
          FROM activos_mes
          WHERE (%(desde)s::date IS NULL OR mes >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR mes <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        duracion_candidato_cliente AS (
          SELECT
            account_id,
            candidate_id,
            MIN(mes) AS first_month_active,
            MAX(mes) AS last_month_active,
            COUNT(*) AS active_months
          FROM activos_mes_filtrado
          GROUP BY 1, 2
        )
        SELECT
          (d.candidate_id::text || '_' || d.account_id::text) AS row_key,
          acc.client_name,
          cand.name AS candidate_name,
          to_char(d.first_month_active, 'YYYY-MM') AS first_month_active,
          to_char(d.last_month_active,  'YYYY-MM') AS last_month_active,
          d.active_months AS meses_activo
        FROM duracion_candidato_cliente d
        JOIN account acc      ON acc.account_id = d.account_id
        LEFT JOIN candidates cand ON cand.candidate_id = d.candidate_id
        ORDER BY d.active_months ASC, acc.client_name, cand.name;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "candidate_lifetime_detail",
    "label": "Candidate Lifetime in Months — Detail (Staffing)",
    "dimensions": [
        {"key": "row_key", "label": "Row Key", "type": "string"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "candidate_name", "label": "Candidate", "type": "string"},
        {"key": "first_month_active", "label": "First Month", "type": "date"},
        {"key": "last_month_active", "label": "Last Month", "type": "date"},
        {"key": "meses_activo", "label": "Active Months", "type": "number"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
