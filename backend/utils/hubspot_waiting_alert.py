"""Mail cuando el sync FRENA un deal esperando una decision.

Se manda SOLO por los que todavia no se avisaron (`notified_at IS NULL`), nunca
por los que siguen esperando: si no, el cron cada 30 min mandaria el mismo mail
48 veces por dia y dejaria de leerse. O sea: un mail por deal frenado, y se
acabo. Si no hay nada frenado, no sale ningun mail.

Destinatarios hardcodeados a proposito, igual que RECIPIENTS del auditor: sin env
var de por medio, para que una variable mal seteada no pueda redirigir el aviso
ni sumar destinatarios por error. Para cambiar la lista hay que editar esa linea,
y solo a pedido de la owner.
"""
from __future__ import annotations

import logging

from utils.transactional_email import email_detail_table, email_shell, post_transactional_email

try:  # today en hora Argentina (mismo criterio que los datasets)
    from dashboards.datasets._now import today_ar
except Exception:  # pragma: no cover - fallback defensivo
    from datetime import date, datetime, timedelta, timezone

    def today_ar() -> "date":
        return (datetime.now(timezone.utc) - timedelta(hours=3)).date()

# pgonzales = owner; mariano = el que carga las opps a mano y por lo tanto el
# unico que sabe si el deal es una busqueda nueva o la que ya tenia cargada.
# Agregado 2026-09-11 a pedido de la owner.
# Tiene que quedar igual a OPP_HUBSPOT_WAITING_ALLOWED de docs/assets/js/main.js,
# que decide quien VE el aviso en la pagina: recibir el mail sin poder resolverlo
# desde Opportunities (o al reves) no le sirve a nadie.
RECIPIENTS = ["pgonzales@vintti.com", "mariano@vintti.com"]

HUB_URL = "https://vinttihub.vintti.com/opportunities.html"


def alerta_en_pausa(hoy=None):
    """True si hoy no se avisa: sabado o domingo, hora Argentina.

    El aviso no se PIERDE, se POSTERGA. El freno ya quedo guardado en
    `hubspot_deals_waiting` con `notified_at` en NULL, asi que la primera corrida
    del lunes lo reclama y manda UN solo mail con todo lo que se acumulo el fin de
    semana — el cuerpo ya es una tabla de N deals, no hace falta nada mas.

    Por eso el corte tiene que ir sobre el CLAIM y no sobre el envio: reclamar la
    fila (marcar notified_at) sin mandar el mail perderia el aviso para siempre,
    que es exactamente el olvido silencioso que esta tabla existe para evitar.

    Hora Argentina y no UTC a proposito: un deal frenado el sabado a las 21:00 ARG
    es domingo 00:00 UTC, y con UTC el mail saldria igual. El cron corre cada 30
    minutos los 7 dias, y un aviso que nadie puede resolver hasta el lunes solo
    sirve para que el lunes ya nadie lo lea.
    """
    hoy = hoy or today_ar()
    return hoy.weekday() >= 5  # 5 = sabado, 6 = domingo


def _fila(deal):
    candidatas = deal.get("candidates") or []
    detalle = ", ".join(
        f"#{c.get('opportunity_id')} {c.get('opp_position_name') or 'sin puesto'}"
        f" ({c.get('opp_stage') or 'sin stage'})"
        for c in candidatas[:4]
    )
    if len(candidatas) > 4:
        detalle += f" y {len(candidatas) - 4} mas"
    return (
        f"{deal.get('account_name') or deal.get('dealname')} · {deal.get('role_to_hire') or 'sin rol'}",
        detalle or "sin candidatas",
    )


def send_waiting_deals_alert(deals):
    """deals: filas RECIEN frenadas de hubspot_deals_waiting."""
    if not deals:
        return {"sent": False, "reason": "nada_para_avisar"}

    cuantos = len(deals)
    intro = (
        f"El sync de HubSpot <strong>frenó {cuantos} deal(s)</strong> porque esa cuenta ya "
        "tiene opportunities sin deal atado: podría ser la misma búsqueda escrita distinto. "
        "<strong>No se creó nada</strong> y no se va a crear hasta que alguien decida.<br/><br/>"
        f'Entrá a <a href="{HUB_URL}">Opportunities</a> y, en cada una, elegí la opportunity '
        "que ya existe o marcala como nueva."
    )
    body = email_shell(intro, email_detail_table([_fila(d) for d in deals]))
    subject = (f"{cuantos} deal(s) de HubSpot esperando tu decisión"
               if cuantos > 1 else "Un deal de HubSpot esperando tu decisión")
    try:
        return post_transactional_email(RECIPIENTS, subject, body, "hubspot_waiting_deals")
    except Exception as exc:  # noqa: BLE001
        # Un mail caido no puede voltear el sync: el freno ya quedo guardado en la
        # tabla y la pagina lo va a mostrar igual.
        logging.exception("No se pudo mandar el aviso de deals frenados: %s", exc)
        return {"sent": False, "error": str(exc)}
