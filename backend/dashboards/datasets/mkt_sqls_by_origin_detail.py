"""Marketing · detalle SQLs (live HubSpot).

Una fila por SQL contado en el card de Métricas de Negocio: contactos cuyo lead_life
ALCANZÓ la etapa SQL (AE) o más (active/inactive client), anclados por
`meeting_date___time` (la fecha REAL del meeting = cuando se volvió SQL) en el
período. Misma definición y mismas bounds que `mkt_business_metrics` (sqls) y
`mkt_sqls_by_origin`, para que el detalle cuadre con el conteo.
"""
from __future__ import annotations

import os

from .mkt_sqls_by_origin import period_bounds
from .mkt_mqls_by_origin import _parse_hs_date_ms, SNAPSHOT_MODE, _IN_VALUES
from ._marketing_scope import is_marketing_mql_source, is_non_marketing_origin

# SQL = etapa ALCANZADA (idéntico a mkt_funnel_mql_sql_cw / mkt_business_metrics).
_REACHED_SQL = {"active client", "inactive client", "sql (ae)"}


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps,
        _first_mapped_value,
        _normalize_lead_source,
    )

    ini, fin, _ = period_bounds(filters)

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    # Ancla SQL = fecha REAL del meeting (`meeting_date___time`), no la de agendamiento.
    # Ver mkt_sqls_by_origin: becoming SQL = la reunión ocurrió. La misma propiedad se
    # muestra como "Meeting" para que el detalle cuadre con el conteo.
    anchor_property = (
        os.environ.get("HUBSPOT_SQL_ANCHOR_PROPERTY")
        or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
        or "meeting_date___time"
    ).strip()
    meeting_property = anchor_property

    client = HubSpotClient()
    property_maps = _resolve_account_property_maps(client)
    origin_prop = (property_maps.get("contacts") or {}).get("where_come_from") or "origin"
    company_prop = (property_maps.get("contacts") or {}).get("client_name") or "company"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[
            lead_life_property, "createdate", anchor_property,
            origin_prop, "mql_source", company_prop,
        ],
    )

    rows = []
    for c in contacts:
        props = c.get("properties") or {}
        # Cohorte por etapa alcanzada: tiene que haber llegado a SQL (AE) o más allá.
        ll = str(props.get(lead_life_property) or "").strip()
        if ll.lower() not in _REACHED_SQL:
            continue
        # Filtramos por el ancla (date_of_meeting_scheduled). En SNAPSHOT_MODE no
        # filtramos por fecha ni excluimos outbound (mostrar todo).
        if not SNAPSHOT_MODE:
            anchor_d = _parse_hs_date_ms(props.get(anchor_property))
            if anchor_d is None or anchor_d < ini or anchor_d > fin:
                continue
        origin = _normalize_lead_source(
            _first_mapped_value(property_maps, "where_come_from", contact=c)
        )
        # Marketing-scope = denylist + import sobre origin (sin conversion_channel).
        if not SNAPSHOT_MODE and not is_marketing_mql_source((c.get("properties") or {}).get("mql_source")):
            continue
        # Excluir Outbound (= Sales), aunque el mql_source diga inbound.
        if not SNAPSHOT_MODE and is_non_marketing_origin(origin):
            continue
        origin = (str(origin or "").strip()) or "(Sin origen)"
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
            "lead_life": ll,
        })

    rows.sort(key=lambda r: r["client_name"])
    rows.sort(key=lambda r: r["meeting_date"], reverse=True)
    return rows


DATASET = {
    "key": "mkt_sqls_by_origin_detail",
    "label": "Marketing · detalle SQLs (período, live HubSpot)",
    "dimensions": [
        {"key": "meeting_date", "label": "Meeting (fecha real)", "type": "date"},
        {"key": "created", "label": "Creación (SQL)", "type": "date"},
        {"key": "client_name", "label": "Cuenta / contacto", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "lead_life", "label": "Etapa (lead_life)", "type": "string"},
    ],
    "measures": [],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
