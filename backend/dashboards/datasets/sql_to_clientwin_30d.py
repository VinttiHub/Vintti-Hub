from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

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
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or today_ar()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    # SQL → Closed Win — PER CLIENT, ANCLA POR FECHA DE CIERRE (spec Bahía p.4:
    # "de todos los clients new que ingresaron al Hub, cuantos se califican como
    #  closed win, sobre los que califican como close lost").
    #
    # Cohorte: los clientes que CERRARON en la ventana (opp_close_date), sin importar
    # cuándo entraron como SQL. Al anclar por cierre, "los que ya se definieron" es
    # automático — todos lo están.
    #
    # Diferencia con nda_to_clientwin_30d: esta NO exige haber pasado por sourcing,
    # así que incluye a los que se cayeron antes de firmar el NDA. Por eso su
    # denominador es mayor y el % sale igual o menor.
    #
    # Exige sql_meeting_date, igual que sql_to_deepdive_30d: las dos cards dicen "SQL"
    # y tienen que hablar del MISMO universo (cuentas con reunión real de SQL). El
    # campo se carga desde nov-2025, pero en las ventanas que se usan casi todos los
    # cierres ya lo tienen: a 30d el gate cuesta 1 cliente, a 90d cuesta 7.
    #
    # DEDUPE per client: un cliente con Close Win Y Closed Lost cuenta como GANADO.
    # M+B por opp_sales_lead (ver _sales_scope: account_manager se reasigna al ganar).
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH cur AS (
          SELECT
            o.account_id,
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            BOOL_OR(TRIM(o.opp_stage) = 'Close Win') AS won
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND a.sql_meeting_date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND TRIM(LOWER(o.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
            AND NULLIF(o.opp_close_date::text, '')::date
                BETWEEN %(win_ini)s::date AND %(win_fin)s::date
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text,'')::date <= %(hasta)s::date)
          GROUP BY o.account_id, a.where_come_from
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales')::int                  AS sales_sql,
          COUNT(*) FILTER (WHERE channel='sales' AND won)::int          AS sales_win,
          ROUND(COUNT(*) FILTER (WHERE channel='sales' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1) AS sales_pct,

          COUNT(*) FILTER (WHERE channel='marketing')::int                  AS mkt_sql,
          COUNT(*) FILTER (WHERE channel='marketing' AND won)::int          AS mkt_win,
          ROUND(COUNT(*) FILTER (WHERE channel='marketing' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1) AS mkt_pct,

          COUNT(*) FILTER (WHERE channel='referrals')::int                  AS ref_sql,
          COUNT(*) FILTER (WHERE channel='referrals' AND won)::int          AS ref_win,
          ROUND(COUNT(*) FILTER (WHERE channel='referrals' AND won)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1) AS ref_pct,

          COUNT(*)::int                     AS total_sql,
          COUNT(*) FILTER (WHERE won)::int  AS total_win,
          ROUND(COUNT(*) FILTER (WHERE won)::numeric * 100.0
                / NULLIF(COUNT(*), 0), 1)   AS total_pct
        FROM cur;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin, "corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_clientwin_30d",
    "label": "SQL → Closed Win por canal, per client (30d, AE)",
    "dimensions": [],
    "measures": [
        {"key": "sales_sql", "label": "Sales · Clientes cerrados", "type": "number"},
        {"key": "sales_win", "label": "Sales · Close Win", "type": "number"},
        {"key": "sales_pct", "label": "Sales · SQL→Win %", "type": "percent"},
        {"key": "mkt_sql", "label": "Marketing · Clientes cerrados", "type": "number"},
        {"key": "mkt_win", "label": "Marketing · Close Win", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · SQL→Win %", "type": "percent"},
        {"key": "ref_sql", "label": "Referrals · Clientes cerrados", "type": "number"},
        {"key": "ref_win", "label": "Referrals · Close Win", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · SQL→Win %", "type": "percent"},
        {"key": "total_sql", "label": "Total · Clientes cerrados en la ventana", "type": "number"},
        {"key": "total_win", "label": "Total · Close Win", "type": "number"},
        {"key": "total_pct", "label": "Total · SQL→Win %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
