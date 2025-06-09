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
      tab.addEventListener('click', () => {
        activateTab(index);

        // Si la pestaña es "Pipeline", cargar los candidatos
        if (tab.textContent.trim() === 'Pipeline') {
          loadPipelineCandidates();
        }
        if (tab.textContent.trim() === 'Candidates') {
          loadCandidatesForBatch();
        }
      });
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
          console.log("🔎 Client data:", {
  name: data.account_name,
  size: data.account_size,
  state: data.account_state,
  linkedin: data.account_linkedin,
  website: data.account_website,
  mail: data.account_mail,
  about: data.account_about
});
    // Overview section
    document.getElementById('opportunity-id-text').textContent = data.opportunity_id || '—';
    document.getElementById('start-date-input').value = formatDate(data.nda_signature_or_start_date);
    document.getElementById('close-date-input').value = formatDate(data.opp_close_date);
    // Client section
    document.getElementById('client-name-input').value = data.account_name || '';
    document.getElementById('client-size-input').value = data.account_size || '';
    document.getElementById('client-state-input').value = data.account_state || '';
    document.getElementById('client-linkedin-input').value = data.account_linkedin || '';
    document.getElementById('client-website-input').value = data.account_website || '';
    document.getElementById('client-mail-input').value = data.account_mail || '';
    document.getElementById('client-about-textarea').value = data.account_about || '';

    // DETAILS
    document.getElementById('details-opportunity-name').value = data.opp_position_name || '';
    document.getElementById('details-account-name').value = data.account_name || '';
    document.getElementById('details-sales-lead').innerHTML = `<option>${data.opp_sales_lead || ''}</option>`;
    document.getElementById('details-hr-lead').innerHTML = `<option>${data.opp_hr_lead || ''}</option>`;
    document.getElementById('details-model').innerHTML = `<option>${data.opp_model || ''}</option>`;
    
    // JOB DESCRIPTION
    document.getElementById('job-description-textarea').value = data.hr_job_description || '';

    // Signed: si tienes un campo de fecha de firma, calcula días
    if (data.nda_signature_or_start_date) {
      const signedDays = calculateDaysAgo(data.nda_signature_or_start_date);
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
  
  const parsed = Date.parse(dateStr);
  if (isNaN(parsed)) return '';

  const date = new Date(parsed);

  // Aquí se usa getFullYear(), getMonth() + 1, getDate() → muestra la fecha tal como la tienes en el JSON
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');

  return `${year}-${month}-${day}`;
}



function calculateDaysAgo(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffTime = Math.abs(now - date);
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  return diffDays;
}

function loadCandidatesForBatch() {
  const opportunityId = document.getElementById('opportunity-id-text').textContent.trim();
  if (opportunityId === '—' || opportunityId === '') {
    console.error('Opportunity ID not found');
    return;
  }

  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`)
    .then(response => response.json())
    .then(candidates => {
      console.log('🔵 Candidates for Batch:', candidates);

      const batchDetail = document.querySelector('.batch-detail');
      // Limpiar las tarjetas que existan actualmente (excepto el .batch-actions)
      const cardsToRemove = batchDetail.querySelectorAll('.candidate-card-static');
      cardsToRemove.forEach(card => card.remove());

      candidates.forEach(candidate => {
        const card = document.createElement('div');
        card.className = 'candidate-card-static';
        card.innerHTML = `
        <span class="candidate-name">${candidate.name}</span>
        <span class="budget">${candidate.employee_salary ? `$${candidate.employee_salary}` : '$0'}</span>
        <select class="status">
          <option ${candidate.stage === 'Client rejected after' ? 'selected' : ''}>Client rejected after</option>
          <option ${candidate.stage === 'Client Hired' ? 'selected' : ''}>Client Hired</option>
          <option ${candidate.stage === 'En proceso con Cliente' ? 'selected' : ''}>En proceso con Cliente</option>
          <option ${candidate.stage === 'Primera entrevista' ? 'selected' : ''}>Primera entrevista</option>
          <option ${candidate.stage === 'Contactado' ? 'selected' : ''}>Contactado</option>
          <option ${candidate.stage === 'No avanza primera' ? 'selected' : ''}>No avanza primera</option>
          <option ${(candidate.stage === '(deleted option)' || !candidate.stage) ? 'selected' : ''}>(deleted option)</option>
        </select>
        <button class="comment-btn">💬</button>
        <button class="delete-btn">🗑️</button>
      `;
        batchDetail.appendChild(card);
      });
    })
    .catch(error => {
      console.error('Error loading batch candidates:', error);
    });
}
