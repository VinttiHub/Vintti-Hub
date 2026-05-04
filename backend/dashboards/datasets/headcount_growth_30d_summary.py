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
    segmento = _norm_segmento(filters.get("segmento"))

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
        cutoff_filtrado AS (
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
        activos_win AS (
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
        candidatos_win AS (
          SELECT cutoff, account_id, COUNT(DISTINCT candidate_id) AS candidatos_activos
          FROM activos_win GROUP BY 1, 2
        ),
        candidatos_prev AS (
          SELECT cutoff, account_id, COUNT(DISTINCT candidate_id) AS candidatos_prev
          FROM activos_prev GROUP BY 1, 2
        ),
        cuentas AS (SELECT DISTINCT account_id FROM hires),
        panel AS (
          SELECT
            v.cutoff,
            c.account_id,
            COALESCE(w.candidatos_activos, 0) AS candidatos_activos,
            COALESCE(p.candidatos_prev, 0)    AS candidatos_prev
          FROM ventanas v
          CROSS JOIN cuentas c
          LEFT JOIN candidatos_win  w ON w.cutoff = v.cutoff AND w.account_id = c.account_id
          LEFT JOIN candidatos_prev p ON p.cutoff = v.cutoff AND p.account_id = c.account_id
        )
        SELECT
          TO_CHAR(p.cutoff, 'YYYY-MM-DD')                                                   AS cutoff,
          TO_CHAR((p.cutoff - INTERVAL '30 day')::date, 'YYYY-MM-DD')                       AS cutoff_prev,
          COUNT(*) FILTER (WHERE p.candidatos_activos >= 1)::int                            AS clientes_activos,
          COUNT(*) FILTER (
            WHERE p.candidatos_activos >= 1
              AND p.candidatos_prev IS NOT NULL
              AND p.candidatos_activos > p.candidatos_prev
          )::int                                                                            AS clientes_que_aumentaron,
          COUNT(*) FILTER (
            WHERE p.candidatos_activos >= 2
              AND p.candidatos_prev = 1
          )::int                                                                            AS pasaron_de_1_a_2_o_mas,
          ROUND(
            100.0 * COUNT(*) FILTER (
              WHERE p.candidatos_activos >= 1
                AND p.candidatos_prev IS NOT NULL
                AND p.candidatos_activos > p.candidatos_prev
            )
            / NULLIF(COUNT(*) FILTER (WHERE p.candidatos_activos >= 1), 0)
          , 2)::float                                                                       AS pct_activos_que_aumentaron,
          ROUND(
            100.0 * COUNT(*) FILTER (
              WHERE p.candidatos_activos >= 2
                AND p.candidatos_prev = 1
            )
            / NULLIF(COUNT(*) FILTER (WHERE p.candidatos_activos >= 1), 0)
          , 2)::float                                                                       AS pct_activos_paso_1_a_2_o_mas
        FROM panel p
        GROUP BY p.cutoff
        ORDER BY p.cutoff;
    """

    return sql, {"corte": corte, "desde": desde, "hasta": hasta, "segmento": segmento}


DATASET = {
    "key": "headcount_growth_30d_summary",
    "label": "Headcount Growth — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "clientes_activos", "label": "Clientes activos", "type": "number"},
        {"key": "clientes_que_aumentaron", "label": "Aumentaron", "type": "number"},
        {"key": "pasaron_de_1_a_2_o_mas", "label": "Pasaron 1→2+", "type": "number"},
        {"key": "pct_activos_que_aumentaron", "label": "% aumentaron", "type": "percent"},
        {"key": "pct_activos_paso_1_a_2_o_mas", "label": "% 1→2+", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
