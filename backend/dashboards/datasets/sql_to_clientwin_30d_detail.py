from __future__ import annotations

from datetime import date, datetime


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
        or datetime.utcnow().date()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # Una fila por SQL (account creada en la ventana, AE) y si llegó a Close Win.
    sql = """
        SELECT
          TO_CHAR(a.creation_date, 'YYYY-MM-DD') AS sql_date,
          CASE
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'Sales'
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'Referrals'
            ELSE 'Marketing'
          END AS channel,
          a.client_name,
          CASE WHEN EXISTS (
            SELECT 1 FROM opportunity o
            WHERE o.account_id = a.account_id AND TRIM(o.opp_stage) = 'Close Win'
          ) THEN 'Close Win' ELSE 'En proceso / no ganada' END AS estado
        FROM account a
        WHERE a.creation_date IS NOT NULL
          AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND a.creation_date BETWEEN (%(corte)s::date - INTERVAL '29 days')::date AND %(corte)s::date
          AND (%(desde)s::date IS NULL OR a.creation_date >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR a.creation_date <= %(hasta)s::date)
        ORDER BY estado, channel, a.creation_date DESC;
    """

    return sql, {"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_clientwin_30d_detail",
    "label": "SQL → Close Win — Detalle SQLs (30d, AE)",
    "dimensions": [
        {"key": "sql_date", "label": "SQL date", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cuenta", "type": "string"},
        {"key": "estado", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
