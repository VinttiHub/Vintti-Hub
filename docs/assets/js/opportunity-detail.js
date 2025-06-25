let emailToChoices = null;
let emailCcChoices = null;
document.addEventListener('DOMContentLoaded', () => {
  // 🔹 Mostrar popup para elegir acción
document.getElementById('createCandidateBtn').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.remove('hidden');
});

// 🔹 Cerrar popup de elección
document.getElementById('closeChoosePopup').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');
});

document.getElementById('openNewCandidatePopup').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');
  document.getElementById('candidatePopup').classList.remove('hidden');

  // Mostrar campos
  document.getElementById('extra-fields').style.display = 'block';
  document.getElementById('popupcreateCandidateBtn').style.display = 'block';
  document.getElementById('popupAddExistingBtn').style.display = 'none';
  document.getElementById('name-warning').style.display = 'none';
  document.getElementById('pipelineCandidateSearchResults').innerHTML = '';

  // Campo de nombre como input normal (sin buscador)
  const input = document.getElementById('candidate-name');
  input.value = '';
  input.placeholder = 'Full name';
  input.removeAttribute('data-candidate-id');

  // ⚠️ Eliminar cualquier buscador anterior
  const newInput = input.cloneNode(true);
  input.parentNode.replaceChild(newInput, input);
});


document.getElementById('openExistingCandidatePopup').addEventListener('click', async () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');

  // Mostrar solo buscador y botón azul
  document.getElementById('candidatePopup').classList.remove('hidden');
  document.getElementById('popupAddExistingBtn').style.display = 'block';
  document.getElementById('popupcreateCandidateBtn').style.display = 'none';
  document.getElementById('extra-fields').style.display = 'none';
  document.getElementById('name-warning').style.display = 'block';

  const input = document.getElementById('candidate-name');
  const list = document.getElementById('pipelineCandidateSearchResults');
  input.value = '';
  list.innerHTML = '';
  input.placeholder = 'Full name or search...';
  input.removeAttribute('data-candidate-id');

  // ⚠️ Limpiar buscador viejo si existe
  const newInput = input.cloneNode(true);
  input.parentNode.replaceChild(newInput, input);

  const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates');
  const candidates = await response.json();

  newInput.addEventListener('input', (e) => {
    const term = e.target.value.toLowerCase().trim().split(' ');
    list.innerHTML = '';
    candidates.forEach(c => {
      const nameTokens = c.name.toLowerCase().split(' ');
      const match = term.every(t => nameTokens.some(n => n.includes(t)));
      if (match) {
        const li = document.createElement('li');
        li.textContent = c.name;
        li.classList.add('search-result-item');
        li.setAttribute('data-candidate-id', c.candidate_id);
        list.appendChild(li);
        li.addEventListener('click', () => {
          newInput.value = c.name;
          newInput.setAttribute('data-candidate-id', c.candidate_id);
        });
      }
    });
  });
});

