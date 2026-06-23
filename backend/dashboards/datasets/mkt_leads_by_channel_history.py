"""Marketing · MQLs/SQLs por canal EN EL TIEMPO (multi-línea, una línea por canal).

`lead_type` (filtro) elige la métrica, AMBAS live desde HubSpot con la misma
definición que los cards/detalles: 'mql' = etapa alcanzada MQL(AE)+ (ancla
`date_of_meeting_scheduled`, cuando se agendó), 'sql' = etapa alcanzada SQL(AE)+
(ancla `meeting_date___time`, cuando ocurrió el meeting); filtro `mql_source` ∈
{Inbound MQL, Event MQL}. La periodicidad define la granularidad del eje X DENTRO
del período seleccionado:
  semana → días · mes → semanas · q/año → meses
Devuelve la grilla completa (buckets × canales) con value=0 donde no hay, para que
las líneas sean continuas.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from .mkt_sqls_by_origin import period_bounds
from ._marketing_scope import is_marketing_mql_source

_MES_ES = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


def _gran(periodo) -> str:
    p = str(periodo or 'mes').strip().lower()
    if p in ('semana', 'week', 'w'):
        return 'day'
    if p in ('q', 'trimestre', 'quarter', 'anio', 'año', 'year', 'anual', 'ytd'):
        return 'month'
    return 'week'  # mes → semanal


def _trunc(d: date, unit: str) -> date:
    if unit == 'day':
        return d
    if unit == 'week':
        return d - timedelta(days=d.weekday())  # lunes (igual que DATE_TRUNC('week'))
    return date(d.year, d.month, 1)  # month


def _next(d: date, unit: str) -> date:
    if unit == 'day':
        return d + timedelta(days=1)
    if unit == 'week':
        return d + timedelta(days=7)
    return date(d.year + (1 if d.month == 12 else 0), 1 if d.month == 12 else d.month + 1, 1)


def _label(d: date, unit: str) -> str:
    if unit == 'month':
        return _MES_ES[d.month]
    return f"{d.day:02d}/{d.month:02d}"


def _spine(ini: date, fin: date, unit: str) -> list[date]:
    out, b = [], _trunc(ini, unit)
    while b <= fin:
        out.append(b)
        b = _next(b, unit)
    return out


def _sql_counts(ini: date, fin: date, unit: str):
    # SQL = etapa ALCANZADA SQL (AE) en HubSpot, ancla `meeting_date___time` (fecha REAL
    # del meeting = cuando se volvió SQL; NO la de agendamiento) — MISMA definición que el
    # card de SQLs y el detalle.
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value, _normalize_lead_source,
    )
    from .mkt_mqls_by_origin import _parse_hs_date_ms, _IN_VALUES
    from .mkt_funnel_mql_sql_cw import _REACHED_SQL

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    anchor = (
        os.environ.get("HUBSPOT_SQL_ANCHOR_PROPERTY")
        or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
        or "meeting_date___time"
    ).strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"
    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, anchor, origin_prop, "mql_source"],
    )
    counts, totals = {}, {}
    for c in contacts:
        p = c.get("properties") or {}
        if str(p.get(lead_life_property) or "").strip().lower() not in _REACHED_SQL:
            continue
        d = _parse_hs_date_ms(p.get(anchor))
        if d is None or d < ini or d > fin:
            continue
        if not is_marketing_mql_source(p.get("mql_source")):
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c))
        origin = (str(origin or "").strip()) or "(Sin origen)"
        b = _trunc(d, unit)
        counts[(b, origin)] = counts.get((b, origin), 0) + 1
        totals[origin] = totals.get(origin, 0) + 1
    return counts, sorted(totals, key=lambda o: -totals[o])


def _mql_counts(ini: date, fin: date, unit: str):
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value, _normalize_lead_source,
    )
    from .mkt_mqls_by_origin import _parse_hs_date_ms, _REACHED_MQL, _IN_VALUES

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    # MQL = agendó reunión → ancla `date_of_meeting_scheduled`, etapa ALCANZADA
    # MQL(AE)+ (mismo criterio que mkt_mqls_by_origin).
    anchor = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"
    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, anchor, origin_prop, "mql_source"],
    )
    counts, totals = {}, {}
    for c in contacts:
        if str((c.get("properties") or {}).get(lead_life_property) or "").strip().lower() not in _REACHED_MQL:
            continue
        d = _parse_hs_date_ms((c.get("properties") or {}).get(anchor))
        if d is None or d < ini or d > fin:
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c))
        # Filtro de marketing OFICIAL del equipo: mql_source ∈ {Inbound MQL, Event MQL}.
        if not is_marketing_mql_source((c.get("properties") or {}).get("mql_source")):
            continue
        origin = (str(origin or "").strip()) or "(Sin origen)"
        b = _trunc(d, unit)
        counts[(b, origin)] = counts.get((b, origin), 0) + 1
        totals[origin] = totals.get(origin, 0) + 1
    return counts, sorted(totals, key=lambda o: -totals[o])


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    f = filters or {}
    lead_type = str(f.get('lead_type') or f.get('leadtype') or 'sql').strip().lower()
    ini, fin, label = period_bounds(f)
    unit = _gran(f.get('periodo'))
    spine = _spine(ini, fin, unit)

    if lead_type in ('mql', 'mqls'):
        counts, origins = _mql_counts(ini, fin, unit)
    else:
        counts, origins = _sql_counts(ini, fin, unit)

    rows = []
    for o in origins:
        for b in spine:
            rows.append({
                "bucket_start": b.isoformat(),
                "bucket_label": _label(b, unit),
                "origin": o,
                "value": counts.get((b, o), 0),
                "period_label": label,
                "lead_type": lead_type,
            })
    return rows


DATASET = {
    "key": "mkt_leads_by_channel_history",
    "label": "Marketing · MQLs/SQLs por canal en el tiempo (multi-línea)",
    "dimensions": [
        {"key": "bucket_start", "label": "Bucket", "type": "date"},
        {"key": "bucket_label", "label": "Etiqueta", "type": "string"},
        {"key": "origin", "label": "Canal", "type": "string"},
    ],
    "measures": [{"key": "value", "label": "Cantidad", "type": "number"}],
    "default_filters": {"periodo": "anio", "lead_type": "sql"},
    "compute": compute,
}
