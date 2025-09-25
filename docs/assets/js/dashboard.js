// ===== Helpers =====
const API = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
// ======= TSR/TSF History (Staffing) =======
async function fetchTSHistory({ fromYM = null, toYM = null } = {}) {
  const params = new URLSearchParams();
  if (fromYM) params.set('from', fromYM);
  if (toYM) params.set('to', toYM);

  // Por defecto: últimos 12 meses completos (hasta último mes completo)
  if (!fromYM || !toYM) {
    const today = new Date();
    const firstOfThisMonth = new Date(today.getFullYear(), today.getMonth(), 1);
    const lastFullMonth = new Date(firstOfThisMonth - 1); // último día del mes pasado
    const toY = lastFullMonth.getFullYear();
    const toM = String(lastFullMonth.getMonth() + 1).padStart(2, '0');
    const toDefault = `${toY}-${toM}`;

    const fromAnchor = new Date(lastFullMonth);
    fromAnchor.setMonth(fromAnchor.getMonth() - 11); // 12 meses
    const fromY = fromAnchor.getFullYear();
    const fromM = String(fromAnchor.getMonth() + 1).padStart(2, '0');
    const fromDefault = `${fromY}-${fromM}`;

    if (!fromYM) params.set('from', fromDefault);
    if (!toYM) params.set('to', toDefault);
  }

  const url = `${API}/metrics/ts_history?${params.toString()}`;
  const r = await fetch(url, { credentials: 'include' });
  const arr = await r.json();
  return Array.isArray(arr) ? arr : [];
}

