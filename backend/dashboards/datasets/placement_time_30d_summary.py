from __future__ import annotations

from datetime import date, datetime


def _parse_date(value: str | None) -> date | None:
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
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    modelo = _resolve_modelo(filters)
    resultado = _resolve_resultado(filters)

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - INTERVAL '30 day')::date AS win_ini,
            %(corte)s::date AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            TRIM(o.opp_stage) AS close_result,
            NULLIF(o.nda_signature_or_start_date::text,'')::date AS pedido_d,
            NULLIF(o.opp_close_date::text,'')::date              AS close_d
          FROM opportunity o
          WHERE o.opportunity_id IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND o.opp_type = 'New'
            AND NULLIF(o.opp_close_date::text,'')::date >= NULLIF(o.nda_signature_or_start_date::text,'')::date
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        )
        SELECT
          ROUND(AVG((b.close_d - b.pedido_d))::numeric)::int AS promedio_dias
        FROM base b
        CROSS JOIN ventana v
        WHERE b.close_d BETWEEN v.win_ini AND v.win_fin
          AND (%(resultado)s = 'Total' OR b.close_result = %(resultado)s);
    """

    return sql, {"corte": corte, "modelo": modelo, "resultado": resultado}


DATASET = {
    "key": "placement_time_30d_summary",
    "label": "Tiempo promedio de colocación — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "promedio_dias", "label": "Promedio días", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
