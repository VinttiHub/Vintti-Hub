
document.addEventListener('DOMContentLoaded', () => {
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

    // Mueve el botón dependiendo del estado del sidebar
    toggleSidebarButton.style.left = isHidden ? '12px' : '220px';
  });
}


  document.querySelectorAll('.filter-toggle').forEach(header => {
    header.addEventListener('click', () => {
      const targetId = header.getAttribute('data-target');
      const target = document.getElementById(targetId);
      const icon = header.querySelector('i');

      target.classList.toggle('hidden');
      if (icon) {
        icon.classList.toggle('rotate-up');
      }
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

  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light')
    .then(response => response.json())
    .then(data => {
      const tbody = document.getElementById('opportunityTableBody');
      tbody.innerHTML = '';

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
      if (!grouped[stage]) grouped[stage] = [];
      grouped[stage].push(opp);
    });

    // 👇 Vaciar tbody
    tbody.innerHTML = '';

    // 👇 Insertar oportunidades en orden
    stageOrder.forEach(stage => {
      if (grouped[stage]) {
        grouped[stage].forEach(opp => {
          let daysAgo = '';
          if (opp.nda_signature_or_start_date) {
            daysAgo = calculateDaysAgo(opp.nda_signature_or_start_date);
          }

          const tr = document.createElement('tr');
          let daysSinceBatch = '-';

          async function fetchDaysSinceBatch(opp, tr) {
            const oppId = opp.opportunity_id;
            let referenceDate = null;

            try {
              const pauseRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/pause_days_since_batch`);
              const pauseData = await pauseRes.json();
              const shouldPause = pauseData.pause;

              if (shouldPause) {
                cell.textContent = '⏸️';
                cell.title = 'Paused due to recent presentation';
                return;
              }

              const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/latest_sourcing_date`);
              const result = await res.json();

              if (result.latest_sourcing_date) {
                referenceDate = new Date(result.latest_sourcing_date);
              } else if (opp.nda_signature_or_start_date) {
                referenceDate = new Date(opp.nda_signature_or_start_date);
              }

              if (referenceDate) {
                const today = new Date();
                const diffTime = today - referenceDate;
                const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1;
                const cell = tr.querySelector('td:last-child');
                if (cell) {
                  cell.textContent = diffDays;
                  if (diffDays >= 7) {
                    cell.classList.add('red-cell');
                    cell.innerHTML += ' ⚠️';
                  }
                }
              }
            } catch (err) {
              console.error(`Error fetching sourcing date para opp ${oppId}:`, err);
            }
          }

          tr.innerHTML = `
            <td>${getStageDropdown(opp.opp_stage, opp.opportunity_id)}</td>
            <td>${opp.client_name || ''}</td>
            <td>${opp.opp_position_name || ''}</td>
            <td>${opp.opp_type || ''}</td>
            <td>${opp.opp_model || ''}</td>
            <td>${opp.sales_lead_name || ''}</td>
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

          tr.style.opacity = 0;
          tbody.appendChild(tr);

          setTimeout(() => {
            tr.style.animation = 'fadeInUp 0.4s ease forwards';
          }, 100 * tbody.children.length); // delay progresivo

          if (opp.opp_stage === 'Sourcing') {
            fetchDaysSinceBatch(opp, tr);
          }
        });
      }
    });
    fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users')
      .then(response => response.json())
      .then(users => {
        const allowedSubstrings = ['Pilar', 'Jazmin', 'Agostina', 'Sol'];
        const dropdowns = document.querySelectorAll('.hr-lead-dropdown');

        dropdowns.forEach(select => {
          const currentValue = select.dataset.current;

          // Filtrar usuarios permitidos
          const filtered = users.filter(user =>
            allowedSubstrings.some(name => user.user_name.includes(name))
          );

          // Agregar opciones al dropdown
          select.innerHTML += filtered.map(user => {
            const selected = user.email_vintti === currentValue ? 'selected' : '';
            return `<option value="${user.email_vintti}" ${selected}>${user.user_name}</option>`;
          }).join('');
        });
      })
      .catch(err => {
        console.error('Error loading HR Leads:', err);
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

function buildMultiFilter(containerId, options, columnIndex) {
  const container = document.getElementById(containerId);
  const column = table.column(columnIndex);

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
    checkbox.checked = !(val === 'Close Win' || val === 'Closed Lost');

    label.appendChild(checkbox);
    label.append(' ' + val);
    checkboxWrapper.appendChild(label);
  });

  function applyFilter() {
    const checkboxes = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const selected = Array.from(checkboxes).filter(c => c.checked).map(c => c.value);
    column.search(selected.length ? selected.join('|') : '', true, false).draw();
  }

  checkboxWrapper.addEventListener('change', applyFilter);

  selectToggle.addEventListener('click', () => {
    const all = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const isDeselecting = selectToggle.textContent === 'Deselect All';

    all.forEach(cb => cb.checked = !isDeselecting);
    selectToggle.textContent = isDeselecting ? 'Select All' : 'Deselect All';
    applyFilter();
  });
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


      buildMultiFilter('filterStage', uniqueStages, 0);
      buildMultiFilter('filterSalesLead', uniqueSalesLeads, 5);
      buildMultiFilter('filterHRLead', uniqueHRLeads, 6);

    })
    .catch(err => {
      console.error('Error fetching opportunities:', err);
      const spinner = document.getElementById('spinner-overlay');
      if (spinner) spinner.classList.add('hidden');
    });
    
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
window.addEventListener('pageshow', () => {
  const tableCard = document.querySelector('.table-card');
  if (tableCard.classList.contains('exit-left')) {
    tableCard.classList.remove('exit-left');
    tableCard.style.opacity = '1';
    tableCard.style.transform = 'translateX(0)';
  }
});
const summaryLink = document.getElementById('summaryLink');
const currentUserEmail = localStorage.getItem('user_email');
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com'];

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
  const tableCard = document.querySelector('.table-card');
  tableCard.classList.add('exit-left');

  setTimeout(() => {
    window.location.href = `opportunity-detail.html?id=${id}`;
  }, 400);
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
  e.preventDefault();

  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  document.getElementById('click-sound').play();
  try {
    const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ email, password })
    });

    const data = await response.json();

    if (response.ok && data.success) {
      const nickname = data.nickname;

      // ✅ Guarda el email del usuario logueado
      localStorage.setItem('user_email', email);

      document.getElementById('personalized-greeting').textContent = `Hey ${nickname}, `;
      document.getElementById('login-container').style.display = 'none';
      document.getElementById('welcome-container').style.display = 'block';
    } else {
      alert(data.message || 'Correo o contraseña incorrectos.');
    }
  } catch (err) {
    console.error('Error en login:', err);
    alert('Ocurrió un error inesperado. Intenta de nuevo más tarde.');
  }
});

const createOpportunityForm = document.getElementById('createOpportunityForm');
const createButton = createOpportunityForm?.querySelector('.create-btn');

if (createOpportunityForm && createButton) {

  // Validación dinámica → activar o desactivar botón
  createOpportunityForm.addEventListener('input', () => {
    const clientName = createOpportunityForm.client_name.value.trim();
    const oppModel = createOpportunityForm.opp_model.value;
    const positionName = createOpportunityForm.position_name.value.trim();
    const salesLead = createOpportunityForm.sales_lead.value;
    const oppType = createOpportunityForm.opp_type.value;

    const allFilled = clientName && oppModel && positionName && salesLead && oppType;
    createButton.disabled = !allFilled;
  });

  // Validación al hacer submit
  createOpportunityForm.addEventListener('submit', async function (e) {
    e.preventDefault();

    const formData = {
      client_name: createOpportunityForm.client_name.value.trim(),
      opp_model: createOpportunityForm.opp_model.value,
      position_name: createOpportunityForm.position_name.value.trim(),
      sales_lead: createOpportunityForm.sales_lead.value,
      opp_type: createOpportunityForm.opp_type.value,
      opp_stage: 'Deep Dive'
    };

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
      return '<span class="stage-pill stage-closewin">Close Win</span>';
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

  const normalizedStage = (currentStage || '').trim();
  const isFinalStage = normalizedStage === 'Close Win' || normalizedStage === 'Closed Lost';

  let dropdown = `<select class="stage-dropdown" data-id="${opportunityId}" ${isFinalStage ? 'disabled' : ''}>`;

  stages.forEach(stage => {
    const selected = (stage === normalizedStage) ? 'selected' : '';
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
    const candidateId = hireInput.split(' - ')[0];  // Extrae solo el ID

    if (!date || !candidateId) {
      alert('Please select a hire and date.');
      return;
    }

    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        opp_close_date: date,
        candidato_contratado: parseInt(candidateId)
      })
    });

    await patchOpportunityStage(opportunityId, 'Close Win', dropdownElement);
    popup.style.display = 'none';
    // 🔁 Redirigir automáticamente a la pestaña Hire del candidato contratado
    localStorage.setItem('fromCloseWin', 'true');
    window.location.href = `candidate-details.html?id=${candidateId}#hire`;
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
