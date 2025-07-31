document.addEventListener('DOMContentLoaded', () => {
document.body.style.backgroundColor = 'var(--bg)';

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
  function getIdFromURL() {
    const params = new URLSearchParams(window.location.search);
    return params.get('id');
  }
  // Cargar datos
  const id = getIdFromURL();
  if (!id) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}`)
    .then(res => res.json())
    .then(data => {
      fillAccountDetails(data);
      loadAssociatedOpportunities(id);
      loadCandidates(id);
    })
    .catch(err => {
      console.error('Error fetching accounts details:', err);
    });
// Botón de Go Back
const goBackButton = document.getElementById('goBackButton');
if (goBackButton) {
  goBackButton.addEventListener('click', () => {
    if (document.referrer) {
      window.history.back();
    } else {
      window.location.href = '/'; // Cambia por la home si quieres
    }
  });
}
  // Guardar Pain Points al hacer blur
  const painPointsTextarea = document.getElementById('pain-points');
  if (painPointsTextarea) {
    painPointsTextarea.addEventListener('blur', () => {
      const value = painPointsTextarea.value.trim();
      const accountId = getIdFromURL();
      if (!accountId) return;

      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pain_points: value })
      })
      .then(res => {
        if (!res.ok) throw new Error('Error updating pain points');
        console.log('Pain Points updated');
      })
      .catch(err => {
        console.error('Failed to update Pain Points:', err);
      });
    });
  }

const clientNameInput = document.getElementById('account-client-name');
if (clientNameInput) {
  clientNameInput.addEventListener('blur', () => {
    const newName = clientNameInput.value.trim();
    const accountId = getIdFromURL();
    if (!accountId || !newName) return;

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_name: newName })
    })
    .then(res => {
      if (!res.ok) throw new Error('Error updating client name');
      console.log('Client name updated');
    })
    .catch(err => {
      console.error('Failed to update client name:', err);
    });
  });
}






});
function editField(field) {
  const currentLink = document.getElementById(`${field}-link`).href;
  const newLink = prompt(`Enter new ${field} URL:`, currentLink);

  if (!newLink) return;

  // Actualiza el link visualmente
  document.getElementById(`${field}-link`).href = newLink;

  // Obtener el account ID desde la URL
  const accountId = new URLSearchParams(window.location.search).get('id');
  if (!accountId) return;

  const body = { [field]: newLink };

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(res => {
    if (!res.ok) throw new Error('Failed to update');
    console.log(`${field} updated successfully`);
  })
  .catch(err => {
    alert('There was an error updating the link. Please try again.');
    console.error(err);
  });
}
function loadAssociatedOpportunities(accountId) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities`)
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
  document.querySelectorAll('#overview .accordion-content p').forEach(p => {
    if (p.textContent.includes('Name:')) {
      const inputHTML = `<strong>Name:</strong> <input id="account-client-name" class="editable-input" type="text" value="${data.client_name || ''}" placeholder="Not available" />`;
      p.innerHTML = inputHTML;
    } else if (p.textContent.includes('Size:')) {
      p.innerHTML = `<strong>Size:</strong> ${data.size || '—'}`;
    } else if (p.textContent.includes('Timezone:')) {
      p.innerHTML = `<strong>Timezone:</strong> ${data.timezone || '—'}`;
    } else if (p.textContent.includes('State:')) {
      p.innerHTML = `<strong>State:</strong> ${data.state || '—'}`;
    } else if (p.textContent.includes('Contract:')) {
      p.innerHTML = `<strong>Contract:</strong> ${data.contract || '—'}`;
    }
  });

  const linkedinLink = document.getElementById('linkedin-link');
  if (linkedinLink) linkedinLink.href = data.linkedin || '#';

  const websiteLink = document.getElementById('website-link');
  if (websiteLink) websiteLink.href = data.website || '#';
}


function fillOpportunitiesTable(opportunities) {
  const tbody = document.querySelector('#overview .accordion-section:nth-of-type(2) tbody');
  tbody.innerHTML = '';

  if (!opportunities.length) {
    tbody.innerHTML = `<tr><td colspan="3">No opportunities found</td></tr>`;
    return;
  }

  opportunities.forEach(opp => {
    const hireContent = opp.candidate_name
      ? opp.candidate_name
      : `<span class="no-hire">Not hired yet</span>`;

    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${opp.opp_position_name || '—'}</td>
      <td>${opp.opp_stage || '—'}</td>
      <td>${hireContent}</td>
    `;
    tbody.appendChild(row);
  });
}

function loadCandidates(accountId) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities/candidates`)
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
    const formatValue = (val) => {
      return val
        ? `$${val}`
        : `<span class="to-be-filled">Unfilled</span>`;
    };

    card.innerHTML = `
      <div class="info-title">👤 ${candidate.name || '—'}</div>
      <div class="info-details">
        <div><strong>Revenue:</strong> ${formatValue(candidate.employee_revenue)}</div>
        <div><strong>Fee:</strong> ${formatValue(candidate.employee_fee)}</div>
        <div><strong>Salary:</strong> ${formatValue(candidate.employee_salary)}</div>
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
