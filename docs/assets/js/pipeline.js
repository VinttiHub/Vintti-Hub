// Mapa de códigos (si ya lo tienes global, puedes usar ese y borrar este)
const WA_countryToCodeMap = {
  "Argentina": "54","Bolivia": "591","Brazil": "55","Chile": "56","Colombia": "57",
  "Costa Rica": "506","Cuba": "53","Ecuador": "593","El Salvador": "503","Guatemala": "502",
  "Honduras": "504","Mexico": "52","United States": "1","Canada": "1","Nicaragua": "505","Panama": "507","Paraguay": "595",
  "Peru": "51","Puerto Rico": "1","Dominican Republic": "1","Uruguay": "598","Venezuela": "58"
};

const PIPELINE_US_STATES = [
  { code: 'AL', name: 'Alabama' },
  { code: 'AK', name: 'Alaska' },
  { code: 'AZ', name: 'Arizona' },
  { code: 'AR', name: 'Arkansas' },
  { code: 'CA', name: 'California' },
  { code: 'CO', name: 'Colorado' },
  { code: 'CT', name: 'Connecticut' },
  { code: 'DE', name: 'Delaware' },
  { code: 'FL', name: 'Florida' },
  { code: 'GA', name: 'Georgia' },
  { code: 'HI', name: 'Hawaii' },
  { code: 'ID', name: 'Idaho' },
  { code: 'IL', name: 'Illinois' },
  { code: 'IN', name: 'Indiana' },
  { code: 'IA', name: 'Iowa' },
  { code: 'KS', name: 'Kansas' },
  { code: 'KY', name: 'Kentucky' },
  { code: 'LA', name: 'Louisiana' },
  { code: 'ME', name: 'Maine' },
  { code: 'MD', name: 'Maryland' },
  { code: 'MA', name: 'Massachusetts' },
  { code: 'MI', name: 'Michigan' },
  { code: 'MN', name: 'Minnesota' },
  { code: 'MS', name: 'Mississippi' },
  { code: 'MO', name: 'Missouri' },
  { code: 'MT', name: 'Montana' },
  { code: 'NE', name: 'Nebraska' },
  { code: 'NV', name: 'Nevada' },
  { code: 'NH', name: 'New Hampshire' },
  { code: 'NJ', name: 'New Jersey' },
  { code: 'NM', name: 'New Mexico' },
  { code: 'NY', name: 'New York' },
  { code: 'NC', name: 'North Carolina' },
  { code: 'ND', name: 'North Dakota' },
  { code: 'OH', name: 'Ohio' },
  { code: 'OK', name: 'Oklahoma' },
  { code: 'OR', name: 'Oregon' },
  { code: 'PA', name: 'Pennsylvania' },
  { code: 'RI', name: 'Rhode Island' },
  { code: 'SC', name: 'South Carolina' },
  { code: 'SD', name: 'South Dakota' },
  { code: 'TN', name: 'Tennessee' },
  { code: 'TX', name: 'Texas' },
  { code: 'UT', name: 'Utah' },
  { code: 'VT', name: 'Vermont' },
  { code: 'VA', name: 'Virginia' },
  { code: 'WA', name: 'Washington' },
  { code: 'WV', name: 'West Virginia' },
  { code: 'WI', name: 'Wisconsin' },
  { code: 'WY', name: 'Wyoming' },
  { code: 'DC', name: 'District of Columbia' }
];
const PIPELINE_US_STATE_MAP = PIPELINE_US_STATES.reduce((acc, entry) => {
  acc[entry.code] = entry.name;
  return acc;
}, {});
const PIPELINE_USA_STATE_REGEX = /^USA\s+([A-Z]{2})$/i;
let candidateStateChoices = null;

function normalizeCountryKey(country){
  const value = (country || '').trim();
  if (!value) return '';
  const match = PIPELINE_USA_STATE_REGEX.exec(value);
  if (match) return 'United States';
  if (value.toUpperCase() === 'USA') return 'United States';
  return value;
}

function extractUsStateCode(country){
  const match = PIPELINE_USA_STATE_REGEX.exec(country || '');
  return match ? match[1].toUpperCase() : '';
}

function formatUsCountryValue(stateCode){
  return `USA ${stateCode.toUpperCase()}`;
}

function formatCountryDisplay(country){
  if (!country) return '—';
  const code = extractUsStateCode(country);
  if (code) {
    const name = PIPELINE_US_STATE_MAP[code] || code;
    return `USA · ${name} (${code})`;
  }
  return country;
}

function resetCandidateStateField(){
  const stateSelect = document.getElementById('candidate-us-state');
  if (!stateSelect) return;
  stateSelect.value = '';
  if (candidateStateChoices) {
    candidateStateChoices.removeActiveItems();
    try { candidateStateChoices.setChoiceByValue(''); } catch {}
  }
}

function updateCandidateStateFieldVisibility(countryValue){
  const wrapper = document.getElementById('candidate-us-state-wrapper');
  if (!wrapper) return;
  const shouldShow = normalizeCountryKey(countryValue) === 'United States';
  wrapper.classList.toggle('hidden', !shouldShow);
  if (!shouldShow) resetCandidateStateField();
}

function getSelectedCandidateStateCode(){
  const stateSelect = document.getElementById('candidate-us-state');
  if (!stateSelect) return '';
  return (stateSelect.value || '').toUpperCase();
}

// Limpia y normaliza a E.164 sin "+" (wa.me exige dígitos, sin signos)
function normalizePhoneForWA(rawPhone, country){
  if (!rawPhone) return '';
  let s = String(rawPhone).trim();

  // Quita espacios, paréntesis y guiones
  s = s.replace(/[\s\-\(\)]/g, '');

  // Si viene con "00" o "+", quitarlos
  s = s.replace(/^00/, '');
  s = s.replace(/^\+/, '');

  // Si tras limpiar empieza con código de país (2–3 dígitos) probablemente ya está bien
  // Si NO, y tenemos país, lo preprendemos.
  const cc = WA_countryToCodeMap[normalizeCountryKey(country)] || '';
  if (cc && !s.startsWith(cc)) {
    // Evita doble indicativo si el número ya venía con él
    // (heurística simple: si la longitud sin cc es <= 10–11, prepende)
    const maybeLocal = s.length <= 11;
    if (maybeLocal) s = cc + s;
  }

  // Deja sólo dígitos
  s = s.replace(/\D/g, '');
  return s;
}
// === WhatsApp helpers ===
const PHONE_CACHE = Object.create(null);
const BLACKLIST_CACHE = Object.create(null);
const CANDIDATE_ASSOCIATION_CACHE = Object.create(null);
const onlyDigits = s => String(s||'').replace(/\D/g, '');
const BLACKLIST_TOOLTIP_TEXT = 'Black list';
let blacklistTooltipEl = null;
let blacklistTooltipHideQueued = false;

