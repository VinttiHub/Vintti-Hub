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
  // OVERVIEW
document.getElementById('start-date-input').addEventListener('blur', async (e) => {
  await updateOpportunityField('nda_signature_or_start_date', e.target.value);
});

document.getElementById('close-date-input').addEventListener('blur', async (e) => {
  await updateOpportunityField('opp_close_date', e.target.value);
});

// CLIENT
document.getElementById('client-name-input').addEventListener('blur', async (e) => {
  await updateAccountField('client_name', e.target.value);
});

document.getElementById('client-size-input').addEventListener('blur', async (e) => {
  await updateAccountField('size', e.target.value);
});

document.getElementById('client-state-input').addEventListener('blur', async (e) => {
  await updateAccountField('state', e.target.value);
});

document.getElementById('client-linkedin-input').addEventListener('blur', async (e) => {
  await updateAccountField('linkedin', e.target.value);
});

document.getElementById('client-website-input').addEventListener('blur', async (e) => {
  await updateAccountField('website', e.target.value);
});

document.getElementById('client-mail-input').addEventListener('blur', async (e) => {
  await updateAccountField('mail', e.target.value);
});

document.getElementById('client-about-textarea').addEventListener('blur', async (e) => {
  await updateAccountField('comments', e.target.value);
});

// DETAILS
document.getElementById('details-opportunity-name').addEventListener('blur', async (e) => {
  await updateOpportunityField('opp_position_name', e.target.value);
});

document.getElementById('details-sales-lead').addEventListener('change', async (e) => {
  const emailValue = e.target.value; // el value es el email
  console.log('🟡 Sales Lead changed:', emailValue);

  await updateOpportunityField('opp_sales_lead', emailValue);
});

document.getElementById('details-hr-lead').addEventListener('change', async (e) => {
  const emailValue = e.target.value; // el value es el email
  console.log('🟡 HR Lead changed:', emailValue);

  await updateOpportunityField('opp_hr_lead', emailValue);
});

document.getElementById('details-model').addEventListener('change', async (e) => {
  await updateOpportunityField('opp_model', e.target.value);
});
// AI Assistant logic
const aiBtn = document.getElementById('ai-assistant-btn');
const aiPopup = document.getElementById('ai-assistant-popup');
const aiClose = document.getElementById('ai-assistant-close');
const aiGo = document.getElementById('ai-assistant-go');

// Mostrar solo en pestaña "Job Description"
function showAIAssistantButton(tabName) {
  if (tabName === 'Job Description') {
    aiBtn.style.display = 'block';
  } else {
    aiBtn.style.display = 'none';
  }
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => {
    activateTab(index);

    const tabName = tab.textContent.trim();
    showAIAssistantButton(tabName);

    if (tabName === 'Pipeline') loadPipelineCandidates();
if (tabName === 'Candidates') {
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  if (opportunityId && opportunityId !== '—') {
    loadBatchesForOpportunity(opportunityId);
  } else {
    console.error('Opportunity ID is invalid:', opportunityId);
  }
}
  });
});

// Botón abre popup
aiBtn.addEventListener('click', () => {
  aiPopup.classList.remove('hidden');
});

// Botón Close
aiClose.addEventListener('click', () => {
  aiPopup.classList.add('hidden');
});

// Botón Let's Go (por ahora solo cierra popup)
aiGo.addEventListener('click', () => {
  alert('✨ AI Assistant is processing your inputs...');
  aiPopup.classList.add('hidden');
});
// Popup para agregar candidato al batch
document.addEventListener("click", async (e) => {
  if (e.target.classList.contains("btn-add")) {
    const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
    if (!opportunityId || opportunityId === '—') return;

    // Obtener candidatos de la oportunidad
    try {
      const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`);
      const candidates = await res.json();

      // Limpiar resultados anteriores
      const resultsList = document.getElementById("candidateSearchResults");
      resultsList.innerHTML = "";

      candidates.forEach(c => {
        const li = document.createElement("li");
        li.textContent = c.name;
        li.classList.add("search-result-item");
        li.setAttribute("data-candidate-id", c.candidate_id);
        resultsList.appendChild(li);
        li.addEventListener("click", async () => {
  const candidateId = li.getAttribute("data-candidate-id");

  // Buscar el batch_id de la caja donde se hizo clic en “Add Candidate”
  const batchBox = e.target.closest(".batch-box");
  if (!batchBox) return;

  // Buscar el número del batch en el h3
  const batchTitle = batchBox.querySelector("h3").textContent.trim();
  const match = batchTitle.match(/#(\d+)/);
  const batchNumber = match ? parseInt(match[1]) : null;

  if (!batchNumber) {
    alert("Batch number not found");
    return;
  }

  const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");

  try {
    // Llamar al backend para obtener los batch_id de la oportunidad
    const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const data = await res.json();

    // Buscar el batch con ese número
    const selectedBatch = data.find(b => b.batch_number === batchNumber);
    if (!selectedBatch) {
      alert("Batch not found");
      return;
    }

    const patchRes = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates/${candidateId}/batch`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ batch_id: selectedBatch.batch_id })
    });

    if (!patchRes.ok) {
      throw new Error("Failed to update candidate batch");
    }

    alert("✅ Candidate assigned to batch");
    document.getElementById("batchCandidatePopup").classList.add("hidden");

  } catch (err) {
    console.error("Error assigning batch:", err);
    alert("❌ Error assigning candidate to batch");
  }
});
      });

      document.getElementById("batchCandidatePopup").classList.remove("hidden");

      // Filtro dinámico
      const searchInput = document.getElementById("candidateSearchInput");
      searchInput.value = '';
      searchInput.addEventListener("input", () => {
        const term = searchInput.value.toLowerCase();
        document.querySelectorAll(".search-result-item").forEach(item => {
          item.style.display = item.textContent.toLowerCase().includes(term) ? "block" : "none";
        });
      });

    } catch (err) {
      console.error("Error loading candidates for batch:", err);
    }
  }
});

