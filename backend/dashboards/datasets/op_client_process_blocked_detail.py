"""Los candidatos que el gate de client process dejó fuera del envío al cliente.

Es el complemento de interviewed_sent_30d_detail: ese lista a los que SÍ se enviaron, éste
a los que no, con quién lo decidió y por qué.

Va en un bloque APARTE del drawer y no como una fila más de la lista de enviados a
propósito: el título de esa lista cuenta sus propias filas (data-reduce="count" en
dashboard.html), así que meter acá adentro a alguien que la card no cuenta haría que el
drawer diga un número y la card otro — y el auditor lo levanta como hero_vs_detail
CRITICAL todos los lunes (dashboards/audit/rules.py:309).

MISMA cohorte y MISMA ventana que la card (window_bounds + opp_close_date). Si usara otro
anclaje, el bloque se vaciaría a principio de mes o mostraría gente de otro período, que es
el problema que ya documentan los otros _detail.
"""
from __future__ import annotations

from datetime import date

from ._periods import window_bounds


def _resolve_modelo(filters: dict) -> str:
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
    return "Total"


def _resolve_resultado(filters: dict) -> str:
    raw = (filters.get("opp_stage") or filters.get("resultado") or "").strip()
    if raw in ("Close Win", "Closed Lost"):
        return raw
    return "Total"


def _resolve_int(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    resultado = _resolve_resultado(filters)
    opportunity_id = _resolve_int(filters.get("opportunity_id") or filters.get("opp_id"))
    desde, hasta = window_bounds(filters)

    # El JOIN a candidates_batches NO es decorativo: sólo interesan los que la recruiter
    # llegó a poner en un batch presentado. Una habilitación de un candidato que nunca
    # entró a un batch no es un "no enviado" de esta cohorte, es alguien que todavía no
    # llegó a esa instancia.
    sql = """
        SELECT DISTINCT
          o.opportunity_id::text            AS opportunity_id,
          COALESCE(a.client_name, '')       AS client_name,
          COALESCE(o.opp_position_name, '') AS opp_position_name,
          COALESCE(c.name, '')              AS candidate_name,
          cpc.status                        AS estado,
          CASE cpc.status
            WHEN 'rejected' THEN 'Bloqueado'
            ELSE 'Esperando aprobación'
          END
          || COALESCE(' · ' || NULLIF(TRIM(cpc.decided_by), ''), '')
          || COALESCE(' · ' || NULLIF(TRIM(cpc.decision_note), ''), '')
                                            AS motivo
        FROM cv_client_process_clearances cpc
        JOIN opportunity o ON o.opportunity_id = cpc.opportunity_id
        JOIN account a     ON a.account_id     = o.account_id
        JOIN batch b       ON b.opportunity_id = o.opportunity_id
        JOIN candidates_batches cb
          ON cb.batch_id = b.batch_id AND cb.candidate_id = cpc.candidate_id
        LEFT JOIN candidates c ON c.candidate_id = cpc.candidate_id
        WHERE cpc.status IN ('rejected', 'pending')
          AND TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
          AND COALESCE(a.vintti_internal, FALSE) = FALSE
          AND NULLIF(b.presentation_date::text, '') IS NOT NULL
          AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
          AND NULLIF(o.opp_close_date::text,'')::date >= %(desde)s::date
          AND NULLIF(o.opp_close_date::text,'')::date <  (%(hasta)s::date + INTERVAL '1 day')
          AND (%(modelo)s = 'Total' OR o.opp_model = %(modelo)s)
          AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
          AND (%(opportunity_id)s::int IS NULL OR o.opportunity_id = %(opportunity_id)s)
        ORDER BY candidate_name;
    """

    return sql, {
        "modelo": modelo,
        "resultado": resultado,
        "opportunity_id": opportunity_id,
        "desde": desde,
        "hasta": hasta,
    }


DATASET = {
    "key": "op_client_process_blocked_detail",
    "label": "Client process — Candidatos NO enviados (bloqueados o esperando el OK)",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "estado", "label": "Estado", "type": "string"},
        {"key": "motivo", "label": "Motivo", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
