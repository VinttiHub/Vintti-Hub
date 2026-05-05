from __future__ import annotations


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


def _resolve_opp_id(filters: dict) -> str | None:
    raw = (
        filters.get("opp_id_batch")
        or filters.get("Opp_ID")
        or filters.get("opp_id")
        or filters.get("opportunity_id")
        or ""
    )
    raw = str(raw).strip()
    return raw or None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    opp_id = _resolve_opp_id(filters)

    sql = """
        WITH opp AS (
          SELECT
            o.opportunity_id,
            o.opp_model,
            o.opp_stage,
            NULLIF(o.nda_signature_or_start_date::text,'')::date AS pedido_ini_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opportunity_id IS NOT NULL
            AND o.opp_stage IN ('Sourcing','Interviewing','Negotiating')
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
        ),
        src AS (
          SELECT
            s.opportunity_id,
            NULLIF(s.since_sourcing::text,'')::date AS pedido_d
          FROM sourcing s
          JOIN opp o ON o.opportunity_id = s.opportunity_id
          WHERE NULLIF(s.since_sourcing::text,'') IS NOT NULL
        ),
        batches AS (
          SELECT
            b.opportunity_id,
            b.batch_id,
            b.batch_number,
            NULLIF(b.presentation_date::text,'')::date AS presentation_d,
            o.opp_model
          FROM batch b
          JOIN opp o ON o.opportunity_id = b.opportunity_id
          WHERE NULLIF(b.presentation_date::text,'') IS NOT NULL
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
            b.opportunity_id,
            b.batch_id,
            b.batch_number,
            b.opp_model,
            b.presentation_d,
            (
              SELECT MAX(p.pedido_d)
              FROM pedidos p
              WHERE p.opportunity_id = b.opportunity_id
                AND p.pedido_d <= b.presentation_d
            ) AS pedido_d
          FROM batches b
        )
        SELECT
          bp.opportunity_id::text                              AS opportunity_id,
          bp.batch_number,
          bp.opp_model,
          TO_CHAR(bp.pedido_d,       'YYYY-MM-DD')             AS pedido_d,
          TO_CHAR(bp.presentation_d, 'YYYY-MM-DD')             AS batch_d,
          (bp.presentation_d - bp.pedido_d)::int               AS dias_entrega
        FROM batch_pedido bp
        WHERE bp.pedido_d IS NOT NULL
          AND (bp.presentation_d - bp.pedido_d)::int > 0
          AND (%(opp_id)s::text IS NULL OR bp.opportunity_id::text = %(opp_id)s)
        ORDER BY bp.opportunity_id, bp.batch_number;
    """

    return sql, {"modelo": modelo, "opp_id": opp_id}


DATASET = {
    "key": "batch_delivery_time_detail",
    "label": "Tiempo promedio en entregar un batch — detalle por batch",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "batch_number", "label": "Batch #", "type": "number"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "pedido_d", "label": "Fecha pedido", "type": "date"},
        {"key": "batch_d", "label": "Fecha batch", "type": "date"},
    ],
    "measures": [
        {"key": "dias_entrega", "label": "Días entrega", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
