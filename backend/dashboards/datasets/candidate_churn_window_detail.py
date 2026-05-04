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
    window_days = 180 if meses == 6 else 90
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - make_interval(days => %(window_days)s - 1))::date AS win_ini,
            %(window_days)s AS window_days
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
        detalle AS (
          SELECT
            v.corte_d,
            v.win_ini,
            h.candidate_name,
            h.account_name,
            h.start_d,
            h.end_d,
            CASE
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.corte_d
                AND h.buyout_d IS NOT NULL
                AND h.buyout_d >= DATE_TRUNC('month', h.end_d)
                THEN 'Baja - Buyout (Conversion)'
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.corte_d
                THEN 'Baja - Real'
              ELSE NULL
            END AS baja_tipo
          FROM ventana v
          JOIN ho h
            ON h.start_d BETWEEN v.win_ini AND v.corte_d
        )
        SELECT
          TO_CHAR(corte_d, 'YYYY-MM-DD') AS corte_d,
          TO_CHAR(win_ini, 'YYYY-MM-DD') AS win_ini,
          candidate_name,
          account_name,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_d,
          TO_CHAR(end_d,   'YYYY-MM-DD') AS end_d,
          baja_tipo
        FROM detalle
        ORDER BY
          account_name,
          candidate_name,
          start_d;
    """

    return sql, {"corte": corte, "window_days": window_days}


DATASET = {
    "key": "candidate_churn_window_detail",
    "label": "Churn de candidatos (Staffing) — Detalle 90/180 días",
    "dimensions": [
        {"key": "corte_d", "label": "Corte", "type": "date"},
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
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