function ensureBlacklistTooltipElement() {
  if (blacklistTooltipEl) return blacklistTooltipEl;
  const el = document.createElement('div');
  el.className = 'blacklist-tooltip';
  el.textContent = BLACKLIST_TOOLTIP_TEXT;
  Object.assign(el.style, {
    position: 'fixed',
    padding: '6px 10px',
    borderRadius: '6px',
    background: 'rgba(17, 24, 39, 0.92)',
    color: '#fff',
    fontSize: '0.78rem',
    fontWeight: '500',
    pointerEvents: 'none',
    zIndex: 2000,
    transform: 'translate(-50%, -100%)',
    whiteSpace: 'nowrap',
    boxShadow: '0 4px 18px rgba(15, 23, 42, 0.35)',
    display: 'none'
  });
  document.body.appendChild(el);
  blacklistTooltipEl = el;
  return el;
}

function showBlacklistTooltip(target) {
  if (!target) return;
  const tooltip = ensureBlacklistTooltipElement();
  const rect = target.getBoundingClientRect();
  tooltip.textContent = target.dataset.tooltipText || BLACKLIST_TOOLTIP_TEXT;
  tooltip.style.left = `${rect.left + rect.width / 2}px`;
  tooltip.style.top = `${rect.top - 6}px`;
  tooltip.style.display = 'block';
  blacklistTooltipHideQueued = false;
}

function hideBlacklistTooltip() {
  blacklistTooltipHideQueued = false;
  if (blacklistTooltipEl) {
    blacklistTooltipEl.style.display = 'none';
  }
}

window.addEventListener('scroll', hideBlacklistTooltip, { passive: true });
window.addEventListener('resize', hideBlacklistTooltip);

// Intenta muchas keys (pipeline y details pueden diferir)
function pickPhoneFromCandidate(obj){
  if (!obj || typeof obj !== 'object') return '';
  const keys = [
    'phone', 'candidate_phone', 'phone_number', 'mobile', 'cellphone',
    'whatsapp', 'tel', 'telefono'
  ];
  // 1) directas
  for (const k of keys){
    const v = (obj?.[k] ?? '').toString().trim();
    if (v) return v;
  }
  // 2) anidadas típicas
  const nested = [
    obj?.candidate?.phone,
    obj?.contact?.phone,
    obj?.phones?.primary,
    obj?.phones?.main
  ].map(x => (x ?? '').toString().trim()).find(Boolean);
  if (nested) return nested;

  return '';
}

function isTruthyFlag(value) {
  if (value === true) return true;
  if (value === false || value == null) return false;
  if (typeof value === 'number') return value !== 0;
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    return normalized === 'true' || normalized === 't' || normalized === '1' || normalized === 'yes';
  }
  return Boolean(value);
}

function attachBlacklistTooltip(indicator) {
  if (!indicator || indicator.dataset.tooltipBound === 'true') return;
  indicator.dataset.tooltipText = indicator.dataset.tooltipText || BLACKLIST_TOOLTIP_TEXT;
  indicator.style.cursor = 'help';
  indicator.style.display = 'inline-flex';
  indicator.style.alignItems = 'center';
  indicator.style.justifyContent = 'center';
  indicator.style.lineHeight = '1';
  indicator.tabIndex = 0;
  indicator.setAttribute('role', 'img');
  indicator.setAttribute('aria-label', indicator.dataset.tooltipText);
  const show = () => {
    if (!document.body.contains(indicator)) return;
    showBlacklistTooltip(indicator);
  };
  const hide = () => {
    blacklistTooltipHideQueued = true;
    requestAnimationFrame(() => {
      if (blacklistTooltipHideQueued) hideBlacklistTooltip();
    });
  };
  indicator.addEventListener('mouseover', show);
  indicator.addEventListener('mouseout', hide);
  indicator.addEventListener('focus', show);
  indicator.addEventListener('blur', hide);
  indicator.addEventListener('touchstart', () => {
    show();
    setTimeout(hideBlacklistTooltip, 1200);
  }, { passive: true });
  indicator.dataset.tooltipBound = 'true';
}

function applyBlacklistStyles(card, indicatorSize = '0.95rem') {
  if (!card || card.dataset.blacklistDecorated === 'true') return;
  card.dataset.blacklisted = 'true';
  card.dataset.blacklistDecorated = 'true';
  card.style.backgroundColor = '#ffecec';
  card.style.border = '1px solid #f5b5b5';
  card.style.boxShadow = '0 2px 8px rgba(245, 181, 181, 0.35)';
  const nameNodes = card.querySelectorAll('.candidate-name');
  nameNodes.forEach((el) => {
    if (!el || el.dataset.hasBlacklistIndicator === 'true') return;
    const indicator = document.createElement('span');
    indicator.className = 'blacklist-indicator';
    indicator.textContent = '🚨';
    indicator.title = BLACKLIST_TOOLTIP_TEXT;
    indicator.style.marginLeft = '0.35rem';
    indicator.style.fontSize = indicatorSize;
    indicator.setAttribute('aria-label', 'Blacklisted candidate');
    el.appendChild(document.createTextNode(' '));
    el.appendChild(indicator);
    attachBlacklistTooltip(indicator);
    el.dataset.hasBlacklistIndicator = 'true';
  });
}

function fetchCandidateBlacklistFlag(candidateId) {
  if (!candidateId) return Promise.resolve(false);
  const key = String(candidateId);
  if (Object.prototype.hasOwnProperty.call(BLACKLIST_CACHE, key)) {
    return Promise.resolve(BLACKLIST_CACHE[key]);
  }
  return fetch(`${API_BASE}/candidates/${candidateId}`, { cache: 'no-store' })
    .then((res) => {
      if (!res.ok) throw new Error(`status ${res.status}`);
      return res.json();
    })
    .then((data) => {
      const raw = data?.is_blacklisted ?? data?.blacklist ?? data?.candidate?.blacklist;
      const flag = isTruthyFlag(raw);
      BLACKLIST_CACHE[key] = flag;
      return flag;
    })
    .catch((err) => {
      console.error('Error fetching blacklist status:', err);
      BLACKLIST_CACHE[key] = false;
      return false;
    });
}

function decorateUsingCandidateBlacklist(card, candidate, rawValue) {
  if (!card || !candidate) return;
  if (rawValue !== undefined && rawValue !== null) {
    if (isTruthyFlag(rawValue)) applyBlacklistStyles(card);
    return;
  }
  const candidateId = candidate.candidate_id || candidate.id;
  if (!candidateId) return;
  fetchCandidateBlacklistFlag(candidateId).then((flag) => {
    if (flag) applyBlacklistStyles(card);
  });
}

window.applyBlacklistStyles = applyBlacklistStyles;
window.attachBlacklistTooltip = attachBlacklistTooltip;

const ASSOCIATION_TOOLTIP_TEXT = 'Candidate associated to another opportunity';
let associationTooltipEl = null;
let associationTooltipHideQueued = false;
const candidateAssociationPopupState = {
  onConfirm: null,
  onCancel: null,
  requireConfirmation: false
};

function ensureAssociationTooltipElement() {
  if (associationTooltipEl) return associationTooltipEl;
  const el = document.createElement('div');
  el.className = 'association-tooltip';
  document.body.appendChild(el);
  associationTooltipEl = el;
  return el;
}

