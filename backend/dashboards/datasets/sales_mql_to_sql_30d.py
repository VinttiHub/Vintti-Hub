"""Sales · MQL → SQL (ventana de 30d / filtro global, live HubSpot).

Es el primer paso del funnel de Marketing (`mkt_funnel_mql_sql_cw`), pero para Sales.
El universo NO sale de `mql_source` —los Outbound tienen `mql_source='Outbound MQL'`,
que el filtro de marketing deja afuera—, sino de la regla que pasó la owner:

    Sales = Origin = Outbound  O  Conversion Channel = Outbound

La segunda parte trae contactos que entraron por marketing (Paid Media, Website
Organic…) y que Sales terminó convirtiendo con outreach. El valor interno del channel
es `Outbound - Linkedin` (label "Outbound"), por eso se compara con `in`.

COHORTE (decisión de la owner, 2026-09-28): MQL = agendó reunión en la ventana
(`date_of_meeting_scheduled`); de ESOS, cuántos llegaron a SQL. Mismos tiers que el
embudo de Marketing (MQL incluye Closed Lost, SQL no; DQL fuera). A diferencia del
embudo de Marketing, acá no hay doble ancla: el % nunca pasa de 100.

Summary y detalle leen `cohort_rows()`, así el drawer suma igual que la card.
"""
from __future__ import annotations

import os
from datetime import date

from ._periods import window_bounds
from .mkt_mqls_by_origin import _parse_hs_date_ms
from .mkt_funnel_mql_sql_cw import _REACHED_SQL, _REACHED_MQL, _IN_VALUES


def _is_outbound(value) -> bool:
    return "outbound" in str(value or "").strip().lower()


def cohort_rows(filters: dict) -> tuple[list[dict], date, date]:
    """Una fila por MQL de Sales agendado en la ventana."""
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value, _normalize_lead_source,
    )

    ini, fin = window_bounds(filters or {})
    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    mql_anchor = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    contact_map = pm.get("contacts") or {}
    origin_prop = contact_map.get("where_come_from") or "origin"
    channel_prop = contact_map.get("conversion_channel") or "conversion_channel"
    company_prop = contact_map.get("client_name") or "company"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, mql_anchor, origin_prop, channel_prop, company_prop],
    )

    rows = []
    for c in contacts:
        props = c.get("properties") or {}
        ll = str(props.get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_MQL:
            continue
        d = _parse_hs_date_ms(props.get(mql_anchor))
        if d is None or d < ini or d > fin:
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c))
        channel = _first_mapped_value(pm, "conversion_channel", contact=c) or props.get(channel_prop)
        origin_ob = _is_outbound(origin)
        if not (origin_ob or _is_outbound(channel)):
            continue
        name = (
            _first_mapped_value(pm, "client_name", contact=c)
            or " ".join(p for p in [props.get("firstname") or "", props.get("lastname") or ""] if p).strip()
            or props.get("email")
            or "—"
        )
        rows.append({
            "mql_date": d.isoformat(),
            "client_name": str(name),
            "origin": (str(origin or "").strip()) or "(Sin origen)",
            "channel": (str(channel or "").strip()) or "(Sin channel)",
            # "ob" = origin Outbound; "ch" = otro origin, convertido por Sales (channel).
            "bucket": "ob" if origin_ob else "ch",
            "lead_life": props.get(lead_life_property) or "—",
            "reached_sql": ll in _REACHED_SQL,
        })
    return rows, ini, fin


def _pct(num: int, den: int):
    return round(100.0 * num / den, 1) if den else None


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    rows, ini, fin = cohort_rows(filters)
    out = {"ventana_desde": ini.isoformat(), "ventana_hasta": fin.isoformat()}
    for prefix, subset in (
        ("total", rows),
        ("ob", [r for r in rows if r["bucket"] == "ob"]),
        ("ch", [r for r in rows if r["bucket"] == "ch"]),
    ):
        mql = len(subset)
        sql = sum(1 for r in subset if r["reached_sql"])
        out[f"{prefix}_mql"] = mql
        out[f"{prefix}_sql"] = sql
        out[f"{prefix}_pct"] = _pct(sql, mql)
    return [out]


DATASET = {
    "key": "sales_mql_to_sql_30d",
    "label": "Sales · MQL → SQL (Outbound por origin o channel, cohorte, live HubSpot)",
    "dimensions": [
        {"key": "ventana_desde", "label": "Desde", "type": "date"},
        {"key": "ventana_hasta", "label": "Hasta", "type": "date"},
    ],
    "measures": [
        {"key": "total_mql", "label": "MQLs", "type": "number"},
        {"key": "total_sql", "label": "SQLs", "type": "number"},
        {"key": "total_pct", "label": "MQL → SQL %", "type": "percent"},
        {"key": "ob_mql", "label": "MQLs · origin Outbound", "type": "number"},
        {"key": "ob_sql", "label": "SQLs · origin Outbound", "type": "number"},
        {"key": "ob_pct", "label": "MQL → SQL % · origin Outbound", "type": "percent"},
        {"key": "ch_mql", "label": "MQLs · channel Outbound", "type": "number"},
        {"key": "ch_sql", "label": "SQLs · channel Outbound", "type": "number"},
        {"key": "ch_pct", "label": "MQL → SQL % · channel Outbound", "type": "percent"},
    ],
    "default_filters": {},
    "compute": compute,
}
