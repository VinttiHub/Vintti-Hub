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

    # Una fila por CLIENTE con deep dive en la ventana (cohorte propia, por
    # deep_dive_date). Misma definición que deepdive_to_nda_30d.
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH opp AS (
          SELECT
            o.account_id,
            a.client_name,
            CASE
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound' THEN 'Sales'
              WHEN LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'referral' THEN 'Referrals'
              ELSE 'Marketing'
            END AS channel,
            COALESCE(NULLIF(TRIM(a.where_come_from), ''), 'NA') AS lead_source,
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
            AND NULLIF(o.deep_dive_date::text,'')::date
                BETWEEN %(win_ini)s::date AND %(win_fin)s::date
            AND (%(desde)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.deep_dive_date::text,'')::date <= %(hasta)s::date)
        )
        SELECT
          TO_CHAR(MAX(dd_d), 'YYYY-MM-DD')  AS deep_dive_date,
          MIN(channel)                      AS channel,
          MIN(client_name)                  AS client_name,
          MIN(lead_source)                  AS lead_source,
          COUNT(*)::int                     AS opps,
          CASE
            WHEN BOOL_OR(signed_nda) THEN 'NDA firmado → Sourcing'
            WHEN BOOL_OR(nda_sent)   THEN 'NDA enviado, sin firmar'
            ELSE 'Solo Deep Dive'
          END                               AS status
        FROM opp
        GROUP BY account_id
        ORDER BY MIN(channel), MAX(dd_d) DESC, MIN(client_name);
    """

    return sql, {
        "win_ini": win_ini, "win_fin": win_fin, "corte": corte, "desde": desde, "hasta": hasta}


DATASET = {
    "key": "deepdive_to_nda_30d_detail",
    "label": "Deep Dive → NDA — Detalle de clientes con Deep Dive en la ventana",
    "dimensions": [
        {"key": "deep_dive_date", "label": "Último Deep Dive", "type": "date"},
        {"key": "channel", "label": "Canal", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "lead_source", "label": "Origen", "type": "string"},
        {"key": "status", "label": "Estado", "type": "string"},
    ],
    "measures": [
        {"key": "opps", "label": "Opps con Deep Dive", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
