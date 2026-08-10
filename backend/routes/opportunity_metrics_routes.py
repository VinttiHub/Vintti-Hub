"""Métricas de una opportunity — alimenta la pestaña Metrics de opportunity-detail.

Equivalente al overview de Hirex (`/hirex/jobs/<id>/overview`), pero sobre el
schema viejo: `opportunity_candidates` (pipeline), `batch` + `candidates_batches`
(presentaciones al cliente) y `applicants` (formulario público).
"""
import traceback

from flask import Blueprint, jsonify
from psycopg2.extras import RealDictCursor

from db import get_connection

bp = Blueprint('opportunity_metrics', __name__)


# Las 5 columnas del Pipeline, en el mismo orden que opportunity-detail.html.
# La key es el valor crudo que guarda `opportunity_candidates.stage_pipeline`.
#
# Los colores salen de los pasteles que cada columna tiene inline en el HTML del
# Pipeline (#fff7ed, #fef2f2, #edf4ff, #fef3fb, #effaf0): se conserva el tinte
# exacto de cada stage y solo se sube la saturación, porque esos pasteles sobre
# una card blanca no se ven. La luminosidad se calculó por tinte para que los
# cinco queden en 3.2:1 contra blanco (umbral WCAG para objetos gráficos): con
# una lightness uniforme el verde y el naranja quedaban en ~1.8:1.
PIPELINE_STAGES = [
    ('Applicant',              'Applicant',         '#ca7f21'),  # ← #fff7ed
    ('Contactado',             'Contacted',         '#e66868'),  # ← #fef2f2
    ('Primera entrevista',     'First interview',   '#5b90e4'),  # ← #edf4ff
    ('En proceso con Cliente', 'In client process', '#e45bbf'),  # ← #fef3fb
    ('No avanza primera',      'No advance',        '#1ba628'),  # ← #effaf0
]

# Outcomes de batch, en el mismo orden que el dropdown de estados de
# opportunity-detail.html. Se emiten SIEMPRE los nueve, aunque estén en cero: un
# "Client interviewing" ausente y un "Client interviewing: 0" cuentan cosas
# distintas, y con solo los que tienen datos no se distinguían.
#
# `candidates_batches.status` viene con mayúsculas inconsistentes ("Client
# rejected CV" y "Client Rejected CV" conviven) y con valores viejos que ya no
# están en el dropdown, así que cada fila junta todos sus alias en minúsculas.
#
# Colores: el mismo set que PIPELINE_STAGES, agrupado por significado —
# naranja = lo cortamos nosotros, rojo = lo cortó el cliente, azul/magenta = en
# curso, gris = se cayó sin decisión, verde = contratado.
BATCH_OUTCOMES = [
    ('Rejected by sales',           '#ca7f21', {'rejected by sales'}),
    ('Client rejected CV',          '#e66868', {'client rejected cv'}),
    # 'client interviewing/testing' es el valor viejo que juntaba ambos pasos;
    # se cuenta acá porque "interviewing" es el que sigue ofreciendo el dropdown.
    ('Client interviewing',         '#5b90e4', {'client interviewing',
                                                'client interviewing/testing'}),
    ('Candidate testing',           '#e45bbf', {'candidate testing'}),
    ('Rejected after interviewing', '#e66868', {'client rejected after interviewing'}),
    ('Failed the test',             '#ca7f21', {'candidate failed test'}),
    ('Candidate abandoned',         '#9aa2ad', {'candidate abandoned process'}),
    ('Client abandoned',            '#9aa2ad', {'client abandoned process'}),
    ('Hired',                       '#1ba628', {'candidate hired', 'client hired'}),
]

_OUTCOME_BY_ALIAS = {
    alias: label for label, _color, aliases in BATCH_OUTCOMES for alias in aliases
}

HIRED_STATUSES = next(a for label, _c, a in BATCH_OUTCOMES if label == 'Hired')

