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
          SELECT DISTINCT
            DATE_TRUNC('month', t.meeting_date)::date AS mes,
            t.opportunity_id,
            TRIM(o.opp_stage) AS opp_stage
          FROM turvo t
          JOIN opportunity o ON o.opportunity_id = t.opportunity_id
          WHERE (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(desde)s::date IS NULL OR t.meeting_date::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR t.meeting_date::date <= %(hasta)s::date)
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                                      AS mes,
          COUNT(*)::int                                                   AS opps_con_turbo,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int            AS opps_close_win,
          ROUND(
            100.0 * COUNT(*) FILTER (WHERE opp_stage = 'Close Win')
            / NULLIF(COUNT(*), 0), 1
          )::float                                                        AS conversion_pct
        FROM base
        GROUP BY mes
        ORDER BY mes;
    """

    return sql, {"modelo": modelo, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "turbo_closewin_history",
    "label": "Turbo → Close Win — por mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "conversion_pct", "label": "Conversión %", "type": "percent"},
        {"key": "opps_con_turbo", "label": "Opps con turbo", "type": "number"},
        {"key": "opps_close_win", "label": "Opps Close Win", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
