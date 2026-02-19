function dateInputValue(v) {
  if (!v) return '';
  const s = String(v).trim();

  // ya viene bien
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;

  // si viene timestamp "YYYY-MM-DDTHH:MM:SS..."
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
  if (m) return m[1];

  // último intento: parse
  const d = new Date(s);
  if (isNaN(d)) return '';
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
}

const API_BASE_URL =
  (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

let buyoutReloadTimer = null;
let ACCOUNT_DETAIL_RECORD = null;
let ACCOUNT_DETAIL_OPPORTUNITIES = [];
let ACCOUNT_DETAIL_CANDIDATES = [];
let ACCOUNT_OPPS_READY = false;
let ACCOUNT_CANDIDATES_READY = false;
let ACCOUNT_DERIVED_REFRESHING = false;
const ACCOUNT_RICH_COMMENT_HANDLES = { comments: null, painPoints: null };

function norm(value) {
  return (value || '').toString().toLowerCase().trim();
}

function normalizeStage(stage) {
  const val = norm(stage);
  if (/closed?[_\s-]?won|close[_\s-]?win/.test(val)) return 'won';
  if (/closed?[_\s-]?lost|close[_\s-]?lost/.test(val)) return 'lost';
  if (/(sourc|interview|negotiat|deep\s?dive)/.test(val)) return 'pipeline';
  return 'other';
}

function isActiveHire(hire = {}) {
  const st = norm(hire.status);
  if (st === 'active') return true;
  if (st === 'inactive') return false;
  const ed = (hire.end_date ?? '').toString().trim().toLowerCase();
  if (!ed || ed === 'null' || ed === 'none' || ed === 'undefined' || ed === '0000-00-00') return true;
  return false;
}

function hasBuyout(hire = {}) {
  const amount = hire.buyout_dolar;
  const range = hire.buyout_daterange;
  const hasAmount = amount !== null && amount !== undefined && String(amount).trim() !== '';
  const hasRange = range !== null && range !== undefined && String(range).trim() !== '';
  return hasAmount || hasRange;
}

function escapeAttribute(value) {
  return String(value).replace(/"/g, '&quot;');
}

function renderReplacementBadge(replacementOf) {
  if (replacementOf === null || replacementOf === undefined) return '';
  const idLabel = typeof replacementOf === 'number' ? replacementOf : String(replacementOf).trim();
  const label = idLabel ? `Replacement · ID ${idLabel}` : 'Replacement';
  const safeLabel = escapeAttribute(label);
  return `<span class="replacement-badge" data-label="${safeLabel}" role="img" aria-label="${safeLabel}">🔁</span>`;
}

function wrapContentWithBadge(content, replacementOf) {
  const badge = renderReplacementBadge(replacementOf);
  if (!badge) return content;
  return `<div class="cell-with-badge">${content}${badge}</div>`;
}

function deriveAccountStatusFromData(opps = [], hires = []) {
  const stages = (Array.isArray(opps) ? opps : []).map(opp => normalizeStage(opp.opp_stage || opp.stage));
  const hasOpps = stages.length > 0;
  const hasPipeline = stages.some(stage => stage === 'pipeline');
  const allLost = hasOpps && stages.every(stage => stage === 'lost');

  const candidates = Array.isArray(hires) ? hires : [];
  const hasCandidates = candidates.length > 0;
  const anyActiveCandidate = hasCandidates && candidates.some(isActiveHire);
  const hasBuyoutCandidate = hasCandidates && candidates.some(hasBuyout);
  const allCandidatesInactive = hasCandidates && candidates.every(candidate => !isActiveHire(candidate));

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

async function fetchSuggestedSalesLead(accountId) {
  if (!accountId) return null;
  try {
    const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/sales-lead/suggest`, { credentials: 'include' });
    if (!res.ok) return null;
    const data = await res.json();
    const suggested = (data?.suggested_sales_lead || '').toString().trim().toLowerCase();
    return suggested || null;
  } catch (err) {
    console.warn('⚠️ Could not fetch sales lead suggestion:', err);
    return null;
  }
}

function scheduleAccountDerivedRefresh() {
  if (!ACCOUNT_DETAIL_RECORD) return;
  if (!ACCOUNT_OPPS_READY || !ACCOUNT_CANDIDATES_READY) return;
  if (ACCOUNT_DERIVED_REFRESHING) return;
  ACCOUNT_DERIVED_REFRESHING = true;
  refreshAccountDerivedFields()
    .catch(err => console.error('❌ Error refreshing derived account info:', err))
    .finally(() => { ACCOUNT_DERIVED_REFRESHING = false; });
}

async function refreshAccountDerivedFields() {
  const base = ACCOUNT_DETAIL_RECORD;
  if (!base || !base.account_id) return;
  const opps = Array.isArray(ACCOUNT_DETAIL_OPPORTUNITIES) ? ACCOUNT_DETAIL_OPPORTUNITIES : [];
  const hires = Array.isArray(ACCOUNT_DETAIL_CANDIDATES) ? ACCOUNT_DETAIL_CANDIDATES : [];
  const derivedStatus = deriveAccountStatusFromData(opps, hires);
  const derivedContract = deriveContractTypeFromCandidates(hires);
  const patch = {};
  const currentStatus = (base.account_status || '').toLowerCase().trim();
  if (derivedStatus && derivedStatus.toLowerCase() !== currentStatus) {
    patch.account_status = derivedStatus;
  }
  const currentContract = (base.contract || '').toString().trim();
  if (derivedContract && derivedContract !== currentContract) {
    patch.contract = derivedContract;
  }
  const normalizedManager = (base.account_manager || '').toString().toLowerCase().trim();
  if (derivedStatus) {
    const normalizedStatus = derivedStatus.toLowerCase();
    if (normalizedStatus === 'active client') {
      const laraEmail = 'lara@vintti.com';
      if (normalizedManager !== laraEmail) {
        patch.account_manager = laraEmail;
      }
    } else if (normalizedStatus === 'lead in process') {
      const suggested = await fetchSuggestedSalesLead(base.account_id);
      if (suggested && suggested !== normalizedManager) {
        patch.account_manager = suggested;
      }
    }
  }
  if (!Object.keys(patch).length) return;
  const res = await fetch(`${API_BASE_URL}/accounts/${base.account_id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch)
  });
  if (!res.ok) throw new Error('Failed to persist derived fields');
  Object.assign(base, patch);
  updateAccountDerivedUi(patch);
}

function updateAccountDerivedUi(fields = {}) {
  if (fields.contract !== undefined) {
    const text = fields.contract || 'Not available';
    const contractEl = document.getElementById('account-contract');
    if (contractEl) {
      contractEl.textContent = text;
      contractEl.classList.toggle('placeholder', !fields.contract);
    }
  }
  if (fields.account_status) {
    const statusEl = document.getElementById('account-status');
    if (statusEl) {
      statusEl.textContent = fields.account_status;
      statusEl.classList.remove('placeholder');
    }
  }
}
document.addEventListener('DOMContentLoaded', () => {
document.body.style.backgroundColor = 'var(--bg)';
  setupStatusChipEvents();

  // Tabs
  const tabs = document.querySelectorAll('.tab-btn');
  const contents = document.querySelectorAll('.tab-content');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.getAttribute('data-tab');
      contents.forEach(c => {
        c.classList.remove('active');
        if (c.id === target) c.classList.add('active');
      });
    });
  });

  // Accordion
  document.querySelectorAll('.accordion-header').forEach(header => {
    header.addEventListener('click', () => {
      const section = header.parentElement;
      section.classList.toggle('open');
    });
  });

  // Cargar datos
  const id = getIdFromURL();
  const richEnabled = window.RichComments && typeof window.RichComments.enhance === 'function';
  const patchAccountField = (field, value) => {
    if (!id) return;
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value || '' })
    }).catch((err) => console.warn(`Failed to update ${field}`, err));
  };

  if (richEnabled) {
    ACCOUNT_RICH_COMMENT_HANDLES.comments = window.RichComments.enhance('comments', {
      placeholder: 'Write comments here...',
      onBlur: (html) => patchAccountField('comments', html)
    });
    ACCOUNT_RICH_COMMENT_HANDLES.painPoints = window.RichComments.enhance('pain-points', {
      placeholder: 'Write Pain Points here...',
      onBlur: (html) => patchAccountField('pain_points', html)
    });
  } else {
    const commentsTextarea = document.getElementById('comments');
    if (commentsTextarea) {
      commentsTextarea.addEventListener('blur', () => patchAccountField('comments', commentsTextarea.value.trim()));
    }
    const painPointsTextarea = document.getElementById('pain-points');
    if (painPointsTextarea) {
      painPointsTextarea.addEventListener('blur', () => patchAccountField('pain_points', painPointsTextarea.value.trim()));
    }
  }

  const overviewFab = document.getElementById('clientOverviewFab');
  if (overviewFab) {
    if (id) {
      overviewFab.href = `account-overview.html?id=${encodeURIComponent(id)}`;
    } else {
      overviewFab.addEventListener('click', (event) => event.preventDefault());
      overviewFab.setAttribute('aria-disabled', 'true');
    }
  }
  if (!id) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}`)
    .then(res => res.json())
    .then(data => {
      ACCOUNT_DETAIL_RECORD = data || null;
      ACCOUNT_DETAIL_OPPORTUNITIES = [];
      ACCOUNT_DETAIL_CANDIDATES = [];
      ACCOUNT_OPPS_READY = false;
      ACCOUNT_CANDIDATES_READY = false;
      fillAccountDetails(data);
      loadAssociatedOpportunities(id);
      loadCandidates(id);
      loadAccountPdfs(id); // ⬅️ NUEVO: pinta la grilla de PDFs
    })
    .catch(err => {
      console.error('Error fetching accounts details:', err);
    });
// Botón de Go Back
const goBackButton = document.getElementById('goBackButton');
if (goBackButton) {
  goBackButton.addEventListener('click', () => {
    if (document.referrer) {
      window.history.back();
    } else {
      window.location.href = '/'; // Cambia por la home si quieres
    }
  });
}

const clientNameInput = document.getElementById('account-client-name');
if (clientNameInput) {
  clientNameInput.addEventListener('blur', () => {
    const newName = clientNameInput.value.trim();
    const accountId = getIdFromURL();
    if (!accountId || !newName) return;

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_name: newName })
    })
    .then(res => {
      if (!res.ok) throw new Error('Error updating client name');
      console.log('Client name updated');
    })
    .catch(err => {
      console.error('Failed to update client name:', err);
    });
  });
}
const closeBtn = document.getElementById("close-discount-alert");
if (closeBtn) {
  closeBtn.addEventListener("click", () => {
    document.getElementById("discount-alert").classList.add("hidden");
  });
}








});
function editField(field) {
  const currentLink = document.getElementById(`${field}-link`).href;
  const newLink = prompt(`Enter new ${field} URL:`, currentLink);

  if (!newLink) return;

  // Actualiza el link visualmente
  document.getElementById(`${field}-link`).href = newLink;

  // Obtener el account ID desde la URL
  const accountId = new URLSearchParams(window.location.search).get('id');
  if (!accountId) return;

  const body = { [field]: newLink };

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(res => {
    if (!res.ok) throw new Error('Failed to update');
    console.log(`${field} updated successfully`);
  })
  .catch(err => {
    alert('There was an error updating the link. Please try again.');
    console.error(err);
  });
}
function loadAssociatedOpportunities(accountId) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities`)
    .then(res => res.json())
    .then(data => {
      ACCOUNT_DETAIL_OPPORTUNITIES = Array.isArray(data) ? data : [];
      ACCOUNT_OPPS_READY = true;
      scheduleAccountDerivedRefresh();
      console.log("Oportunidades asociadas:", data);
      fillOpportunitiesTable(data);
    })
    .catch(err => {
      console.error("Error cargando oportunidades asociadas:", err);
    });
}
function fillAccountDetails(data) {
  const setFieldText = (id, value) => {
    const el = document.getElementById(id);
    if (!el) return;
    const normalized =
      typeof value === 'string'
        ? value.trim().replace(/^(null|undefined)$/i, '').trim()
        : value;
    const hasValue = normalized !== undefined && normalized !== null && normalized !== '';
    el.textContent = hasValue ? normalized : 'Not available';
    if (el.classList) {
      el.classList.toggle('placeholder', !hasValue);
    }
  };

  const clientNameInput = document.getElementById('account-client-name');
  if (clientNameInput) {
    clientNameInput.value = data.client_name || '';
  }

  setFieldText('account-size', data.size);
  setFieldText('account-timezone', data.timezone);
  setFieldText('account-state', data.state);
  setFieldText('account-contact-name', data.name);
  setFieldText('account-contact-surname', data.surname);
  setFieldText('account-industry', data.industry);
  setFieldText('account-lead-source', data.where_come_from);
  setFieldText('account-referral-source', data.referal_source);
  setFieldText('account-position', data.position);
  setFieldText('account-type', data.type);

  const outsourceDisplay = (() => {
    if (data.outsource === true) return 'Yes';
    if (data.outsource === false) return 'No';
    if (typeof data.outsource === 'string' && data.outsource.trim()) {
      return data.outsource;
    }
    return null;
  })();
  setFieldText('account-outsource', outsourceDisplay);

  setFieldText('account-contract', data.contract);

  const mailLink = document.getElementById('account-mail-link');
  if (mailLink) {
    const email = (data.mail || '').trim();
    if (email) {
      mailLink.textContent = email;
      mailLink.href = `mailto:${email}`;
      mailLink.removeAttribute('aria-disabled');
      mailLink.classList.remove('placeholder');
    } else {
      mailLink.textContent = 'Not available';
      mailLink.removeAttribute('href');
      mailLink.removeAttribute('target');
      mailLink.setAttribute('aria-disabled', 'true');
      mailLink.classList.add('placeholder');
    }
  }

  const linkedinLink = document.getElementById('linkedin-link');
  if (linkedinLink) linkedinLink.href = data.linkedin || '#';

  const websiteLink = document.getElementById('website-link');
  if (websiteLink) websiteLink.href = data.website || '#';

  if (ACCOUNT_RICH_COMMENT_HANDLES.comments) {
    ACCOUNT_RICH_COMMENT_HANDLES.comments.setHTML(data.comments || '');
  } else {
    const commentsTextarea = document.getElementById('comments');
    if (commentsTextarea) commentsTextarea.value = data.comments || '';
  }

  if (ACCOUNT_RICH_COMMENT_HANDLES.painPoints) {
    ACCOUNT_RICH_COMMENT_HANDLES.painPoints.setHTML(data.pain_points || '');
  } else {
    const painPointsTextarea = document.getElementById('pain-points');
    if (painPointsTextarea) painPointsTextarea.value = data.pain_points || '';
  }

  document.getElementById('account-tsf').textContent = `$${data.tsf ?? 0}`;
  document.getElementById('account-tsr').textContent = `$${data.tsr ?? 0}`;
  document.getElementById('account-trr').textContent = `$${data.trr ?? 0}`;
}

