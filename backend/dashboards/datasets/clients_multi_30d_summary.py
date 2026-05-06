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


def _norm_modelo(value) -> str:
    if not value:
        return "Total"
    raw = str(value).strip()
    if raw in ("Total", "Staffing", "Recruiting"):
        return raw
    cap = raw[:1].upper() + raw[1:].lower()
    if cap in ("Total", "Staffing", "Recruiting"):
        return cap
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    modelo = _norm_modelo(filters.get("modelo") or filters.get("model") or filters.get("segmento"))

    sql = """
        WITH hires AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            ho.start_date::date AS start_d,
            CASE
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            o.opp_model AS model
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
            AND ho.start_date IS NOT NULL
            AND o.opp_model IN ('Staffing', 'Recruiting')
        ),
        corte AS (
          SELECT %(corte)s::date AS fecha_corte
        ),
        activos_al_corte AS (
          SELECT
            c.fecha_corte,
            h.account_id,
            h.candidate_id
          FROM corte c
          JOIN hires h
            ON h.start_d <= c.fecha_corte
           AND COALESCE(h.end_d, DATE '9999-12-31') >= c.fecha_corte
           AND (%(modelo)s = 'Total' OR h.model = %(modelo)s)
        ),
        candidatos_por_cliente AS (
          SELECT
            fecha_corte,
            account_id,
            COUNT(DISTINCT candidate_id) AS candidatos_activos
          FROM activos_al_corte
          GROUP BY 1, 2
        )
        SELECT
          TO_CHAR(fecha_corte, 'YYYY-MM-DD')                                                AS fecha_corte,
          COUNT(DISTINCT account_id)::int                                                   AS clientes_activos,
          COUNT(DISTINCT account_id) FILTER (WHERE candidatos_activos > 1)::int             AS mayor_a_1,
          ROUND(
            100.0 * COUNT(DISTINCT account_id) FILTER (WHERE candidatos_activos > 1)
            / NULLIF(COUNT(DISTINCT account_id), 0)
          , 2)::float                                                                       AS pct_percent
        FROM candidatos_por_cliente
        GROUP BY fecha_corte;
    """

    return sql, {"corte": corte, "modelo": modelo}


DATASET = {
    "key": "clients_multi_30d_summary",
    "label": "% Clientes con > 1 candidato — Día corte",
    "dimensions": [],
    "measures": [
        {"key": "clientes_activos", "label": "Clientes activos", "type": "number"},
        {"key": "mayor_a_1", "label": "Clientes > 1", "type": "number"},
        {"key": "pct_percent", "label": "% > 1", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
