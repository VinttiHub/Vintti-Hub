let emailToChoices = null;
let emailCcChoices = null;
function toggleActiveButton(command, button) {
  document.execCommand(command, false, '');
  button.classList.toggle('active');
}
document.addEventListener('DOMContentLoaded', () => {
  // 🔹 Mostrar popup para elegir acción
document.getElementById('createCandidateBtn').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.remove('hidden');
});
document.getElementById('closeSignOffPopup').addEventListener('click', () => {
  document.getElementById('signOffPopup').classList.add('hidden');
});

// 🔹 Cerrar popup de elección
document.getElementById('closeChoosePopup').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');
});

document.getElementById('openNewCandidatePopup').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');

  // Mostrar campos
  document.getElementById('extra-fields').style.display = 'block';
  document.getElementById('popupcreateCandidateBtn').style.display = 'block';
  document.getElementById('popupAddExistingBtn').style.display = 'none';
  const nameWarning = document.getElementById('name-warning');
  if (nameWarning) {
    nameWarning.style.display = 'none'; // o 'block' si es el otro caso
  }
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
document.getElementById('openNewCandidatePopup').addEventListener('click', async () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');
  document.getElementById('preCreateCheckPopup').classList.remove('hidden');

  const input = document.getElementById('precreate-search');
  const results = document.getElementById('precreate-results');
  const foundMsg = document.getElementById('precreate-found-msg');
  const noMatch = document.getElementById('precreate-no-match');

  input.value = '';
  results.innerHTML = '';
  foundMsg.style.display = 'none';
  noMatch.style.display = 'none';

  const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates');
  const candidates = await res.json();

  input.addEventListener('input', () => {
    const term = input.value.toLowerCase().trim().split(' ');
    results.innerHTML = '';
    foundMsg.style.display = 'none';
    noMatch.style.display = 'none';

    const matches = candidates.filter(c => {
      const name = c.name?.toLowerCase() || '';
      const linkedin = c.linkedin?.toLowerCase() || '';
      const phone = c.phone?.toLowerCase() || '';

      return term.every(t =>
        name.includes(t) ||
        linkedin.includes(t) ||
        phone.includes(t)
      );
    });


    if (matches.length === 0 && term.join('').length > 3) {
      noMatch.style.display = 'block';
    } else if (matches.length > 0) {
      foundMsg.style.display = 'block';
      matches.forEach(c => {
        const li = document.createElement('li');
        li.classList.add('search-result-item');
        li.setAttribute('data-candidate-id', c.candidate_id);

        const matchBy = term.map(t => {
          if ((c.name || '').toLowerCase().includes(t)) return 'Name';
          if ((c.linkedin || '').toLowerCase().includes(t)) return 'LinkedIn';
          if ((c.phone || '').toLowerCase().includes(t)) return 'Phone';
          return null;
        }).filter(Boolean)[0] || 'Name';

        li.innerHTML = `
          <div style="font-weight: 600;">${c.name}</div>
          <div style="font-size: 12px; color: #666;">🔍 Match by ${matchBy}</div>
        `;

        li.classList.add('search-result-item');
        li.setAttribute('data-candidate-id', c.candidate_id);
        results.appendChild(li);

        li.addEventListener('click', async () => {
          const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
          if (!opportunityId || !c.candidate_id) return alert('❌ Invalid candidate or opportunity');

          // 🔁 Insertar en tabla intermedia
          await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ candidate_id: c.candidate_id })
          });

          // 🔁 Mostrar tarjeta en columna "Contactado"
          const cardTemplate = document.getElementById('candidate-card-template');
          const newCard = cardTemplate.content.cloneNode(true);
          newCard.querySelectorAll('.candidate-name').forEach(el => el.textContent = c.name);
          newCard.querySelector('.candidate-email').textContent = c.email || '';
          newCard.querySelector('.candidate-img').src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;
          newCard.querySelector('.candidate-status-dropdown')?.remove();
          document.querySelector('#contacted').appendChild(newCard);

          document.getElementById('preCreateCheckPopup').classList.add('hidden');
          showFriendlyPopup(`✅ ${c.name} added to pipeline`);
          loadPipelineCandidates();
        });
      });
    }
  });
});

