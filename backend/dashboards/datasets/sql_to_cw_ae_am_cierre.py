"""Sales · SQL → Close Win · AE + AM · POR CIERRE (ventana de 30d / filtro global).

Gemela de `sql_to_cw_ae_am` (la cohorte de SQLs que entraron), con otra pregunta: de
todo lo que se DEFINIÓ en la ventana (por fecha de cierre), qué % se ganó →
CW / (CW + CL). La owner pidió tener las dos a la vista para comparar (2026-10-13).
Siempre da una tasa "madura", pero los SQLs pueden haber entrado hace meses.

Unidad = opp (o deal), no cliente:
  - AE: opps New de M+B (`sales_leads()`).
  - AM: opps New y Replacement de `am_history()`.
  - AE SIN opp: deals de HubSpot que pasaron por el stage SQL (o tienen SQL Date) desde
    el corte, hoy en Closed Lost, con `closedate` en la ventana y sin opp atada. Sólo
    desde el 2026-10-05: antes no había stage SQL.

Mia y Agustín quedan afuera, como en el resto del tab Sales. Summary y detalle leen
`rows()`, así el drawer suma igual que la card.
"""
from __future__ import annotations

from datetime import date

from ._am_scope import am_history
from ._periods import window_bounds
from ._sales_scope import sales_leads
from ._sql_hubspot import EXCLUDED_DEAL_IDS, _CUTOVER, _ms
from .mkt_mqls_by_origin import _parse_hs_date_ms

try:
    from backend.utils import shared_cache  # type: ignore
except ImportError:
    from utils import shared_cache  # type: ignore

_CACHE_TTL_SECONDS = 300
_CACHE_VERSION = 1

GRUPO_LABEL = {
    "cw": "Close Win",
    "cl_opp": "Closed Lost · con opp",
    "cl_sin_opp": "Closed Lost · sin opp",
}

_HUB_SQL = """
    SELECT
      o.opportunity_id,
      NULLIF(o.opp_close_date::text, '')::date             AS close_d,
      TRIM(o.opp_stage)                                    AS stage,
      TRIM(LOWER(o.opp_sales_lead))                        AS sales_lead,
      o.opp_type,
      a.client_name,
      o.opp_position_name,
      NULLIF(TRIM(COALESCE(o.motive_close_lost, '')), '')  AS motivo
    FROM opportunity o
    JOIN account a ON a.account_id = o.account_id
    WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
      AND COALESCE(a.vintti_internal, FALSE) = FALSE
      AND NULLIF(o.opp_close_date::text, '')::date BETWEEN %(ini)s AND %(fin)s
      AND (
            (TRIM(LOWER(o.opp_sales_lead)) IN %(ae)s AND o.opp_type = 'New')
         OR (TRIM(LOWER(o.opp_sales_lead)) IN %(am)s AND o.opp_type IN ('New', 'Replacement'))
      )
"""


def _hub_rows(ini: date, fin: date, ae: tuple, am: tuple) -> tuple[list[dict], set[str]]:
    from db import get_connection

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_HUB_SQL, {"ini": ini, "fin": fin, "ae": ae, "am": am})
        cols = [c[0] for c in cur.description]
        recs = [dict(zip(cols, r)) for r in cur.fetchall()]
        # Todo deal atado a una opp, en cualquier stage o fecha: si el deal tiene opp,
        # ya cuenta (o no) por la opp, nunca como "sin opp".
        cur.execute("SELECT DISTINCT NULLIF(hubspot_deal_id, '') FROM opportunity "
                    "WHERE NULLIF(hubspot_deal_id, '') IS NOT NULL")
        linked = {str(r[0]) for r in cur.fetchall()}
        cur.close()
    finally:
        conn.close()

    rows = []
    for r in recs:
        won = r["stage"] == "Close Win"
        rows.append({
            "close_date": r["close_d"].isoformat(),
            "grupo": "cw" if won else "cl_opp",
            "quien": "AE" if r["sales_lead"] in ae else "AM",
            "client_name": r["client_name"] or "—",
            "position": r["opp_position_name"] or "—",
            "sales_lead": r["sales_lead"] or "—",
            "opp_type": r["opp_type"] or "—",
            "motivo": (r["motivo"] or "—") if not won else "—",
            "ref": f"opp #{r['opportunity_id']}",
        })
    return rows, linked


