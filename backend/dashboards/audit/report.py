"""Arma el mail semanal y el artefacto JSON para el triage posterior.

El mail no lista todo: lista lo que cambio. Un reporte que repite los mismos
80 hallazgos cada lunes se deja de leer a la tercera semana, y ahi el auditor
deja de servir aunque siga funcionando.
"""
from __future__ import annotations

import html as _html
from datetime import date

from utils.transactional_email import email_detail_table, email_shell

# Paleta de marca (ver CLAUDE.md). Nada de rojo/verde fuera de paleta.
SEV_COLOR = {
    "critical": "#ff1fdb",   # magenta
    "high": "#6c38ff",       # violeta
    "medium": "#4ba9ff",     # celeste
    "low": "#8a94a6",
}
SEV_LABEL = {
    "critical": "Critico", "high": "Alto", "medium": "Medio", "low": "Bajo",
}
SEV_ORDER = ("critical", "high", "medium", "low")
MAX_ROWS = 60

_MESES = ("ene", "feb", "mar", "abr", "may", "jun",
          "jul", "ago", "sep", "oct", "nov", "dic")
TAB_LABEL = {
    "sales": "Sales", "ops": "Operations", "am": "Account Management",
    "growth-new": "Management Dashboard", "marketing": "Marketing",
}


def _esc(v) -> str:
    return _html.escape(str(v)) if v not in (None, "") else ""


def _chip(sev) -> str:
    color = SEV_COLOR.get(sev, "#8a94a6")
    return (f'<span style="display:inline-block;padding:2px 9px;border-radius:999px;'
            f'background:{color};color:#fff;font-size:11px;font-weight:700;'
            f'letter-spacing:.02em;">{SEV_LABEL.get(sev, sev)}</span>')


def subject(findings, run_day=None) -> str:
    day = run_day or date.today()
    stamp = f"{day.day}-{_MESES[day.month - 1]}"
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEV_ORDER}
    if not findings:
        return f"Auditoria dashboard · sin hallazgos · {stamp}"
    head = ", ".join(f"{counts[s]} {SEV_LABEL[s].lower()}" for s in SEV_ORDER if counts[s])
    return f"Auditoria dashboard · {head} · {stamp}"


def _findings_table(findings, status) -> str:
    parts = []
    shown = 0
    for sev in SEV_ORDER:
        group = [f for f in findings if f.severity == sev]
        if not group:
            continue
        parts.append(
            f'<h3 style="margin:26px 0 10px;font-size:15px;color:#111927;">'
            f'{_chip(sev)} &nbsp;{len(group)} hallazgo{"s" if len(group) != 1 else ""}</h3>'
        )
        rows = []
        for f in group:
            if shown >= MAX_ROWS:
                break
            shown += 1
            fp_state = status.get(getattr(f, "_fp", ""), "")
            badge = ('<span style="color:#ff1fdb;font-weight:700;">NUEVO</span> '
                     if fp_state == "new" else "")
            tab = TAB_LABEL.get(f.tab or "", f.tab or "")
            rows.append(f"""
        <tr>
          <td style="padding:10px 12px;border-bottom:1px solid #e6eaf0;vertical-align:top;width:34%;">
            <div style="font-weight:600;color:#111927;">{badge}{_esc(f.where or f.chart_key)}</div>
            <div style="font-size:12px;color:#8a94a6;margin-top:2px;">{_esc(tab)}</div>
          </td>
          <td style="padding:10px 12px;border-bottom:1px solid #e6eaf0;vertical-align:top;color:#243B53;">
            <div>{_esc(f.message)}</div>
            <div style="font-size:12px;color:#8a94a6;margin-top:4px;">
              {_esc(f.dataset_key or "")} · docs/dashboard.html:{f.html_line or "?"}
            </div>
          </td>
        </tr>""")
        parts.append(
            '<table style="border-collapse:collapse;width:100%;max-width:680px;'
            'background:#fff;border:1px solid #e6eaf0;border-radius:12px;overflow:hidden;">'
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        if shown >= MAX_ROWS:
            break

    if len(findings) > shown:
        parts.append(
            f'<p style="margin:14px 0 0;font-size:13px;color:#8a94a6;">'
            f"…y {len(findings) - shown} hallazgos mas. El detalle completo esta en "
            f"<code>GET /dashboards/audit/last</code>.</p>"
        )
    return "".join(parts)


def render(run_id, findings, meta, diff) -> tuple[str, str]:
    """Devuelve (asunto, html). `findings` ya viene sin los waived."""
    status = (diff or {}).get("status", {})
    resolved = (diff or {}).get("resolved", set())
    new_count = sum(1 for f in findings if status.get(getattr(f, "_fp", "")) == "new")

    detail = email_detail_table([
        ("Corrida", f"#{run_id}"),
        ("HTML auditado", meta.get("html_source")),
        ("Nodos revisados", meta.get("nodes_seen")),
        ("Datasets ejecutados", f"{meta.get('datasets_run')} "
                                f"({meta.get('datasets_failed', 0)} con error)"),
        ("Duracion", f"{round((meta.get('elapsed_ms') or 0) / 1000)}s"),
        ("Nuevos esta semana", new_count or ""),
        ("Resueltos desde el lunes pasado", len(resolved) or ""),
        ("Silenciados", meta.get("waived_count") or ""),
    ])

    if findings:
        intro = (f"La auditoria semanal del dashboard encontro <strong>{len(findings)}"
                 f"</strong> inconsistencias"
                 + (f", <strong>{new_count}</strong> de ellas nuevas" if new_count else "")
                 + ".")
    else:
        intro = ("La auditoria semanal del dashboard no encontro inconsistencias: "
                 "cada card cuadra con su detalle y no hay metricas rotas.")

    body = email_shell(intro, detail) + _findings_table(findings, status)
    return subject(findings), body


def to_json(run_id, findings, meta, diff) -> dict:
    """Artefacto para el triage: incluye donde mirar sin volver a explorar."""
    status = (diff or {}).get("status", {})
    return {
        "run": {"run_id": run_id, **meta},
        "summary": {
            "by_severity": {s: sum(1 for f in findings if f.severity == s) for s in SEV_ORDER},
            "by_tab": _count_by(findings, "tab"),
            "by_rule": _count_by(findings, "rule"),
            "resolved": sorted((diff or {}).get("resolved", set())),
        },
        "findings": [{
            "fingerprint": getattr(f, "_fp", None),
            "state": status.get(getattr(f, "_fp", ""), "new"),
            "rule": f.rule, "severity": f.severity, "tab": f.tab, "panel": f.panel,
            "where": f.where, "chart_key": f.chart_key, "dataset_key": f.dataset_key,
            "field": f.field, "message": f.message,
            "observed": f.observed, "expected": f.expected,
            # Las dos rutas que hacen que el triage sea de un paso.
            "html_file": "docs/dashboard.html", "html_line": f.html_line,
            "source_file": (f"backend/dashboards/datasets/{f.dataset_key}.py"
                            if f.dataset_key else None),
        } for f in findings],
    }


def _count_by(findings, attr) -> dict:
    out = {}
    for f in findings:
        out[getattr(f, attr) or "?"] = out.get(getattr(f, attr) or "?", 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
