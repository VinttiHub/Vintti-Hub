"""New opportunities by AM — per-row breakdown by window.

Sibling of new_opps_am_windows. Same filter (opps with opp_type='New' owned
by an AM email in DASHBOARD_AM_EMAILS, default `lara@vintti.com`) but
instead of 4 aggregate counts, returns one row per opp inside the selected
window.

The `event_window` filter picks which window the rows belong to:
last_week | wtd | last_month | mtd. Defaults to last_week to match the hero.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds


_DEFAULT_AM_EMAILS = ("lara@vintti.com",)


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


def _am_emails() -> list[str]:
    raw = os.environ.get("DASHBOARD_AM_EMAILS", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(_DEFAULT_AM_EMAILS)


def _window_bounds(filters: dict, corte: date) -> tuple[date, date]:
    # Si hay un rango Desde/Hasta o un Mes activo, el detalle sigue ESE período
    # (coincide con la card colapsada), ignorando las ventanas de calendario.
    if filters.get("desde") or filters.get("hasta") or filters.get("mes"):
        return window_bounds(filters)
    raw = str(
        filters.get("event_window")
        or filters.get("window")
        or filters.get("ventana")
        or "last_week"
    ).strip().lower().replace("-", "_")
    if raw == "week":
        raw = "last_week"
    if raw in {"month", "prev_month"}:
        raw = "last_month"

    this_week_monday = corte - timedelta(days=corte.weekday())
    prev_week_sunday = this_week_monday - timedelta(days=1)
    prev_week_monday = prev_week_sunday - timedelta(days=6)

    month_start = corte.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    if raw == "wtd":
        return this_week_monday, corte
    if raw == "last_month":
        return last_month_start, last_month_end
    if raw == "mtd":
        return month_start, corte
    # default last_week
    return prev_week_monday, prev_week_sunday


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = """
        SELECT
          COALESCE(a.client_name, '')                                              AS client_name,
          COALESCE(o.opp_position_name, '')                                        AS position_name,
          COALESCE(o.opp_model, '')                                                AS opp_model,
          COALESCE(o.opp_stage, '')                                                AS opp_stage,
          COALESCE(LOWER(TRIM(o.opp_sales_lead)), '')                              AS am_email,
          TO_CHAR(
            COALESCE(
              NULLIF(o.nda_signature_or_start_date::text, '')::date,
              NULLIF(o.opp_close_date::text, '')::date
            ),
            'YYYY-MM-DD'
          )                                                                        AS opened_date,
          o.opportunity_id::text                                                   AS opportunity_id
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE o.opp_type = 'New'
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND TRIM(LOWER(o.opp_stage)) <> 'closed lost'
          AND TRIM(LOWER(o.opp_sales_lead)) = ANY(%(am_emails)s)
          AND COALESCE(
            NULLIF(o.nda_signature_or_start_date::text, '')::date,
            NULLIF(o.opp_close_date::text, '')::date
          ) BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ORDER BY opened_date DESC NULLS LAST, a.client_name;
    """

    return sql, {
        "am_emails": _am_emails(),
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "new_opps_am_detail",
    "label": "New opportunities by AM — Detalle por ventana",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "position_name", "label": "Position", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "am_email", "label": "AM", "type": "string"},
        {"key": "opened_date", "label": "Opened", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"event_window": "last_week"},
    "query": query,
}
