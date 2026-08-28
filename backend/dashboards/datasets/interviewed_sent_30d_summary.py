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
    cliente = (filters.get("cliente") or filters.get("client_name") or "").strip() or None
    # Ventana efectiva compartida: MES/desde-hasta → mes calendario; CORTE → 30d
    # rodante terminando en el corte (igual que el resto de las cards de 30d).
    win_ini, win_fin = window_bounds(filters)

    # R16 (2026-08-28): la métrica se redefinió. Antes medía "de los enviados al
    # cliente, cuántos llegaron a entrevista CON EL CLIENTE" (via candidates_batches.status),
    # que es el paso siguiente del embudo y no lo que dice el título. Ahora mide el paso
    # que pidió la owner: de los candidatos que Vintti entrevistó internamente
    # (opportunity.cantidad_entrevistados, cargado a mano o vía "Traer de Apriora"),
    # qué fracción se terminó enviando al cliente.
    # Revierte la deprecación de R8: que cantidad_entrevistados sea ~3x los enviados no
    # es un dato incomparable, es lo esperado (entrevistamos muchos, enviamos una terna).
    # El error de aquellos datasets era numerador con ventana + denominador all-time.
    # Reglas de la owner: el ratio se capa al 100 por opp antes de sumar (hay opps con el
    # campo desactualizado donde enviados > entrevistados, que es imposible).
    # Las opps SIN el campo cargado NO se excluyen de la cohorte (decisión de la owner:
    # el dato siempre debería estar, así que el hueco tiene que verse para que alguien lo
    # cargue). Cuentan en total_opps y se reportan aparte en opps_sin_dato, pero no pueden
    # entrar en el porcentaje porque no hay denominador que dividir: SUM/AVG ignoran los
    # NULL, así que el % sale sólo de las opps con dato. Apenas alguien carga el número,
    # la opp entra sola en el cálculo.
    # OJO con el cap: LEAST() en Postgres IGNORA los NULL (LEAST(9, NULL) = 9, no NULL),
    # así que sin el CASE explícito los enviados de las opps sin dato se colaban en el
    # numerador y inflaban el porcentaje.
    # Las keys de las measures NO cambian, para no romper los data-field del HTML ni
    # obligar a re-seed (mismo criterio que R5 con upsells_lara).
    sql = """
        WITH ventana AS (
          SELECT
            %(win_ini)s::date AS win_ini,
            %(win_fin)s::date AS win_fin
        ),
        base AS (
          SELECT
            o.opportunity_id,
            NULLIF(o.cantidad_entrevistados, 0)::numeric AS entrevistados,
            cb.candidate_id
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
            AND (%(cliente)s::text IS NULL OR a.client_name = %(cliente)s)
            AND (%(resultado)s = 'Total' OR TRIM(o.opp_stage) = %(resultado)s)
        ),
        por_opp AS (
          SELECT
            opportunity_id,
            entrevistados,
            COUNT(DISTINCT candidate_id) AS enviados
          FROM base
          GROUP BY 1, 2
        ),
        capped AS (
          SELECT
            opportunity_id,
            entrevistados,
            CASE
              WHEN entrevistados IS NULL THEN NULL
              ELSE LEAST(enviados, entrevistados)
            END AS enviados_cap
          FROM por_opp
        )
        SELECT
          ROUND(AVG((enviados_cap * 100.0) / NULLIF(entrevistados, 0)), 2)::float
                                                AS promedio_pct_por_opportunity,
          ROUND(
            (SUM(enviados_cap)::numeric * 100.0) / NULLIF(SUM(entrevistados), 0),
            2
          )::float                              AS pct_ponderado_total,
          SUM(enviados_cap)::float              AS total_enviados,
          SUM(entrevistados)::float             AS total_entrevistados,
          COUNT(*)::int                         AS total_opps,
          COUNT(*) FILTER (WHERE entrevistados IS NULL)::int
                                                AS opps_sin_dato
        FROM capped;
    """

    return sql, {
        "modelo": modelo,
        "resultado": resultado,
        "cliente": cliente,
        "win_ini": win_ini,
        "win_fin": win_fin,
    }


DATASET = {
    "key": "interviewed_sent_30d_summary",
    "label": "Entrevistados → Enviados al cliente — Ventana 30 días (global)",
    "dimensions": [],
    "measures": [
        {"key": "promedio_pct_por_opportunity", "label": "Promedio % por opp", "type": "percent"},
        {"key": "pct_ponderado_total", "label": "Enviados sobre entrevistados % (ponderado)", "type": "percent"},
        {"key": "total_enviados", "label": "Total enviados al cliente", "type": "number"},
        {"key": "total_entrevistados", "label": "Total entrevistados por Vintti", "type": "number"},
        {"key": "total_opps", "label": "Total opps", "type": "number"},
        {"key": "opps_sin_dato", "label": "Opps sin el dato cargado", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
