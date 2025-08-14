document.addEventListener('DOMContentLoaded', () => {

  // 🔍 Toggle filtros
  const toggleButton = document.getElementById('toggleFilters');
  const filtersCard = document.getElementById('filtersCard');

  if (toggleButton && filtersCard) {
    toggleButton.addEventListener('click', () => {
      const isExpanded = filtersCard.classList.contains('expanded');
      filtersCard.classList.toggle('expanded', !isExpanded);
      filtersCard.classList.toggle('hidden', isExpanded);
      toggleButton.textContent = isExpanded ? '🔍 Filters' : '❌ Close Filters';
    });
  }

  // 📦 Obtener datos desde Flask
  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/data/light')
    .then(res => res.json())
    .then(data => {
      console.log("Datos recibidos desde el backend:", data);
      // Destruir DataTable previa si ya existe
      if ($.fn.DataTable.isDataTable('#accountTable')) {
        $('#accountTable').DataTable().destroy();
      }

      const tableBody = document.getElementById('accountTableBody');
      tableBody.innerHTML = '';

      if (!Array.isArray(data) || data.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="7">No data found</td></tr>';
        return;
      }
      const currentUserEmail = localStorage.getItem('user_email');
      const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 'lara@vintti.com'];
      const showPriorityColumn = allowedEmails.includes(currentUserEmail);
      data.forEach(item => {
        const contractTxt = item.contract || '<span class="placeholder">No hires yet</span>';
        const trrTxt = fmtMoney(item.trr) || '<span class="placeholder">$0</span>';
        const tsfTxt = fmtMoney(item.tsf) || '<span class="placeholder">$0</span>';
        const tsrTxt = fmtMoney(item.tsr) || '<span class="placeholder">$0</span>';

        let htmlRow = `
          <tr data-id="${item.account_id}">
            <td>${item.client_name || '—'}</td>
            <td class="status-td" data-id="${item.account_id}">
              <span class="chip chip--loading" aria-label="Loading status">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              </span>
            </td>
            <td class="muted-cell">${item.account_manager_name ? item.account_manager_name : '<span class="placeholder">Unavailable</span>'}</td>
            <td class="muted-cell">${contractTxt}</td>
            <td>${trrTxt}</td>
            <td>${tsfTxt}</td>
            <td>${tsrTxt}</td>
        `;

        if (showPriorityColumn) {
          htmlRow += `
            <td>
              <select
                class="priority-select ${item.priority ? 'priority-' + item.priority.toLowerCase() : 'priority-empty'}"
                data-id="${item.account_id}">
                <option value="" ${item.priority ? '' : 'selected'}> </option>
                <option value="A" ${item.priority === 'A' ? 'selected' : ''}>A</option>
                <option value="B" ${item.priority === 'B' ? 'selected' : ''}>B</option>
                <option value="C" ${item.priority === 'C' ? 'selected' : ''}>C</option>
              </select>
            </td>
          `;
        }
        htmlRow += `</tr>`;
        tableBody.innerHTML += htmlRow;
      });


      // 👇 Inserta el nuevo <th> si aplica
      if (showPriorityColumn) {
        const priorityHeader = document.createElement('th');
        priorityHeader.textContent = 'Priority';
        document.querySelector('#accountTable thead tr').appendChild(priorityHeader);
      }

      document.querySelectorAll('#accountTableBody tr').forEach(row => {
        row.addEventListener('click', () => {
          const id = row.getAttribute('data-id');
          if (id) {
            window.location.href = `account-details.html?id=${id}`;
          }
        });
      });

      $('#accountTable').DataTable({
        responsive: true,
        pageLength: 50,
        dom: 'lrtip',
        lengthMenu: [[50, 100, 150], [50, 100, 150]],
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
      computeAndPaintAccountStatuses();
      // Mover selector de "mostrar X registros por página" al contenedor deseado
const lengthMenu = document.querySelector('#accountTable_length');
const customLengthContainer = document.getElementById('datatable-length-container');
if (lengthMenu && customLengthContainer) {
  customLengthContainer.appendChild(lengthMenu);
}

document.querySelectorAll('.priority-select').forEach(select => {
  select.addEventListener('change', async () => {
    const accountId = select.getAttribute('data-id');
    const newPriority = select.value;

    // Quitar clases anteriores
    select.classList.remove('priority-a', 'priority-b', 'priority-c', 'priority-empty');

    // Agregar clase correspondiente (y estado vacío)
    if (!newPriority) select.classList.add('priority-empty');
    if (newPriority === 'A') select.classList.add('priority-a');
    if (newPriority === 'B') select.classList.add('priority-b');
    if (newPriority === 'C') select.classList.add('priority-c');

    try {
      await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priority: newPriority || null })
      });
      console.log(`✅ Priority updated for account ${accountId}`);
    } catch (error) {
      console.error('❌ Error updating priority:', error);
    }
  });
});


    })
    .catch(err => {
      console.error('Error fetching account data:', err);
    });

  // 🆕 Crear nuevo account desde el formulario
  const form = document.querySelector('.popup-form');

  if (form) {
form.addEventListener('submit', async (e) => {
  e.preventDefault();

  const formData = new FormData(form);
  const data = Object.fromEntries(formData.entries());

  console.log("📤 Enviando datos al backend:", data);  // ✅ Ver qué datos se envían

  try {
    const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(data)
    });

    console.log("📥 Respuesta recibida:", response);  // ✅ Ver el status y headers

    if (response.ok) {
      const responseData = await response.json();
      console.log("✅ Éxito al crear account:", responseData);
      alert('✅ Account created!');
      location.reload();
    } else {
      const errorText = await response.text();
      console.warn("⚠️ Error al crear account:", errorText);
      alert('Error: ' + errorText);
    }
  } catch (err) {
    console.error("❌ Error inesperado al enviar request:", err);
    alert('⚠️ Error sending request');
  }
});
  }
