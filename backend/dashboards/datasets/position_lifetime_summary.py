"""Position Lifetime — KPI de cuánto vive un asiento (Staffing).

Es el LTV de la POSICIÓN, no el del candidato ni el del cliente: si un contractor
se va y entra un reemplazo, la posición sigue viva y la vida sigue corriendo.
La cadena de reemplazos la arma `_position_chains.CHAIN_CTES`.

Ventana: `lifetime_window` — all-time por defecto, acotada si hay Desde/Hasta o Mes.
El detail usa exactamente la misma: si divergen, card y drawer no reconcilian.
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
    scope_sql, scope = scope_filter(filters)
    # El drawer muestra qué recorte está mirando; que salga del dataset evita que la
    # etiqueta y los números se desincronicen.
    scope_label = {
        "all": "Activas + cerradas",
        "active": "Sólo activas",
        "closed": "Sólo cerradas",
    }[scope]

    sql = "WITH RECURSIVE " + CHAIN_CTES + """,
        en_ventana AS (
          SELECT p.*
          FROM posiciones p
""" + WINDOW_FILTER + """
        ),
        -- Scope del toggle de la sección (todas / activas / cerradas). Vacío = todas.
        en_scope AS (
          SELECT * FROM en_ventana
""" + scope_sql + """
        )
        SELECT
          %(scope)s::text                                                 AS scope,
          %(scope_label)s::text                                           AS scope_label,
          COUNT(*)::int                                                   AS positions_total,
          COUNT(*) FILTER (WHERE estado IN ('Activa', 'En reemplazo'))::int AS positions_active,
          COUNT(*) FILTER (WHERE estado NOT IN ('Activa', 'En reemplazo'))::int AS positions_closed,
          ROUND(AVG(months), 1)::float                                    AS avg_months,
          ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY months)::numeric, 1)::float
                                                                          AS median_months,
          ROUND(AVG(months) FILTER (WHERE estado NOT IN ('Activa', 'En reemplazo')), 1)::float
                                                                          AS avg_months_closed,
          ROUND(MAX(months), 1)::float                                    AS max_months,
          -- Máximo SOLO entre cerradas: el max_months global suele ser una posición
          -- todavía activa, y ponerlo al lado de "vida promedio cerradas" hacía leer
          -- que esa fue la cerrada más larga (31,4 mo era Wilson, que sigue activa).
          ROUND(MAX(months) FILTER (WHERE estado NOT IN ('Activa', 'En reemplazo')), 1)::float
                                                                          AS max_months_closed,
          COALESCE(SUM(n_replacements), 0)::int                           AS replacements_total,
          COUNT(*) FILTER (WHERE n_replacements > 0)::int                 AS positions_with_replacement,
          -- Desglose: explica por qué "reemplazos totales" > "posiciones con reemplazo".
          COUNT(*) FILTER (WHERE n_replacements = 1)::int                 AS positions_repl_1,
          COUNT(*) FILTER (WHERE n_replacements >= 2)::int                AS positions_repl_2plus,
          COUNT(*) FILTER (WHERE n_replacements = 0)::int                 AS positions_without_replacement,
          ROUND(
            CASE
              WHEN COUNT(*) = 0 THEN NULL
              ELSE 100.0 * COUNT(*) FILTER (WHERE n_replacements > 0)::numeric / COUNT(*)
            END, 1
          )::float                                                        AS pct_with_replacement,
          -- Distribución para las barras del drawer.
          COUNT(*) FILTER (WHERE months < 3)::int                         AS bucket_0_3,
          COUNT(*) FILTER (WHERE months >= 3 AND months < 6)::int         AS bucket_3_6,
          COUNT(*) FILTER (WHERE months >= 6 AND months < 12)::int        AS bucket_6_12,
          COUNT(*) FILTER (WHERE months >= 12)::int                       AS bucket_12_plus,
          -- Los bins también como porcentaje: el bind `progress-fill` del drawer lee
          -- el valor como 0-100 directo, no como conteo. (Ojo: un signo de
          -- porcentaje literal acá rompe el parseo de params de psycopg2.)
          ROUND(100.0 * COUNT(*) FILTER (WHERE months < 3)::numeric
                / NULLIF(COUNT(*), 0), 1)::float                          AS bucket_0_3_pct,
          ROUND(100.0 * COUNT(*) FILTER (WHERE months >= 3 AND months < 6)::numeric
                / NULLIF(COUNT(*), 0), 1)::float                          AS bucket_3_6_pct,
          ROUND(100.0 * COUNT(*) FILTER (WHERE months >= 6 AND months < 12)::numeric
                / NULLIF(COUNT(*), 0), 1)::float                          AS bucket_6_12_pct,
          ROUND(100.0 * COUNT(*) FILTER (WHERE months >= 12)::numeric
                / NULLIF(COUNT(*), 0), 1)::float                          AS bucket_12_plus_pct
        FROM en_scope;
    """

    return sql, {"corte": corte, "win_ini": win_ini, "win_fin": win_fin,
                 "scope": scope, "scope_label": scope_label}


DATASET = {
    "key": "position_lifetime_summary",
    "label": "Position Lifetime — Vida promedio de la posición (Staffing)",
    "dimensions": [
        {"key": "scope", "label": "Scope (all / active / closed)", "type": "string"},
        {"key": "scope_label", "label": "Scope (etiqueta)", "type": "string"},
    ],
    "measures": [
        {"key": "avg_months", "label": "Vida promedio (meses)", "type": "number"},
        {"key": "median_months", "label": "Mediana (meses)", "type": "number"},
        {"key": "avg_months_closed", "label": "Vida promedio — sólo cerradas", "type": "number"},
        {"key": "max_months", "label": "Vida máxima (meses)", "type": "number"},
        {"key": "max_months_closed", "label": "Vida máxima — sólo cerradas", "type": "number"},
        {"key": "positions_total", "label": "Posiciones", "type": "number"},
        {"key": "positions_active", "label": "Posiciones activas", "type": "number"},
        {"key": "positions_closed", "label": "Posiciones cerradas", "type": "number"},
        {"key": "positions_with_replacement", "label": "Posiciones con reemplazo", "type": "number"},
        {"key": "positions_repl_1", "label": "Posiciones reemplazadas 1 vez", "type": "number"},
        {"key": "positions_repl_2plus", "label": "Posiciones reemplazadas 2+ veces", "type": "number"},
        {"key": "positions_without_replacement", "label": "Posiciones sin reemplazo", "type": "number"},
        {"key": "pct_with_replacement", "label": "% posiciones con reemplazo", "type": "percent"},
        {"key": "replacements_total", "label": "Reemplazos totales", "type": "number"},
        {"key": "bucket_0_3", "label": "0-3 meses", "type": "number"},
        {"key": "bucket_3_6", "label": "3-6 meses", "type": "number"},
        {"key": "bucket_6_12", "label": "6-12 meses", "type": "number"},
        {"key": "bucket_12_plus", "label": "12+ meses", "type": "number"},
        {"key": "bucket_0_3_pct", "label": "% 0-3 meses", "type": "percent"},
        {"key": "bucket_3_6_pct", "label": "% 3-6 meses", "type": "percent"},
        {"key": "bucket_6_12_pct", "label": "% 6-12 meses", "type": "percent"},
        {"key": "bucket_12_plus_pct", "label": "% 12+ meses", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
