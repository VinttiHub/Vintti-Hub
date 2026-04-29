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
  'lara@vintti.com','agostina@vintti.com', 'mariano@vintti.com',
  'mia@vintti.com', 'pgonzales@vintti.com'
];

const CRM_UNASSIGNED_SALES_LEAD_VALUE = '__unassigned__';
const CRM_FILTER_STATE = { salesLead: '', status: '', contract: '' };
const CRM_SALES_LEAD_OPTIONS = new Map();
let accountTableInstance = null;
let crmDataTableFilterRegistered = false;
let CRM_ALL_ACCOUNT_IDS = [];
const CRM_EXPORT_CACHE = new Map();
let crmRefreshInFlight = false;
let crmAutoRefreshTimer = null;
let crmAutoRefreshBound = false;
let crmLastAutoRefreshAt = 0;
let crmStorageSyncBound = false;
let crmSilentPollingId = null;
const CRM_STATUS_CACHE_KEY = 'crm_status_cache_v1';
const CRM_STATUS_CACHE_TTL_MS = 1000 * 60 * 60 * 12;
const CRM_DEBUG_ACCOUNT_NAMES = new Set(['prueba refresh crm']);

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

function hasBuyout(h) {
  if (!h) return false;
  const amount = h.buyout_dolar;
  const range = h.buyout_daterange;
  const hasAmount =
    amount !== null && amount !== undefined && String(amount).trim() !== '';
  const hasRange = range !== null && range !== undefined && String(range).trim() !== '';
  return hasAmount || hasRange;
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

function isCrmDebugAccount(item = {}) {
  const name = (item?.client_name || item?.account_name || '').toString().trim().toLowerCase();
  return CRM_DEBUG_ACCOUNT_NAMES.has(name);
}

function logCrmDebug(label, payload) {
  try {
    const current = JSON.parse(localStorage.getItem('crm_debug_trace') || '[]');
    current.push({ label, payload, ts: new Date().toISOString() });
    localStorage.setItem('crm_debug_trace', JSON.stringify(current.slice(-50)));
  } catch {}
  console.warn(`[CRM DEBUG] ${label}`, payload);
}

function readCrmStatusCache() {
  try {
    const raw = localStorage.getItem(CRM_STATUS_CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeCrmStatusCache(cache) {
  try {
    localStorage.setItem(CRM_STATUS_CACHE_KEY, JSON.stringify(cache || {}));
  } catch {}
}

function getCachedCrmStatus(accountId) {
  const id = Number(accountId);
  if (!id) return '';
  const cache = readCrmStatusCache();
  const entry = cache[id];
  if (!entry || !entry.status || !entry.ts) return '';
  if (Date.now() - Number(entry.ts) > CRM_STATUS_CACHE_TTL_MS) return '';
  return String(entry.status).trim();
}

function cacheCrmStatus(accountId, statusText) {
  const id = Number(accountId);
  const status = (statusText || '').toString().trim();
  if (!id || !status || status === '—') return;
  const cache = readCrmStatusCache();
  cache[id] = { status, ts: Date.now() };
  writeCrmStatusCache(cache);
}

function getPreferredAccountStatus(item = {}) {
  const cachedStatus = getCachedCrmStatus(item?.account_id);
  return (
    cachedStatus ||
    item?.computed_status ||
    item?.calculated_status ||
    item?.account_status ||
    '—'
  ).toString().trim() || '—';
}

// Calculate account status from opps + hires
function deriveStatusFrom(opps = [], hires = []) {
  const hasCandidates = Array.isArray(hires) && hires.length > 0;
  const anyActiveCandidate = hasCandidates && hires.some(isActiveHire);
  const hasBuyoutCandidate = Array.isArray(hires) && hires.some(hasBuyout);
  const allCandidatesInactive = hasCandidates && hires.every(h => !isActiveHire(h));

  const stages = (Array.isArray(opps) ? opps : []).map(o => normalizeStage(o.opp_stage || o.stage));
  const hasOpps = stages.length > 0;
  const hasPipeline = stages.some(s => s === 'pipeline');
  const allLost = hasOpps && stages.every(s => s === 'lost');

  if (anyActiveCandidate || hasBuyoutCandidate) return 'Active Client';
  if (allCandidatesInactive) return 'Inactive Client';
  if (!hasOpps && !hasCandidates) return 'Lead';
  if (allLost && !hasCandidates) return 'Lead Lost';
  if (hasPipeline) return 'Lead in Process';

  if (!hasOpps && hasCandidates) return 'Inactive Client';
  return 'Lead in Process';
}

function deriveContractTypeFromCandidates(hires = []) {
  if (!Array.isArray(hires) || hires.length === 0) return null;
  let hasStaffing = false;
  let hasRecruitingOrBuyout = false;
  hires.forEach(hire => {
    if (!hire || !isActiveHire(hire)) return;
    const model = (hire.opp_model || '').toLowerCase();
    if (model.includes('staff')) hasStaffing = true;
    if (model.includes('recruit')) hasRecruitingOrBuyout = true;
    if (hasBuyout(hire)) hasRecruitingOrBuyout = true;
  });
  if (hasStaffing && hasRecruitingOrBuyout) return 'Mix';
  if (hasStaffing) return 'Staffing';
  if (hasRecruitingOrBuyout) return 'Recruiting';
  return null;
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

function updateCrmLoadingProgress(done = 0, total = 0) {
  const bar = document.getElementById('crmLoadingBar');
  const percentEl = document.getElementById('crmLoadingPercent');
  const track = document.getElementById('crmLoadingProgress');
  if (!bar || !percentEl || !track) return;
  const safeTotal = Math.max(0, Number(total) || 0);
  const safeDone = Math.max(0, Math.min(safeTotal, Number(done) || 0));

  if (safeTotal <= 0) {
    track.style.display = 'none';
    percentEl.textContent = '';
    bar.style.width = '0%';
    return;
  }

  const pct = Math.max(0, Math.min(100, Math.round((safeDone / safeTotal) * 100)));
  track.style.display = 'block';
  bar.style.width = pct + '%';
  percentEl.textContent = `${pct}% (${safeDone}/${safeTotal})`;
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

  const statusRaw = getPreferredAccountStatus(item);
  row.dataset.statusLabel = statusRaw || '—';
  row.dataset.statusCode = norm(statusRaw || '—');
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

function csvSafe(value) {
  const text = value === null || value === undefined ? '' : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function csvMoneyValue(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function csvTextValue(value, fallback = '—') {
  const text = value === null || value === undefined ? '' : String(value).trim();
  return text || fallback;
}

function csvNullableTextValue(value) {
  if (value === null || value === undefined) return '';
  const text = String(value).trim();
  const isoDateMatch = text.match(/\d{4}-\d{2}-\d{2}/);
  return isoDateMatch ? isoDateMatch[0] : text;
}

function buildCrmExportRecord(item = {}) {
  const accountId = Number(item.account_id);
  if (!accountId) return null;
  const status = getPreferredAccountStatus(item);
  const salesLead = (item.account_manager_name || item.account_manager || 'Unassigned').toString().trim() || 'Unassigned';
  const contract = deriveContractLabel(item.contract);
  const priority = (item.priority || '').toString().trim().toUpperCase();
  return {
    accountId,
    clientName: (item.client_name || '—').toString().trim() || '—',
    status,
    salesLead,
    leadSource: csvTextValue(item.where_come_from),
    referralSource: csvTextValue(item.referal_source),
    contract,
    trr: csvMoneyValue(item.trr),
    tsf: csvMoneyValue(item.tsf),
    tsr: csvMoneyValue(item.tsr),
    priority
  };
}

function primeCrmExportCache(items = []) {
  CRM_EXPORT_CACHE.clear();
  (Array.isArray(items) ? items : []).forEach(item => {
    const row = buildCrmExportRecord(item);
    if (row) CRM_EXPORT_CACHE.set(row.accountId, row);
  });
}

function updateCrmExportCache(accountId, patch = {}) {
  const id = Number(accountId);
  if (!id) return;
  const current = CRM_EXPORT_CACHE.get(id) || {
    accountId: id,
    clientName: '—',
    status: '—',
    salesLead: 'Unassigned',
    leadSource: '—',
    referralSource: '—',
    contract: 'No Contract',
    trr: 0,
    tsf: 0,
    tsr: 0,
    priority: ''
  };
  CRM_EXPORT_CACHE.set(id, { ...current, ...patch });
}

async function hydrateCrmExportAccountRow(accountId, row = null) {
  const id = Number(accountId);
  if (!id) return row;

  const currentRow = row || CRM_EXPORT_CACHE.get(id);
  const currentLeadSource = (currentRow?.leadSource || '').toString().trim();
  const currentReferralSource = (currentRow?.referralSource || '').toString().trim();
  const hasLeadSource = currentLeadSource && currentLeadSource !== '—';
  const hasReferralSource = currentReferralSource && currentReferralSource !== '—';
  if (currentRow && hasLeadSource && hasReferralSource) return currentRow;

  try {
    const res = await fetch(`${API_BASE}/accounts/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`Account HTTP ${res.status}`);
    const account = await res.json();
    const patch = {
      leadSource: csvTextValue(account?.where_come_from),
      referralSource: csvTextValue(account?.referal_source)
    };
    updateCrmExportCache(id, patch);
    return { ...(currentRow || {}), ...patch };
  } catch (err) {
    console.warn(`Could not hydrate account sources for CSV export on account ${id}:`, err);
    return currentRow;
  }
}

function getOrderedCrmExportIds() {
  if (accountTableInstance) {
    const indexes = accountTableInstance.rows({ search: 'applied', order: 'applied' }).indexes().toArray();
    const ids = indexes
      .map(index => accountTableInstance.row(index).node())
      .filter(Boolean)
      .map(node => Number(node.dataset.id))
      .filter(Boolean);
    if (ids.length) return ids;
  }
  return Array.from(document.querySelectorAll('#accountTableBody tr[data-id]'))
    .map(row => Number(row.dataset.id))
    .filter(Boolean);
}

function setCrmExportButtonState(isLoading) {
  const btn = document.getElementById('crmExportCsvBtn');
  if (!btn) return;
  btn.disabled = Boolean(isLoading);
  btn.textContent = isLoading ? 'Exporting...' : 'Download Excel';
}

function normalizeCrmExportCandidate(detail, candidate, buyout) {
  const staffingEndDate = detail?.end_date || '';
  if (buyout) {
    return {
      ...(detail || {}),
      candidate_id: candidate?.candidate_id ?? detail?.candidate_id ?? '',
      name: candidate?.full_name || buyout?.candidate_name || detail?.name || '—',
      status: 'active',
      opp_model: 'Recruiting',
      start_date: staffingEndDate || buyout?.start_date || detail?.start_date || '',
      end_date: staffingEndDate || buyout?.end_date || detail?.end_date || '',
      employee_salary: buyout?.salary ?? detail?.employee_salary ?? '',
      employee_revenue_recruiting: buyout?.revenue ?? detail?.employee_revenue_recruiting ?? detail?.employee_revenue ?? '',
      employee_revenue: buyout?.revenue ?? detail?.employee_revenue ?? '',
      referral_dolar: buyout?.referral ?? detail?.referral_dolar ?? '',
      referral_daterange: buyout?.referral_date_range ?? detail?.referral_daterange ?? '',
      buyout_id: buyout?.buyout_id ?? '',
      inactive_reason: detail?.inactive_reason ?? '',
      inactive_comments: detail?.inactive_comments ?? ''
    };
  }

  return {
    ...(detail || {}),
    candidate_id: candidate?.candidate_id ?? detail?.candidate_id ?? '',
    name: candidate?.full_name || detail?.name || '—',
    status: detail?.status || candidate?.status || 'active',
    inactive_reason: detail?.inactive_reason ?? '',
    inactive_comments: detail?.inactive_comments ?? ''
  };
}

async function fetchCrmExportCandidateSheets(accountId) {
  if (!accountId) return { active: [], inactive: [] };
  try {
    const [contextRes, detailRes, buyoutsRes] = await Promise.all([
      fetch(`${API_BASE}/public/bonus_request/context?account_id=${encodeURIComponent(accountId)}`),
      fetch(`${API_BASE}/accounts/${accountId}/opportunities/candidates`),
      fetch(`${API_BASE}/accounts/${accountId}/buyouts`)
    ]);

    if (!contextRes.ok) throw new Error(`Bonus context HTTP ${contextRes.status}`);

    const contextData = await contextRes.json();
    const activeCandidates = Array.isArray(contextData?.candidates) ? contextData.candidates : [];
    const activeIds = new Set(
      activeCandidates
        .filter(candidate => (candidate?.status || '').toString().trim().toLowerCase() === 'active')
        .map(candidate => Number(candidate?.candidate_id))
        .filter(Boolean)
    );

    let detailCandidates = [];
    if (detailRes.ok) {
      const detailData = await detailRes.json();
      detailCandidates = Array.isArray(detailData) ? detailData : [];
    } else {
      console.warn(`Could not load detailed candidate rows for CSV export on account ${accountId}: HTTP ${detailRes.status}`);
    }

    let buyouts = [];
    if (buyoutsRes.ok) {
      const buyoutsData = await buyoutsRes.json();
      buyouts = Array.isArray(buyoutsData) ? buyoutsData : [];
    } else {
      console.warn(`Could not load buyout rows for CSV export on account ${accountId}: HTTP ${buyoutsRes.status}`);
    }

    const detailById = new Map();
    detailCandidates.forEach(candidate => {
      const id = Number(candidate?.candidate_id);
      if (!id) return;

      const prev = detailById.get(id);
      if (!prev) {
        detailById.set(id, candidate);
        return;
      }

      const prevModel = (prev?.opp_model || '').toString().trim().toLowerCase();
      const nextModel = (candidate?.opp_model || '').toString().trim().toLowerCase();
      const prevActive = (prev?.status || '').toString().trim().toLowerCase() === 'active';
      const nextActive = (candidate?.status || '').toString().trim().toLowerCase() === 'active';

      const shouldReplace =
        (nextModel === 'recruiting' && prevModel !== 'recruiting') ||
        (nextModel === prevModel && nextActive && !prevActive);

      if (shouldReplace) detailById.set(id, candidate);
    });

    const buyoutByCandidateId = new Map();
    buyouts.forEach(buyout => {
      const id = Number(buyout?.candidate_id);
      if (!id) return;
      const prev = buyoutByCandidateId.get(id);
      const prevId = Number(prev?.buyout_id) || 0;
      const nextId = Number(buyout?.buyout_id) || 0;
      if (!prev || nextId > prevId) buyoutByCandidateId.set(id, buyout);
    });

    const active = activeCandidates.map((candidate = {}) => {
      const id = Number(candidate.candidate_id);
      const detail = id ? detailById.get(id) : null;
      const buyout = id ? buyoutByCandidateId.get(id) : null;
      return normalizeCrmExportCandidate(detail, candidate, buyout);
    }).filter(candidate => activeIds.has(Number(candidate.candidate_id)));

    const inactive = detailCandidates
      .filter(candidate => {
        const id = Number(candidate?.candidate_id);
        if (!id || activeIds.has(id)) return false;
        return (candidate?.status || '').toString().trim().toLowerCase() === 'inactive';
      })
      .map(candidate => normalizeCrmExportCandidate(candidate, candidate, null));

    return { active, inactive };
  } catch (err) {
    console.warn(`Could not load candidates for CSV export on account ${accountId}:`, err);
    return { active: [], inactive: [] };
  }
}

function buildCrmCandidateExportRows(accountRow, candidates = [], { includeEmptyAccountRow = false } = {}) {
  const candidateList = Array.isArray(candidates) ? candidates : [];
  if (!candidateList.length) {
    if (!includeEmptyAccountRow) return [];
    return [[
      accountRow.accountId,
      accountRow.clientName,
      accountRow.status,
      accountRow.salesLead,
      accountRow.leadSource,
      accountRow.referralSource,
      accountRow.contract,
      accountRow.trr,
      accountRow.tsf,
      accountRow.tsr,
      accountRow.priority,
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      '',
      ''
    ]];
  }

  return candidateList.map((candidate = {}) => [
    accountRow.accountId,
    accountRow.clientName,
    accountRow.status,
    accountRow.salesLead,
    accountRow.leadSource,
    accountRow.referralSource,
    accountRow.contract,
    accountRow.trr,
    accountRow.tsf,
    accountRow.tsr,
    accountRow.priority,
    candidate.candidate_id ?? '',
    csvTextValue(candidate.name),
    csvTextValue(candidate.status ?? (candidate.end_date ? 'inactive' : 'active')),
    csvTextValue(candidate.opp_model),
    csvTextValue(candidate.opp_position_name),
    csvNullableTextValue(candidate.start_date),
    csvNullableTextValue(candidate.end_date),
    candidate.employee_fee ?? '',
    candidate.employee_salary ?? '',
    candidate.employee_revenue_recruiting ?? candidate.employee_revenue ?? '',
    csvNullableTextValue(candidate.inactive_reason),
    csvNullableTextValue(candidate.inactive_comments)
  ]);
}

function downloadCrmCsvFile({ headers = [], rows = [], filename }) {
  const lines = [headers.map(csvSafe).join(',')];
  rows.forEach(values => {
    lines.push(values.map(csvSafe).join(','));
  });
  const blob = new Blob([`${lines.join('\n')}\n`], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(link.href);
}

async function downloadCrmCsv() {
  const orderedIds = getOrderedCrmExportIds();
  if (!orderedIds.length) {
    alert('No data available to export.');
    return;
  }

  const headers = [
    'Account ID',
    'Client Name',
    'Status',
    'Sales Lead',
    'lead_source',
    'referal_source',
    'Contract',
    'TRR',
    'TSF',
    'TSR',
    'Priority',
    'Candidate ID',
    'Candidate Name',
    'Candidate Status',
    'Opportunity Model',
    'Position',
    'Start Date',
    'End Date',
    'Employee Fee',
    'Employee Salary',
    'Employee Revenue',
    'Inactive Reason',
    'Inactive Comments'
  ];
  const activeRows = [];
  const inactiveRows = [];

  setCrmExportButtonState(true);
  toggleCrmLoading(true, 'Preparing CRM active and inactive CSV files...');
  updateCrmLoadingProgress(0, orderedIds.length);

  try {
    let doneCount = 0;
    const tasks = orderedIds.map(id => async () => {
      let row = CRM_EXPORT_CACHE.get(id);
      if (!row) {
        doneCount += 1;
        updateCrmLoadingProgress(doneCount, orderedIds.length);
        return;
      }
      row = await hydrateCrmExportAccountRow(id, row);
      const sheetData = await fetchCrmExportCandidateSheets(id);
      buildCrmCandidateExportRows(row, sheetData.active, { includeEmptyAccountRow: true })
        .forEach(values => activeRows.push(values));
      buildCrmCandidateExportRows(row, sheetData.inactive, { includeEmptyAccountRow: false })
        .forEach(values => inactiveRows.push(values));
      doneCount += 1;
      updateCrmLoadingProgress(doneCount, orderedIds.length);
    });

    await runWithConcurrency(tasks, 6);

    if (!activeRows.length && !inactiveRows.length) {
      alert('No rows matched the current table filters.');
      return;
    }

    const date = new Date().toISOString().slice(0, 10);
    downloadCrmCsvFile({
      headers,
      rows: activeRows,
      filename: `crm_active_${date}.csv`
    });
    if (inactiveRows.length) {
      setTimeout(() => {
        downloadCrmCsvFile({
          headers,
          rows: inactiveRows,
          filename: `crm_inactive_${date}.csv`
        });
      }, 150);
    }
  } finally {
    toggleCrmLoading(false);
    updateCrmLoadingProgress(0, 0);
    setCrmExportButtonState(false);
  }
}

function initCrmExportButton() {
  const btn = document.getElementById('crmExportCsvBtn');
  if (!btn) return;
  btn.textContent = 'Download CSV';
  btn.addEventListener('click', downloadCrmCsv);
}

function initHubSpotSyncButton() {
  const btn = document.getElementById('crmHubSpotSyncBtn');
  if (!btn) return;
  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase().trim();
  if (!allowedEmails.includes(currentUserEmail)) {
    btn.style.display = 'none';
    return;
  }
  const originalText = btn.textContent || 'Sync HubSpot';

  btn.addEventListener('click', async () => {
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = 'Syncing...';

    try {
      const response = await fetch(`${API_BASE}/hubspot/sync/mariano-sql-contacts`, {
        method: 'POST'
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || payload.success === false) {
        throw new Error(payload.error || `HubSpot sync failed (${response.status})`);
      }

      const created = Number(payload.created || 0);
      const linked = Number(payload.linked || payload.updated || 0);
      const errors = Array.isArray(payload.errors) ? payload.errors.length : 0;
      alert(`HubSpot sync complete. Created: ${created}. Linked existing: ${linked}. Errors: ${errors}.`);
      window.location.reload();
    } catch (err) {
      console.error('HubSpot sync failed:', err);
      alert(`HubSpot sync failed: ${err.message || err}`);
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  });
}

function formatDuplicateAccountMessage(payload = {}) {
  const matches = Array.isArray(payload.matches) ? payload.matches : [];
  if (!matches.length) return 'This account may already exist.';
  const lines = matches.slice(0, 3).map(match => {
    const name = match.client_name || 'Unnamed account';
    const email = match.mail ? ` · ${match.mail}` : '';
    const id = match.account_id ? `#${match.account_id}` : '';
    const type = match.match_type ? ` (${match.match_type})` : '';
    return `${name}${id ? ` ${id}` : ''}${email}${type}`;
  });
  return `This account may already exist:\n\n${lines.join('\n')}`;
}

async function checkManualAccountDuplicate(data = {}) {
  const response = await fetch(`${API_BASE}/accounts/duplicate-check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name: data.name || '',
      mail: data.mail || ''
    })
  });
  if (!response.ok) return { duplicate: false, matches: [] };
  return response.json();
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

async function fetchJsonOrEmptyArray(url, label) {
  const res = await fetch(url);
  if (res.status === 404 || res.status === 204) return [];
  if (!res.ok) throw new Error(`${label} HTTP ${res.status}`);
  const payload = await res.json();
  return Array.isArray(payload) ? payload : [];
}

async function fetchAccountOppsAndHires(accountId) {
  const [opps, hires] = await Promise.all([
    fetchJsonOrEmptyArray(`${API_BASE}/accounts/${accountId}/opportunities`, 'Opps'),
    fetchJsonOrEmptyArray(`${API_BASE}/accounts/${accountId}/opportunities/candidates`, 'Candidates')
  ]);
  return { opps, hires };
}

async function fetchAccountStatusDetails(accountId) {
  const { opps, hires } = await fetchAccountOppsAndHires(accountId);
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
  const changedStatusIds = new Set();

  function paintStatusForAccount(id, status) {
    const row = rowById.get(id);
    if (!row) return;
    const td = row.querySelector('td.status-td');
    const normalizedStatus = (status || '—').toString().trim() || '—';
    const prevStatus = (row.dataset.statusLabel || '').toString().trim();
    if (td) {
      td.innerHTML = renderAccountStatusChip(normalizedStatus);
      td.dataset.order = String(statusRank(normalizedStatus));
    }
    row.dataset.statusLabel = normalizedStatus;
    row.dataset.statusCode = norm(normalizedStatus);
    updateCrmExportCache(id, { status: normalizedStatus });
    if (normalizedStatus !== prevStatus) {
      changedStatusIds.add(id);
    }

    const clientName = row.querySelector('td')?.textContent?.trim() || '';
    if (CRM_DEBUG_ACCOUNT_NAMES.has(clientName.toLowerCase())) {
      logCrmDebug('Computed status', {
        accountId: id,
        clientName,
        prevStatus,
        nextStatus: normalizedStatus
      });
    }
  }

  function mergeSummary(resp) {
    let added = 0;

    if (Array.isArray(resp)) {
      for (const it of resp) {
        const id = Number(it.account_id ?? it.id ?? it.accountId);
        if (!id) continue;
        const status = it.status ?? it.calculated_status ?? it.value ?? '—';
        if (!summary[id]) added++;
        summary[id] = { status };
        paintStatusForAccount(id, status);
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
        paintStatusForAccount(id, status);
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
        paintStatusForAccount(id, derivedStatus);
      } catch (err) {
        if (!summary[id]) summary[id] = { status: '—' };
        console.warn(`⚠️ Could not re-derive status for account ${id}:`, err);
      } finally {
        if (!hadSummary) onProgress?.(1);
      }
    });
    await runWithConcurrency(tasks, CONC_FALLBACK);
  }

  // 4) Persist using the same account PATCH route that account-details uses.
  if (changedStatusIds.size) {
    const patchTasks = Array.from(changedStatusIds).map(id => async () => {
      try {
        const statusValue = summary?.[id]?.status || '—';
        const row = rowById.get(id);
        const clientName = row?.querySelector('td')?.textContent?.trim() || '';
        if (CRM_DEBUG_ACCOUNT_NAMES.has(clientName.toLowerCase())) {
          logCrmDebug('Persisting status', {
            accountId: id,
            clientName,
            statusValue
          });
        }
        const res = await fetch(`${API_BASE}/accounts/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            account_status: statusValue
          })
        });
        if (CRM_DEBUG_ACCOUNT_NAMES.has(clientName.toLowerCase())) {
          let responseBody = null;
          try {
            responseBody = await res.clone().json();
          } catch {
            try {
              responseBody = await res.clone().text();
            } catch {
              responseBody = null;
            }
          }
          logCrmDebug('Persist status response', {
            accountId: id,
            clientName,
            ok: res.ok,
            status: res.status,
            body: responseBody
          });
        }
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
      } catch (err) {
        console.warn(`⚠️ Could not persist CRM status for account ${id}:`, err);
      }
    });
    await runWithConcurrency(patchTasks, 6);
  }

  return summary;
}

/* =========================
   4b) Contract persistence
   ========================= */

function buildContractUpdatePayload(items = []) {
  const map = new Map();
  items.forEach(item => {
    const accountId = Number(item?.account_id);
    if (!accountId) return;
    const contract = (item?.contract || '').toString().trim();
    if (!contract) return;
    map.set(accountId, contract);
  });
  return Array.from(map.entries()).map(([accountId, contract]) => ({ accountId, contract }));
}

async function persistAccountContracts(items = []) {
  const updates = buildContractUpdatePayload(items);
  if (!updates.length) return { total: 0, persisted: 0 };
  let persisted = 0;
  const tasks = updates.map(({ accountId, contract }) => async () => {
    try {
      const res = await fetch(`${API_BASE}/accounts/${accountId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contract })
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      persisted++;
    } catch (err) {
      console.warn(`⚠️ Could not persist contract for account ${accountId}:`, err);
    }
  });
  await runWithConcurrency(tasks, 6);
  return { total: updates.length, persisted };
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
    'agustina@vintti.com': 'agustina_valentini.png',
    'mariano@vintti.com': 'mariano.png',
    'mia@vintti.com': 'mia_cavanagh.png',
    'vianney@vintti.com': 'vianney.png'
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
  if (s.includes('mia')) return 'MC';
  return '--';
}

function badgeClassForSalesLead(key='') {
  const s = key.toLowerCase();
  if (s.includes('bahia'))   return 'bl';
  if (s.includes('lara'))    return 'lr';
  if (s.includes('agustin')) return 'am';
  if (s.includes('mariano')) return 'ms';   // ✅ ADD
  if (s.includes('mia')) return '';
  return '';
}

function emailFromNameGuess(name='') {
  const s = name.toLowerCase();
  if (s.includes('bahia'))   return 'bahia@vintti.com';
  if (s.includes('lara'))    return 'lara@vintti.com';
  if (s.includes('agustin')) return 'agustin@vintti.com';
  if (s.includes('mariano')) return 'mariano@vintti.com'; // ✅ ADD
  if (s.includes('mia')) return 'mia@vintti.com';
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
  if (s === 'active client') return null;
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
  const accountId = Number(rowEl.dataset.id);
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
  updateCrmExportCache(accountId, {
    salesLead: (meta.label || displayName || normalizedEmail || 'Unassigned').toString().trim() || 'Unassigned'
  });
  return meta;
}

function updateRowStatus(rowEl, statusText) {
  if (!rowEl) return;
  const accountId = Number(rowEl.dataset.id);
  const td = rowEl.querySelector('td.status-td');
  if (td) {
    td.innerHTML = renderAccountStatusChip(statusText);
    td.dataset.order = String(statusRank(statusText));
  }
  rowEl.dataset.statusLabel = statusText;
  rowEl.dataset.statusCode = norm(statusText);
  updateCrmExportCache(accountId, { status: (statusText || '—').toString().trim() || '—' });
  cacheCrmStatus(accountId, statusText);
}

function updateRowContract(rowEl, contractText) {
  if (!rowEl) return;
  const accountId = Number(rowEl.dataset.id);
  const cell = rowEl.querySelector('td.muted-cell');
  if (cell) {
    if (contractText) {
      cell.textContent = contractText;
    } else {
      cell.innerHTML = '<span class="placeholder">No hires yet</span>';
    }
  }
  const label = deriveContractLabel(contractText);
  rowEl.dataset.contractLabel = label;
  rowEl.dataset.contractCode = norm(label);
  updateCrmExportCache(accountId, { contract: label });
}

function getRowContractValue(rowEl) {
  const label = (rowEl?.dataset?.contractLabel || '').toString().trim();
  if (!label || label === 'No Contract') return '';
  return label;
}

async function fetchSuggestedSalesLeadForAccount(accountId) {
  if (!accountId) return null;
  try {
    const res = await fetch(`${API_BASE}/accounts/${accountId}/sales-lead/suggest`, { credentials: 'include' });
    if (!res.ok) return null;
    const data = await res.json();
    const suggested = (data?.suggested_sales_lead || '').toString().trim().toLowerCase();
    return suggested || null;
  } catch (err) {
    console.warn('⚠️ Could not fetch sales lead suggestion:', err);
    return null;
  }
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

    if (status === 'lead in process' || status === 'active client') {
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
   6b) CRM refresh (status + contract + sales lead)
   ========================= */

function getCurrentUserEmail() {
  return (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase()
    .trim();
}

function setCrmRefreshButtonState(btn, isLoading) {
  if (!btn) return;
  btn.disabled = isLoading;
  btn.classList.toggle('is-loading', isLoading);
  btn.textContent = isLoading ? 'Refreshing...' : 'Refresh';
}

function scheduleCrmAutoRefresh(reason = 'auto', delay = 250) {
  if (!CRM_ALL_ACCOUNT_IDS.length) return;
  if (crmAutoRefreshTimer) window.clearTimeout(crmAutoRefreshTimer);
  crmAutoRefreshTimer = window.setTimeout(() => {
    crmAutoRefreshTimer = null;
    refreshCrmStatusesOnly(null, { silent: true });
  }, Math.max(0, Number(delay) || 0));
}

function bindCrmAutoRefreshEvents() {
  if (crmAutoRefreshBound) return;
  crmAutoRefreshBound = true;

  window.addEventListener('focus', () => {
    scheduleCrmAutoRefresh('focus', 150);
  });

  window.addEventListener('pageshow', () => {
    scheduleCrmAutoRefresh('pageshow', 150);
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      scheduleCrmAutoRefresh('visibilitychange', 150);
      startCrmSilentPolling();
    } else {
      stopCrmSilentPolling();
    }
  });
}

function startCrmSilentPolling() {
  if (crmSilentPollingId) return;
  crmSilentPollingId = window.setInterval(() => {
    if (document.visibilityState !== 'visible') return;
    refreshCrmStatusesOnly(null, { silent: true });
  }, 30000);
}

function stopCrmSilentPolling() {
  if (!crmSilentPollingId) return;
  window.clearInterval(crmSilentPollingId);
  crmSilentPollingId = null;
}

async function refreshCrmDerivedFields(accountIds = null, { source = 'manual' } = {}) {
  const btn = document.getElementById('crmRefreshBtn');
  if (crmRefreshInFlight) return;

  const fallbackRows = Array.from(document.querySelectorAll('#accountTableBody tr[data-id]'));
  const fallbackIds = fallbackRows.map(row => Number(row.dataset.id)).filter(Boolean);
  const ids = (Array.isArray(accountIds) && accountIds.length)
    ? accountIds.slice()
    : (CRM_ALL_ACCOUNT_IDS.length ? CRM_ALL_ACCOUNT_IDS.slice() : fallbackIds);
  if (!ids.length) return;

  const now = Date.now();
  if (source !== 'manual' && now - crmLastAutoRefreshAt < 1500) return;
  crmLastAutoRefreshAt = now;
  crmRefreshInFlight = true;

  const isSilentRefresh = source !== 'manual';

  if (!isSilentRefresh) {
    setCrmRefreshButtonState(btn, true);
    toggleCrmLoading(true, 'Refreshing account status, contracts, and sales leads...');
    updateCrmLoadingProgress(0, ids.length);
  }

  try {
    let doneCount = 0;
    let changedRows = 0;
    const rowById = new Map(
      [...document.querySelectorAll('#accountTableBody tr[data-id]')].map(row => [Number(row.dataset.id), row])
    );
    const tasks = ids.map(accountId => async () => {
      if (!accountId) return;

      try {
        let opps = [];
        let hires = [];
        try {
          const payload = await fetchAccountOppsAndHires(accountId);
          opps = payload.opps;
          hires = payload.hires;
        } catch (err) {
          console.warn(`⚠️ Could not load data for account ${accountId}:`, err);
          return;
        }

        const derivedStatus = deriveStatusFrom(opps, hires);
        const derivedContract = deriveContractTypeFromCandidates(hires);
        const patch = {};

        const row = rowById.get(accountId) || null;
        const currentStatus = (row?.dataset?.statusLabel || '').toString().trim().toLowerCase();
        if (derivedStatus && derivedStatus.toLowerCase() !== currentStatus) {
          patch.account_status = derivedStatus;
        }

        const currentContract = row ? getRowContractValue(row) : '';
        if (derivedContract && derivedContract !== currentContract) {
          patch.contract = derivedContract;
        }

        let desiredManager = null;
        const normalizedStatus = (derivedStatus || '').toLowerCase().trim();
        if (normalizedStatus === 'active client') {
          desiredManager = 'lara@vintti.com';
        } else if (normalizedStatus === 'lead in process') {
          desiredManager = await fetchSuggestedSalesLeadForAccount(accountId);
        }

        const currentLead = (row?.dataset?.salesLeadCode || '').toString().toLowerCase().trim();
        if (desiredManager && desiredManager !== currentLead) {
          patch.account_manager = desiredManager;
        }

        if (!Object.keys(patch).length) return;

        const res = await fetch(`${API_BASE}/accounts/${accountId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(patch)
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);

        if (row) {
          if (patch.account_status) updateRowStatus(row, derivedStatus);
          if (patch.contract) updateRowContract(row, derivedContract);
          if (patch.account_manager) updateRowSalesLead(row, patch.account_manager, patch.account_manager);
          changedRows += 1;
        }
      } catch (err) {
        console.warn(`⚠️ Could not update derived fields for account ${accountId}:`, err);
      } finally {
        doneCount += 1;
        if (!isSilentRefresh) updateCrmLoadingProgress(doneCount, ids.length);
      }
    });

    await runWithConcurrency(tasks, 6);

    const shouldRedrawTable = changedRows > 0;
    if (accountTableInstance && shouldRedrawTable) {
      accountTableInstance.rows().invalidate('dom');
    }

    const contractLabels = new Set();
    const statusLabels = new Set();
    rowById.forEach(row => {
      const statusTxt = (row.dataset.statusLabel || '').toString().trim();
      if (statusTxt && statusTxt !== '—') statusLabels.add(statusTxt);
      const contractTxt = (row.dataset.contractLabel || '').toString().trim();
      if (contractTxt) contractLabels.add(contractTxt);
    });
    if (shouldRedrawTable) {
      populateContractFilter(Array.from(contractLabels));
      populateStatusFilter(Array.from(statusLabels));
    }

    if (accountTableInstance && shouldRedrawTable) {
      accountTableInstance.draw(false);
      updateCrmEmptyState(accountTableInstance);
    }
  } finally {
    if (!isSilentRefresh) {
      toggleCrmLoading(false);
      updateCrmLoadingProgress(0, 0);
      setCrmRefreshButtonState(btn, false);
    }
    crmRefreshInFlight = false;
  }
}

function initCrmRefreshButton() {
  const btn = document.getElementById('crmRefreshBtn');
  if (!btn) return;
  btn.style.display = 'inline-flex';
  btn.addEventListener('click', () => refreshCrmDerivedFields());
}

function applyCrmExternalAccountUpdate(accountId, patch = {}) {
  const id = Number(accountId);
  if (!id || !patch || typeof patch !== 'object') return;

  const row = document.querySelector(`#accountTableBody tr[data-id="${id}"]`);
  if (!row) return;

  if (patch.account_status) {
    updateRowStatus(row, patch.account_status);
  }
  if (Object.prototype.hasOwnProperty.call(patch, 'contract')) {
    updateRowContract(row, patch.contract || '');
  }
  if (patch.account_manager) {
    updateRowSalesLead(row, patch.account_manager, patch.account_manager_name || patch.account_manager);
  }

  if (accountTableInstance) {
    accountTableInstance.rows().invalidate('dom');
    accountTableInstance.draw(false);
    updateCrmEmptyState(accountTableInstance);
  }
}

function bindCrmStorageSync() {
  if (crmStorageSyncBound) return;
  crmStorageSyncBound = true;

  window.addEventListener('storage', (event) => {
    if (event.key !== 'crm_account_refresh' || !event.newValue) return;
    try {
      const payload = JSON.parse(event.newValue);
      const accountId = Number(payload?.account_id);
      const patch = payload?.patch;
      if (!accountId || !patch) return;
      applyCrmExternalAccountUpdate(accountId, patch);
    } catch (err) {
      console.warn('⚠️ Could not sync CRM update from another tab:', err);
    }
  });
}

async function refreshCrmStatusesOnly(accountIds = null, { silent = true } = {}) {
  const fallbackRows = Array.from(document.querySelectorAll('#accountTableBody tr[data-id]'));
  const fallbackIds = fallbackRows.map(row => Number(row.dataset.id)).filter(Boolean);
  const ids = (Array.isArray(accountIds) && accountIds.length)
    ? accountIds.slice()
    : (CRM_ALL_ACCOUNT_IDS.length ? CRM_ALL_ACCOUNT_IDS.slice() : fallbackIds);
  if (!ids.length || crmRefreshInFlight) return;

  const rowById = new Map(
    [...document.querySelectorAll('#accountTableBody tr[data-id]')].map(row => [Number(row.dataset.id), row])
  );

  crmRefreshInFlight = true;
  if (!silent) {
    toggleCrmLoading(true, 'Refreshing account statuses...');
    updateCrmLoadingProgress(0, ids.length);
  }

  try {
    let progressDone = 0;
    const summary = await computeAndPaintAccountStatuses({
      ids,
      rowById,
      onProgress: (doneOrInc, total) => {
        if (silent) return;
        if (typeof total === 'number' && total > 0) {
          progressDone = Number(doneOrInc) || 0;
        } else {
          progressDone += Number(doneOrInc) || 0;
        }
        updateCrmLoadingProgress(progressDone, ids.length);
      }
    });

    const statusLabels = new Set();
    ids.forEach(id => {
      const status = summary?.[id]?.status || '';
      if (status && status !== '—') statusLabels.add(status);
    });
    populateStatusFilter(Array.from(statusLabels));

    if (accountTableInstance) {
      accountTableInstance.rows().invalidate('dom');
      accountTableInstance.draw(false);
      updateCrmEmptyState(accountTableInstance);
    }
  } catch (err) {
    console.error('Error refreshing CRM statuses:', err);
  } finally {
    if (!silent) {
      toggleCrmLoading(false);
      updateCrmLoadingProgress(0, 0);
    }
    crmRefreshInFlight = false;
  }
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

function getSelectedReferralMode() {
  const current = document.querySelector('input[name="referral_source_mode"]:checked');
  return (current?.value || 'existing').toLowerCase();
}

function resetReferralMode() {
  const existing = document.querySelector('input[name="referral_source_mode"][value="existing"]');
  if (existing) existing.checked = true;
}

function updateReferralModeUI(isReferral) {
  const searchWrap = document.getElementById('referralSearchContainer');
  const otherWrap = document.getElementById('referralOtherContainer');
  const searchInput = document.getElementById('referralSourceInput');
  const otherInput = document.getElementById('referralOtherInput');

  const mode = isReferral ? getSelectedReferralMode() : 'existing';
  const showSearch = isReferral && mode !== 'other';
  const showOther = isReferral && mode === 'other';

  if (searchWrap) searchWrap.style.display = showSearch ? '' : 'none';
  if (otherWrap) otherWrap.style.display = showOther ? '' : 'none';

  if (searchInput) {
    searchInput.required = showSearch;
    if (!showSearch) searchInput.value = '';
  }
  if (otherInput) {
    otherInput.required = showOther;
    if (!showOther) otherInput.value = '';
  }
}

function updateReferralVisibility(sourceSelect) {
  const wrap  = document.getElementById('referralSourceWrapper');
  if (!wrap || !sourceSelect) return;

  const isReferral = String(sourceSelect.value || '').toLowerCase() === 'referral';
  wrap.style.display = isReferral ? '' : 'none';
  if (!isReferral) resetReferralMode();
  updateReferralModeUI(isReferral);
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
    'mia@vintti.com',
    'jazmin@vintti.com'
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
    'agustin@vintti.com',
    'lara@vintti.com',
    'constanza@vintti.com',
    'pilar@vintti.com',
    'julieta@vintti.com',
    'paz@vintti.com',
    'valentina@vintti.com'
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
    'mariano@vintti.com',
    'mia@vintti.com'
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
    'agustin@vintti.com',
    'lara@vintti.com',
    'constanza@vintti.com',
    'pilar@vintti.com',
    'angie@vintti.com',
    'agostina@vintti.com',
    'julieta@vintti.com',
    'paz@vintti.com'
  ]);

  candidateSearchLink.style.display = CANDIDATE_SEARCH_ALLOWED.has(email) ? 'flex' : 'none';
})();
// Summary / Equipments visibility
(() => {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  const summaryAllowed = [
    'agustin@vintti.com','bahia@vintti.com','angie@vintti.com',
    'lara@vintti.com','agostina@vintti.com','mariano@vintti.com',
    'mia@vintti.com','jazmin@vintti.com'
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
  logCrmDebug('crm.js boot', {
    path: window.location.pathname,
    href: window.location.href
  });
  initCrmFilterControls();
  initCrmRefreshButton();
  bindCrmAutoRefreshEvents();
  bindCrmStorageSync();
  startCrmSilentPolling();
  initCrmExportButton();
  initHubSpotSyncButton();
  loadSalesLeadFilterOptions();
  updateCrmEmptyState(null);
  toggleCrmLoading(true, 'Loading CRM accounts…');

  (async function loadCrmAccounts() {
    try {
      const res = await fetch(`${API_BASE}/data/light`);
      const data = await res.json();
      (Array.isArray(data) ? data : []).forEach(item => {
        if (!isCrmDebugAccount(item)) return;
        logCrmDebug('Initial /data/light row', {
          accountId: item.account_id,
          clientName: item.client_name,
          account_status: item.account_status,
          calculated_status: item.calculated_status,
          computed_status: item.computed_status,
          contract: item.contract,
          account_manager: item.account_manager
        });
      });

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
      primeCrmExportCache(data);

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
        const statusTxt = getPreferredAccountStatus(item);
        const statusOrder = statusRank(statusTxt);
        return `
          <tr data-id="${item.account_id}">
            <td>${item.client_name || '—'}</td>
            <td class="status-td" data-id="${item.account_id}" data-order="${statusOrder}">
              ${renderAccountStatusChip(statusTxt)}
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

      CRM_ALL_ACCOUNT_IDS = data
        .map(item => Number(item.account_id))
        .filter(Boolean);

      const rowById = new Map(
        [...document.querySelectorAll('#accountTableBody tr')].map(r => [Number(r.dataset.id), r])
      );

      const contractLabels = new Set();
      const statusLabels = new Set();
      data.forEach(item => {
        const row = rowById.get(Number(item.account_id));
        const meta = decorateRowFilterMeta(row, item);
        if (meta?.contractLabel) contractLabels.add(meta.contractLabel);
        const statusTxt = getPreferredAccountStatus(item);
        if (statusTxt && statusTxt !== '—') statusLabels.add(statusTxt);
      });
      populateContractFilter(Array.from(contractLabels));
      populateStatusFilter(Array.from(statusLabels));
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
          updateCrmExportCache(accountId, { priority: (newPriority || '').toUpperCase() });
          console.log(`✅ Priority updated for account ${accountId}`);
        } catch (error) {
          console.error('❌ Error updating priority:', error);
        }
      });

      await refreshCrmDerivedFields(CRM_ALL_ACCOUNT_IDS, { source: 'manual' });
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
      const referralModeRadios = form.querySelectorAll('input[name="referral_source_mode"]');
      referralModeRadios.forEach((radio) => {
        radio.addEventListener('change', () => {
          const isReferral = String(sourceSelect.value || '').toLowerCase() === 'referral';
          updateReferralModeUI(isReferral);
        });
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
      const referralMode = (data.referral_source_mode || 'existing').toLowerCase();
      if (isReferral) {
        const fromList = (data.referal_source || '').trim();
        const manualValue = (data.referal_source_other || '').trim();
        data.referal_source = (referralMode === 'other' ? manualValue : fromList) || null;
      } else {
        delete data.referal_source;
      }
      delete data.referal_source_other;
      delete data.referral_source_mode;

      try {
        const duplicatePayload = await checkManualAccountDuplicate(data);
        if (duplicatePayload.duplicate) {
          alert(formatDuplicateAccountMessage(duplicatePayload));
          return;
        }

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
          let errorPayload = null;
          try {
            errorPayload = errorText ? JSON.parse(errorText) : null;
          } catch {
            errorPayload = null;
          }
          if (response.status === 409 && errorPayload?.error === 'duplicate_account') {
            alert(formatDuplicateAccountMessage(errorPayload));
          } else {
            alert('Error: ' + (errorPayload?.message || errorText || 'Failed to create account'));
          }
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
