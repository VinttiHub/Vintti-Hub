const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
const PHONE_CODE_BY_COUNTRY = {
  Argentina: '54',
  Bolivia: '591',
  Brazil: '55',
  Chile: '56',
  Colombia: '57',
  'Costa Rica': '506',
  Cuba: '53',
  Ecuador: '593',
  'El Salvador': '503',
  Guatemala: '502',
  Honduras: '504',
  Mexico: '52',
  Nicaragua: '505',
  Panama: '507',
  Paraguay: '595',
  Peru: '51',
  'Puerto Rico': '1',
  'Dominican Republic': '1',
  Uruguay: '598',
  Venezuela: '58',
  'United States': '1'
};

const COUNTRY_FLAG_BY_NAME = {
  Argentina: '🇦🇷',
  Bolivia: '🇧🇴',
  Brazil: '🇧🇷',
  Chile: '🇨🇱',
  Colombia: '🇨🇴',
  'Costa Rica': '🇨🇷',
  Cuba: '🇨🇺',
  Ecuador: '🇪🇨',
  'El Salvador': '🇸🇻',
  Guatemala: '🇬🇹',
  Honduras: '🇭🇳',
  Mexico: '🇲🇽',
  Nicaragua: '🇳🇮',
  Panama: '🇵🇦',
  Paraguay: '🇵🇾',
  Peru: '🇵🇪',
  'Puerto Rico': '🇵🇷',
  'Dominican Republic': '🇩🇴',
  Uruguay: '🇺🇾',
  Venezuela: '🇻🇪',
  'United States': '🇺🇸'
};

const COUNTRY_NAMES = Object.keys(PHONE_CODE_BY_COUNTRY).sort((a, b) => a.localeCompare(b));
const DEFAULT_PHONE_COUNTRY = 'Argentina';

const candidateState = {
  tbody: null,
  tableEl: null,
  data: [],
  dataTable: null,
  searchBound: false,
  duplicateMatch: null,
  duplicateDetailsCache: new Map(),
  blacklistFilter: 'all',
  loadingOverlay: null,
  loadingText: null
};

const candidateModalRefs = {
  overlay: null,
  form: null,
  submitBtn: null,
  errorBox: null,
  duplicateBox: null,
  duplicateFields: null,
  toast: null,
  nameInput: null,
  emailInput: null,
  countrySelect: null,
  countrySearchInput: null,
  countryDisplayButton: null,
  countryDropdown: null,
  countryOptionsList: null,
  phoneCodeSelect: null,
  phoneInput: null,
  linkedinInput: null,
  openExistingBtn: null
};

let nameSearchDebounce = null;
let toastTimer = null;

document.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('light-mode');

  candidateState.tbody = document.getElementById('candidatesTableBody');
  candidateState.tableEl = document.getElementById('candidatesTable');
  candidateState.loadingOverlay = document.getElementById('candidatesLoadingOverlay');
  candidateState.loadingText = document.querySelector('.candidates-loading-text');

  initCandidatesLoadingOverlay();
  lockSidebarWidth();
  setupBlacklistFilterControl();
  loadCandidates();
  setupRowNavigation();
  setupSidebarToggle();
  setupCandidateModal();
});

async function loadCandidates(options = {}) {
  const { showLoader = true, loaderMessage = 'Loading candidates…' } = options;
  if (showLoader) toggleCandidatesLoading(true, loaderMessage);

  const filter = candidateState.blacklistFilter || 'all';
  const url = new URL(`${API_BASE}/candidates/light_fast`);
  url.searchParams.set('blacklist_filter', filter);

  try {
    const res = await fetch(url.toString(), { cache: 'no-store' });
    const data = await res.json();
    candidateState.data = Array.isArray(data) ? data : [];
    paintCandidateRows(candidateState.data);
  } catch (err) {
    console.error('❌ Error al obtener candidatos:', err);
    candidateState.data = [];
    paintCandidateRows(candidateState.data);
  } finally {
    if (showLoader) toggleCandidatesLoading(false);
  }
}

function initCandidatesLoadingOverlay() {
  if (!candidateState.loadingOverlay) return;
  candidateState.loadingOverlay.classList.add('hidden');
  candidateState.loadingOverlay.setAttribute('aria-hidden', 'true');
}

function toggleCandidatesLoading(show, message) {
  if (!candidateState.loadingOverlay) return;
  if (message && candidateState.loadingText) {
    candidateState.loadingText.textContent = message;
  }
  candidateState.loadingOverlay.classList.toggle('hidden', !show);
  candidateState.loadingOverlay.setAttribute('aria-hidden', show ? 'false' : 'true');
  candidateState.loadingOverlay.setAttribute('aria-busy', show ? 'true' : 'false');
}

