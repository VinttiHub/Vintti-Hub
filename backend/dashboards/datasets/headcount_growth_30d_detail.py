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
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    segmento = _norm_segmento(filters.get("segmento") or filters.get("model"))

    sql = """
        WITH cutoff_filtrado AS (
          SELECT %(corte)s::date AS cutoff
          WHERE (%(desde)s::date IS NULL OR %(corte)s::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR %(corte)s::date <= %(hasta)s::date)
        ),
        ventanas AS (
          SELECT
            cf.cutoff,
            (cf.cutoff - INTERVAL '30 day')::date AS win_ini,
            cf.cutoff::date                       AS win_fin,
            (cf.cutoff - INTERVAL '60 day')::date AS prev_ini,
            (cf.cutoff - INTERVAL '30 day')::date AS prev_fin
          FROM cutoff_filtrado cf
        ),
        hires AS (
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
        activos_ventana AS (
          SELECT DISTINCT
            v.cutoff,
            h.account_id,
            h.candidate_id
          FROM ventanas v
          JOIN hires h ON TRUE
          WHERE h.start_d <= v.win_fin
            AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_ini
            AND (%(segmento)s = 'Total' OR h.model = %(segmento)s)
        ),
        activos_prev AS (
          SELECT DISTINCT
            v.cutoff,
            h.account_id,
            h.candidate_id
          FROM ventanas v
          JOIN hires h ON TRUE
          WHERE h.start_d <= v.prev_fin
            AND COALESCE(h.end_d, DATE '9999-12-31') >= v.prev_ini
            AND (%(segmento)s = 'Total' OR h.model = %(segmento)s)
        ),
        conteo AS (
          SELECT
            COALESCE(m.cutoff, pv.cutoff)         AS cutoff,
            COALESCE(m.account_id, pv.account_id) AS account_id,
            COUNT(DISTINCT pv.candidate_id)::int  AS candidatos_prev,
            COUNT(DISTINCT m.candidate_id)::int   AS candidatos_activos
          FROM activos_ventana m
          FULL JOIN activos_prev pv
            ON pv.cutoff = m.cutoff
           AND pv.account_id = m.account_id
          GROUP BY 1, 2
        )
        SELECT
          TO_CHAR(c.cutoff, 'YYYY-MM-DD')                       AS cutoff,
          a.client_name,
          c.candidatos_prev,
          c.candidatos_activos,
          (c.candidatos_activos - c.candidatos_prev)::int       AS aumento,
          (c.candidatos_prev = 1 AND c.candidatos_activos >= 2) AS paso_1_a_2_o_mas
        FROM conteo c
        JOIN account a ON a.account_id = c.account_id
        WHERE c.candidatos_activos >= 1
          AND c.candidatos_prev IS NOT NULL
          AND c.candidatos_activos > c.candidatos_prev
        ORDER BY
          c.cutoff DESC,
          aumento DESC,
          c.candidatos_activos DESC,
          a.client_name;
    """

    return sql, {"corte": corte, "desde": desde, "hasta": hasta, "segmento": segmento}


DATASET = {
    "key": "headcount_growth_30d_detail",
    "label": "Headcount Growth — Detalle ventana 30 días",
    "dimensions": [
        {"key": "cutoff", "label": "Cutoff", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "paso_1_a_2_o_mas", "label": "1→2+", "type": "string"},
    ],
    "measures": [
        {"key": "candidatos_prev", "label": "Prev", "type": "number"},
        {"key": "candidatos_activos", "label": "Activos", "type": "number"},
        {"key": "aumento", "label": "Aumento", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
