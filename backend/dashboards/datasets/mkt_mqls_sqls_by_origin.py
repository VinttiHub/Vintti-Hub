"""Marketing · MQLs y SQLs por origin (combinado, barras agrupadas).

Combina `mkt_sqls_by_origin` (Postgres) + `mkt_mqls_by_origin` (live HubSpot) en
formato largo: dos filas por origin (serie 'MQLs' y serie 'SQLs') para el render
de barras agrupadas (grouped-bars). Reusa ambos datasets tal cual → misma ventana,
mismo período y misma exclusión de outbound en cada uno.
"""
from __future__ import annotations


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    # Import lazy: evita el ciclo datasets <-> executor al registrar.
    from dashboards.executor import run_dataset

    f = filters or {}
    sql_rows = run_dataset("mkt_sqls_by_origin", f) or []
    mql_rows = run_dataset("mkt_mqls_by_origin", f) or []

    period_label = (
        (sql_rows[0].get("period_label") if sql_rows else None)
        or (mql_rows[0].get("period_label") if mql_rows else None)
        or "Mes"
    )

    sqls = {r["origin"]: int(r.get("count") or 0) for r in sql_rows}
    mqls = {r["origin"]: int(r.get("count") or 0) for r in mql_rows}

    # Unión de origins, ordenada por total (MQL + SQL) desc.
    origins = list(dict.fromkeys([*mqls.keys(), *sqls.keys()]))
    origins.sort(key=lambda o: -(mqls.get(o, 0) + sqls.get(o, 0)))

    rows: list[dict] = []
    for o in origins:
        rows.append({"origin": o, "serie": "MQLs", "value": mqls.get(o, 0), "period_label": period_label})
        rows.append({"origin": o, "serie": "SQLs", "value": sqls.get(o, 0), "period_label": period_label})
    return rows


DATASET = {
    "key": "mkt_mqls_sqls_by_origin",
    "label": "Marketing · MQLs y SQLs por origin (combinado, período)",
    "dimensions": [
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "serie", "label": "Serie", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "value", "label": "Cantidad", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "compute": compute,
}
