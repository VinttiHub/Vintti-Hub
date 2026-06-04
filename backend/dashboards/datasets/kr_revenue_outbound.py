"""KR2 · Revenue generado por Outbound ($) — AM + AE, ventana YTD | 30d.

Mismo cálculo de revenue que el card "Revenue Generated · AE" (revenue_ae_card):
  Staffing  = salary + fee  ·  Recruiting = ho.revenue, por Close Win opp.
Pero scope AM + AE (unión opp_sales_lead ∈ {AEs} OR account_manager = {AM})
y filtrado al canal Outbound. Dos ventanas seleccionables:
  - ytd  : del 1-ene del año en curso al corte.
  - 30d  : últimos 30 días al corte.
La batería se llena con el split Staffing/Recruiting (% del total).
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
        WITH wins AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
            AND ( LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
                  OR LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(am_leads)s )
        ),
        per_opp AS (
          SELECT
            w.opportunity_id, w.opp_model, w.close_d,
            COALESCE(SUM(
              CASE WHEN w.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                   ELSE COALESCE(ho.salary, 0) + COALESCE(ho.fee, 0) END
            ), 0)::numeric AS revenue
          FROM wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          GROUP BY w.opportunity_id, w.opp_model, w.close_d
        ),
        in_window AS (
          SELECT * FROM per_opp
          WHERE close_d IS NOT NULL AND close_d >= %(win_ini)s::date AND close_d <= %(win_fin)s::date
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
    "key": "kr_revenue_outbound",
    "label": "KR2 · Revenue Outbound (AM+AE) por ventana",
    "dimensions": [{"key": "window_label", "label": "Ventana", "type": "string"}],
    "measures": [
        {"key": "total_revenue", "label": "Revenue total", "type": "currency"},
        {"key": "staffing_revenue", "label": "Staffing", "type": "currency"},
        {"key": "recruiting_revenue", "label": "Recruiting", "type": "currency"},
        {"key": "total_closes", "label": "Close wins total", "type": "number"},
        {"key": "staffing_closes", "label": "Close wins Staffing", "type": "number"},
        {"key": "recruiting_closes", "label": "Close wins Recruiting", "type": "number"},
        {"key": "staffing_pct_of_total", "label": "Staffing % del total", "type": "percent"},
        {"key": "recruiting_pct_of_total", "label": "Recruiting % del total", "type": "percent"},
    ],
    "default_filters": {"window": "30d"},
    "query": query,
}
