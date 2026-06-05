"""Marketing · detalle SQLs aperturados (cuentas creadas en el período)."""
from __future__ import annotations

from .mkt_sqls_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, _ = period_bounds(filters)
    sql = """
        SELECT
          a.client_name,
          COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin,
          TO_CHAR(a.creation_date::date, 'YYYY-MM-DD') AS creation_date
        FROM account a
        WHERE a.creation_date IS NOT NULL
          AND a.creation_date::date BETWEEN %(ini)s::date AND %(fin)s::date
        ORDER BY a.creation_date DESC, a.client_name;
    """
    return sql, {"ini": ini, "fin": fin}


DATASET = {
    "key": "mkt_sqls_by_origin_detail",
    "label": "Marketing · detalle SQLs (período)",
    "dimensions": [
        {"key": "client_name", "label": "Cuenta", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "creation_date", "label": "Creación (SQL)", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
