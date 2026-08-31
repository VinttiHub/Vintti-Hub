from __future__ import annotations

from datetime import date, datetime, timezone

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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    modelo = _resolve_modelo(filters)
    resultado = _resolve_resultado(filters)
    # R16: usar la MISMA ventana que la card summary y que el detail. Antes esto tenía
    # la ventana hardcodeada (corte - 29 días, con fallback a CURRENT_DATE en vez de
    # today_ar) e interpretaba un filtro `mes` como fecha de corte en vez de mes
    # calendario → con cualquier filtro de período la gráfica no cuadraba con la card.
    win_ini, win_fin = window_bounds(filters)

    # R16: misma redefinición que interviewed_sent_30d_summary — el denominador es
    # opportunity.cantidad_entrevistados (entrevistas de Vintti/Apriora) y el numerador
    # son los candidatos enviados al cliente, capado al 100 por opp. La measure sigue
    # llamándose `entrevistados_sobre_enviados_pct` (el HTML la usa en data-y y el seed en
    # mapping.y); su significado ahora es enviados / entrevistados.
    # 2026-08-31 (owner): mismo filtro que la card — los candidatos con status
    # 'Rejected By Sales' no cuentan como enviados (ver el comentario largo en
    # interviewed_sent_30d_summary.py). Va en el numerador, no en el WHERE, para que una
    # opp cuyos presentados fueron todos rechazados por sales siga apareciendo con 0.
    # Las opps SIN el campo cargado se listan igual (decisión de la owner: el hueco tiene
    # que verse para que alguien lo cargue), con ratio_label = "sin dato".
    # OJO con el tipo del pct: se devuelve como TEXTO. Si fuera NULL, el renderer hace
    # `+r[yKey]` y `+null === 0` → dibujaría esas opps como 0 por ciento. Un texto no
    # numérico da NaN, y projectPoints lo marca valid:false y no dibuja el punto
    # (control-dashboard.js:136-141), que es justo lo que queremos: la opp aparece en la
    # lista del drawer pero no inventa un valor en la gráfica.
    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            a.client_name,
            o.opp_position_name,
            TRIM(o.opp_stage) AS opp_stage,
            NULLIF(o.cantidad_entrevistados, 0)::numeric AS entrevistados,
            cb.candidate_id,
            (LOWER(TRIM(cb.status)) = 'rejected by sales') AS rechazado_por_sales
          FROM candidates_batches cb
          JOIN batch b ON b.batch_id = cb.batch_id
          JOIN opportunity o ON o.opportunity_id = b.opportunity_id
          JOIN account a ON a.account_id = o.account_id
          CROSS JOIN ventana v
          WHERE TRIM(o.opp_stage) IN ('Close Win', 'Closed Lost')
            AND COALESCE(a.vintti_internal, FALSE) = FALSE
            AND NULLIF(b.presentation_date::text, '') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'') IS NOT NULL
            AND NULLIF(o.opp_close_date::text,'')::date >= v.win_ini
            AND NULLIF(o.opp_close_date::text,'')::date <  (v.win_fin + INTERVAL '1 day')
            AND (%(modelo)s = 'Total' OR o.opp_model = %(modelo)s)
            AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
        ),
        por_opp AS (
          SELECT
            opportunity_id,
            client_name,
            opp_position_name,
            opp_stage,
            entrevistados,
            COUNT(DISTINCT candidate_id)
              FILTER (WHERE NOT COALESCE(rechazado_por_sales, FALSE)) AS enviados
          FROM base
          GROUP BY 1, 2, 3, 4, 5
        ),
        capped AS (
          SELECT
            opportunity_id,
            client_name,
            opp_position_name,
            opp_stage,
            entrevistados,
            enviados AS enviados_raw,
            -- LEAST() ignora los NULL (LEAST(9, NULL) = 9), así que el CASE es necesario
            -- para que las opps sin dato no queden "capadas" a su propio total.
            CASE
              WHEN entrevistados IS NULL THEN NULL
              ELSE LEAST(enviados, entrevistados)
            END AS enviados_cap
          FROM por_opp
        )
        SELECT
          opportunity_id::text                    AS opportunity_id,
          client_name,
          opp_position_name,
          opp_stage                               AS resultado,
          COALESCE(enviados_cap, enviados_raw)::float
                                                  AS candidatos_enviados,
          entrevistados::float                    AS candidatos_entrevistados,
          CASE
            WHEN entrevistados IS NULL THEN 'sin dato'
            ELSE ROUND((enviados_cap * 100.0) / entrevistados, 2)::text
          END                                     AS entrevistados_sobre_enviados_pct,
          CASE
            WHEN entrevistados IS NULL
              THEN ROUND(enviados_raw)::int::text || ' enviado'
                   || CASE WHEN ROUND(enviados_raw)::int = 1 THEN '' ELSE 's' END
                   || ' · sin dato de entrevistados'
            ELSE ROUND(enviados_cap)::int::text || ' / ' || ROUND(entrevistados)::int::text
                 || ' · ' || ROUND((enviados_cap * 100.0) / entrevistados)::int::text || '%%'
          END                                     AS ratio_label
        FROM capped
        ORDER BY (entrevistados IS NULL), candidatos_enviados DESC;
    """

    return sql, {
        "modelo": modelo,
        "resultado": resultado,
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "interviewed_sent_30d_history",
    "label": "Entrevistados → Enviados al cliente — Ventana 30 días por opp",
    "dimensions": [
        {"key": "opportunity_id", "label": "Opportunity ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "opp_position_name", "label": "Posición", "type": "string"},
        {"key": "resultado", "label": "Resultado", "type": "string"},
        {"key": "ratio_label", "label": "Enviados / Entrevistados", "type": "string"},
    ],
    "measures": [
        {"key": "candidatos_enviados", "label": "Enviados al cliente", "type": "number"},
        {"key": "candidatos_entrevistados", "label": "Entrevistados por Vintti", "type": "number"},
        {"key": "entrevistados_sobre_enviados_pct", "label": "Enviados / Entrevistados %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
