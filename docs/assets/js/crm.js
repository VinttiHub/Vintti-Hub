/* =========================================================
   Vintti Hub · Accounts page JS (clean + commented)
   - No breaking changes to names/classes/IDs/APIs
   - Duplicates removed, helpers grouped, tiny fixes only
   ========================================================= */

/* =========================
   0) Constants & Globals
   ========================= */
const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

// Emails allowed for extra UI (priority col, summary link, etc.)
const allowedEmails = [
  'agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com',
  'lara@vintti.com','agostina@vintti.com', 'mariano@vintti.com'
];

const CRM_UNASSIGNED_SALES_LEAD_VALUE = '__unassigned__';
const CRM_FILTER_STATE = { salesLead: '', status: '', contract: '' };
const CRM_SALES_LEAD_OPTIONS = new Map();
let accountTableInstance = null;
let crmDataTableFilterRegistered = false;

/* =========================
   1) Generic helpers
   ========================= */

// Money formatter: returns null for 0 to let caller show placeholders
function fmtMoney(v) {
  if (v === null || v === undefined) return null;
  const num = Number(v) || 0;
  if (num === 0) return null;
  return `$${num.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

// Normalize text (lowercase + trim)
function norm(s) {
  return (s || '').toString().toLowerCase().trim();
}

// Stage normalization to 3 buckets: 'won' | 'lost' | 'pipeline' | 'other'
function normalizeStage(stage) {
  const v = norm(stage);
  if (/closed?[_\s-]?won|close[_\s-]?win/.test(v))  return 'won';
  if (/closed?[_\s-]?lost|close[_\s-]?lost/.test(v)) return 'lost';
  if (/(sourc|interview|negotiat|deep\s?dive)/.test(v)) return 'pipeline';
  return 'other';
}

// Detect if a hire/candidate is active
function isActiveHire(h) {
  const st = norm(h.status);
  if (st === 'active') return true;
  if (st === 'inactive') return false;

  const ed = (h.end_date ?? '').toString().trim().toLowerCase();
  if (!ed || ed === 'null' || ed === 'none' || ed === 'undefined' || ed === '0000-00-00') return true;
  return false;
}

// Render a status chip for the accounts table
function renderAccountStatusChip(statusText) {
  const s = norm(statusText);
  if (s === 'active client')   return '<span class="chip chip--active-client">Active Client</span>';
  if (s === 'inactive client') return '<span class="chip chip--inactive-client">Inactive Client</span>';
  if (s === 'lead in process') return '<span class="chip chip--lead-process">Lead in Process</span>';
  if (s === 'lead')            return '<span class="chip chip--lead">Lead</span>';
  if (s === 'lead lost')       return '<span class="chip chip--lead-lost">Lead Lost</span>';
  return '<span class="chip chip--empty">No data</span>';
}

// Calculate account status from opps + hires
function deriveStatusFrom(opps = [], hires = []) {
  const hasCandidates = Array.isArray(hires) && hires.length > 0;
  const anyActiveCandidate = hasCandidates && hires.some(isActiveHire);
  const allCandidatesInactive = hasCandidates && hires.every(h => !isActiveHire(h));

  const stages = (Array.isArray(opps) ? opps : []).map(o => normalizeStage(o.opp_stage || o.stage));
  const hasOpps = stages.length > 0;
  const hasPipeline = stages.some(s => s === 'pipeline');
  const allLost = hasOpps && stages.every(s => s === 'lost');

  if (anyActiveCandidate) return 'Active Client';
  if (allCandidatesInactive) return 'Inactive Client';
  if (!hasOpps && !hasCandidates) return 'Lead';
  if (allLost && !hasCandidates) return 'Lead Lost';
  if (hasPipeline) return 'Lead in Process';

  if (!hasOpps && hasCandidates) return 'Inactive Client';
  return 'Lead in Process';
}

// Ranking for DataTables ordering by account status
function statusRank(statusText){
  const s = norm(statusText);
  if (s === 'active client')   return 0;
  if (s === 'lead in process') return 1;
  if (s === 'lead')            return 2;
  if (s === 'inactive client') return 3;
  if (s === 'lead lost')       return 4;
  return 5;
}

function initCrmFilterControls() {
  document
    .querySelectorAll('select[data-filter-key]')
    .forEach(select => {
      const key = select.dataset.filterKey;
      if (!key || !(key in CRM_FILTER_STATE)) return;
      select.value = '';
      select.addEventListener('change', handleCrmFilterChange);
    });
  renderSalesLeadOptions();
}

function handleCrmFilterChange(event) {
  const select = event?.currentTarget || event?.target;
  const key = select?.dataset?.filterKey;
  if (!key || !(key in CRM_FILTER_STATE)) return;
  CRM_FILTER_STATE[key] = select.value;
  if (accountTableInstance) {
    accountTableInstance.draw();
    updateCrmEmptyState(accountTableInstance);
  }
}

function registerAccountTableFilters(table) {
  if (crmDataTableFilterRegistered) return;
  $.fn.dataTable.ext.search.push((settings, data, dataIndex) => {
    if (!settings?.nTable || settings.nTable.id !== 'accountTable') return true;
    const api = new $.fn.dataTable.Api(settings);
    const row = api.row(dataIndex).node();
    if (!row) return true;
    return doesRowMatchCrmFilters(row);
  });
  crmDataTableFilterRegistered = true;
}

function doesRowMatchCrmFilters(row) {
  const ds = row?.dataset || {};
  if (CRM_FILTER_STATE.salesLead) {
    const code = ds.salesLeadCode || CRM_UNASSIGNED_SALES_LEAD_VALUE;
    if (code !== CRM_FILTER_STATE.salesLead) return false;
  }
  if (CRM_FILTER_STATE.status) {
    const statusCode = ds.statusCode || '';
    if (statusCode !== CRM_FILTER_STATE.status) return false;
  }
  if (CRM_FILTER_STATE.contract) {
    const contractCode = ds.contractCode || '';
    if (contractCode !== CRM_FILTER_STATE.contract) return false;
  }
  return true;
}

function updateCrmEmptyState(table) {
  const emptyState = document.getElementById('crmEmptyState');
  if (!emptyState) return;
  if (!table) {
    emptyState.classList.remove('visible');
    return;
  }
  const visibleRows = table.rows({ filter: 'applied' }).data().length;
  emptyState.classList.toggle('visible', visibleRows === 0);
}

function toggleCrmLoading(show, message) {
  const overlay = document.getElementById('crmLoadingOverlay');
  if (!overlay) return;
  const textEl = overlay.querySelector('.crm-loading-text');
  if (textEl && message) textEl.textContent = message;
  overlay.classList.toggle('hidden', !show);
  overlay.setAttribute('aria-hidden', show ? 'false' : 'true');
}

function createOption(value, label) {
  const opt = document.createElement('option');
  opt.value = value;
  opt.textContent = label;
  return opt;
}

function renderSalesLeadOptions() {
  const select = document.getElementById('salesLeadFilter');
  if (!select) return;
  const prevValue = select.value;
  const fragment = document.createDocumentFragment();
  fragment.appendChild(createOption('', 'All Sales Leads'));
  fragment.appendChild(createOption(CRM_UNASSIGNED_SALES_LEAD_VALUE, 'Unassigned'));
  const entries = Array.from(CRM_SALES_LEAD_OPTIONS.entries())
    .sort((a, b) => a[1].localeCompare(b[1]));
  entries.forEach(([value, label]) => {
    fragment.appendChild(createOption(value, label || value));
  });
  select.replaceChildren(fragment);

  const desired = CRM_FILTER_STATE.salesLead || prevValue;
  const hasDesired = Array.from(select.options).some(opt => opt.value === desired);
  select.value = hasDesired ? desired : (CRM_FILTER_STATE.salesLead || '');
}

function upsertSalesLeadOption(value, label) {
  const key = (value || '').toLowerCase().trim();
  if (!key) return false;
  const display = (label || '').trim() || value;
  const prev = CRM_SALES_LEAD_OPTIONS.get(key);
  if (prev === display) return false;
  CRM_SALES_LEAD_OPTIONS.set(key, display);
  return true;
}

async function loadSalesLeadFilterOptions() {
  renderSalesLeadOptions();
  try {
    const res = await fetch(`${API_BASE}/users/sales-leads`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    let added = false;
    (Array.isArray(payload) ? payload : []).forEach(lead => {
      const email = (lead?.email || lead?.email_vintti || '').toLowerCase().trim();
      const name = (lead?.user_name || lead?.name || '').trim();
      if (email) added = upsertSalesLeadOption(email, name || email) || added;
    });
    if (added) renderSalesLeadOptions();
  } catch (err) {
    console.warn('⚠️ Could not load sales lead list:', err);
  }
}

function augmentSalesLeadFilterWithData(items = []) {
  let added = false;
  for (const item of items) {
    const meta = deriveSalesLeadMeta(item);
    if (!meta || !meta.code || meta.code === CRM_UNASSIGNED_SALES_LEAD_VALUE) continue;
    added = upsertSalesLeadOption(meta.code, meta.label) || added;
  }
  if (added) renderSalesLeadOptions();
}

function deriveSalesLeadMeta(item = {}) {
  const email = (item.account_manager || '').toString().toLowerCase().trim();
  const name = (item.account_manager_name || '').toString().trim();
  if (email) {
    return { code: email, label: name || item.account_manager || email };
  }
  if (name) {
    return { code: `name:${norm(name)}`, label: name };
  }
  return { code: CRM_UNASSIGNED_SALES_LEAD_VALUE, label: 'Unassigned' };
}

function decorateRowFilterMeta(row, item) {
  if (!row) return null;
  const contractLabel = deriveContractLabel(item?.contract);
  row.dataset.contractLabel = contractLabel;
  row.dataset.contractCode = norm(contractLabel);

  const leadMeta = deriveSalesLeadMeta(item);
  row.dataset.salesLeadLabel = leadMeta.label;
  row.dataset.salesLeadCode = leadMeta.code;

  row.dataset.statusLabel = row.dataset.statusLabel || '';
  row.dataset.statusCode = row.dataset.statusCode || '';
  return { contractLabel, leadMeta };
}

function deriveContractLabel(contractRaw) {
  const txt = (contractRaw || '').toString().trim();
  return txt || 'No Contract';
}

function populateContractFilter(values = []) {
  const select = document.getElementById('contractFilter');
  if (!select) return;
  const prev = select.value;
  const fragment = document.createDocumentFragment();
  fragment.appendChild(createOption('', 'All Contracts'));
  Array.from(new Set(values))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b))
    .forEach(label => {
      fragment.appendChild(createOption(norm(label), label));
    });
  select.replaceChildren(fragment);

  const desired = CRM_FILTER_STATE.contract || prev;
  const hasDesired = Array.from(select.options).some(opt => opt.value === desired);
  select.value = hasDesired ? desired : (CRM_FILTER_STATE.contract || '');
}

function populateStatusFilter(values = []) {
  const select = document.getElementById('statusFilter');
  if (!select) return;
  const prev = select.value;
  const fragment = document.createDocumentFragment();
  fragment.appendChild(createOption('', 'All Statuses'));
  Array.from(new Set(values))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b))
    .forEach(label => {
      fragment.appendChild(createOption(norm(label), label));
    });
  select.replaceChildren(fragment);

  const desired = CRM_FILTER_STATE.status || prev;
  const hasDesired = Array.from(select.options).some(opt => opt.value === desired);
  select.value = hasDesired ? desired : (CRM_FILTER_STATE.status || '');
}

/* =========================
   2) Mini progress toast
   ========================= */

const _sortToastState = { total: 0, done: 0, start: 0 };

function _ensureSortToast() {
  const t = document.getElementById('crmSortToast');
  if (!t) console.warn('crmSortToast element not found.');
  return t;
}

// Show toast; total>0 shows %; otherwise indeterminate
function showSortToast(total = 0) {
  const t = _ensureSortToast();
  if (!t) return;

  _sortToastState.total = Number(total) || 0;
  _sortToastState.done  = 0;
  _sortToastState.start = Date.now();

  const bar = t.querySelector('.sort-toast__bar');
  const percent = t.querySelector('#sortToastPercent');
  const progress = t.querySelector('.sort-toast__progress');

  if (bar) bar.style.width = '0%';
  if (percent) percent.textContent = (_sortToastState.total ? '0%' : '…');
  if (progress) progress.setAttribute('aria-valuenow', '0');

  t.classList.remove('hide');
  t.style.display = 'block';
  t.classList.toggle('indeterminate', !_sortToastState.total);
  requestAnimationFrame(() => t.classList.add('show'));
}

// Update progress: call with (done,total) or with an increment value
function updateSortToast(doneOrInc, maybeTotal) {
  const t = _ensureSortToast();
  if (!t) return;

  if (typeof maybeTotal === 'number' && maybeTotal > 0) {
    _sortToastState.total = maybeTotal;
    _sortToastState.done  = Math.max(0, Math.min(maybeTotal, doneOrInc));
  } else {
    _sortToastState.done  = Math.max(0, _sortToastState.done + (Number(doneOrInc) || 0));
  }

  const { done, total } = _sortToastState;
  const bar = t.querySelector('.sort-toast__bar');
  const percent = t.querySelector('#sortToastPercent');
  const progress = t.querySelector('.sort-toast__progress');

  if (total > 0) {
    const pct = Math.max(0, Math.min(100, Math.round((done / total) * 100)));
    if (bar) bar.style.width = pct + '%';
    if (percent) percent.textContent = pct + '%';
    if (progress) progress.setAttribute('aria-valuenow', String(pct));
    t.classList.remove('indeterminate');
  } else {
    if (percent) percent.textContent = '…';
    t.classList.add('indeterminate');
  }
}

function hideSortToast() {
  const t = _ensureSortToast();
  if (!t) return;
  t.classList.add('hide');
  t.classList.remove('show');
  setTimeout(() => { t.style.display = 'none'; }, 250);
}

function extendSortToastTotal(extra = 0) {
  const inc = Number(extra) || 0;
  if (inc <= 0) return;
  const newTotal = (_sortToastState.total || 0) + inc;
  updateSortToast(_sortToastState.done, newTotal);
}

/* =========================
   3) Controlled concurrency
   ========================= */

async function runWithConcurrency(tasks, limit = 6) {
  const queue = tasks.slice();
  const workers = Array.from({ length: limit }, async () => {
    while (queue.length) await queue.shift()();
  });
  await Promise.all(workers);
}

async function fetchAccountStatusDetails(accountId) {
  const [oppsRes, hiresRes] = await Promise.all([
    fetch(`${API_BASE}/accounts/${accountId}/opportunities`),
    fetch(`${API_BASE}/accounts/${accountId}/opportunities/candidates`)
  ]);
  if (!oppsRes.ok) throw new Error(`Opps HTTP ${oppsRes.status}`);
  if (!hiresRes.ok) throw new Error(`Candidates HTTP ${hiresRes.status}`);
  const [opps, hires] = await Promise.all([oppsRes.json(), hiresRes.json()]);
  return deriveStatusFrom(opps, hires);
}

/* =========================
   4) Status computation & painting
   ========================= */

async function computeAndPaintAccountStatuses({ ids, rowById, onProgress }) {
  const CHUNK = 200;
  const CONC_SUMMARY = 4;
  const CONC_FALLBACK = Math.min(navigator.hardwareConcurrency || 8, 8);
  onProgress?.(0, ids.length);

  const summary = {}; // { [id]: { status: "..." } }

  function mergeSummary(resp) {
    let added = 0;

    if (Array.isArray(resp)) {
      for (const it of resp) {
        const id = Number(it.account_id ?? it.id ?? it.accountId);
        if (!id) continue;
        const status = it.status ?? it.calculated_status ?? it.value ?? '—';
        if (!summary[id]) added++;
        summary[id] = { status };
      }
      return added;
    }

    if (resp && typeof resp === 'object') {
      for (const [k, v] of Object.entries(resp)) {
        const id = Number(k);
        if (!id) continue;
        let status;
        if (v && typeof v === 'object') status = v.status ?? v.calculated_status ?? v.value ?? '—';
        else status = v ?? '—';
        if (!summary[id]) added++;
        summary[id] = { status };
      }
      return added;
    }
    return 0;
  }

  // 1) Try bulk summary
  const chunks = [];
  for (let i = 0; i < ids.length; i += CHUNK) chunks.push(ids.slice(i, i + CHUNK));

  let chunkIndex = 0;
  await Promise.all(
    Array.from({ length: CONC_SUMMARY }, async () => {
      while (true) {
        const myIndex = chunkIndex++;
        if (myIndex >= chunks.length) break;
        const partIds = chunks[myIndex];
        try {
          const r = await fetch(`${API_BASE}/accounts/status/summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: partIds })
          });
          if (r.ok) {
            const json = await r.json();
            const added = mergeSummary(json);
            if (added > 0) onProgress?.(added);
          }
        } catch { /* fallback will handle missing */ }
      }
    })
  );

  // 2) Re-derive using detailed data for anything missing or non-active
  const needsDetail = ids.filter(id => {
    const status = summary[id]?.status || '';
    if (!status) return true;
    return norm(status) !== 'active client';
  });
  if (needsDetail.length) {
    const tasks = needsDetail.map(id => async () => {
      const hadSummary = Boolean(summary[id]);
      try {
        const derivedStatus = await fetchAccountStatusDetails(id);
        summary[id] = { status: derivedStatus };
      } catch (err) {
        if (!summary[id]) summary[id] = { status: '—' };
        console.warn(`⚠️ Could not re-derive status for account ${id}:`, err);
      } finally {
        if (!hadSummary) onProgress?.(1);
      }
    });
    await runWithConcurrency(tasks, CONC_FALLBACK);
  }

  // 3) Paint chips + sort key
  for (const id of ids) {
    const row = rowById.get(id);
    if (!row) continue;
    const td = row.querySelector('td.status-td');
    const status = summary?.[id]?.status || '—';
    if (td) {
      td.innerHTML = renderAccountStatusChip(status);
      td.dataset.order = String(statusRank(status));
    }
    row.dataset.statusLabel = status;
    row.dataset.statusCode = norm(status);
  }

  // 4) Persist — try bulk first; if it fails, patch one by one
  try {
    const updates = ids.map(id => ({
      account_id: id,
      status: summary?.[id]?.status || '—'
    }));
    const rb = await fetch(`${API_BASE}/accounts/status/bulk_update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // FIX: previously referenced u.calculated_status (undefined).
      // If the API expects "calculated_status", send that key with the status value.
      body: JSON.stringify({
        updates: updates.map(u => ({
          account_id: u.account_id,
          calculated_status: u.status
        }))
      })
    });
    if (!rb.ok) throw new Error('bulk endpoint not available');
  } catch {
    const patchTasks = ids.map(id => async () => {
      try {
        await fetch(`${API_BASE}/accounts/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_status: summary?.[id]?.status || '—' })
        });
      } catch { /* noop */ }
    });
    await runWithConcurrency(patchTasks, 6);
  }

  return summary;
}