function buildCandidateRow(candidate) {
  const tr = document.createElement('tr');
  tr.dataset.id = candidate.candidate_id || '';
  tr.dataset.status = (candidate.status || '').toLowerCase();
  tr.dataset.model = (candidate.opp_model || '').trim();

  const rawPhone = candidate.phone ? String(candidate.phone) : '';
  const phone = rawPhone.replace(/\D/g, '');
  const linkedin = candidate.linkedin || '';
  const isBlacklisted = Boolean(candidate.is_blacklisted);
  if (isBlacklisted) {
    tr.classList.add('blacklisted-row');
  }

  const condition = tr.dataset.status || 'unhired';
  const chipClass = {
    active: 'status-active',
    unhired: 'status-unhired'
  }[condition] || 'status-unhired';
  const blacklistChipClass = isBlacklisted ? 'is-blacklisted' : 'not-blacklisted';
  const blacklistLabel = isBlacklisted ? 'True' : 'False';

  const nameCellClasses = ['name-cell'];
  if (isBlacklisted) nameCellClasses.push('danger-name');
  const nameContent = isBlacklisted
    ? `<span class="danger-emoji" role="img" aria-label="Blacklisted candidate" title="Blacklisted candidate">🚨</span>
       <span>${candidate.name || '—'}</span>`
    : `${candidate.name || '—'}`;

  tr.innerHTML = `
    <td class="condition-cell"><span class="status-chip ${chipClass}">${condition}</span></td>
    <td class="${nameCellClasses.join(' ')}">${nameContent}</td>
    <td>${candidate.country || '—'}</td>
    <td>
      ${
        phone
          ? `<button class="icon-button whatsapp" onclick="event.stopPropagation(); window.open('https://wa.me/${phone}', '_blank')">
               <i class='fab fa-whatsapp'></i>
             </button>`
          : '—'
      }
    </td>
    <td>
      ${
        linkedin
          ? `<button class="icon-button linkedin" onclick="event.stopPropagation(); window.open('${linkedin}', '_blank')">
               <i class='fab fa-linkedin-in'></i>
             </button>`
          : '—'
      }
    </td>
    <td>
      <span class="blacklist-chip ${blacklistChipClass}" aria-label="Blacklist status">
        ${blacklistLabel}
      </span>
    </td>
  `;

  return tr;
}

function buildEmptyRow() {
  const tr = document.createElement('tr');
  tr.innerHTML = `<td colspan="6">No data available</td>`;
  return tr;
}

function paintCandidateRows(data) {
  if (!candidateState.tbody) return;
  const rows = (Array.isArray(data) && data.length ? data.map(buildCandidateRow) : [buildEmptyRow()]);

  if (!candidateState.dataTable) {
    const frag = document.createDocumentFragment();
    rows.forEach(row => frag.appendChild(row));
    candidateState.tbody.replaceChildren(frag);
    initDataTable();
    return;
  }

  candidateState.dataTable.clear();
  rows.forEach(row => candidateState.dataTable.row.add(row));
  candidateState.dataTable.draw();
}

function initDataTable() {
  if (!candidateState.tableEl) return;
  candidateState.dataTable = $('#candidatesTable').DataTable({
    responsive: true,
    pageLength: 50,
    dom: 'lrtip',
    lengthMenu: [[50, 100, 150], [50, 100, 150]],
    language: {
      search: "🔍 Buscar:",
      lengthMenu: "Mostrar _MENU_ registros por página",
      zeroRecords: "No se encontraron resultados",
      info: "Mostrando _START_ a _END_ de _TOTAL_ registros",
      paginate: { first: "Primero", last: "Último", next: "Siguiente", previous: "Anterior" }
    }
  });

  moveLengthControl();
  bindNameSearchInput(candidateState.dataTable);
  installAdvancedFilters(candidateState.dataTable);
}

function moveLengthControl() {
  const wrapper = document.getElementById('datatable-wrapper');
  const dataTableLength = document.querySelector('.dataTables_length');
  if (wrapper && dataTableLength && !wrapper.contains(dataTableLength)) {
    wrapper.appendChild(dataTableLength);
  }
}

function bindNameSearchInput(table) {
  if (candidateState.searchBound) return;
  const searchInput = document.getElementById('searchByName');
  if (!searchInput) return;

  searchInput.addEventListener('input', function () {
    clearTimeout(nameSearchDebounce);
    const value = this.value;
    nameSearchDebounce = setTimeout(() => table.column(1).search(value).draw(), 150);
  });
  candidateState.searchBound = true;
}

function setupBlacklistFilterControl() {
  const select = document.getElementById('blacklistFilter');
  if (!select) return;

  const validValues = new Set(['all', 'only', 'exclude']);
  const normalizeValue = (value) => {
    const next = (value || '').trim().toLowerCase();
    return validValues.has(next) ? next : 'all';
  };

  const initialValue = normalizeValue(select.value);
  candidateState.blacklistFilter = initialValue;
  select.value = initialValue;

  select.addEventListener('change', () => {
    const nextValue = normalizeValue(select.value);
    if (candidateState.blacklistFilter === nextValue) return;
    candidateState.blacklistFilter = nextValue;
    loadCandidates({ loaderMessage: 'Applying blacklist filter…' });
  });
}

