"""Recordatorio de referencias al pasar un candidato a "Second Interview".

Cuando un candidato entra a la columna Second Interview del Pipeline
(`opportunity_candidates.stage_pipeline = 'Segunda entrevista'`) sale un mail a
Agostina + la recruiter de la opp (`opportunity.opp_hr_lead`) para que pidan y
carguen las referencias. Se repite cada 24 h hasta que la recruiter marca
"References filled" en la Overview del candidato (`candidates.references_filled`).

`references_filled` NO es `check_hr_lead`: ese check ("All set: resignation letter
& references") corta el recordatorio de Signed, que pide además la carta de
renuncia. Reusarlo apagaría de antemano ese otro recordatorio (decisión de la
owner, 2026-09-29).

Una fila por (opportunity_id, candidate_id): el mismo candidato puede estar en
segunda entrevista en dos vacantes, y cada vacante tiene su recruiter. El check
es por candidato, así que marcarlo corta las dos.

Destinatarios hardcodeados, igual que el auditor: sin env var de por medio.
"""
from __future__ import annotations

import html
import logging
from typing import Any, Dict, List, Optional

from psycopg2.extras import RealDictCursor

from db import get_connection
from utils.hubspot_waiting_alert import alerta_en_pausa
from utils.transactional_email import email_detail_table, email_shell, post_transactional_email

SECOND_INTERVIEW_STAGE = "Segunda entrevista"
AGOSTINA_EMAIL = "agostina@vintti.com"

# Modo prueba: con un email acá, TODOS los mails del recordatorio van sólo a esa
# dirección, con [TEST] en el asunto y un aviso de a quién habrían ido. None =
# producción (Agostina + opp_hr_lead). Salió de prueba el 2026-09-29 a pedido de
# la owner. Hardcodeado a propósito, sin env var, por el mismo criterio que
# RECIPIENTS del auditor.
TEST_ONLY_RECIPIENT: Optional[str] = None
HUB_BASE = "https://vinttihub.vintti.com"

_schema_ready = False


def ensure_second_interview_refs_schema(cur) -> None:
    """Crea la columna del check y la tabla del recordatorio (una vez por proceso)."""
    global _schema_ready
    if _schema_ready:
        return
    # Se mira el catálogo antes: ALTER TABLE toma ACCESS EXCLUSIVE sobre `candidates`
    # aunque la columna ya exista, y esa tabla está caliente.
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'candidates' AND column_name = 'references_filled'
        """
    )
    if not cur.fetchone():
        cur.execute(
            "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS references_filled BOOLEAN NOT NULL DEFAULT FALSE"
        )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS second_interview_refs_reminders (
            reminder_id BIGSERIAL PRIMARY KEY,
            opportunity_id BIGINT NOT NULL,
            candidate_id BIGINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            first_sent_at TIMESTAMPTZ,
            last_sent_at TIMESTAMPTZ,
            stopped_at TIMESTAMPTZ,
            stop_reason TEXT,
            UNIQUE (opportunity_id, candidate_id)
        )
        """
    )
    _schema_ready = True


def ensure_second_interview_refs_schema_standalone() -> None:
    """Para rutas que abren la conexión después (GET/PATCH de candidates)."""
    if _schema_ready:
        return
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            ensure_second_interview_refs_schema(cur)
    finally:
        conn.close()


