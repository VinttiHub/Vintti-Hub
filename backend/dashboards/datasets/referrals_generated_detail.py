from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


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
    win = str(filters.get("window") or filters.get("ventana") or "30d").strip().lower()
    if win in ("week", "semana", "7d", "7"):
        win = "week"
    elif win in ("month", "mes", "mtd"):
        win = "month"
    else:
        win = "30d"

    # win_ini según la ventana; para 'month' se usa date_trunc en el SQL.
    bounds = {
        "30d": "(%(corte)s::date - INTERVAL '29 days')::date",
        "week": "(%(corte)s::date - INTERVAL '6 days')::date",
        "month": "DATE_TRUNC('month', %(corte)s::date)::date",
    }[win]

    sql = f"""
        SELECT
          a.client_name,
          TO_CHAR(a.creation_date, 'YYYY-MM-DD') AS creation_d,
          COALESCE(NULLIF(TRIM(a.referal_source), ''), '—') AS referal_source,
          COALESCE(a.account_manager, '—') AS account_manager
        FROM account a
        WHERE a.creation_date IS NOT NULL
          AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'referral'
          AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND a.creation_date BETWEEN {bounds} AND %(corte)s::date
        ORDER BY a.creation_date DESC, a.client_name;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "referrals_generated_detail",
    "label": "Referrals Generated — Detalle por ventana (AE)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "creation_d", "label": "Creación", "type": "date"},
        {"key": "referal_source", "label": "Referido por", "type": "string"},
        {"key": "account_manager", "label": "AE", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
