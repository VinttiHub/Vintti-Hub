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
document.addEventListener('DOMContentLoaded', () => {
document.body.style.backgroundColor = 'var(--bg)';

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
  if (!id) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}`)
    .then(res => res.json())
    .then(data => {
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
  // Guardar Pain Points al hacer blur
  const painPointsTextarea = document.getElementById('pain-points');
  if (painPointsTextarea) {
    painPointsTextarea.addEventListener('blur', () => {
      const value = painPointsTextarea.value.trim();
      const accountId = getIdFromURL();
      if (!accountId) return;

      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pain_points: value })
      })
      .then(res => {
        if (!res.ok) throw new Error('Error updating pain points');
        console.log('Pain Points updated');
      })
      .catch(err => {
        console.error('Failed to update Pain Points:', err);
      });
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

  const commentsTextarea = document.getElementById('comments');
  if (commentsTextarea) commentsTextarea.value = data.comments || '';

  const painPointsTextarea = document.getElementById('pain-points');
  if (painPointsTextarea) painPointsTextarea.value = data.pain_points || '';

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
    row.innerHTML = `
      <td>${opp.opp_position_name || '—'}</td>
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

function loadCandidates(accountId) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities/candidates`)
    .then(res => res.json())
    .then(data => {
      console.log("Candidates asociados:", data);
      fillEmployeesTables(data);
    })
    .catch(err => {
      console.error("Error cargando candidates asociados:", err);
    });
}

function fillEmployeesTables(candidates) {
  const staffingTableBody   = document.querySelector('#employees .card:nth-of-type(1) tbody');
  const recruitingTableBody = document.querySelector('#employees .card:nth-of-type(2) tbody');

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
      row.innerHTML = `
        <td>${renderStatusChip((candidate.status ?? (candidate.end_date ? 'inactive' : 'active')))}</td>
        <td>
          <a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">
            ${candidate.name || '—'} ${blacklistIndicator}
          </a>
        </td>
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
  endInputS.addEventListener('change', () => {
    const candidateId = endInputS.dataset.candidateId;
    const oppId = endInputS.dataset.opportunityId;
    const newValue = endInputS.value || '';
    const patchValue = newValue || null;
    const prevValue = endInputS.dataset.previousEndDate || '';
    const shouldNotify = !prevValue && !!newValue;
    const accountName = getCurrentAccountName() || candidate.client_name || candidate.account_name || '';
    const updatePromise = updateCandidateField(candidateId, 'end_date', patchValue, oppId) || Promise.resolve();

    updatePromise.then(() => {
      if (shouldNotify) {
        notifyCandidateInactiveEmail({
          candidateId,
          candidateName: candidate.name,
          clientName: accountName,
          roleName: candidate.opp_position_name,
          endDate: newValue,
          opportunityId: oppId
        });
      }
    }).finally(() => {
      endInputS.dataset.previousEndDate = newValue;
    });
  });
}

      staffingTableBody.appendChild(row);
      hasStaffing = true;
    }

    // ---------- RECRUITING ----------
    else if (candidate.opp_model === 'Recruiting') {
      const probation =
        candidate.probation_days ??
        candidate.probation ??
        candidate.probation_days_recruiting ?? '—';

      const revenueRecruit =
        (candidate.employee_revenue_recruiting ??
         candidate.employee_revenue ??
         '—');

      const referralVal =
        (candidate.referral ??
         candidate.referral_dolar ??
         '—');

      const referralRange =
        candidate.referral_daterange
          ? candidate.referral_daterange
              .replace('[','').replace(']','')
              .split(',').map(d => d.trim()).join(' - ')
          : '—';

      const row = document.createElement('tr');
      const isBlacklisted = Boolean(candidate.is_blacklisted);
      const blacklistIndicator = isBlacklisted
        ? `<span class="blacklist-indicator" role="img" aria-label="Blacklisted candidate" title="Blacklisted candidate">⚠️</span>`
        : '';
      row.innerHTML = `
        <td>${renderStatusChip((candidate.status ?? (candidate.end_date ? 'inactive' : 'active')))}</td>
        <td>
          <a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">
            ${candidate.name || '—'} ${blacklistIndicator}
          </a>
        </td>
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
        <td>${(candidate.probation_days ?? candidate.probation ?? candidate.probation_days_recruiting ?? '—')}</td>
        <td>$${candidate.employee_salary ?? '—'}</td>
        <td>$${(candidate.employee_revenue_recruiting ?? candidate.employee_revenue ?? '—')}</td>

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
      `;
      if (isBlacklisted) {
        row.classList.add('blacklisted-row');
        row.style.backgroundColor = '#ffeaea';
      }
      // Recruiting: guardar referral $
      const refRecInput = row.querySelector('.ref-rec-input');
      if (refRecInput) {
        refRecInput.addEventListener('blur', () => {
          const candidateId = refRecInput.dataset.candidateId;
          const oppId = refRecInput.dataset.opportunityId;
          const value = refRecInput.value;
          updateCandidateField(candidateId, 'referral_dolar', value, oppId);
        });
      }

      // Recruiting: referral date range
      const refRecPickerInput = row.querySelector('.ref-rec-range-picker');
      if (refRecPickerInput) {
        const rr = candidate.referral_daterange;
        let startDateR = null, endDateR = null;
        if (rr && rr.includes(',')) {
          const [s,e] = rr.replace('[','').replace(']','').split(',').map(d => d.trim());
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
              const oppId = refRecPickerInput.dataset.opportunityId;
              if (!candidateId) return;
              const start = date1.format('YYYY-MM-DD');
              const end   = date2.format('YYYY-MM-DD');
              updateCandidateField(candidateId, 'referral_daterange', `[${start},${end}]`, oppId);
            });
          }
        };
        if (startDateR && endDateR) { options.startDate = startDateR; options.endDate = endDateR; }
        new Litepicker(options);
      }
