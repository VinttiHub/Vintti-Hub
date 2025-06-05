document.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('light-mode');

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

  fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates')
    .then(response => response.json())
    .then(data => {
      const tbody = document.getElementById('candidatesTableBody');
      tbody.innerHTML = '';

      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5">No data available</td></tr>`;
        return;
      }

      let rows = '';
      data.forEach(candidate => {
        rows += `
          <tr onclick="goToDetails()">
            <td>Candidate</td>
            <td>${candidate.Name || candidate.name || '—'}</td>
            <td>${candidate.country || '—'}</td>
            <td><button class="whatsapp" onclick="event.stopPropagation(); window.open('https://wa.me/${candidate.phone}', '_blank')">Contact</button></td>
            <td><button class="linkedin" onclick="event.stopPropagation(); window.open('${candidate.linkedin}', '_blank')">LinkedIn</button></td>
          </tr>
        `;
      });

      tbody.innerHTML = rows;

      // Esperar a que las filas se rendericen antes de inicializar DataTable
      setTimeout(() => {
        const table = $('#candidatesTable').DataTable({
          responsive: true,
          pageLength: 10,
          dom: 'lrtip',
          lengthMenu: [[10, 20, 50], [10, 20, 50]],
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

        document.getElementById('candidatesTable').addEventListener('click', function (e) {
          const target = e.target.closest('.column-filter');
          if (target) {
            e.preventDefault();
            e.stopPropagation();
            const columnIndex = parseInt(target.getAttribute('data-column'), 10);
            createColumnFilter(columnIndex, table);
          }
        });
      }, 50);
    })
    .catch(err => {
      console.error('❌ Error al obtener candidatos:', err);
    });
});

function goToDetails() {
  window.location.href = "candidate-details.html";
}

function setLightMode() {
  document.body.classList.add("light-mode");
  localStorage.setItem("theme", "light");
}

function setDarkMode() {
  document.body.classList.remove("light-mode");
  localStorage.setItem("theme", "dark");
}

// Filtros tipo Excel con checkboxes
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

// Cierra los filtros si haces clic fuera
document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});

