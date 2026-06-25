"""KR6 detalle · candidatos colocados (AM+AE) en los últimos 30 días (por start date)."""
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
    win_ini, win_fin = window_bounds(filters)

    sql = """
        SELECT
          COALESCE(c.name, '')                          AS candidate_name,
          a.client_name,
          TRIM(o.opp_model)                             AS model,
          o.opp_position_name,
          TO_CHAR(CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                       ELSE NULLIF(ho.start_date::text,'')::date END, 'YYYY-MM-DD') AS start_date
        FROM hire_opportunity ho
        JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
        JOIN account a ON a.account_id = o.account_id
        LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
        WHERE o.opp_model IN ('Staffing', 'Recruiting')
          AND TRIM(o.opp_stage) = 'Close Win'
          AND ho.candidate_id IS NOT NULL
          AND (CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                    ELSE NULLIF(ho.start_date::text,'')::date END) BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND ( LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
                OR LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(am_leads)s )
        ORDER BY start_date DESC, a.client_name;
    """
    return sql, {"ae_leads": AE_LEADS, "am_leads": AM_LEADS, "win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "kr_new_candidates_30d_detail",
    "label": "KR6 detalle · candidatos colocados (AM+AE, 30d)",
    "dimensions": [
        {"key": "candidate_name", "label": "Contractor", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "start_date", "label": "Start", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
