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
            a.client_name,
            o.opp_position_name,
            TRIM(o.opp_stage) AS opp_stage,
            o.opp_model,
            cb.candidate_id,
            COALESCE(NULLIF(TRIM(cb.status), ''), 'Client interviewing/testing') AS status_norm,
            NULLIF(o.opp_close_date::text,'')::date AS close_d
          FROM candidates_batches cb
          JOIN batch b ON b.batch_id = cb.batch_id
          JOIN opportunity o ON o.opportunity_id = b.opportunity_id
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(b.presentation_date::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
        )
        SELECT
          b.opportunity_id::text                  AS opportunity_id,
          b.client_name,
          b.opp_position_name,
          b.opp_stage                             AS resultado,
          COUNT(DISTINCT b.candidate_id)::float   AS candidatos_enviados,
          COUNT(DISTINCT CASE
            WHEN b.status_norm IN (
              'Client interviewing/testing',
              'Client rejected after interviewing',
              'Client hired'
            )
            THEN b.candidate_id
          END)::float                             AS candidatos_entrevistados,
          ROUND(
            CASE
              WHEN COUNT(DISTINCT b.candidate_id) = 0 THEN NULL
              ELSE
                COUNT(DISTINCT CASE
                  WHEN b.status_norm IN (
                    'Client interviewing/testing',
                    'Client rejected after interviewing',
                    'Client hired'
                  )
                  THEN b.candidate_id
                END)::numeric
                / COUNT(DISTINCT b.candidate_id)
                * 100
            END
          , 2)::float                              AS entrevistados_sobre_enviados_pct
        FROM base b
        CROSS JOIN ventana v
        WHERE (%(modelo)s = 'Total' OR b.opp_model = %(modelo)s)
          AND b.close_d >= v.win_ini
          AND b.close_d <  (v.win_fin + INTERVAL '1 day')
          AND (%(resultado)s = 'Total' OR b.opp_stage = %(resultado)s)
        GROUP BY 1,2,3,4
        ORDER BY candidatos_enviados DESC;
    """

    return sql, {"modelo": modelo, "resultado": resultado, "corte": corte}


DATASET = {
    "key": "interviewed_sent_30d_history",
    "label": "Entrevistados vs Enviados en Clientes — Ventana 30 días por opp",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "resultado", "label": "Resultado", "type": "string"},
    ],
    "measures": [
        {"key": "candidatos_enviados", "label": "Enviados", "type": "number"},
        {"key": "candidatos_entrevistados", "label": "Entrevistados", "type": "number"},
        {"key": "entrevistados_sobre_enviados_pct", "label": "Entrevistados / Enviados %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
