"""Orquesta una corrida mensual: consulta, persiste y manda el mail.

Se separa de `queries` para poder correr en seco (`python -m ae_commissions`)
sin escribir en la base ni mandarle un mail a nadie mientras se calibra.
"""
from __future__ import annotations

import logging
from datetime import date

from psycopg2.extras import RealDictCursor

from . import queries, report, store

log = logging.getLogger(__name__)

# Lista fija y explicita, sin env var de por medio: asi una variable mal seteada
# no puede redirigir el reporte ni sumar destinatarios de mas. Para agregar o
# sacar a alguien hay que editar esta linea y que lo pida la owner.
#   - pgonzales@vintti.com  Priscila Gonzales (owner)
#   - bahia@vintti.com      Bahia (Account Executive) - agregada 2026-09-08
# OJO: esta lista NO es la de acceso a la seccion. Quien recibe el mail (2) y
# quien puede abrir la pagina (4) son cosas distintas a proposito; el acceso
# vive en AE_COMMISSIONS_ALLOWED, en routes/ae_commissions_routes.py.
RECIPIENTS = ["pgonzales@vintti.com", "bahia@vintti.com"]


def collect(conn, mes_ini: date, mes_fin: date) -> dict:
    """Los tres bloques del mes. Solo lee: no escribe ni manda nada."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        extra_ok = queries.staffing_extra_exists(cur)

        sql, params = queries.staffing(mes_ini, mes_fin)
        cur.execute(sql, params)
        staffing = [dict(r) for r in cur.fetchall()]

        sql, params = queries.recruiting(mes_ini, mes_fin)
        cur.execute(sql, params)
        recruiting = [dict(r) for r in cur.fetchall()]

        sql, params = queries.m3_churn(mes_ini, mes_fin, staffing_extra_exists=extra_ok)
        cur.execute(sql, params)
        m3 = [dict(r) for r in cur.fetchall()]

    # El fee que se pone en juego en una baja M3 depende del modelo: en Staffing
    # es el fee mensual, en Recruiting el fee one-shot (columna `revenue`).
    for row in m3:
        row["amount"] = (row.get("recruiting_fee")
                         if row.get("opp_model") == "Recruiting"
                         else row.get("fee"))

    return {
        "staffing": staffing,
        "recruiting": recruiting,
        "m3": m3,
        "churn_m3_override_applied": extra_ok,
    }


def execute(period: str | None = None, trigger_source: str = "cli",
            send_email: bool = True, persist: bool = True,
            recipients: list[str] | None = None) -> dict:
    """Corre el reporte de punta a punta y devuelve el artefacto JSON."""
    from db import get_connection

    mes_ini, mes_fin = queries.month_bounds(period)
    to = list(recipients) if recipients else list(RECIPIENTS)

    conn = None
    run_id = None
    try:
        conn = get_connection()
        conn.autocommit = True
        if persist:
            store.ensure_schema(conn)
            run_id = store.start_run(conn, mes_ini, trigger_source)

        payload = collect(conn, mes_ini, mes_fin)
        meta = {
            "run_id": run_id,
            "trigger_source": trigger_source,
            "mes_ini": mes_ini.isoformat(),
            "mes_fin": mes_fin.isoformat(),
            "emailed_to": to if send_email else [],
        }
        artifact = report.to_json(mes_ini, payload, meta)

        if persist:
            store.finish_run(conn, run_id, status="ok", payload=artifact,
                             recipients=to if send_email else None)

        if send_email and to:
            subject, body = report.render(mes_ini, payload)
            from send_email_endpoint import send_email_message

            send_email_message(to, subject, body)
            log.info("Comisiones AE %s: mail enviado a %s",
                     mes_ini.strftime("%Y-%m"), ", ".join(to))

        return artifact

    except Exception as exc:  # noqa: BLE001
        log.exception("Comisiones AE (%s) fallo", period or "mes vencido")
        # Una corrida que muere en silencio es peor que una que no corre: el
        # dia 1 nadie se entera de que falta la data para liquidar.
        if persist and conn is not None and run_id is not None:
            try:
                store.finish_run(conn, run_id, status="error", error_text=str(exc)[:500])
            except Exception:  # noqa: BLE001
                log.exception("No se pudo cerrar el run de comisiones #%s", run_id)
        if send_email and to:
            try:
                from send_email_endpoint import send_email_message

                send_email_message(
                    to, "Comisiones AE - FALLO",
                    "<p>El reporte mensual de comisiones AE no pudo generarse.</p>"
                    f"<pre>{exc}</pre>",
                )
            except Exception:  # noqa: BLE001
                log.exception("Tampoco se pudo avisar por mail")
        raise
    finally:
        if conn is not None:
            conn.close()
