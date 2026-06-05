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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # One row per opp that hit Deep Dive in the current 30d window, with channel
    # and whether it signed NDA. Same definition as deepdive_to_nda_30d.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        SELECT
          TO_CHAR(NULLIF(o.deep_dive_date::text,'')::date, 'YYYY-MM-DD') AS deep_dive_date,
          CASE
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'Sales'
            WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'Referrals'
            ELSE 'Marketing'
          END AS channel,
          a.client_name,
          o.opp_position_name,
          COALESCE(NULLIF(TRIM(a.where_come_from), ''), 'NA') AS lead_source,
          CASE WHEN NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL
               THEN 'NDA firmado' ELSE '—' END AS status
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
          AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
          AND NULLIF(o.deep_dive_date::text,'')::date
              BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          AND (%(desde)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date <= %(hasta)s::date)
        ORDER BY channel, NULLIF(o.deep_dive_date::text,'')::date DESC, a.client_name;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "deepdive_to_nda_30d_detail",
    "label": "Deep Dive → NDA — Detalle de deep dives (30d)",
    "dimensions": [
        {"key": "deep_dive_date", "label": "Deep Dive date", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cuenta", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "lead_source", "label": "Origen", "type": "string"},
        {"key": "status", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
