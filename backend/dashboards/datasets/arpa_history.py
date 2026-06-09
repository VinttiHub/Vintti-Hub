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
            ho.account_id,
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
            LOWER(o.opp_model) AS model,
            COALESCE(ho.revenue, 0)::numeric AS rev_m,
            COALESCE(ho.fee, 0)::numeric AS fee_m
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
        ),
        buyout_rows AS (
          SELECT
            b.account_id,
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
        base AS (
          SELECT * FROM hire_rows
          UNION ALL
          SELECT * FROM buyout_rows
        ),
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date AS mes_ini,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS mes_fin,
            LEAST(
              (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date,
              CURRENT_DATE
            ) AS snapshot_d
          FROM generate_series(
            (SELECT DATE_TRUNC('month', MIN(start_d)) FROM base WHERE start_d IS NOT NULL),
            DATE_TRUNC('month', CURRENT_DATE),
            INTERVAL '1 month'
          ) gs
        ),
        meses_filtrado AS (
          SELECT *
          FROM meses m
          WHERE (%(desde)s::date IS NULL OR m.mes_ini >= DATE_TRUNC('month', %(desde)s::date))
            AND (%(hasta)s::date IS NULL OR m.mes_ini <= DATE_TRUNC('month', %(hasta)s::date))
        ),
        activos_mes AS (
          SELECT DISTINCT
            m.mes_ini AS mes,
            b.account_id
          FROM meses_filtrado m
          JOIN base b
            ON b.model IN ('staffing', 'recruiting')
           AND b.start_d IS NOT NULL
           AND b.start_d <= m.snapshot_d
           AND (b.end_d IS NULL OR b.end_d >= m.snapshot_d)
           AND (
             %(modelo)s = 'Total'
             OR b.model = LOWER(%(modelo)s)
           )
        ),
        clientes_activos AS (
          SELECT
            mes,
            COUNT(DISTINCT account_id)::numeric AS clientes_activos
          FROM activos_mes
          GROUP BY mes
        ),
        ingresos_mes AS (
          SELECT
            m.mes_ini AS mes,
            SUM(
              CASE
                WHEN (
                  LEAST(COALESCE(b.end_d, m.mes_fin), m.mes_fin)
                  - GREATEST(b.start_d, m.mes_ini)
                  + 1
                ) > 0
                THEN
                  (
                    LEAST(COALESCE(b.end_d, m.mes_fin), m.mes_fin)
                    - GREATEST(b.start_d, m.mes_ini)
                    + 1
                  )::numeric
                  / (m.mes_fin - m.mes_ini + 1)::numeric
                  * b.rev_m
                ELSE 0
              END
            ) AS revenue_prorrateado,
            SUM(
              CASE
                WHEN (
                  LEAST(COALESCE(b.end_d, m.mes_fin), m.mes_fin)
                  - GREATEST(b.start_d, m.mes_ini)
                  + 1
                ) > 0
                THEN
                  (
                    LEAST(COALESCE(b.end_d, m.mes_fin), m.mes_fin)
                    - GREATEST(b.start_d, m.mes_ini)
                    + 1
                  )::numeric
                  / (m.mes_fin - m.mes_ini + 1)::numeric
                  * b.fee_m
                ELSE 0
              END
            ) AS fee_prorrateado
          FROM meses_filtrado m
          JOIN base b
            ON b.model IN ('staffing', 'recruiting')
           AND b.start_d IS NOT NULL
           AND b.start_d <= m.mes_fin
           AND COALESCE(b.end_d, DATE '9999-12-31') >= m.mes_ini
           AND (
             %(modelo)s = 'Total'
             OR b.model = LOWER(%(modelo)s)
           )
          GROUP BY 1
        )
        ,
        arpa_per_mes AS (
          SELECT
            c.mes,
            c.clientes_activos,
            ROUND(COALESCE(i.revenue_prorrateado, 0), 2) AS revenue_total_mes,
            ROUND(COALESCE(i.fee_prorrateado, 0), 2)     AS fee_total_mes,
            ROUND(COALESCE(i.revenue_prorrateado, 0) / NULLIF(c.clientes_activos, 0), 2) AS arpa_revenue,
            ROUND(COALESCE(i.fee_prorrateado, 0)     / NULLIF(c.clientes_activos, 0), 2) AS arpa_fee
          FROM clientes_activos c
          LEFT JOIN ingresos_mes i USING (mes)
        )
    """

    if corte_mode:
        anchor_with = """,
        arpa_anchor AS (
          SELECT k.kind,
            COUNT(DISTINCT b.account_id)::numeric AS clientes,
            SUM(b.rev_m)::numeric AS rev,
            SUM(b.fee_m)::numeric AS fee
          FROM (VALUES (%(corte)s::date, 'cur'), (%(prev)s::date, 'prev')) AS k(d, kind)
          JOIN base b
            ON b.model IN ('staffing', 'recruiting')
           AND b.start_d IS NOT NULL
           AND b.start_d <= k.d
           AND COALESCE(b.end_d, DATE '9999-12-31') >= k.d
           AND (%(modelo)s = 'Total' OR b.model = LOWER(%(modelo)s))
          GROUP BY k.kind
        ),
        arpa_corte_vals AS (
          SELECT
            MAX(CASE WHEN kind='cur'  THEN rev / NULLIF(clientes,0) END) AS arpa_rev_cur,
            MAX(CASE WHEN kind='prev' THEN rev / NULLIF(clientes,0) END) AS arpa_rev_prev,
            MAX(CASE WHEN kind='cur'  THEN fee / NULLIF(clientes,0) END) AS arpa_fee_cur,
            MAX(CASE WHEN kind='prev' THEN fee / NULLIF(clientes,0) END) AS arpa_fee_prev,
            MAX(CASE WHEN kind='cur'  THEN rev END) AS rev_total_cur
          FROM arpa_anchor
        )
    """
        kpi_cols = """,
          ROUND(cv.arpa_rev_cur, 2)::numeric AS arpa_revenue_corte,
          ROUND(100.0 * (cv.arpa_rev_cur - cv.arpa_rev_prev) / NULLIF(cv.arpa_rev_prev, 0), 2)::numeric AS arpa_revenue_corte_delta,
          ROUND(cv.arpa_fee_cur, 2)::numeric AS arpa_fee_corte,
          ROUND(100.0 * (cv.arpa_fee_cur - cv.arpa_fee_prev) / NULLIF(cv.arpa_fee_prev, 0), 2)::numeric AS arpa_fee_corte_delta,
          ROUND(cv.rev_total_cur, 2)::numeric AS revenue_total_mes_corte"""
        kpi_join = "\n        CROSS JOIN arpa_corte_vals cv"
        params = {"desde": desde, "hasta": hasta, "modelo": modelo, "corte": corte, "prev": prev}
    else:
        anchor_with = ""
        kpi_cols = """,
          NULL::numeric AS arpa_revenue_corte,
          NULL::numeric AS arpa_revenue_corte_delta,
          NULL::numeric AS arpa_fee_corte,
          NULL::numeric AS arpa_fee_corte_delta,
          NULL::numeric AS revenue_total_mes_corte"""
        kpi_join = ""
        params = {"desde": desde, "hasta": hasta, "modelo": modelo}

    final_select = f"""
        SELECT
          TO_CHAR(p.mes, 'YYYY-MM') AS mes,
          p.clientes_activos::int   AS clientes_activos,
          p.revenue_total_mes,
          p.fee_total_mes,
          p.arpa_revenue,
          p.arpa_fee,
          ROUND(
            CASE
              WHEN LAG(p.arpa_revenue) OVER (ORDER BY p.mes) IS NULL
                OR LAG(p.arpa_revenue) OVER (ORDER BY p.mes) = 0
              THEN NULL
              ELSE (p.arpa_revenue - LAG(p.arpa_revenue) OVER (ORDER BY p.mes))
                   / LAG(p.arpa_revenue) OVER (ORDER BY p.mes) * 100
            END, 2
          ) AS arpa_revenue_mom_pct,
          ROUND(
            CASE
              WHEN LAG(p.arpa_fee) OVER (ORDER BY p.mes) IS NULL
                OR LAG(p.arpa_fee) OVER (ORDER BY p.mes) = 0
              THEN NULL
              ELSE (p.arpa_fee - LAG(p.arpa_fee) OVER (ORDER BY p.mes))
                   / LAG(p.arpa_fee) OVER (ORDER BY p.mes) * 100
            END, 2
          ) AS arpa_fee_mom_pct{kpi_cols}
        FROM arpa_per_mes p{kpi_join}
        ORDER BY 1;
    """

    return base_sql + anchor_with + final_select, params


DATASET = {
    "key": "arpa_history",
    "label": "ARPA — Monthly History (Staffing/Recruiting/Total)",
    "dimensions": [
        {"key": "mes", "label": "Month", "type": "date"},
    ],
    "measures": [
        {"key": "clientes_activos", "label": "Clientes activos", "type": "number"},
        {"key": "revenue_total_mes", "label": "Revenue total mes", "type": "currency"},
        {"key": "fee_total_mes", "label": "Fee total mes", "type": "currency"},
        {"key": "arpa_revenue", "label": "ARPA Revenue", "type": "currency"},
        {"key": "arpa_fee", "label": "ARPA Fee", "type": "currency"},
        {"key": "arpa_revenue_mom_pct", "label": "ARPA Revenue MoM %", "type": "percent"},
        {"key": "arpa_fee_mom_pct", "label": "ARPA Fee MoM %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