function showAssociationTooltip(target) {
  if (!target) return;
  const el = ensureAssociationTooltipElement();
  const rect = target.getBoundingClientRect();
  el.textContent = target.dataset.tooltipText || ASSOCIATION_TOOLTIP_TEXT;
  el.style.left = `${rect.left + rect.width / 2}px`;
  el.style.top = `${rect.top - 6}px`;
  el.style.display = 'block';
  associationTooltipHideQueued = false;
}

function hideAssociationTooltip() {
  associationTooltipHideQueued = false;
  if (associationTooltipEl) {
    associationTooltipEl.style.display = 'none';
  }
}

window.addEventListener('scroll', hideAssociationTooltip, { passive: true });
window.addEventListener('resize', hideAssociationTooltip);

function attachAssociationTooltip(el) {
  if (!el || el.dataset.associationTooltipBound === 'true') return;
  el.dataset.tooltipText = el.dataset.tooltipText || ASSOCIATION_TOOLTIP_TEXT;
  const show = () => {
    if (!document.body.contains(el)) return;
    showAssociationTooltip(el);
  };
  const hide = () => {
    associationTooltipHideQueued = true;
    requestAnimationFrame(() => {
      if (associationTooltipHideQueued) hideAssociationTooltip();
    });
  };
  el.addEventListener('mouseover', show);
  el.addEventListener('mouseout', hide);
  el.addEventListener('focus', show);
  el.addEventListener('blur', hide);
  el.addEventListener('touchstart', () => {
    show();
    setTimeout(hideAssociationTooltip, 1200);
  }, { passive: true });
  el.dataset.associationTooltipBound = 'true';
}

function getCurrentOpportunityIdValue() {
  const el = document.getElementById('opportunity-id-text');
  if (!el) return null;
  const attr = (el.getAttribute('data-id') || '').trim();
  if (attr && attr !== '—') return attr;
  const text = (el.textContent || '').trim();
  if (!text || text === '—') return null;
  return text;
}

function fetchCandidateAssociations(candidateId) {
  if (!candidateId) return Promise.resolve([]);
  const key = String(candidateId);
  if (Object.prototype.hasOwnProperty.call(CANDIDATE_ASSOCIATION_CACHE, key)) {
    return Promise.resolve(CANDIDATE_ASSOCIATION_CACHE[key]);
  }
  return fetch(`${API_BASE}/candidates/${candidateId}/opportunities`, { cache: 'no-store' })
    .then((res) => {
      if (!res.ok) throw new Error(`Association fetch failed ${res.status}`);
      return res.json();
    })
    .then((data) => {
      const list = Array.isArray(data) ? data : [];
      CANDIDATE_ASSOCIATION_CACHE[key] = list;
      return list;
    })
    .catch((err) => {
      console.error('Unable to fetch candidate associations:', err);
      CANDIDATE_ASSOCIATION_CACHE[key] = [];
      return [];
    });
}

function filterAssociationsForOtherOpportunities(list, currentOppId) {
  if (!Array.isArray(list) || !list.length) return [];
  const normalized = currentOppId ? String(currentOppId).trim() : '';
  if (!normalized) {
    const unique = new Set();
    list.forEach((assoc) => {
      if (assoc && assoc.opportunity_id != null) {
        unique.add(String(assoc.opportunity_id));
      }
    });
    if (unique.size <= 1) return [];
    return list.slice();
  }
  return list.filter((assoc) => {
    if (!assoc || assoc.opportunity_id == null) return false;
    return String(assoc.opportunity_id) !== normalized;
  });
}

function prepareCandidateAssociationRows(list) {
  if (!Array.isArray(list)) return [];
  return list.map((row) => {
    const batchNumber = row.batch_number != null ? row.batch_number : row.batch_id;
    return {
      opportunityId: row.opportunity_id,
      accountName: row.account_name || row.client_name || '—',
      roleName: row.opp_position_name || row.opp_model || '—',
      batchLabel: batchNumber != null ? `Batch #${batchNumber}` : '—',
      statusLabel: row.batch_status || '—'
    };
  });
}

