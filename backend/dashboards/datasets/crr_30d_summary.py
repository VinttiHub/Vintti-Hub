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
            %(corte)s::date                                AS cutoff_d,
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
          SELECT DISTINCT v.cutoff_d, h.account_id
          FROM ventana v
          JOIN hires h
            ON h.start_d <= v.win_ini
           AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_ini
        ),
        activos_fin AS (
          SELECT DISTINCT v.cutoff_d, h.account_id
          FROM ventana v
          JOIN hires h
            ON h.start_d <= v.win_fin
           AND COALESCE(h.end_d, DATE '9999-12-31') >= v.win_fin
        ),
        retenidos AS (
          SELECT ai.cutoff_d, COUNT(DISTINCT ai.account_id)::int AS retenidos
          FROM activos_inicio ai
          JOIN activos_fin af USING (cutoff_d, account_id)
          GROUP BY 1
        ),
        totals AS (
          SELECT
            v.cutoff_d,
            v.win_ini,
            v.win_fin,
            (SELECT COUNT(*)::int FROM activos_inicio) AS inicio,
            (SELECT COUNT(*)::int FROM activos_fin)    AS fin,
            COALESCE((SELECT retenidos FROM retenidos), 0)::int AS retenidos
          FROM ventana v
        )
        SELECT
          TO_CHAR(cutoff_d, 'YYYY-MM-DD')                                       AS cutoff_d,
          TO_CHAR(win_ini, 'YYYY-MM-DD')                                        AS win_ini,
          TO_CHAR(win_fin, 'YYYY-MM-DD')                                        AS win_fin,
          inicio                                                                AS inicio,
          fin                                                                   AS fin,
          retenidos                                                             AS retenidos,
          ROUND((fin::numeric        / NULLIF(inicio, 0)) * 100, 2)::float      AS crr_pct,
          ROUND((retenidos::numeric  / NULLIF(inicio, 0)) * 100, 2)::float      AS grr_pct,
          ROUND(((inicio - retenidos)::numeric / NULLIF(inicio, 0)) * 100, 2)::float AS churn_inicio_pct
        FROM totals;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "crr_30d_summary",
    "label": "CRR & GRR (Staffing) — Ventana 30 días",
    "dimensions": [],
    "measures": [
        {"key": "inicio", "label": "Inicio", "type": "number"},
        {"key": "fin", "label": "Fin", "type": "number"},
        {"key": "retenidos", "label": "Retenidos", "type": "number"},
        {"key": "crr_pct", "label": "Growth % (fin/inicio)", "type": "percent"},
        {"key": "grr_pct", "label": "Retention % (retenidos/inicio)", "type": "percent"},
        {"key": "churn_inicio_pct", "label": "Churn inicio %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