function fillOpportunitiesTable(opportunities) {
  const tbody = document.querySelector('#overview .accordion-section:nth-of-type(2) tbody');
  tbody.innerHTML = '';

  if (!opportunities.length) {
    tbody.innerHTML = `<tr><td colspan="3">No opportunities found</td></tr>`;
    return;
  }

  // helper: agarra el id aunque cambie el nombre del campo
  const getOppId = (opp) => opp.opportunity_id ;

  opportunities.forEach(opp => {
    const hireContent = opp.candidate_name
      ? opp.candidate_name
      : `<span class="no-hire">Not hired yet</span>`;

    const row = document.createElement('tr');
    const positionContent = `<span>${opp.opp_position_name || '—'}</span>`;
    row.innerHTML = `
      <td>${wrapContentWithBadge(positionContent, opp.replacement_of)}</td>
      <td>${opp.opp_stage || '—'}</td>
      <td>${hireContent}</td>
    `;

    const oppId = getOppId(opp);
    if (oppId) {
      row.style.cursor = 'pointer';

      row.addEventListener('click', () => {
        // tu URL final:
        window.location.href = `https://vinttihub.vintti.com/opportunity-detail.html?id=${encodeURIComponent(oppId)}`;

      });
    }

    tbody.appendChild(row);
  });
}

async function loadCandidates(accountId) {
  if (!accountId) return;
  try {
    const [candidatesRes, buyoutsRes] = await Promise.allSettled([
      fetch(`${API_BASE_URL}/accounts/${accountId}/opportunities/candidates`),
      fetch(`${API_BASE_URL}/accounts/${accountId}/buyouts`),
    ]);

    if (candidatesRes.status !== 'fulfilled' || !candidatesRes.value.ok) {
      throw new Error('Failed to load candidates');
    }

    const candidates = await candidatesRes.value.json();
    ACCOUNT_DETAIL_CANDIDATES = Array.isArray(candidates) ? candidates : [];
    ACCOUNT_CANDIDATES_READY = true;
    scheduleAccountDerivedRefresh();
    let buyouts = [];
    if (buyoutsRes.status === 'fulfilled' && buyoutsRes.value.ok) {
      buyouts = await buyoutsRes.value.json();
    } else {
      console.warn('Buyouts endpoint unavailable, continuing with empty set');
    }

    const syncedBuyouts = await ensureBuyoutRows(accountId, candidates, buyouts);
    console.log('Candidates asociados:', candidates);
    fillEmployeesTables(candidates, syncedBuyouts);
  } catch (err) {
    console.error('Error cargando candidates asociados:', err);
  }
}

async function fetchAccountBuyouts(accountId) {
  if (!accountId) return [];
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/buyouts`);
  if (!res.ok) {
    throw new Error('Failed to load buyouts');
  }
  return res.json();
}

async function createAccountBuyout(accountId, payload) {
  const res = await fetch(`${API_BASE_URL}/accounts/${accountId}/buyouts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(`Failed to create buyout: ${msg}`);
  }
  return res.json();
}

async function ensureBuyoutRows(accountId, candidates, buyouts) {
  if (!accountId) return Array.isArray(buyouts) ? buyouts : [];

  const candidateList = Array.isArray(candidates) ? candidates : [];
  const buyoutList = Array.isArray(buyouts) ? buyouts : [];
  if (!candidateList.length) return buyoutList;

  const existing = new Set(
    buyoutList
      .filter((row) => row && row.candidate_id != null)
      .map((row) => Number(row.candidate_id))
  );

  const missingCandidates = candidateList.filter((candidate) => {
    if (!candidate || candidate.candidate_id == null) return false;
    if (!hasBuyoutInfo(candidate)) return false;
    return !existing.has(Number(candidate.candidate_id));
  });

  if (!missingCandidates.length) {
    return buyoutList;
  }

  for (const candidate of missingCandidates) {
    try {
      await createAccountBuyout(accountId, {
        candidate_id: candidate.candidate_id,
        salary: null,
        revenue: null,
        referral: null,
        referral_id: null,
        start_date: deriveBuyoutStartDate(candidate.buyout_daterange),
        end_date: null,
      });
    } catch (err) {
      console.error('Failed to auto-create buyout row', err);
    }
  }

  try {
    return await fetchAccountBuyouts(accountId);
  } catch (err) {
    console.error('Failed to refresh buyouts after sync', err);
    return buyoutList;
  }
}

function deriveBuyoutStartDate(raw) {
  if (!raw) return null;
  const text = String(raw).trim();
  const fullDate = text.match(/\d{4}-\d{2}-\d{2}/);
  if (fullDate && fullDate[0]) return fullDate[0];
  const monthDate = text.match(/\d{4}-\d{2}/);
  if (monthDate && monthDate[0]) return `${monthDate[0]}-01`;
  return null;
}

