"""Marketing · detalle New active clients (cuentas cuyo 1er Close Win cae en el período)."""
from __future__ import annotations

from .mkt_new_clients_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, _ = period_bounds(filters)
    sql = """
        WITH first_close AS (
          SELECT o.account_id, MIN(NULLIF(o.opp_close_date::text, '')::date) AS first_d
          FROM opportunity o
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          GROUP BY o.account_id
        )
        SELECT
          a.client_name,
          COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin,
          TO_CHAR(fc.first_d, 'YYYY-MM-DD') AS first_close
        FROM first_close fc
        JOIN account a ON a.account_id = fc.account_id
        WHERE fc.first_d BETWEEN %(ini)s::date AND %(fin)s::date
          AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral')
        ORDER BY fc.first_d DESC, a.client_name;
    """
    return sql, {"ini": ini, "fin": fin}


DATASET = {
    "key": "mkt_new_clients_by_origin_detail",
    "label": "Marketing · detalle New active clients (período)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "first_close", "label": "Primer Close Win", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
