"""Sales · MQL → SQL — detalle (una fila por MQL de la cohorte).

Lee el mismo `cohort_rows()` que la card (`sales_mql_to_sql_30d`), así que la cantidad
de filas es `total_mql` y las "Llegó a SQL" son `total_sql` por construcción.
"""
from __future__ import annotations

from .sales_mql_to_sql_30d import cohort_rows


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    rows, _ini, _fin = cohort_rows(filters)
    out = [{
        "mql_date": r["mql_date"],
        "client_name": r["client_name"],
        "origin": r["origin"],
        "channel": r["channel"],
        "lead_life": r["lead_life"],
        "status": "Llegó a SQL" if r["reached_sql"] else "No llegó",
    } for r in rows]
    out.sort(key=lambda r: r["client_name"])
    out.sort(key=lambda r: r["mql_date"], reverse=True)
    return out


DATASET = {
    "key": "sales_mql_to_sql_30d_detail",
    "label": "Sales · MQL → SQL — Detalle de MQLs (live HubSpot)",
    "dimensions": [
        {"key": "mql_date", "label": "MQL date", "type": "date"},
        {"key": "client_name", "label": "Cuenta / contacto", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "channel", "label": "Conversion channel", "type": "string"},
        {"key": "lead_life", "label": "Etapa actual", "type": "string"},
        {"key": "status", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "compute": compute,
}
