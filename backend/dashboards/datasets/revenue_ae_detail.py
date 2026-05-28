"""Per-row breakdown of Revenue Generated (AEs only), por modelo y ventana.

Mirror of `revenue_ae_window` at row level: each hire owned by an AE (Mariano
or Bahia) whose `opp_close_date` falls in the selected window, with its
candidate, client, close date and the revenue contribution.

Used by the AE Metrics tab's detail tables. Same window/modelo filters as the
summary so the sum of the rows equals the KPI tile.
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
    raw = str(
        filters.get("event_window")
        or filters.get("window")
        or filters.get("ventana")
        or "30d"
    ).strip().lower()
    if raw in ("week", "semana", "last_week", "last-week", "prev_week"):
        prev_sunday = corte - timedelta(days=corte.weekday() + 1)
        prev_monday = prev_sunday - timedelta(days=6)
        return prev_monday, prev_sunday
    if raw in ("7d", "7"):
        return corte - timedelta(days=6), corte
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
    modelo = _modelo(filters)

    revenue_expr = (
        "COALESCE(ho.revenue, 0)::float"
        if modelo == "Recruiting"
        else "(COALESCE(ho.salary, 0) + COALESCE(ho.fee, 0))::float"
    )

    sql = f"""
        SELECT
          COALESCE(c.name, '')                                            AS candidate_name,
          COALESCE(a.client_name, '')                                     AS client_name,
          COALESCE(o.opp_sales_lead, '')                                  AS opp_sales_lead,
          TO_CHAR(NULLIF(o.opp_close_date::text, '')::date, 'YYYY-MM-DD') AS close_date,
          {revenue_expr}                                                  AS revenue
        FROM hire_opportunity ho
        JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
        LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
        LEFT JOIN account a    ON a.account_id   = ho.account_id
        WHERE o.opp_model = %(modelo)s
          AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
          AND o.opp_close_date IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '')::date >= %(win_ini)s::date
          AND NULLIF(o.opp_close_date::text, '')::date <= %(win_fin)s::date
        ORDER BY NULLIF(o.opp_close_date::text, '')::date DESC NULLS LAST,
                 revenue DESC NULLS LAST,
                 c.name;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
        "modelo": modelo,
        "sales_leads": SALES_LEADS,
    }


DATASET = {
    "key": "revenue_ae_detail",
    "label": "Revenue Generated (AEs only) — Detalle por close en ventana",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [
        {"key": "revenue", "label": "Revenue", "type": "currency"},
    ],
    "default_filters": {"window": "30d", "modelo": "Staffing"},
    "query": query,
}
