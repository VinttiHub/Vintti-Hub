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
        "am_area_new_clients_per_month",
        "am_table_new_clients_month_detail",
        "am_kpi_new_clients_30d",
        "am_table_new_clients_30d_detail",
        "op_bar_batches_by_month",
        "op_kpi_avg_sourcing_days",
        "am_bar_opps_by_stage",
        "am_kpi_close_win_count",
        "sa_line_nda_close_win",
        "sa_table_nda_close_win_detail",
        "sa_kpi_nda_close_win_30d",
        "sa_kpi_nda_close_win_30d_breakdown",
        "sa_table_nda_close_win_30d_detail",
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
        "sa_area_new_clients_per_month",
        "sa_table_new_clients_month_detail",
        "sa_kpi_new_clients_30d",
        "sa_table_new_clients_30d_detail",
        "op_bar_new_placements",
        "op_table_new_placements_detail",
        "op_line_placement_time",
        "op_table_placement_time_detail",
        "op_kpi_placement_time_30d",
        "op_table_placement_time_30d_detail",
        "op_line_placement_time_repl",
        "op_table_placement_time_detail_repl",
        "op_kpi_placement_time_30d_repl",
        "op_table_placement_time_30d_detail_repl",
        "op_line_batch_delivery_time",
        "op_table_batch_delivery_time_detail",
        "op_line_batch_delivery_time_month",
        "op_table_batch_delivery_time_month_detail",
        "op_kpi_batch_delivery_time_30d",
        "op_table_batch_delivery_time_30d_detail",
        "op_line_nda_close_win",
        "op_table_nda_close_win_detail",
        "op_kpi_nda_close_win_30d",
        "op_kpi_nda_close_win_30d_breakdown",
        "op_table_nda_close_win_30d_detail",
        "op_line_interview_conversion",
        "op_table_interview_conversion_detail",
        "op_line_interview_conversion_30d",
        "op_kpi_interview_conversion_30d",
        "op_line_sent_hired_30d",
        "op_table_sent_hired_30d_detail",
        "op_kpi_sent_hired_30d",
        "am_line_client_churn",
        "am_table_client_churn_detail",
        "am_kpi_client_churn_30d",
        "am_table_client_churn_30d_detail",
        "am_line_candidate_churn",
        "am_table_candidate_churn_detail",
        "am_kpi_candidate_churn_30d",
        "am_table_candidate_churn_30d_detail",
        "am_line_candidate_churn_window",
        "am_table_candidate_churn_window_detail",
        "am_kpi_candidate_churn_window",
        "am_table_candidate_churn_window_cohort_detail",
        "am_line_crr",
        "am_table_crr_month_detail",
        "am_kpi_crr_30d_growth",
        "am_kpi_crr_30d_retention",
        "am_kpi_crr_30d",
        "am_table_crr_30d_detail",
        "am_line_candidate_retention",
        "am_table_replacements_detail",
        "am_line_replacements_pct",
        "am_table_replacements_month_detail",
        "am_line_lara_winrate",
        "am_table_lara_winrate_month_detail",
        "am_kpi_lara_winrate_30d",
        "am_kpi_lara_winrate_30d_breakdown",
        "am_table_lara_winrate_30d_detail",
        "am_line_clients_multi",
        "am_table_clients_multi_month_detail",
        "am_kpi_clients_multi_30d",
        "am_kpi_clients_multi_30d_breakdown",
        "am_table_clients_multi_30d_detail",
        "am_line_headcount_growth",
        "am_table_headcount_growth_month_detail",
        "am_kpi_headcount_growth_30d",
        "am_table_headcount_growth_30d_detail",
        "am_donut_risk_score",
        "am_table_risk_score_detail",
        "am_bar_risk_score_points",
        "am_bar_risk_score_distribution",
        "am_line_nrr",
        "am_table_nrr_month_detail",
        "am_kpi_nrr_30d",
        "am_table_nrr_30d_detail",
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
        "chart_key": "am_line_client_churn",
        "tab_key": "account-management",
        "title": "Clientes",
        "type": "line",
        "dataset_key": "client_churn_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["clientes_activos", "bajas_real", "churn_real_pct"],
                "formatter": "number",
                "drillKey": "fecha_client_churn",
                "tooltipExtras": [
                    "bajas_buyout",
                    "bajas_total_staffing",
                    "buyout_pct",
                    "churn_total_staffing_pct",
                ],
            },
        },
        "position": {"x": 0, "y": 0, "w": 6, "h": 5},
        "sort_order": 10,
    },
    {
        "chart_key": "am_table_client_churn_detail",
        "tab_key": "account-management",
        "title": "Details - Clientes Churn",
        "type": "table",
        "dataset_key": "client_churn_month_detail",
        "config": {
            "mapping": {
                "columns": ["mes", "client_name", "fecha_baja", "estado_cliente_mes"],
            },
        },
        "position": {"x": 6, "y": 0, "w": 6, "h": 5},
        "sort_order": 20,
    },
    {
        "chart_key": "am_kpi_client_churn_30d",
        "tab_key": "account-management",
        "title": "Churn de clientes (Staffing) — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "client_churn_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "clientes_activos", "label": "Clientes activos", "formatter": "number"},
                    {"key": "bajas_real", "label": "Bajas Staffing", "formatter": "number"},
                    {"key": "bajas_buyout", "label": "Bajas Buyout", "formatter": "number"},
                    {"key": "bajas_total_staffing", "label": "Bajas Staffing + Buyout", "formatter": "number"},
                    {"key": "churn_real_pct", "label": "Churn Staffing %", "formatter": "percent"},
                    {"key": "buyout_pct", "label": "Churn Buyout %", "formatter": "percent"},
                    {"key": "churn_total_staffing_pct", "label": "Churn Staffing + Buyout %", "formatter": "percent"},
                ],
            },
        },
        "position": {"x": 0, "y": 5, "w": 6, "h": 5},
        "sort_order": 30,
    },
    {
        "chart_key": "am_table_client_churn_30d_detail",
        "tab_key": "account-management",
        "title": "Details - Clientes Churn - 30",
        "type": "table",
        "dataset_key": "client_churn_30d_detail",
        "config": {
            "mapping": {
                "columns": ["win_ini", "win_fin", "client_name", "fecha_baja", "estado_cliente_ventana"],
            },
        },
        "position": {"x": 6, "y": 5, "w": 6, "h": 5},
        "sort_order": 40,
    },
    {
        "chart_key": "am_line_candidate_churn",
        "tab_key": "account-management",
        "title": "Candidatos",
        "type": "line",
        "dataset_key": "candidate_churn_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["activos_inicio", "bajas", "churn_pct"],
                "formatter": "number",
                "drillKey": "fecha_candidate_churn",
                "tooltipExtras": ["bajas_real", "bajas_buyout", "churn_real_pct", "buyout_pct"],
            },
        },
        "position": {"x": 0, "y": 10, "w": 6, "h": 5},
        "sort_order": 50,
    },
    {
        "chart_key": "am_table_candidate_churn_detail",
        "tab_key": "account-management",
        "title": "Details - Candidatos Churn",
        "type": "table",
        "dataset_key": "candidate_churn_month_detail",
        "config": {
            "mapping": {
                "columns": ["mes", "client_name", "candidate_name", "start_d", "end_d", "estado"],
            },
        },
        "position": {"x": 6, "y": 10, "w": 6, "h": 5},
        "sort_order": 60,
    },
    {
        "chart_key": "am_kpi_candidate_churn_30d",
        "tab_key": "account-management",
        "title": "Churn de candidatos (Staffing) — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "candidate_churn_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "candidatos_activos", "label": "Candidatos", "formatter": "number"},
                    {"key": "bajas_real", "label": "Bajas Staffing", "formatter": "number"},
                    {"key": "bajas_buyout", "label": "Bajas Buyout", "formatter": "number"},
                    {"key": "bajas_total_staffing", "label": "Bajas Staffing + Buyout", "formatter": "number"},
                    {"key": "churn_real_pct", "label": "Churn Staffing %", "formatter": "percent"},
                    {"key": "buyout_pct", "label": "Churn Buyout %", "formatter": "percent"},
                    {"key": "churn_total_staffing_pct", "label": "Churn Staffing + Buyout %", "formatter": "percent"},
                ],
            },
        },
        "position": {"x": 0, "y": 15, "w": 6, "h": 5},
        "sort_order": 70,
    },
    {
        "chart_key": "am_table_candidate_churn_30d_detail",
        "tab_key": "account-management",
        "title": "Details - Candidatos Churn - 30",
        "type": "table",
        "dataset_key": "candidate_churn_30d_detail",
        "config": {
            "mapping": {
                "columns": ["win_ini", "client_name", "candidate_name", "start_d", "end_d", "estado"],
            },
        },
        "position": {"x": 6, "y": 15, "w": 6, "h": 5},
        "sort_order": 80,
    },
    {
        "chart_key": "am_line_candidate_churn_window",
        "tab_key": "account-management",
        "title": "3 y 6 meses",
        "type": "line",
        "dataset_key": "candidate_churn_window_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["starts", "bajas_real", "churn_real_pct"],
                "formatter": "number",
                "drillKey": "fecha_candidate_window_churn",
                "tooltipExtras": [
                    "bajas",
                    "bajas_buyout",
                    "activos_al_cierre",
                    "churn_pct",
                    "buyout_pct",
                ],
            },
        },
        "position": {"x": 0, "y": 20, "w": 6, "h": 5},
        "sort_order": 90,
    },
    {
        "chart_key": "am_table_candidate_churn_window_detail",
        "tab_key": "account-management",
        "title": "Details - 3 y 6 meses",
        "type": "table",
        "dataset_key": "candidate_churn_window_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "win_ini",
                    "m_fin",
                    "candidate_name",
                    "account_name",
                    "start_d",
                    "end_d",
                    "baja_tipo",
                ],
            },
        },
        "position": {"x": 6, "y": 20, "w": 6, "h": 5},
        "sort_order": 100,
    },
    {
        "chart_key": "am_kpi_candidate_churn_window",
        "tab_key": "account-management",
        "title": "3 y 6 meses con ventana de 90 o 180 días",
        "type": "kpi",
        "dataset_key": "candidate_churn_window_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "candidatos", "label": "Candidatos", "formatter": "number"},
                    {"key": "bajas_real", "label": "Bajas Staffing", "formatter": "number"},
                    {"key": "bajas_buyout", "label": "Bajas Buyout", "formatter": "number"},
                    {"key": "bajas", "label": "Bajas Staffing + Buyout", "formatter": "number"},
                    {"key": "churn_real_pct", "label": "Churn Staffing %", "formatter": "percent"},
                    {"key": "buyout_pct", "label": "Churn Buyout %", "formatter": "percent"},
                    {"key": "churn_pct", "label": "Churn Staffing + Buyout %", "formatter": "percent"},
                ],
            },
        },
        "position": {"x": 0, "y": 25, "w": 6, "h": 5},
        "sort_order": 110,
    },
    {
        "chart_key": "am_table_candidate_churn_window_cohort_detail",
        "tab_key": "account-management",
        "title": "Details - 3 y 6 meses - Cohorte",
        "type": "table",
        "dataset_key": "candidate_churn_window_detail",
        "config": {
            "mapping": {
                "columns": [
                    "corte_d",
                    "win_ini",
                    "candidate_name",
                    "account_name",
                    "start_d",
                    "end_d",
                    "baja_tipo",
                ],
            },
        },
        "position": {"x": 6, "y": 25, "w": 6, "h": 5},
        "sort_order": 120,
    },
    {
        "chart_key": "am_line_crr",
        "tab_key": "account-management",
        "title": "CRR",
        "type": "line",
        "dataset_key": "crr_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["grr_pct", "crr_pct"],
                "formatter": "number",
                "drillKey": "fecha_crr",
                "tooltipExtras": [
                    "clientes_activos_inicio",
                    "clientes_activos_fin",
                    "clientes_retenidos",
                    "churn_inicio_pct",
                ],
            },
        },
        "position": {"x": 0, "y": 30, "w": 6, "h": 5},
        "sort_order": 130,
    },
    {
        "chart_key": "am_table_crr_month_detail",
        "tab_key": "account-management",
        "title": "Detalle CRR",
        "type": "table",
        "dataset_key": "crr_month_detail",
        "config": {
            "mapping": {
                "columns": ["mes", "mes_fin", "tipo", "account_id", "client_name"],
            },
        },
        "position": {"x": 6, "y": 30, "w": 6, "h": 5},
        "sort_order": 140,
    },
    {
        "chart_key": "am_kpi_crr_30d_growth",
        "tab_key": "account-management",
        "title": "Growth %",
        "type": "kpi",
        "dataset_key": "crr_30d_summary",
        "config": {"mapping": {"value": "crr_pct", "formatter": "percent"}},
        "position": {"x": 0, "y": 35, "w": 3, "h": 5},
        "sort_order": 150,
    },
    {
        "chart_key": "am_kpi_crr_30d_retention",
        "tab_key": "account-management",
        "title": "Retention %",
        "type": "kpi",
        "dataset_key": "crr_30d_summary",
        "config": {"mapping": {"value": "grr_pct", "formatter": "percent"}},
        "position": {"x": 3, "y": 35, "w": 3, "h": 5},
        "sort_order": 160,
    },
    {
        "chart_key": "am_kpi_crr_30d",
        "tab_key": "account-management",
        "title": "CRR - 30",
        "type": "kpi",
        "dataset_key": "crr_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "inicio", "label": "Inicio", "formatter": "number"},
                    {"key": "fin", "label": "Fin", "formatter": "number"},
                    {"key": "retenidos", "label": "Retenidos", "formatter": "number"},
                ],
            },
        },
        "position": {"x": 6, "y": 35, "w": 3, "h": 5},
        "sort_order": 170,
    },
    {
        "chart_key": "am_table_crr_30d_detail",
        "tab_key": "account-management",
        "title": "Detalle - 30",
        "type": "table",
        "dataset_key": "crr_30d_detail",
        "config": {
            "mapping": {
                "columns": ["win_ini", "win_fin", "tipo", "account_id", "client_name"],
            },
        },
        "position": {"x": 9, "y": 35, "w": 3, "h": 5},
        "sort_order": 180,
    },
    {
        "chart_key": "am_line_candidate_retention",
        "tab_key": "account-management",
        "title": "Retention Rate de Candidatos - Modificados",
        "type": "line",
        "dataset_key": "candidate_retention_rate",
        "config": {
            "mapping": {
                "x": "cohorte_mes",
                "y": ["start_candidate", "stay_candidate", "retention"],
                "formatter": "number",
            },
        },
        "position": {"x": 0, "y": 40, "w": 6, "h": 5},
        "sort_order": 190,
    },
    {
        "chart_key": "am_table_replacements_detail",
        "tab_key": "account-management",
        "title": "Detalle % de reemplazos realizados",
        "type": "table",
        "dataset_key": "replacements_detail",
        "config": {
            "mapping": {
                "columns": [
                    "month",
                    "client_name",
                    "opp_model",
                    "opp_stage",
                    "replaced_candidate_id",
                    "old_end_date",
                    "new_candidate_id",
                    "new_start_date",
                    "days_to_replace",
                ],
            },
        },
        "position": {"x": 6, "y": 40, "w": 6, "h": 5},
        "sort_order": 200,
    },
    {
        "chart_key": "am_line_replacements_pct",
        "tab_key": "account-management",
        "title": "% de reemplazos realizados",
        "type": "line",
        "dataset_key": "replacements_history",
        "config": {
            "mapping": {
                "x": "month",
                "y": ["pct_replacements"],
                "formatter": "number",
                "drillKey": "fecha_replacements",
                "tooltipExtras": [
                    "replacements",
                    "total_closed",
                ],
            },
        },
        "position": {"x": 0, "y": 45, "w": 6, "h": 5},
        "sort_order": 210,
    },
    {
        "chart_key": "am_table_replacements_month_detail",
        "tab_key": "account-management",
        "title": "% de reemplazos realizados - Detalle",
        "type": "table",
        "dataset_key": "replacements_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "month",
                    "client_name",
                    "opp_model",
                    "opp_stage",
                    "replaced_candidate_name",
                    "old_end_date",
                    "new_candidate_name",
                    "new_start_date",
                    "days_to_replace",
                ],
            },
        },
        "position": {"x": 6, "y": 45, "w": 6, "h": 5},
        "sort_order": 220,
    },
    {
        "chart_key": "am_line_lara_winrate",
        "tab_key": "account-management",
        "title": "Win Rate Re contrataciones",
        "type": "line",
        "dataset_key": "lara_winrate_history",
        "config": {
            "mapping": {
                "x": "mes_close",
                "y": ["conversion_pct"],
                "formatter": "number",
                "drillKey": "fecha_lara",
                "tooltipExtras": ["total_closed", "close_win", "closed_lost"],
            },
        },
        "position": {"x": 0, "y": 50, "w": 6, "h": 5},
        "sort_order": 230,
    },
    {
        "chart_key": "am_table_lara_winrate_month_detail",
        "tab_key": "account-management",
        "title": "Detalle - Win Rate Re contrataciones",
        "type": "table",
        "dataset_key": "lara_winrate_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "client_name",
                    "opp_position_name",
                    "nda_d",
                    "close_d",
                    "opp_stage",
                    "dias_nda_a_close",
                ],
            },
        },
        "position": {"x": 6, "y": 50, "w": 6, "h": 5},
        "sort_order": 240,
    },
    {
        "chart_key": "am_kpi_lara_winrate_30d",
        "tab_key": "account-management",
        "title": "% de conversión de Client a Close Win en ventana de 30 días",
        "type": "kpi",
        "dataset_key": "lara_winrate_30d_summary",
        "config": {"mapping": {"value": "conversion_30d_pct", "formatter": "percent"}},
        "position": {"x": 0, "y": 55, "w": 3, "h": 5},
        "sort_order": 250,
    },
    {
        "chart_key": "am_kpi_lara_winrate_30d_breakdown",
        "tab_key": "account-management",
        "title": "Detalle 30d",
        "type": "kpi",
        "dataset_key": "lara_winrate_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "total_closed", "label": "Total cerradas", "formatter": "number"},
                    {"key": "close_win", "label": "Close Win", "formatter": "number"},
                    {"key": "closed_lost", "label": "Closed Lost", "formatter": "number"},
                ],
            },
        },
        "position": {"x": 3, "y": 55, "w": 3, "h": 5},
        "sort_order": 260,
    },
    {
        "chart_key": "am_table_lara_winrate_30d_detail",
        "tab_key": "account-management",
        "title": "Detalle Win Rate Re contrataciones - 30",
        "type": "table",
        "dataset_key": "lara_winrate_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "client_name",
                    "opp_position_name",
                    "nda_d",
                    "close_d",
                    "opp_stage",
                    "estado_final",
                    "dias_nda_a_close",
                ],
            },
        },
        "position": {"x": 6, "y": 55, "w": 6, "h": 5},
        "sort_order": 270,
    },
    {
        "chart_key": "am_line_clients_multi",
        "tab_key": "account-management",
        "title": "% Clientes > 1 candidato",
        "type": "line",
        "dataset_key": "clients_multi_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["pct_percent"],
                "formatter": "number",
                "drillKey": "fecha_clients_multi",
                "tooltipExtras": ["clientes_activos", "mayor_a_1"],
            },
        },
        "position": {"x": 0, "y": 60, "w": 6, "h": 5},
        "sort_order": 280,
    },
    {
        "chart_key": "am_table_clients_multi_month_detail",
        "tab_key": "account-management",
        "title": "Detalle - % Clientes > 1 candidato",
        "type": "table",
        "dataset_key": "clients_multi_month_detail",
        "config": {
            "mapping": {
                "columns": ["mes", "client_name", "candidate_name"],
            },
        },
        "position": {"x": 6, "y": 60, "w": 6, "h": 5},
        "sort_order": 290,
    },
    {
        "chart_key": "am_kpi_clients_multi_30d",
        "tab_key": "account-management",
        "title": "Conversión Global en ventana de 30 días",
        "type": "kpi",
        "dataset_key": "clients_multi_30d_summary",
        "config": {"mapping": {"value": "pct_percent", "formatter": "percent"}},
        "position": {"x": 0, "y": 65, "w": 3, "h": 5},
        "sort_order": 300,
    },
    {
        "chart_key": "am_kpi_clients_multi_30d_breakdown",
        "tab_key": "account-management",
        "title": "Detalle % - 30 días",
        "type": "kpi",
        "dataset_key": "clients_multi_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "clientes_activos", "label": "Clientes activos", "formatter": "number"},
                    {"key": "mayor_a_1", "label": "Clientes > 1", "formatter": "number"},
                ],
            },
        },
        "position": {"x": 3, "y": 65, "w": 3, "h": 5},
        "sort_order": 310,
    },
    {
        "chart_key": "am_table_clients_multi_30d_detail",
        "tab_key": "account-management",
        "title": "Detalle - 30",
        "type": "table",
        "dataset_key": "clients_multi_30d_detail",
        "config": {
            "mapping": {
                "columns": ["periodo", "client_name", "candidate_name"],
            },
        },
        "position": {"x": 6, "y": 65, "w": 6, "h": 5},
        "sort_order": 320,
    },
    {
        "chart_key": "am_line_headcount_growth",
        "tab_key": "account-management",
        "title": "Headcount Growth",
        "type": "line",
        "dataset_key": "headcount_growth_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["pct_activos_que_aumentaron", "pct_activos_paso_1_a_2_o_mas"],
                "formatter": "number",
                "drillKey": "fecha_headcount",
                "tooltipExtras": [
                    "clientes_activos",
                    "clientes_que_aumentaron",
                    "pasaron_de_1_a_2_o_mas",
                ],
            },
        },
        "position": {"x": 0, "y": 70, "w": 6, "h": 5},
        "sort_order": 330,
    },
    {
        "chart_key": "am_table_headcount_growth_month_detail",
        "tab_key": "account-management",
        "title": "Headcount Growth - Modificados",
        "type": "table",
        "dataset_key": "headcount_growth_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "mes",
                    "client_name",
                    "candidatos_prev",
                    "candidatos_activos",
                    "aumento",
                    "paso_1_a_2_o_mas",
                ],
            },
        },
        "position": {"x": 6, "y": 70, "w": 6, "h": 5},
        "sort_order": 340,
    },
    {
        "chart_key": "am_kpi_headcount_growth_30d",
        "tab_key": "account-management",
        "title": "Headcount Growth - 30d",
        "type": "kpi",
        "dataset_key": "headcount_growth_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "clientes_activos", "label": "Clientes activos", "formatter": "number"},
                    {"key": "clientes_que_aumentaron", "label": "Aumentaron", "formatter": "number"},
                    {"key": "pasaron_de_1_a_2_o_mas", "label": "1→2+", "formatter": "number"},
                    {"key": "pct_activos_que_aumentaron", "label": "% aumentaron", "formatter": "percent"},
                    {"key": "pct_activos_paso_1_a_2_o_mas", "label": "% 1→2+", "formatter": "percent"},
                ],
            },
        },
        "position": {"x": 0, "y": 75, "w": 6, "h": 5},
        "sort_order": 350,
    },
    {
        "chart_key": "am_table_headcount_growth_30d_detail",
        "tab_key": "account-management",
        "title": "Headcount Growth - 30",
        "type": "table",
        "dataset_key": "headcount_growth_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "cutoff",
                    "client_name",
                    "candidatos_prev",
                    "candidatos_activos",
                    "aumento",
                    "paso_1_a_2_o_mas",
                ],
            },
        },
        "position": {"x": 6, "y": 75, "w": 6, "h": 5},
        "sort_order": 360,
    },
    {
        "chart_key": "am_donut_risk_score",
        "tab_key": "account-management",
        "title": "Risk Score",
        "type": "donut",
        "dataset_key": "risk_score_by_label",
        "config": {
            "mapping": {
                "x": "riesgo_label",
                "y": ["clientes"],
                "formatter": "number",
                "drillKey": "riesgo_click",
            },
        },
        "position": {"x": 0, "y": 80, "w": 6, "h": 5},
        "sort_order": 370,
    },
    {
        "chart_key": "am_table_risk_score_detail",
        "tab_key": "account-management",
        "title": "Risk Score - Detalle",
        "type": "table",
        "dataset_key": "risk_score_detail",
        "config": {
            "mapping": {
                "columns": [
                    "riesgo",
                    "client_name",
                    "estado_procesos",
                    "candidatos_activos",
                    "last_hire_d",
                    "replacements",
                    "risk_score",
                ],
            },
        },
        "position": {"x": 6, "y": 80, "w": 6, "h": 5},
        "sort_order": 380,
    },
    {
        "chart_key": "am_bar_risk_score_points",
        "tab_key": "account-management",
        "title": "Risk Score - Puntos acumulados",
        "type": "bar",
        "dataset_key": "risk_score_by_label",
        "config": {
            "mapping": {
                "x": "riesgo_label",
                "y": ["puntos"],
                "formatter": "number",
                "tooltipExtras": ["clientes"],
            },
        },
        "position": {"x": 0, "y": 85, "w": 6, "h": 5},
        "sort_order": 390,
    },
    {
        "chart_key": "am_bar_risk_score_distribution",
        "tab_key": "account-management",
        "title": "Risk Score - Contador",
        "type": "bar",
        "dataset_key": "risk_score_distribution",
        "config": {
            "mapping": {
                "x": "risk_score",
                "y": ["clientes"],
                "formatter": "number",
            },
        },
        "position": {"x": 6, "y": 85, "w": 6, "h": 5},
        "sort_order": 400,
    },
    {
        "chart_key": "am_line_nrr",
        "tab_key": "account-management",
        "title": "NRR",
        "type": "line",
        "dataset_key": "nrr_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["nrr_pct"],
                "formatter": "number",
                "drillKey": "fecha_nrr",
                "tooltipExtras": [
                    "mrr_inicial",
                    "upsells_lara",
                    "downgrades_recorte",
                    "churn_no_recorte",
                ],
            },
        },
        "position": {"x": 0, "y": 90, "w": 6, "h": 5},
        "sort_order": 410,
    },
    {
        "chart_key": "am_table_nrr_month_detail",
        "tab_key": "account-management",
        "title": "Detalle - NRR",
        "type": "table",
        "dataset_key": "nrr_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "mes",
                    "componente",
                    "client_name",
                    "candidate_name",
                    "opportunity_id",
                    "start_d",
                    "end_d",
                    "inactive_reason",
                    "monto",
                ],
            },
        },
        "position": {"x": 6, "y": 90, "w": 6, "h": 5},
        "sort_order": 420,
    },
    {
        "chart_key": "am_kpi_nrr_30d",
        "tab_key": "account-management",
        "title": "NRR en ventana de 30 días",
        "type": "kpi",
        "dataset_key": "nrr_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "mrr_inicial", "label": "MRR", "formatter": "currency"},
                    {"key": "upsells_lara", "label": "Upsells", "formatter": "currency"},
                    {"key": "downgrades_recorte", "label": "Downgrades", "formatter": "currency"},
                    {"key": "churn_no_recorte", "label": "Churn", "formatter": "currency"},
                    {"key": "nrr_pct", "label": "NRR %", "formatter": "percent"},
                ],
            },
        },
        "position": {"x": 0, "y": 95, "w": 6, "h": 5},
        "sort_order": 430,
    },
    {
        "chart_key": "am_table_nrr_30d_detail",
        "tab_key": "account-management",
        "title": "Detalle - 30d",
        "type": "table",
        "dataset_key": "nrr_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "mes",
                    "componente",
                    "client_name",
                    "candidate_name",
                    "opportunity_id",
                    "start_d",
                    "end_d",
                    "inactive_reason",
                    "monto",
                ],
            },
        },
        "position": {"x": 6, "y": 95, "w": 6, "h": 5},
        "sort_order": 440,
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
                "drillKey": "fecha_nda",
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
    {
        "chart_key": "sa_area_new_clients_per_month",
        "tab_key": "sales",
        "title": "New Clients Per Month",
        "type": "area",
        "dataset_key": "new_clients_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["new_clients"],
                "formatter": "number",
                "drillKey": "fecha_new_clients",
            },
        },
        "position": {"x": 0, "y": 20, "w": 6, "h": 5},
        "sort_order": 90,
    },
    {
        "chart_key": "sa_table_new_clients_month_detail",
        "tab_key": "sales",
        "title": "Details New Clients Per Month",
        "type": "table",
        "dataset_key": "new_clients_month_detail",
        "config": {
            "mapping": {
                "columns": ["start_date", "client_name", "candidate_name"],
            },
        },
        "position": {"x": 6, "y": 20, "w": 6, "h": 5},
        "sort_order": 100,
    },
    {
        "chart_key": "sa_kpi_new_clients_30d",
        "tab_key": "sales",
        "title": "Nuevos Clientes en ventana de 30 días",
        "type": "kpi",
        "dataset_key": "new_clients_30d_total",
        "config": {"mapping": {"value": "new_clients_30d", "formatter": "number"}},
        "position": {"x": 0, "y": 25, "w": 6, "h": 5},
        "sort_order": 110,
    },
    {
        "chart_key": "sa_table_new_clients_30d_detail",
        "tab_key": "sales",
        "title": "Detalle - 30",
        "type": "table",
        "dataset_key": "new_clients_30d_detail",
        "config": {
            "mapping": {
                "columns": ["start_date", "client_name", "candidate_name"],
            },
        },
        "position": {"x": 6, "y": 25, "w": 6, "h": 5},
        "sort_order": 120,
    },

    # Operations
    {
        "chart_key": "op_bar_new_placements",
        "tab_key": "operations",
        "title": "Nuevas colocaciones por mes",
        "type": "bar",
        "dataset_key": "new_placements_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["staffing_starts", "recruiting_starts"],
                "formatter": "number",
                "stacked": True,
                "drillKey": "fecha_new_placements",
            },
        },
        "position": {"x": 0, "y": 0, "w": 6, "h": 5},
        "sort_order": 10,
    },
    {
        "chart_key": "op_table_new_placements_detail",
        "tab_key": "operations",
        "title": "Detalle - Nuevas colocaciones por mes",
        "type": "table",
        "dataset_key": "new_placements_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "mes",
                    "opp_model",
                    "candidate_name",
                    "opportunity_id",
                    "start_date",
                    "end_date",
                ],
            },
        },
        "position": {"x": 6, "y": 0, "w": 6, "h": 5},
        "sort_order": 20,
    },
    {
        "chart_key": "op_line_placement_time",
        "tab_key": "operations",
        "title": "Tiempo promedio de colocación",
        "type": "line",
        "dataset_key": "placement_time_history",
        "config": {
            "mapping": {
                "x": "mes_cierre",
                "y": ["promedio_dias"],
                "formatter": "number",
                "drillKey": "fecha_placement_time",
            },
        },
        "position": {"x": 0, "y": 5, "w": 6, "h": 5},
        "sort_order": 30,
    },
    {
        "chart_key": "op_table_placement_time_detail",
        "tab_key": "operations",
        "title": "Detalle - Tiempo promedio de colocación",
        "type": "table",
        "dataset_key": "placement_time_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "month",
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "close_result",
                    "fecha_pedido",
                    "fecha_cierre",
                    "avg_days",
                    "opportunity_id",
                ],
            },
        },
        "position": {"x": 6, "y": 5, "w": 6, "h": 5},
        "sort_order": 40,
    },
    {
        "chart_key": "op_kpi_placement_time_30d",
        "tab_key": "operations",
        "title": "Promedio de días de colocación — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "placement_time_30d_summary",
        "config": {
            "mapping": {
                "value": "promedio_dias",
                "label": "Promedio días",
                "formatter": "number",
            },
        },
        "position": {"x": 0, "y": 10, "w": 6, "h": 5},
        "sort_order": 50,
    },
    {
        "chart_key": "op_table_placement_time_30d_detail",
        "tab_key": "operations",
        "title": "Detalle - 30 días",
        "type": "table",
        "dataset_key": "placement_time_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "month",
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "close_result",
                    "fecha_pedido",
                    "fecha_cierre",
                    "avg_days",
                    "opportunity_id",
                ],
            },
        },
        "position": {"x": 6, "y": 10, "w": 6, "h": 5},
        "sort_order": 60,
    },
    {
        "chart_key": "op_line_placement_time_repl",
        "tab_key": "operations",
        "title": "Tiempo promedio de colocación (Replacement)",
        "type": "line",
        "dataset_key": "placement_time_repl_history",
        "config": {
            "mapping": {
                "x": "mes_cierre",
                "y": ["promedio_dias"],
                "formatter": "number",
                "drillKey": "fecha_placement_time_repl",
                "tooltipExtras": ["opps_cerradas", "mediana_dias", "p90_dias"],
            },
        },
        "position": {"x": 0, "y": 15, "w": 6, "h": 5},
        "sort_order": 70,
    },
    {
        "chart_key": "op_table_placement_time_detail_repl",
        "tab_key": "operations",
        "title": "Detalle - Tiempo promedio de colocación (Replacement)",
        "type": "table",
        "dataset_key": "placement_time_repl_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "month",
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "close_result",
                    "fecha_pedido",
                    "fecha_cierre",
                    "avg_days",
                    "opportunity_id",
                ],
            },
        },
        "position": {"x": 6, "y": 15, "w": 6, "h": 5},
        "sort_order": 80,
    },
    {
        "chart_key": "op_kpi_placement_time_30d_repl",
        "tab_key": "operations",
        "title": "Promedio de días de colocación (Replacement) — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "placement_time_repl_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "promedio_dias", "label": "Promedio días", "formatter": "number"},
                    {"key": "mediana_dias", "label": "Mediana días", "formatter": "number"},
                    {"key": "p90_dias", "label": "P90 días", "formatter": "number"},
                    {"key": "opps_cerradas", "label": "Opps cerradas", "formatter": "number"},
                ],
            },
        },
        "position": {"x": 0, "y": 20, "w": 6, "h": 5},
        "sort_order": 90,
    },
    {
        "chart_key": "op_table_placement_time_30d_detail_repl",
        "tab_key": "operations",
        "title": "Detalle - 30 días (Replacement)",
        "type": "table",
        "dataset_key": "placement_time_repl_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "month",
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "close_result",
                    "fecha_pedido",
                    "fecha_cierre",
                    "avg_days",
                    "opportunity_id",
                ],
            },
        },
        "position": {"x": 6, "y": 20, "w": 6, "h": 5},
        "sort_order": 100,
    },
    {
        "chart_key": "op_line_batch_delivery_time",
        "tab_key": "operations",
        "title": "Tiempo promedio en entregar un batch",
        "type": "line",
        "dataset_key": "batch_delivery_time_history",
        "config": {
            "mapping": {
                "x": "opportunity_id",
                "y": ["dias_promedio_entrega"],
                "formatter": "number",
                "drillKey": "opp_id_batch",
                "tooltipExtras": ["client_name", "opp_position_name", "opp_stage", "total_batches"],
            },
        },
        "position": {"x": 0, "y": 25, "w": 6, "h": 5},
        "sort_order": 110,
    },
    {
        "chart_key": "op_table_batch_delivery_time_detail",
        "tab_key": "operations",
        "title": "Detalle - Tiempo promedio en entregar un batch",
        "type": "table",
        "dataset_key": "batch_delivery_time_detail",
        "config": {
            "mapping": {
                "columns": [
                    "opportunity_id",
                    "batch_number",
                    "opp_model",
                    "pedido_d",
                    "batch_d",
                    "dias_entrega",
                ],
            },
        },
        "position": {"x": 6, "y": 25, "w": 6, "h": 5},
        "sort_order": 120,
    },
    {
        "chart_key": "op_line_batch_delivery_time_month",
        "tab_key": "operations",
        "title": "Tiempo promedio en entregar un batch - x batch",
        "type": "line",
        "dataset_key": "batch_delivery_time_month_history",
        "config": {
            "mapping": {
                "x": "mes_batch",
                "y": ["avg_dias_entrega"],
                "formatter": "number",
                "drillKey": "mes_batch_delivery",
                "tooltipExtras": ["total_batches", "opps_con_batches"],
            },
        },
        "position": {"x": 0, "y": 30, "w": 6, "h": 5},
        "sort_order": 130,
    },
    {
        "chart_key": "op_table_batch_delivery_time_month_detail",
        "tab_key": "operations",
        "title": "Detalle - x batch",
        "type": "table",
        "dataset_key": "batch_delivery_time_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "batch_number",
                    "batch_d",
                    "mes_batch",
                    "opportunity_id",
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "opp_stage",
                    "fecha_pedido",
                    "dias_entrega",
                ],
            },
        },
        "position": {"x": 6, "y": 30, "w": 6, "h": 5},
        "sort_order": 140,
    },
    {
        "chart_key": "op_kpi_batch_delivery_time_30d",
        "tab_key": "operations",
        "title": "Días promedio en entregar un batch — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "batch_delivery_time_30d_summary",
        "config": {
            "mapping": {
                "value": "avg_dias_entrega_30d",
                "label": "días",
                "formatter": "number",
            },
        },
        "position": {"x": 0, "y": 35, "w": 6, "h": 5},
        "sort_order": 150,
    },
    {
        "chart_key": "op_table_batch_delivery_time_30d_detail",
        "tab_key": "operations",
        "title": "Detalle - 30 x batch",
        "type": "table",
        "dataset_key": "batch_delivery_time_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "batch_id",
                    "batch_number",
                    "batch_d",
                    "opportunity_id",
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "opp_stage",
                    "fecha_pedido",
                    "dias_entrega",
                ],
            },
        },
        "position": {"x": 6, "y": 35, "w": 6, "h": 5},
        "sort_order": 160,
    },
    {
        "chart_key": "op_line_nda_close_win",
        "tab_key": "operations",
        "title": "All NDA a close win",
        "type": "line",
        "dataset_key": "nda_close_win_history",
        "config": {
            "mapping": {
                "x": "mes_close",
                "y": ["conversion_pct"],
                "formatter": "percent",
                "drillKey": "mes_nda_close_win",
                "tooltipExtras": ["total_closed", "close_win", "close_lost"],
            },
        },
        "position": {"x": 0, "y": 40, "w": 6, "h": 5},
        "sort_order": 200,
    },
    {
        "chart_key": "op_table_nda_close_win_detail",
        "tab_key": "operations",
        "title": "Detalle - All NDA a close win",
        "type": "table",
        "dataset_key": "nda_close_win_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "client_name",
                    "opp_model",
                    "close_d",
                    "opp_stage",
                    "converted_to_client",
                ],
            },
        },
        "position": {"x": 6, "y": 40, "w": 6, "h": 5},
        "sort_order": 210,
    },
    {
        "chart_key": "op_kpi_nda_close_win_30d",
        "tab_key": "operations",
        "title": "Conversión Global de todos los NDA a Clientes en ventana de 30 días",
        "type": "kpi",
        "dataset_key": "nda_close_win_30d_summary",
        "config": {
            "mapping": {
                "value": "conversion_pct",
                "label": "%",
                "formatter": "percent",
            },
        },
        "position": {"x": 0, "y": 45, "w": 3, "h": 5},
        "sort_order": 220,
    },
    {
        "chart_key": "op_kpi_nda_close_win_30d_breakdown",
        "tab_key": "operations",
        "title": "NDA a Close Win",
        "type": "kpi",
        "dataset_key": "nda_close_win_30d_summary",
        "config": {
            "mapping": {
                "values": [
                    {"key": "total_closed", "label": "total_closed", "formatter": "number"},
                    {"key": "close_win",    "label": "close_win",    "formatter": "number"},
                    {"key": "close_lost",   "label": "close_lost",   "formatter": "number"},
                ],
            },
        },
        "position": {"x": 3, "y": 45, "w": 3, "h": 5},
        "sort_order": 230,
    },
    {
        "chart_key": "op_table_nda_close_win_30d_detail",
        "tab_key": "operations",
        "title": "Detalle - 30",
        "type": "table",
        "dataset_key": "nda_close_win_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "client_name",
                    "opp_model",
                    "close_d",
                    "opp_stage",
                    "converted_to_client",
                ],
            },
        },
        "position": {"x": 6, "y": 45, "w": 6, "h": 5},
        "sort_order": 240,
    },
    {
        "chart_key": "op_line_interview_conversion",
        "tab_key": "operations",
        "title": "Tasa de Conversión a Entrevista",
        "type": "line",
        "dataset_key": "interview_conversion_history",
        "config": {
            "mapping": {
                "x": "mes",
                "y": ["pct_presentados_sobre_entrevistados"],
                "formatter": "percent",
                "drillKey": "mes_interview_conversion",
                "tooltipExtras": ["presentados_total", "entrevistados_total"],
            },
        },
        "position": {"x": 0, "y": 50, "w": 6, "h": 5},
        "sort_order": 250,
    },
    {
        "chart_key": "op_table_interview_conversion_detail",
        "tab_key": "operations",
        "title": "Detalle Tasa de Conversión a Entrevista",
        "type": "table",
        "dataset_key": "interview_conversion_month_detail",
        "config": {
            "mapping": {
                "columns": [
                    "close_date",
                    "client_name",
                    "opp_position_name",
                    "opp_stage",
                    "cantidad_entrevistados",
                    "candidatos_presentados",
                    "pct_presentados_sobre_entrevistados",
                    "pct_entrevistados_sobre_presentados",
                ],
            },
        },
        "position": {"x": 6, "y": 50, "w": 6, "h": 5},
        "sort_order": 260,
    },
    {
        "chart_key": "op_line_interview_conversion_30d",
        "tab_key": "operations",
        "title": "Tasa de Conversión a Entrevista — Ventana 30 días",
        "type": "line",
        "dataset_key": "interview_conversion_30d_history",
        "config": {
            "mapping": {
                "x": "opportunity_id",
                "y": ["conversion_pct"],
                "formatter": "percent",
                "tooltipExtras": [
                    "client_name",
                    "opp_position_name",
                    "cantidad_entrevistados",
                    "candidatos_presentados",
                ],
            },
        },
        "position": {"x": 0, "y": 55, "w": 6, "h": 5},
        "sort_order": 270,
    },
    {
        "chart_key": "op_kpi_interview_conversion_30d",
        "tab_key": "operations",
        "title": "Conversión global ponderada — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "interview_conversion_30d_summary",
        "config": {
            "mapping": {
                "value": "conversion_global_ponderada_pct",
                "label": "%",
                "formatter": "percent",
            },
        },
        "position": {"x": 6, "y": 55, "w": 6, "h": 5},
        "sort_order": 280,
    },
    {
        "chart_key": "op_line_sent_hired_30d",
        "tab_key": "operations",
        "title": "Enviados vs Contratados — Ventana 30 días",
        "type": "line",
        "dataset_key": "sent_hired_30d_history",
        "config": {
            "mapping": {
                "x": "opportunity_id",
                "y": ["conversion_pct"],
                "formatter": "percent",
                "drillKey": "opportunity_id",
                "tooltipExtras": [
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "enviados",
                    "contratados",
                ],
            },
        },
        "position": {"x": 0, "y": 60, "w": 6, "h": 5},
        "sort_order": 290,
    },
    {
        "chart_key": "op_table_sent_hired_30d_detail",
        "tab_key": "operations",
        "title": "Enviados vs Contratados — Detalle por candidato",
        "type": "table",
        "dataset_key": "sent_hired_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "client_name",
                    "opp_position_name",
                    "candidate_name",
                    "sent_date",
                    "contratado",
                ],
            },
        },
        "position": {"x": 6, "y": 60, "w": 6, "h": 5},
        "sort_order": 300,
    },
    {
        "chart_key": "op_kpi_sent_hired_30d",
        "tab_key": "operations",
        "title": "Conversión global Enviados → Contratados — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "sent_hired_30d_summary",
        "config": {
            "mapping": {
                "value": "conversion_pct_general",
                "label": "%",
                "formatter": "percent",
            },
        },
        "position": {"x": 0, "y": 65, "w": 6, "h": 5},
        "sort_order": 310,
    },
    {
        "chart_key": "op_line_interviewed_sent_30d",
        "tab_key": "operations",
        "title": "Entrevistados vs Enviados en Clientes — Ventana 30 días",
        "type": "line",
        "dataset_key": "interviewed_sent_30d_history",
        "config": {
            "mapping": {
                "x": "opportunity_id",
                "y": ["entrevistados_sobre_enviados_pct"],
                "formatter": "percent",
                "drillKey": "opportunity_id",
                "tooltipExtras": [
                    "client_name",
                    "opp_position_name",
                    "resultado",
                    "candidatos_enviados",
                    "candidatos_entrevistados",
                ],
            },
        },
        "position": {"x": 0, "y": 70, "w": 6, "h": 5},
        "sort_order": 320,
    },
    {
        "chart_key": "op_table_interviewed_sent_30d_detail",
        "tab_key": "operations",
        "title": "Entrevistados vs Enviados en Clientes — Detalle por candidato",
        "type": "table",
        "dataset_key": "interviewed_sent_30d_detail",
        "config": {
            "mapping": {
                "columns": [
                    "opportunity_id",
                    "client_name",
                    "opp_position_name",
                    "opp_model",
                    "resultado",
                    "candidate_name",
                    "status_final",
                ],
            },
        },
        "position": {"x": 6, "y": 70, "w": 6, "h": 5},
        "sort_order": 330,
    },
    {
        "chart_key": "op_kpi_interviewed_sent_30d",
        "tab_key": "operations",
        "title": "Conversión global Entrevistados → Enviados — Ventana 30 días",
        "type": "kpi",
        "dataset_key": "interviewed_sent_30d_summary",
        "config": {
            "mapping": {
                "value": "promedio_pct_por_opportunity",
                "label": "%",
                "formatter": "percent",
            },
        },
        "position": {"x": 0, "y": 75, "w": 6, "h": 5},
        "sort_order": 340,
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
