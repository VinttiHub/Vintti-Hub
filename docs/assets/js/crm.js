document.addEventListener('DOMContentLoaded', () => {
  // 🌗 Modo claro / oscuro
  const setTheme = (theme) => {
    if (theme === 'light') {
      document.body.classList.add('light-mode');
      localStorage.setItem('theme', 'light');
    } else {
      document.body.classList.remove('light-mode');
      localStorage.setItem('theme', 'dark');
    }
  };

  setTheme('light');

  setTimeout(() => {
    const lightButtons = document.querySelectorAll('.theme-light');
    const darkButtons = document.querySelectorAll('.theme-dark');

    lightButtons.forEach(btn => btn.addEventListener('click', () => setTheme('light')));
    darkButtons.forEach(btn => btn.addEventListener('click', () => setTheme('dark')));
  }, 0);

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
  fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/data')
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

      data.forEach(item => {
        const htmlRow = `
          <tr data-id="${item.account_id}">
            <td>${item.client_name || '—'}</td>
            <td>${item.account_status || '—'}</td>
            <td>${item.account_manager || '—'}</td>
            <td>${item.contract || '—'}</td>
            <td>—</td>
            <td>—</td>
            <td>—</td>
          </tr>
        `;
        tableBody.innerHTML += htmlRow;
      });

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
        pageLength: 10,
        dom: 'lrtip',
        lengthMenu: [ [10, 20, 50], [10, 20, 50] ],
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
    const response = await fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/accounts', {
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
});

// 🪟 Funciones popup
function openPopup() {
  document.getElementById('popup').style.display = 'flex';
}

function closePopup() {
  document.getElementById('popup').style.display = 'none';
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

  const headerCell = document.querySelectorAll(`#accountTable thead th`)[columnIndex];
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

// Detectar clic en iconos de lupa
document.querySelectorAll('.column-filter').forEach(icon => {
  icon.addEventListener('click', (e) => {
    e.stopPropagation();
    const columnIndex = parseInt(icon.getAttribute('data-column'), 10);
    const table = $('#accountTable').DataTable();
    createColumnFilter(columnIndex, table);
  });
});

// Cerrar dropdown al hacer clic fuera
document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});