document.getElementById('goToCreateCandidateBtn').addEventListener('click', () => {
  document.getElementById('preCreateCheckPopup').classList.add('hidden');
  document.getElementById('candidatePopup').classList.remove('hidden');

  document.getElementById('extra-fields').style.display = 'block';
  document.getElementById('popupcreateCandidateBtn').style.display = 'block';
  document.getElementById('popupAddExistingBtn').style.display = 'none';

  const input = document.getElementById('candidate-name');
  input.value = '';
  input.placeholder = 'Full name';
  input.removeAttribute('data-candidate-id');
});
document.getElementById('closePreCreatePopup').addEventListener('click', () => {
  document.getElementById('preCreateCheckPopup').classList.add('hidden');
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
  newCard.querySelector('.candidate-status-dropdown')?.remove();
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

  const jobDesc = document.getElementById('job-description-textarea').innerText || '—';
  const clientName = document.getElementById('client-name-input').value || '—';
  const positionName = document.getElementById('details-opportunity-name').value || '—';

  // 📩 Mensaje
  const message = `Hi<br><br>Job description ready, please review:<br><br>${jobDesc}`;
  document.getElementById('email-message').innerHTML = message;

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

if (emailToChoices) emailToChoices.destroy();
if (emailCcChoices) emailCcChoices.destroy();

emailToChoices = new Choices(toSelect, {
  removeItemButton: true,
  placeholder: true,
  shouldSort: false
});
emailCcChoices = new Choices(ccSelect, {
  removeItemButton: true,
  placeholder: true,
  shouldSort: false
});

// 🔹 Forzar clase visual compacta para que no colapse
document.querySelectorAll('.choices').forEach(el => {
  el.classList.add('compact-choices');
});


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
  const message = document.getElementById('email-message').innerHTML;

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


document.getElementById('comments-overview-textarea').addEventListener('blur', async (e) => {
  await updateOpportunityField('comments', e.target.value);
});
document.getElementById('interviewing-process-editor').addEventListener('blur', e => {
  updateOpportunityField('client_interviewing_process', e.target.innerHTML);
});

document.getElementById('start-date-input').addEventListener('blur', async (e) => {
  await updateOpportunityField('nda_signature_or_start_date', e.target.value);
});
document.getElementById('job-description-textarea').addEventListener('blur', e =>
  updateOpportunityField('hr_job_description', e.target.innerHTML));

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
document.getElementById('deepdive-recording-input').addEventListener('blur', e =>
  updateOpportunityField('deepdive_recording', e.target.value));

document.getElementById('timezone-input').addEventListener('blur', e =>
  updateAccountField('timezone', e.target.value));

document.getElementById('details-sales-lead').addEventListener('change', async (e) => {
  const emailValue = e.target.value; // el value es el email
  console.log('🟡 Sales Lead changed:', emailValue);

  await updateOpportunityField('opp_sales_lead', emailValue);
});

document.getElementById('details-hr-lead').addEventListener('change', async (e) => {
  const emailValue = e.target.value;
  console.log('🟡 HR Lead changed:', emailValue);

  await updateOpportunityField('opp_hr_lead', emailValue);

  // ✅ Si se asigna, eliminar la alerta si existe
  const alertBox = document.getElementById('hr-alert');
  if (alertBox) alertBox.remove();
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
    loadPresentationTable(opportunityId);
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
      document.getElementById('job-description-textarea').innerHTML = jd;

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
    console.log("✅ Click en Add Candidate detectado");
    const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
    if (!opportunityId || opportunityId === '—') return;

    // Obtener candidatos de la oportunidad
    try {
      const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`);
      const candidates = await res.json();
      console.log("🧠 Todos los candidatos de la oportunidad:", candidates);

      if (!res.ok && filtered.error) {
        showFriendlyPopup(`🌸 ${filtered.error}`);
        return;
      }
      const filtered = candidates.filter(c => c.stage === "En proceso con Cliente");
      console.log("🧪 Candidatos con 'En proceso con Cliente':", filtered);
      // Limpiar resultados anteriores
      const resultsList = document.getElementById("candidateSearchResults");
      resultsList.innerHTML = "";

      filtered.forEach(c => {
        const li = document.createElement('li');
        li.classList.add('search-result-item');
        li.setAttribute('data-candidate-id', c.candidate_id);
        const matchBy = 'Name'; // No hay búsqueda activa, así que no se necesita mostrar "match by"

        li.innerHTML = `
          <div style="font-weight: 600;">${c.name}</div>
          <div style="font-size: 12px; color: #666;">🔍 Match by ${matchBy}</div>
        `;

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

    const patchRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/batch`, {
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

    document.getElementById('signOffBtn').addEventListener('click', async () => {
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  if (!opportunityId) return;

  document.getElementById('signOffPopup').classList.remove('hidden');

  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`);
  const candidates = await res.json();

  const select = document.getElementById('signoff-to');
  select.innerHTML = '';
  candidates.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.email;
    opt.textContent = c.name;
    select.appendChild(opt);
  });

  if (window.signoffChoices) window.signoffChoices.destroy();
  window.signoffChoices = new Choices(select, { removeItemButton: true });
});
let isSpanish = false;
document.getElementById('toggleLangBtn').addEventListener('click', () => {
  const subject = document.getElementById('signoff-subject');
  const message = document.getElementById('signoff-message');

  if (!isSpanish) {
    subject.value = 'Actualización sobre tu aplicación';
    message.value = `Querido candidato,\n\nGracias por haber participado en nuestro proceso en Vintti. Tras una cuidadosa evaluación, hemos decidido continuar con otro candidato.\n\n¡Apreciamos mucho tu tiempo e interés!\nSi deseas compartir tu experiencia con el proceso de selección, aquí hay una encuesta anónima muy corta (menos de 3 minutos):\n🔗 https://tally.so/r/w7K859\n\n¡Te deseamos lo mejor en tu camino! ✨\nCon cariño,\nel equipo de Vintti`;
  } else {
    subject.value = 'Update on your application';
    message.value = `Dear applicant,\n\nThank you so much for being part of our process at Vintti. After careful consideration, we’ve decided to move forward with another candidate.\n\nWe truly appreciate your time and interest!\nIf you'd like to share your experience with the selection process, here’s a short anonymous survey (under 3 minutes):\n🔗 https://tally.so/r/w7K859\n\nWishing you all the best in your journey! ✨\nWarmly,\nthe Vintti team`;
  }
  isSpanish = !isSpanish;
});
document.getElementById('sendSignOffBtn').addEventListener('click', async () => {
  const to = signoffChoices.getValue().map(o => o.value);
  const subject = document.getElementById('signoff-subject').value;
  const body = document.getElementById('signoff-message').value;

  if (!to.length || !subject || !body) {
    alert("❌ Fill in all fields");
    return;
  }

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to, subject, body })
    });

    if (res.ok) {
      alert("✅ Email sent successfully");
      document.getElementById('signOffPopup').classList.add('hidden');
    } else {
      const err = await res.json();
      alert("❌ Error: " + err.detail || err.error);
    }
  } catch (err) {
    console.error(err);
    alert("❌ Failed to send email");
  }
});
document.getElementById('closeApprovalEmailPopup').addEventListener('click', () => {
  document.getElementById('approvalEmailPopup').classList.add('hidden');
});

