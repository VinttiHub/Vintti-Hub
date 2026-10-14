"""Sales · Razones de SQL perdidos — detalle (una opp o deal por fila).

Lee el mismo `rows()` que la dona (`sales_sql_lost_reasons`), así suma igual.
"""
from __future__ import annotations

from .sales_sql_lost_reasons import rows


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    return rows(filters)


DATASET = {
    "key": "sales_sql_lost_reasons_detail",
    "label": "Sales · Razones de SQL perdidos — Detalle",
    "dimensions": [
        {"key": "reason", "label": "Razón", "type": "string"},
        {"key": "client_name", "label": "Cuenta / deal", "type": "string"},
        {"key": "position", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Fecha cierre", "type": "date"},
        {"key": "quien", "label": "AE / AM", "type": "string"},
        {"key": "sales_lead", "label": "Sales lead", "type": "string"},
        {"key": "origen", "label": "Origen", "type": "string"},
        {"key": "ref", "label": "Ref", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "compute": compute,
}
