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

  const savedTheme = localStorage.getItem('theme') || 'dark';
  setTheme(savedTheme);

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
          <tr>
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
      $('#accountTable').DataTable({
  responsive: true,
  pageLength: 10,
  dom: 'Bfrtip',
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
});

// 🪟 Funciones popup
function openPopup() {
  document.getElementById('popup').style.display = 'flex';
}

function closePopup() {
  document.getElementById('popup').style.display = 'none';
}
