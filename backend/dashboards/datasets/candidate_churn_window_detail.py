from __future__ import annotations

from datetime import date, datetime
from ._now import today_ar

from ._periods import window_bounds
from ._sales_scope import origen_case, origen_clause, sales_leads


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


def _parse_meses(value) -> int:
    try:
        n = int(str(value).strip())
        if n in (3, 6):
            return n
    except (TypeError, ValueError):
        pass
    return 3


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    meses = _parse_meses(filters.get("meses"))
    window_days = 180 if meses == 6 else 90
    if filters and (filters.get("desde") or filters.get("hasta") or filters.get("mes")):
        _, corte = window_bounds(filters)
    else:
        corte = (
            _parse_date(filters.get("corte"))
            or _parse_date(filters.get("cutoff"))
            or _parse_date(filters.get("fecha_corte"))
            or today_ar()
        )

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date AS corte_d,
            (%(corte)s::date - make_interval(days => %(window_days)s - 1))::date AS win_ini,
            %(window_days)s AS window_days
        ),
        ho AS (
          SELECT *
          FROM (
            SELECT
              h.candidate_id,
              COALESCE(c.name, '')        AS candidate_name,
              h.account_id,
              COALESCE(a.client_name, '') AS account_name,
              """ + origen_case() + """ AS origen,
              CASE
                WHEN h.carga_active IS NOT NULL THEN h.carga_active::date
                ELSE NULLIF(h.start_date::text, '')::date
              END AS start_d,
              CASE
                WHEN h.carga_inactive IS NOT NULL THEN h.carga_inactive::date
                WHEN h.end_date IS NULL OR h.end_date::text = '' THEN NULL
                ELSE h.end_date::date
              END AS end_d,
              CASE
                WHEN NULLIF(TRIM(h.buyout_daterange), '') IS NOT NULL
                  THEN TO_DATE(TRIM(h.buyout_daterange) || '-01', 'YYYY-MM-DD')
                ELSE NULL
              END AS buyout_d
            FROM hire_opportunity h
            JOIN opportunity o ON o.opportunity_id = h.opportunity_id
            LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
            LEFT JOIN account    a ON a.account_id   = h.account_id
            WHERE o.opp_model = 'Staffing'
              AND COALESCE(a.vintti_internal, FALSE) = FALSE
              /*ORIGEN*/
          ) x
          WHERE start_d IS NOT NULL
        ),
        detalle AS (
          SELECT
            v.corte_d,
            v.win_ini,
            h.candidate_id,
            h.candidate_name,
            h.account_name,
            h.origen,
            h.start_d,
            h.end_d,
            (h.end_d IS NULL OR h.end_d > v.corte_d) AS is_active,
            CASE
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.corte_d
                AND h.buyout_d IS NOT NULL
                AND h.buyout_d >= DATE_TRUNC('month', h.end_d)
                THEN 'BAJA_BUYOUT'
              WHEN h.end_d IS NOT NULL
                AND h.end_d <= v.corte_d
                THEN 'BAJA_REAL'
              ELSE NULL
            END AS baja_raw
          FROM ventana v
          JOIN ho h
            ON h.start_d BETWEEN v.win_ini AND v.corte_d
        ),
        -- Una fila por CANDIDATO, con la misma regla que candidate_churn_window_summary
        -- (R7): activo si CUALQUIER hire sigue activo; si no, baja real antes que
        -- buyout. Asi la lista tiene exactamente `candidatos` filas y las bajas
        -- coinciden con `bajas_real` / `bajas_buyout` de la card. Antes era una fila
        -- por hire y un candidato con 2 hires aparecia 2 veces.
        per_candidate AS (
          SELECT
            MIN(corte_d)                                         AS corte_d,
            MIN(win_ini)                                         AS win_ini,
            MAX(candidate_name)                                  AS candidate_name,
            STRING_AGG(DISTINCT NULLIF(account_name, ''), ' · ') AS account_name,
            STRING_AGG(DISTINCT origen, ' + ' ORDER BY origen)   AS origen,
            MIN(start_d)                                         AS start_d,
            BOOL_OR(is_active)                                   AS is_active,
            BOOL_OR(baja_raw = 'BAJA_REAL')                      AS any_real,
            BOOL_OR(baja_raw = 'BAJA_BUYOUT')                    AS any_buyout,
            MAX(end_d) FILTER (WHERE baja_raw IS NOT NULL)       AS end_baja
          FROM detalle
          GROUP BY candidate_id
        )
        SELECT
          TO_CHAR(corte_d, 'YYYY-MM-DD') AS corte_d,
          TO_CHAR(win_ini, 'YYYY-MM-DD') AS win_ini,
          candidate_name,
          COALESCE(account_name, '')     AS account_name,
          origen,
          TO_CHAR(start_d, 'YYYY-MM-DD') AS start_d,
          -- Un activo no tiene fecha de baja aunque tenga otro hire cerrado.
          CASE WHEN is_active THEN NULL
               ELSE TO_CHAR(end_baja, 'YYYY-MM-DD') END AS end_d,
          CASE
            WHEN is_active  THEN NULL
            WHEN any_real   THEN 'Baja - Real'
            WHEN any_buyout THEN 'Baja - Buyout (Conversion)'
          END AS baja_tipo,
          CASE
            WHEN is_active  THEN 'Activo'
            WHEN any_real   THEN 'Baja · '   || TO_CHAR(end_baja, 'YYYY-MM-DD')
            WHEN any_buyout THEN 'Buyout · ' || TO_CHAR(end_baja, 'YYYY-MM-DD')
          END AS estado
        FROM per_candidate
        ORDER BY
          is_active,           -- primero las bajas
          end_baja DESC NULLS LAST,
          account_name,
          candidate_name;
    """

    # Mismo filtro General / AE / AM que la card Churn M3 (override `origen`).
    origen_sql, origen_params = origen_clause(filters)
    sql = sql.replace("/*ORIGEN*/", origen_sql)

    return sql, {
        "corte": corte, "window_days": window_days,
        # origen_case() usa la misma lista aunque el filtro sea General.
        "origen_ae_leads": tuple(sales_leads()),
        **origen_params,
    }


DATASET = {
    "key": "candidate_churn_window_detail",
    "label": "Churn de candidatos (Staffing) — Detalle 90/180 días (1 fila por candidato)",
    "dimensions": [
        {"key": "corte_d", "label": "Corte", "type": "date"},
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
        {"key": "account_name", "label": "Cliente", "type": "string"},
        {"key": "start_d", "label": "Start", "type": "date"},
        {"key": "end_d", "label": "End", "type": "date"},
        {"key": "baja_tipo", "label": "Tipo de baja", "type": "string"},
        {"key": "origen", "label": "Origen (AE/AM)", "type": "string"},
        {"key": "estado", "label": "Estado al corte", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
