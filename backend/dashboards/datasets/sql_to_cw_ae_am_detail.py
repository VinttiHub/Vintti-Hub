"""Sales · SQL → Close Win · AE + AM — detalle (una fila por SQL: contacto de AE u opp de AM).

Lee las mismas `rows()` que la card (`sql_to_cw_ae_am`), así la cantidad de filas es
`total_sql` y las de grupo `cw` son `total_cw` por construcción. El drawer filtra por
`grupo` (cw / cl_opp / cl_sin_opp / abierto) para separar los Closed Lost con y sin opp.
"""
from __future__ import annotations

from .sql_to_cw_ae_am import GRUPO_LABEL, rows


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    return [{**r, "grupo_label": GRUPO_LABEL[r["grupo"]]} for r in rows(filters)]


DATASET = {
    "key": "sql_to_cw_ae_am_detail",
    "label": "Sales · SQL → Close Win · AE + AM — Detalle",
    "dimensions": [
        {"key": "sql_date", "label": "Entró como SQL", "type": "date"},
        {"key": "estado", "label": "Stage actual", "type": "string"},
        {"key": "grupo", "label": "Grupo", "type": "string"},
        {"key": "grupo_label", "label": "Resultado", "type": "string"},
        {"key": "quien", "label": "AE / AM", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "position", "label": "Posición", "type": "string"},
        {"key": "sales_lead", "label": "Sales lead", "type": "string"},
        {"key": "opp_type", "label": "Tipo", "type": "string"},
        {"key": "motivo", "label": "Motivo", "type": "string"},
        {"key": "ref", "label": "Ref", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "compute": compute,
}
