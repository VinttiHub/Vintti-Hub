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


def _parse_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    as_of = (
        _parse_date(filters.get("as_of_date"))
        or _parse_date(filters.get("corte"))
        or datetime.utcnow().date()
    )
    dias_sin_hire = _parse_int(filters.get("dias_sin_hire"), 90)
    min_replacements = _parse_int(filters.get("min_replacements"), 2)

    sql = """
        WITH params AS (
          SELECT
            %(as_of)s::date AS as_of_d,
            %(dias_sin_hire)s::int AS dias_sin_hire,
            %(min_replacements)s::int AS min_replacements
        ),
        hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            ho.start_date::date AS start_d,
            CASE
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            TRIM(o.opp_type) AS opp_type
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
        ),
        activos_hoy AS (
          SELECT DISTINCT h.account_id
          FROM hires h
          JOIN params p ON TRUE
          WHERE h.start_d <= p.as_of_d
            AND COALESCE(h.end_d, DATE '9999-12-31') >= p.as_of_d
        ),
        activos_count AS (
          SELECT
            h.account_id,
            COUNT(DISTINCT h.candidate_id) AS candidatos_activos
          FROM hires h
          JOIN params p ON TRUE
          WHERE h.start_d <= p.as_of_d
            AND COALESCE(h.end_d, DATE '9999-12-31') >= p.as_of_d
          GROUP BY 1
        ),
        last_hire AS (
          SELECT account_id, MAX(start_d) AS last_hire_d
          FROM hires
          GROUP BY 1
        ),
        replacements AS (
          SELECT account_id, COUNT(*) AS replacements
          FROM hires
          WHERE opp_type = 'Replacement'
          GROUP BY 1
        ),
        base AS (
          SELECT
            ah.account_id,
            (
              CASE WHEN COALESCE(ac.candidatos_activos, 0) = 1 THEN 1 ELSE 0 END +
              CASE
                WHEN lh.last_hire_d < p.as_of_d - (p.dias_sin_hire * INTERVAL '1 day')
                THEN 2 ELSE 0
              END +
              CASE
                WHEN COALESCE(rp.replacements, 0) >= p.min_replacements
                THEN 1 ELSE 0
              END
            ) AS risk_score
          FROM activos_hoy ah
          JOIN params p ON TRUE
          LEFT JOIN activos_count ac ON ac.account_id = ah.account_id
          LEFT JOIN last_hire lh     ON lh.account_id = ah.account_id
          LEFT JOIN replacements rp  ON rp.account_id = ah.account_id
        ),
        clasificado AS (
          SELECT
            account_id,
            risk_score,
            CASE
              WHEN risk_score >= 3 THEN 'Alto'
              WHEN risk_score = 2  THEN 'Medio'
              ELSE 'Bajo'
            END AS riesgo_label
          FROM base
        )
        SELECT
          riesgo_label,
          COUNT(*)::int          AS clientes,
          SUM(risk_score)::int   AS puntos
        FROM clasificado
        GROUP BY riesgo_label
        ORDER BY
          CASE riesgo_label
            WHEN 'Alto'  THEN 1
            WHEN 'Medio' THEN 2
            WHEN 'Bajo'  THEN 3
          END;
    """

    return sql, {
        "as_of": as_of,
        "dias_sin_hire": dias_sin_hire,
        "min_replacements": min_replacements,
    }


DATASET = {
    "key": "risk_score_by_label",
    "label": "Risk Score — Conteo y puntos por riesgo",
    "dimensions": [
        {"key": "riesgo_label", "label": "Riesgo", "type": "string"},
    ],
    "measures": [
        {"key": "clientes", "label": "Clientes", "type": "number"},
        {"key": "puntos", "label": "Puntos acumulados", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
