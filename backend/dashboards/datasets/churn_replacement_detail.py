"""Detalle de Churn → Replacement: una fila por baja real de la ventana.

Mismo universo que churn_replacement_summary (y que las filas "Baja - Real" de
candidate_churn_30d_detail). Si la baja tuvo más de un replacement se muestra el
más reciente.
"""
from __future__ import annotations

from ._now import today_ar
from .candidate_churn_30d_detail import _parse_date, _window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )
    win_ini, win_fin = _window_bounds(filters, corte)

    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        candidatos AS (
          SELECT
            ho.candidate_id,
            ho.account_id,
            COALESCE(c.name, '') AS candidate_name,
            COALESCE(a.client_name, '') AS client_name,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange), '') IS NOT NULL
                THEN TO_DATE(TRIM(ho.buyout_daterange) || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          LEFT JOIN account a    ON a.account_id   = ho.account_id
          WHERE ho.candidate_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        bajas AS (
          -- activos al inicio que se fueron en la ventana
          SELECT c.*
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d IS NOT NULL
            AND c.start_d <= v.win_ini
            AND c.end_d BETWEEN v.win_ini AND v.win_fin
            AND NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
          UNION ALL
          -- entraron y se fueron dentro de la ventana
          SELECT c.*
          FROM candidatos c
          CROSS JOIN ventana v
          WHERE c.start_d BETWEEN v.win_ini AND v.win_fin
            AND c.end_d   BETWEEN v.win_ini AND v.win_fin
            AND NOT (c.buyout_d IS NOT NULL AND c.buyout_d >= DATE_TRUNC('month', c.end_d))
        )
        SELECT
          b.candidate_name,
          b.client_name,
          TO_CHAR(b.start_d, 'YYYY-MM-DD') AS start_d,
          TO_CHAR(b.end_d,   'YYYY-MM-DD') AS end_d,
          CASE WHEN r.opportunity_id IS NOT NULL
               THEN 'Con replacement' ELSE 'Sin replacement' END AS estado,
          r.opportunity_id AS replacement_opp_id,
          r.opp_stage AS replacement_stage,
          r.replacement_name,
          -- Línea de contexto del drawer: cliente + quién la reemplaza o en qué
          -- etapa está la búsqueda.
          CONCAT_WS(' · ', NULLIF(b.client_name, ''),
            CASE
              WHEN r.opportunity_id IS NULL THEN NULL
              WHEN r.opp_stage IN ('Closed Lost', 'Stop')
                THEN 'Replacement ' || r.opp_stage || ' (no se cubrió)'
              WHEN r.replacement_name IS NOT NULL
                THEN 'Reemplazo: ' || r.replacement_name || ' (' || COALESCE(r.opp_stage, '—') || ')'
              ELSE 'Replacement en ' || COALESCE(r.opp_stage, '—')
            END
          ) AS detalle
        FROM bajas b
        LEFT JOIN LATERAL (
          SELECT ro.opportunity_id, ro.opp_stage,
                 -- candidato_contratado si ya está; si no, los hires de la opp CON start
                 -- date. Una fila sin start puede ser un fantasma (la carga de
                 -- referencias crea la fila con el candidato todavía en proceso:
                 -- opp 801, Juliana Bhering en Negotiating).
                 COALESCE(
                   (SELECT NULLIF(TRIM(cc.name), '') FROM candidates cc
                     WHERE cc.candidate_id::text = NULLIF(TRIM(ro.candidato_contratado::text), '')),
                   (SELECT STRING_AGG(DISTINCT TRIM(hc.name), ', ')
                      FROM hire_opportunity rh
                      JOIN candidates hc ON hc.candidate_id = rh.candidate_id
                     WHERE rh.opportunity_id = ro.opportunity_id
                       AND (rh.carga_active IS NOT NULL
                            OR NULLIF(rh.start_date::text, '') IS NOT NULL))
                 ) AS replacement_name
          FROM opportunity ro
          WHERE ro.opp_type = 'Replacement'
            AND ro.account_id = b.account_id
            AND NULLIF(TRIM(ro.replacement_of::text), '') = b.candidate_id::text
          ORDER BY ro.opportunity_id DESC
          LIMIT 1
        ) r ON TRUE
        ORDER BY b.end_d DESC NULLS LAST, b.client_name, b.candidate_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "churn_replacement_detail",
    "label": "Churn → Replacement (Staffing) — Detalle por baja",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
        {"key": "end_d", "label": "End", "type": "date"},
        {"key": "estado", "label": "Estado", "type": "string"},
        {"key": "replacement_opp_id", "label": "Opp replacement", "type": "number"},
        {"key": "replacement_stage", "label": "Stage replacement", "type": "string"},
        {"key": "replacement_name", "label": "Reemplazo", "type": "string"},
        {"key": "detalle", "label": "Detalle", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    # Libro de hechos de la auditoria (dashboards/audit/ledger.py).
    "audit": [{
        "fact": "contractor_baja", "entity": ["candidate_name", "client_name"],
        "date_col": "end_d",
        "excluye": ["buyout"],
    }],
    "query": query,
}
