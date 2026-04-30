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


# Chart keys retired from the seed — DELETE-ed before upserts to keep seed idempotent.
RETIRED_CHART_KEYS = {
    "main": [
        "gr_kpi_recruiting_30d",
        "gr_kpi_active_staffing",
        "gr_kpi_active_recruiting",
        "gr_kpi_ltv_months",
        "gr_line_tsr_tsf_history",
        "gr_line_mrr_growth",
        "gr_table_client_lifetime",
    ],
}

# Chart keys whose layout/config we want to force-reset on this seed run
# (DELETE + INSERT instead of skipping via ON CONFLICT DO NOTHING). Use sparingly:
# this wipes any manual edits made through the editor for these chart_keys.
RESET_CHART_KEYS = {
    "main": [
        "gr_bar_active_headcount",
        "gr_table_active_headcount_detail",
        "gr_kpi_active_30d",
        "gr_table_active_30d_detail",
        "gr_table_inactive_candidates",
        "gr_line_mrr",
        "gr_area_recruiting_upfront",
        "gr_line_client_lifetime",
        "gr_kpi_client_lifetime_avg",
        "gr_line_candidate_lifetime",
        "gr_kpi_candidate_lifetime_avg",
        "gr_line_arpa",
        "gr_line_arpa_total",
    ],
}

