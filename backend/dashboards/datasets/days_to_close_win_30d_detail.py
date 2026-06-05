from __future__ import annotations

from datetime import date, datetime

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


def _resolve_modelo(filters: dict) -> str | None:
    raw = (
        filters.get("modelo")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    modelo = _resolve_modelo(filters)
    # Optional channel filter (sales/marketing/referrals) for the per-area drawer.
    channel = (filters.get("channel") or "").strip().lower() or None
    if channel not in ("sales", "marketing", "referrals"):
        channel = None

    # One row per Close Win deal in the window, with days NDA→close. Mirrors
    # days_to_close_win_30d.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini,
                 %(win_fin)s::date AS win_fin
        )
        SELECT
          CASE
            WHEN LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound' THEN 'Sales'
            WHEN LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'referral' THEN 'Referrals'
            ELSE 'Marketing'
          END AS channel,
          a.client_name,
          o.opp_position_name,
          (NULLIF(o.opp_close_date::text,'')::date
           - NULLIF(o.nda_signature_or_start_date::text,'')::date)::int AS avg_days,
          TO_CHAR(NULLIF(o.opp_close_date::text,'')::date, 'YYYY-MM-DD') AS close_date
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        CROSS JOIN ventana v
        WHERE NULLIF(o.nda_signature_or_start_date::text,'') IS NOT NULL
          AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
          AND TRIM(o.opp_stage) = 'Close Win'
          AND o.opp_type = 'New'
          AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND NULLIF(o.opp_close_date::text,'')::date >= NULLIF(o.nda_signature_or_start_date::text,'')::date
          AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
          AND (%(channel)s::text IS NULL OR
               (CASE
                  WHEN LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound' THEN 'sales'
                  WHEN LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'referral' THEN 'referrals'
                  ELSE 'marketing'
                END) = %(channel)s)
          AND NULLIF(o.opp_close_date::text,'')::date BETWEEN v.win_ini AND v.win_fin
        ORDER BY channel, avg_days DESC;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "modelo": modelo, "channel": channel}


DATASET = {
    "key": "days_to_close_win_30d_detail",
    "label": "Days to Close Win — Detalle deals (30d, AE)",
    "dimensions": [
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [
        {"key": "avg_days", "label": "Días NDA→cierre", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