def _hubspot_lost_without_opp(ini: date, fin: date, ae: tuple, linked: set[str]) -> list[dict]:
    if fin < _CUTOVER:
        return []
    from utils.hubspot import HubSpotClient
    from utils import hubspot_opportunities as ho

    client = HubSpotClient()
    pipeline_map = ho.resolve_pipeline_stage_map(client)
    opp_property_map = ho.resolve_opportunity_property_map(client)
    sql_date_prop = opp_property_map.get("sql_date") or "sql_date_deal"
    lost_reason_prop = "sql_ae_lost_reason"

    markers = [sql_date_prop]
    for entry in (pipeline_map.get("by_pipeline_id") or {}).values():
        prop = (entry.get("date_property_by_key") or {}).get("sql")
        if prop:
            markers.append(prop)
    since_ms = str(_ms(_CUTOVER))
    deals: dict[str, dict] = {}
    for prop in dict.fromkeys(markers):
        for d in client.search_deals(
            [{"propertyName": prop, "operator": "GTE", "value": since_ms}],
            extra_properties=[lost_reason_prop, sql_date_prop],
        ):
            deals[str(d.get("id"))] = d.get("properties") or {}

    rows = []
    for deal_id, p in deals.items():
        if deal_id in EXCLUDED_DEAL_IDS or deal_id in linked:
            continue
        entry = ho.pipeline_entry(pipeline_map, p.get("pipeline"))
        if not entry or not entry.get("closed_lost_stage_id"):
            continue
        if str(p.get("dealstage") or "") != str(entry["closed_lost_stage_id"]):
            continue
        sales_lead = (entry.get("sales_lead") or "").lower()
        if sales_lead not in ae:
            continue
        close_d = _parse_hs_date_ms(p.get("closedate"))
        if close_d is None or close_d < ini or close_d > fin:
            continue
        rows.append({
            "close_date": close_d.isoformat(),
            "grupo": "cl_sin_opp",
            "quien": "AE",
            "client_name": p.get("dealname") or "—",
            "position": "—",
            "sales_lead": sales_lead,
            "opp_type": "—",
            "motivo": p.get(lost_reason_prop) or "—",
            "ref": f"deal {deal_id}",
        })
    return rows


def rows(filters: dict) -> list[dict]:
    ini, fin = window_bounds(filters or {})
    ae = tuple(sorted(sales_leads()))
    am = tuple(sorted(set(am_history()) - set(ae)))
    key = f"sql_cw_ae_am_cierre__v{_CACHE_VERSION}__{ini.isoformat()}__{fin.isoformat()}__{','.join(ae)}__{','.join(am)}"
    hit, cached = shared_cache.get(key)
    if hit:
        return cached
    hub, linked = _hub_rows(ini, fin, ae, am)
    out = hub + _hubspot_lost_without_opp(ini, fin, ae, linked)
    out.sort(key=lambda r: r["client_name"])
    out.sort(key=lambda r: r["close_date"], reverse=True)
    shared_cache.set(key, out, _CACHE_TTL_SECONDS)
    return out


def _pct(num: int, den: int):
    return round(100.0 * num / den, 1) if den else None


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    rs = rows(filters)
    out = {}
    for prefix, subset in (
        ("total", rs),
        ("ae", [r for r in rs if r["quien"] == "AE"]),
        ("am", [r for r in rs if r["quien"] == "AM"]),
    ):
        cw = sum(1 for r in subset if r["grupo"] == "cw")
        out[f"{prefix}_sql"] = len(subset)
        out[f"{prefix}_cw"] = cw
        out[f"{prefix}_pct"] = _pct(cw, len(subset))
    out["cl_opp"] = sum(1 for r in rs if r["grupo"] == "cl_opp")
    out["cl_sin_opp"] = sum(1 for r in rs if r["grupo"] == "cl_sin_opp")
    return [out]


DATASET = {
    "key": "sql_to_cw_ae_am_cierre",
    "label": "Sales · SQL → Close Win · AE + AM · por cierre (opps + SQLs sin opp)",
    "dimensions": [],
    "measures": [
        {"key": "total_sql", "label": "Total · SQLs definidos", "type": "number"},
        {"key": "total_cw", "label": "Total · Close Win", "type": "number"},
        {"key": "total_pct", "label": "Total · SQL→CW %", "type": "percent"},
        {"key": "ae_sql", "label": "AE · SQLs definidos", "type": "number"},
        {"key": "ae_cw", "label": "AE · Close Win", "type": "number"},
        {"key": "ae_pct", "label": "AE · SQL→CW %", "type": "percent"},
        {"key": "am_sql", "label": "AM · SQLs definidos", "type": "number"},
        {"key": "am_cw", "label": "AM · Close Win", "type": "number"},
        {"key": "am_pct", "label": "AM · SQL→CW %", "type": "percent"},
        {"key": "cl_opp", "label": "Closed Lost · con opp", "type": "number"},
        {"key": "cl_sin_opp", "label": "Closed Lost · sin opp (AE)", "type": "number"},
    ],
    "default_filters": {},
    "compute": compute,
}
