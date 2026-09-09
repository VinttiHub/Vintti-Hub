"""Arma el mensaje de Slack (Block Kit) y su version en texto plano.

Decision de layout que sostiene todo el resto: **un `section` por PERSONA, no
por item**. Slack corta en 50 bloques por mensaje, 3000 caracteres por
`section.text` y ~40000 por payload. Doce personas son 16 bloques y entra
comodo; un bloque por item revienta el techo el primer dia.
"""
from __future__ import annotations

import os

from dashboards.datasets._now import today_ar
from utils.slack import esc, link, mention, payload_size

from . import people

# Mismo patron que `ae_commissions/report.py`: base del front con override por
# env, para poder apuntar los links a un entorno de prueba.
FRONT_BASE_URL = os.environ.get("FRONT_BASE_URL", "https://vinttihub.vintti.com")

_DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")

EMOJI = {"pricing": ":dollar:", "jd": ":memo:", "base": ":card_index_dividers:"}

TITULO = {
    "pricing": "Pricing sin cargar",
    "jd": "Falta job description",
    "base": "Faltan datos",
}

# Techo defensivo. Se mide el payload de verdad en vez de confiar en la cuenta.
_MAX_BYTES = 35000


def fecha_larga(d=None) -> str:
    d = d or today_ar()
    return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]}"


def antiguedad(days: int | None) -> str:
    """'hace N dias' en castellano, con los bordes que se leen raro."""
    if days is None:
        return "sin fecha"
    if days <= 0:
        return "hoy"
    if days == 1:
        return "desde ayer"
    if days > 60:
        return "hace mas de 2 meses"
    return f"hace {days} dias"


def url_item(item: dict) -> str:
    """El link lleva a la pagina donde se carga el dato, no a la opp siempre.

    El pricing del hire se edita UNICAMENTE en candidate-details (ver
    `docs/assets/js/main.js`, que redirige ahi despues de un Close Win);
    mandarlo a opportunity-detail seria mandarlo a una pantalla donde el campo
    no existe.
    """
    if item["rule"] == "pricing" and item.get("candidate_id"):
        return f"{FRONT_BASE_URL}/candidate-details.html?id={item['candidate_id']}#hire"
    return f"{FRONT_BASE_URL}/opportunity-detail.html?id={item['opportunity_id']}"


def _etiqueta(item: dict) -> str:
    partes = [p for p in (item.get("client_name"), item.get("position")) if p]
    return " - ".join(partes) or f"Opp {item['opportunity_id']}"


def _linea(item: dict) -> str:
    rule = item["rule"]
    if rule == "base":
        titulo = "Faltan " + ", ".join(item.get("missing") or [])
    elif rule == "pricing":
        titulo = TITULO[rule] + " (" + ", ".join(item.get("missing") or []) + ")"
    else:
        titulo = TITULO[rule]

    trozos = [f"{EMOJI.get(rule, ':small_blue_diamond:')} {esc(titulo)}",
              link(url_item(item), _etiqueta(item))]
    if item.get("candidate_name"):
        trozos.append(f"({esc(item['candidate_name'])})")
    trozos.append(antiguedad(item.get("days")))
    return "  \u2022 " + " \u00b7 ".join(trozos)


def agrupar(findings: list[dict]) -> tuple[list[tuple[str, list]], list[dict]]:
    """(personas ordenadas, huerfanos).

    Huerfano = el duenio no existe en `users` o esta desactivado. No se
    descartan: si se filtraran en el WHERE, una opp de alguien que ya no trabaja
    aca no generaria fila y nadie se enteraria nunca. Van en una linea aparte
    dirigida a la owner.
    """
    huerfanos = [f for f in findings if not f.get("owner_active")]
    vivos = [f for f in findings if f.get("owner_active")]

    por_persona: dict[str, list] = {}
    for f in vivos:
        por_persona.setdefault(f["owner_email"], []).append(f)
    for items in por_persona.values():
        items.sort(key=lambda i: (-(i.get("days") or 0), i["rule"]))

    orden = sorted(por_persona.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return orden, huerfanos


def build(findings: list[dict], *, fallos: list[str] | None = None,
          heartbeat: bool = False) -> tuple[list, str]:
    """(blocks, texto fallback). `blocks` vacio = hoy no se postea nada."""
    orden, huerfanos = agrupar(findings)
    fallos = fallos or []

    if not findings and not fallos:
        if not heartbeat:
            return [], ""
        return ([{"type": "section", "text": {"type": "mrkdwn",
                  "text": f":white_check_mark: *Todo al dia* - {fecha_larga()}. "
                          "Ningun dato pendiente de carga."}}],
                "Todo al dia: ningun dato pendiente")

    total = len(findings)
    blocks: list = [
        {"type": "header", "text": {"type": "plain_text",
         "text": f"Pendientes de carga - {fecha_larga()}", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn",
         "text": f"{total} pendientes - {len(orden)} personas"}]},
        {"type": "divider"},
    ]

    sin_slack_id: list[str] = []
    for email, items in orden[:people.MAX_PEOPLE]:
        nombre = items[0].get("owner_name") or email
        mid = people.slack_id(email)
        if not mid:
            sin_slack_id.append(email)

        visibles = items[:people.MAX_ITEMS_PER_PERSON]
        lineas = [_linea(i) for i in visibles]
        if len(items) > len(visibles):
            lineas.append(f"  \u2022 _y {len(items) - len(visibles)} mas \u2014 estan en el hilo_ :thread:")

        cuenta = "1 pendiente" if len(items) == 1 else f"{len(items)} pendientes"
        cuerpo = f"{mention(mid, nombre)}  *{cuenta}*\n" + "\n".join(lineas)
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": cuerpo[:2900]}})

    pie: list[str] = []
    if len(orden) > people.MAX_PEOPLE:
        resto = sum(len(i) for _e, i in orden[people.MAX_PEOPLE:])
        pie.append(f"+{len(orden) - people.MAX_PEOPLE} personas mas "
                   f"({resto} pendientes) sin listar.")
    if huerfanos:
        cuentas = sorted({(h.get("owner_email") or "sin duenio") for h in huerfanos})
        pie.append(f":warning: {len(huerfanos)} pendientes *sin duenio activo* "
                   f"({esc(', '.join(cuentas))}) - hay que reasignarlos.")
    if sin_slack_id:
        pie.append(f"Sin Slack ID (se muestran, no se mencionan): "
                   f"{esc(', '.join(sin_slack_id))}")
    if fallos:
        pie.append(f":warning: no se pudo calcular: {esc(', '.join(fallos))}")
    pie.append("Se repite todos los dias hasta que el dato este cargado.")

    blocks.append({"type": "divider"})
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn", "text": "\n".join(pie)[:2900]}]})

    # El fallback de nivel superior no es opcional: sin el, el push del celular
    # llega en blanco.
    texto = f"Pendientes de carga: {total} en {len(orden)} personas"

    if payload_size(blocks) > _MAX_BYTES:
        blocks = _compacto(orden, huerfanos, total)
    return blocks, texto


