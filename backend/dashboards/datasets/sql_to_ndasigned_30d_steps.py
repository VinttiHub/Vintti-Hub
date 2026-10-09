"""SQL → NDA Signed — el cálculo de la card abierto en 3 filas.

Los dos pasos con su numerador/denominador reales y el producto. La fila compuesta
no tiene N/M porque las dos cohortes son distintas (ver sql_to_ndasigned_30d.py).
Lee `step_rates()` de la card, así los números son los mismos por construcción.
"""
from __future__ import annotations

from .sql_to_ndasigned_30d import step_rates


def _r1(x):
    return round(x, 1) if x is not None else None


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    st = step_rates(filters)
    a, b = st["tot_rate1"], st["tot_rate2"]
    return [
        {"orden": 1, "paso": "SQL → Deep Dive",
         "numerador": st["step1_num"], "denominador": st["step1_den"], "pct": _r1(a)},
        {"orden": 2, "paso": "Deep Dive → NDA Signed",
         "numerador": st["step2_num"], "denominador": st["step2_den"], "pct": _r1(b)},
        {"orden": 3, "paso": "SQL → NDA Signed (compuesta)",
         "numerador": None, "denominador": None,
         "pct": _r1(a * b / 100.0) if a is not None and b is not None else None},
    ]


DATASET = {
    "key": "sql_to_ndasigned_30d_steps",
    "label": "SQL → NDA Signed — Cálculo paso a paso",
    "dimensions": [
        {"key": "paso", "label": "Paso", "type": "string"},
    ],
    "measures": [
        {"key": "numerador", "label": "Numerador", "type": "number"},
        {"key": "denominador", "label": "Denominador", "type": "number"},
        {"key": "pct", "label": "%", "type": "percent"},
    ],
    "default_filters": {},
    "compute": compute,
}
