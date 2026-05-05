from __future__ import annotations

from datetime import date, datetime, timezone


def _parse_date(value) -> date | None:
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


def _resolve_modelo(filters: dict) -> str | None:
    raw = (
        filters.get("modelo")
        or filters.get("modelo1")
        or filters.get("model")
        or filters.get("opp_model")
        or ""
    ).strip().lower()
    if raw in {"staffing", "staff"}:
        return "Staffing"
    if raw in {"recruiting", "recru"}:
        return "Recruiting"
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    cliente = (filters.get("cliente") or filters.get("client_name") or "").strip() or None
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("mes"))
        or datetime.now(timezone.utc).date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            (%(corte)s::date - INTERVAL '30 day')::date AS win_ini,
            %(corte)s::date                              AS win_fin
        ),
        opp AS (
          SELECT
            o.opportunity_id
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          CROSS JOIN ventana v
          WHERE TRIM(o.opp_stage) = 'Close Win'
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
            AND NULLIF(o.opp_close_date::text,'')::date >= v.win_ini
            AND NULLIF(o.opp_close_date::text,'')::date <  (v.win_fin + INTERVAL '1 day')
        ),
        sent AS (
          SELECT
            b.opportunity_id,
            COUNT(DISTINCT cb.candidate_id) AS enviados
          FROM batch b
          JOIN candidates_batches cb ON cb.batch_id = b.batch_id
          WHERE NULLIF(b.presentation_date::text,'') IS NOT NULL
          GROUP BY 1
        ),
        hired AS (
          SELECT
            ho.opportunity_id,
            COUNT(DISTINCT ho.candidate_id) AS contratados
          FROM hire_opportunity ho
          WHERE ho.opportunity_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
          GROUP BY 1
        ),
        agg AS (
          SELECT
            COALESCE(s.enviados, 0)    AS enviados,
            COALESCE(h.contratados, 0) AS contratados,
            CASE
              WHEN COALESCE(s.enviados, 0) > 0
                THEN (COALESCE(h.contratados, 0)::numeric * 100.0) / s.enviados
              ELSE NULL
            END AS conversion_pct
          FROM opp o
          LEFT JOIN sent  s ON s.opportunity_id = o.opportunity_id
          LEFT JOIN hired h ON h.opportunity_id = o.opportunity_id
        )
        SELECT
          ROUND(
            (SUM(contratados)::numeric * 100.0) / NULLIF(SUM(enviados), 0),
            2
          )::float                                   AS conversion_pct_general,
          ROUND(AVG(conversion_pct), 2)::float       AS promedio_conversion_pct_por_opportunity,
          SUM(enviados)::float                       AS total_enviados,
          SUM(contratados)::float                    AS total_contratados,
          COUNT(*)::int                              AS total_opps_close_win
        FROM agg;
    """

    return sql, {"modelo": modelo, "cliente": cliente, "corte": corte}


DATASET = {
    "key": "sent_hired_30d_summary",
    "label": "Enviados vs Contratados — Ventana 30 días (global)",
    "dimensions": [],
    "measures": [
        {"key": "conversion_pct_general", "label": "Conversión global %", "type": "percent"},
        {"key": "promedio_conversion_pct_por_opportunity", "label": "Promedio % por opp", "type": "percent"},
        {"key": "total_enviados", "label": "Total enviados", "type": "number"},
        {"key": "total_contratados", "label": "Total contratados", "type": "number"},
        {"key": "total_opps_close_win", "label": "Total opps Close Win", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
