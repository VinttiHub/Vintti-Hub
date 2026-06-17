from __future__ import annotations

from datetime import date, datetime, timezone

from ._periods import window_bounds


def _parse_date(value) -> date | None:
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
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("mes"))
        or datetime.now(timezone.utc).date()
    )

    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        opps_turbo AS (
          SELECT DISTINCT
            t.opportunity_id,
            TRIM(o.opp_stage) AS opp_stage
          FROM turvo t
          JOIN opportunity o ON o.opportunity_id = t.opportunity_id
          CROSS JOIN ventana v
          WHERE t.meeting_date::date BETWEEN v.win_ini AND v.win_fin
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        )
        SELECT
          COUNT(*)::int                                                   AS opps_con_turbo,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int            AS opps_close_win,
          ROUND(
            100.0 * COUNT(*) FILTER (WHERE opp_stage = 'Close Win')
            / NULLIF(COUNT(*), 0), 1
          )::float                                                        AS conversion_pct
        FROM opps_turbo;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "modelo": modelo, "corte": corte}


DATASET = {
    "key": "turbo_closewin_30d_summary",
    "label": "Turbo → Close Win — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "conversion_pct", "label": "Conversión %", "type": "percent"},
        {"key": "opps_con_turbo", "label": "Opps con turbo", "type": "number"},
        {"key": "opps_close_win", "label": "Opps Close Win", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
