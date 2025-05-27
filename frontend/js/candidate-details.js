// candidate-details.js

document.addEventListener("DOMContentLoaded", () => {
  const savedTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);
});

// Código para tabs (no cambia):
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const tabId = tab.dataset.tab;

    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    tab.classList.add('active');
    document.getElementById(tabId).classList.add('active');
  });
});
