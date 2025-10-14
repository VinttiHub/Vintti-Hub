// ——— Decidir manager por status ———
function managerEmailForStatus(statusText='') {
  const s = (statusText || '').toLowerCase().trim();
  if (s === 'active client')   return 'lara@vintti.com';
  if (s === 'lead in process') return 'bahia@vintti.com';
  return null; // otros -> no cambiar
}
// === Referral source UI ===
async function loadReferralClients() {
  try {
    const r = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts');
    const arr = await r.json();
    // Endpoint devuelve [{ account_name: '...' }]
    const names = [...new Set((arr || [])
      .map(x => (x.account_name || x.client_name || '').trim())
      .filter(Boolean))]
      .sort((a, b) => a.localeCompare(b));
    const referralListEl = document.getElementById('referralList');
    if (referralListEl) {
      referralListEl.innerHTML = names.map(n => `<option value="${n}"></option>`).join('');
    }
  } catch (e) {
    console.warn('⚠️ Could not load referral clients list:', e);
  }
}

function updateReferralVisibility(sourceSelect) {
  const wrap  = document.getElementById('referralSourceWrapper');
  const input = document.getElementById('referralSourceInput');
  if (!wrap || !input || !sourceSelect) return;

  const isReferral = String(sourceSelect.value || '').toLowerCase() === 'referral';
  wrap.style.display = isReferral ? '' : 'none';
  input.required = isReferral;
  if (!isReferral) input.value = '';
}

