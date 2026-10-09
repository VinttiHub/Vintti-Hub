"""SQL → Deep Dive por canal (ventana de 30d / filtro global, live HubSpot).

De los SQLs de la ventana, cuántos pasó el AE a Deep Dive. Los SQLs salen de
HubSpot, con la misma fuente que MQL → SQL (`_sql_hubspot.py`, que explica por qué
las cuentas del hub no sirven para esto). Canal por el Origin del contacto:
Outbound → Sales, Referral → Referrals, resto → Marketing. Delta vs la ventana previa.

Comparte filas con `sql_to_deepdive_30d_detail` y con el paso 1 de
`sql_to_ndasigned_30d`, así card, drawer y card compuesta dan lo mismo.
"""
from __future__ import annotations

from ._sql_hubspot import cur_and_prev, rate


def _r1(x):
    return round(x, 1) if x is not None else None


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    cur, prev, _ini, _fin = cur_and_prev(filters)
    out = {}
    for prefix, ch in (("sales", "sales"), ("mkt", "marketing"), ("ref", "referrals")):
        num, den, pct = rate([r for r in cur if r["channel"] == ch])
        out[f"{prefix}_sqls"] = den
        out[f"{prefix}_dd"] = num
        out[f"{prefix}_pct"] = _r1(pct)
    num, den, pct = rate(cur)
    _pn, _pd, prev_pct = rate(prev)
    out.update({
        "total_sqls": den,
        "total_dd": num,
        "total_pct": _r1(pct),
        "prev_total_pct": _r1(prev_pct),
        "total_pct_delta": _r1(pct - (prev_pct or 0)) if pct is not None else None,
    })
    return [out]


DATASET = {
    "key": "sql_to_deepdive_30d",
    "label": "SQL → Deep Dive por canal (30d, live HubSpot)",
    "dimensions": [],
    "measures": [
        {"key": "sales_sqls", "label": "Sales · SQLs", "type": "number"},
        {"key": "sales_dd", "label": "Sales · Deep Dive", "type": "number"},
        {"key": "sales_pct", "label": "Sales · SQL→DD %", "type": "percent"},
        {"key": "mkt_sqls", "label": "Marketing · SQLs", "type": "number"},
        {"key": "mkt_dd", "label": "Marketing · Deep Dive", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · SQL→DD %", "type": "percent"},
        {"key": "ref_sqls", "label": "Referrals · SQLs", "type": "number"},
        {"key": "ref_dd", "label": "Referrals · Deep Dive", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · SQL→DD %", "type": "percent"},
        {"key": "total_sqls", "label": "Total · SQLs", "type": "number"},
        {"key": "total_dd", "label": "Total · Deep Dive", "type": "number"},
        {"key": "total_pct", "label": "Total · SQL→DD %", "type": "percent"},
        {"key": "prev_total_pct", "label": "Total · SQL→DD % (30d previos)", "type": "percent"},
        {"key": "total_pct_delta", "label": "Total · Δ SQL→DD (pp)", "type": "percent"},
    ],
    "default_filters": {},
    "compute": compute,
}
