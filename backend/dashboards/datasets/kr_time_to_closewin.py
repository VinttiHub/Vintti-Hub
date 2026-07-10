"""Objetivo 3 · KR3 — Time to Close Win desde NDA Signed (días avg) · AM + AE.

Días promedio = opp_close_date − nda_signature_or_start_date, para Close Win
(opp_type 'New') cuyo cierre cae en los últimos 30 días. Scope AM + AE
(opp_sales_lead ∈ {Mariano,Bahía} OR account_manager = Lara).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar


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
    win_ini = corte - timedelta(days=29)

    sql = """
        WITH base AS (
          SELECT
            (NULLIF(o.opp_close_date::text,'')::date
             - NULLIF(o.nda_signature_or_start_date::text,'')::date) AS days
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND o.opp_type = 'New'
            AND ( LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
                  OR LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(am_leads)s )
            AND NULLIF(o.opp_close_date::text,'')::date >= NULLIF(o.nda_signature_or_start_date::text,'')::date
            AND NULLIF(o.opp_close_date::text,'')::date BETWEEN %(win_ini)s::date AND %(corte)s::date
        )
        SELECT
          ROUND(AVG(days))::int AS promedio_dias,
          COUNT(*)::int         AS deal_count
        FROM base;
    """
    return sql, {"ae_leads": AE_LEADS, "am_leads": AM_LEADS, "win_ini": win_ini, "corte": corte}


DATASET = {
    "key": "kr_time_to_closewin",
    "label": "Obj3 KR3 · Time to Close Win desde NDA (días avg, AM+AE, 30d)",
    "dimensions": [],
    "measures": [
        {"key": "promedio_dias", "label": "Días avg", "type": "number"},
        {"key": "deal_count", "label": "Close wins", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
