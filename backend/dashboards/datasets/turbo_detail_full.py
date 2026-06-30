from __future__ import annotations

from datetime import date
from ._now import today_ar

from ._periods import window_bounds


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
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("mes"))
        or today_ar()
    )

    win_ini, win_fin = window_bounds(filters)
    # Una fila por turbo (reunión). Efectividad derivada de # perfiles obtenidos:
    #   Alta ≥ 6, Media 3–5, Baja < 3.
    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        )
        SELECT
          TO_CHAR(t.meeting_date::date, 'YYYY-MM-DD')           AS meeting_date,
          o.opp_position_name,
          a.client_name,
          a.industry                                            AS rubro,
          COALESCE(NULLIF(TRIM(u.nickname), ''),
                   NULLIF(TRIM(u.user_name), ''),
                   t.hr_lead)                                    AS hr_lead,
          t.candidates::int                                     AS candidates,
          CASE
            WHEN t.candidates >= 6 THEN 'Alta'
            WHEN t.candidates >= 3 THEN 'Media'
            ELSE 'Baja'
          END                                                   AS efectividad,
          -- Close Win solo si la opp está en stage Close Win Y su fecha de cierre
          -- es posterior (o igual) a la fecha del turbo.
          CASE WHEN TRIM(o.opp_stage) = 'Close Win'
                AND o.opp_close_date IS NOT NULL
                AND o.opp_close_date::date >= t.meeting_date::date
               THEN 'Sí' ELSE 'No' END                          AS close_win
        FROM turvo t
        JOIN opportunity o ON o.opportunity_id = t.opportunity_id
        LEFT JOIN account a ON a.account_id = o.account_id
        LEFT JOIN users u ON LOWER(TRIM(u.email_vintti)) = LOWER(TRIM(t.hr_lead))
        CROSS JOIN ventana v
        WHERE t.meeting_date::date BETWEEN v.win_ini AND v.win_fin
          AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
          -- Excluir recruiters que ya no trabajan en Vintti
          AND LOWER(TRIM(t.hr_lead)) <> 'agustina.barbero@vintti.com'
        ORDER BY t.meeting_date DESC, a.client_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "modelo": modelo, "corte": corte}


DATASET = {
    "key": "turbo_detail_full",
    "label": "Detalle de cada turbo (fecha, posición, cliente, rubro, recruiter, perfiles, efectividad)",
    "dimensions": [
        {"key": "meeting_date", "label": "Fecha", "type": "date"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "rubro", "label": "Rubro", "type": "string"},
        {"key": "hr_lead", "label": "Recruiter", "type": "string"},
        {"key": "efectividad", "label": "Efectividad", "type": "string"},
        {"key": "close_win", "label": "Close Win", "type": "string"},
    ],
    "measures": [
        {"key": "candidates", "label": "Perfiles obtenidos", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
