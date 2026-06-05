"""Marketing · detalle CLTV por canal — un cliente por fila (CLTV = MRR × vida real)."""
from __future__ import annotations


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    channel = str(filters.get("channel") or filters.get("origin") or "").strip()
    ch_clause = "AND COALESCE(NULLIF(TRIM(a.where_come_from, ''), ''), '(Sin origen)') = %(channel)s" if channel else ""

    sql = f"""
        WITH acct AS (
          SELECT a.account_id, a.client_name,
                 COALESCE(NULLIF(TRIM(a.where_come_from, ''), ''), '(Sin origen)') AS origin
          FROM account a
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
            {ch_clause}
        ),
        hires AS (
          SELECT ho.account_id, COALESCE(ho.fee, 0)::numeric AS fee,
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
        hc AS (
          SELECT h.account_id, ac.client_name, ac.origin, h.fee, h.start_d, h.end_d,
            (h.end_d IS NULL OR h.end_d >= CURRENT_DATE) AS hire_active,
            GREATEST(1, (DATE_PART('year', AGE(COALESCE(h.end_d, CURRENT_DATE), h.start_d)) * 12
                       + DATE_PART('month', AGE(COALESCE(h.end_d, CURRENT_DATE), h.start_d)) + 1))::int AS months
          FROM hires h JOIN acct ac ON ac.account_id = h.account_id
          WHERE h.start_d IS NOT NULL
        )
        SELECT
          client_name, origin,
          CASE WHEN BOOL_OR(hire_active) THEN 'Activo' ELSE 'Inactivo' END AS estado,
          SUM(fee * months)::bigint AS cltv,
          (DATE_PART('year', AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) * 12
         + DATE_PART('month', AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) + 1)::int AS lifetime_months,
          ROUND(SUM(fee * months) / NULLIF(
            (DATE_PART('year', AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) * 12
           + DATE_PART('month', AGE(MAX(COALESCE(end_d, CURRENT_DATE)), MIN(start_d))) + 1), 0))::bigint AS mrr
        FROM hc
        GROUP BY client_name, origin
        ORDER BY cltv DESC, client_name;
    """
    params = {"channel": channel} if channel else {}
    return sql, params


DATASET = {
    "key": "mkt_cltv_by_channel_detail",
    "label": "Marketing · detalle CLTV por canal (por cliente)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "origin", "label": "Canal", "type": "string"},
        {"key": "estado", "label": "Estado", "type": "string"},
        {"key": "lifetime_months", "label": "Vida (meses)", "type": "number"},
    ],
    "measures": [
        {"key": "cltv", "label": "CLTV", "type": "currency"},
        {"key": "mrr", "label": "MRR", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
