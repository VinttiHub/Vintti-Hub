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

    corte = _parse_date(filters.get("corte"))
    corte_mode = bool(corte) and not (filters.get("mes") or filters.get("desde") or filters.get("hasta"))
    prev = (corte - timedelta(days=30)) if corte else None

    base_sql = """
        WITH hire_rows AS (
          SELECT
            ('hire_' || ho.hire_opp_id::text) AS row_id,
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
            LOWER(TRIM(o.opp_model)) AS model,
            COALESCE(ho.revenue, 0)::numeric AS rev_m,
            COALESCE(ho.fee, 0)::numeric AS fee_m
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          LEFT JOIN account a ON a.account_id = ho.account_id
          WHERE ho.account_id IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
        ),
        buyout_rows AS (
          SELECT
            ('buyout_' || b.buyout_id::text) AS row_id,
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
            'recruiting' AS model,
            COALESCE(b.revenue, 0)::numeric AS rev_m,
            0::numeric AS fee_m
          FROM buyouts b
          WHERE b.account_id IS NOT NULL
        ),
        all_rows AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        ),
        bounds AS (
          SELECT
            DATE_TRUNC('month', MIN(start_d))::date AS min_month,
            DATE_TRUNC('month', GREATEST(COALESCE(MAX(end_d), CURRENT_DATE), CURRENT_DATE))::date AS max_month
          FROM all_rows
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
        activos_det AS (
          SELECT DISTINCT
            m.mes_ini AS mes,
            r.model,
            r.row_id,
            r.candidate_id
          FROM meses_filtrado m
          JOIN all_rows r
            ON (
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
        candidatos_activos AS (
          SELECT
            mes,
            CASE
              WHEN %(modelo)s = 'Staffing'
                THEN COUNT(DISTINCT candidate_id) FILTER (
                  WHERE model = 'staffing' AND candidate_id IS NOT NULL
                )::numeric
              WHEN %(modelo)s = 'Recruiting'
                THEN COUNT(DISTINCT row_id) FILTER (
                  WHERE model = 'recruiting'
                )::numeric
              ELSE
                (
                  COUNT(DISTINCT candidate_id) FILTER (
                    WHERE model = 'staffing' AND candidate_id IS NOT NULL
                  )
                  +
                  COUNT(DISTINCT row_id) FILTER (
                    WHERE model = 'recruiting'
                  )
                )::numeric
            END AS candidatos_activos
          FROM activos_det
          GROUP BY 1
        ),
        ingresos_mes AS (
          SELECT
            m.mes_ini AS mes,
            SUM(
              CASE
                WHEN (
                  LEAST(COALESCE(r.end_d, m.mes_fin), m.mes_fin)
                  - GREATEST(r.start_d, m.mes_ini)
                  + 1
                ) > 0
                THEN (
                  (
                    LEAST(COALESCE(r.end_d, m.mes_fin), m.mes_fin)
                    - GREATEST(r.start_d, m.mes_ini)
                    + 1
                  )::numeric
                  / (m.mes_fin - m.mes_ini + 1)::numeric
                ) * r.rev_m
                ELSE 0
              END
            ) AS revenue_prorrateado,
            SUM(
              CASE
                WHEN (
                  LEAST(COALESCE(r.end_d, m.mes_fin), m.mes_fin)
                  - GREATEST(r.start_d, m.mes_ini)
                  + 1
                ) > 0
                THEN (
                  (
                    LEAST(COALESCE(r.end_d, m.mes_fin), m.mes_fin)
                    - GREATEST(r.start_d, m.mes_ini)
                    + 1
                  )::numeric
                  / (m.mes_fin - m.mes_ini + 1)::numeric
                ) * r.fee_m
                ELSE 0
              END
            ) AS fee_prorrateado
          FROM meses_filtrado m
          JOIN all_rows r
            ON r.start_d IS NOT NULL
           AND r.start_d <= m.mes_fin
           AND COALESCE(r.end_d, DATE '9999-12-31') >= m.mes_ini
           AND (
             %(modelo)s = 'Total'
             OR r.model = LOWER(%(modelo)s)
           )
          GROUP BY 1
        ),
        arpc_per_mes AS (
          SELECT
            m.mes_ini AS mes,
            COALESCE(c.candidatos_activos, 0) AS candidatos_activos,
            COALESCE(i.revenue_prorrateado, 0) AS revenue_prorrateado,
            COALESCE(i.fee_prorrateado, 0)     AS fee_prorrateado,
            COALESCE(i.revenue_prorrateado, 0)
              / NULLIF(COALESCE(c.candidatos_activos, 0), 0) AS arpc_revenue_raw,
            COALESCE(i.fee_prorrateado, 0)
              / NULLIF(COALESCE(c.candidatos_activos, 0), 0) AS arpc_fee_raw
          FROM meses_filtrado m
          LEFT JOIN candidatos_activos c ON c.mes = m.mes_ini
          LEFT JOIN ingresos_mes      i ON i.mes = m.mes_ini
        ),
        arpc_rounded AS (
          SELECT
            p.mes,
            p.candidatos_activos,
            p.revenue_prorrateado,
            p.fee_prorrateado,
            ROUND(p.arpc_revenue_raw, 2) AS arpc_revenue,
            ROUND(p.arpc_fee_raw, 2)     AS arpc_fee
          FROM arpc_per_mes p
        )
    """

    if corte_mode:
        anchor_with = """,
        arpc_anchor AS (
          SELECT k.kind,
            CASE
              WHEN %(modelo)s = 'Staffing'
                THEN COUNT(DISTINCT r.candidate_id) FILTER (WHERE r.model='staffing' AND r.candidate_id IS NOT NULL)::numeric
              WHEN %(modelo)s = 'Recruiting'
                THEN COUNT(DISTINCT r.row_id) FILTER (WHERE r.model='recruiting')::numeric
              ELSE (COUNT(DISTINCT r.candidate_id) FILTER (WHERE r.model='staffing' AND r.candidate_id IS NOT NULL)
                    + COUNT(DISTINCT r.row_id) FILTER (WHERE r.model='recruiting'))::numeric
            END AS candidatos,
            SUM(r.rev_m)::numeric AS rev,
            SUM(r.fee_m)::numeric AS fee
          FROM (VALUES (%(corte)s::date, 'cur'), (%(prev)s::date, 'prev')) AS k(d, kind)
          JOIN all_rows r
            ON r.start_d IS NOT NULL
           AND r.start_d <= k.d
           AND COALESCE(r.end_d, DATE '9999-12-31') >= k.d
           AND (%(modelo)s = 'Total' OR r.model = LOWER(%(modelo)s))
          GROUP BY k.kind
        ),
        arpc_corte_vals AS (
          SELECT
            MAX(CASE WHEN kind='cur'  THEN rev / NULLIF(candidatos,0) END) AS arpc_rev_cur,
            MAX(CASE WHEN kind='prev' THEN rev / NULLIF(candidatos,0) END) AS arpc_rev_prev,
            MAX(CASE WHEN kind='cur'  THEN fee / NULLIF(candidatos,0) END) AS arpc_fee_cur,
            MAX(CASE WHEN kind='prev' THEN fee / NULLIF(candidatos,0) END) AS arpc_fee_prev,
            MAX(CASE WHEN kind='cur'  THEN rev END) AS rev_total_cur
          FROM arpc_anchor
        )
    """
        kpi_cols = """,
          ROUND(cv.arpc_rev_cur, 2)::numeric AS arpc_revenue_corte,
          ROUND(100.0 * (cv.arpc_rev_cur - cv.arpc_rev_prev) / NULLIF(cv.arpc_rev_prev, 0), 2)::numeric AS arpc_revenue_corte_delta,
          ROUND(cv.arpc_fee_cur, 2)::numeric AS arpc_fee_corte,
          ROUND(100.0 * (cv.arpc_fee_cur - cv.arpc_fee_prev) / NULLIF(cv.arpc_fee_prev, 0), 2)::numeric AS arpc_fee_corte_delta,
          ROUND(cv.rev_total_cur, 2)::numeric AS revenue_total_mes_corte"""
        kpi_join = "\n        CROSS JOIN arpc_corte_vals cv"
        params = {"desde": desde, "hasta": hasta, "modelo": modelo, "corte": corte, "prev": prev}
    else:
        anchor_with = ""
        kpi_cols = """,
          NULL::numeric AS arpc_revenue_corte,
          NULL::numeric AS arpc_revenue_corte_delta,
          NULL::numeric AS arpc_fee_corte,
          NULL::numeric AS arpc_fee_corte_delta,
          NULL::numeric AS revenue_total_mes_corte"""
        kpi_join = ""
        params = {"desde": desde, "hasta": hasta, "modelo": modelo}

    final_select = f"""
        SELECT
          TO_CHAR(r.mes, 'YYYY-MM') AS mes,
          r.candidatos_activos::int AS candidatos_activos,
          ROUND(r.revenue_prorrateado, 2) AS revenue_total_mes,
          ROUND(r.fee_prorrateado, 2)     AS fee_total_mes,
          r.arpc_revenue,
          r.arpc_fee,
          ROUND(
            CASE
              WHEN LAG(r.arpc_revenue) OVER (ORDER BY r.mes) IS NULL
                OR LAG(r.arpc_revenue) OVER (ORDER BY r.mes) = 0
              THEN NULL
              ELSE (r.arpc_revenue - LAG(r.arpc_revenue) OVER (ORDER BY r.mes))
                   / LAG(r.arpc_revenue) OVER (ORDER BY r.mes) * 100
            END, 2
          ) AS arpc_revenue_mom_pct,
          ROUND(
            CASE
              WHEN LAG(r.arpc_fee) OVER (ORDER BY r.mes) IS NULL
                OR LAG(r.arpc_fee) OVER (ORDER BY r.mes) = 0
              THEN NULL
              ELSE (r.arpc_fee - LAG(r.arpc_fee) OVER (ORDER BY r.mes))
                   / LAG(r.arpc_fee) OVER (ORDER BY r.mes) * 100
            END, 2
          ) AS arpc_fee_mom_pct{kpi_cols}
        FROM arpc_rounded r{kpi_join}
        ORDER BY 1;
    """

    return base_sql + anchor_with + final_select, params


DATASET = {
    "key": "arpc_history",
    "label": "ARPC — Monthly History (Staffing/Recruiting/Total)",
    "dimensions": [
        {"key": "mes", "label": "Month", "type": "date"},
    ],
    "measures": [
        {"key": "candidatos_activos", "label": "Candidatos activos", "type": "number"},
        {"key": "revenue_total_mes", "label": "Revenue total mes", "type": "currency"},
        {"key": "fee_total_mes", "label": "Fee total mes", "type": "currency"},
        {"key": "arpc_revenue", "label": "ARPC Revenue", "type": "currency"},
        {"key": "arpc_fee", "label": "ARPC Fee", "type": "currency"},
        {"key": "arpc_revenue_mom_pct", "label": "ARPC Revenue MoM %", "type": "percent"},
        {"key": "arpc_fee_mom_pct", "label": "ARPC Fee MoM %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
