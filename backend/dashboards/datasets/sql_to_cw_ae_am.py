"""Sales · SQL → Close Win · AE + AM (ventana de 30d / filtro global).

Pedido de la owner (2026-10-13): de los SQLs que ENTRARON en la ventana —de los AE y
de los AM—, cuántos terminaron en Close Win y cuántos en Closed Lost. Es una cohorte:
los que todavía no se definieron quedan como "abiertos" y el % = CW / SQLs, así que el
número de un mes reciente sube solo a medida que esos SQLs cierran.

Qué es un SQL y cuándo entró:
  - AE: los mismos SQLs que SQL → Deep Dive (`_sql_hubspot.cur_and_prev`, HubSpot), uno
    por contacto, con su fecha de SQL. La base de AE coincide con esa card.
  - AM: cada opp que abre un AM (`opp_sales_lead` ∈ `am_history()`), New o Replacement.
    `opportunity` no tiene fecha de creación: entra el día MÁS TEMPRANO entre
    `deep_dive_date` y `nda_signature_or_start_date` (las del AM van directo a Sourcing;
    la #847 tiene arranque 28-may y deep dive 29-sep, y se abrió en mayo).

En qué terminó un SQL de AE: se cruza con las opps del hub por `hubspot_deal_id` de sus
deals o, si ningún deal está atado (las opps anteriores al sync), por nombre de cuenta
con una opp New abierta desde 7 días antes del SQL.
  - alguna opp en Close Win (o el deal Closed Won en HubSpot) -> cw
  - tiene opps y están todas en Closed Lost                      -> cl_opp
  - sin opp en el hub y sus deals todos en Closed Lost           -> cl_sin_opp
    (el SQL que el AE perdió antes de que se abriera la opp, que el hub crea en Deep Dive)
  - si no                                                        -> abierto

Summary y detalle leen `rows()`, así el drawer suma igual que la card.
"""
from __future__ import annotations

from datetime import date, timedelta

from ._am_scope import am_history
from ._periods import window_bounds
from ._sales_scope import sales_leads
from ._sql_hubspot import _norm, cur_and_prev

GRUPO_LABEL = {
    "cw": "Close Win",
    "cl_opp": "Closed Lost · con opp",
    "cl_sin_opp": "Closed Lost · sin opp",
    "abierto": "Abierto",
}

# Cuántos días antes del SQL puede arrancar una opp matcheada por nombre (una opp
# abierta el mismo día del SQL, o con el deep dive cargado un poco antes).
_NAME_MATCH_SLACK_DAYS = 7

_OPPS_SQL = """
    SELECT
      o.opportunity_id,
      TRIM(o.opp_stage)                                     AS stage,
      TRIM(LOWER(COALESCE(o.opp_sales_lead, '')))           AS sales_lead,
      o.opp_type,
      a.client_name,
      o.opp_position_name,
      NULLIF(TRIM(COALESCE(o.motive_close_lost, '')), '')   AS motivo,
      NULLIF(o.hubspot_deal_id, '')                         AS deal_id,
      LEAST(NULLIF(o.deep_dive_date::text, '')::date,
            NULLIF(o.nda_signature_or_start_date::text, '')::date) AS opened_d
    FROM opportunity o
    JOIN account a ON a.account_id = o.account_id
    WHERE COALESCE(a.vintti_internal, FALSE) = FALSE
"""


def _load_opps() -> list[dict]:
    from db import get_connection

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_OPPS_SQL)
        cols = [c[0] for c in cur.description]
        out = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return out


def _row(entry_d, grupo, quien, client, opp=None, ref="", motivo=None):
    return {
        "sql_date": entry_d.isoformat() if isinstance(entry_d, date) else entry_d,
        "grupo": grupo,
        "quien": quien,
        "client_name": client or "—",
        "position": (opp or {}).get("opp_position_name") or "—",
        "sales_lead": (opp or {}).get("sales_lead") or "—",
        "opp_type": (opp or {}).get("opp_type") or "—",
        "estado": (opp or {}).get("stage") or ("Closed Lost (HubSpot)" if grupo == "cl_sin_opp" else "—"),
        "motivo": motivo or "—",
        "ref": ref,
    }