function renderTSHistory(data){
  const wrap = document.getElementById('tsHistoryWrap');
  const tbl  = document.getElementById('tsHistoryTableBody');
  const svg  = document.getElementById('tsHistoryChart');
  const tip  = document.getElementById('tsTooltip');
  const legend = document.getElementById('tsLegend');
  if (!wrap || !tbl || !svg) return;

  // ---- Tabla ----
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

  const months = data.map(d => d.month);
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
    if (num >= 1_000) return '$' + (num/1_000).toFixed(1).replace(/\.0$/,'') + 'k';
    return '$' + num.toLocaleString('en-US');
  };

  const el = (tag, attrs={}) => {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [k,v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };

  // --- Defs: gradients y filtros suaves ---
  const defs = el('defs');
  const gradTSR = el('linearGradient', { id:'gTSR', x1:'0', y1:'0', x2:'0', y2:'1' });
  gradTSR.append(el('stop', { offset:'0%',  'stop-color':'var(--tsr)', 'stop-opacity': '0.25'}));
  gradTSR.append(el('stop', { offset:'100%','stop-color':'var(--tsr)', 'stop-opacity': '0'}));
  const gradTSF = el('linearGradient', { id:'gTSF', x1:'0', y1:'0', x2:'0', y2:'1' });
  gradTSF.append(el('stop', { offset:'0%',  'stop-color':'var(--tsf)', 'stop-opacity': '0.25'}));
  gradTSF.append(el('stop', { offset:'100%','stop-color':'var(--tsf)', 'stop-opacity': '0'}));
  defs.append(gradTSR, gradTSF);
  svg.append(defs);

  // --- Grid Y (4 líneas) + ejes mínimos ---
  for (let g=0; g<=4; g++){
    const gy = PAD + g * (H - 2*PAD) / 4;
    const line = el('line', { x1: PAD, x2: W-PAD, y1: gy, y2: gy, stroke: 'var(--grid)', 'stroke-width':'1' });
    svg.append(line);
    // etiquetas eje Y a la izquierda (0, 25%, 50%, 75%, 100%)
    const val = Math.round((1 - g/4) * maxY);
    const text = el('text', { x: 8, y: y(val) + 4, 'font-size':'10', fill:'var(--muted)' });
    text.textContent = fmtMoneyShort(val);
    svg.append(text);
  }

  // --- Helpers path ---
  const pathFrom = (arr) => arr.map((v,i) => `${i?'L':'M'} ${x(i)} ${y(v)}`).join(' ');
  const areaFrom = (arr) => `${pathFrom(arr)} L ${x(n-1)} ${y(0)} L ${x(0)} ${y(0)} Z`;

  // --- Series visibles (toggle legend) ---
  const visibility = { tsr: true, tsf: true };

  // --- Draw function (idempotente) ---
  const draw = () => {
    // limpia todo excepto defs y grid/labels ya insertados (dejamos los primeros elementos hasta defs y 10 objetos aprox)
    const keep = 1 + 5 + 5; // defs + grid lines + y labels (aprox) – por simplicidad, reconstruimos completo:
    while (svg.childNodes.length > 0) svg.removeChild(svg.lastChild);
    svg.append(defs);
    // redibuja grid y labels Y
    for (let g=0; g<=4; g++){
      const gy = PAD + g * (H - 2*PAD) / 4;
      svg.append(el('line', { x1: PAD, x2: W-PAD, y1: gy, y2: gy, stroke: 'var(--grid)', 'stroke-width':'1' }));
      const val = Math.round((1 - g/4) * maxY);
      const text = el('text', { x: 8, y: y(val) + 4, 'font-size':'10', fill:'var(--muted)' });
      text.textContent = fmtMoneyShort(val);
      svg.append(text);
    }

    // Áreas
    if (visibility.tsr){
      const a1 = el('path', { d: areaFrom(tsrVals), fill: 'url(#gTSR)' });
      svg.append(a1);
    }
    if (visibility.tsf){
      const a2 = el('path', { d: areaFrom(tsfVals), fill: 'url(#gTSF)' });
      svg.append(a2);
    }

    // Líneas
    if (visibility.tsr){
      svg.append(el('path', { d: pathFrom(tsrVals), fill:'none', stroke:'var(--tsr)', 'stroke-width':'2.5' }));
    }
    if (visibility.tsf){
      svg.append(el('path', { d: pathFrom(tsfVals), fill:'none', stroke:'var(--tsf)', 'stroke-width':'2.5' }));
    }

    // Puntos
    const pts = el('g', { id:'points' });
    for (let i=0;i<n;i++){
      if (visibility.tsr){
        pts.append(el('circle', { cx:x(i), cy:y(tsrVals[i]), r:'3.5', fill:'#fff', stroke:'var(--tsr)', 'stroke-width':'2' }));
      }
      if (visibility.tsf){
        pts.append(el('circle', { cx:x(i), cy:y(tsfVals[i]), r:'3.5', fill:'#fff', stroke:'var(--tsf)', 'stroke-width':'2' }));
      }
    }
    svg.append(pts);

    // Guía vertical + hit-area
    const guide = el('line', { id:'vGuide', x1:0, x2:0, y1:PAD-6, y2:H-PAD+6, stroke:'rgba(0,0,0,.25)', 'stroke-dasharray':'3 3', 'stroke-width':'1.2', opacity:'0' });
    svg.append(guide);

    const hit = el('rect', { x:PAD, y:0, width:(W-2*PAD), height:H, fill:'transparent', style:'cursor:crosshair' });
    svg.append(hit);

// reemplaza la función showTip por esta versión
  const showTip = (i, clientX, clientY) => {
    if (i < 0 || i >= n) return;

    // 1) Actualiza la guía vertical
    const gx = x(i);
    guide.setAttribute('x1', gx);
    guide.setAttribute('x2', gx);
    guide.setAttribute('opacity', '1');

    // 2) Contenido del tooltip
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

    // 3) Convertir coords del SVG (viewBox) a pixels reales
    const svgRect  = svg.getBoundingClientRect();
    const wrapRect = wrap.getBoundingClientRect();
    const sx = svgRect.width  / W;
    const sy = svgRect.height / H;

    // x de ese índice
    const px = x(i) * sx + (svgRect.left - wrapRect.left);

    // y según las series visibles (tomamos el punto más “alto”, o sea menor y)
    const ys = [];
    if (visibility.tsr) ys.push(y(tsrVals[i]) * sy);
    if (visibility.tsf) ys.push(y(tsfVals[i]) * sy);
    // fallback por si ambas están ocultas
    if (!ys.length) ys.push(y(0) * sy);

    const pYsvg   = Math.min(...ys);
    const py      = pYsvg + (svgRect.top - wrapRect.top);

    // 4) Clamp dentro del card y decidir si va arriba o abajo del punto
    const margin = 12;
    const leftClamped = Math.max(margin, Math.min(px, wrapRect.width - margin));

    // Si el punto está muy arriba, mostramos el tooltip por debajo
    // medimos altura después de display:block para decidir
    const willOverflowTop = (py - tip.offsetHeight - 16) < 0;
    tip.classList.toggle('below', willOverflowTop);

    // 5) Posicionar
    tip.style.left = `${leftClamped}px`;
    tip.style.top  = `${py}px`;
  };

  const hideTip = () => {
    guide.setAttribute('opacity', '0');
    tip.style.display = 'none';
    tip.classList.remove('below');
  };


    // índice más cercano para un x dado
    const nearestIndex = (px) => {
      const rel = Math.max(PAD, Math.min(px, W-PAD));
      const t = (rel - PAD) / Math.max(1, (W - 2*PAD));
      return Math.round(t * (n - 1));
    };

    // Eventos hover
    hit.addEventListener('mousemove', (e) => {
      const rect = svg.getBoundingClientRect();
      const i = nearestIndex(e.clientX - rect.left);
      showTip(i, e.clientX, e.clientY);
    });
    hit.addEventListener('mouseleave', hideTip);
    // también para touch
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

  // ---- Leyenda: toggle series ----
  if (legend){
    legend.querySelectorAll('.legend-item').forEach(btn => {
      btn.onclick = () => {
        const key = btn.getAttribute('data-series');
        visibility[key] = !visibility[key];
        btn.classList.toggle('off', !visibility[key]);
        btn.classList.toggle('on',  visibility[key]);
        draw();
      };
    });
  }

  // Dibuja inicial
  draw();

  // Etiquetas de extremos (mes inicial/final)
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

async function loadTSHistorySection(){
  try {
    const data = await fetchTSHistory(); // últimos 12 meses completos
    renderTSHistory(data);
  } catch (e){
    console.warn('TS history error:', e);
  }
}

function norm(s){ return String(s || '').toLowerCase().trim(); }

// Normaliza stage a categorías y excluye las que no contamos
function isStageExcluded(stage){
  const v = norm(stage);
  if (!v) return false;
  // excluye deep dive, nda sent, close win, close lost
  return /(deep\s*dive|nda\s*sent|close[ds]?\s*win|close[ds]?\s*lost)/i.test(v);
}

// Normaliza opp_model → 'staffing' | 'recruiting' | null
function normalizeModel(modelRaw){
  const v = norm(modelRaw);
  if (!v) return null;
  if (v.includes('staff')) return 'staffing';
  if (v.includes('recru')) return 'recruiting';
  return null;
}

// Normaliza opp_type → 'new' | 'replacement' | null
function normalizeType(typeRaw){
  const v = norm(typeRaw);
  if (!v) return null;
  if (v.includes('new')) return 'new';
  if (v.includes('repl')) return 'replacement';
  return null;
}

function fmtMoney(v){
  const num = Number(v) || 0;
  return '$' + num.toLocaleString('en-US', { maximumFractionDigits: 0 });
}
// === Expected (Fee & Revenue) usando filtros del pipeline ===
function computeExpectedTotals(opps){
  let sumFee = 0;
  let sumRevenue = 0;

  for (const o of opps){
    // mismo filtro que la tabla de pipeline
    if (isStageExcluded(o.opp_stage)) continue;

    const fee = Number(o.expected_fee);
    const rev = Number(o.expected_revenue);

    if (!Number.isNaN(fee)) sumFee += fee;
    if (!Number.isNaN(rev)) sumRevenue += rev;
  }
  return { sumFee, sumRevenue };
}

function renderExpectedCard({ sumFee, sumRevenue }){
  const elFee = document.getElementById('kpiExpectedFee');
  const elRev = document.getElementById('kpiExpectedRevenue');
  if (!elFee || !elRev) return;

  elFee.textContent = fmtMoney(sumFee);
  elRev.textContent = fmtMoney(sumRevenue);
}

// ===== Data =====
async function fetchOpportunitiesLight(){
  const r = await fetch(`${API}/opportunities/light`, { credentials:'include' });
  const arr = await r.json();
  return Array.isArray(arr) ? arr : [];
}

async function fetchAccountsLight(){
  // trae tsr/tsf por account; tu SQL ya separa por modelo
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

function computeMatrix(opps){
  const M = buildEmptyMatrix();
  for (const o of opps){
    if (isStageExcluded(o.opp_stage)) continue;

    const m = normalizeModel(o.opp_model);
    const t = normalizeType(o.opp_type);

    if (!m || !t) continue;
    if (!(m in M)) continue;
    if (!(t in M[m])) continue;

    M[m][t] += 1;
  }
  return M;
}

function renderTable(matrix){
  const tbody = document.getElementById('oppsTbody');
  const tpl = document.getElementById('rowTemplate');

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
// envolver valores en <span class="pill"> sin tocar el HTML base
const totalCell = tr.querySelector('.row-total-val');
totalCell.innerHTML = `<span class="pill">${totalCell.textContent}</span>`;

    tbody.appendChild(tr);

    colNew += newVal;
    colRep += repVal;
    grand += rowTotal;
  }

  document.getElementById('colTotalNew').textContent = colNew;
  document.getElementById('colTotalReplacement').textContent = colRep;
  document.getElementById('grandTotal').textContent = grand;
  // aplicar pill a totales de columnas del tfoot
['colTotalNew','colTotalReplacement','grandTotal'].forEach(id => {
  const el = document.getElementById(id);
  if (el && !el.querySelector('.pill')) {
    el.innerHTML = `<span class="pill">${el.textContent}</span>`;
  }
});

}

// ===== Render MRR (Solo Staffing) =====
function renderMRRFromAccounts(accounts){
  // Tus campos por cuenta:
  //  - tsr: suma salaries de Staffing (revenue)
  //  - tsf: suma fees de Staffing
  // Sumamos globalmente:
  let totalTSR = 0;
  let totalTSF = 0;

  for (const a of accounts){
    totalTSR += Number(a.tsr || 0);
    totalTSF += Number(a.tsf || 0);
  }
  document.getElementById('kpiTSR').textContent = fmtMoney(totalTSR);
  document.getElementById('kpiTSF').textContent = fmtMoney(totalTSF);
}

// ===== Orquestación =====
async function loadDashboard(){
  try{
    document.body.classList.add('loading');

    // 1) Tabla (desde opportunities/light)
    const opps = await fetchOpportunitiesLight();
    const matrix = computeMatrix(opps);
    renderTable(matrix);

    // 1.b) Expected Fee / Expected Revenue (mismos filtros del pipeline)
    const expectedTotals = computeExpectedTotals(opps);
    renderExpectedCard(expectedTotals);

    // 2) MRR (desde data/light)
    const accounts = await fetchAccountsLight();
    renderMRRFromAccounts(accounts);
  }catch(e){
    console.warn('Dashboard load error:', e);
  }finally{
    document.body.classList.remove('loading');
  }
}


document.addEventListener('DOMContentLoaded', () => {
  loadDashboard();
  loadTSHistorySection(); // ← ¡esta faltaba!
  document.getElementById('refreshBtn')?.addEventListener('click', () => {
    loadDashboard();
    loadTSHistorySection(); // opcional: refrescar también el histórico
  });
});