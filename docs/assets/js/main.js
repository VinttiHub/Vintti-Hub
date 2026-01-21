// =========================
// Interviewing popup
// =========================
let _interviewingOppId = null;
let _interviewingDropdownEl = null;

const STAGE_ORDER_PRIORITY = [
  'Negotiating',
  'Sourcing',
  'Interviewing',
  'NDA Sent',
  'Deep Dive',
  'Close Win',
  'Closed Lost'
];

function openInterviewingPopup(opportunityId, dropdownElement) {
  _interviewingOppId = Number(opportunityId);
  _interviewingDropdownEl = dropdownElement;

  const popup = document.getElementById('interviewingPopup');
  const input = document.getElementById('interviewingStartDate');
  const saveBtn = document.getElementById('saveInterviewingStartDate');

  if (!popup || !input || !saveBtn) {
    console.error('❌ Interviewing popup elements not found in HTML');
    return;
  }

  // reset
  input.value = '';

  popup.style.display = 'flex';

  // IMPORTANT: asignar onclick para no duplicar listeners
  saveBtn.onclick = async () => {
    const date = (input.value || '').trim();
    if (!date) {
      alert('Please select a start date.');
      return;
    }

    try {
      // 1) Insert en tabla interviewing
      const res = await fetch(`${API_BASE}/interviewing`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          opportunity_id: _interviewingOppId,
          since_interviewing: date
        })
      });

      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        console.error('❌ /interviewing failed:', res.status, txt);
        alert('Error saving interviewing start date. Please try again.');
        return;
      }

      // 2) Cambiar stage
      await patchOpportunityStage(_interviewingOppId, 'Interviewing', _interviewingDropdownEl);

      // 3) Cerrar
      closeInterviewingPopup();

    } catch (err) {
      console.error('❌ Interviewing save error:', err);
      alert('Network error. Please try again.');
    }
  };
}

function closeInterviewingPopup() {
  const popup = document.getElementById('interviewingPopup');
  if (popup) popup.style.display = 'none';
  _interviewingOppId = null;
  _interviewingDropdownEl = null;
}

// (Opcional) cerrar al clickear el overlay (background)
document.addEventListener('click', (e) => {
  const overlay = document.getElementById('interviewingPopup');
  if (overlay && e.target === overlay) closeInterviewingPopup();
});
// === Helper: traer el nombre del cliente desde accounts usando account_id ===
async function resolveAccountName(opp) {
  // si ya viene correcto, úsalo
  const direct = (opp.client_name || '').trim();
  if (direct) return direct;

  const accountId = opp.account_id ?? opp.accountId ?? opp.accountid ?? null;
  if (!accountId) return 'the client';

  try {
    // intenta endpoint REST de item único
    let r = await fetch(`${API_BASE}/accounts/${encodeURIComponent(accountId)}`, { credentials: 'include' });
    if (r.ok) {
      const acc = await r.json();
      return (acc.client_name || acc.account_name || acc.name || '').trim() || 'the client';
    }

    // fallback: buscar en lista si no tienes endpoint por id
    r = await fetch(`${API_BASE}/accounts`, { credentials: 'include' });
    if (r.ok) {
      const list = await r.json();
      const acc = (list || []).find(a =>
        String(a.account_id ?? a.id ?? '').trim() === String(accountId).trim()
      );
      if (acc) return (acc.client_name || acc.account_name || acc.name || '').trim() || 'the client';
    }
  } catch (e) {
    console.warn('resolveAccountName() failed:', e);
  }
  return 'the client';
}

