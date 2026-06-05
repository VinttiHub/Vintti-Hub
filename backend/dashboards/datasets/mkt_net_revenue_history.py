"""Marketing · Net revenue generado por origin — HISTÓRICO (barras apiladas).

El filtro `periodo` actúa como GRANULARIDAD del eje X:
  semana → últimas 8 semanas · mes → últimos 8 meses · q → últimos 6 Q · anio → últimos 4 años
Una fila por (bucket, origin) con net_revenue. bucket_start = fecha de inicio del
bucket (para el drill). Excluye outbound. Net revenue = fee Vintti
(Staffing ho.fee + Recruiting ho.revenue) de Close Wins por opp_close_date.
"""
from __future__ import annotations

from datetime import date, datetime


# (date_trunc unit, generate_series step, nº de buckets)
_GRAN = {
    "semana": ("week", "1 week", 8, "weeks"),
    "mes": ("month", "1 month", 8, "months"),
    "q": ("quarter", "3 months", 6, "months_q"),
    "anio": ("year", "1 year", 4, "years"),
}
_LABEL = {
    "week": "TO_CHAR(b.bucket_start, 'DD/MM')",
    "month": "TO_CHAR(b.bucket_start, 'Mon YY')",
    "quarter": "'Q' || EXTRACT(QUARTER FROM b.bucket_start)::int || ' ' || TO_CHAR(b.bucket_start, 'YY')",
    "year": "TO_CHAR(b.bucket_start, 'YYYY')",
}


def _parse_date(value):
    if not value:
        return None
    parts = str(value).strip().split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None
    return None


def _gran_key(filters: dict) -> str:
    p = str(filters.get("periodo") or filters.get("period") or "mes").strip().lower()
    if p in ("semana", "week", "w"):
        return "semana"
    if p in ("q", "trimestre", "quarter"):
        return "q"
    if p in ("anio", "año", "year", "anual", "ytd"):
        return "anio"
    return "mes"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or datetime.utcnow().date())
    gk = _gran_key(filters)
    unit, step, n, off_kind = _GRAN[gk]
    if off_kind == "months_q":
        offset = f"{(n - 1) * 3} months"
    else:
        offset = f"{n - 1} {off_kind}"
    label_expr = _LABEL[unit]

    sql = f"""
        WITH first_b AS (
          SELECT (DATE_TRUNC('{unit}', %(corte)s::date) - INTERVAL '{offset}')::date AS d0
        ),
        spine AS (
          SELECT gs::date AS bucket_start
          FROM first_b, generate_series((SELECT d0 FROM first_b), %(corte)s::date, INTERVAL '{step}') gs
        ),
        wins AS (
          SELECT o.opportunity_id, o.opp_model,
                 COALESCE(NULLIF(TRIM(a.where_come_from), ''), '(Sin origen)') AS origin,
                 NULLIF(o.opp_close_date::text, '')::date AS close_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND o.opp_model IN ('Staffing', 'Recruiting')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
        ),
        per_opp AS (
          SELECT w.origin, w.close_d,
            COALESCE(SUM(CASE WHEN w.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                              ELSE COALESCE(ho.fee, 0) END), 0)::numeric AS net_rev
          FROM wins w
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = w.opportunity_id
          GROUP BY w.opportunity_id, w.origin, w.close_d
        ),
        bucketed AS (
          SELECT DATE_TRUNC('{unit}', close_d)::date AS bucket_start, origin, SUM(net_rev) AS rev
          FROM per_opp
          WHERE close_d >= (SELECT d0 FROM first_b) AND close_d <= %(corte)s::date
          GROUP BY 1, origin
        )
        SELECT
          TO_CHAR(b.bucket_start, 'YYYY-MM-DD') AS bucket_start,
          {label_expr} AS bucket_label,
          COALESCE(bk.origin, '—') AS origin,
          COALESCE(ROUND(bk.rev), 0)::bigint AS net_revenue
        FROM spine b
        LEFT JOIN bucketed bk ON bk.bucket_start = b.bucket_start
        ORDER BY b.bucket_start, COALESCE(bk.rev, 0) DESC, origin;
    """
    return sql, {"corte": corte}


DATASET = {
    "key": "mkt_net_revenue_history",
    "label": "Marketing · Net revenue histórico por origin (barras apiladas)",
    "dimensions": [
        {"key": "bucket_start", "label": "Bucket", "type": "date"},
        {"key": "bucket_label", "label": "Período", "type": "string"},
        {"key": "origin", "label": "Origin", "type": "string"},
    ],
    "measures": [{"key": "net_revenue", "label": "Net revenue", "type": "currency"}],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
