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
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM hires),
            COALESCE((SELECT MAX(end_d) FROM hires), CURRENT_DATE),
            interval '1 month'
          ) gs
        ),
        meses_filtrado AS (
          SELECT *
          FROM meses m
          WHERE (%(desde)s::date IS NULL OR m.mes >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR m.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        activos_mes AS (
          SELECT DISTINCT
            m.mes,
            h.account_id,
            h.candidate_id
          FROM meses_filtrado m
          JOIN hires h
            ON h.start_d <= (m.mes + interval '1 month - 1 day')::date
           AND COALESCE(h.end_d, DATE '9999-12-31') >= m.mes
           AND (%(segmento)s = 'Total' OR h.model = %(segmento)s)
        ),
        candidatos_por_cliente_mes AS (
          SELECT mes, account_id, COUNT(DISTINCT candidate_id) AS candidatos_activos
          FROM activos_mes
          GROUP BY 1, 2
        ),
        cuentas AS (SELECT DISTINCT account_id FROM candidatos_por_cliente_mes),
        serie AS (
          SELECT m.mes, c.account_id
          FROM meses_filtrado m
          CROSS JOIN cuentas c
        ),
        panel AS (
          SELECT
            s.mes,
            s.account_id,
            COALESCE(c.candidatos_activos, 0) AS candidatos_activos
          FROM serie s
          LEFT JOIN candidatos_por_cliente_mes c
            ON c.mes = s.mes AND c.account_id = s.account_id
        ),
        comparado AS (
          SELECT
            mes,
            account_id,
            candidatos_activos,
            LAG(candidatos_activos) OVER (PARTITION BY account_id ORDER BY mes) AS candidatos_prev
          FROM panel
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM-DD')                                                        AS mes,
          COUNT(*) FILTER (WHERE candidatos_activos >= 1)::int                              AS clientes_activos,
          COUNT(*) FILTER (
            WHERE candidatos_activos >= 1
              AND candidatos_prev IS NOT NULL
              AND candidatos_activos > candidatos_prev
          )::int                                                                            AS clientes_que_aumentaron,
          COUNT(*) FILTER (
            WHERE candidatos_activos >= 2
              AND candidatos_prev = 1
          )::int                                                                            AS pasaron_de_1_a_2_o_mas,
          ROUND(
            100.0 * COUNT(*) FILTER (
              WHERE candidatos_activos >= 1
                AND candidatos_prev IS NOT NULL
                AND candidatos_activos > candidatos_prev
            )
            / NULLIF(COUNT(*) FILTER (WHERE candidatos_activos >= 1), 0)
          , 2)::float                                                                       AS pct_activos_que_aumentaron,
          ROUND(
            100.0 * COUNT(*) FILTER (
              WHERE candidatos_activos >= 2
                AND candidatos_prev = 1
            )
            / NULLIF(COUNT(*) FILTER (WHERE candidatos_activos >= 1), 0)
          , 2)::float                                                                       AS pct_activos_paso_1_a_2_o_mas
        FROM comparado
        GROUP BY mes
        ORDER BY mes;
    """

    return sql, {"desde": desde, "hasta": hasta, "segmento": segmento}


DATASET = {
    "key": "headcount_growth_history",
    "label": "Headcount Growth — Histórico mensual",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
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