/* =========================
   5) Sales Lead visuals (avatars + badges)
   ========================= */

// Merge avatar map without losing previously-defined entries
window.AVATAR_BASE = window.AVATAR_BASE || './assets/img/';
window.AVATAR_BY_EMAIL = Object.assign(
  {
    'agostina@vintti.com': 'agos.png',
    'bahia@vintti.com':    'bahia.png',
    'lara@vintti.com':     'lara.png',
    'jazmin@vintti.com':   'jaz.png',
    'pilar@vintti.com':    'pilar.png',
    'agustin@vintti.com':  'agus.png',
    'agustina.barbero@vintti.com': 'agustina.png',
    'mariano@vintti.com': 'mariano.png' 
  },
  window.AVATAR_BY_EMAIL || {}
);

if (typeof window.resolveAvatar !== 'function') {
  window.resolveAvatar = function resolveAvatar(email) {
    if (!email) return null;
    const key = String(email).trim().toLowerCase();
    const filename = window.AVATAR_BY_EMAIL[key];
    return filename ? (window.AVATAR_BASE + filename) : null;
  };
}

function initialsForSalesLead(key='') {
  const s = key.toLowerCase();
  if (s.includes('bahia'))   return 'BL';
  if (s.includes('lara'))    return 'LR';
  if (s.includes('agustin')) return 'AM';
  if (s.includes('mariano')) return 'MS';   // ✅ ADD
  return '--';
}

