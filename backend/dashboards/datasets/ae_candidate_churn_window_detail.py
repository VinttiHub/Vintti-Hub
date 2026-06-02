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
        if n in (1, 3):
            return n
    except (TypeError, ValueError):
        pass
    return 1


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    meses = _parse_meses(filters.get("meses"))
    window_days = 90 if meses == 3 else 30
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )

    # Detalle de la cohorte M1/M3 de candidatos (AE M+B). Misma lógica que
    # ae_candidate_churn_window, pero una fila por hire con su estado al corte.
    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - make_interval(days => %(window_days)s - 1))::date AS win_ini
        ),
        ho AS (
          SELECT *
          FROM (
            SELECT
              COALESCE(c.name, '')        AS candidate_name,
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
              AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
          ) x
          WHERE start_d IS NOT NULL
        )
        SELECT
          h.candidate_name,
          h.account_name,
          TO_CHAR(h.start_d, 'YYYY-MM-DD') AS start_d,
          TO_CHAR(h.end_d,   'YYYY-MM-DD') AS end_d,
          CASE
            WHEN h.end_d IS NOT NULL AND h.end_d <= v.corte_d
                 AND h.buyout_d IS NOT NULL AND h.buyout_d >= DATE_TRUNC('month', h.end_d)
              THEN 'Baja buyout'
            WHEN h.end_d IS NOT NULL AND h.end_d <= v.corte_d
              THEN 'Baja real'
            ELSE 'Activo'
          END AS estado
        FROM ventana v
        JOIN ho h ON h.start_d BETWEEN v.win_ini AND v.corte_d
        ORDER BY estado, h.account_name, h.candidate_name;
    """

    return sql, {"corte": corte, "window_days": window_days}


DATASET = {
    "key": "ae_candidate_churn_window_detail",
    "label": "M1/M3 Churn candidatos — Detalle cohorte (AE)",
    "dimensions": [
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "account_name", "label": "Cliente", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
        {"key": "end_d", "label": "End", "type": "date"},
        {"key": "estado", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
