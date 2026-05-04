from __future__ import annotations

from datetime import date, datetime


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 3:
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
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date                                AS cutoff,
            (%(corte)s::date - INTERVAL '30 day')::date    AS win_ini,
            %(corte)s::date                                AS win_fin
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
            v.win_fin                AS mes,
            'mrr_inicial'::text      AS componente,
            h.client_name,
            h.candidate_name,
            h.opportunity_id,
            h.start_d,
            h.end_d,
            NULL::text               AS inactive_reason,
            NULL::text               AS opp_sales_lead,
            CASE
              WHEN %(metric)s = 'Fee' THEN h.fee
              ELSE (h.salary + h.fee)
            END::numeric AS monto
          FROM ventana v
          JOIN hires_full h
            ON h.start_d <= v.win_ini
           AND (h.end_d IS NULL OR h.end_d >= v.win_ini)
        ),
        upsells_lara_det AS (
          SELECT
            v.win_fin                AS mes,
            'upsells_lara'::text     AS componente,
            h.client_name,
            h.candidate_name,
            h.opportunity_id,
            h.start_d,
            h.end_d,
            NULL::text               AS inactive_reason,
            h.opp_sales_lead,
            CASE
              WHEN %(metric)s = 'Fee' THEN h.fee
              ELSE (h.salary + h.fee)
            END::numeric AS monto
          FROM ventana v
          JOIN hires_full h
            ON h.opp_sales_lead = 'lara@vintti.com'
           AND h.opp_close_d IS NOT NULL
           AND h.opp_close_d >  v.win_ini
           AND h.opp_close_d <= v.win_fin
        ),
        perdidas_det AS (
          SELECT
            v.win_fin                AS mes,
            CASE
              WHEN h.inactive_reason ILIKE '%%recorte%%' THEN 'downgrades_recorte'
              ELSE 'churn_no_recorte'
            END::text                AS componente,
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
          FROM ventana v
          JOIN hires_full h
            ON h.start_d <= v.win_ini
           AND (h.end_d IS NULL OR h.end_d >= v.win_ini)
          WHERE h.end_d IS NOT NULL
            AND h.end_d >  v.win_ini
            AND h.end_d <= v.win_fin
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

    return sql, {"metric": metric, "corte": corte}


DATASET = {
    "key": "nrr_30d_detail",
    "label": "NRR (Staffing) — Detalle ventana 30 días",
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
