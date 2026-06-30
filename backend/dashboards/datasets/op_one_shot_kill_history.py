"""Operations · "One shot, one kill" — tendencia mensual.

% de one-shot por mes (mes de la fecha de contratación). Misma definición que el KPI:
denominador = contrataciones cuya opp tiene batch N°1; numerador = candidato contratado
en el batch N°1. Acota opcionalmente con desde/hasta. Excluye recruiters inactivos.
"""
from __future__ import annotations

from datetime import date


def _parse_date(value) -> date | None:
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    sql = """
        WITH hires AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            DATE_TRUNC('month', MIN(ho.carga_active))::date AS mes
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE LOWER(TRIM(o.opp_hr_lead)) <> 'agustina.barbero@vintti.com'
            AND (%(desde)s::date IS NULL OR ho.carga_active::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR ho.carga_active::date <= %(hasta)s::date)
          GROUP BY ho.opportunity_id, ho.candidate_id
        ),
        firstbatch AS (
          SELECT b.opportunity_id, cb.candidate_id, MIN(b.batch_number) AS batch_num
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          GROUP BY b.opportunity_id, cb.candidate_id
        ),
        oppb1 AS (
          SELECT DISTINCT opportunity_id FROM batch WHERE batch_number = 1
        ),
        scored AS (
          SELECT h.mes, (fb.batch_num = 1) AS one_shot
          FROM hires h
          JOIN oppb1 ON oppb1.opportunity_id = h.opportunity_id
          LEFT JOIN firstbatch fb
            ON fb.opportunity_id = h.opportunity_id AND fb.candidate_id = h.candidate_id
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                           AS mes,
          COUNT(*)::int                                        AS placements,
          COUNT(*) FILTER (WHERE one_shot)::int                AS one_shot_count,
          ROUND(100.0 * COUNT(*) FILTER (WHERE one_shot)
                / NULLIF(COUNT(*), 0), 1)::float               AS conversion_pct
        FROM scored
        GROUP BY mes
        ORDER BY mes;
    """
    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "op_one_shot_kill_history",
    "label": "Operations · One shot one kill — por mes",
    "dimensions": [{"key": "mes", "label": "Mes", "type": "date"}],
    "measures": [
        {"key": "conversion_pct", "label": "% one-shot", "type": "percent"},
        {"key": "one_shot_count", "label": "One-shot", "type": "number"},
        {"key": "placements", "label": "Contrataciones", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
