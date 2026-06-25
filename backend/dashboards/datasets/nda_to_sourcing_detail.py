"""NDA Sent → Sourcing · detail (30d, Mariano + Bahia).

Lists every opportunity whose `nda_sent_date` falls in the last 30 days,
scoped to accounts managed by M+B (per [[project-sales-tab-filter]]).
For each opp, exposes whether it has progressed to `nda_signature_or_start_date`.

Powers the side-drawer for the "NDA Sent → Sourcing" card.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from ._now import today_ar


from ._sales_scope import sales_leads as _sales_leads


def _parse_date(value):
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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    win_ini = corte - timedelta(days=29)

    sql = """
        SELECT
          a.client_name,
          o.opp_position_name,
          o.opp_model,
          TO_CHAR(NULLIF(o.nda_sent_date::text, '')::date, 'YYYY-MM-DD')                AS nda_sent_d,
          TO_CHAR(NULLIF(o.nda_signature_or_start_date::text, '')::date, 'YYYY-MM-DD')  AS nda_signed_d,
          TRIM(o.opp_stage)                                                              AS opp_stage,
          CASE
            WHEN NULLIF(o.nda_signature_or_start_date::text, '') IS NULL THEN 'No'
            ELSE 'Sí'
          END                                                                            AS has_nda_signed
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE NULLIF(o.nda_sent_date::text, '') IS NOT NULL
          AND NULLIF(o.nda_sent_date::text, '')::date BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND TRIM(LOWER(a.account_manager)) = ANY(%(sales_leads)s)
        ORDER BY NULLIF(o.nda_sent_date::text, '')::date DESC, a.client_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


DATASET = {
    "key": "nda_to_sourcing_detail",
    "label": "NDA Sent → Sourcing · detalle 30d (M+B)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "nda_sent_d", "label": "NDA sent", "type": "date"},
        {"key": "nda_signed_d", "label": "NDA signed", "type": "date"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "has_nda_signed", "label": "Con NDA signed", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