function setupRowNavigation() {
  if (!candidateState.tbody) return;
  candidateState.tbody.addEventListener('click', (e) => {
    const row = e.target.closest('tr');
    if (!row) return;
    const id = row.dataset.id;
    if (!id) return;

    const clickSound = document.getElementById('click-sound');
    if (clickSound) {
      try { clickSound.currentTime = 0; clickSound.play(); } catch (_) {}
      setTimeout(() => { window.location.href = `candidate-details.html?id=${id}`; }, 120);
    } else {
      window.location.href = `candidate-details.html?id=${id}`;
    }
  });
}

function setupSidebarToggle() {
  const sidebar = document.querySelector('.sidebar');
  const mainContent = document.querySelector('.main-content');
  const toggleButton = document.getElementById('sidebarToggle');
  const toggleIcon = document.getElementById('sidebarToggleIcon');
  if (!sidebar || !mainContent || !toggleButton || !toggleIcon) return;

  const applySidebarState = (isHidden) => {
    sidebar.classList.toggle('custom-sidebar-hidden', isHidden);
    mainContent.classList.toggle('custom-main-expanded', isHidden);
    toggleIcon.classList.toggle('fa-chevron-left', !isHidden);
    toggleIcon.classList.toggle('fa-chevron-right', isHidden);
    toggleButton.style.left = isHidden ? '12px' : '220px';
  };

  applySidebarState(localStorage.getItem('sidebarHidden') === 'true');
  toggleButton.addEventListener('click', () => {
    const isHidden = !sidebar.classList.contains('custom-sidebar-hidden');
    applySidebarState(isHidden);
    localStorage.setItem('sidebarHidden', isHidden);
  });
}

function lockSidebarWidth() {
  const sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;
  const rootStyles = getComputedStyle(document.documentElement);
  let sidebarWidth = rootStyles.getPropertyValue('--sidebar-width');
  sidebarWidth = sidebarWidth ? sidebarWidth.trim() : '';
  if (!sidebarWidth) {
    sidebarWidth = `${sidebar.offsetWidth || 250}px`;
  }
  sidebar.style.flex = `0 0 ${sidebarWidth}`;
  sidebar.style.minWidth = sidebarWidth;
  sidebar.style.maxWidth = sidebarWidth;
}

function setupCandidateModal() {
  candidateModalRefs.overlay = document.getElementById('candidateCreateModal');
  candidateModalRefs.form = document.getElementById('candidateCreateForm');
  candidateModalRefs.submitBtn = document.getElementById('candidateModalSubmit');
  candidateModalRefs.errorBox = document.getElementById('candidateFormError');
  candidateModalRefs.duplicateBox = document.getElementById('candidateDuplicateBox');
  candidateModalRefs.duplicateFields = document.getElementById('candidateDuplicateFields');
  candidateModalRefs.toast = document.getElementById('candidateCreateToast');
  candidateModalRefs.nameInput = document.getElementById('candidateFullName');
  candidateModalRefs.emailInput = document.getElementById('candidateEmail');
  candidateModalRefs.countrySelect = document.getElementById('candidateCountry');
  candidateModalRefs.countrySearchInput = document.getElementById('candidateCountrySearch');
  candidateModalRefs.countryDisplayButton = document.getElementById('candidateCountryDisplay');
  candidateModalRefs.countryDropdown = document.getElementById('candidateCountryDropdown');
  candidateModalRefs.countryOptionsList = document.getElementById('candidateCountryOptions');
  candidateModalRefs.phoneCodeSelect = document.getElementById('candidatePhoneCode');
  candidateModalRefs.phoneInput = document.getElementById('candidatePhone');
  candidateModalRefs.linkedinInput = document.getElementById('candidateLinkedin');
  candidateModalRefs.openExistingBtn = document.getElementById('openExistingCandidateBtn');

  const openBtn = document.getElementById('openCandidateModalBtn');
  const closeBtn = document.getElementById('candidateModalCloseBtn');
  if (!candidateModalRefs.overlay || !candidateModalRefs.form || !openBtn) return;

  openBtn.addEventListener('click', openCandidateModal);
  closeBtn?.addEventListener('click', closeCandidateModal);
  candidateModalRefs.overlay.addEventListener('click', (e) => {
    if (e.target === candidateModalRefs.overlay) closeCandidateModal();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && candidateModalRefs.overlay.getAttribute('aria-hidden') === 'false') {
      closeCandidateModal();
    }
  });

  candidateModalRefs.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    await handleCandidateSubmit();
  });

  candidateModalRefs.form.addEventListener('input', () => {
    hideFormError();
    hideDuplicateWarning();
    clearInputErrors();
  });

  candidateModalRefs.openExistingBtn?.addEventListener('click', () => {
    const id = candidateState.duplicateMatch?.candidate_id;
    if (id) {
      window.location.href = `https://vinttihub.vintti.com/candidate-details.html?id=${encodeURIComponent(id)}`;
    }
  });

  renderPhoneCountryOptions();
  renderNativeCountryOptions();
  updateCountryDisplay('');
  renderCountrySelectOptions('');

  candidateModalRefs.countrySearchInput?.addEventListener('input', (event) => {
    renderCountrySelectOptions(event.target.value || '');
  });
  candidateModalRefs.countrySearchInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      closeCountryDropdown();
    }
  });

  candidateModalRefs.countryDisplayButton?.addEventListener('click', () => {
    toggleCountryDropdown();
  });
  candidateModalRefs.countryDisplayButton?.setAttribute('aria-haspopup', 'listbox');
  candidateModalRefs.countryDisplayButton?.setAttribute('aria-expanded', 'false');
  candidateModalRefs.countryDisplayButton?.addEventListener('keydown', (event) => {
    if (event.key === ' ' || event.key === 'Enter') {
      event.preventDefault();
      toggleCountryDropdown();
    }
    if (event.key === 'Escape') {
      closeCountryDropdown();
    }
  });

  document.addEventListener('click', (event) => {
    if (!candidateModalRefs.countryDropdown || candidateModalRefs.countryDropdown.hidden) return;
    const within = event.target.closest('.searchable-select');
    if (!within) {
      closeCountryDropdown();
    }
  });
}