// 🔹 Agregar candidato existente al pipeline
document.getElementById('popupAddExistingBtn').addEventListener('click', async () => {
  const input = document.getElementById('candidate-name');
  const candidateId = input.getAttribute('data-candidate-id');
  const name = input.value;
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  if (!candidateId || !opportunityId) return alert('❌ Select a candidate first');

  // Crear en tabla intermedia
  await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId })
  });

  // Mostrar tarjeta en el pipeline
  const cardTemplate = document.getElementById('candidate-card-template');
  const newCard = cardTemplate.content.cloneNode(true);
  newCard.querySelectorAll('.candidate-name').forEach(el => el.textContent = name);
  newCard.querySelector('.candidate-email').textContent = ''; // puedes mejorar esto si tienes el email
  newCard.querySelector('.candidate-img').src = `https://randomuser.me/api/portraits/lego/${candidateId % 10}.jpg`;

  document.querySelector('#contacted').appendChild(newCard); // agregar a columna inicial

  document.getElementById('candidatePopup').classList.add('hidden');
});

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
  document.querySelector('.job-header-right .header-btn').addEventListener('click', async () => {
  document.getElementById('emailPopup').classList.remove('hidden');

  const jobDesc = document.getElementById('job-description-textarea').value || '—';
  const clientName = document.getElementById('client-name-input').value || '—';
  const positionName = document.getElementById('details-opportunity-name').value || '—';

  // 📩 Mensaje
  const message = `Hi\n\nJob description ready, please review:\n\n${jobDesc}`;
  document.getElementById('email-message').value = message;

  // 📝 Asunto
  const subject = `${clientName} - ${positionName} - Job Description`;
  document.getElementById('email-subject').value = subject;


  const toSelect = document.getElementById('email-to');
  const ccSelect = document.getElementById('email-cc');
  toSelect.innerHTML = '';
  ccSelect.innerHTML = '';

  const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users');
  const users = await res.json();

  users.forEach(user => {
    const optionTo = document.createElement('option');
    optionTo.value = user.email_vintti;
    optionTo.textContent = user.user_name;
    toSelect.appendChild(optionTo);

    const optionCc = optionTo.cloneNode(true);
    ccSelect.appendChild(optionCc);
  });

  emailToChoices = new Choices(toSelect, { removeItemButton: true, placeholder: true });
  emailCcChoices = new Choices(ccSelect, { removeItemButton: true, placeholder: true });
});

document.getElementById('closeEmailPopup').addEventListener('click', () => {
  document.getElementById('emailPopup').classList.add('hidden');
  
  // Limpiar campos del formulario
  if (emailToChoices) emailToChoices.clearStore();
  if (emailCcChoices) emailCcChoices.clearStore();
  document.getElementById('email-subject').value = '';
  document.getElementById('email-message').value = '';
});

const overlay = document.getElementById('email-overlay');
const overlayText = document.getElementById('email-overlay-message');

document.getElementById('sendEmailBtn').addEventListener('click', async () => {
  const btn = document.getElementById('sendEmailBtn');
  const toChoices = emailToChoices.getValue().map(o => o.value);
  const ccChoices = emailCcChoices.getValue().map(o => o.value);
  const subject = document.getElementById('email-subject').value;
  const message = document.getElementById('email-message').value;

  if (!toChoices.length || !subject || !message) {
    alert("❌ Fill in all required fields (To, Subject, Message)");
    return;
  }


  btn.disabled = true;
  overlayText.textContent = "Sending email...";
  overlay.classList.remove('hidden');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ to: toChoices, cc: ccChoices, subject, body: message })
    });

    const result = await res.json();
    if (res.ok) {
      overlayText.textContent = "✅ Email sent successfully";
      setTimeout(() => {
        overlay.classList.add('hidden');
        document.getElementById('emailPopup').classList.add('hidden');
        
        // Limpiar campos del formulario
        if (emailToChoices) emailToChoices.clearStore();
        if (emailCcChoices) emailCcChoices.clearStore();
        document.getElementById('email-subject').value = '';
        document.getElementById('email-message').value = '';

        btn.disabled = false;
      }, 2000);
    } else {
      overlay.classList.add('hidden');
      alert("❌ Error sending email: " + (result.error || 'Unknown error'));
      btn.disabled = false;
    }
  } catch (err) {
    overlay.classList.add('hidden');
    console.error("❌ Error:", err);
    alert("❌ Failed to send email");
    btn.disabled = false;
  }
});



document.getElementById('start-date-input').addEventListener('blur', async (e) => {
  await updateOpportunityField('nda_signature_or_start_date', e.target.value);
});
document.getElementById('job-description-textarea').addEventListener('blur', e =>
  updateOpportunityField('hr_job_description', e.target.value));

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
document.getElementById('min-budget-input').addEventListener('blur', e =>
  updateOpportunityField('min_budget', e.target.value));

document.getElementById('max-budget-input').addEventListener('blur', e =>
  updateOpportunityField('max_budget', e.target.value));

document.getElementById('min-salary-input').addEventListener('blur', e =>
  updateOpportunityField('min_salary', e.target.value));

