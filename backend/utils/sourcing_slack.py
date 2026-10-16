"""Aviso a Slack cuando una opp entra a Sourcing por PRIMERA vez.

Para que las recruiters se enteren en el momento de que arrancó una vacante.
Lo disparan los dos caminos que mueven una opp a Sourcing, siempre DESPUÉS del
commit y sin levantar nunca:

  - `update_opportunity_stage` (cambio manual en el hub).
  - El sync de HubSpot (NDA Signed -> Sourcing, o una opp creada directo ahí).

"Primera vez" son dos frenos, y hacen falta los dos:

  1. `previous_stage` tiene que ser pre-Sourcing (vacío, Deep Dive, NDA Sent).
     Una reactivación desde Stop / Closed Lost o una vuelta desde Interviewing
     no es una opp nueva (decisión de la owner, 2026-10-16).
  2. `sourcing_slack_notified` (una fila por opp) — una opp que volvió a NDA Sent
     y entra de nuevo a Sourcing no avisa dos veces. Al crearse, la tabla se
     siembra con todas las opps que YA pasaron por Sourcing, así el deploy no
     dispara avisos por opps viejas.

Canal hardcodeado, sin env var, mismo criterio que `stale_opps_slack.py`.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from psycopg2.extras import RealDictCursor

from daily_digest.people import slack_id
from db import get_connection
from utils import slack

# Canal "Sales & Opps". Definitivo desde el 2026-10-16 (antes apuntaba al canal
# de prueba C0C0UQ7SYBW).
SLACK_CHANNEL_ID = "C07GZ8RQWF3"
HUB_BASE = "https://vinttihub.vintti.com"

SOURCING_STAGE = "Sourcing"
PRE_SOURCING_STAGES = ("", "deep dive", "nda sent")
# Para la siembra: stages a los que sólo se llega pasando por Sourcing.
_POST_SOURCING_STAGES = ("sourcing", "interviewing", "negotiating", "signed", "close win")

log = logging.getLogger(__name__)

_schema_ready = False


def _ensure_schema(cur, exclude_opportunity_id: Optional[int]) -> None:
    global _schema_ready
    if _schema_ready:
        return
    cur.execute("SELECT to_regclass('public.sourcing_slack_notified') IS NOT NULL AS ok")
    existed = cur.fetchone()["ok"]
    if not existed:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sourcing_slack_notified (
                opportunity_id INTEGER PRIMARY KEY,
                notified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                channel TEXT,
                slack_ts TEXT,
                seeded BOOLEAN NOT NULL DEFAULT FALSE
            )
            """
        )
        # Siembra única: todo lo que ya pasó por Sourcing cuenta como avisado.
        # Se excluye la opp que dispara la llamada: su commit ya la dejó en
        # Sourcing con start date, y sembrarla se comería su propio aviso.
        cur.execute(
            """
            INSERT INTO sourcing_slack_notified (opportunity_id, notified_at, seeded)
            SELECT o.opportunity_id, now(), TRUE
              FROM opportunity o
             WHERE o.opportunity_id <> COALESCE(%s, -1)
               AND (LOWER(TRIM(COALESCE(o.opp_stage, ''))) = ANY(%s)
                    OR o.nda_signature_or_start_date IS NOT NULL
                    OR EXISTS (SELECT 1 FROM sourcing s
                                WHERE s.opportunity_id = o.opportunity_id))
            ON CONFLICT (opportunity_id) DO NOTHING
            """,
            (exclude_opportunity_id, list(_POST_SOURCING_STAGES)),
        )
        log.info("sourcing_slack: tabla creada, %s opps sembradas", cur.rowcount)
    _schema_ready = True


def _is_pre_sourcing(stage: Optional[str]) -> bool:
    return (stage or "").strip().lower() in PRE_SOURCING_STAGES


def _fmt_date(d) -> str:
    meses = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{d.day:02d}-{meses[d.month - 1]}"


def _person(cur, email: Optional[str], mention: bool) -> str:
    """Sólo la HR lead se menciona (decisión de la owner); el resto va por nombre."""
    email = (email or "").strip().lower()
    # El desplegable guarda su placeholder ("select sales lead") cuando nadie
    # eligió a nadie: cualquier cosa que no sea un mail cuenta como vacío.
    if "@" not in email:
        return "_sin asignar_"
    cur.execute(
        "SELECT user_name FROM users WHERE LOWER(TRIM(email_vintti)) = %s LIMIT 1",
        (email,),
    )
    row = cur.fetchone()
    name = (row or {}).get("user_name") or email
    if not mention:
        return slack.esc(name)
    return slack.mention(slack_id(email), name)


