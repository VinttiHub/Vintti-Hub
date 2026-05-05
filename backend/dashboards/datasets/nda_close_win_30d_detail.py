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
            %(corte)s::date                              AS corte_d,
            (%(corte)s::date - INTERVAL '30 days')::date AS win_ini,
            (%(corte)s::date + INTERVAL '1 day')::date   AS win_fin_excl
        ),
        base AS (
          SELECT
            o.opportunity_id,
            a.client_name,
            o.opp_model,
            NULLIF(o.opp_close_date::text,'')::date AS close_d,
            TRIM(o.opp_stage) AS opp_stage
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
        )
        SELECT
          cu.client_name,
          cu.opp_model,
          TO_CHAR(cu.close_d, 'YYYY-MM-DD') AS close_d,
          cu.opp_stage,
          CASE WHEN cu.opp_stage = 'Close Win' THEN 1 ELSE 0 END AS converted_to_client
        FROM closed_universe cu
        CROSS JOIN ventana v
        WHERE cu.close_d >= v.win_ini
          AND cu.close_d <  v.win_fin_excl
          AND (%(resultado)s = 'Total' OR cu.opp_stage = %(resultado)s)
        ORDER BY cu.close_d, cu.client_name;
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
    "key": "nda_close_win_30d_detail",
    "label": "Conversión global NDA → cliente — Detalle ventana 30 días",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "close_d", "label": "Fecha cierre", "type": "date"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
    ],
    "measures": [
        {"key": "converted_to_client", "label": "Converted", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
