from __future__ import annotations

from datetime import date


def _parse_date(value) -> date | None:
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
        or filters.get("modelo1")
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
    modelo = _resolve_modelo(filters)
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH base AS (
          SELECT
            DATE_TRUNC('month', t.meeting_date)::date AS mes,
            t.candidates
          FROM turvo t
          JOIN opportunity o ON o.opportunity_id = t.opportunity_id
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            -- Excluir recruiters inactivos (ya no trabajan en Vintti)
            AND LOWER(TRIM(t.hr_lead)) <> 'agustina.barbero@vintti.com'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND (%(desde)s::date IS NULL OR t.meeting_date::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR t.meeting_date::date <= %(hasta)s::date)
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                             AS mes,
          ROUND(AVG(candidates), 1)::float                       AS promedio_candidatos,
          COUNT(*)::int                                          AS turbos_total,
          COALESCE(SUM(candidates), 0)::int                      AS candidatos_total
        FROM base
        GROUP BY mes
        ORDER BY mes;
    """

    return sql, {"modelo": modelo, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "turbo_avg_candidates_history",
    "label": "Promedio candidatos por turbo — por mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "promedio_candidatos", "label": "Promedio candidatos", "type": "number"},
        {"key": "turbos_total", "label": "Turbos totales", "type": "number"},
        {"key": "candidatos_total", "label": "Candidatos totales", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