function fillEmployeesTables(candidates, buyouts = []) {
  setupStatusChipEvents();
  const staffingTableBody   = document.querySelector('#employees .card:nth-of-type(1) tbody');
  const recruitingTableBody = document.querySelector('#employees .card:nth-of-type(2) tbody');

  if (!staffingTableBody || !recruitingTableBody) return;

  staffingTableBody.innerHTML = '';
  recruitingTableBody.innerHTML = '';

  const candidateList = Array.isArray(candidates) ? candidates : [];
  const candidateLookup = new Map();
  candidateList.forEach((candidate) => {
    if (candidate && candidate.candidate_id != null) {
      candidateLookup.set(Number(candidate.candidate_id), candidate);
    }
  });

  let hasStaffing = false;
  let hasRecruiting = false;
  let hasActiveStaffing = false;
  let hasActiveRecruiting = false;

  candidateList.forEach(candidate => {
    // ---------- STAFFING ----------
    if (candidate.opp_model === 'Staffing') {
      const row = document.createElement('tr');
      const isBlacklisted = Boolean(candidate.is_blacklisted);
      const blacklistIndicator = isBlacklisted
        ? `<span class="blacklist-indicator" role="img" aria-label="Blacklisted candidate" title="Blacklisted candidate">⚠️</span>`
        : '';
      console.log('end_date raw:', candidate.end_date, 'candidate:', candidate.candidate_id);
      const startVal = dateInputValue(candidate.start_date);
const endVal   = dateInputValue(candidate.end_date);
      const candidateLink = `
          <a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">
            ${candidate.name || '—'} ${blacklistIndicator}
          </a>
        `;
      const employeeCell = wrapContentWithBadge(candidateLink, candidate.replacement_of);
      const rowStatus = candidate.status ?? (candidate.end_date ? 'inactive' : 'active');
      row.innerHTML = `
        <td>${renderStatusChip(rowStatus)}</td>
        <td>${employeeCell}</td>
        <td>
<input
  type="date"
  class="start-date-input input-chip"
  ${startVal ? `value="${startVal}"` : ``}
  data-candidate-id="${candidate.candidate_id}"
  data-opportunity-id="${candidate.opportunity_id}"
/>
        </td>

        <td>
<input
  type="date"
  class="end-date-input input-chip"
  ${endVal ? `value="${endVal}"` : ``}
  data-candidate-id="${candidate.candidate_id}"
  data-opportunity-id="${candidate.opportunity_id}"
/>

        </td>
        <td>${candidate.opp_position_name || '—'}</td>
        <td>$${candidate.employee_fee ?? '—'}</td>
        <td>$${candidate.employee_salary ?? '—'}</td>
        <td>$${candidate.employee_revenue ?? '—'}</td>

        <!-- Discount $ -->
        <td>
          <input 
            type="number"
            class="discount-input"
            placeholder="$"
            value="${candidate.discount_dolar || ''}"
            data-candidate-id="${candidate.candidate_id}"
            data-opportunity-id="${candidate.opportunity_id}"
          />
        </td>

        <!-- Discount Date Range -->
        <td>
         <input 
           type="text" 
           class="month-range-picker range-chip" 
            placeholder="Select range"
           readonly 
            data-candidate-id="${candidate.candidate_id}"
            data-opportunity-id="${candidate.opportunity_id}"
            value="${candidate.discount_daterange?.replace('[','').replace(']','').split(',').map(d => d.trim()).join(' - ') || ''}"
          />
        </td>

        <!-- Discount Months (badge) -->
        <td></td>

        <!-- NUEVO: Referral $ -->
        <td>
         <div class="currency-wrap">
           <input 
             type="number"
             class="referral-input input-chip"
             placeholder="0.00"
             step="0.01" min="0" inputmode="decimal"
             value="${candidate.referral_dolar ?? ''}"
             data-candidate-id="${candidate.candidate_id}"
             data-opportunity-id="${candidate.opportunity_id}"
           />
         </div>
        </td>

        <!-- NUEVO: Referral Date Range -->
        <td>
         <input 
           type="text" 
           class="referral-range-picker range-chip" 
            placeholder="Select range"
            readonly 
            data-candidate-id="${candidate.candidate_id}"
            data-opportunity-id="${candidate.opportunity_id}"
            value="${candidate.referral_daterange?.replace('[','').replace(']','').split(',').map(d => d.trim()).join(' - ') || ''}"
          />
        </td>

        <!-- NUEVO: Buy Out $ -->
        <td>
         <div class="currency-wrap">
           <input 
             type="number"
             class="buyout-input input-chip"
             placeholder="0.00"
             step="0.01" min="0" inputmode="decimal"
             value="${candidate.buyout_dolar ?? ''}"
             data-candidate-id="${candidate.candidate_id}"
           />
         </div>
        </td>

        <!-- NUEVO: Buy Out Month (mes & año) -->
        <td>
         <div class="buyout-month-wrap segmented" data-candidate-id="${candidate.candidate_id}">
           <select class="buyout-month select-chip"></select>
           <select class="buyout-year select-chip"></select>
         </div>
        </td>
      `;
      applyStatusChipMetadata(row, candidate, rowStatus);
      if (isBlacklisted) {
        row.classList.add('blacklisted-row');
        row.style.backgroundColor = '#ffeaea';
      }
      const recruitingEndEl = row.querySelector('.end-date-input');
      if (recruitingEndEl) {
        recruitingEndEl.dataset.previousEndDate = dateInputValue(candidate.end_date) || '';
      }
// Safari safety: force-clear if empty
const endEl = row.querySelector('.end-date-input');
if (endEl) {
  if (!endVal) {
    endEl.value = '';
    endEl.valueAsDate = null;
  }
  endEl.dataset.previousEndDate = endVal || '';
}

      // ----- Lógica de Discount SOLO para Staffing -----
      const monthsCell    = row.children[10]; // Discount Months
      const dateRangeCell = row.children[9];  // Discount Date Range
      const dollarCell    = row.children[8];  // Discount $

      if (candidate.discount_daterange && candidate.discount_daterange.includes(',')) {
        const [startStr, endStr] = candidate.discount_daterange
          .replace('[','').replace(']','')
          .split(',').map(d => d.trim());

        const start = new Date(startStr);
        const end   = new Date(endStr);

        if (!isNaN(start.getTime()) && !isNaN(end.getTime())) {
          // Meses (inclusive)
          const months =
            (end.getFullYear() - start.getFullYear()) * 12 +
            (end.getMonth() - start.getMonth()) + 1;
          monthsCell.textContent = months;

          // Badge activo/expirado
          const now = new Date();
          const current = new Date(now.getFullYear(), now.getMonth(), 1);
          const endMonth = new Date(end.getFullYear(), end.getMonth(), 1);
          const isExpired = endMonth < current;

          const badge = document.createElement('span');
          badge.className = `badge-pill ${isExpired ? 'expired' : 'active'}`;
          badge.textContent = isExpired ? 'expired' : 'active';

          const dateInput = dateRangeCell.querySelector('.month-range-picker');
          if (dateInput && dateInput.parentElement) {
            dateInput.parentElement.appendChild(badge);
          }

          if (isExpired) {
            [monthsCell, dateRangeCell, dollarCell].forEach(cell => {
              cell.style.backgroundColor = '#fff0f0';
              cell.style.color = '#b30000';
              cell.style.fontWeight = '500';
            });
          } else {
            [monthsCell, dateRangeCell, dollarCell].forEach(cell => {
              cell.style.backgroundColor = '#f2fff2';
              cell.style.color = '#006600';
            });
          }
        }
      }
      // === Referral ===
      const referralInput = row.querySelector('.referral-input');
      if (referralInput) {
        referralInput.addEventListener('blur', () => {
          const candidateId = referralInput.dataset.candidateId;
          const oppId = referralInput.dataset.opportunityId;
          const value = referralInput.value;
          updateCandidateField(candidateId, 'referral_dolar', value, oppId);
        });
      }

      const referralPickerInput = row.querySelector('.referral-range-picker');
      if (referralPickerInput) {
        // Precargar rango si ya existía
        const rr = candidate.referral_daterange;
        let startDateR = null, endDateR = null;
        if (rr && rr.includes(',')) {
          const [s,e] = rr.replace('[','').replace(']','').split(',').map(d => d.trim());
          startDateR = new Date(s.slice(0,7) + '-15');
          endDateR   = new Date(e.slice(0,7) + '-15');
        }

        const refOptions = {
          element: referralPickerInput,
          format: 'MMM YYYY',
          numberOfMonths: 2,
          numberOfColumns: 2,
          singleMode: false,
          allowRepick: true,
          dropdowns: { minYear: 2020, maxYear: 2030, months: true, years: true },
          setup: (picker) => {
            picker.on('selected', (date1, date2) => {
              const candidateId = referralPickerInput.dataset.candidateId;
              const oppId = referralPickerInput.dataset.opportunityId;
              if (!candidateId) return;
              const start = date1.format('YYYY-MM-DD');
              const end   = date2.format('YYYY-MM-DD');
              updateCandidateField(candidateId, 'referral_daterange', `[${start},${end}]`, oppId);
            });
          }
        };
        if (startDateR && endDateR) { refOptions.startDate = startDateR; refOptions.endDate = endDateR; }
        new Litepicker(refOptions);
      }

      // === Buy Out (mes/año) ===
      const wrap = row.querySelector('.buyout-month-wrap');
      if (wrap) {
        const mSel = wrap.querySelector('.buyout-month');
        const ySel = wrap.querySelector('.buyout-year');
        const candidateId = wrap.dataset.candidateId;

        // Opciones de mes
        const months = ['01','02','03','04','05','06','07','08','09','10','11','12'];
        mSel.innerHTML = months.map((m,idx) => `<option value="${m}">${new Date(2000, idx, 1).toLocaleString('en-US',{month:'short'})}</option>`).join('');

        // Opciones de año (rango dinámico)
        const nowY = new Date().getFullYear();
        const years = Array.from({length: 9}, (_,i) => nowY - 4 + i); // [nowY-4 .. nowY+4]
        ySel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');

        // Preselección si ya hay valor guardado (acepta "YYYY-MM" o "[YYYY-MM-01,YYYY-MM-01]")
        let preY = null, preM = null;
        const bo = candidate.buyout_daterange;
        if (bo) {
          const ym = (bo.match(/\d{4}-\d{2}/) || [])[0];
          if (ym) { preY = ym.slice(0,4); preM = ym.slice(5,7); }
        }
        if (preY && years.includes(+preY)) ySel.value = preY;
        if (preM && months.includes(preM)) mSel.value = preM;

        const saveBuyout = () => {
          const y = ySel.value, m = mSel.value;
          if (!y || !m) return;
          // Guardamos como "YYYY-MM" (simple y suficiente para tu UI)
          updateCandidateField(candidateId, 'buyout_daterange', `${y}-${m}`, candidate.opportunity_id);
        };
        mSel.addEventListener('change', saveBuyout);
        ySel.addEventListener('change', saveBuyout);

        // Guardar Buyout $
        const buyoutInput = row.querySelector('.buyout-input');
        if (buyoutInput) {
          buyoutInput.addEventListener('blur', () => {
            const value = buyoutInput.value;
            updateCandidateField(candidateId, 'buyout_dolar', value, candidate.opportunity_id);
          });
        }
      }

      // Inicializar Litepicker (si hay valores previos, precargar)
      const monthPickerInput = row.querySelector('.month-range-picker');
      if (monthPickerInput) {
        const daterange = candidate.discount_daterange;
        let startDate = null;
        let endDate = null;

        if (daterange && daterange.includes(',')) {
          const dates = daterange.replace('[', '').replace(']', '').split(',');
          if (dates.length === 2) {
            startDate = new Date(dates[0].trim().slice(0, 7) + '-15');
            endDate   = new Date(dates[1].trim().slice(0, 7) + '-15');
          }
        }

        const litepickerOptions = {
          element: monthPickerInput,
          format: 'MMM YYYY',
          numberOfMonths: 2,
          numberOfColumns: 2,
          singleMode: false,
          allowRepick: true,
          dropdowns: { minYear: 2020, maxYear: 2030, months: true, years: true },
          setup: (picker) => {
            picker.on('selected', (date1, date2) => {
              const candidateId = monthPickerInput.dataset.candidateId;
              const oppId = monthPickerInput.dataset.opportunityId;
              if (!candidateId) return;

              const start = date1.format('YYYY-MM-DD');
              const end   = date2.format('YYYY-MM-DD');

              updateCandidateField(candidateId, 'discount_daterange', `[${start},${end}]`, oppId);
            });
          }
        };

        if (startDate && endDate) {
          litepickerOptions.startDate = startDate;
          litepickerOptions.endDate   = endDate;
        }

        new Litepicker(litepickerOptions);
      }

      const discountInput = row.querySelector('.discount-input');
      if (discountInput) {
        discountInput.addEventListener('blur', () => {
          const candidateId = discountInput.dataset.candidateId;
          const oppId = discountInput.dataset.opportunityId;
          const value = discountInput.value;
          updateCandidateField(candidateId, 'discount_dolar', value, oppId);
        });
      }
// === Start/End date (hire_opportunity) — STAFFING ===
const startInputS = row.querySelector('.start-date-input');
if (startInputS) {
  startInputS.addEventListener('change', () => {
    const candidateId = startInputS.dataset.candidateId;
    const oppId = startInputS.dataset.opportunityId;
    updateCandidateField(candidateId, 'start_date', startInputS.value || null, oppId);
  });
}

const endInputS = row.querySelector('.end-date-input');
if (endInputS) {
  endInputS.addEventListener('change', async () => {
    const candidateId = endInputS.dataset.candidateId;
    const oppId = endInputS.dataset.opportunityId;
    const newValue = endInputS.value || '';
    const patchValue = newValue || null;
    const prevValue = endInputS.dataset.previousEndDate || '';
    const shouldNotify = !prevValue && !!newValue;
    const accountName = getCurrentAccountName() || candidate.client_name || candidate.account_name || '';
    const persistEndDate = () =>
      updateCandidateField(candidateId, 'end_date', patchValue, oppId) || Promise.resolve();

    try {
      if (shouldNotify) {
        const modalResult = await captureInactiveMetadataFromAccount({
          candidateId,
          candidateName: candidate.name,
          clientName: accountName,
          roleName: candidate.opp_position_name,
          opportunityId: oppId
        });
        if (!modalResult) {
          endInputS.value = prevValue;
          endInputS.dataset.previousEndDate = prevValue;
          return;
        }
      }

      await persistEndDate();

      if (shouldNotify) {
        await notifyCandidateInactiveEmail({
          candidateId,
          candidateName: candidate.name,
          clientName: accountName,
          roleName: candidate.opp_position_name,
          endDate: newValue,
          opportunityId: oppId
        });
      }

      endInputS.dataset.previousEndDate = newValue;
    } catch (err) {
      console.error('Failed to process Staffing end date change', err);
      endInputS.value = prevValue;
      endInputS.dataset.previousEndDate = prevValue;
    }
  });
}

      staffingTableBody.appendChild(row);
      hasStaffing = true;
      if (isActiveHire(candidate)) {
        hasActiveStaffing = true;
      }
    }

    // ---------- RECRUITING ----------
    else if (candidate.opp_model === 'Recruiting') {
      const row = createRecruitingRow(candidate);
      if (row) {
        recruitingTableBody.appendChild(row);
        hasRecruiting = true;
        if (isActiveHire(candidate)) {
          hasActiveRecruiting = true;
        }
      }
    }
  });

  const appendedBuyoutRows = appendBuyoutsToRecruiting(buyouts, candidateLookup, recruitingTableBody);
  if (appendedBuyoutRows > 0) {
    hasRecruiting = true;
    hasActiveRecruiting = true;
  }

  if (!hasStaffing) {
    staffingTableBody.innerHTML = `<tr><td colspan="15">No employees in Staffing</td></tr>`;
  }
  if (!hasRecruiting) {
    recruitingTableBody.innerHTML = `<tr><td colspan="11">No employees in Recruiting</td></tr>`;
  }

  // ------- Alertas de Discount (solo Staffing) -------
  const alertDiv        = document.getElementById("discount-alert");
  const discountCountEl = document.getElementById("discount-count");
  const discountListEl  = document.getElementById("discount-list");

  const discountCandidates = candidateList.filter(c => {
    if (c.opp_model !== 'Staffing') return false;
    if (!c.discount_dolar || !c.discount_daterange || !c.discount_daterange.includes(',')) return false;

    const [, endStr] = c.discount_daterange.replace('[', '').replace(']', '').split(',').map(s => s.trim());
    const endDate = new Date(endStr);
    const now = new Date();
    const currentMonthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const endMonthStart = new Date(endDate.getFullYear(), endDate.getMonth(), 1);

    return endMonthStart >= currentMonthStart; // solo no expirados
  });

  if (discountCandidates.length > 0) {
    discountCountEl.innerText = discountCandidates.length;
    discountListEl.innerHTML = '';

    discountCandidates.sort((a, b) => {
      const endA = a.discount_daterange.match(/\d{4}-\d{2}-\d{2}/g)?.[1];
      const endB = b.discount_daterange.match(/\d{4}-\d{2}-\d{2}/g)?.[1];
      return new Date(endA) - new Date(endB);
    });

    discountCandidates.forEach(c => {
      const endDate = c.discount_daterange.match(/\d{4}-\d{2}-\d{2}/g)?.[1];
      if (endDate) {
        const formattedEnd = new Date(endDate).toLocaleDateString('en-US', { year: 'numeric', month: 'short' });
        const li = document.createElement('li');
        const discountDollar = c.discount_dolar ? `$${c.discount_dolar}` : '';
        li.innerHTML = `💵 ${discountDollar} until <strong>${formattedEnd}</strong>`;
        discountListEl.appendChild(li);
      }
    });

    alertDiv.classList.remove("hidden");
  } else {
    alertDiv.classList.add("hidden");
  }

  // ------- Contract visual + persistencia -------
  let contractType = '—';
  if (hasActiveStaffing && !hasActiveRecruiting) {
    contractType = 'Staffing';
  } else if (!hasActiveStaffing && hasActiveRecruiting) {
    contractType = 'Recruiting';
  } else if (hasActiveStaffing && hasActiveRecruiting) {
    contractType = 'Mix';
  }

  updateAccountDerivedUi({ contract: contractType !== '—' ? contractType : '' });
}

