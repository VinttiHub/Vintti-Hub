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
        activos_cutoff AS (
          SELECT DISTINCT ON (h.opportunity_id, h.candidate_id)
            h.opportunity_id,
            h.candidate_id,
            h.salary,
            h.fee
          FROM ventana v
          JOIN hires_full h
            ON h.start_d <= v.win_fin
           AND (h.end_d IS NULL OR h.end_d >= v.win_fin)
          ORDER BY h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        mrr_base AS (
          SELECT
            SUM(
              CASE
                WHEN %(metric)s = 'Fee' THEN a.fee
                ELSE (a.salary + a.fee)
              END
            )::numeric AS mrr_inicial
          FROM activos_cutoff a
        ),
        upsells AS (
          SELECT
            SUM(
              CASE
                WHEN %(metric)s = 'Fee' THEN h.fee
                ELSE (h.salary + h.fee)
              END
            )::numeric AS upsells_lara
          FROM ventana v
          JOIN hires_full h
            ON h.opp_sales_lead = 'lara@vintti.com'
           AND h.opp_close_d IS NOT NULL
           AND h.opp_close_d >  v.win_ini
           AND h.opp_close_d <= v.win_fin
        ),
        perdidas AS (
          SELECT
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
          FROM ventana v
          JOIN hires_full h
            ON h.start_d <= v.win_ini
           AND (h.end_d IS NULL OR h.end_d >= v.win_ini)
          WHERE h.end_d IS NOT NULL
            AND h.end_d >  v.win_ini
            AND h.end_d <= v.win_fin
        )
        SELECT
          TO_CHAR(v.win_ini, 'YYYY-MM-DD')                                           AS win_ini,
          TO_CHAR(v.win_fin, 'YYYY-MM-DD')                                           AS win_fin,
          COALESCE(mb.mrr_inicial,        0)::float                                  AS mrr_inicial,
          COALESCE(u.upsells_lara,        0)::float                                  AS upsells_lara,
          COALESCE(p.downgrades_recorte,  0)::float                                  AS downgrades_recorte,
          COALESCE(p.churn_no_recorte,    0)::float                                  AS churn_no_recorte,
          ROUND(
            100.0 *
            (
              (COALESCE(mb.mrr_inicial, 0)
               + COALESCE(u.upsells_lara, 0)
               - COALESCE(p.downgrades_recorte, 0)
               - COALESCE(p.churn_no_recorte, 0)
              )
              / NULLIF(mb.mrr_inicial, 0)
            )
          , 2)::float                                                                AS nrr_pct
        FROM ventana v
        CROSS JOIN mrr_base mb
        LEFT JOIN upsells u  ON TRUE
        LEFT JOIN perdidas p ON TRUE;
    """

    return sql, {"metric": metric, "corte": corte}


DATASET = {
    "key": "nrr_30d_summary",
    "label": "NRR (Staffing) — Ventana 30 días",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio", "type": "date"},
        {"key": "win_fin", "label": "Fin", "type": "date"},
    ],
    "measures": [
        {"key": "mrr_inicial", "label": "MRR", "type": "currency"},
        {"key": "upsells_lara", "label": "Upsells", "type": "currency"},
        {"key": "downgrades_recorte", "label": "Downgrades", "type": "currency"},
        {"key": "churn_no_recorte", "label": "Churn", "type": "currency"},
        {"key": "nrr_pct", "label": "NRR %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
