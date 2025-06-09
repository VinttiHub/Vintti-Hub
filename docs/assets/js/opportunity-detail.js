document.addEventListener('DOMContentLoaded', () => {
  const savedTheme = localStorage.getItem('theme') || 'dark';
  setTheme(savedTheme);

  const tabs = document.querySelectorAll('.nav-item');
  const sections = document.querySelectorAll('.detail-section');
  const indicator = document.querySelector('.nav-indicator');

  function activateTab(index) {
    tabs.forEach((t, i) => {
      t.classList.toggle('active', i === index);
      sections[i].classList.toggle('hidden', i !== index);
    });

    const tab = tabs[index];
    indicator.style.left = `${tab.offsetLeft}px`;
    indicator.style.width = `${tab.offsetWidth}px`;
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => activateTab(index));
  });

  activateTab(0);

  // ✅ Card toggle
  document.querySelectorAll('.card-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.overview-card');
      card.classList.toggle('open');
    });
  });

  // ✅ Copy button
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.parentElement.querySelector('span').innerText;
      navigator.clipboard.writeText(id).then(() => {
        btn.title = "Copied!";
        setTimeout(() => btn.title = "Copy to clipboard", 2000);
      });
    });
  });

  // ✅ Cargar datos reales de la oportunidad
  loadOpportunityData();
});

function setTheme(theme) {
  if (theme === 'light') {
    document.body.classList.add('light-mode');
    localStorage.setItem('theme', 'light');
  } else {
    document.body.classList.remove('light-mode');
    localStorage.setItem('theme', 'dark');
  }
}

async function loadOpportunityData() {
  const params = new URLSearchParams(window.location.search);
  const opportunityId = params.get('id');
  if (!opportunityId) return;

  try {
    const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}`);
    const data = await res.json();

    console.log('Opportunity Data:', data); // te ayuda a debuggear

    // Opportunity ID
    document.getElementById('opportunity-id-text').textContent = data.opportunity_id || '—';

    // Start Date
    document.getElementById('start-date-input').value = formatDate(data.ida_signature_or_start_date);

    // Closed Date
    document.getElementById('close-date-input').value = formatDate(data.opp_close_date);

    // Signed: si tienes un campo de fecha de firma, calcula días
    if (data.ida_signature_or_start_date) {
      const signedDays = calculateDaysAgo(data.ida_signature_or_start_date);
      document.getElementById('signed-tag').textContent = `${signedDays} days ago`;
    } else {
      document.getElementById('signed-tag').textContent = '—';
    }

  } catch (err) {
    console.error("Error loading opportunity:", err);
  }
}
function formatDate(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  if (isNaN(date)) return ''; // por si el backend devuelve formato raro
  return date.toISOString().slice(0, 10); // YYYY-MM-DD (puedes cambiar formato si quieres)
}

function calculateDaysAgo(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffTime = Math.abs(now - date);
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  return diffDays;
}

