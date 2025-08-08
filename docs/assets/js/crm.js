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
      const currentUserEmail = localStorage.getItem('user_email');
      const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 'lara@vintti.com'];
      const showPriorityColumn = allowedEmails.includes(currentUserEmail);
      data.forEach(item => {
      let htmlRow = `
        <tr data-id="${item.account_id}">
          <td>${item.client_name || '—'}</td>
          <td>${item.calculated_status || '—'}</td>
          <td class="muted-cell">${item.account_manager_name ? item.account_manager_name : '<span class="placeholder">No sales lead assigned</span>'}</td>
          <td class="muted-cell">${item.contract ? item.contract : '<span class="placeholder">No hires yet</span>'}</td>
          <td>$${item.trr ?? '—'}</td>
          <td>$${item.tsf ?? '—'}</td>
          <td>$${item.tsr ?? '—'}</td>
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
      htmlRow += `</tr>`;
      tableBody.innerHTML += htmlRow;
      });

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
      // Mover selector de "mostrar X registros por página" al contenedor deseado
const lengthMenu = document.querySelector('#accountTable_length');
const customLengthContainer = document.getElementById('datatable-length-container');
if (lengthMenu && customLengthContainer) {
  customLengthContainer.appendChild(lengthMenu);
}

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

