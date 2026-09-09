"""Persistencia de las corridas del digest.

Se guarda el snapshot de lo que se posteo, no solo un conteo: cuando alguien
pregunte "?por que me nombraron el jueves si yo eso lo habia cargado?", la
corrida vieja tiene que poder mostrar lo que la base decia ese dia, no lo que
dice hoy. Ademas deja donde colgar un snooze mas adelante, con la forma que ya
tiene `dashboard_audit_waivers`.
"""
from __future__ import annotations

import json


def tables_exist(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.daily_digest_runs')")
        return cur.fetchone()[0] is not None


def ensure_schema(conn) -> None:
    """Crea la tabla si falta.

    Existe la migracion `backend/sql/20260909_daily_digest.sql` para correr a
    mano contra RDS, pero esto ademas deja el digest corrible en local sin
    ningun paso previo ([[feedback_hirex_local_runnable]]).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_digest_runs (
                run_id         BIGSERIAL PRIMARY KEY,
                run_date       DATE NOT NULL,
                trigger_source TEXT,
                status         TEXT NOT NULL DEFAULT 'running',
                findings_total INTEGER,
                people_total   INTEGER,
                slack_transport TEXT,
                slack_error    TEXT,
                payload        JSONB,
                error_text     TEXT,
                started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at    TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """CREATE INDEX IF NOT EXISTS ix_daily_digest_runs_date
                 ON daily_digest_runs (run_date DESC, run_id DESC)"""
        )


def start_run(conn, run_date, trigger_source="cli") -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO daily_digest_runs (run_date, trigger_source)
               VALUES (%s, %s) RETURNING run_id""",
            (run_date, trigger_source),
        )
        return cur.fetchone()[0]


def finish_run(conn, run_id, *, status, payload=None, findings_total=None,
               people_total=None, slack_transport=None, slack_error=None,
               error_text=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE daily_digest_runs
                  SET finished_at     = NOW(),
                      status          = %s,
                      findings_total  = COALESCE(%s, findings_total),
                      people_total    = COALESCE(%s, people_total),
                      slack_transport = COALESCE(%s, slack_transport),
                      slack_error     = %s,
                      payload         = COALESCE(%s::jsonb, payload),
                      error_text      = %s
                WHERE run_id = %s""",
            (status, findings_total, people_total, slack_transport, slack_error,
             json.dumps(payload, default=str) if payload is not None else None,
             error_text, run_id),
        )


def list_runs(conn, limit=30) -> list[dict]:
    """Corridas guardadas, mas nuevas primero. Sin el payload (pesa)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT run_id, run_date, status, trigger_source, findings_total,
                      people_total, slack_transport, slack_error,
                      started_at, finished_at
                 FROM daily_digest_runs
                ORDER BY run_id DESC
                LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
    return [{
        "run_id": r[0],
        "run_date": r[1].isoformat() if r[1] else None,
        "status": r[2],
        "trigger_source": r[3],
        "findings_total": r[4],
        "people_total": r[5],
        "slack_transport": r[6],
        "slack_error": r[7],
        "started_at": r[8].isoformat() if r[8] else None,
        "finished_at": r[9].isoformat() if r[9] else None,
    } for r in rows]
