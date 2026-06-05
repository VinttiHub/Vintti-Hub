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

    # Deep Dive → NDA Signed conversion (opp-level).
    # Denominador: opps con deep_dive_date en la ventana. Numerador: de esas, las
    # que tienen nda_signature_or_start_date. Canal = account.where_come_from.
    # M+B: account.account_manager (consistente con SQL → Deep Dive; funnel temprano).
    # Window = deep_dive_date (cohorte). Delta vs los 30d previos.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH dd AS (
          SELECT
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            NULLIF(o.deep_dive_date::text, '')::date AS dd_d,
            (NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL) AS signed_nda
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
            AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
            AND (%(desde)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date <= %(hasta)s::date)
        ),
        cur AS (
          SELECT * FROM dd
          WHERE dd_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ),
        prev_rate AS (
          SELECT ROUND(
            COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0 / NULLIF(COUNT(*), 0), 1
          ) AS prev_total_pct
          FROM dd
          WHERE dd_d BETWEEN (%(corte)s::date - INTERVAL '59 days')::date
                         AND (%(corte)s::date - INTERVAL '30 days')::date
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales')::int                       AS sales_dd,
          COUNT(*) FILTER (WHERE channel='sales' AND signed_nda)::int        AS sales_nda,
          ROUND(COUNT(*) FILTER (WHERE channel='sales' AND signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1)     AS sales_pct,

          COUNT(*) FILTER (WHERE channel='marketing')::int                   AS mkt_dd,
          COUNT(*) FILTER (WHERE channel='marketing' AND signed_nda)::int    AS mkt_nda,
          ROUND(COUNT(*) FILTER (WHERE channel='marketing' AND signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1) AS mkt_pct,

          COUNT(*) FILTER (WHERE channel='referrals')::int                   AS ref_dd,
          COUNT(*) FILTER (WHERE channel='referrals' AND signed_nda)::int    AS ref_nda,
          ROUND(COUNT(*) FILTER (WHERE channel='referrals' AND signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1) AS ref_pct,

          COUNT(*)::int                              AS total_dd,
          COUNT(*) FILTER (WHERE signed_nda)::int    AS total_nda,
          ROUND(COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*), 0), 1)            AS total_pct,
          pr.prev_total_pct,
          ROUND(
            COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0 / NULLIF(COUNT(*), 0)
            - COALESCE(pr.prev_total_pct, 0), 1
          ) AS total_pct_delta
        FROM cur
        CROSS JOIN prev_rate pr
        GROUP BY pr.prev_total_pct;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,"corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "deepdive_to_nda_30d",
    "label": "Deep Dive → NDA Signed por canal (30d)",
    "dimensions": [],
    "measures": [
        {"key": "sales_dd", "label": "Sales · Deep Dives", "type": "number"},
        {"key": "sales_nda", "label": "Sales · NDA firmado", "type": "number"},
        {"key": "sales_pct", "label": "Sales · DD→NDA %", "type": "percent"},
        {"key": "mkt_dd", "label": "Marketing · Deep Dives", "type": "number"},
        {"key": "mkt_nda", "label": "Marketing · NDA firmado", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · DD→NDA %", "type": "percent"},
        {"key": "ref_dd", "label": "Referrals · Deep Dives", "type": "number"},
        {"key": "ref_nda", "label": "Referrals · NDA firmado", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · DD→NDA %", "type": "percent"},
        {"key": "total_dd", "label": "Total · Deep Dives", "type": "number"},
        {"key": "total_nda", "label": "Total · NDA firmado", "type": "number"},
        {"key": "total_pct", "label": "Total · DD→NDA %", "type": "percent"},
        {"key": "prev_total_pct", "label": "Total · DD→NDA % (30d previos)", "type": "percent"},
        {"key": "total_pct_delta", "label": "Total · Δ DD→NDA (pp)", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
