"""Arma el mail mensual de comisiones AE y el artefacto JSON de la corrida.

El mail lleva las tres tablas renderizadas, no un link: quien liquida las
comisiones las lee desde el celular el dia 1 y necesita los numeros a la vista.

Paleta de marca (ver CLAUDE.md): azul, violeta, lima, celeste y magenta. Nada
de rojo/verde fuera de paleta, ni siquiera para marcar una baja.
"""
from __future__ import annotations

import html as _html
import os
from datetime import date

# Mismo patron que admin_routes.py y reset_password.py: base del front con
# override por env, para poder apuntar el boton a un entorno de prueba.
FRONT_BASE_URL = os.environ.get("FRONT_BASE_URL", "https://vinttihub.vintti.com")


C_BLUE = "#003bff"
C_VIOLET = "#6c38ff"
C_LIME = "#c1ff72"
C_LIME_INK = "#3a6b00"
C_CYAN = "#4ba9ff"
C_MAGENTA = "#ff1fdb"
C_INK = "#111927"
C_MUTED = "#52606d"
C_LINE = "#e6eaf0"

_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre")

# Cada bloque con un primario distinto para que se distingan de un vistazo.
# El tercer valor es la tinta de la cabecera: blanca en los tres por decision de
# la owner (2026-09-08). Queda por debajo de AA en celeste (2.5:1) y magenta
# (3.3:1); si alguna vez hay que subir el contraste sin cambiar el color, la
# tinta oscura de cada tono era celeste #0b2942 (6.0:1) y magenta #4a0040 (4.7:1).
BLOCKS = {
    "staffing": (C_VIOLET, "Staffing", "#ffffff"),
    "recruiting": (C_CYAN, "Recruiting", "#ffffff"),
    "m3": (C_MAGENTA, "M3 - Replacements", "#ffffff"),
}

# (clave en la fila, encabezado, alineacion). El orden es el de la spec, mas dos
# columnas que ella no dibuja y que aca hacen falta: "Candidato" (para poder
# cruzar una baja M3 contra la colocacion original) y "AE" (el reporte cubre a
# los dos AEs juntos, asi que sin la columna no se sabe de quien es cada cierre).
# Estas listas son tambien el orden de las tablas de la pagina y del CSV: si se
# tocan aca, hay que tocarlas en docs/assets/js/ae-commissions.js.
COLS_STAFFING = [
    ("client_name", "Nombre de Cliente", "left"),
    ("opp_position_name", "Nombre de Oportunidad", "left"),
    ("candidates", "Candidato", "left"),
    ("close_date", "Fecha de Cierre", "left"),
    ("setup_fee", "Setup Fee", "right"),
    ("fee", "Fee", "right"),
    ("is_replacement", "Replacement", "center"),
    ("equipment", "Equipment", "center"),
    ("ae", "AE", "left"),
]
COLS_RECRUITING = [
    ("client_name", "Nombre de Cliente", "left"),
    ("opp_position_name", "Nombre de Oportunidad", "left"),
    ("candidates", "Candidato", "left"),
    ("close_date", "Fecha de Cierre", "left"),
    ("recruiting_fee", "Recruiting Fee", "right"),
    ("is_replacement", "Replacement", "center"),
    ("ae", "AE", "left"),
]
COLS_M3 = [
    ("client_name", "Nombre de Cliente", "left"),
    ("opp_position_name", "Nombre de Oportunidad", "left"),
    ("candidate_name", "Candidato", "left"),
    ("opp_model", "Modelo", "left"),
    ("close_date", "Fecha de Cierre", "left"),
    ("end_date", "Fecha de Baja", "left"),
    ("amount", "Fee", "right"),
    ("is_replacement", "Replacement", "center"),
    ("inactive_reason", "Motivo", "left"),
    ("ae", "AE", "left"),
]
MONEY_KEYS = {"setup_fee", "fee", "recruiting_fee", "amount"}


def period_label(period_month: date) -> str:
    return f"{_MESES[period_month.month - 1]} {period_month.year}"


def _esc(v) -> str:
    return _html.escape(str(v)) if v not in (None, "") else ""