// 🟣 SIDEBAR TOGGLE CON MEMORIA (único y sin colisión)
const sidebarToggleBtn = document.getElementById('sidebarToggle');
const sidebarToggleIcon = document.getElementById('sidebarToggleIcon');
const sidebarEl = document.querySelector('.sidebar');
const mainContentEl = document.querySelector('.main-content');

// Leer estado anterior desde localStorage
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

  localStorage.setItem('sidebarHidden', hidden); // 🧠 guardar estado
});
const summaryLink = document.getElementById('summaryLink');
const currentUserEmail = localStorage.getItem('user_email');
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 'lara@vintti.com'];

if (summaryLink && allowedEmails.includes(currentUserEmail)) {
  summaryLink.style.display = 'block';
}
// 🔍 Buscador por Client Name
const clientSearchInput = document.getElementById('searchClientInput');
if (clientSearchInput) {
  clientSearchInput.addEventListener('input', function () {
    const table = $('#accountTable').DataTable();
    table.column(0).search(this.value, true, false).draw();
  });
}








  
});

// 🪟 Funciones popup
function openPopup() {
  const popup = document.getElementById('popup');
  popup.style.display = 'flex';
  popup.classList.add('show');  // ⭐ Agregas clase show
}

function closePopup() {
  const popup = document.getElementById('popup');
  popup.classList.remove('show');  // ⭐ Quitas clase show
  setTimeout(() => {
    popup.style.display = 'none';
  }, 300);  // Esperas a que termine la animación de fade-out
}

