"""Sales GMRR / MRR — Staffing Outbound (AE) · historia mensual (año en curso).

Una fila por mes (ene → corte) con el MRR de ese mes:
  - gmrr    = Σ (salary + fee) de contratos Staffing activos ese mes
  - mrr_fee = Σ (fee)
Scope: canal Outbound + AE (opp_sales_lead ∈ {mariano, bahia}). Misma mecánica de
salary_updates + dedup de opp primaria que el resto. El YTD acumulado del front
se obtiene sumando la columna (reduce=sum).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")


def _parse_date(value):
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
        or _parse_date(filters.get("hasta"))
        or today_ar()
    )

    # Modo-corte: el usuario eligió CORTE y NO hay mes/desde/hasta → las cards
    # last/MoM muestran el run-rate AL día del corte (vs 30d antes). Las de YTD
    # (reduce=sum) no se tocan.
    corte_mode = bool(filters.get("corte") or filters.get("cutoff")) and not (
        filters.get("mes") or filters.get("desde") or filters.get("hasta")
    )
    prev = corte - timedelta(days=30)

    base_sql = """
        WITH params AS (
          SELECT %(corte)s::date AS corte_d, DATE_TRUNC('year', %(corte)s::date)::date AS year_start
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes,
                 (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes
          FROM params p, generate_series(p.year_start, p.corte_d, INTERVAL '1 month') gs
        ),
        staffing_hires AS (
          SELECT
            h.candidate_id, h.account_id, h.opportunity_id,
            CASE WHEN h.carga_active IS NOT NULL THEN h.carga_active::date
                 ELSE NULLIF(h.start_date::text,'')::date END AS start_d,
            CASE WHEN h.carga_inactive IS NOT NULL THEN h.carga_inactive::date
                 WHEN NULLIF(h.end_date::text,'') IS NULL THEN NULL
                 ELSE h.end_date::date END AS end_d,
            COALESCE(h.salary,0)::numeric AS hire_salary,
            COALESCE(h.fee,0)::numeric AS hire_fee
          FROM hire_opportunity h
          JOIN opportunity o ON o.opportunity_id = h.opportunity_id
          JOIN account a ON a.account_id = h.account_id
          WHERE o.opp_model = 'Staffing'
            AND h.candidate_id IS NOT NULL AND h.account_id IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'outbound'
            AND TRIM(LOWER(o.opp_sales_lead)) IN %(ae_leads)s
        ),
        opps_in_month AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, m.fin_mes, h.opportunity_id, h.candidate_id, h.account_id,
            h.start_d, h.hire_salary, h.hire_fee
          FROM meses m
          JOIN staffing_hires h
            ON h.start_d IS NOT NULL AND h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        opps_marked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY mes, candidate_id, account_id
            ORDER BY start_d DESC NULLS LAST, opportunity_id DESC) AS rn
          FROM opps_in_month
        ),
        eff AS (
          SELECT om.mes,
            CASE WHEN om.rn=1 THEN COALESCE(su.salary::numeric, om.hire_salary) ELSE om.hire_salary END AS salary,
            CASE WHEN om.rn=1 THEN COALESCE(su.fee::numeric, om.hire_fee) ELSE om.hire_fee END AS fee
          FROM opps_marked om
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = om.candidate_id AND s.date IS NOT NULL AND s.date::date <= om.fin_mes
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su ON TRUE
        ),
        per_month AS (
          SELECT mes,
            SUM(salary + fee)::bigint AS gmrr,
            SUM(fee)::bigint AS mrr_fee
          FROM eff GROUP BY mes
        )
    """

    if corte_mode:
        anchor_with = """,
        anchors AS (
          SELECT %(corte)s::date AS fin, 'cur'::text AS kind
          UNION ALL
          SELECT %(prev)s::date  AS fin, 'prev'::text AS kind
        ),
        a_opps AS (
          SELECT DISTINCT ON (an.kind, h.opportunity_id, h.candidate_id)
            an.kind, an.fin, h.opportunity_id, h.candidate_id, h.account_id,
            h.start_d, h.hire_salary, h.hire_fee
          FROM anchors an
          JOIN staffing_hires h
            ON h.start_d IS NOT NULL AND h.start_d <= an.fin
           AND (h.end_d IS NULL OR h.end_d >= an.fin)
          ORDER BY an.kind, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        a_marked AS (
          SELECT *, ROW_NUMBER() OVER (
            PARTITION BY kind, candidate_id, account_id
            ORDER BY start_d DESC NULLS LAST, opportunity_id DESC) AS rn
          FROM a_opps
        ),
        a_eff AS (
          SELECT am.kind,
            CASE WHEN am.rn=1 THEN COALESCE(su.salary::numeric, am.hire_salary) ELSE am.hire_salary END AS salary,
            CASE WHEN am.rn=1 THEN COALESCE(su.fee::numeric, am.hire_fee) ELSE am.hire_fee END AS fee
          FROM a_marked am
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = am.candidate_id AND s.date IS NOT NULL AND s.date::date <= am.fin
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) su ON TRUE
        ),
        a_mrr AS (
          SELECT kind, SUM(salary + fee)::bigint AS gmrr, SUM(fee)::bigint AS mrr_fee
          FROM a_eff GROUP BY kind
        ),
        a_vals AS (
          SELECT
            MAX(CASE WHEN kind='cur'  THEN gmrr END)    AS gmrr_cur,
            MAX(CASE WHEN kind='prev' THEN gmrr END)    AS gmrr_prev,
            MAX(CASE WHEN kind='cur'  THEN mrr_fee END) AS fee_cur,
            MAX(CASE WHEN kind='prev' THEN mrr_fee END) AS fee_prev
          FROM a_mrr
        )
    """
        kpi_cols = """,
          cv.gmrr_cur::bigint AS gmrr_corte,
          ROUND(100.0 * (cv.gmrr_cur - cv.gmrr_prev) / NULLIF(cv.gmrr_prev, 0), 2)::float AS gmrr_corte_delta,
          cv.fee_cur::bigint AS mrr_fee_corte,
          ROUND(100.0 * (cv.fee_cur - cv.fee_prev) / NULLIF(cv.fee_prev, 0), 2)::float AS mrr_fee_corte_delta"""
        kpi_join = "\n        CROSS JOIN a_vals cv"
        params = {"corte": corte, "prev": prev, "ae_leads": AE_LEADS}
    else:
        anchor_with = ""
        kpi_cols = """,
          NULL::bigint AS gmrr_corte,
          NULL::float  AS gmrr_corte_delta,
          NULL::bigint AS mrr_fee_corte,
          NULL::float  AS mrr_fee_corte_delta"""
        kpi_join = ""
        params = {"corte": corte, "ae_leads": AE_LEADS}

    final_select = f"""
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM') AS mes,
          COALESCE(pm.gmrr, 0)::bigint    AS gmrr,
          COALESCE(pm.mrr_fee, 0)::bigint AS mrr_fee{kpi_cols}
        FROM meses m
        LEFT JOIN per_month pm ON pm.mes = m.mes{kpi_join}
        ORDER BY m.mes;
    """

    return base_sql + anchor_with + final_select, params


DATASET = {
    "key": "sales_mrr_staffing_ae_history",
    "label": "Sales GMRR / MRR — Staffing Outbound (AE) · mensual (año en curso)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "gmrr", "label": "GMRR (salary+fee)", "type": "currency"},
        {"key": "mrr_fee", "label": "MRR Fee Vintti", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
