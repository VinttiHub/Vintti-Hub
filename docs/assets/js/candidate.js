document.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('light-mode');

  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/light')
    .then(response => response.json())
    .then(data => {
      const tbody = document.getElementById('candidatesTableBody');
      tbody.innerHTML = '';

      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5">No data available</td></tr>`;
        return;
      }

      let delay = 0;
      data.forEach(candidate => {
        const tr = document.createElement('tr');
        tr.dataset.id = candidate.candidate_id || '';
        tr.innerHTML = `
          <td class="${!candidate.condition ? 'empty-cell' : ''}">
            ${candidate.condition || '-'}
          </td>
          <td>${candidate.full_name || candidate.name || candidate.Name || '—'}</td>
          <td>${candidate.country || '—'}</td>
          <td>
            <button class="icon-button whatsapp" title="Enviar mensaje"
              onclick="event.stopPropagation(); window.open('https://wa.me/${candidate.phone}', '_blank')">
              <i class='fab fa-whatsapp'></i>
            </button>
          </td>
          <td>
            <button class="icon-button linkedin" title="Ver perfil LinkedIn"
              onclick="event.stopPropagation(); window.open('${candidate.linkedin}', '_blank')">
              <i class='fab fa-linkedin-in'></i>
            </button>
          </td>
          <td>${candidate.employee || '—'}</td>
        `;
        tr.style.animation = `fadeInRow 0.4s ease both`;
        tr.style.animationDelay = `${delay}s`;
        delay += 0.07;
        tbody.appendChild(tr);
      });


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
          paginate: {
            first: "Primero",
            last: "Último",
            next: "Siguiente",
            previous: "Anterior"
          }
        }
      });
      // Mover el control de "Mostrar X registros" al wrapper
      const lengthControl = document.querySelector('.dataTables_length');
      const wrapper = document.getElementById('datatable-wrapper');
      if (lengthControl && wrapper) {
        wrapper.appendChild(lengthControl);
      }
      // Hacer clic en fila -> ir a detalles
      document.getElementById('candidatesTableBody').addEventListener('click', function (e) {
        const row = e.target.closest('tr');
        if (!row) return;

        const id = row.getAttribute('data-id');
        if (id) {
          const clickSound = document.getElementById('click-sound');
          if (clickSound) {
            clickSound.play();
            setTimeout(() => {
              window.location.href = `candidate-details.html?id=${id}`;
            }, 200);
          } else {
            window.location.href = `candidate-details.html?id=${id}`;
          }
        }
      });

      // Filtros tipo Excel (activar después de DataTables)
      document.querySelectorAll('.column-filter').forEach(icon => {
        const columnIndex = parseInt(icon.getAttribute('data-column'), 10);
        if ([2, 3, 4].includes(columnIndex)) return; // omitimos Country, Whatsapp, LinkedIn
        icon.addEventListener('click', (e) => {
          e.stopPropagation();
          createColumnFilter(columnIndex, table);
        });
      });
      document.getElementById('searchByName').addEventListener('input', function () {
      table.column(1).search(this.value).draw(); // columna 1 = full_name
    });
    })
    .catch(err => {
      console.error('❌ Error al obtener candidatos:', err);
    });
// 🟣 SIDEBAR TOGGLE CON MEMORIA
const sidebar = document.querySelector('.sidebar');
const mainContent = document.querySelector('.main-content');
const toggleButton = document.getElementById('sidebarToggle');
const toggleIcon = document.getElementById('sidebarToggleIcon');

// Leer estado anterior
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
  localStorage.setItem('sidebarHidden', isHidden); // 🧠 guardar estado
});
const summaryLink = document.getElementById('summaryLink');
const currentUserEmail = localStorage.getItem('user_email');
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com'];

if (summaryLink && allowedEmails.includes(currentUserEmail)) {
  summaryLink.style.display = 'block';
}








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
