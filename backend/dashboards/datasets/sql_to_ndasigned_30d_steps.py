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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # El calculo de la card SQL -> NDA Signed, abierto en 3 filas: los dos pasos con
    # su numerador/denominador reales y el producto. La fila compuesta no tiene N/M
    # porque las dos cohortes son distintas (ver sql_to_ndasigned_30d.py).
    #
    # Misma ventana que la card: window_bounds(filters), no una rodante propia.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH acc AS (
          SELECT
            a.account_id,
            a.sql_meeting_date AS sql_d,
            EXISTS (
              SELECT 1 FROM opportunity o
              WHERE o.account_id = a.account_id
                AND NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
            ) AS reached_dd
          FROM account a
          WHERE a.sql_meeting_date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND NOT EXISTS (
                  SELECT 1 FROM opportunity o3
                  WHERE o3.account_id = a.account_id
                    AND TRIM(o3.opp_stage) = 'Close Win'
                    AND NULLIF(o3.opp_close_date::text,'')::date < a.sql_meeting_date
              )
            AND (
                  TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
                OR EXISTS (
                       SELECT 1 FROM opportunity o2
                       WHERE o2.account_id = a.account_id
                         AND TRIM(LOWER(o2.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
                   )
            )
            AND a.sql_meeting_date BETWEEN %(win_ini)s::date AND %(win_fin)s::date
            AND (%(desde)s::date IS NULL OR a.sql_meeting_date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR a.sql_meeting_date <= %(hasta)s::date)
        ),
        opp AS (
          SELECT
            o.account_id,
            (NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL) AS signed_nda
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND NOT EXISTS (
                  SELECT 1 FROM opportunity o3
                  WHERE o3.account_id = a.account_id
                    AND TRIM(o3.opp_stage) = 'Close Win'
                    AND NULLIF(o3.opp_close_date::text,'')::date < NULLIF(o.deep_dive_date::text, '')::date
              )
            AND (
                  TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
                OR EXISTS (
                       SELECT 1 FROM opportunity o2
                       WHERE o2.account_id = a.account_id
                         AND TRIM(LOWER(o2.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
                   )
            )
            AND NULLIF(o.deep_dive_date::text,'')::date
                BETWEEN %(win_ini)s::date AND %(win_fin)s::date
            AND (%(desde)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date <= %(hasta)s::date)
        ),
        cur2 AS (
          SELECT account_id, BOOL_OR(signed_nda) AS signed_nda
          FROM opp
          GROUP BY account_id
        ),
        s1 AS (
          SELECT
            COUNT(*)::int                          AS den,
            COUNT(*) FILTER (WHERE reached_dd)::int AS num,
            COUNT(*) FILTER (WHERE reached_dd)::numeric * 100.0
              / NULLIF(COUNT(*), 0)                AS rate
          FROM acc
        ),
        s2 AS (
          SELECT
            COUNT(*)::int                           AS den,
            COUNT(*) FILTER (WHERE signed_nda)::int AS num,
            COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0
              / NULLIF(COUNT(*), 0)                 AS rate
          FROM cur2
        )
        SELECT 1 AS orden,
               'SQL → Deep Dive'::text AS paso,
               s1.num AS numerador, s1.den AS denominador,
               ROUND(s1.rate, 1) AS pct
        FROM s1
        UNION ALL
        SELECT 2,
               'Deep Dive → NDA Signed',
               s2.num, s2.den,
               ROUND(s2.rate, 1)
        FROM s2
        UNION ALL
        SELECT 3,
               'SQL → NDA Signed (compuesta)',
               NULL::int, NULL::int,
               ROUND(s1.rate * s2.rate / 100.0, 1)
        FROM s1 CROSS JOIN s2
        ORDER BY orden;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,
        "corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_ndasigned_30d_steps",
    "label": "SQL → NDA Signed — Cálculo paso a paso",
    "dimensions": [
        {"key": "paso", "label": "Paso", "type": "string"},
    ],
    "measures": [
        {"key": "numerador", "label": "Numerador", "type": "number"},
        {"key": "denominador", "label": "Denominador", "type": "number"},
        {"key": "pct", "label": "%", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
