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


def _resolve_modelo(filters: dict) -> str | None:
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
    return None


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
    cliente = (filters.get("cliente") or filters.get("client_name") or "").strip() or None
    opportunity_id = _resolve_int(
        filters.get("opportunity_id")
        or filters.get("opp_id")
        or filters.get("Opp_EC")
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("mes"))
        or datetime.now(timezone.utc).date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            (%(corte)s::date - INTERVAL '30 day')::date AS win_ini,
            %(corte)s::date                              AS win_fin
        ),
        opp AS (
          SELECT
            o.opportunity_id,
            o.opp_position_name,
            o.opp_model,
            a.client_name
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          CROSS JOIN ventana v
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
            AND NULLIF(o.opp_close_date::text,'')::date >= v.win_ini
            AND NULLIF(o.opp_close_date::text,'')::date <  (v.win_fin + INTERVAL '1 day')
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
        ),
        b AS (
          SELECT
            b.batch_id,
            b.opportunity_id,
            NULLIF(b.presentation_date::text,'')::date AS sent_date
          FROM batch b
          WHERE b.batch_id IS NOT NULL
            AND NULLIF(b.presentation_date::text,'') IS NOT NULL
            AND (%(desde)s::date IS NULL OR b.presentation_date::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR b.presentation_date::date <= %(hasta)s::date)
        ),
        sent_detail AS (
          SELECT
            b.opportunity_id,
            cb.candidate_id,
            c.name AS candidate_name,
            b.sent_date
          FROM candidates_batches cb
          JOIN b ON b.batch_id = cb.batch_id
          LEFT JOIN candidates c ON c.candidate_id = cb.candidate_id
        ),
        hired_any AS (
          SELECT DISTINCT ho.candidate_id
          FROM hire_opportunity ho
          WHERE ho.candidate_id IS NOT NULL
        )
        SELECT
          sd.opportunity_id::text                    AS opportunity_id,
          o.client_name,
          o.opp_position_name,
          sd.candidate_name,
          TO_CHAR(sd.sent_date, 'YYYY-MM-DD')        AS sent_date,
          CASE
            WHEN ha.candidate_id IS NOT NULL THEN 'Sí'
            ELSE 'No'
          END                                        AS contratado
        FROM sent_detail sd
        JOIN opp o
          ON o.opportunity_id = sd.opportunity_id
        LEFT JOIN hired_any ha
          ON ha.candidate_id = sd.candidate_id
        WHERE (%(opportunity_id)s::int IS NULL OR sd.opportunity_id = %(opportunity_id)s)
        ORDER BY sd.sent_date ASC, sd.candidate_name;
    """

    return sql, {
        "modelo": modelo,
        "cliente": cliente,
        "opportunity_id": opportunity_id,
        "desde": desde,
        "hasta": hasta,
        "corte": corte,
    }


DATASET = {
    "key": "sent_hired_30d_detail",
    "label": "Enviados vs Contratados — Detalle por candidato",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "sent_date", "label": "Fecha envío", "type": "date"},
        {"key": "contratado", "label": "Contratado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
