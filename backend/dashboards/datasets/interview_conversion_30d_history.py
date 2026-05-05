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
            a.client_name,
            o.opp_position_name,
            o.cantidad_entrevistados::numeric AS cantidad_entrevistados,
            TRIM(o.opp_stage) AS opp_stage
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.cantidad_entrevistados::text, '') IS NOT NULL
            AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
        ),
        presentados AS (
          SELECT
            b.opportunity_id,
            COUNT(*)::numeric AS candidatos_presentados
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          CROSS JOIN ventana v
          WHERE b.presentation_date IS NOT NULL
            AND b.presentation_date::date >= v.win_ini
            AND b.presentation_date::date <  (v.win_fin + INTERVAL '1 day')
          GROUP BY 1
        )
        SELECT
          b.opportunity_id::text                             AS opportunity_id,
          b.client_name,
          b.opp_position_name,
          b.opp_stage,
          b.cantidad_entrevistados::float                    AS cantidad_entrevistados,
          p.candidatos_presentados::float                    AS candidatos_presentados,
          ROUND(
            (p.candidatos_presentados / b.cantidad_entrevistados::numeric) * 100, 2
          )::float AS conversion_pct
        FROM base b
        JOIN presentados p ON p.opportunity_id = b.opportunity_id
        ORDER BY b.opportunity_id;
    """

    return sql, {"resultado": resultado, "corte": corte}


DATASET = {
    "key": "interview_conversion_30d_history",
    "label": "Tasa de Conversión a Entrevista — Ventana 30 días por opp",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
    ],
    "measures": [
        {"key": "cantidad_entrevistados", "label": "Entrevistados", "type": "number"},
        {"key": "candidatos_presentados", "label": "Presentados", "type": "number"},
        {"key": "conversion_pct", "label": "Conversion %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