function renderCandidateAssociationList(container, rows) {
  if (!container) return;
  container.innerHTML = '';
  if (!rows.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-state';
    empty.textContent = 'No linked opportunities to display.';
    container.appendChild(empty);
    return;
  }

  const table = document.createElement('table');
  table.className = 'association-table';
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  ['Account', 'Opportunity', 'Batch', 'Status'].forEach((label) => {
    const th = document.createElement('th');
    th.textContent = label;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  rows.forEach((row) => {
    const tr = document.createElement('tr');
    const tdAccount = document.createElement('td');
    tdAccount.textContent = row.accountName || '—';
    const tdRole = document.createElement('td');
    tdRole.textContent = row.roleName || '—';
    const tdBatch = document.createElement('td');
    tdBatch.textContent = row.batchLabel || '—';
    const tdStatus = document.createElement('td');
    tdStatus.textContent = row.statusLabel || '—';
    tr.appendChild(tdAccount);
    tr.appendChild(tdRole);
    tr.appendChild(tdBatch);
    tr.appendChild(tdStatus);
    tbody.appendChild(tr);
  });

  table.appendChild(tbody);
  container.appendChild(table);
}

function openCandidateAssociationPopup({
  candidateName,
  associations,
  message,
  requireConfirmation = false,
  onConfirm,
  onCancel
}) {
  const popup = document.getElementById('candidateAssociationPopup');
  const title = document.getElementById('candidateAssociationTitle');
  const msg = document.getElementById('candidateAssociationMessage');
  const list = document.getElementById('candidateAssociationList');
  const actions = document.getElementById('candidateAssociationActions');
  if (!popup || !list) return false;

  if (title) {
    title.textContent = candidateName
      ? `Linked opportunities for ${candidateName}`
      : 'Candidate associations';
  }
  if (msg) {
    msg.textContent = message || '';
  }
  renderCandidateAssociationList(list, prepareCandidateAssociationRows(associations || []));
  if (actions) {
    actions.classList.toggle('hidden', !requireConfirmation);
  }

  candidateAssociationPopupState.onConfirm = typeof onConfirm === 'function' ? onConfirm : null;
  candidateAssociationPopupState.onCancel = typeof onCancel === 'function' ? onCancel : null;
  candidateAssociationPopupState.requireConfirmation = !!requireConfirmation;

  popup.classList.remove('hidden');
  return true;
}

function closeCandidateAssociationPopup(triggerCancel = true) {
  const popup = document.getElementById('candidateAssociationPopup');
  const msg = document.getElementById('candidateAssociationMessage');
  const list = document.getElementById('candidateAssociationList');
  if (popup) popup.classList.add('hidden');
  if (msg) msg.textContent = '';
  if (list) list.innerHTML = '';

  if (triggerCancel && typeof candidateAssociationPopupState.onCancel === 'function') {
    try {
      candidateAssociationPopupState.onCancel();
    } catch (err) {
      console.error('Association popup cancel handler error:', err);
    }
  }

  candidateAssociationPopupState.onConfirm = null;
  candidateAssociationPopupState.onCancel = null;
  candidateAssociationPopupState.requireConfirmation = false;
}

function confirmCandidateAssociationPopup() {
  const handler = candidateAssociationPopupState.onConfirm;
  closeCandidateAssociationPopup(false);
  if (typeof handler === 'function') {
    try {
      handler();
    } catch (err) {
      console.error('Association popup confirm handler error:', err);
    }
  }
}

function wireCandidateAssociationPopup() {
  const popup = document.getElementById('candidateAssociationPopup');
  if (!popup || popup.dataset.wired === 'true') return;
  popup.dataset.wired = 'true';
  const closeBtn = document.getElementById('closeCandidateAssociationPopup');
  const cancelBtn = document.getElementById('candidateAssociationCancelBtn');
  const confirmBtn = document.getElementById('candidateAssociationConfirmBtn');

  const cancelHandler = () => closeCandidateAssociationPopup(true);

  closeBtn?.addEventListener('click', cancelHandler);
  cancelBtn?.addEventListener('click', cancelHandler);
  confirmBtn?.addEventListener('click', () => {
    confirmCandidateAssociationPopup();
  });
  popup.addEventListener('click', (evt) => {
    if (evt.target === popup) {
      cancelHandler();
    }
  });
}

function showCandidateAssociationDetails(candidateId, candidateName, preloadedAssociations = null) {
  const currentOppId = getCurrentOpportunityIdValue();
  const dataPromise = preloadedAssociations
    ? Promise.resolve(preloadedAssociations)
    : fetchCandidateAssociations(candidateId);
  dataPromise.then((raw) => {
    const relevant = filterAssociationsForOtherOpportunities(raw || [], currentOppId);
    if (!relevant.length) return;
    openCandidateAssociationPopup({
      candidateName,
      associations: relevant,
      message: `${candidateName || 'This candidate'} is also linked to the opportunities below.`,
      requireConfirmation: false
    });
  });
}

function ensureCandidateAssociationAllowed(candidateId, candidateName, currentOppId) {
  return fetchCandidateAssociations(candidateId)
    .then((rows) => {
      const conflicts = filterAssociationsForOtherOpportunities(rows, currentOppId);
      if (!conflicts.length) return true;
      return new Promise((resolve) => {
        const opened = openCandidateAssociationPopup({
          candidateName,
          associations: conflicts,
          message: 'Heads up! This candidate is already associated to another opportunity. Are you sure you want to add them?',
          requireConfirmation: true,
          onConfirm: () => resolve(true),
          onCancel: () => resolve(false)
        });
        if (!opened) {
          const fallback = window.confirm('This candidate is already associated to another opportunity. Do you still want to add them?');
          resolve(Boolean(fallback));
        }
      });
    })
    .catch((err) => {
      console.error('Unable to validate candidate associations:', err);
      return true;
    });
}

function decorateCandidateAssociations(card, candidate, options = {}) {
  if (!card || !candidate) return;
  if (card.dataset.associationDecorated === 'true' || card.dataset.associationDecorating === 'true') return;
  const candidateId = candidate.candidate_id || candidate.id;
  if (!candidateId) return;
  card.dataset.associationDecorating = 'true';
  const candidateName = candidate.name || candidate.full_name || candidate.label || 'Candidate';
  fetchCandidateAssociations(candidateId)
    .then((rows) => {
      const currentOppId = getCurrentOpportunityIdValue();
      const relevant = filterAssociationsForOtherOpportunities(rows, currentOppId);
      if (!relevant.length) return;
      insertAssociationIndicator(card, candidateId, candidateName, relevant, options);
    })
    .finally(() => {
      card.dataset.associationDecorating = 'false';
    });
}

function insertAssociationIndicator(card, candidateId, candidateName, associations, options = {}) {
  if (!card || card.querySelector('.association-indicator')) return;
  const indicator = document.createElement('span');
  indicator.className = 'association-indicator';
  indicator.textContent = options.emoji || '🤝';
  indicator.style.fontSize = options.indicatorSize || '16px';
  indicator.dataset.tooltipText = ASSOCIATION_TOOLTIP_TEXT;
  indicator.dataset.candidateId = candidateId;
  indicator.__associations = Array.isArray(associations) ? associations.slice() : [];
  indicator.addEventListener('click', (evt) => {
    evt.stopPropagation();
    const cached = indicator.__associations ? indicator.__associations.slice() : null;
    showCandidateAssociationDetails(candidateId, candidateName, cached);
  });
  attachAssociationTooltip(indicator);

  const waIcon = card.querySelector('.wa-icon');
  if (waIcon && waIcon.parentElement) {
    waIcon.insertAdjacentElement('afterend', indicator);
  } else if (options.fallbackTargetSelector) {
    const fallback = card.querySelector(options.fallbackTargetSelector);
    if (fallback) {
      fallback.appendChild(indicator);
    } else {
      (card.querySelector('.candidate-card-header') || card).appendChild(indicator);
    }
  } else {
    (card.querySelector('.candidate-card-header') || card).appendChild(indicator);
  }
  card.dataset.associationDecorated = 'true';
}
window.decorateCandidateAssociations = decorateCandidateAssociations;

// Trae y cachea el teléfono si no vino en el pipeline
async function resolvePhone(candidate){
  const id = candidate?.candidate_id || candidate?.id;
  if (!id) return '';

  // a) ¿vino inline?
  const inline = pickPhoneFromCandidate(candidate);
  if (inline){
    PHONE_CACHE[id] = inline;
    return inline;
  }

  // b) caché
  if (PHONE_CACHE[id]) return PHONE_CACHE[id];

  // c) fallback a /candidates/:id
  try{
    const r = await fetch(`${API_BASE}/candidates/${id}`, { cache: 'no-store' });
    if (!r.ok) throw 0;
    const full = await r.json();
    const phone = pickPhoneFromCandidate(full);
    if (phone) PHONE_CACHE[id] = phone;
    return phone || '';
  }catch{ return ''; }
}

document.addEventListener("DOMContentLoaded", () => {
    const containers = document.querySelectorAll(".card-container");
    const stageMap = {
      'contacted': 'Contactado',
      'no-advance': 'No avanza primera',
      'first-interview': 'Primera entrevista',
      'client-process': 'En proceso con Cliente',
      'applicant': 'Applicant'  
    };
    const stageOrder = ['applicant', 'contacted', 'first-interview', 'no-advance', 'client-process'];
    const stageIndexLookup = stageOrder.reduce((acc, key, idx) => {
      acc[key] = idx;
      return acc;
    }, {});
    const PIPELINE_BACKTRACK_WHITELIST = new Set([
      'bahia@vintti.com',
      'agostina@vintti.com',
      'lara@vintti.com',
      'agustin@vintti.com',
      'jazmin@vintti.com'
    ].map(email => email.toLowerCase()));
    const pipelineUserEmail = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '').toLowerCase().trim();
    const canMoveCandidateBackward = PIPELINE_BACKTRACK_WHITELIST.has(pipelineUserEmail);
    const pipelineRestrictionToast = document.getElementById('pipelineRestrictionToast');
    let pipelineRestrictionToastTimer = null;
    pipelineRestrictionToast?.setAttribute('aria-hidden', 'true');

    function hidePipelineRestrictionMessage() {
      if (!pipelineRestrictionToast) return;
      pipelineRestrictionToast.classList.remove('show');
      pipelineRestrictionToast.setAttribute('aria-hidden', 'true');
    }

    function showPipelineRestrictionMessage() {
      if (!pipelineRestrictionToast) {
        alert("Heads up! You can only move candidates forward in this pipeline.");
        return;
      }
      pipelineRestrictionToast.classList.add('show');
      pipelineRestrictionToast.setAttribute('aria-hidden', 'false');
      clearTimeout(pipelineRestrictionToastTimer);
      pipelineRestrictionToastTimer = setTimeout(() => {
        hidePipelineRestrictionMessage();
      }, 4200);
    }
    pipelineRestrictionToast?.addEventListener('click', hidePipelineRestrictionMessage);

    let draggedCard = null;
    setupPipelineCandidateSearch();
    const candidateCountrySelect = document.getElementById('candidate-country');
    const candidateStateSelect = document.getElementById('candidate-us-state');
    if (candidateStateSelect) {
      const options = ['<option value=\"\">Select state…</option>']
        .concat(PIPELINE_US_STATES.map(s => `<option value=\"${s.code}\">${s.name} (${s.code})</option>`));
      candidateStateSelect.innerHTML = options.join('');
      candidateStateChoices = new Choices('#candidate-us-state', {
        searchEnabled: true,
        itemSelectText: '',
        shouldSort: false,
      });
    }
    updateCandidateStateFieldVisibility(candidateCountrySelect ? candidateCountrySelect.value : '');
 
    // Activar drag para tarjetas iniciales
    document.querySelectorAll(".candidate-card").forEach(enableDrag);
  
    // Permitir soltar en columnas
    containers.forEach(container => {
      container.addEventListener("dragover", e => {
        e.preventDefault();
        container.parentElement.classList.add('drag-over'); // añade clase visual a .column
      });

      container.addEventListener("dragleave", () => {
        container.parentElement.classList.remove('drag-over');
      });
      container.addEventListener("drop", (e) => {
        e.preventDefault();
        console.log('📥 Drop event triggered');

        // Recuperar candidateId desde dataTransfer
        const candidateId = e.dataTransfer.getData("text/plain");
        console.log('📥 CandidateID from dataTransfer:', candidateId);

        if (candidateId) {
          // Buscar la tarjeta en el DOM
          const draggedCardElement = document.querySelector(`.candidate-card[data-candidate-id='${candidateId}']`);
          if (draggedCardElement) {
            console.log('📥 Found draggedCardElement:', draggedCardElement);

            const currentColumn = draggedCardElement.closest('.card-container');
            const currentColumnId = currentColumn?.id || '';
            const targetColumnId = container.id || container.getAttribute('id');
            const currentIndex = stageIndexLookup[currentColumnId];
            const nextIndex = stageIndexLookup[targetColumnId];
            const isMovingBackward = typeof currentIndex === 'number' &&
                                     typeof nextIndex === 'number' &&
                                     nextIndex < currentIndex;

            if (isMovingBackward && !canMoveCandidateBackward) {
              console.info('⛔ Backward move blocked for', pipelineUserEmail || 'unknown user');
              showPipelineRestrictionMessage();
              container.parentElement.classList.remove('drag-over');
              return;
            }

            container.appendChild(draggedCardElement);

            const newStage = container.parentElement.getAttribute('data-status');
            const mappedStage = stageMap[newStage] || null;
            const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");

            console.log(`➡️ Updating candidate ${candidateId} to stage ${mappedStage}`);
            console.log("📤 PATCH stage_pipeline")
            console.log("🔹 candidateId:", candidateId)
            console.log("🔹 opportunityId:", opportunityId)
            console.log("🔹 newStage:", mappedStage)

            fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}/stage`, {
              method: 'PATCH',
              headers: {
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({ stage_pipeline: mappedStage })
            })

            .then(response => {
              if (!response.ok) {
                throw new Error('Error updating candidate stage');
              }
              console.log('✅ Candidate stage updated successfully');
              setTimeout(() => {
                loadPipelineCandidates();
              }, 200);
            })
            .catch(error => {
              console.error('Error updating candidate stage:', error);
            });
          } else {
            console.warn('⚠️ No draggedCardElement found!');
          }
        }
      });

    });

document.getElementById("closePopup").addEventListener("click", () => {
  document.getElementById("candidatePopup").classList.add("hidden");
  loadPipelineCandidates();

  ["candidate-name", "candidate-email", "candidate-phone", "candidate-linkedin", "candidate-country"]
    .forEach(id => document.getElementById(id).value = '');
  resetCandidateStateField();
  updateCandidateStateFieldVisibility('');
});


// Legacy pipeline creation flow: this handler builds the payload posted to
// POST /opportunities/<opportunity_id>/candidates, which creates the candidate
// and immediately links it to the opportunity.
document.getElementById("popupcreateCandidateBtn").addEventListener("click", async () => {
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  const name = document.getElementById("candidate-name").value;
  const email = document.getElementById("candidate-email").value;
  const phoneCode = document.getElementById("phone-country-code").value;
  const rawPhone = document.getElementById("candidate-phone").value.replace(/\s+/g, '');
  const phone = phoneCode + rawPhone;
  const linkedin = document.getElementById("candidate-linkedin").value;
  const selectedCountry = document.getElementById("candidate-country").value;
  let country = selectedCountry;
  if (normalizeCountryKey(selectedCountry) === 'United States') {
    const stateCode = getSelectedCandidateStateCode();
    if (!stateCode) {
      alert('Please choose a state for United States candidates.');
      return;
    }
    country = formatUsCountryValue(stateCode);
  }
  const stage = "Contactado";

  if (!opportunityId || opportunityId === '—') {
    alert('Opportunity ID not found');
    return;
  }

  const payload = {
    name,
    email,
    phone,
    linkedin,
    country,
    stage,
    created_by: localStorage.getItem('user_email') // ✅ esto lo agrega
  };

  try {
    console.log("Payload:", payload);
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Failed to create candidate');

    document.getElementById("candidatePopup").classList.add("hidden");

    // Limpiar campos
    ["candidate-name", "candidate-email", "candidate-phone", "candidate-linkedin", "candidate-country"]
      .forEach(id => document.getElementById(id).value = '');

    loadPipelineCandidates();
  } catch (err) {
    console.error("Error creating candidate:", err);
    alert("Failed to create candidate");
  }
});
const goBackButton = document.getElementById('goBackButton');
const previousPage = localStorage.getItem('previousPage');

if (previousPage && goBackButton) {
  goBackButton.style.display = 'block';
  goBackButton.addEventListener('click', () => {
    window.location.href = previousPage;
    localStorage.removeItem('previousPage');
  });
}
new Choices('#candidate-country', {
  searchEnabled: true,
  itemSelectText: '',
  shouldSort: false,
});
const countryToCodeMap = {
  "Argentina": "54",
  "Bolivia": "591",
  "Brazil": "55",
  "Chile": "56",
  "Colombia": "57",
  "Costa Rica": "506",
  "Cuba": "53",
  "Ecuador": "593",
  "El Salvador": "503",
  "Guatemala": "502",
  "Honduras": "504",
  "Mexico": "52",
  "United States": "1",
  "Canada": "1",
  "Nicaragua": "505",
  "Panama": "507",
  "Paraguay": "595",
  "Peru": "51",
  "Puerto Rico": "1",
  "Dominican Republic": "1",
  "Uruguay": "598",
  "Venezuela": "58"
};

document.getElementById('candidate-country').addEventListener('change', (e) => {
  const selectedCountry = e.target.value;
  updateCandidateStateFieldVisibility(selectedCountry);
  const code = countryToCodeMap[normalizeCountryKey(selectedCountry)];
  if (code) {
    document.getElementById('phone-country-code').value = code;
  }
});

  // 🔢 Prefill + guardado del input "Number of interviewed candidates"
  const interviewedInput = document.getElementById('interviewed-count-input');
  if (interviewedInput) {
    // Prefill desde la BD
    (async () => {
      try {
        const el = document.getElementById('opportunity-id-text');
        const oppId = (el?.getAttribute('data-id') || el?.textContent || '').trim();
        console.log('🧩 Prefill entrevistados · oppId =', oppId);

        if (!oppId || oppId === '—') {
          console.warn('⚠️ No oppId para prefill de entrevistados');
          return;
        }

        const res = await fetch(`${API_BASE}/opportunities/${oppId}`, {
          cache: 'no-store'
        });
        if (!res.ok) {
          console.warn('⚠️ GET /opportunities/:id no OK para prefill entrevistados', res.status);
          return;
        }

        const data = await res.json();
        console.log('📦 Datos oportunidad para prefill entrevistados:', data);

        // intenta leer el campo exactamente como viene del backend
        const v = data.cantidad_entrevistados ?? data.candidates_interviewed ?? null;
        console.log('🎯 cantidad_entrevistados leído del API =', v, 'typeof =', typeof v);

        if (v === null || v === undefined) {
          // no hay valor en DB -> deja vacío
          interviewedInput.value = '';
        } else {
          interviewedInput.value = String(v);
        }

        console.log('✅ Valor final en interviewed-count-input =', interviewedInput.value);
      } catch (err) {
        console.warn('⚠️ Could not prefill interviewed count', err);
      }
    })();

    // Guardar en la BD al cambiar
    interviewedInput.addEventListener('blur', async (e) => {
      if (typeof updateOpportunityField !== 'function') {
        console.warn('⚠️ updateOpportunityField no está definido en este scope');
        return;
      }

      let raw = (e.target.value || '').trim();

      if (raw === '') {
        // Borrado → guardamos null
        await updateOpportunityField('cantidad_entrevistados', null);
        return;
      }

      let n = parseInt(raw, 10);
      if (!Number.isFinite(n) || n < 0) {
        n = 0;
      }

      // Normalizar lo que ve el usuario
      e.target.value = String(n);

      // 💾 Guardar en DB (tabla opportunity.cantidad_entrevistados)
      await updateOpportunityField('cantidad_entrevistados', n);
    });
  }

}); //  cierre del DOMContentLoaded

// 🚀 FUNCION: Cargar candidatos desde el backend y mostrarlos en el pipeline
function loadPipelineCandidates() {
  // Leer el opportunity_id que ya está en la página
  const opportunityId = document.getElementById('opportunity-id-text').textContent.trim();
  if (opportunityId === '—' || opportunityId === '') {
    console.error('Opportunity ID not found');
    return;
  }

  // Hacer fetch al backend
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`)
    .then(response => response.json())
    .then(candidates => {
      console.log('🔵 Candidates:', candidates);
              const counters = {
                'applicant': 0, 
        'contacted': 0,
        'no-advance': 0,
        'first-interview': 0,
        'client-process': 0
      };
      // Limpiar todas las columnas antes
      document.querySelectorAll('.card-container').forEach(container => {
        container.innerHTML = '';
      });

candidates.forEach(candidate => {
  const card = document.createElement('div');
  card.className = 'candidate-card pipeline-card';
  card.setAttribute('data-candidate-id', candidate.candidate_id); 
  const signoffChecked = candidate.sign_off === 'yes' ? 'checked' : '';
  const isStarred = candidate.star === 'yes';
  const starClass = isStarred ? 'starred' : '';
  const rawBlacklist = candidate.is_blacklisted ?? candidate.blacklist;

card.innerHTML = `
<div class="card-header">
  <div class="candidate-info">
    <strong class="candidate-name" title="${candidate.name}">${candidate.name}</strong>
    <div class="candidate-meta">
      <span class="country"></span>
      <span class="salary">${candidate.salary_range ? `$${Number(candidate.salary_range).toLocaleString()}` : '—'}</span>
    </div>
    <div class="star-wrapper">
      <i class="fas fa-star star-icon ${starClass}" title="Star"></i>
      <i class="fab fa-whatsapp wa-icon" title="WhatsApp"></i>
    </div>
  </div>
  <span class="delete-icon" title="Delete">🗑️</span>
  <div class="signoff-toggle">
    <label class="switch">
      <input type="checkbox" class="signoff-checkbox" ${signoffChecked} data-candidate-id="${candidate.candidate_id}">
      <span class="slider round"></span>
    </label>
  </div>
</div>
`;
const countryEl = card.querySelector('.country');
if (countryEl) {
  const formattedCountry = formatCountryDisplay(candidate.country);
  const flag = getFlagEmoji(candidate.country);
  if (formattedCountry && formattedCountry !== '—') {
    countryEl.textContent = flag ? `${flag} ${formattedCountry}` : formattedCountry;
  } else {
    countryEl.textContent = '—';
  }
}
decorateUsingCandidateBlacklist(card, candidate, rawBlacklist);
decorateCandidateAssociations(card, candidate);
// WhatsApp click (robusto con fallback a /candidates/:id)
// WhatsApp click (robusto con fallback a /candidates/:id)
{
  const waIcon = card.querySelector('.wa-icon');
  if (waIcon) {
    // si ya vino un teléfono “inline”, precárgalo en dataset (no bloquea el fallback)
    const inlineRaw = pickPhoneFromCandidate(candidate);
    if (inlineRaw) waIcon.dataset.rawPhone = inlineRaw;

    waIcon.addEventListener('click', async (e) => {
      e.stopPropagation();

      // 1) usa dataset si existe, si no, resuélvelo con fetch al /candidates/:id
      let raw = waIcon.dataset.rawPhone || '';
      if (!raw) {
        raw = await resolvePhone(candidate);
        if (raw) waIcon.dataset.rawPhone = raw; // cachea en el DOM
      }

      // 2) normaliza → E.164 sin "+" (wa.me requiere solo dígitos)
      const waNumber = normalizePhoneForWA(raw, candidate.country);

      if (!waNumber) {
        alert('No phone number for this candidate.');
        return;
      }

      // 3) abrir en la MISMA pestaña para evitar bloqueos de popup
      location.href = `https://wa.me/${waNumber}`;
      // (alternativa igual de válida)
      // location.assign(`https://wa.me/${waNumber}`);
    });
  }
}



  card.querySelector(".delete-icon").addEventListener("click", async (e) => {

  e.stopPropagation(); // evitar que redireccione

  const candidateId = card.getAttribute("data-candidate-id");
  const opportunityId = document.getElementById('opportunity-id-text').textContent.trim();
  if (columnId) {
    container.appendChild(card);
    counters[columnId]++;
  }

  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/opportunities`);
  const linkedOpportunities = await res.json();

  let message = "Are you sure you want to delete this candidate from the pipeline?";
  if (linkedOpportunities.length === 1 && linkedOpportunities[0].opportunity_id == opportunityId) {
    message += "\n⚠️ This candidate is only linked to this opportunity. Deleting will remove them from the database.";
  }

  if (confirm(message)) {
    const deleteRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}`, {
      method: 'DELETE'
    });
    if (deleteRes.ok) {
      loadPipelineCandidates();
    } else {
      alert("Error deleting candidate.");
    }
  }
});
card.querySelector(".star-icon").addEventListener("click", async (e) => {
  e.stopPropagation();
  const starIcon = e.target;
  const candidateId = card.getAttribute("data-candidate-id");
  const newStarValue = starIcon.classList.contains('starred') ? 'no' : 'yes';

  try {
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}/star`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ star: newStarValue })
    });
    console.log(`⭐ Star status updated for candidate ${candidateId} to ${newStarValue}`);
    starIcon.classList.toggle('starred', newStarValue === 'yes');
  } catch (err) {
    console.error("❌ Error updating star:", err);
  }
});

  card.querySelector(".signoff-checkbox").addEventListener("change", async (e) => {
  e.stopPropagation();
  const checkbox = e.target;
  const candidateId = checkbox.getAttribute("data-candidate-id");
  const signOffValue = checkbox.checked ? "yes" : "no";

  try {
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}/signoff`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sign_off: signOffValue }),
    });
    console.log(`📝 Sign off status updated for candidate ${candidateId}`);
    checkbox.checked = signOffValue === 'yes';
  } catch (err) {
    console.error("❌ Error updating sign_off:", err);
  }
});

  enableDrag(card);
  card.addEventListener('click', (e) => {
    const candidateId = card.getAttribute('data-candidate-id');
    if (!candidateId) return;

    const isSafe = !e.target.closest('.signoff-toggle') &&
                  !e.target.closest('.delete-icon') &&
                  !e.target.closest('input') &&
                  !e.target.closest('select');

    if (!isSafe) return;

    localStorage.setItem('previousPage', window.location.href);
    window.location.href = `https://vinttihub.vintti.com/candidate-details.html?id=${candidateId}`;
  });



// Mapeo del stage → columna id
const stageVal = (candidate.stage_pipeline || candidate.stage || '').trim();

let columnId = '';
switch (stageVal) {
  case 'Applicant':
    columnId = 'applicant';
    break;
  case 'Contactado':
    columnId = 'contacted';
    break;
  case 'No avanza primera':
    columnId = 'no-advance';
    break;
  case 'Primera entrevista':
    columnId = 'first-interview';
    break;
  case 'En proceso con Cliente':
    columnId = 'client-process';
    break;
  default:
    console.warn(`Stage desconocido: ${stageVal}`);
    columnId = 'contacted'; // fallback amigable
}


  const container = document.getElementById(columnId);
  if (container) {
    container.appendChild(card);
    counters[columnId]++; // ✅ Sumar al contador después de agregar
  }
        for (const column in counters) {
        const countElement = document.getElementById(`count-${column}`);
        if (countElement) {
          countElement.textContent = counters[column];
        }
      }
});
for (const column in counters) {
  const countElement = document.getElementById(`count-${column}`);
  if (countElement) {
    countElement.textContent = counters[column];
  }
}

    })
    .catch(error => {
      console.error('Error loading candidates:', error);
    });
}
window.loadPipelineCandidates = loadPipelineCandidates;

