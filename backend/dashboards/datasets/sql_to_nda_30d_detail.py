"""SQL → NDA signed detail (Last 30d).

Lists every CRM account whose `creation_date` falls in the 30d window (the
"SQL" denominator) together with whether it already has an opportunity with
`nda_signature_or_start_date` set (the "NDA" numerator).
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
          SELECT a.account_id, a.client_name,
                 a.sql_meeting_date AS creation_d
          FROM account a
          CROSS JOIN ventana v
          WHERE a.sql_meeting_date IS NOT NULL
            AND a.sql_meeting_date BETWEEN v.win_ini AND v.win_fin
        ),
        nda_per_account AS (
          SELECT
            o.account_id,
            MIN(NULLIF(o.nda_signature_or_start_date::text, '')::date) AS first_nda_d
          FROM opportunity o
          WHERE o.account_id IS NOT NULL
            AND NULLIF(o.nda_signature_or_start_date::text, '') IS NOT NULL
          GROUP BY o.account_id
        )
        SELECT
          s.client_name,
          s.creation_d                                     AS creation_d,
          n.first_nda_d                                    AS nda_d,
          CASE WHEN n.first_nda_d IS NULL THEN 'No' ELSE 'Sí' END AS has_nda,
          CASE WHEN n.first_nda_d IS NULL THEN 0 ELSE 1 END      AS nda_flag
        FROM sql_accounts s
        LEFT JOIN nda_per_account n USING (account_id)
        ORDER BY (n.first_nda_d IS NULL), s.creation_d DESC, s.client_name;
    """

    return sql, {
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "sql_to_nda_30d_detail",
    "label": "SQL → NDA signed (30d) — detalle accounts",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "creation_d", "label": "Creación", "type": "date"},
        {"key": "nda_d", "label": "NDA", "type": "date"},
        {"key": "has_nda", "label": "Con NDA", "type": "string"},
    ],
    "measures": [
        {"key": "nda_flag", "label": "NDA flag", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
