"""
Seed initial dashboards + charts into the dashboards/dashboard_charts tables.

Idempotent: UPSERT by (slug) for dashboards and (dashboard_id, chart_key) for charts.
Does NOT overwrite edits made via the editor after initial seed (UPDATE only touches
rows we explicitly list here, keyed by chart_key).

Usage (from repo root):
    python -m backend.dashboards.seed
    DASHBOARD_EDITOR_EMAIL=pgonzales@vintti.com python -m backend.dashboards.seed
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running via `python backend/dashboards/seed.py` or `-m backend.dashboards.seed`.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg2.extras import Json

from db import get_connection


DASHBOARDS = [
    {
        "slug": "main",
        "name": "Main Dashboard",
        "layout": {
            "tabs": [
                {"key": "growth", "label": "Growth & Revenue"},
                {"key": "account-management", "label": "Account Management"},
                {"key": "sales", "label": "Sales"},
                {"key": "operations", "label": "Operations"},
            ],
        },
    },
    {
        "slug": "sales-force",
        "name": "Sales Force",
        "layout": {"tabs": [{"key": "default", "label": "Sales Force"}]},
    },
    {
        "slug": "recruiter-lab",
        "name": "Recruiter Lab",
        "layout": {"tabs": [{"key": "default", "label": "Recruiter Lab"}]},
    },
]


# Reduced Fase 1 seed (12 charts). Mapping convention understood by chart-factory.js:
#   { mapping: { x: dim, y: [measures], value: measure, formatter: 'currency'|'number'|'percent' } }
MAIN_CHARTS = [
    # Growth & Revenue
    {
        "chart_key": "gr_kpi_recruiting_30d",
        "tab_key": "growth",
        "title": "Recruiting Revenue (30d)",
        "type": "kpi",
        "dataset_key": "management_dashboard",
        "config": {"mapping": {"value": "recruiting_revenue_30d", "formatter": "currency"}},
        "position": {"x": 0, "y": 0, "w": 3, "h": 2},
        "sort_order": 10,
    },
    {
        "chart_key": "gr_kpi_active_staffing",
        "tab_key": "growth",
        "title": "Active Staffing",
        "type": "kpi",
        "dataset_key": "management_dashboard",
        "config": {"mapping": {"value": "active_staffing", "formatter": "number"}},
        "position": {"x": 3, "y": 0, "w": 3, "h": 2},
        "sort_order": 20,
    },
    {
        "chart_key": "gr_kpi_active_recruiting",
        "tab_key": "growth",
        "title": "Active Recruiting",
        "type": "kpi",
        "dataset_key": "management_dashboard",
        "config": {"mapping": {"value": "active_recruiting", "formatter": "number"}},
        "position": {"x": 6, "y": 0, "w": 3, "h": 2},
        "sort_order": 30,
    },
    {
        "chart_key": "gr_kpi_ltv_months",
        "tab_key": "growth",
        "title": "LTV (meses)",
        "type": "kpi",
        "dataset_key": "management_dashboard",
        "config": {"mapping": {"value": "ltv_months", "formatter": "number"}},
        "position": {"x": 9, "y": 0, "w": 3, "h": 2},
        "sort_order": 40,
    },
    {
        "chart_key": "gr_line_tsr_tsf_history",
        "tab_key": "growth",
        "title": "TSR + TSF por mes",
        "type": "line",
        "dataset_key": "ts_history",
        "config": {"mapping": {"x": "month", "y": ["tsr", "tsf"], "formatter": "currency"}},
        "position": {"x": 0, "y": 2, "w": 8, "h": 5},
        "sort_order": 50,
    },
    {
        "chart_key": "gr_bar_active_headcount",
        "tab_key": "growth",
        "title": "Active Headcount por mes",
        "type": "bar",
        "dataset_key": "active_headcount_history",
        "config": {"mapping": {"x": "month", "y": ["active_count"], "formatter": "number"}},
        "position": {"x": 8, "y": 2, "w": 4, "h": 5},
        "sort_order": 60,
    },
    {
        "chart_key": "gr_line_mrr",
        "tab_key": "growth",
        "title": "MRR",
        "type": "line",
        "dataset_key": "mrr_history",
        "config": {
            "filters": {"metric": "Revenue"},
            "mapping": {"x": "mes", "y": ["mrr_total"], "formatter": "currency"},
        },
        "position": {"x": 0, "y": 7, "w": 8, "h": 5},
        "sort_order": 70,
    },
    {
        "chart_key": "gr_line_mrr_growth",
        "tab_key": "growth",
        "title": "MRR Growth %",
        "type": "line",
        "dataset_key": "mrr_history",
        "config": {
            "filters": {"metric": "Revenue"},
            "mapping": {"x": "mes", "y": ["growth_pct"], "formatter": "percent"},
        },
        "position": {"x": 8, "y": 7, "w": 4, "h": 5},
        "sort_order": 80,
    },

    # Account Management
    {
        "chart_key": "am_bar_opps_by_stage",
        "tab_key": "account-management",
        "title": "Opportunities por Stage",
        "type": "bar",
        "dataset_key": "opportunities",
        "config": {"mapping": {"x": "opp_stage", "y": ["opportunity_id"], "agg": "count", "formatter": "number"}},
        "position": {"x": 0, "y": 0, "w": 8, "h": 5},
        "sort_order": 10,
    },
    {
        "chart_key": "am_kpi_close_win_count",
        "tab_key": "account-management",
        "title": "Close Win (total)",
        "type": "kpi",
        "dataset_key": "opportunities",
        "config": {
            "filters": {"stage": "Close Win"},
            "mapping": {"value": "opportunity_id", "agg": "count", "formatter": "number"},
        },
        "position": {"x": 8, "y": 0, "w": 4, "h": 2},
        "sort_order": 20,
    },

    # Sales
    {
        "chart_key": "sa_donut_lead_source",
        "tab_key": "sales",
        "title": "Lead Source",
        "type": "donut",
        "dataset_key": "opportunities",
        "config": {"mapping": {"x": "lead_source", "y": ["opportunity_id"], "agg": "count"}},
        "position": {"x": 0, "y": 0, "w": 6, "h": 5},
        "sort_order": 10,
    },
    {
        "chart_key": "sa_bar_opps_close_month",
        "tab_key": "sales",
        "title": "Opportunities by Close Month",
        "type": "bar",
        "dataset_key": "opportunities",
        "config": {"mapping": {"x": "opp_close_date", "y": ["opportunity_id"], "agg": "count", "bucket": "month"}},
        "position": {"x": 6, "y": 0, "w": 6, "h": 5},
        "sort_order": 20,
    },

    # Operations
    {
        "chart_key": "op_bar_batches_by_month",
        "tab_key": "operations",
        "title": "Batches por mes",
        "type": "bar",
        "dataset_key": "batch_sourcing",
        "config": {"mapping": {"x": "month", "y": ["batch_id"], "agg": "count", "formatter": "number"}},
        "position": {"x": 0, "y": 0, "w": 8, "h": 5},
        "sort_order": 10,
    },
    {
        "chart_key": "op_kpi_avg_sourcing_days",
        "tab_key": "operations",
        "title": "Avg días sourcing → batch",
        "type": "kpi",
        "dataset_key": "batch_sourcing",
        "config": {"mapping": {"value": "days_from_sourcing", "agg": "avg", "formatter": "number"}},
        "position": {"x": 8, "y": 0, "w": 4, "h": 2},
        "sort_order": 20,
    },
]


def upsert_dashboard(cur, slug: str, name: str, layout: dict) -> int:
    cur.execute(
        """
        INSERT INTO dashboards (slug, name, layout_json)
        VALUES (%s, %s, %s)
        ON CONFLICT (slug) DO UPDATE SET
          name = EXCLUDED.name,
          layout_json = EXCLUDED.layout_json,
          updated_at = NOW()
        RETURNING id
        """,
        (slug, name, Json(layout)),
    )
    return cur.fetchone()[0]


def upsert_chart(cur, dashboard_id: int, chart: dict) -> None:
    cur.execute(
        """
        INSERT INTO dashboard_charts
          (dashboard_id, chart_key, tab_key, title, type, dataset_key,
           config_json, position_json, sort_order)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (dashboard_id, chart_key) DO NOTHING
        """,
        (
            dashboard_id,
            chart["chart_key"],
            chart["tab_key"],
            chart["title"],
            chart["type"],
            chart["dataset_key"],
            Json(chart["config"]),
            Json(chart["position"]),
            chart.get("sort_order", 0),
        ),
    )


def main() -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        ids = {}
        for d in DASHBOARDS:
            ids[d["slug"]] = upsert_dashboard(cur, d["slug"], d["name"], d["layout"])
            print(f"dashboard {d['slug']}: id={ids[d['slug']]}")

        for chart in MAIN_CHARTS:
            upsert_chart(cur, ids["main"], chart)
        print(f"main charts: {len(MAIN_CHARTS)} upserted (ON CONFLICT DO NOTHING, so edits preserved)")

        conn.commit()
        cur.close()
        print("seed complete")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
