document.addEventListener('DOMContentLoaded', () => {
  // ✅ Mover esta función arriba
  const setTheme = (theme) => {
    if (theme === 'light') {
      document.body.classList.add('light-mode');
      localStorage.setItem('theme', 'light');
    } else {
      document.body.classList.remove('light-mode');
      localStorage.setItem('theme', 'dark');
    }
  };

  // ✅ Aplica el tema guardado al cargar
  const savedTheme = localStorage.getItem('theme') || 'dark';
  setTheme(savedTheme);

  // ✅ Espera a que todo el DOM esté listo y los íconos existan
  setTimeout(() => {
    const lightButtons = document.querySelectorAll('.theme-light');
    const darkButtons = document.querySelectorAll('.theme-dark');

    lightButtons.forEach(btn => btn.addEventListener('click', () => setTheme('light')));
    darkButtons.forEach(btn => btn.addEventListener('click', () => setTheme('dark')));
  }, 0);

  // ✅ Filtros (si existen)
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
});

// ✅ Otras funciones
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
  // Aquí reemplaza el alert con lógica de carga dinámica si tienes HTML para las otras secciones
}
document.addEventListener('DOMContentLoaded', () => {
  // ...todo lo que ya tienes...

  // 📦 Fetch para oportunidades
  fetch('https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities')
    .then(response => response.json())
    .then(data => {
      const container = document.getElementById('opportunityTableBody');
      container.innerHTML = ''; // Limpia antes de agregar

      if (!Array.isArray(data) || data.length === 0) {
        container.innerHTML = `<div class="table-row"><div colspan="9">No data available</div></div>`;
        return;
      }

      data.forEach(opp => {
        const row = document.createElement('div');
        row.className = 'table-row';
        row.onclick = () => openOpportunity(opp.id || ''); // Cambia esto si el ID tiene otro nombre

        row.innerHTML = `
          <div>${opp.opp__stage || '—'}</div>
          <div>${opp.account__id || '—'}</div>
          <div>${opp.opp__position__name || '—'}</div>
          <div>—</div>
          <div>${opp.opp__model || '—'}</div>
          <div>${opp.opp__sales__lead || '—'}</div>
          <div>${opp.opp__hr__lead || '—'}</div>
          <div>${opp.opp__comments || '—'}</div>
          <div>—</div>
        `;
        container.appendChild(row);
      });
    })
    .catch(err => {
      console.error('Error fetching opportunities:', err);
    });
});
