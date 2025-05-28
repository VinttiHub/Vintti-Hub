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
      const tableContainer = document.getElementById('accountTableRows');
      tableContainer.innerHTML = '';

      if (!Array.isArray(data) || data.length === 0) {
        tableContainer.innerHTML = '<div class="table-row"><div colspan="7">No data found</div></div>';
        return;
      }

      data.forEach(item => {
        const htmlRow = `
          <div class="table-row">
            <div>${item.client_name || '—'}</div>
            <div>${item.account_status || '—'}</div>
            <div>${item.account_manager || '—'}</div>
            <div>${item.contract || '—'}</div>
            <div>—</div>
            <div>—</div>
            <div>—</div>
          </div>
        `;
        tableContainer.innerHTML += htmlRow;
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
