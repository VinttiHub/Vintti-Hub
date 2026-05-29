"""Equipment YTD — % de candidatos alocados que necesitan computadora, AE.

Datos para la donut "% con PC" en el card de Setup Fee · Breakdown.
Window: desde 1 de enero del año actual hasta hoy (`opp_close_date`).
Solo cuenta hires de deals Staffing Close Win con `opp_sales_lead` ∈ {Mariano,
Bahia}.

Nota: se cuenta por **candidato (hire_opportunity)**, no por opp. Si una opp
tiene 2 hires (ej Theta), cada uno suma independientemente — el ratio queda
"% de candidatos alocados con PC" tal como dice el metric brief del Metabase.
"""
from __future__ import annotations

from datetime import date, datetime


SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = datetime.utcnow().date()
    year_start = date(today.year, 1, 1)

    sql = """
        WITH base AS (
          -- One row per hire (candidato). Si Theta tiene 2 hires con flags
          -- distintos, cada uno cuenta independiente — el ratio mide
          -- "candidatos con PC / total candidatos".
          SELECT
            CASE
              WHEN LOWER(TRIM(COALESCE(ho.computer, ''))) = 'yes' THEN TRUE
              ELSE FALSE
            END AS has_pc
          FROM opportunity o
          JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '')::date BETWEEN %(year_start)s::date AND %(today)s::date
            AND ho.candidate_id IS NOT NULL
        )
        SELECT
          COUNT(*) FILTER (WHERE has_pc)::int       AS count_with_pc,
          COUNT(*) FILTER (WHERE NOT has_pc)::int   AS count_without_pc,
          COUNT(*)::int                             AS count_total,
          CASE WHEN COUNT(*) = 0 THEN 0
               ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE has_pc) / COUNT(*), 1)
          END                                       AS pct_with_pc,
          CASE WHEN COUNT(*) = 0 THEN 0
               ELSE ROUND(100.0 * COUNT(*) FILTER (WHERE NOT has_pc) / COUNT(*), 1)
          END                                       AS pct_without_pc
        FROM base;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "year_start": year_start,
        "today": today,
    }


DATASET = {
    "key": "equipment_ytd",
    "label": "Equipment YTD — % con PC vs sin PC (Staffing · M+B)",
    "dimensions": [],
    "measures": [
        {"key": "count_with_pc", "label": "Deals CON PC (YTD)", "type": "number"},
        {"key": "count_without_pc", "label": "Deals SIN PC (YTD)", "type": "number"},
        {"key": "count_total", "label": "Deals total (YTD)", "type": "number"},
        {"key": "pct_with_pc", "label": "% CON PC", "type": "percent"},
        {"key": "pct_without_pc", "label": "% SIN PC", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
