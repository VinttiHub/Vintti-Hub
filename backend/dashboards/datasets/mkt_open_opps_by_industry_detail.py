"""Marketing · detalle Oportunidades abiertas (opps no cerradas de cuentas creadas en el período)."""
from __future__ import annotations

from .mkt_open_opps_by_industry import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, _ = period_bounds(filters)
    sql = """
        SELECT
          a.client_name,
          COALESCE(NULLIF(TRIM(a.industry), ''), '(Sin industria)') AS industry,
          o.opp_position_name,
          TRIM(o.opp_stage) AS opp_stage,
          COALESCE(o.expected_revenue, 0)::bigint AS expected_revenue
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE TRIM(COALESCE(o.opp_stage, '')) NOT IN ('Close Win', 'Close Lost', 'Closed Lost')
          AND a.creation_date IS NOT NULL
          AND a.creation_date::date BETWEEN %(ini)s::date AND %(fin)s::date
          AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
        ORDER BY expected_revenue DESC, a.client_name;
    """
    return sql, {"ini": ini, "fin": fin}


DATASET = {
    "key": "mkt_open_opps_by_industry_detail",
    "label": "Marketing · detalle Open opps (período)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "industry", "label": "Industria", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
    ],
    "measures": [{"key": "expected_revenue", "label": "Expected revenue", "type": "currency"}],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
