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

    # NDA Signed → Closed Win — PER OPPORTUNITY (spec Bahía 2026-08-25, punto 5).
    # Es la card 3 (nda_to_clientwin_30d) SIN dedupe por cuenta: acá 20 opps de un
    # mismo cliente cuentan 20. Va debajo del funnel per client, como métrica de deals.
    # Denominador: opps con NDA firmado que ya decidieron (Close Win / Closed Lost),
    #              con opp_close_date en la ventana.
    # Numerador:   las Close Win.
    # M+B por opp_sales_lead (la unidad es la opp, y la opp tiene su propio sales lead).
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH cur AS (
          SELECT
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            (TRIM(o.opp_stage) = 'Close Win') AS won
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
            AND NULLIF(o.opp_close_date::text, '')::date
                BETWEEN %(win_ini)s::date AND %(win_fin)s::date
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales')::int                  AS sales_opps,
          COUNT(*) FILTER (WHERE channel='sales' AND won)::int          AS sales_win,
          ROUND(COUNT(*) FILTER (WHERE channel='sales' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1) AS sales_pct,

          COUNT(*) FILTER (WHERE channel='marketing')::int                  AS mkt_opps,
          COUNT(*) FILTER (WHERE channel='marketing' AND won)::int          AS mkt_win,
          ROUND(COUNT(*) FILTER (WHERE channel='marketing' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1) AS mkt_pct,

          COUNT(*) FILTER (WHERE channel='referrals')::int                  AS ref_opps,
          COUNT(*) FILTER (WHERE channel='referrals' AND won)::int          AS ref_win,
          ROUND(COUNT(*) FILTER (WHERE channel='referrals' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1) AS ref_pct,

          COUNT(*)::int                           AS total_opps,
          COUNT(*) FILTER (WHERE won)::int        AS total_win,
          ROUND(COUNT(*) FILTER (WHERE won)::numeric * 100.0
                / NULLIF(COUNT(*), 0), 1)         AS total_pct
        FROM cur;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "nda_closewin_opp_30d",
    "label": "NDA Signed → Closed Win por canal, per opportunity (30d, AE)",
    "dimensions": [],
    "measures": [
        {"key": "sales_opps", "label": "Sales · Opps decididas", "type": "number"},
        {"key": "sales_win", "label": "Sales · Close Win", "type": "number"},
        {"key": "sales_pct", "label": "Sales · NDA→Win %", "type": "percent"},
        {"key": "mkt_opps", "label": "Marketing · Opps decididas", "type": "number"},
        {"key": "mkt_win", "label": "Marketing · Close Win", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · NDA→Win %", "type": "percent"},
        {"key": "ref_opps", "label": "Referrals · Opps decididas", "type": "number"},
        {"key": "ref_win", "label": "Referrals · Close Win", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · NDA→Win %", "type": "percent"},
        {"key": "total_opps", "label": "Total · Opps decididas", "type": "number"},
        {"key": "total_win", "label": "Total · Close Win", "type": "number"},
        {"key": "total_pct", "label": "Total · NDA→Win %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
