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


def _resolve_cliente(filters: dict) -> str | None:
    raw = (filters.get("cliente") or filters.get("client_name") or "").strip()
    return raw or None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    cliente = _resolve_cliente(filters)

    sql = """
        WITH opp AS (
          SELECT
            o.opportunity_id,
            o.account_id,
            a.client_name,
            o.opp_position_name,
            o.opp_model,
            o.opp_stage,
            NULLIF(o.nda_signature_or_start_date::text,'')::date AS pedido_ini_d
          FROM opportunity o
          JOIN account a ON a.account_id = o.account_id
          WHERE o.opportunity_id IS NOT NULL
            AND o.opp_stage IN ('Sourcing','Interviewing','Negotiating')
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
        ),
        src AS (
          SELECT
            s.opportunity_id,
            NULLIF(s.since_sourcing::text,'')::date AS pedido_d
          FROM sourcing s
          WHERE NULLIF(s.since_sourcing::text,'') IS NOT NULL
        ),
        batches AS (
          SELECT
            b.batch_id,
            b.opportunity_id,
            b.batch_number,
            NULLIF(b.presentation_date::text,'')::date AS batch_d
          FROM batch b
          WHERE NULLIF(b.presentation_date::text,'') IS NOT NULL
        ),
        pedidos AS (
          SELECT
            o.opportunity_id, o.account_id, o.client_name, o.opp_position_name,
            o.opp_model, o.opp_stage, o.pedido_ini_d AS pedido_d
          FROM opp o
          WHERE o.pedido_ini_d IS NOT NULL
          UNION ALL
          SELECT
            o.opportunity_id, o.account_id, o.client_name, o.opp_position_name,
            o.opp_model, o.opp_stage, s.pedido_d
          FROM opp o
          JOIN src s ON s.opportunity_id = o.opportunity_id
        ),
        batch_pedido AS (
          SELECT
            b.batch_id,
            b.opportunity_id,
            b.batch_number,
            b.batch_d,
            (
              SELECT MAX(p.pedido_d)
              FROM pedidos p
              WHERE p.opportunity_id = b.opportunity_id
                AND p.pedido_d <= b.batch_d
            ) AS pedido_d
          FROM batches b
        ),
        detallado AS (
          SELECT
            p.opportunity_id,
            p.client_name,
            p.opp_position_name,
            p.opp_model,
            p.opp_stage,
            (bp.batch_d - bp.pedido_d)::int AS dias_entrega
          FROM batch_pedido bp
          JOIN pedidos p
            ON p.opportunity_id = bp.opportunity_id
           AND p.pedido_d       = bp.pedido_d
          WHERE bp.pedido_d IS NOT NULL
            AND (bp.batch_d - bp.pedido_d)::int > 0
        )
        SELECT
          opportunity_id::text AS opportunity_id,
          MIN(client_name)        AS client_name,
          MIN(opp_position_name)  AS opp_position_name,
          MIN(opp_model)          AS opp_model,
          MIN(opp_stage)          AS opp_stage,
          ROUND(AVG(dias_entrega))::int AS dias_promedio_entrega,
          COUNT(*)::int           AS total_batches
        FROM detallado
        GROUP BY opportunity_id
        ORDER BY dias_promedio_entrega, opportunity_id;
    """

    return sql, {"modelo": modelo, "cliente": cliente}


DATASET = {
    "key": "batch_delivery_time_history",
    "label": "Tiempo promedio en entregar un batch — por opp",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_model", "label": "Modelo", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
    ],
    "measures": [
        {"key": "dias_promedio_entrega", "label": "Días promedio entrega", "type": "number"},
        {"key": "total_batches", "label": "Total batches", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
