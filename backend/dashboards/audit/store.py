"""Persistencia de las corridas y el diff semana a semana.

Lo que hace accionable al reporte no es la lista de hallazgos sino el delta:
que apareci esta semana, que sigue igual y que se resolvio. Eso exige guardar
la corrida anterior, y por eso existe este modulo.
"""
from __future__ import annotations

import hashlib


def fingerprint(finding) -> str:
    raw = "|".join(str(p) for p in finding.fingerprint_parts())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def tables_exist(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.dashboard_audit_runs')")
        return cur.fetchone()[0] is not None


def start_run(conn, trigger_source="cli", html_source=None) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO dashboard_audit_runs (trigger_source, html_source)
               VALUES (%s, %s) RETURNING run_id""",
            (trigger_source, html_source),
        )
        return cur.fetchone()[0]


def finish_run(conn, run_id, *, status, nodes_seen=None, datasets_run=None,
               datasets_failed=None, elapsed_ms=None, findings_total=None,
               error_text=None, html_source=None) -> None:
    """Cierra la corrida.

    html_source se escribe aca y no al abrirla: el endpoint crea la fila antes
    de saber de donde salio el HTML. Es el campo que delata si la auditoria
    corrio contra el dashboard de produccion o contra una copia vieja del
    contenedor, asi que no puede quedar nulo.
    """
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE dashboard_audit_runs
                  SET finished_at = NOW(), status = %s, nodes_seen = %s,
                      datasets_run = %s, datasets_failed = %s, elapsed_ms = %s,
                      findings_total = %s, error_text = %s,
                      html_source = COALESCE(%s, html_source)
                WHERE run_id = %s""",
            (status, nodes_seen, datasets_run, datasets_failed, elapsed_ms,
             findings_total, error_text, html_source, run_id),
        )


def load_waivers(conn) -> list:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT fingerprint, rule, chart_key, dataset_key, panel, reason
                 FROM dashboard_audit_waivers
                WHERE expires_at IS NULL OR expires_at >= CURRENT_DATE"""
        )
        cols = ("fingerprint", "rule", "chart_key", "dataset_key", "panel", "reason")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def match_waiver(finding, fp, waivers):
    """Devuelve el motivo del waiver que tapa este hallazgo, o None.

    Se compara solo contra los campos que el waiver declara, asi un waiver
    puede ser tan puntual como un fingerprint o tan amplio como "esta regla
    para este dataset".
    """
    for w in waivers:
        if w["fingerprint"]:
            if w["fingerprint"] == fp:
                return w["reason"]
            continue
        checks = (
            (w["rule"], finding.rule),
            (w["chart_key"], finding.chart_key),
            (w["dataset_key"], finding.dataset_key),
            (w["panel"], finding.panel),
        )
        declared = [(want, got) for want, got in checks if want]
        if declared and all(want == got for want, got in declared):
            return w["reason"]
    return None


def previous_fingerprints(conn, before_run_id) -> set:
    """Huellas de la ultima corrida terminada antes de esta."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT run_id FROM dashboard_audit_runs
                WHERE status = 'ok' AND run_id < %s
             ORDER BY run_id DESC LIMIT 1""",
            (before_run_id,),
        )
        row = cur.fetchone()
        if not row:
            return set()
        cur.execute(
            "SELECT fingerprint FROM dashboard_audit_findings WHERE run_id = %s",
            (row[0],),
        )
        return {r[0] for r in cur.fetchall()}


def save_findings(conn, run_id, findings, waivers) -> dict:
    """Guarda los hallazgos y devuelve {fingerprint: 'new'|'recurring'}.

    Los waived se guardan igual (marcados) para que el triage los vea: un
    hallazgo silenciado sigue siendo informacion, solo no interrumpe.
    """
    previous = previous_fingerprints(conn, run_id)
    status = {}
    rows = []
    for f in findings:
        fp = fingerprint(f)
        reason = match_waiver(f, fp, waivers)
        status[fp] = "recurring" if fp in previous else "new"
        rows.append((run_id, fp, f.rule, f.severity, f.tab, f.panel, f.where,
                     f.chart_key, f.dataset_key, f.field, f.message, f.observed,
                     f.expected, f.html_line, reason is not None, reason))
    if rows:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO dashboard_audit_findings
                     (run_id, fingerprint, rule, severity, tab, panel, where_txt,
                      chart_key, dataset_key, field, message, observed, expected,
                      html_line, waived, waive_reason)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                rows,
            )
    resolved = previous - set(status)
    return {"status": status, "resolved": resolved}
