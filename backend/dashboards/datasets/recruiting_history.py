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
    return "week" if raw in ("week", "weekly", "semana", "w") else "month"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = datetime.utcnow().date()
    grain = _grain(filters)

    if grain == "week":
        default_from = today - timedelta(weeks=12)
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
        recruiting_hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            COALESCE(ho.revenue, 0)::numeric AS revenue,
            o.opp_close_date::date           AS close_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Recruiting'
            AND o.opp_close_date IS NOT NULL
        ),
        first_close_per_account AS (
          SELECT account_id, MIN(close_d) AS first_close_d
          FROM recruiting_hires
          WHERE account_id IS NOT NULL
          GROUP BY account_id
        ),
        agg_per_period AS (
          SELECT
            pr.period_start,
            COALESCE(SUM(rh.revenue), 0)            AS revenue,
            COUNT(rh.candidate_id)                  AS new_ftes,
            COUNT(DISTINCT rh.account_id)           AS active_clients
          FROM period_ranges pr
          LEFT JOIN recruiting_hires rh
            ON rh.close_d BETWEEN pr.period_start AND pr.period_end
          GROUP BY pr.period_start
        ),
        new_clients_per_period AS (
          SELECT
            pr.period_start,
            COUNT(*) AS new_clients
          FROM period_ranges pr
          LEFT JOIN first_close_per_account fc
            ON fc.first_close_d BETWEEN pr.period_start AND pr.period_end
          GROUP BY pr.period_start
        )
        SELECT
          to_char(pr.period_start, {period_format})::text AS periodo,
          pr.period_start,
          ({period_end_expr})                             AS period_end,
          COALESCE(ap.revenue, 0)::bigint                 AS revenue,
          COALESCE(ap.new_ftes, 0)::int                   AS new_ftes,
          COALESCE(nc.new_clients, 0)::int                AS new_clients,
          COALESCE(ap.active_clients, 0)::int             AS active_clients
        FROM period_ranges pr
        LEFT JOIN agg_per_period         ap ON ap.period_start = pr.period_start
        LEFT JOIN new_clients_per_period nc ON nc.period_start = pr.period_start
        ORDER BY pr.period_start;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "recruiting_history",
    "label": "Recruiting History — Weekly | Monthly",
    "dimensions": [
        {"key": "periodo", "label": "Período", "type": "string"},
        {"key": "period_start", "label": "Inicio del período", "type": "date"},
        {"key": "period_end", "label": "Fin del período", "type": "date"},
    ],
    "measures": [
        {"key": "revenue", "label": "Revenue", "type": "currency"},
        {"key": "new_ftes", "label": "New FTEs", "type": "number"},
        {"key": "new_clients", "label": "New Clients", "type": "number"},
        {"key": "active_clients", "label": "Active Clients", "type": "number"},
    ],
    "default_filters": {"grain": "month"},
    "query": query,
}
