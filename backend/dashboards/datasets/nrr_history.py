from __future__ import annotations

from datetime import date

from ._mrr_staffing import HIRES_FULL_CTE


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


def _norm_metric(value) -> str:
    if not value:
        return "All"
    raw = str(value).strip()
    if raw in ("All", "Revenue", "Fee"):
        return raw
    if raw.lower() == "all":
        return "All"
    if raw.lower() == "revenue":
        return "Revenue"
    if raw.lower() == "fee":
        return "Fee"
    return "All"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    metric = _norm_metric(filters.get("metric"))
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # R5: NRR mensual sobre el MOTOR CANÓNICO de MRR (mismo de Management/mrr_history):
    # MRR efectivo por (candidato, cuenta) con dedup de opp primaria + salary_updates.
    # Para el mes M, la base (mrr_inicial) = MRR canónico al FIN DEL MES ANTERIOR
    # (prev_end = primer día de M − 1), de modo que cuadra EXACTO con el GMRR de
    # Management del mes M−1 (antes anclaba al fin del propio mes → inflaba la base).
    # La "ventana" del mes M es (prev_end, fin_mes].
    sql = f"""
        WITH {HIRES_FULL_CTE},
        meses AS (
          SELECT
            DATE_TRUNC('month', gs)::date                                AS mes,
            (DATE_TRUNC('month', gs) + INTERVAL '1 month - 1 day')::date AS fin_mes,
            (DATE_TRUNC('month', gs) - INTERVAL '1 day')::date           AS prev_end
          FROM generate_series(
            (SELECT MIN(start_d) FROM hires_full),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM hires_full),
            INTERVAL '1 month'
          ) gs
        ),
        -- snapshot canónico por mes al FIN DEL MES ANTERIOR (prev_end)
        snap_opps AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, m.prev_end, m.fin_mes,
            h.opportunity_id, h.candidate_id, h.account_id, h.start_d,
            h.salary AS hs, h.fee AS hf
          FROM meses m
          JOIN hires_full h
            ON h.start_d <= m.prev_end
           AND (h.end_d IS NULL OR h.end_d >= m.prev_end)
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        snap_marked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY mes, candidate_id, account_id
              ORDER BY start_d DESC NULLS LAST, opportunity_id DESC
            ) AS rn
          FROM snap_opps
        ),
        snap_eff AS (
          SELECT sm.mes, sm.candidate_id, sm.account_id,
            CASE WHEN sm.rn = 1
              THEN COALESCE(sr.salary::numeric, se.salary::numeric, sm.hs)
              ELSE sm.hs END AS salary,
            CASE WHEN sm.rn = 1
              THEN COALESCE(sr.fee::numeric, se.fee::numeric, sm.hf)
              ELSE sm.hf END AS fee
          FROM snap_marked sm
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = sm.candidate_id
              AND s.date IS NOT NULL AND s.date::date <= sm.prev_end
            ORDER BY s.date::date DESC, s.update_id DESC LIMIT 1
          ) sr ON TRUE
          LEFT JOIN LATERAL (
            SELECT s.salary, s.fee FROM salary_updates s
            WHERE s.candidate_id = sm.candidate_id AND s.date IS NOT NULL
            ORDER BY s.date::date ASC, s.update_id ASC LIMIT 1
          ) se ON TRUE
        ),
        unit_ini AS (
          SELECT mes, candidate_id, account_id,
            SUM(salary)::numeric AS salary,
            SUM(fee)::numeric    AS fee
          FROM snap_eff
          GROUP BY mes, candidate_id, account_id
        ),
        base_nrr AS (
          SELECT mes,
            SUM(CASE WHEN %(metric)s = 'Fee' THEN fee ELSE (salary + fee) END)::numeric AS mrr_inicial
          FROM unit_ini
          GROUP BY mes
        ),
        cohort_accounts AS (
          SELECT DISTINCT mes, account_id FROM unit_ini WHERE account_id IS NOT NULL
        ),
        -- unidades activas al FIN del mes (para detectar churn de la cohorte)
        active_fin AS (
          SELECT DISTINCT m.mes, h.candidate_id, h.account_id
          FROM meses m
          JOIN hires_full h
            ON h.start_d <= m.fin_mes
           AND (h.end_d IS NULL OR h.end_d >= m.fin_mes)
        ),
        churn_units AS (
          SELECT
            ui.mes, ui.candidate_id, ui.account_id, ui.salary, ui.fee,
            (
              SELECT TRIM(COALESCE(h.inactive_reason, ''))
              FROM hires_full h
              JOIN meses mm ON mm.mes = ui.mes
              WHERE h.candidate_id = ui.candidate_id
                AND h.account_id = ui.account_id
                AND h.end_d IS NOT NULL
                AND h.end_d > mm.prev_end AND h.end_d <= mm.fin_mes
              ORDER BY h.end_d DESC LIMIT 1
            ) AS reason
          FROM unit_ini ui
          WHERE NOT EXISTS (
            SELECT 1 FROM active_fin af
            WHERE af.mes = ui.mes
              AND af.candidate_id = ui.candidate_id
              AND af.account_id = ui.account_id
          )
        ),
        perdidas AS (
          SELECT mes,
            SUM(CASE
                  WHEN (reason ILIKE '%%layoff%%' OR reason ILIKE '%%downsizing%%')
                  THEN (CASE WHEN %(metric)s = 'Fee' THEN fee ELSE (salary + fee) END)
                  ELSE 0
                END)::numeric AS downgrades_recorte,
            SUM(CASE
                  WHEN (reason ILIKE '%%layoff%%' OR reason ILIKE '%%downsizing%%')
                  THEN 0
                  ELSE (CASE WHEN %(metric)s = 'Fee' THEN fee ELSE (salary + fee) END)
                END)::numeric AS churn_no_recorte
          FROM churn_units
          GROUP BY mes
        ),
        upsell_hires AS (
          SELECT DISTINCT ON (m.mes, h.opportunity_id, h.candidate_id)
            m.mes, h.salary AS hs, h.fee AS hf
          FROM meses m
          JOIN hires_full h
            ON h.opp_close_d IS NOT NULL
           AND h.opp_close_d > m.prev_end AND h.opp_close_d <= m.fin_mes
           AND h.account_id IN (
             SELECT ca.account_id FROM cohort_accounts ca WHERE ca.mes = m.mes
           )
          ORDER BY m.mes, h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        upsells AS (
          SELECT mes,
            SUM(CASE WHEN %(metric)s = 'Fee' THEN hf ELSE (hs + hf) END)::numeric AS upsells_lara
          FROM upsell_hires
          GROUP BY mes
        )
        SELECT
          TO_CHAR(b.mes, 'YYYY-MM-DD')                          AS mes,
          b.mrr_inicial::float                                  AS mrr_inicial,
          COALESCE(u.upsells_lara, 0)::float                    AS upsells_lara,
          COALESCE(p.downgrades_recorte, 0)::float              AS downgrades_recorte,
          COALESCE(p.churn_no_recorte, 0)::float                AS churn_no_recorte,
          ROUND(
            100.0 *
            (
              (COALESCE(b.mrr_inicial, 0)
               + COALESCE(u.upsells_lara, 0)
               - COALESCE(p.downgrades_recorte, 0)
               - COALESCE(p.churn_no_recorte, 0)
              )
              / NULLIF(b.mrr_inicial, 0)
            )
          , 2)::float                                           AS nrr_pct
        FROM base_nrr b
        LEFT JOIN upsells u ON u.mes = b.mes
        LEFT JOIN perdidas p ON p.mes = b.mes
        WHERE b.mrr_inicial IS NOT NULL AND b.mrr_inicial > 0
          AND (%(desde)s::date IS NULL OR b.mes >= DATE_TRUNC('month', %(desde)s::date))
          AND (%(hasta)s::date IS NULL OR b.mes <= DATE_TRUNC('month', %(hasta)s::date))
        ORDER BY b.mes;
    """

    return sql, {"metric": metric, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "nrr_history",
    "label": "NRR mensual (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "mrr_inicial", "label": "MRR inicial", "type": "currency"},
        {"key": "upsells_lara", "label": "Upsells", "type": "currency"},
        {"key": "downgrades_recorte", "label": "Downgrades", "type": "currency"},
        {"key": "churn_no_recorte", "label": "Churn", "type": "currency"},
        {"key": "nrr_pct", "label": "NRR %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
