document.addEventListener('DOMContentLoaded', () => {
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
  
  function openPopup() {
    document.getElementById('popup').style.display = 'flex';
  }
  
  function closePopup() {
    document.getElementById('popup').style.display = 'none';
  }
  document.querySelectorAll('.table-row').forEach(row => {
    row.addEventListener('click', () => {
      const accountId = row.getAttribute('data-account');
      window.location.href = `account-details.html?id=${accountId}`;
    });
  });
  