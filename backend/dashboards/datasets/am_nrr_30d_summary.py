"""NRR del AM: el mismo NRR, contando solo lo que ya es del Account Manager.

Misma descomposicion que `nrr_30d_summary` (`_nrr_decomp`), pero sobre el motor del tab
Account Management (`_am_mrr_staffing`), que excluye las vacantes todavia dentro de los
3 meses posteriores al Close Win de un AE.

Lo que entra al libro del AM porque vencio ese M3 NO cuenta como expansion: sale aparte
en `entradas_m3`, fuera del cociente. Es un traspaso del AE, no algo que hizo el AM.
"""
from __future__ import annotations

from ._periods import window_bounds
from ._am_mrr_staffing import HIRES_CTE, ae_leads, am_unit_snapshot
from ._nrr_decomp import (
    MEASURES_AM,
    base_label_sql,
    decomp_cte,
    summary_columns,
    upsell_population,
)

# La base es el snapshot al CIERRE DEL DIA ANTERIOR al inicio de la ventana, igual que
# `prev_end` en la serie mensual: asi, al elegir un mes, esta card da exactamente el
# mismo numero que el punto de ese mes en el chart. Anclarla al primer dia de la ventana
# dejaba una diferencia de un dia entre las dos lecturas.
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
    am = str(filters.get("am") or "").strip().lower()
    win_ini, win_fin = window_bounds(filters)

    sql = f"""
        WITH {HIRES_CTE},
        {am_unit_snapshot('unit_ini', D_INI)},
        {am_unit_snapshot('unit_fin', D_FIN)},
        {am_unit_snapshot('unit_ups', D_FIN, upsell_population(D_INI, D_FIN, col='close_d'))},
        {decomp_cte('unit_ini', 'unit_fin', 'unit_ups', 'hires',
                    D_INI, D_FIN, owned=True)}
        SELECT
          TO_CHAR({D_INI}, 'YYYY-MM-DD') AS win_ini,
          {base_label_sql(D_INI)}        AS base_fecha,
          TO_CHAR({D_FIN}, 'YYYY-MM-DD') AS win_fin,
          {summary_columns(owned=True)}
        FROM nrr_rows;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
        "metric": metric,
        "am": am,
        "ae_leads": ae_leads(),
    }


DATASET = {
    "key": "am_nrr_30d_summary",
    "label": "NRR del AM — Ventana 30 días",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio", "type": "date"},
        {"key": "win_fin", "label": "Fin", "type": "date"},
        {"key": "base_fecha", "label": "Base al", "type": "string"},
    ],
    "measures": MEASURES_AM,
    "default_filters": {},
    "query": query,
}
