document.addEventListener('DOMContentLoaded', () => {
    const toggleButton = document.getElementById('toggleFilters');
    const filtersCard = document.getElementById('filtersCard');
  
    toggleButton.addEventListener('click', () => {
      const isExpanded = filtersCard.classList.contains('expanded');
  
      if (isExpanded) {
        filtersCard.classList.remove('expanded');
        filtersCard.classList.add('hidden');
        toggleButton.textContent = '🔍 Filters';
      } else {
        filtersCard.classList.add('expanded');
        filtersCard.classList.remove('hidden');
        toggleButton.textContent = '❌ Close Filters';
      }
    });
  });
  // Popup logic
function openPopup() {
  document.getElementById('popup').style.display = 'flex';
}

function closePopup() {
  document.getElementById('popup').style.display = 'none';
}
function openOpportunity(id) {
  window.location.href = `opportunity-detail.html?id=${id}`;
}