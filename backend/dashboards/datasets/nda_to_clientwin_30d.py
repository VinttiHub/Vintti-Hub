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

    # NDA Signed → Client Win (= Close Win) conversion (opp-level).
    # Denominador: opps con nda_signature_or_start_date en la ventana. Numerador: las
    # que llegaron a Close Win. Canal = account.where_come_from. M+B por opp_sales_lead.
    # Window = fecha de NDA (cohorte). OJO: el salto NDA→cierre tarda meses, así que
    # una ventana corta puede verse baja (muchas siguen en proceso).
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH base AS (
          SELECT
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            NULLIF(o.nda_signature_or_start_date::text, '')::date AS nda_d,
            (TRIM(o.opp_stage) = 'Close Win') AS won
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
            AND (%(desde)s::date IS NULL OR NULLIF(o.nda_signature_or_start_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.nda_signature_or_start_date::text,'')::date <= %(hasta)s::date)
        ),
        cur AS (
          SELECT * FROM base
          WHERE nda_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales')::int                  AS sales_nda,
          COUNT(*) FILTER (WHERE channel='sales' AND won)::int          AS sales_win,
          ROUND(COUNT(*) FILTER (WHERE channel='sales' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1) AS sales_pct,

          COUNT(*) FILTER (WHERE channel='marketing')::int                  AS mkt_nda,
          COUNT(*) FILTER (WHERE channel='marketing' AND won)::int          AS mkt_win,
          ROUND(COUNT(*) FILTER (WHERE channel='marketing' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1) AS mkt_pct,

          COUNT(*) FILTER (WHERE channel='referrals')::int                  AS ref_nda,
          COUNT(*) FILTER (WHERE channel='referrals' AND won)::int          AS ref_win,
          ROUND(COUNT(*) FILTER (WHERE channel='referrals' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1) AS ref_pct,

          COUNT(*)::int                          AS total_nda,
          COUNT(*) FILTER (WHERE won)::int        AS total_win,
          ROUND(COUNT(*) FILTER (WHERE won)::numeric * 100.0
                / NULLIF(COUNT(*), 0), 1)        AS total_pct
        FROM cur;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "nda_to_clientwin_30d",
    "label": "NDA Signed → Client Win por canal (30d, AE)",
    "dimensions": [],
    "measures": [
        {"key": "sales_nda", "label": "Sales · NDAs", "type": "number"},
        {"key": "sales_win", "label": "Sales · Client Win", "type": "number"},
        {"key": "sales_pct", "label": "Sales · NDA→Win %", "type": "percent"},
        {"key": "mkt_nda", "label": "Marketing · NDAs", "type": "number"},
        {"key": "mkt_win", "label": "Marketing · Client Win", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · NDA→Win %", "type": "percent"},
        {"key": "ref_nda", "label": "Referrals · NDAs", "type": "number"},
        {"key": "ref_win", "label": "Referrals · Client Win", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · NDA→Win %", "type": "percent"},
        {"key": "total_nda", "label": "Total · NDAs", "type": "number"},
        {"key": "total_win", "label": "Total · Client Win", "type": "number"},
        {"key": "total_pct", "label": "Total · NDA→Win %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