# Estados que implican que el cliente llegó a entrevistar a la persona.
INTERVIEWED_STATUSES = {
    alias
    for label, _color, aliases in BATCH_OUTCOMES
    if label in {'Client interviewing', 'Candidate testing',
                 'Rejected after interviewing', 'Failed the test', 'Hired'}
    for alias in aliases
}


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, 'isoformat') else value


@bp.route('/opportunities/<int:opportunity_id>/metrics', methods=['GET'])
def get_opportunity_metrics(opportunity_id):
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("""
            SELECT
                o.opportunity_id,
                o.opp_position_name,
                o.opp_stage,
                o.opp_model,
                o.opp_hr_lead,
                o.nda_signature_or_start_date,
                o.interviewing_date,
                o.opp_close_date,
                o.cantidad_entrevistados,
                a.client_name
            FROM opportunity o
            LEFT JOIN account a ON a.account_id = o.account_id
            WHERE o.opportunity_id = %s
            LIMIT 1
        """, (opportunity_id,))
        opp = cur.fetchone()
        if not opp:
            return jsonify({'error': 'Opportunity not found'}), 404

        # --- Pipeline por stage -------------------------------------------
        # Mismo COALESCE que GET /opportunities/<id>/candidates, para que los
        # números del gráfico coincidan con las columnas del tab Pipeline.
        cur.execute("""
            SELECT
                COALESCE(
                    NULLIF(TRIM(oc.stage_pipeline), ''),
                    NULLIF(TRIM(c.stage), ''),
                    'Contactado'
                ) AS stage,
                COUNT(*) AS n
            FROM opportunity_candidates oc
            JOIN candidates c ON c.candidate_id = oc.candidate_id
            WHERE oc.opportunity_id = %s
            GROUP BY 1
        """, (opportunity_id,))
        stage_counts = {r['stage']: r['n'] for r in cur.fetchall()}
        by_stage = [
            {'key': key, 'label': label, 'color': color, 'count': stage_counts.get(key, 0)}
            for key, label, color in PIPELINE_STAGES
        ]
        # Cualquier stage viejo que no esté en las 5 columnas no se pierde.
        known = {key for key, _, _ in PIPELINE_STAGES}
        for stage, n in stage_counts.items():
            if stage not in known:
                by_stage.append({'key': stage, 'label': stage, 'color': '#9aa2ad', 'count': n})
        pipeline_total = sum(stage_counts.values())

        # --- Fuentes -------------------------------------------------------
        cur.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(c.candidate_source), ''), 'Unknown') AS source,
                COUNT(*) AS n
            FROM opportunity_candidates oc
            JOIN candidates c ON c.candidate_id = oc.candidate_id
            WHERE oc.opportunity_id = %s
            GROUP BY 1
            ORDER BY 2 DESC, 1
        """, (opportunity_id,))
        by_source = [{'label': r['source'], 'count': r['n']} for r in cur.fetchall()]

        # --- Batches (presentaciones al cliente) ---------------------------
        # candidates_batches.opportunity_id está 100% NULL, así que el join
        # tiene que pasar sí o sí por batch.
        cur.execute("""
            SELECT
                b.batch_id,
                b.batch_number,
                b.presentation_date,
                COUNT(cb.candidate_id) AS n
            FROM batch b
            LEFT JOIN candidates_batches cb ON cb.batch_id = b.batch_id
            WHERE b.opportunity_id = %s
            GROUP BY b.batch_id, b.batch_number, b.presentation_date
            ORDER BY b.presentation_date NULLS LAST, b.batch_number
        """, (opportunity_id,))
        batches = [{
            'batch_number': r['batch_number'],
            'presentation_date': _iso(r['presentation_date']),
            'count': r['n'],
        } for r in cur.fetchall()]

        cur.execute("""
            SELECT COUNT(DISTINCT cb.candidate_id) AS n
            FROM candidates_batches cb
            JOIN batch b ON b.batch_id = cb.batch_id
            WHERE b.opportunity_id = %s
        """, (opportunity_id,))
        presented = (cur.fetchone() or {}).get('n', 0)

        # --- Feedback del cliente (status de batch) ------------------------
        cur.execute("""
            SELECT LOWER(TRIM(cb.status)) AS status, COUNT(*) AS n
            FROM candidates_batches cb
            JOIN batch b ON b.batch_id = cb.batch_id
            WHERE b.opportunity_id = %s
              AND NULLIF(TRIM(cb.status), '') IS NOT NULL
            GROUP BY 1
        """, (opportunity_id,))
        raw_status = cur.fetchall()

        merged = {}
        unknown = {}
        client_interviewed = 0
        hired = 0
        for row in raw_status:
            raw = row['status']
            n = row['n']
            label = _OUTCOME_BY_ALIAS.get(raw)
            if label:
                merged[label] = merged.get(label, 0) + n
            else:
                # Un status que no está en el dropdown ni entre los alias viejos:
                # se muestra igual, en gris y al final, en vez de desaparecer.
                pretty = (raw or '').capitalize()
                unknown[pretty] = unknown.get(pretty, 0) + n
            if raw in INTERVIEWED_STATUSES:
                client_interviewed += n
            if raw in HIRED_STATUSES:
                hired += n

        by_batch_status = [
            {'label': label, 'color': color, 'count': merged.get(label, 0)}
            for label, color, _aliases in BATCH_OUTCOMES
        ]
        by_batch_status += [
            {'label': label, 'color': '#9aa2ad', 'count': n}
            for label, n in sorted(unknown.items(), key=lambda x: -x[1])
        ]

        # --- Applicants (formulario público) -------------------------------
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(match_score) AS scored,
                ROUND(AVG(match_score)::numeric, 1) AS avg_score,
                MAX(created_at) AS last_at
            FROM applicants
            WHERE opportunity_id = %s
        """, (opportunity_id,))
        app_row = cur.fetchone() or {}

        cur.execute("""
            SELECT created_at::date AS d, COUNT(*) AS n
            FROM applicants
            WHERE opportunity_id = %s
              AND created_at >= CURRENT_DATE - INTERVAL '13 days'
            GROUP BY 1
            ORDER BY 1
        """, (opportunity_id,))
        applicants_daily = [{'date': _iso(r['d']), 'count': r['n']} for r in cur.fetchall()]

        # --- Duración del proceso ------------------------------------------
        # since_sourcing está vacío en la práctica (1 fila en toda la tabla), así
        # que el ancla es la Start Date del Overview y, si falta, la primera
        # presentación o la fecha de interviewing.
        first_presentation = next(
            (b['presentation_date'] for b in batches if b['presentation_date']), None
        )
        started = (
            _iso(opp['nda_signature_or_start_date'])
            or first_presentation
            or _iso(opp['interviewing_date'])
        )
        closed = _iso(opp['opp_close_date'])

        cur.close()
        return jsonify({
            'opportunity': {
                'opportunity_id': opp['opportunity_id'],
                'position_name': opp['opp_position_name'],
                'stage': opp['opp_stage'],
                'model': opp['opp_model'],
                'hr_lead': opp['opp_hr_lead'],
                'client_name': opp['client_name'],
                'started_at': started,
                'closed_at': closed,
            },
            'totals': {
                'pipeline': pipeline_total,
                'presented': presented,
                'batches': len(batches),
                'client_interviewed': client_interviewed,
                'hired': hired,
                'interviewed_reported': opp['cantidad_entrevistados'],
            },
            'applicants': {
                'total': app_row.get('total') or 0,
                'scored': app_row.get('scored') or 0,
                # match_score va de 1 a 10 (no 0-100 como el score de Hirex)
                'avg_score': float(app_row['avg_score']) if app_row.get('avg_score') is not None else None,
                'daily': applicants_daily,
            },
            'by_stage': by_stage,
            'by_source': by_source,
            'by_batch_status': by_batch_status,
            'batches': batches,
        })

    except Exception as e:
        print("❌ Error en GET /opportunities/<id>/metrics:")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            conn.close()
