document.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('light-mode');

  const tbody = document.getElementById('candidatesTableBody');

  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/light')
    .then(r => r.json())
    .then(data => {
      // Limpia y arma TODO en un DocumentFragment (menos reflows)
      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6">No data available</td></tr>`;
        return;
      }

      const frag = document.createDocumentFragment();

      for (const candidate of data) {
        const tr = document.createElement('tr');
        tr.dataset.id = candidate.candidate_id || '';

        const phone = candidate.phone ? String(candidate.phone).replace(/\D/g, '') : '';
        const linkedin = candidate.linkedin || '';

        tr.innerHTML = `
          <td>${candidate.condition || '-'}</td>
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
          <td class="employee-cell">
            ${candidate.employee ? candidate.employee : "<i class='fa-solid fa-xmark gray-x'></i>"}
          </td>
        `;
        frag.appendChild(tr);
      }

      // Un solo reemplazo del tbody
      tbody.replaceChildren(frag);

      // Inicializa DataTable después de inyectar filas
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

      // Mover el selector de registros al contenedor izquierdo
      const dataTableLength = document.querySelector('.dataTables_length');
      const wrapper = document.getElementById('datatable-wrapper');
      if (dataTableLength && wrapper) wrapper.appendChild(dataTableLength);

      // Búsqueda por nombre con debounce (evita recalcular en cada tecla)
      const searchInput = document.getElementById('searchByName');
      let t;
      searchInput.addEventListener('input', function () {
        clearTimeout(t);
        const v = this.value;
        t = setTimeout(() => table.column(1).search(v).draw(), 150);
      });
    })
    .catch(err => console.error('❌ Error al obtener candidatos:', err));

  // ✅ Un solo listener (delegado) PARA TODO el tbody, fuera del bucle
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

  // 🟣 SIDEBAR TOGGLE CON MEMORIA (igual que lo tenías)
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
  const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com'];
  if (summaryLink && allowedEmails.includes(currentUserEmail)) summaryLink.style.display = 'block';
});

// Filtros tipo Excel
function createColumnFilter(columnIndex, table) {
  document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());

  const columnData = table
    .column(columnIndex)
    .data()
    .toArray()
    .map(item => item.trim())
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
