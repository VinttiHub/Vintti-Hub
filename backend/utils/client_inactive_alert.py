"""Mail de aviso cuando una cuenta cae a 'Inactive Client'.

"Inactive Client" es EXACTAMENTE lo que pinta el CRM (utils/account_status.py), no
un conteo propio de hires. Eso importa porque hay dos reglas que un conteo ingenuo
se saltea:
  - un hire con buyout mantiene la cuenta en 'Active Client';
  - una opp en pipeline (un REEMPLAZO abierto, típicamente) la deja en
    'Lead in Process' — la cuenta todavía no está perdida.

Por eso hay dos disparadores, y los dos hacen falta:
  1. routes/candidates_routes.py — se da de baja al último contractor activo.
     Si hay un reemplazo abierto, acá NO sale mail (queda 'Lead in Process').
  2. routes/accounts_routes.py — ese reemplazo se marca Closed Lost. Recién ahí
     la cuenta queda 'Inactive Client' y sale el mail.

El payload se arma DENTRO de la transacción (build_client_inactive_email) y se
manda DESPUÉS del commit (send_client_inactive_email), para no dejar el request
colgado de un POST HTTP con la transacción abierta.
"""
from __future__ import annotations

import html

from utils.account_status import ACTIVE_CLIENT, INACTIVE_CLIENT
from utils.transactional_email import (
    email_detail_table,
    email_shell,
    post_transactional_email,
)

CLIENT_INACTIVE_EMAIL_RECIPIENTS = [
    'mia@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com',
    'jazmin@vintti.com',
    'pgonzales@vintti.com',
]

# Texto del disparador, para que el mail diga por qué se cayó la cuenta.
TRIGGER_LAST_EMPLOYEE_OUT = 'Last active employee ended'
TRIGGER_OPPORTUNITY_LOST = 'Last open opportunity marked Closed Lost'


def build_client_inactive_email(cur, account_id, trigger):
    """Arma {recipients, subject, body} o None si falta la cuenta.

    Llamar DENTRO de la transacción; mandar con send_client_inactive_email()
    después del commit.
    """
    if not account_id:
        return None

    cur.execute(
        """
        SELECT a.client_name, a.account_manager
        FROM account a
        WHERE a.account_id = %s
        LIMIT 1
        """,
        (account_id,),
    )
    account_row = cur.fetchone()
    if not account_row:
        return None
    client_name = (_value(account_row, 'client_name', 0) or f'Account #{account_id}').strip()

    # Último que salió: la baja más reciente de la cuenta. Se resuelve por cuenta y
    # no por el hire que se acaba de tocar, así el mail dice lo mismo lo dispare la
    # baja del contractor o el Closed Lost del reemplazo.
    cur.execute(
        """
        SELECT
            c.name                AS candidate_name,
            o.opp_position_name   AS position_name,
            o.opp_sales_lead      AS sales_lead,
            h.end_date            AS end_date,
            h.inactive_reason     AS inactive_reason,
            h.inactive_comments   AS inactive_comments
        FROM hire_opportunity h
        JOIN opportunity o ON o.opportunity_id = h.opportunity_id
        LEFT JOIN candidates c ON c.candidate_id = h.candidate_id
        WHERE COALESCE(h.account_id, o.account_id) = %s
          AND h.end_date IS NOT NULL
        ORDER BY h.end_date DESC, h.opportunity_id DESC
        LIMIT 1
        """,
        (account_id,),
    )
    last_out = cur.fetchone() or {}

    # Contexto de las opps: cuántas hay y cuántas se perdieron. Sirve para leer de
    # un vistazo si quedó algún reemplazo dando vueltas.
    cur.execute(
        """
        SELECT
            COUNT(*)                                                        AS total_opps,
            COUNT(*) FILTER (WHERE lower(opp_stage) LIKE '%%lost%%')        AS lost_opps,
            COUNT(*) FILTER (WHERE candidato_contratado IS NOT NULL)        AS hired_opps
        FROM opportunity
        WHERE account_id = %s
        """,
        (account_id,),
    )
    opp_row = cur.fetchone() or {}

    detail_html = email_detail_table([
        ('Client', client_name),
        ('Account manager', _value(account_row, 'account_manager', 1)),
        ('Sales lead', _value(last_out, 'sales_lead', 2)),
        ('Trigger', trigger),
        ('Last employee out', _value(last_out, 'candidate_name', 0)),
        ('Role', _value(last_out, 'position_name', 1)),
        ('End date', _value(last_out, 'end_date', 3)),
        ('Reason', _value(last_out, 'inactive_reason', 4) or 'Not captured'),
        ('Comments', _value(last_out, 'inactive_comments', 5)),
        ('Hires with this client', _value(opp_row, 'hired_opps', 2)),
        ('Opportunities (total / lost)',
         f"{_value(opp_row, 'total_opps', 0) or 0} / {_value(opp_row, 'lost_opps', 1) or 0}"),
        ('Account ID', account_id),
    ])
    intro = (
        f'<strong>{html.escape(client_name)}</strong> just moved to '
        f'<strong>Inactive Client</strong>: no active candidate and no open opportunity left.'
    )
    return {
        'recipients': CLIENT_INACTIVE_EMAIL_RECIPIENTS,
        'subject': f'Client inactive - {client_name}',
        'body': email_shell(intro, detail_html),
    }


def send_client_inactive_email(payload):
    if not payload:
        return None
    return post_transactional_email(
        payload['recipients'],
        payload['subject'],
        payload['body'],
        'Client inactive',
    )


def became_inactive_from_hire_change(status_before, status_after):
    """Transición que avisa desde el PATCH del hire.

    Exige que el estado previo sea ACTIVO, y no simplemente ≠ inactivo, porque
    cargar a mano un hire viejo que ya venía con end_date (backfill) también mueve
    la cuenta a 'Inactive Client' y eso no es un cliente que se acaba de ir.
    """
    return status_after == INACTIVE_CLIENT and status_before == ACTIVE_CLIENT


def became_inactive_from_stage_change(status_before, status_after):
    """Transición que avisa desde el PATCH del stage de la opp.

    Acá alcanza con cualquier entrada a 'Inactive Client': el caso central es
    'Lead in Process' → 'Inactive Client', o sea el reemplazo que se marca Closed
    Lost y deja a la cuenta sin nada abierto. No hay riesgo de backfill porque
    esta ruta sólo cambia el stage de una opp que ya existe.
    """
    return status_after == INACTIVE_CLIENT and status_before != INACTIVE_CLIENT


def _value(row, key, index):
    """Lee una fila venga de RealDictCursor (dict) o de un cursor de tuplas."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[index]
    except (IndexError, TypeError):
        return None
