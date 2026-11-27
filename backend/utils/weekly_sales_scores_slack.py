"""«📊 WEEKLY SALES SCORES» a Slack, los lunes desde las 07:00 (hora Argentina).

Reemplaza el mensaje que se armaba a mano (pedido de la owner, 2026-11-27). Sin IA: los
números salen de `prospecting.panels.sqls_by_bdr`, el mismo panel «SQLs by BDR» de
Prospecting → Paneles (que cuadra con HubSpot). Si el panel y el mensaje no coinciden,
el que cambió es uno de los dos: nunca contar SQLs con otra query acá.

  - Weekly Recap  = semana anterior, lunes a domingo, con empresa — Scheduled By.
  - Monthly Recap = del día 1 del mes del domingo anterior hasta ese domingo:
                    Top Bookers con medallas y NextGen vs VinttiKids (`panels.TEAMS`).

El cron pega cada hora los lunes; `weekly_sales_scores_log` (una fila por semana
resumida) garantiza un solo mensaje. `force` manda una prueba cualquier día sin tocar
el log.

Canal hardcodeado, mismo criterio que stale_opps_slack.py.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from daily_digest.people import slack_id
from db import get_connection
from prospecting import panels
from utils import slack
from utils.hubspot_waiting_alert import today_ar

# Canal definitivo elegido por la owner (2026-11-27); antes, el de prueba C0C0UQ7SYBW.
# El bot tiene que estar invitado al canal.
SLACK_CHANNEL_ID = "C09C4C6RHNK"
SEND_FROM_HOUR_AR = 7
MEDALS = (":first_place_medal:", ":second_place_medal:", ":third_place_medal:")
TEAM_LABELS = (("nextgen", "NextGen"), ("vinttikids", "VinttiKids"))
MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

log = logging.getLogger(__name__)

_schema_ready = False


def _ensure_schema(cur) -> None:
    global _schema_ready
    if _schema_ready:
        return
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_sales_scores_log (
            week_start DATE PRIMARY KEY,
            sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            n_week INTEGER NOT NULL DEFAULT 0,
            n_month INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    _schema_ready = True


def periods(hoy: date) -> Dict[str, date]:
    """Semana anterior (lun-dom) y mes en curso hasta ese domingo."""
    week_to = hoy - timedelta(days=hoy.weekday() + 1)   # domingo anterior
    week_from = week_to - timedelta(days=6)              # su lunes
    return {"week_from": week_from, "week_to": week_to,
            "month_from": week_to.replace(day=1), "month_to": week_to}


def _who(row: Dict[str, Any]) -> str:
    email = (row.get("scheduled_by") or "").strip().lower()
    name = row.get("scheduled_by_name") or email
    return slack.mention(slack_id(email), name)


def _ranking(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Personas por cantidad desc; empates comparten medalla (como la captura)."""
    by: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = (r.get("scheduled_by") or "").lower()
        p = by.setdefault(k, {"row": r, "name": r.get("scheduled_by_name") or k, "n": 0})
        p["n"] += 1
    ranked = sorted(by.values(), key=lambda p: (-p["n"], p["name"].lower()))
    place, prev = 0, None
    for p in ranked:
        if p["n"] != prev:
            place += 1
            prev = p["n"]
        p["place"] = place
    return ranked


def _team_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    return {key: sum(1 for r in rows if (r.get("scheduled_by") or "").lower() in panels.TEAMS[key])
            for key, _ in TEAM_LABELS}


# Separa las partes del mensaje: cada una va en su propio section block (Slack les
# da aire entre bloques) y adentro lleva una línea en blanco bajo el título.
PART_SEP = "\n\u2063PART\u2063\n"


