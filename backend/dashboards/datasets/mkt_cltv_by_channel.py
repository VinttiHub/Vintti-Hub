"""Marketing · CLTV por canal de adquisición — por modelo (Staffing | Recruiting).

Filtro `model` (default 'Staffing'):

STAFFING (recurrente) — vida REAL por cliente, all-time:
  CLTV_cliente = Σ (fee mensual del hire × meses activos)        [Staffing]
  MRR_cliente  = CLTV_cliente / meses_de_vida_del_cliente
  Activo       = el cliente tiene ≥1 contractor con baja vacía o futura.
  Columnas: clients · active_clients · avg_mrr · avg_lifetime · avg_cltv · total_cltv.

RECRUITING (one-time) — no hay MRR ni vida ni "activo":
  CLTV_cliente = Σ fee de placement (ho.revenue) de sus deals Recruiting Close Win.
  Columnas: clients · placements · avg_fee (por placement) · avg_cltv (por cliente) · total_cltv.

Por canal (origin = where_come_from, sin outbound, '(Sin origen)' aparte).
"""
from __future__ import annotations


def _model(filters: dict) -> str:
    m = str(filters.get("model") or "").strip().lower()
    return "Recruiting" if m == "recruiting" else "Staffing"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    model = _model(filters)

    if model == "Recruiting":
        # One-time: el ingreso del cliente es la suma de fees de placement (ho.revenue)
        # de sus oportunidades Recruiting ganadas. Sin MRR / vida / activo.
        sql = """
            WITH acct AS (
              SELECT a.account_id,
                     COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
              FROM account a
              WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral')
            ),
            rec AS (
              SELECT
                o.opportunity_id,
                o.account_id,
                ac.origin,
                COALESCE(SUM(ho.revenue), 0)::numeric AS deal_fee
              FROM opportunity o
              JOIN acct ac ON ac.account_id = o.account_id
              LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
              WHERE o.opp_model = 'Recruiting' AND TRIM(o.opp_stage) = 'Close Win'
              GROUP BY o.opportunity_id, o.account_id, ac.origin
            ),
            per_client AS (
              SELECT account_id, origin,
                     COUNT(*)::int        AS placements,
                     SUM(deal_fee)::numeric AS client_fee
              FROM rec
              GROUP BY account_id, origin
            )
            SELECT
              origin,
              COUNT(*)::int                                            AS clients,
              NULL::int                                                AS active_clients,
              NULL::int                                                AS inactive_clients,
              NULL::bigint                                             AS avg_mrr,
              NULL::float                                              AS avg_lifetime,
              SUM(placements)::int                                     AS placements,
              ROUND(SUM(client_fee) / NULLIF(SUM(placements), 0))::bigint AS avg_fee,
              ROUND(AVG(client_fee))::bigint                           AS avg_cltv,
              ROUND(SUM(client_fee))::bigint                           AS total_cltv,
              CASE WHEN COUNT(*) < 3 THEN '⚠ reducida' ELSE '' END     AS muestra
            FROM per_client
            GROUP BY origin
            ORDER BY total_cltv DESC, origin;
        """
        return sql, {}

    # STAFFING (default)
    sql = """
        WITH acct AS (
          SELECT a.account_id,
                 COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin
          FROM account a
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) NOT IN ('outbound', 'connected inbox', 'referral')
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
          NULL::int                                                 AS placements,
          NULL::bigint                                              AS avg_fee,
          ROUND(AVG(cltv))::bigint                                   AS avg_cltv,
          ROUND(SUM(cltv))::bigint                                   AS total_cltv,
          CASE WHEN COUNT(*) < 3 THEN '⚠ reducida' ELSE '' END       AS muestra
        FROM pc
        GROUP BY origin
        ORDER BY avg_cltv DESC, origin;
    """
    return sql, {}


DATASET = {
    "key": "mkt_cltv_by_channel",
    "label": "Marketing · CLTV por canal (Staffing | Recruiting)",
    "dimensions": [{"key": "origin", "label": "Canal", "type": "string"}],
    "measures": [
        {"key": "clients", "label": "Clientes", "type": "number"},
        {"key": "active_clients", "label": "Activos", "type": "number"},
        {"key": "placements", "label": "# Placements", "type": "number"},
        {"key": "avg_fee", "label": "Fee promedio", "type": "currency"},
        {"key": "avg_mrr", "label": "MRR promedio", "type": "currency"},
        {"key": "avg_lifetime", "label": "Vida promedio (meses)", "type": "number"},
        {"key": "avg_cltv", "label": "CLTV promedio", "type": "currency"},
        {"key": "total_cltv", "label": "CLTV total", "type": "currency"},
    ],
    "default_filters": {"model": "Staffing"},
    "query": query,
}