document.getElementById('sendApprovalEmailBtn').addEventListener('click', async () => {
  const to = approvalToChoices.getValue().map(o => o.value);
  const cc = approvalCcChoices.getValue().map(o => o.value);
  const subject = document.getElementById('approval-subject').value;
  const body = document.getElementById('approval-message').innerHTML;

  if (!to.length || !subject || !body) {
    alert('❌ Please fill all required fields');
    return;
  }

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to, cc, subject, body })
    });

    if (res.ok) {
      alert('✅ Email sent!');
      document.getElementById('approvalEmailPopup').classList.add('hidden');
    } else {
      alert('❌ Error sending email');
    }
  } catch (err) {
    alert('❌ Failed to send email');
  }
});
async function loadPresentationTable(opportunityId) {
  const tableBody = document.getElementById("presentation-batch-table-body");
  tableBody.innerHTML = '';

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const batches = await res.json();

    batches.forEach(batch => {
      // Solo mostrar si hay presentation_date
      if (!batch.presentation_date) return;

      const tr = document.createElement("tr");

      // Batch #
      const tdBatch = document.createElement("td");
      tdBatch.textContent = `#${batch.batch_number}`;

      // Presentation Date
      const tdDate = document.createElement("td");
      const inputDate = document.createElement("input");
      inputDate.type = "date";
      inputDate.value = formatDate(batch.presentation_date);
      inputDate.addEventListener("blur", async () => {
        const updated = { presentation_date: inputDate.value };
        await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batch.batch_id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updated)
        });
      });
      tdDate.appendChild(inputDate);

      // Time (días desde presentation_date hasta hoy)
      const tdTime = document.createElement("td");
      if (batch.presentation_date) {
        const today = new Date();
        const presentation = new Date(batch.presentation_date);
        const diffMs = today - presentation;
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        tdTime.textContent = diffDays;
      } else {
        tdTime.textContent = '—';
      }

      // View button
      const tdView = document.createElement("td");
      const viewBtn = document.createElement("button");
      viewBtn.textContent = "View";
      viewBtn.classList.add("view-btn");
      // Agrega acción si necesitas
      tdView.appendChild(viewBtn);

      tr.appendChild(tdBatch);
      tr.appendChild(tdDate);
      tr.appendChild(tdTime);
      tr.appendChild(tdView);
      tableBody.appendChild(tr);
    });

  } catch (err) {
    console.error("❌ Error loading batches for presentation table:", err);
  }
}

// Marcar activo si el estilo está aplicado al soltar selección
document.getElementById('job-description-textarea').addEventListener('mouseup', () => {
  document.querySelectorAll('.toolbar button').forEach(btn => {
    const command = btn.getAttribute('data-command');
    if (!command) return;

    const isActive = document.queryCommandState(command);
    btn.classList.toggle('active', isActive);
  });
});

const picker = document.getElementById('emoji-picker');
const trigger = document.getElementById('emoji-trigger');
const editor = document.getElementById('job-description-textarea');

trigger.addEventListener('click', () => {
  picker.style.display = picker.style.display === 'block' ? 'none' : 'block';
});

