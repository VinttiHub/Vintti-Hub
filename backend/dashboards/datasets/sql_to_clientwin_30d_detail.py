from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds


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
        or today_ar()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # Una fila por CLIENTE (account) que decidió (cerró ≥1 opp: Close Win/Closed Lost)
    # en la ventana, M+B. Estado = "Close Win" si el cliente tiene ≥1 Close Win, si no
    # "Closed Lost". opps = cuántas opps decididas tuvo en la ventana (informativo).
    win_ini, win_fin = window_bounds(filters)
    sql = """
        SELECT
          TO_CHAR(MAX(NULLIF(o.opp_close_date::text, '')::date), 'YYYY-MM-DD') AS close_date,
          CASE
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'Sales'
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'Referrals'
            ELSE 'Marketing'
          END AS channel,
          a.client_name,
          COUNT(*)::int AS opps,
          CASE WHEN BOOL_OR(TRIM(o.opp_stage) = 'Close Win')
               THEN 'Close Win' ELSE 'Closed Lost' END AS estado
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND NULLIF(o.opp_close_date::text, '')::date BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com', 'mariano@vintti.com')
        GROUP BY a.account_id, a.client_name, a.where_come_from
        ORDER BY estado, channel, close_date DESC;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_clientwin_30d_detail",
    "label": "SQL → Close Win — Detalle por cliente (30d, AE)",
    "dimensions": [
        {"key": "close_date", "label": "Última close date", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cuenta", "type": "string"},
        {"key": "estado", "label": "Estado", "type": "string"},
    ],
    "measures": [
        {"key": "opps", "label": "Opps decididas", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