function appendBuyoutsToRecruiting(buyouts, candidateLookup, recruitingTableBody) {
  if (!recruitingTableBody) return 0;
  const rows = Array.isArray(buyouts) ? buyouts : [];
  if (!rows.length) return 0;

  let appended = 0;
  const sorted = [...rows].sort((a, b) => (Number(a.buyout_id) || 0) - (Number(b.buyout_id) || 0));

  sorted.forEach((buyout) => {
    const baseCandidate =
      candidateLookup.get(Number(buyout.candidate_id)) || buildBuyoutCandidateFallback(buyout);
    if (!baseCandidate) return;

    const candidateForRow = {
      ...baseCandidate,
      start_date: buyout.start_date || baseCandidate.start_date,
      end_date: buyout.end_date || baseCandidate.end_date,
      employee_salary: buyout.salary ?? baseCandidate.employee_salary,
      employee_revenue_recruiting: buyout.revenue ?? baseCandidate.employee_revenue_recruiting,
      employee_revenue: buyout.revenue ?? baseCandidate.employee_revenue,
      referral_dolar: buyout.referral ?? baseCandidate.referral_dolar,
      referral_id: buyout.referral_id ?? baseCandidate.referral_id,
      referral_daterange: buyout.referral_date_range ?? baseCandidate.referral_daterange,
      buyoutProbation: buyout.probation ?? null,
    };

    const row = createRecruitingRow(candidateForRow, {
      forceActiveStatus: true,
      isBuyoutDuplicate: true,
      updateTarget: 'buyout',
      buyoutId: buyout.buyout_id,
      disableReferralRange: false,
    });

    if (row) {
      row.dataset.buyoutId = buyout.buyout_id || '';
      recruitingTableBody.appendChild(row);
      appended += 1;
    }
  });

  return appended;
}

function buildBuyoutCandidateFallback(buyout) {
  if (!buyout) return null;
  const candidateId = buyout.candidate_id;
  return {
    candidate_id: candidateId,
    name: buyout.candidate_name || (candidateId ? `Candidate #${candidateId}` : 'Candidate'),
    opportunity_id: null,
    opp_position_name: '',
    probation_days: '—',
    status: 'active',
    start_date: buyout.start_date || null,
    end_date: buyout.end_date || null,
    employee_salary: buyout.salary ?? null,
    employee_revenue_recruiting: buyout.revenue ?? null,
    employee_revenue: buyout.revenue ?? null,
    referral_dolar: buyout.referral ?? null,
    referral_id: buyout.referral_id ?? null,
    referral_daterange: buyout.referral_date_range ?? null,
    buyoutProbation: buyout.probation ?? null,
  };
}

function hasBuyoutInfo(candidate) {
  if (!candidate) return false;
  const amount = candidate.buyout_dolar;
  const range = candidate.buyout_daterange;
  const hasAmount =
    amount !== null &&
    amount !== undefined &&
    !(typeof amount === 'string' && amount.trim() === '');
  const hasRange = Boolean(range && String(range).trim());
  return hasAmount || hasRange;
}

