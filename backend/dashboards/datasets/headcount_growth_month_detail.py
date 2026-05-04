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
    mes = (
        _parse_date(filters.get("fecha_headcount"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    segmento = _norm_segmento(filters.get("segmento") or filters.get("model"))

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
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
        meses_filtrado AS (
          SELECT mo.mes_pick AS mes_sel
          FROM mes_objetivo mo
          WHERE (%(desde)s::date IS NULL OR mo.mes_pick >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR mo.mes_pick <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        params AS (
          SELECT
            mf.mes_sel,
            (mf.mes_sel - interval '1 month')::date AS mes_prev
          FROM meses_filtrado mf
        ),
        activos_mes AS (
          SELECT DISTINCT
            p.mes_sel,
            h.account_id,
            h.candidate_id
          FROM params p
          JOIN hires h ON TRUE
          WHERE h.start_d <= (p.mes_sel + interval '1 month - 1 day')::date
            AND COALESCE(h.end_d, DATE '9999-12-31') >= p.mes_sel
            AND (%(segmento)s = 'Total' OR h.model = %(segmento)s)
        ),
        activos_prev AS (
          SELECT DISTINCT
            p.mes_sel,
            h.account_id,
            h.candidate_id
          FROM params p
          JOIN hires h ON TRUE
          WHERE h.start_d <= (p.mes_prev + interval '1 month - 1 day')::date
            AND COALESCE(h.end_d, DATE '9999-12-31') >= p.mes_prev
            AND (%(segmento)s = 'Total' OR h.model = %(segmento)s)
        ),
        conteo AS (
          SELECT
            COALESCE(m.mes_sel, pv.mes_sel)         AS mes,
            COALESCE(m.account_id, pv.account_id)   AS account_id,
            COUNT(DISTINCT pv.candidate_id)::int    AS candidatos_prev,
            COUNT(DISTINCT m.candidate_id)::int     AS candidatos_activos
          FROM activos_mes m
          FULL JOIN activos_prev pv
            ON pv.mes_sel = m.mes_sel
           AND pv.account_id = m.account_id
          GROUP BY 1, 2
        )
        SELECT
          TO_CHAR(c.mes, 'YYYY-MM-DD')                              AS mes,
          a.client_name,
          c.candidatos_prev,
          c.candidatos_activos,
          (c.candidatos_activos - c.candidatos_prev)::int           AS aumento,
          (c.candidatos_prev = 1 AND c.candidatos_activos >= 2)     AS paso_1_a_2_o_mas
        FROM conteo c
        JOIN account a ON a.account_id = c.account_id
        WHERE c.candidatos_activos >= 1
          AND c.candidatos_prev IS NOT NULL
          AND c.candidatos_activos > c.candidatos_prev
        ORDER BY
          c.mes DESC,
          aumento DESC,
          c.candidatos_activos DESC,
          a.client_name;
    """

    return sql, {"mes": mes, "desde": desde, "hasta": hasta, "segmento": segmento}


DATASET = {
    "key": "headcount_growth_month_detail",
    "label": "Headcount Growth — Detalle del mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
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
