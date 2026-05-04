from __future__ import annotations

from datetime import date


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def _norm_metric(value) -> str:
    if not value:
        return "All"
    raw = str(value).strip()
    if raw in ("All", "Revenue", "Fee"):
        return raw
    if raw.lower() == "all":
        return "All"
    if raw.lower() == "revenue":
        return "Revenue"
    if raw.lower() == "fee":
        return "Fee"
    return "All"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    metric = _norm_metric(filters.get("metric"))
    mes = (
        _parse_date(filters.get("fecha_nrr"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_sel
        ),
        mes_fin AS (
          SELECT
            mo.mes_sel AS mes,
            (mo.mes_sel + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM mes_objetivo mo
        ),
        hires_full AS (
          SELECT
            ho.opportunity_id,
            ho.candidate_id,
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            COALESCE(ho.salary, 0)::numeric AS salary,
            COALESCE(ho.fee,    0)::numeric AS fee,
            TRIM(COALESCE(ho.inactive_reason::text, '')) AS inactive_reason,
            o.opp_sales_lead,
            o.opp_close_date::date AS opp_close_d,
            a.client_name,
            c.name AS candidate_name
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a    ON a.account_id    = ho.account_id
          LEFT JOIN candidates c ON c.candidate_id  = ho.candidate_id
          WHERE o.opp_model = 'Staffing'
            AND (
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                ELSE NULLIF(ho.start_date::text, '')::date
              END
            ) IS NOT NULL
        ),
        mrr_inicial_det AS (
          SELECT
            mf.mes,
            'mrr_inicial'::text AS componente,
            h.client_name,
            h.candidate_name,
            h.opportunity_id,
            h.start_d,
            h.end_d,
            NULL::text AS inactive_reason,
            NULL::text AS opp_sales_lead,
            CASE
              WHEN %(metric)s = 'Fee' THEN h.fee
              ELSE (h.salary + h.fee)
            END::numeric AS monto
          FROM mes_fin mf
          JOIN hires_full h
            ON h.start_d <= mf.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= mf.fin_mes)
        ),
        upsells_lara_det AS (
          SELECT
            mf.mes,
            'upsells_lara'::text AS componente,
            h.client_name,
            h.candidate_name,
            h.opportunity_id,
            h.start_d,
            h.end_d,
            NULL::text AS inactive_reason,
            h.opp_sales_lead,
            CASE
              WHEN %(metric)s = 'Fee' THEN h.fee
              ELSE (h.salary + h.fee)
            END::numeric AS monto
          FROM mes_fin mf
          JOIN hires_full h
            ON h.opp_sales_lead = 'lara@vintti.com'
           AND h.opp_close_d IS NOT NULL
           AND h.opp_close_d >= mf.mes
           AND h.opp_close_d <= mf.fin_mes
        ),
        perdidas_det AS (
          SELECT
            mf.mes,
            CASE
              WHEN h.inactive_reason ILIKE '%%recorte%%' THEN 'downgrades_recorte'
              ELSE 'churn_no_recorte'
            END::text AS componente,
            h.client_name,
            h.candidate_name,
            h.opportunity_id,
            h.start_d,
            h.end_d,
            h.inactive_reason,
            h.opp_sales_lead,
            CASE
              WHEN %(metric)s = 'Fee' THEN h.fee
              ELSE (h.salary + h.fee)
            END::numeric AS monto
          FROM mes_fin mf
          JOIN hires_full h
            ON h.start_d <= (mf.mes - INTERVAL '1 day')::date
           AND (h.end_d IS NULL OR h.end_d >= (mf.mes - INTERVAL '1 day')::date)
          WHERE h.end_d IS NOT NULL
            AND h.end_d >= mf.mes
            AND h.end_d <= mf.fin_mes
        ),
        all_rows AS (
          SELECT * FROM mrr_inicial_det
          UNION ALL
          SELECT * FROM upsells_lara_det
          UNION ALL
          SELECT * FROM perdidas_det
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')          AS mes,
          componente,
          client_name,
          candidate_name,
          opportunity_id,
          TO_CHAR(start_d, 'YYYY-MM-DD')      AS start_d,
          TO_CHAR(end_d,   'YYYY-MM-DD')      AS end_d,
          inactive_reason,
          opp_sales_lead,
          monto::float                        AS monto
        FROM all_rows
        ORDER BY componente, client_name, candidate_name, opportunity_id;
    """

    return sql, {"metric": metric, "mes": mes}


DATASET = {
    "key": "nrr_month_detail",
    "label": "NRR — Detalle del mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "componente", "label": "Componente", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "opportunity_id", "label": "Opportunity", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
        {"key": "end_d", "label": "End", "type": "date"},
        {"key": "inactive_reason", "label": "Razón inactividad", "type": "string"},
        {"key": "opp_sales_lead", "label": "Sales lead", "type": "string"},
    ],
    "measures": [
        {"key": "monto", "label": "Monto", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
