"""Revenue Generated por ventana (30d | week) — feeds the AE card.

Suma `salary + fee` para Staffing + `ho.revenue` para Recruiting de las opps
**Close Win** owned por los AEs (Mariano + Bahia) cuya `opp_close_date` cae
en la ventana seleccionada.

El frontend hace dos fetches (`window=30d` y `window=week`) y un toggle local
en la card swappea entre los dos panes. Por eso no hay nada de YTD ni objetivo
anual acá — sólo totales puntuales de la ventana y su breakdown por modelo.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


# AE roster — la card siempre agrega ambos. Para sumar otro AE alcanza con
# meter el email acá.
SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")

# Human-friendly title shown in the card.
AE_NAME = "AE"

# Goal per window (USD). The battery's dashed "meta" line and the
# "$X restantes" badge derive from these.
GOAL_BY_WINDOW = {
    "30d":  50_000,
    "week": 12_000,
}


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
    except (ValueError, TypeError):
        return None
    return None


def _window_key(filters: dict) -> str:
    raw = str(filters.get("window") or filters.get("ventana") or "30d").strip().lower()
    if raw in ("week", "semana", "last_week", "last-week", "prev_week"):
        return "week"
    return "30d"


def _window_bounds(window_key: str, corte: date) -> tuple[date, date, str]:
    """Resolve (win_ini, win_fin, label) for the given window key."""
    if window_key == "week":
        prev_sunday = corte - timedelta(days=corte.weekday() + 1)
        prev_monday = prev_sunday - timedelta(days=6)
        return prev_monday, prev_sunday, "Semana"
    return corte - timedelta(days=29), corte, "Últimos 30 días"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or datetime.utcnow().date()
    )
    window_key = _window_key(filters)
    win_ini, win_fin, window_label = _window_bounds(window_key, corte)
    goal = GOAL_BY_WINDOW.get(window_key, GOAL_BY_WINDOW["30d"])

    # One row per Close Win opp (NOT per hire) — same pattern as
    # `revenue_ae_detail`. LEFT JOIN keeps wins without hires (revenue = 0)
    # so the count matches the CRM.
    sql = """
        WITH ae_wins AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          WHERE TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND TRIM(o.opp_stage) = 'Close Win'
        ),
        per_opp AS (
          SELECT
            w.opportunity_id,
            w.opp_model,
            w.close_d,
            COALESCE(SUM(
              CASE WHEN w.opp_model = 'Recruiting'
                   THEN COALESCE(ho.revenue, 0)
                   ELSE COALESCE(ho.salary, 0) + COALESCE(ho.fee, 0)
              END
            ), 0)::numeric AS revenue
          FROM ae_wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          GROUP BY w.opportunity_id, w.opp_model, w.close_d
        ),
        in_window AS (
          SELECT *
          FROM per_opp
          WHERE close_d IS NOT NULL
            AND close_d >= %(win_ini)s::date
            AND close_d <= %(win_fin)s::date
        ),
        rolled AS (
          SELECT
            COALESCE(SUM(revenue) FILTER (WHERE opp_model = 'Staffing'),   0)::numeric AS staffing_revenue,
            COALESCE(SUM(revenue) FILTER (WHERE opp_model = 'Recruiting'), 0)::numeric AS recruiting_revenue,
            COUNT(*) FILTER (WHERE opp_model = 'Staffing')::int                        AS staffing_closes,
            COUNT(*) FILTER (WHERE opp_model = 'Recruiting')::int                      AS recruiting_closes,
            COUNT(*)::int                                                              AS total_closes
          FROM in_window
        )
        SELECT
          %(ae_name)s::text                                            AS ae_name,
          %(window_label)s::text                                       AS window_label,
          %(win_ini)s::date                                            AS win_ini,
          %(win_fin)s::date                                            AS win_fin,
          r.staffing_revenue::bigint                                   AS staffing_revenue,
          r.recruiting_revenue::bigint                                 AS recruiting_revenue,
          (r.staffing_revenue + r.recruiting_revenue)::bigint          AS total_revenue,
          r.staffing_closes,
          r.recruiting_closes,
          r.total_closes,
          ROUND(100.0 * r.staffing_revenue
                / NULLIF(r.staffing_revenue + r.recruiting_revenue, 0), 1)::float
                                                                       AS staffing_pct_of_total,
          ROUND(100.0 * r.recruiting_revenue
                / NULLIF(r.staffing_revenue + r.recruiting_revenue, 0), 1)::float
                                                                       AS recruiting_pct_of_total,
          -- Goal-relative metrics (drive the battery meta line + restantes badge).
          %(goal)s::bigint                                             AS goal,
          ROUND(100.0 * (r.staffing_revenue + r.recruiting_revenue)
                / NULLIF(%(goal)s, 0), 1)::float                       AS pct_of_goal,
          ROUND(100.0 * r.staffing_revenue
                / NULLIF(%(goal)s, 0), 1)::float                       AS staffing_pct_of_goal,
          ROUND(100.0 * r.recruiting_revenue
                / NULLIF(%(goal)s, 0), 1)::float                       AS recruiting_pct_of_goal,
          GREATEST(%(goal)s::bigint - (r.staffing_revenue + r.recruiting_revenue)::bigint, 0)::bigint
                                                                       AS remaining
        FROM rolled r;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "ae_name": AE_NAME,
        "win_ini": win_ini,
        "win_fin": win_fin,
        "window_label": window_label,
        "goal": goal,
    }


DATASET = {
    "key": "revenue_ae_card",
    "label": "Revenue Generated (Mariano + Bahia) — por ventana",
    "dimensions": [
        {"key": "ae_name", "label": "AE", "type": "string"},
        {"key": "window_label", "label": "Ventana", "type": "string"},
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "win_fin", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "total_revenue", "label": "Revenue total", "type": "currency"},
        {"key": "staffing_revenue", "label": "Staffing", "type": "currency"},
        {"key": "recruiting_revenue", "label": "Recruiting", "type": "currency"},
        {"key": "total_closes", "label": "Closes total", "type": "number"},
        {"key": "staffing_closes", "label": "Closes Staffing", "type": "number"},
        {"key": "recruiting_closes", "label": "Closes Recruiting", "type": "number"},
        {"key": "staffing_pct_of_total", "label": "Staffing % del total", "type": "percent"},
        {"key": "recruiting_pct_of_total", "label": "Recruiting % del total", "type": "percent"},
        {"key": "goal", "label": "Meta de la ventana", "type": "currency"},
        {"key": "pct_of_goal", "label": "% de la meta", "type": "percent"},
        {"key": "staffing_pct_of_goal", "label": "Staffing % de la meta", "type": "percent"},
        {"key": "recruiting_pct_of_goal", "label": "Recruiting % de la meta", "type": "percent"},
        {"key": "remaining", "label": "Restantes para la meta", "type": "currency"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
