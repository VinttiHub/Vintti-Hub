from __future__ import annotations

from datetime import date, timedelta


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


def _resolve_modelo(filters: dict) -> str:
    raw = (
        filters.get("modelo")
        or filters.get("model")
        or filters.get("segmento")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    desde = _parse_date(filters.get("desde")) or _parse_date(filters.get("from"))
    hasta = _parse_date(filters.get("hasta")) or _parse_date(filters.get("to"))
    modelo = _resolve_modelo(filters)

    # Modo-corte: hay corte y NO hay mes/desde/hasta → snapshot al día del corte.
    corte = _parse_date(filters.get("corte"))
    corte_mode = bool(corte) and not (filters.get("mes") or filters.get("desde") or filters.get("hasta"))
    prev = (corte - timedelta(days=30)) if corte else None

    base_sql = """
        WITH hire_rows AS (
          SELECT
            ('hire_' || ho.hire_opp_id::text) AS row_id,
            ho.candidate_id,
            ho.account_id,
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
          WHERE ho.account_id IS NOT NULL
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
        ),
        buyout_rows AS (
          SELECT
            ('buyout_' || b.buyout_id::text) AS row_id,
            NULL::integer AS candidate_id,
            b.account_id,
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
          WHERE b.account_id IS NOT NULL
        ),
        account_rows AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        ),
        bounds AS (
          SELECT
            DATE_TRUNC('month', MIN(start_d))::date AS min_month,
            DATE_TRUNC('month', GREATEST(COALESCE(MAX(end_d), CURRENT_DATE), CURRENT_DATE))::date AS max_month
          FROM account_rows
          WHERE start_d IS NOT NULL
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes_ini,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS mes_fin
          FROM bounds bb,
               generate_series(bb.min_month, bb.max_month, INTERVAL '1 month') gs
        ),
        meses_filtrado AS (
          SELECT *
          FROM meses m
          WHERE (%(desde)s::date IS NULL OR m.mes_ini >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR m.mes_ini <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        activos_base AS (
          SELECT DISTINCT
            m.mes_ini AS mes,
            r.model,
            r.row_id,
            r.candidate_id,
            r.account_id
          FROM meses_filtrado m
          JOIN account_rows r
            ON r.model IN ('staffing', 'recruiting')
           AND (
             (
               r.start_d IS NOT NULL
               AND r.start_d <= m.mes_fin
               AND COALESCE(r.end_d, DATE '9999-12-31') >= m.mes_fin
             )
             OR (
               m.mes_ini = DATE_TRUNC('month', CURRENT_DATE)
               AND r.status = 'active'
               AND (r.end_d IS NULL OR r.end_d >= CURRENT_DATE)
             )
           )
           AND (
             %(modelo)s = 'Total'
             OR r.model = LOWER(%(modelo)s)
           )
        ),
        metricas_mes AS (
          SELECT
            mes,
            CASE
              WHEN %(modelo)s = 'Staffing'
                THEN COUNT(DISTINCT candidate_id) FILTER (WHERE model = 'staffing' AND candidate_id IS NOT NULL)::numeric
              WHEN %(modelo)s = 'Recruiting'
                THEN COUNT(DISTINCT row_id) FILTER (WHERE model = 'recruiting')::numeric
              ELSE
                (
                  COUNT(DISTINCT candidate_id) FILTER (WHERE model = 'staffing' AND candidate_id IS NOT NULL)
                  +
                  COUNT(DISTINCT row_id) FILTER (WHERE model = 'recruiting')
                )::numeric
            END AS candidatos_activos,
            COUNT(DISTINCT account_id)::numeric AS cuentas_activas
          FROM activos_base
          GROUP BY 1
        ),
        acpa_base AS (
          SELECT
            m.mes_ini AS mes,
            COALESCE(mm.candidatos_activos, 0) AS candidatos_activos,
            COALESCE(mm.cuentas_activas, 0)    AS cuentas_activas,
            COALESCE(mm.candidatos_activos, 0)
              / NULLIF(COALESCE(mm.cuentas_activas, 0), 0) AS acpa_raw
          FROM meses_filtrado m
          LEFT JOIN metricas_mes mm ON mm.mes = m.mes_ini
        )
    """

    if corte_mode:
        anchor_with = """,
        acpa_anchor AS (
          SELECT k.kind,
            CASE
              WHEN %(modelo)s = 'Staffing'
                THEN COUNT(DISTINCT r.candidate_id) FILTER (WHERE r.model='staffing' AND r.candidate_id IS NOT NULL)::numeric
              WHEN %(modelo)s = 'Recruiting'
                THEN COUNT(DISTINCT r.row_id) FILTER (WHERE r.model='recruiting')::numeric
              ELSE (COUNT(DISTINCT r.candidate_id) FILTER (WHERE r.model='staffing' AND r.candidate_id IS NOT NULL)
                    + COUNT(DISTINCT r.row_id) FILTER (WHERE r.model='recruiting'))::numeric
            END AS candidatos_activos,
            COUNT(DISTINCT r.account_id)::numeric AS cuentas_activas
          FROM (VALUES (%(corte)s::date, 'cur'), (%(prev)s::date, 'prev')) AS k(d, kind)
          JOIN account_rows r
            ON r.model IN ('staffing','recruiting')
           AND r.start_d IS NOT NULL
           AND r.start_d <= k.d
           AND COALESCE(r.end_d, DATE '9999-12-31') >= k.d
           AND (%(modelo)s = 'Total' OR r.model = LOWER(%(modelo)s))
          GROUP BY k.kind
        ),
        acpa_corte_vals AS (
          SELECT
            MAX(CASE WHEN kind='cur'  THEN candidatos_activos / NULLIF(cuentas_activas,0) END) AS acpa_cur,
            MAX(CASE WHEN kind='prev' THEN candidatos_activos / NULLIF(cuentas_activas,0) END) AS acpa_prev,
            MAX(CASE WHEN kind='cur'  THEN cuentas_activas END) AS cuentas_cur,
            MAX(CASE WHEN kind='prev' THEN cuentas_activas END) AS cuentas_prev
          FROM acpa_anchor
        )
    """
        kpi_cols = """,
          ROUND(cv.acpa_cur, 2)::numeric AS acpa_corte,
          ROUND(100.0 * (cv.acpa_cur - cv.acpa_prev) / NULLIF(cv.acpa_prev, 0), 2)::numeric AS acpa_corte_delta,
          cv.cuentas_cur::int AS cuentas_corte,
          ROUND(100.0 * (cv.cuentas_cur - cv.cuentas_prev) / NULLIF(cv.cuentas_prev, 0), 2)::numeric AS cuentas_corte_delta,
          (cv.cuentas_cur - cv.cuentas_prev)::int AS cuentas_corte_abs"""
        kpi_join = "\n        CROSS JOIN acpa_corte_vals cv"
        params = {"desde": desde, "hasta": hasta, "modelo": modelo, "corte": corte, "prev": prev}
    else:
        anchor_with = ""
        kpi_cols = """,
          NULL::numeric AS acpa_corte,
          NULL::numeric AS acpa_corte_delta,
          NULL::int     AS cuentas_corte,
          NULL::numeric AS cuentas_corte_delta,
          NULL::int     AS cuentas_corte_abs"""
        kpi_join = ""
        params = {"desde": desde, "hasta": hasta, "modelo": modelo}

    final_select = f"""
        SELECT
          TO_CHAR(b.mes, 'YYYY-MM')        AS mes,
          b.cuentas_activas::int           AS cuentas_activas,
          b.candidatos_activos::int        AS candidatos_activos,
          ROUND(b.acpa_raw, 2)             AS acpa,
          ROUND(
            CASE
              WHEN LAG(b.acpa_raw) OVER (ORDER BY b.mes) IS NULL
                OR LAG(b.acpa_raw) OVER (ORDER BY b.mes) = 0
                OR b.acpa_raw IS NULL
              THEN NULL
              ELSE (b.acpa_raw - LAG(b.acpa_raw) OVER (ORDER BY b.mes))
                   / LAG(b.acpa_raw) OVER (ORDER BY b.mes) * 100
            END, 2
          ) AS acpa_mom_pct{kpi_cols}
        FROM acpa_base b{kpi_join}
        ORDER BY 1;
    """

    return base_sql + anchor_with + final_select, params


DATASET = {
    "key": "acpa_history",
    "label": "ACPA — Average Consultants per Account (Staffing/Recruiting/Total)",
    "dimensions": [
        {"key": "mes", "label": "Month", "type": "date"},
    ],
    "measures": [
        {"key": "cuentas_activas", "label": "Cuentas activas", "type": "number"},
        {"key": "candidatos_activos", "label": "Candidatos activos", "type": "number"},
        {"key": "acpa", "label": "ACPA", "type": "number"},
        {"key": "acpa_mom_pct", "label": "ACPA MoM %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
