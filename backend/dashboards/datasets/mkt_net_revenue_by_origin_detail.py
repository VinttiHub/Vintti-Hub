"""Marketing · detalle Net revenue por origin (Close Wins del período, sin outbound)."""
from __future__ import annotations

from .mkt_sqls_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, _ = period_bounds(filters)
    sql = """
        WITH wins AS (
          SELECT
            o.opportunity_id, a.client_name, o.opp_position_name, TRIM(o.opp_model) AS model,
            COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
        )
        SELECT
          w.client_name, w.origin, w.model, w.opp_position_name,
          TO_CHAR(w.close_d, 'YYYY-MM-DD') AS close_date,
          COALESCE(SUM(
            CASE WHEN w.model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                 ELSE COALESCE(ho.fee, 0) END), 0)::bigint AS net_revenue
        FROM wins w
        LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
        WHERE w.close_d BETWEEN %(ini)s::date AND %(fin)s::date
        GROUP BY w.client_name, w.origin, w.model, w.opp_position_name, w.close_d
        ORDER BY net_revenue DESC, w.client_name;
    """
    return sql, {"ini": ini, "fin": fin}


DATASET = {
    "key": "mkt_net_revenue_by_origin_detail",
    "label": "Marketing · detalle Net revenue por origin (período)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [{"key": "net_revenue", "label": "Net revenue", "type": "currency"}],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