document.getElementById('max-salary-input').addEventListener('blur', e =>
  updateOpportunityField('max_salary', e.target.value));

document.getElementById('model-select').addEventListener('change', e =>
  updateOpportunityField('opp_model', e.target.value));

document.getElementById('years-experience-input').addEventListener('blur', e =>
  updateOpportunityField('years_experience', e.target.value));

document.getElementById('fee-input').addEventListener('blur', e =>
  updateOpportunityField('fee', e.target.value));

document.getElementById('comments-firstmeeting-textarea').addEventListener('blur', e =>
  updateOpportunityField('opp_comments', e.target.value));

document.getElementById('recording-input').addEventListener('blur', e =>
  updateOpportunityField('first_meeting_recording', e.target.value));

document.getElementById('timezone-input').addEventListener('blur', e =>
  updateAccountField('timezone', e.target.value));

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

aiGo.addEventListener('click', async () => {
  const intro = document.querySelector('#ai-assistant-popup textarea[placeholder="00:00 Speaker: Text here..."]').value;
  const deepDive = document.querySelector('#ai-assistant-popup input[placeholder="2nd_Call_Transcript"]').value;
  const notes = document.querySelector('#ai-assistant-popup textarea[placeholder="Your notes here..."]').value;

  console.log("📤 Enviando a AI Assistant:", { intro, deepDive, notes });

  if (!intro && !deepDive && !notes) {
    alert("❌ Please fill at least one field");
    return;
  }

  aiGo.textContent = '⏳ Generating...';
  aiGo.disabled = true;

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/ai/generate_jd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intro, deepDive, notes })
    });

    const data = await res.json();
    console.log("📥 Respuesta de AI Assistant:", data);

    if (data.job_description) {
      const jd = data.job_description;

      // Mostrar y guardar en textarea
      document.getElementById('job-description-textarea').value = jd;

      // Guardar en la base de datos
      await updateOpportunityField('hr_job_description', jd);
      console.log("✅ Job description saved in DB");

      alert("✅ Job description generated!");
    } else {
      alert("⚠️ Unexpected response from AI");
    }
  } catch (err) {
    console.error("❌ AI Assistant error:", err);
    alert("❌ Error generating job description");
  } finally {
    aiGo.textContent = "Let's Go 🚀";
    aiGo.disabled = false;
    aiPopup.classList.add('hidden');
  }
});

