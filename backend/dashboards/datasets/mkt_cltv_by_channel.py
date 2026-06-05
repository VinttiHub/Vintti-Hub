"""Marketing · CLTV por canal de adquisición — vida REAL por cliente · all-time.

CLTV individual de cada cliente:
  CLTV_cliente = Σ (fee mensual del hire × meses activos del hire)   [Staffing]
  MRR_cliente  = CLTV_cliente / meses_de_vida_del_cliente             (fee mensual prom.)
  meses_activos = span del cliente: primer start → última baja (o hoy si sigue activo)

Por canal (origin = where_come_from, sin outbound, '(Sin origen)' aparte):
  total / activos / inactivos · MRR prom · vida prom + mediana ·
  CLTV prom + mediana · CLTV total · flag muestra reducida (<3 clientes).
Solo Staffing (relación recurrente); Recruiting es one-time y no aplica al
modelo MRR × vida.
"""
from __future__ import annotations


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    sql = """
        WITH acct AS (
          SELECT a.account_id,
                 COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
          FROM account a
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
        ),
        hires AS (
          SELECT
            ho.account_id,
            COALESCE(ho.fee, 0)::numeric AS fee,
            CASE WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                 ELSE NULLIF(ho.start_date::text, '')::date END AS start_d,
            CASE WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                 WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
                 ELSE ho.end_date::date END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL AND TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_model = 'Staffing'
        ),
        hire_calc AS (
          SELECT
            h.account_id, ac.origin, h.fee, h.start_d, h.end_d,
            (h.end_d IS NULL OR h.end_d >= CURRENT_DATE) AS hire_active,
            GREATEST(1, (DATE_PART('year',  AGE(COALESCE(h.end_d, CURRENT_DATE), h.start_d)) * 12
                       + DATE_PART('month', AGE(COALESCE(h.end_d, CURRENT_DATE), h.start_d)) + 1))::int AS months
          FROM hires h
          JOIN acct ac ON ac.account_id = h.account_id
          WHERE h.start_d IS NOT NULL
        ),
        per_client AS (
          SELECT
            account_id, origin,
            BOOL_OR(hire_active) AS is_active,
            SUM(fee * months)::numeric AS cltv,
            (DATE_PART('year',  AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) * 12
           + DATE_PART('month', AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) + 1)::int AS lifetime_months
          FROM hire_calc
          GROUP BY account_id, origin
        ),
        pc AS (
          SELECT *,
            (cltv / NULLIF(lifetime_months, 0))::numeric AS mrr
          FROM per_client
        )
        SELECT
          origin,
          COUNT(*)::int                                              AS clients,
          COUNT(*) FILTER (WHERE is_active)::int                     AS active_clients,
          COUNT(*) FILTER (WHERE NOT is_active)::int                 AS inactive_clients,
          ROUND(AVG(mrr))::bigint                                    AS avg_mrr,
          ROUND(AVG(lifetime_months), 1)::float                     AS avg_lifetime,
          ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY lifetime_months)::numeric, 1)::float AS median_lifetime,
          ROUND(AVG(cltv))::bigint                                   AS avg_cltv,
          ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY cltv)::numeric)::bigint AS median_cltv,
          ROUND(SUM(cltv))::bigint                                   AS total_cltv,
          CASE WHEN COUNT(*) < 3 THEN '⚠ reducida' ELSE '' END       AS muestra
        FROM pc
        GROUP BY origin
        ORDER BY avg_cltv DESC, origin;
    """
    return sql, {}


DATASET = {
    "key": "mkt_cltv_by_channel",
    "label": "Marketing · CLTV por canal (vida real por cliente)",
    "dimensions": [{"key": "origin", "label": "Canal", "type": "string"}],
    "measures": [
        {"key": "clients", "label": "Clientes", "type": "number"},
        {"key": "active_clients", "label": "Activos", "type": "number"},
        {"key": "inactive_clients", "label": "Inactivos", "type": "number"},
        {"key": "avg_mrr", "label": "MRR promedio", "type": "currency"},
        {"key": "avg_lifetime", "label": "Vida promedio (meses)", "type": "number"},
        {"key": "median_lifetime", "label": "Vida mediana (meses)", "type": "number"},
        {"key": "avg_cltv", "label": "CLTV promedio", "type": "currency"},
        {"key": "median_cltv", "label": "CLTV mediano", "type": "currency"},
        {"key": "total_cltv", "label": "CLTV total", "type": "currency"},
    ],
    "dimensions_extra": [{"key": "muestra", "label": "Muestra", "type": "string"}],
    "default_filters": {},
    "query": query,
}
