"""Operations · lista de recruiters para el dropdown de caídas.

Devuelve TODOS los recruiters activos (aunque no tengan caídas en la ventana), para
que el filtro los muestre siempre. Ver [[_recruiters]].
"""
from __future__ import annotations

from ._recruiters import ALL_RECRUITERS_SQL


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    return ALL_RECRUITERS_SQL, {}


DATASET = {
    "key": "op_churn_recruiters",
    "label": "Operations · recruiters (todos, activos)",
    "dimensions": [
        {"key": "value", "label": "Recruiter email", "type": "string"},
        {"key": "label", "label": "Recruiter", "type": "string"},
    ],
    "measures": [{"key": "count", "label": "—", "type": "number"}],
    "default_filters": {},
    "query": query,
}
