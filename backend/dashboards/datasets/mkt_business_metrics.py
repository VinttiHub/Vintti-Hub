"""Marketing · Métricas de negocio — strip de KPIs company-wide (sin outbound).

Una sola fila con los totales del período seleccionado (semana / mes / q / anio)
y su variación vs el MISMO span del período anterior (MTD vs MTD, YTD vs YTD, etc.):

  - sqls         → cuentas que entraron al CRM (creation_date) en el período.
  - new_clients  → cuentas con su PRIMER Close Win (opp_close_date) en el período.
  - close_rate   → win rate por cliente de lo decidido (cierre en el período):
                   Close Win ÷ (Close Win + solo Closed Lost), a nivel cuenta.
  - net_rev      → fee de Vintti (Staffing ho.fee + Recruiting ho.revenue) de los
                   Close Win cerrados en el período.

Deltas: sqls/new_clients/net_rev en % de cambio; close_rate en puntos (pp).
MQLs no existe en el CRM (no hay etapa pre-SQL) → no se incluye.

Marketing-scope: excluye outbound, igual que el resto del tab.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from .mkt_sqls_by_origin import period_bounds


def _minus_months(d: date, n: int) -> date:
    total = (d.year * 12 + (d.month - 1)) - n
    y, m = divmod(total, 12)
    m += 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def _prev_bounds(ini: date, fin: date, label: str) -> tuple[date, date]:
    """Mismo span, un período hacia atrás (para comparación justa MTD/YTD/...)."""
    if label == "Semana":
        from datetime import timedelta
        return ini - timedelta(days=7), fin - timedelta(days=7)
    if label == "Trimestre":
        return _minus_months(ini, 3), _minus_months(fin, 3)
    if label == "Año":
        return date(ini.year - 1, 1, 1), _minus_months(fin, 12)
    # Mes
    return _minus_months(ini, 1), _minus_months(fin, 1)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    ini, fin, label = period_bounds(filters)
    pini, pfin = _prev_bounds(ini, fin, label)
    sql = """
        WITH acct AS (
          SELECT a.account_id, a.creation_date::date AS cd
          FROM account a
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
        ),
        sqls AS (
          SELECT
            COUNT(*) FILTER (WHERE cd BETWEEN %(ci)s::date AND %(cf)s::date)::int AS cur,
            COUNT(*) FILTER (WHERE cd BETWEEN %(pi)s::date AND %(pf)s::date)::int AS prev
          FROM acct WHERE cd IS NOT NULL
        ),
        first_close AS (
          SELECT o.account_id, MIN(NULLIF(o.opp_close_date::text, '')::date) AS fd
          FROM opportunity o
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          GROUP BY o.account_id
        ),
        newc AS (
          SELECT
            COUNT(*) FILTER (WHERE fc.fd BETWEEN %(ci)s::date AND %(cf)s::date)::int AS cur,
            COUNT(*) FILTER (WHERE fc.fd BETWEEN %(pi)s::date AND %(pf)s::date)::int AS prev
          FROM first_close fc
          JOIN account a ON a.account_id = fc.account_id
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
        ),
        dec AS (
          SELECT a.account_id,
            BOOL_OR(TRIM(o.opp_stage) = 'Close Win')
              FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(ci)s::date AND %(cf)s::date) AS won_cur,
            BOOL_OR(TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost'))
              FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(ci)s::date AND %(cf)s::date) AS dec_cur,
            BOOL_OR(TRIM(o.opp_stage) = 'Close Win')
              FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(pi)s::date AND %(pf)s::date) AS won_prev,
            BOOL_OR(TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost'))
              FILTER (WHERE NULLIF(o.opp_close_date::text, '')::date BETWEEN %(pi)s::date AND %(pf)s::date) AS dec_prev
          FROM account a
          JOIN opportunity o ON o.account_id = a.account_id
          WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
            AND TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          GROUP BY a.account_id
        ),
        cr AS (
          SELECT
            ROUND(COUNT(*) FILTER (WHERE won_cur)::numeric * 100.0
                  / NULLIF(COUNT(*) FILTER (WHERE dec_cur), 0), 1)::float AS cur,
            ROUND(COUNT(*) FILTER (WHERE won_prev)::numeric * 100.0
                  / NULLIF(COUNT(*) FILTER (WHERE dec_prev), 0), 1)::float AS prev
          FROM dec
        ),
        rev_opp AS (
          SELECT o.opportunity_id, NULLIF(o.opp_close_date::text, '')::date AS cdte,
            COALESCE(SUM(CASE WHEN o.opp_model = 'Recruiting' THEN COALESCE(ho.revenue, 0)
                              ELSE COALESCE(ho.fee, 0) END), 0)::numeric AS rev
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          LEFT JOIN hire_opportunity ho ON ho.opportunity_id = o.opportunity_id
          WHERE TRIM(o.opp_stage) = 'Close Win' AND o.opp_model IN ('Staffing', 'Recruiting')
            AND LOWER(TRIM(COALESCE(a.where_come_from, ''))) <> 'outbound'
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
          GROUP BY o.opportunity_id, cdte
        ),
        nr AS (
          SELECT
            COALESCE(SUM(rev) FILTER (WHERE cdte BETWEEN %(ci)s::date AND %(cf)s::date), 0)::bigint AS cur,
            COALESCE(SUM(rev) FILTER (WHERE cdte BETWEEN %(pi)s::date AND %(pf)s::date), 0)::bigint AS prev
          FROM rev_opp
        )
        SELECT
          sqls.cur                                     AS sqls,
          newc.cur                                     AS new_clients,
          cr.cur                                       AS close_rate,
          nr.cur                                       AS net_rev,
          CASE WHEN sqls.prev > 0 THEN ROUND((sqls.cur - sqls.prev)::numeric * 100.0 / sqls.prev)::float END        AS sqls_delta,
          CASE WHEN newc.prev > 0 THEN ROUND((newc.cur - newc.prev)::numeric * 100.0 / newc.prev)::float END        AS new_clients_delta,
          CASE WHEN cr.prev IS NOT NULL AND cr.cur IS NOT NULL THEN ROUND((cr.cur - cr.prev)::numeric)::float END    AS close_rate_delta,
          CASE WHEN nr.prev > 0 THEN ROUND((nr.cur - nr.prev)::numeric * 100.0 / nr.prev)::float END                 AS net_rev_delta,
          %(label)s::text                              AS period_label
        FROM sqls, newc, cr, nr;
    """
    return sql, {
        "ci": ini, "cf": fin, "pi": pini, "pf": pfin, "label": label,
    }


DATASET = {
    "key": "mkt_business_metrics",
    "label": "Marketing · Métricas de negocio (strip KPIs, período)",
    "dimensions": [
        {"key": "period_label", "label": "Período", "type": "string"},
    ],
    "measures": [
        {"key": "sqls", "label": "SQLs totales", "type": "number"},
        {"key": "new_clients", "label": "New active clients", "type": "number"},
        {"key": "close_rate", "label": "Tasa de cierre", "type": "percent"},
        {"key": "net_rev", "label": "Net revenue", "type": "currency"},
        {"key": "sqls_delta", "label": "Δ SQLs", "type": "number"},
        {"key": "new_clients_delta", "label": "Δ Clients", "type": "number"},
        {"key": "close_rate_delta", "label": "Δ Tasa cierre (pp)", "type": "number"},
        {"key": "net_rev_delta", "label": "Δ Net revenue", "type": "number"},
    ],
    "default_filters": {"periodo": "mes"},
    "query": query,
}
