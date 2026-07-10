"""Revenue Generated (AEs only) — snapshot per ventana, por modelo.

"AEs only" means filtered to `opp_sales_lead IN ('mariano@vintti.com',
'bahia@vintti.com')`. Two model behaviors:

- Recruiting → SUM(ho.revenue)         (one-time revenue per close win)
- Staffing   → SUM(ho.salary + ho.fee) (first month of MRR booked at close)

Window is resolved from the `window` filter (week | 30d). Default: 30d.
A row is included when `opp_close_date` falls in the window AND the deal is
owned by an AE. Sibling dataset `revenue_ae_detail` lists each row that the
KPI total is composed of.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
ALLOWED_MODELS = ("Staffing", "Recruiting")


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
    """Resolve (win_ini, win_fin). Supported: week (prev full Mon-Sun) | 30d."""
    raw = str(filters.get("window") or filters.get("ventana") or "30d").strip().lower()
    if raw in ("week", "semana", "last_week", "last-week", "prev_week"):
        prev_sunday = corte - timedelta(days=corte.weekday() + 1)
        prev_monday = prev_sunday - timedelta(days=6)
        return prev_monday, prev_sunday
    if raw in ("7d", "7"):
        return corte - timedelta(days=6), corte
    # default: rolling 30d (29-day offset, matches recruiting_window_summary)
    return window_bounds(filters)


def _modelo(filters: dict) -> str:
    raw = str(filters.get("modelo") or "Staffing").strip()
    return raw if raw in ALLOWED_MODELS else "Staffing"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)
    window_days = (win_fin - win_ini).days + 1
    modelo = _modelo(filters)

    # Revenue per hire. Recruiting uses ho.revenue (one-time placement fee),
    # Staffing uses salary + fee (first month of MRR booked at close).
    revenue_expr = (
        "COALESCE(ho.revenue, 0)::numeric"
        if modelo == "Recruiting"
        else "COALESCE(ho.salary, 0)::numeric + COALESCE(ho.fee, 0)::numeric"
    )

    # NOTE: one close win = one row. An opp with N hire_opportunity rows would
    # naively be counted N times — Theta has 1 win but 2 hires, so we aggregate
    # per opportunity first. LEFT JOIN keeps close wins that have no
    # hire_opportunity row yet (their revenue contribution is 0). Stage filter
    # `Close Win` mirrors the rest of the codebase (sourcing_to_close_win.py,
    # nda_close_win_30d_summary.py, …) and excludes `Closed Lost`.
    sql = f"""
        WITH params AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        ae_wins AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_model = %(modelo)s
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        per_opp AS (
          SELECT
            w.opportunity_id,
            w.account_id,
            w.close_d,
            COALESCE(SUM({revenue_expr}), 0)::numeric AS revenue
          FROM ae_wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          GROUP BY w.opportunity_id, w.account_id, w.close_d
        )
        SELECT
          (SELECT win_fin FROM params)                       AS corte,
          (SELECT win_ini FROM params)                       AS win_ini,
          %(window_days)s::int                               AS window_days,
          %(modelo)s::text                                   AS modelo,
          COALESCE(SUM(po.revenue), 0)::bigint               AS revenue_window,
          COUNT(*)::int                                      AS closes_window,
          COUNT(DISTINCT po.account_id)::int                 AS clients_window
        FROM per_opp po
        CROSS JOIN params p
        WHERE po.close_d IS NOT NULL
          AND po.close_d BETWEEN p.win_ini AND p.win_fin;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
        "window_days": window_days,
        "modelo": modelo,
        "sales_leads": SALES_LEADS,
    }


DATASET = {
    "key": "revenue_ae_window",
    "label": "Revenue Generated (AEs only) — Snapshot por ventana (week | 30d)",
    "dimensions": [
        {"key": "corte", "label": "Corte", "type": "date"},
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "window_days", "label": "Ventana (días)", "type": "number"},
        {"key": "modelo", "label": "Modelo", "type": "string"},
    ],
    "measures": [
        {"key": "revenue_window", "label": "Revenue (window)", "type": "currency"},
        {"key": "closes_window", "label": "Closes (window)", "type": "number"},
        {"key": "clients_window", "label": "Clients (window)", "type": "number"},
    ],
    "default_filters": {"window": "30d", "modelo": "Staffing"},
    "query": query,
}
