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
        "sa_donut_lead_source",
        "sa_bar_opps_close_month",
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
        "gr_line_arpa_pct",
        "gr_bar_active_clients",
        "gr_line_arpc",
        "gr_line_arpc_total",
        "gr_line_arpc_pct",
        "gr_line_acpa",
        "gr_combo_clients_candidates",
        "sa_line_nda_to_clients",
        "sa_table_nda_to_clients_detail",
        "sa_kpi_nda_30d",
        "sa_table_nda_30d_detail",
        "sa_bar_lead_source_month",
        "sa_bar_lead_source_30d",
        "sa_donut_lead_source_30d",
        "sa_table_lead_source_30d",
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
        "chart_key": "gr_line_arpa_pct",
        "tab_key": "growth",
        "title": "% ARPA",
        "type": "line",
        "dataset_key": "arpa_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["arpa_revenue_mom_pct", "arpa_fee_mom_pct"],
                "formatter": "percent",
            },
        },
        "position": {"x": 0, "y": 35, "w": 6, "h": 5},
        "sort_order": 140,
    },
    {
        "chart_key": "gr_bar_active_clients",
        "tab_key": "growth",
        "title": "Clientes Activos",
        "type": "bar",
        "dataset_key": "arpa_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["clientes_activos"],
                "formatter": "number",
            },
        },
        "position": {"x": 6, "y": 35, "w": 6, "h": 5},
        "sort_order": 150,
    },
    {
        "chart_key": "gr_line_arpc",
        "tab_key": "growth",
        "title": "ARPC",
        "type": "line",
        "dataset_key": "arpc_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["arpc_revenue", "arpc_fee"],
                "formatter": "currency",
            },
        },
        "position": {"x": 0, "y": 40, "w": 6, "h": 5},
        "sort_order": 160,
    },
    {
        "chart_key": "gr_line_arpc_total",
        "tab_key": "growth",
        "title": "ARPC Total",
        "type": "line",
        "dataset_key": "arpc_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["revenue_total_mes", "fee_total_mes"],
                "formatter": "currency",
            },
        },
        "position": {"x": 6, "y": 40, "w": 6, "h": 5},
        "sort_order": 170,
    },
    {
        "chart_key": "gr_line_arpc_pct",
        "tab_key": "growth",
        "title": "% ARPC",
        "type": "line",
        "dataset_key": "arpc_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["arpc_revenue_mom_pct", "arpc_fee_mom_pct"],
                "formatter": "percent",
            },
        },
        "position": {"x": 0, "y": 45, "w": 6, "h": 5},
        "sort_order": 180,
    },
    {
        "chart_key": "gr_line_acpa",
        "tab_key": "growth",
        "title": "ACPA",
        "type": "line",
        "dataset_key": "acpa_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["acpa", "acpa_mom_pct"],
                "formatter": "number",
            },
        },
        "position": {"x": 0, "y": 50, "w": 6, "h": 5},
        "sort_order": 190,
    },
    {
        "chart_key": "gr_combo_clients_candidates",
        "tab_key": "growth",
        "title": "Clientes y Candidatos Activos",
        "type": "line",
        "dataset_key": "acpa_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["candidatos_activos", "cuentas_activas"],
                "seriesTypes": ["line", "bar"],
                "formatter": "number",
            },
        },
        "position": {"x": 6, "y": 50, "w": 6, "h": 5},
        "sort_order": 200,
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
        "chart_key": "sa_line_nda_to_clients",
        "tab_key": "sales",
        "title": "NDA a Clientes",
        "type": "line",
        "dataset_key": "nda_to_clients_history",
        "config": {
            "mapping": {
                "x": "mes_close",
                "y": ["conversion_pct"],
                "formatter": "number",
                "drillKey": "fecha",
                "tooltipExtras": ["total_closed_opps", "close_win", "closed_lost", "unique_clients_closed_that_month"],
            },
        },
        "position": {"x": 0, "y": 0, "w": 6, "h": 5},
        "sort_order": 10,
    },
    {
        "chart_key": "sa_table_nda_to_clients_detail",
        "tab_key": "sales",
        "title": "Detalle",
        "type": "table",
        "dataset_key": "nda_to_clients_detail",
        "config": {
            "mapping": {
                "columns": [
                    "client_name",
                    "lead_source",
                    "opp_model",
                    "nda_d_first_time",
                    "close_d",
                    "opp_stage",
                    "is_unique_client_closed",
                ],
            },
        },
        "position": {"x": 6, "y": 0, "w": 6, "h": 5},
        "sort_order": 20,
    },
    {
        "chart_key": "sa_kpi_nda_30d",
        "tab_key": "sales",
        "title": "Conversión Global de NDA a Clientes — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "nda_to_clients_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "conversion_pct", "label": "Conversion %", "formatter": "percent"},
                    {"key": "total_closed_opps", "label": "Total cerradas", "formatter": "number"},
                    {"key": "close_win", "label": "Close Win", "formatter": "number"},
                    {"key": "closed_lost", "label": "Closed Lost", "formatter": "number"},
                ],
            },
        },
        "position": {"x": 0, "y": 5, "w": 6, "h": 5},
        "sort_order": 30,
    },
    {
        "chart_key": "sa_table_nda_30d_detail",
        "tab_key": "sales",
        "title": "Detalle - 30 días",
        "type": "table",
        "dataset_key": "nda_to_clients_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "client_name",
                    "lead_source",
                    "opp_model",
                    "nda_d_first_time",
                    "close_d",
                    "opp_stage",
                    "is_unique_client_closed",
                ],
            },
        },
        "position": {"x": 6, "y": 5, "w": 6, "h": 5},
        "sort_order": 40,
    },
    {
        "chart_key": "sa_bar_lead_source_month",
        "tab_key": "sales",
        "title": "Lead Source x Close Win/Closed Lost",
        "type": "bar",
        "dataset_key": "nda_lead_source_month",
        "config": {
            "mapping": {
                "x": "lead_source",
                "y": ["pct_of_selected_stage"],
                "formatter": "percent",
                "tooltipExtras": ["total_closed_opps", "close_win", "closed_lost", "unique_clients"],
            },
        },
        "position": {"x": 0, "y": 10, "w": 6, "h": 5},
        "sort_order": 50,
    },
    {
        "chart_key": "sa_bar_lead_source_30d",
        "tab_key": "sales",
        "title": "Lead Source x Close Win/Closed Lost - 30d",
        "type": "bar",
        "dataset_key": "nda_lead_source_30d",
        "config": {
            "mapping": {
                "x": "lead_source",
                "y": ["pct_of_selected_stage"],
                "formatter": "percent",
                "tooltipExtras": ["total_closed_opps", "close_win", "closed_lost", "unique_clients"],
            },
        },
        "position": {"x": 6, "y": 10, "w": 6, "h": 5},
        "sort_order": 60,
    },
    {
        "chart_key": "sa_donut_lead_source_30d",
        "tab_key": "sales",
        "title": "Lead Source 30d",
        "type": "donut",
        "dataset_key": "nda_lead_source_30d_basic",
        "config": {
            "mapping": {
                "x": "lead_source",
                "y": ["total_closed_opps"],
                "formatter": "number",
            },
        },
        "position": {"x": 0, "y": 15, "w": 6, "h": 5},
        "sort_order": 70,
    },
    {
        "chart_key": "sa_table_lead_source_30d",
        "tab_key": "sales",
        "title": "Lead Source 30d - Detalle",
        "type": "table",
        "dataset_key": "nda_lead_source_30d_basic",
        "config": {
            "mapping": {
                "columns": ["lead_source", "total_closed_opps", "close_win", "closed_lost"],
            },
        },
        "position": {"x": 6, "y": 15, "w": 6, "h": 5},
        "sort_order": 80,
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
