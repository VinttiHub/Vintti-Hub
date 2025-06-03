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

  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates/${id}`)
    .then(res => res.json())
    .then(data => {
      fillAccountDetails(data);  // función para llenar el HTML
    })
    .catch(err => {
      console.error('Error fetching candidate details:', err);
    });
});
function fillAccountDetails(data) {
  const container = document.querySelector('.grid-two-cols');

  container.innerHTML = `
    <p><strong>Name:</strong> ${data.client_name || '—'}</p>
    <p><strong>Size:</strong> ${data.company_size || '—'}</p>
    <p><strong>Timezone:</strong> ${data.timezone || '—'}</p>
    <p><strong>Location:</strong> ${data.location || '—'}</p>
    <p><strong>State:</strong> ${data.state || '—'}</p>
    <p><strong>Active Time:</strong> ${data.active_time || '—'}</p>
    <p><strong>LinkedIn:</strong> <a href="${data.linkedin}" target="_blank">${data.linkedin || '—'}</a></p>
    <p><strong>Website:</strong> <a href="${data.website}" target="_blank">${data.website || '—'}</a></p>
    <p><strong>Contract:</strong> ${data.contract || '—'}</p>
    <p><strong>Referral:</strong> ${data.referral || '—'}</p>
    <p><strong>Total Staffing Fee:</strong> ${data.total_fee || '—'}</p>
    <p><strong>Total Staffing Revenue:</strong> ${data.total_revenue || '—'}</p>
    <p><strong>Staffing Discount:</strong> ${data.discount || '—'}</p>
    <p><strong>Qualified Lead:</strong> ${data.qualified_lead || '—'}</p>
  `;
}

    