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


def _resolve_modelo(filters: dict) -> str | None:
    raw = (
        filters.get("modelo")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    mes = (
        _parse_date(filters.get("fecha"))
        or _parse_date(filters.get("mes"))
        or _parse_date(filters.get("month"))
    )
    modelo = _resolve_modelo(filters)

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
        ),
        base AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(ho.start_date::text, '') IS NOT NULL THEN ho.start_date::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text, '') IS NOT NULL THEN ho.end_date::date
              ELSE NULL
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.candidate_id IS NOT NULL
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND o.opp_model IN ('Staffing','Recruiting')
        ),
        detalle AS (
          SELECT DISTINCT
            DATE_TRUNC('month', b.start_d)::date AS mes,
            b.opp_model,
            b.candidate_id,
            c.name AS candidate_name,
            b.opportunity_id,
            b.start_d,
            b.end_d
          FROM base b
          LEFT JOIN candidates c ON c.candidate_id = b.candidate_id
          WHERE b.start_d IS NOT NULL
        )
        SELECT
          TO_CHAR(d.mes, 'YYYY-MM') AS mes,
          d.opp_model,
          d.candidate_name,
          d.opportunity_id,
          TO_CHAR(d.start_d, 'YYYY-MM-DD') AS start_date,
          TO_CHAR(d.end_d,   'YYYY-MM-DD') AS end_date
        FROM detalle d
        JOIN mes_objetivo m ON d.mes = m.mes_pick
        ORDER BY d.opp_model, d.start_d, d.opportunity_id, d.candidate_id;
    """

    return sql, {"mes": mes, "modelo": modelo}


DATASET = {
    "key": "new_placements_month_detail",
    "label": "Nuevas colocaciones — Detalle del mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "number"},
        {"key": "start_date", "label": "Start", "type": "date"},
        {"key": "end_date", "label": "End", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
