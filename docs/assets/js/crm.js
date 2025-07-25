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
  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/data/light')
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
            <td>${item.calculated_status || '—'}</td>
            <td>${item.account_manager || '—'}</td>
            <td>${item.contract || '—'}</td>
            <td>$${item.trr ?? '—'}</td>
            <td>$${item.tsf ?? '—'}</td>
            <td>$${item.tsr ?? '—'}</td>
          </tr>
        `;
        if (showPriorityColumn) {
          htmlRow += `
            <td>
              <select class="priority-select ${item.priority ? 'priority-' + item.priority.toLowerCase() : ''}" data-id="${item.account_id}">
                <option value="">—</option>
                <option value="A" ${item.priority === 'A' ? 'selected' : ''}>A</option>
                <option value="B" ${item.priority === 'B' ? 'selected' : ''}>B</option>
                <option value="C" ${item.priority === 'C' ? 'selected' : ''}>C</option>
              </select>
            </td>
          `;
        }
        tableBody.innerHTML += htmlRow;
        setTimeout(() => {
          const rows = document.querySelectorAll('#accountTableBody tr');
          rows.forEach((row, index) => {
            row.style.opacity = '0';
            row.style.animation = `fadeInUp 0.4s ease forwards`;
            row.style.animationDelay = `${index * 0.05}s`;
          });
        }, 100); // delay para esperar al render
      });
      const currentUserEmail = localStorage.getItem('user_email');
      const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com'];
      const showPriorityColumn = allowedEmails.includes(currentUserEmail);

      // 👇 Inserta el nuevo <th> si aplica
      if (showPriorityColumn) {
        const priorityHeader = document.createElement('th');
        priorityHeader.textContent = 'Priority';
        document.querySelector('#accountTable thead tr').appendChild(priorityHeader);
      }

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
document.querySelectorAll('.priority-select').forEach(select => {
  select.addEventListener('change', async () => {
    const accountId = select.getAttribute('data-id');
    const newPriority = select.value;

    // Quitar clases anteriores
    select.classList.remove('priority-a', 'priority-b', 'priority-c');

    // Agregar clase correspondiente
    if (newPriority === 'A') select.classList.add('priority-a');
    if (newPriority === 'B') select.classList.add('priority-b');
    if (newPriority === 'C') select.classList.add('priority-c');

    try {
      await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ priority: newPriority })
      });
      console.log(`✅ Priority updated for account ${accountId}`);
    } catch (error) {
      console.error('❌ Error updating priority:', error);
    }
  });
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
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com'];

if (summaryLink && allowedEmails.includes(currentUserEmail)) {
  summaryLink.style.display = 'block';
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
