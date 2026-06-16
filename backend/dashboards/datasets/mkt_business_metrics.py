"""Marketing · Métricas de negocio — strip de KPIs company-wide (sin outbound).

Una sola fila con los totales del período seleccionado (semana / mes / q / anio)
y su variación vs el MISMO span del período anterior (MTD vs MTD, YTD vs YTD, etc.):

  - sqls         → contactos que ALCANZARON la etapa SQL (AE) en HubSpot, anclados
                   por `date_of_meeting_scheduled`, en el período. MISMA definición
                   que el embudo (mkt_funnel_mql_sql_cw) para que ambos cuadren.
  - new_clients  → cuentas con su PRIMER Close Win (opp_close_date) en el período.
  - close_rate   → win rate por cliente de lo decidido (cierre en el período):
                   Close Win ÷ (Close Win + solo Closed Lost), a nivel cuenta.
  - net_rev      → fee de Vintti (Staffing ho.fee + Recruiting ho.revenue) de los
                   Close Win cerrados en el período.

Deltas: sqls/new_clients/net_rev en % de cambio; close_rate en puntos (pp).

Marketing-scope: excluye outbound/connected inbox/referral, igual que el resto del tab.

Es un dataset `compute` (no `query`) porque `sqls` se calcula en vivo desde HubSpot;
el resto de los KPIs se siguen calculando con SQL sobre Postgres dentro del mismo
compute (patrón de mkt_leads_by_channel_history.py).
"""
from __future__ import annotations

import os
from calendar import monthrange
from datetime import date

from .mkt_sqls_by_origin import period_bounds
from ._marketing_scope import is_marketing_mql_source

# Definición de SQL = etapa ALCANZADA en HubSpot (idéntica a mkt_funnel_mql_sql_cw):
#   SQL = llegó a SQL (AE) o más (active/inactive client). NO cuenta Closed Lost.
_WON = {"active client", "inactive client"}
_REACHED_SQL = _WON | {"sql (ae)"}
# Valores exactos de lead_life para acotar el search en HubSpot.
_IN_VALUES = ["MQL (AE)", "SQL (AE)", "Active Client", "Inactive Client", "Closed Lost"]


def _minus_months(d: date, n: int) -> date:
    total = (d.year * 12 + (d.month - 1)) - n
    y, m = divmod(total, 12)
    m += 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def _prev_bounds(ini: date, fin: date, label: str) -> tuple[date, date]:
    """Mismo span, un período hacia atrás (para comparación justa MTD/YTD/...)."""
    if label == "Semana":
        from datetime import timedelta
        return ini - timedelta(days=7), fin - timedelta(days=7)
    if label == "Trimestre":
        return _minus_months(ini, 3), _minus_months(fin, 3)
    if label == "Año":
        return date(ini.year - 1, 1, 1), _minus_months(fin, 12)
    # Mes
    return _minus_months(ini, 1), _minus_months(fin, 1)


def _hs_sql_counts(ini: date, fin: date, pini: date, pfin: date) -> tuple[int, int]:
    """SQLs (etapa alcanzada en HubSpot, ancla date_of_meeting_scheduled) para el
    período actual [ini, fin] y el anterior [pini, pfin]. Misma lógica que el embudo."""
    from utils.hubspot import HubSpotClient
    from routes.hubspot_routes import (
        _resolve_account_property_maps, _first_mapped_value,
    )
    from .mkt_mqls_by_origin import _parse_hs_date_ms

    lead_life_property = (os.environ.get("HUBSPOT_LEAD_LIFE_PROPERTY") or "lead_life").strip()
    anchor = (os.environ.get("HUBSPOT_MQL_ANCHOR_PROPERTY") or "date_of_meeting_scheduled").strip()

    client = HubSpotClient()
    pm = _resolve_account_property_maps(client)
    origin_prop = (pm.get("contacts") or {}).get("where_come_from") or "origin"

    contacts = client.search_contacts(
        [{"propertyName": lead_life_property, "operator": "IN", "values": _IN_VALUES}],
        extra_properties=[lead_life_property, anchor, origin_prop, "mql_source"],
    )

    cur = prev = 0
    for c in contacts:
        props = c.get("properties") or {}
        d = _parse_hs_date_ms(props.get(anchor))
        if d is None:
            continue
        # Marketing-scope = denylist + import sobre origin (sin conversion_channel).
        if not is_marketing_mql_source((c.get("properties") or {}).get("mql_source")):
            continue
        ll = str(props.get(lead_life_property) or "").strip().lower()
        if ll not in _REACHED_SQL:
            continue
        if ini <= d <= fin:
            cur += 1
        elif pini <= d <= pfin:
            prev += 1
    return cur, prev


