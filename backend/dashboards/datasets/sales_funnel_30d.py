"""Sales funnel — SQL → NDA Sent → Sourcing → Close Win.

Snapshot-based funnel using `opp_stage` cumulative thresholds. All counts
are filtered to the AE/sales-lead set (Mariano + Bahia). No date window is
applied — this is the CURRENT state of their pipeline:

  SQL          = every opp that exists in the CRM under these sales_leads
                 (every opp originated as a SQL).
  NDA Sent     = opps that progressed past 'Deep Dive' → stage IN ('NDA Sent',
                 'Sourcing', 'Interviewing', 'Negotiating', 'Close Win',
                 'Closed Lost').
  Sourcing     = opps that signed the NDA (moved past 'NDA Sent') → stage IN
                 ('Sourcing', 'Interviewing', 'Negotiating', 'Close Win',
                 'Closed Lost').
  Close Win    = opps currently at 'Close Win'.

Returns 4 counts + 4 cumulative conversion percentages.
"""
from __future__ import annotations

import os


SALES_LEADS_DEFAULT = ("mariano@vintti.com", "bahia@vintti.com")


def _sales_leads() -> list[str]:
    raw = os.environ.get("DASHBOARD_SALES_AES", "")
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return parts or list(SALES_LEADS_DEFAULT)


def query(filters: dict, *_args, **_kwargs) -> tuple[str, dict]:
    # Snapshot — no time filter. Just the current funnel state.
    sql = """
        WITH base AS (
          SELECT
            o.opportunity_id,
            TRIM(o.opp_stage) AS opp_stage
          FROM opportunity o
          WHERE TRIM(LOWER(o.opp_sales_lead)) = ANY(%(sales_leads)s)
            AND o.opp_stage IS NOT NULL
        ),
        counts AS (
          SELECT
            COUNT(*)::int                                                                 AS sql_count,
            COUNT(*) FILTER (
              WHERE opp_stage IN ('NDA Sent','Sourcing','Interviewing','Negotiating',
                                  'Close Win','Closed Lost')
            )::int                                                                        AS nda_sent_count,
            COUNT(*) FILTER (
              WHERE opp_stage IN ('Sourcing','Interviewing','Negotiating',
                                  'Close Win','Closed Lost')
            )::int                                                                        AS sourcing_count,
            COUNT(*) FILTER (WHERE opp_stage = 'Close Win')::int                          AS close_win_count
          FROM base
        )
        SELECT
          sql_count,
          nda_sent_count,
          sourcing_count,
          close_win_count,
          ROUND(
            CASE WHEN sql_count = 0 THEN NULL
                 ELSE 100.0 * nda_sent_count::numeric / sql_count END, 2
          )::float                                                                        AS sql_to_nda_sent_pct,
          ROUND(
            CASE WHEN nda_sent_count = 0 THEN NULL
                 ELSE 100.0 * sourcing_count::numeric / nda_sent_count END, 2
          )::float                                                                        AS nda_sent_to_sourcing_pct,
          ROUND(
            CASE WHEN sourcing_count = 0 THEN NULL
                 ELSE 100.0 * close_win_count::numeric / sourcing_count END, 2
          )::float                                                                        AS sourcing_to_close_win_pct,
          ROUND(
            CASE WHEN sql_count = 0 THEN NULL
                 ELSE 100.0 * close_win_count::numeric / sql_count END, 2
          )::float                                                                        AS sql_to_close_win_pct
        FROM counts;
    """

    return sql, {"sales_leads": _sales_leads()}


DATASET = {
    "key": "sales_funnel_snapshot",
    "label": "Sales funnel — SQL → NDA Sent → Sourcing → Close Win (snapshot, Mariano + Bahia)",
    "dimensions": [],
    "measures": [
        {"key": "sql_count", "label": "SQL (all opps)", "type": "number"},
        {"key": "nda_sent_count", "label": "NDA Sent (past Deep Dive)", "type": "number"},
        {"key": "sourcing_count", "label": "Sourcing (NDA signed)", "type": "number"},
        {"key": "close_win_count", "label": "Close Win", "type": "number"},
        {"key": "sql_to_nda_sent_pct", "label": "SQL → NDA Sent %", "type": "percent"},
        {"key": "nda_sent_to_sourcing_pct", "label": "NDA Sent → Sourcing %", "type": "percent"},
        {"key": "sourcing_to_close_win_pct", "label": "Sourcing → Close Win %", "type": "percent"},
        {"key": "sql_to_close_win_pct", "label": "SQL → Close Win %", "type": "percent"},
    ],
    "default_filters": {},
    "query": query,
}
