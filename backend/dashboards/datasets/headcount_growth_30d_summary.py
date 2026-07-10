from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds


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
        or today_ar()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    modelo = _norm_modelo(filters.get("modelo") or filters.get("model") or filters.get("segmento"))
    win_ini, win_fin = window_bounds(filters)

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
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
            AND ho.start_date IS NOT NULL
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        cutoff_filtrado AS (
          SELECT %(win_fin)s::date AS cutoff
        ),
        ventanas AS (
          SELECT
            cf.cutoff,
            %(win_ini)s::date AS win_ini,
            cf.cutoff::date                       AS win_fin,
            -- Si la ventana es un MES calendario completo (filtro Mes), el período
            -- anterior es el mes calendario previo → coincide con el LAG mensual de
            -- la gráfica headcount_growth_history. Si no (default 30d rolling o rango
            -- desde/hasta), se usa la ventana de 30 días inmediatamente anterior.
            CASE WHEN %(win_ini)s::date = DATE_TRUNC('month', cf.cutoff)::date
                  AND cf.cutoff::date = (DATE_TRUNC('month', cf.cutoff) + INTERVAL '1 month - 1 day')::date
                 THEN (DATE_TRUNC('month', cf.cutoff)::date - INTERVAL '1 month')::date
                 ELSE (cf.cutoff - INTERVAL '60 day')::date END AS prev_ini,
            CASE WHEN %(win_ini)s::date = DATE_TRUNC('month', cf.cutoff)::date
                  AND cf.cutoff::date = (DATE_TRUNC('month', cf.cutoff) + INTERVAL '1 month - 1 day')::date
                 THEN (DATE_TRUNC('month', cf.cutoff)::date - INTERVAL '1 day')::date
                 ELSE (cf.cutoff - INTERVAL '29 day')::date END AS prev_fin
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
            AND (%(modelo)s = 'Total' OR h.model = %(modelo)s)
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
            AND (%(modelo)s = 'Total' OR h.model = %(modelo)s)
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
          TO_CHAR(
            CASE WHEN %(win_ini)s::date = DATE_TRUNC('month', p.cutoff)::date
                  AND p.cutoff = (DATE_TRUNC('month', p.cutoff) + INTERVAL '1 month - 1 day')::date
                 THEN (DATE_TRUNC('month', p.cutoff)::date - INTERVAL '1 day')::date
                 ELSE (p.cutoff - INTERVAL '29 day')::date END,
            'YYYY-MM-DD')                                                                       AS cutoff_prev,
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

    return sql, {"corte": corte, "desde": desde, "hasta": hasta, "modelo": modelo, "win_ini": win_ini, "win_fin": win_fin}


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
