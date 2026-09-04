"""Cadenas de posición (asientos) — CTEs compartidas por position_lifetime_*.

Una "posición" no existe como tabla: es el ASIENTO que el cliente nos paga, y
sobrevive a los cambios de persona. Se reconstruye encadenando opportunities:

  - Un reemplazo es una opportunity NUEVA con `opp_type = 'Replacement'` y
    `replacement_of = <candidate_id que se fue>`. Ojo: `replacement_of` guarda un
    CANDIDATE_ID, no un opportunity_id (ver replacements_detail.py).
  - Arista padre→hijo: `hijo.replacement_of = padre.candidate_id`
    AND `hijo.account_id = padre.account_id` (el mismo candidato puede haber
    trabajado en más de una cuenta).
  - Raíz de cadena: un hire que no es hijo de nadie.

La vida de la posición va desde que arranca el PRIMER contractor de la cadena
hasta que se va el ÚLTIMO sin reemplazo. Los huecos entre que uno se va y entra
el reemplazo cuentan como activos: la posición sigue siendo nuestra.

Por qué el ancla es `start_d` y no `opp_close_date`: de los 233 hires Staffing,
40 arrancan ANTES de su close date (uno 741 días antes) y 4 no tienen close date
— usar el close date daría vidas negativas en ~17% de las posiciones. El close
date se expone igual como columna informativa.

`start_d` / `end_d` son el idiom canónico de todo el dashboard (ver
candidate_lifetime_detail.py). `WHERE start_d IS NOT NULL` descarta las filas
fantasma que crea el formulario público de reference checks.
"""
from __future__ import annotations

from datetime import date

from ._periods import window_bounds

# Estados posibles de una posición (orden de precedencia en el CASE de abajo):
#   Activa       — algún hire de la cadena sigue sin end_d
#   En reemplazo — la silla quedó vacía pero hay un Replacement abierto en pipeline
#   Buyout       — el cliente se llevó al contractor (no es churn real)
#   Cerrada      — se terminó
ESTADOS = ("Activa", "En reemplazo", "Buyout", "Cerrada")

# Guarda de recursión: la cadena más larga observada tiene profundidad 3; 12 deja
# margen de sobra y evita un loop infinito si alguna vez se cargan datos cíclicos.
_MAX_DEPTH = 12

# Stages que NO cuentan como "reemplazo abierto" (ya se decidieron o se abandonó).
_CLOSED_STAGES = "('Close Win', 'Closed Lost', 'Stop', '')"

# Bloque WITH RECURSIVE compartido. El dataset que lo use arranca con
# `WITH RECURSIVE ` + CHAIN_CTES + su propio SELECT (o CTEs extra encadenadas).
# Params requeridos: %(corte)s. El filtro de ventana lo aplica cada dataset sobre
# la CTE `posiciones` con WINDOW_FILTER.
CHAIN_CTES = """
        hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(CAST(ho.start_date AS TEXT), '') IS NOT NULL
                THEN NULLIF(CAST(ho.start_date AS TEXT), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR CAST(ho.end_date AS TEXT) = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
                THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d,
            o.replacement_of,
            o.opp_position_name,
            NULLIF(o.opp_close_date::text, '')::date AS close_d,
            a.client_name
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE ho.candidate_id IS NOT NULL
            AND ho.account_id IS NOT NULL
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(CAST(ho.start_date AS TEXT), '') IS NOT NULL
            )
            AND o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        edges AS (
          SELECT
            p.opportunity_id AS parent_opp,
            s.opportunity_id AS child_opp
          FROM hires p
          JOIN hires s
            ON s.replacement_of = p.candidate_id
           AND s.account_id     = p.account_id
           AND s.opportunity_id <> p.opportunity_id
        ),
        roots AS (
          SELECT h.opportunity_id
          FROM hires h
          WHERE NOT EXISTS (SELECT 1 FROM edges e WHERE e.child_opp = h.opportunity_id)
        ),
        chain AS (
          SELECT r.opportunity_id AS root_opp, r.opportunity_id AS opp, 1 AS depth
          FROM roots r
          UNION ALL
          SELECT ch.root_opp, e.child_opp, ch.depth + 1
          FROM chain ch
          JOIN edges e ON e.parent_opp = ch.opp
          WHERE ch.depth < __MAX_DEPTH__
        ),
        open_repl AS (
          SELECT DISTINCT ch.root_opp
          FROM chain ch
          JOIN hires h ON h.opportunity_id = ch.opp
          JOIN opportunity ro
            ON ro.replacement_of = h.candidate_id
           AND ro.account_id     = h.account_id
          WHERE ro.opp_type = 'Replacement'
            AND TRIM(COALESCE(ro.opp_stage, '')) NOT IN __CLOSED_STAGES__
        ),
        agg AS (
          SELECT
            ch.root_opp,
            MIN(h.start_d) AS pos_start,
            -- Si algún hire de la cadena sigue activo, la posición no tiene fin.
            CASE WHEN BOOL_OR(h.end_d IS NULL) THEN NULL ELSE MAX(h.end_d) END AS pos_end,
            COUNT(DISTINCT h.candidate_id) AS n_contractors,
            BOOL_OR(h.buyout_d IS NOT NULL) AS any_buyout
          FROM chain ch
          JOIN hires h ON h.opportunity_id = ch.opp
          GROUP BY ch.root_opp
        ),
        posiciones AS (
          SELECT
            g.root_opp,
            r.client_name,
            r.opp_position_name AS position_name,
            r.close_d,
            g.pos_start,
            g.pos_end,
            g.n_contractors,
            (g.n_contractors - 1) AS n_replacements,
            CASE
              WHEN g.pos_end IS NULL              THEN 'Activa'
              WHEN orp.root_opp IS NOT NULL       THEN 'En reemplazo'
              WHEN g.any_buyout                   THEN 'Buyout'
              ELSE 'Cerrada'
            END AS estado,
            -- Vida en meses, con un decimal. Los huecos entre contractors cuentan:
            -- la posición sigue siendo nuestra mientras haya (o se busque) alguien.
            ROUND(
              ((COALESCE(g.pos_end, %(corte)s::date) - g.pos_start)::numeric / 30.44),
              1
            ) AS months
          FROM agg g
          JOIN hires r ON r.opportunity_id = g.root_opp
          LEFT JOIN open_repl orp ON orp.root_opp = g.root_opp
          WHERE g.pos_start IS NOT NULL
        )
""".replace("__MAX_DEPTH__", str(_MAX_DEPTH)).replace("__CLOSED_STAGES__", _CLOSED_STAGES)


