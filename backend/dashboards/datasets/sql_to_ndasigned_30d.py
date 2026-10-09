from __future__ import annotations

from ._periods import prev_window_bounds, window_bounds
from ._sql_hubspot import cur_and_prev, rate

_STEP2_SQL = """
        WITH opp AS (
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
        cur2 AS (
          SELECT account_id, MIN(channel) AS channel, BOOL_OR(signed_nda) AS signed_nda
          FROM opp
          WHERE dd_d BETWEEN %(win_ini)s::date AND %(win_fin)s::date
          GROUP BY account_id
        ),
        prev2 AS (
          SELECT account_id, BOOL_OR(signed_nda) AS signed_nda
          FROM opp
          WHERE dd_d BETWEEN %(prev_ini)s::date AND %(prev_fin)s::date
          GROUP BY account_id
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
        p2 AS (
          SELECT COUNT(*) FILTER (WHERE signed_nda)::numeric * 100.0
                 / NULLIF(COUNT(*), 0) AS tot_rate
          FROM prev2
        )
        SELECT
          s2.sales_den, s2.sales_num, s2.mkt_den, s2.mkt_num, s2.ref_den, s2.ref_num,
          s2.tot_den, s2.tot_num, p2.tot_rate AS prev_rate
        FROM s2 CROSS JOIN p2;
"""


def _r1(x):
    return round(x, 1) if x is not None else None


def _prod(a, b):
    return a * b / 100.0 if a is not None and b is not None else None


def _step2(filters: dict) -> dict:
    from db import get_connection
    from ._periods import _pd

    win_ini, win_fin = window_bounds(filters)
    prev_ini, prev_fin = prev_window_bounds(filters)
    params = {
        "win_ini": win_ini, "win_fin": win_fin, "prev_ini": prev_ini, "prev_fin": prev_fin,
        "desde": _pd(filters.get("desde")), "hasta": _pd(filters.get("hasta")),
    }
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_STEP2_SQL, params)
        cols = [c[0] for c in cur.description]
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    return dict(zip(cols, row)) if row else {}


def step_rates(filters: dict) -> dict:
    """Numeradores, denominadores y tasas sin redondear de los dos pasos (también los
    usa sql_to_ndasigned_30d_steps)."""
    filters = filters or {}
    cur, prev, _ini, _fin = cur_and_prev(filters)
    s2 = _step2(filters)

    def r2(num, den):
        return num * 100.0 / den if den else None

    out = {}
    for prefix, ch in (("sales", "sales"), ("mkt", "marketing"), ("ref", "referrals")):
        out[f"{prefix}_rate1"] = rate([r for r in cur if r["channel"] == ch])[2]
        out[f"{prefix}_rate2"] = r2(s2.get(f"{prefix}_num") or 0, s2.get(f"{prefix}_den") or 0)
    out["step1_num"], out["step1_den"], out["tot_rate1"] = rate(cur)
    out["step2_num"] = int(s2.get("tot_num") or 0)
    out["step2_den"] = int(s2.get("tot_den") or 0)
    out["tot_rate2"] = r2(out["step2_num"], out["step2_den"])
    prev_r2 = s2.get("prev_rate")
    out["prev_rate"] = _prod(rate(prev)[2], float(prev_r2) if prev_r2 is not None else None)
    return out


def compute(filters: dict, *_args, **_kwargs) -> list[dict]:
    # SQL -> NDA Signed — TASA COMPUESTA, no una cohorte.
    #
    # pct = (SQL->Deep Dive) * (Deep Dive->NDA Signed), por canal y total. Los dos
    # factores salen de las DOS cards que ya estan en la pestana, con sus cohortes
    # tal cual: paso 1 son los SQLs de HubSpot (_sql_hubspot.py, las mismas filas que
    # la card SQL -> Deep Dive), paso 2 ancla en opportunity.deep_dive_date. Las cohortes son DISTINTAS a proposito (decision
    # del negocio, ago-2026: ver deepdive_to_nda_30d.py), asi que esta card NO tiene
    # numerador ni denominador propios — por eso la UI muestra "A% x B%" y no "N / M".
    #
    # El paso 2 es un port 1:1 de la CTE de deepdive_to_nda_30d.py (opp + dedupe por
    # account). Si se toca el filtro M+B, el de "solo clientes nuevos" o el bucket de
    # canal alla, hay que tocarlo aca tambien o la card deja de ser el producto de lo
    # que se ve arriba.
    #
    # OJO con los nombres de columna: el auditor empareja sufijos (_dd,_nda,_cw) con
    # _sqls como numerador/denominador (audit/rules.py::_NUM_DEN_HINTS) y dispara
    # ratio_inverted si el primero es mayor. Aca step2_den (deep dives) puede superar
    # a step1_den (SQLs) legitimamente, por eso todo se llama step1_*/step2_*.
    st = step_rates(filters)
    out = {}
    for prefix in ("sales", "mkt", "ref"):
        a, b = st[f"{prefix}_rate1"], st[f"{prefix}_rate2"]
        out[f"{prefix}_step1_pct"] = _r1(a)
        out[f"{prefix}_step2_pct"] = _r1(b)
        out[f"{prefix}_pct"] = _r1(_prod(a, b))
    a, b = st["tot_rate1"], st["tot_rate2"]
    total = _prod(a, b)
    out.update({
        "total_step1_pct": _r1(a),
        "total_step2_pct": _r1(b),
        "total_pct": _r1(total),
        "step1_num": st["step1_num"],
        "step1_den": st["step1_den"],
        "step2_num": st["step2_num"],
        "step2_den": st["step2_den"],
        "prev_total_pct": _r1(st["prev_rate"]),
        "total_pct_delta": _r1(total - (st["prev_rate"] or 0)) if total is not None else None,
    })
    return [out]


DATASET = {
    "key": "sql_to_ndasigned_30d",
    "label": "SQL → NDA Signed por canal — compuesta (30d; paso 1 live HubSpot)",
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
    "compute": compute,
}