def build_text(hoy: date, week_rows: List[Dict[str, Any]], month_rows: List[Dict[str, Any]],
               per: Dict[str, date]) -> str:
    iso_week = hoy.isocalendar()[1]  # como el mensaje manual: W46 = lunes 9-nov
    parts = [f":bar_chart: *WEEKLY SALES SCORES — W{iso_week} | {hoy.day} de {MESES[hoy.month - 1]}*"]

    weekly = [f"*Weekly Recap — {len(week_rows)} SQLs*"]
    if week_rows:
        weekly += ["", "*SQLs Booked:*"]
        for i, r in enumerate(week_rows, 1):
            company = r.get("company_name") or r.get("deal_name") or r.get("contact_name") or "Sin empresa"
            weekly.append(f"{i}. {slack.esc(company)} — {_who(r)}")
    parts.append("\n".join(weekly))

    monthly = [f"*Monthly Recap — {len(month_rows)} SQLs*"]
    ranked = _ranking(month_rows)
    if ranked:
        monthly += ["", "*Top Bookers:*"]
        for p in ranked:
            medal = MEDALS[min(p["place"], len(MEDALS)) - 1]
            monthly.append(f"{medal} {_who(p['row'])} — {p['n']} SQLs")
    parts.append("\n".join(monthly))

    teams = _team_counts(month_rows)
    (k1, l1), (k2, l2) = TEAM_LABELS
    parts.append(f":crossed_swords: *{l1}: {teams[k1]} SQLs*  VS  *{l2}: {teams[k2]} SQLs*")
    parts.append("*Let's keep the momentum going!* :rocket:")
    return PART_SEP.join(parts)


def _section(text: str) -> Dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _blocks(text: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    parts = text.split(PART_SEP)
    for i, part in enumerate(parts):
        # Un section admite 3000 caracteres: se parte por líneas.
        chunk: List[str] = []
        for ln in part.split("\n"):
            if sum(len(x) + 1 for x in chunk) + len(ln) > 2800:
                blocks.append(_section("\n".join(chunk)))
                chunk = []
            chunk.append(ln)
        if chunk:
            blocks.append(_section("\n".join(chunk)))
        if i == 0:
            blocks.append({"type": "divider"})
    return blocks


def _release(week_start: date) -> None:
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM weekly_sales_scores_log WHERE week_start = %s", (week_start,))
    finally:
        conn.close()


def run_weekly_sales_scores(dry_run: bool = False, force: bool = False,
                            today: Optional[date] = None) -> Dict[str, Any]:
    hoy = today or today_ar()
    hora_ar = (datetime.now(timezone.utc) - timedelta(hours=3)).hour
    per = periods(hoy)

    conn = get_connection()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            _ensure_schema(cur)
            month_rows = panels.sqls_by_bdr(cur, per["month_from"], per["month_to"])["rows"]
    finally:
        conn.close()
    wf, wt = per["week_from"].isoformat(), per["week_to"].isoformat()
    week_rows = [r for r in month_rows if r.get("date") and wf <= r["date"] <= wt]
    if per["week_from"] < per["month_from"]:
        # Semana partida entre dos meses: la parte del mes anterior no está en month_rows.
        conn = get_connection()
        try:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                week_rows = panels.sqls_by_bdr(cur, per["week_from"], per["week_to"])["rows"]
        finally:
            conn.close()

    text = build_text(hoy, week_rows, month_rows, per)
    result: Dict[str, Any] = {
        "date": hoy.isoformat(), "channel": SLACK_CHANNEL_ID,
        "periods": {k: v.isoformat() for k, v in per.items()},
        "week_sqls": len(week_rows), "month_sqls": len(month_rows),
        "teams": _team_counts(month_rows), "text": text, "posted": False,
    }

    if dry_run:
        result["status"] = "dry_run"
        return result
    if not force:
        if hoy.weekday() != 0:
            result["status"] = "not_monday"
            return result
        if hora_ar < SEND_FROM_HOUR_AR:
            result["status"] = "too_early"
            return result
        # Se reclama la semana ANTES de postear: dos corridas solapadas no duplican.
        conn = get_connection()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO weekly_sales_scores_log (week_start, n_week, n_month)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (week_start) DO NOTHING
                    RETURNING week_start
                    """,
                    (per["week_from"], len(week_rows), len(month_rows)),
                )
                claimed = cur.fetchone() is not None
        finally:
            conn.close()
        if not claimed:
            result["status"] = "already_sent"
            return result

    head = f"Weekly Sales Scores — {len(week_rows)} SQLs esta semana, {len(month_rows)} en el mes"
    sent = slack.post_blocks(_blocks(text), head, channel_override=SLACK_CHANNEL_ID)
    result["slack"] = sent
    if not sent.get("sent"):
        if not force:
            _release(per["week_from"])  # la próxima corrida lo reintenta
        log.error("weekly_sales_scores: Slack no aceptó el mensaje: %s", sent.get("error"))
        result["status"] = "slack_error"
        return result
    result["posted"] = True
    result["status"] = "sent_forced" if force else "sent"
    return result
