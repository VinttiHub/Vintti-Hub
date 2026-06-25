"""SQL Sales — per-account breakdown by window.

Sibling of `sql_leads_windows`. Pulls from the local `account` table using
`creation_date` (same convention as the Marketing tab and the windowing
counts dataset). One row per account whose `creation_date` falls inside the
selected window.

The `event_window` filter picks which window the rows belong to:
  last_week | wtd | last_month | mtd
Defaults to `last_week` to match the drawer hero.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
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


def _window_bounds(filters: dict, corte: date) -> tuple[date, date]:
    raw = str(
        filters.get("event_window")
        or filters.get("window")
        or filters.get("ventana")
        or "last_week"
    ).strip().lower().replace("-", "_")
    if raw == "week":
        raw = "last_week"
    if raw in {"month", "prev_month"}:
        raw = "last_month"

    this_week_monday = corte - timedelta(days=corte.weekday())
    prev_week_sunday = this_week_monday - timedelta(days=1)
    prev_week_monday = prev_week_sunday - timedelta(days=6)

    month_start = corte.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)

    if raw == "wtd":
        return this_week_monday, corte
    if raw == "last_month":
        return last_month_start, last_month_end
    if raw == "mtd":
        return month_start, corte
    return prev_week_monday, prev_week_sunday  # default last_week


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = """
        SELECT
          COALESCE(a.client_name, '')                                       AS client_name,
          TRIM(CONCAT_WS(' ', NULLIF(a.name, ''), NULLIF(a.surname, '')))   AS contact,
          COALESCE(NULLIF(TRIM(a.mail), ''), '')                            AS email,
          COALESCE(NULLIF(TRIM(a.conversion_channel), ''), '')              AS channel,
          COALESCE(NULLIF(TRIM(a.account_manager), ''), '')                 AS account_manager,
          TO_CHAR(a.sql_meeting_date, 'YYYY-MM-DD') AS creation_date
        FROM account a
        -- SQL SALES = solo Outbound + owner M+B; ancla = fecha real del meeting
        -- (sql_meeting_date), estricto: solo cuentas con reunión real. Mismo filtro que sql_leads_windows.
        WHERE a.sql_meeting_date IS NOT NULL
          AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
          AND LOWER(TRIM(COALESCE(a.account_manager, ''))) IN ('mariano@vintti.com', 'bahia@vintti.com')
          AND a.sql_meeting_date BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ORDER BY a.sql_meeting_date DESC, a.client_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "sql_leads_detail",
    "label": "SQL Sales — Detalle por ventana (CRM accounts)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "contact", "label": "Contacto", "type": "string"},
        {"key": "email", "label": "Email", "type": "string"},
        {"key": "channel", "label": "Channel", "type": "string"},
        {"key": "account_manager", "label": "AM", "type": "string"},
        {"key": "creation_date", "label": "Creation date", "type": "date"},
    ],
    "measures": [],
    "default_filters": {"event_window": "last_week"},
    "query": query,
}
