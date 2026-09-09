"""Postear a Slack. Unico punto del repo que le habla a Slack.

Funciona con los dos transportes porque cuando se escribio esto todavia no se
sabia si en el workspace de Vintti se puede instalar una app:

  1. Bot token  (SLACK_BOT_TOKEN + SLACK_CHANNEL_ID) -> chat.postMessage
  2. Webhook    (SLACK_WEBHOOK_URL)                  -> canal fijo, sin scopes

Preferimos el bot: se puede rotar, puede responder en thread y puede leer
`users.list` para cosechar los member IDs. El webhook esta porque suele ser una
aprobacion mas liviana en un workspace cerrado.

No se agrega `slack_sdk`: `requests` ya esta pinneado y ya es el transporte
saliente del repo (ver `utils/transactional_email.py`).
"""
from __future__ import annotations

import json
import logging
import os

import requests

log = logging.getLogger(__name__)

_POST_MESSAGE = "https://slack.com/api/chat.postMessage"
_USERS_LIST = "https://slack.com/api/users.list"
_AUTH_TEST = "https://slack.com/api/auth.test"
_CONV_INFO = "https://slack.com/api/conversations.info"
_TIMEOUT = 20


def esc(value) -> str:
    """Escapa texto para mrkdwn.

    Slack escapa EXACTAMENTE tres caracteres, no es HTML: `&`, `<` y `>`. El `&`
    va primero o se escaparia dos veces. Sin esto, un cliente llamado
    "Smith & Co" o un puesto con un "<" devuelven `invalid_blocks`... con HTTP
    200, asi que el mensaje no sale y nadie se entera.
    """
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def link(url: str, label: str) -> str:
    """Link mrkdwn. Slack NO entiende la sintaxis markdown [label](url)."""
    return f"<{url}|{esc(label)}>"


def mention(member_id: str | None, fallback_name: str) -> str:
    """Mencion real si tenemos el member ID, si no el nombre en negrita.

    Nunca se omite a la persona: sin ID se la ve pero no le suena el celular,
    que es un modo de falla visible y arreglable. Mencionar por mail o por
    @nombre no funciona en la API: hace falta el `U...`.
    """
    return f"<@{member_id}>" if member_id else f"*{esc(fallback_name)}*"


def configured() -> str | None:
    """'bot', 'webhook' o None. Para poder avisar antes de calcular nada."""
    if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_CHANNEL_ID"):
        return "bot"
    if os.environ.get("SLACK_WEBHOOK_URL"):
        return "webhook"
    return None


def post_blocks(blocks: list, text: str, *, channel_override: str | None = None) -> dict:
    """Postea y devuelve {'sent', 'transport', 'error', 'channel'}. NUNCA levanta.

    Que no levante es deliberado: un Slack caido no puede volver 500 al endpoint
    del cron. Quien llama mira `sent` y decide (el digest avisa por mail, que es
    un canal independiente: si lo roto es Slack, avisar por Slack no sirve).
    """
    transport = configured()
    payload = {"blocks": blocks, "text": text,
               "unfurl_links": False, "unfurl_media": False}

    if transport == "bot":
        channel = channel_override or os.environ["SLACK_CHANNEL_ID"]
        payload["channel"] = channel
        try:
            resp = requests.post(
                _POST_MESSAGE, json=payload, timeout=_TIMEOUT,
                headers={"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}",
                         "Content-Type": "application/json; charset=utf-8"})
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Slack: no se pudo postear: %s", exc)
            return {"sent": False, "transport": "bot", "error": str(exc)[:300],
                    "channel": channel}
        # OJO: Slack devuelve HTTP 200 aunque falle. El status no dice nada;
        # lo que importa es `ok`. El error tipico del setup es `not_in_channel`:
        # la app existe pero nadie la invito al canal (`/invite @VinttiHub`).
        if not data.get("ok"):
            log.error("Slack rechazo el mensaje: %s", data.get("error"))
            return {"sent": False, "transport": "bot",
                    "error": data.get("error") or "unknown", "channel": channel}
        return {"sent": True, "transport": "bot", "error": None, "channel": channel,
                "ts": data.get("ts")}

    if transport == "webhook":
        if channel_override:
            # El canal del webhook viene fijado desde Slack. Se avisa fuerte para
            # que un override ignorado no parezca que funciono.
            log.warning("Slack: channel_override=%s IGNORADO (transporte webhook)",
                        channel_override)
        try:
            resp = requests.post(os.environ["SLACK_WEBHOOK_URL"], json=payload,
                                 timeout=_TIMEOUT)
        except requests.RequestException as exc:
            log.error("Slack: no se pudo postear al webhook: %s", exc)
            return {"sent": False, "transport": "webhook", "error": str(exc)[:300],
                    "channel": None}
        if resp.status_code != 200 or (resp.text or "").strip().lower() != "ok":
            log.error("Slack webhook fallo: %s %s", resp.status_code, resp.text[:200])
            return {"sent": False, "transport": "webhook",
                    "error": f"{resp.status_code}: {resp.text[:200]}", "channel": None}
        return {"sent": True, "transport": "webhook", "error": None, "channel": None}

    log.warning("Slack no configurado: falta SLACK_BOT_TOKEN + SLACK_CHANNEL_ID "
                "o SLACK_WEBHOOK_URL. No se posteo nada.")
    return {"sent": False, "transport": None, "error": "not_configured", "channel": None}


