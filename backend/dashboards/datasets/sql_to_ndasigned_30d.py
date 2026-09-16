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

    # SQL -> NDA Signed — TASA COMPUESTA, no una cohorte.
    #
    # pct = (SQL->Deep Dive) * (Deep Dive->NDA Signed), por canal y total. Los dos
    # factores salen de las DOS cards que ya estan en la pestana, con sus cohortes
    # tal cual: paso 1 ancla en account.sql_meeting_date, paso 2 en
    # opportunity.deep_dive_date. Las cohortes son DISTINTAS a proposito (decision
    # del negocio, ago-2026: ver deepdive_to_nda_30d.py), asi que esta card NO tiene
    # numerador ni denominador propios — por eso la UI muestra "A% x B%" y no "N / M".
    #
    # Port 1:1 de las CTEs de sql_to_deepdive_30d.py (acc) y deepdive_to_nda_30d.py
    # (opp + dedupe por account). Si se toca el filtro M+B, el de "solo clientes
    # nuevos" o el bucket de canal en alguno de esos dos, hay que tocarlo aca tambien
    # o la card deja de ser el producto de lo que se ve arriba.
    #
    # OJO con los nombres de columna: el auditor empareja sufijos (_dd,_nda,_cw) con
    # _sqls como numerador/denominador (audit/rules.py::_NUM_DEN_HINTS) y dispara
    # ratio_inverted si el primero es mayor. Aca step2_den (deep dives) puede superar
    # a step1_den (SQLs) legitimamente, por eso todo se llama step1_*/step2_*.
    win_ini, win_fin = window_bounds(filters)
    prev_ini, prev_fin = prev_window_bounds(filters)
    sql = """
        WITH acc AS (
          -- PASO 1 — R1: ancla SQL = fecha real del meeting (sql_meeting_date),
          -- estricto: solo cuentas con reunion real.
          SELECT
            a.account_id,
            a.sql_meeting_date AS sql_d,
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            EXISTS (
              SELECT 1 FROM opportunity o
              WHERE o.account_id = a.account_id
                AND NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
            ) AS reached_dd
          FROM account a
          WHERE a.sql_meeting_date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            -- Solo clientes NUEVOS: el funnel mide adquisicion, no expansion. Una
            -- cuenta que ya era cliente antes de este evento (Elevate Clinics, 42 CW)
            -- abriendo otra posicion NO es una venta nueva. Sin este filtro entraban
            -- 11 clientes existentes y el denominador casi se duplicaba.
            AND NOT EXISTS (
                  SELECT 1 FROM opportunity o3
                  WHERE o3.account_id = a.account_id
                    AND TRIM(o3.opp_stage) = 'Close Win'
                    AND NULLIF(o3.opp_close_date::text,'')::date < a.sql_meeting_date
              )
            AND (
                  TRIM(LOWER(a.account_manager)) IN ('bahia@vintti.com','mariano@vintti.com')
                OR EXISTS (
                       SELECT 1 FROM opportunity o2
                       WHERE o2.account_id = a.account_id
                         AND TRIM(LOWER(o2.opp_sales_lead)) IN ('bahia@vintti.com','mariano@vintti.com')
                   )
            )
            AND (%(desde)s::date IS NULL OR a.sql_meeting_date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR a.sql_meeting_date <= %(hasta)s::date)
        ),
        opp AS (
          -- PASO 2 — ancla en deep_dive_date, per client (dedupe mas abajo).
          SELECT
            o.account_id,
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'referrals'
              ELSE 'marketing'
            END AS channel,
            NULLIF(o.deep_dive_date::text, '')::date AS dd_d,
            (NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL) AS signed_nda
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE NULLIF(o.deep_dive_date::text, '')::date IS NOT NULL
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
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
        cur1 AS (
          SELECT * FROM acc
          WHERE sql_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
        ),
        cur2 AS (
          SELECT account_id, MIN(channel) AS channel, BOOL_OR(signed_nda) AS signed_nda
          FROM opp
          WHERE dd_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          GROUP BY account_id
        ),
        prev1 AS (
          SELECT * FROM acc
          WHERE sql_d BETWEEN %(prev_ini)s::date AND %(prev_fin)s::date
        ),
        prev2 AS (
          SELECT account_id, BOOL_OR(signed_nda) AS signed_nda
          FROM opp
          WHERE dd_d BETWEEN %(prev_ini)s::date AND %(prev_fin)s::date
          GROUP BY account_id
        ),
        -- Tasas sin redondear: el producto se calcula sobre el valor real, no sobre
        -- el entero que muestra la card, asi que en un borde los tres numeros que se
        -- ven pueden no cerrar por un punto. (Sin el signo de porcentaje en este
        -- comentario a proposito: un literal ahi rompe psycopg2 con
        -- "argument formats can't be mixed".)
        s1 AS (
          SELECT
            COUNT(*) FILTER (WHERE channel='sales')::int                    AS sales_den,
            COUNT(*) FILTER (WHERE channel='sales' AND reached_dd)::int     AS sales_num,
            COUNT(*) FILTER (WHERE channel='sales' AND reached_dd)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0)          AS sales_rate,
            COUNT(*) FILTER (WHERE channel='marketing')::int                AS mkt_den,
            COUNT(*) FILTER (WHERE channel='marketing' AND reached_dd)::int AS mkt_num,
            COUNT(*) FILTER (WHERE channel='marketing' AND reached_dd)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0)      AS mkt_rate,
            COUNT(*) FILTER (WHERE channel='referrals')::int                AS ref_den,
            COUNT(*) FILTER (WHERE channel='referrals' AND reached_dd)::int AS ref_num,
            COUNT(*) FILTER (WHERE channel='referrals' AND reached_dd)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0)      AS ref_rate,
            COUNT(*)::int                                                   AS tot_den,
            COUNT(*) FILTER (WHERE reached_dd)::int                         AS tot_num,
            COUNT(*) FILTER (WHERE reached_dd)::numeric * 100.0
              / NULLIF(COUNT(*), 0)                                         AS tot_rate
          FROM cur1
        ),
        s2 AS (
          SELECT
            COUNT(*) FILTER (WHERE channel='sales')::int                    AS sales_den,
            COUNT(*) FILTER (WHERE channel='sales' AND signed_nda)::int     AS sales_num,
            COUNT(*) FILTER (WHERE channel='sales' AND signed_nda)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE channel='sales'), 0)          AS sales_rate,
            COUNT(*) FILTER (WHERE channel='marketing')::int                AS mkt_den,
            COUNT(*) FILTER (WHERE channel='marketing' AND signed_nda)::int AS mkt_num,
            COUNT(*) FILTER (WHERE channel='marketing' AND signed_nda)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE channel='marketing'), 0)      AS mkt_rate,
            COUNT(*) FILTER (WHERE channel='referrals')::int                AS ref_den,
            COUNT(*) FILTER (WHERE channel='referrals' AND signed_nda)::int AS ref_num,
            COUNT(*) FILTER (WHERE channel='referrals' AND signed_nda)::numeric * 100.0
              / NULLIF(COUNT(*) FILTER (WHERE channel='referrals'), 0)      AS ref_rate,
            COUNT(*)::int                                                   AS tot_den,
            COUNT(*) FILTER (WHERE signed_nda)::int                         AS tot_num,
            COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0
              / NULLIF(COUNT(*), 0)                                         AS tot_rate
          FROM cur2
        ),
        p1 AS (
          SELECT COUNT(*) FILTER (WHERE reached_dd)::numeric * 100.0
                 / NULLIF(COUNT(*), 0) AS tot_rate
          FROM prev1
        ),
        p2 AS (
          SELECT COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0
                 / NULLIF(COUNT(*), 0) AS tot_rate
          FROM prev2
        )
        SELECT
          ROUND(s1.sales_rate, 1)                        AS sales_step1_pct,
          ROUND(s2.sales_rate, 1)                        AS sales_step2_pct,
          ROUND(s1.sales_rate * s2.sales_rate / 100.0, 1) AS sales_pct,

          ROUND(s1.mkt_rate, 1)                          AS mkt_step1_pct,
          ROUND(s2.mkt_rate, 1)                          AS mkt_step2_pct,
          ROUND(s1.mkt_rate * s2.mkt_rate / 100.0, 1)    AS mkt_pct,

          ROUND(s1.ref_rate, 1)                          AS ref_step1_pct,
          ROUND(s2.ref_rate, 1)                          AS ref_step2_pct,
          ROUND(s1.ref_rate * s2.ref_rate / 100.0, 1)    AS ref_pct,

          ROUND(s1.tot_rate, 1)                          AS total_step1_pct,
          ROUND(s2.tot_rate, 1)                          AS total_step2_pct,
          ROUND(s1.tot_rate * s2.tot_rate / 100.0, 1)    AS total_pct,

          s1.tot_num                                     AS step1_num,
          s1.tot_den                                     AS step1_den,
          s2.tot_num                                     AS step2_num,
          s2.tot_den                                     AS step2_den,

          ROUND(p1.tot_rate * p2.tot_rate / 100.0, 1)    AS prev_total_pct,
          ROUND(
            s1.tot_rate * s2.tot_rate / 100.0
            - COALESCE(p1.tot_rate * p2.tot_rate / 100.0, 0), 1
          )                                              AS total_pct_delta
        FROM s1
        CROSS JOIN s2
        CROSS JOIN p1
        CROSS JOIN p2;
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin,
        "prev_ini": prev_ini, "prev_fin": prev_fin,
        "corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "sql_to_ndasigned_30d",
    "label": "SQL → NDA Signed por canal, per client — compuesta (30d)",
    "dimensions": [],
    "measures": [
        {"key": "sales_step1_pct", "label": "Sales · SQL→DD %", "type": "percent"},
        {"key": "sales_step2_pct", "label": "Sales · DD→NDA %", "type": "percent"},
        {"key": "sales_pct", "label": "Sales · SQL→NDA % (compuesta)", "type": "percent"},
        {"key": "mkt_step1_pct", "label": "Marketing · SQL→DD %", "type": "percent"},
        {"key": "mkt_step2_pct", "label": "Marketing · DD→NDA %", "type": "percent"},
        {"key": "mkt_pct", "label": "Marketing · SQL→NDA % (compuesta)", "type": "percent"},
        {"key": "ref_step1_pct", "label": "Referrals · SQL→DD %", "type": "percent"},
        {"key": "ref_step2_pct", "label": "Referrals · DD→NDA %", "type": "percent"},
        {"key": "ref_pct", "label": "Referrals · SQL→NDA % (compuesta)", "type": "percent"},
        {"key": "total_step1_pct", "label": "Total · SQL→DD %", "type": "percent"},
        {"key": "total_step2_pct", "label": "Total · DD→NDA %", "type": "percent"},
        {"key": "total_pct", "label": "Total · SQL→NDA % (compuesta)", "type": "percent"},
        {"key": "step1_num", "label": "Paso 1 · SQLs que llegaron a Deep Dive", "type": "number"},
        {"key": "step1_den", "label": "Paso 1 · SQLs de la ventana", "type": "number"},
        {"key": "step2_num", "label": "Paso 2 · Clientes que firmaron NDA", "type": "number"},
        {"key": "step2_den", "label": "Paso 2 · Clientes con Deep Dive en la ventana", "type": "number"},
        {"key": "prev_total_pct", "label": "Total · SQL→NDA % (período previo)", "type": "percent"},
        {"key": "total_pct_delta", "label": "Total · Δ SQL→NDA (pp)", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