function enableDrag(card) {
      card.draggable = true;
  
      card.addEventListener("dragstart", (e) => {
        draggedCard = card;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.getAttribute("data-candidate-id"));
      });

  
      card.addEventListener("dragend", () => {
        setTimeout(() => {
          draggedCard = null;
        }, 0);
      });
    }
function getFlagEmoji(country) {
  const flags = {
    "Argentina": "🇦🇷", "Bolivia": "🇧🇴", "Brazil": "🇧🇷", "Chile": "🇨🇱",
    "Colombia": "🇨🇴", "Costa Rica": "🇨🇷", "Cuba": "🇨🇺", "Ecuador": "🇪🇨",
    "El Salvador": "🇸🇻", "Guatemala": "🇬🇹", "Honduras": "🇭🇳", "Mexico": "🇲🇽",
    "United States": "🇺🇸", "Canada": "🇨🇦",
    "Nicaragua": "🇳🇮", "Panama": "🇵🇦", "Paraguay": "🇵🇾", "Peru": "🇵🇪",
    "Puerto Rico": "🇵🇷", "Dominican Republic": "🇩🇴", "Uruguay": "🇺🇾", "Venezuela": "🇻🇪"
  };
  const base = normalizeCountryKey(country);
  return flags[base] || "";
}

const pipelineSearchUI = {
  popup: null,
  input: null,
  closeBtn: null,
  results: null,
  start: null,
  loading: null,
  empty: null,
  error: null,
  success: null,
  openBtn: null
};
let pipelineSearchAbortController = null;
let pipelineSearchDebounced = null;

