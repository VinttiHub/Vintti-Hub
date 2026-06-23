"""Marketing · Embudo de conversión MQL (AE) → SQL (AE) → Close Win (live HubSpot).

Por etapa ALCANZADA (el lead_life actual = la etapa máxima a la que llegó), filtrado
por marketing (`mql_source` ∈ {Inbound MQL, Event MQL}). Cada etapa se ancla con su
PROPIA fecha para cuadrar con sus cards: MQL por `date_of_meeting_scheduled` (se
agendó), SQL y CW por `meeting_date___time` (la reunión ocurrió). Normalmente
MQL ≥ SQL ≥ CW; con anclas distintas puede invertirse en bordes de período (raro).
"""
from __future__ import annotations

import os

from .mkt_mqls_by_origin import period_bounds, _parse_hs_date_ms
from ._marketing_scope import is_marketing_mql_source

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
    # Ancla DOBLE (cada etapa con su fecha, para que cuadre con sus cards):
    #   MQL = agendó reunión → `date_of_meeting_scheduled` (cuando se reservó).
    #   SQL / CW = la reunión OCURRIÓ → `meeting_date___time` (fecha real del meeting).
    # Un lead reservado la semana pasada para reunirse esta semana es MQL la pasada y
    # SQL esta. Mismas anclas que mkt_mqls_* (MQL) y mkt_sqls_* (SQL).
    mql_anchor = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()
    sql_anchor = (
        os.environ.get("HUBSPOT_SQL_ANCHOR_PROPERTY")
        or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
        or "meeting_date___time"
    ).strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, mql_anchor, sql_anchor, origin_prop, "mql_source"],
    )

    mql = sqlc = cw = 0
    for c in contacts:
        props = c.get("properties") or {}
        # Marketing-scope = denylist + import sobre origin (sin conversion_channel).
        if not is_marketing_mql_source(props.get("mql_source")):
            continue
        ll = str(props.get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_MQL:
            continue
        d_mql = _parse_hs_date_ms(props.get(mql_anchor))
        d_sql = _parse_hs_date_ms(props.get(sql_anchor))
        in_mql = d_mql is not None and ini <= d_mql <= fin
        in_sql = d_sql is not None and ini <= d_sql <= fin
        if in_mql:
            mql += 1
        if ll in _REACHED_SQL and in_sql:
            sqlc += 1
        if ll in _WON and in_sql:
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
