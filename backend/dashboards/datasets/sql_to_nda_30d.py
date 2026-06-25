"""SQL → NDA signed conversion (Last 30d).

Source: local CRM only.
  - SQL (denominator): accounts whose `account.creation_date` falls in the
                       30d window. Mirrors the definition used by the
                       `SQL Sales` tile.
  - NDA (numerator):   of those same accounts, how many have at least one
                       opportunity with `nda_signature_or_start_date` set.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from ._now import today_ar

from ._periods import window_bounds


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
        or today_ar()
    )
    win_ini, win_fin = window_bounds(filters)

    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        sql_accounts AS (
          -- R1: ancla SQL = fecha real del meeting (sql_meeting_date), estricto: solo cuentas con reunión real.
          SELECT a.account_id
          FROM account a
          CROSS JOIN ventana v
          WHERE a.sql_meeting_date IS NOT NULL
            AND a.sql_meeting_date BETWEEN v.win_ini AND v.win_fin
        ),
        accounts_with_nda AS (
          SELECT DISTINCT s.account_id
          FROM sql_accounts s
          JOIN opportunity o ON o.account_id = s.account_id
          WHERE NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
        )
        SELECT
          (SELECT win_ini FROM ventana)                       AS ventana_desde,
          (SELECT win_fin FROM ventana)                       AS ventana_hasta,
          (SELECT COUNT(*)::int FROM sql_accounts)            AS sql_count,
          (SELECT COUNT(*)::int FROM accounts_with_nda)       AS nda_count,
          ROUND(
            CASE
              WHEN (SELECT COUNT(*) FROM sql_accounts) = 0 THEN NULL
              ELSE 100.0 * (SELECT COUNT(*) FROM accounts_with_nda)::numeric
                          / (SELECT COUNT(*) FROM sql_accounts)
            END, 2
          )::float                                            AS sql_to_nda_pct;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "sql_to_nda_30d",
    "label": "SQL → NDA signed (30d) — CRM accounts → opps con NDA",
    "dimensions": [
        {"key": "ventana_desde", "label": "Inicio ventana", "type": "date"},
        {"key": "ventana_hasta", "label": "Fin ventana", "type": "date"},
    ],
    "measures": [
        {"key": "sql_count", "label": "SQL (accounts CRM)", "type": "number"},
        {"key": "nda_count", "label": "Accounts con NDA", "type": "number"},
        {"key": "sql_to_nda_pct", "label": "% SQL → NDA signed", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
