// ===== Helpers =====
const API = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

/** Normalize any string-ish value to lowercased, trimmed text. */
function norm(s){ return String(s || '').toLowerCase().trim(); }

/**
 * Exclude pipeline stages you do NOT want to count in aggregations.
 * Mirrors the visual table filters: deep dive, nda sent, close win/lost.
 */
function isStageExcluded(stage){
  const v = norm(stage);
  if (!v) return false;
  return /(deep\s*dive|nda\s*sent|close[ds]?\s*win|close[ds]?\s*lost)/i.test(v);
}

/** Map raw model to canonical bucket. */
function normalizeModel(modelRaw){
  const v = norm(modelRaw);
  if (!v) return null;
  if (v.includes('staff')) return 'staffing';
  if (v.includes('recru')) return 'recruiting';
  return null;
}

/** Map raw type to canonical bucket. */
function normalizeType(typeRaw){
  const v = norm(typeRaw);
  if (!v) return null;
  if (v.includes('new')) return 'new';
  if (v.includes('repl')) return 'replacement';
  return null;
}

/** Format money in whole dollars with US locale commas. */
function fmtMoney(v){
  const num = Number(v) || 0;
  return '$' + num.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

// ======= TSR/TSF History (Staffing) =======
// === Expected (Fee & Revenue) por modelo (Staffing / Recruiting) ===
/**
 * Aggregate expected fee & revenue by model, respecting pipeline exclusions.
 * @param {Array<Object>} opps
 * @returns {{staffing:{fee:number,revenue:number}, recruiting:{fee:number,revenue:number}}}
 */
function computeExpectedByModel(opps){
  const out = {
    staffing:   { fee: 0, revenue: 0 },
    recruiting: { fee: 0, revenue: 0 }
  };

  for (const o of opps){
    if (isStageExcluded(o.opp_stage)) continue; // same filter as pipeline

    const m = normalizeModel(o.opp_model);
    if (!m || !(m in out)) continue;

    const fee = Number(o.expected_fee);
    const rev = Number(o.expected_revenue);

    if (!Number.isNaN(fee)) out[m].fee += fee;
    if (!Number.isNaN(rev)) out[m].revenue += rev;
  }
  return out;
}

/**
 * Push KPI numbers into fixed DOM ids.
 */
function renderExpectedByModel(modelTotals){
  const map = [
    ['kpiExpectedFeeStaff', modelTotals.staffing.fee],
    ['kpiExpectedRevStaff', modelTotals.staffing.revenue],
    ['kpiExpectedRevRec',   modelTotals.recruiting.revenue],
  ];
  for (const [id, val] of map){
    const el = document.getElementById(id);
    if (el) el.textContent = fmtMoney(val);
  }
}

/**
 * Fetch TSR/TSF history. If no range is provided, defaults to the
 * last FULL 12 months (ending on the last day of the previous month).
 * @param {{fromYM?:string,toYM?:string}} [opts]
 */
async function fetchTSHistory({ fromYM = null, toYM = null } = {}) {
  const params = new URLSearchParams();
  if (fromYM) params.set('from', fromYM);
  if (toYM) params.set('to', toYM);

  if (!fromYM || !toYM) {
    // Build default range: last 12 full months
    const today = new Date();
    const firstOfThisMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    const lastFullMonth = new Date(firstOfThisMonth - 1);

    const toDefault = `${lastFullMonth.getFullYear()}-${String(lastFullMonth.getMonth() + 1).padStart(2, '0')}`;

    const fromAnchor = new Date(lastFullMonth);
    fromAnchor.setMonth(fromAnchor.getMonth() - 11);
    const fromDefault = `${fromAnchor.getFullYear()}-${String(fromAnchor.getMonth() + 1).padStart(2, '0')}`;

    if (!fromYM) params.set('from', fromDefault);
    if (!toYM) params.set('to', toDefault);
  }

  const url = `${API}/metrics/ts_history?${params.toString()}`;
  const r = await fetch(url, { credentials: 'include' });
  const arr = await r.json();
  return Array.isArray(arr) ? arr : [];
}

/**
 * Render TSR/TSF history table and SVG chart with a lightweight tooltip.
 * Uses custom SVG paths for performance and visual control.
 */
function renderTSHistory(data){
  const wrap   = document.getElementById('tsHistoryWrap');
  const tbl    = document.getElementById('tsHistoryTableBody');
  const svg    = document.getElementById('tsHistoryChart');
  const tip    = document.getElementById('tsTooltip');
  const legend = document.getElementById('tsLegend');
  if (!wrap || !tbl || !svg) return;

  // ---- Table ----
  tbl.innerHTML = '';
  for (const it of data){
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${it.month}</td>
      <td class="num">$${Number(it.tsr || 0).toLocaleString('en-US')}</td>
      <td class="num">$${Number(it.tsf || 0).toLocaleString('en-US')}</td>
      <td class="num">${it.active_count || 0}</td>
    `;
    tbl.appendChild(tr);
  }

  // ---- SVG setup ----
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const W = svg.viewBox.baseVal.width || 720;
  const H = svg.viewBox.baseVal.height || 220;
  const PAD = 36;

  const months  = data.map(d => d.month);
  const tsrVals = data.map(d => Number(d.tsr || 0));
  const tsfVals = data.map(d => Number(d.tsf || 0));
  const hires   = data.map(d => Number(d.active_count || 0));

  const maxY = Math.max(1, ...tsrVals, ...tsfVals);
  const n = Math.max(1, data.length);
  const x = i => PAD + (i * (W - 2*PAD)) / Math.max(1, n - 1);
  const y = v => H - PAD - (v * (H - 2*PAD)) / maxY;

  const fmtMoneyShort = (v) => {
    const num = Number(v) || 0;
    if (num >= 1_000_000) return '$' + (num/1_000_000).toFixed(1).replace(/\.0$/,'') + 'M';
    if (num >= 1_000)     return '$' + (num/1_000).toFixed(1).replace(/\.0$/,'') + 'k';
    return '$' + num.toLocaleString('en-US');
  };

  const el = (tag, attrs={}) => {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k,v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };

  // --- Defs: gradients ---
  const defs = el('defs');
  const gradTSR = el('linearGradient', { id:'gTSR', x1:'0', y1:'0', x2:'0', y2:'1' });
  gradTSR.append(el('stop', { offset:'0%',  'stop-color':'var(--tsr)', 'stop-opacity': '0.25'}));
  gradTSR.append(el('stop', { offset:'100%','stop-color':'var(--tsr)', 'stop-opacity': '0'}));
  const gradTSF = el('linearGradient', { id:'gTSF', x1:'0', y1:'0', x2:'0', y2:'1' });
  gradTSF.append(el('stop', { offset:'0%',  'stop-color':'var(--tsf)', 'stop-opacity': '0.25'}));
  gradTSF.append(el('stop', { offset:'100%','stop-color':'var(--tsf)', 'stop-opacity': '0'}));
  defs.append(gradTSR, gradTSF);
  svg.append(defs);

  // --- Grid Y (4 lines) + labels ---
  for (let g=0; g<=4; g++){
    const gy = PAD + g * (H - 2*PAD) / 4;
    svg.append(el('line', { x1: PAD, x2: W-PAD, y1: gy, y2: gy, stroke: 'var(--grid)', 'stroke-width':'1' }));
    const val = Math.round((1 - g/4) * maxY);
    const text = el('text', { x: 8, y: y(val) + 4, 'font-size':'10', fill:'var(--muted)' });
    text.textContent = fmtMoneyShort(val);
    svg.append(text);
  }

  // Helpers to build paths
  const pathFrom = (arr) => arr.map((v,i) => `${i?'L':'M'} ${x(i)} ${y(v)}`).join(' ');
  const areaFrom = (arr) => `${pathFrom(arr)} L ${x(n-1)} ${y(0)} L ${x(0)} ${y(0)} Z`;

  // Toggle state from legend (both on by default)
  const visibility = { tsr: true, tsf: true };

  const draw = () => {
    // wipe everything and rebuild (keeps logic simple for toggles)
    while (svg.childNodes.length) svg.removeChild(svg.lastChild);
    svg.append(defs);

    // grid + labels
    for (let g=0; g<=4; g++){
      const gy = PAD + g * (H - 2*PAD) / 4;
      svg.append(el('line', { x1: PAD, x2: W-PAD, y1: gy, y2: gy, stroke: 'var(--grid)', 'stroke-width':'1' }));
      const val = Math.round((1 - g/4) * maxY);
      const text = el('text', { x: 8, y: y(val) + 4, 'font-size':'10', fill:'var(--muted)' });
      text.textContent = fmtMoneyShort(val);
      svg.append(text);
    }

    // Areas
    if (visibility.tsr) svg.append(el('path', { d: areaFrom(tsrVals), fill: 'url(#gTSR)' }));
    if (visibility.tsf) svg.append(el('path', { d: areaFrom(tsfVals), fill: 'url(#gTSF)' }));

    // Lines
    if (visibility.tsr) svg.append(el('path', { d: pathFrom(tsrVals), fill:'none', stroke:'var(--tsr)', 'stroke-width':'2.5' }));
    if (visibility.tsf) svg.append(el('path', { d: pathFrom(tsfVals), fill:'none', stroke:'var(--tsf)', 'stroke-width':'2.5' }));

    // Points
    const pts = el('g', { id:'points' });
    for (let i=0;i<n;i++){
      if (visibility.tsr) pts.append(el('circle', { cx:x(i), cy:y(tsrVals[i]), r:'3.5', fill:'#fff', stroke:'var(--tsr)', 'stroke-width':'2' }));
      if (visibility.tsf) pts.append(el('circle', { cx:x(i), cy:y(tsfVals[i]), r:'3.5', fill:'#fff', stroke:'var(--tsf)', 'stroke-width':'2' }));
    }
    svg.append(pts);

    // Guide + hit area
    const guide = el('line', { id:'vGuide', x1:0, x2:0, y1:PAD-6, y2:H-PAD+6, stroke:'rgba(0,0,0,.25)', 'stroke-dasharray':'3 3', 'stroke-width':'1.2', opacity:'0' });
    svg.append(guide);

    const hit = el('rect', { x:PAD, y:0, width:(W-2*PAD), height:H, fill:'transparent', style:'cursor:crosshair' });
    svg.append(hit);

    // Tooltip helpers
    const showTip = (i, clientX, clientY) => {
      if (!tip || i < 0 || i >= n) return;

      const gx = x(i);
      guide.setAttribute('x1', gx);
      guide.setAttribute('x2', gx);
      guide.setAttribute('opacity', '1');

      const m = months[i];
      const tsr = tsrVals[i];
      const tsf = tsfVals[i];
      const act = hires[i];

      tip.innerHTML = `
        <div class="tt-title">${m}</div>
        <div class="row"><span class="badge"><span class="dot tsr"></span>TSR</span><span>${fmtMoneyShort(tsr)}</span></div>
        <div class="row"><span class="badge"><span class="dot tsf"></span>TSF</span><span>${fmtMoneyShort(tsf)}</span></div>
        <div class="muted">Active hires: ${act}</div>
      `;
      tip.style.display = 'block';

      // convert viewbox coords → pixels
      const svgRect  = svg.getBoundingClientRect();
      const wrapRect = wrap.getBoundingClientRect();
      const sx = svgRect.width  / W;
      const sy = svgRect.height / H;

      const px = x(i) * sx + (svgRect.left - wrapRect.left);

      const ys = [];
      if (visibility.tsr) ys.push(y(tsrVals[i]) * sy);
      if (visibility.tsf) ys.push(y(tsfVals[i]) * sy);
      if (!ys.length) ys.push(y(0) * sy);

      const pYsvg = Math.min(...ys);
      const py    = pYsvg + (svgRect.top - wrapRect.top);

      const margin = 12;
      const leftClamped = Math.max(margin, Math.min(px, wrapRect.width - margin));

      const willOverflowTop = (py - tip.offsetHeight - 16) < 0;
      tip.classList.toggle('below', willOverflowTop);

      tip.style.left = `${leftClamped}px`;
      tip.style.top  = `${py}px`;
    };

    const hideTip = () => {
      guide.setAttribute('opacity', '0');
      if (tip){ tip.style.display = 'none'; tip.classList.remove('below'); }
    };

    // nearest index by x in pixels
    const nearestIndex = (px) => {
      const rel = Math.max(PAD, Math.min(px, W-PAD));
      const t = (rel - PAD) / Math.max(1, (W - 2*PAD));
      return Math.round(t * (n - 1));
    };

    // Pointer events
    hit.addEventListener('mousemove', (e) => {
      const rect = svg.getBoundingClientRect();
      const i = nearestIndex(e.clientX - rect.left);
      showTip(i, e.clientX, e.clientY);
    });
    hit.addEventListener('mouseleave', hideTip);

    // Touch events
    hit.addEventListener('touchstart', (e) => {
      const t = e.touches[0];
      const rect = svg.getBoundingClientRect();
      const i = nearestIndex(t.clientX - rect.left);
      showTip(i, t.clientX, t.clientY);
    }, {passive:true});
    hit.addEventListener('touchmove', (e) => {
      const t = e.touches[0];
      const rect = svg.getBoundingClientRect();
      const i = nearestIndex(t.clientX - rect.left);
      showTip(i, t.clientX, t.clientY);
    }, {passive:true});
    hit.addEventListener('touchend', hideTip);
  };

  // Legend toggles
  if (legend){
    legend.querySelectorAll('.legend-item').forEach(btn => {
      btn.onclick = () => {
        const key = btn.getAttribute('data-series');
        if (!key) return;
        const next = !btn.classList.contains('on');
        // sync state
        btn.classList.toggle('off', !next);
        btn.classList.toggle('on',  next);
        // reflect in visibility, then redraw
        if (key in { tsr:1, tsf:1 }){
          // recompute from DOM state to avoid drift
          const tsrOn = !!legend.querySelector('[data-series="tsr"].on');
          const tsfOn = !!legend.querySelector('[data-series="tsf"].on');
          visibility.tsr = tsrOn; visibility.tsf = tsfOn;
          draw();
        }
      };
    });
  }

  draw();

  // Month labels (start & end only to keep it clean)
  if (data.length){
    const mkText = (txt, px) => {
      const t = document.createElementNS('http://www.w3.org/2000/svg','text');
      t.setAttribute('x', px); t.setAttribute('y', H - 10);
      t.setAttribute('font-size', '10');
      t.setAttribute('text-anchor', 'middle');
      t.setAttribute('fill', 'var(--muted)');
      t.textContent = txt;
      return t;
    };
    svg.append(mkText(data[0].month, x(0)));
    svg.append(mkText(data[data.length-1].month, x(data.length-1)));
  }
}

// ===== Data fetchers =====
async function fetchOpportunitiesLight(){
  const r = await fetch(`${API}/opportunities/light`, { credentials:'include' });
  const arr = await r.json();
  return Array.isArray(arr) ? arr : [];
}

async function fetchAccountsLight(){
  // tsr/tsf by account (SQL already separated by model)
  const r = await fetch(`${API}/data/light`, { credentials:'include' });
  const arr = await r.json();
  return Array.isArray(arr) ? arr : [];
}

// ===== Render Tabla Oportunidades =====
function buildEmptyMatrix(){
  return {
    staffing: { new: 0, replacement: 0 },
    recruiting: { new: 0, replacement: 0 }
  };
}

/**
 * Count opportunities by (model × type) with pipeline stage exclusions.
 */
function computeMatrix(opps){
  const M = buildEmptyMatrix();
  for (const o of opps){
    if (isStageExcluded(o.opp_stage)) continue;

    const m = normalizeModel(o.opp_model);
    const t = normalizeType(o.opp_type);

    if (!m || !t) continue;
    if (!(m in M) || !(t in M[m])) continue;

    M[m][t] += 1;
  }
  return M;
}

/**
 * Render the (model × type) matrix table using an existing row template.
 * Adds a `.pill` span around totals without altering surrounding markup.
 */
function renderTable(matrix){
  const tbody = document.getElementById('oppsTbody');
  const tpl   = document.getElementById('rowTemplate');
  if (!tbody || !tpl) return;

  tbody.innerHTML = '';

  const rows = [
    ['Staffing', 'staffing'],
    ['Recruiting', 'recruiting']
  ];

  let colNew = 0, colRep = 0, grand = 0;

  for (const [label, key] of rows){
    const clone = tpl.content.cloneNode(true);
    const tr = clone.querySelector('tr');

    tr.querySelector('.row-head').textContent = label;

    const newVal = matrix[key].new || 0;
    const repVal = matrix[key].replacement || 0;
    const rowTotal = newVal + repVal;

    tr.querySelector('[data-key="new"]').textContent = newVal;
    tr.querySelector('[data-key="replacement"]').textContent = repVal;
    tr.querySelector('.row-total-val').textContent = rowTotal;

    // wrap totals with a pill (idempotent)
    const totalCell = tr.querySelector('.row-total-val');
    if (totalCell && !totalCell.querySelector('.pill')){
      totalCell.innerHTML = `<span class="pill">${totalCell.textContent}</span>`;
    }

    tbody.appendChild(tr);

    colNew += newVal;
    colRep += repVal;
    grand  += rowTotal;
  }

  // Footer totals
  const ids = ['colTotalNew','colTotalReplacement','grandTotal'];
  const vals = [colNew, colRep, grand];
  ids.forEach((id, i) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = String(vals[i]);
    if (!el.querySelector('.pill')) el.innerHTML = `<span class="pill">${el.textContent}</span>`;
  });
}

// ===== Render MRR (Solo Staffing) =====
function renderMRRFromAccounts(accounts){
  let totalTSR = 0;
  let totalTSF = 0;

  for (const a of accounts){
    totalTSR += Number(a.tsr || 0);
    totalTSF += Number(a.tsf || 0);
  }

  const elTSR = document.getElementById('kpiTSR');
  const elTSF = document.getElementById('kpiTSF');
  if (elTSR) elTSR.textContent = fmtMoney(totalTSR);
  if (elTSF) elTSF.textContent = fmtMoney(totalTSF);
}

// ===== Orchestración =====
async function loadTSHistorySection(){
  try {
    const data = await fetchTSHistory();
    renderTSHistory(data);
  } catch (e){
    console.warn('TS history error:', e);
  }
}

async function loadDashboard(){
  try{
    document.body.classList.add('loading');

    // 1) Opportunities table
    const opps = await fetchOpportunitiesLight();
    const matrix = computeMatrix(opps);
    renderTable(matrix);

    // 1.b) Expected Fee/Revenue (pipeline filters)
    const expectedByModel = computeExpectedByModel(opps);
    renderExpectedByModel(expectedByModel);

    // 2) MRR from accounts
    const accounts = await fetchAccountsLight();
    renderMRRFromAccounts(accounts);
  }catch(e){
    console.warn('Dashboard load error:', e);
  }finally{
    document.body.classList.remove('loading');
  }
}

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
  loadDashboard();
  loadTSHistorySection();
  document.getElementById('refreshBtn')?.addEventListener('click', () => {
    loadDashboard();
    loadTSHistorySection();
  });
});