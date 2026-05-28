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
        "COALESCE(ho.revenue, 0)::numeric"
        if modelo == "Recruiting"
        else "(COALESCE(ho.salary, 0) + COALESCE(ho.fee, 0))::numeric"
    )

    # One row per close win (NOT per hire). An opp with 2 hires (e.g. Theta)
    # would otherwise appear twice — we aggregate per opportunity, concatenating
    # candidate names with `, ` so the row still has context. LEFT JOIN keeps
    # wins that don't have a hire_opportunity row yet (revenue = 0).
    sql = f"""
        WITH ae_wins AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            COALESCE(o.opp_sales_lead, '')                                  AS opp_sales_lead,
            COALESCE(o.opp_position_name, '')                               AS opp_position_name,
            NULLIF(o.opp_close_date::text, '')::date                        AS close_d
          FROM opportunity o
          WHERE o.opp_model = %(modelo)s
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND TRIM(o.opp_stage) = 'Close Win'
        ),
        per_opp AS (
          SELECT
            w.opportunity_id,
            w.account_id,
            w.opp_sales_lead,
            w.opp_position_name,
            w.close_d,
            STRING_AGG(NULLIF(TRIM(c.name), ''), ', ' ORDER BY c.name)      AS candidate_name,
            COUNT(ho.candidate_id)                                          AS hire_count,
            COALESCE(SUM({revenue_expr}), 0)::float                         AS revenue
          FROM ae_wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          LEFT JOIN candidates       c  ON c.candidate_id   = ho.candidate_id
          GROUP BY w.opportunity_id, w.account_id, w.opp_sales_lead, w.opp_position_name, w.close_d
        )
        SELECT
          COALESCE(po.candidate_name, '')                                   AS candidate_name,
          COALESCE(a.client_name, '')                                       AS client_name,
          po.opp_sales_lead                                                 AS opp_sales_lead,
          po.opp_position_name                                              AS opp_position_name,
          po.hire_count::int                                                AS hire_count,
          TO_CHAR(po.close_d, 'YYYY-MM-DD')                                 AS close_date,
          po.revenue                                                        AS revenue
        FROM per_opp po
        LEFT JOIN account a ON a.account_id = po.account_id
        WHERE po.close_d IS NOT NULL
          AND po.close_d >= %(win_ini)s::date
          AND po.close_d <= %(win_fin)s::date
        ORDER BY po.close_d DESC NULLS LAST,
                 po.revenue DESC NULLS LAST,
                 a.client_name;
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
        {"key": "candidate_name", "label": "Candidato(s)", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [
        {"key": "hire_count", "label": "Candidatos en la opp", "type": "number"},
        {"key": "revenue", "label": "Revenue", "type": "currency"},
    ],
    "default_filters": {"window": "30d", "modelo": "Staffing"},
    "query": query,
}
