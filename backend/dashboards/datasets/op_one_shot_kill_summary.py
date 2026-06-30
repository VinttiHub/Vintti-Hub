"""Operations · "One shot, one kill" — KPI global.

% de placements (hires) cuyo candidato contratado estaba en el BATCH N°1 de la opp.
Denominador: placements cuya opp tiene al menos un batch N°1 registrado. Ancla la
ventana en la fecha de contratación (hire_opportunity.carga_active). Excluye recruiters
inactivos. Una fila con placements / one_shot_count / conversion_pct.
"""
from __future__ import annotations

from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    lo, hi = window_bounds(filters)
    sql = """
        WITH hires AS (
          SELECT DISTINCT ho.opportunity_id, ho.candidate_id, o.opp_hr_lead
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.carga_active BETWEEN %(w_lo)s AND %(w_hi)s
            AND LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
        ),
        firstbatch AS (   -- primer batch (mínimo batch_number) donde aparece cada candidato por opp
          SELECT b.opportunity_id, cb.candidate_id, MIN(b.batch_number) AS batch_num
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          GROUP BY b.opportunity_id, cb.candidate_id
        ),
        oppb1 AS (        -- opps que tienen batch N°1 (denominador)
          SELECT DISTINCT opportunity_id FROM batch WHERE batch_number = 1
        ),
        scored AS (
          SELECT (fb.batch_num = 1) AS one_shot
          FROM hires h
          JOIN oppb1 ON oppb1.opportunity_id = h.opportunity_id
          LEFT JOIN firstbatch fb
            ON fb.opportunity_id = h.opportunity_id AND fb.candidate_id = h.candidate_id
        )
        SELECT
          COUNT(*)::int                                        AS placements,
          COUNT(*) FILTER (WHERE one_shot)::int                AS one_shot_count,
          ROUND(100.0 * COUNT(*) FILTER (WHERE one_shot)
                / NULLIF(COUNT(*), 0), 1)::float               AS conversion_pct
        FROM scored;
    """
    return sql, {"w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_one_shot_kill_summary",
    "label": "Operations · One shot one kill (KPI)",
    "dimensions": [],
    "measures": [
        {"key": "conversion_pct", "label": "% one-shot", "type": "percent"},
        {"key": "one_shot_count", "label": "One-shot", "type": "number"},
        {"key": "placements", "label": "Placements", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
