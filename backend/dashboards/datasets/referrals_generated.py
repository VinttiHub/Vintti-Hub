from __future__ import annotations

from datetime import date, datetime

from ._periods import window_bounds


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
    # Referrals Generated = SQLs (accounts creadas) de origen Referral, AE (M+B por
    # account_manager), en 3 ventanas: últimos 30 días, últimos 7 días (semana) y
    # mes en curso (MTD). También el mes anterior (para delta) y target mensual.
    # cnt_30d sigue el filtro (MES → mes, CORTE → 30d rodante). Las ventanas de
    # CALENDARIO (semana 7d / MTD / mes anterior) se anclan a HOY e ignoran el corte.
    win_ini, win_fin = window_bounds(filters)
    hoy = datetime.utcnow().date()
    sql = """
        WITH base AS (
          SELECT a.creation_date AS d
          FROM account a
          WHERE a.creation_date IS NOT NULL
            AND LOWER(TRIM(COALESCE(a.where_come_from,''))) = 'referral'
            AND TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
        )
        SELECT
          COUNT(*) FILTER (WHERE d BETWEEN %(win_ini)s::date AND %(win_fin)s::date)::int AS cnt_30d,
          COUNT(*) FILTER (WHERE d BETWEEN (%(hoy)s::date - INTERVAL '6 days')::date  AND %(hoy)s::date)::int AS cnt_week,
          COUNT(*) FILTER (WHERE d BETWEEN DATE_TRUNC('month', %(hoy)s::date)::date    AND %(hoy)s::date)::int AS cnt_month,
          COUNT(*) FILTER (WHERE d BETWEEN DATE_TRUNC('month', %(hoy)s::date - INTERVAL '1 month')::date
                                       AND (DATE_TRUNC('month', %(hoy)s::date)::date - 1))::int AS cnt_prev_month
        FROM base;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin, "hoy": hoy}


DATASET = {
    "key": "referrals_generated",
    "label": "Referrals Generated — SQLs de origen Referral (AE)",
    "dimensions": [],
    "measures": [
        {"key": "cnt_30d", "label": "Últimos 30 días", "type": "number"},
        {"key": "cnt_week", "label": "Semana (7d)", "type": "number"},
        {"key": "cnt_month", "label": "Mes (MTD)", "type": "number"},
        {"key": "cnt_prev_month", "label": "Mes anterior", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
