"""Marketing · Revenue mix — % Recruiting vs % Staffing del net revenue.

Dos filas (Recruiting, Staffing) con el fee de Vintti de los Close Win cerrados
en el período (semana / mes / q / anio). Net revenue = Staffing ho.fee +
Recruiting ho.revenue. Marketing-scope: excluye outbound (reconcilia con la card
'Net revenue' del strip). Siempre devuelve ambos modelos (0 si no hubo).
"""
from __future__ import annotations

from .mkt_sqls_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, label = period_bounds(filters)
    sql = """
        WITH rev_opp AS (
          SELECT o.opportunity_id, o.opp_model,
                 NULLIF(o.opp_close_date::text, '')::date AS cdte,
                 COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                                   ELSE COALESCE(ho.fee, 0) END), 0)::numeric AS rev
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
          WHERE TRIM(o.opp_stage) = 'Close Win' AND o.opp_model IN ('Staffing', 'Recruiting')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          GROUP BY o.opportunity_id, o.opp_model, cdte
        ),
        agg AS (
          SELECT opp_model AS model, SUM(rev)::numeric AS net_rev
          FROM rev_opp
          WHERE cdte BETWEEN %(ini)s::date AND %(fin)s::date
          GROUP BY opp_model
        ),
        models AS (SELECT unnest(ARRAY['Recruiting', 'Staffing']) AS model)
        SELECT
          m.model,
          COALESCE(ROUND(a.net_rev), 0)::bigint                                     AS net_rev,
          ROUND(100.0 * COALESCE(a.net_rev, 0)
                / NULLIF(SUM(COALESCE(a.net_rev, 0)) OVER (), 0), 1)::float          AS pct,
          ROUND(SUM(COALESCE(a.net_rev, 0)) OVER ())::bigint                         AS total,
          %(label)s::text                                                           AS period_label
        FROM models m
        LEFT JOIN agg a ON a.model = m.model
        ORDER BY m.model;
    """
    return sql, {"ini": ini, "fin": fin, "label": label}


DATASET = {
    "key": "mkt_revenue_mix",
    "label": "Marketing · Revenue mix (Recruiting vs Staffing, período)",
    "dimensions": [
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "net_rev", "label": "Net revenue", "type": "currency"},
        {"key": "pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Net revenue total", "type": "currency"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
