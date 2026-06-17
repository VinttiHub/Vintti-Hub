"""Operations · detalle de Hunteados vs Postulados de UN mes (bucket clickeado).

Lista los candidatos taggeados (Hunteo / Applicant) cuyo `created_at` cae en el mes
del bucket seleccionado. Filtro `bucket` = inicio del mes clickeado (lo setea el drawer
de barras apiladas); default = mes actual.
"""
from __future__ import annotations

from datetime import date

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
    bucket = _parse_date(filters.get("bucket")) or _parse_date(filters.get("mes"))
    lo, hi = monthly_range(filters)
    sql = """
        WITH params AS (
          SELECT COALESCE(DATE_TRUNC('month', %(bucket)s::date)::date,
                          DATE_TRUNC('month', CURRENT_DATE)::date) AS mes_ini,
                 %(lo)s::date AS w_lo,
                 %(hi)s::date AS w_hi
        )
        SELECT
          TO_CHAR(c.created_at, 'YYYY-MM-DD') AS created_at,
          COALESCE(NULLIF(TRIM(c.name), ''), '—') AS candidate_name,
          CASE WHEN LOWER(TRIM(c.candidate_origin)) = 'hunteo' THEN 'Hunteo' ELSE 'Applicant' END AS origin,
          COALESCE(NULLIF(TRIM(c.candidate_source), ''), '—') AS candidate_source
        FROM candidates c
        CROSS JOIN params p
        WHERE c.created_at >= GREATEST(p.mes_ini, p.w_lo)
          AND c.created_at <= LEAST((p.mes_ini + INTERVAL '1 month - 1 day')::date, p.w_hi)
          AND LOWER(TRIM(c.candidate_origin)) IN ('hunteo', 'applicant', 'talentum applicant')
        ORDER BY origin, c.created_at DESC, candidate_name;
    """
    return sql, {"bucket": bucket, "lo": lo, "hi": hi}


DATASET = {
    "key": "op_hunteo_vs_applicant_monthly_detail",
    "label": "Operations · detalle Hunteados vs Postulados del mes",
    "dimensions": [
        {"key": "created_at", "label": "Creado", "type": "date"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "origin", "label": "Origen", "type": "string"},
        {"key": "candidate_source", "label": "Source", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
