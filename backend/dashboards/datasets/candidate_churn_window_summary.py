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
              h.account_id,
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
          ) x
          WHERE start_d IS NOT NULL
        ),
        detalle AS (
          SELECT
            v.corte_d,
            h.candidate_id,
            h.end_d,
            h.buyout_d,
            CASE
              WHEN h.end_d IS NOT NULL AND h.end_d <= v.corte_d THEN 'BAJA'
              WHEN COALESCE(h.end_d, DATE '9999-12-31') > v.corte_d THEN 'ACTIVO'
              ELSE 'FUERA'
            END AS estado_en_corte,
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
          JOIN ho h
            ON h.start_d BETWEEN v.win_ini AND v.corte_d
        ),
        totals AS (
          SELECT
            COUNT(DISTINCT candidate_id)::int                                    AS starts,
            COUNT(*) FILTER (WHERE estado_en_corte = 'BAJA')::int                AS bajas,
            COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::int                 AS bajas_real,
            COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_BUYOUT')::int               AS bajas_buyout,
            COUNT(*) FILTER (WHERE estado_en_corte = 'ACTIVO')::int              AS activos_al_corte
          FROM detalle
        )
        SELECT
          starts                                                                 AS candidatos,
          bajas                                                                  AS bajas,
          bajas_real                                                             AS bajas_real,
          bajas_buyout                                                           AS bajas_buyout,
          activos_al_corte                                                       AS activos_al_corte,
          ROUND(100.0 * bajas::numeric        / NULLIF(starts, 0), 2)::float     AS churn_pct,
          ROUND(100.0 * bajas_real::numeric   / NULLIF(starts, 0), 2)::float     AS churn_real_pct,
          ROUND(100.0 * bajas_buyout::numeric / NULLIF(starts, 0), 2)::float     AS buyout_pct
        FROM totals;
    """

    return sql, {"corte": corte, "window_days": window_days}


DATASET = {
    "key": "candidate_churn_window_summary",
    "label": "Churn de candidatos (Staffing) — Cohorte 90/180 días",
    "dimensions": [],
    "measures": [
        {"key": "candidatos", "label": "Candidatos", "type": "number"},
        {"key": "bajas", "label": "Bajas total", "type": "number"},
        {"key": "bajas_real", "label": "Bajas Staffing", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas Buyout", "type": "number"},
        {"key": "activos_al_corte", "label": "Activos al corte", "type": "number"},
        {"key": "churn_pct", "label": "Churn total %", "type": "percent"},
        {"key": "churn_real_pct", "label": "Churn Staffing %", "type": "percent"},
        {"key": "buyout_pct", "label": "Churn Buyout %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