// ——— Current user helpers ———
function getCurrentUserEmail(){
  return (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase()
    .trim();
}

const _plainTextParser = document.createElement('div');
function htmlToPlainText(value) {
  if (value === null || value === undefined) return '';
  _plainTextParser.innerHTML = value;
  const text = _plainTextParser.textContent || _plainTextParser.innerText || '';
  _plainTextParser.textContent = '';
  return text;
}

function escapeAttribute(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '&#10;');
}
// --- Email cuando se asigna / cambia HR Lead en una oportunidad ---
async function sendHRLeadAssignmentEmail(opportunityId, hrEmail) {
  try {
    const cleanEmail = String(hrEmail || '').toLowerCase().trim();
    if (!cleanEmail) {
      console.warn('⚠️ No HR Lead email to notify for opp', opportunityId);
      return;
    }

    // 1) Traer detalles de la oportunidad
    const r = await fetch(`${API_BASE}/opportunities/${opportunityId}`, { 
      credentials: 'include' 
    });
    if (!r.ok) throw new Error(`GET opp ${opportunityId} failed ${r.status}`);
    const opp = await r.json();

    // 2) Resolver client_name desde accounts
    const clientName = await resolveAccountName(opp);
    const position   = opp.opp_position_name || 'Role';
    const model      = opp.opp_model || '';

    // 3) Subject info de client & position
    const subject = `You’ve been assigned a new search – ${clientName} | ${position}`;

    // Por si quieres usar escapeHtml del helper global
    const esc = s => String(s || '').replace(/[&<>"]/g, ch => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]
    ));

    // 4) Cuerpo en HTML, amigable y cute
    const htmlBody = `
<div style="font-family: Inter, Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.6;">
  <p>Hi there 💕</p>

  <p>
    You’ve just been assigned a brand new search in Vintti Hub – how exciting! ✨
  </p>

  <p style="margin: 12px 0;">
    <strong>Client:</strong> ${esc(clientName)}<br/>
    <strong>Position:</strong> ${esc(position)}<br/>
    <strong>Model:</strong> ${esc(model)}
  </p>

  <p>
    You’re going to do amazing on this one – as always. 🌸<br/>
  </p>

  <p style="margin-top: 16px; font-size: 12px; color: #777;">
    - Vintti Hub
  </p>
</div>
    `.trim();

    // 5) Enviar email a HR Lead + Angie
    const payload = {
      to: [cleanEmail]
        .filter((v, i, arr) => v && arr.indexOf(v) === i),
      subject,
      body: htmlBody,
      body_html: htmlBody,
      content_type: 'text/html',
      html: true
    };

    const res = await fetch(`${API_BASE}/send_email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      throw new Error(`send_email failed ${res.status}: ${errText}`);
    }

    console.info('✅ HR Lead assignment email sent to', cleanEmail, 'for opp', opportunityId);
  } catch (err) {
    console.error('❌ Failed to send HR Lead assignment email:', err);
  }
}

const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

// Try to get user_id from storage; if missing, resolve by email and cache it
// Usa getCurrentUserId({force:true}) para ignorar cache.
async function getCurrentUserId({ force = false } = {}) {
  const email = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase()
    .trim();

  // invalida cache si cambió el email o si piden "force"
  const cachedUid = localStorage.getItem('user_id');
  const cachedOwner = localStorage.getItem('user_id_owner_email');
  if (force || (cachedOwner && cachedOwner !== email)) {
    localStorage.removeItem('user_id');
  }

  // 1) ¿Sigue habiendo cache válido?
  const cached = localStorage.getItem('user_id');
  console.debug('[uid] cached:', cached, '(owner:', localStorage.getItem('user_id_owner_email'), ')');
  if (cached) return Number(cached);

  if (!email) {
    console.warn('[uid] No email available to resolve user_id');
    return null;
  }

  // 2) Fast path: /users?email=
  try {
    const fast = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/users?email=${encodeURIComponent(email)}`);
    console.debug('[uid] /users?email status:', fast.status);
    if (fast.ok) {
      const arr = await fast.json(); // [] o [ { user_id, email_vintti, ... } ]
      const hit = Array.isArray(arr) ? arr.find(u => (u.email_vintti || '').toLowerCase() === email) : null;
      console.debug('[uid] hit (by email):', hit?.user_id);
      if (hit?.user_id != null) {
        localStorage.setItem('user_id', String(hit.user_id));
        localStorage.setItem('user_id_owner_email', email);
        return Number(hit.user_id);
      }
    }
  } catch (e) {
    console.debug('users?email lookup failed (will try full list):', e);
  }

  // 3) Fallback: /users (full) y match por email
  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users');
    console.debug('[uid] /users status:', res.status);
    if (!res.ok) return null;
    const users = await res.json();
    const me = (users || []).find(u => String(u.email_vintti || '').toLowerCase() === email);
    console.debug('[uid] hit (by full list):', me?.user_id);
    if (me?.user_id != null) {
      localStorage.setItem('user_id', String(me.user_id));
      localStorage.setItem('user_id_owner_email', email);
      return Number(me.user_id);
    }
  } catch (e) {
    console.error('Could not resolve current user_id:', e);
  }
  return null;
}
window.getCurrentUserId = getCurrentUserId;
// ——— API helper que SIEMPRE intenta enviar el usuario ———
async function api(path, opts = {}) {
  const uid = await window.getCurrentUserId(); // puede ser null
  const url = `${API_BASE}${path}`;

  // 1) Intento con cookie + header X-User-Id si lo tengo
  let headers = { ...(opts.headers || {}) };
  if (uid != null) headers['X-User-Id'] = String(uid);

  let r = await fetch(url, {
    ...opts,
    headers,
    credentials: 'include'
  });

  // 2) Si el backend/proxy quitó headers o hay 401, reintenta con ?user_id=
  if (r.status === 401 && uid != null) {
    const sep = url.includes('?') ? '&' : '?';
    const urlWithQuery = `${url}${sep}user_id=${encodeURIComponent(uid)}`;
    r = await fetch(urlWithQuery, {
      ...opts,
      credentials: 'include'
    });
  }

  return r;
}
window.api = api;
// ——— Helpers de nombre/escape ———
function escapeHtml(s){
  return String(s || '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
}

function prettyNameFromEmail(email, fallback = 'Assign HR Lead') {
  const local = String(email || '').split('@')[0];
  if (!local) return fallback;
  const cleaned = local.replace(/[_\-.]+/g, ' ').trim();
  if (!cleaned) return fallback;
  return cleaned.split(/\s+/).map(part => part ? part[0].toUpperCase() + part.slice(1) : '').join(' ') || fallback;
}

function displayNameForHR(email){
  const key = String(email||'').toLowerCase();
  if (!key) return 'Assign HR Lead';
  const directoryName = (window.userDirectoryByEmail || {})[key];
  if (directoryName) return directoryName;
  const u = (window.allowedHRUsers||[]).find(x => String(x.email_vintti||'').toLowerCase() === key);
  if (u?.user_name) return u.user_name;
  return prettyNameFromEmail(email, 'Assign HR Lead');
}

function displayNameForSales(value){
  const key = String(value||'').toLowerCase();

  // 1) Si viene email -> busca por email
  let u = (window.allowedSalesUsers||[]).find(x => String(x.email_vintti||'').toLowerCase() === key);
  if (u?.user_name) return u.user_name;

  // 2) Si viene nombre -> busca por nombre
  u = (window.allowedSalesUsers||[]).find(x => String(x.user_name||'').toLowerCase() === key);
  if (u?.user_name) return u.user_name;

  // 3) Fallback heurístico legacy
  if (key.includes('bahia'))   return 'Bahía';
  if (key.includes('lara'))    return 'Lara';
  if (key.includes('agustin')) return 'Agustín';
  if (key.includes('mariano')) return 'Mariano';

  // 4) Último recurso
  return String(value||'Unassigned');
}

const HIDDEN_HR_FILTER_EMAILS = new Set([
  'bahia@vintti.com',
  'sol@vintti.com',
  'agustin@vintti.com',
  'agustina.ferrari@vintti.com',
].map((email) => email.toLowerCase()));

const SALES_ALLOWED_EMAILS = new Set([
  'agustin@vintti.com',
  'bahia@vintti.com',
  'lara@vintti.com',
  'mariano@vintti.com',
].map((email) => email.toLowerCase()));

const SALES_ALLOWED_NAME_OVERRIDES = new Map([
  ['agustin@vintti.com', 'Agustín'],
  ['bahia@vintti.com', 'Bahía'],
  ['lara@vintti.com', 'Lara'],
  ['mariano@vintti.com', 'Mariano'],
]);

function buildDefaultSalesUsers() {
  return Array.from(SALES_ALLOWED_EMAILS)
    .map((email) => ({
      user_id: null,
      user_name: SALES_ALLOWED_NAME_OVERRIDES.get(email) || prettyNameFromEmail(email, email),
      email_vintti: email,
    }))
    .sort((a, b) => (a.user_name || '').localeCompare(b.user_name || ''));
}
window.allowedSalesUsers = (window.allowedSalesUsers && window.allowedSalesUsers.length)
  ? window.allowedSalesUsers
  : buildDefaultSalesUsers();
window.allowedHRUsers = window.allowedHRUsers || [];
window.userDirectoryByEmail = window.userDirectoryByEmail || {};
let roleDirectoryPromise = null;

function normalizeRoleDirectory(users) {
  const deduped = [];
  const seen = new Set();
  (Array.isArray(users) ? users : []).forEach(user => {
    const email = String(user?.email_vintti || '').trim().toLowerCase();
    if (!email || seen.has(email)) return;
    seen.add(email);
    deduped.push({
      user_id: user.user_id,
      user_name: user.user_name || user.email_vintti || email,
      email_vintti: email
    });
  });
  deduped.sort((a, b) => (a.user_name || '').localeCompare(b.user_name || ''));
  return deduped;
}

function buildUserDirectoryMap(users) {
  const map = {};
  (Array.isArray(users) ? users : []).forEach((user) => {
    const email = String(user?.email_vintti || '').trim().toLowerCase();
    if (!email || map[email]) return;
    if (user?.user_name) map[email] = user.user_name;
  });
  return map;
}

async function fetchRoleDirectories() {
  const [hrRes, salesRes, usersRes] = await Promise.all([
    fetch(`${API_BASE}/users/recruiters`, { credentials: 'include' }),
    fetch(`${API_BASE}/users/sales-leads`, { credentials: 'include' }),
    fetch(`${API_BASE}/users`, { credentials: 'include' }),
  ]);
  if (!hrRes.ok) throw new Error(`Recruiter directory failed: ${hrRes.status}`);
  if (!salesRes.ok) throw new Error(`Sales directory failed: ${salesRes.status}`);
  if (!usersRes.ok) throw new Error(`Users directory failed: ${usersRes.status}`);
  const [hrData, salesData, usersData] = await Promise.all([hrRes.json(), salesRes.json(), usersRes.json()]);
  window.allowedHRUsers = normalizeRoleDirectory(hrData);
  window.allowedSalesUsers = normalizeRoleDirectory(salesData);
  window.userDirectoryByEmail = buildUserDirectoryMap(usersData);

  if (!window.allowedSalesUsers.length) {
    const fallbackFromUsers = (Array.isArray(usersData) ? usersData : []).filter((user) => {
      const email = String(user?.email_vintti || '').trim().toLowerCase();
      return email && SALES_ALLOWED_EMAILS.has(email);
    });
    if (fallbackFromUsers.length) {
      window.allowedSalesUsers = normalizeRoleDirectory(fallbackFromUsers);
    } else {
      window.allowedSalesUsers = buildDefaultSalesUsers();
    }
  }
}

function ensureRoleDirectoryPromise() {
  if (!roleDirectoryPromise) {
    roleDirectoryPromise = fetchRoleDirectories().catch(err => {
      console.error('Error loading role directories:', err);
      throw err;
    });
  }
  return roleDirectoryPromise;
}

async function ensureRoleDirectoriesLoaded() {
  if ((window.allowedHRUsers?.length || 0) && (window.allowedSalesUsers?.length || 0)) return;
  await ensureRoleDirectoryPromise();
}

ensureRoleDirectoryPromise();

window.generateSalesOptions = function generateSalesOptions(currentValue) {
  const normalized = String(currentValue || '').trim().toLowerCase();
  const allowedEmails = new Set((window.allowedSalesUsers || []).map(u => u.email_vintti));
  const isKnown = !!normalized && allowedEmails.has(normalized);

  let html = `<option disabled ${isKnown ? '' : 'selected'}>Assign Sales Lead</option>`;
  (window.allowedSalesUsers || []).forEach(user => {
    const email = user.email_vintti;
    const selected = (isKnown && email === normalized) ? 'selected' : '';
    html += `<option value="${email}" ${selected}>${escapeHtml(user.user_name)}</option>`;
  });
  return html;
};

window.generateHROptions = function generateHROptions(currentValue) {
  const normalized = String(currentValue || '').trim().toLowerCase();
  const visibleHrUsers = (window.allowedHRUsers || []).filter((user) => !HIDDEN_HR_FILTER_EMAILS.has(user.email_vintti));
  const allowedEmails = new Set(visibleHrUsers.map((u) => u.email_vintti));
  const isKnown = !!normalized && allowedEmails.has(normalized);
  const isHiddenSelection = !!normalized && HIDDEN_HR_FILTER_EMAILS.has(normalized);

  const shouldSelectDefault = !isKnown && (!normalized || isHiddenSelection);
  let html = `<option disabled ${shouldSelectDefault ? 'selected' : ''}>Assign HR Lead</option>`;
  visibleHrUsers.forEach((user) => {
    const email = user.email_vintti;
    const selected = normalized && email === normalized ? 'selected' : '';
    html += `<option value="${email}" ${selected}>${escapeHtml(user.user_name)}</option>`;
  });

  if (normalized && !isKnown && !isHiddenSelection) {
    const fallbackLabel = displayNameForHR(normalized) || prettyNameFromEmail(normalized);
    if (fallbackLabel && fallbackLabel !== 'Assign HR Lead') {
      html += `<option value="${normalized}" selected>${escapeHtml(fallbackLabel)}</option>`;
    }
  }
  return html;
};

document.addEventListener('DOMContentLoaded', () => {
  // --- Replacement UI wiring ---
    const el = document.getElementById('click-sound');
  el?.load();
const oppTypeSelect = document.getElementById('opp_type');
const replacementFields = document.getElementById('replacementFields');
const replacementCandidateInput = document.getElementById('replacementCandidate');
const replacementCandidatesList  = document.getElementById('replacementCandidates');
const replacementEndDateInput    = document.getElementById('replacementEndDate');

function toggleReplacementFields() {
  const isReplacement = oppTypeSelect && oppTypeSelect.value === 'Replacement';
  if (replacementFields) replacementFields.style.display = isReplacement ? 'block' : 'none';
  if (!isReplacement) {
    if (replacementCandidateInput) replacementCandidateInput.value = '';
    if (replacementEndDateInput) replacementEndDateInput.value = '';
  }
}
oppTypeSelect?.addEventListener('change', toggleReplacementFields);
toggleReplacementFields();

// Small debounce helper
function debounce(fn, wait = 250) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
}

// Live search against /candidates?search=
replacementCandidateInput?.addEventListener('input', debounce(async (e) => {
  const q = e.target.value.trim();
  if (q.length < 2) return; // avoid spam
  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates?search=${encodeURIComponent(q)}`);
    const items = await res.json();
    replacementCandidatesList.innerHTML = '';
    items.forEach(({ candidate_id, name }) => {
      const opt = document.createElement('option');
      opt.value = `${candidate_id} - ${name}`;
      replacementCandidatesList.appendChild(opt);
    });
  } catch (err) {
    console.error('Error searching candidates:', err);
  }
}, 250));

function getReplacementCandidateId() {
  if (!replacementCandidateInput?.value) return null;
  const idStr = replacementCandidateInput.value.split(' - ')[0];
  const id = parseInt(idStr, 10);
  return Number.isInteger(id) ? id : null;
}

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


function setupFilterToggle(header, targetIdOverride) {
  if (!header || header.dataset.filterToggleBound === 'true') return;
  const targetId = targetIdOverride || header.getAttribute('data-target');
  if (!targetId) return;
  const icon = header.querySelector('i');

  function toggle() {
    const target = document.getElementById(targetId);
    if (!target) return;
    const isHidden = target.classList.toggle('hidden');
    if (icon) {
      icon.classList.toggle('rotate-up', !isHidden);
    }
  }

  header.addEventListener('click', toggle);
  const button = header.querySelector('button');
  if (button) {
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      toggle();
    });
  }
  header.dataset.filterToggleBound = 'true';
}

document.querySelectorAll('.filter-header').forEach((header) => setupFilterToggle(header));
  const toggleButton = document.getElementById('toggleFilters');
  const filtersCard = document.getElementById('filtersCard');

  if (toggleButton && filtersCard) {
    toggleButton.addEventListener('click', () => {
      const isExpanded = filtersCard.classList.contains('expanded');
      filtersCard.classList.toggle('expanded', !isExpanded);
      filtersCard.classList.toggle('hidden', isExpanded);
      toggleButton.textContent = isExpanded ? '🔍 Filters' : '✖ Close Filters';
    });
  }
  const onOppPage = !!document.getElementById('opportunityTableBody');
  if (onOppPage) {
  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light')
    .then(response => response.json())
    .then(async data => {
      
      const tbody = document.getElementById('opportunityTableBody');
      tbody.innerHTML = '';
      // 🔄 Enriquecer con latest_sourcing_date solo para oportunidades en 'Sourcing'
      await Promise.all(data.map(async opp => {
        if (opp.opp_stage === 'Sourcing') {
          try {
            const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opp.opportunity_id}/latest_sourcing_date`);
            const result = await res.json();
            if (result.latest_sourcing_date) {
              opp.latest_sourcing_date = result.latest_sourcing_date;
            }
          } catch (err) {
            console.error(`Error fetching sourcing date for opp ${opp.opportunity_id}`, err);
          }
        }
      }));
      // ✅ Precalcular días para ordenar Sourcing
      const today = new Date();
      for (const opp of data) {
        if (opp.opp_stage === 'Sourcing') {
          const ref = opp.latest_sourcing_date || opp.nda_signature_or_start_date || null;
          if (ref) {
            const d = new Date(ref);
            opp._days_since_batch = Math.ceil((today - d) / (1000 * 60 * 60 * 24)) - 1;
          } else {
            opp._days_since_batch = null; // sin fecha aún
          }
        }
      }

      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9">No data available</td></tr>';
        return;
      }

    // 👇 Orden de etapas personalizado
    const stageOrder = STAGE_ORDER_PRIORITY;

    // 👇 Agrupar oportunidades por stage
    const grouped = {};
    data.forEach(opp => {
      const stage = opp.opp_stage || '—';

      // Para Sourcing: usar exclusivamente nda_signature_or_start_date
      if (stage === 'Sourcing') {
        opp._sort_date = opp.nda_signature_or_start_date || null;
      }

      // Para Close Win / Closed Lost: usar opp_close_date
      else if (stage === 'Close Win' || stage === 'Closed Lost') {
        opp._sort_date = opp.opp_close_date || null;
      }

      // Otros stages: usar nda_signature_or_start_date como respaldo
      else {
        opp._sort_date = opp.nda_signature_or_start_date || null;
      }

      if (!grouped[stage]) grouped[stage] = [];
      grouped[stage].push(opp);
    });


    // 👇 Vaciar tbody
    tbody.innerHTML = '';
    // Ordenar internamente cada grupo por la fecha relevante
    Object.keys(grouped).forEach(stage => {
      grouped[stage].sort((a, b) => {
        if (stage === 'Sourcing') {
          const A = (typeof a._days_since_batch === 'number') ? a._days_since_batch : -Infinity;
          const B = (typeof b._days_since_batch === 'number') ? b._days_since_batch : -Infinity;
          return B - A; // 👈 mayor a menor por Days Since Batch
        }
        // 🔁 el resto queda con tu lógica por fecha
        const dateA = a._sort_date ? new Date(a._sort_date) : new Date(0);
        const dateB = b._sort_date ? new Date(b._sort_date) : new Date(0);
        return dateB - dateA;
      });
    });

    // 👇 Insertar oportunidades en orden
    stageOrder.forEach(stage => {
      if (grouped[stage]) {
        grouped[stage].forEach(opp => {
          let daysAgo = '';

          // 👉 Si la opp está en Close Win o Closed Lost:
          //    Days = diferencia entre start date y close date
          if (opp.opp_stage === 'Close Win' || opp.opp_stage === 'Closed Lost') {
            if (opp.nda_signature_or_start_date && opp.opp_close_date) {
              daysAgo = calculateDaysBetween(
                opp.nda_signature_or_start_date,
                opp.opp_close_date
              );
            } else if (opp.nda_signature_or_start_date) {
              // fallback si por alguna razón no hay close_date
              daysAgo = calculateDaysAgo(opp.nda_signature_or_start_date);
            } else {
              daysAgo = '-';
            }
          }
          // 👉 Para el resto de etapas: se mantiene la lógica actual
          else if (opp.nda_signature_or_start_date) {
            daysAgo = calculateDaysAgo(opp.nda_signature_or_start_date);
          } else {
            daysAgo = '-';
          }

          const tr = document.createElement('tr');
          let daysSinceBatch = (opp.opp_stage === 'Sourcing' && typeof opp._days_since_batch === 'number')
            ? opp._days_since_batch
            : '-';

          async function fetchDaysSinceBatch(opp, tr) {
            const oppId = opp.opportunity_id;

            // 👉 celda de "Days Since Sourcing" (última columna)
            const daysCell = tr.querySelector('td:last-child');
            if (!daysCell) return;

            try {
              // 1) Intentar usar la fecha ya enriquecida o el start_date
              let referenceDate = null;
              if (opp.latest_sourcing_date) {
                referenceDate = new Date(opp.latest_sourcing_date);
              } else if (opp.nda_signature_or_start_date) {
                referenceDate = new Date(opp.nda_signature_or_start_date);
              } else {
                // 2) Fallback: pedirla al backend
                const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/latest_sourcing_date`);
                const result = await res.json();
                if (result.latest_sourcing_date) {
                  referenceDate = new Date(result.latest_sourcing_date);
                }
              }
              // 3) Si no hay fecha, no contamos
              if (!referenceDate) {
                colorizeSourcingCell(daysCell, null);
                return;
              }

              // 4) Calcular días (misma fórmula que usas en Days)
              const today = new Date();
              const diffTime = today - referenceDate;
              const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1;

              // 5) Pintar con semáforo (verde / amarillo / rojo)
              colorizeSourcingCell(daysCell, diffDays);
            } catch (err) {
              console.error(`Error fetching sourcing date para opp ${oppId}:`, err);
            }
          }

          const plainComment = htmlToPlainText(opp.comments || '');
          const typeLabel = opp.opp_type || '';
          tr.innerHTML = `
            <td>${getStageDropdown(opp.opp_stage, opp.opportunity_id)}</td>
            <td>${opp.client_name || ''}</td>
            <td>${opp.opp_position_name || ''}</td>
            <td data-type-value="${escapeAttribute(typeLabel)}">
              ${getTypeBadge(typeLabel)}
              <span class="sr-only type-label">${escapeHtml(typeLabel)}</span>
            </td>
            <td>${opp.opp_model || ''}</td>
            <td class="sales-lead-cell">${getSalesLeadCell(opp)}</td>
            <td class="hr-lead-cell">
              ${getHRLeadCell(opp)}
            </td>
            <td>
              <input
                type="text"
                class="comment-input"
                data-id="${opp.opportunity_id}"
                data-original-value="${escapeAttribute(plainComment)}"
                value="${escapeAttribute(plainComment)}"
              />
            </td>
            <td>${daysAgo}</td>
            <td>${daysSinceBatch}</td>
          `;

          tr.querySelectorAll('td').forEach((cell, index) => {
            cell.setAttribute('data-col-index', index);
          });

          tr.addEventListener('click', (e) => {
            const td = e.target.closest('td');
            if (!td) return;
            const cellIndex = parseInt(td.getAttribute('data-col-index'), 10);
            if ([0, 5, 6, 7].includes(cellIndex)) return; // 5 = Sales Lead
            openOpportunity(opp.opportunity_id);
          });

          tbody.appendChild(tr);
          tr.style.opacity = 1;
          tr.style.animation = 'none';
            if (opp.opp_stage === 'Sourcing') {
              const daysCell = tr.querySelector('td:last-child');
              if (typeof opp._days_since_batch === 'number') {
                colorizeSourcingCell(daysCell, opp._days_since_batch);
              } else {
                // Sin fecha luego del enriquecimiento → usar tu fallback asíncrono existente
                fetchDaysSinceBatch(opp, tr);
              }
            }
          if (opp.opp_stage === 'Sourcing') {
            fetchDaysSinceBatch(opp, tr);
          }
        });
      }
    });
console.info("🔢 Fetched opportunities:", data.length); // justo antes de crear la tabla

const table = $('#opportunityTable').DataTable({

  responsive: true,
  pageLength: 50,                         // puedes dejar 50 por defecto…
  lengthMenu: [[50, 100, 150, -1], [50, 100, 150, 'All']], // …pero permite ver “All”
  dom: 'lrtip',
  ordering: false,
  columnDefs: [
    { targets: [0], width: "8%" },
    { targets: [1, 2, 3, 4, 5, 6, 8], width: "10%" },
    { targets: 7, width: "25%" },
    {
      targets: 0,
      render: function (data, type) {
        if (type === 'filter' || type === 'sort') {
          const div = document.createElement('div');
          div.innerHTML = data;
          const select = div.querySelector('select');
          return select ? select.options[select.selectedIndex].textContent : data;
        }
        return data;
      }
    },
    {
      targets: 5,
      render: function (data, type) {
        if (type === 'filter' || type === 'sort') {
          const div = document.createElement('div');
          div.innerHTML = data;
          const hidden = div.querySelector('.sr-only');
          return hidden ? hidden.textContent : div.textContent || data;
        }
        return data;
      }
    },
    {
      targets: 6,
      render: function (data, type) {
        if (type === 'filter' || type === 'sort') {
          const div = document.createElement('div');
          div.innerHTML = data;
          const select = div.querySelector('select');
          return select ? select.options[select.selectedIndex].textContent : data;
        }
        return data;
      }
    }
  ],
  language: {
    search: "🔍 Buscar:",
    lengthMenu: "Mostrar _MENU_ registros por página",
    zeroRecords: "No se encontraron resultados",
    info: "Mostrando _START_ a _END_ de _TOTAL_ registros",
    paginate: { first: "Primero", last: "Último", next: "Siguiente", previous: "Anterior" }
  }
});
   table.search('');
 table.columns().search('');
 table.draw();
const uniqueTypes = [...new Set(
  data
    .map(d => (d.opp_type || '').trim())
    .filter(Boolean)
)].sort((a, b) => a.localeCompare(b));

window.__typeFilterState = {
  selected: new Set(uniqueTypes.map((type) => type.toLowerCase())),
};

if (!window.__typeFilterExtRegistered && $.fn?.dataTable?.ext?.search) {
  $.fn.dataTable.ext.search.push((settings, rowData, rowIndex) => {
    if (!settings?.nTable || settings.nTable.id !== 'opportunityTable') return true;
    const selection = window.__typeFilterState?.selected;
    if (!selection || selection.size === 0) return true;
    const row = settings.aoData?.[rowIndex]?.nTr;
    const cell = row?.querySelector('[data-type-value]');
    const value = String(cell?.getAttribute('data-type-value') || '')
      .trim()
      .toLowerCase();
    return selection.has(value);
  });
  window.__typeFilterExtRegistered = true;
}

const accountSearchInput = document.getElementById('accountSearchInput');
if (accountSearchInput) {
  accountSearchInput.addEventListener('input', () => {
    const value = accountSearchInput.value;
    table.column(1).search(value, true, false).draw(); // columna 1 = Account
  });
}

const positionSearchInput = document.getElementById('positionSearchInput');
if (positionSearchInput) {
  positionSearchInput.addEventListener('input', () => {
    const value = positionSearchInput.value;
    table.column(2).search(value, true, false).draw(); // columna 2 = Position
  });
}
// 🔒 Asegura que allowedHRUsers esté cargado (el fetch /users arriba puede no haber terminado)
if (!window.allowedHRUsers || !window.allowedHRUsers.length) {
  try {
    await ensureRoleDirectoriesLoaded();
  } catch (e) {
    console.error('Error reloading HR Leads:', e);
  }
}

// Mapa email->nombre priorizando tabla users
const emailToNameMap = { ...(window.userDirectoryByEmail || {}) };
(window.allowedHRUsers || []).forEach(u => {
  const email = String(u.email_vintti || '').toLowerCase();
  if (email && !emailToNameMap[email]) emailToNameMap[email] = u.user_name;
});

// STAGES (igual que antes)
const uniqueStages = [...new Set(data.map(d => d.opp_stage).filter(Boolean))].sort((a, b) => {
  const idxA = STAGE_ORDER_PRIORITY.indexOf(a);
  const idxB = STAGE_ORDER_PRIORITY.indexOf(b);
  if (idxA === -1 && idxB === -1) return a.localeCompare(b);
  if (idxA === -1) return 1;
  if (idxB === -1) return -1;
  return idxA - idxB;
});

// SALES LEAD: agrega 'Unassigned' si hay filas sin nombre
let uniqueSalesLeads = [...new Set(data.map(d => d.sales_lead_name).filter(Boolean))];
if (data.some(d => !d.sales_lead_name)) {
  uniqueSalesLeads.push('Unassigned'); // coincide con regex ^$ que pondremos abajo
}

// HR LEAD: mostrar nombre completo y ocultar ciertos correos
const hrLeadNameToEmail = {};
let uniqueHRLeads = [...new Set(
  data.map(d => {
    const hrEmailRaw = String(d.opp_hr_lead || '').trim();
    const hrEmail = hrEmailRaw.toLowerCase();
    if (!hrEmail) return 'Assign HR Lead';
    if (HIDDEN_HR_FILTER_EMAILS.has(hrEmail)) return null;
    const label = emailToNameMap[hrEmail] || displayNameForHR(hrEmailRaw);
    if (label && label !== 'Assign HR Lead') {
      hrLeadNameToEmail[label.toLowerCase()] = hrEmail;
      return label;
    }
    return 'Assign HR Lead';
  }).filter(Boolean)
)];
if (!uniqueHRLeads.includes('Assign HR Lead')) uniqueHRLeads.unshift('Assign HR Lead');
window.hrLeadNameToEmail = hrLeadNameToEmail;
const filterRegistry = [];
// Llama a los filtros con estas opciones
buildMultiFilter('filterStage',     uniqueStages,     0, 'Stage',      'Stage',    table);
buildMultiFilter('filterSalesLead', uniqueSalesLeads, 5, 'Sales Lead', 'SalesLead',table);
buildMultiFilter('filterHRLead',    uniqueHRLeads,    6, 'HR Lead',    'HRLead',   table);
buildMultiFilter('filterType',      uniqueTypes,      3, 'Type',       'Type',     table);

const dtLength = document.querySelector('#opportunityTable_length');
const dtTarget = document.getElementById('dataTablesLengthTarget');
if (dtLength && dtTarget) dtTarget.appendChild(dtLength);

   const selectedFilters = { Stage: [], SalesLead: [], HRLead: [] };

 function renderActiveFilters() {
   const bar = document.getElementById('activeFilters');
   if (!bar) return;
   const groups = Object.entries(selectedFilters).filter(([_, arr]) => arr.length);
   if (!groups.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
   bar.style.display = 'flex';
   bar.innerHTML = groups.map(([group, arr]) =>
     arr.map(val => `
       <span class="filter-chip" data-group="${group}" data-value="${val}">
         <strong>${group}:</strong> ${val} <span class="x" title="Remove">✕</span>
       </span>
     `).join('')
   ).join('');
 }

 // click en "x" del chip para quitarlo
 document.addEventListener('click', (e) => {
   const x = e.target.closest('.filter-chip .x');
   if (!x) return;
   const chip = x.parentElement;
   const group = chip.getAttribute('data-group');
   const value = chip.getAttribute('data-value');
   const idMap = { Stage: 'filterStage', SalesLead: 'filterSalesLead', HRLead: 'filterHRLead' };
   const cont = document.getElementById(idMap[group]);
  if (cont) {
    const cb = Array.from(cont.querySelectorAll('input[type="checkbox"]')).find(c => c.value === value);
    if (cb) { cb.checked = false; cb.dispatchEvent(new Event('change', { bubbles: true })); }
   }
 });



// Mapa de clases CSS para cada Stage → puntito
const STAGE_DOT_CLASS = {
  'Negotiating': 'stage-dot--negotiating',
  'Interviewing': 'stage-dot--interviewing',
  'Sourcing': 'stage-dot--sourcing',
  'NDA Sent': 'stage-dot--nda',
  'Deep Dive': 'stage-dot--deep-dive',
  'Close Win': 'stage-dot--close-win',
  'Closed Lost': 'stage-dot--closed-lost'
};

function buildMultiFilter(containerId, options, columnIndex, displayName, filterKey, dataTable) {
  const DOT_CLASS = {
    'Negotiating': 'stage-dot--negotiating',
    'Interviewing': 'stage-dot--interviewing',
    'Sourcing': 'stage-dot--sourcing',
    'NDA Sent': 'stage-dot--nda',
    'Deep Dive': 'stage-dot--deep-dive',
    'Close Win': 'stage-dot--close-win',
    'Closed Lost': 'stage-dot--closed-lost'
  };

  const IS_STAGE = (containerId === 'filterStage');
  const IS_SALES = (containerId === 'filterSalesLead');
  const IS_HR    = (containerId === 'filterHRLead');
  const IS_TYPE  = (containerId === 'filterType');

  const container = document.getElementById(containerId);
  if (!container) return;

  const column = dataTable.column(columnIndex);
  if (typeof filterRegistry !== 'undefined' && Array.isArray(filterRegistry)) {
    filterRegistry.push({ containerId, columnIndex });
  }

  // Header del filtro
  const headerWrap =
    document.querySelector(`#${containerId}Container .filter-header`) ||
    document.querySelector(`.filter-header[data-target="${containerId}"]`);
  if (headerWrap) setupFilterToggle(headerWrap, containerId);

  // Barras de puntitos en el header:
  // - Stage usa .stage-dot-bar (ya la tienes en el HTML; si no, la creo)
  // - HR y Sales usan .lead-dot-bar (creadas aquí)
  let stageDotBar = null;
  if (IS_STAGE && headerWrap) {
    stageDotBar = headerWrap.querySelector('.stage-dot-bar');
    if (!stageDotBar) {
      stageDotBar = document.createElement('span');
      stageDotBar.className = 'stage-dot-bar';
      headerWrap.insertBefore(stageDotBar, headerWrap.querySelector('button') || null);
    }
  }

  let leadDotBar = null;
  if ((IS_SALES || IS_HR) && headerWrap) {
    leadDotBar = headerWrap.querySelector('.lead-dot-bar');
    if (!leadDotBar) {
      leadDotBar = document.createElement('span');
      leadDotBar.className = 'lead-dot-bar';
      leadDotBar.id = containerId + 'DotBar';
      headerWrap.insertBefore(leadDotBar, headerWrap.querySelector('button') || null);
    }
  }

  // Botón select/deselect all
  const selectToggle = document.createElement('button');
  selectToggle.className = 'select-toggle';
  container.appendChild(selectToggle);

  // Lista de checkboxes
  const checkboxWrapper = document.createElement('div');
  checkboxWrapper.classList.add('checkbox-list');
  container.appendChild(checkboxWrapper);

  // Initial selection: Stage deselects wins/losses, others select all
  const DEFAULT_EXCLUDED = IS_STAGE ? new Set(['Close Win', 'Closed Lost']) : null;
  const initialSelection = new Set(
    options.filter((val) => !(DEFAULT_EXCLUDED && DEFAULT_EXCLUDED.has(val)))
  );
  if (initialSelection.size === 0) {
    options.forEach((val) => initialSelection.add(val));
  }
  const anyUnchecked = initialSelection.size !== options.length;
  selectToggle.textContent = anyUnchecked ? 'Select All' : 'Deselect All';

  // Render checkboxes
  options.forEach(val => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = val;
    checkbox.checked = initialSelection.has(val);
    label.appendChild(checkbox);
    label.append(' ' + val);
    checkboxWrapper.appendChild(label);
  });

  if (IS_TYPE && window.__typeFilterState) {
    window.__typeFilterState.selected = new Set(
      Array.from(initialSelection).map((val) => String(val || '').trim().toLowerCase())
    );
  }

  function escapeRegex(s){ return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  // Helpers para HR/Sales avatar-dots
  function computeInitials(name){
    return (String(name||'')
      .trim()
      .split(/\s+/)
      .map(w => w[0] || '')
      .join('')
      .slice(0,2) || '—').toUpperCase();
  }
function nameToEmail(label, isHR){
  const lower = String(label||'').toLowerCase();
  if (isHR && window.hrLeadNameToEmail) {
    const mapped = window.hrLeadNameToEmail[lower];
    if (mapped) return mapped;
  }

  const arr = isHR ? (window.allowedHRUsers||[]) : (window.allowedSalesUsers||[]);
  const match = arr.find(u => String(u.user_name||'').toLowerCase() === lower);
  if (match?.email_vintti) return match.email_vintti;

  if (isHR) {
    // ➕ primero casos específicos
    if (lower.includes('paz'))                                    return 'paz@vintti.com';
    if (lower.includes('pilar') && lower.includes('fernandez')) return 'pilar.fernandez@vintti.com';
    if (lower.includes('pilar'))                                 return 'pilar@vintti.com';

    if (lower.includes('jazmin'))                                 return 'jazmin@vintti.com';
    if (lower.includes('agostina') && lower.includes('barbero'))  return 'agustina.barbero@vintti.com';
    if (lower.includes('agostina') && lower.includes('ferrari'))  return 'agustina.ferrari@vintti.com';
    if (lower === 'agustina barbero')                             return 'agustina.barbero@vintti.com';
    if (lower === 'agustina ferrari')                             return 'agustina.ferrari@vintti.com';
    if (lower.includes('agostina'))                               return 'agostina@vintti.com';
  } else {
    if (lower.includes('bahia'))   return 'bahia@vintti.com';
    if (lower.includes('lara'))    return 'lara@vintti.com';
    if (lower.includes('agustin')) return 'agustin@vintti.com';
    if (lower.includes('mariano')) return 'mariano@vintti.com';
  }

  return '';
}


  // Pintar puntitos de Stage (colores)
  function paintStageDots(selectedList) {
    if (!IS_STAGE || !stageDotBar) return;
    stageDotBar.innerHTML = '';
    if (!selectedList.length) return;

    selectedList.forEach(stage => {
      const span = document.createElement('span');
      span.className = 'stage-dot ' + (DOT_CLASS[stage] || 'stage-dot--default');
      span.setAttribute('data-tip', stage);
      span.setAttribute('aria-label', stage);
      span.setAttribute('tabindex', '0');
      stageDotBar.appendChild(span);
    });
  }

  // Pintar avatar-dots para HR & Sales
function paintLeadDots(selectedList) {
  if (!(IS_SALES || IS_HR) || !leadDotBar) return;
  leadDotBar.innerHTML = '';
  if (!selectedList.length) return;

  selectedList.forEach(label => {
    const span = document.createElement('span');
    span.className = 'lead-dot';

    const isPlaceholder = /^(Unassigned|Assign HR Lead|Assign Sales Lead)$/i.test(label);

    // email (para avatar) y nombre bonito (para tooltip)
    const email   = isPlaceholder ? '' : nameToEmail(label, IS_HR);
    const fallbackLabel = label || (IS_HR ? 'Assign HR Lead' : 'Unassigned');
    const tipText = isPlaceholder
      ? fallbackLabel
      : (IS_HR
          ? (email ? displayNameForHR(email) : fallbackLabel)
          : displayNameForSales(label));

    // ✅ tooltip + accesibilidad + foco por teclado
    span.setAttribute('data-tip', escapeHtml(tipText));
    span.setAttribute('title',     tipText);         // fallback nativo
    span.setAttribute('aria-label',tipText);
    span.setAttribute('tabindex',  '0');

    if (!isPlaceholder) {
      const avatar = email ? resolveAvatar(email) : null;
      if (avatar) {
        span.innerHTML = `<img src="${avatar}" alt="${escapeHtml(tipText)}">`;
      } else {
        // iniciales si no hay avatar
        span.textContent = (tipText || '')
          .trim().split(/\s+/).map(w => w[0]||'').join('').slice(0,2).toUpperCase() || '—';
      }
    } else {
      span.textContent = '—';
    }

    leadDotBar.appendChild(span);
  });
}

  // Aplicar filtro + refrescar barras
  function applyFilter() {
    const cbs = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const selected = Array.from(cbs).filter(c => c.checked).map(c => c.value);
    const pieces = selected.map(v => (v === 'Unassigned') ? '^$' : escapeRegex(v));
    const pattern = selected.length ? pieces.join('|') : '';

    if (IS_TYPE) {
      if (window.__typeFilterState) {
        window.__typeFilterState.selected = new Set(
          selected.map((val) => String(val || '').trim().toLowerCase()),
        );
      }
      dataTable.draw();
    } else {
      column.search(pattern, true, false).draw();
    }

    if (IS_STAGE) paintStageDots(selected);
    if (IS_HR || IS_SALES) paintLeadDots(selected);

    const allChecked = Array.from(cbs).every(c => c.checked);
    selectToggle.textContent = allChecked ? 'Deselect All' : 'Select All';
  }

  checkboxWrapper.addEventListener('change', applyFilter);
  selectToggle.addEventListener('click', () => {
    const all = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const isDeselecting = selectToggle.textContent === 'Deselect All';
    all.forEach(cb => cb.checked = !isDeselecting);
    applyFilter();
  });

  // Aplica inmediatamente (Stage mantiene CW/CL desmarcados por defecto)
  applyFilter();
}

      document.getElementById('opportunityTable').addEventListener('click', function(e) {
        const target = e.target.closest('.column-filter');
        if (target) {
          e.preventDefault();
          e.stopPropagation();
          const columnIndex = parseInt(target.getAttribute('data-column'), 10);
          createColumnFilter(columnIndex, table);
        }
      });
const uniqueAccounts = [...new Set(data.map(d => d.client_name).filter(Boolean))];
    })
    .catch(err => {
      console.error('Error fetching opportunities:', err);
      const spinner = document.getElementById('spinner-overlay');
      if (spinner) spinner.classList.add('hidden');
    });
} else {
  // Opcional: silencio/diagnóstico en index
  console.debug('No hay tabla de oportunidades en esta página; omito inicialización.');
}

const CLOSE_WIN_CELEBRATION_DURATION = 1500;
let closeWinCelebrationTimer = null;

function playCloseWinCelebration(onDone) {
  if (closeWinCelebrationTimer) {
    clearTimeout(closeWinCelebrationTimer);
    closeWinCelebrationTimer = null;
  }

  const existing = document.getElementById('closeWinCelebrationOverlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'closeWinCelebrationOverlay';
  overlay.className = 'close-win-celebration';
  overlay.setAttribute('aria-hidden', 'true');

  const gif = document.createElement('img');
  gif.src = './assets/img/applause.gif';
  gif.alt = 'Celebration fireworks';
  gif.className = 'close-win-celebration__gif';
  overlay.appendChild(gif);

  (document.body || document.documentElement).appendChild(overlay);

  closeWinCelebrationTimer = window.setTimeout(() => {
    overlay.remove();
    closeWinCelebrationTimer = null;
    if (typeof onDone === 'function') {
      onDone();
    }
  }, CLOSE_WIN_CELEBRATION_DURATION);
}

document.addEventListener('change', async (e) => {
    if (e.target && e.target.classList.contains('stage-dropdown')) {
      const newStage = e.target.value;
      const opportunityId = e.target.getAttribute('data-id');

      if (e.target.disabled) {
        alert("This stage is final and cannot be changed.");
        return;
      }

    console.log('🟡 Stage dropdown changed! Opportunity ID:', opportunityId, 'New Stage:', newStage);

    if (newStage === 'Sourcing') {
      openSourcingPopup(opportunityId, e.target);
      return;
    }    
    if (newStage === 'Interviewing') {
      openInterviewingPopup(opportunityId, e.target);
      return;
    }
    if (newStage === 'Close Win') {
      playCloseWinCelebration(() => openCloseWinPopup(opportunityId, e.target));
      return;
    }
    if (newStage === 'Closed Lost') {
      openCloseLostPopup(opportunityId, e.target);
      return;
    }
    await patchOpportunityStage(opportunityId, newStage, e.target);
    const select = e.target;
if (select.classList.contains('stage-dropdown')) {
  // Elimina clases anteriores
  select.classList.forEach(cls => {
    if (cls.startsWith('stage-color-')) select.classList.remove(cls);
  });

  // Agrega la nueva clase
  const newClass = 'stage-color-' + newStage.toLowerCase().replace(/\s/g, '-');
  select.classList.add(newClass);
}

  }
});
document.addEventListener('change', async e => {
  if (!e.target.classList.contains('hr-lead-dropdown')) return;

  const oppId   = e.target.dataset.id;
  const newLead = (e.target.value || '').toLowerCase().trim();

  // Si por alguna razón seleccionan algo vacío o placeholder, no hacemos nada
  if (!newLead) return;

  try {
    // 1) Persistir en backend
    const res = await fetch(`${API_BASE}/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opp_hr_lead: newLead })
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      console.error('❌ Error updating opp_hr_lead:', res.status, txt);
      alert('Error updating HR Lead. Please try again.');
      return;
    }

    // 2) Refrescar display (inicial + avatar) en la misma celda
    const wrap = e.target.closest('.hr-lead-cell-wrap');
    if (wrap) {
      const current = wrap.querySelector('.hr-lead');
      if (current) current.outerHTML = hrDisplayHTML(newLead);
    }

    // 3) Enviar email de asignación de búsqueda (HR Lead + Angie)
    sendHRLeadAssignmentEmail(oppId, newLead);

  } catch (err) {
    console.error('❌ Network error updating HR Lead:', err);
    alert('Network error. Please try again.');
  }
});
document.addEventListener('change', async e => {
  const el = e.target;
  if (!el.classList.contains('sales-lead-dropdown')) return;

  const oppId   = el.dataset.id;
  const newLead = (el.value || '').toLowerCase();

  try {
    // 1) Persistir en backend
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opp_sales_lead: newLead })
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`PATCH sales_lead failed ${res.status}: ${t}`);
    }

    // 2) Refrescar display en la misma celda (iniciales + avatar)
    const wrap = el.closest('.sales-lead-cell-wrap');
    if (wrap) {
      const current = wrap.querySelector('.sales-lead');
      if (current) current.outerHTML = salesDisplayHTML(newLead);
    }
  } catch (err) {
    console.error('❌ Error updating sales lead:', err);
    alert('Error updating Sales Lead. Please try again.');
  }
});

// Evita que el click en el select burbujee y dispare la redirección por fila
document.addEventListener('click', e => {
  if (e.target.closest('.sales-lead-dropdown')) {
    e.stopPropagation();
  }
}, true);

document.addEventListener('blur', async (e) => {
  if (!e.target.classList.contains('comment-input')) return;
  const input = e.target;
  const oppId = input.dataset.id;
  const newComment = input.value;
  const original = input.dataset.originalValue ?? '';
  if (newComment === original) return;

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comments: newComment })
    });
    if (!res.ok) {
      console.error('Failed to update plain comment', res.status);
      return;
    }
    input.dataset.originalValue = newComment;
  } catch (err) {
    console.error('Error updating comment', err);
  }
}, true);

  const helloBtn = document.getElementById('helloGPT');
  const chatResponse = document.getElementById('chatResponse');

  if (helloBtn && chatResponse) {
helloBtn.addEventListener('click', async () => {
  console.log("🚀 Enviando solicitud a /ai/hello...");

  try {
    const res = await fetch('https://vinttihub.vintti.com/ai/hello', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errorText}`);
    }

    const data = await res.json();
    console.log("📥 Respuesta recibida:", data);
    chatResponse.innerText = data.message || '❌ No se recibió mensaje.';
  } catch (err) {
    console.error("❌ Error al contactar ChatGPT:", err);
    chatResponse.innerText = 'Ocurrió un error al hablar con ChatGPT.';
  }
});
  }
const summaryLink = document.getElementById('summaryLink');
const currentUserEmail = localStorage.getItem('user_email');
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 
  'lara@vintti.com','agostina@vintti.com','mariano@vintti.com','jazmin@vintti.com'];

if (summaryLink && allowedEmails.includes(currentUserEmail)) {
  summaryLink.style.display = 'flex';  // o '' para usar el de CSS
}
// --- Candidate Search button visibility ---
const candidateSearchLink = document.getElementById('candidateSearchLink');

if (candidateSearchLink) {
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
    'julieta@vintti.com',
    'paz@vintti.com' 
  ]);

  candidateSearchLink.style.display = CANDIDATE_SEARCH_ALLOWED.has(email) ? 'flex' : 'none';
}

