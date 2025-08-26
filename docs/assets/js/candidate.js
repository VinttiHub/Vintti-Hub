document.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('light-mode');

  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const tbody = document.getElementById('candidatesTableBody');

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
        tr.dataset.id = candidate.candidate_id || '';

        const phone = candidate.phone ? String(candidate.phone).replace(/\D/g, '') : '';
        const linkedin = candidate.linkedin || '';

        const condition = candidate.condition || 'unhired';
        const chipClass = {
          active:   'status-active',
          inactive: 'status-inactive',
          unhired:  'status-unhired'
        }[condition] || 'status-unhired';

        tr.innerHTML = `
          <td class="condition-cell"><span class="status-chip ${chipClass}">${condition}</span></td>
          <td>${candidate.name || '—'}</td>
          <td>${candidate.country || '—'}</td>
          <td>
            ${phone
              ? `<button class="icon-button whatsapp" onclick="event.stopPropagation(); window.open('https://wa.me/${phone}', '_blank')">
                  <i class='fab fa-whatsapp'></i>
                </button>`
              : '—'}
          </td>
          <td>
            ${linkedin
              ? `<button class="icon-button linkedin" onclick="event.stopPropagation(); window.open('${linkedin}', '_blank')">
                  <i class='fab fa-linkedin-in'></i>
                </button>`
              : '—'}
          </td>
        `;
        frag.appendChild(tr);
      }

      tbody.replaceChildren(frag);

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

      const dataTableLength = document.querySelector('.dataTables_length');
      const wrapper = document.getElementById('datatable-wrapper');
      if (dataTableLength && wrapper) wrapper.appendChild(dataTableLength);

      const searchInput = document.getElementById('searchByName');
      let t;
      searchInput.addEventListener('input', function () {
        clearTimeout(t);
        const v = this.value;
        t = setTimeout(() => table.column(1).search(v).draw(), 150);
      });
    })
    .catch(err => console.error('❌ Error al obtener candidatos:', err));

  // Navegación por fila
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

  // Sidebar
  const sidebar = document.querySelector('.sidebar');
  const mainContent = document.querySelector('.main-content');
  const toggleButton = document.getElementById('sidebarToggle');
  const toggleIcon = document.getElementById('sidebarToggleIcon');

  const savedState = localStorage.getItem('sidebarHidden') === 'true';
  if (savedState) {
    sidebar.classList.add('custom-sidebar-hidden');
    mainContent.classList.add('custom-main-expanded');
    toggleIcon.classList.remove('fa-chevron-left');
    toggleIcon.classList.add('fa-chevron-right');
    toggleButton.style.left = '12px';
  } else {
    toggleButton.style.left = '220px';
  }

  toggleButton.addEventListener('click', () => {
    const isHidden = sidebar.classList.toggle('custom-sidebar-hidden');
    mainContent.classList.toggle('custom-main-expanded', isHidden);
    toggleIcon.classList.toggle('fa-chevron-left', !isHidden);
    toggleIcon.classList.toggle('fa-chevron-right', isHidden);
    toggleButton.style.left = isHidden ? '12px' : '220px';
    localStorage.setItem('sidebarHidden', isHidden);
  });

  const summaryLink = document.getElementById('summaryLink');
  const currentUserEmail = localStorage.getItem('user_email');
  if (summaryLink && allowedEmails.includes(currentUserEmail)) summaryLink.style.display = 'block';

  // ---------------- helpers Condition ----------------
  async function kickoffConditionResolve(tableInstance) {
    const rows = Array.from(document.querySelectorAll('#candidatesTableBody tr'));
    const tasks = rows.map(tr => async () => {
      const id = tr.dataset.id;
      const cell = tr.querySelector('.condition-cell');
      if (!id || !cell) return;

      try {
        const hire = await fetchHireDates(id);
        const start = hire?.start_date || hire?.[0]?.start_date || null;
        const end   = hire?.end_date   || hire?.[0]?.end_date   || null;

        const condition = !start ? 'unhired' : (end ? 'inactive' : 'active');
        renderCondition(cell, condition);

        // (Opcional) actualizar DataTables internamente para filtros/búsquedas futuras
        // Busca índice de la fila en DataTables y sincroniza la columna 0
        const rowIdx = tableInstance.row(tr).index();
        if (rowIdx != null && rowIdx >= 0) {
          tableInstance.cell(rowIdx, 0).data(cell.innerHTML);
        }
      } catch (e) {
        // En error, mostrar "unhired"
        renderCondition(cell, 'unhired');
      }
    });

    await runWithConcurrency(tasks, 8); // limita concurrencia para no saturar la red
  }

  async function fetchHireDates(candidateId) {
    // Preferimos un GET que ya usas para PATCH: /candidates/:id/hire
    // Debe devolver al menos { start_date, end_date } o []/{} si no hay registro
    try {
      const r = await fetch(`${API_BASE}/candidates/${candidateId}/hire`, { method: 'GET' });
      if (!r.ok) return null;
      return await r.json();
    } catch {
      return null;
    }
  }

  function renderCondition(cell, condition) {
    const cls = {
      active: 'status-active',
      inactive: 'status-inactive',
      unhired: 'status-unhired'
    }[condition] || 'status-unhired';

    cell.innerHTML = `<span class="status-chip ${cls}">${condition}</span>`;
  }

  async function runWithConcurrency(tasks, limit) {
    let i = 0;
    const workers = new Array(limit).fill(0).map(async () => {
      while (i < tasks.length) {
        const t = tasks[i++];
        await t();
      }
    });
    await Promise.all(workers);
  }
});

// ===== Filtros tipo Excel (tu código tal cual) =====
function createColumnFilter(columnIndex, table) {
  document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());

  const columnData = table
    .column(columnIndex)
    .data()
    .toArray()
    .map(item => (item || '').toString().trim())
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
    checkbox.value = value.replace(/<[^>]*>/g, ''); // limpia HTML
    label.appendChild(checkbox);
    label.append(' ' + checkbox.value);
    checkboxContainer.appendChild(label);
  });

  container.appendChild(checkboxContainer);

  const headerCell = document.querySelectorAll(`#candidatesTable thead th`)[columnIndex];
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

// Cerrar dropdown si haces clic fuera
document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});
(() => {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  // Quienes ven Summary
  const summaryAllowed = [
    'agustin@vintti.com',
    'bahia@vintti.com',
    'angie@vintti.com',
    'lara@vintti.com'
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