function openCandidateModal() {
  resetCandidateForm();
  hideDuplicateWarning();
  hideFormError();
  candidateModalRefs.overlay.removeAttribute('hidden');
  candidateModalRefs.overlay.setAttribute('aria-hidden', 'false');
  candidateModalRefs.nameInput?.focus();
}

function closeCandidateModal() {
  candidateModalRefs.overlay.setAttribute('aria-hidden', 'true');
  candidateModalRefs.overlay.setAttribute('hidden', '');
  closeCountryDropdown();
}

function resetCandidateForm() {
  candidateModalRefs.form?.reset();
  candidateState.duplicateMatch = null;
  clearInputErrors();
  if (candidateModalRefs.countrySearchInput) {
    candidateModalRefs.countrySearchInput.value = '';
  }
  if (candidateModalRefs.countrySelect) {
    candidateModalRefs.countrySelect.value = '';
  }
  renderCountrySelectOptions(candidateModalRefs.countrySearchInput?.value || '');
  updateCountryDisplay('');
  closeCountryDropdown();
  if (candidateModalRefs.phoneCodeSelect) {
    candidateModalRefs.phoneCodeSelect.value = DEFAULT_PHONE_COUNTRY;
  }
}

function clearInputErrors() {
  [
    candidateModalRefs.nameInput,
    candidateModalRefs.emailInput,
    candidateModalRefs.countrySelect,
    candidateModalRefs.phoneInput,
    candidateModalRefs.linkedinInput
  ].forEach(input => input?.classList.remove('input-error'));
}

async function handleCandidateSubmit() {
  if (!candidateModalRefs.form || !candidateModalRefs.submitBtn) return;
  hideFormError();
  hideDuplicateWarning();
  clearInputErrors();

  const formValues = gatherCandidateFormValues();
  const validationMsg = validateCandidateForm(formValues);
  if (validationMsg) {
    showFormError(validationMsg);
    return;
  }

  const duplicate = findDuplicateCandidate(formValues);
  if (duplicate) {
    await showDuplicateWarning(duplicate);
    return;
  }

  await submitCandidate(formValues);
}

function gatherCandidateFormValues() {
  const name = candidateModalRefs.nameInput?.value.trim() || '';
  const email = candidateModalRefs.emailInput?.value.trim() || '';
  const country = candidateModalRefs.countrySelect?.value || '';
  const phoneCountry = candidateModalRefs.phoneCodeSelect?.value || DEFAULT_PHONE_COUNTRY;
  const phoneCode = PHONE_CODE_BY_COUNTRY[phoneCountry] || '';
  const rawPhone = candidateModalRefs.phoneInput?.value || '';
  const linkedinRawInput = candidateModalRefs.linkedinInput?.value || '';
  const linkedinRaw = linkedinRawInput.trim();

  const phoneDigits = normalizePhoneDigits(rawPhone, phoneCode);
  const linkedinForSubmit = formatLinkedinForSubmit(linkedinRaw);
  const normalizedLinkedin = normalizeLinkedin(linkedinForSubmit);

  return {
    name,
    email,
    country,
    phoneCountry,
    phoneCode,
    rawPhone,
    phoneDigits,
    linkedinRaw,
    normalizedLinkedin,
    linkedinForSubmit
  };
}

function validateCandidateForm(values) {
  let error = '';
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!values.email || !emailRegex.test(values.email)) {
    error = 'Enter a valid email address.';
    candidateModalRefs.emailInput?.classList.add('input-error');
  }

  if (!values.phoneDigits) {
    error = error || 'Enter a valid phone number.';
    candidateModalRefs.phoneInput?.classList.add('input-error');
  }

  if (!values.normalizedLinkedin.includes('linkedin.com')) {
    error = error || 'LinkedIn URL must point to linkedin.com.';
    candidateModalRefs.linkedinInput?.classList.add('input-error');
  }

  return error;
}

function showFormError(message) {
  if (!candidateModalRefs.errorBox) return;
  candidateModalRefs.errorBox.textContent = message;
  candidateModalRefs.errorBox.hidden = false;
}