function createRecruitingRow(candidate, options = {}) {
  if (!candidate) return null;
  const {
    forceActiveStatus = false,
    isBuyoutDuplicate = false,
    updateTarget = 'candidate',
    buyoutId = null,
    disableReferralRange = false,
  } = options;
  if (isBuyoutDuplicate) ensureBuyoutNoteStyles();
  const isBuyoutRow = updateTarget === 'buyout' && buyoutId;

  const isBlacklisted = Boolean(candidate.is_blacklisted);
  const blacklistIndicator = isBlacklisted
    ? `<span class="blacklist-indicator" role="img" aria-label="Blacklisted candidate" title="Blacklisted candidate">⚠️</span>`
    : '';
  const buyoutNote = isBuyoutDuplicate
    ? `<span class="buyout-note" title="Candidate has buyout info">Buyout${buyoutId ? ` #${buyoutId}` : ''}</span>`
    : '';
  const candidateLink = `
          <a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">
            ${candidate.name || '—'} ${blacklistIndicator}
          </a>
        `;
  const employeeCell = wrapContentWithBadge(candidateLink, candidate.replacement_of);

  const probationValueRaw =
    candidate.buyoutProbation ??
    candidate.probation_days ??
    candidate.probation ??
    candidate.probation_days_recruiting ??
    null;
  const probationCellContent = isBuyoutRow
    ? `<input type="number" class="buyout-probation-input input-chip" step="1" min="0" placeholder="0" data-buyout-id="${buyoutId}" value="${(probationValueRaw === null || probationValueRaw === undefined || probationValueRaw === '—') ? '' : probationValueRaw}"/>`
    : (probationValueRaw ?? '—');

  const salaryCellContent = isBuyoutRow
    ? `<input type="number" class="buyout-salary-input input-chip" step="0.01" min="0" placeholder="0.00" data-buyout-id="${buyoutId}" value="${candidate.employee_salary ?? ''}" />`
    : `$${candidate.employee_salary ?? '—'}`;
  const revenueCellContent = isBuyoutRow
    ? `<input type="number" class="buyout-revenue-input input-chip" step="0.01" min="0" placeholder="0.00" data-buyout-id="${buyoutId}" value="${candidate.employee_revenue_recruiting ?? candidate.employee_revenue ?? ''}" />`
    : `$${(candidate.employee_revenue_recruiting ?? candidate.employee_revenue ?? '—')}`;
  const referralIdCellContent = isBuyoutRow
    ? `<input type="text" class="buyout-referral-id-input input-chip" placeholder="Referral ID" data-buyout-id="${buyoutId}" value="${candidate.referral_id ?? ''}" />`
    : '—';

  const rowStatus =
    forceActiveStatus
      ? 'active'
      : (candidate.status ?? (candidate.end_date ? 'inactive' : 'active'));
  const row = document.createElement('tr');
  row.innerHTML = `
        <td>${renderStatusChip(rowStatus)}</td>
        <td>${employeeCell}${buyoutNote}</td>
        <td>
          <input
            type="date"
            class="start-date-input input-chip"
            value="${dateInputValue(candidate.start_date)}"
            data-candidate-id="${candidate.candidate_id}"
            data-opportunity-id="${candidate.opportunity_id}"
          />
        </td>

        <td>
          <input
            type="date"
            class="end-date-input input-chip"
            value="${dateInputValue(candidate.end_date)}"
            data-candidate-id="${candidate.candidate_id}"
            data-opportunity-id="${candidate.opportunity_id}"
          />
        </td>
        <td>${candidate.opp_position_name || '—'}</td>
        <td>${probationCellContent}</td>
        <td>${salaryCellContent}</td>
        <td>${revenueCellContent}</td>

        <!-- NUEVO: Referral $ -->
        <td>
         <div class="currency-wrap">
           <input 
             type="number"
             class="ref-rec-input input-chip"
             placeholder="0.00"
             step="0.01" min="0" inputmode="decimal"
             value="${candidate.referral_dolar ?? ''}"
             data-candidate-id="${candidate.candidate_id}"
             data-opportunity-id="${candidate.opportunity_id}"
           />
         </div>
        </td>

        <!-- NUEVO: Referral Date Range -->
        <td>
       <input 
         type="text" 
         class="ref-rec-range-picker range-chip" 
            placeholder="Select range"
            readonly 
            data-candidate-id="${candidate.candidate_id}"
            data-opportunity-id="${candidate.opportunity_id}"
            value="${candidate.referral_daterange?.replace('[','').replace(']','').split(',').map(d => d.trim()).join(' - ') || ''}"
          />
        </td>
        <td>${referralIdCellContent}</td>
      `;
  applyStatusChipMetadata(row, candidate, rowStatus);

  if (isBlacklisted) {
    row.classList.add('blacklisted-row');
    row.style.backgroundColor = '#ffeaea';
  }
  if (isBuyoutDuplicate) {
    row.dataset.buyoutDuplicate = 'true';
  }

  if (isBuyoutRow) {
    const attachNumberHandler = (selector, field) => {
      const input = row.querySelector(selector);
      if (!input) return;
      input.addEventListener('blur', () => {
        updateBuyoutRow(buyoutId, { [field]: numberOrNull(input.value) })
          .then(() => scheduleBuyoutReload())
          .catch((err) => console.error(`Failed to update buyout ${field}`, err));
      });
    };
    attachNumberHandler('.buyout-salary-input', 'salary');
    attachNumberHandler('.buyout-revenue-input', 'revenue');
    const referralIdInput = row.querySelector('.buyout-referral-id-input');
    if (referralIdInput) {
      referralIdInput.addEventListener('blur', () => {
        const val = String(referralIdInput.value || '').trim() || null;
        updateBuyoutRow(buyoutId, { referral_id: val })
          .then(() => scheduleBuyoutReload())
          .catch((err) => console.error('Failed to update buyout referral_id', err));
      });
    }
    const probationInput = row.querySelector('.buyout-probation-input');
    if (probationInput) {
      probationInput.addEventListener('blur', () => {
        updateBuyoutRow(buyoutId, { probation: numberOrNull(probationInput.value) })
          .then(() => scheduleBuyoutReload())
          .catch((err) => console.error('Failed to update buyout probation', err));
      });
    }
  }

  const refRecInput = row.querySelector('.ref-rec-input');
  if (refRecInput) {
    refRecInput.addEventListener('blur', () => {
      const value = refRecInput.value;
      if (isBuyoutRow) {
        updateBuyoutRow(buyoutId, { referral: numberOrNull(value) })
          .then(() => scheduleBuyoutReload())
          .catch((err) => console.error('Failed to update buyout referral', err));
        return;
      }
      const candidateId = refRecInput.dataset.candidateId;
      const oppId = refRecInput.dataset.opportunityId;
      updateCandidateField(candidateId, 'referral_dolar', value, oppId);
    });
  }

  const refRecPickerInput = row.querySelector('.ref-rec-range-picker');
  if (refRecPickerInput) {
    if (disableReferralRange) {
      refRecPickerInput.value = '';
      refRecPickerInput.placeholder = '—';
      refRecPickerInput.disabled = true;
    } else {
    const rr = candidate.referral_daterange;
    let startDateR = null;
    let endDateR = null;
    if (rr && rr.includes(',')) {
      const [s, e] = rr.replace('[', '').replace(']', '').split(',').map(d => d.trim());
      startDateR = new Date(s.slice(0, 7) + '-15');
      endDateR = new Date(e.slice(0, 7) + '-15');
    }

    const options = {
      element: refRecPickerInput,
      format: 'MMM YYYY',
      numberOfMonths: 2,
      numberOfColumns: 2,
      singleMode: false,
      allowRepick: true,
      dropdowns: { minYear: 2020, maxYear: 2030, months: true, years: true },
      setup: (picker) => {
        picker.on('selected', (date1, date2) => {
          const start = date1.format('YYYY-MM-DD');
          const end = date2.format('YYYY-MM-DD');
          if (isBuyoutRow) {
            updateBuyoutRow(buyoutId, { referral_date_range: `[${start},${end}]` })
              .then(() => scheduleBuyoutReload())
              .catch((err) => console.error('Failed to update buyout referral date range', err));
          } else {
            const candidateId = refRecPickerInput.dataset.candidateId;
            const oppId = refRecPickerInput.dataset.opportunityId;
            if (!candidateId) return;
            updateCandidateField(candidateId, 'referral_daterange', `[${start},${end}]`, oppId);
          }
        });
      }
    };
    if (startDateR && endDateR) {
      options.startDate = startDateR;
      options.endDate = endDateR;
    }
    new Litepicker(options);
    }
  }

  const startInput = row.querySelector('.start-date-input');
  if (startInput) {
    startInput.addEventListener('change', () => {
      if (isBuyoutRow) {
        updateBuyoutRow(buyoutId, { start_date: startInput.value || null })
          .then(() => scheduleBuyoutReload())
          .catch((err) => console.error('Failed to update buyout start date', err));
        return;
      }
      const candidateId = startInput.dataset.candidateId;
      const oppId = startInput.dataset.opportunityId;
      updateCandidateField(candidateId, 'start_date', startInput.value || null, oppId);
    });
  }

  const endInput = row.querySelector('.end-date-input');
  if (endInput) {
    endInput.addEventListener('change', async () => {
      if (isBuyoutRow) {
        updateBuyoutRow(buyoutId, { end_date: endInput.value || null })
          .then(() => scheduleBuyoutReload())
          .catch((err) => console.error('Failed to update buyout end date', err));
        return;
      }
      const candidateId = endInput.dataset.candidateId;
      const oppId = endInput.dataset.opportunityId;
      const newValue = endInput.value || '';
      const patchValue = newValue || null;
      const prevValue = endInput.dataset.previousEndDate || '';
      const shouldNotify = !prevValue && !!newValue;
      const accountName = getCurrentAccountName() || candidate.client_name || candidate.account_name || '';
      const persistEndDate = () =>
        updateCandidateField(candidateId, 'end_date', patchValue, oppId) || Promise.resolve();

      try {
        if (shouldNotify) {
          const modalResult = await captureInactiveMetadataFromAccount({
            candidateId,
            candidateName: candidate.name,
            clientName: accountName,
            roleName: candidate.opp_position_name,
            opportunityId: oppId
          });
          if (!modalResult) {
            endInput.value = prevValue;
            endInput.dataset.previousEndDate = prevValue;
            return;
          }
        }

        await persistEndDate();

        if (shouldNotify) {
          await notifyCandidateInactiveEmail({
            candidateId,
            candidateName: candidate.name,
            clientName: accountName,
            roleName: candidate.opp_position_name,
            endDate: newValue,
            opportunityId: oppId
          });
        }

        endInput.dataset.previousEndDate = newValue;
      } catch (err) {
        console.error('Failed to process Recruiting/Buyout end date change', err);
        endInput.value = prevValue;
        endInput.dataset.previousEndDate = prevValue;
      }
    });
  }

  return row;
}

function ensureBuyoutNoteStyles() {
  if (document.getElementById('buyout-note-style')) return;
  const style = document.createElement('style');
  style.id = 'buyout-note-style';
  style.textContent = `
    .buyout-note {
      display: inline-block;
      margin-left: 6px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #fff4e5;
      color: #b45a00;
      font-size: 10px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      font-weight: 600;
    }
  `;
  document.head.appendChild(style);
}

  function getIdFromURL() {
    const params = new URLSearchParams(window.location.search);
    return params.get('id');
  }
