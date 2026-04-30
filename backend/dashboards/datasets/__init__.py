from __future__ import annotations

from typing import Any, Callable

from . import (
    ts_history,
    management_dashboard,
    opportunities,
    batch_sourcing,
    mrr_history,
    active_headcount_history,
    active_headcount_detail,
    active_headcount_30d_total,
    active_headcount_30d_detail,
    inactive_candidates_detail,
    recruiting_upfront,
    client_lifetime_detail,
    client_lifetime_avg,
    candidate_lifetime_detail,
    candidate_lifetime_avg,
    arpa_history,
    arpc_history,
    acpa_history,
    nda_to_clients_history,
    nda_to_clients_detail,
    nda_to_clients_30d_summary,
    nda_to_clients_30d_detail,
    nda_lead_source_month,
    nda_lead_source_30d,
)

_REGISTRY: dict[str, dict[str, Any]] = {
    ts_history.DATASET["key"]: ts_history.DATASET,
    management_dashboard.DATASET["key"]: management_dashboard.DATASET,
    opportunities.DATASET["key"]: opportunities.DATASET,
    batch_sourcing.DATASET["key"]: batch_sourcing.DATASET,
    mrr_history.DATASET["key"]: mrr_history.DATASET,
    active_headcount_history.DATASET["key"]: active_headcount_history.DATASET,
    active_headcount_detail.DATASET["key"]: active_headcount_detail.DATASET,
    active_headcount_30d_total.DATASET["key"]: active_headcount_30d_total.DATASET,
    active_headcount_30d_detail.DATASET["key"]: active_headcount_30d_detail.DATASET,
    inactive_candidates_detail.DATASET["key"]: inactive_candidates_detail.DATASET,
    recruiting_upfront.DATASET["key"]: recruiting_upfront.DATASET,
    client_lifetime_detail.DATASET["key"]: client_lifetime_detail.DATASET,
    client_lifetime_avg.DATASET["key"]: client_lifetime_avg.DATASET,
    candidate_lifetime_detail.DATASET["key"]: candidate_lifetime_detail.DATASET,
    candidate_lifetime_avg.DATASET["key"]: candidate_lifetime_avg.DATASET,
    arpa_history.DATASET["key"]: arpa_history.DATASET,
    arpc_history.DATASET["key"]: arpc_history.DATASET,
    acpa_history.DATASET["key"]: acpa_history.DATASET,
    nda_to_clients_history.DATASET["key"]: nda_to_clients_history.DATASET,
    nda_to_clients_detail.DATASET["key"]: nda_to_clients_detail.DATASET,
    nda_to_clients_30d_summary.DATASET["key"]: nda_to_clients_30d_summary.DATASET,
    nda_to_clients_30d_detail.DATASET["key"]: nda_to_clients_30d_detail.DATASET,
    nda_lead_source_month.DATASET["key"]: nda_lead_source_month.DATASET,
    nda_lead_source_30d.DATASET["key"]: nda_lead_source_30d.DATASET,
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
