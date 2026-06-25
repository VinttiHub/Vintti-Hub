from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds
from ._mrr_staffing import HIRES_FULL_CTE, unit_snapshot


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
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )

    win_ini, win_fin = window_bounds(filters)
    # R5: NRR sobre el MOTOR CANÓNICO de MRR (mismo de Management/mrr_history):
    # MRR efectivo por (candidato, cuenta) con dedup de opp primaria + salary_updates,
    # para que "MRR inicial" reconcilie EXACTO con el GMRR de Management.
    #   - base (mrr_inicial) = MRR canónico de la cohorte activa al INICIO (win_ini).
    #   - upsell = nuevos hires cerrados en la ventana sobre cuentas de la cohorte.
    #   - churn/downgrade = unidades de la cohorte que YA NO están activas al fin,
    #     valuadas a su MRR canónico al inicio; downgrade = baja por layoffs/downsizing.
    sql = f"""
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        {HIRES_FULL_CTE},
        {unit_snapshot('unit_ini', '%(win_ini)s::date')},
        mrr_base AS (
          SELECT SUM(
            CASE WHEN %(metric)s = 'Fee' THEN fee ELSE (salary + fee) END
          )::numeric AS mrr_inicial
          FROM unit_ini
        ),
        cohort_accounts AS (
          SELECT DISTINCT account_id FROM unit_ini WHERE account_id IS NOT NULL
        ),
        active_fin AS (
          SELECT DISTINCT h.candidate_id, h.account_id
          FROM hires_full h CROSS JOIN ventana v
          WHERE h.start_d <= v.win_fin AND (h.end_d IS NULL OR h.end_d >= v.win_fin)
        ),
        churn_units AS (
          SELECT
            ui.candidate_id, ui.account_id, ui.salary, ui.fee,
            (
              SELECT TRIM(COALESCE(h.inactive_reason, ''))
              FROM hires_full h CROSS JOIN ventana v
              WHERE h.candidate_id = ui.candidate_id
                AND h.account_id = ui.account_id
                AND h.end_d IS NOT NULL
                AND h.end_d > v.win_ini AND h.end_d <= v.win_fin
              ORDER BY h.end_d DESC LIMIT 1
            ) AS reason
          FROM unit_ini ui
          WHERE NOT EXISTS (
            SELECT 1 FROM active_fin af
            WHERE af.candidate_id = ui.candidate_id
              AND af.account_id = ui.account_id
          )
        ),
        perdidas AS (
          SELECT
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
        ),
        upsell_hires AS (
          SELECT DISTINCT ON (h.opportunity_id, h.candidate_id)
            h.salary AS hs, h.fee AS hf
          FROM hires_full h CROSS JOIN ventana v
          WHERE h.opp_close_d IS NOT NULL
            AND h.opp_close_d > v.win_ini AND h.opp_close_d <= v.win_fin
            AND h.account_id IN (SELECT account_id FROM cohort_accounts)
          ORDER BY h.opportunity_id, h.candidate_id, h.start_d DESC NULLS LAST
        ),
        upsells AS (
          SELECT SUM(
            CASE WHEN %(metric)s = 'Fee' THEN hf ELSE (hs + hf) END
          )::numeric AS upsells_lara
          FROM upsell_hires
        )
        SELECT
          TO_CHAR(v.win_ini, 'YYYY-MM-DD')                          AS win_ini,
          TO_CHAR(v.win_fin, 'YYYY-MM-DD')                          AS win_fin,
          COALESCE(mb.mrr_inicial,        0)::float                 AS mrr_inicial,
          COALESCE(u.upsells_lara,        0)::float                 AS upsells_lara,
          COALESCE(p.downgrades_recorte,  0)::float                 AS downgrades_recorte,
          COALESCE(p.churn_no_recorte,    0)::float                 AS churn_no_recorte,
          ROUND(
            100.0 *
            (
              (COALESCE(mb.mrr_inicial, 0)
               + COALESCE(u.upsells_lara, 0)
               - COALESCE(p.downgrades_recorte, 0)
               - COALESCE(p.churn_no_recorte, 0)
              )
              / NULLIF(mb.mrr_inicial, 0)
            )
          , 2)::float                                               AS nrr_pct
        FROM ventana v
        CROSS JOIN mrr_base mb
        LEFT JOIN upsells u  ON TRUE
        LEFT JOIN perdidas p ON TRUE;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin, "metric": metric, "corte": corte}


DATASET = {
    "key": "nrr_30d_summary",
    "label": "NRR (Staffing) — Ventana 30 días",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio", "type": "date"},
        {"key": "win_fin", "label": "Fin", "type": "date"},
    ],
    "measures": [
        {"key": "mrr_inicial", "label": "MRR", "type": "currency"},
        {"key": "upsells_lara", "label": "Upsells", "type": "currency"},
        {"key": "downgrades_recorte", "label": "Downgrades", "type": "currency"},
        {"key": "churn_no_recorte", "label": "Churn", "type": "currency"},
        {"key": "nrr_pct", "label": "NRR %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
