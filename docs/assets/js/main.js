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

  fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities')
    .then(response => response.json())
    .then(data => {
      const tbody = document.getElementById('opportunityTableBody');
      tbody.innerHTML = '';

      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9">No data available</td></tr>`;
        return;
      }

      data.forEach(opp => {
        const row = `
          <tr onclick="openOpportunity('${opp.opp_id || ''}')">
            <td>${opp.opp_stage || '—'}</td>
            <td>${opp.account_id || '—'}</td>
            <td>${opp.opp_position_name || '—'}</td>
            <td>—</td>
            <td>${opp.opp_model || '—'}</td>
            <td>${opp.opp_sales_lead || '—'}</td>
            <td>${opp.opp_hr_lead || '—'}</td>
            <td>${opp.opp_comments || '—'}</td>
            <td>—</td>
          </tr>
        `;
        tbody.innerHTML += row;
      });

      // Inicializa DataTables
      const table = $('#opportunityTable').DataTable({
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
document.getElementById('opportunityTable').addEventListener('click', function(e) {
  const target = e.target.closest('.column-filter');
  if (target) {
    e.preventDefault();
    e.stopPropagation();
    const columnIndex = parseInt(target.getAttribute('data-column'), 10);
    const table = $('#opportunityTable').DataTable();
    createColumnFilter(columnIndex, table);
  }
});


    })
    .catch(err => {
      console.error('Error fetching opportunities:', err);
    });
});

function openPopup() {
  document.getElementById('popup').style.display = 'flex';
}

function closePopup() {
  document.getElementById('popup').style.display = 'none';
}

function openOpportunity(id) {
  window.location.href = `opportunity-detail.html?id=${id}`;
}

function navigateTo(section) {
  alert(`Navigation to "${section}" would happen here.`);
}

// 🔍 Filtro por columna con múltiples checkboxes
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

  const headerCell = document.querySelectorAll(`#opportunityTable thead th`)[columnIndex];
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

// ✅ Cierra dropdowns si haces clic fuera
document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});