def money(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    if not n:
        return "-"
    return "USD " + f"{n:,.0f}".replace(",", ".")


def _ae_short(value) -> str:
    return str(value or "").split("@")[0] or "-"


def _cell(row, key) -> str:
    if key == "ae":
        return _esc(_ae_short(row.get(key)))
    value = row.get(key)
    if key in MONEY_KEYS:
        return money(value)
    return _esc(value) or "-"


def _table(rows, cols, color, ink="#ffffff") -> str:
    head = "".join(
        f'<th style="padding:8px 10px;text-align:{align};font-size:11px;'
        f'letter-spacing:.04em;text-transform:uppercase;color:{ink};'
        f'background:{color};font-weight:700;white-space:nowrap;">{_esc(label)}</th>'
        for _key, label, align in cols
    )
    body = []
    for i, row in enumerate(rows):
        bg = "#ffffff" if i % 2 == 0 else "#f8fafc"
        tds = "".join(
            f'<td style="padding:8px 10px;text-align:{align};border-bottom:1px solid {C_LINE};'
            f'color:{C_INK};font-size:13px;">{_cell(row, key)}</td>'
            for key, _label, align in cols
        )
        body.append(f'<tr style="background:{bg};">{tds}</tr>')
    return (
        '<div style="overflow-x:auto;">'
        '<table style="border-collapse:collapse;width:100%;min-width:560px;'
        'border-radius:10px;overflow:hidden;margin:0 0 6px;">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _totals_line(rows, keys) -> str:
    parts = []
    for key, label in keys:
        total = sum(float(r.get(key) or 0) for r in rows)
        if total:
            parts.append(f"{label}: <strong>{money(total)}</strong>")
    if not parts:
        return ""
    return (f'<p style="margin:2px 0 0;font-size:13px;color:{C_MUTED};">'
            + " &nbsp;·&nbsp; ".join(parts) + "</p>")


def _empty(color, text) -> str:
    return (f'<p style="margin:0;padding:12px 14px;border-radius:10px;'
            f'background:{C_LIME};color:{C_LIME_INK};font-weight:600;font-size:14px;">'
            f"{_esc(text)}</p>")


def _section(key, rows, cols, totals, empty_text) -> str:
    color, title, ink = BLOCKS[key]
    head = (f'<h2 style="margin:26px 0 10px;font-size:16px;color:{color};'
            f'font-weight:700;letter-spacing:.01em;">{title} '
            f'<span style="color:{C_MUTED};font-weight:500;">({len(rows)})</span></h2>')
    if not rows:
        return head + _empty(color, empty_text)
    return head + _table(rows, cols, color, ink) + _totals_line(rows, totals)


def incomplete_rows(staffing, recruiting) -> list[dict]:
    """Cierres del mes que no tienen fee cargado.

    Un fee en cero no es un cierre sin comision: es data que falta. Pasa por dos
    caminos y los dos importan igual — la opp cerro sin hire cargado todavia, o
    el hire existe pero nadie completo el monto. El mail los lista aparte para
    que se corrijan antes de liquidar, en vez de que pasen como cero.
    """
    faltantes = [r for r in staffing if not r.get("hire_count") or not r.get("fee")]
    faltantes += [r for r in recruiting
                  if not r.get("hire_count") or not r.get("recruiting_fee")]
    return faltantes


def _cta(period_month: date) -> str:
    """Boton a la pestana de comisiones, ya abierta en el mes del reporte.

    Va ARRIBA de las tablas: el mail alcanza para liquidar, pero cuando hace
    falta abrir una oportunidad o exportar, el link tiene que estar antes de
    scrollear tres tablas, no despues.
    """
    url = f"{FRONT_BASE_URL}/ae-commissions.html?period={period_month.strftime('%Y-%m')}"
    return f"""
    <div style="margin:0 0 24px;padding:18px 20px;border-radius:16px;
                background:#f4f0ff;border:1px solid #d9ccff;">
      <div style="font-size:15px;font-weight:700;color:{C_INK};margin-bottom:4px;">
        Comisiones AE · {period_label(period_month)}
      </div>
      <div style="color:{C_MUTED};font-size:13px;margin-bottom:14px;">
        Abrilo en el Hub para entrar a cada oportunidad o bajarte el detalle.
      </div>
      <a href="{url}" target="_blank" rel="noopener"
         style="display:inline-block;padding:11px 20px;border-radius:12px;
                background:{C_VIOLET};color:#ffffff;text-decoration:none;
                font-weight:700;font-size:14px;">
        Ver en el Hub &rarr;
      </a>
    </div>
    """.strip()


def _shell(intro_html: str, body_html: str) -> str:
    """Envoltorio del mail.

    No usa `utils.transactional_email.email_shell` a proposito: ese arma una
    tabla label/valor de ancho fijo, y este reporte necesita tres tablas anchas
    con scroll horizontal propio.
    """
    return f"""
    <div style="font-family:'Inter','Segoe UI',Arial,sans-serif;font-size:15px;line-height:1.6;color:{C_INK};">
      <p style="margin:0 0 16px;font-size:16px;">Hi team,</p>
      <p style="margin:0 0 4px;color:{C_MUTED};">{intro_html}</p>
      {body_html}
      <p style="margin:26px 0 0;font-size:14px;color:{C_MUTED};">
        Thanks,<br/><strong>Vintti Hub</strong>
      </p>
    </div>
    """.strip()


def subject(period_month: date, payload: dict) -> str:
    n_st = len(payload.get("staffing") or [])
    n_rc = len(payload.get("recruiting") or [])
    n_m3 = len(payload.get("m3") or [])
    cola = f"{n_st} staffing, {n_rc} recruiting"
    if n_m3:
        cola += f", {n_m3} M3"
    return f"Comisiones AE · {period_label(period_month)} · {cola}"


def render(period_month: date, payload: dict) -> tuple[str, str]:
    """(asunto, html) del mail mensual."""
    staffing = payload.get("staffing") or []
    recruiting = payload.get("recruiting") or []
    m3 = payload.get("m3") or []

    intro = (
        f"Data de <strong>{period_label(period_month)}</strong> para el calculo de "
        "comisiones de Account Executives: las oportunidades de Staffing y Recruiting "
        "cerradas en el mes (Close Win) y las caidas dentro de los primeros 3 meses."
    )

    body = _cta(period_month)
    body += _section(
        "staffing", staffing, COLS_STAFFING,
        [("setup_fee", "Setup fees"), ("fee", "Fee mensual")],
        "Sin cierres de Staffing en el mes.",
    )
    body += _section(
        "recruiting", recruiting, COLS_RECRUITING,
        [("recruiting_fee", "Recruiting fees")],
        "Sin cierres de Recruiting en el mes.",
    )
    body += _section(
        "m3", m3, COLS_M3,
        [("amount", "Fee comprometido")],
        "No M3 churn.",
    )

    faltantes = incomplete_rows(staffing, recruiting)
    if faltantes:
        detalle = ", ".join(
            f"{_esc(r.get('client_name'))} · {_esc(r.get('opp_position_name'))}"
            for r in faltantes[:8]
        )
        body += (
            f'<p style="margin:18px 0 0;padding:12px 14px;border-radius:10px;'
            f'background:#fff;border:1px solid {C_MAGENTA};color:{C_INK};font-size:13px;">'
            f'<strong>{len(faltantes)}</strong> oportunidad(es) cerradas sin fee cargado. '
            "Hay que completarlas antes de liquidar, porque suman cero a la comision: "
            f'{detalle}{" ..." if len(faltantes) > 8 else ""}</p>'
        )

    body += (
        f'<p style="margin:22px 0 0;font-size:12px;color:{C_MUTED};">'
        "Alcance: opps con etapa Close Win y fecha de cierre dentro del mes, de los AEs "
        "del scope Sales, excluyendo cuentas internas. M3 = baja real (no buyout) "
        "ocurrida en el mes dentro de los primeros 3 meses del candidato, asi cada "
        "caida se reporta una sola vez, en su mes. Esta lista NO coincide con el "
        "detalle de la card de churn M3 del dashboard, y no tiene por que: esa card "
        "mide una tasa sobre los que arrancaron en los ultimos 90 dias, y ademas no "
        "filtra por AE.</p>"
    )

    return subject(period_month, payload), _shell(intro, body)


def to_json(period_month: date, payload: dict, meta: dict | None = None) -> dict:
    return {
        "period": period_month.strftime("%Y-%m"),
        "period_label": period_label(period_month),
        "staffing": payload.get("staffing") or [],
        "recruiting": payload.get("recruiting") or [],
        "m3": payload.get("m3") or [],
        "meta": meta or {},
    }
