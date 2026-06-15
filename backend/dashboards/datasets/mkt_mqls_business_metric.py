"""Marketing · MQLs totales (métrica de negocio, live HubSpot) con delta vs período anterior.

Definición (según el owner de HubSpot):
  - MQL (AE) = el contacto AGENDÓ una reunión. La fecha que decide el mes es
    `date_of_meeting_scheduled`.
  - Es COHORTE POR ETAPA ALCANZADA: una vez que llegó a MQL (AE) cuenta para su
    mes, aunque hoy ya sea SQL / Active Client / Closed Lost. Por eso se filtra
    por `lead_life` ∈ {las etapas MQL(AE) o más allá}, no solo "MQL (AE)" actual.
  - Excluye DQL (descalificados). [Nota: el tratamiento fino de Closed Lost que
    nunca llegó a SQL queda pendiente de reconciliar con un export — por ahora se
    cuentan los Closed Lost que alcanzaron MQL(AE), que es lo más cercano.]
  - Marketing-scope: excluye outbound / connected inbox / referral.

Compara contra el MISMO span del período anterior (MTD vs MTD, etc.) → % de cambio.
"""
from __future__ import annotations

import os

from .mkt_mqls_by_origin import period_bounds, _parse_hs_date_ms
from .mkt_business_metrics import _prev_bounds
from ._marketing_scope import is_inbound_lead

# Etapa ALCANZADA = MQL (AE) o más allá (excluye DQL y los MQL pre-meeting como
# MQL (BDRs) / MQL (MKT) TOFU-MOFU-BOFU, que NO agendaron reunión).
_WON = {"active client", "inactive client"}
_REACHED_MQL = _WON | {"sql (ae)", "closed lost", "mql (ae)"}
# Valores exactos de lead_life para acotar el search en HubSpot.
_IN_VALUES = ["MQL (AE)", "SQL (AE)", "Active Client", "Inactive Client", "Closed Lost"]


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps,
        _first_mapped_value,
    )

    ini, fin, label = period_bounds(filters)
    pini, pfin = _prev_bounds(ini, fin, label)

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    # Ancla = fecha en que agendaron la reunión (= se volvieron MQL AE).
    anchor_property = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()

    client = HubSpotClient()
    property_maps = _resolve_account_property_maps(client)
    origin_prop = (property_maps.get("contacts") or {}).get("where_come_from") or "origin"
    channel_prop = (property_maps.get("contacts") or {}).get("conversion_channel") or "conversion_channel"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, anchor_property, origin_prop, channel_prop],
    )

    cur = prev = 0
    for c in contacts:
        props = c.get("properties") or {}
        # Cohorte por etapa alcanzada: tiene que haber llegado a MQL (AE) o más allá.
        ll = str(props.get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_MQL:
            continue
        d = _parse_hs_date_ms(props.get(anchor_property))
        if d is None:
            continue
        # Marketing-scope = Inbound en AMBAS (MQL Source origin + Booking Source channel).
        if not is_inbound_lead(
            _first_mapped_value(property_maps, "where_come_from", contact=c),
            _first_mapped_value(property_maps, "conversion_channel", contact=c),
        ):
            continue
        if ini <= d <= fin:
            cur += 1
        elif pini <= d <= pfin:
            prev += 1

    delta = round((cur - prev) * 100.0 / prev) if prev > 0 else None
    return [{"mqls": cur, "mqls_delta": delta, "period_label": label}]


DATASET = {
    "key": "mkt_mqls_business_metric",
    "label": "Marketing · MQLs totales (métrica de negocio, live HubSpot)",
    "dimensions": [
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "mqls", "label": "MQLs totales", "type": "number"},
        {"key": "mqls_delta", "label": "Δ MQLs", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
