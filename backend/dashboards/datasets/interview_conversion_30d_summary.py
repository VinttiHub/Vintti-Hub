from __future__ import annotations

from datetime import date, datetime, timezone


def _parse_date(value) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def _resolve_resultado(filters: dict) -> str:
    raw = (filters.get("opp_stage") or filters.get("resultado") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    resultado = _resolve_resultado(filters)
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.now(timezone.utc).date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            (%(corte)s::date - INTERVAL '30 day')::date AS win_ini,
            %(corte)s::date                              AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            o.cantidad_entrevistados::numeric AS entrevistados,
            TRIM(o.opp_stage) AS opp_stage
          FROM opportunity o
          WHERE TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.cantidad_entrevistados::text, '') IS NOT NULL
            AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
        ),
        presentados AS (
          SELECT
            b.opportunity_id,
            COUNT(*)::numeric AS presentados
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          CROSS JOIN ventana v
          WHERE b.presentation_date IS NOT NULL
            AND b.presentation_date::date >= v.win_ini
            AND b.presentation_date::date <  (v.win_fin + INTERVAL '1 day')
          GROUP BY 1
        )
        SELECT
          COALESCE(
            ROUND(
              100.0 * (
                SUM(COALESCE(p.presentados, 0)) / NULLIF(SUM(b.entrevistados), 0)
              ),
              2
            ),
            0
          )::float AS conversion_global_ponderada_pct
        FROM base b
        LEFT JOIN presentados p ON p.opportunity_id = b.opportunity_id;
    """

    return sql, {"resultado": resultado, "corte": corte}


DATASET = {
    "key": "interview_conversion_30d_summary",
    "label": "Tasa de Conversión a Entrevista — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "conversion_global_ponderada_pct", "label": "Conversión global %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