function setupPipelineCandidateSearch() {
  pipelineSearchUI.popup = document.getElementById('pipelineSearchPopup');
  pipelineSearchUI.input = document.getElementById('pipeline-search-input');
  pipelineSearchUI.closeBtn = document.getElementById('closePipelineSearchPopup');
  pipelineSearchUI.results = document.getElementById('pipeline-search-results');
  pipelineSearchUI.start = document.getElementById('pipeline-search-start');
  pipelineSearchUI.loading = document.getElementById('pipeline-search-loading');
  pipelineSearchUI.empty = document.getElementById('pipeline-search-empty');
  pipelineSearchUI.error = document.getElementById('pipeline-search-error');
  pipelineSearchUI.success = document.getElementById('pipeline-search-success');
  pipelineSearchUI.openBtn = document.getElementById('pipelineAddCandidateBtn');

  if (!pipelineSearchUI.popup || !pipelineSearchUI.input || !pipelineSearchUI.results || !pipelineSearchUI.openBtn) {
    return;
  }

  pipelineSearchDebounced = debounce(runPipelineCandidateSearch, 320);

  pipelineSearchUI.openBtn.addEventListener('click', openPipelineSearchPopup);
  pipelineSearchUI.closeBtn?.addEventListener('click', closePipelineSearchPopup);
  pipelineSearchUI.popup.addEventListener('click', (evt) => {
    if (evt.target === pipelineSearchUI.popup) {
      closePipelineSearchPopup();
    }
  });

  pipelineSearchUI.input.addEventListener('input', (e) => {
    const term = (e.target.value || '').trim();
    if (term.length < 2) {
      pipelineSearchUI.results.innerHTML = '';
      showPipelineSearchNotice('start');
      if (pipelineSearchAbortController) {
        pipelineSearchAbortController.abort();
        pipelineSearchAbortController = null;
      }
      return;
    }
    pipelineSearchDebounced(term);
  });

  // Estado inicial
  showPipelineSearchNotice('start');
}

