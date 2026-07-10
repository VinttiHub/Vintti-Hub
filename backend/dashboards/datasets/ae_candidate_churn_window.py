from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


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
        or today_ar()
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
              CASE
                WHEN h.carga_active IS NOT NULL THEN h.carga_active::date
                ELSE NULLIF(h.start_date::text, '')::date
              END AS start_d,
              CASE
                WHEN h.carga_inactive IS NOT NULL THEN h.carga_inactive::date
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
            LEFT JOIN account a ON a.account_id = h.account_id
            WHERE o.opp_model = 'Staffing'
              AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
              AND COALESCE(a.vintti_internal, FALSE) = FALSE
          ) x
          WHERE start_d IS NOT NULL
        ),
        detalle AS (
          SELECT
            h.candidate_id,
            CASE WHEN h.end_d IS NOT NULL AND h.end_d <= v.corte_d THEN 'BAJA' ELSE 'ACTIVO' END AS estado,
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
        ),
        -- R7: roll-up a grano CANDIDATO. Antes `candidatos` contaba filas-hire
        -- (un candidato con 2 hires contaba 2), pese a que el label dice Candidatos.
        per_candidate AS (
          SELECT
            candidate_id,
            BOOL_OR(estado = 'ACTIVO')         AS is_active,
            BOOL_OR(baja_tipo = 'BAJA_REAL')   AS any_real,
            BOOL_OR(baja_tipo = 'BAJA_BUYOUT') AS any_buyout
          FROM detalle
          GROUP BY candidate_id
        ),
        cand_state AS (
          SELECT
            CASE
              WHEN is_active  THEN NULL
              WHEN any_real   THEN 'BAJA_REAL'
              WHEN any_buyout THEN 'BAJA_BUYOUT'
              ELSE NULL
            END AS baja_tipo
          FROM per_candidate
        )
        SELECT
          COUNT(*)::int                                            AS candidatos,
          COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::int     AS bajas_real,
          COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_BUYOUT')::int   AS bajas_buyout,
          ROUND(100.0 * COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::numeric
                / NULLIF(COUNT(*), 0), 1)::float                   AS churn_real_pct,
          ROUND(100.0 - 100.0 * COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::numeric
                / NULLIF(COUNT(*), 0), 1)::float                   AS retention_pct
        FROM cand_state;
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
