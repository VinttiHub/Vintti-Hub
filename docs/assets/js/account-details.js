document.addEventListener('DOMContentLoaded', () => {
  // Obtener preferencia del usuario y del sistema
  const savedTheme = localStorage.getItem('theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

  // Aplicar el modo adecuado
  if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
    document.body.classList.add('dark-mode');
  } else {
    document.body.classList.add('light-mode');
  }

  // Funcionalidad de pestañas
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
});
document.querySelectorAll('.accordion-header').forEach(header => {
  header.addEventListener('click', () => {
    const section = header.parentElement;
    section.classList.toggle('open');
  });
});
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
document.addEventListener('DOMContentLoaded', () => {
  const id = getIdFromURL();

  if (!id) return;

  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/accounts/${id}`)
    .then(res => res.json())
    .then(data => {
      fillAccountDetails(data);  // función para llenar el HTML
      loadAssociatedOpportunities(id); 
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
    <p><strong>Size:</strong> ${data.Size || '—'}</p>
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
      <td>${opp.position || '—'}</td>
      <td>${opp.stage || '—'}</td>
      <td>${opp.hire || '—'}</td>
    `;
    tbody.appendChild(row);
  });
}


    