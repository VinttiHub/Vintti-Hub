from __future__ import annotations

from datetime import date, datetime


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


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    corte = (
        _parse_date(filters.get("corte"))
        or _parse_date(filters.get("cutoff"))
        or _parse_date(filters.get("fecha_corte"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH ventana AS (
          SELECT
            %(corte)s::date                                AS corte_d,
            (%(corte)s::date - INTERVAL '29 days')::date   AS win_ini,
            %(corte)s::date                                AS win_fin
        ),
        hires AS (
          SELECT
            ho.account_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text, '')::date
            END AS start_d,
            CASE
              WHEN ho.carga_inactive IS NOT NULL THEN ho.carga_inactive::date
              WHEN ho.end_date IS NULL OR ho.end_date::text = '' THEN NULL
              ELSE ho.end_date::date
            END AS end_d
          FROM hire_opportunity ho
          JOIN opportunity o ON o.opportunity_id = ho.opportunity_id
          WHERE ho.account_id IS NOT NULL
            AND o.opp_model = 'Staffing'
            AND (
              ho.carga_active IS NOT NULL
              OR NULLIF(ho.start_date::text, '') IS NOT NULL
            )
        ),
        activos_inicio AS (
          SELECT DISTINCT
            v.corte_d, v.win_ini, v.win_fin, h.account_id
          FROM ventana v
          JOIN hires h
            ON h.start_d <= v.win_ini
           AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_ini
        ),
        activos_fin AS (
          SELECT DISTINCT
            v.corte_d, v.win_ini, v.win_fin, h.account_id
          FROM ventana v
          JOIN hires h
            ON h.start_d <= v.win_fin
           AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_fin
        ),
        full_set AS (
          SELECT corte_d, win_ini, win_fin, account_id FROM activos_inicio
          UNION
          SELECT corte_d, win_ini, win_fin, account_id FROM activos_fin
        ),
        clasif AS (
          SELECT
            fs.corte_d,
            fs.win_ini,
            fs.win_fin,
            fs.account_id,
            CASE
              WHEN ai.account_id IS NOT NULL AND af.account_id IS NOT NULL THEN 'retenido'
              WHEN ai.account_id IS NOT NULL AND af.account_id IS NULL     THEN 'churn_inicio'
              WHEN ai.account_id IS NULL     AND af.account_id IS NOT NULL THEN 'nuevo_en_mes'
            END AS tipo
          FROM full_set fs
          LEFT JOIN activos_inicio ai
            ON ai.corte_d = fs.corte_d AND ai.account_id = fs.account_id
          LEFT JOIN activos_fin af
            ON af.corte_d = fs.corte_d AND af.account_id = fs.account_id
        )
        SELECT
          TO_CHAR(c.win_ini, 'YYYY-MM-DD') AS win_ini,
          TO_CHAR(c.win_fin, 'YYYY-MM-DD') AS win_fin,
          c.tipo,
          c.account_id,
          COALESCE(a.client_name, '')      AS client_name
        FROM clasif c
        LEFT JOIN account a ON a.account_id = c.account_id
        ORDER BY
          CASE c.tipo
            WHEN 'churn_inicio' THEN 1
            WHEN 'nuevo_en_mes' THEN 2
            WHEN 'retenido'     THEN 3
          END,
          a.client_name;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "crr_30d_detail",
    "label": "CRR & GRR (Staffing) — Detalle ventana 30 días",
    "dimensions": [
        {"key": "win_ini", "label": "Inicio ventana", "type": "date"},
        {"key": "win_fin", "label": "Fin ventana", "type": "date"},
        {"key": "tipo", "label": "Tipo", "type": "string"},
        {"key": "account_id", "label": "Account ID", "type": "string"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
