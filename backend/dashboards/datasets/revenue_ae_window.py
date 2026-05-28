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
    return corte - timedelta(days=29), corte


def _modelo(filters: dict) -> str:
    raw = str(filters.get("modelo") or "Staffing").strip()
    return raw if raw in ALLOWED_MODELS else "Staffing"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )
    win_ini, win_fin = _window_bounds(filters, corte)
    window_days = (win_fin - win_ini).days + 1
    modelo = _modelo(filters)

    # Revenue expression varies per model. Recruiting uses ho.revenue (one-time
    # placement fee). Staffing uses salary + fee (first month of MRR booked at
    # close). The window summary just sums whatever applies for the chosen model.
    revenue_expr = (
        "COALESCE(ho.revenue, 0)::numeric"
        if modelo == "Recruiting"
        else "COALESCE(ho.salary, 0)::numeric + COALESCE(ho.fee, 0)::numeric"
    )

    sql = f"""
        WITH params AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        ae_hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            ho.opportunity_id,
            {revenue_expr}                       AS revenue_row,
            o.opp_close_date::date               AS close_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = %(modelo)s
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
        )
        SELECT
          (SELECT win_fin FROM params)                       AS corte,
          (SELECT win_ini FROM params)                       AS win_ini,
          %(window_days)s::int                               AS window_days,
          %(modelo)s::text                                   AS modelo,
          COALESCE(SUM(rh.revenue_row), 0)::bigint           AS revenue_window,
          COUNT(*)::int                                      AS closes_window,
          COUNT(DISTINCT rh.account_id)::int                 AS clients_window
        FROM ae_hires rh
        CROSS JOIN params p
        WHERE rh.close_d IS NOT NULL
          AND rh.close_d BETWEEN p.win_ini AND p.win_fin;
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
