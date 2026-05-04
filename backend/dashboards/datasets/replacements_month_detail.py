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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _norm_model(filters.get("model") or filters.get("modelo"))
    mes = (
        _parse_date(filters.get("fecha_replacements"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
        ),
        opp_replacements AS (
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
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        ),
        old_end AS (
          SELECT
            ho.candidate_id::text AS old_candidate_id,
            MAX(NULLIF(ho.end_date::text, '')::date) AS old_end_date
          FROM hire_opportunity ho
          GROUP BY ho.candidate_id::text
        ),
        new_start AS (
          SELECT
            ho.opportunity_id,
            MIN(NULLIF(ho.start_date::text, '')::date) AS new_start_date,
            MIN(ho.candidate_id)::text AS new_candidate_id
          FROM hire_opportunity ho
          GROUP BY ho.opportunity_id
        )
        SELECT
          TO_CHAR(DATE_TRUNC('month', ns.new_start_date)::date, 'YYYY-MM-DD') AS month,
          r.client_name,
          r.opp_model,
          r.opp_stage,
          c_old.name        AS replaced_candidate_name,
          TO_CHAR(oe.old_end_date,   'YYYY-MM-DD') AS old_end_date,
          c_new.name        AS new_candidate_name,
          TO_CHAR(ns.new_start_date, 'YYYY-MM-DD') AS new_start_date,
          CASE
            WHEN oe.old_end_date IS NOT NULL AND ns.new_start_date IS NOT NULL
              THEN (ns.new_start_date - oe.old_end_date)
            ELSE NULL
          END::int AS days_to_replace
        FROM opp_replacements r
        LEFT JOIN old_end oe
          ON oe.old_end_date IS NOT NULL
         AND oe.old_candidate_id = r.old_candidate_id
        LEFT JOIN new_start ns
          ON ns.new_start_date IS NOT NULL
         AND ns.opportunity_id = r.opportunity_id
        LEFT JOIN candidates c_old
          ON c_old.candidate_id::text = r.old_candidate_id
        LEFT JOIN candidates c_new
          ON c_new.candidate_id::text = ns.new_candidate_id
        CROSS JOIN mes_objetivo mo
        WHERE ns.new_start_date IS NOT NULL
          AND DATE_TRUNC('month', ns.new_start_date)::date = mo.mes_pick
        ORDER BY r.client_name, r.opportunity_id;
    """

    return sql, {"modelo": modelo, "mes": mes}


DATASET = {
    "key": "replacements_month_detail",
    "label": "% de reemplazos realizados — Detalle del mes",
    "dimensions": [
        {"key": "month", "label": "Mes", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "replaced_candidate_name", "label": "Reemplazado", "type": "string"},
        {"key": "old_end_date", "label": "Old end", "type": "date"},
        {"key": "new_candidate_name", "label": "Nuevo", "type": "string"},
        {"key": "new_start_date", "label": "New start", "type": "date"},
    ],
    "measures": [
        {"key": "days_to_replace", "label": "Días para reemplazar", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
