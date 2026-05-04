from __future__ import annotations

from datetime import date, datetime


LARA_EMAIL = "lara@vintti.com"


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


def _norm_stage_optional(value) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))
    stage = _norm_stage_optional(filters.get("opp_stage"))

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date                                AS cutoff_d,
            (%(corte)s::date - INTERVAL '30 days')::date   AS win_ini,
            %(corte)s::date                                AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            a.client_name,
            o.opp_position_name,
            NULLIF(o.nda_signature_or_start_date::text, '')::date AS nda_d,
            NULLIF(o.opp_close_date::text, '')::date              AS close_d,
            TRIM(o.opp_stage)                                      AS opp_stage
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          CROSS JOIN ventana v
          WHERE o.opportunity_id IS NOT NULL
            AND LOWER(TRIM(o.opp_sales_lead)) = %(lara)s
            AND TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND NULLIF(o.opp_close_date::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text, '')::date BETWEEN v.win_ini AND v.win_fin
            AND (%(stage)s::text IS NULL OR TRIM(o.opp_stage) = %(stage)s)
            AND (%(desde)s::date IS NULL OR NULLIF(o.opp_close_date::text, '')::date >= %(desde)s::date)
            AND (%(hasta)s::date IS NULL OR NULLIF(o.opp_close_date::text, '')::date <= %(hasta)s::date)
        )
        SELECT
          client_name,
          opp_position_name,
          TO_CHAR(nda_d,   'YYYY-MM-DD') AS nda_d,
          TO_CHAR(close_d, 'YYYY-MM-DD') AS close_d,
          opp_stage,
          CASE
            WHEN nda_d IS NOT NULL AND close_d IS NOT NULL
              THEN (close_d - nda_d)
            ELSE NULL
          END::int AS dias_nda_a_close,
          CASE
            WHEN opp_stage = 'Close Win'   THEN 'Close Win'
            WHEN opp_stage = 'Closed Lost' THEN 'Closed Lost'
            ELSE 'Sin cierre'
          END AS estado_final
        FROM base
        ORDER BY close_d DESC, opportunity_id;
    """

    return sql, {
        "lara": LARA_EMAIL,
        "corte": corte,
        "desde": desde,
        "hasta": hasta,
        "stage": stage,
    }


DATASET = {
    "key": "lara_winrate_30d_detail",
    "label": "Win Rate Re contrataciones (Lara) — Detalle ventana 30 días",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "nda_d", "label": "NDA", "type": "date"},
        {"key": "close_d", "label": "Cierre", "type": "date"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "estado_final", "label": "Estado", "type": "string"},
    ],
    "measures": [
        {"key": "dias_nda_a_close", "label": "Días NDA→Close", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
