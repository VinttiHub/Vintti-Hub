from __future__ import annotations

from datetime import date, datetime, timezone
from ._now import today_ar

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
        or today_ar()
    )

    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        )
        SELECT
          t.opportunity_id::text                                AS opportunity_id,
          a.client_name,
          o.opp_position_name,
          TRIM(o.opp_stage)                                     AS opp_stage,
          COUNT(*)::int                                         AS turbos,
          TO_CHAR(MAX(t.meeting_date)::date, 'YYYY-MM-DD')      AS last_meeting_date
        FROM turvo t
        JOIN opportunity o ON o.opportunity_id = t.opportunity_id
        LEFT JOIN account a ON a.account_id = o.account_id
        CROSS JOIN ventana v
        WHERE t.meeting_date::date BETWEEN v.win_ini AND v.win_fin
          AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        GROUP BY 1, 2, 3, 4
        ORDER BY a.client_name, last_meeting_date DESC;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "modelo": modelo, "corte": corte}


DATASET = {
    "key": "turbo_closewin_detail",
    "label": "Turbo → Close Win — Detalle por opp (ventana)",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "last_meeting_date", "label": "Última turbo", "type": "date"},
    ],
    "measures": [
        {"key": "turbos", "label": "Turbos", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
