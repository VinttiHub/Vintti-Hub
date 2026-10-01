"""Churn → Replacement: de las bajas reales de la ventana, cuántas abrieron replacement.

El universo es EXACTAMENTE el `bajas_real` de candidate_churn_30d_summary (misma
ventana, misma regla de buyout, misma suma inicio + starts), así la card cuadra
con "Churn contractors". Una baja "abrió replacement" si existe una opp
`opp_type='Replacement'` de la misma cuenta con `replacement_of = candidate_id`,
en cualquier stage (también Closed Lost / Stop) y sin importar si se abrió antes
de la baja (preaviso) o después — decisión de la owner, 2026-10-01.
"""
from __future__ import annotations

from ._now import today_ar
from .candidate_churn_30d_summary import _parse_date, _window_bounds


# Mismos CTE que candidate_churn_30d_summary (+ el flag de replacement por hire).
CANDIDATOS_CTE = """
        ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        candidatos AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
                THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d,
            EXISTS (
              SELECT 1 FROM opportunity ro
              WHERE ro.opp_type = 'Replacement'
                AND ro.account_id = ho.account_id
                AND NULLIF(TRIM(ro.replacement_of::text), '') = ho.candidate_id::text
            ) AS con_replacement
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        )
"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = "WITH" + CANDIDATOS_CTE + """,
        -- Una fila por candidato en cada rama, como el COUNT(DISTINCT) del summary
        -- de churn. Si el candidato tuvo más de un hire, basta un replacement.
        bajas_inicio AS (
          SELECT c.candidate_id, BOOL_OR(c.con_replacement) AS con_replacement
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.start_d <= v.win_ini
            AND c.end_d BETWEEN v.win_ini AND v.win_fin
            AND NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
          GROUP BY c.candidate_id
        ),
        bajas_starts AS (
          SELECT c.candidate_id, BOOL_OR(c.con_replacement) AS con_replacement
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d BETWEEN v.win_ini AND v.win_fin
            AND c.end_d   BETWEEN v.win_ini AND v.win_fin
            AND NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
          GROUP BY c.candidate_id
        ),
        bajas AS (
          SELECT con_replacement FROM bajas_inicio
          UNION ALL
          SELECT con_replacement FROM bajas_starts
        ),
        totals AS (
          SELECT
            COUNT(*)::int AS bajas_real,
            COUNT(*) FILTER (WHERE con_replacement)::int AS con_replacement
          FROM bajas
        )
        SELECT
          bajas_real,
          con_replacement,
          (bajas_real - con_replacement)::int AS sin_replacement,
          -- Sin bajas da 0 y no NULL: así se lee igual que las otras cards de churn.
          COALESCE(ROUND((con_replacement::numeric / NULLIF(bajas_real, 0)) * 100, 2), 0)::float AS replacement_pct
        FROM totals;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "churn_replacement_summary",
    "label": "Churn → Replacement (Staffing) — Resumen por ventana",
    "dimensions": [],
    "measures": [
        {"key": "bajas_real", "label": "Bajas reales", "type": "number"},
        {"key": "con_replacement", "label": "Abrieron replacement", "type": "number"},
        {"key": "sin_replacement", "label": "Sin replacement", "type": "number"},
        {"key": "replacement_pct", "label": "% con replacement", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
