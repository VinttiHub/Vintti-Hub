/*********************************************************************************
 * Account Details — JS
 * Goal: Organize, document, and streamline without changing names/classes/behavior
 * Notes:
 *  - All DOM ids/classes and function names used by your HTML/CSS remain the same.
 *  - Removed duplicate definitions and consolidated event wiring.
 *  - Kept legacy helpers (e.g., saveDiscountDolar, ensurePdfStyles, truncateFileName)
 *    but routed them to the canonical logic to avoid drift.
 **********************************************************************************/

/* ============================== CONSTANTS ==================================== */

/** Path to the opportunity details page (used to build links) */
const OPPORTUNITY_DETAILS_PATH = '/opportunity-detail.html';

/** Your API base */
const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';


/* ============================== NAVIGATION =================================== */

/** Safely resolve an opportunity id no matter the server shape */
function getOpportunityId(opp) {
  return opp?.opp_id ?? opp?.opportunity_id ?? opp?.id ?? opp?.oppId ?? null;
}

/** Navigate to the opportunity details (protects against missing id) */
function goToOpportunity(oppId) {
  if (!oppId) {
    console.warn('No opportunity id provided for navigation');
    return;
  }
  window.location.href = `${OPPORTUNITY_DETAILS_PATH}?id=${encodeURIComponent(oppId)}`;
}


/* =============================== UTILITIES =================================== */

/** Read "id" param from current URL */
function getIdFromURL() {
  const params = new URLSearchParams(window.location.search);
  return params.get('id');
}

/** Format a status badge (Active/Inactive) used in employees tables */
function renderStatusChip(status) {
  const s = String(status || '').toLowerCase();
  const cls = (s === 'inactive') ? 'inactive' : 'active';
  const label = cls.charAt(0).toUpperCase() + cls.slice(1);
  return `<span class="status-chip ${cls}">${label}</span>`;
}

/** Robust date formatter: accepts "YYYY-MM-DD", ISO strings, or timestamps */
function formatAnyDate(v, locale = 'en-US') {
  if (v == null) return '—';
  const s = String(v).trim();
  if (!s || /^(-{2,}|null|undefined)$/i.test(s)) return '—';

  // "YYYY-MM-DD" or "YYYY-MM-DDTHH:mm:ss..."
  const m = s.match(
    /^(\d{4})-(\d{2})-(\d{2})(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})?)?$/
  );
  if (m) {
    const [, y, mo, d] = m;
    const dt = new Date(Number(y), Number(mo) - 1, Number(d));
    return isNaN(dt.getTime()) ? '—' : dt.toLocaleDateString(locale);
  }

  // Numeric timestamp (ms or s)
  if (/^\d+$/.test(s)) {
    const n = Number(s);
    const dt = new Date(n > 1e12 ? n : n * 1000);
    return isNaN(dt.getTime()) ? '—' : dt.toLocaleDateString(locale);
  }

  // Fallback
  const dt = new Date(s);
  return isNaN(dt.getTime()) ? '—' : dt.toLocaleDateString(locale);
}

/** Keep numeric content for number inputs; prefix $ only if type !== number */
function formatDollarInput(input) {
  const raw = String(input.value || '').replace(/[^\d.]/g, '');
  if (input.type === 'number') {
    input.value = raw;
  } else {
    input.value = raw ? `$${raw}` : '';
  }
}

/** Optional filename helper (kept for compatibility) */
function truncateFileName(name, maxLen = 26) {
  if (!name) return '';
  return name.length > maxLen ? name.slice(0, maxLen - 7) + '…' + name.slice(-6) : name;
}

