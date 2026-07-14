from __future__ import annotations

from datetime import date, datetime, timezone
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
    sql = """
        WITH ventana AS (
          SELECT %(win_ini)s::date AS win_ini, %(win_fin)s::date AS win_fin
        ),
        turbos AS (
          SELECT t.candidates
          FROM (
          -- Dedupe: el sync de Turvo crea varios registros por reunión (mismo opp+día,
          -- 0 candidatos). Colapsamos a 1 por (opp, día), quedándonos con el de MÁS
          -- candidatos para no perder turbos reales. Ver Hallazgo 30.
          SELECT DISTINCT ON (opportunity_id, meeting_date::date) *
          FROM turvo
          -- Solo reuniones turbo REALES: el nombre debe contener 'turbo'/'trbo'.
          -- La tabla turvo sincroniza TODAS las reuniones del calendar (interviews,
          -- calls, etc.); la mayoría no son turbos. Ver Hallazgo 30.
          WHERE meeting_name ~* 'turbo|trbo'
          ORDER BY opportunity_id, meeting_date::date, candidates DESC NULLS LAST, turvo_id DESC
        ) t
          JOIN opportunity o ON o.opportunity_id = t.opportunity_id
          LEFT JOIN account a ON a.account_id = o.account_id
          CROSS JOIN ventana v
          WHERE t.meeting_date::date BETWEEN v.win_ini AND v.win_fin
            AND (%(modelo)s::text IS NULL OR o.opp_model = %(modelo)s)
            -- Excluir recruiters inactivos (ya no trabajan en Vintti)
            AND LOWER(TRIM(t.hr_lead)) <> 'agustina.barbero@vintti.com'
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
        )
        SELECT
          COUNT(*)::int                                          AS turbos_total,
          COUNT(*) FILTER (WHERE candidates > 0)::int            AS turbos_con,
          ROUND(
            100.0 * COUNT(*) FILTER (WHERE candidates > 0)
            / NULLIF(COUNT(*), 0), 1
          )::float                                               AS pct_con_candidatos
        FROM turbos;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "modelo": modelo, "corte": corte}


DATASET = {
    "key": "turbo_with_candidates_30d_summary",
    "label": "% Turbos con candidatos — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "pct_con_candidatos", "label": "% con candidatos", "type": "percent"},
        {"key": "turbos_con", "label": "Turbos con candidatos", "type": "number"},
        {"key": "turbos_total", "label": "Turbos totales", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