// Popup para agregar candidato al batch
document.addEventListener("click", async (e) => {
  if (e.target.classList.contains("btn-add")) {
    const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
    if (!opportunityId || opportunityId === '—') return;

    // Obtener candidatos de la oportunidad
    try {
      const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`);
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
  const selectedCandidate = {
  candidate_id: candidateId,
  name: li.textContent,
  email: '' // puedes actualizar esto si luego quieres mostrar el email
};


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
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const data = await res.json();

    // Buscar el batch con ese número
    const selectedBatch = data.find(b => b.batch_number === batchNumber);
    if (!selectedBatch) {
      alert("Batch not found");
      return;
    }

    const patchRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.comcom/candidates/${candidateId}/batch`, {
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
    await reloadBatchCandidates();
    document.getElementById("batchCandidatePopup").classList.add("hidden");
    await loadBatchesForOpportunity(opportunityId);
    // Recargar sección de batches
    await loadBatchesForOpportunity(opportunityId);
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
    // Cargar batches si estamos ya en la pestaña "Candidates"
    const activeTab = document.querySelector(".nav-item.active");
    if (activeTab && activeTab.textContent.trim() === "Candidates") {
      const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
      if (opportunityId && opportunityId !== '—') {
        loadBatchesForOpportunity(opportunityId);
      }
    }
    document.getElementById('hire-select').addEventListener('change', async (e) => {
      const selectedCandidateId = e.target.value;
      await updateOpportunityField('candidato_contratado', selectedCandidateId);
    });
});

async function loadOpportunityData() {
  const params = new URLSearchParams(window.location.search);
  const opportunityId = params.get('id');
  if (!opportunityId) return;

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`);
    const data = await res.json();
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

    // FIRST MEETING INFO
    document.getElementById('min-budget-input').value = data.min_budget || '';
    document.getElementById('max-budget-input').value = data.max_budget || '';
    document.getElementById('min-salary-input').value = data.min_salary || '';
    document.getElementById('max-salary-input').value = data.max_salary || '';
    document.getElementById('model-select').value = data.opp_model || '';
    document.getElementById('years-experience-input').value = data.years_experience || '';
    document.getElementById('fee-input').value = data.fee || '';
    document.getElementById('timezone-input').value = data.account_timezone || '';
    document.getElementById('comments-firstmeeting-textarea').value = data.opp_comments || '';
    document.getElementById('recording-input').value = data.first_meeting_recording || '';

    // Signed: si tienes un campo de fecha de firma, calcula días
    if (data.nda_signature_or_start_date) {
      const signedDays = calculateDaysAgo(data.nda_signature_or_start_date);
      document.getElementById('signed-tag').textContent = `${signedDays} days ago`;
    } else {
      document.getElementById('signed-tag').textContent = '—';
    }
    // Cargar el select de hire con los candidatos
    // Cargar el select de hire con los candidatos
    try {
      const hireSelect = document.getElementById('hire-select');
      const candidatoContratadoId = data.candidato_contratado;

      const resCandidates = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates`);
      const candidates = await resCandidates.json();

      hireSelect.innerHTML = '<option value="">Select Hire...</option>';

      candidates.forEach(candidate => {
        const option = document.createElement('option');
        option.value = candidate.candidate_id;
        option.textContent = candidate.name;
        if (candidate.candidate_id === candidatoContratadoId) {
          option.selected = true;
        }
        hireSelect.appendChild(option);
      });

      new Choices(hireSelect, {
        searchEnabled: true,
        itemSelectText: '',
        shouldSort: false
      });

    } catch (error) {
      console.error('Error loading hire candidates:', error);
    }
      window.currentAccountId = data.account_id;
        try {
          const resUsers = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/users`);
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
          if (data.opportunity_id) {
            reloadBatchCandidates();
          }
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
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/fields`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errorText = await res.text();
      console.error(`❌ Error updating ${fieldName}:`, errorText);
    } else {
      console.log(`✅ ${fieldName} updated successfully`);
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
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
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
    console.log("🚀 Calling URL:", `https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`, {
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
    const [batchesRes, candidatesRes] = await Promise.all([
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`),
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`)
    ]);

    const batches = await batchesRes.json();
    const candidates = await candidatesRes.json();

    const container = document.getElementById('batch-detail-container');
    container.innerHTML = '';

    batches.forEach(batch => {
      const box = document.createElement("div");
      box.classList.add("batch-box");
      box.setAttribute("data-batch-id", batch.batch_id); // ✅ para referencia directa

      box.innerHTML = `
        <div class="batch-actions">
          <h3>Batch #${batch.batch_number}</h3>
          <div>
            <button class="btn-add">Add candidate</button>
            <button class="btn-send">Send for Approval</button>
          </div>
        </div>
        <div class="batch-candidates"></div>
      `;

      const candidateContainer = box.querySelector(".batch-candidates");

      candidates
        .filter(c => c.batch_id === batch.batch_id)
        .forEach(c => {
          const template = document.getElementById("candidate-card-template");
          const cardFragment = template.content.cloneNode(true);
          const cardElement = cardFragment.querySelector('.candidate-card');

          // Mostrar datos del candidato
          cardElement.querySelectorAll(".candidate-name").forEach(el => el.textContent = c.name);
          cardElement.querySelector(".candidate-email").textContent = c.email || '';
          cardElement.querySelector(".candidate-img").src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;

          // Actualizar valor actual del dropdown si existe stage_batch
          const dropdown = cardElement.querySelector('.candidate-status-dropdown');
          if (dropdown && c.stage_batch) {
            dropdown.value = c.stage_batch;
          }

          // Agregar listener para actualizar stage_batch en la base de datos
          dropdown.addEventListener('change', async (e) => {
            const stageBatch = e.target.value;
            const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
            const candidateId = c.candidate_id;

            try {
              const response = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunity_candidates/stage_batch`, {
                method: 'PATCH',
                headers: {
                  'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                  opportunity_id: opportunityId,
                  candidate_id: candidateId,
                  stage_batch: stageBatch
                })
              });

              if (!response.ok) {
                const errorText = await response.text();
                console.error("❌ Error updating stage_batch:", errorText);
              } else {
                console.log(`✅ stage_batch updated to "${stageBatch}" for candidate ${candidateId}`);
              }
            } catch (err) {
              console.error("❌ Error updating stage_batch:", err);
            }
          });

          candidateContainer.appendChild(cardElement);
        });


      container.appendChild(box);
    });
  } catch (err) {
    console.error('Error loading batches:', err);
  }
}

async function reloadBatchCandidates() {
  const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
  if (!opportunityId || opportunityId === '—') return;

  try {
    const [batchesRes, candidatesRes] = await Promise.all([
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`),
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`)
    ]);

    const batches = await batchesRes.json();
    const candidates = await candidatesRes.json();

    const container = document.getElementById("batch-detail-container");
    container.innerHTML = "";

    batches.forEach(batch => {
      const box = document.createElement("div");
      box.classList.add("batch-box");
      box.setAttribute("data-batch-id", batch.batch_id);

      box.innerHTML = `
        <div class="batch-actions">
          <h3>Batch #${batch.batch_number}</h3>
          <div>
            <button class="btn-add">Add candidate</button>
            <button class="btn-send">Send for Approval</button>
          </div>
        </div>
        <div class="batch-candidates"></div>
      `;

      const candidateContainer = box.querySelector(".batch-candidates");

      candidates
        .filter(c => c.batch_id === batch.batch_id)
        .forEach(c => {
          const card = document.createElement("div");
          card.classList.add("candidate-card");
          card.innerHTML = `
            <strong>${c.name}</strong>
            <div class="preview">
              <img src="https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg" />
              <div class="info">
                <span class="name">${c.name}</span>
                <span class="email">${c.email || ''}</span>
              </div>
            </div>
          `;
          candidateContainer.appendChild(card);
        });

      container.appendChild(box);
    });

  } catch (err) {
    console.error("❌ Error reloading batch candidates:", err);
  }
}

async function loadBatchesAndCandidates() {
  const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
  if (!opportunityId || opportunityId === '—') return;

  const container = document.getElementById("batch-detail-container");
  container.innerHTML = "";

  try {
    const [batchesRes, candidatesRes] = await Promise.all([
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`),
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`)
    ]);

    const batches = await batchesRes.json();
    const candidates = await candidatesRes.json();

    batches.forEach(batch => {
    const box = document.createElement("div");
    box.classList.add("batch-box");
    box.setAttribute("data-batch-id", batch.batch_id); // ✅ Aquí se asigna el batch_id

    box.innerHTML = `
      <div class="batch-actions">
        <h3>Batch #${batch.batch_number}</h3>
        <div>
          <button class="btn-add">Add candidate</button>
          <button class="btn-send">Send for Approval</button>
        </div>
      </div>
      <div class="batch-candidates"></div>
    `;
      const candidateContainer = box.querySelector(".batch-candidates");
      candidates
        .filter(c => c.batch_id === batch.batch_id)
        .forEach(c => {
          const template = document.getElementById("candidate-card-template");
          const cardFragment = template.content.cloneNode(true);
          const cardElement = cardFragment.querySelector('.candidate-card');

          cardElement.querySelectorAll(".candidate-name").forEach(el => el.textContent = c.name);
          cardElement.querySelector(".candidate-email").textContent = c.email || '';
          cardElement.querySelector(".candidate-img").src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;

          candidateContainer.appendChild(cardElement);
        });
      container.appendChild(box);
    });

  } catch (err) {
    console.error("Error loading batches and candidates:", err);
  }
}
