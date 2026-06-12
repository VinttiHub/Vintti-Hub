"""Marketing · MQLs totales (métrica de negocio, live HubSpot) con delta vs período anterior.

Equivalente a las cards de `mkt_business_metrics`, pero para MQLs (que viven solo en
HubSpot). Cuenta los MQLs creados (createdate) en el período actual y en el MISMO span
del período anterior (MTD vs MTD, YTD vs YTD, etc.) → % de cambio. Excluye outbound,
igual que el card de MQLs por origin.
"""
from __future__ import annotations

import os

from .mkt_mqls_by_origin import period_bounds, _parse_hs_date_ms
from .mkt_business_metrics import _prev_bounds


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps,
        _first_mapped_value,
        _normalize_lead_source,
    )

    ini, fin, label = period_bounds(filters)
    pini, pfin = _prev_bounds(ini, fin, label)

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    lead_life_value = (os.environ.get("HUBSPOT_LEAD_LIFE_MQL_VALUE") or "MQL (AE)").strip()
    anchor_property = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "createdate").strip()

    client = HubSpotClient()
    property_maps = _resolve_account_property_maps(client)
    origin_prop = (property_maps.get("contacts") or {}).get("where_come_from") or "origin"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "EQ", "value": lead_life_value}],
        extra_properties=[lead_life_property, anchor_property, origin_prop],
    )

    cur = prev = 0
    for c in contacts:
        d = _parse_hs_date_ms((c.get("properties") or {}).get(anchor_property))
        if d is None:
            continue
        origin = _normalize_lead_source(
            _first_mapped_value(property_maps, "where_come_from", contact=c)
        )
        if str(origin or "").strip().lower() in ("outbound", "connected inbox", "referral"):  # espejo del card de MQLs
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