// 👉 Helpers de formateo
function fmtMoney(v) {
  if (v === null || v === undefined) return null;
  const num = Number(v) || 0;
  if (num === 0) return null; // para mostrar "No available"
  return `$${num.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

// —— Helpers de normalización ——
function norm(s) {
  return (s || '').toString().toLowerCase().trim();
}
function normalizeStage(stage) {
  const v = norm(stage);
  if (/sourc|interview|negotiat/.test(v)) return 'pipeline';
  if (/closed[_\s-]?won|close[_\s-]?win/.test(v)) return 'won';
  if (/closed[_\s-]?lost|close[_\s-]?lost/.test(v)) return 'lost';
  return 'other';
}
function isActiveHire(h) {
  // Prioriza campo status si existe
  const st = norm(h.status);
  if (st === 'active') return true;
  if (st === 'inactive') return false;

  // Si no, vemos end_date: activo si NO hay fecha real
  const ed = (h.end_date ?? '').toString().trim().toLowerCase();
  if (!ed || ed === 'null' || ed === 'none' || ed === 'undefined' || ed === '0000-00-00') return true;
  // YYYY-MM o YYYY-MM-DD válido => inactivo
  return false;
}
function renderAccountStatusChip(statusText) {
  const s = norm(statusText);
  if (s === 'active client')   return '<span class="chip chip--active-client">Active Client</span>';
  if (s === 'inactive client') return '<span class="chip chip--inactive-client">Inactive Client</span>';
  if (s === 'lead in process') return '<span class="chip chip--lead-process">Lead in Process</span>';
  return '—';
}
function deriveStatusFrom(opps = [], hires = []) {
  if (!Array.isArray(opps) || opps.length === 0) return '—';

  const stages = opps.map(o => normalizeStage(o.opp_stage || o.stage));
  const hasPipeline = stages.some(s => s === 'pipeline');
  if (hasPipeline) return 'Lead in Process';

  const closedOnly = stages.every(s => s === 'won' || s === 'lost');
  const wins = stages.filter(s => s === 'won').length;

  if (closedOnly && wins > 0) {
    const total = (hires || []).length;
    const activeCount = (hires || []).filter(isActiveHire).length;
    if (total > 0 && activeCount > 0)  return 'Active Client';
    if (total > 0 && activeCount === 0) return 'Inactive Client';
  }
  return '—';
}

// —— Runner con límite de concurrencia (para fallback) ——
async function runWithConcurrency(tasks, limit = 6) {
  const queue = tasks.slice();
  const workers = Array.from({ length: limit }, async () => {
    while (queue.length) await queue.shift()();
  });
  await Promise.all(workers);
}

// —— Cálculo y pintado batch ——
async function computeAndPaintAccountStatuses() {
  const rows = [...document.querySelectorAll('#accountTableBody tr')];
  const ids  = rows.map(r => Number(r.dataset.id)).filter(Boolean);
  if (!ids.length) return;

  // 1) Intento recomendado: 1 request batch al backend
  //    POST /accounts/status/summary  -> { [id]: { status: "Active Client" | ... } }
  let summary = null;
  try {
    const r = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/status/summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_ids: ids })
    });
    if (r.ok) summary = await r.json();
  } catch (e) { /* ignoramos y hacemos fallback */ }

  // 2) Fallback sin bloquear: concurrencia limitada usando endpoints existentes
  if (!summary) {
    summary = {};
    const tasks = ids.map(id => async () => {
      try {
        const [opps, hires] = await Promise.all([
          fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}/opportunities`).then(r => r.json()),
          fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}/opportunities/candidates`).then(r => r.json()),
        ]);
        summary[id] = { status: deriveStatusFrom(opps, hires) };
      } catch { summary[id] = { status: '—' }; }
    });
    await runWithConcurrency(tasks, 6); // <-- ajusta si quieres más/menos paralelismo
  }

  // 3) Pintar y persistir (no bloquea UI)
  for (const id of ids) {
    const td = document.querySelector(`#accountTableBody tr[data-id="${id}"] td.status-td`);
    const status = summary?.[id]?.status || '—';
    if (td) td.innerHTML = renderAccountStatusChip(status);

    // Guarda en DB para cachearlo (best-effort, sin await)
    if (status !== '—') {
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ calculated_status: status })
      }).catch(() => {});
    }
  }
}
function renderAccountStatusChip(statusText) {
  const s = norm(statusText);
  if (s === 'active client')   return '<span class="chip chip--active-client">Active Client</span>';
  if (s === 'inactive client') return '<span class="chip chip--inactive-client">Inactive Client</span>';
  if (s === 'lead in process') return '<span class="chip chip--lead-process">Lead in Process</span>';
  // sin dato: chip gris (nada de '-')
  return '<span class="chip chip--empty">No data</span>';
}
