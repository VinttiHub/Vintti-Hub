"""Sales · ¿Dónde se pierden los SQLs? — opciones del filtro AE / AM.

Hidrata el desplegable de la card (`sa_select_sql_lost_stage_quien`): los valores de
`quien` que hay en la ventana, con su conteo. Lee el mismo `rows()` que la dona
(`sales_sql_lost_stage`), así cada opción suma lo que muestra la dona al elegirla.
"Otro" (sales leads fuera de AE y AM) sale sólo si hay casos.
"""
from __future__ import annotations

from .sales_sql_lost_stage import rows

_ORDER = {"AE": 0, "AM": 1, "Otro": 2}


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    f = dict(filters or {})
    f.pop("quien", None)
    counts: dict[str, int] = {}
    for r in rows(f):
        counts[r["quien"]] = counts.get(r["quien"], 0) + 1
    out = [{"quien": k, "count": v} for k, v in counts.items()]
    out.sort(key=lambda r: (_ORDER.get(r["quien"], 9), r["quien"]))
    return out


DATASET = {
    "key": "sales_sql_lost_quien",
    "label": "Sales · ¿Dónde se pierden los SQLs? — filtro AE / AM",
    "dimensions": [{"key": "quien", "label": "AE / AM", "type": "string"}],
    "measures": [{"key": "count", "label": "SQLs", "type": "number"}],
    "default_filters": {},
    "compute": compute,
}
