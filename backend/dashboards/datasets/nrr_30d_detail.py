from __future__ import annotations

from ._periods import window_bounds
from ._mrr_staffing import HIRES_FULL_CTE, unit_snapshot
from ._nrr_decomp import decomp_cte, upsell_population

# La base es el snapshot al CIERRE DEL DIA ANTERIOR al inicio de la ventana, igual que
# `prev_end` en la serie mensual: asi, al elegir un mes, esta card da exactamente el
# mismo numero que el punto de ese mes en el chart. Anclarla al primer dia de la ventana
# dejaba una diferencia de un dia entre las dos lecturas.
D_INI = "(%(win_ini)s::date - 1)"
D_FIN = "%(win_fin)s::date"

def unit_info_cte(src: str = "hires_full", close_col: str = "opp_close_d") -> str:
    """Datos de la unidad para pintar la fila: los de su hire mas reciente.

    `close_col` es como se llama la fecha de Close Win en el CTE base (`opp_close_d` en
    `hires_full`, `close_d` en `hires`). Hace falta en el drawer porque hay componentes
    que se explican por esa fecha y no por el start: el upsell se cuenta por Close Win, y
    el M3 del AE vence a los 3 meses del Close Win. Mostrando solo el start, las filas
    parecen fuera de periodo (la owner lo pregunto el 2026-09-22 viendo starts de mayo en
    la ventana de septiembre).
    """
    return f"""
        unit_info AS (
          SELECT DISTINCT ON (h.candidate_id, h.account_id)
            h.candidate_id, h.account_id, h.start_d, h.end_d, h.inactive_reason,
            h.{close_col} AS close_d,
            (h.{close_col} + INTERVAL '3 months')::date AS m3_d
          FROM {src} h
          ORDER BY h.candidate_id, h.account_id, h.start_d DESC NULLS LAST
        )"""

# El SELECT del drawer. Sale de `nrr_rows`, el MISMO CTE que agrega la card: por eso
# la suma de `monto` por componente da exactamente el campo homonimo del resumen.
DETAIL_SELECT = """
        SELECT
          TO_CHAR({mes}, 'YYYY-MM-DD')        AS mes,
          r.componente,
          COALESCE(a.client_name, '')         AS client_name,
          COALESCE(c.name, '')                AS candidate_name,
          r.opportunity_id,
          TO_CHAR(u.start_d, 'YYYY-MM-DD')    AS start_d,
          TO_CHAR(u.end_d,   'YYYY-MM-DD')    AS end_d,
          TO_CHAR(u.close_d, 'YYYY-MM-DD')    AS close_date,
          TO_CHAR(u.m3_d,    'YYYY-MM-DD')    AS entra_el,
          u.inactive_reason,
          r.monto::float                      AS monto,
          r.monto_ini::float                  AS monto_ini,
          r.monto_fin::float                  AS monto_fin
        FROM nrr_rows r
        LEFT JOIN candidates c ON c.candidate_id = r.candidate_id
        LEFT JOIN account    a ON a.account_id   = r.account_id
        LEFT JOIN unit_info  u ON u.candidate_id = r.candidate_id
                              AND u.account_id   = r.account_id
        ORDER BY r.componente, client_name, candidate_name, r.opportunity_id;"""

DIMENSIONS = [
    {"key": "mes", "label": "Mes", "type": "date"},
    {"key": "componente", "label": "Componente", "type": "string"},
    {"key": "client_name", "label": "Cliente", "type": "string"},
    {"key": "candidate_name", "label": "Candidato", "type": "string"},
    {"key": "opportunity_id", "label": "Opportunity", "type": "string"},
    {"key": "start_d", "label": "Start", "type": "date"},
    {"key": "end_d", "label": "End", "type": "date"},
    {"key": "close_date", "label": "Close Win", "type": "date"},
    {"key": "entra_el", "label": "Entra al AM", "type": "date"},
    {"key": "inactive_reason", "label": "Motivo", "type": "string"},
]

MEASURES = [
    {"key": "monto", "label": "Monto", "type": "currency"},
    {"key": "monto_ini", "label": "Antes", "type": "currency"},
    {"key": "monto_fin", "label": "Ahora", "type": "currency"},
]


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

    sql = f"""
        WITH {HIRES_FULL_CTE},
        {unit_info_cte()},
        {unit_snapshot('unit_ini', D_INI)},
        {unit_snapshot('unit_fin', D_FIN)},
        {unit_snapshot('unit_ups', D_FIN, upsell_population(D_INI, D_FIN))},
        {decomp_cte('unit_ini', 'unit_fin', 'unit_ups', 'hires_full', D_INI, D_FIN)}
        {DETAIL_SELECT.format(mes=D_FIN)}
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "metric": metric}


DATASET = {
    "key": "nrr_30d_detail",
    "label": "NRR (Staffing) — Detalle ventana 30 días",
    "dimensions": DIMENSIONS,
    "measures": MEASURES,
    "default_filters": {},
    "query": query,
}
