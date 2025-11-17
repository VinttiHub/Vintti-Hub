document.addEventListener('DOMContentLoaded', () => {
  /* --------------------------------------
   * 0) Theme boot
   * ------------------------------------ */
  document.body.classList.add('light-mode');

  /* --------------------------------------
   * 1) Constants & DOM refs
   * ------------------------------------ */
  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const tbody    = document.getElementById('candidatesTableBody');
  const tableEl  = document.getElementById('candidatesTable');

/* --------------------------------------
 * 2) Fetch + render candidates
 * ------------------------------------ */
fetch(`${API_BASE}/candidates/light_fast`)
  .then(r => r.json())
  .then(data => {
    if (!Array.isArray(data) || data.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5">No data available</td></tr>`;
      return;
    }

    const frag = document.createDocumentFragment();

    for (const candidate of data) {
      const tr = document.createElement('tr');
      tr.dataset.id     = candidate.candidate_id || '';
      tr.dataset.status = (candidate.status || '').toLowerCase();                // 'active' | 'unhired'
      tr.dataset.model  = (candidate.opp_model || '').trim();                    // 'Recruiting' | 'Staffing' | ''

      const rawPhone = candidate.phone ? String(candidate.phone) : '';
      const phone    = rawPhone.replace(/\D/g, '');
      const linkedin = candidate.linkedin || '';

      const condition = tr.dataset.status || 'unhired';
      const chipClass = {
        active:  'status-active',
        unhired: 'status-unhired'
      }[condition] || 'status-unhired';

      tr.innerHTML = `
        <td class="condition-cell"><span class="status-chip ${chipClass}">${condition}</span></td>
        <td>${candidate.name || '—'}</td>
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
      `;
      frag.appendChild(tr);
    }

    tbody.replaceChildren(frag);

    /* --------------------------------------
     * 3) DataTable setup
     * ------------------------------------ */
    const table = $('#candidatesTable').DataTable({
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

    // Mover selector de length
    const dataTableLength = document.querySelector('.dataTables_length');
    const wrapper = document.getElementById('datatable-wrapper');
    if (dataTableLength && wrapper) wrapper.appendChild(dataTableLength);

    // Búsqueda por nombre (columna 1) con debounce
    const searchInput = document.getElementById('searchByName');
    if (searchInput) {
      let t;
      searchInput.addEventListener('input', function () {
        clearTimeout(t);
        const v = this.value;
        t = setTimeout(() => table.column(1).search(v).draw(), 150);
      });
    }

    /* --------------------------------------
     * 4) Filtros: Status + Model
     * ------------------------------------ */
    installAdvancedFilters(table);
  })
  .catch(err => console.error('❌ Error al obtener candidatos:', err));

  /* --------------------------------------
   * 5) Row navigation (click fila -> details)
   * ------------------------------------ */
  tbody.addEventListener('click', (e) => {
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

  /* --------------------------------------
   * 6) Sidebar toggle (persistente en localStorage)
   * ------------------------------------ */
  const sidebar      = document.querySelector('.sidebar');
  const mainContent  = document.querySelector('.main-content');
  const toggleButton = document.getElementById('sidebarToggle');
  const toggleIcon   = document.getElementById('sidebarToggleIcon');

  if (sidebar && mainContent && toggleButton && toggleIcon) {
    const savedState = localStorage.getItem('sidebarHidden') === 'true';
    applySidebarState(savedState);

    toggleButton.addEventListener('click', () => {
      const isHidden = !sidebar.classList.contains('custom-sidebar-hidden');
      applySidebarState(isHidden);
      localStorage.setItem('sidebarHidden', isHidden);
    });
  }

  function applySidebarState(isHidden) {
    sidebar.classList.toggle('custom-sidebar-hidden', isHidden);
    mainContent.classList.toggle('custom-main-expanded', isHidden);
    toggleIcon.classList.toggle('fa-chevron-left', !isHidden);
    toggleIcon.classList.toggle('fa-chevron-right', isHidden);
    // Mantener posiciones existentes del toggle sin cambiar estilos globales
    toggleButton.style.left = isHidden ? '12px' : '220px';
  }
});

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

/* =========================================================================
   Permissions (Summary / Equipments): visible por email
   ====================================================================== */
(() => {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  // Quienes ven Summary
  const summaryAllowed = [
    'agustin@vintti.com',
    'bahia@vintti.com',
    'angie@vintti.com',
    'lara@vintti.com',
    'agostina@vintti.com',
    'mariano@vintti.com'
  ];

  // Quienes ven Equipments
  const equipmentsAllowed = [
    'angie@vintti.com',
    'jazmin@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com'
  ];

  const summaryLink    = document.getElementById('summaryLink');
  const equipmentsLink = document.getElementById('equipmentsLink');

  if (summaryLink)     summaryLink.style.display     = summaryAllowed.includes(email)     ? '' : 'none';
  if (equipmentsLink)  equipmentsLink.style.display  = equipmentsAllowed.includes(email)  ? '' : 'none';
})();

/* =========================================================================
   Dashboard + Management Metrics (cross-pages)
   ====================================================================== */
(() => {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();
  const MGMT_ALLOWED = new Set(['agustin@vintti.com', 'angie@vintti.com', 'lara@vintti.com', 'bahia@vintti.com']);

  // Si no está permitido: elimina si existieran y sal
  if (!email || !MGMT_ALLOWED.has(email)) {
    document.getElementById('dashboardLink')?.remove();
    document.getElementById('managementMetricsLink')?.remove();
    return;
  }

  // 1) Resolver anclas existentes en el sidebar
  const summary = document.getElementById('summaryLink')
    || document.querySelector('.sidebar a[href*="opportunities-summary"]')
    || document.querySelector('.sidebar a[href*="summary"]');

  const opportunities = document.getElementById('opportunitiesLink')
    || document.querySelector('.sidebar a[href*="opportunities.html"]');

  const equipments = document.getElementById('equipmentsLink')
    || document.querySelector('.sidebar a[href*="equipments.html"]');

  // Punto de inserción preferido
  const anchor = equipments || summary || opportunities
    || document.querySelector('.sidebar a, nav a, .menu a');
  if (!anchor) return;

  // 2) Base de estilos (hereda del Summary si existe)
  const baseClass = (document.getElementById('summaryLink')?.className) || anchor.className || 'menu-item';

  // 3) Crear enlaces si no existen
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
        // Reinyecta una vez (evitando duplicados)
        setTimeout(() => {
          if (!document.getElementById('dashboardLink') || !document.getElementById('managementMetricsLink')) {
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