/** Optional style injector for PDF cards (kept; not force-invoked) */
function ensurePdfStyles() {
  if (document.getElementById('pdf-styles')) return;
  const style = document.createElement('style');
  style.id = 'pdf-styles';
  style.textContent = `
    #pdfPreviewContainer.pdf-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;align-items:start}
    .pdf-card{position:relative;background:var(--card);border:1px solid var(--border);border-radius:18px;box-shadow:0 8px 22px var(--shadow);overflow:hidden;transition:transform .15s ease, box-shadow .15s ease}
    .pdf-card:hover{transform:translateY(-2px);box-shadow:0 10px 28px var(--shadow)}
    .pdf-open-overlay{position:absolute;inset:0 0 40px 0;z-index:1}
    .pdf-thumb{width:100%;height:240px;border:none;background:#fff;display:block}
    .pdf-fallback{padding:24px;font-size:13px}
    .pdf-meta{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:linear-gradient(180deg,rgba(255,255,255,.6),rgba(0,0,0,.02));backdrop-filter:saturate(110%) blur(2px)}
    .pdf-name{max-width:65%;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-weight:600;color:var(--text);font-size:12.5px}
    .pdf-actions{display:flex;gap:8px;z-index:2}
    .open-btn{font-size:12px;padding:4px 8px;border-radius:10px;border:1px solid var(--border);background:var(--bg);text-decoration:none;color:var(--text)}
    .open-btn:hover{background:var(--accent)}
    .delete-btn{border:none;background:transparent;cursor:pointer;font-size:16px;line-height:1;opacity:.8}
    .delete-btn:hover{opacity:1;transform:scale(1.05)}
    .pdf-empty{border:1.5px dashed var(--border);border-radius:16px;padding:20px;text-align:center;color:#666;background:var(--card)}
  `;
  document.head.appendChild(style);
}


/* ============================== API WRAPPERS ================================= */

