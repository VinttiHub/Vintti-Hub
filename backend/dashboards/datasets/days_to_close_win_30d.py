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
        or today_ar()
    )
    modelo = _resolve_modelo(filters)

    # Velocidad del sales cycle: días promedio desde NDA firmado hasta Close Win.
    # Solo Close Win, opp_type='New', ventana por fecha de cierre (últimos 30d).
    # M+B por opp_sales_lead (cuenta Close Win → reasignación de account_manager no aplica).
    # Canal por account.where_come_from + cuál cierra más rápido (menor avg días).
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini,
                 %(win_fin)s::date AS win_fin
        ),
        base AS (
          SELECT
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            (NULLIF(o.opp_close_date::text,'')::date
             - NULLIF(o.nda_signature_or_start_date::text,'')::date) AS days
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
            AND NULLIF(o.opp_close_date::text,'')::date BETWEEN v.win_ini AND v.win_fin
        ),
        agg AS (
          SELECT channel, ROUND(AVG(days))::int AS dias, COUNT(*)::int AS cnt
          FROM base GROUP BY channel
        )
        SELECT
          (SELECT ROUND(AVG(days))::int FROM base) AS promedio_dias,
          (SELECT COUNT(*)::int FROM base)         AS deal_count,
          (SELECT dias FROM agg WHERE channel='sales')     AS sales_dias,
          (SELECT cnt  FROM agg WHERE channel='sales')     AS sales_count,
          (SELECT dias FROM agg WHERE channel='marketing') AS mkt_dias,
          (SELECT cnt  FROM agg WHERE channel='marketing') AS mkt_count,
          (SELECT dias FROM agg WHERE channel='referrals') AS ref_dias,
          (SELECT cnt  FROM agg WHERE channel='referrals') AS ref_count,
          (CASE (SELECT channel FROM agg WHERE cnt > 0 ORDER BY dias ASC, cnt DESC LIMIT 1)
             WHEN 'sales' THEN 'Sales'
             WHEN 'referrals' THEN 'Referrals'
             WHEN 'marketing' THEN 'Marketing'
           END) AS fastest_channel,
          (SELECT dias FROM agg WHERE cnt > 0 ORDER BY dias ASC, cnt DESC LIMIT 1) AS fastest_dias;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "modelo": modelo}


DATASET = {
    "key": "days_to_close_win_30d",
    "label": "Days to Close Win — NDA Signed → Close Win (30d, AE)",
    "dimensions": [
        {"key": "fastest_channel", "label": "Canal más rápido", "type": "string"},
    ],
    "measures": [
        {"key": "promedio_dias", "label": "Promedio días", "type": "number"},
        {"key": "deal_count", "label": "Deals", "type": "number"},
        {"key": "sales_dias", "label": "Sales · días", "type": "number"},
        {"key": "sales_count", "label": "Sales · deals", "type": "number"},
        {"key": "mkt_dias", "label": "Marketing · días", "type": "number"},
        {"key": "mkt_count", "label": "Marketing · deals", "type": "number"},
        {"key": "ref_dias", "label": "Referrals · días", "type": "number"},
        {"key": "ref_count", "label": "Referrals · deals", "type": "number"},
        {"key": "fastest_dias", "label": "Más rápido · días", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
