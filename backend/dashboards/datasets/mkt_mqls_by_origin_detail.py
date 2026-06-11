"""Marketing · detalle MQLs aperturados (live HubSpot).

Una fila por MQL contado en `mkt_mqls_by_origin` (misma ventana, mismo ancla,
misma exclusión de 'outbound'). Muestra ambas fechas (createdate = ancla, y
date_of_meeting_scheduled) + origin + MQL (AE) lost reason, para inspeccionar el
conteo del card.
"""
from __future__ import annotations

import os

from .mkt_mqls_by_origin import period_bounds, _parse_hs_date_ms, SNAPSHOT_MODE


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps,
        _first_mapped_value,
        _normalize_lead_source,
    )

    ini, fin, _ = period_bounds(filters)

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    lead_life_value = (os.environ.get("HUBSPOT_LEAD_LIFE_MQL_VALUE") or "MQL (AE)").strip()
    meeting_property = (os.environ.get("HUBSPOT_MQL_DATE_PROPERTY") or "date_of_meeting_scheduled").strip()
    anchor_property = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "createdate").strip()
    lost_property = (os.environ.get("HUBSPOT_MQL_LOST_REASON_PROPERTY") or "mql_ae_lost_reason").strip()

    client = HubSpotClient()
    property_maps = _resolve_account_property_maps(client)
    origin_prop = (property_maps.get("contacts") or {}).get("where_come_from") or "origin"
    company_prop = (property_maps.get("contacts") or {}).get("client_name") or "company"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value}],
        extra_properties=[
            lead_life_property, "createdate", anchor_property, meeting_property,
            lost_property, origin_prop, company_prop,
        ],
    )

    rows = []
    for c in contacts:
        props = c.get("properties") or {}
        # Filtramos por el ancla (createdate por defecto), mostrando ambas fechas.
        # En SNAPSHOT_MODE no filtramos por fecha ni excluimos outbound (mostrar todo).
        if not SNAPSHOT_MODE:
            anchor_d = _parse_hs_date_ms(props.get(anchor_property))
            if anchor_d is None or anchor_d < ini or anchor_d > fin:
                continue
        origin = _normalize_lead_source(
            _first_mapped_value(property_maps, "where_come_from", contact=c)
        )
        origin = (str(origin or "").strip()) or "(Sin origen)"
        if not SNAPSHOT_MODE and origin.lower() == "outbound":
            continue
        name = (
            _first_mapped_value(property_maps, "client_name", contact=c)
            or " ".join(p for p in [props.get("firstname") or "", props.get("lastname") or ""] if p).strip()
            or props.get("email")
            or "—"
        )
        created_d = _parse_hs_date_ms(props.get("createdate"))
        meeting_d = _parse_hs_date_ms(props.get(meeting_property))
        rows.append({
            "created": created_d.isoformat() if created_d else "",
            "meeting_date": meeting_d.isoformat() if meeting_d else "",
            "client_name": str(name),
            "origin": origin,
            "lost_reason": props.get(lost_property) or "",
        })

    rows.sort(key=lambda r: r["client_name"])
    rows.sort(key=lambda r: r["created"], reverse=True)
    return rows


DATASET = {
    "key": "mkt_mqls_by_origin_detail",
    "label": "Marketing · detalle MQLs (período, live HubSpot)",
    "dimensions": [
        {"key": "created", "label": "Creación (MQL)", "type": "date"},
        {"key": "meeting_date", "label": "Meeting agendado", "type": "date"},
        {"key": "client_name", "label": "Cuenta / contacto", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "lost_reason", "label": "MQL (AE) Lost Reason", "type": "string"},
    ],
    "measures": [],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
