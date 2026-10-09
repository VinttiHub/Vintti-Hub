"""SQLs de HubSpot para SQL → Deep Dive (tab Sales), una fila por contacto.

Misma fuente que MQL → SQL (`sales_mql_to_sql_30d`): la propiedad Lead Life de los
contactos. Antes esta card leía cuentas del hub con `sql_meeting_date`, y eso no
servía por dos razones (medido 2026-10-08):
  - `sql_meeting_date` la escribe `sync_mariano_sql_contacts`, que es manual, sólo de
    Mariano y sólo de los que siguen en 'SQL (AE)': no corría desde el 11-sep. La
    card daba 9 SQLs con 21 al lado.
  - Hasta el 2026-10-05 el hub creaba la cuenta recién en Deep Dive, así que todo SQL
    del hub "avanzaba": la tasa no podía dar menos de 100%.

Qué es SQL:
  - Lead Life ∈ {SQL (AE), Active Client, Inactive Client} — igual que MQL → SQL; o
  - algún deal suyo pasó por el stage SQL de HubSpot (existe desde el 2026-10-05) o
    tiene "SQL Date (Deal)" desde el corte. Esto suma los SQL que después se
    perdieron antes del Deep Dive (quedan con Lead Life Closed Lost): sin esto la tasa
    sólo podría bajar si alguien se queda parado, nunca por un SQL perdido.
  Ojo: antes del corte HubSpot marcaba SQL (AE) recién con el deal en Deep Dive, así que
  la historia da ~100% y no hay de dónde sacar los SQL perdidos de entonces.

Fecha del SQL: mismo criterio que `_sql_anchor.py` (si tocás el corte, tocá los dos):
  Meeting Date & Time anterior al corte -> esa (historia congelada); si no, la SQL Date
  del deal (`sql_date_from_deal`: "SQL Date (Deal)" o la entrada al stage SQL, nunca
  anterior al corte); si no, Meeting Date & Time.

Llegó a Deep Dive: algún deal tiene fecha de entrada a Deep Dive, o hoy está en un stage
igual o posterior (un deal que saltó directo a NDA); o, de respaldo, el hub tiene una
opp con `deep_dive_date` para ese deal o para una cuenta con el mismo nombre (deals que
HubSpot dejó atrás, ver `_hub_deep_dives`).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

from ._periods import prev_window_bounds, window_bounds
from ._sql_anchor import SQL_CUTOVER
from .mkt_mqls_by_origin import _parse_hs_date_ms
from .mkt_funnel_mql_sql_cw import _REACHED_SQL, _IN_VALUES

try:
    from backend.utils import shared_cache  # type: ignore
except ImportError:
    from utils import shared_cache  # type: ignore

_CUTOVER = date.fromisoformat(SQL_CUTOVER)
_CACHE_TTL_SECONDS = 300
# Bump si cambia la forma de las filas: el cache vive en Postgres y sobrevive deploys.
_CACHE_VERSION = 3


# Deals de prueba que no son un SQL. "prueba mia" (2026-10-05) está atado al contacto
# personal de Mia y pasó por el stage SQL: sin esto contaba como SQL perdido.
EXCLUDED_DEAL_IDS = {"65578237193"}


def _ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _associations(client, from_type: str, to_type: str, ids: list[str]) -> dict[str, list[str]]:
    """{id: [ids asociados]} en lotes de 100 (API v4): una llamada por cada 100, no
    una por contacto/deal."""
    out: dict[str, list[str]] = {i: [] for i in ids}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        payload = client._request(
            "POST",
            f"/crm/v4/associations/{from_type}/{to_type}/batch/read",
            json={"inputs": [{"id": x} for x in chunk]},
        ) or {}
        for res in payload.get("results") or []:
            src = str((res.get("from") or {}).get("id"))
            out[src] = [str(t.get("toObjectId")) for t in res.get("to") or []]
    return out


def _norm(name) -> str:
    return " ".join(str(name or "").lower().split())


def _hub_deep_dives() -> tuple[set[str], set[str]]:
    """Cuentas (nombre normalizado) y deals con alguna opp con Deep Dive en el hub.

    Respaldo para los deals que HubSpot dejó atrás: en agosto de 2026 Huddleston,
    Skyler, HomeTeam y Zen Investing tenían el Deep Dive cargado a mano en el hub y
    el deal parado en Intro Call, sin `hubspot_deal_id`. Por eso va también por nombre.
    """
    from db import get_connection

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT LOWER(a.client_name), NULLIF(o.hubspot_deal_id, '')
            FROM opportunity o
            JOIN account a ON a.account_id = o.account_id
            WHERE NULLIF(o.deep_dive_date::text, '') IS NOT NULL
            """
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return {_norm(n) for n, _ in rows if n}, {str(d) for _, d in rows if d}


