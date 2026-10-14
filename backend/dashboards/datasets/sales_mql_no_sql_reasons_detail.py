"""Sales · Razones de no SQL — detalle (un MQL por fila).

Lee el mismo `rows()` que la dona (`sales_mql_no_sql_reasons`), así suma igual.
"""
from __future__ import annotations

from .sales_mql_no_sql_reasons import rows


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    return rows(filters)


DATASET = {
    "key": "sales_mql_no_sql_reasons_detail",
    "label": "Sales · Razones de no SQL — Detalle de MQLs (live HubSpot)",
    "dimensions": [
        {"key": "reason", "label": "Razón", "type": "string"},
        {"key": "client_name", "label": "Cuenta / contacto", "type": "string"},
        {"key": "mql_date", "label": "MQL date", "type": "date"},
        {"key": "tipo", "label": "Tipo", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "channel", "label": "Conversion channel", "type": "string"},
        {"key": "lead_life", "label": "Etapa actual", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "compute": compute,
}
