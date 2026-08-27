from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import prev_window_bounds, window_bounds


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

    # Deep Dive → NDA Signed — PER CLIENT, COHORTE PROPIA.
    # Denominador: CUENTAS con >=1 opp cuyo deep_dive_date cae en la ventana.
    # Numerador:   de esas, las que firmaron NDA (= pasan a sourcing).
    #
    # OJO: cada card del funnel tiene su PROPIA cohorte y NO encadenan entre sí — es
    # una decisión del negocio (ago-2026). El denominador de esta card NO es el
    # numerador de sql_to_deepdive_30d: son deep dives que ocurrieron en la ventana,
    # en su mayoría de cuentas que fueron SQL hace meses. Por eso los números de dos
    # cards contiguas no tienen por qué coincidir.
    #
    # Dedupe por account: 3 opps de un mismo cliente = 1 cliente.
    # Canal = account.where_come_from. Pertenencia M+B: account_manager ∈ M+B O la
    # cuenta tiene una opp con opp_sales_lead ∈ M+B (al ganar, el account_manager se
    # reasigna al AM post-venta y la cuenta se caería del funnel).
    win_ini, win_fin = window_bounds(filters)
    prev_ini, prev_fin = prev_window_bounds(filters)
    sql = """
        WITH opp AS (
          SELECT
            o.account_id,
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            NULLIF(o.deep_dive_date::text, '')::date AS dd_d,
            (NULLIF(o.nda_sent_date::text, '')::date IS NOT NULL) AS nda_sent,
            (NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL) AS signed_nda
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            -- Solo clientes NUEVOS: el funnel mide adquisición, no expansión. Una
            -- cuenta que ya era cliente antes de este evento (Elevate Clinics, 42 CW)
            -- abriendo otra posición NO es una venta nueva. Sin este filtro entraban
            -- 11 clientes existentes y el denominador casi se duplicaba.
            AND NOT EXISTS (
                  SELECT 1 FROM opportunity o3
                  WHERE o3.account_id = a.account_id
                    AND TRIM(o3.opp_stage) = 'Close Win'
                    AND NULLIF(o3.opp_close_date::text,'')::date < NULLIF(o.deep_dive_date::text, '')::date
              )
            AND (
                  TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
                OR EXISTS (
                       SELECT 1 FROM opportunity o2
                       WHERE o2.account_id = a.account_id
                         AND TRIM(LOWER(o2.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
                   )
            )
            AND (%(desde)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date <= %(hasta)s::date)
        ),
        cur AS (
          SELECT
            account_id,
            MIN(channel)        AS channel,
            BOOL_OR(nda_sent)   AS nda_sent,
            BOOL_OR(signed_nda) AS signed_nda
          FROM opp
          WHERE dd_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          GROUP BY account_id
        ),
        prev AS (
          SELECT account_id, BOOL_OR(signed_nda) AS signed_nda
          FROM opp
          WHERE dd_d BETWEEN %(prev_ini)s::date AND %(prev_fin)s::date
          GROUP BY account_id
        ),
        prev_rate AS (
          SELECT ROUND(
            COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0 / NULLIF(COUNT(*), 0), 1
          ) AS prev_total_pct
          FROM prev
        )
        SELECT
          COUNT(*) FILTER (WHERE channel='sales')::int                       AS sales_dd,
          COUNT(*) FILTER (WHERE channel='sales' AND signed_nda)::int        AS sales_nda,
          ROUND(COUNT(*) FILTER (WHERE channel='sales' AND signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0), 1)     AS sales_pct,

          COUNT(*) FILTER (WHERE channel='marketing')::int                   AS mkt_dd,
          COUNT(*) FILTER (WHERE channel='marketing' AND signed_nda)::int    AS mkt_nda,
          ROUND(COUNT(*) FILTER (WHERE channel='marketing' AND signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0), 1) AS mkt_pct,

          COUNT(*) FILTER (WHERE channel='referrals')::int                   AS ref_dd,
          COUNT(*) FILTER (WHERE channel='referrals' AND signed_nda)::int    AS ref_nda,
          ROUND(COUNT(*) FILTER (WHERE channel='referrals' AND signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0), 1) AS ref_pct,

          COUNT(*)::int                              AS total_dd,
          COUNT(*) FILTER (WHERE nda_sent)::int      AS total_nda_sent,
          COUNT(*) FILTER (WHERE signed_nda)::int    AS total_nda,
          ROUND(COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0
                / NULLIF(COUNT(*), 0), 1)            AS total_pct,
          pr.prev_total_pct,
          ROUND(
            COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0 / NULLIF(COUNT(*), 0)
            - COALESCE(pr.prev_total_pct, 0), 1
          ) AS total_pct_delta
        FROM cur
        CROSS JOIN prev_rate pr
        GROUP BY pr.prev_total_pct;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,
        "prev_ini": prev_ini, "prev_fin": prev_fin, "corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "deepdive_to_nda_30d",
    "label": "Deep Dive → NDA Signed por canal, per client (30d)",
    "dimensions": [],
    "measures": [
        {"key": "sales_dd", "label": "Sales · Clientes con Deep Dive", "type": "number"},
        {"key": "sales_nda", "label": "Sales · Firmaron NDA", "type": "number"},
        {"key": "sales_pct", "label": "Sales · DD→NDA %", "type": "percent"},
        {"key": "mkt_dd", "label": "Marketing · Clientes con Deep Dive", "type": "number"},
        {"key": "mkt_nda", "label": "Marketing · Firmaron NDA", "type": "number"},
        {"key": "mkt_pct", "label": "Marketing · DD→NDA %", "type": "percent"},
        {"key": "ref_dd", "label": "Referrals · Clientes con Deep Dive", "type": "number"},
        {"key": "ref_nda", "label": "Referrals · Firmaron NDA", "type": "number"},
        {"key": "ref_pct", "label": "Referrals · DD→NDA %", "type": "percent"},
        {"key": "total_dd", "label": "Total · Clientes con Deep Dive", "type": "number"},
        {"key": "total_nda_sent", "label": "Total · Clientes con NDA enviado", "type": "number"},
        {"key": "total_nda", "label": "Total · Firmaron NDA", "type": "number"},
        {"key": "total_pct", "label": "Total · DD→NDA %", "type": "percent"},
        {"key": "prev_total_pct", "label": "Total · DD→NDA % (período previo)", "type": "percent"},
        {"key": "total_pct_delta", "label": "Total · Δ DD→NDA (pp)", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
