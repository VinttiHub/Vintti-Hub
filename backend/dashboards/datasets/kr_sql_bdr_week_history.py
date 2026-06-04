"""Objetivo 2 · KR1 — SQLs por BDRs, histórico semanal (últimas 6 semanas).

Una fila por semana (Lun–Dom); la última = semana en curso (cap al corte).
SQL = account.creation_date · origen Outbound · owner AE (Mariano/Bahía).
Cada fila repite (constante) el `pct_vs_prev` (semana en curso vs la previa) y
`current_count`, para el footer del card.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")
WEEKS = 6


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (_parse_date(filters.get("corte")) or _parse_date(filters.get("hasta"))
             or datetime.utcnow().date())
    this_monday = corte - timedelta(days=corte.weekday())
    first_monday = this_monday - timedelta(days=7 * (WEEKS - 1))

    sql = """
        WITH params AS (
          SELECT %(first_monday)s::date AS first_mon,
                 %(this_monday)s::date  AS this_mon,
                 %(corte)s::date        AS corte_d
        ),
        weeks AS (
          SELECT gs::date AS wk_mon
          FROM params p, generate_series(p.first_mon, p.this_mon, INTERVAL '7 days') gs
        ),
        sqls AS (
          SELECT a.creation_date::date AS d
          FROM account a
          WHERE a.creation_date IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
            AND LOWER(TRIM(COALESCE(a.account_manager, ''))) IN %(ae_leads)s
        ),
        per_week AS (
          SELECT
            w.wk_mon,
            TO_CHAR(w.wk_mon, 'DD/MM') AS week_label,
            (SELECT COUNT(*) FROM sqls s
               WHERE s.d >= w.wk_mon
                 AND s.d <= LEAST(w.wk_mon + 6, (SELECT corte_d FROM params)))::int AS sqls
          FROM weeks w
        ),
        ranked AS (
          SELECT *,
            LAG(sqls) OVER (ORDER BY wk_mon) AS prev_sqls,
            ROW_NUMBER() OVER (ORDER BY wk_mon DESC) AS rn
          FROM per_week
        )
        SELECT
          week_label,
          TO_CHAR(wk_mon, 'YYYY-MM-DD') AS wk_mon,
          sqls,
          MAX(CASE WHEN rn = 1 THEN sqls END) OVER ()                            AS current_count,
          MAX(CASE WHEN rn = 1
                   THEN ROUND(100.0 * (sqls - prev_sqls) / NULLIF(prev_sqls, 0))
              END) OVER ()::int                                                  AS pct_vs_prev
        FROM ranked
        ORDER BY wk_mon;
    """
    return sql, {
        "ae_leads": AE_LEADS,
        "first_monday": first_monday,
        "this_monday": this_monday,
        "corte": corte,
    }


DATASET = {
    "key": "kr_sql_bdr_week_history",
    "label": "Obj2 KR1 · SQLs por BDRs — histórico semanal",
    "dimensions": [
        {"key": "week_label", "label": "Semana", "type": "string"},
        {"key": "wk_mon", "label": "Lunes", "type": "date"},
    ],
    "measures": [
        {"key": "sqls", "label": "SQLs", "type": "number"},
        {"key": "current_count", "label": "Semana en curso", "type": "number"},
        {"key": "pct_vs_prev", "label": "Δ% vs semana anterior", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
