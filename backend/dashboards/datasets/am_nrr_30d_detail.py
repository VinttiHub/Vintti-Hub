"""Drawer del NRR del AM. Sale del MISMO `nrr_rows` que la card."""
from __future__ import annotations

from ._periods import window_bounds
from ._am_mrr_staffing import HIRES_CTE, ae_leads, am_unit_snapshot
from ._nrr_decomp import decomp_cte, upsell_population
from .nrr_30d_detail import DETAIL_SELECT, DIMENSIONS, MEASURES, unit_info_cte

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
        {unit_info_cte('hires', close_col='close_d')},
        {am_unit_snapshot('unit_ini', D_INI)},
        {am_unit_snapshot('unit_fin', D_FIN)},
        {am_unit_snapshot('unit_ups', D_FIN, upsell_population(D_INI, D_FIN, col='close_d'))},
        {decomp_cte('unit_ini', 'unit_fin', 'unit_ups', 'hires',
                    D_INI, D_FIN, owned=True)}
        {DETAIL_SELECT.format(mes=D_FIN)}
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
        "metric": metric,
        "am": am,
        "ae_leads": ae_leads(),
    }


DATASET = {
    "key": "am_nrr_30d_detail",
    "label": "NRR del AM — Detalle ventana 30 días",
    "dimensions": DIMENSIONS,
    "measures": MEASURES,
    "default_filters": {},
    "query": query,
}
