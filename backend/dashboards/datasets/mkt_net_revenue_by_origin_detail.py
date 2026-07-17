"""Marketing · detalle Net revenue por origin (Close Wins del período, sin outbound).

Net revenue por deal: Recruiting = ho.revenue (one-shot); Staffing = ho.fee * LTV,
donde LTV = vida promedio (meses activos) de los clientes de Staffing, calculada con
el mismo bloque canonico que mkt_revenue_mix.py. Asi el detalle reconcilia con la
tarjeta Revenue mix (cada fila de Staffing muestra el fee proyectado a su vida, no el
fee de un mes).
"""
from __future__ import annotations

from .mkt_sqls_by_origin import period_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, _ = period_bounds(filters)
    sql = """
        WITH wins AS (
          SELECT
            o.opportunity_id, a.client_name, o.opp_position_name, TRIM(o.opp_model) AS model,
            COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin,
            NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral', 'import')
        ),
        -- LTV (avg meses activos por cliente de Staffing) — mismo bloque canonico
        -- que mkt_revenue_mix.py; multiplica el fee de Staffing por la vida promedio.
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
        )
        SELECT
          w.client_name, w.origin, w.model, w.opp_position_name,
          TO_CHAR(w.close_d, 'YYYY-MM-DD') AS close_date,
          COALESCE(SUM(
            CASE WHEN w.model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                 ELSE COALESCE(ho.fee, 0) * (SELECT ltv FROM ltv_months) END), 0)::bigint AS net_revenue
        FROM wins w
        LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
        WHERE w.close_d BETWEEN %(ini)s::date AND %(fin)s::date
        GROUP BY w.client_name, w.origin, w.model, w.opp_position_name, w.close_d
        ORDER BY net_revenue DESC, w.client_name;
    """
    return sql, {"ini": ini, "fin": fin}


DATASET = {
    "key": "mkt_net_revenue_by_origin_detail",
    "label": "Marketing · detalle Net revenue por origin (período)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "close_date", "label": "Close date", "type": "date"},
    ],
    "measures": [{"key": "net_revenue", "label": "Net revenue", "type": "currency"}],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