function hideFormError() {
  if (candidateModalRefs.errorBox) candidateModalRefs.errorBox.hidden = true;
}

async function showDuplicateWarning(match) {
  candidateState.duplicateMatch = match.candidate;
  if (!candidateModalRefs.duplicateBox || !candidateModalRefs.duplicateFields) return;

  candidateModalRefs.duplicateBox.hidden = false;
  candidateModalRefs.duplicateFields.textContent = 'Loading candidate information…';

  const details = await resolveDuplicateDetails(match.candidate.candidate_id);
  const merged = Object.assign({}, match.candidate, details || {});
  renderDuplicateFields(merged, match.fields);
}

function hideDuplicateWarning() {
  if (candidateModalRefs.duplicateBox) candidateModalRefs.duplicateBox.hidden = true;
  candidateState.duplicateMatch = null;
}

async function resolveDuplicateDetails(candidateId) {
  if (!candidateId) return null;
  if (candidateState.duplicateDetailsCache.has(candidateId)) {
    return candidateState.duplicateDetailsCache.get(candidateId);
  }
  try {
    const res = await fetch(`${API_BASE}/candidates/${candidateId}`, { cache: 'no-store' });
    if (!res.ok) return null;
    const data = await res.json();
    candidateState.duplicateDetailsCache.set(candidateId, data);
    return data;
  } catch {
    return null;
  }
}

function renderDuplicateFields(candidate, fieldsUsed = []) {
  if (!candidateModalRefs.duplicateFields) return;
  const fragment = document.createDocumentFragment();

  if (fieldsUsed.length) {
    const matchLine = document.createElement('div');
    matchLine.textContent = `Matched on: ${fieldsUsed.join(', ')}`;
    fragment.appendChild(matchLine);
  }

  const infoLines = [];
  if (candidate.name) infoLines.push(`Name: ${candidate.name}`);
  if (candidate.email) infoLines.push(`Email: ${candidate.email}`);
  if (candidate.phone) infoLines.push(`Phone: ${candidate.phone}`);
  if (candidate.linkedin) infoLines.push(`LinkedIn: ${candidate.linkedin}`);

  infoLines.forEach(line => {
    const div = document.createElement('div');
    div.textContent = line;
    fragment.appendChild(div);
  });

  candidateModalRefs.duplicateFields.innerHTML = '';
  candidateModalRefs.duplicateFields.appendChild(fragment);
}

function findDuplicateCandidate(values) {
  if (!Array.isArray(candidateState.data) || !candidateState.data.length) return null;
  const normalizedName = normalizeName(values.name);
  const phoneDigits = values.phoneDigits;
  const linkedinNormalized = values.normalizedLinkedin;

  for (const candidate of candidateState.data) {
    const duplicates = [];
    if (normalizedName && normalizeName(candidate.name) === normalizedName) {
      duplicates.push('name');
    }

    const existingPhone = normalizeStoredPhone(candidate.phone, candidate.country);
    if (phoneDigits && existingPhone && phoneDigits === existingPhone) {
      duplicates.push('phone');
    }

    if (linkedinNormalized && normalizeLinkedin(candidate.linkedin) === linkedinNormalized) {
      duplicates.push('linkedin');
    }

    if (duplicates.length) {
      return { candidate, fields: duplicates };
    }
  }

  return null;
}

function normalizeName(name) {
  return (name || '').toString().trim().toLowerCase();
}

function normalizeLinkedin(url) {
  if (!url) return '';
  let clean = url.trim().toLowerCase();
  clean = clean.replace(/\s+/g, ' ');
  clean = clean.replace(/\/+$/, '');
  clean = clean.trim();
  return clean;
}

function formatLinkedinForSubmit(url) {
  if (!url) return '';
  let clean = url.trim();
  if (!/^https?:\/\//i.test(clean)) {
    clean = `https://${clean.replace(/^\/+/, '')}`;
  }
  return clean;
}

function normalizePhoneDigits(rawPhone, phoneCode) {
  const digits = (rawPhone || '').replace(/\D/g, '');
  if (!digits) return '';
  const code = (phoneCode || '').replace(/\D/g, '');
  if (code && !digits.startsWith(code)) {
    return code + digits;
  }
  return digits;
}

function normalizeStoredPhone(phone, country) {
  const digits = (phone || '').toString().replace(/\D/g, '');
  if (!digits) return '';
  const code = PHONE_CODE_BY_COUNTRY[country] || '';
  if (code && !digits.startsWith(code) && digits.length <= 11) {
    return code + digits;
  }
  return digits;
}

function renderPhoneCountryOptions() {
  if (!candidateModalRefs.phoneCodeSelect) return;
  const fragment = document.createDocumentFragment();
  COUNTRY_NAMES.forEach(country => {
    const option = document.createElement('option');
    option.value = country;
    option.dataset.code = PHONE_CODE_BY_COUNTRY[country];
    option.textContent = `${getCountryLabel(country)} +${PHONE_CODE_BY_COUNTRY[country]}`;
    fragment.appendChild(option);
  });
  candidateModalRefs.phoneCodeSelect.innerHTML = '';
  candidateModalRefs.phoneCodeSelect.appendChild(fragment);
  candidateModalRefs.phoneCodeSelect.value = DEFAULT_PHONE_COUNTRY;
}

