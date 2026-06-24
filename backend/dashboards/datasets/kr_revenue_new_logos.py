"""KR1 · Revenue total de nuevos clientes cerrados ($) — AM + AE, ventana YTD | 30d.

"Nuevo cliente" = new logo: la cuenta cierra su PRIMER Close Win (de cualquier
dueño). Ese primer deal cuenta para KR1 si su close date cae en la ventana Y la
opp del primer cierre es AM+AE (unión opp_sales_lead ∈ {AEs} OR account_manager
= {AM}). Revenue = salary+fee (Staffing) / ho.revenue (Recruiting) de esa opp.
Split Staffing/Recruiting según el modelo del primer deal. Ventanas: ytd | 30d.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)


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

    sql = """
        WITH all_wins AS (
          SELECT
            o.opportunity_id, o.account_id, o.opp_model,
            NULLIF(o.opp_close_date::text, '')::date AS close_d,
            LOWER(TRIM(COALESCE(o.opp_sales_lead, '')))  AS lead,
            LOWER(TRIM(COALESCE(a.account_manager, '')))  AS amgr
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
        ),
        first_close AS (
          SELECT account_id, MIN(close_d) AS first_d FROM all_wins GROUP BY account_id
        ),
        new_logo AS (   -- la(s) opp(s) del primer cierre, sólo si cae en ventana y es AM+AE
          SELECT w.opportunity_id, w.opp_model
          FROM all_wins w
          JOIN first_close f ON f.account_id = w.account_id AND w.close_d = f.first_d
          WHERE f.first_d >= %(win_ini)s::date AND f.first_d <= %(win_fin)s::date
            AND ( w.lead IN %(ae_leads)s OR w.amgr IN %(am_leads)s )
        ),
        per_opp AS (
          SELECT
            n.opportunity_id, n.opp_model,
            COALESCE(SUM(
              CASE WHEN n.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                   ELSE COALESCE(ho.salary, 0) + COALESCE(ho.fee, 0) END
            ), 0)::numeric AS revenue
          FROM new_logo n
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = n.opportunity_id
          GROUP BY n.opportunity_id, n.opp_model
        ),
        rolled AS (
          SELECT
            COALESCE(SUM(revenue) FILTER (WHERE opp_model = 'Staffing'),   0)::numeric AS staffing_revenue,
            COALESCE(SUM(revenue) FILTER (WHERE opp_model = 'Recruiting'), 0)::numeric AS recruiting_revenue,
            COUNT(*) FILTER (WHERE opp_model = 'Staffing')::int                        AS staffing_closes,
            COUNT(*) FILTER (WHERE opp_model = 'Recruiting')::int                      AS recruiting_closes,
            COUNT(*)::int                                                              AS total_closes
          FROM per_opp
        )
        SELECT
          %(window_label)s::text                                       AS window_label,
          r.staffing_revenue::bigint                                   AS staffing_revenue,
          r.recruiting_revenue::bigint                                 AS recruiting_revenue,
          (r.staffing_revenue + r.recruiting_revenue)::bigint          AS total_revenue,
          r.staffing_closes, r.recruiting_closes, r.total_closes,
          ROUND(100.0 * r.staffing_revenue
                / NULLIF(r.staffing_revenue + r.recruiting_revenue, 0), 1)::float   AS staffing_pct_of_total,
          ROUND(100.0 * r.recruiting_revenue
                / NULLIF(r.staffing_revenue + r.recruiting_revenue, 0), 1)::float   AS recruiting_pct_of_total
        FROM rolled r;
    """
    return sql, {
        "ae_leads": AE_LEADS, "am_leads": AM_LEADS,
        "win_ini": win_ini, "win_fin": win_fin, "window_label": window_label,
    }


DATASET = {
    "key": "kr_revenue_new_logos",
    "label": "KR1 · Gross Revenue nuevos clientes (new logos, AM+AE, salary + fee) por ventana",
    "dimensions": [{"key": "window_label", "label": "Ventana", "type": "string"}],
    "measures": [
        {"key": "total_revenue", "label": "Revenue total", "type": "currency"},
        {"key": "staffing_revenue", "label": "Staffing", "type": "currency"},
        {"key": "recruiting_revenue", "label": "Recruiting", "type": "currency"},
        {"key": "total_closes", "label": "Nuevos clientes", "type": "number"},
        {"key": "staffing_closes", "label": "Nuevos · Staffing", "type": "number"},
        {"key": "recruiting_closes", "label": "Nuevos · Recruiting", "type": "number"},
        {"key": "staffing_pct_of_total", "label": "Staffing % del total", "type": "percent"},
        {"key": "recruiting_pct_of_total", "label": "Recruiting % del total", "type": "percent"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
