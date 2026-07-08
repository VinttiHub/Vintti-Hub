from __future__ import annotations

from datetime import date, datetime, timedelta
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
    hoy = today_ar()
    win = str(filters.get("window") or filters.get("ventana") or "").strip().lower()
    # Explicit week/MTD sub-windows anchor to today (match the card's cnt_week/cnt_month).
    # Default window honors desde/hasta > mes > rolling 30d via window_bounds, so the
    # drawer reconciles with the card's headline cnt_30d.
    if win in ("week", "semana", "7d", "7"):
        win_ini, win_fin = hoy - timedelta(days=6), hoy
    elif win in ("month", "mes", "mtd"):
        win_ini, win_fin = hoy.replace(day=1), hoy
    else:
        win_ini, win_fin = window_bounds(filters)

    sql = """
        SELECT
          a.client_name,
          TO_CHAR(a.creation_date, 'YYYY-MM-DD') AS creation_d,
          COALESCE(NULLIF(TRIM(a.referal_source), ''), '—') AS referal_source,
          COALESCE(a.account_manager, '—') AS account_manager
        FROM account a
        WHERE a.creation_date IS NOT NULL
          AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'referral'
          AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND a.creation_date BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ORDER BY a.creation_date DESC, a.client_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


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