/** PATCH to /accounts/:id with a partial body */
async function patchAccount(accountId, body) {
  const res = await fetch(`${API_BASE}/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Account patch failed');
  return res.json().catch(() => ({}));
}

/** PATCH to /candidates/:id/hire for hire_opportunity fields */
async function patchCandidateHire(candidateId, body) {
  const res = await fetch(`${API_BASE}/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Candidate hire patch failed');
  return res.json().catch(() => ({}));
}

/** PATCH to /candidates/:id for standard candidate fields */
async function patchCandidate(candidateId, body) {
  const res = await fetch(`${API_BASE}/candidates/${candidateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error('Candidate patch failed');
  return res.json().catch(() => ({}));
}


/* =========================== DOMAIN SAVE HELPERS ============================= */

/**
 * Unified field updater.
 * Saves hire_opportunity fields via /candidates/:id/hire,
 * otherwise falls back to /candidates/:id
 */
function updateCandidateField(candidateId, field, value) {
  const hireFields = new Set([
    'discount_dolar', 'discount_daterange',
    'referral_dolar', 'referral_daterange',
    'buyout_dolar',   'buyout_daterange',
  ]);

  const payloadValue = field.endsWith('_dolar')
    ? parseFloat(String(value).replace(/[^\d.]/g, ''))
    : value;

  if (field.endsWith('_dolar') && isNaN(payloadValue)) return;

  const save = hireFields.has(field)
    ? patchCandidateHire(candidateId, { [field]: payloadValue })
    : patchCandidate(candidateId,     { [field]: payloadValue });

  save
    .then(() => {
      console.log(`💾 ${field} saved for candidate ${candidateId}${hireFields.has(field) ? ' (hire_opportunity)' : ''}`);
      // If buyout changed, refresh the candidates list to reflect any computed UI
      if (field.startsWith('buyout_')) {
        const accountId = getIdFromURL && getIdFromURL();
        if (accountId) loadCandidates(accountId);
      }
    })
    .catch(err => console.error('❌ Failed to save field:', err));
}

/** Legacy helper kept for compatibility; now delegates to updateCandidateField */
function saveDiscountDolar(candidateId, value) {
  updateCandidateField(candidateId, 'discount_dolar', value);
}


/* =========================== RENDER / FILL FUNCTIONS ========================= */

/** Fill overview area and wire inline edit for client name */
function fillAccountDetails(data) {
  // Replace overview lines
  document.querySelectorAll('#overview .accordion-content p').forEach(p => {
    if (p.textContent.includes('Name:')) {
      p.innerHTML = `<strong>Name:</strong> <input id="account-client-name" class="editable-input" type="text" value="${data.client_name || ''}" placeholder="Not available" />`;
      const clientNameInput = document.getElementById('account-client-name');
      if (clientNameInput) {
        clientNameInput.addEventListener('blur', () => {
          const newName = clientNameInput.value.trim();
          const accountId = getIdFromURL();
          if (!accountId || !newName) return;
          patchAccount(accountId, { client_name: newName })
            .then(() => console.log('Client name updated'))
            .catch(err => console.error('Failed to update client name:', err));
        });
      }
    } else if (p.textContent.includes('Size:')) {
      p.innerHTML = `<strong>Size:</strong> ${data.size || '—'}`;
    } else if (p.textContent.includes('Timezone:')) {
      p.innerHTML = `<strong>Timezone:</strong> ${data.timezone || '—'}`;
    } else if (p.textContent.includes('State:')) {
      p.innerHTML = `<strong>State:</strong> ${data.state || '—'}`;
    } else if (p.textContent.includes('Contract:')) {
      p.innerHTML = `<strong>Contract:</strong> ${data.contract || '—'}`;
    }
  });

  // External links
  const linkedinLink = document.getElementById('linkedin-link');
  if (linkedinLink) linkedinLink.href = data.linkedin || '#';

  const websiteLink = document.getElementById('website-link');
  if (websiteLink) websiteLink.href = data.website || '#';

  // Totals
  const tsfEl = document.getElementById('account-tsf');
  const tsrEl = document.getElementById('account-tsr');
  const trrEl = document.getElementById('account-trr');
  if (tsfEl) tsfEl.textContent = `$${data.tsf ?? 0}`;
  if (tsrEl) tsrEl.textContent = `$${data.tsr ?? 0}`;
  if (trrEl) trrEl.textContent = `$${data.trr ?? 0}`;
}

/** Build opportunities table (rows are clickable & accessible) */
function fillOpportunitiesTable(opportunities = []) {
  const tbody = document.querySelector('#overview .accordion-section:nth-of-type(2) tbody');
  if (!tbody) return;

  tbody.innerHTML = '';

  if (!Array.isArray(opportunities) || opportunities.length === 0) {
    tbody.innerHTML = `<tr><td colspan="3">No opportunities found</td></tr>`;
    return;
  }

  opportunities.forEach(opp => {
    const oppId = getOpportunityId(opp);
    const hireContent = opp.candidate_name ? opp.candidate_name : `<span class="no-hire">Not hired yet</span>`;

    const row = document.createElement('tr');

    const positionCellHTML = oppId
      ? `<a class="opp-link" href="${OPPORTUNITY_DETAILS_PATH}?id=${encodeURIComponent(oppId)}" title="Open opportunity">${opp.opp_position_name || '—'}</a>`
      : (opp.opp_position_name || '—');

    row.innerHTML = `
      <td>${positionCellHTML}</td>
      <td>${opp.opp_stage || '—'}</td>
      <td>${hireContent}</td>
    `;

    if (oppId) {
      row.classList.add('clickable-row');
      row.dataset.oppId = oppId;
      row.title = 'Open opportunity details';
      row.tabIndex = 0;

      row.addEventListener('click', (e) => {
        if (e.target.closest('a')) return;
        goToOpportunity(oppId);
      });

      row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          goToOpportunity(oppId);
        }
      });
    }

    tbody.appendChild(row);
  });
}

/** Build Staffing/Recruiting tables + alerts + contract inference/persist */
function fillEmployeesTables(candidates = []) {
  const staffingTableBody   = document.querySelector('#employees .card:nth-of-type(1) tbody');
  const recruitingTableBody = document.querySelector('#employees .card:nth-of-type(2) tbody');
  if (!staffingTableBody || !recruitingTableBody) return;

  staffingTableBody.innerHTML = '';
  recruitingTableBody.innerHTML = '';

  let hasStaffing = false;
  let hasRecruiting = false;

  if (!Array.isArray(candidates) || candidates.length === 0) {
    staffingTableBody.innerHTML   = `<tr><td colspan="15">No employees in Staffing</td></tr>`;
    recruitingTableBody.innerHTML = `<tr><td colspan="10">No employees in Recruiting</td></tr>`;
    return;
  }

  candidates.forEach(candidate => {
    /* ============================== STAFFING ============================== */
    if (candidate.opp_model === 'Staffing') {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${renderStatusChip((candidate.status ?? (candidate.end_date ? 'inactive' : 'active')))}</td>
        <td><a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">${candidate.name || '—'}</a></td>
        <td>${candidate.start_date ? new Date(candidate.start_date).toLocaleDateString('en-US') : '—'}</td>
        <td>${formatAnyDate(candidate.end_date)}</td>
        <td>${candidate.opp_position_name || '—'}</td>
        <td>$${candidate.employee_fee ?? '—'}</td>
        <td>$${candidate.employee_salary ?? '—'}</td>
        <td>$${candidate.employee_revenue ?? '—'}</td>
        <!-- Discount $ -->
        <td><input type="number" class="discount-input" placeholder="$" value="${candidate.discount_dolar || ''}" data-candidate-id="${candidate.candidate_id}" /></td>
        <!-- Discount Date Range -->
        <td><input type="text" class="month-range-picker range-chip" placeholder="Select range" readonly data-candidate-id="${candidate.candidate_id}" value="${candidate.discount_daterange?.replace('[','').replace(']','').split(',').map(d => d.trim()).join(' - ') || ''}" /></td>
        <!-- Discount Months (badge) -->
        <td></td>
        <!-- Referral $ -->
        <td><div class="currency-wrap"><input type="number" class="referral-input input-chip" placeholder="0.00" step="0.01" min="0" inputmode="decimal" value="${candidate.referral_dolar ?? ''}" data-candidate-id="${candidate.candidate_id}" /></div></td>
        <!-- Referral Date Range -->
        <td><input type="text" class="referral-range-picker range-chip" placeholder="Select range" readonly data-candidate-id="${candidate.candidate_id}" value="${candidate.referral_daterange?.replace('[','').replace(']','').split(',').map(d => d.trim()).join(' - ') || ''}" /></td>
        <!-- Buy Out $ -->
        <td><div class="currency-wrap"><input type="number" class="buyout-input input-chip" placeholder="0.00" step="0.01" min="0" inputmode="decimal" value="${candidate.buyout_dolar ?? ''}" data-candidate-id="${candidate.candidate_id}" /></div></td>
        <!-- Buy Out Month (mes & año) -->
        <td><div class="buyout-month-wrap segmented" data-candidate-id="${candidate.candidate_id}">
              <select class="buyout-month select-chip"></select>
              <select class="buyout-year  select-chip"></select>
            </div></td>
      `;

      // Discount months/badge coloring
      const monthsCell    = row.children[10];
      const dateRangeCell = row.children[9];
      const dollarCell    = row.children[8];

      if (candidate.discount_daterange && candidate.discount_daterange.includes(',')) {
        const [startStr, endStr] = candidate.discount_daterange
          .replace('[','').replace(']','').split(',').map(d => d.trim());
        const start = new Date(startStr);
        const end   = new Date(endStr);

        if (!isNaN(start.getTime()) && !isNaN(end.getTime())) {
          const months = (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth()) + 1;
          monthsCell.textContent = months;

          const now = new Date();
          const current = new Date(now.getFullYear(), now.getMonth(), 1);
          const endMonth = new Date(end.getFullYear(), end.getMonth(), 1);
          const isExpired = endMonth < current;

          const badge = document.createElement('span');
          badge.className = `badge-pill ${isExpired ? 'expired' : 'active'}`;
          badge.textContent = isExpired ? 'expired' : 'active';

          const dateInput = dateRangeCell.querySelector('.month-range-picker');
          if (dateInput && dateInput.parentElement) dateInput.parentElement.appendChild(badge);

          const paint = (bg, color, weight = 'normal') => {
            [monthsCell, dateRangeCell, dollarCell].forEach(cell => {
              cell.style.backgroundColor = bg;
              cell.style.color = color;
              cell.style.fontWeight = weight;
            });
          };
          isExpired ? paint('#fff0f0', '#b30000', '500') : paint('#f2fff2', '#006600');
        }
      }

      // Wire inputs: referral
      const referralInput = row.querySelector('.referral-input');
      if (referralInput) {
        referralInput.addEventListener('blur', () => {
          updateCandidateField(referralInput.dataset.candidateId, 'referral_dolar', referralInput.value);
        });
      }

      // Referral range picker
      const referralPickerInput = row.querySelector('.referral-range-picker');
      if (referralPickerInput) {
        let startDateR = null, endDateR = null;
        const rr = candidate.referral_daterange;
        if (rr && rr.includes(',')) {
          const [s, e] = rr.replace('[','').replace(']','').split(',').map(d => d.trim());
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
              if (!candidateId) return;
              const start = date1.format('YYYY-MM-DD');
              const end   = date2.format('YYYY-MM-DD');
              updateCandidateField(candidateId, 'referral_daterange', `[${start},${end}]`);
            });
          }
        };
        if (startDateR && endDateR) { refOptions.startDate = startDateR; refOptions.endDate = endDateR; }
        new Litepicker(refOptions);
      }

      // Buyout month/year selects + save
      const wrap = row.querySelector('.buyout-month-wrap');
      if (wrap) {
        const mSel = wrap.querySelector('.buyout-month');
        const ySel = wrap.querySelector('.buyout-year');
        const candidateId = wrap.dataset.candidateId;

        const months = ['01','02','03','04','05','06','07','08','09','10','11','12'];
        mSel.innerHTML = months.map((m,idx) =>
          `<option value="${m}">${new Date(2000, idx, 1).toLocaleString('en-US', { month:'short' })}</option>`
        ).join('');

        const nowY = new Date().getFullYear();
        const years = Array.from({ length: 9 }, (_, i) => nowY - 4 + i);
        ySel.innerHTML = years.map(y => `<option value="${y}">${y}</option>`).join('');

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
          updateCandidateField(candidateId, 'buyout_daterange', `${y}-${m}`);
        };
        mSel.addEventListener('change', saveBuyout);
        ySel.addEventListener('change', saveBuyout);

        const buyoutInput = row.querySelector('.buyout-input');
        if (buyoutInput) {
          buyoutInput.addEventListener('blur', () => {
            updateCandidateField(candidateId, 'buyout_dolar', buyoutInput.value);
          });
        }
      }

      // Discount date range picker
      const monthPickerInput = row.querySelector('.month-range-picker');
      if (monthPickerInput) {
        let startDate = null, endDate = null;
        const dr = candidate.discount_daterange;
        if (dr && dr.includes(',')) {
          const [s, e] = dr.replace('[','').replace(']','').split(',').map(d => d.trim());
          startDate = new Date(s.slice(0,7) + '-15');
          endDate   = new Date(e.slice(0,7) + '-15');
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
              if (!candidateId) return;
              const start = date1.format('YYYY-MM-DD');
              const end   = date2.format('YYYY-MM-DD');
              patchCandidateHire(candidateId, { discount_daterange: `[${start},${end}]` })
                .then(() => console.log('🟢 Discount date range updated'))
                .catch(err => console.error('❌ Error:', err));
            });
          }
        };
        if (startDate && endDate) { litepickerOptions.startDate = startDate; litepickerOptions.endDate = endDate; }
        new Litepicker(litepickerOptions);
      }

      // Discount $
      const discountInput = row.querySelector('.discount-input');
      if (discountInput) {
        discountInput.addEventListener('blur', () => {
          updateCandidateField(discountInput.dataset.candidateId, 'discount_dolar', discountInput.value);
        });
      }

      staffingTableBody.appendChild(row);
      hasStaffing = true;
    }

    /* ============================= RECRUITING ============================= */
    else if (candidate.opp_model === 'Recruiting') {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${renderStatusChip((candidate.status ?? (candidate.end_date ? 'inactive' : 'active')))}</td>
        <td><a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">${candidate.name || '—'}</a></td>
        <td>${candidate.start_date ? new Date(candidate.start_date).toLocaleDateString('en-US') : '—'}</td>
        <td>${formatAnyDate(candidate.end_date)}</td>
        <td>${candidate.opp_position_name || '—'}</td>
        <td>${(candidate.probation_days ?? candidate.probation ?? candidate.probation_days_recruiting ?? '—')}</td>
        <td>$${candidate.employee_salary ?? '—'}</td>
        <td>$${(candidate.employee_revenue_recruiting ?? candidate.employee_revenue ?? '—')}</td>
        <!-- Referral $ -->
        <td><div class="currency-wrap"><input type="number" class="ref-rec-input input-chip" placeholder="0.00" step="0.01" min="0" inputmode="decimal" value="${candidate.referral_dolar ?? ''}" data-candidate-id="${candidate.candidate_id}" /></div></td>
        <!-- Referral Date Range -->
        <td><input type="text" class="ref-rec-range-picker range-chip" placeholder="Select range" readonly data-candidate-id="${candidate.candidate_id}" value="${candidate.referral_daterange?.replace('[','').replace(']','').split(',').map(d => d.trim()).join(' - ') || ''}" /></td>
      `;

      const refRecInput = row.querySelector('.ref-rec-input');
      if (refRecInput) {
        refRecInput.addEventListener('blur', () => {
          updateCandidateField(refRecInput.dataset.candidateId, 'referral_dolar', refRecInput.value);
        });
      }

      const refRecPickerInput = row.querySelector('.ref-rec-range-picker');
      if (refRecPickerInput) {
        let startDateR = null, endDateR = null;
        const rr = candidate.referral_daterange;
        if (rr && rr.includes(',')) {
          const [s, e] = rr.replace('[','').replace(']','').split(',').map(d => d.trim());
          startDateR = new Date(s.slice(0,7) + '-15');
          endDateR   = new Date(e.slice(0,7) + '-15');
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
              const candidateId = refRecPickerInput.dataset.candidateId;
              if (!candidateId) return;
              const start = date1.format('YYYY-MM-DD');
              const end   = date2.format('YYYY-MM-DD');
              updateCandidateField(candidateId, 'referral_daterange', `[${start},${end}]`);
            });
          }
        };
        if (startDateR && endDateR) { options.startDate = startDateR; options.endDate = endDateR; }
        new Litepicker(options);
      }

      recruitingTableBody.appendChild(row);
      hasRecruiting = true;
    }
  });

  if (!hasStaffing) {
    staffingTableBody.innerHTML = `<tr><td colspan="15">No employees in Staffing</td></tr>`;
  }
  if (!hasRecruiting) {
    recruitingTableBody.innerHTML = `<tr><td colspan="10">No employees in Recruiting</td></tr>`;
  }

  /* -------- Discount alert (only non-expired Staffing discounts) -------- */
  const alertDiv        = document.getElementById('discount-alert');
  const discountCountEl = document.getElementById('discount-count');
  const discountListEl  = document.getElementById('discount-list');

  if (alertDiv && discountCountEl && discountListEl) {
    const discountCandidates = candidates.filter(c => {
      if (c.opp_model !== 'Staffing') return false;
      if (!c.discount_dolar || !c.discount_daterange || !c.discount_daterange.includes(',')) return false;

      const endStr = c.discount_daterange.match(/\d{4}-\d{2}-\d{2}/g)?.[1];
      if (!endStr) return false;

      const endDate = new Date(endStr);
      const now = new Date();
      const currentMonthStart = new Date(now.getFullYear(), now.getMonth(), 1);
      const endMonthStart = new Date(endDate.getFullYear(), endDate.getMonth(), 1);

      return endMonthStart >= currentMonthStart;
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

      alertDiv.classList.remove('hidden');
    } else {
      alertDiv.classList.add('hidden');
    }
  }

  /* ----------------------- Contract inference + save ---------------------- */
  let contractType = '—';
  if (hasStaffing && !hasRecruiting) contractType = 'Staffing';
  else if (!hasStaffing && hasRecruiting) contractType = 'Recruiting';
  else if (hasStaffing && hasRecruiting) contractType = 'Mix';

  const contractField = Array.from(document.querySelectorAll('#overview .accordion-content p'))
    .find(p => p.textContent.includes('Contract:'));
  if (contractField) contractField.innerHTML = `<strong>Contract:</strong> ${contractType}`;

  const accountId = getIdFromURL();
  if (accountId && contractType !== '—') {
    patchAccount(accountId, { contract: contractType })
      .then(() => console.log('✅ Contract updated to:', contractType))
      .catch(err => console.error('❌ Error updating contract:', err));
  }
}


/* =============================== PDF HANDLERS ================================ */

async function deletePDF(key) {
  const accountId = getIdFromURL();
  if (!accountId || !key) return;
  if (!confirm('Are you sure you want to delete this PDF?')) return;

  try {
    const res = await fetch(`${API_BASE}/accounts/${accountId}/pdfs`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key }),
    });
    if (!res.ok) throw new Error('Failed to delete PDF');
    await loadAccountPdfs(accountId);
  } catch (err) {
    console.error('Error deleting PDF:', err);
    alert('Failed to delete PDF');
  }
}

async function renamePDF(key, new_name) {
  const accountId = getIdFromURL();
  if (!accountId || !key || !new_name) return;

  const res = await fetch(`${API_BASE}/accounts/${accountId}/pdfs`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key, new_name }),
  });
  if (!res.ok) throw new Error('Failed to rename PDF');
  await loadAccountPdfs(accountId);
}

async function loadAccountPdfs(accountId) {
  try {
    const res = await fetch(`${API_BASE}/accounts/${accountId}/pdfs`);
    const pdfs = await res.json();
    renderPdfList(pdfs);
  } catch (err) {
    console.error('Error loading account PDFs:', err);
  }
}

/** Render list (row style) with rename/delete flows */
function renderPdfList(pdfs = []) {
  const container = document.getElementById('pdfPreviewContainer');
  if (!container) return;

  container.classList.add('contracts-list');
  container.innerHTML = '';

  if (!Array.isArray(pdfs) || pdfs.length === 0) {
    container.innerHTML = `
      <div class="contract-item" style="justify-content:center; color:#666;">
        📄 No contracts uploaded yet — use the Upload button.
      </div>`;
    return;
  }

  pdfs.forEach(pdf => {
    const row = document.createElement('div');
    row.className = 'contract-item';
    row.innerHTML = `
      <div class="contract-left">
        <span class="file-icon">📄</span>
        <a class="file-name" href="${pdf.url}" target="_blank" title="${pdf.name}">${pdf.name}</a>
        <input class="file-edit hidden" type="text" value="${pdf.name}" placeholder="Type a new name…" aria-label="Rename file" data-orig="${pdf.name}" />
      </div>
      <div class="contract-right">
        <button class="icon-btn rename-btn">Rename</button>
        <button class="icon-btn save-btn hidden">Save</button>
        <button class="icon-btn cancel-btn hidden">Cancel</button>
        <a class="link-btn" href="${pdf.url}" target="_blank">Open</a>
        <button class="icon-btn icon-danger delete-btn" data-key="${pdf.key}">Delete</button>
      </div>
    `;

    const nameLink  = row.querySelector('.file-name');
    const nameInput = row.querySelector('.file-edit');
    const renameBtn = row.querySelector('.rename-btn');
    const saveBtn   = row.querySelector('.save-btn');
    const cancelBtn = row.querySelector('.cancel-btn');
    const deleteBtn = row.querySelector('.delete-btn');

    const enterEdit = () => {
      nameLink.classList.add('hidden');
      renameBtn.classList.add('hidden');
      nameInput.classList.remove('hidden');
      saveBtn.classList.remove('hidden');
      cancelBtn.classList.remove('hidden');
      nameInput.value = nameInput.dataset.orig || nameLink.textContent || '';
      requestAnimationFrame(() => { nameInput.focus(); nameInput.select(); });
    };

    const exitEdit = () => {
      nameLink.classList.remove('hidden');
      renameBtn.classList.remove('hidden');
      nameInput.classList.add('hidden');
      saveBtn.classList.add('hidden');
      cancelBtn.classList.add('hidden');
    };

    nameInput.classList.add('hidden');
    renameBtn.addEventListener('click', enterEdit);
    cancelBtn.addEventListener('click', exitEdit);

    saveBtn.addEventListener('click', async () => {
      let newName = (nameInput.value || '').trim();
      if (!newName) return;
      if (!/\.pdf$/i.test(newName)) newName += '.pdf';
      newName = newName.replace(/[\/\\]/g, '-');

      try {
        nameLink.textContent = newName; // optimistic UI
        nameLink.title = newName;
        await renamePDF(pdf.key, newName);
        nameInput.dataset.orig = newName;
        exitEdit();
      } catch (e) {
        alert('Failed to rename file');
        console.error(e);
      }
    });

    nameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') saveBtn.click();
      if (e.key === 'Escape') cancelBtn.click();
    });

    deleteBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const key = deleteBtn.getAttribute('data-key');
      deletePDF(key);
    });

    container.appendChild(row);
  });
}


/* ================================ LOADERS ==================================== */

/** Fetch + render opportunities for this account */
function loadAssociatedOpportunities(accountId) {
  fetch(`${API_BASE}/accounts/${accountId}/opportunities`)
    .then(res => res.json())
    .then(data => {
      console.log('Oportunidades asociadas:', data);
      fillOpportunitiesTable(data); // render only
    })
    .catch(err => console.error('Error cargando oportunidades asociadas:', err));
}

/** Fetch + render candidates (both models) */
function loadCandidates(accountId) {
  fetch(`${API_BASE}/accounts/${accountId}/opportunities/candidates`)
    .then(res => res.json())
    .then(data => {
      console.log('Candidates asociados:', data);
      fillEmployeesTables(data);
    })
    .catch(err => console.error('Error cargando candidates asociados:', err));
}


/* ============================ INLINE LINK EDITOR ============================= */

/**
 * Small generic editor for account link fields (e.g., linkedin, website)
 * Uses: editField('linkedin') / editField('website') — same as your original API
 */
function editField(field) {
  const linkEl = document.getElementById(`${field}-link`);
  const currentLink = linkEl ? linkEl.href : '';
  const newLink = prompt(`Enter new ${field} URL:`, currentLink);
  if (!newLink) return;

  if (linkEl) linkEl.href = newLink;

  const accountId = new URLSearchParams(window.location.search).get('id');
  if (!accountId) return;

  patchAccount(accountId, { [field]: newLink })
    .then(() => console.log(`${field} updated successfully`))
    .catch(err => {
      alert('There was an error updating the link. Please try again.');
      console.error(err);
    });
}


/* =============================== BOOTSTRAP =================================== */

document.addEventListener('DOMContentLoaded', () => {
  // Soft theme background (existing classnames preserved)
  document.body.style.backgroundColor = 'var(--bg)';

  /* Tabs */
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

  /* Accordion */
  document.querySelectorAll('.accordion-header').forEach(header => {
    header.addEventListener('click', () => header.parentElement.classList.toggle('open'));
  });

  /* Go Back button */
  const goBackButton = document.getElementById('goBackButton');
  if (goBackButton) {
    goBackButton.addEventListener('click', () => {
      if (document.referrer) window.history.back();
      else window.location.href = '/';
    });
  }

  /* Discount alert close */
  const closeBtn = document.getElementById('close-discount-alert');
  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      const alertEl = document.getElementById('discount-alert');
      if (alertEl) alertEl.classList.add('hidden');
    });
  }

  /* Pain Points auto-save on blur */
  const painPointsTextarea = document.getElementById('pain-points');
  if (painPointsTextarea) {
    painPointsTextarea.addEventListener('blur', () => {
      const value = painPointsTextarea.value.trim();
      const accountId = getIdFromURL();
      if (!accountId) return;
      patchAccount(accountId, { pain_points: value })
        .then(() => console.log('Pain Points updated'))
        .catch(err => console.error('Failed to update Pain Points:', err));
    });
  }

  /* PDF upload (multi) */
  const uploadBtn = document.getElementById('uploadPdfBtn');
  const pdfInput  = document.getElementById('pdfUpload');
  if (pdfInput) pdfInput.setAttribute('multiple', 'multiple');
  if (uploadBtn && pdfInput) {
    uploadBtn.addEventListener('click', async () => {
      const files = Array.from(pdfInput.files || []).filter(f => f.type === 'application/pdf');
      if (!files.length) return alert('Please select at least one PDF.');
      const accountId = getIdFromURL();
      try {
        await Promise.all(files.map(file => {
          const formData = new FormData();
          formData.append('pdf', file);
          return fetch(`${API_BASE}/accounts/${accountId}/upload_pdf`, { method: 'POST', body: formData })
            .then(r => (r.ok ? r.json() : Promise.reject(r)));
        }));
        pdfInput.value = '';
        await loadAccountPdfs(accountId);
      } catch (err) {
        console.error('Error uploading PDFs:', err);
        alert('Upload failed');
      }
    });
  }

  /* Initial data load */
  const id = getIdFromURL();
  if (!id) return;

  fetch(`${API_BASE}/accounts/${id}`)
    .then(res => res.json())
    .then(data => {
      window.__accountDetails = data; // lightweight cache
      fillAccountDetails(data);
      loadAssociatedOpportunities(id);
      loadCandidates(id);
      loadAccountPdfs(id);
    })
    .catch(err => console.error('Error fetching accounts details:', err));
});
