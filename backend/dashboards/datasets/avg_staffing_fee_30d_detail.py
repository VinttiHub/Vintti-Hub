"""Detalle Avg Staffing Fee — un row por deal Staffing close-won (M+B, 30d).

`AVG(deal_fee)` = `avg_fee` del summary `avg_staffing_fee_30d`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("hasta"))
        or today_ar()
    )
    win_ini, win_fin = window_bounds(filters)

    sql = """
        WITH ae_wins AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            COALESCE(o.opp_sales_lead, '')                 AS opp_sales_lead,
            COALESCE(o.opp_position_name, '')              AS opp_position_name,
            NULLIF(o.opp_close_date::text, '')::date       AS close_d
          FROM opportunity o
          WHERE o.opp_model = 'Staffing'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND TRIM(o.opp_stage) = 'Close Win'
        ),
        per_opp AS (
          SELECT
            w.opportunity_id,
            w.account_id,
            w.opp_sales_lead,
            w.opp_position_name,
            w.close_d,
            STRING_AGG(NULLIF(TRIM(c.name), ''), ', ' ORDER BY c.name) AS candidate_name,
            COUNT(ho.candidate_id)::int                               AS hire_count,
            COALESCE(SUM(ho.salary), 0)::float                        AS deal_salary,
            COALESCE(SUM(ho.fee), 0)::float                           AS deal_fee
          FROM ae_wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          LEFT JOIN candidates       c  ON c.candidate_id   = ho.candidate_id
          GROUP BY w.opportunity_id, w.account_id, w.opp_sales_lead, w.opp_position_name, w.close_d
        )
        SELECT
          COALESCE(po.candidate_name, '')                  AS candidate_name,
          COALESCE(a.client_name, '')                      AS client_name,
          po.opp_sales_lead                                AS opp_sales_lead,
          po.opp_position_name                             AS opp_position_name,
          po.hire_count                                    AS hire_count,
          TO_CHAR(po.close_d, 'YYYY-MM-DD')                AS close_date,
          po.deal_salary                                   AS deal_salary,
          po.deal_fee                                      AS deal_fee
        FROM per_opp po
        LEFT JOIN account a ON a.account_id = po.account_id
        WHERE po.close_d IS NOT NULL
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND po.close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ORDER BY po.close_d DESC NULLS LAST,
                 po.deal_fee DESC NULLS LAST,
                 a.client_name;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "avg_staffing_fee_30d_detail",
    "label": "Avg Staffing Fee — Detalle deals (30d, M+B)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato(s)", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [
        {"key": "hire_count", "label": "Hires en deal", "type": "number"},
        {"key": "deal_salary", "label": "Salary mensual", "type": "currency"},
        {"key": "deal_fee", "label": "Fee mensual Vintti", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
