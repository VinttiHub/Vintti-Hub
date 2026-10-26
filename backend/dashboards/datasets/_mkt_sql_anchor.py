"""Cuándo un contacto se volvió SQL: el ancla de las cards de SQL del tab Marketing.

Hasta el 2026-10-05 el tab Marketing anclaba el SQL en `meeting_date___time` del
contacto (la reunión ocurrió). Desde ese día HubSpot tiene un stage "SQL" en los dos
pipelines de deals y una "SQL Date (Deal)". Pedido de la owner (2026-10-26): usarla
**sólo de ahí en adelante**, así no cambia ningún número histórico. Es la misma regla
que el tab Sales (`_sql_anchor.py` sobre `account`, `_sql_hubspot.py` sobre HubSpot):

    1. Meeting Date & Time anterior al corte -> esa fecha; SQL = Lead Life SQL (AE),
       Active o Inactive Client (la definición de siempre: historia congelada).
    2. si no, algún deal suyo tiene SQL Date desde el corte -> esa fecha (la mínima),
       y es SQL con cualquier Lead Life (también Closed Lost: decisión de la owner,
       un SQL que se perdió antes del Deep Dive sigue siendo un SQL, igual que en Sales).
    3. si no -> Meeting Date & Time, con la definición de siempre.

La SQL Date sale de `sql_date_from_deal` ("SQL Date (Deal)" o la entrada al stage SQL),
que nunca devuelve una fecha anterior al corte. Si tocás el corte, tocalo en
`_sql_anchor.py` y en `SQL_DATE_CUTOVER` de utils/hubspot_opportunities.py.

Los deals con SQL Date desde el corte son pocos: una sola pasada por HubSpot (cacheada
5 min, sin rango) alcanza para todas las cards del tab.
"""
from __future__ import annotations

from datetime import date

from ._sql_anchor import SQL_CUTOVER
from ._sql_hubspot import EXCLUDED_DEAL_IDS, _associations, _ms
from .mkt_funnel_mql_sql_cw import _REACHED_SQL
from .mkt_mqls_by_origin import _parse_hs_date_ms

try:
    from backend.utils import shared_cache  # type: ignore
except ImportError:
    from utils import shared_cache  # type: ignore

_CUTOVER = date.fromisoformat(SQL_CUTOVER)
_CACHE_TTL_SECONDS = 300
# Bump si cambia la forma del dict: el cache vive en Postgres y sobrevive deploys.
_CACHE_KEY = "mkt_deal_sql_dates__v1"


def _fetch_deal_sql_dates(client) -> dict[str, str | None]:
    from utils import hubspot_opportunities as ho

    pipeline_map = ho.resolve_pipeline_stage_map(client)
    opp_property_map = ho.resolve_opportunity_property_map(client)
    sql_date_prop = opp_property_map.get("sql_date") or "sql_date_deal"
    markers = [sql_date_prop]
    for entry in (pipeline_map.get("by_pipeline_id") or {}).values():
        sql_prop = (entry.get("date_property_by_key") or {}).get("sql")
        if sql_prop:
            markers.append(sql_prop)
    markers = list(dict.fromkeys(markers))

    since_ms = str(_ms(_CUTOVER))
    deals: dict[str, dict] = {}
    for prop in markers:
        for d in client.search_deals(
            [{"propertyName": prop, "operator": "GTE", "value": since_ms}],
            extra_properties=markers,
        ):
            deals[str(d.get("id"))] = d
    for deal_id in EXCLUDED_DEAL_IDS:
        deals.pop(deal_id, None)

    out: dict[str, str | None] = {}
    for deal_id, contact_ids in _associations(client, "deals", "contacts", sorted(deals)).items():
        d = deals[deal_id]
        d_sql = ho.sql_date_from_deal(
            pipeline_map, (d.get("properties") or {}).get("pipeline"),
            d.get("properties") or {}, opp_property_map, _parse_hs_date_ms,
        )
        for cid in contact_ids:
            prev = out.get(cid)
            if cid not in out or (d_sql is not None and (prev is None or d_sql.isoformat() < prev)):
                out[cid] = d_sql.isoformat() if d_sql else None
    return out


def deal_sql_dates(client) -> dict[str, date | None]:
    """{contact_id: SQL Date mínima de sus deals} para los contactos con algún deal
    calificado SQL desde el corte. `None` = el deal pasó por SQL pero sin fecha usable
    (cuenta como SQL; la fecha cae al meeting)."""
    hit, cached = shared_cache.get(_CACHE_KEY)
    if not hit:
        cached = _fetch_deal_sql_dates(client)
        shared_cache.set(_CACHE_KEY, cached, _CACHE_TTL_SECONDS)
    return {cid: (date.fromisoformat(v) if v else None) for cid, v in cached.items()}


def sql_date_of(contact: dict, deal_dates: dict, meeting_prop: str, lead_life_prop: str) -> date | None:
    """Fecha en que el contacto se volvió SQL, o None si no es SQL (o no tiene fecha)."""
    props = contact.get("properties") or {}
    meeting = _parse_hs_date_ms(props.get(meeting_prop))
    ll = str(props.get(lead_life_prop) or "").strip().lower()
    if meeting is not None and meeting < _CUTOVER:
        return meeting if ll in _REACHED_SQL else None
    cid = str(contact.get("id") or "").strip()
    if cid in deal_dates:
        return deal_dates[cid] or meeting
    return meeting if ll in _REACHED_SQL else None
