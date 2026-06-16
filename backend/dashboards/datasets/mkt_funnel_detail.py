"""Marketing · Detalle del embudo MQL/SQL/Close Win (live HubSpot).

`stage` (filtro): 'mql' | 'sql' | 'cw'. Lista los contactos (origin de marketing,
createdate en el período) que alcanzaron esa etapa, con su etapa actual (lead_life).
Misma cohorte/tiers que mkt_funnel_mql_sql_cw.
"""
from __future__ import annotations

import os

from .mkt_mqls_by_origin import period_bounds, _parse_hs_date_ms
from .mkt_funnel_mql_sql_cw import _WON, _REACHED_SQL, _REACHED_MQL, _IN_VALUES
from ._marketing_scope import is_marketing_mql_source


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value, _normalize_lead_source,
    )

    stage = str((filters or {}).get("stage") or "mql").strip().lower()
    if stage in ("cw", "close_win", "win"):
        tier = _WON
    elif stage == "sql":
        tier = _REACHED_SQL
    else:
        tier = _REACHED_MQL

    ini, fin, _label = period_bounds(filters or {})
    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    anchor = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "createdate").strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"
    company_prop = (pm.get("contacts") or {}).get("client_name") or "company"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, anchor, origin_prop, "mql_source", company_prop],
    )

    rows = []
    for c in contacts:
        props = c.get("properties") or {}
        d = _parse_hs_date_ms(props.get(anchor))
        if d is None or d < ini or d > fin:
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c))
        # Marketing-scope = denylist + import sobre origin (sin conversion_channel).
        if not is_marketing_mql_source((c.get("properties") or {}).get("mql_source")):
            continue
        origin = (str(origin or "").strip()) or "(Sin origen)"
        ll = str(props.get(lead_life_property) or "").strip().lower()
        if ll not in tier:
            continue
        name = (
            _first_mapped_value(pm, "client_name", contact=c)
            or " ".join(p for p in [props.get("firstname") or "", props.get("lastname") or ""] if p).strip()
            or props.get("email")
            or "—"
        )
        rows.append({
            "created": d.isoformat(),
            "client_name": str(name),
            "origin": origin,
            "lead_life": props.get(lead_life_property) or "—",
        })

    rows.sort(key=lambda r: r["client_name"])
    rows.sort(key=lambda r: r["created"], reverse=True)
    return rows


DATASET = {
    "key": "mkt_funnel_detail",
    "label": "Marketing · Detalle embudo (por etapa, live HubSpot)",
    "dimensions": [
        {"key": "created", "label": "Creación", "type": "date"},
        {"key": "client_name", "label": "Cuenta / contacto", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "lead_life", "label": "Etapa actual", "type": "string"},
    ],
    "measures": [],
    "default_filters": {"stage": "mql", "periodo": "anio"},
    "compute": compute,
}
