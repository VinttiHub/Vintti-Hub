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
    mes = (
        _parse_date(filters.get("mes"))
        or _parse_date(filters.get("fecha"))
        or _parse_date(filters.get("month"))
    )
    modelo = _resolve_modelo(filters)
    opp_stage = _resolve_stage(filters)

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
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
        closed_base AS (
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
        marked AS (
          SELECT
            cb.*,
            ROW_NUMBER() OVER (
              PARTITION BY cb.account_id, DATE_TRUNC('month', cb.close_d)
              ORDER BY cb.close_d ASC, cb.opportunity_id ASC
            ) AS rn_client_month
          FROM closed_base cb
        )
        SELECT
          m.client_name,
          m.lead_source,
          m.opp_model,
          TO_CHAR(m.first_nda_d, 'YYYY-MM-DD') AS nda_d_first_time,
          TO_CHAR(m.close_d, 'YYYY-MM-DD')     AS close_d,
          m.opp_stage,
          CASE WHEN m.rn_client_month = 1 THEN 1 ELSE 0 END AS is_unique_client_closed
        FROM marked m
        CROSS JOIN mes_objetivo mo
        WHERE 1 = 1
          AND DATE_TRUNC('month', m.close_d)::date = mo.mes_pick
          AND (%(modelo)s::text IS NULL OR LOWER(TRIM(m.opp_model)) = LOWER(%(modelo)s))
          AND (%(opp_stage)s::text IS NULL OR m.opp_stage = %(opp_stage)s)
        ORDER BY m.close_d, m.client_name;
    """

    return sql, {"mes": mes, "modelo": modelo, "opp_stage": opp_stage}


DATASET = {
    "key": "nda_to_clients_detail",
    "label": "NDA a Clientes — Detalle del mes",
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
