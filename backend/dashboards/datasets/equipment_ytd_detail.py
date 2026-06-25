"""Detalle Equipment YTD — un row por candidato alocado (hire), AE.

Espejo a nivel hire de `equipment_ytd`: cada candidato Staffing Close Win con
`opp_sales_lead` ∈ {Mariano, Bahia} cuyo deal cerró desde 1-ene del año actual,
con su flag `computer` y el setup fee de ese hire.

Conteo por hire (no por opp) para que el % `con PC` cuadre con la donut.
"""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = today_ar()
    year_start = date(today.year, 1, 1)

    sql = """
        SELECT
          TO_CHAR(NULLIF(o.opp_close_date::text, '')::date, 'YYYY-MM-DD')   AS close_date,
          COALESCE(a.client_name, '')                                       AS client_name,
          COALESCE(o.opp_position_name, '')                                 AS opp_position_name,
          COALESCE(c.name, '')                                              AS candidate_name,
          COALESCE(o.opp_sales_lead, '')                                    AS opp_sales_lead,
          CASE
            WHEN LOWER(TRIM(COALESCE(ho.computer, ''))) = 'yes' THEN 'Yes'
            ELSE 'No'
          END                                                               AS has_pc,
          COALESCE(ho.setup_fee, 0)::float                                  AS setup_fee
        FROM opportunity o
        JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
        LEFT JOIN account a      ON a.account_id   = o.account_id
        LEFT JOIN candidates c   ON c.candidate_id = ho.candidate_id
        WHERE o.opp_model = 'Staffing'
          AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
          AND TRIM(o.opp_stage) = 'Close Win'
          AND ho.candidate_id IS NOT NULL
          AND NULLIF(o.opp_close_date::text, '')::date BETWEEN %(year_start)s::date AND %(today)s::date
        ORDER BY has_pc DESC,
                 NULLIF(o.opp_close_date::text, '')::date DESC NULLS LAST,
                 a.client_name,
                 c.name;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "year_start": year_start,
        "today": today,
    }


DATASET = {
    "key": "equipment_ytd_detail",
    "label": "Equipment YTD — Detalle hires (Staffing · AE)",
    "dimensions": [
        {"key": "close_date", "label": "Close date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "has_pc", "label": "Computer", "type": "string"},
    ],
    "measures": [
        {"key": "setup_fee", "label": "Setup fee", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
