from __future__ import annotations

from datetime import date


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


def _resolve_modelo(filters: dict) -> str | None:
    raw = (
        filters.get("modelo")
        or filters.get("modelo1")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def _resolve_resultado(filters: dict) -> str:
    raw = (filters.get("opp_stage") or filters.get("resultado") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    modelo = _resolve_modelo(filters)
    resultado = _resolve_resultado(filters)

    sql = """
        WITH base AS (
          SELECT
            o.opportunity_id,
            a.client_name,
            o.opp_model,
            o.opp_type,
            TRIM(o.opp_stage) AS close_result,
            NULLIF(o.nda_signature_or_start_date::text,'')::date AS pedido_d,
            NULLIF(o.opp_close_date::text,'')::date              AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opportunity_id IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND o.opp_type = 'New'
            AND NULLIF(o.opp_close_date::text,'')::date >= NULLIF(o.nda_signature_or_start_date::text,'')::date
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        )
        SELECT
          TO_CHAR(DATE_TRUNC('month', close_d)::date, 'YYYY-MM-DD') AS mes_cierre,
          ROUND(AVG((close_d - pedido_d))::numeric)::int AS promedio_dias
        FROM base
        WHERE 1=1
          AND (%(desde)s::date IS NULL OR close_d >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR close_d <  (%(hasta)s::date + INTERVAL '1 day'))
          AND (%(resultado)s = 'Total' OR close_result = %(resultado)s)
        GROUP BY 1
        ORDER BY 1;
    """

    return sql, {"desde": desde, "hasta": hasta, "modelo": modelo, "resultado": resultado}


DATASET = {
    "key": "placement_time_history",
    "label": "Tiempo promedio (pedido → cierre) por mes de cierre",
    "dimensions": [
        {"key": "mes_cierre", "label": "Mes cierre", "type": "date"},
    ],
    "measures": [
        {"key": "promedio_dias", "label": "Promedio días", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