def _ae_rows(ae_sqls: list[dict], opps: list[dict]) -> list[dict]:
    by_deal = {}
    by_name = {}
    for o in opps:
        if o["deal_id"]:
            by_deal.setdefault(str(o["deal_id"]), []).append(o)
        if o["opp_type"] == "New":
            by_name.setdefault(_norm(o["client_name"]), []).append(o)

    out = []
    for s in ae_sqls:
        sql_d = date.fromisoformat(s["sql_date"])
        linked = [o for d in s.get("deal_ids") or [] for o in by_deal.get(str(d), [])]
        if not linked:
            floor = sql_d - timedelta(days=_NAME_MATCH_SLACK_DAYS)
            linked = [
                o for o in by_name.get(_norm(s["client_name"]), [])
                if o["opened_d"] is not None and o["opened_d"] >= floor
            ]
        hs = s.get("hs_outcomes") or []
        won = [o for o in linked if o["stage"] == "Close Win"]
        if won or "won" in hs:
            grupo, opp = "cw", (won[0] if won else (linked[0] if linked else None))
        elif linked and all(o["stage"] == "Closed Lost" for o in linked):
            grupo, opp = "cl_opp", linked[0]
        elif not linked and hs and all(x == "lost" for x in hs):
            grupo, opp = "cl_sin_opp", None
        else:
            grupo, opp = "abierto", (linked[0] if linked else None)
        ref = ", ".join(f"opp #{o['opportunity_id']}" for o in linked) or \
            ", ".join(f"deal {d}" for d in s.get("deal_ids") or [])
        out.append(_row(sql_d, grupo, "AE", s["client_name"], opp, ref,
                        (opp or {}).get("motivo") if grupo == "cl_opp" else None))
    return out


def _am_rows(ini: date, fin: date, opps: list[dict]) -> list[dict]:
    am = set(am_history()) - set(sales_leads())
    out = []
    for o in opps:
        if o["sales_lead"] not in am or o["opp_type"] not in ("New", "Replacement"):
            continue
        if o["opened_d"] is None or o["opened_d"] < ini or o["opened_d"] > fin:
            continue
        grupo = {"Close Win": "cw", "Closed Lost": "cl_opp"}.get(o["stage"], "abierto")
        out.append(_row(o["opened_d"], grupo, "AM", o["client_name"], o,
                        f"opp #{o['opportunity_id']}",
                        o["motivo"] if grupo == "cl_opp" else None))
    return out


def rows(filters: dict) -> list[dict]:
    ae_sqls, _prev, ini, fin = cur_and_prev(filters or {})
    opps = _load_opps()
    out = _ae_rows(ae_sqls, opps) + _am_rows(ini, fin, opps)
    out.sort(key=lambda r: r["client_name"])
    out.sort(key=lambda r: r["sql_date"], reverse=True)
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
        cl = sum(1 for r in subset if r["grupo"] in ("cl_opp", "cl_sin_opp"))
        out[f"{prefix}_sql"] = len(subset)
        out[f"{prefix}_cw"] = cw
        out[f"{prefix}_cl"] = cl
        out[f"{prefix}_abiertos"] = len(subset) - cw - cl
        out[f"{prefix}_pct"] = _pct(cw, len(subset))
    out["cl_opp"] = sum(1 for r in rs if r["grupo"] == "cl_opp")
    out["cl_sin_opp"] = sum(1 for r in rs if r["grupo"] == "cl_sin_opp")
    return [out]


DATASET = {
    "key": "sql_to_cw_ae_am",
    "label": "Sales · SQL → Close Win · AE + AM (cohorte: SQLs que entraron en la ventana)",
    "dimensions": [],
    "measures": [
        {"key": "total_sql", "label": "Total · SQLs que entraron", "type": "number"},
        {"key": "total_cw", "label": "Total · Close Win", "type": "number"},
        {"key": "total_cl", "label": "Total · Closed Lost", "type": "number"},
        {"key": "total_abiertos", "label": "Total · todavía abiertos", "type": "number"},
        {"key": "total_pct", "label": "Total · SQL→CW %", "type": "percent"},
        {"key": "ae_sql", "label": "AE · SQLs que entraron", "type": "number"},
        {"key": "ae_cw", "label": "AE · Close Win", "type": "number"},
        {"key": "ae_cl", "label": "AE · Closed Lost", "type": "number"},
        {"key": "ae_abiertos", "label": "AE · abiertos", "type": "number"},
        {"key": "ae_pct", "label": "AE · SQL→CW %", "type": "percent"},
        {"key": "am_sql", "label": "AM · SQLs que entraron", "type": "number"},
        {"key": "am_cw", "label": "AM · Close Win", "type": "number"},
        {"key": "am_cl", "label": "AM · Closed Lost", "type": "number"},
        {"key": "am_abiertos", "label": "AM · abiertos", "type": "number"},
        {"key": "am_pct", "label": "AM · SQL→CW %", "type": "percent"},
        {"key": "cl_opp", "label": "Closed Lost · con opp", "type": "number"},
        {"key": "cl_sin_opp", "label": "Closed Lost · sin opp (AE)", "type": "number"},
    ],
    "default_filters": {},
    "compute": compute,
}