function renderCountrySelectOptions(searchValue = '') {
  if (!candidateModalRefs.countryOptionsList) return;
  const normalizedTerm = (searchValue || '').trim().toLowerCase();
  const currentValue = candidateModalRefs.countrySelect?.value || '';
  let matches = normalizedTerm
    ? COUNTRY_NAMES.filter(country => country.toLowerCase().includes(normalizedTerm))
    : COUNTRY_NAMES.slice();
  if (currentValue && normalizedTerm && !matches.includes(currentValue)) {
    matches = [currentValue, ...matches];
  }

  const fragment = document.createDocumentFragment();
  const clearButton = document.createElement('button');
  clearButton.type = 'button';
  clearButton.className = 'searchable-select__option';
  clearButton.textContent = '— No country —';
  clearButton.setAttribute('role', 'option');
  if (!currentValue) {
    clearButton.setAttribute('aria-selected', 'true');
  }
  clearButton.addEventListener('click', () => handleCountrySelection(''));
  fragment.appendChild(clearButton);

  if (!matches.length) {
    const emptyDiv = document.createElement('div');
    emptyDiv.className = 'searchable-select__empty';
    emptyDiv.textContent = 'No countries match';
    fragment.appendChild(emptyDiv);
  } else {
    matches.forEach(country => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'searchable-select__option';
      button.textContent = getCountryLabel(country);
      button.setAttribute('role', 'option');
      if (country === currentValue) {
        button.setAttribute('aria-selected', 'true');
      }
      button.addEventListener('click', () => handleCountrySelection(country));
      fragment.appendChild(button);
    });
  }

  candidateModalRefs.countryOptionsList.innerHTML = '';
  candidateModalRefs.countryOptionsList.appendChild(fragment);
}

function getCountryLabel(country) {
  const flag = COUNTRY_FLAG_BY_NAME[country];
  return flag ? `${flag} ${country}` : country;
}

function syncPhoneCountryToSelected(country) {
  if (!country || !candidateModalRefs.phoneCodeSelect) return;
  if (!COUNTRY_NAMES.includes(country)) return;
  candidateModalRefs.phoneCodeSelect.value = country;
}

function handleCountrySelection(country) {
  if (!candidateModalRefs.countrySelect) return;
  candidateModalRefs.countrySelect.value = country || '';
  updateCountryDisplay(country);
  if (country) {
    syncPhoneCountryToSelected(country);
  } else if (candidateModalRefs.phoneCodeSelect) {
    candidateModalRefs.phoneCodeSelect.value = DEFAULT_PHONE_COUNTRY;
  }
  closeCountryDropdown();
}

function renderNativeCountryOptions() {
  if (!candidateModalRefs.countrySelect) return;
  const fragment = document.createDocumentFragment();
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = 'Select country…';
  fragment.appendChild(placeholder);

  COUNTRY_NAMES.forEach(country => {
    const option = document.createElement('option');
    option.value = country;
    option.textContent = getCountryLabel(country);
    fragment.appendChild(option);
  });

  candidateModalRefs.countrySelect.innerHTML = '';
  candidateModalRefs.countrySelect.appendChild(fragment);
}

function updateCountryDisplay(country) {
  if (!candidateModalRefs.countryDisplayButton) return;
  candidateModalRefs.countryDisplayButton.textContent = country ? getCountryLabel(country) : 'Select country…';
}

function openCountryDropdown() {
  if (!candidateModalRefs.countryDropdown) return;
  candidateModalRefs.countryDropdown.hidden = false;
  candidateModalRefs.countryDisplayButton?.setAttribute('aria-expanded', 'true');
  if (candidateModalRefs.countrySearchInput) {
    candidateModalRefs.countrySearchInput.value = '';
    candidateModalRefs.countrySearchInput.focus();
  }
  renderCountrySelectOptions('');
}

function closeCountryDropdown() {
  if (!candidateModalRefs.countryDropdown) return;
  candidateModalRefs.countryDropdown.hidden = true;
  candidateModalRefs.countryDisplayButton?.setAttribute('aria-expanded', 'false');
}

function toggleCountryDropdown() {
  if (!candidateModalRefs.countryDropdown) return;
  if (candidateModalRefs.countryDropdown.hidden) {
    openCountryDropdown();
  } else {
    closeCountryDropdown();
  }
}

