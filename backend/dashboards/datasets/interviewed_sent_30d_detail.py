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


def _resolve_int(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    resultado = _resolve_resultado(filters)
    opportunity_id = _resolve_int(
        filters.get("opportunity_id")
        or filters.get("opp_id")
    )
    today = datetime.now(timezone.utc).date()
    desde = (
        _parse_date(filters.get("desde"))
        or date(today.year, today.month, 1)
    )
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    end_of_month = date.fromordinal(next_month.toordinal() - 1)
    hasta = _parse_date(filters.get("hasta")) or end_of_month

    sql = """
        WITH base AS (
          SELECT
            b.opportunity_id,
            a.client_name,
            o.opp_position_name,
            o.opp_model,
            TRIM(o.opp_stage) AS opp_stage,
            cb.candidate_id,
            COALESCE(c.name, '') AS candidate_name,
            b.batch_id,
            b.presentation_date::date AS presentation_date,
            COALESCE(NULLIF(TRIM(cb.status), ''), 'Client interviewing/testing') AS status_norm,
            NULLIF(o.opp_close_date::text,'')::date AS close_d
          FROM candidates_batches cb
          JOIN batch b ON b.batch_id = cb.batch_id
          JOIN opportunity o ON o.opportunity_id = b.opportunity_id
          JOIN account a ON a.account_id = o.account_id
          LEFT JOIN candidates c ON c.candidate_id = cb.candidate_id
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(b.presentation_date::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND (%(opportunity_id)s::int IS NULL OR b.opportunity_id = %(opportunity_id)s)
        )
        SELECT
          b.opportunity_id::text         AS opportunity_id,
          b.client_name,
          b.opp_position_name,
          b.opp_model,
          b.opp_stage                    AS resultado,
          b.candidate_name,
          CASE
            WHEN BOOL_OR(b.status_norm = 'Client hired') THEN 'Client hired'
            WHEN BOOL_OR(b.status_norm = 'Client rejected after interviewing') THEN 'Client rejected after interviewing'
            WHEN BOOL_OR(b.status_norm = 'Client interviewing/testing') THEN 'Client interviewing/testing'
            ELSE MIN(b.status_norm)
          END                            AS status_final
        FROM base b
        WHERE (%(modelo)s = 'Total' OR b.opp_model = %(modelo)s)
          AND b.close_d >= %(desde)s::date
          AND b.close_d <  (%(hasta)s::date + INTERVAL '1 day')
          AND (%(resultado)s = 'Total' OR b.opp_stage = %(resultado)s)
        GROUP BY
          b.opportunity_id, b.client_name, b.opp_position_name, b.opp_model,
          b.opp_stage, b.candidate_id, b.candidate_name
        ORDER BY b.candidate_name;
    """

    return sql, {
        "modelo": modelo,
        "resultado": resultado,
        "opportunity_id": opportunity_id,
        "desde": desde,
        "hasta": hasta,
    }


DATASET = {
    "key": "interviewed_sent_30d_detail",
    "label": "Entrevistados vs Enviados en Clientes — Detalle por candidato",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "resultado", "label": "Resultado", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "status_final", "label": "Status final", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