def _fetch_context(cur, opportunity_id: int, candidate_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(
        """
        SELECT oc.stage_pipeline,
               o.opp_position_name,
               o.opp_hr_lead,
               a.client_name,
               c.name AS candidate_name,
               COALESCE(c.references_filled, FALSE) AS references_filled
          FROM opportunity o
          JOIN candidates c ON c.candidate_id = %s
          LEFT JOIN opportunity_candidates oc
                 ON oc.opportunity_id = o.opportunity_id AND oc.candidate_id = c.candidate_id
          LEFT JOIN account a ON a.account_id = o.account_id
         WHERE o.opportunity_id = %s
         LIMIT 1
        """,
        (candidate_id, opportunity_id),
    )
    return cur.fetchone()


def _stop(cur, opportunity_id: int, candidate_id: int, reason: str) -> None:
    cur.execute(
        """
        UPDATE second_interview_refs_reminders
           SET stopped_at = COALESCE(stopped_at, now()),
               stop_reason = COALESCE(stop_reason, %s)
         WHERE opportunity_id = %s AND candidate_id = %s
        """,
        (reason, opportunity_id, candidate_id),
    )


def _recipients(hr_lead: Optional[str]) -> List[str]:
    out = [AGOSTINA_EMAIL]
    hr = (hr_lead or "").strip().lower()
    if hr and hr not in out:
        out.append(hr)
    return out


def _email(ctx: Dict[str, Any], candidate_id: int, is_first: bool):
    candidate = ctx.get("candidate_name") or "the candidate"
    client = ctx.get("client_name") or "Client"
    role = ctx.get("opp_position_name") or "the role"
    link = f"{HUB_BASE}/candidate-details.html?id={candidate_id}"

    prefix = "" if is_first else "Reminder: "
    subject = f"{prefix}References needed for {candidate} — {client} ({role})"
    if len(subject) > 120:
        subject = subject[:117] + "..."

    intro = (
        f"<strong>{html.escape(str(candidate))}</strong> moved to <strong>Second Interview</strong> "
        f"for <strong>{html.escape(str(client))} — {html.escape(str(role))}</strong>. "
        "Please request and fill in the candidate's <strong>references</strong>.<br/><br/>"
        "Once they're in the hub, tick <strong>References filled</strong> in the candidate's "
        f'Overview (<a href="{link}">open the candidate</a>). '
        "Until then this reminder repeats every 24 hours (Monday to Friday)."
    )
    detail = email_detail_table([
        ("Candidate", candidate),
        ("Client", client),
        ("Position", role),
        ("Recruiter", ctx.get("opp_hr_lead") or "—"),
    ])
    return subject, email_shell(intro, detail)


def send_second_interview_refs_email(cur, opportunity_id: int, candidate_id: int) -> Dict[str, Any]:
    """Manda el mail si corresponde. No mira las 24 h: eso lo decide quien llama.

    `cur` tiene que ser un RealDictCursor.
    """
    ensure_second_interview_refs_schema(cur)
    base = {"opportunity_id": opportunity_id, "candidate_id": candidate_id}

    cur.execute(
        """
        INSERT INTO second_interview_refs_reminders (opportunity_id, candidate_id)
        VALUES (%s, %s)
        ON CONFLICT (opportunity_id, candidate_id) DO NOTHING
        """,
        (opportunity_id, candidate_id),
    )

    ctx = _fetch_context(cur, opportunity_id, candidate_id)
    if not ctx:
        _stop(cur, opportunity_id, candidate_id, "not_found")
        return {**base, "sent": False, "reason": "not_found"}

    if ctx.get("references_filled"):
        _stop(cur, opportunity_id, candidate_id, "references_filled")
        return {**base, "sent": False, "reason": "references_filled"}

    if (ctx.get("stage_pipeline") or "").strip() != SECOND_INTERVIEW_STAGE:
        _stop(cur, opportunity_id, candidate_id, "left_stage")
        return {**base, "sent": False, "reason": "left_stage"}

    cur.execute(
        "SELECT first_sent_at FROM second_interview_refs_reminders WHERE opportunity_id = %s AND candidate_id = %s",
        (opportunity_id, candidate_id),
    )
    first_sent = (cur.fetchone() or {}).get("first_sent_at")

    intended = _recipients(ctx.get("opp_hr_lead"))
    subject, body = _email(ctx, candidate_id, is_first=first_sent is None)
    to = intended
    if TEST_ONLY_RECIPIENT:
        to = [TEST_ONLY_RECIPIENT]
        subject = f"[TEST] {subject}"
        body = (
            '<p style="font-family:Arial,sans-serif;font-size:13px;color:#b45309;'
            'background:#fffbeb;padding:8px 12px;border-radius:8px;">'
            f"Test mode — in production this would go to: {html.escape(', '.join(intended))}</p>"
        ) + body
    result = post_transactional_email(to, subject, body, "Second interview references")
    if not result.get("sent"):
        # last_sent_at queda como estaba: el runner lo reintenta en la próxima corrida.
        return {**base, "sent": False, "reason": "send_failed", "to": to}

    cur.execute(
        """
        UPDATE second_interview_refs_reminders
           SET first_sent_at = COALESCE(first_sent_at, now()),
               last_sent_at = now()
         WHERE opportunity_id = %s AND candidate_id = %s
        """,
        (opportunity_id, candidate_id),
    )
    return {**base, "sent": True, "to": to}


def start_second_interview_refs_reminder(opportunity_id: int, candidate_id: int) -> Dict[str, Any]:
    """Se llama al entrar a la columna. Nunca levanta: el stage ya se movió.

    Si el candidato vuelve a entrar después de haber salido, la fila se reabre.
    Manda el primer mail al instante aunque sea fin de semana: lo disparó una
    persona, no el cron.
    """
    conn = None
    try:
        conn = get_connection()
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_second_interview_refs_schema(cur)
            cur.execute(
                """
                INSERT INTO second_interview_refs_reminders (opportunity_id, candidate_id)
                VALUES (%s, %s)
                ON CONFLICT (opportunity_id, candidate_id) DO UPDATE
                   SET stopped_at = NULL, stop_reason = NULL
                """,
                (opportunity_id, candidate_id),
            )
            return send_second_interview_refs_email(cur, opportunity_id, candidate_id)
    except Exception:
        logging.exception("second interview refs: start failed opp=%s cand=%s", opportunity_id, candidate_id)
        return {"sent": False, "reason": "error"}
    finally:
        if conn is not None:
            conn.close()


def run_due_second_interview_refs_reminders(dry_run: bool = False) -> Dict[str, Any]:
    """Los que no se cortaron y ya pasaron 24 h (o nunca salieron: primer envío fallido)."""
    if alerta_en_pausa() and not dry_run:
        return {"skipped": True, "reason": "weekend", "results": []}

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            ensure_second_interview_refs_schema(cur)
            cur.execute(
                """
                SELECT opportunity_id, candidate_id
                  FROM second_interview_refs_reminders
                 WHERE stopped_at IS NULL
                   AND (last_sent_at IS NULL OR now() - last_sent_at >= interval '24 hours')
                 ORDER BY last_sent_at NULLS FIRST
                """
            )
            due = [dict(r) for r in (cur.fetchall() or [])]
            conn.commit()
            if dry_run:
                return {"dry_run": True, "due": due}
            results = []
            for r in due:
                # Commit por fila: un error en una no puede deshacer el last_sent_at
                # de las que ya salieron (se volverían a mandar en una hora).
                try:
                    results.append(send_second_interview_refs_email(
                        cur, int(r["opportunity_id"]), int(r["candidate_id"])))
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    logging.exception("second interview refs: due failed %s", r)
                    results.append({**r, "sent": False, "reason": f"error: {exc}"})
            return {"results": results}
    finally:
        conn.close()
