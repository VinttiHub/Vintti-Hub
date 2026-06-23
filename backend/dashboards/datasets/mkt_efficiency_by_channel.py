"""Marketing · Eficiencia por canal — COHORTE POR SQL (def HubSpot), por origin / período.

Una fila por canal (origin = where_come_from normalizado). La COHORTE son los
contactos que ALCANZARON la etapa SQL (AE) en HubSpot en el período (ancla
`meeting_date___time` = fecha real del meeting, filtro `mql_source` ∈ {Inbound MQL,
Event MQL}) — MISMA definición de SQL que el card / detalle / embudo. La columna MQL
usa su propia ancla `date_of_meeting_scheduled`. Esos contactos se mapean a sus
cuentas (`account.hubspot_contact_id`) y medimos qué pasó con ellas (outcomes
acumulados a hoy, Postgres):

  - sqls        → tamaño de la cohorte (contactos que llegaron a SQL en el período).
  - clients     → cuántas de esas CUENTAS se volvieron cliente (≥1 Close Win, ever).
  - net_rev     → fee de Vintti (Staffing ho.fee + Recruiting ho.revenue) de los
                  Close Win de esas cuentas.
  - close_rate  → win rate de lo DECIDIDO de la cohorte: Close Win ÷ (Close Win +
                  solo Closed Lost), a nivel cuenta. + ratio "won/decided".
  - cltv_months → vida promedio real en meses (Staffing) de esas cuentas.

OJO: cohortes recientes (semana/mes) se ven inmaduras porque los deals tardan meses
en cerrar; mirá Q / Año para conversión madura. clients ≤ sqls (sqls cuenta
contactos; clients cuenta cuentas ganadas).
"""
from __future__ import annotations

import os
from collections import Counter

from .mkt_sqls_by_origin import period_bounds


