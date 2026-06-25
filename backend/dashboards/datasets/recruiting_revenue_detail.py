"""Per-row breakdown of Recruiting revenue inside a window.

Lists each Recruiting hire whose `opp_close_date` falls in the selected
window with its candidate, client and revenue. Default window is YTD so the
sum of the rows matches the hero of the "Revenue · Recruiting" drawer.

Window can be overridden via the `window` filter (week, mtd, month, 30d, 7d,
ytd) to mirror the breakdown by smaller periods.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ._periods import window_bounds


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


def _window_bounds(filters: dict, corte: date) -> tuple[date, date]:
    """Resolve (win_ini, win_fin) from the `window` filter. Default: YTD.

    Mirrors recruiting_window_summary so per-window totals stay in sync.
    """
    # event_window (drawer-tile click) takes priority over the global window.
    raw = str(
        filters.get("event_window")
        or filters.get("window")
        or filters.get("ventana")
        or "ytd"
    ).strip().lower()
    if raw in ("7d", "7"):
        return corte - timedelta(days=6), corte
    if raw in ("week", "semana", "last_week", "last-week", "prev_week"):
        prev_sunday = corte - timedelta(days=corte.weekday() + 1)
        prev_monday = prev_sunday - timedelta(days=6)
        return prev_monday, prev_sunday
    if raw == "mtd":
        return corte.replace(day=1), corte
    if raw in ("month", "last_month", "last-month", "prev_month"):
        first_this = corte.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        first_prev = last_prev.replace(day=1)
        return first_prev, last_prev
    if raw == "30d":
        return window_bounds(filters)
    # default: YTD (Jan 1 of the corte year through corte)
    return corte.replace(month=1, day=1), corte


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = """
        SELECT
          COALESCE(c.name, '')                                            AS candidate_name,
          COALESCE(a.client_name, '')                                     AS client_name,
          TO_CHAR(NULLIF(o.opp_close_date::text, '')::date, 'YYYY-MM-DD') AS close_date,
          COALESCE(ho.revenue, 0)::float                                  AS revenue
        FROM hire_opportunity ho
        JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
        LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
        LEFT JOIN account a    ON a.account_id   = ho.account_id
        WHERE o.opp_model = 'Recruiting'
          AND TRIM(o.opp_stage) = 'Close Win'   -- R10: solo revenue de opps ganadas
          AND o.opp_close_date IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '')::date >= %(win_ini)s::date
          AND NULLIF(o.opp_close_date::text, '')::date <= %(win_fin)s::date
        ORDER BY NULLIF(o.opp_close_date::text, '')::date DESC NULLS LAST,
                 COALESCE(ho.revenue, 0) DESC NULLS LAST,
                 c.name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "recruiting_revenue_detail",
    "label": "Recruiting Revenue — Detalle por contractor (Close Win en ventana)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [
        {"key": "revenue", "label": "Revenue", "type": "currency"},
    ],
    "default_filters": {"window": "ytd"},
    "query": query,
}