# Filtro de ventana compartido. Una posición entra si estuvo VIVA en algún momento
# del rango (no si cerró dentro): si filtráramos por fecha de cierre, el promedio
# se vaciaría al elegir un mes y las posiciones activas nunca aparecerían.
WINDOW_FILTER = """
          WHERE p.pos_start <= %(win_fin)s::date
            AND (p.pos_end IS NULL OR p.pos_end >= %(win_ini)s::date)
"""

# Piso de madurez para el scope "activas" (decisión de la dueña, 2026-09-01).
# Una posición que arrancó hace 3 semanas entra al promedio con 0,7 meses y lo tira
# abajo, pero no dice NADA sobre cuánto va a durar: todavía no tuvo tiempo de durar.
# Con el corte en 3 meses el promedio de activas mide posiciones ya asentadas.
# Sólo aplica a "activas": en cerradas un asiento de 1 mes SÍ es información real
# (duró un mes de verdad), y el total queda como el universo completo sin recortes.
_ACTIVE_MIN_MONTHS = 3

# Scope de la sección Position Lifetime: todas / sólo activas / sólo cerradas.
# "Activa" incluye "En reemplazo" (la silla sigue siendo nuestra); "cerrada" incluye
# Buyout (el asiento terminó igual, aunque no sea churn real).
# OJO con las activas: su reloj sigue corriendo, así que su vida es un PISO, no el
# total final — por eso el promedio de activas y el de cerradas no son comparables.
_SCOPE_SQL = {
    # 'all' aplica el MISMO piso de madurez que 'active': si no, el total cuenta
    # activas de 1 mes que la card de Activas deja afuera, y los tres numeros
    # dejan de cerrar entre si (activas 77 + cerradas 115 != total 210). El piso
    # NO se aplica a las cerradas: una posicion que duro un mes y termino tiene
    # una vida real de un mes, y sacarla falsearia el promedio hacia arriba.
    "all": (
        "          WHERE estado NOT IN ('Activa', 'En reemplazo')\n"
        f"             OR months >= {_ACTIVE_MIN_MONTHS}\n"
    ),
    "active": (
        "          WHERE estado IN ('Activa', 'En reemplazo')\n"
        f"            AND months >= {_ACTIVE_MIN_MONTHS}\n"
    ),
    "closed": "          WHERE estado NOT IN ('Activa', 'En reemplazo')\n",
}

# SQL del recorte de madurez, para que el summary pueda contar cuántas activas quedan
# afuera. Vive acá para que el umbral se toque en UN solo lugar.
ACTIVE_YOUNG_SQL = (
    f"estado IN ('Activa', 'En reemplazo') AND months < {_ACTIVE_MIN_MONTHS}"
)
ACTIVE_MIN_MONTHS = _ACTIVE_MIN_MONTHS

_SCOPE_ALIASES = {
    "active": "active", "activa": "active", "activas": "active", "abiertas": "active",
    "closed": "closed", "cerrada": "closed", "cerradas": "closed",
}


def scope_filter(filters: dict | None) -> tuple[str, str]:
    """WHERE por estado para la CTE ya filtrada por ventana.

    Devuelve (sql, scope). Summary y detail DEBEN usar el mismo: si divergen, la
    card y la tabla dejan de reconciliar (mismo criterio que `lifetime_window`).
    """
    filters = filters or {}
    raw = str(filters.get("pos_scope") or filters.get("scope") or "all").strip().lower()
    scope = _SCOPE_ALIASES.get(raw, "all")
    return _SCOPE_SQL[scope], scope


def lifetime_window(filters: dict | None, corte: date) -> tuple[date, date]:
    """Ventana de la métrica: ALL-TIME por defecto, acotada si el usuario filtra.

    `window_bounds` sin filtros devuelve un rolling de 30d, y eso acá miente: una
    "vida promedio" que sólo mira las posiciones vivas en los últimos 30 días deja
    afuera todas las cerradas y da 9,2 meses sobre 101 posiciones en vez de 7,7
    sobre 208. Las otras cards de lifetime del dashboard (client_lifetime_avg,
    candidate_lifetime_avg) hacen lo mismo: no aplican default de 30d.

    Con Desde/Hasta o Mes cargados sí delega en `window_bounds`, así la sección
    responde a la barra de filtros como el resto del tab.

    Summary y detail DEBEN llamar a esta misma función: si divergen, la card y el
    drawer muestran números distintos.
    """
    filters = filters or {}
    if filters.get("desde") or filters.get("hasta") or filters.get("mes"):
        return window_bounds(filters)
    return date(1900, 1, 1), corte
