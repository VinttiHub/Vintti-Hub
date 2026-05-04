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


def _parse_meses(value) -> int:
    try:
        n = int(str(value).strip())
        if n in (3, 6):
            return n
    except (TypeError, ValueError):
        pass
    return 3


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    meses = _parse_meses(filters.get("meses"))
    mes = (
        _parse_date(filters.get("fecha_candidate_window_churn"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_pick
        ),
        ho AS (
          SELECT *
          FROM (
            SELECT
              h.candidate_id,
              COALESCE(c.name, '')        AS candidate_name,
              h.account_id,
              COALESCE(a.client_name, '') AS account_name,
              NULLIF(h.start_date::text, '')::date AS start_d,
              CASE
                WHEN h.end_date IS NULL OR h.end_date::text = '' THEN NULL
                ELSE h.end_date::date
              END AS end_d,
              CASE
                WHEN NULLIF(TRIM(h.buyout_daterange), '') IS NOT NULL
                  THEN TO_DATE(TRIM(h.buyout_daterange) || '-01', 'YYYY-MM-DD')
                ELSE NULL
              END AS buyout_d
            FROM hire_opportunity h
            JOIN opportunity o ON o.opportunity_id = h.opportunity_id
            LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
            LEFT JOIN account    a ON a.account_id   = h.account_id
            WHERE o.opp_model = 'Staffing'
          ) x
          WHERE start_d IS NOT NULL
        ),
        meses_cal AS (
          SELECT mo.mes_pick AS mes
          FROM mes_objetivo mo
          WHERE (%(desde)s::date IS NULL OR mo.mes_pick >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR mo.mes_pick <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        ventana AS (
          SELECT
            m.mes,
            (m.mes - ((%(meses)s - 1) || ' months')::interval)::date AS win_ini,
            (m.mes + interval '1 month - 1 day')::date              AS m_fin
          FROM meses_cal m
        ),
        detalle AS (
          SELECT
            v.mes,
            v.win_ini,
            v.m_fin,
            h.candidate_name,
            h.account_name,
            h.start_d,
            h.end_d,
            CASE
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.m_fin
                AND h.buyout_d IS NOT NULL
                AND h.buyout_d >= DATE_TRUNC('month', h.end_d)
                THEN 'Baja - Buyout (Conversion)'
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.m_fin
                THEN 'Baja - Real'
              ELSE NULL
            END AS baja_tipo
          FROM ventana v
          JOIN ho h
            ON h.start_d BETWEEN v.win_ini AND v.m_fin
        )
        SELECT
          TO_CHAR(d.win_ini, 'YYYY-MM-DD')                AS win_ini,
          TO_CHAR(d.m_fin,   'YYYY-MM-DD')                AS m_fin,
          d.candidate_name,
          d.account_name,
          TO_CHAR(d.start_d, 'YYYY-MM-DD')                AS start_d,
          TO_CHAR(d.end_d,   'YYYY-MM-DD')                AS end_d,
          d.baja_tipo
        FROM detalle d
        ORDER BY
          d.mes,
          d.account_name,
          d.candidate_name;
    """

    return sql, {"meses": meses, "mes": mes, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "candidate_churn_window_month_detail",
    "label": "Churn 3/6 meses (rolling) — Detalle del mes",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "m_fin", "label": "Fin ventana", "type": "date"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "account_name", "label": "Cliente", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
        {"key": "end_d", "label": "End", "type": "date"},
        {"key": "baja_tipo", "label": "Tipo de baja", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
