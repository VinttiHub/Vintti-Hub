from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds


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
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )
    modelo = _norm_modelo(filters.get("modelo") or filters.get("model") or filters.get("segmento"))

    # Active-clients logic mirrors acpa_history.py so the denominator
    # (`clientes_activos`) matches the "Active clients" tile exactly:
    #   - Uses COALESCE(carga_active, start_date) and COALESCE(carga_inactive, end_date)
    #   - Includes buyouts as Recruiting account rows (their candidate_id is NULL
    #     so they don't add to "mayor_a_1" but DO count toward "clientes_activos")
    #   - For the current month, falls back to ho.status='active' when dates fall short
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH hire_rows AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            LOWER(TRIM(COALESCE(ho.status, ''))) AS status,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '') IS NULL THEN NULL
              ELSE NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '')::date
            END AS end_d,
            LOWER(TRIM(o.opp_model)) AS model
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE ho.account_id IS NOT NULL
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        buyout_rows AS (
          SELECT
            b.account_id,
            NULL::integer AS candidate_id,
            '' AS status,
            CASE
              WHEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(b.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(b.end_date AS TEXT)), '')::date
              ELSE NULL
            END AS end_d,
            'recruiting' AS model
          FROM buyouts b
          LEFT JOIN account a ON a.account_id = b.account_id
          WHERE b.account_id IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        ),
        account_rows AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        ),
        corte AS (
          SELECT
            %(win_fin)s::date AS fecha_corte,
            %(win_ini)s::date AS mes_ini,
            %(win_fin)s::date AS mes_fin
        ),
        activos_al_corte AS (
          SELECT DISTINCT
            c.fecha_corte,
            r.account_id,
            r.candidate_id,
            r.model
          FROM corte c
          JOIN account_rows r
            ON (
                 (r.start_d IS NOT NULL
                  AND r.start_d <= c.mes_fin
                  AND COALESCE(r.end_d, DATE '9999-12-31') >= c.mes_fin)
                 OR
                 (c.mes_ini = DATE_TRUNC('month', CURRENT_DATE)
                  AND r.status = 'active'
                  AND (r.end_d IS NULL OR r.end_d >= CURRENT_DATE))
               )
           AND (%(modelo)s = 'Total' OR r.model = LOWER(%(modelo)s))
        ),
        candidatos_por_cliente AS (
          SELECT
            fecha_corte,
            account_id,
            COUNT(DISTINCT candidate_id) AS candidatos_activos
          FROM activos_al_corte
          GROUP BY 1, 2
        ),
        overlap AS (
          -- Clientes activos en AMBAS líneas (Staffing y Recruiting) al corte. Como
          -- clientes_activos = COUNT(DISTINCT account_id), estos se cuentan 1 sola vez
          -- en el Total → el Total NO es la suma simple S+R. Para modelo != Total el
          -- CTE trae una sola línea, así que da 0.
          SELECT COUNT(*)::int AS both_lines
          FROM (
            SELECT account_id
            FROM activos_al_corte
            GROUP BY account_id
            HAVING COUNT(DISTINCT model) > 1
          ) x
        )
        SELECT
          TO_CHAR(fecha_corte, 'YYYY-MM-DD')                                                AS fecha_corte,
          COUNT(DISTINCT account_id)::int                                                   AS clientes_activos,
          COUNT(DISTINCT account_id) FILTER (WHERE candidatos_activos > 1)::int             AS mayor_a_1,
          (SELECT both_lines FROM overlap)::int                                             AS both_lines,
          ROUND(
            100.0 * COUNT(DISTINCT account_id) FILTER (WHERE candidatos_activos > 1)
            / NULLIF(COUNT(DISTINCT account_id), 0)
          , 2)::float                                                                       AS pct_percent
        FROM candidatos_por_cliente
        GROUP BY fecha_corte;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "corte": corte, "modelo": modelo}


DATASET = {
    "key": "clients_multi_30d_summary",
    "label": "% Clientes con > 1 candidato — Día corte",
    "dimensions": [],
    "measures": [
        {"key": "clientes_activos", "label": "Clientes activos", "type": "number"},
        {"key": "mayor_a_1", "label": "Clientes > 1", "type": "number"},
        {"key": "both_lines", "label": "Activos en ambas líneas", "type": "number"},
        {"key": "pct_percent", "label": "% > 1", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
