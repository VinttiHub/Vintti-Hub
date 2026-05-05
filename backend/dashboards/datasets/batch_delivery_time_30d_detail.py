from __future__ import annotations

from datetime import date, datetime


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


def _resolve_cliente(filters: dict) -> str | None:
    raw = (filters.get("cliente") or filters.get("client_name") or "").strip()
    return raw or None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    cliente = _resolve_cliente(filters)
    corte = (
        _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH params_final AS (
          SELECT %(corte)s::date AS corte_d, 30::int AS window_days
        ),
        opp AS (
          SELECT
            o.opportunity_id,
            a.client_name,
            o.opp_position_name,
            o.opp_model,
            o.opp_stage,
            NULLIF(o.nda_signature_or_start_date::text,'')::date AS pedido_ini_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opportunity_id IS NOT NULL
            AND o.opp_stage IN ('Sourcing','Interviewing','Negotiating')
            AND (%(modelo)s::text  IS NULL OR o.opp_model   = %(modelo)s)
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
        ),
        src AS (
          SELECT s.opportunity_id, NULLIF(s.since_sourcing::text,'')::date AS pedido_d
          FROM sourcing s
          WHERE NULLIF(s.since_sourcing::text,'') IS NOT NULL
        ),
        batches AS (
          SELECT
            b.batch_id, b.opportunity_id, b.batch_number,
            NULLIF(b.presentation_date::text,'')::date AS batch_d
          FROM batch b
          CROSS JOIN params_final p
          WHERE NULLIF(b.presentation_date::text,'') IS NOT NULL
            AND NULLIF(b.presentation_date::text,'')::date >  (p.corte_d - (p.window_days || ' days')::interval)::date
            AND NULLIF(b.presentation_date::text,'')::date <= p.corte_d
        ),
        pedidos AS (
          SELECT o.opportunity_id, o.pedido_ini_d AS pedido_d
          FROM opp o
          WHERE o.pedido_ini_d IS NOT NULL
          UNION ALL
          SELECT o.opportunity_id, s.pedido_d
          FROM opp o
          JOIN src s ON s.opportunity_id = o.opportunity_id
        ),
        batch_pedido AS (
          SELECT
            b.batch_id, b.opportunity_id, b.batch_number, b.batch_d,
            (
              SELECT MAX(p.pedido_d)
              FROM pedidos p
              WHERE p.opportunity_id = b.opportunity_id
                AND p.pedido_d <= b.batch_d
            ) AS pedido_d
          FROM batches b
          JOIN opp o ON o.opportunity_id = b.opportunity_id
        ),
        detalle AS (
          SELECT
            bp.batch_id,
            bp.batch_number,
            bp.batch_d,
            bp.opportunity_id,
            o.client_name,
            o.opp_position_name,
            o.opp_model,
            o.opp_stage,
            bp.pedido_d AS fecha_pedido,
            (bp.batch_d - bp.pedido_d)::int AS dias_entrega
          FROM batch_pedido bp
          JOIN opp o ON o.opportunity_id = bp.opportunity_id
          WHERE bp.pedido_d IS NOT NULL
            AND (bp.batch_d - bp.pedido_d)::int > 0
        )
        SELECT
          batch_id,
          batch_number,
          TO_CHAR(batch_d,      'YYYY-MM-DD') AS batch_d,
          opportunity_id::text                AS opportunity_id,
          client_name,
          opp_position_name,
          opp_model,
          opp_stage,
          TO_CHAR(fecha_pedido, 'YYYY-MM-DD') AS fecha_pedido,
          dias_entrega
        FROM detalle
        ORDER BY batch_d, opportunity_id, batch_number;
    """

    return sql, {"modelo": modelo, "cliente": cliente, "corte": corte}


DATASET = {
    "key": "batch_delivery_time_30d_detail",
    "label": "Tiempo promedio en entregar un batch — Detalle ventana 30 días",
    "dimensions": [
        {"key": "batch_id", "label": "Batch ID", "type": "number"},
        {"key": "batch_number", "label": "Batch #", "type": "number"},
        {"key": "batch_d", "label": "Fecha batch", "type": "date"},
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "fecha_pedido", "label": "Fecha pedido", "type": "date"},
    ],
    "measures": [
        {"key": "dias_entrega", "label": "Días entrega", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