async function submitCandidate(values) {
  const payload = {
    name: values.name || null,
    email: values.email,
    phone: values.phoneDigits,
    linkedin: values.linkedinForSubmit,
    country: values.country || null,
    stage: 'Contactado',
    created_by: localStorage.getItem('user_email')
  };

  candidateModalRefs.submitBtn.disabled = true;
  candidateModalRefs.submitBtn.textContent = 'Creating...';

  try {
    const res = await fetch(`${API_BASE}/candidates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Failed to create candidate');

    closeCandidateModal();
    showCandidateToast('Candidate created');
    await loadCandidates({ loaderMessage: 'Refreshing candidates…' });
  } catch (err) {
    console.error('❌ Error creating candidate:', err);
    showFormError(err.message || 'Failed to create candidate');
  } finally {
    candidateModalRefs.submitBtn.disabled = false;
    candidateModalRefs.submitBtn.textContent = 'Create Candidate';
  }
}

function showCandidateToast(message) {
  if (!candidateModalRefs.toast) return;
  candidateModalRefs.toast.textContent = message;
  candidateModalRefs.toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    if (candidateModalRefs.toast) candidateModalRefs.toast.hidden = true;
  }, 3200);
}

/* =========================================================================
   Column filters (tipo Excel) — Global (usado por UI existente)
   ====================================================================== */
function createColumnFilter(columnIndex, table) {
  // Cierra cualquier dropdown anterior
  document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());

  // Normaliza valores y deduplica
  const columnData = table
    .column(columnIndex)
    .data()
    .toArray()
    .map(item => (item || '').toString().trim())
    .filter((v, i, a) => v && a.indexOf(v) === i)
    .sort();

  // Contenedor del dropdown
  const container = document.createElement('div');
  container.classList.add('filter-dropdown');

  // Buscador local dentro del dropdown
  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.placeholder = 'Search...';
  container.appendChild(searchInput);

  // Lista de checks
  const checkboxContainer = document.createElement('div');
  checkboxContainer.classList.add('checkbox-list');

  columnData.forEach(value => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    // Limpia HTML si la celda venía con tags
    checkbox.value = value.replace(/<[^>]*>/g, '');
    label.appendChild(checkbox);
    label.append(' ' + checkbox.value);
    checkboxContainer.appendChild(label);
  });

  container.appendChild(checkboxContainer);

  // Monta el dropdown sobre el TH correspondiente
  const headerCell = document.querySelectorAll(`#candidatesTable thead th`)[columnIndex];
  if (headerCell) headerCell.appendChild(container);

  // Filtro de texto dentro del dropdown
  searchInput.addEventListener('input', () => {
    const searchTerm = searchInput.value.toLowerCase();
    checkboxContainer.querySelectorAll('label').forEach(label => {
      const text = label.textContent.toLowerCase();
      label.style.display = text.includes(searchTerm) ? 'block' : 'none';
    });
  });

  // Aplica filtro a DataTables (OR con regex por valores seleccionados)
  checkboxContainer.addEventListener('change', () => {
    const selected = Array.from(checkboxContainer.querySelectorAll('input:checked')).map(c => c.value);
    table.column(columnIndex).search(selected.length ? selected.join('|') : '', true, false).draw();
  });
}

// Cierra dropdown si se hace clic fuera
document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});
function installAdvancedFilters(table) {
  const statusSel = document.getElementById('statusFilter');
  const modelSel  = document.getElementById('modelFilter');

  if (!statusSel && !modelSel) return;

  // Filtro custom usando los data-attrs del <tr>
  $.fn.dataTable.ext.search.push((settings, data, dataIndex) => {
    if (settings.nTable !== document.getElementById('candidatesTable')) return true;

    const tr      = table.row(dataIndex).node();
    const rStatus = (tr?.dataset?.status || '').toLowerCase();   // 'active'|'unhired'|''
    const rModel  = (tr?.dataset?.model  || '');                  // 'Recruiting'|'Staffing'|''

    const wantStatus = (statusSel?.value || '').toLowerCase();    // '', 'active', 'unhired'
    const wantModel  = (modelSel?.value  || '');                  // '', 'Recruiting', 'Staffing'

    const passStatus = !wantStatus || rStatus === wantStatus;
    const passModel  = !wantModel  || rModel  === wantModel;

    return passStatus && passModel;
  });

  const redraw = () => $('#candidatesTable').DataTable().draw();

  statusSel?.addEventListener('change', redraw);
  modelSel?.addEventListener('change', redraw);
}
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
/* =========================================================================
   Profile
   ====================================================================== */
