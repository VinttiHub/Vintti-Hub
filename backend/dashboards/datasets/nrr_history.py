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
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH mrr_base AS (
          WITH hires AS (
            SELECT *
            FROM (
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
                COALESCE(ho.fee,    0)::numeric AS fee
              FROM hire_opportunity ho
              JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
              WHERE o.opp_model = 'Staffing'
            ) x
            WHERE start_d IS NOT NULL
          ),
          meses AS (
            SELECT
              DATE_TRUNC('month', gs)::date                                AS mes,
              (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
            FROM generate_series(
              (SELECT MIN(start_d) FROM hires),
              (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM hires),
              INTERVAL '1 month'
            ) gs
          ),
          activos_fin AS (
            SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
                   m.mes, h.opportunity_id, h.candidate_id, h.start_d, h.end_d, h.salary, h.fee
            FROM meses m
            JOIN hires h
              ON h.start_d <= m.fin_mes
             AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
            ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
          ),
          mrr_mes AS (
            SELECT
              mes,
              SUM(
                CASE
                  WHEN %(metric)s = 'Fee'     THEN fee
                  ELSE (salary + fee)
                END
              )::numeric AS mrr_total
            FROM activos_fin
            GROUP BY mes
          )
          SELECT mes, mrr_total
          FROM mrr_mes
        ),
        base_nrr AS (
          SELECT
            mes,
            mrr_total AS mrr_inicial
          FROM mrr_base
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
            o.opp_close_date::date AS opp_close_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND (
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                ELSE NULLIF(ho.start_date::text, '')::date
              END
            ) IS NOT NULL
        ),
        upsells_lara AS (
          SELECT
            b.mes,
            SUM(
              CASE
                WHEN %(metric)s = 'Fee' THEN h.fee
                ELSE (h.salary + h.fee)
              END
            )::numeric AS upsells_lara
          FROM base_nrr b
          JOIN hires_full h
            ON h.opp_sales_lead = 'lara@vintti.com'
           AND h.opp_close_d >= b.mes
           AND h.opp_close_d <= (b.mes + INTERVAL '1 month - 1 day')::date
          WHERE b.mrr_inicial IS NOT NULL AND b.mrr_inicial > 0
          GROUP BY b.mes
        ),
        perdidas AS (
          SELECT
            b.mes,
            SUM(
              CASE
                WHEN h.inactive_reason ILIKE '%%recorte%%' THEN
                  CASE WHEN %(metric)s = 'Fee' THEN h.fee ELSE (h.salary + h.fee) END
                ELSE 0
              END
            )::numeric AS downgrades_recorte,
            SUM(
              CASE
                WHEN h.inactive_reason ILIKE '%%recorte%%' THEN 0
                ELSE
                  CASE WHEN %(metric)s = 'Fee' THEN h.fee ELSE (h.salary + h.fee) END
              END
            )::numeric AS churn_no_recorte
          FROM base_nrr b
          JOIN hires_full h
            ON h.start_d <= (b.mes - INTERVAL '1 day')::date
           AND (h.end_d IS NULL OR h.end_d >= (b.mes - INTERVAL '1 day')::date)
          WHERE h.end_d IS NOT NULL
            AND h.end_d >= b.mes
            AND h.end_d <= (b.mes + INTERVAL '1 month - 1 day')::date
          GROUP BY b.mes
        )
        SELECT
          TO_CHAR(b.mes, 'YYYY-MM-DD')                          AS mes,
          b.mrr_inicial::float                                  AS mrr_inicial,
          COALESCE(u.upsells_lara, 0)::float                    AS upsells_lara,
          COALESCE(p.downgrades_recorte, 0)::float              AS downgrades_recorte,
          COALESCE(p.churn_no_recorte, 0)::float                AS churn_no_recorte,
          ROUND(
            100.0 *
            (
              (COALESCE(b.mrr_inicial, 0)
               + COALESCE(u.upsells_lara, 0)
               - COALESCE(p.downgrades_recorte, 0)
               - COALESCE(p.churn_no_recorte, 0)
              )
              / NULLIF(b.mrr_inicial, 0)
            )
          , 2)::float                                           AS nrr_pct
        FROM base_nrr b
        LEFT JOIN upsells_lara u ON u.mes = b.mes
        LEFT JOIN perdidas    p ON p.mes = b.mes
        WHERE b.mrr_inicial IS NOT NULL
          AND (%(desde)s::date IS NULL OR b.mes >= DATE_TRUNC('month', %(desde)s::date))
          AND (%(hasta)s::date IS NULL OR b.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ORDER BY b.mes;
    """

    return sql, {"metric": metric, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "nrr_history",
    "label": "NRR mensual (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "mrr_inicial", "label": "MRR inicial", "type": "currency"},
        {"key": "upsells_lara", "label": "Upsells Lara", "type": "currency"},
        {"key": "downgrades_recorte", "label": "Downgrades", "type": "currency"},
        {"key": "churn_no_recorte", "label": "Churn", "type": "currency"},
        {"key": "nrr_pct", "label": "NRR %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
