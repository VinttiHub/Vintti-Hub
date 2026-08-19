/* CV Review — la cola del sales lead.
 *
 * Aprobar/rechazar los CVs que armaron las recruiters, más el resumen por recruiter del
 * período. El gate de verdad es del backend: POST /cv_reviews/<id>/decision devuelve 403
 * a quien no sea sales lead. El chequeo de esta página es sólo para que nadie más
 * tropiece con una pantalla que no le sirve.
 *
 * Usa el design system de Hirex (hirex.css) — las clases hx-* vienen de ahí.
 */
(function () {
  'use strict';

  const API = (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  // Sales leads + la supervisión (pgonzales y agostina, que ven TODOS los reviews).
  // Misma forma que las allow-lists de sidebar.js. Se mantiene en sincronía a mano con
  // OVERSIGHT_EMAILS + user_roles.role_type='sales_lead' del backend, que es quien decide
  // de verdad (POST /cv_reviews/<id>/decision devuelve 403).
  // La supervisión ve TODO por defecto; un sales lead entra viendo sólo sus oportunidades.
  // Espeja OVERSIGHT_EMAILS del backend.
  const OVERSIGHT = new Set([
    'pgonzales@vintti.com',
    'agostina@vintti.com',
  ]);

  const ALLOWED = new Set([
    ...OVERSIGHT,
    'agustin@vintti.com',
    'bahia@vintti.com',
    'lara@vintti.com',
    'mariano@vintti.com',
    'mia@vintti.com',
  ]);

  const me = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase().trim();

  const $ = (id) => document.getElementById(id);
  const headers = () => ({ 'Content-Type': 'application/json', 'X-User-Email': me });
  const show = (el, on) => { if (el) el.hidden = !on; };

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const fmtDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
  };

  function daysWaiting(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  }

  // Clase del semáforo para un score 0-100.
  const qCls = (s) => (s === null || s === undefined) ? 'cvr-q-none'
    : s >= 75 ? 'cvr-q-good' : s >= 50 ? 'cvr-q-mid' : 'cvr-q-low';

  // Con n chico el porcentaje engaña: 1 de 20 es 5 por ciento, y "5%" solo parece una
  // tendencia. Siempre se muestra el conteo al lado.
  function fmtRate(count, total, pct) {
    if (!total) return '—';
    const p = (pct === null || pct === undefined) ? Math.round(1000 * count / total) / 10 : pct;
    return `${count}/${total} · ${p}%`;
  }

  let reasonLabels = {};
  let currentReview = null;
  let queueRows = [];

  // Deep-link desde los mails. Los CTA ya se mandaban con estos parámetros pero nadie los
  // leía, así que el botón "Open the CV review" del mail no hacía nada: caía en la cola sin
  // filtrar y sin abrir nada.
  const DEEP = new URLSearchParams(location.search);
  const deepReviewId = Number(DEEP.get('review_id')) || null;
  const deepOppId = Number(DEEP.get('opportunity_id')) || null;

  /* ---------------------------------------------------------------- métricas */

  function renderMetrics(data) {
    const box = $('cvrMetrics');
    const rows = data.rows || [];
    const totals = data.totals || {};
    const meta = data.meta || {};

    $('cvrMetricsWindow').textContent =
      (meta.desde ? `${meta.desde} → ${meta.hasta}` : '')
      + (meta.sales_lead ? '  ·  your opportunities' : '')
      + (meta.ai_version ? `  ·  rubric v${meta.ai_version}` : '');

    if (!rows.length) {
      box.innerHTML = '';
      show($('cvrMetricsEmpty'), true);
      return;
    }
    show($('cvrMetricsEmpty'), false);

    const card = (r, isTotal) => {
      const q = r.quality_avg;
      const reasons = (r.reasons || []).map(x =>
        `<li><span>${esc(x.reason_label)}</span>
             <b>${fmtRate(x.profiles, r.profiles_decided, x.pct)}</b></li>`).join('');
      const foot = [];
      if (r.profiles_pending) {
        foot.push(`${r.profiles_pending} still waiting on a decision — the rates only count what you decided.`);
      }
      if (r.stale_version_profiles) {
        foot.push(`${r.stale_version_profiles} excluded from CV quality: scored by an older rubric version.`);
      }
      if (r.unscored_profiles) {
        foot.push(`${r.unscored_profiles} have no AI score (no job description, or scoring failed).`);
      }
      return `
      <article class="cvr-mcard ${isTotal ? 'cvr-mcard--total' : ''}">
        <div class="cvr-mcard-head">
          <h3>${esc(isTotal ? 'All recruiters' : (r.recruiter_label || r.recruiter_email))}</h3>
          <span class="cvr-mcard-sent"><b>${r.profiles_sent}</b> sent</span>
        </div>
        <div class="cvr-stats">
          <div class="cvr-stat">
            <span class="cvr-stat-v ${qCls(q)}">${q === null || q === undefined ? '—' : q}</span>
            <span class="cvr-stat-l">CV quality${r.quality_n ? ` n=${r.quality_n}` : ''}</span>
          </div>
          <div class="cvr-stat">
            <span class="cvr-stat-v">${r.approved_first_try_pct === null ? '—' : r.approved_first_try_pct + '%'}</span>
            <span class="cvr-stat-l">Approved 1st</span>
          </div>
          <div class="cvr-stat">
            <span class="cvr-stat-v">${r.rejected_first_try_pct === null ? '—' : r.rejected_first_try_pct + '%'}</span>
            <span class="cvr-stat-l">Rejected 1st</span>
          </div>
        </div>
        ${reasons ? `<ul class="cvr-reasons-list">${reasons}</ul>` : ''}
        ${foot.length ? `<p class="cvr-mfoot">${foot.map(esc).join(' ')}</p>` : ''}
      </article>`;
    };

    const totalRow = {
      ...totals,
      recruiter_label: 'All recruiters',
      reasons: aggregateReasons(data.by_reason || [], totals.profiles_decided),
    };
    box.innerHTML = card(totalRow, true) + rows.map(r => card(r, false)).join('');
  }

  function aggregateReasons(byReason, decided) {
    const acc = {};
    byReason.forEach(r => { acc[r.reason_code] = (acc[r.reason_code] || 0) + r.profiles; });
    return Object.entries(acc)
      .sort((a, b) => b[1] - a[1])
      .map(([code, profiles]) => ({
        reason_code: code,
        reason_label: reasonLabels[code] || code,
        profiles,
        pct: decided ? Math.round(1000 * profiles / decided) / 10 : null,
      }));
  }

  /* ------------------------------------------------------------------- cola */

  const STATUS = {
    pending:   ['Waiting',   'cvr-st-pending'],
    approved:  ['Approved',  'cvr-st-approved'],
    rejected:  ['Rejected',  'cvr-st-rejected'],
    cancelled: ['Cancelled', 'cvr-st-cancelled'],
  };

  function renderQueue() {
    const term = ($('cvrSearch').value || '').toLowerCase().trim();
    let list = !term ? queueRows : queueRows.filter(r =>
      [r.candidate_name, r.opp_position_name, r.client_name, r.recruiter_email]
        .some(v => String(v || '').toLowerCase().includes(term)));
    // El CTA de un batch apunta a una oportunidad: son N reviews, no uno.
    if (deepOppId) list = list.filter(r => Number(r.opportunity_id) === deepOppId);

    const body = $('cvrQueue');
    $('cvrCount').innerHTML = `<b>${list.length}</b> of ${queueRows.length}`;

    show($('cvrQueueLoading'), false);
    if (!list.length) {
      body.innerHTML = '';
      show($('cvrQueueWrap'), false);
      show($('cvrQueueEmpty'), true);
      return;
    }
    show($('cvrQueueEmpty'), false);
    show($('cvrQueueWrap'), true);

    body.innerHTML = list.map(r => {
      const [label, cls] = STATUS[r.status] || [r.status, ''];
      const waited = r.status === 'pending' ? daysWaiting(r.requested_at) : null;
      const score = r.ai_pending
        ? '<span class="cvr-score-none">scoring…</span>'
        : (r.ai_score === null || r.ai_score === undefined
            ? '<span class="cvr-score-none">—</span>'
            : `<span class="cvr-score ${qCls(r.ai_score)}">${r.ai_score}</span>`);
      const age = waited !== null
        ? `<span class="cvr-age${waited >= 3 ? ' cvr-age--old' : ''}">${waited === 0 ? 'today' : waited + 'd'}</span>`
        : `<span class="cvr-age">${fmtDate(r.reviewed_at || r.requested_at)}</span>`;
      return `
      <tr data-review-id="${r.review_id}" tabindex="0">
        <td><div class="cvr-cand">${esc(r.candidate_name || 'Candidate')}</div></td>
        <td class="hx-cell-muted">${esc(r.opp_position_name || '—')}
            <span class="cvr-oppid">#${r.opportunity_id}</span></td>
        <td class="hx-cell-muted">${esc(r.client_name || '—')}</td>
        <td class="hx-cell-muted">${esc(r.recruiter_email || '—')}</td>
        <td class="cvr-col-round"><span class="cvr-round-n">${r.round}</span></td>
        <td class="cvr-col-score">${score}</td>
        <td><span class="hx-status ${cls}">${label}</span></td>
        <td>${age}</td>
      </tr>`;
    }).join('');

    body.querySelectorAll('tr').forEach(el => {
      const open = () => openDrawer(Number(el.dataset.reviewId));
      el.addEventListener('click', open);
      el.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
  }

  /* ---------------------------------------------------------------- el panel */


  function aiPanelHtml(review) {
    const a = review.ai_analysis;
    if (!a) {
      if (review.ai_error === 'no_jd') {
        return `<p class="cvr-ai-none">No score: opportunity #${review.opportunity_id} has no job
          description, so scoring the CV against it would be meaningless. Add the JD, then re-run.</p>`;
      }
      if (review.ai_error === 'budget') {
        return '<p class="cvr-ai-none">No score: the OpenAI budget for this month is exhausted.</p>';
      }
      if (review.ai_error) return '<p class="cvr-ai-none">The AI score could not be computed. Try re-running.</p>';
      return '<p class="cvr-ai-none">Scoring…</p>';
    }

    const score = a._composite_score;

    // El desglose se dibuja desde el _rubric guardado con el análisis, no desde la
    // rúbrica actual: así una ronda vieja sigue mostrando con qué pesos se puntuó.
    const byKey = {};
    (a.criteria || []).forEach(c => { byKey[c.key] = c; });
    const bars = (a._rubric || []).map(rb => {
      const c = byKey[rb.key] || {};
      const na = c.not_applicable || c.score === null || c.score === undefined;
      return `
      <div>
        <div class="cvr-crit-head">
          <span>${esc(rb.label)}${rb.computed ? ' <i class="cvr-crit-calc" title="Computed from the CV, not by the model">calc</i>' : ''}</span>
          <b>${na ? 'n/a' : c.score}</b>
          <span class="cvr-crit-w">${rb.weight}</span>
        </div>
        <div class="cvr-crit-bar"><span style="width:${na ? 0 : Math.max(0, Math.min(100, c.score))}%"></span></div>
        ${c.verdict ? `<p class="cvr-crit-note">${esc(c.verdict)}</p>` : ''}
        ${c.evidence ? `<p class="cvr-crit-ev">“${esc(c.evidence)}”</p>` : ''}
      </div>`;
    }).join('');

    const claims = (list, kind, title) => list.length ? `
      <div class="cvr-find cvr-find--${kind}">
        <h5>${title}</h5>
        <ul>${list.map(c => `<li><q>${esc(c.cv_quote)}</q> ${esc(c.why || '')}</li>`).join('')}</ul>
      </div>` : '';

    const hard = (a.unsupported_claims || []).filter(c => c.severity === 'hard');
    const soft = (a.unsupported_claims || []).filter(c => c.severity !== 'hard');

    // Eco de JD: advertencia, no acusación. No toca el score — alinear el CV con la JD
    // está bien; lo que está mal es que el cliente lea su propio aviso de vuelta.
    const echo = a.jd_echo || [];
    const echoHtml = echo.length ? `
      <div class="cvr-find cvr-find--echo">
        <h5>Wording copied from the job description (${echo.length})</h5>
        <p class="cvr-echo-lead">Aligning with the JD is good — reusing its sentences is not.
          The client ends up reading their own posting back as this candidate's experience.</p>
        <ul>${echo.map(e => `<li>
            <q>${esc(e.cv_quote)}</q>
            ${e.jd_quote ? `<div class="cvr-echo-jd">JD: “${esc(e.jd_quote)}”</div>` : ''}
            ${e.why ? esc(e.why) : ''}
          </li>`).join('')}</ul>
      </div>` : '';

    // Cobertura de la JD. Va arriba porque es lo primero que el reviewer necesita: qué
    // pedía la vacante y si el CV lo muestra. La distinción que importa no es
    // "aparece / no aparece" sino "está DESCRITO en la experiencia" vs "sólo figura en la
    // lista de tools", que es lo que un cliente lee distinto.
    // El estado visual no es sólo el status: un requisito que falta porque el candidato no
    // lo tiene NO es un defecto del CV y no se pinta en rojo como si la recruiter hubiera
    // hecho algo mal. Lo que decide es el cruce con in_source.
    const reqFace = r => {
      if (r.status === 'described') return { cls: 'described', label: 'Described in the experience' };
      if (r.in_source === 'no')     return { cls: 'fit',       label: "Not in the CV — not in the source either" };
      if (r.status === 'listed_only') {
        return { cls: 'listed_only',
                 label: r.in_source === 'yes' ? 'Only listed — the source backs it up'
                                              : 'Only listed — no role describes it' };
      }
      return { cls: 'missing',
               label: r.in_source === 'yes' ? 'Missing — but the source has it'
                                            : 'Not in the CV' };
    };
    const reqs = a.jd_requirements || [];
    const rs = a._requirements_summary || {};
    const reqRow = r => {
      const f = reqFace(r);
      return `
      <li class="cvr-req cvr-req--${f.cls}">
        <div class="cvr-req-main">
          <b>${esc(r.requirement)}</b>
          ${r.kind === 'soft' ? '<i class="cvr-req-soft">soft skill</i>' : ''}
          <span class="cvr-req-status">${esc(f.label)}</span>
        </div>
        ${r.evidence ? `<p class="cvr-req-ev">“${esc(r.evidence)}”</p>` : ''}
        ${r.note ? `<p class="cvr-req-note">${esc(r.note)}</p>` : ''}
      </li>`;
    };
    const reqsHtml = reqs.length ? `
      <div class="cvr-reqs">
        <h5>What the JD asked for
          ${rs.technical ? `<span class="cvr-reqs-count">${rs.described || 0} described ·
            ${rs.fixable_gaps || 0} the recruiter can fix ·
            ${rs.fit_gaps || 0} the candidate doesn't have</span>` : ''}
        </h5>
        ${rs.incomplete ? `<p class="cvr-reqs-warn">⚠️ The job posting lists
          ${rs.expected} requirements and only ${rs.listed} could be checked. Read the
          posting for the rest.</p>` : ''}
        <p class="cvr-reqs-lead">A tool in the skills list is not the same as a role that
          describes using it. What counts against the CV is only what the source material
          <b>does</b> support and the CV still doesn't show — the rest is the candidate not
          being a fit, which is not something the recruiter can or should fix.</p>
        <ul>${reqs.map(reqRow).join('')}</ul>
      </div>` : '';

    // Agrupadas por sección: el modelo devuelve una entrada por arreglo, y tres seguidas
    // que dicen "Work Experience" se leen como si la lista estuviera repetida.
    const bySection = [];
    (a.fixes || []).forEach(f => {
      const name = String(f.section || 'The document').trim();
      const g = bySection.find(x => x.name.toLowerCase() === name.toLowerCase());
      (g || bySection[bySection.push({ name, items: [] }) - 1]).items.push(f.fix || '');
    });
    const fixes = bySection.map(g => `<li><b>${esc(g.name)}</b>${
      g.items.length === 1
        ? `: ${esc(g.items[0])}`
        : `<ul>${g.items.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`
    }</li>`).join('');

    return `
      <div class="cvr-ai-top">
        <div class="cvr-ai-score">
          <b class="${qCls(score)}">${score === null || score === undefined ? '—' : score}</b>
          <span>/100</span>
        </div>
        <div class="cvr-ai-sum">
          ${a.verdict ? `<span class="cvr-verdict cvr-verdict--${esc(a.verdict)}">${esc(a.verdict.replace('_', ' '))}</span>` : ''}
          <p>${esc(a.summary || '')}</p>
          ${a._cap_reason ? `<p class="cvr-ai-cap">Capped: ${esc(a._cap_reason)} (would have been ${a._uncapped_score}).</p>` : ''}
          ${a._alignment_floor_reason ? `<p class="cvr-ai-floor">${esc(a._alignment_floor_reason)}</p>` : ''}
          ${a._partial ? '<p class="cvr-ai-cap">Partial: no job description, so JD alignment (30 of the weight) was skipped. Excluded from the recruiter average.</p>' : ''}
        </div>
      </div>
      ${reqsHtml}
      ${claims(hard, 'hard', 'Claims the source material does not support')}
      ${echoHtml}
      ${claims(soft, 'soft', 'Softer wording to double-check')}
      ${a.fit_note ? `<p class="cvr-note-block"><b>On the candidate's fit (not scored):</b> ${esc(a.fit_note)}</p>` : ''}
      ${!reqs.length && (a.jd_requirements_missed || []).length
        ? `<p class="cvr-note-block"><b>JD requirements the CV never addresses:</b> ${a.jd_requirements_missed.map(esc).join('; ')}</p>`
        : ''}
      ${fixes ? `<div class="cvr-fixes"><h5>What would make it better</h5><ul>${fixes}</ul></div>` : ''}
      <div class="cvr-crits">${bars}</div>
      <p class="cvr-ai-foot">The score is a hint, not a verdict. Read the CV before you decide.</p>`;
  }

  function renderRounds(reviews) {
    const box = $('cvrRounds');
    show($('cvrRoundsSection'), reviews.length > 1);
    box.innerHTML = reviews.sort((a, b) => b.round - a.round).map(r => {
      const [label, cls] = STATUS[r.status] || [r.status, ''];
      const reasons = (r.reasons || []).map(c => esc(reasonLabels[c] || c)).join(', ');
      return `
      <div class="cvr-round">
        <div class="cvr-round-head">
          <span class="cvr-round-n">Round ${r.round}</span>
          <span class="hx-status ${cls}">${label}</span>
          <span class="cvr-round-date">${fmtDate(r.reviewed_at || r.requested_at)}</span>
          ${r.ai_score !== null && r.ai_score !== undefined ? `<span class="cvr-round-score">${r.ai_score}/100</span>` : ''}
        </div>
        ${r.recruiter_note ? `<p class="cvr-round-line"><b>Recruiter:</b> ${esc(r.recruiter_note)}</p>` : ''}
        ${reasons ? `<p class="cvr-round-line"><b>Reasons:</b> ${reasons}</p>` : ''}
        ${r.reject_other ? `<p class="cvr-round-line"><b>Other:</b> ${esc(r.reject_other)}</p>` : ''}
        ${r.reviewer_comment ? `<p class="cvr-round-comment">${esc(r.reviewer_comment)}</p>` : ''}
      </div>`;
    }).join('');
  }

  function setRejectMode(on) {
    show($('cvrRejectForm'), on);
    show($('cvrRejectConfirm'), on);
    show($('cvrRejectCancel'), on);
    show($('cvrRejectToggle'), !on);
    show($('cvrApprove'), !on);
    $('cvrFootHint').textContent = on
      ? 'Pick at least one reason and leave a comment — it is what the recruiter acts on.'
      : '';
    if (on) {
      // Llevar el ojo al formulario: en un CV largo queda debajo del iframe.
      $('cvrRejectForm').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  function openDrawer(reviewId) {
    $('cvrDrawerError').textContent = '';
    setRejectMode(false);
    $('cvrAi').innerHTML = '<p class="cvr-ai-none">Loading…</p>';
    $('cvrRounds').innerHTML = '';
    show($('cvrScrim'), true);
    requestAnimationFrame(() => {
      $('cvrScrim').classList.add('is-open');
      $('cvrDrawer').classList.add('is-open');
    });

    fetch(`${API}/cv_reviews/${reviewId}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(data => {
        const r = data.review;
        currentReview = r;

        $('cvrDrawerTitle').textContent = r.candidate_name || 'Candidate';
        $('cvrDrawerEyebrow').textContent = `Round ${r.round} · ${r.status}`;
        $('cvrDrawerSub').textContent =
          [r.opp_position_name, r.client_name, `sent by ${r.recruiter_email}`]
            .filter(Boolean).join(' · ');

        // El CV TAL COMO SE ENVIÓ, no el actual: se juzga lo que la recruiter mandó, y
        // así las frases que cita el análisis existen seguro en lo que se está viendo.
        // resume-readonly.js lo pide a /cv_reviews/<id>/resume cuando ve review_id.
        const url = `resume-readonly.html?id=${r.candidate_id}&review_id=${r.review_id}`;
        $('cvrFrame').src = url;
        $('cvrOpenCv').href = url;

        const drift = $('cvrDrift');
        if (r.resume_drift) {
          drift.textContent = 'The recruiter edited this CV after submitting it, so what you '
            + 'see below is not exactly what was sent to review.';
          show(drift, true);
        } else {
          show(drift, false);
        }

        $('cvrAi').innerHTML = aiPanelHtml(r);

        show($('cvrDecisionFoot'), r.status === 'pending');

        return fetch(`${API}/candidates/${r.candidate_id}/cv_reviews?opportunity_id=${r.opportunity_id}`,
          { headers: headers() })
          .then(res => res.ok ? res.json() : { reviews: [] })
          .then(d => renderRounds(d.reviews || []));
      })
      .catch(err => {
        $('cvrAi').innerHTML = '';
        $('cvrDrawerError').textContent = `Could not load the review: ${err.message}`;
      });
  }

  function closeDrawer() {
    $('cvrDrawer').classList.remove('is-open');
    $('cvrScrim').classList.remove('is-open');
    setTimeout(() => { show($('cvrScrim'), false); $('cvrFrame').src = 'about:blank'; }, 220);
    currentReview = null;
  }

  /* -------------------------------------------------------------- decisiones */

  function renderReasonChecks() {
    $('cvrReasons').innerHTML = Object.entries(reasonLabels).map(([code, label]) => `
      <label class="cvr-reason">
        <input type="checkbox" value="${esc(code)}" />
        <span>${esc(label)}</span>
      </label>`).join('');
    // "Other" pide texto: sin eso la razón se pierde en las métricas.
    $('cvrReasons').addEventListener('change', () => {
      const other = $('cvrReasons').querySelector('input[value="other"]');
      show($('cvrReasonOtherWrap'), !!other?.checked);
    });
  }

  function decide(decision) {
    if (!currentReview) return;
    const body = { decision };
    if (decision === 'rejected') {
      body.reasons = Array.from($('cvrReasons').querySelectorAll('input:checked')).map(i => i.value);
      body.reason_other = $('cvrReasonOther').value.trim();
      body.reviewer_comment = $('cvrComment').value.trim();
    }

    const buttons = [$('cvrApprove'), $('cvrRejectConfirm'), $('cvrRejectToggle')];
    buttons.forEach(b => { b.disabled = true; });
    $('cvrDrawerError').textContent = '';

    fetch(`${API}/cv_reviews/${currentReview.review_id}/decision`, {
      method: 'POST', headers: headers(), body: JSON.stringify(body),
    })
      .then(async r => {
        const out = await r.json().catch(() => ({}));
        if (!r.ok) throw Object.assign(new Error(out.error || `HTTP ${r.status}`), { body: out });
        return out;
      })
      .then(out => {
        $('cvrComment').value = '';
        $('cvrReasonOther').value = '';
        $('cvrReasons').querySelectorAll('input:checked').forEach(i => { i.checked = false; });
        closeDrawer();
        refresh();
        if (out.batch_synced) {
          // Vale decirlo: el status del batch alimenta el donut de "razones de rechazo".
          console.info('cv-review: batch status set to "Rejected By Sales"');
        }
      })
      .catch(err => {
        $('cvrDrawerError').textContent = err.body?.error || err.message;
        if (err.body?.code === 'already_decided') refresh();
      })
      .finally(() => { buttons.forEach(b => { b.disabled = false; }); });
  }

  /* ------------------------------------------------------------------ carga */

  // Sin esto, alguien que ve 2 filas no sabe si hay 2 o si el filtro le esconde el resto.
  function updateScopeHint(isOversight) {
    const mine = $('cvrMine').checked;
    $('cvrScope').textContent = mine
      ? 'Showing only opportunities where you are the sales lead. Untick to see the rest.'
      : (isOversight
          ? 'Showing every recruiter and every sales lead.'
          : 'Showing everyone\'s, not just yours.');
  }

  const queryString = () => {
    const p = new URLSearchParams();
    if ($('cvrStatus').value) p.set('status', $('cvrStatus').value);
    if ($('cvrRecruiter').value) p.set('recruiter', $('cvrRecruiter').value);
    if ($('cvrMine').checked) p.set('mine', '1');
    return p.toString();
  };

  const periodString = () => {
    const p = new URLSearchParams();
    if ($('cvrFrom').value) p.set('desde', $('cvrFrom').value);
    if ($('cvrTo').value) p.set('hasta', $('cvrTo').value);
    // El MISMO filtro que la cola: si no, la métrica de arriba y la lista de abajo
    // estarían contando universos distintos en la misma pantalla.
    if ($('cvrMine').checked) p.set('mine', '1');
    if ($('cvrRecruiter').value) p.set('recruiter', $('cvrRecruiter').value);
    return p.toString();
  };

  function refresh() {
    show($('cvrQueueLoading'), true);
    show($('cvrQueueWrap'), false);
    show($('cvrQueueEmpty'), false);

    fetch(`${API}/cv_reviews?${queryString()}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => { queueRows = d.reviews || []; renderQueue(); })
      .catch(err => {
        queueRows = [];
        $('cvrQueue').innerHTML = '';
        show($('cvrQueueLoading'), false);
        show($('cvrQueueWrap'), false);
        const empty = $('cvrQueueEmpty');
        empty.querySelector('h3').textContent = 'Could not load the queue';
        empty.querySelector('p').textContent = err.message;
        show(empty, true);
      });

    const period = periodString();
    fetch(`${API}/cv_reviews/metrics${period ? '?' + period : ''}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(renderMetrics)
      .catch(err => {
        $('cvrMetrics').innerHTML = '';
        $('cvrMetricsEmpty').querySelector('p').textContent = `Could not load the metrics: ${err.message}`;
        show($('cvrMetricsEmpty'), true);
      });
  }

  const loadRecruiters = () => fetch(`${API}/users/recruiters`, { headers: headers() })
    .then(r => r.ok ? r.json() : [])
    .then(list => {
      (Array.isArray(list) ? list : []).forEach(u => {
        const email = (u.email_vintti || '').toLowerCase();
        if (!email) return;
        const o = document.createElement('option');
        o.value = email;
        o.textContent = u.user_name || email;
        $('cvrRecruiter').appendChild(o);
      });
    })
    .catch(() => {});

  const loadReasons = () => fetch(`${API}/cv_review_reasons`, { headers: headers() })
    .then(r => r.ok ? r.json() : { reasons: [] })
    .then(d => {
      (d.reasons || []).forEach(x => { reasonLabels[x.code] = x.label; });
      renderReasonChecks();
    })
    .catch(() => {});

  /* ------------------------------------------------------------------- init */

  document.addEventListener('DOMContentLoaded', () => {
    if (!ALLOWED.has(me)) { show($('cvrDenied'), true); return; }
    show($('cvrApp'), true);

    // Un sales lead abre la página viendo SÓLO sus oportunidades; la supervisión, todo.
    // Es un valor por defecto, no un candado: destildando la casilla ve el resto.
    const isOversight = OVERSIGHT.has(me);
    $('cvrMine').checked = !isOversight;
    $('cvrMineLabel').textContent = isOversight ? 'Only mine' : 'Only my opportunities';

    // Un deep-link desde un mail es una instrucción explícita: mostrame ESTO. Los defaults
    // (status="pending", "sólo mis oportunidades") lo esconderían si el review ya se decidió
    // o si es de otro sales lead, y el botón del mail parecería roto.
    if (deepReviewId || deepOppId) $('cvrStatus').value = '';
    if (deepOppId) $('cvrMine').checked = false;

    updateScopeHint(isOversight);
    $('cvrMine').addEventListener('change', () => updateScopeHint(isOversight));

    $('cvrApply').addEventListener('click', refresh);
    $('cvrRefresh').addEventListener('click', refresh);
    $('cvrStatus').addEventListener('change', refresh);
    $('cvrRecruiter').addEventListener('change', refresh);
    $('cvrMine').addEventListener('change', refresh);
    // El buscador filtra en memoria: la cola ya está cargada, no hace falta ir al backend.
    $('cvrSearch').addEventListener('input', renderQueue);

    $('cvrRejectToggle').addEventListener('click', () => setRejectMode(true));
    $('cvrRejectCancel').addEventListener('click', () => setRejectMode(false));
    $('cvrApprove').addEventListener('click', () => decide('approved'));
    $('cvrRejectConfirm').addEventListener('click', () => decide('rejected'));

    $('cvrReanalyze').addEventListener('click', () => {
      if (!currentReview) return;
      const btn = $('cvrReanalyze');
      btn.disabled = true;
      const label = btn.innerHTML;
      btn.innerHTML = '<i class="fa-solid fa-rotate fa-spin"></i> Running…';
      fetch(`${API}/cv_reviews/${currentReview.review_id}/analyze`,
        { method: 'POST', headers: headers() })
        .then(async r => {
          const out = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(out.error || `HTTP ${r.status}`);
          return out;
        })
        .then(out => {
          currentReview.ai_analysis = out.ai_analysis;
          currentReview.ai_score = out.ai_score;
          currentReview.ai_error = null;
          $('cvrAi').innerHTML = aiPanelHtml(currentReview);
          refresh();
        })
        .catch(err => { $('cvrDrawerError').textContent = err.message; })
        .finally(() => { btn.disabled = false; btn.innerHTML = label; });
    });

    $('cvrClose').addEventListener('click', closeDrawer);
    $('cvrScrim').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && $('cvrDrawer').classList.contains('is-open')) closeDrawer();
    });

    Promise.all([loadReasons(), loadRecruiters()]).then(() => {
      refresh();
      // openDrawer se trae el review por su id, así que no espera a la cola.
      if (deepReviewId) openDrawer(deepReviewId);
    });
  });
})();
