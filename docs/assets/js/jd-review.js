/* JD Review — la cola del sales lead para las Job Descriptions.
 *
 * Hermana de cv-review.js. La JD la escribe la AI desde los transcripts de Grain de la
 * Intro Call y la Deep Dive; acá el sales lead ve, punto por punto, qué de lo que dijo el
 * cliente llegó a la JD, qué dice distinto y qué agregó sin que nadie lo pidiera, y aprueba
 * o pide cambios. El gate real es del backend (POST /jd_reviews/<id>/decision → 403).
 *
 * Reusa el CSS de cv-review (clases cvr-*) y el anillo de cv-review-cards.js.
 */
(function () {
  'use strict';

  const API = (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  // Mismas listas que cv-review.js: quién revisa es la misma gente. El backend importa
  // OVERSIGHT_EMAILS / _require_reviewer de cv_review_routes, así que hay UNA fuente allá.
  const OVERSIGHT = new Set(['pgonzales@vintti.com', 'agostina@vintti.com']);
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
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const CARDS = window.CvReviewCards;

  const who = (email) => String(email || '').split('@')[0] || 'someone';
  const fmtDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
  };
  const daysWaiting = (iso) => {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? Math.floor((Date.now() - d.getTime()) / 86400000) : null;
  };

  const STATUS = {
    pending:   ['Waiting',   'cvr-st-pending'],
    approved:  ['Approved',  'cvr-st-approved'],
    changes_requested: ['Needs changes', 'cvr-st-changes'],
    cancelled: ['Cancelled', 'cvr-st-cancelled'],
  };

  const CATEGORY_LABEL = {
    responsibilities: 'Responsibilities',
    tools: 'Tools / tech stack',
    experience: 'Experience / seniority',
    english: 'English level',
    schedule_location: 'Schedule / timezone / location',
    conditions: 'Contract / conditions',
    nice_to_have: 'Nice to have',
    company_context: 'Company / team context',
  };
  const SOURCE_LABEL = { intro: 'Intro Call', deep_dive: 'Deep Dive' };
  const NO_SCORE = {
    no_transcripts: 'The opportunity has no usable Grain recording (Intro Call / Deep Dive), so there was nothing to check the JD against. Add the links on the opportunity and re-run.',
    no_jd: 'The JD was empty when it was sent.',
    budget: 'The OpenAI budget is spent — the analysis could not run.',
  };

  let checklistLabels = {};
  let currentReview = null;
  let queueRows = [];
  const DEEP = new URLSearchParams(location.search);
  const deepReviewId = Number(DEEP.get('review_id')) || null;

  /* --------------------------------------------------------------- métricas */

  const metricCard = (r, isTotal) => window.JdReviewCards.card(r, isTotal);

  function renderMetrics(data) {
    const rows = data.rows || [];
    const totals = data.totals || {};
    const meta = data.meta || {};
    $('jdrMetricsWindow').textContent = (meta.desde ? `${meta.desde} → ${meta.hasta}` : '')
      + (meta.ai_version ? `  ·  scoring v${meta.ai_version}` : '');
    const sum = [];
    if (rows.length) sum.push(`${rows.length} recruiter${rows.length === 1 ? '' : 's'}`);
    if (totals.jds_sent) sum.push(`${totals.jds_sent} sent`);
    if (totals.quality_avg !== null && totals.quality_avg !== undefined) sum.push(`${totals.quality_avg} avg coverage`);
    $('jdrMetricsSum').textContent = sum.join('  ·  ');
    if (!rows.length) {
      $('jdrMetrics').innerHTML = '';
      show($('jdrMetricsEmpty'), true);
      return;
    }
    show($('jdrMetricsEmpty'), false);
    $('jdrMetrics').innerHTML = metricCard(totals, true) + rows.map(r => metricCard(r, false)).join('');
  }

  /* ------------------------------------------------------------------- cola */

  function covCell(r) {
    if (r.ai_pending) return '<span class="cvr-score-none">scoring…</span>';
    if (r.ai_score === null || r.ai_score === undefined) {
      const why = r.ai_error === 'no_transcripts' ? 'no recordings' : '—';
      return `<span class="cvr-score-none">${why}</span>`;
    }
    return CARDS.ringHtml(r.ai_score);
  }

  function ageCell(r) {
    const waited = r.status === 'pending' ? daysWaiting(r.requested_at) : null;
    if (waited === null) return `<span class="cvr-age">${fmtDate(r.reviewed_at || r.requested_at)}</span>`;
    return `<span class="cvr-age${waited >= 3 ? ' cvr-age--old' : ''}">${waited === 0 ? 'today' : waited + 'd'}</span>`;
  }

  function renderQueue() {
    const term = ($('jdrSearch').value || '').toLowerCase().trim();
    const list = !term ? queueRows : queueRows.filter(r =>
      [r.opp_position_name, r.client_name, r.recruiter_email, String(r.opportunity_id)]
        .some(v => String(v || '').toLowerCase().includes(term)));
    $('jdrCount').innerHTML = `<b>${list.length}</b> of ${queueRows.length}`;
    show($('jdrQueueLoading'), false);
    if (!list.length) {
      $('jdrQueueBody').innerHTML = '';
      show($('jdrQueueWrap'), false);
      show($('jdrQueueEmpty'), true);
      return;
    }
    show($('jdrQueueEmpty'), false);
    show($('jdrQueueWrap'), true);
    const statuses = new Set(list.map(r => r.status));
    $('jdrQueueTable').classList.toggle('cvr-table--nostatus', statuses.size <= 1);
    $('jdrQueueBody').innerHTML = list.map(r => {
      const [label, cls] = STATUS[r.status] || [r.status, ''];
      const round = Number(r.round) > 1 ? `<span class="cvr-round-chip">R${esc(r.round)}</span>` : '';
      return `
      <tr class="cvr-row" data-review-id="${r.review_id}" tabindex="0">
        <td>
          <div class="cvr-cand">${esc(r.opp_position_name || '—')}
            <span class="cvr-oppid">#${esc(r.opportunity_id)}</span>${round}</div>
          <div class="cvr-row-sub">${esc([r.client_name, r.recruiter_email].filter(Boolean).join(' · '))}</div>
        </td>
        <td class="cvr-col-score">${covCell(r)}</td>
        <td class="cvr-col-status"><span class="hx-status ${cls}">${esc(label)}</span></td>
        <td class="cvr-col-age">${ageCell(r)}</td>
      </tr>`;
    }).join('');
  }

  function wireQueue() {
    const body = $('jdrQueueBody');
    const act = (e) => {
      const row = e.target.closest('.cvr-row');
      if (row) openDrawer(Number(row.dataset.reviewId));
    };
    body.addEventListener('click', act);
    body.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(e); }
    });
  }

  /* -------------------------------------------------------------- resaltado
   *
   * Las citas del análisis se pintan sobre la JD con la CSS Custom Highlight API: no toca el
   * DOM de la JD, así que no hay forma de que un <mark> termine copiado a otro lado.
   * Se ubican contra el texto normalizado (minúsculas, sin comillas, espacios colapsados),
   * con un mapa de vuelta a la posición real en cada nodo de texto.
   */
  const HL_KINDS = ['covered', 'partial', 'contradicted', 'invented', 'focus'];
  const hlSupported = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight === 'function';
  let hlIndex = null;
  const hlRanges = new Map(); // key -> Range

  function hlBuildIndex() {
    const root = $('jdrDoc');
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let norm = '';
    const map = []; // norm idx -> [node, offset]
    let lastSpace = true;
    let node;
    while ((node = walker.nextNode())) {
      const t = node.nodeValue;
      for (let i = 0; i < t.length; i++) {
        let c = t[i];
        if (/["“”'’`]/.test(c)) continue;
        if (/\s/.test(c)) {
          if (lastSpace) continue;
          c = ' ';
          lastSpace = true;
        } else {
          lastSpace = false;
          c = c.toLowerCase();
        }
        norm += c;
        map.push([node, i]);
      }
      // Un bloque nuevo es un corte de palabra aunque el HTML no tenga espacio.
      if (!lastSpace) { norm += ' '; map.push([node, t.length]); lastSpace = true; }
    }
    hlIndex = { norm, map };
  }

  const normQuote = (q) => String(q || '').replace(/["“”'’`]/g, '').replace(/\s+/g, ' ')
    .trim().toLowerCase();

  function hlLocate(quote) {
    if (!hlIndex) return null;
    const q = normQuote(quote);
    if (q.length < 3) return null;
    const at = hlIndex.norm.indexOf(q);
    if (at < 0) return null;
    const [sn, so] = hlIndex.map[at];
    const [en, eo] = hlIndex.map[at + q.length - 1];
    const r = document.createRange();
    r.setStart(sn, so);
    r.setEnd(en, Math.min(eo + 1, en.nodeValue.length));
    return r;
  }

  function hlApply() {
    if (!hlSupported) return;
    HL_KINDS.forEach(k => CSS.highlights.delete(`jdr-${k}`));
    if (!$('jdrHlSwitch').checked) return;
    const byKind = {};
    hlRanges.forEach((v) => { (byKind[v.kind] = byKind[v.kind] || []).push(v.range); });
    Object.entries(byKind).forEach(([k, ranges]) => CSS.highlights.set(`jdr-${k}`, new Highlight(...ranges)));
  }

  function hlGoTo(key) {
    const entry = hlRanges.get(key);
    if (!entry) return;
    const doc = $('jdrDoc');
    const rect = entry.range.getBoundingClientRect();
    const box = doc.getBoundingClientRect();
    doc.scrollTo({ top: doc.scrollTop + rect.top - box.top - box.height / 3, behavior: 'smooth' });
    if (hlSupported) {
      CSS.highlights.set('jdr-focus', new Highlight(entry.range));
      setTimeout(() => CSS.highlights.delete('jdr-focus'), 1600);
    }
  }

  function hlLoad(analysis) {
    hlRanges.clear();
    hlBuildIndex();
    if (!analysis) { hlApply(); return; }
    (analysis.facts || []).forEach((f, i) => {
      if (!f.jd_quote || f.status === 'missing') return;
      const range = hlLocate(f.jd_quote);
      if (range) hlRanges.set(`f${i}`, { range, kind: f.status });
    });
    (analysis.unsupported || []).forEach((u, i) => {
      const range = hlLocate(u.jd_quote);
      if (range) hlRanges.set(`u${i}`, { range, kind: 'invented' });
    });
    hlApply();
  }

  /* ---------------------------------------------------------------- análisis */

  const fmtN = (n) => (Number.isInteger(Number(n)) ? String(Number(n)) : Number(n).toFixed(1));

  // Lo que ese punto aporta al score. Los números los pone el backend (compute_score): acá no
  // se recalcula nada, sólo se muestra.
  function pointsChip(f) {
    if (f.max_points === undefined) return '';
    const got = Number(f.points) || 0;
    const cls = got >= f.max_points ? 'is-full' : got > 0 ? 'is-half' : 'is-zero';
    const pen = f.penalty ? ` <b class="jdr-pts-pen">−${fmtN(f.penalty)}</b>` : '';
    return `<span class="jdr-pts ${cls}" title="Adds ${fmtN(got)} of the ${fmtN(f.max_points)} this point is worth${f.penalty ? `, and takes ${fmtN(f.penalty)} more off the final score` : ''}">+${fmtN(got)} of ${fmtN(f.max_points)}${pen}</span>`;
  }

  // Con más de una parte se dice cuál está y cuál no: es lo que explica un "partly there".
  const PART_MARK = { explicit: ['✓', 'In the JD'], implied: ['≈', 'Implied by the JD'], no: ['✗', 'Not in the JD'] };
  function partsHtml(f) {
    const parts = f.parts || [];
    if (parts.length < 2) return '';
    return `<div class="jdr-parts">${parts.map(p => {
      const [mark, title] = PART_MARK[p.in_jd] || PART_MARK.no;
      return `<span class="jdr-part jdr-part--${esc(p.in_jd)}" title="${esc(title)}${p.evidence ? ': “' + esc(p.evidence) + '”' : ''}">${mark} ${esc(p.part)}</span>`;
    }).join('')}</div>`;
  }

  function factItem(f, i) {
    const src = SOURCE_LABEL[f.source] || '';
    const key = `f${i}`;
    const loc = hlRanges.has(key);
    // Las dos etiquetas SIEMPRE: con sólo "core" los secundarios no decían nada y había que
    // deducirlos. El title explica cuánto pesa cada una.
    const imp = f.importance === 'must'
      ? '<span class="jdr-imp" title="Core: the client presented it as required or central to the job. Weighs 2.">core</span>'
      : '<span class="jdr-imp jdr-imp--nice" title="Secondary: optional, a plus, nice to have, or salary. Weighs 1.">secondary</span>';
    return `
      <li class="jdr-fact jdr-fact--${esc(f.status)}${loc ? ' is-locatable' : ''}" ${loc ? `data-hl="${key}" tabindex="0" role="button"` : ''}>
        <div class="jdr-fact-l1"><b>${esc(f.fact)}</b>${imp}${src ? `<span class="jdr-src">${esc(src)}</span>` : ''}${pointsChip(f)}</div>
        ${partsHtml(f)}
        ${f.quote ? `<div class="jdr-quote">“${esc(f.quote)}”</div>` : ''}
        ${f.jd_quote && f.status !== 'covered' ? `<div class="jdr-jdq"><span>JD:</span> “${esc(f.jd_quote)}”</div>` : ''}
        ${f.why ? `<div class="jdr-why">${esc(f.why)}</div>` : ''}
      </li>`;
  }

  function aiPanelHtml(r) {
    if (r.ai_pending) {
      return '<p class="cvr-ai-none"><i class="fa-solid fa-spinner fa-spin"></i> Fetching the recordings and scoring… this takes about a minute.</p>';
    }
    const a = r.ai_analysis;
    if (r.ai_score === null || r.ai_score === undefined) {
      const msg = NO_SCORE[r.ai_error] || (a && a._score_basis === 'no_facts'
        ? 'The recordings did not contain anything concrete about the role to check against.'
        : (r.ai_error ? `The analysis failed (${esc(r.ai_error)}). Re-run it.` : 'No analysis yet.'));
      if (!a) return `<p class="cvr-ai-none">${msg}</p>`;
    }
    const s = (a && a.summary) || {};
    const counts = s.counts || {};
    const facts = (a && a.facts) || [];
    const coreN = facts.filter(f => f.importance === 'must').length;
    const niceN = facts.length - coreN;
    const hero = (r.ai_score !== null && r.ai_score !== undefined) ? `
      <div class="jdr-hero">
        ${CARDS.ringHtml(r.ai_score, 'cvr-cov--lg')}
        <div>
          <div class="jdr-verdict jdr-verdict--${esc(a.verdict || '')}">${esc({ ready: 'Ready', needs_work: 'Needs work', not_sendable: 'Fix before publishing' }[a.verdict] || '')}</div>
          <div class="jdr-verdict-why">${esc(a.verdict_why || '')}</div>
          <div class="jdr-math">${coreN} core · ${niceN} secondary points from the calls</div>
          <div class="jdr-math">${counts.covered || 0} covered · ${counts.partial || 0} partial · ${counts.missing || 0} missing · ${counts.contradicted || 0} different
            ${s.contradiction_penalty ? ` · −${s.contradiction_penalty} for differences` : ''}
            ${s.unsupported_penalty ? ` · −${s.unsupported_penalty} for invented` : ''}</div>
        </div>
      </div>` : '';

    const idx = facts.map((f, i) => [f, i]);
    const math = scoreMathHtml(s, r.ai_score);
    const contradicted = idx.filter(([f]) => f.status === 'contradicted');
    const missing = idx.filter(([f]) => f.status === 'missing');
    const partial = idx.filter(([f]) => f.status === 'partial');
    const covered = idx.filter(([f]) => f.status === 'covered');

    const byCategory = (pairs) => {
      const groups = {};
      pairs.forEach(p => { (groups[p[0].category] = groups[p[0].category] || []).push(p); });
      return Object.entries(groups).map(([cat, ps]) => `
        <p class="jdr-cat">${esc(CATEGORY_LABEL[cat] || cat)}</p>
        <ul class="jdr-facts">${ps.map(([f, i]) => factItem(f, i)).join('')}</ul>`).join('');
    };

    const unsupported = ((a && a.unsupported) || []).map((u, i) => {
      const key = `u${i}`;
      const loc = hlRanges.has(key);
      return `<li class="jdr-fact jdr-fact--invented${u.severity === 'soft' ? ' is-soft' : ''}${loc ? ' is-locatable' : ''}" ${loc ? `data-hl="${key}" tabindex="0" role="button"` : ''}>
        <div class="jdr-fact-l1"><b>“${esc(u.jd_quote)}”</b>${u.severity === 'hard' ? '<span class="jdr-imp">requirement</span>' : '<span class="jdr-src">filler</span>'}${u.penalty ? `<span class="jdr-pts is-zero"><b class="jdr-pts-pen">−${fmtN(u.penalty)}</b></span>` : (u.severity === 'soft' ? '<span class="jdr-pts is-free" title="Generic filler is shown but does not take points off">no penalty</span>' : '')}</div>
        ${u.why ? `<div class="jdr-why">${esc(u.why)}</div>` : ''}
      </li>`;
    }).join('');

    const block = (title, cls, inner, open) => inner ? `
      <details class="jdr-block ${cls}" ${open ? 'open' : ''}>
        <summary>${title}</summary>${inner}
      </details>` : '';

    return hero + math
      + block(`Says something different from the calls <b>${contradicted.length}</b>`, 'jdr-block--contradicted',
              contradicted.length ? `<ul class="jdr-facts">${contradicted.map(([f, i]) => factItem(f, i)).join('')}</ul>` : '', true)
      + block(`Discussed in the calls, missing from the JD <b>${missing.length}</b>`, 'jdr-block--missing',
              missing.length ? byCategory(missing) : '', true)
      + block(`In the JD, but nobody said it <b>${((a && a.unsupported) || []).length}</b>`, 'jdr-block--invented',
              unsupported ? `<ul class="jdr-facts">${unsupported}</ul>` : '', true)
      + block(`Only partly there <b>${partial.length}</b>`, 'jdr-block--partial',
              partial.length ? `<ul class="jdr-facts">${partial.map(([f, i]) => factItem(f, i)).join('')}</ul>` : '', false)
      + block(`Covered <b>${covered.length}</b>`, 'jdr-block--covered',
              covered.length ? byCategory(covered) : '', false);
  }

  const STATUS_WORD = { covered: 'covered', partial: 'partly there', missing: 'missing', contradicted: 'says something different' };

  // La cuenta del score, fila por fila. Todo viene armado del backend (summary.breakdown).
  function scoreMathHtml(s, score) {
    if (!s || !s.breakdown || score === null || score === undefined) return '';
    const rules = s.rules || {};
    const rows = s.breakdown.map(g => `
      <tr class="jdr-math-${esc(g.status)}">
        <td>${g.importance === 'must' ? 'Core' : 'Secondary'} · ${esc(STATUS_WORD[g.status] || g.status)}</td>
        <td class="n">${g.count} × ${fmtN(g.weight * g.credit)}</td>
        <td class="n">+${fmtN(g.points)} <span>of ${fmtN(g.max)}</span></td>
      </tr>`).join('');
    const pen = [];
    if (s.contradiction_penalty) {
      pen.push(`<tr class="jdr-math-pen"><td>Says something different (−${fmtN(rules.contradiction_penalty)} each, max −${fmtN(rules.contradiction_cap)})</td><td class="n">${(s.counts || {}).contradicted || 0}</td><td class="n">−${fmtN(s.contradiction_penalty)}</td></tr>`);
    }
    if (s.unsupported_penalty) {
      pen.push(`<tr class="jdr-math-pen"><td>Requirements nobody asked for (−${fmtN(rules.unsupported_penalty)} each, max −${fmtN(rules.unsupported_cap)})</td><td class="n">${s.hard_unsupported || 0}</td><td class="n">−${fmtN(s.unsupported_penalty)}</td></tr>`);
    }
    return `
      <details class="jdr-block jdr-block--math">
        <summary>How the ${score} is built</summary>
        <p class="jdr-math-note">Core points are worth ${fmtN((rules.weights || {}).must || 2)}, secondary ${fmtN((rules.weights || {}).nice || 1)}.
          Covered earns all of it, partly there half, missing or different nothing.</p>
        <table class="jdr-math-table">
          <tbody>${rows}</tbody>
          <tbody class="jdr-math-sub">
            <tr><td>Coverage</td><td class="n">${fmtN(s.earned)} of ${fmtN(s.possible)}</td><td class="n">${fmtN(s.base)}</td></tr>
            ${pen.join('')}
          </tbody>
          <tfoot><tr><td>Score</td><td></td><td class="n">${score}</td></tr></tfoot>
        </table>
      </details>`;
  }

  function renderSources(r) {
    const t = r.transcripts || {};
    const bits = ['intro', 'deep_dive'].map(k => {
      const e = t[k] || {};
      const label = SOURCE_LABEL[k];
      if (e.chars) return `${label}: <b>${e.pasted ? 'pasted transcript' : 'recording read'}</b>`;
      if (e.error === 'no_link') return `${label}: <b>no link on the opportunity</b>`;
      if (e.error) return `${label}: <b>could not be read</b> (${esc(String(e.error).slice(0, 120))})`;
      return `${label}: —`;
    });
    const missingOne = ['intro', 'deep_dive'].some(k => !(t[k] || {}).chars);
    $('jdrSources').innerHTML = bits.join('<br>')
      + (missingOne && !r.ai_pending ? '<br>What was said in a missing call can\'t be checked.' : '');
    show($('jdrSources'), !r.ai_pending && (t.intro || t.deep_dive));
  }

  function renderRounds(rounds) {
    show($('jdrRoundsSection'), rounds.length > 1);
    $('jdrRounds').innerHTML = rounds.map(r => {
      const [label, cls] = STATUS[r.status] || [r.status, ''];
      const flags = (r.checklist || []).map(c => esc(checklistLabels[c] || c)).join(', ');
      return `
      <div class="cvr-round">
        <div class="cvr-round-head">
          <span class="cvr-round-n">Round ${r.round}</span>
          <span class="hx-status ${cls}">${label}</span>
          <span class="cvr-round-date">${fmtDate(r.reviewed_at || r.requested_at)}</span>
          ${r.ai_score !== null && r.ai_score !== undefined ? `<span class="cvr-round-score">${r.ai_score}/100</span>` : ''}
        </div>
        ${r.recruiter_note ? `<p class="cvr-round-line"><b>Recruiter:</b> ${esc(r.recruiter_note)}</p>` : ''}
        ${flags ? `<p class="cvr-round-line"><b>Checklist:</b> ${flags}</p>` : ''}
        ${r.reviewer_comment ? `<p class="cvr-round-comment">${esc(r.reviewer_comment)}</p>` : ''}
      </div>`;
    }).join('');
  }

  /* ------------------------------------------------------------------ drawer */

  let pollTimer = null;

  function openDrawer(reviewId) {
    $('jdrDrawerError').textContent = '';
    setMode(null);
    resetChecklist();
    $('jdrAi').innerHTML = '<p class="cvr-ai-none">Loading…</p>';
    $('jdrDoc').innerHTML = '';
    $('jdrRounds').innerHTML = '';
    show($('jdrDrift'), false);
    show($('jdrSources'), false);
    show($('jdrScrim'), true);
    requestAnimationFrame(() => {
      $('jdrScrim').classList.add('is-open');
      $('jdrDrawer').classList.add('is-open');
    });
    loadReview(reviewId);
  }

  function loadReview(reviewId) {
    clearTimeout(pollTimer);
    return fetch(`${API}/jd_reviews/${reviewId}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(r => {
        currentReview = r;
        $('jdrDrawerTitle').textContent = r.opp_position_name || 'Job description';
        $('jdrDrawerSub').textContent = [r.client_name, `#${r.opportunity_id}`, `Round ${r.round}`,
          `sent by ${r.recruiter_email}`, (STATUS[r.status] || [r.status])[0]].filter(Boolean).join(' · ');
        $('jdrOpenOpp').href = `opportunity-detail.html?id=${r.opportunity_id}&tab=job%20description`;
        // La JD viene del editor de la vacante (HTML propio del Hub). Se pinta tal cual,
        // igual que la pestaña Job Description, sin scripts.
        $('jdrDoc').innerHTML = sanitize(r.jd_snapshot || '');
        const drift = $('jdrDrift');
        if (r.jd_changed_since) {
          drift.innerHTML = r.status === 'pending'
            ? '<b>The JD on the opportunity changed after this was sent.</b> You are reviewing the version that was sent.'
            : 'The JD on the opportunity changed after this round.';
          show(drift, true);
        }
        hlLoad(r.ai_analysis);
        $('jdrAi').innerHTML = aiPanelHtml(r);
        renderSources(r);
        // Re-run sólo tiene sentido si algo falló: la JD de la ronda está congelada y la lista de
        // puntos guardada, así que sin error daría lo mismo. "Falló" incluye una grabación que
        // no se pudo leer (sin link o Grain caído): cargarla y reintentar es el caso de uso.
        const tr = r.transcripts || {};
        const recordingFailed = ['intro', 'deep_dive'].some(k => !(tr[k] || {}).chars);
        show($('jdrReanalyze'), !r.ai_pending && (!!r.ai_error || recordingFailed));
        show($('jdrRebuild'), !r.ai_pending && !r.ai_error);
        const fn = $('jdrFactsNote');
        const an = r.ai_analysis || {};
        if (!r.ai_pending && an._facts_key) {
          // Reconstruir cambia la vara de TODAS las rondas: se dice quién y cuándo, en ámbar.
          const rebuilt = an._facts_rebuilt_by
            ? `List of points rebuilt by ${who(an._facts_rebuilt_by)} on ${fmtDate(an._facts_rebuilt_at)}. `
              + 'Every round of this opportunity was re-scored against it.'
            : '';
          fn.textContent = rebuilt || (an._facts_reused
            ? 'Same saved list of points from the calls as the previous run — only the JD was re-checked.'
            : 'New list of points from the calls. It is saved: later rounds reuse it.');
          fn.classList.toggle('is-rebuilt', !!rebuilt);
          show(fn, true);
        } else show(fn, false);
        renderRounds(r.rounds || []);
        paintDecisionState(r);
        // Mientras el hilo scorea, se vuelve a pedir: el mail sale al terminar y el sales
        // lead suele abrir la página antes.
        if (r.ai_pending) pollTimer = setTimeout(() => {
          if (currentReview && currentReview.review_id === reviewId) loadReview(reviewId);
        }, 8000);
      })
      .catch(err => {
        $('jdrAi').innerHTML = '';
        $('jdrDrawerError').textContent = `Could not load the review: ${err.message}`;
      });
  }

  function sanitize(html) {
    const tpl = document.createElement('template');
    tpl.innerHTML = html;
    tpl.content.querySelectorAll('script,style,iframe,object,embed,link,meta').forEach(n => n.remove());
    tpl.content.querySelectorAll('*').forEach(el => {
      [...el.attributes].forEach(a => {
        if (/^on/i.test(a.name) || (/^(href|src)$/i.test(a.name) && /^\s*javascript:/i.test(a.value))) {
          el.removeAttribute(a.name);
        }
      });
    });
    const div = document.createElement('div');
    div.appendChild(tpl.content);
    return div.innerHTML;
  }

  function closeDrawer() {
    clearTimeout(pollTimer);
    $('jdrDrawer').classList.remove('is-open');
    $('jdrScrim').classList.remove('is-open');
    if (hlSupported) HL_KINDS.forEach(k => CSS.highlights.delete(`jdr-${k}`));
    setTimeout(() => show($('jdrScrim'), false), 220);
    currentReview = null;
  }

  /* -------------------------------------------------------------- decisiones */

  function renderChecklistChecks() {
    $('jdrChecklist').innerHTML = Object.entries(checklistLabels).map(([code, label]) => `
      <label class="cvr-check">
        <input type="checkbox" value="${esc(code)}" />
        <span>${esc(label)}</span>
      </label>`).join('');
  }

  const checklistPicks = () =>
    Array.from($('jdrChecklist').querySelectorAll('input:checked')).map(i => i.value);
  const checklistDone = () => !!checklistPicks().length || $('jdrChecklistClean').checked;

  function resetChecklist() {
    $('jdrChecklist').querySelectorAll('input').forEach(i => { i.checked = false; i.disabled = false; });
    const clean = $('jdrChecklistClean');
    clean.checked = false;
    clean.disabled = false;
    $('jdrChecklistSection').classList.remove('is-missing');
  }

  function paintDecisionState(r) {
    const pending = r.status === 'pending';
    show($('jdrDecisionFoot'), pending);
    if (!pending) {
      const picks = new Set(r.checklist || []);
      $('jdrChecklist').querySelectorAll('input').forEach(i => { i.checked = picks.has(i.value); i.disabled = true; });
      const clean = $('jdrChecklistClean');
      clean.checked = r.checklist_done && !picks.size;
      clean.disabled = true;
    }
    syncGate();
  }

  let mode = null;
  function setMode(m) {
    mode = m;
    const chg = m === 'changes_requested';
    show($('jdrChangesForm'), chg);
    show($('jdrChangesConfirm'), chg);
    show($('jdrChangesCancel'), chg);
    show($('jdrChangesToggle'), !chg);
    show($('jdrApprove'), !chg);
    syncGate();
  }

  function syncGate() {
    if (!currentReview || currentReview.status !== 'pending') return;
    const ready = checklistDone();
    [$('jdrApprove'), $('jdrChangesConfirm')].forEach(b => { b.disabled = !ready; });
    $('jdrFootHint').textContent = ready
      ? (mode ? 'The recruiter gets your comment by email.' : '')
      : 'Go through the checklist before deciding.';
    if (ready) $('jdrChecklistSection').classList.remove('is-missing');
  }

  function decide(decision) {
    if (!currentReview) return;
    if (!checklistDone()) {
      const sec = $('jdrChecklistSection');
      sec.open = true;
      sec.classList.add('is-missing');
      sec.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    const body = {
      decision,
      checklist: checklistPicks(),
      checklist_clean: $('jdrChecklistClean').checked,
      comment: decision === 'changes_requested' ? $('jdrChangesComment').value.trim() : '',
    };
    const buttons = [$('jdrApprove'), $('jdrChangesConfirm'), $('jdrChangesToggle')];
    buttons.forEach(b => { b.disabled = true; });
    $('jdrDrawerError').textContent = '';
    fetch(`${API}/jd_reviews/${currentReview.review_id}/decision`, {
      method: 'POST', headers: headers(), body: JSON.stringify(body),
    })
      .then(async r => {
        const out = await r.json().catch(() => ({}));
        if (!r.ok) throw Object.assign(new Error(out.error || `HTTP ${r.status}`), { body: out });
        return out;
      })
      .then(() => {
        $('jdrChangesComment').value = '';
        closeDrawer();
        refresh();
      })
      .catch(err => {
        $('jdrDrawerError').textContent = err.body?.error || err.message;
        if (err.body?.code === 'already_decided') refresh();
      })
      .finally(() => { buttons.forEach(b => { b.disabled = false; }); syncGate(); });
  }

  /* ------------------------------------------------------------------ carga */

  function queryString() {
    const p = new URLSearchParams();
    if ($('jdrStatus').value) p.set('status', $('jdrStatus').value);
    if ($('jdrRecruiter').value) p.set('recruiter', $('jdrRecruiter').value);
    if ($('jdrFrom').value) p.set('from', $('jdrFrom').value);
    if ($('jdrTo').value) p.set('to', $('jdrTo').value);
    if ($('jdrMine').checked) p.set('mine', '1');
    return p.toString();
  }

  function periodString() {
    const p = new URLSearchParams();
    if ($('jdrFrom').value) p.set('desde', $('jdrFrom').value);
    if ($('jdrTo').value) p.set('hasta', $('jdrTo').value);
    if (!$('jdrFrom').value && !$('jdrTo').value) p.set('dias', '90');
    if ($('jdrRecruiter').value) p.set('recruiter', $('jdrRecruiter').value);
    if ($('jdrMine').checked) p.set('mine', '1');
    return p.toString();
  }

  function refresh() {
    show($('jdrQueueLoading'), true);
    show($('jdrQueueWrap'), false);
    show($('jdrQueueEmpty'), false);
    fetch(`${API}/jd_reviews?${queryString()}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => { queueRows = d.reviews || []; renderQueue(); })
      .catch(err => {
        queueRows = [];
        $('jdrQueueBody').innerHTML = '';
        show($('jdrQueueLoading'), false);
        const empty = $('jdrQueueEmpty');
        empty.querySelector('h3').textContent = 'Could not load the queue';
        empty.querySelector('p').textContent = err.message;
        show(empty, true);
      });
    fetch(`${API}/jd_reviews/metrics?${periodString()}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(renderMetrics)
      .catch(err => {
        $('jdrMetrics').innerHTML = '';
        $('jdrMetricsEmpty').querySelector('p').textContent = `Could not load the metrics: ${err.message}`;
        show($('jdrMetricsEmpty'), true);
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
        $('jdrRecruiter').appendChild(o);
      });
    })
    .catch(() => {});

  const loadChecklistItems = () => fetch(`${API}/jd_reviews/checklist_items`, { headers: headers() })
    .then(r => r.ok ? r.json() : { items: [] })
    .then(d => {
      (d.items || []).forEach(x => { checklistLabels[x.code] = x.label; });
      renderChecklistChecks();
    })
    .catch(() => {});

  /* ------------------------------------------------------------------- init */

  document.addEventListener('DOMContentLoaded', () => {
    if (!ALLOWED.has(me)) { show($('jdrDenied'), true); return; }
    show($('jdrApp'), true);

    const isOversight = OVERSIGHT.has(me);
    $('jdrMine').checked = !isOversight;
    $('jdrMineLabel').textContent = isOversight ? 'Only mine' : 'Only my opportunities';
    if (deepReviewId) { $('jdrStatus').value = ''; $('jdrMine').checked = false; }

    const head = $('jdrMetricsToggle');
    const panel = $('jdrMetricsPanel');
    const toggle = () => {
      const open = panel.hidden;
      panel.hidden = !open;
      head.setAttribute('aria-expanded', String(open));
      head.classList.toggle('is-open', open);
    };
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); } });

    wireQueue();
    $('jdrSearch').addEventListener('input', renderQueue);
    $('jdrApply').addEventListener('click', refresh);
    $('jdrRefresh').addEventListener('click', refresh);
    ['jdrStatus', 'jdrMine'].forEach(id => $(id).addEventListener('change', refresh));

    $('jdrChecklist').addEventListener('change', () => {
      if (checklistPicks().length) $('jdrChecklistClean').checked = false;
      syncGate();
    });
    $('jdrChecklistClean').addEventListener('change', () => {
      if ($('jdrChecklistClean').checked) {
        $('jdrChecklist').querySelectorAll('input:checked').forEach(i => { i.checked = false; });
      }
      syncGate();
    });

    $('jdrApprove').addEventListener('click', () => decide('approved'));
    $('jdrChangesToggle').addEventListener('click', () => setMode('changes_requested'));
    $('jdrChangesCancel').addEventListener('click', () => setMode(null));
    $('jdrChangesConfirm').addEventListener('click', () => decide('changes_requested'));

    // Re-run: reusa la lista de puntos guardada (el score sólo se mueve si cambió la JD).
    // Rebuild: la vuelve a sacar de las reuniones; confirma porque el número puede moverse sólo
    // por eso. A Grain se le vuelve a pedir sólo si faltaba alguna grabación.
    const rerun = (rebuild) => {
      if (!currentReview) return;
      if (rebuild && !confirm('Read the calls again and build a new list of points?\n\n'
        + 'Every round of this opportunity will be re-scored against the new list, including '
        + 'rounds already decided, and your name will show on it. The score can change just '
        + 'because the AI groups the points differently. Do it only if the current list looks wrong.')) return;
      const btns = [$('jdrReanalyze'), $('jdrRebuild')];
      btns.forEach(b => { b.disabled = true; });
      $('jdrDrawerError').textContent = '';
      const id = currentReview.review_id;
      const t = currentReview.transcripts || {};
      const refetch = !((t.intro || {}).chars && (t.deep_dive || {}).chars);
      fetch(`${API}/jd_reviews/${id}/analyze`, {
        method: 'POST', headers: headers(), body: JSON.stringify({ refetch, rebuild }),
      })
        .then(async r => {
          const out = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(out.error || `HTTP ${r.status}`);
        })
        .then(() => loadReview(id))
        .catch(err => { $('jdrDrawerError').textContent = err.message; })
        .finally(() => { btns.forEach(b => { b.disabled = false; }); });
    };
    $('jdrReanalyze').addEventListener('click', () => rerun(false));
    $('jdrRebuild').addEventListener('click', () => rerun(true));

    $('jdrAi').addEventListener('click', ev => {
      const el = ev.target.closest('[data-hl]');
      if (el) hlGoTo(el.getAttribute('data-hl'));
    });
    $('jdrAi').addEventListener('keydown', ev => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      const el = ev.target.closest('[data-hl]');
      if (el) { ev.preventDefault(); hlGoTo(el.getAttribute('data-hl')); }
    });
    $('jdrHlSwitch').addEventListener('change', hlApply);

    $('jdrClose').addEventListener('click', closeDrawer);
    $('jdrScrim').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && $('jdrDrawer').classList.contains('is-open')) closeDrawer();
    });

    Promise.all([loadChecklistItems(), loadRecruiters()]).then(() => {
      refresh();
      if (deepReviewId) openDrawer(deepReviewId);
    });
  });
})();