picker.addEventListener('emoji-click', event => {
  const emoji = event.detail.unicode; // emoji unicode, p.ej. "😊"
  editor.focus();
  document.execCommand('insertText', false, emoji);
  picker.style.display = 'none';
});
// Botón de Go Back
const goBackButton = document.getElementById('goBackButton');
if (goBackButton) {
  goBackButton.addEventListener('click', () => {
    if (document.referrer) {
      window.history.back();
    } else {
      window.location.href = '/'; // Cambia por la home si quieres
    }
  });
}
document.getElementById('hire-display').addEventListener('click', () => {
  const candidateId = document.getElementById('hire-display').getAttribute('data-candidate-id');
  if (candidateId) {
    window.location.href = `/candidate-details.html?id=${candidateId}`;
  }
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
    document.getElementById('comments-overview-textarea').value = data.comments || '';

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
    document.getElementById('job-description-textarea').innerHTML = data.hr_job_description || '';

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
    document.getElementById('deepdive-recording-input').value = data.deepdive_recording || '';
    document.getElementById('interviewing-process-editor').innerHTML = data.client_interviewing_process || '';

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
      const hireDisplay = document.getElementById('hire-display');
      const candidatoContratadoId = data.candidato_contratado;

      if (candidatoContratadoId) {
        try {
          const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidatoContratadoId}`);
          if (res.ok) {
            const candidato = await res.json();
            hireDisplay.value = candidato.name || '—';
            hireDisplay.setAttribute('data-candidate-id', candidato.candidate_id);
            console.log(candidato)
          } else {
            hireDisplay.value = '—';
          }
        } catch (err) {
          console.error('Error fetching hire name:', err);
          hireDisplay.value = '—';
        }
      } else {
        hireDisplay.value = '';
      }

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

          const allowedSubstrings = ['Pilar', 'Jazmin', 'Agostina', 'Sol'];

          users.forEach(user => {
            const option1 = document.createElement('option');
            option1.value = user.email_vintti;
            option1.textContent = user.user_name;
            salesLeadSelect.appendChild(option1);

            // Solo agregar al dropdown de HR Lead si coincide con los nombres permitidos
            if (allowedSubstrings.some(name => user.user_name.includes(name))) {
              const option2 = document.createElement('option');
              option2.value = user.email_vintti;
              option2.textContent = user.user_name;
              hrLeadSelect.appendChild(option2);
            }
          });

          // Ahora cruzas: en data.opp_sales_lead y opp_hr_lead tienes el EMAIL → debes setear el value del <select> con ese email:
          salesLeadSelect.value = data.opp_sales_lead || '';
          hrLeadSelect.value = data.opp_hr_lead || '';
          if (data.opportunity_id) {
            reloadBatchCandidates();
          }
          // 🚨 Mostrar alerta si no hay HR Lead asignado
          if (!data.opp_hr_lead) {
            const alertBox = document.createElement('div');
            alertBox.textContent = "⚠️ This opportunity doesn't have an HR Lead assigned. Please assign one.";
            alertBox.style.background = '#fff3cd';
            alertBox.style.color = '#856404';
            alertBox.style.border = '1px solid #ffeeba';
            alertBox.style.padding = '12px';
            alertBox.style.borderRadius = '10px';
            alertBox.style.margin = '15px 0';
            alertBox.style.fontWeight = '500';
            alertBox.style.textAlign = 'center';

            const container = document.querySelector('.detail-main');
            container.insertBefore(alertBox, container.firstChild);
          }

        } catch (err) {
          console.error('Error loading users for Sales/HR Lead:', err);
        }


        } catch (err) {
          console.error("Error loading opportunity:", err);
        }
        try {
  const lightRes = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light');
  const lightData = await lightRes.json();
  const currentId = opportunityId;
  const opp = lightData.find(o => o.opportunity_id == currentId); // usa comparación flexible con ==

  if (opp && opp.opp_stage) {
    const stageText = opp.opp_stage;
    const stageTag = document.getElementById('stage-tag');
    const stageSpan = document.getElementById('stage-text');

    stageSpan.textContent = stageText;

    // Limpiar clases anteriores por si hay recarga
    stageTag.className = 'opportunity-stage-card';

    // Generar clase CSS dinámicamente
    const cssClass = `stage-color-${stageText.toLowerCase().replace(/\s+/g, '-').replace(/[^\w-]/g, '')}`;
    stageTag.classList.add(cssClass);
  }
} catch (err) {
  console.error("❌ Error loading stage from opportunities/light:", err);
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
document.querySelector('.btn-create').addEventListener('click', () => {
  document.getElementById('presentationDateInput').value = ''; // limpia fecha previa
  document.getElementById('createBatchPopup').classList.remove('hidden');
});

document.getElementById('closeCreateBatchPopup').addEventListener('click', () => {
  document.getElementById('createBatchPopup').classList.add('hidden');
});

document.getElementById('confirmCreateBatchBtn').addEventListener('click', async () => {
  const presentationDate = document.getElementById('presentationDateInput').value;
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');

  if (!presentationDate) return alert('❌ Please select a presentation date');

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ presentation_date: presentationDate })  // ← ahora se envía la fecha
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
      document.getElementById('createBatchPopup').classList.add('hidden');
      showFriendlyPopup("✅ Batch created successfully");
    } else {
      alert('❌ Failed to create batch');
    }
  } catch (err) {
    console.error('Error creating batch:', err);
    alert('❌ Could not create batch');
  }
});
async function loadBatchesForOpportunity(opportunityId) {
  try {
    const batchesRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const batches = await batchesRes.json();

    const container = document.getElementById('batch-detail-container');
    container.innerHTML = '';

    for (const batch of batches) {
      const box = document.createElement('div');
      box.classList.add('batch-box');
      box.setAttribute('data-batch-id', batch.batch_id);

      box.innerHTML = `
        <div class="batch-actions">
          <h3>Batch #${batch.batch_number}</h3>
          <div>
            <button class="btn-add">Add candidate</button>
            <button class="btn-send">Send for Approval</button>
            <button class="btn-delete" data-batch-id="${batch.batch_id}" title="Delete Batch">🗑️</button>
          </div>
        </div>
        <div class="batch-candidates"></div>
      `;
// 👉 Este es el botón de Send for Approval
box.querySelector('.btn-send').addEventListener('click', () => openApprovalPopup(batch.batch_id));

      const candidateContainer = box.querySelector('.batch-candidates');

      // Traer candidatos por batch desde tabla intermedia
      const batchCandidatesRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batch.batch_id}/candidates`);
      const batchCandidates = await batchCandidatesRes.json();
      batchCandidates.forEach(c => {
        const template = document.getElementById('candidate-card-template');
        const cardFragment = template.content.cloneNode(true);
        const cardElement = cardFragment.querySelector('.candidate-card');
        cardElement.setAttribute('data-candidate-id', c.candidate_id);


        cardElement.querySelectorAll('.candidate-name').forEach(el => el.textContent = c.name);
        cardElement.querySelector('.candidate-email').textContent = c.email || '';
        cardElement.querySelector('.candidate-img').src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;
        const dropdown = cardElement.querySelector('.candidate-status-dropdown');
        dropdown.value = "Client interviewing/testing";
        if (c.status) {
          const options = dropdown.options;
          let found = false;
          for (let i = 0; i < options.length; i++) {
            if (options[i].value.trim() === c.status.trim()) {
              options[i].selected = true;
              found = true;
              break;
            }
          }
          if (!found) {
            console.warn("⚠️ Status no encontrado en opciones:", c.status);
          }
        }
      // Evita que clicks en el dropdown o trash icon activen la redirección
      cardElement.addEventListener('click', (e) => {
        const isDropdown = e.target.classList.contains('candidate-status-dropdown');
        const isTrash = e.target.classList.contains('delete-candidate-btn');
        if (isDropdown || isTrash) return;

        const candidateId = cardElement.getAttribute('data-candidate-id');
        if (candidateId) {
          window.location.href = `/candidate-details.html?id=${candidateId}`;
        }
      });


        dropdown.addEventListener("change", async (e) => {
          const newStatus = e.target.value;
          const candidateId = c.candidate_id;
          const batchId = batch.batch_id;

          console.log("📥 Cambio en status");
          console.log("📌 candidateId:", candidateId);
          console.log("📌 batchId:", batchId);
          console.log("📌 newStatus:", newStatus);

          try {
            const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates_batches/status`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                candidate_id: candidateId,
                batch_id: batchId,
                status: newStatus
              })
            });

            const result = await res.json();
            console.log("📤 Respuesta backend:", result);

            if (res.ok) {
              dropdown.value = newStatus;
              showFriendlyPopup("✅ Status updated");
            } else {
              showFriendlyPopup("❌ Error updating status");
            }
          } catch (err) {
            console.error("❌ Error enviando status:", err);
          }
        });

        candidateContainer.appendChild(cardElement);
                const trash = document.createElement("button");
      trash.innerHTML = "🗑️";
      trash.classList.add("delete-candidate-btn");
      trash.title = "Remove from batch";
      trash.style.marginLeft = "auto";
      trash.style.background = "none";
      trash.style.border = "none";
      trash.style.cursor = "pointer";
      trash.style.fontSize = "18px";

      trash.addEventListener("click", async () => {
        const confirmed = confirm(`⚠️ Remove ${c.name} from this batch?`);
        if (!confirmed) return;

        try {
          const res = await fetch("https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates_batches", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              candidate_id: c.candidate_id,
              batch_id: batch.batch_id
            })
          });

          if (res.ok) {
            showFriendlyPopup("✅ Candidate removed from batch");
            await reloadBatchCandidates();
          } else {
            alert("❌ Failed to remove candidate");
          }
        } catch (err) {
          console.error("❌ Error removing candidate:", err);
          alert("❌ Could not remove candidate");
        }
      });

    const header = cardElement.querySelector(".candidate-card-header");
    header.insertBefore(trash, header.firstChild);



      });

      // Eliminar batch
      box.querySelector('.btn-delete').addEventListener('click', async (e) => {
        const confirmed = confirm("⚠️ Are you sure you want to delete this batch?");
        if (!confirmed) return;

        const batchId = e.target.getAttribute('data-batch-id');

        try {
          const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batchId}`, {
            method: 'DELETE'
          });

          if (res.ok) {
            alert('✅ Batch deleted successfully');
            await loadBatchesForOpportunity(opportunityId);
          } else {
            alert('❌ Error deleting batch');
          }
        } catch (err) {
          console.error('Error deleting batch:', err);
          alert('❌ Could not delete batch');
        }
      });

      container.appendChild(box);
    }
  } catch (err) {
    console.error('Error loading batches:', err);
  }
}