function openPipelineSearchPopup() {
  if (!pipelineSearchUI.popup) return;
  pipelineSearchUI.popup.classList.remove('hidden');
  pipelineSearchUI.results.innerHTML = '';
  pipelineSearchUI.input.value = '';
  showPipelineSearchNotice('start');
  requestAnimationFrame(() => pipelineSearchUI.input?.focus());
}

function closePipelineSearchPopup() {
  if (!pipelineSearchUI.popup) return;
  pipelineSearchUI.popup.classList.add('hidden');
  pipelineSearchUI.results.innerHTML = '';
  pipelineSearchUI.input.value = '';
  showPipelineSearchNotice('start');
  if (pipelineSearchAbortController) {
    pipelineSearchAbortController.abort();
    pipelineSearchAbortController = null;
  }
}

function hidePipelineSearchNotices() {
  ['start', 'loading', 'empty', 'error', 'success'].forEach((key) => {
    const el = pipelineSearchUI[key];
    if (el) el.style.display = 'none';
  });
}

function showPipelineSearchNotice(type, message) {
  hidePipelineSearchNotices();
  const el = pipelineSearchUI[type];
  if (!el) return;
  if (typeof message === 'string') {
    el.textContent = message;
  }
  el.style.display = 'block';
}

async function runPipelineCandidateSearch(term) {
  if (!pipelineSearchUI.results) return;
  try {
    showPipelineSearchNotice('loading');
    pipelineSearchUI.results.innerHTML = '';
    if (pipelineSearchAbortController) {
      pipelineSearchAbortController.abort();
    }
    pipelineSearchAbortController = new AbortController();
    const res = await fetch(`${API_BASE}/candidates/search?q=${encodeURIComponent(term)}`, {
      signal: pipelineSearchAbortController.signal,
      cache: 'no-store'
    });
    if (!res.ok) {
      throw new Error(`Search failed ${res.status}`);
    }
    const items = await res.json();
    pipelineSearchAbortController = null;
    if (!Array.isArray(items) || !items.length) {
      showPipelineSearchNotice('empty');
      return;
    }
    hidePipelineSearchNotices();
    renderPipelineSearchResults(items);
  } catch (err) {
    if (err.name === 'AbortError') return;
    console.error('Error searching candidates:', err);
    showPipelineSearchNotice('error', 'Could not search candidates. Please try again.');
  }
}

