"""Operations · % de razón de caída SOLO para el churn M3 (primeros 3 meses).

Misma dona que `op_churn_reasons`, pero la población NO es "todas las caídas de la
ventana": es el cohorte de **churn M3** de la card "3/6m Churn" de Account Management
(dataset `candidate_churn_window_summary` con meses=3). Es decir, candidatos de
Staffing cuyo `start` cae en la ventana trailing de 90 días y que ya tienen fecha de
baja (`end_d <= corte`) → los que "se fueron en sus primeros 3 meses".

Se replica el mismo cohorte (Staffing, cuenta no-interna, roll-up a grano CANDIDATO:
BAJA solo si NINGÚN hire suyo en la ventana sigue activo) para que el total de la dona
reconcilie con el número "Bajas" de la card 3/6m Churn (M3). De cada candidato-baja se
toma la razón (`inactive_reason`) del hire dado de baja más reciente; los sin razón
cargada se excluyen (igual que [[op_churn_reasons]]).

A diferencia de la dona general, NO se ancla en `carga_inactive` ni se excluye a
`agustina.barbero`: se ancla en el corte del cohorte para reconciliar 1:1 con la card AM.
"""
from __future__ import annotations

from datetime import date, timedelta
from ._now import today_ar
from ._periods import window_bounds


_WINDOW_DAYS = 90  # M3 = ventana de exposure de 90 días (igual que meses=3 en el summary).


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


def _corte(filters: dict) -> date:
    # Igual que candidate_churn_window_summary: si hay filtro global (Desde/Hasta/Mes)
    # el fin de la ventana se ancla ahí; si no, corte/cutoff explícito o hoy (ARG).
    if filters and (filters.get("desde") or filters.get("hasta") or filters.get("mes")):
        _, corte = window_bounds(filters)
        return corte
    return (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )


# CTEs del cohorte M3 (Staffing, no-interna, start en ventana 90d, roll-up a candidato).
# Compartido por la dona, el detalle y el select de accounts para que todo reconcilie.
COHORT_CTES = """
    WITH ventana AS (
      SELECT %(corte)s::date AS corte_d, %(win_ini)s::date AS win_ini
    ),
    ho AS (
      SELECT
        h.candidate_id,
        h.account_id,
        h.opportunity_id,
        TRIM(h.inactive_reason) AS reason,
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
    ),
    detalle AS (
      SELECT
        ho.candidate_id, ho.account_id, ho.opportunity_id, ho.reason, ho.end_d,
        CASE
          WHEN ho.end_d IS NOT NULL AND ho.end_d <= v.corte_d THEN 'BAJA'
          WHEN COALESCE(ho.end_d, DATE '9999-12-31') > v.corte_d THEN 'ACTIVO'
          ELSE 'FUERA'
        END AS estado,
        -- Clasificación buyout vs real, igual que candidate_churn_window_summary.
        CASE
          WHEN ho.end_d IS NOT NULL AND ho.end_d <= v.corte_d
            AND ho.buyout_d IS NOT NULL AND ho.buyout_d >= DATE_TRUNC('month', ho.end_d)
            THEN 'BAJA_BUYOUT'
          WHEN ho.end_d IS NOT NULL AND ho.end_d <= v.corte_d
            THEN 'BAJA_REAL'
          ELSE NULL
        END AS baja_tipo
      FROM ho
      CROSS JOIN ventana v
      WHERE ho.start_d IS NOT NULL
        AND ho.start_d BETWEEN v.win_ini AND v.corte_d
    ),
    per_candidate AS (
      SELECT
        candidate_id,
        BOOL_OR(estado = 'ACTIVO')          AS is_active,
        BOOL_OR(baja_tipo = 'BAJA_REAL')    AS any_real
      FROM detalle GROUP BY candidate_id
    ),
    baja_hire AS (
      -- Candidato baja REAL = bajas_real de la card churn M3: no activo Y con al menos
      -- un hire dado de baja REAL (no buyout). Se toma el hire de baja real más reciente
      -- como representante (su razón/account/opp). Los buyouts NO cuentan.
      SELECT DISTINCT ON (d.candidate_id)
        d.candidate_id, d.account_id, d.opportunity_id, d.reason, d.end_d
      FROM detalle d
      JOIN per_candidate pc
        ON pc.candidate_id = d.candidate_id AND pc.is_active = FALSE AND pc.any_real
      WHERE d.baja_tipo = 'BAJA_REAL'
      ORDER BY d.candidate_id, d.end_d DESC NULLS LAST
    )
"""


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = _corte(filters)
    win_ini = corte - timedelta(days=_WINDOW_DAYS - 1)
    recruiter = str(filters.get("recruiter") or "").strip().lower()
    account = str(filters.get("account") or "").strip()
    reason = str(filters.get("reason") or "").strip()
    sql = COHORT_CTES + """
        SELECT
          bh.reason AS reason,
          COUNT(*)::int AS count,
          ROUND(100.0 * COUNT(*) / NULLIF(SUM(COUNT(*)) OVER (), 0), 1)::float AS share_pct
        FROM baja_hire bh
        LEFT JOIN opportunity o ON o.opportunity_id = bh.opportunity_id
        LEFT JOIN account a     ON a.account_id      = bh.account_id
        WHERE NULLIF(bh.reason, '') IS NOT NULL
          AND (%(recruiter)s = '' OR LOWER(TRIM(o.opp_hr_lead)) = %(recruiter)s)
          AND (%(account)s = '' OR TRIM(a.client_name) = %(account)s)
          AND (%(reason)s = '' OR bh.reason = %(reason)s)
        GROUP BY bh.reason
        ORDER BY count DESC, reason;
    """
    return sql, {
        "corte": corte, "win_ini": win_ini,
        "recruiter": recruiter, "account": account, "reason": reason,
    }


DATASET = {
    "key": "op_churn_reasons_m3",
    "label": "Operations · Razones de caída — churn M3 (%)",
    "dimensions": [{"key": "reason", "label": "Razón", "type": "string"}],
    "measures": [
        {"key": "count", "label": "Candidatos", "type": "number"},
        {"key": "share_pct", "label": "% del total", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