# KPIs no-SQL (new_clients, close_rate, net_rev) — Postgres. `sqls` ya NO sale de aquí.
_PG_SQL = """
    WITH first_close AS (
      SELECT o.account_id, MIN(NULLIF(o.opp_close_date::text, '')::date) AS fd
      FROM opportunity o
      WHERE TRIM(o.opp_stage) = 'Close Win'
        AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
      GROUP BY o.account_id
    ),
    newc AS (
      SELECT
        COUNT(*) FILTER (WHERE fc.fd BETWEEN %(ci)s::date AND %(cf)s::date)::int AS cur,
        COUNT(*) FILTER (WHERE fc.fd BETWEEN %(pi)s::date AND %(pf)s::date)::int AS prev
      FROM first_close fc
      JOIN account a ON a.account_id = fc.account_id
      WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
    ),
    dec AS (
      SELECT a.account_id,
        BOOL_OR(TRIM(o.opp_stage) = 'Close Win')
          FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(ci)s::date AND %(cf)s::date) AS won_cur,
        BOOL_OR(TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost'))
          FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(ci)s::date AND %(cf)s::date) AS dec_cur,
        BOOL_OR(TRIM(o.opp_stage) = 'Close Win')
          FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(pi)s::date AND %(pf)s::date) AS won_prev,
        BOOL_OR(TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost'))
          FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(pi)s::date AND %(pf)s::date) AS dec_prev
      FROM account a
      JOIN opportunity o ON o.account_id = a.account_id
      WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
        AND TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
        AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
      GROUP BY a.account_id
    ),
    cr AS (
      SELECT
        ROUND(COUNT(*) FILTER (WHERE won_cur)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE dec_cur), 0), 1)::float AS cur,
        ROUND(COUNT(*) FILTER (WHERE won_prev)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE dec_prev), 0), 1)::float AS prev
      FROM dec
    ),
    rev_opp AS (
      SELECT o.opportunity_id, NULLIF(o.opp_close_date::text, '')::date AS cdte,
        COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                          ELSE COALESCE(ho.fee, 0) END), 0)::numeric AS rev
      FROM opportunity o
      JOIN account a ON a.account_id = o.account_id
      LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
      WHERE TRIM(o.opp_stage) = 'Close Win' AND o.opp_model IN ('Staffing', 'Recruiting')
        AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
        AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
      GROUP BY o.opportunity_id, cdte
    ),
    nr AS (
      SELECT
        COALESCE(SUM(rev) FILTER (WHERE cdte BETWEEN %(ci)s::date AND %(cf)s::date), 0)::bigint AS cur,
        COALESCE(SUM(rev) FILTER (WHERE cdte BETWEEN %(pi)s::date AND %(pf)s::date), 0)::bigint AS prev
      FROM rev_opp
    )
    SELECT
      newc.cur                                     AS new_clients,
      cr.cur                                       AS close_rate,
      nr.cur                                       AS net_rev,
      CASE WHEN newc.prev > 0 THEN ROUND((newc.cur - newc.prev)::numeric * 100.0 / newc.prev)::float END        AS new_clients_delta,
      CASE WHEN cr.prev IS NOT NULL AND cr.cur IS NOT NULL THEN ROUND((cr.cur - cr.prev)::numeric)::float END    AS close_rate_delta,
      CASE WHEN nr.prev > 0 THEN ROUND((nr.cur - nr.prev)::numeric * 100.0 / nr.prev)::float END                 AS net_rev_delta
    FROM newc, cr, nr;
"""


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    from db import get_connection

    ini, fin, label = period_bounds(filters)
    pini, pfin = _prev_bounds(ini, fin, label)

    # SQLs: definición HubSpot (etapa alcanzada), idéntica al embudo.
    sqls_cur, sqls_prev = _hs_sql_counts(ini, fin, pini, pfin)
    sqls_delta = (
        round((sqls_cur - sqls_prev) * 100.0 / sqls_prev) if sqls_prev > 0 else None
    )

    # Resto de KPIs: Postgres.
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_PG_SQL, {"ci": ini, "cf": fin, "pi": pini, "pf": pfin})
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        cur.close()
        rec = dict(zip(cols, row)) if row else {}
    finally:
        conn.close()

    return [{
        "sqls": sqls_cur,
        "new_clients": rec.get("new_clients"),
        "close_rate": rec.get("close_rate"),
        "net_rev": rec.get("net_rev"),
        "sqls_delta": float(sqls_delta) if sqls_delta is not None else None,
        "new_clients_delta": rec.get("new_clients_delta"),
        "close_rate_delta": rec.get("close_rate_delta"),
        "net_rev_delta": rec.get("net_rev_delta"),
        "period_label": label,
    }]


DATASET = {
    "key": "mkt_business_metrics",
    "label": "Marketing · Métricas de negocio (strip KPIs, período)",
    "dimensions": [
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "sqls", "label": "SQLs totales", "type": "number"},
        {"key": "new_clients", "label": "New active clients", "type": "number"},
        {"key": "close_rate", "label": "Tasa de cierre", "type": "percent"},
        {"key": "net_rev", "label": "Net revenue", "type": "currency"},
        {"key": "sqls_delta", "label": "Δ SQLs", "type": "number"},
        {"key": "new_clients_delta", "label": "Δ Clients", "type": "number"},
        {"key": "close_rate_delta", "label": "Δ Tasa cierre (pp)", "type": "number"},
        {"key": "net_rev_delta", "label": "Δ Net revenue", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
