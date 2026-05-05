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
        detallado AS (
          SELECT
            bp.opportunity_id,
            bp.batch_d,
            (bp.batch_d - bp.pedido_d)::int AS dias_entrega
          FROM batch_pedido bp
          WHERE bp.pedido_d IS NOT NULL
            AND (bp.batch_d - bp.pedido_d)::int > 0
        )
        SELECT
          TO_CHAR(DATE_TRUNC('month', batch_d)::date, 'YYYY-MM-DD') AS mes_batch,
          COUNT(*)::int                                              AS total_batches,
          COUNT(DISTINCT opportunity_id)::int                        AS opps_con_batches,
          ROUND(AVG(dias_entrega))::int                              AS avg_dias_entrega
        FROM detallado
        GROUP BY 1
        ORDER BY 1;
    """

    return sql, {"modelo": modelo, "cliente": cliente}


DATASET = {
    "key": "batch_delivery_time_month_history",
    "label": "Tiempo promedio en entregar un batch — por mes",
    "dimensions": [
        {"key": "mes_batch", "label": "Mes batch", "type": "date"},
    ],
    "measures": [
        {"key": "total_batches", "label": "Total batches", "type": "number"},
        {"key": "opps_con_batches", "label": "Opps con batches", "type": "number"},
        {"key": "avg_dias_entrega", "label": "Días promedio entrega", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
