"""GMRR / MRR del AM, mes a mes (tab Account Management).

Mismo numero que los tiles GMRR/MRR del tab Management Dashboard pero contando
**solo lo que ya es del AM**: una vacante vendida por un AE (Mariano/Bahia) entra
recien a los 3 meses del Close Win. Ver `_am_mrr_staffing.py` para la regla.

Los filtros son **los mismos que los tiles originales** (`mrr_history.py`), a pedido
de la owner:
  - `desde`/`hasta` (o `from`/`to`) parseados como YYYY-MM. El pill **Mes** del
    dashboard ya setea desde/hasta solo (`control-dashboard.js`), asi que con eso
    alcanza para que la card respete el mes elegido.
  - `metric` = 'Revenue' (GMRR = salary + fee) | 'Fee' (MRR = fee). Un solo dataset
    sirve a los dos tiles via `data-override-metric`.
  - **Modo corte**: si hay `corte` y no hay mes/desde/hasta, se exponen `kpi_corte`
    (run-rate al dia del corte) y `kpi_corte_delta` (vs 30 dias antes) como columnas
    constantes, sin tocar la serie mensual.

A diferencia de `mrr_history.py` los params van **nombrados**: la tupla posicional
de 6 elementos del modo-corte es justo donde es facil equivocarse.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from ._now import today_ar
from ._am_mrr_staffing import ANCHOR_CTE, HISTORY_CTE, ae_leads


_ALLOWED_METRICS = {"Revenue", "Fee"}


def _parse_ym(value) -> date | None:
    if not value:
        return None
    parts = str(value).strip().split("-")
    if len(parts) < 2:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, TypeError):
        return None


def _parse_ymd(value) -> date | None:
    if not value:
        return None
    parts = str(value).strip().split("-")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        return None


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    filters = filters or {}
    current_month_start = today_ar().replace(day=1)

    period_start = _parse_ym(filters.get("from")) or _parse_ym(filters.get("desde")) or date(2023, 1, 1)
    period_end = _parse_ym(filters.get("to")) or _parse_ym(filters.get("hasta")) or current_month_start
    if period_end < period_start:
        period_end = period_start

    metric = str(filters.get("metric") or "Revenue").strip()
    if metric not in _ALLOWED_METRICS:
        metric = "Revenue"
    gmrr_col, fee_col = ("monthly_fee", "m3_fee") if metric == "Fee" else ("monthly_gmrr", "m3_gmrr")

    am = str(filters.get("am") or "").strip().lower()

    corte = _parse_ymd(filters.get("corte"))
    has_window = bool(filters.get("mes") or filters.get("desde") or filters.get("hasta"))
    corte_mode = bool(corte) and not has_window

    params = {
        "ae_leads": ae_leads(),
        "am": am,
        "period_start": period_start,
        "period_end": period_end,
        "corte": corte or today_ar(),
        "corte_prev": (corte or today_ar()) - timedelta(days=30),
    }

    if corte_mode:
        anchor_with = ANCHOR_CTE
        anchor_metric = "fee" if metric == "Fee" else "gmrr"
        kpi_cols = (
            "ac.kpi_corte,\n          ac.kpi_corte_delta,"
            "\n          ac.m3_corte,\n          ac.m3_corte_count"
        )
        kpi_join = f"""
        CROSS JOIN (
          SELECT
            MAX(CASE WHEN kind = 'cur' THEN {anchor_metric} END)::bigint AS kpi_corte,
            ROUND(
              100.0 * (MAX(CASE WHEN kind = 'cur'  THEN {anchor_metric} END)
                     - MAX(CASE WHEN kind = 'prev' THEN {anchor_metric} END))
              / NULLIF(MAX(CASE WHEN kind = 'prev' THEN {anchor_metric} END), 0), 2
            )::float AS kpi_corte_delta,
            MAX(CASE WHEN kind = 'cur' THEN m3_{anchor_metric} END)::bigint AS m3_corte,
            MAX(CASE WHEN kind = 'cur' THEN m3_contractors END)::int        AS m3_corte_count
          FROM a_mrr
        ) ac"""
    else:
        anchor_with = ""
        kpi_cols = (
            "NULL::bigint AS kpi_corte,\n          NULL::float AS kpi_corte_delta,"
            "\n          NULL::bigint AS m3_corte,\n          NULL::int AS m3_corte_count"
        )
        kpi_join = ""

    sql = f"""
        WITH {HISTORY_CTE}{anchor_with}
        SELECT
          TO_CHAR(m.mes, 'YYYY-MM')                   AS mes,
          m.{gmrr_col}::bigint                        AS mrr_total,
          m.active_contractors                        AS candidatos_activos,
          m.active_accounts                           AS clientes_activos,
          m.{fee_col}::bigint                         AS m3_excluded_total,
          m.m3_contractors                            AS m3_excluded_count,
          ROUND(
            100.0 * (m.{gmrr_col} - LAG(m.{gmrr_col}) OVER (ORDER BY m.mes))
                  / NULLIF(LAG(m.{gmrr_col}) OVER (ORDER BY m.mes), 0),
            2
          )::float                                    AS growth_pct,
          {kpi_cols}
        FROM monthly m{kpi_join}
        ORDER BY m.mes;
    """

    return sql, params


DATASET = {
    "key": "am_mrr_history",
    "label": "GMRR / MRR del AM (sin M3 del AE)",
    "dimensions": [
        {"key": "mes", "label": "Mes", "type": "date"},
        {"key": "candidatos_activos", "label": "Contractors activos", "type": "number"},
        {"key": "clientes_activos", "label": "Clientes activos", "type": "number"},
        {"key": "m3_excluded_count", "label": "Contractors en M3 del AE", "type": "number"},
    ],
    "measures": [
        {"key": "mrr_total", "label": "Total del AM", "type": "currency"},
        {"key": "m3_excluded_total", "label": "En M3 del AE (no cuenta)", "type": "currency"},
        {"key": "growth_pct", "label": "Growth %", "type": "percent"},
    ],
    "default_filters": {"metric": "Revenue"},
    "query": query,
}
