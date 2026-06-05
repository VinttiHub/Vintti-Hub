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
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    modelo = _resolve_modelo(filters)

    # Channels group `account.where_come_from` into Sales / Referrals / Marketing.
    # Population: ALL closed opps (Close Win + Closed Lost) with sales_lead M+B in
    # the window — NDA cohort is NOT required (an opp counts even with no NDA).
    # Two windows: current 30d (corte-29..corte) and prior 30d (corte-59..corte-30),
    # so the total win rate can show a delta vs the previous period.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH closed AS (
          SELECT
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            TRIM(o.opp_stage) AS opp_stage,
            NULLIF(o.opp_close_date::text,'')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.account_id IS NOT NULL
            AND TRIM(o.opp_stage) IN ('Close Win','Closed Lost')
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
            AND (%(modelo)s::text IS NULL OR LOWER(TRIM(o.opp_model)) = LOWER(%(modelo)s))
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
        ),
        cur AS (
          SELECT * FROM closed
          WHERE close_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ),
        prev_rate AS (
          SELECT ROUND(
            COUNT(*) FILTER (WHERE opp_stage='Close Win')::numeric * 100.0
            / NULLIF(COUNT(*), 0), 1
          ) AS prev_total_win_rate
          FROM closed
          WHERE close_d BETWEEN (%(corte)s::date - INTERVAL '59 days')::date
                            AND (%(corte)s::date - INTERVAL '30 days')::date
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales'     AND opp_stage='Close Win')::int   AS sales_win,
          COUNT(*) FILTER (WHERE channel='sales'     AND opp_stage='Closed Lost')::int AS sales_lost,
          COUNT(*) FILTER (WHERE channel='sales')::int                                 AS sales_total,
          ROUND(
            COUNT(*) FILTER (WHERE channel='sales' AND opp_stage='Close Win')::numeric * 100.0
            / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1
          ) AS sales_win_rate,

          COUNT(*) FILTER (WHERE channel='referrals' AND opp_stage='Close Win')::int   AS ref_win,
          COUNT(*) FILTER (WHERE channel='referrals' AND opp_stage='Closed Lost')::int AS ref_lost,
          COUNT(*) FILTER (WHERE channel='referrals')::int                             AS ref_total,
          ROUND(
            COUNT(*) FILTER (WHERE channel='referrals' AND opp_stage='Close Win')::numeric * 100.0
            / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1
          ) AS ref_win_rate,

          COUNT(*) FILTER (WHERE channel='marketing' AND opp_stage='Close Win')::int   AS mkt_win,
          COUNT(*) FILTER (WHERE channel='marketing' AND opp_stage='Closed Lost')::int AS mkt_lost,
          COUNT(*) FILTER (WHERE channel='marketing')::int                             AS mkt_total,
          ROUND(
            COUNT(*) FILTER (WHERE channel='marketing' AND opp_stage='Close Win')::numeric * 100.0
            / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1
          ) AS mkt_win_rate,

          COUNT(*) FILTER (WHERE opp_stage='Close Win')::int   AS total_win,
          COUNT(*) FILTER (WHERE opp_stage='Closed Lost')::int AS total_lost,
          COUNT(*)::int                                        AS total_total,
          ROUND(
            COUNT(*) FILTER (WHERE opp_stage='Close Win')::numeric * 100.0
            / NULLIF(COUNT(*), 0), 1
          ) AS total_win_rate,
          pr.prev_total_win_rate,
          ROUND(
            COUNT(*) FILTER (WHERE opp_stage='Close Win')::numeric * 100.0
            / NULLIF(COUNT(*), 0)
            - COALESCE(pr.prev_total_win_rate, 0), 1
          ) AS total_win_rate_delta
        FROM cur
        CROSS JOIN prev_rate pr
        GROUP BY pr.prev_total_win_rate;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,
        "corte": corte,
        "desde": desde,
        "hasta": hasta,
        "modelo": modelo,
    }


DATASET = {
    "key": "lead_channel_winrate_30d",
    "label": "Win rate por canal (Sales/Referrals/Marketing) — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "sales_win", "label": "Sales · Win", "type": "number"},
        {"key": "sales_lost", "label": "Sales · Lost", "type": "number"},
        {"key": "sales_total", "label": "Sales · Total", "type": "number"},
        {"key": "sales_win_rate", "label": "Sales · Win rate", "type": "percent"},
        {"key": "ref_win", "label": "Referrals · Win", "type": "number"},
        {"key": "ref_lost", "label": "Referrals · Lost", "type": "number"},
        {"key": "ref_total", "label": "Referrals · Total", "type": "number"},
        {"key": "ref_win_rate", "label": "Referrals · Win rate", "type": "percent"},
        {"key": "mkt_win", "label": "Marketing · Win", "type": "number"},
        {"key": "mkt_lost", "label": "Marketing · Lost", "type": "number"},
        {"key": "mkt_total", "label": "Marketing · Total", "type": "number"},
        {"key": "mkt_win_rate", "label": "Marketing · Win rate", "type": "percent"},
        {"key": "total_win", "label": "Total · Win", "type": "number"},
        {"key": "total_lost", "label": "Total · Lost", "type": "number"},
        {"key": "total_total", "label": "Total · Cerradas", "type": "number"},
        {"key": "total_win_rate", "label": "Total · Win rate", "type": "percent"},
        {"key": "prev_total_win_rate", "label": "Total · Win rate (30d previos)", "type": "percent"},
        {"key": "total_win_rate_delta", "label": "Total · Δ win rate (pp)", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
