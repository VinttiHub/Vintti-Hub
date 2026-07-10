"""Pipeline · Outbound (AE) — detalle de opps abiertas (drawer Worth / LTV).

Lista las oportunidades del pipeline abierto (mismas exclusiones de stage que
active_pipeline.py), canal Outbound + book AE. Si `only_nda` es truthy, filtra
a las que tienen NDA firmado (nda_signature_or_start_date poblada).
"""
from __future__ import annotations


AE_LEADS = ("mariano@vintti.com", "bahia@vintti.com")

PIPELINE_EXCLUDE_STAGES_SQL = """
  AND o.opp_stage IS NOT NULL
  AND TRIM(o.opp_stage) <> ''
  AND o.opp_stage NOT ILIKE '%%deep dive%%'
  AND o.opp_stage NOT ILIKE '%%nda sent%%'
  AND o.opp_stage NOT ILIKE '%%close%%win%%'
  AND o.opp_stage NOT ILIKE '%%close%%lost%%'
"""


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "si", "sí")


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    only_nda = _truthy(filters.get("only_nda"))
    nda_clause = (
        "AND NULLIF(o.nda_signature_or_start_date::text, '')::date IS NOT NULL"
        if only_nda
        else ""
    )

    sql = f"""
        SELECT
          a.client_name,
          o.opp_position_name,
          TRIM(o.opp_stage)                                   AS opp_stage,
          TRIM(o.opp_model)                                   AS model,
          COALESCE(o.expected_revenue, 0)::bigint             AS expected_revenue,
          TO_CHAR(o.nda_signature_or_start_date, 'YYYY-MM-DD') AS nda_signed_date
        FROM opportunity o
        JOIN account a ON a.account_id = o.account_id
        WHERE LOWER(TRIM(COALESCE(a.where_come_from, ''))) = 'outbound'
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND LOWER(TRIM(COALESCE(o.opp_sales_lead, ''))) IN %(ae_leads)s
          {PIPELINE_EXCLUDE_STAGES_SQL}
          {nda_clause}
        ORDER BY expected_revenue DESC, a.client_name;
    """

    return sql, {"ae_leads": AE_LEADS}


DATASET = {
    "key": "pipeline_outbound_ae_detail",
    "label": "Pipeline · Outbound (AE) — detalle opps abiertas",
    "dimensions": [
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "opp_stage", "label": "Stage", "type": "string"},
        {"key": "model", "label": "Modelo", "type": "string"},
        {"key": "nda_signed_date", "label": "NDA firmado", "type": "date"},
    ],
    "measures": [
        {"key": "expected_revenue", "label": "Expected revenue ($)", "type": "currency"},
    ],
    "default_filters": {},
    "query": query,
}