function formatDollarInput(input) {
  const raw = String(input.value || '').replace(/[^\d.]/g, '');
  if (input.type === 'number') {
    // Para type="number" no inyectamos '$' (Safari/Chrome lo rechazan)
    input.value = raw;
  } else {
    input.value = raw ? `$${raw}` : '';
  }
}
function saveDiscountDolar(candidateId, value) {
  const numericValue = parseFloat(value.replace(/[^\d.]/g, ''));
  if (isNaN(numericValue)) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ discount_dolar: numericValue })
  })
  .then(res => {
    if (!res.ok) throw new Error('Error saving discount');
    console.log('💾 Discount $ saved');
  })
  .catch(err => console.error('❌ Failed to save discount:', err));
}
const uploadBtn = document.getElementById("uploadPdfBtn");
const pdfInput = document.getElementById("pdfUpload");
const previewContainer = document.getElementById("pdfPreviewContainer");
if (pdfInput) pdfInput.setAttribute('multiple', 'multiple');
uploadBtn.addEventListener("click", async () => {
  const files = Array.from(pdfInput.files || []).filter(f => f.type === 'application/pdf');
  if (!files.length) return alert("Please select at least one PDF.");

  const accountId = getIdFromURL();
  try {
    await Promise.all(files.map(file => {
      const formData = new FormData();
      formData.append("pdf", file);
      return fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/upload_pdf`, {
        method: "POST",
        body: formData,
      }).then(r => r.ok ? r.json() : Promise.reject(r));
    }));

    pdfInput.value = "";
    await loadAccountPdfs(accountId);
  } catch (err) {
    console.error("Error uploading PDFs:", err);
    alert("Upload failed");
  }
});

const HIRE_FIELD_NAMES = new Set([
  'discount_dolar','discount_daterange',
  'referral_dolar','referral_daterange',
  'buyout_dolar','buyout_daterange',
  'start_date','end_date',
  'inactive_reason','inactive_comments','inactive_vinttierror'
]);

function persistHireFields(candidateId, patch, opportunityId) {
  if (!candidateId) return Promise.resolve();
  if (!opportunityId) {
    console.error('Missing opportunity_id for hire field update:', { candidateId, patch });
    return Promise.resolve();
  }
  const body = { ...patch, opportunity_id: opportunityId };
  return fetch(`${API_BASE_URL}/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(res => {
    if (!res.ok) {
      return res.text().then(text => {
        throw new Error(text || `Error saving hire fields (${res.status})`);
      });
    }
    return res;
  });
}

async function captureInactiveMetadataFromAccount({
  candidateId,
  candidateName,
  clientName,
  roleName,
  opportunityId
} = {}) {
  if (typeof window.openInactiveInfoModal !== 'function') return null;
  if (!candidateId || !opportunityId) return null;
  try {
    const modalResult = await window.openInactiveInfoModal({
      candidateName,
      clientName,
      roleName
    });
    if (!modalResult) return null;
    const trimmedComments = modalResult.comments?.trim();
    const normalizedComments = trimmedComments ? trimmedComments : null;
    await persistHireFields(
      candidateId,
      {
        inactive_reason: modalResult.reason,
        inactive_comments: normalizedComments,
        inactive_vinttierror: Boolean(modalResult.vinttiError)
      },
      opportunityId
    );
    return {
      reason: modalResult.reason,
      comments: normalizedComments,
      vinttiError: Boolean(modalResult.vinttiError)
    };
  } catch (err) {
    console.error('❌ Failed to store inactive metadata (account view)', err);
    alert('We saved the end date but could not store the offboarding info. Please try again.');
    return null;
  }
}

function updateCandidateField(candidateId, field, value, opportunityId) {
  if (HIRE_FIELD_NAMES.has(field)) {
    const payloadValue = field.endsWith('_dolar')
      ? parseFloat(String(value).replace(/[^\d.]/g, ''))
      : value;

    if (field.endsWith('_dolar') && isNaN(payloadValue)) return;

    return persistHireFields(candidateId, { [field]: payloadValue }, opportunityId)
      .then(() => {
        console.log(`💾 ${field} saved in hire_opportunity for candidate ${candidateId}`);
        if (field.startsWith('buyout_')) {
          const accountId = getIdFromURL && getIdFromURL();
          if (accountId) loadCandidates(accountId);
        }
      })
      .catch(err => console.error('❌ Failed to save field:', explainFetchError(err)));
  }

  // Fallback candidates table
  return fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [field]: value })
  })
  .then(res => {
    if (!res.ok) throw new Error('Error saving field');
    console.log(`💾 ${field} saved for candidate ${candidateId}`);
  })
  .catch(err => console.error('❌ Failed to save field:', err));
}

function updateBuyoutRow(buyoutId, data) {
  if (!buyoutId) return Promise.resolve();
  return fetch(`${API_BASE_URL}/buyouts/${buyoutId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  }).then((res) => {
    if (!res.ok) {
      return res.text().then((text) => {
        throw new Error(text || 'Failed to update buyout');
      });
    }
    return res.json();
  });
}

function scheduleBuyoutReload() {
  if (buyoutReloadTimer) {
    clearTimeout(buyoutReloadTimer);
  }
  buyoutReloadTimer = setTimeout(() => {
    buyoutReloadTimer = null;
    const accountId = getIdFromURL();
    if (accountId) {
      loadCandidates(accountId);
    }
  }, 400);
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

const INACTIVE_EMAIL_TO = ['angie@vintti.com', 'lara@vintti.com'];
const SEND_EMAIL_ENDPOINT = 'https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email';

function getCurrentAccountName() {
  const input = document.getElementById('account-client-name');
  return input ? (input.value || '').trim() : '';
}

function notifyCandidateInactiveEmail({
  candidateId,
  candidateName,
  clientName,
  roleName,
  endDate,
  opportunityId
}) {
  if (!endDate) return Promise.resolve();

  const displayName = (candidateName || '').trim() || `Candidate #${candidateId}`;
  const subject = `Inactive candidate – ${displayName}`;

  const detailRows = [
    { label: 'End date', value: endDate },
    { label: 'Client', value: clientName },
    { label: 'Role', value: roleName },
    { label: 'Opportunity ID', value: opportunityId }
  ].filter(item => item.value);

  const detailHtml = detailRows.length
    ? `<div style="background:#f5f7fa;border-radius:14px;padding:18px 20px;margin:0 0 20px;">
        ${detailRows.map(item => `<p style="margin:0 0 10px;font-size:15px;color:#111927;">
          <span style="font-weight:600;">${item.label}:</span> ${item.value}
        </p>`).join('')}
      </div>`
    : '';

  const htmlBody = `
    <div style="font-family:'Inter','Segoe UI',Arial,sans-serif;font-size:15px;line-height:1.65;color:#243B53;">
      <p style="margin:0 0 18px;font-size:16px;">Hi Lara,</p>
      <p style="margin:0 0 18px;">
        <strong>${displayName}</strong> has just been marked as
        <strong style="color:#b42318;">inactive</strong>.
      </p>
      ${detailHtml}
      <p style="margin:0 0 16px;">
        Please proceed with the <strong>billing adjustments</strong> and coordinate the
        <strong>laptop pickup</strong> with the client.
      </p>
      <p style="margin:0;font-size:14px;color:#52606d;">
        Thanks,<br/>
        <strong>Vintti Hub</strong>
      </p>
    </div>
  `.trim();

  return fetch(SEND_EMAIL_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      to: INACTIVE_EMAIL_TO,
      subject,
      body: htmlBody
    })
  })
  .then(res => {
    if (!res.ok) {
      return res.text().then(text => {
        throw new Error(`send_email failed ${res.status}: ${text}`);
      });
    }
    console.log(`📨 Notified Lara about inactive candidate ${candidateId}`);
  })
  .catch(err => console.error('❌ Failed to notify Lara about inactive candidate', err));
}

function explainFetchError(err) {
  // helper opcional para debug
  return err;
}