def hay_overflow(findings: list[dict]) -> bool:
    orden, _ = agrupar(findings)
    return any(len(items) > people.MAX_ITEMS_PER_PERSON for _e, items in orden)


def build_detalle(findings: list[dict]) -> list[tuple[list, str]]:
    """El detalle COMPLETO, para responder en el hilo. Devuelve [(blocks, text)].

    Solo lista a la gente que quedo truncada en el mensaje principal: repetir a
    quien ya se ve entero convierte el hilo en una segunda copia del mensaje.

    Puede devolver mas de una respuesta: el techo de 50 bloques por mensaje
    aplica igual dentro de un hilo, y una persona con 60 pendientes no entra en
    un solo `section` de 3000 caracteres.
    """
    orden, _ = agrupar(findings)
    truncados = [(e, items) for e, items in orden
                 if len(items) > people.MAX_ITEMS_PER_PERSON]
    if not truncados:
        return []

    mensajes: list[tuple[list, str]] = []
    bloques: list = []

    def cerrar():
        if bloques:
            mensajes.append((list(bloques), "Detalle completo de pendientes"))
            bloques.clear()

    for email, items in truncados:
        nombre = items[0].get("owner_name") or email
        # Nombre en negrita, NO mencion: en el mensaje principal ya se los
        # menciono, y `<@U...>` dentro del hilo vuelve a notificar. Dos pings por
        # persona por dia es exactamente el ruido que este digest tiene que evitar.
        cabecera = f"*{esc(nombre)}* - los {len(items)} pendientes"
        # Se parte en trozos que entren en un section (3000 chars de techo).
        trozo: list[str] = [cabecera]
        for linea in (_linea(i) for i in items):
            tentativo = "\n".join(trozo + [linea])
            if len(tentativo) > 2800:
                bloques.append({"type": "section",
                                "text": {"type": "mrkdwn", "text": "\n".join(trozo)}})
                trozo = [f"{esc(nombre)} _(sigue)_", linea]
                if len(bloques) >= 45:
                    cerrar()
            else:
                trozo.append(linea)
        bloques.append({"type": "section",
                        "text": {"type": "mrkdwn", "text": "\n".join(trozo)}})
        if len(bloques) >= 45:
            cerrar()

    cerrar()
    return mensajes


def _compacto(orden, huerfanos, total) -> list:
    """Degradado: una linea por persona. Solo si el payload no entra."""
    lineas = [f"{mention(people.slack_id(e), items[0].get('owner_name') or e)}: "
              f"{len(items)}" for e, items in orden]
    if huerfanos:
        lineas.append(f":warning: sin duenio activo: {len(huerfanos)}")
    return [
        {"type": "header", "text": {"type": "plain_text",
         "text": f"Pendientes de carga - {fecha_larga()}", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn",
         "text": (f"{total} pendientes. Detalle en el Hub.\n" + "\n".join(lineas))[:2900]}},
    ]


def to_text(findings: list[dict], *, fallos=None) -> str:
    """Version plana, para la CLI y para el mail de fallo."""
    orden, huerfanos = agrupar(findings)
    out = [f"Pendientes de carga - {fecha_larga()} - {len(findings)} en {len(orden)} personas"]
    for email, items in orden:
        out.append(f"\n{items[0].get('owner_name') or email}  ({len(items)})")
        for i in items:
            det = ", ".join(i.get("missing") or [])
            out.append(f"   [{i['rule']:7}] {_etiqueta(i)} | {det} | {antiguedad(i.get('days'))}")
    if huerfanos:
        out.append(f"\nSIN DUENIO ACTIVO ({len(huerfanos)}):")
        for h in huerfanos:
            out.append(f"   {h.get('owner_email') or '(vacio)'} - {_etiqueta(h)}")
    for f in (fallos or []):
        out.append(f"\nREGLA CAIDA: {f}")
    return "\n".join(out)