async function reloadBatchCandidates() {
  const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
  if (!opportunityId || opportunityId === '—') return;

  try {
    const batchesRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const batches = await batchesRes.json();

    const container = document.getElementById("batch-detail-container");
    container.innerHTML = "";

    for (const batch of batches) {
      const box = document.createElement("div");
      box.classList.add("batch-box");
      box.setAttribute("data-batch-id", batch.batch_id);

      box.innerHTML = `
        <div class="batch-actions">
          <h3>Batch #${batch.batch_number}</h3>
          <div>
            <button class="btn-add">Add candidate</button>
            <button class="btn-send">Send for Approval</button>
            <button class="btn-delete" data-batch-id="${batch.batch_id}" title="Delete Batch">🗑️</button>
          </div>
        </div>
        <div class="batch-candidates"></div>
      `;
// 👉 Este es el botón de Send for Approval
box.querySelector('.btn-send').addEventListener('click', () => openApprovalPopup(batch.batch_id));

      const candidateContainer = box.querySelector(".batch-candidates");

      // 🔁 Obtener candidatos desde nuevo endpoint
      const batchCandidatesRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batch.batch_id}/candidates`);
      const batchCandidates = await batchCandidatesRes.json();
batchCandidates.forEach(c => {
  const template = document.getElementById("candidate-card-template");
  const cardFragment = template.content.cloneNode(true);
  const cardElement = cardFragment.querySelector(".candidate-card");

  // Setear nombre, email, imagen
  cardElement.querySelectorAll(".candidate-name").forEach(el => el.textContent = c.name);
  cardElement.querySelector(".candidate-email").textContent = c.email || '';
  const salaryEl = document.createElement("span");
  salaryEl.classList.add("candidate-salary");
  salaryEl.textContent = c.salary_range ? `$${c.salary_range}` : '—';
  cardElement.querySelector(".info").appendChild(salaryEl);

  cardElement.querySelector(".candidate-img").src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;

  // Status dropdown
  const dropdown = cardElement.querySelector('.candidate-status-dropdown');
  dropdown.value = "Client interviewing/testing";
// Evita que clicks en el dropdown o trash icon activen la redirección
  cardElement.addEventListener('click', (e) => {
    const isDropdown = e.target.classList.contains('candidate-status-dropdown');
    const isTrash = e.target.classList.contains('delete-candidate-btn');
    if (isDropdown || isTrash) return;

    const candidateId = cardElement.getAttribute('data-candidate-id');
    if (candidateId) {
      window.location.href = `/candidate-details.html?id=${candidateId}`;
    }
  });


  if (c.status) {
    const options = dropdown.options;
    let found = false;
    for (let i = 0; i < options.length; i++) {
      if (options[i].value.trim() === c.status.trim()) {
        options[i].selected = true;
        found = true;
        break;
      }
    }
    if (!found) {
      console.warn("⚠️ Status no encontrado en opciones:", c.status);
    }
  }


  // ✅ Listener funcional
  dropdown.addEventListener("change", async (e) => {
    const newStatus = e.target.value;
    const candidateId = c.candidate_id;
    const batchId = batch.batch_id;

    console.log("📥 Cambio en status");
    console.log("📌 candidateId:", candidateId);
    console.log("📌 batchId:", batchId);
    console.log("📌 newStatus:", newStatus);

    try {
      const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates_batches/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate_id: candidateId,
          batch_id: batchId,
          status: newStatus
        })
      });

      console.log("📤 Enviado al backend. Status HTTP:", res.status);
      const result = await res.json();
      console.log("📥 Respuesta del backend:", result);

      if (res.ok) {
        dropdown.value = newStatus;
        showFriendlyPopup("✅ Status updated");
      } else {
        showFriendlyPopup("❌ Error updating status");
      }
    } catch (err) {
      console.error("❌ Exception updating status:", err);
    }
  });

  candidateContainer.appendChild(cardElement);
          const trash = document.createElement("button");
      trash.innerHTML = "🗑️";
      trash.classList.add("delete-candidate-btn");
      trash.title = "Remove from batch";
      trash.style.marginLeft = "auto";
      trash.style.background = "none";
      trash.style.border = "none";
      trash.style.cursor = "pointer";
      trash.style.fontSize = "18px";

      trash.addEventListener("click", async () => {
        const confirmed = confirm(`⚠️ Remove ${c.name} from this batch?`);
        if (!confirmed) return;

        try {
          const res = await fetch("https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates_batches", {
            method: "DELETE",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              candidate_id: c.candidate_id,
              batch_id: batch.batch_id
            })
          });

          if (res.ok) {
            showFriendlyPopup("✅ Candidate removed from batch");
            await reloadBatchCandidates();
          } else {
            alert("❌ Failed to remove candidate");
          }
        } catch (err) {
          console.error("❌ Error removing candidate:", err);
          alert("❌ Could not remove candidate");
        }
      });

      const header = cardElement.querySelector(".candidate-card-header");
      header.insertBefore(trash, header.firstChild);



});


      // 🗑️ Agregar botón eliminar
      box.querySelector('.btn-delete').addEventListener('click', async (e) => {
        const confirmed = confirm("⚠️ Are you sure you want to delete this batch?");
        if (!confirmed) return;

        const batchId = e.target.getAttribute('data-batch-id');

        try {
          const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batchId}`, {
            method: 'DELETE'
          });

          if (res.ok) {
            alert('✅ Batch deleted successfully');
            await reloadBatchCandidates();
          } else {
            alert('❌ Error deleting batch');
          }
        } catch (err) {
          console.error('Error deleting batch:', err);
          alert('❌ Could not delete batch');
        }
      });

      container.appendChild(box);
    }

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

