"""SQL → NDA signed conversion (Last 30d, Staffing).

CRM-only version: both numerator and denominator come from the local
`opportunity` table. "SQL" = every opportunity that entered the CRM
within the 30d window, "NDA signed" = subset that already has the
`nda_signature_or_start_date` filled.

  - SQL (denominator):  opps with `opp_model='Staffing'` and activity
                        in last 30d, where activity = COALESCE of
                        `nda_signature_or_start_date` or `opp_close_date`.
                        Matches the "opportunity_created_date" proxy
                        used in `recruiter_metrics_routes.py:486-489`.
  - NDA (numerator):    subset above with `nda_signature_or_start_date`
                        actually populated in the 30d window.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


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
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    win_ini = corte - timedelta(days=29)
    win_fin = corte

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            NULLIF(o.nda_signature_or_start_date::text, '')::date AS nda_d,
            COALESCE(
              NULLIF(o.nda_signature_or_start_date::text, '')::date,
              NULLIF(o.opp_close_date::text, '')::date
            ) AS opp_date
          FROM opportunity o
          WHERE o.opp_model = 'Staffing'
        ),
        sql_in_window AS (
          SELECT COUNT(*)::int AS sql_count
          FROM base b
          CROSS JOIN ventana v
          WHERE b.opp_date IS NOT NULL
            AND b.opp_date BETWEEN v.win_ini AND v.win_fin
        ),
        nda_in_window AS (
          SELECT COUNT(*)::int AS nda_count
          FROM base b
          CROSS JOIN ventana v
          WHERE b.nda_d IS NOT NULL
            AND b.nda_d BETWEEN v.win_ini AND v.win_fin
        )
        SELECT
          (SELECT win_ini FROM ventana)    AS ventana_desde,
          (SELECT win_fin FROM ventana)    AS ventana_hasta,
          s.sql_count,
          n.nda_count,
          ROUND(
            CASE
              WHEN s.sql_count = 0 THEN NULL
              ELSE 100.0 * n.nda_count::numeric / s.sql_count
            END, 2
          )::float                          AS sql_to_nda_pct
        FROM sql_in_window s
        CROSS JOIN nda_in_window n;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin}


DATASET = {
    "key": "sql_to_nda_30d",
    "label": "SQL → NDA signed (Staffing, 30d) — CRM only",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL (opps active in window)", "type": "number"},
        {"key": "nda_count", "label": "NDAs signed in window", "type": "number"},
        {"key": "sql_to_nda_pct", "label": "% SQL → NDA signed", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
