from __future__ import annotations

from ._periods import window_bounds
from ._mrr_staffing import HIRES_FULL_CTE, unit_snapshot
from ._nrr_decomp import (
    MEASURES,
    base_label_sql,
    decomp_cte,
    summary_columns,
    upsell_population,
)

# La base es el snapshot al CIERRE DEL DIA ANTERIOR al inicio de la ventana, igual que
# `prev_end` en la serie mensual: asi, al elegir un mes, esta card da exactamente el
# mismo numero que el punto de ese mes en el chart. Anclarla al primer dia de la ventana
# dejaba una diferencia de un dia entre las dos lecturas.
# Los dos snapshots van con `exclude_end_day=True`: quien termina justo en D_INI (baja
# del 30-sep) no entra en la base de octubre, y quien termina en D_FIN ya no esta al
# cierre. Asi la baja cae en su propio mes, como en el CRR y en Client churn.
D_INI = "(%(win_ini)s::date - 1)"
D_FIN = "%(win_fin)s::date"


def _norm_metric(value) -> str:
    raw = str(value or "").strip().lower()
    if raw == "fee":
        return "Fee"
    if raw == "revenue":
        return "Revenue"
    return "All"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    metric = _norm_metric(filters.get("metric"))
    win_ini, win_fin = window_bounds(filters)

    # R5: el NRR corre sobre el MOTOR CANONICO de MRR (el mismo de Management /
    # `mrr_history`): MRR efectivo por (candidato, cuenta) con dedup de opp primaria +
    # `salary_updates`, para que "MRR inicial" reconcilie EXACTO con el GMRR de
    # Management. Los tres snapshots y la descomposicion en componentes viven en
    # `_nrr_decomp.decomp_cte()`, compartidos con el drawer: la suma del detalle da
    # este mismo numero por construccion.
    sql = f"""
        WITH {HIRES_FULL_CTE},
        {unit_snapshot('unit_ini', D_INI, exclude_end_day=True)},
        {unit_snapshot('unit_fin', D_FIN, exclude_end_day=True)},
        {unit_snapshot('unit_ups', D_FIN, upsell_population(D_INI, D_FIN))},
        {decomp_cte('unit_ini', 'unit_fin', 'unit_ups', 'hires_full', D_INI, D_FIN)}
        SELECT
          TO_CHAR({D_INI}, 'YYYY-MM-DD') AS win_ini,
          {base_label_sql(D_INI)}        AS base_fecha,
          TO_CHAR({D_FIN}, 'YYYY-MM-DD') AS win_fin,
          {summary_columns()}
        FROM nrr_rows;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "metric": metric}


DATASET = {
    "key": "nrr_30d_summary",
    "label": "NRR (Staffing) — Ventana 30 días",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio", "type": "date"},
        {"key": "win_fin", "label": "Fin", "type": "date"},
        {"key": "base_fecha", "label": "Base al", "type": "string"},
    ],
    "measures": MEASURES,
    "default_filters": {},
    "query": query,
}
