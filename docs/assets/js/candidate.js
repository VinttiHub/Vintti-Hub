document.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('light-mode');

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
          <tr data-id="${candidate.candidate_id || ''}">
            <td>${candidate.condition || 'Candidate'}</td>
            <td>${candidate.Name || candidate.name || '—'}</td>
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
          </tr>
        `;
      });

      tbody.innerHTML = rows;

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

      // Hacer clic en fila -> ir a detalles
    document.querySelectorAll('#candidatesTableBody tr').forEach(row => {
      row.addEventListener('click', () => {
        const id = row.getAttribute('data-id');
        if (id) {
          const clickSound = document.getElementById('click-sound');
          if (clickSound) {
            clickSound.play();
            setTimeout(() => {
              window.location.href = `candidate-details.html?id=${id}`;
            }, 200); // Espera 200 ms para dejar sonar el clic
          } else {
            window.location.href = `candidate-details.html?id=${id}`;
          }
        }
      });
    });


      // Filtros tipo Excel (activar después de DataTables)
      document.querySelectorAll('.column-filter').forEach(icon => {
        icon.addEventListener('click', (e) => {
          e.stopPropagation();
          const columnIndex = parseInt(icon.getAttribute('data-column'), 10);
          createColumnFilter(columnIndex, table);
        });
      });
    })
    .catch(err => {
      console.error('❌ Error al obtener candidatos:', err);
    });
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