def list_members(domain: str = "vintti.com") -> dict:
    """mail -> member ID, para llenar `daily_digest/people.py` una sola vez.

    Requiere los scopes `users:read` y `users:read.email`, que el cron NO
    necesita (le alcanza con `chat:write`).
    """
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return {"ok": False, "error": "SLACK_BOT_TOKEN no configurado", "members": {}}

    members, cursor = {}, None
    try:
        while True:
            resp = requests.get(
                _USERS_LIST, timeout=_TIMEOUT,
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": 200, **({"cursor": cursor} if cursor else {})})
            data = resp.json()
            if not data.get("ok"):
                return {"ok": False, "error": _detalle_error(data), "members": {}}
            for m in data.get("members") or []:
                if m.get("deleted") or m.get("is_bot"):
                    continue
                email = ((m.get("profile") or {}).get("email") or "").strip().lower()
                if email and email.endswith("@" + domain):
                    members[email] = m.get("id")
            cursor = ((data.get("response_metadata") or {}).get("next_cursor") or "").strip()
            if not cursor:
                break
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "error": str(exc)[:300], "members": members}

    return {"ok": True, "error": None, "members": dict(sorted(members.items()))}


def post_thread_reply(channel: str, thread_ts: str, blocks: list, text: str) -> dict:
    """Responde dentro del hilo de un mensaje ya posteado. NUNCA levanta.

    Es la unica forma de tener un "ver mas" en Slack sin montar un endpoint de
    interactividad (un boton obliga a exponer una Request URL publica y a
    verificar la firma de cada request; para desplegar una lista no lo vale).
    El hilo lo da Slack gratis: el canal queda corto y el detalle esta a un click.

    Solo funciona con bot token: un Incoming Webhook no devuelve el `ts` del
    mensaje, asi que no hay a que responderle.
    """
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return {"sent": False, "error": "sin bot token, no se puede responder en hilo"}
    try:
        resp = requests.post(
            _POST_MESSAGE, timeout=_TIMEOUT,
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
            json={"channel": channel, "thread_ts": thread_ts, "blocks": blocks,
                  "text": text, "unfurl_links": False, "unfurl_media": False})
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("Slack: no se pudo responder en el hilo: %s", exc)
        return {"sent": False, "error": str(exc)[:300]}
    if not data.get("ok"):
        log.error("Slack rechazo la respuesta del hilo: %s", data.get("error"))
        return {"sent": False, "error": _detalle_error(data)}
    return {"sent": True, "error": None, "ts": data.get("ts")}