async function deletePDF(key) {
  const accountId = getIdFromURL();
  if (!accountId || !key) return;

  if (!confirm("Are you sure you want to delete this PDF?")) return;

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/pdfs`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key })
    });
    if (!res.ok) throw new Error("Failed to delete PDF");
    await loadAccountPdfs(accountId);
  } catch (err) {
    console.error("Error deleting PDF:", err);
    alert("Failed to delete PDF");
  }
}
async function renamePDF(key, new_name) {
  const accountId = getIdFromURL();
  if (!accountId || !key || !new_name) return;

  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/pdfs`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, new_name })
  });

  if (!res.ok) throw new Error("Failed to rename PDF");
  await loadAccountPdfs(accountId);
}
async function loadAccountPdfs(accountId) {
  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/pdfs`);
    const pdfs = await res.json();
    renderPdfList(pdfs);
  } catch (err) {
    console.error("Error loading account PDFs:", err);
  }
}

function renderPdfList(pdfs = []) {
  const container = document.getElementById("pdfPreviewContainer");
  if (!container) return;

  container.classList.add("contracts-list");
  container.innerHTML = "";

  if (!Array.isArray(pdfs) || pdfs.length === 0) {
    container.innerHTML = `
      <div class="contract-item" style="justify-content:center; color:#666;">
        📄 No contracts uploaded yet — use the Upload button.
      </div>`;
    return;
  }

  pdfs.forEach(pdf => {
    const row = document.createElement("div");
    row.className = "contract-item";

    row.innerHTML = `
      <div class="contract-left">
        <span class="file-icon">📄</span>
        <a class="file-name" href="${pdf.url}" target="_blank" title="${pdf.name}">${pdf.name}</a>
        <input
          class="file-edit hidden"
          type="text"
          value="${pdf.name}"
          placeholder="Type a new name…"
          aria-label="Rename file"
          data-orig="${pdf.name}"
        />
      </div>
      <div class="contract-right">
        <button class="icon-btn rename-btn">Rename</button>
        <button class="icon-btn save-btn hidden">Save</button>
        <button class="icon-btn cancel-btn hidden">Cancel</button>
        <a class="link-btn" href="${pdf.url}" target="_blank">Open</a>
        <button class="icon-btn icon-danger delete-btn" data-key="${pdf.key}">Delete</button>
      </div>
    `;

    const nameLink   = row.querySelector(".file-name");
    const nameInput  = row.querySelector(".file-edit");
    const renameBtn  = row.querySelector(".rename-btn");
    const saveBtn    = row.querySelector(".save-btn");
    const cancelBtn  = row.querySelector(".cancel-btn");
    const deleteBtn  = row.querySelector(".delete-btn");

    // Rename flow
const enterEdit = () => {
  nameLink.classList.add('hidden');
  renameBtn.classList.add('hidden');

  nameInput.classList.remove('hidden');
  saveBtn.classList.remove('hidden');
  cancelBtn.classList.remove('hidden');

  // Asegura que el input tenga el nombre actual y se enfoque
  nameInput.value = nameInput.dataset.orig || nameLink.textContent || '';
  requestAnimationFrame(() => {
    nameInput.focus();
    nameInput.select();
  });
};

const exitEdit = () => {
  nameLink.classList.remove('hidden');
  renameBtn.classList.remove('hidden');

  nameInput.classList.add('hidden');
  saveBtn.classList.add('hidden');
  cancelBtn.classList.add('hidden');
};

// init: garantiza que arranca oculto
nameInput.classList.add('hidden');

renameBtn.addEventListener("click", enterEdit);
cancelBtn.addEventListener("click", exitEdit);

saveBtn.addEventListener("click", async () => {
  let newName = (nameInput.value || "").trim();
  if (!newName) return;

  if (!/\.pdf$/i.test(newName)) newName += ".pdf";
  newName = newName.replace(/[\/\\]/g, "-");

  try {
    // feedback inmediato
    nameLink.textContent = newName;
    nameLink.title = newName;

    await renamePDF(pdf.key, newName);
    // actualiza el "original" para próximos edits
    nameInput.dataset.orig = newName;
    exitEdit();
  } catch (e) {
    alert("Failed to rename file");
    console.error(e);
  }
});

nameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") saveBtn.click();
  if (e.key === "Escape") cancelBtn.click();
});

    // Delete
    deleteBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const key = deleteBtn.getAttribute("data-key");
      deletePDF(key);
    });

    container.appendChild(row);
  });
}

function truncateFileName(name, maxLen = 26) {
  if (!name) return "";
  return name.length > maxLen ? name.slice(0, maxLen - 7) + "…" + name.slice(-6) : name;
}

function ensurePdfStyles() {
  if (document.getElementById("pdf-styles")) return;
  const style = document.createElement("style");
  style.id = "pdf-styles";
  style.textContent = `
    /* Grid contenedor */
    #pdfPreviewContainer.pdf-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 14px;
      align-items: start;
    }
    /* Tarjeta */
    .pdf-card {
      position: relative;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 8px 22px var(--shadow);
      overflow: hidden;
      transition: transform .15s ease, box-shadow .15s ease;
    }
    .pdf-card:hover {
      transform: translateY(-2px);
      box-shadow: 0 10px 28px var(--shadow);
    }
    /* Área clicable completa para abrir */
    .pdf-open-overlay {
      position: absolute;
      inset: 0 0 40px 0; /* no cubre el footer de meta */
      z-index: 1;
    }
    /* Preview PDF */
    .pdf-thumb {
      width: 100%;
      height: 240px;
      border: none;
      background: #fff;
      display: block;
    }
    .pdf-fallback { padding: 24px; font-size: 13px; }
    /* Meta */
    .pdf-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      background: linear-gradient(180deg, rgba(255,255,255,0.6), rgba(0,0,0,0.02));
      backdrop-filter: saturate(110%) blur(2px);
    }
    .pdf-name {
      max-width: 65%;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      font-weight: 600;
      color: var(--text);
      font-size: 12.5px;
    }
    .pdf-actions {
      display: flex;
      gap: 8px;
      z-index: 2;
    }
    .open-btn {
      font-size: 12px;
      padding: 4px 8px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: var(--bg);
      text-decoration: none;
      color: var(--text);
    }
    .open-btn:hover { background: var(--accent); }
    .delete-btn {
      border: none;
      background: transparent;
      cursor: pointer;
      font-size: 16px;
      line-height: 1;
      opacity: .8;
    }
    .delete-btn:hover { opacity: 1; transform: scale(1.05); }
    /* Vacío */
    .pdf-empty {
      border: 1.5px dashed var(--border);
      border-radius: 16px;
      padding: 20px;
      text-align: center;
      color: #666;
      background: var(--card);
    }
  `;
  document.head.appendChild(style);
}

function renderStatusChip(status) {
  const s = String(status || '').toLowerCase();
  const cls = (s === 'inactive') ? 'inactive' : 'active';
  const label = cls.charAt(0).toUpperCase() + cls.slice(1);
  return `<span class="status-chip ${cls}">${label}</span>`;
}

let statusInfoOverlay = null;
let statusInfoTitle = null;
let statusInfoSubtitle = null;
let statusInfoContent = null;
let statusChipEventsBound = false;
let statusInfoKeyListenerBound = false;

function applyStatusChipMetadata(row, candidate = {}, statusValue) {
  if (!row) return;
  const chip = row.querySelector('.status-chip');
  if (!chip) return;
  const normalizedStatus = String(statusValue || '').toLowerCase() === 'inactive' ? 'inactive' : 'active';
  chip.dataset.statusPopup = '1';
  chip.dataset.statusType = normalizedStatus;
  chip.dataset.candidateId = candidate.candidate_id ?? '';
  chip.dataset.candidateName = candidate.name || '';
  chip.dataset.positionName = candidate.opp_position_name || '';
  chip.dataset.salary = candidate.employee_salary ?? '';
  chip.dataset.startDate = dateInputValue(candidate.start_date) || '';
  chip.dataset.clientName = candidate.client_name || candidate.account_name || '';
  chip.dataset.inactiveReason = candidate.inactive_reason || '';
  chip.dataset.inactiveComments = candidate.inactive_comments || '';
  chip.dataset.inactiveVinttierror = candidate.inactive_vinttierror ? 'true' : 'false';
}

function setupStatusChipEvents() {
  if (statusChipEventsBound) return;
  const employeesSection = document.getElementById('employees');
  if (!employeesSection) return;
  employeesSection.addEventListener('click', (event) => {
    const chip = event.target.closest('.status-chip');
    if (!chip || !employeesSection.contains(chip)) return;
    if (!chip.dataset.statusPopup) return;
    event.preventDefault();
    handleStatusChipClick(chip);
  });
  statusChipEventsBound = true;
}

function handleStatusChipClick(chip) {
  if (!chip) return;
  openStatusInfoPopup({
    status: chip.dataset.statusType || '',
    name: chip.dataset.candidateName || '',
    positionName: chip.dataset.positionName || '',
    salary: chip.dataset.salary,
    startDate: chip.dataset.startDate || '',
    inactiveReason: chip.dataset.inactiveReason || '',
    inactiveComments: chip.dataset.inactiveComments || '',
    inactiveVinttierror: chip.dataset.inactiveVinttierror || '',
    clientName: chip.dataset.clientName || ''
  });
}

function openStatusInfoPopup(meta = {}) {
  ensureStatusInfoUi();
  if (!statusInfoOverlay || !statusInfoTitle || !statusInfoSubtitle || !statusInfoContent) return;
  const normalizedStatus = String(meta.status || '').toLowerCase() === 'inactive' ? 'inactive' : 'active';
  const candidateName = meta.name || 'Candidate';
  const clientName = meta.clientName || '';

  if (normalizedStatus === 'inactive') {
    statusInfoTitle.textContent = `${candidateName} is inactive`;
    const subtitle = clientName ? `Offboarding info for ${clientName}` : 'Offboarding info';
    statusInfoSubtitle.textContent = subtitle;
    statusInfoSubtitle.style.display = 'block';
    setStatusInfoRows([
      { label: 'Reason', value: meta.inactiveReason || 'Not provided' },
      { label: 'Comments', value: meta.inactiveComments || 'No comments added' },
      {
        label: 'Vintti process error?',
        value: (meta.inactiveVinttierror === 'true' || meta.inactiveVinttierror === true) ? 'Yes' : 'No'
      }
    ]);
  } else {
    statusInfoTitle.textContent = `${candidateName} is active`;
    const subtitle = clientName ? `Working with ${clientName}` : 'Active engagement details';
    statusInfoSubtitle.textContent = subtitle;
    statusInfoSubtitle.style.display = 'block';
    const startReadable = formatReadableDate(meta.startDate);
    const tenureText = describeTenure(meta.startDate);
    const tenureDisplay = startReadable ? `${tenureText} (since ${startReadable})` : tenureText;
    setStatusInfoRows([
      { label: 'Position', value: meta.positionName || 'Not provided' },
      { label: 'Salary', value: formatCurrencyDisplay(meta.salary) },
      { label: 'Time with client', value: tenureDisplay }
    ]);
  }

  requestAnimationFrame(() => {
    statusInfoOverlay.classList.add('is-visible');
  });
}

function closeStatusInfoPopup() {
  if (statusInfoOverlay) {
    statusInfoOverlay.classList.remove('is-visible');
  }
}

function ensureStatusInfoUi() {
  ensureStatusInfoStyles();
  if (statusInfoOverlay) return;
  statusInfoOverlay = document.createElement('div');
  statusInfoOverlay.className = 'status-info-overlay';
  statusInfoOverlay.innerHTML = `
    <div class="status-info-card" role="dialog" aria-modal="true">
      <button type="button" class="status-info-close" aria-label="Close dialog">×</button>
      <div class="status-info-eyebrow">Employee status</div>
      <h3 class="status-info-title"></h3>
      <p class="status-info-subtitle"></p>
      <div class="status-info-rows"></div>
    </div>
  `;
  document.body.appendChild(statusInfoOverlay);
  statusInfoTitle = statusInfoOverlay.querySelector('.status-info-title');
  statusInfoSubtitle = statusInfoOverlay.querySelector('.status-info-subtitle');
  statusInfoContent = statusInfoOverlay.querySelector('.status-info-rows');
  const closeBtn = statusInfoOverlay.querySelector('.status-info-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', closeStatusInfoPopup);
  }
  statusInfoOverlay.addEventListener('click', (event) => {
    if (event.target === statusInfoOverlay) closeStatusInfoPopup();
  });
  if (!statusInfoKeyListenerBound) {
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeStatusInfoPopup();
    });
    statusInfoKeyListenerBound = true;
  }
}

function ensureStatusInfoStyles() {
  if (document.getElementById('status-info-styles')) return;
  const style = document.createElement('style');
  style.id = 'status-info-styles';
  style.textContent = `
.status-info-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 20px;
  z-index: 9998;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.2s ease;
}
.status-info-overlay.is-visible {
  opacity: 1;
  pointer-events: auto;
}
.status-info-card {
  width: min(420px, 100%);
  background: #fff;
  border-radius: 20px;
  padding: 26px;
  box-shadow: 0 30px 60px rgba(15, 23, 42, 0.25);
  font-family: 'Onest', 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  position: relative;
}
.status-info-close {
  position: absolute;
  top: 14px;
  right: 14px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: rgba(15, 23, 42, 0.08);
  cursor: pointer;
  font-size: 20px;
  line-height: 1;
}
.status-info-eyebrow {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: #6366f1;
  font-weight: 600;
  margin-bottom: 6px;
}
.status-info-title {
  margin: 0 0 4px;
  font-size: 24px;
  color: #0f172a;
}
.status-info-subtitle {
  margin: 0 0 18px;
  font-size: 14px;
  color: #475569;
}
.status-info-rows {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.status-info-row {
  background: #f8faff;
  border-radius: 14px;
  padding: 12px 14px;
}
.status-info-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #94a3b8;
  margin-bottom: 4px;
}
.status-info-value {
  font-size: 15px;
  color: #0f172a;
  font-weight: 600;
  word-break: break-word;
}
`;
  document.head.appendChild(style);
}

function setStatusInfoRows(rows = []) {
  if (!statusInfoContent) return;
  statusInfoContent.innerHTML = '';
  rows.forEach(({ label, value }) => {
    const row = document.createElement('div');
    row.className = 'status-info-row';
    const labelEl = document.createElement('span');
    labelEl.className = 'status-info-label';
    labelEl.textContent = label;
    const valueEl = document.createElement('span');
    valueEl.className = 'status-info-value';
    valueEl.textContent = value || '—';
    row.appendChild(labelEl);
    row.appendChild(valueEl);
    statusInfoContent.appendChild(row);
  });
}

function formatCurrencyDisplay(value) {
  if (value === null || value === undefined) return 'Not provided';
  const strValue = typeof value === 'string' ? value.trim() : value;
  if (strValue === '' || strValue === '—') return 'Not provided';
  const num = Number(strValue);
  if (Number.isNaN(num)) return `$${strValue}`;
  try {
    return num.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
  } catch (err) {
    return `$${num}`;
  }
}

function describeTenure(startDate) {
  const iso = dateInputValue(startDate);
  if (!iso) return 'Start date not available';
  const start = new Date(iso);
  if (isNaN(start)) return 'Start date not available';
  const now = new Date();
  if (now < start) return 'Starts in the future';

  let years = now.getFullYear() - start.getFullYear();
  let months = now.getMonth() - start.getMonth();
  let days = now.getDate() - start.getDate();

  if (days < 0) {
    months -= 1;
    const previousMonth = new Date(now.getFullYear(), now.getMonth(), 0);
    days += previousMonth.getDate();
  }
  if (months < 0) {
    years -= 1;
    months += 12;
  }

  const parts = [];
  if (years > 0) parts.push(`${years} yr${years === 1 ? '' : 's'}`);
  if (months > 0) parts.push(`${months} mo${months === 1 ? '' : 's'}`);
  if (!parts.length) {
    if (days > 0) {
      parts.push(`${days} day${days === 1 ? '' : 's'}`);
    } else {
      parts.push('Less than a day');
    }
  }
  return parts.join(' ');
}

function formatReadableDate(value) {
  const iso = dateInputValue(value);
  if (!iso) return '';
  const date = new Date(iso);
  if (isNaN(date)) return '';
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function isRealISODate(v) {
  if (!v) return false;
  const s = String(v).trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(s);
}
function fmtISODate(v) {
  // devuelve vacío si no hay fecha real
  return isRealISODate(v) ? new Date(v).toLocaleDateString('en-US') : '';
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;

    // activar botón
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    // mostrar/ocultar secciones
    document.querySelectorAll(".tab-content").forEach(sec => {
      const on = sec.id === tab;
      sec.classList.toggle("active", on);
      sec.hidden = !on;
    });

    // cargar billing.html en iframe cuando abres invoice
    if (tab === "invoice") {
      loadBonusRequests().catch(console.error);
  const frame = document.getElementById("billingFrame");
  if (!frame) return;

  const url = new URL(window.location.href);

  // intenta varias keys comunes:
  const accountId =
    url.searchParams.get("account_id") ||
    url.searchParams.get("id") ||
    url.searchParams.get("accountId");

  console.log("Invoice tab open. accountId =", accountId);

  if (!accountId) {
    frame.srcdoc = `<div style="font-family:Onest,system-ui;padding:20px;color:#fff;background:#0b0d10">
      No encontré account_id en la URL 😭 <br/>
      Agrega ?account_id=123 o ajusta el JS a tu parámetro real.
    </div>`;
    return;
  }

  const month = new Date().toISOString().slice(0, 7); // YYYY-MM
  frame.src = `billing.html?account_id=${encodeURIComponent(accountId)}&month=${month}`;
}

  });
});

document.getElementById('requestBonusBtn')?.addEventListener('click', () => {
  const params = new URLSearchParams(window.location.search);
  const accountId = params.get('id'); // porque account-details usa ?id=32

  if (!accountId) {
    alert('Missing account id in URL');
    return;
  }

  const url = `bonus-form.html?account_id=${encodeURIComponent(accountId)}`;
  window.open(url, '_blank', 'noopener,noreferrer');
});

function getAccountIdFromUrl(){
  const p = new URLSearchParams(window.location.search);
  return p.get("id") || p.get("account_id") || null;
}

document.getElementById("requestBonusBtn")?.addEventListener("click", () => {
  const accountId = getAccountIdFromUrl();
  if (!accountId) {
    alert("Account id missing in Account Details URL");
    return;
  }

  // si bonus-form.html está en la misma carpeta /docs:
  const url = `bonus-form.html?id=${encodeURIComponent(accountId)}`;
  window.open(url, "_blank", "noopener,noreferrer");
});

//FORM DATAAA

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;

    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");

    document.querySelectorAll(".tab-content").forEach(sec => {
      const on = sec.id === tab;
      sec.classList.toggle("active", on);
      sec.hidden = !on;
    });

    if (tab === "invoice") {
      const frame = document.getElementById("billingFrame");
      if (!frame) return;

      const params = new URLSearchParams(window.location.search);
      const accountId = params.get("id"); // en account-details usas ?id=32

      if (!accountId) {
        frame.srcdoc = `<div style="padding:20px;font-family:Onest,system-ui">Missing account id</div>`;
        return;
      }

      const month = new Date().toISOString().slice(0, 7);
      frame.src = `billing.html?account_id=${encodeURIComponent(accountId)}&month=${month}`;
    }
  });
});



//form data

function getAccountId() {
  const p = new URLSearchParams(window.location.search);
  return p.get("id") || p.get("account_id");
}

function money(currency, amount) {
  const n = Number(amount || 0);
  return `${currency || ""} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
}

