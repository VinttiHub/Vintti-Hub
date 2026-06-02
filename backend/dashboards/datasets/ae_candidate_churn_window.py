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

    # M1/M3 churn de candidatos (Staffing) — solo AE (Mariano+Bahía por opp_sales_lead).
    # Cohorte rolling: hires que arrancaron en los últimos window_days; churn = end_d <= corte.
    # churn_real_pct excluye buyouts (conversiones). Mismo criterio que candidate_churn_window_summary.
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
              h.candidate_id,
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
            WHERE o.opp_model = 'Staffing'
              AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
          ) x
          WHERE start_d IS NOT NULL
        ),
        detalle AS (
          SELECT
            CASE
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.corte_d
                AND h.buyout_d IS NOT NULL
                AND h.buyout_d >= DATE_TRUNC('month', h.end_d)
                THEN 'BAJA_BUYOUT'
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.corte_d
                THEN 'BAJA_REAL'
              ELSE NULL
            END AS baja_tipo
          FROM ventana v
          JOIN ho h ON h.start_d BETWEEN v.win_ini AND v.corte_d
        )
        SELECT
          COUNT(*)::int                                            AS candidatos,
          COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::int     AS bajas_real,
          COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_BUYOUT')::int   AS bajas_buyout,
          ROUND(100.0 * COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::numeric
                / NULLIF(COUNT(*), 0), 1)::float                   AS churn_real_pct,
          ROUND(100.0 - 100.0 * COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::numeric
                / NULLIF(COUNT(*), 0), 1)::float                   AS retention_pct
        FROM detalle;
    """

    return sql, {"corte": corte, "window_days": window_days}


DATASET = {
    "key": "ae_candidate_churn_window",
    "label": "M1/M3 Churn de candidatos — AE (Mariano+Bahía)",
    "dimensions": [],
    "measures": [
        {"key": "candidatos", "label": "Candidatos (cohorte)", "type": "number"},
        {"key": "bajas_real", "label": "Bajas reales", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas buyout", "type": "number"},
        {"key": "churn_real_pct", "label": "Churn real %", "type": "percent"},
        {"key": "retention_pct", "label": "Retención %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