def channel_of(origin: str) -> str:
    o = (origin or "").strip().lower()
    if o == "outbound":
        return "sales"
    if o == "referral":
        return "referrals"
    return "marketing"


def _fetch_rows(ini: date, fin: date) -> list[dict]:
    from utils.hubspot import HubSpotClient
    from utils import hubspot_opportunities as ho
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value, _normalize_lead_source,
    )

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    meeting_prop = (
        os.environ.get("HUBSPOT_SQL_ANCHOR_PROPERTY")
        or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
        or "meeting_date___time"
    ).strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    contact_map = pm.get("contacts") or {}
    origin_prop = contact_map.get("where_come_from") or "origin"
    company_prop = contact_map.get("client_name") or "company"
    pipeline_map = ho.resolve_pipeline_stage_map(client)
    opp_property_map = ho.resolve_opportunity_property_map(client)

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, meeting_prop, origin_prop, company_prop],
    )
    by_id = {str(c.get("id")): c for c in contacts}

    # A) Lead Life SQL+ con la reunión en el rango. Si después del corte el deal trae
    #    otra SQL Date, la fila se re-ancla abajo; los que tienen SQL Date en el rango
    #    pero la reunión afuera entran por B.
    candidates: set[str] = set()
    for cid, c in by_id.items():
        p = c.get("properties") or {}
        if str(p.get(lead_life_property) or "").strip().lower() not in _REACHED_SQL:
            continue
        meeting = _parse_hs_date_ms(p.get(meeting_prop))
        if meeting is not None and ini <= meeting <= fin:
            candidates.add(cid)

    # B) Deals con SQL Date / entrada al stage SQL desde el inicio del rango: suman los
    #    SQL que se perdieron antes del Deep Dive (Lead Life Closed Lost).
    sql_date_prop = opp_property_map.get("sql_date") or "sql_date_deal"
    deal_props = [sql_date_prop]
    markers = [sql_date_prop]
    for entry in (pipeline_map.get("by_pipeline_id") or {}).values():
        by_key = entry.get("date_property_by_key") or {}
        deal_props += [v for v in by_key.values() if v]
        if by_key.get("sql"):
            markers.append(by_key["sql"])
    sql_deal_ids: set[str] = set()
    if fin >= _CUTOVER:
        since_ms = str(_ms(max(ini, _CUTOVER)))
        for prop in dict.fromkeys(markers):
            for d in client.search_deals([{"propertyName": prop, "operator": "GTE", "value": since_ms}]):
                sql_deal_ids.add(str(d.get("id")))
        sql_deal_ids -= EXCLUDED_DEAL_IDS
        for ids in _associations(client, "deals", "contacts", sorted(sql_deal_ids)).values():
            candidates.update(ids)

    deals_of = _associations(client, "contacts", "deals", sorted(candidates))
    all_deal_ids = sorted({d for ids in deals_of.values() for d in ids} - EXCLUDED_DEAL_IDS)
    deals: dict[str, dict] = {}
    for i in range(0, len(all_deal_ids), 100):
        chunk = all_deal_ids[i:i + 100]
        for d in client.search_deals(
            [{"propertyName": "hs_object_id", "operator": "IN", "values": chunk}],
            extra_properties=deal_props,
        ):
            deals[str(d.get("id"))] = d.get("properties") or {}
    for cid in candidates - set(by_id):
        by_id[cid] = client.get_contact(
            cid, extra_properties=[lead_life_property, meeting_prop, origin_prop, company_prop],
        )

    hub_dd_names, hub_dd_deals = _hub_deep_dives()
    dd_rank = ho.HUBSPOT_STAGE_RANK["deep_dive"]
    rows = []
    for cid in candidates:
        c = by_id.get(cid) or {}
        p = c.get("properties") or {}
        email = str(p.get("email") or "").strip().lower()
        if email.endswith("@vintti.com"):
            continue
        ll = str(p.get(lead_life_property) or "").strip().lower()
        sql_from_deal = None
        reached_dd = False
        deal_is_sql = False
        for deal_id in deals_of.get(cid) or []:
            dp = deals.get(deal_id)
            if dp is None:
                continue
            pipeline_id, stage_id = dp.get("pipeline"), dp.get("dealstage")
            d_sql = ho.sql_date_from_deal(pipeline_map, pipeline_id, dp, opp_property_map, _parse_hs_date_ms)
            if d_sql is not None:
                deal_is_sql = True
                sql_from_deal = d_sql if sql_from_deal is None else min(sql_from_deal, d_sql)
            if deal_id in sql_deal_ids:
                deal_is_sql = True
            dates = ho.stage_dates_from_deal(pipeline_map, pipeline_id, dp, _parse_hs_date_ms)
            key = ho.deal_stage_key(pipeline_map, pipeline_id, stage_id)
            if dates.get("deep_dive_date") is not None or \
                    ho.HUBSPOT_STAGE_RANK.get(key or "", -1) >= dd_rank:
                reached_dd = True
        if ll not in _REACHED_SQL and not deal_is_sql:
            continue
        meeting = _parse_hs_date_ms(p.get(meeting_prop))
        if meeting is not None and meeting < _CUTOVER:
            sql_d = meeting
        else:
            sql_d = sql_from_deal or meeting
        if sql_d is None or sql_d < ini or sql_d > fin:
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c))
        name = (
            _first_mapped_value(pm, "client_name", contact=c)
            or " ".join(x for x in [p.get("firstname") or "", p.get("lastname") or ""] if x).strip()
            or p.get("email")
            or "—"
        )
        if not reached_dd:
            reached_dd = (
                any(d in hub_dd_deals for d in deals_of.get(cid) or [])
                or _norm(name) in hub_dd_names
            )
        rows.append({
            "sql_date": sql_d.isoformat(),
            "channel": channel_of(origin),
            "client_name": str(name),
            "lead_source": (str(origin or "").strip()) or "NA",
            "lead_life": p.get(lead_life_property) or "—",
            "reached_dd": reached_dd,
        })
    return rows


