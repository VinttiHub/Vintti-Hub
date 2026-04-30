from __future__ import annotations

from datetime import date


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) >= 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None
    return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    mes = (
        _parse_date(filters.get("fecha"))
        or _parse_date(filters.get("mes_inicio"))
        or _parse_date(filters.get("mes"))
        or _parse_date(filters.get("month"))
    )

    sql = """
        WITH mes AS (
          SELECT COALESCE(
            DATE_TRUNC('month', %(mes)s::date)::date,
            DATE_TRUNC('month', CURRENT_DATE)::date
          ) AS mes_ini
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
        CROSS JOIN mes m
        LEFT JOIN account    a ON a.account_id   = fh.account_id
        LEFT JOIN candidates c ON c.candidate_id = fh.candidate_id
        WHERE fh.start_d >= m.mes_ini
          AND fh.start_d <  (m.mes_ini + INTERVAL '1 month')
        ORDER BY fh.start_d;
    """

    return sql, {"mes": mes}


DATASET = {
    "key": "new_clients_month_detail",
    "label": "New Clients — Detalle por Mes (Staffing)",
    "dimensions": [
        {"key": "start_date", "label": "Start Date", "type": "date"},
        {"key": "client_name", "label": "Cliente", "type": "string"},
        {"key": "candidate_name", "label": "Candidato", "type": "string"},
    ],
    "measures": [],
    "default_filters": {},
    "query": query,
}