function badgeClassForSalesLead(key='') {
  const s = key.toLowerCase();
  if (s.includes('bahia'))   return 'bl';
  if (s.includes('lara'))    return 'lr';
  if (s.includes('agustin')) return 'am';
  if (s.includes('mariano')) return 'ms';   // ✅ ADD
  return '';
}

function emailFromNameGuess(name='') {
  const s = name.toLowerCase();
  if (s.includes('bahia'))   return 'bahia@vintti.com';
  if (s.includes('lara'))    return 'lara@vintti.com';
  if (s.includes('agustin')) return 'agustin@vintti.com';
  if (s.includes('mariano')) return 'mariano@vintti.com'; // ✅ ADD
  return '';
}

// Render the sales-lead cell (avatar + initials bubble)
function getAccountSalesLeadCell(item) {
  const email = (item.account_manager || emailFromNameGuess(item.account_manager_name || '')).toLowerCase();
  const name  = item.account_manager_name || '';
  const key = (email || name).toLowerCase();

  const initials = initialsForSalesLead(key);
  const bubbleCl = badgeClassForSalesLead(key);
  const avatar = window.resolveAvatar(email);
  const img = avatar ? `<img class="lead-avatar" src="${avatar}" alt="">` : '';

  return `
    <div class="sales-lead">
      <span class="lead-bubble ${bubbleCl}">${initials}</span>
      ${img}
      <span class="sr-only" style="display:none">${name}</span>
    </div>
  `;
}