def sql_rows(ini: date, fin: date) -> list[dict]:
    key = f"sql_hubspot_rows__v{_CACHE_VERSION}__{ini.isoformat()}__{fin.isoformat()}"
    hit, cached = shared_cache.get(key)
    if hit:
        return cached
    rows = _fetch_rows(ini, fin)
    shared_cache.set(key, rows, _CACHE_TTL_SECONDS)
    return rows


def cur_and_prev(filters: dict) -> tuple[list[dict], list[dict], date, date]:
    """(filas de la ventana, filas de la ventana previa, win_ini, win_fin).

    Las tres cards (SQL → Deep Dive, su detalle y SQL → NDA Signed) piden el mismo
    rango, así comparten una sola entrada de cache y una sola pasada por HubSpot.
    """
    win_ini, win_fin = window_bounds(filters or {})
    prev_ini, prev_fin = prev_window_bounds(filters or {})
    rows = sql_rows(prev_ini, win_fin)
    cur = [r for r in rows if win_ini.isoformat() <= r["sql_date"] <= win_fin.isoformat()]
    prev = [r for r in rows if prev_ini.isoformat() <= r["sql_date"] <= prev_fin.isoformat()]
    return cur, prev, win_ini, win_fin


def rate(rows: list[dict]):
    """(llegaron, total, % sin redondear o None)."""
    den = len(rows)
    num = sum(1 for r in rows if r["reached_dd"])
    return num, den, (num * 100.0 / den if den else None)
