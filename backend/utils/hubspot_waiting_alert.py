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

# pgonzales = owner; mariano = el que carga las opps a mano y por lo tanto el
# unico que sabe si el deal es una busqueda nueva o la que ya tenia cargada.
# Agregado 2026-09-11 a pedido de la owner.
RECIPIENTS = ["pgonzales@vintti.com", "mariano@vintti.com"]

HUB_URL = "https://vinttihub.vintti.com/opportunities.html"


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
