
document.addEventListener('DOMContentLoaded', () => {
  document.body.classList.add('light-mode');
  const toggleButton = document.getElementById('toggleFilters');
  const filtersCard = document.getElementById('filtersCard');

  if (toggleButton && filtersCard) {
    toggleButton.addEventListener('click', () => {
      const isExpanded = filtersCard.classList.contains('expanded');
      filtersCard.classList.toggle('expanded', !isExpanded);
      filtersCard.classList.toggle('hidden', isExpanded);
      toggleButton.textContent = isExpanded ? 'ðŸ” Filters' : 'âŒ Close Filters';
    });
  }

  fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities')
    .then(response => response.json())
    .then(data => {
      const tbody = document.getElementById('opportunityTableBody');
      tbody.innerHTML = '';

      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9">No data available</td></tr>';
        return;
      }

      data.forEach(opp => {
        const row = `
          <tr onclick="openOpportunity('${opp.opportunity_id || ''}')">
            <td>${opp.opp_stage || 'â€”'}</td>
            <td>${opp.account_id || 'â€”'}</td>
            <td>${opp.opp_position_name || 'â€”'}</td>
            <td>â€”</td>
            <td>${opp.opp_model || 'â€”'}</td>
            <td>${opp.opp_sales_lead || 'â€”'}</td>
            <td>${opp.opp_hr_lead || 'â€”'}</td>
            <td>${opp.opp_comments || 'â€”'}</td>
            <td>â€”</td>
          </tr>
        `;
        tbody.innerHTML += row;
      });

      const table = $('#opportunityTable').DataTable({
        responsive: true,
        pageLength: 10,
        dom: 'lrtip',
        lengthMenu: [[10, 20, 50], [10, 20, 50]],
        language: {
          search: "ðŸ” Buscar:",
          lengthMenu: "Mostrar _MENU_ registros por pÃ¡gina",
          zeroRecords: "No se encontraron resultados",
          info: "Mostrando _START_ a _END_ de _TOTAL_ registros",
          paginate: {
            first: "Primero",
            last: "Ãšltimo",
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

  const headerCell = document.querySelectorAll('#opportunityTable thead th')[columnIndex];
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

document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});

document.getElementById('login-form')?.addEventListener('submit', async function (e) {
  e.preventDefault();

  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;

  try {
    const response = await fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ email, password })
    });

    const data = await response.json();

    if (response.ok && data.success) {
      const nickname = data.nickname;
      document.getElementById('personalized-greeting').textContent = `Hey ${nickname}, `;
      document.getElementById('login-container').style.display = 'none';
      document.getElementById('welcome-container').style.display = 'block';
    } else {
      alert(data.message || 'Correo o contraseÃ±a incorrectos.');
    }
  } catch (err) {
    console.error('Error en login:', err);
    alert('OcurriÃ³ un error inesperado. Intenta de nuevo mÃ¡s tarde.');
  }
});

document.getElementById('createOpportunityForm')?.addEventListener('submit', async function (e) {
  e.preventDefault();

  const form = e.target;
  const formData = {
    client_name: form.client_name.value.trim(),
    opp_model: form.opp_model.value,
    position_name: form.position_name.value.trim(),
    sales_lead: form.sales_lead.value,
    opp_type: form.opp_type.value
  };

  try {
    const response = await fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formData)
    });

    const result = await response.json();

    if (response.ok) {
      alert('Opportunity created successfully!');
      closePopup();
      location.reload();
    } else {
      alert('Error: ' + (result.message || 'Unexpected error'));
    }
  } catch (err) {
    console.error('Error creating opportunity:', err);
    alert('Connection error. Please try again.');
  }
});

fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/users')
  .then(response => response.json())
  .then(users => {
    const select = document.getElementById('sales_lead');
    if (!select) return;
    select.innerHTML = '<option disabled selected>Select a user</option>';
    users.forEach(user => {
      const option = document.createElement('option');
      option.value = user;
      option.textContent = user;
      select.appendChild(option);
    });
  })
  .catch(err => {
    console.error('Error loading users:', err);
  });

fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/accounts')
  .then(response => response.json())
  .then(accounts => {
    const datalist = document.getElementById('accountList');
    if (!datalist) return;
    accounts.forEach(account => {
      const option = document.createElement('option');
      option.value = account.account_name;
      datalist.appendChild(option);
    });
  })
  .catch(err => {
    console.error('Error loading accounts:', err);
  });