def _fetch_context(cur, opportunity_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT o.opportunity_id, o.opp_stage, o.opp_position_name, o.opp_model,
               o.opp_sales_lead, o.opp_hr_lead, o.nda_signature_or_start_date,
               a.client_name
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
         WHERE o.opportunity_id = %s
        """,
        (opportunity_id,),
    )
    return cur.fetchone()


def _blocks(cur, ctx: Dict[str, Any]):
    label = f"{ctx.get('client_name') or 'Sin cliente'} — {ctx.get('opp_position_name') or 'Sin puesto'}"
    url = f"{HUB_BASE}/opportunity-detail.html?id={ctx['opportunity_id']}"
    head = f":rocket: *Nueva opp en Sourcing* — {slack.link(url, label)}"
    start = ctx.get("nda_signature_or_start_date")
    detalle = " · ".join([
        f"Modelo: {slack.esc(ctx.get('opp_model') or '—')}",
        f"Sales lead: {_person(cur, ctx.get('opp_sales_lead'), mention=False)}",
        f"HR lead: {_person(cur, ctx.get('opp_hr_lead'), mention=True)}",
        f"Start date: {_fmt_date(start) if start else '—'}",
    ])
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"{head}\n{detalle}"}}]
    text = f"Nueva opp en Sourcing: {label}"
    return blocks, text


def notify_first_sourcing(opportunity_id: int, previous_stage: Optional[str]) -> Dict[str, Any]:
    """Postea el aviso si es la primera entrada a Sourcing. NUNCA levanta."""
    result: Dict[str, Any] = {"opportunity_id": opportunity_id, "posted": False}
    try:
        if not _is_pre_sourcing(previous_stage):
            result["status"] = "not_new"
            return result

        conn = get_connection()
        try:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                _ensure_schema(cur, opportunity_id)
                ctx = _fetch_context(cur, opportunity_id)
                if not ctx or (ctx.get("opp_stage") or "").strip() != SOURCING_STAGE:
                    result["status"] = "not_in_sourcing"
                    return result
                # Se reclama ANTES de postear: dos requests solapados no duplican.
                cur.execute(
                    """
                    INSERT INTO sourcing_slack_notified (opportunity_id, channel)
                    VALUES (%s, %s)
                    ON CONFLICT (opportunity_id) DO NOTHING
                    RETURNING opportunity_id
                    """,
                    (opportunity_id, SLACK_CHANNEL_ID),
                )
                if cur.fetchone() is None:
                    result["status"] = "already_notified"
                    return result
                blocks, text = _blocks(cur, ctx)
        finally:
            conn.close()

        sent = slack.post_blocks(blocks, text, channel_override=SLACK_CHANNEL_ID)
        result["slack"] = sent
        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                if sent.get("sent"):
                    cur.execute(
                        "UPDATE sourcing_slack_notified SET slack_ts = %s WHERE opportunity_id = %s",
                        (sent.get("ts"), opportunity_id),
                    )
                else:
                    # Se suelta para no dejar una opp marcada como avisada sin aviso.
                    cur.execute(
                        "DELETE FROM sourcing_slack_notified WHERE opportunity_id = %s",
                        (opportunity_id,),
                    )
        finally:
            conn.close()
        if not sent.get("sent"):
            log.error("sourcing_slack: Slack no aceptó el aviso de la opp %s: %s",
                      opportunity_id, sent.get("error"))
            result["status"] = "slack_error"
            return result
        result["posted"] = True
        result["status"] = "sent"
        return result
    except Exception as exc:  # noqa: BLE001
        log.exception("sourcing_slack: falló el aviso de la opp %s", opportunity_id)
        result["status"] = "error"
        result["error"] = str(exc)[:300]
        return result


def notify_first_sourcing_async(opportunity_id: int, previous_stage: Optional[str]) -> None:
    """Lo mismo en un hilo: el POST a Slack (hasta 20 s) no demora el cambio de stage."""
    def _run():
        out = notify_first_sourcing(opportunity_id, previous_stage)
        logging.info("sourcing slack opp=%s → %s", opportunity_id, out.get("status"))

    threading.Thread(target=_run, daemon=True).start()
