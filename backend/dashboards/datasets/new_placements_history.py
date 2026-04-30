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


def _resolve_modelo(filters: dict) -> str | None:
    raw = (
        filters.get("modelo")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    modelo = _resolve_modelo(filters)

    sql = """
        WITH base AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text,'') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND o.opp_model IN ('Staffing','Recruiting')
        ),
        starts AS (
          SELECT
            DATE_TRUNC('month', b.start_d)::date AS mes,
            b.opp_model,
            COUNT(DISTINCT (b.candidate_id, b.opportunity_id, b.start_d)) AS starts
          FROM base b
          WHERE b.start_d IS NOT NULL
          GROUP BY 1, 2
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT COALESCE(MIN(start_d), CURRENT_DATE)::date FROM base),
            (SELECT COALESCE(MAX(start_d), CURRENT_DATE)::date FROM base),
            interval '1 month'
          ) gs
        ),
        pivot AS (
          SELECT
            m.mes,
            COALESCE(SUM(CASE WHEN s.opp_model = 'Staffing'   THEN s.starts END), 0)::int AS staffing_starts,
            COALESCE(SUM(CASE WHEN s.opp_model = 'Recruiting' THEN s.starts END), 0)::int AS recruiting_starts
          FROM meses m
          LEFT JOIN starts s ON s.mes = m.mes
          GROUP BY 1
        )
        SELECT
          TO_CHAR(p.mes, 'YYYY-MM-DD') AS mes,
          p.staffing_starts,
          p.recruiting_starts,
          (p.staffing_starts + p.recruiting_starts)::int AS total_starts
        FROM pivot p
        WHERE 1=1
          AND (%(desde)s::date IS NULL OR p.mes >= DATE_TRUNC('month', %(desde)s::date))
          AND (%(hasta)s::date IS NULL OR p.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ORDER BY p.mes;
    """

    return sql, {"modelo": modelo, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "new_placements_history",
    "label": "Nuevas colocaciones por mes (Staffing + Recruiting)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "staffing_starts", "label": "Staffing", "type": "number"},
        {"key": "recruiting_starts", "label": "Recruiting", "type": "number"},
        {"key": "total_starts", "label": "Total", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
