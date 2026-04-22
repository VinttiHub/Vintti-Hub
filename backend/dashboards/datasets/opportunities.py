from __future__ import annotations


def query(filters: dict, *_args, **_kwargs) -> tuple[str, tuple]:
    where = ["1=1"]
    params: list = []

    stage = filters.get("stage") or filters.get("opp_stage")
    if isinstance(stage, list) and stage:
        where.append("o.opp_stage = ANY(%s)")
        params.append(stage)
    elif isinstance(stage, str) and stage:
        where.append("o.opp_stage = %s")
        params.append(stage)

    model = filters.get("model") or filters.get("opp_model")
    if isinstance(model, str) and model:
        where.append("lower(o.opp_model) LIKE lower(%s)")
        params.append(f"{model}%")

    desde = filters.get("desde") or filters.get("from")
    hasta = filters.get("hasta") or filters.get("to")
    if desde:
        where.append("o.opp_close_date >= %s")
        params.append(desde)
    if hasta:
        where.append("o.opp_close_date <= %s")
        params.append(hasta)

    sql = f"""
        SELECT
          o.opportunity_id,
          o.account_id,
          o.opp_stage,
          o.opp_model,
          o.opp_type,
          o.opp_position_name,
          o.nda_signature_or_start_date,
          o.opp_close_date,
          o.expected_revenue,
          o.expected_fee,
          a.client_name,
          a.where_come_from AS lead_source
        FROM opportunity o
        LEFT JOIN account a ON a.account_id = o.account_id
        WHERE {' AND '.join(where)}
        ORDER BY o.opp_close_date DESC NULLS LAST
        LIMIT 5000;
    """
    return sql, tuple(params)


DATASET = {
    "key": "opportunities",
    "label": "Opportunities (denormalized)",
    "dimensions": [
        {"key": "opp_stage", "label": "Stage", "type": "categorical"},
        {"key": "opp_model", "label": "Model", "type": "categorical"},
        {"key": "opp_type", "label": "Type", "type": "categorical"},
        {"key": "client_name", "label": "Client", "type": "categorical"},
        {"key": "lead_source", "label": "Lead Source", "type": "categorical"},
        {"key": "opp_close_date", "label": "Close Date", "type": "date"},
        {"key": "nda_signature_or_start_date", "label": "NDA / Start Date", "type": "date"},
    ],
    "measures": [
        {"key": "expected_revenue", "label": "Expected Revenue", "type": "currency"},
        {"key": "expected_fee", "label": "Expected Fee", "type": "currency"},
        {"key": "opportunity_id", "label": "Count", "type": "number", "agg": "count"},
    ],
    "default_filters": {},
    "query": query,
}