async function initSidebarProfileCandidates(){
  // helpers
  function initialsFromName(name = "") {
    const parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "—";
    const a = (parts[0]?.[0] || "").toUpperCase();
    const b = (parts[1]?.[0] || "").toUpperCase();
    return (a + b) || a || "—";
  }

  function initialsFromEmail(email = "") {
    const local = String(email).split("@")[0] || "";
    if (!local) return "—";
    const bits = local.split(/[._-]+/).filter(Boolean);
    return (bits.length >= 2)
      ? (bits[0][0] + bits[1][0]).toUpperCase()
      : local.slice(0, 2).toUpperCase();
  }

  let tile = document.getElementById("sidebarProfile");
  const sidebar = document.querySelector(".sidebar");

  // Crear el bloque del profile si no existe todavía
  if (!tile && sidebar) {
    sidebar.insertAdjacentHTML(
      "beforeend",
      `
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
    `
    );
    tile = document.getElementById("sidebarProfile");
  }

  if (!tile) return;

  const $init   = document.getElementById("profileAvatarInitials");
  const $name   = document.getElementById("profileName");
  const $emailE = document.getElementById("profileEmail");
  const $img    = document.getElementById("profileAvatarImg");

  // Nunca mostrar foto
  if ($img) {
    $img.removeAttribute("src");
    $img.style.display = "none";
  }

  // Nunca mostrar email (igual que en main)
  if ($emailE) {
    $emailE.textContent = "";
    $emailE.style.display = "none";
  }

  // Resolver uid igual que en main
  let uid = null;
  try {
    uid = (typeof window.getCurrentUserId === "function")
      ? (await window.getCurrentUserId())
      : (Number(localStorage.getItem("user_id")) || null);
  } catch {
    uid = Number(localStorage.getItem("user_id")) || null;
  }

  // Link al profile con user_id
  const base = "profile.html";
  tile.href = uid != null ? `${base}?user_id=${encodeURIComponent(uid)}` : base;

  // Iniciales rápidas con el email mientras carga
  const email = (localStorage.getItem("user_email") || sessionStorage.getItem("user_email") || "").toLowerCase();
  if ($init) $init.textContent = initialsFromEmail(email);

  // Intentar /users/<uid>, fallback a /profile/me
  let user = null;
  try {
    if (uid != null) {
      const r = await fetch(
        `${API_BASE}/users/${encodeURIComponent(uid)}?user_id=${encodeURIComponent(uid)}`,
        { credentials: "include" }
      );
      if (r.ok) user = await r.json();
      else console.debug("[sidebar CRM] /users/<uid> failed:", r.status);
    }
    if (!user) {
      const r2 = await fetch(
        `${API_BASE}/profile/me${uid != null ? `?user_id=${encodeURIComponent(uid)}` : ""}`,
        { credentials: "include" }
      );
      if (r2.ok) user = await r2.json();
      else console.debug("[sidebar CRM] /profile/me failed:", r2.status);
    }
  } catch (e) {
    console.debug("[sidebar CRM] fetch error:", e);
  }

  const userName = user?.user_name || "";
  if (userName) {
    if ($name) $name.textContent = userName;            // ← muestra el nombre
    if ($init) $init.textContent = initialsFromName(userName); // ← iniciales del nombre
  } else {
    if ($name) $name.textContent = "Profile"; // fallback
  }

  // Aseguramos que se vea
  const cs = window.getComputedStyle(tile);
  if (cs.display === "none") tile.style.display = "flex";
}

// Mantener este listener tal cual
document.addEventListener("DOMContentLoaded", initSidebarProfileCandidates);

/* =========================================================================
   Helpers — hire condition resolution (kept public names)
   ====================================================================== */

/**
 * Recorre filas y sincroniza la condición (active/inactive/unhired) contra la API.
 * Limita concurrencia para no saturar la red y, si existe DataTables,
 * actualiza su celda (col 0) para mantener búsquedas/ordenamientos consistentes.
 */
async function kickoffConditionResolve(tableInstance) {
  const rows  = Array.from(document.querySelectorAll('#candidatesTableBody tr'));
  const tasks = rows.map(tr => async () => {
    const id   = tr.dataset.id;
    const cell = tr.querySelector('.condition-cell');
    if (!id || !cell) return;

    try {
      const hire  = await fetchHireDates(id);
      const start = hire?.start_date || hire?.[0]?.start_date || null;
      const end   = hire?.end_date   || hire?.[0]?.end_date   || null;

      const condition = !start ? 'unhired' : (end ? 'inactive' : 'active');
      renderCondition(cell, condition);

      // sincroniza DataTables si está disponible
      if (tableInstance) {
        const rowIdx = tableInstance.row(tr).index();
        if (rowIdx != null && rowIdx >= 0) {
          tableInstance.cell(rowIdx, 0).data(cell.innerHTML);
        }
      }
    } catch {
      renderCondition(cell, 'unhired');
    }
  });

  await runWithConcurrency(tasks, 8);
}

/** GET /candidates/:id/hire — devuelve { start_date, end_date } o []/{} */
async function fetchHireDates(candidateId) {
  try {
    const r = await fetch(`${API_BASE}/candidates/${candidateId}/hire`, { method: 'GET' });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

/** Renderiza chip de estado en la celda dada */
function renderCondition(cell, condition) {
  const cls = {
    active:   'status-active',
    inactive: 'status-inactive',
    unhired:  'status-unhired'
  }[condition] || 'status-unhired';

  cell.innerHTML = `<span class="status-chip ${cls}">${condition}</span>`;
}

/** Ejecuta tareas async con límite de concurrencia */
async function runWithConcurrency(tasks, limit = 8) {
  let i = 0;
  const workers = new Array(limit).fill(0).map(async () => {
    while (i < tasks.length) {
      const t = tasks[i++];
      // protege contra fallas aisladas
      try { await t(); } catch {}
    }
  });
  await Promise.all(workers);
}
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
