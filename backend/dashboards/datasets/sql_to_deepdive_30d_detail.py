"""SQL → Deep Dive — detalle (una fila por SQL de la ventana, live HubSpot).

Lee las mismas filas que la card (`_sql_hubspot.cur_and_prev`), así la cantidad de
filas es `total_sqls` y las "Deep Dive" son `total_dd` por construcción.
"""
from __future__ import annotations

from ._sql_hubspot import cur_and_prev

_CHANNEL_LABEL = {"sales": "Sales", "marketing": "Marketing", "referrals": "Referrals"}


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    cur, _prev, _ini, _fin = cur_and_prev(filters)
    out = [{
        "sql_date": r["sql_date"],
        "channel": _CHANNEL_LABEL[r["channel"]],
        "client_name": r["client_name"],
        "lead_source": r["lead_source"],
        "status": "Deep Dive" if r["reached_dd"] else "—",
    } for r in cur]
    out.sort(key=lambda r: r["client_name"])
    out.sort(key=lambda r: r["sql_date"], reverse=True)
    out.sort(key=lambda r: r["channel"])
    return out


DATASET = {
    "key": "sql_to_deepdive_30d_detail",
    "label": "SQL → Deep Dive — Detalle de SQLs (30d, live HubSpot)",
    "dimensions": [
        {"key": "sql_date", "label": "SQL date", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cuenta", "type": "string"},
        {"key": "lead_source", "label": "Origen", "type": "string"},
        {"key": "status", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "compute": compute,
}