// ——— PATCH a /accounts/<id> con el account_manager ———
async function patchAccountManager(accountId, email) {
  const API = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  await fetch(`${API}/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account_manager: email })
  });
}

// ——— Render rápido del manager en la celda (igual estilo que Opps) ———
function paintManagerCell(rowEl, email) {
  if (!rowEl) return;
  const cell = rowEl.querySelector('.sales-lead-cell');
  if (!cell) return;
  const item = { account_manager: email, account_manager_name: email };
  cell.innerHTML = getAccountSalesLeadCell(item);
}

// === Sales Lead visuals (como en Opportunities) ===
window.AVATAR_BASE = window.AVATAR_BASE || './assets/img/';
window.AVATAR_BY_EMAIL = {  // se fusiona con lo que ya tengas
  'agostina@vintti.com': 'agos.png',
  'bahia@vintti.com':    'bahia.png',
  'lara@vintti.com':     'lara.png',
  'jazmin@vintti.com':   'jaz.png',
  'pilar@vintti.com':    'pilar.png',
  'agustin@vintti.com':  'agus.png',
  'agustina.barbero@vintti.com': 'agustina.png',
  ...(window.AVATAR_BY_EMAIL || {})
};

if (typeof window.resolveAvatar !== 'function') {
  window.resolveAvatar = function resolveAvatar(email) {
    if (!email) return null;
    const key = String(email).trim().toLowerCase();
    const filename = window.AVATAR_BY_EMAIL[key];
    return filename ? (window.AVATAR_BASE + filename) : null;
  };
}

// Iniciales & color igual que en Opps
function initialsForSalesLead(key='') {
  const s = key.toLowerCase();
  if (s.includes('bahia'))   return 'BL';
  if (s.includes('lara'))    return 'LR';
  if (s.includes('agustin')) return 'AM';
  return '--';
}
function badgeClassForSalesLead(key='') {
  const s = key.toLowerCase();
  if (s.includes('bahia'))   return 'bl';
  if (s.includes('lara'))    return 'lr';
  if (s.includes('agustin')) return 'am';
  return '';
}

// Fallback simple para mapear nombre→email si el backend no manda el email crudo
function emailFromNameGuess(name='') {
  const s = name.toLowerCase();
  if (s.includes('bahia'))   return 'bahia@vintti.com';
  if (s.includes('lara'))    return 'lara@vintti.com';
  if (s.includes('agustin')) return 'agustin@vintti.com';
  return '';
}

// 📦 Render desde los campos del account (account_manager / account_manager_name)
function getAccountSalesLeadCell(item) {
  // Preferir el email real del account_manager si viene en el JSON;
  // si no, tratar de inferirlo por el nombre.
  const email = (item.account_manager || emailFromNameGuess(item.account_manager_name || '')).toLowerCase();
  const name  = item.account_manager_name || '';

  // key para iniciales/clase (usa lo que haya)
  const key = (email || name).toLowerCase();
  const initials = initialsForSalesLead(key);
  const bubbleCl = badgeClassForSalesLead(key);

  const avatar = window.resolveAvatar(email);
  const img = avatar ? `<img class="lead-avatar" src="${avatar}" alt="">` : '';

  // nombre oculto para filtros/orden (igual que en Opps)
  return `
    <div class="sales-lead">
      <span class="lead-bubble ${bubbleCl}">${initials}</span>
      ${img}
      <span class="sr-only" style="display:none">${name}</span>
    </div>
  `;
}


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
// 📦 Obtener datos desde Flask
fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/data/light')
  .then(res => res.json())
  .then(async (data) => {
    console.log("Datos recibidos desde el backend:", data);
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
    const showPriorityColumn = allowedEmails.includes(currentUserEmail);

    // ——— Render de filas SIN DataTables todavía ———
    // (más rápido: un solo innerHTML)
    const rowsHtml = data.map(item => {
      const contractTxt = item.contract || '<span class="placeholder">No hires yet</span>';
      const trrTxt = fmtMoney(item.trr) || '<span class="placeholder">$0</span>';
      const tsfTxt = fmtMoney(item.tsf) || '<span class="placeholder">$0</span>';
      const tsrTxt = fmtMoney(item.tsr) || '<span class="placeholder">$0</span>';

      return `
        <tr data-id="${item.account_id}">
          <td>${item.client_name || '—'}</td>
          <td class="status-td" data-id="${item.account_id}" data-order="99">
            <span class="chip chip--loading" aria-label="Loading status">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            </span>
          </td>
          <td class="sales-lead-cell">
            ${ (item.account_manager || item.account_manager_name)
                ? getAccountSalesLeadCell(item)
                : '<span class="placeholder">Unassigned</span>' }
          </td>
          <td class="muted-cell">${contractTxt}</td>
          <td>${trrTxt}</td>
          <td>${tsfTxt}</td>
          <td>${tsrTxt}</td>
          ${showPriorityColumn ? `
            <td>
              <select
                class="priority-select ${item.priority ? 'priority-' + item.priority.toLowerCase() : 'priority-empty'}"
                data-id="${item.account_id}">
                <option value="" ${item.priority ? '' : 'selected'}> </option>
                <option value="A" ${item.priority === 'A' ? 'selected' : ''}>A</option>
                <option value="B" ${item.priority === 'B' ? 'selected' : ''}>B</option>
                <option value="C" ${item.priority === 'C' ? 'selected' : ''}>C</option>
              </select>
            </td>` : ``}
        </tr>`;
    }).join('');
    tableBody.innerHTML = rowsHtml;
const th3 = document.querySelector('#accountTable thead tr th:nth-child(3)');
if (th3) th3.textContent = 'Sales Lead';

    // 👉 Cabecera "Priority" si aplica
    if (showPriorityColumn) {
      const th = document.createElement('th');
      th.textContent = 'Priority';
      document.querySelector('#accountTable thead tr').appendChild(th);
    }

    // Navegación por fila (delegado para que no se rompa con DataTables)
const $tbody = document.getElementById('accountTableBody');

$tbody.addEventListener('click', (e) => {
  // NO navegar si el click fue sobre el dropdown de Priority u otro control interactivo
  if (e.target.closest('select.priority-select, option, input, button, a, label')) return;

  const row = e.target.closest('tr[data-id]');
  if (!row) return;

  const id = row.getAttribute('data-id');
  if (!id) return;

  const url = `account-details.html?id=${id}`;
  window.open(url, '_blank', 'noopener,noreferrer'); // ← pestaña nueva
});

// Salvaguarda extra: al abrir el select, evita que el click “burbujee” a la fila
$tbody.addEventListener('mousedown', (e) => {
  if (e.target.closest('select.priority-select')) {
    e.stopPropagation();
  }
});


    // ♻️ Toast mientras se calcula
    const ids = data.map(x => Number(x.account_id)).filter(Boolean);
    const rowById = new Map(
      [...document.querySelectorAll('#accountTableBody tr')].map(r => [Number(r.dataset.id), r])
    );

    // ♻️ Toast con “paso extra” para el ordenamiento
    showSortToast(ids.length + 1);

    // 🧮 Calcula y actualiza barra (solo incrementos durante el cálculo)
// 🧮 Calcula y actualiza barra (solo incrementos durante el cálculo)
const summary = await computeAndPaintAccountStatuses({
  ids,
  rowById,
  onProgress: (inc) => updateSortToast(inc)
});

// 🟣 Asignar account_manager según status (solo Active/Lead in Process)
await (async function assignManagersFromStatus() {
  const tasks = [];

  for (const [idStr, obj] of Object.entries(summary || {})) {
    const accountId = Number(idStr);
    const status = obj?.status || '';
    const targetEmail = managerEmailForStatus(status);
    if (!targetEmail) continue; // otros status -> no tocar

    // Evitar PATCH innecesario si ya está pintado con ese manager
    const row = rowById.get(accountId);
    const currentCellEmail = (() => {
      if (!row) return '';
      const hiddenName = row.querySelector('.sales-lead-cell .sr-only');
      return (hiddenName?.textContent || '').toLowerCase().trim();
    })();
    if (currentCellEmail === targetEmail) {
      // ya coinciden visualmente; igual intentamos evitar parchar si la BD ya lo tiene
      // (no lo sabemos con certeza desde el front, pero podemos pintar y omitir PATCH)
      continue;
    }

    tasks.push(async () => {
      try {
        await patchAccountManager(accountId, targetEmail);
        paintManagerCell(row, targetEmail);      // refresca UI
        // console.log(`✅ account ${accountId} → ${targetEmail}`);
      } catch (e) {
        console.warn(`⚠️ No se pudo asignar manager a ${accountId}:`, e);
      } finally {
        updateSortToast(1); // opcional: marcar avance visual
      }
    });
  }

  // Reutilizamos tu runner con concurrencia amable
  if (tasks.length) {
    await runWithConcurrency(tasks, 6);
  }
})();


    // ✅ DataTables: subimos a 100% cuando ya dibujó con el orden aplicado
    let _finalized = false;
    const finalizeToast = () => {
      if (_finalized) return;
      _finalized = true;
      updateSortToast(1);       // ← último “tick” reservado para el sort/draw
      setTimeout(hideSortToast, 400);
    };

    // Importante: engancha el primer draw ANTES o justo al crear la tabla
    const $tbl = $('#accountTable');
    $tbl.one('draw.dt', finalizeToast);

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
        zeroRecords: "No se encontraron resultados",
        info: "Mostrando _START_ a _END_ de _TOTAL_ registros",
        paginate: { first: "Primero", last: "Último", next: "Siguiente", previous: "Anterior" }
      },
      // Respaldo por si algo impide capturar el primer draw
      initComplete: finalizeToast
    });

    // Mover selector "mostrar X registros"
    const lengthMenu = document.querySelector('#accountTable_length');
    const customLengthContainer = document.getElementById('datatable-length-container');
    if (lengthMenu && customLengthContainer) customLengthContainer.appendChild(lengthMenu);

    // Buscador por Client Name
    const clientSearchInput = document.getElementById('searchClientInput');
    if (clientSearchInput) {
      clientSearchInput.addEventListener('input', function () {
        table.column(0).search(this.value, true, false).draw();
      });
    }

    // Priority: listeners (delegado por simplicidad/robustez)
    document.getElementById('accountTableBody').addEventListener('change', async (e) => {
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

    hideSortToast(); // cerrar alerta al final
  })
  .catch(err => {
    console.error('Error fetching account data:', err);
  });

// 🆕 Crear nuevo account desde el formulario
const form = document.querySelector('.popup-form');
// Cargar lista de clientes para referral y manejar visibilidad
if (form) {
  const sourceSelect = form.querySelector('select[name="where_come_from"]');
  loadReferralClients();
  if (sourceSelect) {
    updateReferralVisibility(sourceSelect); // estado inicial oculto
    sourceSelect.addEventListener('change', () => updateReferralVisibility(sourceSelect));
  }
}

if (form) {
  // Referencia al dropdown nuevo (debe existir en el HTML con name="where_come_from")
  const sourceSelect = form.querySelector('select[name="where_come_from"]');

  // Limpia mensajes de validación cuando cambia
  if (sourceSelect) {
    sourceSelect.addEventListener('change', () => {
      sourceSelect.setCustomValidity('');
    });
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    // Validación suave por si el required no dispara (Safari viejito, etc.)
    if (sourceSelect && !sourceSelect.value) {
      sourceSelect.setCustomValidity('Please select a lead source');
      sourceSelect.reportValidity();
      return;
    }

    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());
// Normaliza lead source y referal_source
if (data.where_come_from != null) {
  data.where_come_from = String(data.where_come_from).trim();
}
const isReferral = (data.where_come_from || '').toLowerCase() === 'referral';
if (isReferral) {
  data.referal_source = (data.referal_source || '').trim() || null;
} else {
  // si no es Referral, no mandamos el campo
  delete data.referal_source;
}

    // Asegurar string limpio
    if (data.where_come_from != null) {
      data.where_come_from = String(data.where_come_from).trim();
    }

    console.log("📤 Enviando datos al backend:", data);

    try {
      const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });

      console.log("📥 Respuesta recibida:", response);

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
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 'lara@vintti.com','agostina@vintti.com'];

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
// —— Helpers de normalización ——
function normalizeStage(stage) {
  const v = norm(stage);
  // Won / Lost (variantes: "closed won", "close win", etc.)
  if (/closed?[_\s-]?won|close[_\s-]?win/.test(v))  return 'won';
  if (/closed?[_\s-]?lost|close[_\s-]?lost/.test(v)) return 'lost';

  // En proceso: sourcing, interview, negotiating, deep dive, etc.
  if (/(sourc|interview|negotiat|deep\s?dive)/.test(v)) return 'pipeline';

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
  if (s === 'lead')            return '<span class="chip chip--lead">Lead</span>';
  if (s === 'lead lost')       return '<span class="chip chip--lead-lost">Lead Lost</span>';
  return '<span class="chip chip--empty">No data</span>';
}

function deriveStatusFrom(opps = [], hires = []) {
  // --- candidatos (relaciones de oportunidades ↔ candidatos) ---
  const hasCandidates = Array.isArray(hires) && hires.length > 0;
  const anyActiveCandidate = hasCandidates && hires.some(isActiveHire);
  const allCandidatesInactive = hasCandidates && hires.every(h => !isActiveHire(h));

  // --- oportunidades ---
  const stages = (Array.isArray(opps) ? opps : []).map(o => normalizeStage(o.opp_stage || o.stage));
  const hasOpps = stages.length > 0;
  const hasPipeline = stages.some(s => s === 'pipeline');
  const allLost = hasOpps && stages.every(s => s === 'lost');

  // 1) Active client → ≥1 candidato activo
  if (anyActiveCandidate) return 'Active Client';

  // 2) Inactive client → tiene candidatos y todos inactivos
  if (allCandidatesInactive) return 'Inactive Client';

  // 5) Lead → no tiene ninguna oportunidad asociada (y tampoco candidatos)
  if (!hasOpps && !hasCandidates) return 'Lead';

  // 4) Lead lost → todas sus oportunidades son close lost y no tiene candidatos
  if (allLost && !hasCandidates) return 'Lead Lost';

  // 3) Lead in process → igual a como lo hacemos ahora
  if (hasPipeline) return 'Lead in Process';

  // Fallbacks razonables:
  if (!hasOpps && hasCandidates) return 'Inactive Client'; // tiene candidatos pero ninguno activo
  return 'Lead in Process'; // estado intermedio cuando hay señales pero no encaja 1:1
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
// 🧮 Calcula y pinta el status de TODOS los accounts (con progreso opcional)
async function computeAndPaintAccountStatuses({ ids, rowById, onProgress }) {
  const API = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const CHUNK = 200;                        // tamaño de lote para /status/summary
  const CONC_SUMMARY = 4;                   // concurrencia para summary
  const CONC_FALLBACK = Math.min(navigator.hardwareConcurrency || 8, 8); // fallback por cuenta

  // Progreso inicial (si el caller lo usa)
  onProgress?.(0, ids.length);

  // Guarda los resultados aquí: { [id]: { status: "..." } }
  const summary = {};

  // Normaliza la respuesta del endpoint /accounts/status/summary a {id: {status}}
  function mergeSummary(resp) {
    let added = 0;

    if (Array.isArray(resp)) {
      // Ej: [{account_id: 123, status: "Active Client"}]
      for (const it of resp) {
        const id = Number(it.account_id ?? it.id ?? it.accountId);
        if (!id) continue;
        const status = it.status ?? it.calculated_status ?? it.value ?? '—';
        if (!summary[id]) added++;
        summary[id] = { status };
      }
      return added;
    }

    if (resp && typeof resp === 'object') {
      // Ej: { "123": {status: "Active Client"}, "124": "Inactive Client" }
      for (const [k, v] of Object.entries(resp)) {
        const id = Number(k);
        if (!id) continue;
        let status;
        if (v && typeof v === 'object') status = v.status ?? v.calculated_status ?? v.value ?? '—';
        else status = v ?? '—';
        if (!summary[id]) added++;
        summary[id] = { status };
      }
      return added;
    }

    return 0;
  }

  // 1) Intento principal: summary en lotes
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
          const r = await fetch(`${API}/accounts/status/summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_ids: partIds })
          });
          if (r.ok) {
            const json = await r.json();
            const added = mergeSummary(json);
            if (added > 0) onProgress?.(added); // avanza progreso por IDs resueltos
          }
        } catch (_) {
          // silencioso; faltantes se resuelven con fallback
        }
      }
    })
  );

  // 2) Fallback por cuenta para los que falten
  const missing = ids.filter(id => !summary[id]);
  if (missing.length) {
    const tasks = missing.map(id => async () => {
      try {
        const [opps, hires] = await Promise.all([
          fetch(`${API}/accounts/${id}/opportunities`).then(r => r.json()),
          fetch(`${API}/accounts/${id}/opportunities/candidates`).then(r => r.json()),
        ]);
        summary[id] = { status: deriveStatusFrom(opps, hires) };
      } catch {
        summary[id] = { status: '—' };
      } finally {
        onProgress?.(1); // cada cuenta faltante completada
      }
    });
    await runWithConcurrency(tasks, CONC_FALLBACK);
  }

  // 3) Pintar chips + clave de orden en el DOM (todas las filas)
  for (const id of ids) {
    const row = rowById.get(id);
    if (!row) continue;
    const td = row.querySelector('td.status-td');
    const status = summary?.[id]?.status || '—';
    if (td) {
      td.innerHTML = renderAccountStatusChip(status);
      td.dataset.order = String(statusRank(status));
    }
  }

  // 4) Persistir: intenta bulk, si falla cae a PATCH concurrente
  try {
    const updates = ids.map(id => ({
      account_id: id,
      status: summary?.[id]?.status || '—'
    }));
    const rb = await fetch(`${API}/accounts/status/bulk_update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
      updates: updates.map(u => ({
        account_id: u.account_id,
        status: u.calculated_status   // ← we rename key on the wire
      }))
    })
    });
    if (!rb.ok) throw new Error('bulk endpoint not available');
  } catch {
    const patchTasks = ids.map(id => async () => {
      try {
        await fetch(`${API}/accounts/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_status: summary?.[id]?.status || '—' })
        });
      } catch { /* noop */ }
    });
    await runWithConcurrency(patchTasks, 6);
  }

  return summary; // por si quieres usarlo después
}
// Rank para el orden deseado: Active → Lead → Inactive → No data
function statusRank(statusText){
  const s = norm(statusText);
  if (s === 'active client')   return 0;
  if (s === 'lead in process') return 1;
  if (s === 'lead')            return 2;
  if (s === 'inactive client') return 3;
  if (s === 'lead lost')       return 4;
  return 5; // No data / —
}