def _detalle_error(data: dict) -> str:
    """Mensaje de error de Slack, con el scope que falta si lo dice.

    En `missing_scope` la respuesta trae `needed` y `provided`; sin eso el error
    es solo la palabra 'missing_scope' y hay que adivinar cual de los veinte.
    """
    err = data.get("error")
    if not err:
        return ""
    if err == "missing_scope" and data.get("needed"):
        return f"missing_scope: falta '{data['needed']}'"
    return str(err)


def diagnose() -> dict:
    """Chequeo de setup, paso por paso. Para `python -m daily_digest --check`.

    Existe porque los tres errores tipicos de esta configuracion son invisibles:
    Slack contesta HTTP 200 en los tres casos y el mensaje simplemente no
    aparece. Cada chequeo se hace contra la API de verdad, no contra el .env.
    """
    pasos: list[dict] = []

    def ok(nombre, bien, detalle=""):
        pasos.append({"paso": nombre, "ok": bool(bien), "detalle": detalle})
        return bien

    transporte = configured()
    if not ok("Transporte configurado", transporte,
              transporte or "falta SLACK_BOT_TOKEN + SLACK_CHANNEL_ID, o SLACK_WEBHOOK_URL"):
        return {"transport": None, "pasos": pasos}

    if transporte == "webhook":
        ok("Webhook", True, "canal fijado desde Slack; no se puede verificar sin postear")
        return {"transport": "webhook", "pasos": pasos}

    token = os.environ["SLACK_BOT_TOKEN"]
    canal = os.environ["SLACK_CHANNEL_ID"]
    head = {"Authorization": f"Bearer {token}"}

    try:
        data = requests.post(_AUTH_TEST, headers=head, timeout=_TIMEOUT).json()
    except (requests.RequestException, ValueError) as exc:
        ok("Token valido", False, str(exc)[:200])
        return {"transport": "bot", "pasos": pasos}

    if not ok("Token valido", data.get("ok"),
              _detalle_error(data) or f"app '{data.get('user')}' en '{data.get('team')}'"):
        return {"transport": "bot", "pasos": pasos}

    bot_id = data.get("user_id")
    try:
        info = requests.get(_CONV_INFO, headers=head, timeout=_TIMEOUT,
                            params={"channel": canal}).json()
    except (requests.RequestException, ValueError) as exc:
        ok("Canal existe", False, str(exc)[:200])
        return {"transport": "bot", "bot_user_id": bot_id, "pasos": pasos}

    ch = info.get("channel") or {}
    if not info.get("ok"):
        # `missing_scope` aca NO bloquea nada: conversations.info es solo para
        # este diagnostico. El cron postea con chat:write y nada mas. Se informa
        # como aviso, no como falta, para no mandar a nadie a pedir permisos que
        # el digest no necesita.
        if info.get("error") == "missing_scope":
            pasos.append({
                "paso": "Canal verificable (opcional)", "ok": True, "aviso": True,
                "detalle": (f"sin verificar: la app no tiene "
                            f"'{info.get('needed')}'. No hace falta para postear; "
                            f"agregalo solo si querés que este chequeo lo confirme"),
            })
            return {"transport": "bot", "bot_user_id": bot_id, "pasos": pasos}
        # `channel_not_found` con un ID bien escrito casi siempre es un canal
        # privado al que la app no fue invitada: no lo ve, ni para leer el nombre.
        ok("Canal existe y es visible", False, info.get("error"))
        return {"transport": "bot", "bot_user_id": bot_id, "pasos": pasos}
    ok("Canal existe y es visible", True, f"#{ch.get('name')}")

    ok("La app esta EN el canal", ch.get("is_member"),
       "listo" if ch.get("is_member")
       else f"falta invitarla: escribi '/invite @{data.get('user')}' dentro de #{ch.get('name')}")

    return {"transport": "bot", "bot_user_id": bot_id,
            "channel_name": ch.get("name"), "pasos": pasos}


def payload_size(blocks: list) -> int:
    """Bytes del payload, para chequear contra el techo de Slack antes de mandar."""
    return len(json.dumps(blocks, ensure_ascii=False))
