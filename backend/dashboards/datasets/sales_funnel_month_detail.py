"""Sales funnel — list of opps in the selected month (flip-back detail).

Returns the list of opps for Mariano + Bahia active in the given month.
Filtered by an optional `stage_min` param:
  - 'sql'        → all opps active in the month
  - 'nda_sent'   → opps past Deep Dive
  - 'sourcing'   → opps with NDA signed (past NDA Sent)
  - 'close_win'  → opps closed as Win in the month

Each row includes opp_position_name, client_name, opp_stage and the
relevant date for the listed stage.
"""
from __future__ import annotations

import os
from datetime import date, datetime


SALES_LEADS_DEFAULT = ("mariano@vintti.com", "bahia@vintti.com")

STAGE_PAST_DEEP_DIVE = (
    "NDA Sent", "Sourcing", "Interviewing", "Negotiating",
    "Close Win", "Closed Lost",
)
STAGE_PAST_NDA_SENT = (
    "Sourcing", "Interviewing", "Negotiating", "Close Win", "Closed Lost",
)


def _parse_date(value):
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


def _sales_leads() -> list[str]:
    raw = os.environ.get("DASHBOARD_SALES_AES", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(SALES_LEADS_DEFAULT)


def _resolve_stage(filters: dict) -> str:
    raw = (filters.get("stage_min") or filters.get("stage") or "sql").strip().lower()
    if raw in ("nda_sent", "nda-sent", "nda sent"):
        return "nda_sent"
    if raw == "sourcing":
        return "sourcing"
    if raw in ("close_win", "close-win", "close win", "cw"):
        return "close_win"
    return "sql"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    mes = (
        _parse_date(filters.get("mes"))
        or _parse_date(filters.get("month"))
        or _parse_date(filters.get("fecha"))
    )
    stage = _resolve_stage(filters)

    sql = """
        WITH mes_pick AS (
          SELECT
            COALESCE(
              DATE_TRUNC('month', %(mes)s::date)::date,
              DATE_TRUNC('month', CURRENT_DATE)::date
            ) AS mes_ini,
            (COALESCE(
              DATE_TRUNC('month', %(mes)s::date)::date,
              DATE_TRUNC('month', CURRENT_DATE)::date
            ) + INTERVAL '1 month - 1 day')::date AS mes_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            o.opp_position_name,
            TRIM(o.opp_stage) AS opp_stage,
            o.opp_model,
            o.opp_type,
            COALESCE(
              NULLIF(o.nda_sent_date::text, '')::date,
              NULLIF(o.nda_signature_or_start_date::text, '')::date,
              NULLIF(o.opp_close_date::text, '')::date
            ) AS opp_date,
            NULLIF(o.opp_close_date::text, '')::date AS close_d,
            a.client_name
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            AND o.opp_stage IS NOT NULL
        )
        SELECT
          b.opportunity_id,
          b.opp_position_name,
          b.client_name,
          b.opp_stage,
          b.opp_model,
          b.opp_type,
          TO_CHAR(b.opp_date, 'YYYY-MM-DD') AS opp_date,
          TO_CHAR(b.close_d, 'YYYY-MM-DD')  AS close_d
        FROM base b
        CROSS JOIN mes_pick m
        WHERE
          (
            %(stage)s = 'close_win' AND b.opp_stage = 'Close Win'
              AND b.close_d IS NOT NULL AND b.close_d BETWEEN m.mes_ini AND m.mes_fin
          )
          OR (
            %(stage)s = 'sourcing'
              AND b.opp_stage = ANY(%(stage_sourcing)s)
              AND b.opp_date IS NOT NULL AND b.opp_date BETWEEN m.mes_ini AND m.mes_fin
          )
          OR (
            %(stage)s = 'nda_sent'
              AND b.opp_stage = ANY(%(stage_nda_sent)s)
              AND b.opp_date IS NOT NULL AND b.opp_date BETWEEN m.mes_ini AND m.mes_fin
          )
          OR (
            %(stage)s = 'sql'
              AND b.opp_date IS NOT NULL AND b.opp_date BETWEEN m.mes_ini AND m.mes_fin
          )
        ORDER BY COALESCE(b.close_d, b.opp_date) DESC NULLS LAST
        LIMIT 200;
    """

    return sql, {
        "mes": mes,
        "stage": stage,
        "sales_leads": _sales_leads(),
        "stage_sourcing": list(STAGE_PAST_NDA_SENT),
        "stage_nda_sent": list(STAGE_PAST_DEEP_DIVE),
    }


DATASET = {
    "key": "sales_funnel_month_detail",
    "label": "Sales funnel — opps en el mes (detail)",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opp ID", "type": "string"},
        {"key": "opp_position_name", "label": "Position", "type": "string"},
        {"key": "client_name", "label": "Client", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "opp_model", "label": "Model", "type": "string"},
        {"key": "opp_type", "label": "Type", "type": "string"},
        {"key": "opp_date", "label": "Activity Date", "type": "date"},
        {"key": "close_d", "label": "Close Date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