for (const batch of batches) {
  const box = document.createElement("div");
  box.classList.add("batch-box");
  box.setAttribute("data-batch-id", batch.batch_id);

  box.innerHTML = `
    <div class="batch-actions">
      <h3>Batch #${batch.batch_number}</h3>
      <div>
        <button class="btn-add">Add candidate</button>
        <button class="btn-send">Send for Approval</button>
        <button class="btn-delete" data-batch-id="${batch.batch_id}" title="Delete Batch">🗑️</button>
      </div>
    </div>
    <div class="batch-candidates"></div>
  `;
  // 👉 Este es el botón de Send for Approval
box.querySelector('.btn-send').addEventListener('click', () => openApprovalPopup(batch.batch_id));


  const candidateContainer = box.querySelector(".batch-candidates");

  // ✅ Aquí sí puedes usar await
  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batch.batch_id}/candidates`);
  const batchCandidates = await res.json();

  batchCandidates.forEach(c => {
    const template = document.getElementById("candidate-card-template");
    const cardFragment = template.content.cloneNode(true);
    const cardElement = cardFragment.querySelector(".candidate-card");
    const dropdown = cardElement.querySelector('.candidate-status-dropdown');
    dropdown.value = "Client interviewing/testing";

    console.log("🎯 Seteando status:", c.status);
    console.log("🧩 Opciones en dropdown:", [...dropdown.options].map(opt => opt.value));
    if (c.status) {
      const options = dropdown.options;
      let found = false;
      for (let i = 0; i < options.length; i++) {
        if (options[i].value.trim() === c.status.trim()) {
          options[i].selected = true;
          found = true;
          break;
        }
      }
      if (!found) {
        console.warn("⚠️ Status no encontrado en opciones:", c.status);
      }
    }


    cardElement.querySelectorAll(".candidate-name").forEach(el => el.textContent = c.name);
    cardElement.querySelector(".candidate-email").textContent = c.email || '';
    const salaryEl = document.createElement("span");
    salaryEl.classList.add("candidate-salary");
    salaryEl.textContent = c.salary_range ? `$${c.salary_range}` : '—';
    cardElement.querySelector(".info").appendChild(salaryEl);

    cardElement.querySelector(".candidate-img").src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;
    const statusDropdown = cardElement.querySelector(".candidate-status-dropdown");

batchCandidates.forEach(c => {
  const template = document.getElementById("candidate-card-template");
  const cardFragment = template.content.cloneNode(true);
  const cardElement = cardFragment.querySelector(".candidate-card");

  // Setear nombre, email, imagen
  cardElement.querySelectorAll(".candidate-name").forEach(el => el.textContent = c.name);
  cardElement.querySelector(".candidate-email").textContent = c.email || '';
  const salaryEl = document.createElement("span");
  salaryEl.classList.add("candidate-salary");
  salaryEl.textContent = c.salary_range ? `$${c.salary_range}` : '—';
  cardElement.querySelector(".info").appendChild(salaryEl);
  cardElement.querySelector(".candidate-img").src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;
  
  // Status dropdown
  const dropdown = cardElement.querySelector('.candidate-status-dropdown');
  dropdown.value = "Client interviewing/testing";

  console.log("🎯 Seteando status:", c.status);
  console.log("🧩 Opciones en dropdown:", [...dropdown.options].map(opt => opt.value));
  if (c.status) {
    const options = dropdown.options;
    let found = false;
    for (let i = 0; i < options.length; i++) {
      if (options[i].value.trim() === c.status.trim()) {
        options[i].selected = true;
        found = true;
        break;
      }
    }
    if (!found) {
      console.warn("⚠️ Status no encontrado en opciones:", c.status);
    }
  }

  // ✅ Listener funcional
  dropdown.addEventListener("change", async (e) => {
    const newStatus = e.target.value;
    const candidateId = c.candidate_id;
    const batchId = batch.batch_id;

    console.log("📥 Cambio en status");
    console.log("📌 candidateId:", candidateId);
    console.log("📌 batchId:", batchId);
    console.log("📌 newStatus:", newStatus);

    try {
      const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates_batches/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate_id: candidateId,
          batch_id: batchId,
          status: newStatus
        })
      });

      console.log("📤 Enviado al backend. Status HTTP:", res.status);
      const result = await res.json();
      console.log("📥 Respuesta del backend:", result);

      if (res.ok) {
        showFriendlyPopup("✅ Status updated");
      } else {
        showFriendlyPopup("❌ Error updating status");
      }
    } catch (err) {
      console.error("❌ Exception updating status:", err);
    }
  });

  candidateContainer.appendChild(cardElement);
});

    candidateContainer.appendChild(cardElement);
  });

  container.appendChild(box);
}


  } catch (err) {
    console.error("Error loading batches and candidates:", err);
  }
}
async function openApprovalPopup(batchId) {
  const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
// Obtener info completa de la oportunidad, incluyendo client_name
const [opportunityInfoRes, batchListRes] = await Promise.all([
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`),
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`)
]);
const opportunityInfo = await opportunityInfoRes.json();
const batchList = await batchListRes.json();
const batchInfo = batchList.find(b => b.batch_id === batchId);

const subject = `Batch#${batchInfo.batch_number} – ${opportunityInfo.opp_position_name} – ${opportunityInfo.account_name}`;

