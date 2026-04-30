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
    desde = _parse_date(filters.get("desde"))
    hasta = _parse_date(filters.get("hasta"))

    sql = """
        WITH base AS (
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
        ),
        res AS (
          SELECT
            DATE_TRUNC('month', start_d)::date AS mes,
            COUNT(*)::int AS new_clients
          FROM first_hire
          GROUP BY 1
        )
        SELECT
          TO_CHAR(mes, 'YYYY-MM') AS mes,
          new_clients
        FROM res
        WHERE 1=1
          AND (%(desde)s::date IS NULL OR mes >= DATE_TRUNC('month', %(desde)s::date)::date)
          AND (%(hasta)s::date IS NULL OR mes <= DATE_TRUNC('month', %(hasta)s::date)::date)
        ORDER BY mes;
    """

    return sql, {"desde": desde, "hasta": hasta}


DATASET = {
    "key": "new_clients_history",
    "label": "New Clients per Month (Staffing)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
    ],
    "measures": [
        {"key": "new_clients", "label": "Nuevos clientes", "type": "number"},
    ],
    "default_filters": {},
    "query": query,
}
