"""Revenue Generated YTD per AE — feeds the fuel-tank card.

For each fetch (one `sales_lead` per call), returns a single row with:
  - YTD revenue total + per-model breakdown (Staffing salary+fee, Recruiting revenue)
  - Annual goal (hardcoded constant — set per AE in `ANNUAL_GOALS`)
  - Percent-of-goal, dollars remaining, months remaining in year
  - Per-model percent of total + percent of goal (drive the right-side bars)

The frontend (`ae` tab in `docs/dashboard.html`) renders two cards by fetching
with `data-override-sales_lead="mariano@vintti.com"` and
`data-override-sales_lead="bahia@vintti.com"`. Adding a new AE = add an entry
in `ANNUAL_GOALS` and add another card to the HTML.
"""
from __future__ import annotations

from datetime import date, datetime


# AE roster. The card aggregates ALL of these into a single fuel tank.
# Add an email here to include another AE; nothing else changes.
SALES_LEADS = ("mariano@vintti.com", "bahia@vintti.com")

# Combined annual revenue goal across the AEs above (USD).
# Change here, not in SQL.
ANNUAL_GOAL = 1_000_000

# Human-friendly title shown in the card.
AE_NAME = "Mariano + Bahia"


def _parse_int(value, default: int) -> int:
    try:
        n = int(str(value).strip())
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    return default


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    today = datetime.utcnow().date()
    year = _parse_int(filters.get("year"), today.year)
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    period_end = min(today, year_end)
    # Months left in the calendar year *after* the current month, e.g. May → Jun-Dec = 7.
    months_remaining = max(0, 12 - period_end.month)

    sql = """
        WITH per_model AS (
          SELECT
            o.opp_model,
            SUM(
              CASE
                WHEN o.opp_model = 'Recruiting'
                  THEN COALESCE(ho.revenue, 0)
                ELSE COALESCE(ho.salary, 0) + COALESCE(ho.fee, 0)
              END
            )::numeric AS revenue
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE TRIM(LOWER(o.opp_sales_lead)) IN %(sales_leads)s
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND o.opp_close_date IS NOT NULL
            AND NULLIF(o.opp_close_date::text, '')::date >= %(year_start)s::date
            AND NULLIF(o.opp_close_date::text, '')::date <= %(period_end)s::date
          GROUP BY o.opp_model
        ),
        rolled AS (
          SELECT
            COALESCE(MAX(CASE WHEN opp_model = 'Staffing'   THEN revenue END), 0)::numeric AS staffing_revenue_ytd,
            COALESCE(MAX(CASE WHEN opp_model = 'Recruiting' THEN revenue END), 0)::numeric AS recruiting_revenue_ytd
          FROM per_model
        )
        SELECT
          %(ae_name)s::text                                                 AS ae_name,
          %(year)s::int                                                     AS year,
          %(months_remaining)s::int                                         AS months_remaining,
          %(annual_goal)s::bigint                                           AS annual_goal,
          r.staffing_revenue_ytd::bigint                                    AS staffing_revenue_ytd,
          r.recruiting_revenue_ytd::bigint                                  AS recruiting_revenue_ytd,
          (r.staffing_revenue_ytd + r.recruiting_revenue_ytd)::bigint       AS total_revenue_ytd,
          GREATEST(%(annual_goal)s::bigint - (r.staffing_revenue_ytd + r.recruiting_revenue_ytd)::bigint, 0)::bigint
                                                                            AS remaining,
          ROUND(100.0 * (r.staffing_revenue_ytd + r.recruiting_revenue_ytd)
                / NULLIF(%(annual_goal)s, 0), 1)::float                     AS pct_of_goal,
          ROUND(100.0 * r.staffing_revenue_ytd
                / NULLIF(r.staffing_revenue_ytd + r.recruiting_revenue_ytd, 0), 1)::float
                                                                            AS staffing_pct_of_total,
          ROUND(100.0 * r.staffing_revenue_ytd
                / NULLIF(%(annual_goal)s, 0), 1)::float                     AS staffing_pct_of_goal,
          ROUND(100.0 * r.recruiting_revenue_ytd
                / NULLIF(r.staffing_revenue_ytd + r.recruiting_revenue_ytd, 0), 1)::float
                                                                            AS recruiting_pct_of_total,
          ROUND(100.0 * r.recruiting_revenue_ytd
                / NULLIF(%(annual_goal)s, 0), 1)::float                     AS recruiting_pct_of_goal
        FROM rolled r;
    """

    return sql, {
        "sales_leads": SALES_LEADS,
        "ae_name": AE_NAME,
        "year": year,
        "annual_goal": ANNUAL_GOAL,
        "months_remaining": months_remaining,
        "year_start": year_start,
        "period_end": period_end,
    }


DATASET = {
    "key": "revenue_ae_card",
    "label": "Revenue Generated (Mariano + Bahia) — YTD vs anual goal",
    "dimensions": [
        {"key": "ae_name", "label": "AE name", "type": "string"},
        {"key": "year", "label": "Year", "type": "number"},
        {"key": "months_remaining", "label": "Meses restantes", "type": "number"},
    ],
    "measures": [
        {"key": "annual_goal", "label": "Objetivo anual", "type": "currency"},
        {"key": "total_revenue_ytd", "label": "Revenue total YTD", "type": "currency"},
        {"key": "staffing_revenue_ytd", "label": "Staffing YTD", "type": "currency"},
        {"key": "recruiting_revenue_ytd", "label": "Recruiting YTD", "type": "currency"},
        {"key": "remaining", "label": "Restante para meta", "type": "currency"},
        {"key": "pct_of_goal", "label": "% del objetivo", "type": "percent"},
        {"key": "staffing_pct_of_total", "label": "Staffing % del total", "type": "percent"},
        {"key": "staffing_pct_of_goal", "label": "Staffing % del objetivo", "type": "percent"},
        {"key": "recruiting_pct_of_total", "label": "Recruiting % del total", "type": "percent"},
        {"key": "recruiting_pct_of_goal", "label": "Recruiting % del objetivo", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
