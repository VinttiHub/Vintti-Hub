/* =============================================================
   Metrics tab — opportunity-detail
   Equivalente al overview de Hirex, con los datos del schema viejo:
   pipeline (opportunity_candidates), presentaciones (batch +
   candidates_batches) y applicants del formulario público.

   Se auto-cablea al botón "Metrics" en vez de tocar el switch de
   pestañas de opportunity-detail.js (que empareja tabs y secciones
   por índice). Todo vive en un IIFE para no depender del orden de
   carga de los otros scripts.
   ============================================================= */
(function () {
  const API_BASE =
    (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
      ? 'http://127.0.0.1:5000'
      : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  const $ = (id) => document.getElementById(id);

  function oppId() {
    const el = $('opportunity-id-text');
    const fromDataset = (el?.getAttribute('data-id') || '').trim();
    if (fromDataset && fromDataset !== '—') return fromDataset;
    const fromQS = new URLSearchParams(location.search).get('id');
    if (fromQS) return fromQS;
    const fromText = (el?.textContent || '').trim();
    return fromText && fromText !== '—' ? fromText : '';
  }

  const esc = (s) =>
    String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // Las fechas vienen como 'YYYY-MM-DD'; new Date() sobre ese string las
  // interpreta en UTC y en AR/US se corren un día. Se parsea a mano.
  function parseDay(iso) {
    if (!iso) return null;
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso));
    if (!m) return null;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  }
  const fmtDay = (iso, opts) => {
    const d = parseDay(iso);
    return d ? d.toLocaleDateString('en-US', opts || { year: 'numeric', month: 'short', day: 'numeric' }) : '—';
  };
  const daysBetween = (a, b) =>
    Math.max(0, Math.round((b.getTime() - a.getTime()) / 86400000));

  const SOURCE_LABEL = {
    linkedin: 'LinkedIn',
    turbo: 'Turbo',
    referido: 'Referral',
    talentum: 'Talentum',
    'other recruitment tool': 'Other recruitment tool',
    unknown: 'Not set',
  };

  let loaded = false;
  let loading = false;

  /* ---------------------------------------------------------- render */

  function kpi(big, label, sub) {
    return `<div class="om-card om-kpi">
      <div class="om-big">${big}</div>
      <div class="om-label">${esc(label)}</div>
      ${sub ? `<div class="om-sub">${sub}</div>` : ''}
    </div>`;
  }

  function barRow(label, count, max, color) {
    const pct = max > 0 ? (count / max) * 100 : 0;
    return `<div class="om-bar-row">
      <span class="om-bar-label">${color ? `<span class="om-dot" style="background:${color}"></span>` : ''}${esc(label)}</span>
      <span class="om-bar"><span style="width:${pct.toFixed(1)}%${color ? `;background:${color}` : ''}"></span></span>
      <span class="om-bar-n">${count}</span>
    </div>`;
  }

  function bars(rows, emptyText) {
    if (!rows.length) return `<p class="om-none">${esc(emptyText)}</p>`;
    const max = Math.max(1, ...rows.map((r) => r.count));
    return `<div class="om-bars">${rows.map((r) => barRow(r.label, r.count, max, r.color)).join('')}</div>`;
  }

  function durationKpi(o) {
    const start = parseDay(o.started_at);
    if (!start) return kpi('—', 'Process duration', 'No start date yet');
    const end = parseDay(o.closed_at) || new Date();
    const days = daysBetween(start, end);
    const big = `${days}<span class="om-unit">day${days === 1 ? '' : 's'}</span>`;
    const sub = o.closed_at
      ? `${esc(o.stage || 'Closed')} · closed ${fmtDay(o.closed_at)}`
      : `Open since ${fmtDay(o.started_at)}`;
    return kpi(big, 'Process duration', sub);
  }

  function batchChart(batches) {
    if (!batches.length) {
      return `<div class="om-card">
        <h4>Candidates presented · by batch</h4>
        <p class="om-none">No batches presented yet.</p>
      </div>`;
    }
    const max = Math.max(1, ...batches.map((b) => b.count));
    // Con pocos batches entra la fecha bajo cada barra; con muchos se apiñan y
    // se cae al pie con el rango (primera → última presentación).
    const perBarLabels = batches.length <= 8;

    const chart = batches.map((b) => {
      const when = b.presentation_date
        ? fmtDay(b.presentation_date, { month: 'short', day: 'numeric' })
        : 'No date';
      const pct = (b.count / max) * 100;
      // El número va dentro de la barra si hay lugar; si no, flotando justo
      // encima. Antes solo existía en el `title`, o sea el tooltip del sistema.
      const inside = pct >= 34;
      const label = inside
        ? `<b class="om-chart-val is-in">${b.count}</b>`
        : `<b class="om-chart-val is-out" style="bottom:calc(${pct.toFixed(1)}% + 7px)">${b.count}</b>`;

      return `<div class="om-chart-col">
        <span class="om-chart-bar">
          <span class="om-chart-fill" style="height:${pct.toFixed(1)}%">${inside ? label : ''}</span>
          ${inside ? '' : label}
          <span class="om-chart-tip" role="tooltip">
            <b>${b.count} candidate${b.count === 1 ? '' : 's'}</b>
            <i>Batch ${esc(b.batch_number)} · ${esc(when)}</i>
          </span>
        </span>
        ${perBarLabels ? `<span class="om-chart-x">${esc(when)}</span>` : ''}
      </div>`;
    }).join('');

    let foot = '';
    if (!perBarLabels) {
      const when = (b) => (b.presentation_date
        ? fmtDay(b.presentation_date, { month: 'short', day: 'numeric' })
        : `Batch ${b.batch_number}`);
      foot = `<div class="om-chart-foot">
        <span>${esc(when(batches[0]))}</span>
        <span>${esc(when(batches[batches.length - 1]))}</span>
      </div>`;
    }

    return `<div class="om-card">
      <h4>Candidates presented · by batch</h4>
      <div class="om-chart">${chart}</div>
      ${foot}
    </div>`;
  }

  function render(data) {
    const body = $('om-body');
    if (!body) return;

    const o = data.opportunity || {};
    const t = data.totals || {};
    const ap = data.applicants || {};

    const pipeline = t.pipeline || 0;
    const presented = t.presented || 0;

    const presentedRate = pipeline > 0 ? Math.round((presented / pipeline) * 100) : null;

    const kpis =
      kpi(pipeline, 'Candidates in pipeline',
        `<b>${presented}</b> presented${presentedRate != null ? ` · ${presentedRate}% of the pipeline` : ''}`)
      + durationKpi(o)
      + kpi(presented, 'Presented to client',
        `${t.batches || 0} batch${(t.batches || 0) === 1 ? '' : 'es'}`);

    // Los applicants existen solo si la opp tuvo link público, así que la
    // tarjeta aparece únicamente cuando hay datos reales.
    const applicantsKpi = (ap.total || 0) > 0
      ? kpi(ap.total, 'Applicants (public form)',
          ap.avg_score != null
            ? `Avg match <b>${ap.avg_score}</b>/10 · ${ap.scored || 0} scored`
            : 'No AI scoring yet')
      : '';

    const stageRows = (data.by_stage || []).map((s) => ({
      label: s.label, count: s.count, color: s.color,
    }));
    const sourceRows = (data.by_source || []).map((s) => ({
      label: SOURCE_LABEL[String(s.label || '').toLowerCase()] || s.label,
      count: s.count,
    }));
    // Los outcomes vienen siempre completos (los nueve del dropdown, aunque
    // estén en cero), así que el "no hay nada" hay que mirarlo por la suma.
    const statusRows = (data.by_batch_status || []).map((s) => ({
      label: s.label, count: s.count, color: s.color,
    }));
    const hasOutcomes = statusRows.some((s) => s.count > 0);

    body.innerHTML = `
      <div class="om-section">
        <h3>Opportunity performance</h3>
        <div class="om-kpis">${kpis}${applicantsKpi}</div>
        ${batchChart(data.batches || [])}
      </div>

      <div class="om-section">
        <h3>Candidate pipeline</h3>
        <div class="om-grid2">
          <div class="om-card">
            <h4>By stage</h4>
            ${bars(stageRows, 'No candidates in the pipeline yet.')}
          </div>
          <div class="om-card">
            <h4>Sources</h4>
            ${bars(sourceRows, 'No source data yet.')}
          </div>
        </div>
      </div>

      <div class="om-section">
        <h3>Batch outcomes</h3>
        <div class="om-card">
          <h4>Candidate status</h4>
          ${hasOutcomes ? bars(statusRows, '') : '<p class="om-none">No candidate has a batch status yet.</p>'}
        </div>
      </div>`;
  }

  /* ---------------------------------------------------------- load */

  async function load(force) {
    if (loading) return;
    if (loaded && !force) return;

    const body = $('om-body');
    if (!body) return;

    const id = oppId();
    if (!id) {
      body.innerHTML = `<div class="om-state"><p>Couldn't tell which opportunity this is.</p></div>`;
      return;
    }

    loading = true;
    const btn = $('om-refresh-btn');
    if (btn) btn.disabled = true;
    body.innerHTML = `<div class="om-state"><div class="om-spinner"></div><p>Loading metrics…</p></div>`;

    // Sin timeout, un fetch que nunca resuelve deja el spinner girando para
    // siempre y no queda ni un rastro de por qué. El AbortController lo corta.
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 20000);

    try {
      const url = `${API_BASE}/opportunities/${encodeURIComponent(id)}/metrics`;
      const res = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status} — ${url}`);
      render(await res.json());
      loaded = true;
    } catch (err) {
      const detail = err && err.name === 'AbortError'
        ? `The request to ${API_BASE} timed out after 20s.`
        : `${(err && err.message) || err}`;
      console.error('❌ metrics:', err);
      body.innerHTML = `<div class="om-state">
        <p>Couldn't load the metrics for this opportunity.</p>
        <p class="om-state-detail">${esc(detail)}</p>
        <button type="button" class="om-refresh-btn" id="om-retry-btn">Try again</button>
      </div>`;
      $('om-retry-btn')?.addEventListener('click', () => load(true));
    } finally {
      clearTimeout(timer);
      loading = false;
      if (btn) btn.disabled = false;
    }
  }

  function init() {
    const tab = Array.from(document.querySelectorAll('.nav-item'))
      .find((t) => t.textContent.trim() === 'Metrics');
    if (tab) tab.addEventListener('click', () => load(false));

    $('om-refresh-btn')?.addEventListener('click', () => load(true));

    // Si se entra directo con #metrics en la URL.
    if (location.hash === '#metrics') setTimeout(() => tab?.click(), 0);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