def _cohort(ini, fin) -> tuple[list[tuple[str, str]], Counter]:
    """Una sola pasada por HubSpot (mql_source de marketing, meeting en [ini, fin]):
      - sql_contacts: (contact_id, origin) de los que alcanzaron SQL (AE) — para
        outcomes + conteo de SQLs.
      - mql_by_origin: Counter de MQLs (alcanzaron MQL(AE)+) por origin — para la
        columna MQL del funnel. MQL ≥ SQL por canal."""
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value, _normalize_lead_source,
    )
    from .mkt_mqls_by_origin import _parse_hs_date_ms, _IN_VALUES, _REACHED_MQL
    from .mkt_funnel_mql_sql_cw import _REACHED_SQL
    from ._marketing_scope import is_marketing_mql_source

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    # Ancla DOBLE: MQL por `date_of_meeting_scheduled` (se agendó), SQL por
    # `meeting_date___time` (la reunión ocurrió) — para que el SQL cuadre con sus cards.
    mql_anchor = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()
    sql_anchor = (
        os.environ.get("HUBSPOT_SQL_ANCHOR_PROPERTY")
        or os.environ.get("HUBSPOT_MEETING_DATETIME_PROPERTY")
        or "meeting_date___time"
    ).strip()
    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"
    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, mql_anchor, sql_anchor, origin_prop, "mql_source"],
    )
    sql_contacts, mql_by_origin = [], Counter()
    for c in contacts:
        p = c.get("properties") or {}
        ll = str(p.get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_MQL:
            continue
        if not is_marketing_mql_source(p.get("mql_source")):
            continue
        origin = _normalize_lead_source(_first_mapped_value(pm, "where_come_from", contact=c))
        origin = (str(origin or "").strip()) or "(Sin origen)"
        d_mql = _parse_hs_date_ms(p.get(mql_anchor))
        if d_mql is not None and ini <= d_mql <= fin:
            mql_by_origin[origin] += 1
        if ll in _REACHED_SQL:
            d_sql = _parse_hs_date_ms(p.get(sql_anchor))
            if d_sql is not None and ini <= d_sql <= fin:
                sql_contacts.append((str(c.get("id") or "").strip(), origin))
    return sql_contacts, mql_by_origin


# Outcomes (a hoy) por cuenta, para un set de account_ids dado.
_OUTCOMES_SQL = """
    WITH ids AS (SELECT UNNEST(%(aids)s::int[]) AS account_id),
    opp_agg AS (
      SELECT i.account_id,
             BOOL_OR(TRIM(o.opp_stage) = 'Close Win')                      AS won,
             BOOL_OR(TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost'))     AS decided
      FROM ids i JOIN opportunity o ON o.account_id = i.account_id
      GROUP BY i.account_id
    ),
    rev_per_opp AS (
      SELECT i.account_id, o.opportunity_id,
             COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                               ELSE COALESCE(ho.fee, 0) END), 0)::numeric AS rev
      FROM ids i
      JOIN opportunity o ON o.account_id = i.account_id
        AND TRIM(o.opp_stage) = 'Close Win' AND o.opp_model IN ('Staffing', 'Recruiting')
      LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
      GROUP BY i.account_id, o.opportunity_id
    ),
    rev AS (SELECT account_id, SUM(rev)::numeric AS net_rev FROM rev_per_opp GROUP BY account_id),
    hires AS (
      SELECT i.account_id,
             CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                  ELSE NULLIF(ho.start_date::text, '')::date END AS start_d,
             CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                  WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
                  ELSE ho.end_date::date END AS end_d
      FROM ids i
      JOIN hire_opportunity ho ON ho.account_id = i.account_id
      JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
      WHERE TRIM(o.opp_stage) = 'Close Win' AND o.opp_model = 'Staffing'
    ),
    life AS (
      SELECT account_id,
             (DATE_PART('year',  AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) * 12
            + DATE_PART('month', AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) + 1)::int AS lifetime_months
      FROM hires WHERE start_d IS NOT NULL GROUP BY account_id
    )
    SELECT i.account_id,
           COALESCE(oa.won, false)      AS won,
           COALESCE(oa.decided, false)  AS decided,
           COALESCE(r.net_rev, 0)       AS net_rev,
           l.lifetime_months            AS lifetime_months
    FROM ids i
    LEFT JOIN opp_agg oa ON oa.account_id = i.account_id
    LEFT JOIN rev     r  ON r.account_id  = i.account_id
    LEFT JOIN life    l  ON l.account_id  = i.account_id;
"""


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from db import get_connection

    ini, fin, label = period_bounds(filters)
    cohort, mql_by_origin = _cohort(ini, fin)   # sql_contacts [(contact_id, origin)], mqls por origin
    sqls = Counter(o for _, o in cohort)        # contactos SQL por origin

    acc_origin = {}                              # account_id -> origin (de su contacto SQL)
    out = {}                                     # account_id -> outcomes
    cids = [cid for cid, _ in cohort if cid]
    if cids:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT hubspot_contact_id, account_id FROM account "
                "WHERE hubspot_contact_id = ANY(%s)",
                (cids,),
            )
            c2a = {str(hcid): aid for hcid, aid in cur.fetchall()}
            for cid, o in cohort:
                aid = c2a.get(str(cid))
                if aid is not None and aid not in acc_origin:
                    acc_origin[aid] = o
            aids = list(acc_origin.keys())
            if aids:
                cur.execute(_OUTCOMES_SQL, {"aids": aids})
                cols = [d[0] for d in cur.description]
                for row in cur.fetchall():
                    rd = dict(zip(cols, row))
                    out[rd["account_id"]] = rd
            cur.close()
        finally:
            conn.close()

    # Agregar outcomes por origin (a nivel cuenta).
    agg: dict[str, dict] = {}
    for aid, o in acc_origin.items():
        a = agg.setdefault(o, {"clients": 0, "net_rev": 0.0, "life": [], "won": 0, "decided": 0})
        od = out.get(aid, {})
        if od.get("won"):
            a["clients"] += 1
            a["won"] += 1
        if od.get("decided"):
            a["decided"] += 1
        a["net_rev"] += float(od.get("net_rev") or 0)
        if od.get("lifetime_months") is not None:
            a["life"].append(od["lifetime_months"])

    rows = []
    # Unión: canales con MQL (agendado en el período) Y/O con SQL (meeting en el
    # período). Con anclas distintas, un canal puede tener SQL sin MQL en el período.
    for o in set(mql_by_origin) | set(sqls):
        a = agg.get(o, {})
        won, dec, life = a.get("won", 0), a.get("decided", 0), a.get("life", [])
        rows.append({
            "origin": o,
            "mql": mql_by_origin[o],
            "sqls": sqls.get(o, 0),
            "clients": a.get("clients", 0),
            "net_rev": round(a.get("net_rev", 0.0)),
            "cltv_months": round(sum(life) / len(life), 1) if life else None,
            "close_rate": round(won * 100.0 / dec, 1) if dec else None,
            "ratio": f"{won}/{dec}",
            "period_label": label,
        })
    rows.sort(key=lambda r: (-r["mql"], -r["sqls"], -r["clients"], r["origin"]))
    return rows


DATASET = {
    "key": "mkt_efficiency_by_channel",
    "label": "Marketing · Eficiencia por canal (cohorte por SQL, período)",
    "dimensions": [
        {"key": "origin", "label": "Canal", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "mql", "label": "MQL", "type": "number"},
        {"key": "sqls", "label": "SQLs", "type": "number"},
        {"key": "clients", "label": "Clients", "type": "number"},
        {"key": "net_rev", "label": "Net rev.", "type": "currency"},
        {"key": "cltv_months", "label": "CLTV (meses)", "type": "number"},
        {"key": "close_rate", "label": "Tasa cierre", "type": "percent"},
        {"key": "ratio", "label": "CW / Total", "type": "string"},
    ],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
