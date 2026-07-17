"""Marketing · Revenue mix — % Recruiting vs % Staffing del net revenue.

Dos filas (Recruiting, Staffing) con el fee de Vintti de los Close Win cerrados
en el período (semana / mes / q / anio).
  Recruiting net revenue = ho.revenue (one-shot, se cuenta una vez).
  Staffing net revenue   = ho.fee * LTV, donde LTV = vida promedio (meses activos)
                           de los clientes de Staffing. Recruiting es un pago único,
                           pero el fee de Staffing es recurrente, así que se proyecta
                           sobre la vida promedio del cliente.
El LTV se calcula dinámicamente (NO es un ×10 fijo) con el mismo bloque canónico
que pipeline_cr_minus_churn.py / metrics_routes.py: AVG de meses calendario activos
por cliente de Staffing, excluyendo vintti_internal.
Marketing-scope: excluye outbound (reconcilia con la card 'Net revenue' del strip).
Siempre devuelve ambos modelos (0 si no hubo).
"""
from __future__ import annotations

from .mkt_sqls_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, label = period_bounds(filters)
    sql = """
        WITH rev_opp AS (
          SELECT o.opportunity_id, o.opp_model,
                 NULLIF(o.opp_close_date::text, '')::date AS cdte,
                 COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                                   ELSE COALESCE(ho.fee, 0) END), 0)::numeric AS rev
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
          WHERE TRIM(o.opp_stage) = 'Close Win' AND o.opp_model IN ('Staffing', 'Recruiting')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          GROUP BY o.opportunity_id, o.opp_model, cdte
        ),
        -- LTV (avg meses activos por cliente de Staffing) — bloque canonico, misma
        -- logica que pipeline_cr_minus_churn.py / metrics_routes.py. Devuelve un
        -- unico entero que se usa como multiplicador del fee de Staffing.
        ltv_base AS (
          SELECT c.candidate_id, c.account_id, c.start_d, c.end_d
          FROM (
            SELECT ho.candidate_id, ho.account_id,
              CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                   WHEN NULLIF(ho.start_date::text,'') IS NOT NULL THEN ho.start_date::date
                   ELSE NULL END AS start_d,
              CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                   WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
                   ELSE ho.end_date::date END AS end_d
            FROM hire_opportunity ho
            JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
            LEFT JOIN account a ON a.account_id = ho.account_id
            WHERE ho.account_id IS NOT NULL
              AND o.opp_model = 'Staffing'
              AND COALESCE(a.vintti_internal, FALSE) = FALSE
          ) c
          WHERE c.start_d IS NOT NULL
        ),
        ltv_meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM ltv_base),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM ltv_base),
            INTERVAL '1 month'
          ) gs
        ),
        ltv_activos_mes AS (
          SELECT m.mes, b.account_id, COUNT(DISTINCT b.candidate_id) AS activos
          FROM ltv_meses m
          JOIN ltv_base b
            ON b.start_d < (m.mes + INTERVAL '1 month')
           AND (b.end_d IS NULL OR b.end_d >= m.mes)
          GROUP BY 1, 2
        ),
        ltv_duracion AS (
          SELECT account_id, COUNT(*) AS active_months
          FROM ltv_activos_mes
          WHERE activos > 0
          GROUP BY account_id
        ),
        ltv_months AS (
          SELECT COALESCE(ROUND(AVG(active_months)), 0)::int AS ltv
          FROM ltv_duracion
        ),
        agg AS (
          SELECT opp_model AS model, SUM(rev)::numeric AS net_rev_raw
          FROM rev_opp
          WHERE cdte BETWEEN %(ini)s::date AND %(fin)s::date
          GROUP BY opp_model
        ),
        agg_adj AS (
          -- Staffing fee se proyecta sobre la vida promedio del cliente (fee * LTV);
          -- Recruiting queda igual (one-shot).
          SELECT model,
                 CASE WHEN model = 'Staffing'
                      THEN net_rev_raw * (SELECT ltv FROM ltv_months)
                      ELSE net_rev_raw END AS net_rev
          FROM agg
        ),
        models AS (SELECT unnest(ARRAY['Recruiting', 'Staffing']) AS model)
        SELECT
          m.model,
          COALESCE(ROUND(a.net_rev), 0)::bigint                                     AS net_rev,
          ROUND(100.0 * COALESCE(a.net_rev, 0)
                / NULLIF(SUM(COALESCE(a.net_rev, 0)) OVER (), 0), 1)::float          AS pct,
          ROUND(SUM(COALESCE(a.net_rev, 0)) OVER ())::bigint                         AS total,
          (SELECT ltv FROM ltv_months)                                              AS ltv,
          %(label)s::text                                                           AS period_label
        FROM models m
        LEFT JOIN agg_adj a ON a.model = m.model
        ORDER BY m.model;
    """
    return sql, {"ini": ini, "fin": fin, "label": label}


DATASET = {
    "key": "mkt_revenue_mix",
    "label": "Marketing · Revenue mix (Recruiting vs Staffing, período)",
    "dimensions": [
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "net_rev", "label": "Net revenue", "type": "currency"},
        {"key": "pct", "label": "% del total", "type": "percent"},
        {"key": "total", "label": "Net revenue total", "type": "currency"},
        {"key": "ltv", "label": "LTV Staffing (meses)", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
