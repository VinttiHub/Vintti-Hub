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


def _resolve_stage(filters: dict) -> str | None:
    raw = (filters.get("opp_stage") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return None


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
            a.where_come_from AS lead_source,
            o.opp_model,
            NULLIF(o.opp_close_date::text,'')::date AS close_d,
            TRIM(o.opp_stage) AS opp_stage,
            c.first_nda_d
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
            AND (%(opp_stage)s::text IS NULL OR w.opp_stage = %(opp_stage)s)
        ),
        marked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (
              PARTITION BY account_id, DATE_TRUNC('month', close_d)
              ORDER BY close_d ASC, opportunity_id ASC
            ) AS rn_client_month
          FROM windowed
        )
        SELECT
          client_name,
          lead_source,
          opp_model,
          TO_CHAR(first_nda_d, 'YYYY-MM-DD') AS nda_d_first_time,
          TO_CHAR(close_d, 'YYYY-MM-DD')     AS close_d,
          opp_stage,
          CASE WHEN rn_client_month = 1 THEN 1 ELSE 0 END AS is_unique_client_closed
        FROM marked
        ORDER BY close_d, client_name;
    """

    return sql, {"corte": corte, "modelo": modelo, "opp_stage": opp_stage}


DATASET = {
    "key": "nda_to_clients_30d_detail",
    "label": "NDA a Clientes — Detalle 30 días",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "lead_source", "label": "Lead Source", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "nda_d_first_time", "label": "Primer NDA", "type": "date"},
        {"key": "close_d", "label": "Fecha cierre", "type": "date"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
    ],
    "measures": [
        {"key": "is_unique_client_closed", "label": "Cliente único", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
