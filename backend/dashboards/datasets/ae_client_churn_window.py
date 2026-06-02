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

    # M1/M3 churn de clientes (Staffing) — solo AE (Mariano+Bahía por opp_sales_lead).
    # Cohorte rolling: cuentas cuyo PRIMER hire arrancó en los últimos window_days.
    # Churn = la cuenta no tiene ningún contractor activo al corte (todos terminaron).
    # churn_real_pct excluye buyouts (la última baja fue conversión).
    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - make_interval(days => %(window_days)s - 1))::date AS win_ini
        ),
        hires AS (
          SELECT
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
              ELSE ho.end_date::date
            END AS end_d,
            CASE
              WHEN NULLIF(TRIM(ho.buyout_daterange::text), '') IS NOT NULL
                THEN TO_DATE(NULLIF(TRIM(ho.buyout_daterange::text), '') || '-01', 'YYYY-MM-DD')
              ELSE NULL
            END AS buyout_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
        ),
        acct AS (
          SELECT
            account_id,
            MIN(start_d) FILTER (WHERE start_d IS NOT NULL) AS first_start,
            MAX(end_d)   AS last_end,
            MAX(buyout_d) AS buyout_d,
            BOOL_OR(COALESCE(end_d, DATE '9999-12-31') >= (SELECT corte_d FROM ventana)) AS has_active
          FROM hires
          GROUP BY account_id
        ),
        cohort AS (
          SELECT a.*
          FROM acct a
          CROSS JOIN ventana v
          WHERE a.first_start BETWEEN v.win_ini AND v.corte_d
        ),
        classified AS (
          SELECT
            account_id,
            CASE
              WHEN has_active THEN NULL
              WHEN buyout_d IS NOT NULL AND last_end IS NOT NULL
                   AND buyout_d >= DATE_TRUNC('month', last_end) THEN 'BAJA_BUYOUT'
              ELSE 'BAJA_REAL'
            END AS baja_tipo
          FROM cohort
        )
        SELECT
          COUNT(*)::int                                          AS clientes,
          COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::int   AS bajas_real,
          COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_BUYOUT')::int AS bajas_buyout,
          ROUND(100.0 * COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::numeric
                / NULLIF(COUNT(*), 0), 1)::float                 AS churn_real_pct,
          ROUND(100.0 - 100.0 * COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::numeric
                / NULLIF(COUNT(*), 0), 1)::float                 AS retention_pct
        FROM classified;
    """

    return sql, {"corte": corte, "window_days": window_days}


DATASET = {
    "key": "ae_client_churn_window",
    "label": "M1/M3 Churn de clientes — AE (Mariano+Bahía)",
    "dimensions": [],
    "measures": [
        {"key": "clientes", "label": "Clientes (cohorte)", "type": "number"},
        {"key": "bajas_real", "label": "Bajas reales", "type": "number"},
        {"key": "bajas_buyout", "label": "Bajas buyout", "type": "number"},
        {"key": "churn_real_pct", "label": "Churn real %", "type": "percent"},
        {"key": "retention_pct", "label": "Retención %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