function badge(status) {
  const s = String(status || "pending").toLowerCase();
  return `<span class="badge ${s}">${s}</span>`;
}

async function loadBonusRequests(){
  console.log("➡️ loadBonusRequests running");
console.log("accountId =", getAccountId());

  const tbody = document.getElementById("bonusTbody");
  if (!tbody) return;

  const accountId = getAccountId();
  if (!accountId) {
    tbody.innerHTML = `<tr><td colspan="7">Missing account id</td></tr>`;
    return;
  }

  tbody.innerHTML = `<tr><td colspan="7">Loading…</td></tr>`;

  const url = `${API_BASE_URL}/public/bonus_request/account/${encodeURIComponent(accountId)}`;
  const res = await fetch(url, { credentials: "include" });

  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    tbody.innerHTML = `<tr><td colspan="7">Error ${res.status}: ${txt}</td></tr>`;
    return;
  }

  const data = await res.json();
  const items = data.items || [];

    // 1) pinta tabla primero SIEMPRE
  tbody.innerHTML = items.map(b => {
    const employee =
  b.candidate_id
    ? (b.candidate_name || `Candidate #${b.candidate_id}`)
    : (b.employee_name_manual || "—");

    const inv = b.invoice_target === "specific_month"
      ? `Specific (${String(b.target_month || "").slice(0,7)})`
      : "Next invoice";

    return `
      <tr>
        <td>${String(b.created_date || "").slice(0,10)}</td>
        <td>${employee}</td>
        <td>${money(b.currency, b.amount)}</td>
        <td>${String(b.payout_date || "").slice(0,10)}</td>
        <td>${inv}</td>
        <td>${badge(b.status)}</td>
        <td>${b.approver_name || "—"}</td>
      </tr>
    `;
  }).join("");

  // 2) luego crea ToDos SIN romper la UI
  items.forEach(b => {
  const payoutRaw =
    b.payout_date ?? b.payout ?? b.payout_at ?? b.payoutDate ?? b.payout_datetime;

  const payoutISO = toISODateOrNull(payoutRaw); // YYYY-MM-DD o null

  if (!payoutISO) {
    console.warn("⚠️ Bonus sin payout parseable:", {
      bonus_request_id: b.bonus_request_id,
      payoutRaw,
      keys: Object.keys(b || {})
    });
    return; // 👈 NO crees ToDo si no hay payout real
  }

  const employee =
  b.candidate_id ? (b.candidate_name || `Candidate #${b.candidate_id}`) : (b.employee_name_manual || "Employee");


  const amt = `${b.currency || ""} ${Number(b.amount || 0).toFixed(2)}`.trim();
const accLabel =
  getCurrentAccountName() ||
  (b.account_name || "").trim() ||
  `account #${b.account_id}`;

  upsertTodoTask({
    sourceKey: `bonus_request:${b.bonus_request_id}`,
    description: `Pagar bono ${amt} a ${employee} (${accLabel})`,
    due_date: payoutISO,
  }).catch(err => console.warn("upsertTodoTask failed:", err));
});

}

document.addEventListener("DOMContentLoaded", () => {
  // Si invoice ya está activo al cargar, carga bonus de una vez
  const activeTab = document.querySelector(".tab-btn.active")?.dataset?.tab;
  if (activeTab === "invoice") {
    loadBonusRequests().catch(err => console.error("loadBonusRequests failed:", err));
  }

  // Botón Reload
  document.getElementById("btnReloadBonus")?.addEventListener("click", () => {
    loadBonusRequests().catch(err => console.error("reload failed:", err));
  });
});

// TODO FORM


async function apiFetch(path, opts = {}) {
  const url = `${API_BASE_URL}${path}`;
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };

  const token = localStorage.getItem("token") || localStorage.getItem("access_token");
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(url, { credentials: "include", ...opts, headers });
  const ct = res.headers.get("content-type") || "";
  const payload = ct.includes("application/json") ? await res.json() : await res.text();

  if (!res.ok) {
    const msg = payload?.error || payload?.message || (typeof payload === "string" ? payload : "Request failed");
    throw new Error(msg);
  }
  return payload;
}

// async function upsertTodoTask({ sourceKey, description, due_date, forceUserId = null }) {
//   const userId = forceUserId ?? (Number(localStorage.getItem("user_id")) || null);
//   if (!userId) return;

//   const tasks = await apiFetch(`/to_do?user_id=${encodeURIComponent(userId)}`);
//   const list = Array.isArray(tasks) ? tasks : [];
//   const marker = `[AUTO:${sourceKey}]`;

//   const existing = list.find(t => (t.description || "").includes(marker));

//   const safeDue = toISODateOrNull(due_date);   // ✅ CLAVE
//   const payload = {
//     user_id: userId,
//     description: `${marker} ${description}`,
//     due_date: safeDue,                         // null o YYYY-MM-DD
//     check: existing ? Boolean(existing.check) : false,
//   };

//   if (existing) {
//     await apiFetch(`/to_do/${existing.to_do_id}`, {
//       method: "PATCH",
//       body: JSON.stringify(payload),
//     });
//   } else {
//     await apiFetch(`/to_do`, {
//       method: "POST",
//       body: JSON.stringify(payload),
//     });
//   }
// }

function toISODateOrNull(v){
  if (!v) return null;
  const s = String(v).trim();

  // ya viene ISO
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;

  // timestamp ISO
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
  if (m) return m[1];

  // NO aceptamos "Fri, 27 Fe" etc -> null
  const d = new Date(s);
  if (isNaN(d)) return null;

  const yyyy = d.getFullYear();
  const mm = String(d.getMonth()+1).padStart(2,"0");
  const dd = String(d.getDate()).padStart(2,"0");
  return `${yyyy}-${mm}-${dd}`;
}

function todayISO(){
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
}

async function upsertTodoTask({ sourceKey, description, due_date, forceUserId=null }){
  const userId = forceUserId ?? (Number(localStorage.getItem("user_id")) || null);
  if (!userId) throw new Error("Missing localStorage user_id");

  const safeDue = toISODateOrNull(due_date); // ✅ solo ISO o null
  if (!safeDue) throw new Error(`Invalid due_date for ${sourceKey}: ${due_date}`);

  const tasks = await apiFetch(`/to_do?user_id=${encodeURIComponent(userId)}`);
  const list = Array.isArray(tasks) ? tasks : [];
  const marker = `[AUTO:${sourceKey}]`;
  const existing = list.find(t => (t.description || "").includes(marker));

  if (existing) {
    await apiFetch(`/to_do/${existing.to_do_id}`, {
      method: "DELETE",
      body: JSON.stringify({ user_id: userId }),
    });
  }

  await apiFetch(`/to_do`, {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      description: `${marker} ${description}`,
      due_date: safeDue, // ✅ payout real
    }),
  });
}

const AGUSTIN_USER_ID = 1;        // ✅ ya lo tienes
const LARA_USER_ID    = 2;      // 👈 pon el ID real de Lara

const TODO_ASSIGNEES = [AGUSTIN_USER_ID, LARA_USER_ID];

async function createBonusTodosForApprovers(b){
  const payoutRaw =
    b.payout_date ?? b.payout ?? b.payout_at ?? b.payoutDate ?? b.payout_datetime;

  const payoutISO = toISODateOrNull(payoutRaw);
  if (!payoutISO) return;

  const employee = b.candidate_id
    ? (b.candidate_name || `Candidate #${b.candidate_id}`)
    : (b.employee_name_manual || "Employee");

  const amt = `${b.currency || ""} ${Number(b.amount || 0).toFixed(2)}`.trim();

  const accLabel =
    getCurrentAccountName() ||
    (b.account_name || "").trim() ||
    `account #${b.account_id}`;

  await Promise.allSettled(
    TODO_ASSIGNEES.map(uid =>
      upsertTodoTask({
        // ✅ mismo bonus, pero distinto “marker” por usuario para que no choquen
        sourceKey: `bonus_request:${b.bonus_request_id}:assignee:${uid}`,
        description: `Pagar bono ${amt} a ${employee} (${accLabel})`,
        due_date: payoutISO,
        forceUserId: uid
      })
    )
  );
}
