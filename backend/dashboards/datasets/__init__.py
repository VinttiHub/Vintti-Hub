from __future__ import annotations

from typing import Any, Callable

from . import ts_history, management_dashboard, opportunities, batch_sourcing, mrr_history

_REGISTRY: dict[str, dict[str, Any]] = {
    ts_history.DATASET["key"]: ts_history.DATASET,
    management_dashboard.DATASET["key"]: management_dashboard.DATASET,
    opportunities.DATASET["key"]: opportunities.DATASET,
    batch_sourcing.DATASET["key"]: batch_sourcing.DATASET,
    mrr_history.DATASET["key"]: mrr_history.DATASET,
}


def get(key: str) -> dict[str, Any] | None:
    return _REGISTRY.get(key)


def list_all() -> list[dict[str, Any]]:
    return [
        {
            "key": d["key"],
            "label": d.get("label", d["key"]),
            "dimensions": d["dimensions"],
            "measures": d["measures"],
        }
        for d in _REGISTRY.values()
    ]
