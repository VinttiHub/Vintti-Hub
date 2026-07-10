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

    # Una fila por opp con NDA firmado en la ventana, con su canal y si llegó a Client Win.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        SELECT
          TO_CHAR(NULLIF(o.nda_signature_or_start_date::text,'')::date, 'YYYY-MM-DD') AS nda_date,
          CASE
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'Sales'
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'Referrals'
            ELSE 'Marketing'
          END AS channel,
          a.client_name,
          o.opp_position_name,
          CASE
            WHEN TRIM(o.opp_stage) = 'Close Win'   THEN 'Client Win'
            WHEN TRIM(o.opp_stage) = 'Closed Lost' THEN 'Closed Lost'
            ELSE 'En proceso · ' || TRIM(o.opp_stage)
          END AS estado
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE NULLIF(o.nda_signature_or_start_date::text,'')::date IS NOT NULL
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND NULLIF(o.nda_signature_or_start_date::text,'')::date
              BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND (%(desde)s::date IS NULL OR NULLIF(o.nda_signature_or_start_date::text,'')::date >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR NULLIF(o.nda_signature_or_start_date::text,'')::date <= %(hasta)s::date)
        ORDER BY channel, estado, nda_date DESC;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "nda_to_clientwin_30d_detail",
    "label": "NDA → Client Win — Detalle NDAs (30d, AE)",
    "dimensions": [
        {"key": "nda_date", "label": "NDA date", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "estado", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
