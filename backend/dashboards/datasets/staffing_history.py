from __future__ import annotations

from datetime import date, datetime, timedelta


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


def _grain(filters: dict) -> str:
    raw = (filters.get("grain") or filters.get("granularity") or "month")
    raw = str(raw).strip().lower()
    if raw in ("week", "weekly", "semana", "w"):
        return "week"
    if raw in ("year", "yearly", "annual", "anual", "ano", "año", "y"):
        return "year"
    return "month"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = datetime.utcnow().date()
    grain = _grain(filters)

    # Defaults: weekly = last 12 ISO weeks, monthly = last 12 months, yearly = last 5 years
    if grain == "week":
        default_from = today - timedelta(weeks=12)
    elif grain == "year":
        default_from = today.replace(month=1, day=1) - timedelta(days=365 * 5)
    else:
        default_from = today.replace(day=1) - timedelta(days=365)

    desde = (
        _parse_date(filters.get("desde"))
        or _parse_date(filters.get("from"))
        or default_from
    )
    hasta = (
        _parse_date(filters.get("hasta"))
        or _parse_date(filters.get("to"))
        or today
    )
    if hasta < desde:
        hasta = desde

    if grain == "week":
        trunc = "week"
        period_format = "'IYYY-\"W\"IW'"
        step = "INTERVAL '1 week'"
        period_end_expr = "(p.period_start + INTERVAL '6 days')::date"
    elif grain == "year":
        trunc = "year"
        period_format = "'YYYY'"
        step = "INTERVAL '1 year'"
        period_end_expr = "(DATE_TRUNC('year', p.period_start) + INTERVAL '1 year - 1 day')::date"
    else:
        trunc = "month"
        period_format = "'YYYY-MM'"
        step = "INTERVAL '1 month'"
        period_end_expr = "(DATE_TRUNC('month', p.period_start) + INTERVAL '1 month - 1 day')::date"

    sql = f"""
        WITH params AS (
          SELECT
            DATE_TRUNC('{trunc}', %(desde)s::date)::date AS desde_d,
            DATE_TRUNC('{trunc}', %(hasta)s::date)::date AS hasta_d
        ),
        periods AS (
          SELECT
            gs::date AS period_start
          FROM params,
               generate_series(params.desde_d, params.hasta_d, {step}) gs
        ),
        period_ranges AS (
          SELECT
            p.period_start,
            {period_end_expr} AS period_end
          FROM periods p
        ),
        hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            ho.opportunity_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange::text), '') IS NOT NULL
                THEN TO_DATE(NULLIF(TRIM(ho.buyout_daterange::text),'') || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee, 0)::numeric    AS fee
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
        ),
        first_hire_per_account AS (
          SELECT account_id, MIN(start_d) AS first_d
          FROM hires
          WHERE start_d IS NOT NULL AND account_id IS NOT NULL
          GROUP BY account_id
        ),
        last_baja_per_account AS (
          SELECT account_id, MAX(end_d) AS fecha_baja
          FROM hires
          WHERE end_d IS NOT NULL
          GROUP BY account_id
        ),
        accounts_alive_after_last_baja AS (
          SELECT DISTINCT lb.account_id
          FROM last_baja_per_account lb
          JOIN hires h
            ON h.account_id = lb.account_id
           AND COALESCE(h.end_d, DATE '9999-12-31') > lb.fecha_baja
        ),
        churn_account AS (
          -- Accounts whose last_baja is final (no posterior active hire)
          SELECT lb.account_id, lb.fecha_baja,
                 (b.buyout_d IS NOT NULL AND b.buyout_d >= DATE_TRUNC('month', lb.fecha_baja)) AS is_buyout
          FROM last_baja_per_account lb
          LEFT JOIN (
            SELECT account_id, MAX(buyout_d) AS buyout_d
            FROM hires WHERE buyout_d IS NOT NULL
            GROUP BY account_id
          ) b ON b.account_id = lb.account_id
          WHERE lb.account_id NOT IN (SELECT account_id FROM accounts_alive_after_last_baja)
        ),
        active_at_end AS (
          SELECT
            pr.period_start,
            COUNT(DISTINCT h.candidate_id) AS active_contractors,
            COUNT(DISTINCT h.account_id)   AS active_clients,
            SUM(h.salary + h.fee)          AS mrr,
            SUM(h.fee)                     AS mrr_fee_total
          FROM period_ranges pr
          LEFT JOIN hires h
            ON h.start_d IS NOT NULL
           AND h.start_d <= pr.period_end
           AND (h.end_d IS NULL OR h.end_d >= pr.period_end)
          GROUP BY pr.period_start
        ),
        new_clients_per_period AS (
          SELECT
            pr.period_start,
            COUNT(*) AS new_clients
          FROM period_ranges pr
          LEFT JOIN first_hire_per_account fh
            ON fh.first_d BETWEEN pr.period_start AND pr.period_end
          GROUP BY pr.period_start
        ),
        churn_per_period AS (
          SELECT
            pr.period_start,
            COUNT(*) FILTER (WHERE NOT ca.is_buyout) AS churn_clients,
            COUNT(*) FILTER (WHERE ca.is_buyout)     AS buyout_clients
          FROM period_ranges pr
          LEFT JOIN churn_account ca
            ON ca.fecha_baja BETWEEN pr.period_start AND pr.period_end
          GROUP BY pr.period_start
        ),
        churn_contractors_per_period AS (
          SELECT
            pr.period_start,
            COUNT(*) FILTER (WHERE NOT (h.buyout_d IS NOT NULL AND h.buyout_d >= DATE_TRUNC('month', h.end_d))) AS churn_contractors,
            COUNT(*) FILTER (WHERE h.buyout_d IS NOT NULL AND h.buyout_d >= DATE_TRUNC('month', h.end_d))       AS buyout_contractors
          FROM period_ranges pr
          LEFT JOIN hires h
            ON h.end_d BETWEEN pr.period_start AND pr.period_end
          GROUP BY pr.period_start
        )
        SELECT
          to_char(pr.period_start, {period_format})::text AS periodo,
          pr.period_start,
          pr.period_end,
          COALESCE(ae.mrr, 0)::bigint                     AS mrr,
          COALESCE(ae.mrr_fee_total, 0)::bigint           AS mrr_fee_total,
          ROUND(
            COALESCE(ae.mrr_fee_total, 0)::numeric / NULLIF(ae.active_contractors, 0),
            2
          )::float                                        AS staffing_fee_avg,
          COALESCE(ae.active_clients, 0)::int             AS active_clients,
          COALESCE(ae.active_contractors, 0)::int         AS active_contractors,
          COALESCE(nc.new_clients, 0)::int                AS new_clients,
          COALESCE(cp.churn_clients, 0)::int              AS churn_clients,
          COALESCE(cp.buyout_clients, 0)::int             AS buyout_clients,
          COALESCE(ccp.churn_contractors, 0)::int         AS churn_contractors,
          COALESCE(ccp.buyout_contractors, 0)::int        AS buyout_contractors
        FROM period_ranges pr
        LEFT JOIN active_at_end                ae  ON ae.period_start  = pr.period_start
        LEFT JOIN new_clients_per_period       nc  ON nc.period_start  = pr.period_start
        LEFT JOIN churn_per_period             cp  ON cp.period_start  = pr.period_start
        LEFT JOIN churn_contractors_per_period ccp ON ccp.period_start = pr.period_start
        ORDER BY pr.period_start;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "staffing_history",
    "label": "Staffing History — Weekly | Monthly | Yearly",
    "dimensions": [
        {"key": "periodo", "label": "Período", "type": "string"},
        {"key": "period_start", "label": "Inicio del período", "type": "date"},
        {"key": "period_end", "label": "Fin del período", "type": "date"},
    ],
    "measures": [
        {"key": "mrr", "label": "MRR", "type": "currency"},
        {"key": "mrr_fee_total", "label": "MRR Fee Total", "type": "currency"},
        {"key": "staffing_fee_avg", "label": "Staffing Fee Avg", "type": "currency"},
        {"key": "active_clients", "label": "Active Clients", "type": "number"},
        {"key": "active_contractors", "label": "Active Contractors", "type": "number"},
        {"key": "new_clients", "label": "New Clients", "type": "number"},
        {"key": "churn_clients", "label": "Churn Clients", "type": "number"},
        {"key": "buyout_clients", "label": "Buyout Clients", "type": "number"},
        {"key": "churn_contractors", "label": "Churn Contractors", "type": "number"},
        {"key": "buyout_contractors", "label": "Buyout Contractors", "type": "number"},
    ],
    "default_filters": {"grain": "month"},
    "query": query,
}
