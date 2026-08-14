"""Helpers compartidos para los mails automáticos del Hub.

Los mails salen por POST al endpoint /send_email del propio backend (SendGrid vive
ahí), no llamando a SendGrid directo, para no duplicar credenciales ni plantilla.
"""
from __future__ import annotations

import html
import logging

import requests

SEND_EMAIL_URL = 'https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email'


def email_detail_table(detail_rows):
    """Tabla label/valor de los mails transaccionales. Saltea valores vacíos."""
    return ''.join(
        f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e6eaf0;font-weight:600;color:#111927;width:180px;">{html.escape(str(label))}</td>
          <td style="padding:10px 12px;border-bottom:1px solid #e6eaf0;color:#243B53;">{html.escape(str(value))}</td>
        </tr>
        """
        for label, value in detail_rows
        if value not in (None, '')
    )


def email_shell(intro_html, detail_html):
    """Cuerpo estándar: saludo + párrafo de contexto + tabla de detalle."""
    return f"""
    <div style="font-family:'Inter','Segoe UI',Arial,sans-serif;font-size:15px;line-height:1.65;color:#243B53;">
      <p style="margin:0 0 18px;font-size:16px;">Hi team,</p>
      <p style="margin:0 0 18px;">{intro_html}</p>
      <table style="border-collapse:collapse;width:100%;max-width:680px;background:#f8fafc;border-radius:14px;overflow:hidden;margin:0 0 20px;">
        <tbody>{detail_html}</tbody>
      </table>
      <p style="margin:0;font-size:14px;color:#52606d;">
        Thanks,<br/>
        <strong>Vintti Hub</strong>
      </p>
    </div>
    """.strip()


def post_transactional_email(recipients, subject, body, log_label):
    response = requests.post(
        SEND_EMAIL_URL,
        json={'to': recipients, 'subject': subject, 'body': body},
        timeout=30,
    )
    if not response.ok:
        logging.error('%s email failed: %s %s', log_label, response.status_code, response.text)
    return {'sent': response.ok, 'status_code': response.status_code}
