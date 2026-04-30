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
        or _parse_date(filters.get("fecha_corte"))
        or _parse_date(filters.get("cutoff"))
        or datetime.utcnow().date()
    )

    sql = """
        WITH ventana AS (
          SELECT %(corte)s::date AS cutoff_d
        ),
        base AS (
          SELECT
            ho.account_id,
            ho.candidate_id,
            CASE
              WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
              ELSE NULLIF(ho.start_date::text,'')::date
            END AS start_d,
            ROW_NUMBER() OVER (
              PARTITION BY ho.account_id
              ORDER BY
                CASE
                  WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                  ELSE NULLIF(ho.start_date::text,'')::date
                END,
                ho.candidate_id
            ) AS rn
          FROM hire_opportunity ho
          JOIN opportunity o
            ON o.opportunity_id = ho.opportunity_id
           AND o.opp_model = 'Staffing'
          WHERE ho.account_id IS NOT NULL
            AND ho.candidate_id IS NOT NULL
            AND (
              CASE
                WHEN ho.carga_active IS NOT NULL THEN ho.carga_active::date
                ELSE NULLIF(ho.start_date::text,'')::date
              END
            ) IS NOT NULL
        ),
        first_hire AS (
          SELECT account_id, candidate_id, start_d
          FROM base
          WHERE rn = 1
        )
        SELECT
          TO_CHAR(fh.start_d, 'YYYY-MM-DD') AS start_date,
          a.client_name,
          c.name AS candidate_name
        FROM first_hire fh
        CROSS JOIN ventana v
        LEFT JOIN account    a ON a.account_id   = fh.account_id
        LEFT JOIN candidates c ON c.candidate_id = fh.candidate_id
        WHERE fh.start_d BETWEEN (v.cutoff_d - INTERVAL '29 days')::date AND v.cutoff_d
        ORDER BY fh.start_d;
    """

    return sql, {"corte": corte}


DATASET = {
    "key": "new_clients_30d_detail",
    "label": "New Clients — Detalle 30d (Staffing)",
    "dimensions": [
        {"key": "start_date", "label": "Start Date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
