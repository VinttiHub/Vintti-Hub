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
    const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 'lara@vintti.com'];
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
          <td class="muted-cell">${item.account_manager_name ? item.account_manager_name : '<span class="placeholder">Unavailable</span>'}</td>
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

    // 👉 Cabecera "Priority" si aplica
    if (showPriorityColumn) {
      const th = document.createElement('th');
      th.textContent = 'Priority';
      document.querySelector('#accountTable thead tr').appendChild(th);
    }

    // Navegación por fila (delegado para que no se rompa con DataTables)
    document.getElementById('accountTableBody').addEventListener('click', (e) => {
      const row = e.target.closest('tr[data-id]');
      if (!row) return;
      const id = row.getAttribute('data-id');
      if (id) window.location.href = `account-details.html?id=${id}`;
    });

    // ♻️ Toast mientras se calcula
    const ids = data.map(x => Number(x.account_id)).filter(Boolean);
    const rowById = new Map(
      [...document.querySelectorAll('#accountTableBody tr')].map(r => [Number(r.dataset.id), r])
    );

    // ♻️ Toast con “paso extra” para el ordenamiento
    showSortToast(ids.length + 1);

    // 🧮 Calcula y actualiza barra (solo incrementos durante el cálculo)
    await computeAndPaintAccountStatuses({
      ids,
      rowById,
      onProgress: (inc) => updateSortToast(inc)  // ← solo incrementa
    });

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
  return '<span class="chip chip--empty">No data</span>'; // fallback
}
function deriveStatusFrom(opps = [], hires = []) {
  // Sin oportunidades: conserva tu comportamiento especial
  if (!Array.isArray(opps) || opps.length === 0) return '—';

  const stages         = opps.map(o => normalizeStage(o.opp_stage || o.stage));
  const hasWon         = stages.includes('won');
  const allLost        = stages.every(s => s === 'lost');
  const hasPipeline    = stages.some(s => s === 'pipeline');
  const hasActiveHire  = (hires || []).some(isActiveHire);
  const closedOnly     = stages.every(s => s === 'won' || s === 'lost');

  // 🔝 Regla B: prioridad máxima
  if (hasWon && hasActiveHire) return 'Active Client';

  // 🟥 Regla A: todas perdidas
  if (allLost) return 'Inactive Client';

  // ▶️ Si hay pipeline y ninguna regla anterior aplicó
  if (hasPipeline) return 'Lead in Process';

  // ⚖️ Cierre solo (won/lost) con wins pero sin hires activos → inactivo
  if (closedOnly && hasWon && !hasActiveHire) return 'Inactive Client';

  // Sin señal clara
  return 'No data';
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
      calculated_status: summary?.[id]?.status || '—'
    }));
    const rb = await fetch(`${API}/accounts/status/bulk_update`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ updates })
    });
    if (!rb.ok) throw new Error('bulk endpoint not available');
  } catch {
    const patchTasks = ids.map(id => async () => {
      try {
        await fetch(`${API}/accounts/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ calculated_status: summary?.[id]?.status || '—' })
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
  if (s === 'inactive client') return 2;
  return 3; // No data / vacío
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
