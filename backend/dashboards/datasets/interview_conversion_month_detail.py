from __future__ import annotations

from datetime import date


def _parse_date(value) -> date | None:
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


def _resolve_resultado(filters: dict) -> str:
    raw = (filters.get("opp_stage") or filters.get("resultado") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    resultado = _resolve_resultado(filters)
    mes = (
        _parse_date(filters.get("mes_interview_conversion"))
        or _parse_date(filters.get("Pres_Sent"))
        or _parse_date(filters.get("mes"))
        or _parse_date(filters.get("month"))
    )

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
        ),
        base AS (
          SELECT
            o.opportunity_id,
            a.client_name,
            o.opp_position_name,
            o.cantidad_entrevistados::numeric AS cantidad_entrevistados,
            TRIM(o.opp_stage) AS opp_stage,
            NULLIF(o.opp_close_date::text,'')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          CROSS JOIN mes_objetivo mo
          WHERE TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.cantidad_entrevistados::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
            AND DATE_TRUNC('month', NULLIF(o.opp_close_date::text,'')::date)::date = mo.mes_pick
        ),
        presentados AS (
          SELECT
            b.opportunity_id,
            COUNT(*)::numeric AS candidatos_presentados
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          WHERE b.presentation_date IS NOT NULL
          GROUP BY 1
        )
        SELECT
          TO_CHAR(b.close_d, 'YYYY-MM-DD')                       AS close_date,
          b.client_name,
          b.opp_position_name,
          b.opp_stage,
          b.cantidad_entrevistados::float                        AS cantidad_entrevistados,
          COALESCE(p.candidatos_presentados, 0)::float           AS candidatos_presentados,
          CASE
            WHEN b.cantidad_entrevistados = 0 THEN 0
            ELSE ROUND(
              (COALESCE(p.candidatos_presentados,0) / b.cantidad_entrevistados) * 100, 2)
          END::float AS pct_presentados_sobre_entrevistados,
          CASE
            WHEN COALESCE(p.candidatos_presentados,0) = 0 THEN 0
            ELSE ROUND(
              (b.cantidad_entrevistados / COALESCE(p.candidatos_presentados,0)) * 100, 2)
          END::float AS pct_entrevistados_sobre_presentados
        FROM base b
        LEFT JOIN presentados p ON p.opportunity_id = b.opportunity_id
        ORDER BY b.close_d DESC, b.client_name;
    """

    return sql, {"resultado": resultado, "mes": mes}


DATASET = {
    "key": "interview_conversion_month_detail",
    "label": "Tasa de Conversión a Entrevista — detalle por mes",
    "dimensions": [
        {"key": "close_date", "label": "Close date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
    ],
    "measures": [
        {"key": "cantidad_entrevistados", "label": "Entrevistados", "type": "number"},
        {"key": "candidatos_presentados", "label": "Presentados", "type": "number"},
        {"key": "pct_presentados_sobre_entrevistados", "label": "% Presentados/Entrevistados", "type": "percent"},
        {"key": "pct_entrevistados_sobre_presentados", "label": "% Entrevistados/Presentados", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