// Mini-toast
// —— Estado interno del toast de ordenamiento —— //
const _sortToastState = {
  total: 0,
  done: 0,
  start: 0,
};

function _ensureSortToast() {
  const t = document.getElementById('crmSortToast');
  if (!t) {
    console.warn('crmSortToast element not found.');
  }
  return t;
}

// Muestra el toast. Si pasas total > 0, mostrará porcentaje; si no, usa modo indeterminado.
function showSortToast(total = 0) {
  const t = _ensureSortToast();
  if (!t) return;

  _sortToastState.total = Number(total) || 0;
  _sortToastState.done = 0;
  _sortToastState.start = Date.now();

  const bar = t.querySelector('.sort-toast__bar');
  const percent = t.querySelector('#sortToastPercent');
  const progress = t.querySelector('.sort-toast__progress');

  if (bar) bar.style.width = '0%';
  if (percent) percent.textContent = (_sortToastState.total ? '0%' : '…');
  if (progress) progress.setAttribute('aria-valuenow', '0');

  t.classList.remove('hide');
  t.style.display = 'block';
  if (_sortToastState.total) t.classList.remove('indeterminate');
  else t.classList.add('indeterminate');
  requestAnimationFrame(() => t.classList.add('show'));
}

// Actualiza progreso. Puedes llamar con (done, total) o solo con (incremento).
function updateSortToast(doneOrInc, maybeTotal) {
  const t = _ensureSortToast();
  if (!t) return;

  if (typeof maybeTotal === 'number' && maybeTotal > 0) {
    _sortToastState.total = maybeTotal;
    _sortToastState.done = Math.max(0, Math.min(maybeTotal, doneOrInc));
  } else {
    _sortToastState.done = Math.max(0, _sortToastState.done + (Number(doneOrInc) || 0));
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
    // modo indeterminado
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
(() => {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  // Quienes ven Summary
  const summaryAllowed = [
    'agustin@vintti.com',
    'bahia@vintti.com',
    'angie@vintti.com',
    'lara@vintti.com',
    'agostina@vintti.com'
  ];

  // Quienes ven Equipments
  const equipmentsAllowed = [
    'angie@vintti.com',
    'jazmin@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com'
  ];

  const summaryLink = document.getElementById('summaryLink');
  const equipmentsLink = document.getElementById('equipmentsLink');

  if (summaryLink)   summaryLink.style.display   = summaryAllowed.includes(email)   ? '' : 'none';
  if (equipmentsLink) equipmentsLink.style.display = equipmentsAllowed.includes(email) ? '' : 'none';
})();
// === LÍMITE DE INTERFAZ PARA CIERTOS USUARIOS (mostrar SOLO CRM y Opportunities) ===
(function enforceLimitedUI() {
  const LIMITED_USERS = new Set([
    'felipe@vintti.com',
    'felicitas@vintti.com',
    'luca@vintti.com',
    'abril@vintti.com'
  ]);

  // IDs/keys que SÍ deben permanecer visibles
  const ALLOWED_IDS = new Set([
    'crmLink',            // <a id="crmLink" ...>CRM</a>
    'opportunitiesLink'   // <a id="opportunitiesLink" ...>Opportunities</a>
  ]);

  // Palabras clave fallback por si algún botón no tiene ID consistente
  const ALLOWED_TEXT_KEYWORDS = ['crm', 'opportunit']; // 'opportunity' / 'opportunities'

  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();
  if (!LIMITED_USERS.has(email)) return; // Si no es usuario limitado, no hacemos nada

  // 1) Ocultar todo lo que parezca navegación y dejar sólo CRM/Opportunities
  //    Ajusta/añade selectores si tienes otros menús/zonas de navegación.
  const navCandidates = Array.from(document.querySelectorAll(`
    .sidebar a, 
    .sidebar button, 
    nav a, 
    nav button, 
    .topbar a, 
    .topbar button, 
    .menu a, 
    .menu button, 
    .bubble-button, 
    a[id], 
    button[id]
  `));

  navCandidates.forEach(el => {
    // Valida si este elemento es "permitido"
    const id = (el.id || '').toLowerCase();
    const txt = (el.textContent || el.getAttribute('aria-label') || '').toLowerCase().trim();

    const isAllowedById = id && ALLOWED_IDS.has(id);
    const isAllowedByText = ALLOWED_TEXT_KEYWORDS.some(k => txt.includes(k));

    // Si NO está permitido, lo ocultamos
    if (!isAllowedById && !isAllowedByText) {
      el.style.display = 'none';
      el.setAttribute('aria-hidden', 'true');
    }
  });

  // 2) Si existen enlaces concretos por ID, asegúrate de que sí se muestren
  ['crmLink', 'opportunitiesLink'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.style.display = '';           // visible
      el.removeAttribute('aria-hidden');
    }
  });

  // 3) Defensa opcional: redirige si está en páginas no permitidas
  //    Ajusta rutas según tus archivos reales (ej: crm.html, opportunities.html)
  const path = (location.pathname || '').toLowerCase();
  const isAllowedPage =
    path.includes('opportunities') || // opportunity-detail.html, opportunities.html, etc.
    path.includes('opportunity')  ||
    path.includes('crm');

  if (!isAllowedPage) {
    // Redirige a Opportunities por defecto
    const fallback = document.getElementById('opportunitiesLink')?.getAttribute('href') || 'opportunities.html';
    try { location.replace(fallback); } catch { location.href = fallback; }
  }
})();
// ——— Dashboard + Management Metrics (cross-pages) ———
(() => {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();
  const MGMT_ALLOWED = new Set(['agustin@vintti.com', 'angie@vintti.com', 'lara@vintti.com','bahia@vintti.com']);

  // Si no está permitido: no insertes los botones y elimina si ya existieran
  if (!email || !MGMT_ALLOWED.has(email)) {
    document.getElementById('dashboardLink')?.remove();
    document.getElementById('managementMetricsLink')?.remove();
    return; // 👈 salimos, no hay parpadeo
  }

  // 1) Resolver anclas disponibles en el sidebar
  const summary = document.getElementById('summaryLink')
    || document.querySelector('.sidebar a[href*="opportunities-summary"]')
    || document.querySelector('.sidebar a[href*="summary"]');

  const opportunities = document.getElementById('opportunitiesLink')
    || document.querySelector('.sidebar a[href*="opportunities.html"]');

  // Equipments puede ser creado dinámicamente en algunas páginas
  const equipments = document.getElementById('equipmentsLink')
    || document.querySelector('.sidebar a[href*="equipments.html"]');

  // Punto de inserción preferido
  const anchor = equipments || summary || opportunities
    || document.querySelector('.sidebar a, nav a, .menu a'); // último fallback
  if (!anchor) return;

  // 2) Base de estilos (hereda del Summary si existe, si no "menu-item")
  const baseClass = (document.getElementById('summaryLink')?.className) || anchor.className || 'menu-item';

  // 3) Crear enlaces solo si no existen
  if (!document.getElementById('dashboardLink')) {
    const a = document.createElement('a');
    a.id = 'dashboardLink';
    a.className = baseClass;
    a.textContent = 'Dashboard';
    a.href = 'https://dashboard.vintti.com/public/dashboard/a6d74a9c-7ffb-4bec-b202-b26cdb57ff84?meses=3&metric_arpa=&metrica=revenue&tab=5-growth-%26-revenue';
    a.target = '_blank';
    a.rel = 'noopener';
    anchor.insertAdjacentElement('afterend', a);
  }

  if (!document.getElementById('managementMetricsLink')) {
    const a = document.createElement('a');
    a.id = 'managementMetricsLink';
    a.className = baseClass;
    a.textContent = 'Management Metrics';
    a.href = 'control-dashboard.html';
    (document.getElementById('dashboardLink') || anchor).insertAdjacentElement('afterend', a);
  }

  // Accesibilidad
  document.getElementById('dashboardLink')?.setAttribute('aria-hidden', 'false');
  document.getElementById('managementMetricsLink')?.setAttribute('aria-hidden', 'false');

  // 4) Si el sidebar se monta tarde, reintenta SOLO para usuarios permitidos
  if (!equipments && !summary && !opportunities) {
    const obs = new MutationObserver((muts, o) => {
      const again = document.getElementById('summaryLink')
        || document.querySelector('.sidebar a[href*="opportunities.html"]')
        || document.querySelector('.sidebar a, nav a, .menu a');
      if (again) {
        o.disconnect();
        // Reinyecta una vez
        setTimeout(() => {
          // Evita duplicados
          if (!document.getElementById('dashboardLink') || !document.getElementById('managementMetricsLink')) {
            // Reejecuta este mismo bloque creando los links faltantes
            const evt = document.createElement('script');
            evt.type = 'module';
            evt.textContent = `(${arguments.callee.toString()})();`;
            document.head.appendChild(evt);
          }
        }, 0);
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }
})();
