"""KR1 detalle · nuevos clientes (new logos, AM+AE) de la ventana (ytd | 30d).

Lista la opp del primer Close Win de cada cuenta cuyo primer cierre cae en la
ventana y es AM+AE. Una fila por new-logo opp.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
AM_LEADS = ("lara@vintti.com",)


def _parse_date(value):
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or today_ar())
    window_key = str(filters.get("window") or "30d").strip().lower()
    if window_key in ("week", "semana", "last_week", "prev_week"):
        prev_sunday = corte - timedelta(days=corte.weekday() + 1)
        win_ini, win_fin = prev_sunday - timedelta(days=6), prev_sunday
    else:
        win_ini, win_fin = window_bounds(filters)
    model = str(filters.get("model") or "").strip()
    model_clause = "AND w.model = %(model)s" if model in ("Staffing", "Recruiting") else ""

    sql = f"""
        WITH all_wins AS (
          SELECT o.opportunity_id, o.account_id, a.client_name, o.opp_position_name,
                 TRIM(o.opp_model) AS model,
                 NULLIF(o.opp_close_date::text,'')::date AS close_d,
                 LOWER(TRIM(COALESCE(o.opp_sales_lead,''))) AS lead,
                 LOWER(TRIM(COALESCE(a.account_manager,''))) AS amgr
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND o.opp_model IN ('Staffing','Recruiting')
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
        ),
        first_close AS (
          SELECT account_id, MIN(close_d) AS first_d FROM all_wins GROUP BY account_id
        ),
        new_logo AS (
          SELECT w.* FROM all_wins w
          JOIN first_close f ON f.account_id = w.account_id AND w.close_d = f.first_d
          WHERE f.first_d >= %(win_ini)s::date AND f.first_d <= %(win_fin)s::date
            AND ( w.lead IN %(ae_leads)s OR w.amgr IN %(am_leads)s )
            {model_clause}
        )
        SELECT w.client_name, w.model, w.opp_position_name,
               TO_CHAR(w.close_d,'YYYY-MM-DD') AS close_date,
               COALESCE(SUM(
                 CASE WHEN w.model = 'Recruiting' THEN COALESCE(ho.revenue,0)
                      ELSE COALESCE(ho.salary,0)+COALESCE(ho.fee,0) END), 0)::bigint AS revenue
        FROM new_logo w
        LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
        GROUP BY w.client_name, w.model, w.opp_position_name, w.close_d
        ORDER BY revenue DESC, w.client_name;
    """
    params = {"ae_leads": AE_LEADS, "am_leads": AM_LEADS, "win_ini": win_ini, "win_fin": win_fin}
    if model_clause:
        params["model"] = model
    return sql, params


DATASET = {
    "key": "kr_revenue_new_logos_detail",
    "label": "KR1 detalle · nuevos clientes (new logos, AM+AE)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Primer cierre", "type": "date"},
    ],
    "measures": [{"key": "revenue", "label": "Revenue ($)", "type": "currency"}],
    "default_filters": {"window": "ytd"},
    "query": query,
}
