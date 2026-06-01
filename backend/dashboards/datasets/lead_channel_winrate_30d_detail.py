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
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    modelo = _resolve_modelo(filters)

    # One row per closed deal in the current 30d window, with its channel.
    # Same population as lead_channel_winrate_30d (all CW+CL with sales_lead M+B,
    # no NDA cohort) so it reconciles with the card total.
    sql = """
        SELECT
          TO_CHAR(NULLIF(o.opp_close_date::text,'')::date, 'YYYY-MM-DD') AS close_date,
          CASE
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'Sales'
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'Referrals'
            ELSE 'Marketing'
          END AS channel,
          a.client_name,
          COALESCE(NULLIF(TRIM(a.where_come_from), ''), 'NA') AS lead_source,
          TRIM(o.opp_stage) AS result
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE o.account_id IS NOT NULL
          AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
          AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
          AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND (%(modelo)s::text IS NULL OR LOWER(TRIM(o.opp_model)) = LOWER(%(modelo)s))
          AND NULLIF(o.opp_close_date::text,'')::date
              BETWEEN (%(corte)s::date - INTERVAL '29 days')::date AND %(corte)s::date
          AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
        ORDER BY channel, NULLIF(o.opp_close_date::text,'')::date DESC, a.client_name;
    """

    return sql, {
        "corte": corte,
        "desde": desde,
        "hasta": hasta,
        "modelo": modelo,
    }


DATASET = {
    "key": "lead_channel_winrate_30d_detail",
    "label": "Win rate por canal — Detalle de cerradas (30d)",
    "dimensions": [
        {"key": "close_date", "label": "Close date", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "lead_source", "label": "Origen", "type": "string"},
        {"key": "result", "label": "Resultado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