// Cerrar popup
document.getElementById("closeBatchPopup").addEventListener("click", () => {
  document.getElementById("batchCandidatePopup").classList.add("hidden");
});

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
    document.getElementById('opportunity-id-text').setAttribute('data-id', data.opportunity_id);
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
    document.getElementById('details-model').value = data.opp_model || '';
    
    // JOB DESCRIPTION
    document.getElementById('job-description-textarea').value = data.hr_job_description || '';

    // Signed: si tienes un campo de fecha de firma, calcula días
    if (data.nda_signature_or_start_date) {
      const signedDays = calculateDaysAgo(data.nda_signature_or_start_date);
      document.getElementById('signed-tag').textContent = `${signedDays} days ago`;
    } else {
      document.getElementById('signed-tag').textContent = '—';
    }
    // Cargar el select de hire con los candidatos
      try {
        const hireSelect = document.getElementById('hire-select');

        // Llama al endpoint que ya usas para cargar los candidatos del batch
        const resCandidates = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates`);
        const candidates = await resCandidates.json();

        // Limpia el select
        hireSelect.innerHTML = '<option value="">Select Hire...</option>';

        // Llena el select con las opciones
        candidates.forEach(candidate => {
          const option = document.createElement('option');
          option.value = candidate.name;
          option.textContent = candidate.name;
          hireSelect.appendChild(option);
        });

        // Inicializa Choices.js en el select
        const choices = new Choices(hireSelect, {
          searchEnabled: true,
          itemSelectText: '',
          shouldSort: false
        });

      } catch (error) {
        console.error('Error loading hire candidates:', error);
      }
      window.currentAccountId = data.account_id;
        try {
          const resUsers = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/users`);
          const users = await resUsers.json();

          const salesLeadSelect = document.getElementById('details-sales-lead');
          const hrLeadSelect = document.getElementById('details-hr-lead');

          salesLeadSelect.innerHTML = `<option value="">Select Sales Lead...</option>`;
          hrLeadSelect.innerHTML = `<option value="">Select HR Lead...</option>`;

          users.forEach(user => {
            const option1 = document.createElement('option');
            option1.value = user.email_vintti;
            option1.textContent = user.user_name;
            salesLeadSelect.appendChild(option1);

            const option2 = document.createElement('option');
            option2.value = user.email_vintti;
            option2.textContent = user.user_name;
            hrLeadSelect.appendChild(option2);
          });

          // Ahora cruzas: en data.opp_sales_lead y opp_hr_lead tienes el EMAIL → debes setear el value del <select> con ese email:
          salesLeadSelect.value = data.opp_sales_lead || '';
          hrLeadSelect.value = data.opp_hr_lead || '';

        } catch (err) {
          console.error('Error loading users for Sales/HR Lead:', err);
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
async function updateOpportunityField(fieldName, fieldValue) {
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  if (opportunityId === '—' || opportunityId === '') {
    console.error('Opportunity ID not found');
    return;
  }

  const payload = {};
  payload[fieldName] = fieldValue;

  try {
    const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/fields`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      console.error(`Failed to update ${fieldName}`);
    }

  } catch (err) {
    console.error(`Error updating ${fieldName}:`, err);
  }
}

async function updateAccountField(fieldName, fieldValue) {
  const accountId = getAccountId();

  if (!accountId) {
    console.error('Account ID not found');
    return;
  }

  const payload = {};
  payload[fieldName] = fieldValue;

  try {
    const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/accounts/${accountId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      console.error(`Failed to update ${fieldName} in account`);
    }

  } catch (err) {
    console.error(`Error updating ${fieldName} in account:`, err);
  }
}

function getAccountId() {
  return window.currentAccountId || null;
}

document.querySelector('.btn-create').addEventListener('click', async () => {
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  if (!opportunityId || opportunityId === '—') {
    alert('Opportunity ID not found');
    return;
  }

  try {
    console.log("📌 Creating batch for opportunity ID:", opportunityId);
    console.log("🚀 Calling URL:", `https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`, {
      method: 'POST'
    });

    const data = await res.json();

    if (res.ok) {
      const batchContainer = document.createElement('div');
      batchContainer.classList.add('batch-box');
      batchContainer.innerHTML = `
        <div class="batch-actions">
          <h3>Batch #${data.batch_number}</h3>
          <div>
            <button class="btn-add">Add candidate</button>
            <button class="btn-send">Send for Approval</button>
          </div>
        </div>
      `;
      document.getElementById('batch-detail-container').appendChild(batchContainer);
    } else {
      alert('Failed to create batch');
    }
  } catch (err) {
    console.error('Error creating batch:', err);
  }
});
async function loadBatchesForOpportunity(opportunityId) {
  try {
    const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const batches = await res.json();

    const container = document.getElementById('batch-detail-container');
    container.innerHTML = ''; // Limpia

    batches.forEach(batch => {
      const box = document.createElement('div');
      box.classList.add('batch-box');
      box.innerHTML = `
        <div class="batch-actions">
          <h3>Batch #${batch.batch_number}</h3>
          <div>
            <button class="btn-add">Add candidate</button>
            <button class="btn-send">Send for Approval</button>
          </div>
        </div>
      `;
      container.appendChild(box);
    });
  } catch (err) {
    console.error('Error loading batches:', err);
  }
}
