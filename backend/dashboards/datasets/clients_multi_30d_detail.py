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


def _norm_segmento(value) -> str:
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
    segmento = _norm_segmento(filters.get("segmento"))

    sql = """
        WITH hires AS (
          SELECT
            ho.account_id,
            a.client_name,
            ho.candidate_id,
            c.name              AS candidate_name,
            ho.start_date::date AS start_d,
            CASE
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END                  AS end_d,
            o.opp_model          AS model
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a     ON a.account_id    = ho.account_id
          JOIN candidates c  ON c.candidate_id  = ho.candidate_id
          WHERE ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
            AND ho.start_date IS NOT NULL
            AND o.opp_model IN ('Staffing', 'Recruiting')
        ),
        periodos AS (
          SELECT
            (%(corte)s::date - INTERVAL '30 days')::date AS period_start,
            %(corte)s::date                              AS period_end,
            TO_CHAR(%(corte)s::date, 'YYYY-MM-DD')       AS etiqueta
        ),
        activos AS (
          SELECT DISTINCT
            per.etiqueta AS periodo,
            h.account_id,
            h.client_name,
            h.candidate_id,
            h.candidate_name
          FROM periodos per
          JOIN hires h
            ON h.start_d <= per.period_end
           AND COALESCE(h.end_d, DATE '9999-12-31') >= per.period_end
           AND (%(segmento)s = 'Total' OR h.model = %(segmento)s)
        ),
        clientes_con_mas_de_1 AS (
          SELECT periodo, account_id
          FROM activos
          GROUP BY 1, 2
          HAVING COUNT(DISTINCT candidate_id) > 1
        )
        SELECT
          a.periodo,
          a.client_name,
          a.candidate_name
        FROM activos a
        JOIN clientes_con_mas_de_1 x
          ON x.periodo = a.periodo
         AND x.account_id = a.account_id
        ORDER BY a.periodo, a.client_name, a.candidate_name;
    """

    return sql, {"corte": corte, "segmento": segmento}


DATASET = {
    "key": "clients_multi_30d_detail",
    "label": "% Clientes con > 1 candidato — Detalle ventana 30 días",
    "dimensions": [
        {"key": "periodo", "label": "Período", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
