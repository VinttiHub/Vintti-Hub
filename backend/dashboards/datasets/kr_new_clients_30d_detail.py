"""KR5 detalle · clientes nuevos (new logos, AM+AE) cerrados en los últimos 30 días."""
from __future__ import annotations

from datetime import date, datetime, timedelta


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
             or datetime.utcnow().date())
    win_ini, win_fin = corte - timedelta(days=29), corte

    sql = """
        WITH all_wins AS (
          SELECT o.opportunity_id, o.account_id, a.client_name, o.opp_position_name,
                 TRIM(o.opp_model) AS model,
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
        )
        SELECT w.client_name, w.model, w.opp_position_name,
               TO_CHAR(w.close_d, 'YYYY-MM-DD') AS close_date
        FROM all_wins w
        JOIN first_close f ON f.account_id = w.account_id AND w.close_d = f.first_d
        WHERE f.first_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND ( w.lead IN %(ae_leads)s OR w.amgr IN %(am_leads)s )
        ORDER BY w.close_d DESC, w.client_name;
    """
    return sql, {"ae_leads": AE_LEADS, "am_leads": AM_LEADS, "win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "kr_new_clients_30d_detail",
    "label": "KR5 detalle · clientes nuevos (new logos, AM+AE, 30d)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Primer cierre", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
