"""Aviso diario a Slack: opps de Mariano paradas +20 días en Deep Dive / NDA Sent.

Un mensaje por día hábil (hora Argentina, desde las 09:00) al canal
SLACK_CHANNEL_ID, mencionando a Mariano con la lista de opps que tiene que
cerrar o mover. Los días se cuentan desde la fecha de la etapa ACTUAL:
`deep_dive_date` si está en Deep Dive, `nda_sent_date` si está en NDA Sent.

Sin opps vencidas no se postea nada. El corte es por construcción: la lista se
recalcula en cada corrida, así que una opp que cambia de stage deja de salir sola.

El cron pega cada hora; `stale_opps_slack_log` (una fila por día) garantiza un
solo mensaje aunque el curl reintente o dos corridas se solapen.

Canal y persona hardcodeados, sin env var, mismo criterio que RECIPIENTS del
auditor: el costo de una variable mal seteada es mencionar a la persona
equivocada delante del equipo.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from psycopg2.extras import RealDictCursor

from daily_digest.people import slack_id
from db import get_connection
from utils import slack
from utils.hubspot_waiting_alert import alerta_en_pausa, today_ar

# Canal "Sales & Opps". Definitivo desde el 2026-09-30 (antes apuntaba al canal
# de prueba C0C0UQ7SYBW).
SLACK_CHANNEL_ID = "C07GZ8RQWF3"
SALES_LEAD = "mariano@vintti.com"
STALE_DAYS = 20
SEND_FROM_HOUR_AR = 9
HUB_BASE = "https://vinttihub.vintti.com"

log = logging.getLogger(__name__)

_schema_ready = False


def _ensure_schema(cur) -> None:
    global _schema_ready
    if _schema_ready:
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS stale_opps_slack_log (
            run_date DATE PRIMARY KEY,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            n_opps INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    _schema_ready = True


def _fetch_stale(cur, hoy) -> List[Dict[str, Any]]:
    cur.execute(
        """
        SELECT o.opportunity_id,
               o.opp_stage,
               o.opp_position_name,
               a.client_name,
               CASE WHEN o.opp_stage = 'Deep Dive' THEN o.deep_dive_date
                    ELSE COALESCE(o.nda_sent_date, o.deep_dive_date) END AS stage_date
          FROM opportunity o
          LEFT JOIN account a ON a.account_id = o.account_id
         WHERE o.opp_stage IN ('Deep Dive', 'NDA Sent')
           AND LOWER(TRIM(o.opp_sales_lead)) = %s
        """,
        (SALES_LEAD,),
    )
    out = []
    for r in cur.fetchall():
        d = r["stage_date"]
        if d is None:
            continue
        days = (hoy - d).days
        if days >= STALE_DAYS:
            out.append({**r, "days": days})
    out.sort(key=lambda r: (r["opp_stage"] != "Deep Dive", -r["days"]))
    return out


def _fmt_date(d) -> str:
    meses = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{d.day:02d}-{meses[d.month - 1]}"


def _line(o: Dict[str, Any]) -> str:
    label = f"{o.get('client_name') or 'Sin cliente'} — {o.get('opp_position_name') or 'Sin puesto'}"
    url = f"{HUB_BASE}/opportunity-detail.html?id={o['opportunity_id']}"
    return f"• {slack.link(url, label)} · desde {_fmt_date(o['stage_date'])} (*{o['days']} días*)"


def _blocks(opps: List[Dict[str, Any]]):
    who = slack.mention(slack_id(SALES_LEAD), "Mariano")
    n = len(opps)
    plural = "oportunidades" if n != 1 else "oportunidad"
    head = (f"Hola {who}, hay *{n} {plural}* que llevan más de {STALE_DAYS} días en "
            f"*Deep Dive / NDA Sent*. Por favor, revísalas y ciérralas o avánzalas "
            f"a la siguiente etapa :point_down:")
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": head}}]
    for stage in ("Deep Dive", "NDA Sent"):
        rows = [o for o in opps if o["opp_stage"] == stage]
        if not rows:
            continue
        # Un section admite 3000 caracteres: se parte en tandas por las dudas.
        lines = [_line(o) for o in rows]
        chunk, chunks = [], []
        for ln in lines:
            if sum(len(x) + 1 for x in chunk) + len(ln) > 2800:
                chunks.append(chunk)
                chunk = []
            chunk.append(ln)
        chunks.append(chunk)
        for i, ch in enumerate(chunks):
            title = f"*{stage}* ({len(rows)})\n" if i == 0 else ""
            blocks.append({"type": "section",
                           "text": {"type": "mrkdwn", "text": title + "\n".join(ch)}})
    text = f"Mariano: {n} {plural} con más de {STALE_DAYS} días en Deep Dive / NDA Sent"
    return blocks, text


def run_stale_opps_alert(dry_run: bool = False) -> Dict[str, Any]:
    hoy = today_ar()
    hora_ar = (datetime.now(timezone.utc) - timedelta(hours=3)).hour

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_schema(cur)
            opps = _fetch_stale(cur, hoy)
    finally:
        conn.close()

    preview = [{"opportunity_id": o["opportunity_id"], "stage": o["opp_stage"],
                "client": o.get("client_name"), "position": o.get("opp_position_name"),
                "stage_date": o["stage_date"].isoformat(), "days": o["days"]}
               for o in opps]
    result: Dict[str, Any] = {"date": hoy.isoformat(), "channel": SLACK_CHANNEL_ID,
                              "count": len(opps), "opps": preview, "posted": False}

    if dry_run:
        result["status"] = "dry_run"
        return result
    if alerta_en_pausa(hoy):
        result["status"] = "weekend"
        return result
    if hora_ar < SEND_FROM_HOUR_AR:
        result["status"] = "too_early"
        return result
    if not opps:
        result["status"] = "nothing_stale"
        return result

    # Se reclama el día ANTES de postear: dos corridas solapadas no duplican.
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stale_opps_slack_log (run_date, n_opps) VALUES (%s, %s)
                ON CONFLICT (run_date) DO NOTHING
                RETURNING run_date
                """,
                (hoy, len(opps)),
            )
            claimed = cur.fetchone() is not None
    finally:
        conn.close()
    if not claimed:
        result["status"] = "already_sent"
        return result

    blocks, text = _blocks(opps)
    sent = slack.post_blocks(blocks, text, channel_override=SLACK_CHANNEL_ID)
    result["slack"] = sent
    if not sent.get("sent"):
        # Se suelta el día para que la próxima corrida lo reintente.
        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("DELETE FROM stale_opps_slack_log WHERE run_date = %s", (hoy,))
        finally:
            conn.close()
        log.error("stale_opps_slack: Slack no aceptó el mensaje: %s", sent.get("error"))
        result["status"] = "slack_error"
        return result

    result["posted"] = True
    result["status"] = "sent"
    return result
