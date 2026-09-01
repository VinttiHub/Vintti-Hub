"""Position Lifetime — una fila por posición (Staffing).

Alimenta la tabla de la sección y el drawer. Usa la MISMA `CHAIN_CTES` y la misma
`lifetime_window` que `position_lifetime_summary`, así `positions_total` del KPI
siempre coincide con la cantidad de filas de acá.
"""
from __future__ import annotations

from datetime import date

from ._now import today_ar
from ._position_chains import CHAIN_CTES, WINDOW_FILTER, lifetime_window, scope_filter


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )
    win_ini, win_fin = lifetime_window(filters, corte)
    scope_sql, _scope = scope_filter(filters)

    sql = "WITH RECURSIVE " + CHAIN_CTES + """,
        en_ventana_full AS (
          SELECT p.*
          FROM posiciones p
""" + WINDOW_FILTER + """
        ),
        -- Mismo scope que el summary (toggle Todas / Activas / Cerradas).
        en_ventana AS (
          SELECT * FROM en_ventana_full
""" + scope_sql + """
        ),
        -- Quiénes ocuparon el asiento, en orden de entrada.
        ocupantes AS (
          SELECT
            ch.root_opp,
            STRING_AGG(COALESCE(c.name, '—'), ' → ' ORDER BY h.start_d, h.candidate_id) AS contractors
          FROM chain ch
          JOIN hires h ON h.opportunity_id = ch.opp
          LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
          GROUP BY ch.root_opp
        )
        SELECT
          v.root_opp::text                      AS opportunity_id,
          v.client_name,
          COALESCE(NULLIF(TRIM(v.position_name), ''), '—') AS position_name,
          v.estado,
          TO_CHAR(v.pos_start, 'YYYY-MM-DD')    AS start_date,
          COALESCE(TO_CHAR(v.pos_end, 'YYYY-MM-DD'), '—') AS end_date,
          v.months,
          v.n_contractors,
          v.n_replacements,
          COALESCE(o.contractors, '—')          AS contractors,
          COALESCE(TO_CHAR(v.close_d, 'YYYY-MM-DD'), '—') AS close_date
        FROM en_ventana v
        LEFT JOIN ocupantes o ON o.root_opp = v.root_opp
        ORDER BY v.months DESC, v.client_name, v.position_name;
    """

    return sql, {"corte": corte, "win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "position_lifetime_detail",
    "label": "Position Lifetime — Detalle por posición (Staffing)",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity raíz", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "position_name", "label": "Posición", "type": "string"},
        {"key": "estado", "label": "Estado", "type": "string"},
        {"key": "start_date", "label": "Inicio", "type": "date"},
        {"key": "end_date", "label": "Fin", "type": "date"},
        {"key": "contractors", "label": "Ocupantes", "type": "string"},
        {"key": "close_date", "label": "Close date (opp)", "type": "date"},
    ],
    "measures": [
        {"key": "months", "label": "Vida (meses)", "type": "number"},
        {"key": "n_contractors", "label": "Contractors", "type": "number"},
        {"key": "n_replacements", "label": "Reemplazos", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
