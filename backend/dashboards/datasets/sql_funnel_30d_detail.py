"""SQL funnel detail (30d, Mariano + Bahia).

Lists every account whose `creation_date` falls in the last 30 days and
whose `account_manager` ∈ {Mariano, Bahia} (per [[project-sales-tab-filter]]).
For each account, exposes flags + dates that the Sales tab funnel drawers
slice on:

  - has_nda_sent / nda_sent_d
  - has_nda_signed / nda_signed_d
  - has_close_win / close_win_d / close_win_stage

Powers the side-drawers for "SQL → NDA Sent" and "SQL → Close Win" cards.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta


from ._sales_scope import sales_leads as _sales_leads


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    win_ini = corte - timedelta(days=29)

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        cohort AS (
          -- R1: ancla SQL = fecha real del meeting (sql_meeting_date), estricto: solo cuentas con reunión real.
          SELECT a.account_id, a.client_name,
                 a.sql_meeting_date AS creation_d
          FROM account a
          CROSS JOIN ventana v
          WHERE a.sql_meeting_date IS NOT NULL
            AND a.sql_meeting_date BETWEEN v.win_ini AND v.win_fin
            AND TRIM(LOWER(a.account_manager)) = ANY(%(sales_leads)s)
        ),
        agg AS (
          SELECT
            c.account_id,
            c.client_name,
            c.creation_d,
            MIN(NULLIF(o.nda_sent_date::text, '')::date)                AS nda_sent_d,
            MIN(NULLIF(o.nda_signature_or_start_date::text, '')::date)  AS nda_signed_d,
            MIN(CASE
                  WHEN TRIM(o.opp_stage) = 'Close Win'
                       AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
                  THEN NULLIF(o.opp_close_date::text, '')::date
                END)                                                    AS close_win_d
          FROM cohort c
          LEFT JOIN opportunity o ON o.account_id = c.account_id
          GROUP BY c.account_id, c.client_name, c.creation_d
        )
        SELECT
          client_name,
          TO_CHAR(creation_d, 'YYYY-MM-DD')                                AS creation_d,
          TO_CHAR(nda_sent_d, 'YYYY-MM-DD')                                AS nda_sent_d,
          TO_CHAR(nda_signed_d, 'YYYY-MM-DD')                              AS nda_signed_d,
          TO_CHAR(close_win_d, 'YYYY-MM-DD')                               AS close_win_d,
          CASE WHEN nda_sent_d   IS NULL THEN 'No' ELSE 'Sí' END           AS has_nda_sent,
          CASE WHEN nda_signed_d IS NULL THEN 'No' ELSE 'Sí' END           AS has_nda_signed,
          CASE WHEN close_win_d  IS NULL THEN 'No' ELSE 'Sí' END           AS has_close_win
        FROM agg
        ORDER BY creation_d DESC, client_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": corte, "sales_leads": _sales_leads()}


DATASET = {
    "key": "sql_funnel_30d_detail",
    "label": "SQL funnel · detalle 30d (M+B)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "creation_d", "label": "Creación", "type": "date"},
        {"key": "nda_sent_d", "label": "NDA sent", "type": "date"},
        {"key": "nda_signed_d", "label": "NDA signed", "type": "date"},
        {"key": "close_win_d", "label": "Close Win", "type": "date"},
        {"key": "has_nda_sent", "label": "Con NDA sent", "type": "string"},
        {"key": "has_nda_signed", "label": "Con NDA signed", "type": "string"},
        {"key": "has_close_win", "label": "Con Close Win", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
