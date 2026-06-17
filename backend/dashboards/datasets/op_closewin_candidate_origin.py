"""Operations · % de close wins por origen del candidato (Hunteo vs Applicant).

Sobre los close-win placements (hire_opportunity de opps Close Win), clasifica el
`candidates.candidate_origin`:
  - 'Hunteo'                          → Hunteo (hunteado)
  - 'Applicant' / 'Talentum applicant' → Applicant (postulado)
  - vacío / otros                     → (Sin origen)
Denominador = TODOS los close-win placements (incluye los sin origen). Para un donut.
"""
from __future__ import annotations

from ._periods import window_bounds

# CASE compartido (donut + detalle): normaliza candidate_origin a su categoría.
ORIGIN_CASE = """
    CASE
      WHEN LOWER(TRIM({col})) = 'hunteo'                            THEN 'Hunteo'
      WHEN LOWER(TRIM({col})) IN ('applicant', 'talentum applicant') THEN 'Applicant'
      ELSE '(Sin origen)'
    END
"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Ventana estándar (Desde/Hasta > Mes > rolling 30d). Ancla en la fecha de cierre.
    lo, hi = window_bounds(filters)
    sql = f"""
        WITH mapped AS (
          SELECT {ORIGIN_CASE.format(col='ca.candidate_origin')} AS origin
          FROM hire_opportunity ho
          JOIN opportunity op ON op.opportunity_id = ho.opportunity_id
            AND TRIM(op.opp_stage) = 'Close Win'
          JOIN candidates ca  ON ca.candidate_id = ho.candidate_id
          WHERE NULLIF(op.opp_close_date::text, '')::date BETWEEN %(w_lo)s AND %(w_hi)s
        )
        SELECT origin,
               COUNT(*)::int AS count,
               ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1)::float AS share_pct
        FROM mapped
        GROUP BY origin
        ORDER BY COUNT(*) DESC, origin;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_closewin_candidate_origin",
    "label": "Operations · Close wins por origen del candidato (%)",
    "dimensions": [{"key": "origin", "label": "Origen", "type": "string"}],
    "measures": [
        {"key": "count", "label": "Placements", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