function renderPipelineSearchResults(items) {
  pipelineSearchUI.results.innerHTML = '';
  const fragment = document.createDocumentFragment();
  items.forEach((candidate) => {
    const li = document.createElement('li');
    li.className = 'search-result-item';

    const wrapper = document.createElement('div');
    wrapper.className = 'search-result-item-content';

    const details = document.createElement('div');
    details.className = 'search-result-details';
    const nameEl = document.createElement('div');
    nameEl.className = 'search-result-name';
    nameEl.textContent = candidate.name || '(no name)';
    const linkedinEl = document.createElement('div');
    linkedinEl.className = 'search-result-meta';
    linkedinEl.textContent = candidate.linkedin ? formatLinkedInPreview(candidate.linkedin) : 'LinkedIn not available';
    const emailEl = document.createElement('div');
    emailEl.className = 'search-result-meta';
    emailEl.textContent = candidate.email || 'Email not available';

    details.appendChild(nameEl);
    details.appendChild(linkedinEl);
    details.appendChild(emailEl);

    const actionBtn = document.createElement('button');
    actionBtn.type = 'button';
    actionBtn.className = 'pipeline-add-btn';
    actionBtn.textContent = 'Add';
    actionBtn.addEventListener('click', (evt) => {
      evt.stopPropagation();
      linkCandidateToPipeline(candidate.candidate_id, actionBtn, candidate.name || '(no name)');
    });

    wrapper.appendChild(details);
    wrapper.appendChild(actionBtn);
    li.appendChild(wrapper);
    li.addEventListener('click', () => {
      linkCandidateToPipeline(candidate.candidate_id, actionBtn, candidate.name || '(no name)');
    });
    fragment.appendChild(li);
  });
  pipelineSearchUI.results.appendChild(fragment);
}

// Pipeline search uses this helper to call POST /opportunities/<id>/candidates/link,
// which only inserts the relationship row in opportunity_candidates.
async function linkCandidateToPipeline(candidateId, triggerButton, candidateName = '') {
  const opportunityEl = document.getElementById('opportunity-id-text');
  const opportunityId = opportunityEl?.getAttribute('data-id') || opportunityEl?.textContent || '';
  if (!candidateId || !opportunityId || opportunityId === '—') {
    showPipelineSearchNotice('error', 'Opportunity ID not found.');
    return;
  }
  const candidateLabel = (candidateName || '').trim() || 'this candidate';
  const allow = await ensureCandidateAssociationAllowed(candidateId, candidateLabel, opportunityId);
  if (!allow) return;

  setCandidateLinkButtonState(triggerButton, true);
  try {
    const payload = {
      candidate_id: candidateId,
      stage: 'Contactado',
      created_by: localStorage.getItem('user_email') || undefined
    };

    const res = await fetch(`${API_BASE}/opportunities/${opportunityId}/candidates/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (res.status === 409) {
      showPipelineSearchNotice('error', 'Candidate is already in this opportunity.');
      return;
    }
    if (!res.ok) {
      throw new Error(`Link failed ${res.status}`);
    }

    showPipelineSearchNotice('success', 'Candidate added to pipeline.');
    pipelineSearchUI.results.innerHTML = '';
    if (typeof loadPipelineCandidates === 'function') {
      loadPipelineCandidates();
    }
    setTimeout(() => {
      closePipelineSearchPopup();
    }, 900);
  } catch (err) {
    console.error('Error linking candidate:', err);
    showPipelineSearchNotice('error', 'Could not add candidate. Please try again.');
  } finally {
    setCandidateLinkButtonState(triggerButton, false);
  }
}

function setCandidateLinkButtonState(btn, isLoading) {
  if (!btn) return;
  btn.disabled = Boolean(isLoading);
  btn.textContent = isLoading ? 'Adding…' : 'Add';
}

function formatLinkedInPreview(url) {
  if (!url) return '';
  let clean = url.trim();
  if (!clean) return '';
  if (!/^https?:\/\//i.test(clean)) {
    clean = `https://${clean}`;
  }
  try {
    const parsed = new URL(clean);
    const host = parsed.hostname.replace(/^www\./, '');
    let path = parsed.pathname.replace(/\/$/, '');
    if (path.length > 25) {
      path = `${path.slice(0, 25)}…`;
    }
    return `${host}${path}`;
  } catch {
    return clean.length > 30 ? `${clean.slice(0, 30)}…` : clean;
  }
}

function debounce(fn, wait = 300) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn.apply(null, args), wait);
  };
}

document.addEventListener('DOMContentLoaded', wireCandidateAssociationPopup);