# Reduced Fase 1 seed. Mapping convention understood by chart-factory.js:
#   { mapping: { x: dim, y: [measures], value: measure, formatter: 'currency'|'number'|'percent' } }
MAIN_CHARTS = [
    # Growth & Revenue — 2×2 layout: bar + monthly detail (top), 30d KPI + 30d detail (bottom)
    {
        "chart_key": "gr_bar_active_headcount",
        "tab_key": "growth",
        "title": "Active Headcount por mes",
        "type": "bar",
        "dataset_key": "active_headcount_history",
        "config": {"mapping": {
            "x": "month",
            "y": ["active_count"],
            "formatter": "number",
            "drillKey": "fecha",
        }},
        "position": {"x": 0, "y": 15, "w": 6, "h": 5},
        "sort_order": 70,
    },
    {
        "chart_key": "gr_table_active_headcount_detail",
        "tab_key": "growth",
        "title": "Candidatos activos (detalle por mes)",
        "type": "table",
        "dataset_key": "active_headcount_detail",
        "config": {
            "mapping": {
                "columns": ["month", "client_name", "candidate_name", "start_date"],
            },
        },
        "position": {"x": 6, "y": 15, "w": 6, "h": 5},
        "sort_order": 80,
    },
    {
        "chart_key": "gr_kpi_active_30d",
        "tab_key": "growth",
        "title": "Candidatos activos · Ventana 30 días",
        "type": "kpi",
        "dataset_key": "active_headcount_30d_total",
        "config": {"mapping": {"value": "active_count", "formatter": "number"}},
        "position": {"x": 0, "y": 20, "w": 6, "h": 5},
        "sort_order": 90,
    },
    {
        "chart_key": "gr_table_active_30d_detail",
        "tab_key": "growth",
        "title": "Detalle 30d",
        "type": "table",
        "dataset_key": "active_headcount_30d_detail",
        "config": {
            "mapping": {
                "columns": ["cutoff_date", "client_name", "candidate_name", "start_date"],
            },
        },
        "position": {"x": 6, "y": 20, "w": 6, "h": 5},
        "sort_order": 100,
    },
    {
        "chart_key": "gr_table_inactive_candidates",
        "tab_key": "growth",
        "title": "Candidatos inactivos (detalle por mes)",
        "type": "table",
        "dataset_key": "inactive_candidates_detail",
        "config": {
            "mapping": {
                "columns": ["month", "client_name", "candidate_name", "start_date", "end_date"],
            },
        },
        "position": {"x": 0, "y": 25, "w": 12, "h": 5},
        "sort_order": 110,
    },
    {
        "chart_key": "gr_line_arpa",
        "tab_key": "growth",
        "title": "ARPA",
        "type": "line",
        "dataset_key": "arpa_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["arpa_revenue", "arpa_fee"],
                "formatter": "currency",
            },
        },
        "position": {"x": 0, "y": 30, "w": 6, "h": 5},
        "sort_order": 120,
    },
    {
        "chart_key": "gr_line_arpa_total",
        "tab_key": "growth",
        "title": "ARPA Total",
        "type": "line",
        "dataset_key": "arpa_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["revenue_total_mes", "fee_total_mes"],
                "formatter": "currency",
            },
        },
        "position": {"x": 6, "y": 30, "w": 6, "h": 5},
        "sort_order": 130,
    },
    {
        "chart_key": "gr_line_mrr",
        "tab_key": "growth",
        "title": "MRR",
        "type": "line",
        "dataset_key": "mrr_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["mrr_total", "growth_pct"],
                "twinAxis": True,
                "formatter": "currency",
                "formatter2": "percent",
            },
        },
        "position": {"x": 0, "y": 0, "w": 6, "h": 5},
        "sort_order": 10,
    },
    {
        "chart_key": "gr_area_recruiting_upfront",
        "tab_key": "growth",
        "title": "Recruiting (upfront payment)",
        "type": "area",
        "dataset_key": "recruiting_upfront",
        "config": {
            "mapping": {
                "x": "mes_cierre",
                "y": ["monto_recruiting"],
                "formatter": "currency",
            },
        },
        "position": {"x": 6, "y": 0, "w": 6, "h": 5},
        "sort_order": 20,
    },
    {
        "chart_key": "gr_line_client_lifetime",
        "tab_key": "growth",
        "title": "Tiempo de Vida del Cliente en Meses (Staffing)",
        "type": "line",
        "dataset_key": "client_lifetime_detail",
        "config": {
            "mapping": {
                "x": "client_name",
                "y": ["meses_con_al_menos_un_cliente"],
                "formatter": "number",
                "tooltipExtras": ["first_month_active", "last_month_active"],
                "hideXLabels": True,
                "preserveOrder": True,
            },
        },
        "position": {"x": 0, "y": 5, "w": 8, "h": 5},
        "sort_order": 30,
    },
    {
        "chart_key": "gr_kpi_client_lifetime_avg",
        "tab_key": "growth",
        "title": "Promedio meses por cliente",
        "type": "kpi",
        "dataset_key": "client_lifetime_avg",
        "config": {"mapping": {"value": "promedio_meses_por_cliente", "formatter": "number"}},
        "position": {"x": 8, "y": 5, "w": 4, "h": 5},
        "sort_order": 40,
    },
    {
        "chart_key": "gr_line_candidate_lifetime",
        "tab_key": "growth",
        "title": "Tiempo de Vida del Candidato en Meses (Staffing)",
        "type": "line",
        "dataset_key": "candidate_lifetime_detail",
        "config": {
            "mapping": {
                "x": "row_key",
                "y": ["meses_activo"],
                "formatter": "number",
                "tooltipExtras": ["candidate_name", "client_name", "first_month_active", "last_month_active"],
                "hideXLabels": True,
                "preserveOrder": True,
            },
        },
        "position": {"x": 0, "y": 10, "w": 8, "h": 5},
        "sort_order": 50,
    },
    {
        "chart_key": "gr_kpi_candidate_lifetime_avg",
        "tab_key": "growth",
        "title": "Promedio meses por candidato en cliente",
        "type": "kpi",
        "dataset_key": "candidate_lifetime_avg",
        "config": {"mapping": {"value": "promedio_meses_por_candidato_en_cliente", "formatter": "number"}},
        "position": {"x": 8, "y": 10, "w": 4, "h": 5},
        "sort_order": 60,
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


def delete_retired_charts(cur, dashboard_id: int, chart_keys: list[str]) -> int:
    if not chart_keys:
        return 0
    cur.execute(
        """
        DELETE FROM dashboard_charts
        WHERE dashboard_id = %s
          AND chart_key = ANY(%s)
        """,
        (dashboard_id, list(chart_keys)),
    )
    return cur.rowcount or 0


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

        for slug, retired in RETIRED_CHART_KEYS.items():
            removed = delete_retired_charts(cur, ids[slug], retired)
            print(f"{slug} retired charts: {removed} deleted")

        for slug, reset in RESET_CHART_KEYS.items():
            removed = delete_retired_charts(cur, ids[slug], reset)
            print(f"{slug} reset charts: {removed} deleted (will re-insert from seed)")

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
