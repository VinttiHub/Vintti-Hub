
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

const toggleSidebarButton = document.getElementById("sidebarToggleUnique");
const sidebar = document.querySelector(".sidebar");
const mainContent = document.querySelector(".main-content");

if (toggleSidebarButton && sidebar && mainContent) {
  toggleSidebarButton.addEventListener("click", () => {
    const isHidden = sidebar.classList.toggle("custom-sidebar-hidden");
    mainContent.classList.toggle("custom-main-expanded", isHidden);

    const icon = toggleSidebarButton.querySelector("i");
    if (icon) {
      icon.classList.toggle("fa-chevron-left", !isHidden);
      icon.classList.toggle("fa-chevron-right", isHidden);
    }
  });
}


document.querySelectorAll('.filter-header').forEach(header => {
  header.addEventListener('click', () => {
    const targetId = header.getAttribute('data-target');
    const target = document.getElementById(targetId);
    const icon = header.querySelector('i');

    const isHidden = target.classList.toggle('hidden');
    if (icon) {
      icon.classList.toggle('rotate-up', !isHidden);
    }
  });
});

document.querySelectorAll('.filter-header button').forEach(button => {
  button.addEventListener('click', (e) => {
    e.stopPropagation(); // evita que se dispare doble
    button.parentElement.click();
  });
});
  const toggleButton = document.getElementById('toggleFilters');
  const filtersCard = document.getElementById('filtersCard');

  var allowedHRUsers = [];

  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users')
    .then(response => response.json())
    .then(users => {
      const allowedSubstrings = ['Pilar', 'Jazmin', 'Agostina', 'Sol'];
      allowedHRUsers = users.filter(user =>
        allowedSubstrings.some(name => user.user_name.includes(name))
      );
    })
    .catch(err => console.error('Error loading HR Leads:', err));
    function generateHROptions(currentValue) {
    let html = `<option disabled ${currentValue ? '' : 'selected'}>Assign HR Lead</option>`;
    allowedHRUsers.forEach(user => {
      const selected = user.email_vintti === currentValue ? 'selected' : '';
      html += `<option value="${user.email_vintti}" ${selected}>${user.user_name}</option>`;
    });
    return html;
  }
  if (toggleButton && filtersCard) {
    toggleButton.addEventListener('click', () => {
      const isExpanded = filtersCard.classList.contains('expanded');
      filtersCard.classList.toggle('expanded', !isExpanded);
      filtersCard.classList.toggle('hidden', isExpanded);
      toggleButton.textContent = isExpanded ? 'ðŸ” Filters' : 'âŒ Close Filters';
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
    const stageOrder = [
      'Negotiating',
      'Interviewing',
      'Sourcing',
      'NDA Sent',
      'Deep Dive',
      'Close Win',
      'Closed Lost'
    ];

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
          if (opp.nda_signature_or_start_date) {
            daysAgo = calculateDaysAgo(opp.nda_signature_or_start_date);
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
                daysCell.textContent = '-';
                daysCell.removeAttribute('title');
                daysCell.classList.remove('red-cell');
                return;
              }

              // 4) Calcular días (misma fórmula que usas en Days)
              const today = new Date();
              const diffTime = today - referenceDate;
              const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1;

              // 5) Pintar valor y alerta roja si ≥ 7
              daysCell.textContent = diffDays;
              daysCell.title = `Days since sourcing: ${diffDays}`;
              if (diffDays >= 7) {
                daysCell.classList.add('red-cell');
                daysCell.innerHTML += ' ⚠️';
              } else {
                daysCell.classList.remove('red-cell');
              }
            } catch (err) {
              console.error(`Error fetching sourcing date para opp ${oppId}:`, err);
            }
          }

          tr.innerHTML = `
            <td>${getStageDropdown(opp.opp_stage, opp.opportunity_id)}</td>
            <td>${opp.client_name || ''}</td>
            <td>${opp.opp_position_name || ''}</td>
            <td>${getTypeBadge(opp.opp_type)}</td>
            <td>${opp.opp_model || ''}</td>
            <td class="sales-lead-cell">${getSalesLeadCell(opp)}</td>
            <td>
              <select class="hr-lead-dropdown" data-id="${opp.opportunity_id}">
                ${generateHROptions(opp.opp_hr_lead)}
              </select>
            </td>
            <td>
              <input type="text" class="comment-input" data-id="${opp.opportunity_id}" value="${opp.comments || ''}" />
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
            if ([0, 6, 7].includes(cellIndex)) return;
            openOpportunity(opp.opportunity_id);
          });

          tbody.appendChild(tr);
          tr.style.opacity = 1;
          tr.style.animation = 'none';
          if (opp.opp_stage === 'Sourcing') {
            const daysCell = tr.querySelector('td:last-child');
            if (typeof opp._days_since_batch === 'number') {
              daysCell.title = `Days since sourcing: ${opp._days_since_batch}`;
              if (opp._days_since_batch >= 7) {
                daysCell.classList.add('red-cell');
                daysCell.innerHTML = `${opp._days_since_batch} ⚠️`;
              } else {
                daysCell.classList.remove('red-cell');
                daysCell.textContent = opp._days_since_batch;
              }
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

  const table = $('#opportunityTable').DataTable({
  responsive: true,
  pageLength: 50,
  dom: 'lrtip',
  ordering: false,
  lengthMenu: [[50, 100, 150], [50, 100, 150]],
  columnDefs: [
    { targets: [0], width: "8%" },
    { targets: [1, 2, 3, 4, 5, 6, 8], width: "10%" },
    { targets: 7, width: "25%" },
    {
      targets: 0, // Stage column rendering
      render: function (data, type, row, meta) {
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
  targets: 5, // Sales Lead
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
  targets: 6, // HR Lead column rendering
  render: function (data, type, row, meta) {
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
    paginate: {
      first: "Primero",
      last: "Último",
      next: "Siguiente",
      previous: "Anterior"
    }
  }
});
const accountSearchInput = document.getElementById('accountSearchInput');
if (accountSearchInput) {
  accountSearchInput.addEventListener('input', () => {
    const value = accountSearchInput.value;
    table.column(1).search(value, true, false).draw(); // columna 1 = Account
  });
}

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

const filterRegistry = [];

function buildMultiFilter(containerId, options, columnIndex, displayName, filterKey) {
  const container = document.getElementById(containerId);
  const column = table.column(columnIndex);
  filterRegistry.push({ containerId, columnIndex });

  const selectToggle = document.createElement('button');
  selectToggle.className = 'select-toggle';
  selectToggle.textContent = 'Deselect All';
  container.appendChild(selectToggle);

  const checkboxWrapper = document.createElement('div');
  checkboxWrapper.classList.add('checkbox-list');
  container.appendChild(checkboxWrapper);

  options.forEach(val => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = val;
    checkbox.checked = !(val === 'Close Win' || val === 'Closed Lost'); // tu default
    label.appendChild(checkbox);
    label.append(' ' + val);
    checkboxWrapper.appendChild(label);
  });

  const headerLabel = container.parentElement.querySelector('.filter-header label');

  function setBadge(n){
    let badge = headerLabel.querySelector('.filter-count');
    if(!badge){
      badge = document.createElement('span');
      badge.className = 'filter-count';
      headerLabel.appendChild(badge);
    }
    if (!n) badge.style.display = 'none';
    else { badge.style.display = 'inline-flex'; badge.textContent = n; }
  }

  function applyFilter() {
    const cbs = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const selected = Array.from(cbs).filter(c => c.checked).map(c => c.value);
    column.search(selected.length ? selected.join('|') : '', true, false).draw();
    setBadge(selected.length);
  }

  checkboxWrapper.addEventListener('change', applyFilter);

  selectToggle.addEventListener('click', () => {
    const all = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const isDeselecting = selectToggle.textContent === 'Deselect All';
    all.forEach(cb => cb.checked = !isDeselecting);
    selectToggle.textContent = isDeselecting ? 'Select All' : 'Deselect All';
    applyFilter();
  });

  // Estado inicial
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
      const uniqueStages = [...new Set(data.map(d => d.opp_stage).filter(Boolean))];
      const uniqueSalesLeads = [...new Set(data.map(d => d.sales_lead_name).filter(Boolean))];
      const emailToNameMap = {};
allowedHRUsers.forEach(user => {
  emailToNameMap[user.email_vintti] = user.user_name;
});
const uniqueHRLeads = [...new Set(
  data.map(d => emailToNameMap[d.opp_hr_lead] || '').filter(Boolean)
)];
const uniqueAccounts = [...new Set(data.map(d => d.client_name).filter(Boolean))];


 buildMultiFilter('filterStage',     uniqueStages,     0, 'Stage',      'Stage');
 buildMultiFilter('filterSalesLead', uniqueSalesLeads, 5, 'Sales Lead', 'SalesLead');
 buildMultiFilter('filterHRLead',    uniqueHRLeads,    6, 'HR Lead',    'HRLead');

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

    if (newStage === 'Close Win') {
      openCloseWinPopup(opportunityId, e.target);
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
  if (e.target.classList.contains('hr-lead-dropdown')) {
    const oppId = e.target.dataset.id;
    const newLead = e.target.value;
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opp_hr_lead: newLead })
    });
  }
});

document.addEventListener('blur', async e => {
  if (e.target.classList.contains('comment-input')) {
    const oppId = e.target.dataset.id;
    const newComment = e.target.value;
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comments: newComment })
    });
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
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 'lara@vintti.com'];

if (summaryLink && allowedEmails.includes(currentUserEmail)) {
  summaryLink.style.display = 'block';
}




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

    const allowedPrefixes = ['Agustin', 'Lara', 'Bahia'];
    const filtered = users.filter(user =>
      allowedPrefixes.some(prefix => user.user_name.startsWith(prefix))
    );

    filtered.forEach(user => {
      const option = document.createElement('option');
      option.value = user.email_vintti;
      option.textContent = user.user_name;
      salesDropdown.appendChild(option);
    });
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
function computeDaysSinceBatch(refDateStr) {
  if (!refDateStr) return null;
  const ref = new Date(refDateStr);
  const today = new Date();
  const diffDays = Math.ceil((today - ref) / (1000 * 60 * 60 * 24)) - 1; // mismo criterio que usas
  return diffDays;
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


// Popup Close Win
function openCloseWinPopup(opportunityId, dropdownElement) {
  const popup = document.getElementById('closeWinPopup');
  popup.style.display = 'flex';

  loadCandidatesForCloseWin();

  const saveBtn = document.getElementById('saveCloseWin');
saveBtn.onclick = async () => {
  const date = document.getElementById('closeWinDate').value;
  const hireInput = document.getElementById('closeWinHireInput').value;
  const candidateId = parseInt(hireInput.split(' - ')[0], 10);

  if (!date || !candidateId) {
    alert('Please select a hire and date.');
    return;
  }

  try {
    // 1) Guardar fecha + contratado en opportunity (con logs y errores claros)
    await patchOppFields(opportunityId, {
      opp_close_date: date,
      candidato_contratado: candidateId
    });

    // 2) Asegurar la fila en hire_opportunity (tu endpoint ya es idempotente)
    const res2 = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opportunity_id: Number(opportunityId) })
    });
    if (!res2.ok) {
      const t = await res2.text();
      console.error('❌ /candidates/{id}/hire PATCH failed:', res2.status, t);
      throw new Error(`hire PATCH ${res2.status}: ${t}`);
    }

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
    const motive = document.getElementById('closeLostReason').value;

    if (!closeDate || !motive) {
      alert("Please fill in both date and reason.");
      return;
    }

    // Guardar en DB
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        opp_close_date: closeDate,
        motive_close_lost: motive
      })
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
// --- Equipments button (debajo de Opportunities Summary + visibilidad por email) ---
(() => {
  // Debe existir el link de Opportunities Summary en el menú lateral.
  const summary = document.getElementById('summaryLink');
  if (!summary) return; // Si no existe (ej. index), no creamos el botón.

  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase();
  const equipmentsAllowed = [
    'angie@vintti.com',
    'jazmin@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com'
  ];

  let eq = document.getElementById('equipmentsLink');
  if (!eq) {
    eq = document.createElement('a');
    eq.id = 'equipmentsLink';
    eq.href = 'equipments.html';
    eq.textContent = 'Equipments';

    // Usa exactamente las mismas clases/estilos del link de Opportunities Summary del menú lateral
    eq.className = summary.className;
    eq.style.display = 'none';

    // Insertar justo debajo de Opportunities Summary en el menú lateral
    summary.insertAdjacentElement('afterend', eq);
  }

  // Mostrar solo para emails permitidos
  eq.style.display = equipmentsAllowed.includes(currentUserEmail) ? '' : 'none';
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
 // === Avatares por email ===
const AVATAR_BASE = './assets/img/'; // cambia si tus imágenes viven en otra ruta
const AVATAR_BY_EMAIL = {
  'agostina@vintti.com': 'agos.png',
  'bahia@vintti.com':    'bahia.png',
  'lara@vintti.com':     'lara.png',
  'jazmin@vintti.com':   'jaz.png',
  'pilar@vintti.com':    'pilar.png',
  'agustin@vintti.com':  'agus.png'
};

function resolveAvatar(email) {
  if (!email) return null;
  const key = String(email).trim().toLowerCase();
  const filename = AVATAR_BY_EMAIL[key];
  return filename ? (AVATAR_BASE + filename) : null;
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
  if (opp.sales_lead) return String(opp.sales_lead).toLowerCase();
  const name = (opp.sales_lead_name || '').toLowerCase();
  if (name.includes('bahia'))   return 'bahia@vintti.com';
  if (name.includes('lara'))    return 'lara@vintti.com';
  if (name.includes('agustin') || name.includes('agustina')) return 'agustin@vintti.com';
  return '';
}

// Iniciales pedidas: Bahía → BL, Lara → LR, Agustín → AR
function initialsForSalesLead(key) {
  if (key.includes('bahia')   || key.includes('bahia@'))   return 'BL';
  if (key.includes('lara')    || key.includes('lara@'))    return 'LR';
  if (key.includes('agustin') || key.includes('agustina') || key.includes('agustin@')) return 'AM';
  return '--';
}

// Clase de color de la burbuja
function badgeClassForSalesLead(key) {
  if (key.includes('bahia')   || key.includes('bahia@'))   return 'bl';
  if (key.includes('lara')    || key.includes('lara@'))    return 'lr';
  if (key.includes('agustin') || key.includes('agustina') || key.includes('agustin@')) return 'am';
  return '';
}

function getSalesLeadCell(opp) {
  const email = emailForSalesLead(opp);
  const key   = (email || opp.sales_lead_name || '').toLowerCase();
  const initials = initialsForSalesLead(key);
  const bubbleCl = badgeClassForSalesLead(key);
  const avatar = resolveAvatar(email);
  const fullName = opp.sales_lead_name || ''; // escondido para filtro/orden

  const img = avatar ? `<img class="lead-avatar" src="${avatar}" alt="">` : '';
  return `
    <div class="sales-lead">
      <span class="lead-bubble ${bubbleCl}">${initials}</span>
      ${img}
      <span class="sr-only" style="display:none">${fullName}</span>
    </div>
  `;
}

function getTypeBadge(type) {
  const t = String(type || '').toLowerCase();
  if (t.startsWith('new'))         return '<span class="type-badge N">N</span>';
  if (t.startsWith('replacement')) return '<span class="type-badge R">R</span>';
  return type || '';
}
