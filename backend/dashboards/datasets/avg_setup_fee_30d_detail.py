"""Detalle Avg Setup Fee — un row por deal Staffing Close Win (M+B, 30d).

Se agrega por opportunity (no por hire) para que las opps con varios candidatos
(ej Theta con 2 hires) aparezcan como una sola fila — mismo criterio que las
otras métricas de avg fee. Por deal:
  - `setup_fee` = SUM(ho.setup_fee) de los hires del deal
  - `has_pc`    = 'Yes' si CUALQUIER hire tiene `ho.computer` = 'yes', sino 'No'
  - `candidate_name` = nombres concatenados con `, `

`AVG(setup_fee)` filtrado por has_pc = los avg del summary `avg_setup_fee_30d`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

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
        or datetime.utcnow().date()
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
            STRING_AGG(NULLIF(TRIM(c.name), ''), ', ' ORDER BY c.name)  AS candidate_name,
            COUNT(ho.candidate_id)::int                                AS hire_count,
            COALESCE(SUM(ho.setup_fee), 0)::float                      AS setup_fee,
            BOOL_OR(LOWER(TRIM(COALESCE(ho.computer, ''))) = 'yes')    AS has_pc_bool
          FROM ae_wins w
          JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          LEFT JOIN candidates    c  ON c.candidate_id   = ho.candidate_id
          WHERE ho.candidate_id IS NOT NULL
          GROUP BY w.opportunity_id, w.account_id, w.opp_sales_lead, w.opp_position_name, w.close_d
        )
        SELECT
          TO_CHAR(po.close_d, 'YYYY-MM-DD')                  AS close_date,
          COALESCE(a.client_name, '')                        AS client_name,
          po.opp_position_name                               AS opp_position_name,
          po.opp_sales_lead                                  AS opp_sales_lead,
          COALESCE(po.candidate_name, '')                    AS candidate_name,
          po.hire_count                                      AS hire_count,
          CASE WHEN po.has_pc_bool THEN 'Yes' ELSE 'No' END  AS has_pc,
          po.setup_fee                                       AS setup_fee
        FROM per_opp po
        LEFT JOIN account a ON a.account_id = po.account_id
        WHERE po.close_d IS NOT NULL
          AND po.close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ORDER BY po.close_d DESC NULLS LAST,
                 po.setup_fee DESC NULLS LAST,
                 a.client_name;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "avg_setup_fee_30d_detail",
    "label": "Avg Setup Fee — Detalle hires (Staffing · 30d · M+B)",
    "dimensions": [
        {"key": "close_date", "label": "Close date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "candidate_name", "label": "Candidato(s)", "type": "string"},
        {"key": "opp_sales_lead", "label": "AE", "type": "string"},
        {"key": "has_pc", "label": "Computer", "type": "string"},
    ],
    "measures": [
        {"key": "hire_count", "label": "Hires en deal", "type": "number"},
        {"key": "setup_fee", "label": "Setup fee del deal", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
