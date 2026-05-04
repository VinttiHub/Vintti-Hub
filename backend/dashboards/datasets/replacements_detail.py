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

    sql = """
        WITH opp_replacements AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            a.client_name,
            o.opp_model,
            o.opp_stage,
            o.opp_type,
            NULLIF(o.replacement_of::text, '')::text AS old_candidate_id
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opp_type = 'Replacement'
            AND o.opp_stage IN ('Close Win', 'Close Lost')
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
            AND (%(modelo)s::text  IS NULL OR o.opp_model   = %(modelo)s)
        ),
        old_end AS (
          SELECT
            ho.candidate_id::text AS old_candidate_id,
            MAX(
              CASE
                WHEN NULLIF(ho.end_date::text, '') IS NULL THEN NULL
                ELSE ho.end_date::date
              END
            ) AS old_end_date
          FROM hire_opportunity ho
          WHERE ho.candidate_id IS NOT NULL
          GROUP BY ho.candidate_id::text
        ),
        new_start AS (
          SELECT
            ho.opportunity_id,
            MIN(
              CASE
                WHEN NULLIF(ho.start_date::text, '') IS NULL THEN NULL
                ELSE ho.start_date::date
              END
            ) AS new_start_date,
            MIN(ho.candidate_id)::text AS new_candidate_id
          FROM hire_opportunity ho
          WHERE ho.opportunity_id IS NOT NULL
          GROUP BY ho.opportunity_id
        )
        SELECT
          TO_CHAR(DATE_TRUNC('month', COALESCE(ns.new_start_date, oe.old_end_date))::date, 'YYYY-MM-DD') AS month,
          r.client_name,
          r.opp_model,
          r.opportunity_id,
          r.opp_stage,
          'Yes'::text AS is_replacement,
          r.old_candidate_id        AS replaced_candidate_id,
          TO_CHAR(oe.old_end_date,     'YYYY-MM-DD') AS old_end_date,
          ns.new_candidate_id       AS new_candidate_id,
          TO_CHAR(ns.new_start_date,   'YYYY-MM-DD') AS new_start_date,
          CASE
            WHEN oe.old_end_date IS NOT NULL AND ns.new_start_date IS NOT NULL
              THEN (ns.new_start_date - oe.old_end_date)
            ELSE NULL
          END::int AS days_to_replace
        FROM opp_replacements r
        LEFT JOIN old_end   oe ON oe.old_candidate_id = r.old_candidate_id
        LEFT JOIN new_start ns ON ns.opportunity_id   = r.opportunity_id
        WHERE 1=1
          AND (%(desde)s::date IS NULL OR COALESCE(oe.old_end_date, ns.new_start_date) >= %(desde)s::date)
          AND (%(hasta)s::date IS NULL OR COALESCE(oe.old_end_date, ns.new_start_date) <= %(hasta)s::date)
        ORDER BY r.client_name, r.opp_model, r.opportunity_id;
    """

    return sql, {"modelo": modelo, "cliente": cliente, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "replacements_detail",
    "label": "Reemplazos — Detalle",
    "dimensions": [
        {"key": "month", "label": "Mes", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "opportunity_id", "label": "Opportunity", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "is_replacement", "label": "Replacement", "type": "string"},
        {"key": "replaced_candidate_id", "label": "Reemplazado (id)", "type": "string"},
        {"key": "old_end_date", "label": "Old end", "type": "date"},
        {"key": "new_candidate_id", "label": "Nuevo (id)", "type": "string"},
        {"key": "new_start_date", "label": "New start", "type": "date"},
    ],
    "measures": [
        {"key": "days_to_replace", "label": "Días para reemplazar", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
