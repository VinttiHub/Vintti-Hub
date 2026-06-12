"""Marketing · Net revenue generado por origin — ranking por período.

Net revenue = fee de Vintti (Staffing ho.fee + Recruiting ho.revenue) de las
opps Close Win cuyo opp_close_date cae en el período. Segmentado por origin
(account.where_come_from), EXCLUYENDO outbound. Período a la fecha: semana /
mes / q / anio.
"""
from __future__ import annotations

from .mkt_sqls_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, label = period_bounds(filters)
    sql = """
        WITH wins AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral')
        ),
        per_opp AS (
          SELECT
            w.origin, w.close_d,
            COALESCE(SUM(
              CASE WHEN w.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                   ELSE COALESCE(ho.fee, 0) END
            ), 0)::numeric AS net_rev
          FROM wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          GROUP BY w.opportunity_id, w.origin, w.close_d
        ),
        in_period AS (
          SELECT * FROM per_opp
          WHERE close_d BETWEEN %(ini)s::date AND %(fin)s::date
        ),
        agg AS (SELECT origin, SUM(net_rev) AS rev FROM in_period GROUP BY origin)
        SELECT
          origin,
          ROUND(rev)::bigint AS net_revenue,
          ROUND(100.0 * rev / NULLIF(SUM(rev) OVER (), 0), 1)::float AS share_pct,
          ROUND(SUM(rev) OVER ())::bigint AS total,
          %(label)s::text AS period_label
        FROM agg
        WHERE rev > 0
        ORDER BY rev DESC, origin;
    """
    return sql, {"ini": ini, "fin": fin, "label": label}


DATASET = {
    "key": "mkt_net_revenue_by_origin",
    "label": "Marketing · Net revenue por origin (ranking, período)",
    "dimensions": [
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "net_revenue", "label": "Net revenue", "type": "currency"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Net revenue total", "type": "currency"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
