"""Obj3 KR3 detalle · close wins con días NDA→cierre (AM+AE, últimos 30 días)."""
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
    win_ini = corte - timedelta(days=29)

    sql = """
        SELECT
          a.client_name,
          o.opp_position_name,
          TO_CHAR(NULLIF(o.nda_signature_or_start_date::text,'')::date, 'YYYY-MM-DD') AS nda_date,
          TO_CHAR(NULLIF(o.opp_close_date::text,'')::date, 'YYYY-MM-DD')              AS close_date,
          (NULLIF(o.opp_close_date::text,'')::date
           - NULLIF(o.nda_signature_or_start_date::text,'')::date)::int              AS days
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
          AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
          AND TRIM(o.opp_stage) = 'Close Win'
          AND o.opp_type = 'New'
          AND ( LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
                OR LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(am_leads)s )
          AND NULLIF(o.opp_close_date::text,'')::date >= NULLIF(o.nda_signature_or_start_date::text,'')::date
          AND NULLIF(o.opp_close_date::text,'')::date BETWEEN %(win_ini)s::date AND %(corte)s::date
        ORDER BY days ASC, a.client_name;
    """
    return sql, {"ae_leads": AE_LEADS, "am_leads": AM_LEADS, "win_ini": win_ini, "corte": corte}


DATASET = {
    "key": "kr_time_to_closewin_detail",
    "label": "Obj3 KR3 detalle · días NDA→cierre (AM+AE, 30d)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "nda_date", "label": "NDA firmado", "type": "date"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [{"key": "days", "label": "Días", "type": "number"}],
    "default_filters": {},
    "query": query,
}
