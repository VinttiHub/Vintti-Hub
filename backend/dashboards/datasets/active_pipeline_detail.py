"""Active pipeline — opportunity-level detail.

Lists every opportunity counted by `active_pipeline` (the snapshot KPI).
Filtering happens client-side on the dashboard (model / type) using the
columns returned here, so the dataset itself just emits the full list.
"""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from .active_pipeline import PIPELINE_EXCLUDE_STAGES_SQL


def _parse_date(value):
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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )

    sql = f"""
        SELECT
          a.client_name,
          o.opp_position_name,
          o.opp_model,
          o.opp_type,
          TRIM(o.opp_stage)                                 AS opp_stage,
          COALESCE(o.expected_revenue, 0)::bigint           AS expected_revenue,
          o.opp_sales_lead
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE TRUE
          {PIPELINE_EXCLUDE_STAGES_SQL}
        ORDER BY a.client_name, o.opp_position_name;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "active_pipeline_detail",
    "label": "Active pipeline — detalle de opps abiertas",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "opp_type", "label": "Tipo", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "opp_sales_lead", "label": "Sales lead", "type": "string"},
    ],
    "measures": [
        {"key": "expected_revenue", "label": "Expected revenue", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
