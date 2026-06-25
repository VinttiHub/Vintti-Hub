from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds


def _parse_date(value: str | None) -> date | None:
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


def _norm_modelo(value) -> str:
    if not value:
        return "Total"
    raw = str(value).strip()
    if raw in ("Total", "Staffing", "Recruiting"):
        return raw
    cap = raw[:1].upper() + raw[1:].lower()
    if cap in ("Total", "Staffing", "Recruiting"):
        return cap
    return "Total"


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or today_ar()
    )
    modelo = _norm_modelo(filters.get("modelo") or filters.get("model") or filters.get("segmento"))

    # Active-hire logic mirrors clients_multi_30d_summary.py exactly so the
    # detail list matches the KPI count:
    #   - Uses COALESCE(carga_active, start_date) / COALESCE(carga_inactive, end_date)
    #   - For the current month, falls back to ho.status='active' when dates fall short
    #   - Normalizes opp_model with LOWER(TRIM) before comparing to the modelo filter
    # Only hires with a non-null candidate_id are listed (a candidate row needs a name);
    # this matches the summary, whose ">1" count uses COUNT(DISTINCT candidate_id)
    # and so already ignores NULL candidate_ids (e.g. buyouts).
    win_ini, win_fin = window_bounds(filters)
    sql = """
        WITH hires AS (
          SELECT
            ho.account_id,
            a.client_name,
            ho.candidate_id,
            c.name AS candidate_name,
            LOWER(TRIM(COALESCE(ho.status, ''))) AS status,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              WHEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '') IS NOT NULL
                THEN NULLIF(TRIM(CAST(ho.start_date AS TEXT)), '')::date
              ELSE NULL
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '') IS NULL THEN NULL
              ELSE NULLIF(TRIM(CAST(ho.end_date AS TEXT)), '')::date
            END AS end_d,
            LOWER(TRIM(o.opp_model)) AS model
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          JOIN account a     ON a.account_id    = ho.account_id
          JOIN candidates c  ON c.candidate_id  = ho.candidate_id
          WHERE ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
            AND LOWER(TRIM(o.opp_model)) IN ('staffing', 'recruiting')
        ),
        corte AS (
          SELECT
            %(win_fin)s::date                         AS mes_fin,
            %(win_ini)s::date                         AS mes_ini,
            TO_CHAR(%(win_fin)s::date, 'YYYY-MM-DD')  AS etiqueta
        ),
        activos AS (
          SELECT DISTINCT
            c.etiqueta AS periodo,
            h.account_id,
            h.client_name,
            h.candidate_id,
            h.candidate_name
          FROM corte c
          JOIN hires h
            ON (
                 (h.start_d IS NOT NULL
                  AND h.start_d <= c.mes_fin
                  AND COALESCE(h.end_d, DATE '9999-12-31') >= c.mes_fin)
                 OR
                 (c.mes_ini = DATE_TRUNC('month', CURRENT_DATE)
                  AND h.status = 'active'
                  AND (h.end_d IS NULL OR h.end_d >= CURRENT_DATE))
               )
           AND (%(modelo)s = 'Total' OR h.model = LOWER(%(modelo)s))
        ),
        clientes_con_mas_de_1 AS (
          SELECT periodo, account_id
          FROM activos
          GROUP BY 1, 2
          HAVING COUNT(DISTINCT candidate_id) > 1
        )
        SELECT
          a.periodo,
          a.client_name,
          a.candidate_name
        FROM activos a
        JOIN clientes_con_mas_de_1 x
          ON x.periodo = a.periodo
         AND x.account_id = a.account_id
        ORDER BY a.periodo, a.client_name, a.candidate_name;
    """

    return sql, {"win_ini": win_ini, "win_fin": win_fin, "corte": corte, "modelo": modelo}


DATASET = {
    "key": "clients_multi_30d_detail",
    "label": "% Clientes con > 1 candidato — Detalle ventana 30 días",
    "dimensions": [
        {"key": "periodo", "label": "Período", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
