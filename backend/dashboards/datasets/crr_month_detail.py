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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    mes = (
        _parse_date(filters.get("fecha_crr"))
        or _parse_date(filters.get("mes_click"))
        or _parse_date(filters.get("mes"))
    )

    sql = """
        WITH mes_objetivo AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes
        ),
        ventana_mes AS (
          SELECT
            mo.mes,
            CASE
              WHEN mo.mes = DATE_TRUNC('month', CURRENT_DATE)::date
                THEN CURRENT_DATE::date
              ELSE (mo.mes + interval '1 month - 1 day')::date
            END AS mes_fin
          FROM mes_objetivo mo
        ),
        hires AS (
          SELECT
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE o.opp_model = 'Staffing'
            AND ho.account_id IS NOT NULL
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(ho.start_date::text, '') IS NOT NULL
            )
        ),
        activos_inicio AS (
          SELECT DISTINCT
            v.mes,
            v.mes_fin,
            h.account_id
          FROM ventana_mes v
          JOIN hires h
            ON h.start_d <= v.mes
           AND COALESCE(h.end_d, DATE '9999-12-31') >= v.mes
        ),
        activos_fin AS (
          SELECT DISTINCT
            v.mes,
            v.mes_fin,
            h.account_id
          FROM ventana_mes v
          JOIN hires h
            ON h.start_d <= v.mes_fin
           AND COALESCE(h.end_d, DATE '9999-12-31') >= v.mes_fin
        ),
        full_set AS (
          SELECT mes, mes_fin, account_id FROM activos_inicio
          UNION
          SELECT mes, mes_fin, account_id FROM activos_fin
        ),
        clasif AS (
          SELECT
            fs.mes,
            fs.mes_fin,
            fs.account_id,
            CASE
              WHEN ai.account_id IS NOT NULL AND af.account_id IS NOT NULL THEN 'retenido'
              WHEN ai.account_id IS NOT NULL AND af.account_id IS NULL     THEN 'churn_inicio'
              WHEN ai.account_id IS NULL     AND af.account_id IS NOT NULL THEN 'nuevo_en_mes'
            END AS tipo
          FROM full_set fs
          LEFT JOIN activos_inicio ai
            ON ai.mes = fs.mes AND ai.account_id = fs.account_id
          LEFT JOIN activos_fin af
            ON af.mes = fs.mes AND af.account_id = fs.account_id
        )
        SELECT
          TO_CHAR(c.mes, 'YYYY-MM-DD')     AS mes,
          TO_CHAR(c.mes_fin, 'YYYY-MM-DD') AS mes_fin,
          c.tipo,
          c.account_id,
          COALESCE(a.client_name, '')      AS client_name
        FROM clasif c
        LEFT JOIN account a ON a.account_id = c.account_id
        ORDER BY
          CASE c.tipo
            WHEN 'churn_inicio' THEN 1
            WHEN 'nuevo_en_mes' THEN 2
            WHEN 'retenido'     THEN 3
          END,
          a.client_name;
    """

    return sql, {"mes": mes}


DATASET = {
    "key": "crr_month_detail",
    "label": "CRR mensual — Detalle del mes",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "mes_fin", "label": "Mes fin", "type": "date"},
        {"key": "tipo", "label": "Tipo", "type": "string"},
        {"key": "account_id", "label": "Account ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
