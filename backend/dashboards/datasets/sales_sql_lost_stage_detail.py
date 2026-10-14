"""Sales · ¿Dónde se pierden los SQLs? — detalle (una opp o deal por fila).

Lee el mismo `rows()` que la dona (`sales_sql_lost_stage`), así suma igual.
"""
from __future__ import annotations

from .sales_sql_lost_stage import rows


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    return rows(filters)


DATASET = {
    "key": "sales_sql_lost_stage_detail",
    "label": "Sales · ¿Dónde se pierden los SQLs? — Detalle",
    "dimensions": [
        {"key": "stage", "label": "Se perdió en", "type": "string"},
        {"key": "client_name", "label": "Cuenta / deal", "type": "string"},
        {"key": "position", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Fecha cierre", "type": "date"},
        {"key": "quien", "label": "AE / AM", "type": "string"},
        {"key": "sales_lead", "label": "Sales lead", "type": "string"},
        {"key": "motivo", "label": "Motivo", "type": "string"},
        {"key": "origen", "label": "Origen", "type": "string"},
        {"key": "ref", "label": "Ref", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "compute": compute,
}
