"""Orquesta una corrida: consulta, arma el mensaje, postea y persiste.

Sincrono, como `ae_commissions` y a diferencia de la auditoria del dashboard:
son tres queries, no ~316, y terminan en segundos. No hace falta el hilo ni el
202.
"""
from __future__ import annotations

import logging

from psycopg2.extras import RealDictCursor

from dashboards.datasets._now import today_ar
from utils.html_utils import html_to_plain_text

from . import people, queries, render, store

log = logging.getLogger(__name__)

RECIPIENTS = people.RECIPIENTS


def _dias(anchor, hoy) -> int | None:
    return None if anchor is None else (hoy - anchor).days


def _jd_realmente_vacia(row) -> bool:
    """?El HTML de la JD es texto de verdad o son tags vacios?

    La columna es HTML y casi nunca es NULL: viene con `<p></p>`, `<br>` o un
    `<p>TBD</p>`. Se decide con `html_to_plain_text`, el stripper que el resto
    del repo ya usa para la misma columna (ai_routes, hirex, talentum). Escribir
    una segunda semantica en SQL seria garantizar que las dos se despeguen.
    """
    return len(html_to_plain_text(row.get("jd_raw") or "").strip()) < people.JD_MIN_CHARS


def collect(conn, solo_regla: str | None = None) -> dict:
    """Los pendientes de hoy. Solo lee: no escribe ni postea nada.

    Cada regla va en su propia query y en su propio try. Si una se rompe, las
    otras se postean igual y el mensaje lo dice: un digest mudo es peor que uno
    incompleto (mismo criterio que `dashboards/audit/runner.py`).
    """
    hoy = today_ar()
    findings: list[dict] = []
    fallos: list[str] = []
    por_regla: dict[str, int] = {}

    reglas = ({solo_regla: queries.RULES[solo_regla]} if solo_regla
              else dict(queries.RULES))

    for nombre, fn in reglas.items():
        try:
            sql, params = fn()
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                filas = [dict(r) for r in cur.fetchall()]
            if nombre == "jd":
                filas = [f for f in filas if _jd_realmente_vacia(f)]
            for f in filas:
                f.pop("jd_raw", None)
                f["days"] = _dias(f.get("anchor_date"), hoy)
                f["url"] = render.url_item(f)
            findings.extend(filas)
            por_regla[nombre] = len(filas)
        except Exception:  # noqa: BLE001
            log.exception("Digest: la regla '%s' fallo", nombre)
            fallos.append(nombre)
            por_regla[nombre] = -1
            # Sin esto el aislamiento entre reglas es mentira: si la conexion no
            # esta en autocommit, el error deja la transaccion abortada y las
            # reglas siguientes fallan todas con "current transaction is aborted"
            # ([[reference_txn_abortada_borra_todo]]). Los dos call sites de hoy
            # usan autocommit, pero eso no se puede garantizar desde aca.
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass

    orden, huerfanos = render.agrupar(findings)
    return {
        "findings": findings,
        "fallos": fallos,
        "por_regla": por_regla,
        "total": len(findings),
        "people_total": len(orden),
        "huerfanos": len(huerfanos),
        "run_date": hoy.isoformat(),
    }


