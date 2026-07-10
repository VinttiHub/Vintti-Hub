"""Operations · detalle de close-win placements por origen del candidato.

Una fila por placement (hire de opp Close Win): origen · candidato · account ·
posición. Filtro `candorigin` = porción clickeada en la dona (vacío = todas).
"""
from __future__ import annotations

from .op_closewin_candidate_origin import ORIGIN_CASE
from ._periods import window_bounds


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    candorigin = str(filters.get("candorigin") or "").strip()
    lo, hi = window_bounds(filters)
    sql = f"""
        WITH base AS (
          SELECT {ORIGIN_CASE.format(col='ca.candidate_origin')} AS origin,
                 COALESCE(ca.name, '—') AS candidate_name,
                 COALESCE(a.client_name, '—') AS client_name,
                 COALESCE(op.opp_position_name, '—') AS opp_position_name
          FROM hire_opportunity ho
          JOIN opportunity op ON op.opportunity_id = ho.opportunity_id
            AND TRIM(op.opp_stage) = 'Close Win'
          JOIN candidates ca  ON ca.candidate_id = ho.candidate_id
          LEFT JOIN account a ON a.account_id = op.account_id
          WHERE NULLIF(op.opp_close_date::text, '')::date BETWEEN %(w_lo)s AND %(w_hi)s
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        )
        SELECT origin, candidate_name, client_name, opp_position_name
        FROM base
        WHERE (%(candorigin)s = '' OR origin = %(candorigin)s)
        ORDER BY origin, candidate_name;
    """
    return sql, {"candorigin": candorigin, "w_lo": lo, "w_hi": hi}


DATASET = {
    "key": "op_closewin_candidate_origin_detail",
    "label": "Operations · detalle close wins por origen del candidato",
    "dimensions": [
        {"key": "origin", "label": "Origen", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "client_name", "label": "Account", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
