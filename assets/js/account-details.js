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


    