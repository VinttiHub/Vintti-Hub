from __future__ import annotations

from datetime import date, datetime, timezone


def _parse_date(value) -> date | None:
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


def _resolve_modelo(filters: dict) -> str:
    raw = (
        filters.get("modelo")
        or filters.get("modelo1")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return "Total"


def _resolve_resultado(filters: dict) -> str:
    raw = (filters.get("opp_stage") or filters.get("resultado") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    resultado = _resolve_resultado(filters)
    cliente = (filters.get("cliente") or filters.get("client_name") or "").strip() or None
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("mes"))
    )

    sql = """
        WITH cutoff_sel AS (
          SELECT COALESCE(%(corte)s::date, CURRENT_DATE)::date AS cutoff_d
        ),
        ventana AS (
          SELECT
            (c.cutoff_d - INTERVAL '30 day')::date AS win_ini,
            c.cutoff_d::date                       AS win_fin
          FROM cutoff_sel c
        ),
        base AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            TRIM(o.opp_stage) AS opp_stage,
            a.client_name,
            cb.candidate_id,
            COALESCE(NULLIF(TRIM(cb.status), ''), 'Client interviewing/testing') AS status_norm
          FROM candidates_batches cb
          JOIN batch b ON b.batch_id = cb.batch_id
          JOIN opportunity o ON o.opportunity_id = b.opportunity_id
          JOIN account a ON a.account_id = o.account_id
          CROSS JOIN ventana v
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(b.presentation_date::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'')::date >= v.win_ini
            AND NULLIF(o.opp_close_date::text,'')::date <  (v.win_fin + INTERVAL '1 day')
            AND (%(modelo)s = 'Total' OR o.opp_model = %(modelo)s)
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
            AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
        ),
        por_opp AS (
          SELECT
            opportunity_id,
            COUNT(DISTINCT candidate_id) AS enviados,
            COUNT(DISTINCT CASE
              WHEN status_norm IN (
                'Client interviewing/testing',
                'Client rejected after interviewing',
                'Client hired'
              )
              THEN candidate_id
            END) AS entrevistados,
            CASE
              WHEN COUNT(DISTINCT candidate_id) = 0 THEN 0::numeric
              ELSE
                (COUNT(DISTINCT CASE
                  WHEN status_norm IN (
                    'Client interviewing/testing',
                    'Client rejected after interviewing',
                    'Client hired'
                  )
                  THEN candidate_id
                END)::numeric * 100.0)
                / COUNT(DISTINCT candidate_id)
            END AS entrevistados_sobre_enviados_pct
          FROM base
          GROUP BY 1
        )
        SELECT
          ROUND(AVG(entrevistados_sobre_enviados_pct), 2)::float AS promedio_pct_por_opportunity,
          ROUND(
            (SUM(entrevistados)::numeric * 100.0) / NULLIF(SUM(enviados), 0),
            2
          )::float                              AS pct_ponderado_total,
          SUM(enviados)::float                  AS total_enviados,
          SUM(entrevistados)::float             AS total_entrevistados,
          COUNT(*)::int                         AS total_opps
        FROM por_opp;
    """

    return sql, {
        "modelo": modelo,
        "resultado": resultado,
        "cliente": cliente,
        "corte": corte,
    }


DATASET = {
    "key": "interviewed_sent_30d_summary",
    "label": "Entrevistados vs Enviados en Clientes — Ventana 30 días (global)",
    "dimensions": [],
    "measures": [
        {"key": "promedio_pct_por_opportunity", "label": "Promedio % por opp", "type": "percent"},
        {"key": "pct_ponderado_total", "label": "Conversión global %", "type": "percent"},
        {"key": "total_enviados", "label": "Total enviados", "type": "number"},
        {"key": "total_entrevistados", "label": "Total entrevistados", "type": "number"},
        {"key": "total_opps", "label": "Total opps", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
