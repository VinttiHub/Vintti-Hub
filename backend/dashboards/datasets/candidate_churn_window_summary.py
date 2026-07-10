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
    # Mantiene la ventana de 90/180 días, pero ancla su fin (`corte`) al filtro
    # global (Desde/Hasta o Mes) cuando está presente, para que la card coincida
    # con la barra mensual de la gráfica. Sin filtro → corte/hoy como antes.
    if filters and (filters.get("desde") or filters.get("hasta") or filters.get("mes")):
        _, corte = window_bounds(filters)
    else:
        corte = (
            _parse_date(filters.get("corte"))
            or _parse_date(filters.get("cutoff"))
            or _parse_date(filters.get("fecha_corte"))
            or today_ar()
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
              AND COALESCE(a.vintti_internal, FALSE) = FALSE
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
        -- R7: roll-up a grano CANDIDATO antes de contar. Antes el numerador contaba
        -- filas-hire (COUNT(*)) y el denominador candidatos distintos → si un
        -- candidato tenía 2 hires en la ventana, el churn podía pasar de 100.
        -- Un candidato está ACTIVO si CUALQUIER hire suyo sigue activo; si no, es
        -- BAJA (real prioriza sobre buyout cuando tiene ambos). Antes el churn
        -- podia superar el 100 por contar filas-hire sobre candidatos distintos.
        per_candidate AS (
          SELECT
            candidate_id,
            BOOL_OR(estado_en_corte = 'ACTIVO')  AS is_active,
            BOOL_OR(baja_tipo = 'BAJA_REAL')     AS any_real,
            BOOL_OR(baja_tipo = 'BAJA_BUYOUT')   AS any_buyout
          FROM detalle
          GROUP BY candidate_id
        ),
        cand_state AS (
          SELECT
            candidate_id,
            CASE WHEN is_active THEN 'ACTIVO' ELSE 'BAJA' END AS estado,
            CASE
              WHEN is_active   THEN NULL
              WHEN any_real    THEN 'BAJA_REAL'
              WHEN any_buyout  THEN 'BAJA_BUYOUT'
              ELSE NULL
            END AS baja_tipo
          FROM per_candidate
        ),
        totals AS (
          SELECT
            COUNT(*)::int                                                AS starts,
            COUNT(*) FILTER (WHERE estado = 'BAJA')::int                 AS bajas,
            COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_REAL')::int         AS bajas_real,
            COUNT(*) FILTER (WHERE baja_tipo = 'BAJA_BUYOUT')::int       AS bajas_buyout,
            COUNT(*) FILTER (WHERE estado = 'ACTIVO')::int              AS activos_al_corte
          FROM cand_state
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