// === Start/End date (hire_opportunity) ===
const startInput = row.querySelector('.start-date-input');
if (startInput) {
  startInput.addEventListener('change', () => {
    const candidateId = startInput.dataset.candidateId;
    const oppId = startInput.dataset.opportunityId;
    updateCandidateField(candidateId, 'start_date', startInput.value || null, oppId);
  });
}

const endInput = row.querySelector('.end-date-input');
if (endInput) {
  endInput.addEventListener('change', () => {
    const candidateId = endInput.dataset.candidateId;
    const oppId = endInput.dataset.opportunityId;
    const newValue = endInput.value || '';
    const patchValue = newValue || null;
    const prevValue = endInput.dataset.previousEndDate || '';
    const shouldNotify = !prevValue && !!newValue;
    const accountName = getCurrentAccountName() || candidate.client_name || candidate.account_name || '';
    const updatePromise = updateCandidateField(candidateId, 'end_date', patchValue, oppId) || Promise.resolve();

    updatePromise.then(() => {
      if (shouldNotify) {
        notifyCandidateInactiveEmail({
          candidateId,
          candidateName: candidate.name,
          clientName: accountName,
          roleName: candidate.opp_position_name,
          endDate: newValue,
          opportunityId: oppId
        });
      }
    }).finally(() => {
      endInput.dataset.previousEndDate = newValue;
    });
  });
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

  // ------- Alertas de Discount (solo Staffing) -------
  const alertDiv        = document.getElementById("discount-alert");
  const discountCountEl = document.getElementById("discount-count");
  const discountListEl  = document.getElementById("discount-list");

  const discountCandidates = candidates.filter(c => {
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
  if (hasStaffing && !hasRecruiting) {
    contractType = 'Staffing';
  } else if (!hasStaffing && hasRecruiting) {
    contractType = 'Recruiting';
  } else if (hasStaffing && hasRecruiting) {
    contractType = 'Mix';
  }

  const contractField = Array.from(document.querySelectorAll('#overview .accordion-content p'))
    .find(p => p.textContent.includes('Contract:'));
  if (contractField) {
    contractField.innerHTML = `<strong>Contract:</strong> ${contractType}`;
  }

  const accountId = getIdFromURL();
  if (accountId && contractType !== '—') {
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contract: contractType })
    })
    .then(res => {
      if (!res.ok) throw new Error('Error updating contract');
      console.log('✅ Contract updated to:', contractType);
    })
    .catch(err => console.error('❌ Error updating contract:', err));
  }
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

function updateCandidateField(candidateId, field, value, opportunityId) {
  const hireFields = new Set([
    'discount_dolar','discount_daterange',
    'referral_dolar','referral_daterange',
    'buyout_dolar','buyout_daterange',
    'start_date','end_date'
  ]);

  if (hireFields.has(field)) {
    const payloadValue = field.endsWith('_dolar')
      ? parseFloat(String(value).replace(/[^\d.]/g, ''))
      : value;

    if (field.endsWith('_dolar') && isNaN(payloadValue)) return;

    // ✅ opportunity_id obligatorio para tu backend
    const body = { [field]: payloadValue, opportunity_id: opportunityId };

    // Si por alguna razón no viene, mejor loguearlo (para no mandar 400 silencioso)
    if (!opportunityId) {
      console.error('Missing opportunity_id for hire field update:', { candidateId, field, value });
      return Promise.resolve();
    }

    return fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    .then(res => {
      if (!res.ok) throw new Error(`Error saving ${field} (hire_opportunity)`);
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

const INACTIVE_EMAIL_TO = ('lara@vintti.com', 'angie@vintti.com');
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

  const contextLines = [
    clientName ? `Client: ${clientName}` : '',
    roleName ? `Role: ${roleName}` : '',
    opportunityId ? `Opportunity ID: ${opportunityId}` : ''
  ].filter(Boolean);

  const bodyLines = [
'Hi Lara,',
'',
`${displayName} has just been marked as inactive.`,
`End date: ${endDate}`,
...contextLines,
'',
'Please proceed with billing adjustments and coordinate the laptop pickup.',
'',
'Thanks,',
'Vintti Hub'
  ].filter(Boolean);

  return fetch(SEND_EMAIL_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      to: [INACTIVE_EMAIL_TO],
      subject,
      body: bodyLines.join('\n')
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
function isRealISODate(v) {
  if (!v) return false;
  const s = String(v).trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(s);
}
function fmtISODate(v) {
  // devuelve vacío si no hay fecha real
  return isRealISODate(v) ? new Date(v).toLocaleDateString('en-US') : '';
}
