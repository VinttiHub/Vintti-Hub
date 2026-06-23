"""Marketing · SQLs aperturados por origin — ranking por período.

SQL = contacto que ALCANZÓ la etapa SQL (AE) o más (active/inactive client) en
HubSpot, anclado por `meeting_date___time` (la fecha REAL del meeting, = cuando se
volvió SQL; NO la de agendamiento, que es el ancla del MQL). Misma definición que el
card de SQLs (mkt_business_metrics) — ya NO es
account.creation_date sobre Postgres. Marketing-scope = Inbound en AMBAS dimensiones
(origin/MQL Source + conversion_channel/Booking Source). Segmentado por origin.
Período (a la fecha): semana / mes / q / anio. Devuelve una fila por origin con
count, share_pct y total.

NOTA: `period_bounds` y `_parse_date` se mantienen acá porque los importan
mkt_business_metrics y mkt_sqls_by_origin_detail.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

from ._marketing_scope import is_marketing_mql_source

# SQL = etapa ALCANZADA SQL (AE) o más (idéntico a mkt_business_metrics / embudo).
_WON = {"active client", "inactive client"}
_REACHED_SQL = _WON | {"sql (ae)"}
_IN_VALUES = ["MQL (AE)", "SQL (AE)", "Active Client", "Inactive Client", "Closed Lost"]


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


def period_bounds(filters: dict) -> tuple[date, date, str]:
    """(ini, fin=corte, label) para el período en curso a la fecha."""
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or datetime.utcnow().date())
    p = str(filters.get("periodo") or filters.get("period") or "mes").strip().lower()
    if p in ("semana", "week", "w"):
        return corte - timedelta(days=corte.weekday()), corte, "Semana"
    if p in ("q", "trimestre", "quarter"):
        q_month = ((corte.month - 1) // 3) * 3 + 1
        return date(corte.year, q_month, 1), corte, "Trimestre"
    if p in ("anio", "año", "year", "anual", "ytd"):
        return date(corte.year, 1, 1), corte, "Año"
    return date(corte.year, corte.month, 1), corte, "Mes"


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    # Imports lazy: evita acoplar el registro de datasets a las rutas/HubSpot.
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps,
        _first_mapped_value,
        _normalize_lead_source,
    )
    from .mkt_mqls_by_origin import _parse_hs_date_ms, SNAPSHOT_MODE

    ini, fin, label = period_bounds(filters)

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    # Ancla SQL = fecha REAL en que ocurrió la reunión (`meeting_date___time`), NO la
    # fecha en que se agendó/reservó (`date_of_meeting_scheduled`, que es el ancla del
    # MQL). Becoming SQL = la reunión efectivamente sucedió: un lead que reservó la
    # semana pasada para reunirse esta semana es MQL la semana pasada pero SQL esta
    # semana (caso Wesley vs Ameel, confirmado con el equipo).
    anchor_property = (
        os.environ.get("HUBSPOT_SQL_ANCHOR_PROPERTY")
        or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
        or "meeting_date___time"
    ).strip()

    client = HubSpotClient()
    property_maps = _resolve_account_property_maps(client)
    origin_prop = (property_maps.get("contacts") or {}).get("where_come_from") or "origin"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, anchor_property, origin_prop, "mql_source"],
    )

    counts: dict[str, int] = {}
    for c in contacts:
        # Tiene que haber ALCANZADO SQL (AE) o más allá.
        ll = str((c.get("properties") or {}).get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_SQL:
            continue
        if not SNAPSHOT_MODE:
            d = _parse_hs_date_ms((c.get("properties") or {}).get(anchor_property))
            if d is None or d < ini or d > fin:
                continue
        origin = _normalize_lead_source(
            _first_mapped_value(property_maps, "where_come_from", contact=c)
        )
        # Marketing-scope = denylist + import sobre origin (sin conversion_channel).
        # El desglose se sigue agrupando por origin (MQL Source).
        if not SNAPSHOT_MODE and not is_marketing_mql_source((c.get("properties") or {}).get("mql_source")):
            continue
        origin = (str(origin or "").strip()) or "(Sin origen)"
        counts[origin] = counts.get(origin, 0) + 1

    total = sum(counts.values())
    label = "Snapshot (todos)" if SNAPSHOT_MODE else label
    rows = [
        {
            "origin": origin,
            "count": n,
            "share_pct": round(100.0 * n / total, 1) if total else 0.0,
            "total": total,
            "period_label": label,
        }
        for origin, n in counts.items()
    ]
    rows.sort(key=lambda r: (-r["count"], r["origin"]))
    return rows


DATASET = {
    "key": "mkt_sqls_by_origin",
    "label": "Marketing · SQLs por origin (live HubSpot, período)",
    "dimensions": [
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "count", "label": "SQLs", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Total SQLs", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
