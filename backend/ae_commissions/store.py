"""Persistencia de las corridas mensuales.

Se guarda el snapshot completo (`payload`) y no solo un conteo: la comision se
liquida sobre lo que el mail dijo ese dia 1. Si despues alguien corrige un fee
o una fecha de baja, la corrida vieja tiene que seguir mostrando lo que se
mando, no lo que la base dice hoy.
"""
from __future__ import annotations

import json


def tables_exist(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.ae_commission_runs')")
        return cur.fetchone()[0] is not None


def ensure_schema(conn) -> None:
    """Crea la tabla si falta.

    Existe la migracion `backend/sql/20260908_ae_commissions.sql` para correr a
    mano contra RDS, pero esto ademas deja la seccion levantable en local sin
    ningun paso previo.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ae_commission_runs (
                run_id         BIGSERIAL PRIMARY KEY,
                period_month   DATE NOT NULL,
                trigger_source TEXT,
                status         TEXT NOT NULL DEFAULT 'running',
                recipients     TEXT,
                payload        JSONB,
                error_text     TEXT,
                started_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at    TIMESTAMPTZ
            )
            """
        )
        cur.execute(
            """CREATE INDEX IF NOT EXISTS ix_ae_commission_runs_period
                 ON ae_commission_runs (period_month DESC)"""
        )


def start_run(conn, period_month, trigger_source="cli") -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ae_commission_runs (period_month, trigger_source)
               VALUES (%s, %s) RETURNING run_id""",
            (period_month, trigger_source),
        )
        return cur.fetchone()[0]


def finish_run(conn, run_id, *, status, payload=None, recipients=None,
               error_text=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ae_commission_runs
                  SET finished_at = NOW(),
                      status      = %s,
                      payload     = COALESCE(%s::jsonb, payload),
                      recipients  = COALESCE(%s, recipients),
                      error_text  = %s
                WHERE run_id = %s""",
            (
                status,
                json.dumps(payload, default=str) if payload is not None else None,
                ", ".join(recipients) if recipients else None,
                error_text,
                run_id,
            ),
        )


def list_runs(conn, limit=24) -> list[dict]:
    """Corridas guardadas, mas nuevas primero. Sin el payload (pesa)."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT run_id, period_month, status, trigger_source,
                      recipients, started_at, finished_at
                 FROM ae_commission_runs
                ORDER BY period_month DESC, run_id DESC
                LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
    out = []
    for r in rows:
        run_id, period, status, trigger, recipients, started, finished = r
        out.append({
            "run_id": run_id,
            "period": period.strftime("%Y-%m") if period else None,
            "status": status,
            "trigger_source": trigger,
            "recipients": recipients,
            "started_at": started.isoformat() if started else None,
            "finished_at": finished.isoformat() if finished else None,
        })
    return out


def load_payload(conn, period_month):
    """Snapshot guardado de un mes (la ultima corrida ok), o None."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT payload FROM ae_commission_runs
                WHERE period_month = %s AND status = 'ok' AND payload IS NOT NULL
             ORDER BY run_id DESC LIMIT 1""",
            (period_month,),
        )
        row = cur.fetchone()
    return row[0] if row else None
