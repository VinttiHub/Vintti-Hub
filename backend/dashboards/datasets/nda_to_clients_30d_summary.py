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
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def _resolve_stage(filters: dict) -> str:
    raw = (filters.get("opp_stage") or "").strip()
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
    opp_stage = _resolve_stage(filters)

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - INTERVAL '30 days')::date AS win_ini,
            %(corte)s::date AS win_fin
        ),
        base_nda AS (
          SELECT
            o.account_id,
            MIN(NULLIF(o.nda_signature_or_start_date::text,'')::date) AS first_nda_d
          FROM opportunity o
          WHERE o.account_id IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN (
              'bahia@vintti.com',
              'mariano@vintti.com'
            )
          GROUP BY 1
        ),
        closed_opps AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            a.client_name,
            o.opp_model,
            NULLIF(o.opp_close_date::text,'')::date AS close_d,
            TRIM(o.opp_stage) AS opp_stage
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          JOIN base_nda c ON c.account_id = o.account_id
          WHERE o.account_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN (
              'bahia@vintti.com',
              'mariano@vintti.com'
            )
        ),
        windowed AS (
          SELECT w.*
          FROM closed_opps w
          CROSS JOIN ventana v
          WHERE w.close_d BETWEEN v.win_ini AND v.win_fin
            AND (%(modelo)s::text IS NULL OR LOWER(TRIM(w.opp_model)) = LOWER(%(modelo)s))
        )
        SELECT
          (SELECT win_fin FROM ventana) AS cutoff_date,
          (SELECT win_ini FROM ventana) AS window_start,
          COUNT(*)::int AS total_closed_opps,
          COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int   AS close_win,
          COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::int AS closed_lost,
          ROUND(
            CASE
              WHEN %(opp_stage)s = 'Closed Lost' THEN
                COUNT(*) FILTER (WHERE opp_stage = 'Closed Lost')::numeric * 100.0
                / NULLIF(COUNT(*), 0)
              WHEN %(opp_stage)s IN ('Close Win', 'Total') THEN
                COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::numeric * 100.0
                / NULLIF(COUNT(*), 0)
              ELSE NULL
            END,
            1
          ) AS conversion_pct
        FROM windowed;
    """

    return sql, {"corte": corte, "modelo": modelo, "opp_stage": opp_stage}


DATASET = {
    "key": "nda_to_clients_30d_summary",
    "label": "NDA a Clientes — Resumen 30 días",
    "dimensions": [
        {"key": "cutoff_date", "label": "Corte", "type": "date"},
        {"key": "window_start", "label": "Inicio ventana", "type": "date"},
    ],
    "measures": [
        {"key": "total_closed_opps", "label": "Total cerradas", "type": "number"},
        {"key": "close_win", "label": "Close Win", "type": "number"},
        {"key": "closed_lost", "label": "Closed Lost", "type": "number"},
        {"key": "conversion_pct", "label": "Conversion %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
