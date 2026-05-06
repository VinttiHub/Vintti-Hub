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
    mes = (
        _parse_date(filters.get("fecha_clients_multi"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )
    modelo = _norm_modelo(filters.get("modelo") or filters.get("model") or filters.get("segmento"))

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
        meses_filtrado AS (
          SELECT mo.mes_pick AS mes FROM mes_objetivo mo
        ),
        activos_mes AS (
          SELECT DISTINCT
            m.mes,
            h.account_id,
            h.client_name,
            h.candidate_id,
            h.candidate_name
          FROM meses_filtrado m
          JOIN hires h
            ON h.start_d <= (m.mes + interval '1 month - 1 day')::date
           AND COALESCE(h.end_d, DATE '9999-12-31') >= (m.mes + interval '1 month - 1 day')::date
           AND (%(modelo)s = 'Total' OR h.model = %(modelo)s)
        ),
        clientes_con_mas_de_1 AS (
          SELECT mes, account_id
          FROM activos_mes
          GROUP BY 1, 2
          HAVING COUNT(DISTINCT candidate_id) > 1
        )
        SELECT
          TO_CHAR(a.mes, 'YYYY-MM') AS mes,
          a.client_name,
          a.candidate_name
        FROM activos_mes a
        JOIN clientes_con_mas_de_1 x
          ON x.mes = a.mes
         AND x.account_id = a.account_id
        ORDER BY a.mes, a.client_name, a.candidate_name;
    """

    return sql, {"mes": mes, "modelo": modelo}


DATASET = {
    "key": "clients_multi_month_detail",
    "label": "% Clientes con > 1 candidato — Detalle del mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
