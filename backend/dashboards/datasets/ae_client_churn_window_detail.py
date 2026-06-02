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

    # Detalle de la cohorte M1/M3 de clientes (AE M+B). Una fila por cuenta cuyo
    # primer hire arrancó en la ventana, con su estado al corte.
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
        )
        SELECT
          COALESCE(ac.client_name, '') AS client_name,
          TO_CHAR(a.first_start, 'YYYY-MM-DD') AS first_start,
          -- Solo tiene sentido como "fecha de churn" si la cuenta NO tiene activos.
          CASE WHEN a.has_active THEN NULL ELSE TO_CHAR(a.last_end, 'YYYY-MM-DD') END AS last_end,
          CASE
            WHEN a.has_active THEN 'Activo'
            WHEN a.buyout_d IS NOT NULL AND a.last_end IS NOT NULL
                 AND a.buyout_d >= DATE_TRUNC('month', a.last_end) THEN 'Baja buyout'
            ELSE 'Baja real'
          END AS estado
        FROM acct a
        CROSS JOIN ventana v
        LEFT JOIN account ac ON ac.account_id = a.account_id
        WHERE a.first_start BETWEEN v.win_ini AND v.corte_d
        ORDER BY estado, client_name;
    """

    return sql, {"corte": corte, "window_days": window_days}


DATASET = {
    "key": "ae_client_churn_window_detail",
    "label": "M1/M3 Churn clientes — Detalle cohorte (AE)",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "first_start", "label": "Primer hire", "type": "date"},
        {"key": "last_end", "label": "Última baja", "type": "date"},
        {"key": "estado", "label": "Estado", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