const [usersRes, batchCandidatesRes] = await Promise.all([
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/users`),
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batchId}/candidates`)
]);

const users = await usersRes.json();
const batchCandidates = await batchCandidatesRes.json();


  const toSelect = document.getElementById('approval-to');
  const ccSelect = document.getElementById('approval-cc');
  toSelect.innerHTML = '';
  ccSelect.innerHTML = '';

  users.forEach(user => {
    const option = document.createElement('option');
    option.value = user.email_vintti;
    option.textContent = user.user_name;
    toSelect.appendChild(option);

    const optionCc = option.cloneNode(true);
    ccSelect.appendChild(optionCc);
  });

  if (window.approvalToChoices) approvalToChoices.destroy();
  if (window.approvalCcChoices) approvalCcChoices.destroy();

  window.approvalToChoices = new Choices(toSelect, { removeItemButton: true });
  window.approvalCcChoices = new Choices(ccSelect, { removeItemButton: true });

  const yourName = localStorage.getItem('nickname') || 'The Vintti Team';

let candidateBlocks = '';

for (let c of batchCandidates) {
  try {
    const resumeUrl = `https://vinttihub.vintti.com/resume-readonly.html?id=${c.candidate_id}`;
    const aboutRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${c.candidate_id}`);
    const aboutData = await aboutRes.json();

    candidateBlocks += `
      <li style="margin-bottom: 10px;">
        <strong>Name:</strong> ${c.name}<br>
        <strong>Monthly Cost:</strong> $${c.salary_range || '—'}<br>
        <strong>Resume:</strong> <em><a href="${resumeUrl}" target="_blank">${resumeUrl}</a></em><br>
      </li>
    `;
  } catch (error) {
    console.error(`❌ Error procesando candidato ID ${c.candidate_id}:`, error);
  }
}

const body = `
  <p>Hi XXX,</p>
  <p>Hope you're doing great!</p>
  <p>
    XXX has handpicked a shortlist of candidates who align with everything you outlined — from experience to budget. 
    We’re confident you’ll find strong potential here.
  </p>
  <p>Please let us know your availability, and XXX will take care of scheduling the first round of interviews.</p>
  <p><strong>Candidates:</strong></p>
  <ul>${candidateBlocks}</ul>
  <p>
    Let us know what times work best and we’ll get things moving. Looking forward to your thoughts!
  </p>
  <p>Best,<br>${yourName}</p>
`;

document.getElementById('approval-message').innerHTML = body;


document.getElementById('approval-subject').value = subject;

document.getElementById('approvalEmailPopup').classList.remove('hidden');

}
function closeAiPopup() {
  document.getElementById('ai-assistant-popup').classList.add('hidden');
}
function showFriendlyPopup(message) {
  const popup = document.createElement('div');
  popup.textContent = message;
  popup.style.position = 'fixed';
  popup.style.top = '20px';
  popup.style.right = '20px';
  popup.style.backgroundColor = '#ffe4ec';
  popup.style.color = '#b3005f';
  popup.style.padding = '14px 20px';
  popup.style.borderRadius = '20px';
  popup.style.fontWeight = '600';
  popup.style.boxShadow = '0 4px 10px rgba(0,0,0,0.1)';
  popup.style.zIndex = '9999';
  popup.style.transition = 'opacity 0.3s ease';
  popup.style.opacity = '1';
  popup.style.fontFamily = 'Quicksand, sans-serif';

  document.body.appendChild(popup);

  setTimeout(() => {
    popup.style.opacity = '0';
    setTimeout(() => popup.remove(), 300);
  }, 3000);
}
function insertEmoji(emoji) {
  const editor = document.getElementById('job-description-textarea');
  editor.focus();
  document.execCommand('insertText', false, emoji);
}
function getFlagEmoji(country) {
  const flags = {
    "Argentina": "🇦🇷", "Bolivia": "🇧🇴", "Brazil": "🇧🇷", "Chile": "🇨🇱",
    "Colombia": "🇨🇴", "Costa Rica": "🇨🇷", "Cuba": "🇨🇺", "Ecuador": "🇪🇨",
    "El Salvador": "🇸🇻", "Guatemala": "🇬🇹", "Honduras": "🇭🇳", "Mexico": "🇲🇽",
    "Nicaragua": "🇳🇮", "Panama": "🇵🇦", "Paraguay": "🇵🇾", "Peru": "🇵🇪",
    "Puerto Rico": "🇵🇷", "Dominican Republic": "🇩🇴", "Uruguay": "🇺🇾", "Venezuela": "🇻🇪"
  };
  return flags[country] || "";
}
function toggleActiveButton(command, button) {
  document.execCommand(command, false, '');
  button.classList.toggle('active');
}
