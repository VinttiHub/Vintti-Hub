document.addEventListener('DOMContentLoaded', () => {
  // Tema claro/oscuro
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  document.body.classList.add((savedTheme === 'dark' || (!savedTheme && prefersDark)) ? 'dark-mode' : 'light-mode');

  // Tabs
  const tabs = document.querySelectorAll('.tab-btn');
  const contents = document.querySelectorAll('.tab-content');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.getAttribute('data-tab');
      contents.forEach(c => {
        c.classList.remove('active');
        if (c.id === target) c.classList.add('active');
      });
    });
  });

  // Accordion
  document.querySelectorAll('.accordion-header').forEach(header => {
    header.addEventListener('click', () => {
      const section = header.parentElement;
      section.classList.toggle('open');
    });
  });

  // Expandable rows
  document.querySelectorAll('.expand-btn').forEach(button => {
    button.addEventListener('click', () => {
      const table = button.closest('table');
      const isOpen = button.classList.toggle('opened');
      const toggleCells = table.querySelectorAll('.hidden-column');
      toggleCells.forEach(cell => {
        cell.style.display = isOpen ? 'table-cell' : 'none';
      });
    });
  });

  // Cargar datos
  const id = getIdFromURL();
  if (!id) return;

  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/accounts/${id}`)
    .then(res => res.json())
    .then(data => {
      fillAccountDetails(data);
      loadAssociatedOpportunities(id);
      loadCandidates(id);
    })
    .catch(err => {
      console.error('Error fetching accounts details:', err);
    });
});

function loadAssociatedOpportunities(accountId) {
  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities`)
    .then(res => res.json())
    .then(data => {
      console.log("Oportunidades asociadas:", data);
      fillOpportunitiesTable(data);
    })
    .catch(err => {
      console.error("Error cargando oportunidades asociadas:", err);
    });
}
function fillAccountDetails(data) {
  const container = document.querySelector('.grid-two-cols');
  container.innerHTML = `
    <p><strong>Name:</strong> ${data.client_name || '—'}</p>
    <p><strong>Size:</strong> ${data.size || '—'}</p>
    <p><strong>Timezone:</strong> ${data.timezone || '—'}</p>
    <p><strong>State:</strong> ${data.state || '—'}</p>
    <p><strong>LinkedIn:</strong> <a href="${data.linkedin}" target="_blank">${data.linkedin || '—'}</a></p>
    <p><strong>Website:</strong> <a href="${data.website}" target="_blank">${data.website || '—'}</a></p>
    <p><strong>Contract:</strong> ${data.contract || '—'}</p>
    <p><strong>Total Staffing Fee:</strong> —</p>
    <p><strong>Total Staffing Revenue:</strong> —</p>
  `;
}

function fillOpportunitiesTable(opportunities) {
  const tbody = document.querySelector('#overview .accordion-section:nth-of-type(2) tbody');
  tbody.innerHTML = '';

  if (!opportunities.length) {
    tbody.innerHTML = `<tr><td colspan="3">No opportunities found</td></tr>`;
    return;
  }

  opportunities.forEach(opp => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${opp.opp_position_name || '—'}</td>
      <td>${opp.opp_stage || '—'}</td>
      <td>${opp.candidate_name || '—'}</td>
    `;
    tbody.appendChild(row);
  });
}
function loadCandidates(accountId) {
  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities/candidates`)
    .then(res => res.json())
    .then(data => {
      console.log("Candidates asociados:", data);
      fillCandidatesCards(data);
      fillEmployeesTables(data);
    })
    .catch(err => {
      console.error("Error cargando candidates asociados:", err);
    });
}
function fillCandidatesCards(candidates) {
  const staffingContainer = document.querySelector('#overview .accordion-section:nth-of-type(3) .card-grid');
  const recruitingContainer = document.querySelector('#overview .accordion-section:nth-of-type(4) .card-grid');

  staffingContainer.innerHTML = '';   // Limpiar
  recruitingContainer.innerHTML = '';

  if (!candidates.length) return;

  candidates.forEach(candidate => {
    const card = document.createElement('div');
    card.classList.add('info-card', 'square');
    card.innerHTML = `
      <div class="info-title">👤 ${candidate.name || '—'}</div>
      <div class="info-details">
        <div><strong>Revenue:</strong> $${candidate.employee_revenue || '—'}</div>
        <div><strong>Fee:</strong> $${candidate.employee_fee || '—'}</div>
        <div><strong>Salary:</strong> $${candidate.employee_salary || '—'}</div>
        <div><strong>Type:</strong> ${candidate.employee_type || '—'}</div>
      </div>
    `;

    // Según peoplemodel lo metemos en el contenedor correcto:
    if (candidate.opp_model === 'Staffing') {
      staffingContainer.appendChild(card);
    } else if (candidate.opp_model === 'Recruiting') {
      recruitingContainer.appendChild(card);
    }
  });
}

function fillEmployeesTables(candidates) {
  const staffingTableBody = document.querySelector('#employees .card:nth-of-type(1) tbody');
  const recruitingTableBody = document.querySelector('#employees .card:nth-of-type(2) tbody');

  staffingTableBody.innerHTML = '';   // Limpiar
  recruitingTableBody.innerHTML = '';

  if (!candidates.length) return;

  candidates.forEach(candidate => {
    // Crear fila de tabla:
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${candidate.status || '—'}</td>
      <td>${candidate.name || '—'}</td>
      <td>${candidate.startingdate || '—'}</td>
      <td>${candidate.enddate || '—'}</td>
      <td>${candidate.opportunity_id || '—'}</td>
      <td>$${candidate.employee_fee ?? '—'}</td>
      <td>$${candidate.employee_salary ?? '—'}</td>
      <td>$${candidate.employee_revenue ?? '—'}</td>
      <td class="toggle-col-btn"><button class="expand-btn">＋</button></td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
      <td class="hidden-column">—</td>
    `;

    // Según peoplemodel lo metemos en la tabla correcta:
    if (candidate.opp_model === 'Staffing') {
      staffingTableBody.appendChild(row);
    } else if (candidate.opp_model === 'Recruiting') {
      recruitingTableBody.appendChild(row);
    }
  });

  // Re-asignar eventos a los botones expand-btn:
  document.querySelectorAll('.expand-btn').forEach(button => {
    button.addEventListener('click', () => {
      const table = button.closest('table');
      const isOpen = button.classList.toggle('opened');
      
      const toggleCells = table.querySelectorAll('.hidden-column');
      toggleCells.forEach(cell => {
        cell.style.display = isOpen ? 'table-cell' : 'none';
      });
    });
  });
}
