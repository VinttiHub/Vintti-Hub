// ===== Helpers =====
const API = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

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