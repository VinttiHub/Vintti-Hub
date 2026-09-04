"""Orquesta una corrida completa: audita, persiste, y manda el mail.

Se separa del runner para que la auditoria en si pueda correrse en seco (sin
base ni mail) mientras se calibran las reglas, que es como conviene iterar.
"""
from __future__ import annotations

import logging
import time

from . import report, store
from .runner import run as run_audit

log = logging.getLogger(__name__)

# Lista fija y explicita, sin env var de por medio: asi una variable mal seteada no
# puede redirigir el reporte ni sumar destinatarios de mas. Para agregar o sacar a
# alguien hay que editar esta linea, con nombre y apellido, y que lo pida la owner.
#   - pgonzales@vintti.com  Priscila Gonzales (owner)
#   - lara@vintti.com       Lara Reinhardt (Account Manager) - agregada 2026-09-04
RECIPIENTS = ["pgonzales@vintti.com", "lara@vintti.com"]


def execute(run_id=None, trigger_source="cli", send_email=True, persist=True) -> dict:
    """Corre la auditoria de punta a punta y devuelve el artefacto JSON."""
    from db import get_connection

    t0 = time.monotonic()
    conn = None
    findings, execs, topo = [], {}, None
    try:
        findings, execs, topo = run_audit()

        meta = {
            "html_source": topo.source,
            "nodes_seen": len(topo.nodes),
            "datasets_run": len(execs),
            "datasets_failed": sum(1 for e in execs.values() if e.error),
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "trigger_source": trigger_source,
        }

        diff, visible = {"status": {}, "resolved": set()}, findings
        if persist:
            conn = get_connection()
            conn.autocommit = True
            if not store.tables_exist(conn):
                raise RuntimeError(
                    "Faltan las tablas de auditoria: correr "
                    "backend/sql/20260902_dashboard_audit.sql contra RDS"
                )
            if run_id is None:
                run_id = store.start_run(conn, trigger_source, topo.source)
            waivers = store.load_waivers(conn)
            diff = store.save_findings(conn, run_id, findings, waivers)
            # Finding es un dataclass con eq=True, asi que no es hasheable: la
            # marca va en el propio objeto en vez de en un set.
            visible = []
            waived_count = 0
            for f in findings:
                f._fp = store.fingerprint(f)
                if store.match_waiver(f, f._fp, waivers) is None:
                    visible.append(f)
                else:
                    waived_count += 1
            meta["waived_count"] = waived_count
            store.finish_run(conn, run_id, status="ok", findings_total=len(findings),
                             html_source=topo.source,
                             **{k: meta[k] for k in
                                ("nodes_seen", "datasets_run", "datasets_failed", "elapsed_ms")})

        if send_email and RECIPIENTS:
            subject, body = report.render(run_id, visible, meta, diff)
            from send_email_endpoint import send_email_message

            send_email_message(RECIPIENTS, subject, body)
            log.info("Auditoria #%s: mail enviado a %s", run_id, ", ".join(RECIPIENTS))

        return report.to_json(run_id, visible, meta, diff)

    except Exception as exc:  # noqa: BLE001
        log.exception("Auditoria #%s fallo", run_id)
        # Una corrida que muere en silencio es peor que una que no corre: nadie
        # se entera de que el control dejo de existir. Se cierra el run y se
        # avisa por el mismo canal que usa el reporte normal.
        if persist and conn is not None and run_id is not None:
            try:
                store.finish_run(conn, run_id, status="error", error_text=str(exc)[:500])
            except Exception:  # noqa: BLE001
                log.exception("No se pudo cerrar el run #%s", run_id)
        if send_email and RECIPIENTS:
            try:
                from send_email_endpoint import send_email_message

                send_email_message(
                    RECIPIENTS, "Auditoria dashboard · FALLO",
                    f"<p>La auditoria semanal no pudo completarse.</p><pre>{exc}</pre>",
                )
            except Exception:  # noqa: BLE001
                log.exception("Tampoco se pudo avisar por mail")
        raise
    finally:
        if conn is not None:
            conn.close()
