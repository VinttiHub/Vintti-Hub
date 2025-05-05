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