async function initSidebarProfile(){
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

  if ($emailE) { $emailE.textContent = ''; $emailE.style.display = 'none'; }

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

  // resolve uid
  let uid = null;
  try {
    uid = (typeof window.getCurrentUserId === 'function')
      ? (await window.getCurrentUserId())
      : (Number(localStorage.getItem('user_id')) || null);
  } catch {
    uid = Number(localStorage.getItem('user_id')) || null;
  }

  // link
  const base = 'profile.html';
  tile.href = uid != null ? `${base}?user_id=${encodeURIComponent(uid)}` : base;

  // show email initials immediately
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

  // try /users/<uid>, fallback to /profile/me
  let user = null;
  try {
    if (uid != null) {
      const r = await fetch(`${API_BASE}/users/${encodeURIComponent(uid)}?user_id=${encodeURIComponent(uid)}`, { credentials:'include' });
      if (r.ok) user = await r.json();
      else console.debug('[sidebar] /users/<uid> failed:', r.status);
    }
    if (!user) {
      const r2 = await fetch(`${API_BASE}/profile/me${uid!=null?`?user_id=${encodeURIComponent(uid)}`:''}`, { credentials:'include' });
      if (r2.ok) user = await r2.json();
      else console.debug('[sidebar] /profile/me failed:', r2.status);
    }
  } catch (e) {
    console.debug('[sidebar] fetch error:', e);
  }

  const userName = user?.user_name || '';
  if (userName) {
    if ($name) $name.textContent = userName;
    if ($init) $init.textContent = initialsFromName(userName);
  } else if ($name) {
    $name.textContent = 'Profile'; // graceful fallback label
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

  // ensure visible
  const cs = window.getComputedStyle(tile);
  if (cs.display === 'none') tile.style.display = 'flex';
}
initSidebarProfile();
// === Password reset popup (index) ===
const resetModal       = document.getElementById('passwordResetModal');
const openResetBtn     = document.getElementById('open-reset-modal');
const closeResetBtn    = document.getElementById('close-reset-modal');
const resetForm        = document.getElementById('passwordResetForm');
const resetEmailInput  = document.getElementById('resetEmail');
const resetFeedback    = document.getElementById('resetFeedback');

// Abrir popup
openResetBtn?.addEventListener('click', () => {
  // precargar email desde el campo de login si ya está
  const loginEmail = (document.getElementById('email')?.value || '').trim();
  if (loginEmail) resetEmailInput.value = loginEmail;

  resetFeedback.textContent = '';
  resetFeedback.className = 'reset-feedback';
  resetModal.style.display = 'flex';
});

// Cerrar popup
closeResetBtn?.addEventListener('click', () => {
  resetModal.style.display = 'none';
});

// Cerrar si hacen click en el fondo
resetModal?.addEventListener('click', (e) => {
  if (e.target === resetModal) {
    resetModal.style.display = 'none';
  }
});

// Enviar petición de reset
resetForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = resetEmailInput.value.trim().toLowerCase();

  resetFeedback.textContent = '';
  resetFeedback.className = 'reset-feedback';

  if (!email) {
    resetFeedback.textContent = 'Please enter your email.';
    resetFeedback.classList.add('error');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/password_reset_request`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });

    // Por seguridad, aunque el email no exista el backend debe devolver 200
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      console.error('❌ password_reset_request failed:', res.status, txt);
      resetFeedback.textContent = 'There was an error sending the reset email. Please try again.';
      resetFeedback.classList.add('error');
      return;
    }

    resetFeedback.textContent = 'If this email exists, a reset link has been sent.';
    resetFeedback.classList.add('ok');
  } catch (err) {
    console.error('❌ Network error in password_reset_request:', err);
    resetFeedback.textContent = 'Network error. Please try again.';
    resetFeedback.classList.add('error');
  }
});





});

function openPopup() {
  document.getElementById('popup').style.display = 'flex';
}

function closePopup() {
  document.getElementById('popup').style.display = 'none';
}

function openOpportunity(id) {
  const url = `opportunity-detail.html?id=${id}`;
  window.open(url, '_blank'); // 👉 abre en nueva pestaña
}

function navigateTo(section) {
  alert(`Navigation to "${section}" would happen here.`);
}

function createColumnFilter(columnIndex, table) {
  document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());

  const columnData = table
  .column(columnIndex)
  .data()
  .toArray()
  .map(item => extractTextFromHTML(item).trim())
  .filter((v, i, a) => v && a.indexOf(v) === i)
  .sort();


  const container = document.createElement('div');
  container.classList.add('filter-dropdown');

  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.placeholder = 'Search...';
  container.appendChild(searchInput);

  const checkboxContainer = document.createElement('div');
  checkboxContainer.classList.add('checkbox-list');

  columnData.forEach(value => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = value;
    label.appendChild(checkbox);
    label.append(' ' + value);
    checkboxContainer.appendChild(label);
  });

  container.appendChild(checkboxContainer);

  const headerCell = document.querySelectorAll('#opportunityTable thead th')[columnIndex];
  headerCell.appendChild(container);

  searchInput.addEventListener('input', () => {
    const searchTerm = searchInput.value.toLowerCase();
    checkboxContainer.querySelectorAll('label').forEach(label => {
      const text = label.textContent.toLowerCase();
      label.style.display = text.includes(searchTerm) ? 'block' : 'none';
    });
  });

  checkboxContainer.addEventListener('change', () => {
    const selected = Array.from(checkboxContainer.querySelectorAll('input:checked')).map(c => c.value);
    table.column(columnIndex).search(selected.length ? selected.join('|') : '', true, false).draw();
  });
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});

document.getElementById('login-form')?.addEventListener('submit', async function (e) {
  e.preventDefault();                          // ✅ evita que la página se recargue (causante del "Load failed")
  const form = e.currentTarget;
  const email = form.email.value.trim();
  const password = form.password.value;

  // evitemos rechazos del audio en Safari si falla la carga
  document.getElementById('click-sound')?.play().catch(() => {});

  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn?.setAttribute('disabled', 'disabled');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    // leer el cuerpo con fallback por si no es JSON (para logs útiles)
    const raw = await res.text();
    let data = {};
    try { data = JSON.parse(raw); } catch {}

    if (!res.ok || !data.success) {
      const msg = (data && (data.message || data.error)) || `HTTP ${res.status}: ${raw}`;
      alert(msg);
      return;
    }

    const nickname = data.nickname;
    localStorage.setItem('user_email', email.toLowerCase());
    // If backend sent user_id, store it; otherwise resolve & cache now
    if (typeof data.user_id === 'number') {
      localStorage.setItem('user_id', String(data.user_id));
    } else {
      getCurrentUserId().catch(()=>{});
    }
    // Si el backend no mandó user_id, resuélvelo fresco (sin cache)
const finalUid = typeof data.user_id === 'number'
  ? Number(data.user_id)
  : (await getCurrentUserId({ force: true })) ?? null;

if (finalUid != null) {
  localStorage.setItem('user_id', String(finalUid));
  localStorage.setItem('user_id_owner_email', email.toLowerCase());
  console.info('✅ [login] user_id (fresh):', finalUid);
} else {
  console.warn('⚠️ [login] Could not resolve user_id for', email);
}

    const avatarSrc = resolveAvatar(email);
    if (avatarSrc) localStorage.setItem('user_avatar', avatarSrc);
    document.getElementById('personalized-greeting').textContent = `Hey ${nickname}, `;
    document.getElementById('login-container').style.display = 'none';
    document.getElementById('welcome-container').style.display = 'block';
    showWelcomeAvatar(email);
  } catch (err) {
    console.error('Error en login:', err);
    alert('Ocurrió un error inesperado. Intenta de nuevo más tarde.');
  } finally {
    submitBtn?.removeAttribute('disabled');
  }
});
// 🔧 HAZ GLOBAL el helper para que exista donde lo usas
window.getReplacementCandidateId = function () {
  const input = document.getElementById('replacementCandidate');
  if (!input || !input.value) return null;
  const idStr = String(input.value).split(' - ')[0].trim();
  const id = parseInt(idStr, 10);
  return Number.isFinite(id) ? id : null;
};

// --- Create Opportunity form (drop-in fix de scope) ---
const createOpportunityForm = document.getElementById('createOpportunityForm');
const createButton = createOpportunityForm?.querySelector('.create-btn');

// helper seguro para leer el end date del replacement
const getReplacementEndDateEl = () => document.getElementById('replacementEndDate');

if (createOpportunityForm && createButton) {
  // Habilitar/deshabilitar botón según campos
  createOpportunityForm.addEventListener('input', () => {
    const clientName   = createOpportunityForm.client_name.value.trim();
    const oppModel     = createOpportunityForm.opp_model.value;
    const positionName = createOpportunityForm.position_name.value.trim();
    const salesLead    = createOpportunityForm.sales_lead.value;
    const oppType      = createOpportunityForm.opp_type.value;

    const needsReplacement = oppType === 'Replacement';
    const hasRepCandidate  = !!getReplacementCandidateId();
    const hasRepEndDate    = !!getReplacementEndDateEl()?.value;

    const allFilled = clientName && oppModel && positionName && salesLead && oppType &&
                      (!needsReplacement || (hasRepCandidate && hasRepEndDate));

    createButton.disabled = !allFilled;
  });

  // Submit
  createOpportunityForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = {
      client_name:   createOpportunityForm.client_name.value.trim(),
      opp_model:     createOpportunityForm.opp_model.value,
      position_name: createOpportunityForm.position_name.value.trim(),
      sales_lead:    createOpportunityForm.sales_lead.value,
      opp_type:      createOpportunityForm.opp_type.value,
      opp_stage:     'Deep Dive'
    };

    if (formData.opp_type === 'Replacement') {
      const repId = getReplacementCandidateId();
      const endEl = getReplacementEndDateEl();

      if (!repId) {
        alert('Please select a valid candidate to replace (pick from the list).');
        return;
      }
      if (!endEl?.value) {
        alert('Please select the replacement end date.');
        return;
      }
      formData.replacement_of = repId;
      formData.replacement_end_date = endEl.value;
    }

    try {
      const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      const result = await response.json();

      if (response.ok) {
        alert('Opportunity created successfully!');
        closePopup();
        location.reload();
      } else {
        console.log("🔴 Backend error:", result.error);
        alert('Error: ' + (result.error || 'Unexpected error'));
      }
    } catch (err) {
      console.error('Error creating opportunity:', err);
      alert('Connection error. Please try again.');
    }
  });
}


fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts')
  .then(response => response.json())
  .then(accounts => {
    const datalist = document.getElementById('accountList');
    if (!datalist) return;
    accounts.forEach(account => {
      const option = document.createElement('option');
      option.value = account.account_name;
      datalist.appendChild(option);
    });
  })
  .catch(err => {
    console.error('Error loading accounts:', err);
  });
fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users')
  .then(response => response.json())
  .then(users => {
    const salesDropdown = document.getElementById('sales_lead');
    if (!salesDropdown) return;

fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users')
  .then(response => response.json())
  .then(users => {
    const salesDropdown = document.getElementById('sales_lead');
    if (!salesDropdown) return;

    // ✅ Allow-list estricta por email (evita confundir Agustin vs Agustina)
    const allowedEmails = new Set([
      'agustin@vintti.com',
      'bahia@vintti.com',
      'lara@vintti.com',
      'mariano@vintti.com'
    ]);

    // Limpia opciones previas y agrega placeholder
    salesDropdown.innerHTML = '<option disabled selected>Select Sales Lead</option>';

    // Filtra por email exacto (case-insensitive)
    users
      .filter(u => allowedEmails.has((u.email_vintti || '').toLowerCase()))
      // (opcional) orden alfabético por nombre
      .sort((a, b) => a.user_name.localeCompare(b.user_name))
      .forEach(user => {
        const option = document.createElement('option');
        option.value = (user.email_vintti || '').toLowerCase();
        option.textContent = user.user_name; 
        salesDropdown.appendChild(option);
      });

    // 🔒 Defensa extra (por si el backend cambia nombres):
    // elimina cualquier opción que contenga "agustina" en el label
    Array.from(salesDropdown.options).forEach(opt => {
      if (/agustina\b/i.test(opt.textContent)) opt.remove();
    });
  })
  .catch(err => console.error('Error loading sales leads:', err));
  })
  .catch(err => console.error('Error loading sales leads:', err));


  function getStagePill(stage) {
  switch (stage) {
    case 'Close Win':
      return '<span class="stage-pill stage-closewin">Close Win</span>';
    case 'Closed Lost':
      return '<span class="stage-pill stage-closewin">Closed Lost</span>';
    case 'Negotiating':
      return '<span class="stage-pill stage-negotiating">Negotiating</span>';
    case 'Interviewing':
      return '<span class="stage-pill stage-interviewing">Interviewing</span>';
    case 'Sourcing':
      return '<span class="stage-pill stage-sourcing">Sourcing</span>';
    case 'NDA Sent':
      return '<span class="stage-pill stage-nda">NDA Sent</span>';
    case 'Deep Dive':
      return '<span class="stage-pill stage-deepdive">Deep Dive</span>';
    default:
      return stage ? `<span class="stage-pill">${stage}</span>` : '—';
  }
}
function extractTextFromHTML(htmlString) {
  const div = document.createElement('div');
  div.innerHTML = htmlString;

  // Caso especial para la columna Stage con <select>
  const select = div.querySelector('select');
  if (select) {
    return select.options[select.selectedIndex].textContent;
  }

  return div.textContent || div.innerText || '';
}

// Particle trail en hover para las burbujas
document.querySelectorAll('.bubble-button').forEach(bubble => {
  bubble.addEventListener('mousemove', e => {
    const particle = document.createElement('span');
    particle.classList.add('bubble-particle');
    particle.style.left = `${e.offsetX}px`;
    particle.style.top = `${e.offsetY}px`;

    bubble.appendChild(particle);

    setTimeout(() => {
      particle.remove();
    }, 500); // la partícula desaparece en 500ms
  });
});
function getStageDropdown(currentStage, opportunityId) {
  const stages = [
    'Close Win',
    'Closed Lost',
    'Negotiating',
    'Interviewing',
    'Sourcing',
    'NDA Sent',
    'Deep Dive'
  ];

  const normalized = currentStage?.toLowerCase().replace(/\s/g, '-') || '';
  const isFinalStage = currentStage === 'Close Win' || currentStage === 'Closed Lost';

  let dropdown = `<select class="stage-dropdown stage-color-${normalized}" data-id="${opportunityId}" ${isFinalStage ? 'disabled' : ''}>`;

  stages.forEach(stage => {
    const selected = stage === currentStage ? 'selected' : '';
    dropdown += `<option value="${stage}" ${selected}>${stage}</option>`;
  });

  dropdown += `</select>`;

  return dropdown;
}

function calculateDaysAgo(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffTime = Math.abs(now - date);
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1;
  return diffDays;
}
function calculateDaysBetween(startStr, endStr) {
  if (!startStr || !endStr) return '-';

  const start = new Date(startStr);
  const end   = new Date(endStr);

  if (isNaN(start) || isNaN(end)) return '-';

  const diffMs   = end - start;
  const msPerDay = 1000 * 60 * 60 * 24;

  // diferencia “normal” en días (0 si fue el mismo día, 1 si fue al día siguiente, etc.)
  const diffDays = Math.floor(diffMs / msPerDay);
  return diffDays;
}
function computeDaysSinceBatch(refDateStr) {
  if (!refDateStr) return null;
  const ref = new Date(refDateStr);
  const today = new Date();
  const diffDays = Math.ceil((today - ref) / (1000 * 60 * 60 * 24)) - 1; // mismo criterio que usas
  return diffDays;
}
function colorizeSourcingCell(cell, days) {
  if (!cell) return;

  // Limpia clases previas
  cell.classList.remove('green-cell', 'yellow-cell', 'red-cell');

  // Si no hay días válidos, muestra guion
  if (days == null || Number.isNaN(Number(days))) {
    cell.textContent = '-';
    cell.removeAttribute('title');
    return;
  }

  const n = Number(days);
  let label = String(n);

  // 🎨 Lógica de colores:
  // 1–2 días  → verde
  // 3–5 días  → amarillo
  // 6+ días   → rojo + ⚠️
  if (n >= 6) {
    cell.classList.add('red-cell');
    label = `${n} ⚠️`;
  } else if (n >= 3) {
    cell.classList.add('yellow-cell');
    label = `${n} ⏳`;
  } else if (n >= 0) {
    cell.classList.add('green-cell');
    label = `${n} 🌱`;
  }

  cell.textContent = label;
  cell.title = `Days since sourcing: ${n}`;
}


function openSourcingPopup(opportunityId, dropdownElement) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`)
    .then(res => res.json())
    .then(opportunity => {
      const hasStartDate = opportunity.nda_signature_or_start_date;

      if (!hasStartDate) {
        // 🟢 Primera vez: abrir popup antigua
        const popup = document.getElementById('sourcingPopup');
        popup.style.display = 'flex';

        const saveBtn = document.getElementById('saveSourcingDate');
        saveBtn.onclick = async () => {
          const date = document.getElementById('sourcingDate').value;
          if (!date) return alert('Please select a date.');

          await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/fields`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nda_signature_or_start_date: date })
          });

          await patchOpportunityStage(opportunityId, 'Sourcing', dropdownElement);
          closeSourcingPopup();
        };
      } else {
        // 🔁 Ya tiene start_date: abrir nueva popup
        const popup = document.getElementById('newSourcingPopup');
        popup.style.display = 'flex';

        const saveNewBtn = document.getElementById('saveNewSourcing');
        saveNewBtn.onclick = async () => {
          const date = document.getElementById('newSourcingDate').value;
          if (!date) return alert('Please select a date.');

          const hr_lead = opportunity.opp_hr_lead;
          if (!hr_lead) return alert('HR Lead is missing.');

          await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/sourcing', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              opportunity_id: opportunityId,
              user_id: hr_lead,
              since_sourcing: date
            })
          });

          await patchOpportunityStage(opportunityId, 'Sourcing', dropdownElement);
          closeNewSourcingPopup();
        };
      }
    });
}
// —— Close Win: autocomplete rápido ——
const CW_CACHE = new Map(); // término -> resultados [{id,name}]
let cwAbort = null;
let cwSelIndex = -1;
let cwResults = [];
let cwSelectedId = null;

function renderCloseWinList(items){
  const list = document.getElementById('closeWinHireList');
  list.innerHTML = '';

  if (!items.length){
    list.innerHTML = `<div class="autocomplete-empty">No results…</div>`;
  } else {
    items.forEach((it, idx) => {
      const row = document.createElement('div');
      row.className = 'autocomplete-item';
      row.setAttribute('role','option');
      row.setAttribute('data-id', it.candidate_id);
      row.textContent = `${it.candidate_id} - ${it.name}`;
      row.addEventListener('mousedown', (e) => {
        // mousedown para que no pierda foco el input antes de click
        pickCloseWinCandidate(idx);
        e.preventDefault();
      });
      list.appendChild(row);
    });
  }
  list.style.display = 'block';
}

function highlightCloseWinItem(newIndex){
  const list = document.getElementById('closeWinHireList');
  const items = Array.from(list.querySelectorAll('.autocomplete-item'));
  items.forEach((el,i)=> el.setAttribute('aria-selected', i===newIndex ? 'true':'false'));
}

function pickCloseWinCandidate(index){
  const input = document.getElementById('closeWinHireInput');
  const list  = document.getElementById('closeWinHireList');
  const item  = cwResults[index];
  if (!item) return;
  input.value = `${item.candidate_id} - ${item.name}`;
  cwSelectedId = item.candidate_id;
  list.style.display = 'none';
}

async function queryCandidates(term){
  const q = term.trim();
  if (q.length < 2) return [];
  if (CW_CACHE.has(q)) return CW_CACHE.get(q);

  // cancela request anterior
  if (cwAbort) cwAbort.abort();
  cwAbort = new AbortController();

  const url = `https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates?search=${encodeURIComponent(q)}`;
  const res = await fetch(url, { signal: cwAbort.signal });
  const data = await res.json();
  CW_CACHE.set(q, data || []);
  return data || [];
}

function setupCloseWinAutocomplete(){
  const input = document.getElementById('closeWinHireInput');
  const list  = document.getElementById('closeWinHireList');
  if (!input || !list) return;

  let t = null;
  input.addEventListener('input', () => {
    cwSelectedId = null;      // si cambia el texto, invalida selección previa
    clearTimeout(t);
    const term = input.value;
    if (term.trim().length < 2){
      list.style.display = 'none';
      return;
    }
    t = setTimeout(async () => {
      try{
        cwResults = await queryCandidates(term);
        cwSelIndex = -1;
        renderCloseWinList(cwResults);
      } catch(e){
        if (e.name !== 'AbortError') {
          console.error('CW search error:', e);
        }
      }
    }, 220); // debounce
  });

  input.addEventListener('keydown', (e) => {
    if (list.style.display !== 'block') return;
    const max = cwResults.length - 1;
    if (e.key === 'ArrowDown'){
      e.preventDefault();
      cwSelIndex = Math.min(max, cwSelIndex + 1);
      highlightCloseWinItem(cwSelIndex);
    } else if (e.key === 'ArrowUp'){
      e.preventDefault();
      cwSelIndex = Math.max(0, cwSelIndex - 1);
      highlightCloseWinItem(cwSelIndex);
    } else if (e.key === 'Enter'){
      if (cwSelIndex >= 0){
        e.preventDefault();
        pickCloseWinCandidate(cwSelIndex);
      }
    } else if (e.key === 'Escape'){
      list.style.display = 'none';
    }
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#closeWinHireBox')) {
      list.style.display = 'none';
    }
  });
}


// Popup Close Win
function openCloseWinPopup(opportunityId, dropdownElement) {
  const popup = document.getElementById('closeWinPopup');
  popup.style.display = 'flex';

  // inicializa autocomplete
  setupCloseWinAutocomplete();

  const saveBtn = document.getElementById('saveCloseWin');
  saveBtn.onclick = async () => {
    const date = document.getElementById('closeWinDate').value;

    // ✅ tomamos el ID “real” (no split de texto)
    const candidateId = cwSelectedId;

    if (!date || !candidateId) {
      alert('Please select a hire and date.');
      return;
    }

    try {
      // 1) Guardar fecha + contratado en opportunity
      await patchOppFields(opportunityId, {
        opp_close_date: date,                // 'YYYY-MM-DD' exacto
        candidato_contratado: candidateId
      });

      // 2) Asegurar hire_opportunity
      const res2 = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ opportunity_id: Number(opportunityId) })
      });
      if (!res2.ok) throw new Error(await res2.text());

      // 3) Cambiar stage
      await patchOpportunityStage(opportunityId, 'Close Win', dropdownElement);

      // 4) Cerrar y redirigir
      popup.style.display = 'none';
      localStorage.setItem('fromCloseWin', 'true');
      window.location.href = `candidate-details.html?id=${candidateId}#hire`;
    } catch (err) {
      console.error('❌ Close Win flow failed:', err);
      alert(`Close Win failed:\n${err.message}`);
    }
  };
}

function loadCandidatesForCloseWin() {
  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates')
    .then(response => response.json())
    .then(candidates => {
      const datalist = document.getElementById('closeWinCandidates');
      datalist.innerHTML = '';
      candidates.forEach(candidate => {
        const option = document.createElement('option');
        option.value = candidate.candidate_id + ' - ' + candidate.name;
        datalist.appendChild(option);
      });
    });
}
function closeSourcingPopup() {
  document.getElementById('sourcingPopup').style.display = 'none';
}
function closeNewSourcingPopup() {
  document.getElementById('newSourcingPopup').style.display = 'none';
}

function closeCloseWinPopup() {
  document.getElementById('closeWinPopup').style.display = 'none';
}
async function patchOpportunityStage(opportunityId, newStage, dropdownElement) {
  try {
    const response = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opp_stage: newStage })
    });

    const result = await response.json();

    if (response.ok) {
      const toast = document.getElementById('stage-toast');
      toast.textContent = '✨ Stage updated!';
      toast.style.display = 'inline-block';
      toast.classList.remove('sparkle-show'); // para reiniciar si se repite
      void toast.offsetWidth; // forzar reflow
      toast.classList.add('sparkle-show');

      setTimeout(() => {
        toast.style.display = 'none';
      }, 3000);
    } else {
      console.error('❌ Error updating stage:', result.error || result);
      alert('Error updating stage: ' + (result.error || 'Unexpected error'));
    }
  } catch (err) {
    console.error('❌ Network error updating stage:', err);
    alert('Network error. Please try again.');
  }
}
function openCloseLostPopup(opportunityId, dropdownElement) {
  const popup = document.getElementById('closeLostPopup');
  popup.style.display = 'flex';

  const saveBtn = document.getElementById('saveCloseLost');
  saveBtn.onclick = async () => {
    const closeDate = document.getElementById('closeLostDate').value;
    const motive    = document.getElementById('closeLostReason').value;
    const details   = (document.getElementById('closeLostDetails')?.value || '').trim();

    if (!closeDate || !motive) {
      alert("Please fill in both date and reason.");
      return;
    }

    // Construimos el payload
    const payload = {
      opp_close_date:   closeDate,
      motive_close_lost: motive
    };

    // Solo mandamos details si hay algo escrito (opcional)
    if (details) {
      payload.details_close_lost = details;
    }

    // Guardar en DB
    await fetch(`${API_BASE}/opportunities/${opportunityId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    await patchOpportunityStage(opportunityId, 'Closed Lost', dropdownElement);
    closeCloseLostPopup();
  };
}

function closeCloseLostPopup() {
  document.getElementById('closeLostPopup').style.display = 'none';
}
async function patchOppFields(oppId, payload) {
  console.log("📤 PATCH /opportunities/%s/fields", oppId, payload);
  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const text = await res.text();
  if (!res.ok) {
    console.error('❌ fields PATCH failed:', res.status, text);
    throw new Error(`fields PATCH ${res.status}: ${text}`);
  }
  try { return JSON.parse(text); } catch { return text; }
}
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
    'julieta@vintti.com',
    'paz@vintti.com'
  ]);

  // Mantener flex para icono + texto alineados
  link.style.display = RECRUITER_POWER_ALLOWED.has(email) ? 'flex' : 'none';
})();

window.addEventListener('pageshow', () => {
  const tableCard = document.querySelector('.table-card');
  if (!tableCard) return;                 // ⬅️ evita el error en index
  if (tableCard.classList.contains('exit-left')) {
    tableCard.classList.remove('exit-left');
    tableCard.style.opacity = '1';
    tableCard.style.transform = 'translateX(0)';
  }
});
// --- HR initials (dos letras) ---
const HR_INITIALS_BY_EMAIL = {
  'agostina@vintti.com':                'AC',
  'jazmin@vintti.com':                  'JP',
  'pilar@vintti.com':                   'PL', 
  'pilar.fernandez@vintti.com':         'PF', 
  'agustina.barbero@vintti.com':        'AB',
  'josefina@vintti.com':                'JP',
  'constanza@vintti.com':               'CL',
  'julieta@vintti.com':                 'JG',
  'paz@vintti.com':                     'PL'
};

function initialsForHRLead(emailOrName) {
  const s = String(emailOrName || '').trim().toLowerCase();

  if (HR_INITIALS_BY_EMAIL[s]) return HR_INITIALS_BY_EMAIL[s];

  // Distinción por nombre
  if (s.includes('pilar') && s.includes('fernandez')) return 'PF'; // nueva
  if (s.includes('pilar') && s.includes('flores'))     return 'PL'; // si la Pilar anterior es López
  // fallback histórico (si solo dice "Pilar", asumimos la de siempre)
  if (s === 'pilar' || (s.includes('pilar') && !s.includes('fernandez'))) return 'PL';

  if (s.includes('agostina') && s.includes('barbero'))  return 'AB';
  if (s.includes('agostina') && s.includes('ferrari'))  return 'AF';
  if (s.includes('agostina')) return 'AC';
  if (s.includes('jazmin'))   return 'JP';
  if (s.includes('paz'))      return 'PZ';

  return '—';
}

// HTML visible (inicial + avatar). El select va encima, invisible, para que abra con nombres completos.
function hrDisplayHTML(email) {
  const initials = initialsForHRLead(email);
  const avatar   = resolveAvatar(email);
  const nameTip  = displayNameForHR(email);

  const img = avatar ? `<img class="lead-avatar" src="${avatar}" alt="">` : '';
  return `
    <div class="hr-lead lead-tip" data-tip="${escapeHtml(nameTip)}">
      <span class="lead-bubble">${initials}</span>
      ${img}
    </div>
  `;
}

function salesDisplayHTML(emailOrName) {
  const key      = String(emailOrName || '').toLowerCase();
  const initials = initialsForSalesLead(key);
  const bubbleCl = badgeClassForSalesLead(key);
  const avatar   = resolveAvatar(key);
  const nameTip  = displayNameForSales(emailOrName);

  const img = avatar ? `<img class="lead-avatar" src="${avatar}" alt="">` : '';
  return `
    <div class="sales-lead lead-tip" data-tip="${escapeHtml(nameTip)}">
      <span class="lead-bubble ${bubbleCl}">${initials}</span>
      ${img}
    </div>
  `;
}

// Celda completa: display visible + <select> (opciones con nombres completos)
function getHRLeadCell(opp) {
  const email = opp.opp_hr_lead || '';
  return `
    <div class="hr-lead-cell-wrap" style="position:relative;min-height:28px;">
      ${hrDisplayHTML(email)}
      <select class="hr-lead-dropdown"
              data-id="${opp.opportunity_id}"
              style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;">
        ${generateHROptions(opp.opp_hr_lead)}
      </select>
    </div>
  `;
}


function showLoginAvatar(email) {
  const img = document.getElementById('login-avatar');
  if (!img) return;
  const src = resolveAvatar(email);
  if (src) {
    img.src = src;
    img.style.display = 'block';
  } else {
    img.removeAttribute('src');
    img.style.display = 'none';
  }
}

function showWelcomeAvatar(email) {
  const img = document.getElementById('welcome-avatar');
  if (!img) return;
  const src = resolveAvatar(email);
  if (src) {
    img.src = src;
    img.style.display = 'inline-block';
  } else {
    img.removeAttribute('src');
    img.style.display = 'none';
  }
}

// Mientras el usuario escribe el email en el login
const emailInputEl = document.getElementById('email');
emailInputEl?.addEventListener('input', () => {
  showLoginAvatar(emailInputEl.value);
});
emailInputEl?.addEventListener('blur', () => {
  showLoginAvatar(emailInputEl.value);
});

// Si ya había un email prellenado (autofill del navegador), refleja el avatar
if (emailInputEl && emailInputEl.value) {
  showLoginAvatar(emailInputEl.value);
}
function safePlay(id) {
  const el = document.getElementById(id);
  if (!el) return;
  try {
    el.currentTime = 0;
    const p = el.play();
    if (p && typeof p.catch === 'function') {
      p.catch(err => console.debug('🔇 Click sound blocked/failed:', err));
    }
  } catch (e) {
    console.debug('🔇 Click sound exception:', e);
  }
}
// Map de email -> avatar ya lo tienes en AVATAR_BY_EMAIL y resolveAvatar()

// Detecta email del sales lead si viene en el objeto; si no, infiere por el nombre
function emailForSalesLead(opp) {
  if (opp?.opp_sales_lead) return String(opp.opp_sales_lead).toLowerCase();
  if (opp?.sales_lead) return String(opp.sales_lead).toLowerCase();
  const name = (opp?.sales_lead_name || '').toLowerCase();
  if (name) {
    const match = (window.allowedSalesUsers || []).find(u => String(u.user_name || '').toLowerCase() === name);
    if (match?.email_vintti) return match.email_vintti;
  }
  if (name.includes('bahia'))   return 'bahia@vintti.com';
  if (name.includes('lara'))    return 'lara@vintti.com';
  if (name.includes('agustin')) return 'agustin@vintti.com';
  if (name.includes('mariano')) return 'mariano@vintti.com';
  return '';
}

// Iniciales pedidas: Bahía → BL, Lara → LR, Agustín → AR
function initialsForSalesLead(key) {
  if (key.includes('bahia')   || key.includes('bahia@'))   return 'BL';
  if (key.includes('lara')    || key.includes('lara@'))    return 'LR';
  if (key.includes('mariano')    || key.includes('marian@'))    return 'MS';
  if (key.includes('agustin')) return 'AM';
  return '--';
}

// Clase de color de la burbuja
function badgeClassForSalesLead(key) {
  if (key.includes('bahia')   || key.includes('bahia@'))   return 'bl';
  if (key.includes('lara')    || key.includes('lara@'))    return 'lr';
  if (key.includes('mariano')    || key.includes('marian@'))    return 'ms';
  if (key.includes('agustin')) return 'am';
  return '';
}

function getSalesLeadCell(opp) {
  // email guardado o inferido
  const email = (emailForSalesLead(opp) || '').toLowerCase();
  const fullName = opp.sales_lead_name || ''; // para filtros

  return `
    <div class="sales-lead-cell-wrap" style="position:relative;min-height:28px;">
      ${salesDisplayHTML(email || fullName)}
      <span class="sr-only" style="display:none">${fullName}</span>
      <select class="sales-lead-dropdown"
              data-id="${opp.opportunity_id}"
              style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;">
        ${window.generateSalesOptions(email)}
      </select>
    </div>
  `;
}


function getTypeBadge(type) {
  const t = String(type || '').toLowerCase();
  if (t.startsWith('new'))         return '<span class="type-badge N">N</span>';
  if (t.startsWith('replacement')) return '<span class="type-badge R">R</span>';
  return type || '';
}

window.getCurrentUserEmail = getCurrentUserEmail;
window.getCurrentUserId    = getCurrentUserId;

// --- evita duplicados por cambios rápidos / re-renders ---
window._negotiatingEmailSent = window._negotiatingEmailSent || new Set();

/**
 * Obtiene info clave de la opp, resuelve el client_name desde accounts y envía email en HTML.
 */
async function sendNegotiatingReminder(opportunityId){
  try {
    // evita re-envíos en la misma sesión
    if (window._negotiatingEmailSent.has(opportunityId)) return;

    // 1) Traer detalles de la oportunidad
    const r = await fetch(`${API_BASE}/opportunities/${opportunityId}`, { credentials: 'include' });
    if (!r.ok) throw new Error(`GET opp ${opportunityId} failed ${r.status}`);
    const opp = await r.json();

    const hrEmail = String(opp.opp_hr_lead || '').toLowerCase().trim();
    if (!hrEmail) {
      console.warn('⚠️ No HR Lead email on opp', opportunityId);
      return; // sin HR lead asignada, no enviamos
    }

    // 2) Resolver nombre de cliente desde accounts (via account_id)
    const client = await resolveAccountName(opp);

    // 3) Rol/posición
    const role   = opp.opp_position_name || 'the role';

    // 4) Asunto + cuerpo en HTML (negritas reales)
    const subject = `Heads up: ${client} — ${role} moved to Negotiating ✨`;

    // pequeño escape por seguridad
    const esc = s => String(s || '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));

    const htmlBody = `
<div style="font-family:Inter, Arial, sans-serif; font-size:14px; color:#222; line-height:1.5;">
  <p>Hi there! 🌸</p>
  <p>
    Quick note to share that the opportunity
    <strong>${esc(client)} — ${esc(role)}</strong>
    has just moved to <strong>Negotiating</strong>. 🎉
  </p>
  <p>This is a reminder to:</p>
  <ul>
    <li>Request and upload the <strong>resignation letter</strong> 📝</li>
    <li>Collect and upload the <strong>references</strong> 📎</li>
  </ul>
  <p>Once both are in the hub, please check the box in the candidate overview page. 💕</p>
  <p style="margin-top:16px">— Vintti HUB</p>
</div>`.trim();

    // 5) Enviar email.
    // 🔸 En muchos backends el campo se llama "body" y si huele a HTML lo mandan como HTML.
    // 🔸 Para mayor compatibilidad añadimos también "body_html" y una pista "content_type".
    const payload = {
      to: [hrEmail, 'angie@vintti.com'].filter((v, i, arr) => v && arr.indexOf(v) === i),
      subject,
      body: htmlBody,              // si tu /send_email usa esto, verá HTML
      body_html: htmlBody,         // alternativo común
      content_type: 'text/html',   // pista para el backend
      html: true                   // pista opcional
      // cc: ['jazmin@vintti.com'] // descomenta si quieres copia
    };

    const res = await fetch(`${API_BASE}/send_email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errText = await res.text().catch(()=> '');
      throw new Error(`send_email failed ${res.status}: ${errText}`);
    }

    // marca como enviado para no duplicar
    window._negotiatingEmailSent.add(opportunityId);
    console.info('✅ Negotiating reminder sent to', hrEmail);

  } catch (e) {
    console.error('❌ Failed to send negotiating reminder:', e);
  }
}

/**
 * Hook: después de actualizar el stage, si es Negotiating -> enviar mail.
 * (Usa tu patchOpportunityStage existente y solo añadimos la llamada)
 */
const _origPatchOpportunityStage = window.patchOpportunityStage;
window.patchOpportunityStage = async function(opportunityId, newStage, dropdownElement){
  await _origPatchOpportunityStage.call(this, opportunityId, newStage, dropdownElement);
  // Si salió bien y la etapa es Negotiating, dispara el recordatorio
  if (String(newStage) === 'Negotiating') {
    sendNegotiatingReminder(opportunityId);
  }
};
// === Log out button ===
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
