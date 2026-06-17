"""Operations · Hunteados vs Postulados (mensual, YTD).

Cuenta candidatos por mes de `candidates.created_at` (año en curso), clasificando
`candidate_origin`:
  - 'Hunteo'                           → Hunteo (hunteado)
  - 'Applicant' / 'Talentum applicant' → Applicant (postulado)
Universo = TODOS los candidatos taggeados (sin importar etapa). Los sin origen quedan
fuera. Una fila por (mes, origen) con `cnt`, para barras apiladas Hunteo/Applicant.
"""
from __future__ import annotations

from datetime import date, datetime

from ._period import monthly_range


def _parse_date(value):
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Rango de meses: Mes/Desde-Hasta > Corte (ventana 30d) > YTD por defecto.
    lo, hi = monthly_range(filters)
    sql = """
        WITH params AS (
          SELECT DATE_TRUNC('month', %(lo)s::date)::date AS lo_mes,
                 %(lo)s::date AS lo_real,
                 %(hi)s::date AS hi_d
        ),
        meses AS (
          SELECT DATE_TRUNC('month', gs)::date AS mes
          FROM params p, generate_series(p.lo_mes, p.hi_d, INTERVAL '1 month') gs
        ),
        origins AS (SELECT UNNEST(ARRAY['Hunteo', 'Applicant']) AS origin),
        counts AS (
          SELECT CASE
                   WHEN LOWER(TRIM(c.candidate_origin)) = 'hunteo' THEN 'Hunteo'
                   ELSE 'Applicant'
                 END AS origin,
                 DATE_TRUNC('month', c.created_at)::date AS mes,
                 COUNT(*)::int AS cnt
          FROM candidates c, params p
          WHERE c.created_at IS NOT NULL
            AND LOWER(TRIM(c.candidate_origin)) IN ('hunteo', 'applicant', 'talentum applicant')
            AND c.created_at BETWEEN p.lo_real AND p.hi_d
          GROUP BY 1, 2
        )
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM-DD') AS bucket_start,
          (ARRAY['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'])[EXTRACT(MONTH FROM m.mes)::int] AS bucket_label,
          o.origin AS origin,
          COALESCE(ct.cnt, 0)::int AS cnt
        FROM meses m
        CROSS JOIN origins o
        LEFT JOIN counts ct ON ct.mes = m.mes AND ct.origin = o.origin
        ORDER BY m.mes, o.origin;
    """
    return sql, {"lo": lo, "hi": hi}


DATASET = {
    "key": "op_hunteo_vs_applicant_monthly",
    "label": "Operations · Hunteados vs Postulados (mensual, YTD)",
    "dimensions": [
        {"key": "bucket_start", "label": "Mes", "type": "date"},
        {"key": "bucket_label", "label": "Mes", "type": "string"},
        {"key": "origin", "label": "Origen", "type": "string"},
    ],
    "measures": [{"key": "cnt", "label": "Candidatos", "type": "number"}],
    "default_filters": {},
    "query": query,
}
