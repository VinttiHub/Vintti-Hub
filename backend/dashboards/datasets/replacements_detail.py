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


def _norm_model(value) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return raw[:1].upper() + raw[1:].lower()


def _norm_str(value) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    return raw or None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _norm_model(filters.get("model") or filters.get("modelo"))
    cliente = _norm_str(filters.get("cliente"))
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    # Month-aware filter: when present, narrow to opps whose Close Win happened
    # in the same calendar month as `corte` (end-of-month date passed by the JS
    # `refetchMonthAwareElements` helper). Falls back to desde/hasta.
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
    )

    # Replacement events shown in the detail = Replacement opps with stage
    # 'Close Win' whose `opp_close_date` falls in the selected month. Joined to
    # `hire_opportunity` to pull the candidate that became the replacement.
    sql = """
        WITH replacement_close_wins AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            a.client_name,
            o.opp_model,
            o.opp_stage,
            NULLIF(o.opp_close_date::text, '')::date AS close_d,
            NULLIF(o.replacement_of::text, '')::text AS replaced_candidate_id
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_type = 'Replacement'
            AND TRIM(o.opp_stage) = 'Close Win'
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
            AND (%(modelo)s::text  IS NULL OR o.opp_model   = %(modelo)s)
        ),
        hire_per_opp AS (
          SELECT
            ho.opportunity_id,
            MIN(ho.candidate_id)::text AS new_candidate_id,
            MIN(c.name) AS candidate_name
          FROM hire_opportunity ho
          LEFT JOIN candidates c ON c.candidate_id = ho.candidate_id
          WHERE ho.opportunity_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
          GROUP BY ho.opportunity_id
        )
        SELECT
          TO_CHAR(DATE_TRUNC('month', r.close_d)::date, 'YYYY-MM-DD') AS month,
          r.client_name,
          r.opp_model,
          r.opportunity_id,
          r.opp_stage,
          hp.candidate_name,
          hp.new_candidate_id,
          r.replaced_candidate_id,
          TO_CHAR(r.close_d, 'YYYY-MM-DD') AS close_date
        FROM replacement_close_wins r
        LEFT JOIN hire_per_opp hp ON hp.opportunity_id = r.opportunity_id
        WHERE r.close_d IS NOT NULL
          AND (
            %(corte)s::date IS NULL
            OR DATE_TRUNC('month', r.close_d) = DATE_TRUNC('month', %(corte)s::date)
          )
          AND (%(desde)s::date IS NULL OR r.close_d >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR r.close_d <= %(hasta)s::date)
        ORDER BY r.close_d DESC, r.client_name;
    """

    return sql, {
        "modelo": modelo,
        "cliente": cliente,
        "desde": desde,
        "hasta": hasta,
        "corte": corte,
    }


DATASET = {
    "key": "replacements_detail",
    "label": "Reemplazos — Detalle",
    "dimensions": [
        {"key": "month", "label": "Mes", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "opportunity_id", "label": "Opportunity", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "candidate_name", "label": "Replacement (candidato)", "type": "string"},
        {"key": "new_candidate_id", "label": "Replacement (id)", "type": "string"},
        {"key": "replaced_candidate_id", "label": "Reemplazado (id)", "type": "string"},
        {"key": "close_date", "label": "Fecha de cierre", "type": "date"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