/* =========================
   6) Auto-assign manager by status
   ========================= */

function managerEmailForStatus(statusText='') {
  const s = (statusText || '').toLowerCase().trim();
  if (s === 'active client') return 'lara@vintti.com';
  // lead in process => se resuelve por endpoint (mayoría)
  return null;
}

async function patchAccountManager(accountId, email) {
  await fetch(`${API_BASE}/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_manager: email })
  });
}

function updateRowSalesLead(rowEl, email, displayName) {
  if (!rowEl) return null;
  const normalizedEmail = (email || '').toString().trim().toLowerCase();
  const item = {
    account_manager: normalizedEmail,
    account_manager_name: displayName || email || normalizedEmail
  };
  const cell = rowEl.querySelector('.sales-lead-cell');
  if (cell) cell.innerHTML = getAccountSalesLeadCell(item);
  const meta = deriveSalesLeadMeta(item);
  rowEl.dataset.salesLeadLabel = meta.label || '';
  rowEl.dataset.salesLeadCode = meta.code || '';
  if (meta.code && upsertSalesLeadOption(meta.code, meta.label || meta.code)) {
    renderSalesLeadOptions();
  }
  return meta;
}

async function assignManagersFromStatus(summary = {}, rowById = new Map(), onProgress) {
  if (!summary || !rowById) return 0;
  const tasks = [];
  const getRowLead = (row) => (row?.dataset?.salesLeadCode || '').toLowerCase().trim();

  for (const [idStr, info] of Object.entries(summary)) {
    const accountId = Number(idStr);
    if (!accountId) continue;
    const status = norm(info?.status);
    const row = rowById.get(accountId);
    if (!row) continue;

    if (status === 'active client') {
      const targetEmail = 'lara@vintti.com';
      if (getRowLead(row) === targetEmail) continue;
      tasks.push(async () => {
        try {
          await patchAccountManager(accountId, targetEmail);
          updateRowSalesLead(row, targetEmail, targetEmail);
        } catch (e) {
          console.warn(`⚠️ Could not assign manager to ${accountId}:`, e);
        } finally {
          onProgress?.(1);
        }
      });
      continue;
    }

    if (status === 'lead in process') {
      tasks.push(async () => {
        try {
          const r = await fetch(`${API_BASE}/accounts/${accountId}/sales-lead/suggest`);
          const json = r.ok ? await r.json() : null;
          const suggested = (json?.suggested_sales_lead || '').toLowerCase().trim();
          if (!suggested) return;
          if (getRowLead(row) === suggested) return;
          await patchAccountManager(accountId, suggested);
          updateRowSalesLead(row, suggested, suggested);
        } catch (e) {
          console.warn(`⚠️ Could not assign majority sales lead to ${accountId}:`, e);
        } finally {
          onProgress?.(1);
        }
      });
    }
  }

  if (!tasks.length) return 0;
  extendSortToastTotal(tasks.length);
  await runWithConcurrency(tasks, 6);
  return tasks.length;
}

function kickoffCrmStatusPipeline({ ids = [], rowById = new Map() }) {
  if (!Array.isArray(ids) || ids.length === 0) {
    return Promise.resolve({ summary: {}, assignments: 0 });
  }
  showSortToast(ids.length + 1);
  return computeAndPaintAccountStatuses({
    ids,
    rowById,
    onProgress: (inc) => updateSortToast(inc)
  })
    .then(async (summary) => {
      const statusLabels = new Set();
      ids.forEach(id => {
        const status = summary?.[id]?.status || '—';
        if (status && status !== '—') statusLabels.add(status);
      });
      populateStatusFilter(Array.from(statusLabels));
      const assignments = await assignManagersFromStatus(summary, rowById, (inc) => updateSortToast(inc));
      return { summary, assignments };
    })
    .catch((err) => {
      console.error('Error computing CRM statuses:', err);
      return { summary: {}, assignments: 0 };
    })
    .finally(() => {
      updateSortToast(1);
      setTimeout(hideSortToast, 400);
    });
}

/* =========================
   7) Referral source UI
   ========================= */

async function loadReferralClients() {
  try {
    const r = await fetch(`${API_BASE}/accounts`);
    const arr = await r.json();
    const names = [...new Set((arr || [])
      .map(x => (x.account_name || x.client_name || '').trim())
      .filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
    const el = document.getElementById('referralList');
    if (el) el.innerHTML = names.map(n => `<option value="${n}"></option>`).join('');
  } catch (e) {
    console.warn('⚠️ Could not load referral clients list:', e);
  }
}

function updateReferralVisibility(sourceSelect) {
  const wrap  = document.getElementById('referralSourceWrapper');
  const input = document.getElementById('referralSourceInput');
  if (!wrap || !input || !sourceSelect) return;

  const isReferral = String(sourceSelect.value || '').toLowerCase() === 'referral';
  wrap.style.display = isReferral ? '' : 'none';
  input.required = isReferral;
  if (!isReferral) input.value = '';
}

/* =========================
   8) Popup helpers (UI)
   ========================= */

function openPopup() {
  const popup = document.getElementById('popup');
  popup.style.display = 'flex';
  popup.classList.add('show');
}
function closePopup() {
  const popup = document.getElementById('popup');
  popup.classList.remove('show');
  setTimeout(() => { popup.style.display = 'none'; }, 300);
}
/* =========================
   Sidebar profile tile 
   ========================= */

async function initSidebarProfileCRM(){
  // helpers
  function initialsFromName(name=""){
    const parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '—';
    const a = (parts[0]?.[0]||'').toUpperCase();
    const b = (parts[1]?.[0]||'').toUpperCase();
    return (a + b) || a || '—';
  }
  function initialsFromEmail(email=""){
    const local = String(email).split('@')[0] || '';
    if (!local) return '—';
    const bits = local.split(/[._-]+/).filter(Boolean);
    return (bits.length >= 2)
      ? (bits[0][0] + bits[1][0]).toUpperCase()
      : local.slice(0,2).toUpperCase();
  }

  let tile = document.getElementById('sidebarProfile');
  const sidebar = document.querySelector('.sidebar');
  if (!tile && sidebar){
    sidebar.insertAdjacentHTML('beforeend', `
      <a href="profile.html" class="profile-tile" id="sidebarProfile">
        <span class="profile-avatar">
          <img id="profileAvatarImg" alt="" />
          <span id="profileAvatarInitials" class="profile-initials" aria-hidden="true">—</span>
        </span>
        <span class="profile-meta">
          <span id="profileName" class="profile-name">Profile</span>
          <span id="profileEmail" class="profile-email"></span>
        </span>
      </a>
    `);
    tile = document.getElementById('sidebarProfile');
  }
  if (!tile) return;

  const $init   = document.getElementById('profileAvatarInitials');
  const $name   = document.getElementById('profileName');
  const $emailE = document.getElementById('profileEmail');
  const $img    = document.getElementById('profileAvatarImg');

  // nunca mostrar email en el profile (igual que main)
  if ($emailE) { 
    $emailE.textContent = ''; 
    $emailE.style.display = 'none'; 
  }

  const showInitials = (value) => {
    if (!$init || !$img) return;
    $init.style.display = 'grid';
    $init.textContent = value || '—';
    $img.removeAttribute('src');
    $img.style.display = 'none';
  };

  const showAvatar = (src) => {
    if (!$img || !$init) return;
    if (src) {
      $img.src = src;
      $img.style.display = 'block';
      $init.style.display = 'none';
    } else {
      showInitials($init?.textContent || '—');
    }
  };

  // resolver uid igual que en main
  let uid = null;
  try {
    uid = (typeof window.getCurrentUserId === 'function')
      ? (await window.getCurrentUserId())
      : (Number(localStorage.getItem('user_id')) || null);
  } catch {
    uid = Number(localStorage.getItem('user_id')) || null;
  }

  // link al profile con user_id
  const base = 'profile.html';
  tile.href = uid != null ? `${base}?user_id=${encodeURIComponent(uid)}` : base;

  // iniciales rápidas con el email mientras carga
  const email = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '').toLowerCase();
  if ($init) {
    $init.textContent = initialsFromEmail(email);
    $init.style.display = 'grid';
  }

  const cachedAvatar = localStorage.getItem('user_avatar');
  if (cachedAvatar) {
    showAvatar(cachedAvatar);
  } else {
    showInitials($init?.textContent || initialsFromEmail(email));
  }

  // intentar /users/<uid>, fallback a /profile/me
  let user = null;
  try {
    if (uid != null) {
      const r = await fetch(`${API_BASE}/users/${encodeURIComponent(uid)}?user_id=${encodeURIComponent(uid)}`, { credentials:'include' });
      if (r.ok) user = await r.json();
      else console.debug('[sidebar CRM] /users/<uid> failed:', r.status);
    }
    if (!user) {
      const r2 = await fetch(`${API_BASE}/profile/me${uid!=null?`?user_id=${encodeURIComponent(uid)}`:''}`, { credentials:'include' });
      if (r2.ok) user = await r2.json();
      else console.debug('[sidebar CRM] /profile/me failed:', r2.status);
    }
  } catch (e) {
    console.debug('[sidebar CRM] fetch error:', e);
  }

  const userName = user?.user_name || '';
  if (userName) {
    if ($name) $name.textContent = userName;
    if ($init) $init.textContent = initialsFromName(userName);
  } else if ($name) {
    $name.textContent = 'Profile'; // fallback
  }

  const avatarSrc = typeof window.resolveUserAvatar === 'function'
    ? window.resolveUserAvatar({
        avatar_url: user?.avatar_url,
        email_vintti: user?.email_vintti || email,
        email: user?.email_vintti || email,
        user_id: user?.user_id ?? uid
      })
    : (user?.avatar_url || '');

  if (avatarSrc) {
    localStorage.setItem('user_avatar', avatarSrc);
    showAvatar(avatarSrc);
  } else {
    showInitials(initialsFromName(userName) || initialsFromEmail(email));
  }

  // aseguramos que se vea
  const cs = window.getComputedStyle(tile);
  if (cs.display === 'none') tile.style.display = 'flex';
}

// mantener este listener tal cual
document.addEventListener('DOMContentLoaded', initSidebarProfileCRM);

// Enforce limited UI for specific users (CRM + Opportunities only)
(function enforceLimitedUI() {
  const LIMITED_USERS = new Set(['felipe@vintti.com','felicitas@vintti.com','luca@vintti.com','abril@vintti.com']);
  const ALLOWED_IDS = new Set(['crmLink','opportunitiesLink']);
  const ALLOWED_TEXT_KEYWORDS = ['crm', 'opportunit'];

  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();
  if (!LIMITED_USERS.has(email)) return;

  const navCandidates = Array.from(document.querySelectorAll(`
    .sidebar a, .sidebar button, nav a, nav button,
    .topbar a, .topbar button, .menu a, .menu button,
    .bubble-button, a[id], button[id]
  `));

  navCandidates.forEach(el => {
    const id = (el.id || '').toLowerCase();
    const txt = (el.textContent || el.getAttribute('aria-label') || '').toLowerCase().trim();
    const isAllowedById = id && ALLOWED_IDS.has(id);
    const isAllowedByText = ALLOWED_TEXT_KEYWORDS.some(k => txt.includes(k));
    if (!isAllowedById && !isAllowedByText) {
      el.style.display = 'none';
      el.setAttribute('aria-hidden', 'true');
    }
  });

  ['crmLink', 'opportunitiesLink'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.style.display = ''; el.removeAttribute('aria-hidden'); }
  });

  const path = (location.pathname || '').toLowerCase();
  const isAllowedPage = path.includes('opportunit') || path.includes('crm');
  if (!isAllowedPage) {
    const fallback = document.getElementById('opportunitiesLink')?.getAttribute('href') || 'opportunities.html';
    try { location.replace(fallback); } catch { location.href = fallback; }
  }
})();

// Inject Dashboard + Management Metrics for allowed users 
// --- Equipments(visibilidad por email) ---
(() => {
  const eq = document.getElementById('equipmentsLink');
  if (!eq) return;

  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase();
  const equipmentsAllowed = [
    'angie@vintti.com',
    'jazmin@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com'
  ];

  eq.style.display = equipmentsAllowed.includes(currentUserEmail) ? 'flex' : 'none';
})();
// --- Dashboard + Management Metrics (usar botones del HTML con iconos) ---
(() => {
  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase();
  const DASH_ALLOWED = new Set([
    'agustin@vintti.com',
    'angie@vintti.com',
    'lara@vintti.com',
    'bahia@vintti.com',
    'agostina@vintti.com',
    'mia@vintti.com'
  ]);

  const dash = document.getElementById('dashboardLink');
  const mgmt = document.getElementById('managementMetricsLink');

  if (!DASH_ALLOWED.has(currentUserEmail)) {
    if (dash) dash.style.display = 'none';
    if (mgmt) mgmt.style.display = 'none';
    return;
  }

  if (dash) dash.style.display = 'flex';
  if (mgmt) mgmt.style.display = 'flex';
})();
// --- Recruiter Power (visibilidad por email) ---
(() => {
  const link = document.getElementById('recruiterPowerLink');
  if (!link) return;

  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  const RECRUITER_POWER_ALLOWED = new Set([
    'angie@vintti.com',
    'agostina@vintti.com',
    'agostin@vintti.com',
    'agustina.barbero@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com',
    'constanza@vintti.com',
    'pilar@vintti.com',
    'pilar.fernandez@vintti.com',
    'julieta@vintti.com'
  ]);

  // Mantener flex para icono + texto alineados
  link.style.display = RECRUITER_POWER_ALLOWED.has(email) ? 'flex' : 'none';
})();
// --- Sales Metrics ---
(() => {
  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase();
  const SALES_ALLOWED = new Set([
    'agustin@vintti.com',
    'angie@vintti.com',
    'lara@vintti.com',
    'bahia@vintti.com',
    'mariano@vintti.com'
  ]);

  const sales = document.getElementById('salesLink');

  if (!SALES_ALLOWED.has(currentUserEmail)) {
    if (sales) sales.style.display = 'none';
    return;
  }

  if (sales) sales.style.display = 'flex';
})();
/* === Candidate Search button visibility (igual que en main) === */
(() => {
  const candidateSearchLink = document.getElementById('candidateSearchLink');
  if (!candidateSearchLink) return;

  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  const CANDIDATE_SEARCH_ALLOWED = new Set([
    'agustina.barbero@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com',
    'constanza@vintti.com',
    'pilar@vintti.com',
    'pilar.fernandez@vintti.com',
    'angie@vintti.com',
    'agostina@vintti.com',
    'julieta@vintti.com'
  ]);

  candidateSearchLink.style.display = CANDIDATE_SEARCH_ALLOWED.has(email) ? 'flex' : 'none';
})();
// Summary / Equipments visibility
(() => {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  const summaryAllowed = [
    'agustin@vintti.com','bahia@vintti.com','angie@vintti.com',
    'lara@vintti.com','agostina@vintti.com','mariano@vintti.com',
    'jazmin@vintti.com'
  ];
  const equipmentsAllowed = [
    'angie@vintti.com','jazmin@vintti.com','agustin@vintti.com','lara@vintti.com'
  ];

  const summaryLink = document.getElementById('summaryLink');
  const equipmentsLink = document.getElementById('equipmentsLink');

  if (summaryLink)   summaryLink.style.display   = summaryAllowed.includes(email)   ? '' : 'none';
  if (equipmentsLink) equipmentsLink.style.display = equipmentsAllowed.includes(email) ? '' : 'none';
})();
/* =========================
   10) Sidebar toggle with memory
   ========================= */

(() => {
  const sidebarToggleBtn = document.getElementById('sidebarToggle');
  const sidebarToggleIcon = document.getElementById('sidebarToggleIcon');
  const sidebarEl = document.querySelector('.sidebar');
  const mainContentEl = document.querySelector('.main-content');
  if (!sidebarToggleBtn || !sidebarToggleIcon || !sidebarEl || !mainContentEl) return;

  const isSidebarHidden = localStorage.getItem('sidebarHidden') === 'true';
  if (isSidebarHidden) {
    sidebarEl.classList.add('custom-sidebar-hidden');
    mainContentEl.classList.add('custom-main-expanded');
    sidebarToggleIcon.classList.remove('fa-chevron-left');
    sidebarToggleIcon.classList.add('fa-chevron-right');
    sidebarToggleBtn.style.left = '12px';
  } else {
    sidebarToggleBtn.style.left = '220px';
  }

  sidebarToggleBtn.addEventListener('click', () => {
    const hidden = sidebarEl.classList.toggle('custom-sidebar-hidden');
    mainContentEl.classList.toggle('custom-main-expanded', hidden);
    sidebarToggleIcon.classList.toggle('fa-chevron-left', !hidden);
    sidebarToggleIcon.classList.toggle('fa-chevron-right', hidden);
    sidebarToggleBtn.style.left = hidden ? '12px' : '220px';
    localStorage.setItem('sidebarHidden', hidden);
  });
})();

/* =========================
   11) Main: data fetch + table render + behaviors
   ========================= */

document.addEventListener('DOMContentLoaded', () => {
  initCrmFilterControls();
  loadSalesLeadFilterOptions();
  updateCrmEmptyState(null);
  toggleCrmLoading(true, 'Loading CRM accounts…');

  (async function loadCrmAccounts() {
    try {
      const res = await fetch(`${API_BASE}/data/light`);
      const data = await res.json();

      if ($.fn.DataTable.isDataTable('#accountTable')) {
        $('#accountTable').DataTable().destroy();
        accountTableInstance = null;
        updateCrmEmptyState(null);
      }

      const tableBody = document.getElementById('accountTableBody');
      tableBody.innerHTML = '';

      if (!Array.isArray(data) || data.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="7">No data found</td></tr>';
        populateContractFilter([]);
        populateStatusFilter([]);
        toggleCrmLoading(false);
        return;
      }

      const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase().trim();
      const showPriorityColumn = allowedEmails.includes(currentUserEmail);

      const rowsHtml = data.map(item => {
        const contractTxt = item.contract || '<span class="placeholder">No hires yet</span>';
        const trrTxt = fmtMoney(item.trr) || '<span class="placeholder">$0</span>';
        const tsfTxt = fmtMoney(item.tsf) || '<span class="placeholder">$0</span>';
        const tsrTxt = fmtMoney(item.tsr) || '<span class="placeholder">$0</span>';
        const priorityRaw   = (item.priority || '').toString().trim();
        const priorityUpper = priorityRaw.toUpperCase();
        const priorityClass = priorityUpper
          ? 'priority-' + priorityUpper.toLowerCase()
          : 'priority-empty';
        return `
          <tr data-id="${item.account_id}">
            <td>${item.client_name || '—'}</td>
            <td class="status-td" data-id="${item.account_id}" data-order="99">
              <span class="chip chip--loading" aria-label="Loading status">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              </span>
            </td>
            <td class="sales-lead-cell">
              ${(item.account_manager || item.account_manager_name)
                ? getAccountSalesLeadCell(item)
                : '<span class="placeholder">Unassigned</span>'}
            </td>
            <td class="muted-cell">${contractTxt}</td>
            <td>${trrTxt}</td>
            <td>${tsfTxt}</td>
            <td>${tsrTxt}</td>
            ${showPriorityColumn ? `
              <td>
                <select
                  class="priority-select ${priorityClass}"
                  data-id="${item.account_id}">
                  <option value="" ${priorityUpper ? '' : 'selected'}> </option>
                  <option value="A" ${priorityUpper === 'A' ? 'selected' : ''}>A</option>
                  <option value="B" ${priorityUpper === 'B' ? 'selected' : ''}>B</option>
                  <option value="C" ${priorityUpper === 'C' ? 'selected' : ''}>C</option>
                </select>
              </td>` : ``}
          </tr>`;
        }).join('');
      tableBody.innerHTML = rowsHtml;

      const rowById = new Map(
        [...document.querySelectorAll('#accountTableBody tr')].map(r => [Number(r.dataset.id), r])
      );
      const ids = data.map(x => Number(x.account_id)).filter(Boolean);

      const contractLabels = new Set();
      data.forEach(item => {
        const row = rowById.get(Number(item.account_id));
        const meta = decorateRowFilterMeta(row, item);
        if (meta?.contractLabel) contractLabels.add(meta.contractLabel);
      });
      populateContractFilter(Array.from(contractLabels));
      augmentSalesLeadFilterWithData(data);

      const th3 = document.querySelector('#accountTable thead tr th:nth-child(3)');
      if (th3) th3.textContent = 'Sales Lead';

      if (showPriorityColumn) {
        const th = document.createElement('th');
        th.textContent = 'Priority';
        document.querySelector('#accountTable thead tr').appendChild(th);
      }

      const tbodyEl = tableBody;
      tbodyEl.addEventListener('click', (e) => {
        if (e.target.closest('select.priority-select, option, input, button, a, label')) return;
        const row = e.target.closest('tr[data-id]');
        if (!row) return;
        const id = row.getAttribute('data-id');
        if (!id) return;
        const url = `account-details.html?id=${id}`;
        window.open(url, '_blank', 'noopener,noreferrer');
      });
      tbodyEl.addEventListener('mousedown', (e) => {
        if (e.target.closest('select.priority-select')) e.stopPropagation();
      });

      const statusWorkflowPromise = kickoffCrmStatusPipeline({ ids, rowById });

      const $tbl = $('#accountTable');
      const table = $tbl.DataTable({
        responsive: true,
        pageLength: 50,
        deferRender: true,
        dom: 'lrtip',
        lengthMenu: [[50, 100, 150], [50, 100, 150]],
        order: [[1, 'asc']],
        language: {
          search: "🔍 Buscar:",
          lengthMenu: "Mostrar _MENU_ registros por página",
          paginate: {
            previous: "Anterior",
            next: "Siguiente"
          }
        },
        initComplete() {
          accountTableInstance = this.api();
          updateCrmEmptyState(accountTableInstance);
          toggleCrmLoading(false);
          statusWorkflowPromise.then(({ assignments, summary }) => {
            if (accountTableInstance) {
              accountTableInstance.rows().invalidate('dom');
              accountTableInstance.order([1, 'asc']).draw(false);
            }
          });
        }
      });

      accountTableInstance = table;
      registerAccountTableFilters(table);
      $tbl.on('draw.dt', () => updateCrmEmptyState(table));
      updateCrmEmptyState(table);

      const lengthMenu = document.querySelector('#accountTable_length');
      const customLengthContainer = document.getElementById('dataTablesLengthTarget');
      if (lengthMenu && customLengthContainer) customLengthContainer.appendChild(lengthMenu);

      const clientSearchInput = document.getElementById('searchClientInput');
      if (clientSearchInput) {
        clientSearchInput.addEventListener('input', function () {
          table.column(0).search(this.value, true, false).draw();
        });
      }

      tbodyEl.addEventListener('change', async (e) => {
        const select = e.target.closest('.priority-select');
        if (!select) return;

        const accountId = select.getAttribute('data-id');
        const newPriority = select.value;

        select.classList.remove('priority-a', 'priority-b', 'priority-c', 'priority-empty');
        if (!newPriority) select.classList.add('priority-empty');
        if (newPriority === 'A') select.classList.add('priority-a');
        if (newPriority === 'B') select.classList.add('priority-b');
        if (newPriority === 'C') select.classList.add('priority-c');

        try {
          await fetch(`${API_BASE}/accounts/${accountId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ priority: newPriority || null })
          });
          console.log(`✅ Priority updated for account ${accountId}`);
        } catch (error) {
          console.error('❌ Error updating priority:', error);
        }
      });
    } catch (err) {
      console.error('Error fetching account data:', err);
      toggleCrmLoading(false);
    }
  })();

  /* ---------- New account form (create) ---------- */
  const form = document.querySelector('.popup-form');
  if (form) {
    // Lead source + referral visibility
    const sourceSelect = form.querySelector('select[name="where_come_from"]');
    loadReferralClients();
    if (sourceSelect) {
      updateReferralVisibility(sourceSelect);
      sourceSelect.addEventListener('change', () => {
        sourceSelect.setCustomValidity('');
        updateReferralVisibility(sourceSelect);
      });
    }

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (sourceSelect && !sourceSelect.value) {
        sourceSelect.setCustomValidity('Please select a lead source');
        sourceSelect.reportValidity();
        return;
      }

      const formData = new FormData(form);
      const data = Object.fromEntries(formData.entries());

      // Normalize lead source + referral_source
      if (data.where_come_from != null) data.where_come_from = String(data.where_come_from).trim();
      const isReferral = (data.where_come_from || '').toLowerCase() === 'referral';
      if (isReferral) {
        data.referal_source = (data.referal_source || '').trim() || null;
      } else {
        delete data.referal_source;
      }

      try {
        const response = await fetch(`${API_BASE}/accounts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });

        if (response.ok) {
          await response.json();
          alert('✅ Account created!');
          location.reload();
        } else {
          const errorText = await response.text();
          alert('Error: ' + errorText);
        }
      } catch (err) {
        console.error("❌ Error sending request:", err);
        alert('⚠️ Error sending request');
      }
    });
  }
});
/* =========================
   Log out FAB (igual que main)
   ========================= */
document.addEventListener('DOMContentLoaded', () => {
  const logoutFab = document.getElementById('logoutFab');
  if (!logoutFab) return;

  logoutFab.addEventListener('click', () => {
    // limpiar sesión local
    localStorage.removeItem('user_email');
    localStorage.removeItem('user_id');
    localStorage.removeItem('user_id_owner_email');
    localStorage.removeItem('user_avatar');

    sessionStorage.clear();

    // redirigir al login
    window.location.href = 'index.html';
  });
});
