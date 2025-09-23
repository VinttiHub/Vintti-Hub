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
  if (!wrap || !tbl) return;

  // -------- Tabla --------
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

  // -------- Mini chart (SVG doble línea TSR/TSF) --------
  const svg = document.getElementById('tsHistoryChart');
  if (!svg) return;
  // limpia
  while (svg.firstChild) svg.removeChild(svg.firstChild);

  const W = svg.viewBox.baseVal.width || 640;
  const H = svg.viewBox.baseVal.height || 180;
  const PAD = 24;

  const xs = data.map((_, i) => i);
  const tsr = data.map(d => Number(d.tsr || 0));
  const tsf = data.map(d => Number(d.tsf || 0));
  const maxY = Math.max(1, ...tsr, ...tsf);

  const x = i => PAD + (i * (W - 2*PAD)) / Math.max(1, data.length - 1);
  const y = v => H - PAD - (v * (H - 2*PAD)) / maxY;

  function makePath(values){
    return values.map((v,i) => `${i ? 'L' : 'M'} ${x(i)} ${y(v)}`).join(' ');
  }

  // grid horizontal (3 líneas)
  for (let g=0; g<=3; g++){
    const gy = PAD + g * (H - 2*PAD) / 3;
    const line = document.createElementNS('http://www.w3.org/2000/svg','line');
    line.setAttribute('x1', PAD); line.setAttribute('x2', W-PAD);
    line.setAttribute('y1', gy);  line.setAttribute('y2', gy);
    line.setAttribute('stroke', 'rgba(0,0,0,.08)');
    line.setAttribute('stroke-width', '1');
    svg.appendChild(line);
  }

  // TSR line
  const p1 = document.createElementNS('http://www.w3.org/2000/svg','path');
  p1.setAttribute('d', makePath(tsr));
  p1.setAttribute('fill', 'none');
  p1.setAttribute('stroke-width', '2.5');
  p1.setAttribute('stroke', 'currentColor'); // usa color actual del texto
  svg.appendChild(p1);

  // TSF line (misma técnica, distinto grupo con opacidad)
  const p2 = document.createElementNS('http://www.w3.org/2000/svg','path');
  p2.setAttribute('d', makePath(tsf));
  p2.setAttribute('fill', 'none');
  p2.setAttribute('stroke-width', '2.5');
  p2.setAttribute('stroke', 'currentColor');
  p2.setAttribute('opacity', '0.55');
  svg.appendChild(p2);

  // labels extremos (mes inicial y final)
  const mkText = (txt, px, py, anchor='middle') => {
    const t = document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x', px); t.setAttribute('y', py);
    t.setAttribute('font-size', '10');
    t.setAttribute('text-anchor', anchor);
    t.textContent = txt;
    return t;
  };
  if (data.length){
    svg.appendChild(mkText(data[0].month, x(0), H-6));
    svg.appendChild(mkText(data[data.length-1].month, x(data.length-1), H-6));
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
  document.getElementById('refreshBtn')?.addEventListener('click', loadDashboard);
});