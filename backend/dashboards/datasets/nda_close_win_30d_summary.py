from __future__ import annotations

from datetime import date, datetime


SALES_LEADS = ("bahia@vintti.com", "mariano@vintti.com", "lara@vintti.com")


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
    modelo = _resolve_modelo(filters)
    resultado = _resolve_resultado(filters)
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date                              AS cutoff_d,
            (%(corte)s::date - INTERVAL '30 days')::date AS window_start,
            %(corte)s::date                              AS window_end,
            (%(corte)s::date + INTERVAL '1 day')::date   AS window_end_excl
        ),
        base AS (
          SELECT
            o.opportunity_id,
            NULLIF(o.opp_close_date::text,'')::date AS close_d,
            TRIM(o.opp_stage) AS opp_stage,
            o.opp_model
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(desde)s::date  IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date  IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
        ),
        closed_universe AS (
          SELECT * FROM base WHERE opp_stage IN ('Close Win','Closed Lost')
        ),
        windowed AS (
          SELECT v.cutoff_d, v.window_start, v.window_end, cu.opp_stage
          FROM closed_universe cu
          CROSS JOIN ventana v
          WHERE cu.close_d >= v.window_start
            AND cu.close_d <  v.window_end_excl
        )
        SELECT
          TO_CHAR(MIN(cutoff_d),     'YYYY-MM-DD') AS cutoff_d,
          TO_CHAR(MIN(window_start), 'YYYY-MM-DD') AS window_start,
          TO_CHAR(MIN(window_end),   'YYYY-MM-DD') AS window_end,
          COUNT(*)::int                            AS total_closed,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int   AS close_win,
          COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::int AS close_lost,
          CASE
            WHEN COUNT(*) = 0 THEN 0
            WHEN %(resultado)s = 'Close Win'
              THEN ROUND(
                (COUNT(*) FILTER (WHERE opp_stage = 'Close Win'))::numeric * 100.0
                / NULLIF(COUNT(*), 0),
                1)
            WHEN %(resultado)s = 'Closed Lost'
              THEN ROUND(
                (COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost'))::numeric * 100.0
                / NULLIF(COUNT(*), 0),
                1)
            ELSE 100.0
          END::float AS conversion_pct
        FROM windowed;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "modelo": modelo,
        "resultado": resultado,
        "desde": desde,
        "hasta": hasta,
        "corte": corte,
    }


DATASET = {
    "key": "nda_close_win_30d_summary",
    "label": "Conversión global NDA → cliente — Ventana 30 días",
    "dimensions": [
        {"key": "cutoff_d", "label": "Fecha corte", "type": "date"},
        {"key": "window_start", "label": "Inicio ventana", "type": "date"},
        {"key": "window_end", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "total_closed", "label": "Total closed", "type": "number"},
        {"key": "close_win", "label": "Close Win", "type": "number"},
        {"key": "close_lost", "label": "Closed Lost", "type": "number"},
        {"key": "conversion_pct", "label": "Conversion %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
