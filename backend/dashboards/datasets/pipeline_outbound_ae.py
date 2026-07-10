"""Pipeline · Outbound (AE) — Worth, LTV y NDAs Signed.

Misma lógica de "pipeline abierto" que el Pipeline Explosion del Management
Dashboard (`active_pipeline.py`): se excluyen los stages deep dive / nda sent /
close win / close lost. Pero filtrado al canal Outbound y al book AE:
  account.where_come_from = 'Outbound'  AND  opp_sales_lead ∈ {AEs}

Métricas:
  - pipeline_worth        = Σ expected_revenue del pipeline abierto ($).
  - ltv_months            = meses promedio de vida por cliente Staffing
                            (mismo cálculo que Pipeline Explosion / Management,
                            global — no se acota a outbound porque es un promedio
                            de comportamiento de retención).
  - pipeline_ltv          = pipeline_worth × ltv_months  (Worth × LTV meses).
  - nda_signed_count      = opps activas (en pipeline) con NDA firmado
                            (nda_signature_or_start_date poblada).
  - nda_signed_worth      = Σ expected_revenue de esas opps con NDA firmado.
"""
from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")

# Mismas exclusiones de stage que active_pipeline.py (Pipeline Explosion).
# `%` doblado a `%%` para que psycopg2 no confunda los wildcards de ILIKE.
PIPELINE_EXCLUDE_STAGES_SQL = """
  AND o.opp_stage IS NOT NULL
  AND TRIM(o.opp_stage) <> ''
  AND o.opp_stage NOT ILIKE '%%deep dive%%'
  AND o.opp_stage NOT ILIKE '%%nda sent%%'
  AND o.opp_stage NOT ILIKE '%%close%%win%%'
  AND o.opp_stage NOT ILIKE '%%close%%lost%%'
"""


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

    sql = f"""
        WITH pipeline AS (
          SELECT
            o.opp_model,
            COALESCE(o.expected_revenue, 0)::numeric AS exp_rev,
            (NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL) AS nda_signed
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
            {PIPELINE_EXCLUDE_STAGES_SQL}
        ),
        agg AS (
          SELECT
            COUNT(*)::int                                                   AS pipeline_count,
            COUNT(*) FILTER (WHERE opp_model = 'Staffing')::int             AS pipeline_count_staffing,
            COUNT(*) FILTER (WHERE opp_model = 'Recruiting')::int           AS pipeline_count_recruiting,
            COALESCE(SUM(exp_rev), 0)::bigint                               AS pipeline_worth,
            COUNT(*) FILTER (WHERE nda_signed)::int                         AS nda_signed_count,
            COALESCE(SUM(exp_rev) FILTER (WHERE nda_signed), 0)::bigint     AS nda_signed_worth
          FROM pipeline
        ),
        -- LTV (meses promedio por cliente Staffing) — mismo cálculo que
        -- pipeline_cr_minus_churn.py / metrics_routes.py (Management). Global.
        ltv_base AS (
          SELECT c.candidate_id, c.start_d, c.end_d, c.account_id
          FROM (
            SELECT
              ho.candidate_id,
              ho.account_id,
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                WHEN NULLIF(ho.start_date::text,'') IS NOT NULL THEN ho.start_date::date
                ELSE NULL
              END AS start_d,
              CASE
                WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
                WHEN NULLIF(ho.end_date::text,'') IS NULL THEN NULL
                ELSE ho.end_date::date
              END AS end_d
            FROM hire_opportunity ho
            JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
            WHERE ho.account_id IS NOT NULL
              AND o.opp_model = 'Staffing'
          ) c
          WHERE c.start_d IS NOT NULL
        ),
        ltv_meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM generate_series(
            (SELECT MIN(start_d) FROM ltv_base),
            (SELECT MAX(COALESCE(end_d, CURRENT_DATE)) FROM ltv_base),
            INTERVAL '1 month'
          ) gs
        ),
        ltv_activos_mes AS (
          SELECT m.mes, b.account_id, COUNT(DISTINCT b.candidate_id) AS activos
          FROM ltv_meses m
          JOIN ltv_base b
            ON b.start_d < (m.mes + INTERVAL '1 month')
           AND (b.end_d IS NULL OR b.end_d >= m.mes)
          GROUP BY 1, 2
        ),
        ltv_duracion AS (
          SELECT account_id, COUNT(*) AS active_months
          FROM ltv_activos_mes
          WHERE activos > 0
          GROUP BY account_id
        ),
        ltv_months AS (
          SELECT COALESCE(ROUND(AVG(active_months)), 0)::int AS ltv
          FROM ltv_duracion
        )
        SELECT
          a.pipeline_count,
          a.pipeline_count_staffing,
          a.pipeline_count_recruiting,
          a.pipeline_worth,
          a.nda_signed_count,
          a.nda_signed_worth,
          l.ltv::int                                       AS ltv_months,
          (a.pipeline_worth * l.ltv)::bigint               AS pipeline_ltv
        FROM agg a
        CROSS JOIN ltv_months l;
    """

    return sql, {"corte": corte, "ae_leads": AE_LEADS}


DATASET = {
    "key": "pipeline_outbound_ae",
    "label": "Pipeline · Outbound (AE) — Worth, LTV, NDAs Signed",
    "dimensions": [],
    "measures": [
        {"key": "pipeline_count", "label": "Opps abiertas", "type": "number"},
        {"key": "pipeline_count_staffing", "label": "Opps abiertas — Staffing", "type": "number"},
        {"key": "pipeline_count_recruiting", "label": "Opps abiertas — Recruiting", "type": "number"},
        {"key": "pipeline_worth", "label": "Pipeline Worth ($)", "type": "currency"},
        {"key": "ltv_months", "label": "LTV (meses prom. por cliente)", "type": "number"},
        {"key": "pipeline_ltv", "label": "Pipeline LTV ($)", "type": "currency"},
        {"key": "nda_signed_count", "label": "Opps activas con NDA firmado", "type": "number"},
        {"key": "nda_signed_worth", "label": "Worth de opps con NDA firmado ($)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
