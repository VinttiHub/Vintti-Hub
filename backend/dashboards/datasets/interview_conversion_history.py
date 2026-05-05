from __future__ import annotations


def _resolve_resultado(filters: dict) -> str:
    raw = (filters.get("opp_stage") or filters.get("resultado") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    resultado = _resolve_resultado(filters)

    sql = """
        WITH base AS (
          SELECT
            o.opportunity_id,
            o.cantidad_entrevistados::numeric AS cantidad_entrevistados,
            TRIM(o.opp_stage) AS opp_stage,
            NULLIF(o.opp_close_date::text,'')::date AS close_d
          FROM opportunity o
          WHERE TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.cantidad_entrevistados::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
        ),
        presentados AS (
          SELECT
            b.opportunity_id,
            COUNT(*)::numeric AS candidatos_presentados
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          WHERE b.presentation_date IS NOT NULL
          GROUP BY 1
        ),
        final AS (
          SELECT
            DATE_TRUNC('month', b.close_d)::date AS mes,
            b.opportunity_id,
            b.cantidad_entrevistados,
            COALESCE(p.candidatos_presentados, 0) AS candidatos_presentados
          FROM base b
          LEFT JOIN presentados p ON p.opportunity_id = b.opportunity_id
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                              AS mes,
          COUNT(*)::int                                           AS opps,
          SUM(candidatos_presentados)::float                      AS presentados_total,
          SUM(cantidad_entrevistados)::float                      AS entrevistados_total,
          CASE WHEN SUM(cantidad_entrevistados) = 0 THEN 0
               ELSE ROUND((SUM(candidatos_presentados) / SUM(cantidad_entrevistados)) * 100, 2)
          END::float AS pct_presentados_sobre_entrevistados,
          CASE WHEN SUM(candidatos_presentados) = 0 THEN 0
               ELSE ROUND((SUM(cantidad_entrevistados) / SUM(candidatos_presentados)) * 100, 2)
          END::float AS pct_entrevistados_sobre_presentados
        FROM final
        GROUP BY 1
        ORDER BY 1;
    """

    return sql, {"resultado": resultado}


DATASET = {
    "key": "interview_conversion_history",
    "label": "Tasa de Conversión a Entrevista — por mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "opps", "label": "Opps", "type": "number"},
        {"key": "presentados_total", "label": "Presentados", "type": "number"},
        {"key": "entrevistados_total", "label": "Entrevistados", "type": "number"},
        {"key": "pct_presentados_sobre_entrevistados", "label": "% Presentados/Entrevistados", "type": "percent"},
        {"key": "pct_entrevistados_sobre_presentados", "label": "% Entrevistados/Presentados", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
