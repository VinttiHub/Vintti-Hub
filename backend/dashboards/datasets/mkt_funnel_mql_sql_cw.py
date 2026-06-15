"""Marketing · Embudo de conversión MQL (AE) → SQL (AE) → Close Win (live HubSpot).

Cohorte por etapa ALCANZADA: el lead_life actual de un contacto = la etapa máxima
a la que llegó. De los contactos (origin de marketing, createdate en el período) que
llegaron a MQL (AE), cuántos llegaron a SQL (AE) y cuántos a Active Client (won).
Baja bien: MQL ≥ SQL ≥ CW. Excluye outbound/connected inbox/referral.
"""
from __future__ import annotations

import os

from .mkt_mqls_by_origin import period_bounds, _parse_hs_date_ms
from ._marketing_scope import is_inbound_lead

# DQL (descalificados) se EXCLUYE del embudo (no son conversiones reales).
_WON = {"active client", "inactive client"}
# SQL = llegó a SQL y calificó — NO cuenta los Closed Lost (los perdidos no son SQL).
_REACHED_SQL = _WON | {"sql (ae)"}
# MQL = agendó reunión: SÍ incluye los que después se perdieron (Closed Lost) o avanzaron.
_REACHED_MQL = _REACHED_SQL | {"mql (ae)", "closed lost"}
# Valores exactos de lead_life que cuentan en el embudo — para acotar el search.
_IN_VALUES = ["MQL (AE)", "SQL (AE)", "Active Client", "Inactive Client", "Closed Lost"]


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value,
    )

    ini, fin, label = period_bounds(filters)
    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    # MQL = agendó reunión → ancla `date_of_meeting_scheduled` (mismo criterio que
    # los cards de MQL: mkt_mqls_by_origin / mkt_mqls_business_metric).
    anchor = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"
    channel_prop = (pm.get("contacts") or {}).get("conversion_channel") or "conversion_channel"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, anchor, origin_prop, channel_prop],
    )

    mql = sqlc = cw = 0
    for c in contacts:
        props = c.get("properties") or {}
        d = _parse_hs_date_ms(props.get(anchor))
        if d is None or d < ini or d > fin:
            continue
        # Marketing-scope = Inbound en AMBAS (MQL Source origin + Booking Source channel).
        if not is_inbound_lead(
            _first_mapped_value(pm, "where_come_from", contact=c),
            _first_mapped_value(pm, "conversion_channel", contact=c),
        ):
            continue
        ll = str(props.get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_MQL:
            continue
        mql += 1
        if ll in _REACHED_SQL:
            sqlc += 1
        if ll in _WON:
            cw += 1

    return [{
        "mql": mql,
        "sql": sqlc,
        "close_win": cw,
        "sql_pct": round(100.0 * sqlc / mql, 1) if mql else None,
        "cw_pct": round(100.0 * cw / sqlc, 1) if sqlc else None,
        "cw_of_mql_pct": round(100.0 * cw / mql, 1) if mql else None,
        "period_label": label,
    }]


DATASET = {
    "key": "mkt_funnel_mql_sql_cw",
    "label": "Marketing · Embudo MQL → SQL → Close Win (live HubSpot)",
    "dimensions": [
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "mql", "label": "MQL (AE)", "type": "number"},
        {"key": "sql", "label": "SQL (AE)", "type": "number"},
        {"key": "close_win", "label": "Close Win", "type": "number"},
        {"key": "sql_pct", "label": "MQL→SQL %", "type": "percent"},
        {"key": "cw_pct", "label": "SQL→CW %", "type": "percent"},
        {"key": "cw_of_mql_pct", "label": "MQL→CW %", "type": "percent"},
    ],
    "default_filters": {"periodo": "anio"},
    "compute": compute,
}