def execute(trigger_source: str = "cli", *, post: bool = True, persist: bool = True,
            solo_regla: str | None = None, channel_override: str | None = None) -> dict:
    """Corre el digest de punta a punta y devuelve el artefacto JSON."""
    from db import get_connection

    hoy = today_ar()
    conn = None
    run_id = None
    try:
        conn = get_connection()
        conn.autocommit = True

        if persist:
            store.ensure_schema(conn)
            run_id = store.start_run(conn, hoy, trigger_source)

        # Solo lectura sobre la conexion del calculo: un write accidental falla
        # fuerte aca en vez de bajito en produccion. Y `application_name` es lo
        # que hace encontrable esta corrida en pg_stat_activity a las 9 de la
        # manana.
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = '25s'")
            cur.execute("SET application_name = 'daily_digest'")
            cur.execute("SET default_transaction_read_only = on")

        payload = collect(conn, solo_regla=solo_regla)

        with conn.cursor() as cur:
            cur.execute("SET default_transaction_read_only = off")

        heartbeat = people.POSTEAR_SIN_PENDIENTES
        blocks, texto = render.build(payload["findings"], fallos=payload["fallos"],
                                     heartbeat=heartbeat)
        payload["blocks"] = blocks
        payload["text"] = texto
        payload["heartbeat"] = heartbeat
        payload["meta"] = {"run_id": run_id, "trigger_source": trigger_source}

        slack = {"sent": False, "transport": None, "error": None}
        if post and blocks:
            from utils import slack as slack_api

            slack = slack_api.post_blocks(blocks, texto,
                                          channel_override=channel_override)
            # El detalle de quien quedo truncado va como respuesta en el hilo:
            # el canal queda corto y el resto esta a un click, sin necesidad de
            # un boton (que obligaria a exponer un endpoint de interactividad).
            # Si falla, se loguea y ya: el mensaje principal ya salio y es lo
            # que importa; no se vuelve a postear nada.
            if slack.get("sent") and slack.get("ts"):
                hilos = render.build_detalle(payload["findings"])
                enviados = 0
                for b_detalle, t_detalle in hilos:
                    r = slack_api.post_thread_reply(
                        slack["channel"], slack["ts"], b_detalle, t_detalle)
                    if not r.get("sent"):
                        log.warning("Digest: no se pudo colgar el detalle del hilo: %s",
                                    r.get("error"))
                        break
                    enviados += 1
                slack["thread_replies"] = enviados
        elif post and not blocks:
            log.info("Digest: sin pendientes y no es lunes, no se postea.")
        payload["slack"] = slack

        # El orden importa: se postea ANTES de cerrar el run, y si el cierre
        # falla se loguea pero se devuelve 200 igual. El curl del cron reintenta
        # 3 veces; un 500 posterior a un post exitoso le mandaria el mismo
        # digest tres veces al canal.
        if persist and run_id is not None:
            try:
                store.finish_run(
                    conn, run_id,
                    status="ok" if not payload["fallos"] else "partial",
                    payload={k: payload[k] for k in
                             ("findings", "por_regla", "total", "people_total",
                              "huerfanos", "fallos", "run_date")},
                    findings_total=payload["total"],
                    people_total=payload["people_total"],
                    slack_transport=slack.get("transport"),
                    slack_error=slack.get("error"))
            except Exception:  # noqa: BLE001
                log.exception("No se pudo cerrar el run del digest #%s", run_id)

        if post and blocks and not slack.get("sent"):
            # `not_configured` es un estado de setup, no una falla: todavia no se
            # instalo la app. Se corta igual (el job queda en rojo y se ve), pero
            # sin mandarle un mail por dia a la owner por algo que ya sabe.
            if slack.get("error") != "not_configured":
                _avisar_por_mail(payload, slack)
            raise RuntimeError(f"Slack no acepto el mensaje: {slack.get('error')}")

        return payload

    except Exception as exc:  # noqa: BLE001
        log.exception("Digest diario: la corrida fallo")
        if persist and conn is not None and run_id is not None:
            try:
                store.finish_run(conn, run_id, status="error",
                                 error_text=str(exc)[:500])
            except Exception:  # noqa: BLE001
                log.exception("Tampoco se pudo cerrar el run #%s", run_id)
        raise
    finally:
        if conn is not None:
            conn.close()


def _avisar_por_mail(payload: dict, slack: dict) -> None:
    """Si Slack no acepto el mensaje, el aviso sale por mail.

    Dos canales independientes a proposito: si lo que se rompio es Slack,
    avisar por Slack no sirve de nada.
    """
    if not RECIPIENTS:
        return
    try:
        from send_email_endpoint import send_email_message

        detalle = render.to_text(payload["findings"], fallos=payload["fallos"])
        send_email_message(
            RECIPIENTS, "Digest diario - NO se pudo postear a Slack",
            "<p>El digest se calculo bien pero Slack rechazo el mensaje.</p>"
            f"<p><b>Error:</b> {slack.get('error')} "
            f"(transporte: {slack.get('transport') or 'sin configurar'})</p>"
            f"<pre>{detalle}</pre>")
    except Exception:  # noqa: BLE001
        log.exception("Tampoco se pudo avisar por mail")
