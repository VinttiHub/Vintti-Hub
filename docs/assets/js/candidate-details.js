
document.addEventListener("DOMContentLoaded", () => {
  window.updateHireField = function(field, value) {
  const candidateId = new URLSearchParams(window.location.search).get('id');
  if (!candidateId) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [field]: value })
  }).then(() => loadHireData());
};
  document.documentElement.setAttribute('data-theme', 'light');
  const urlParams = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get('id');
  if (!candidateId) return;

  const aboutP = document.getElementById('aboutField');
  aboutP.contentEditable = "true";
  aboutP.addEventListener('blur', () => saveResume());

  const educationList = document.getElementById('educationList');
  const addEducationBtn = document.getElementById('addEducationBtn');
  addEducationBtn.addEventListener('click', () => addEducationEntry());

  const workExperienceList = document.getElementById('workExperienceList');
  const addWorkExperienceBtn = document.getElementById('addWorkExperienceBtn');
  addWorkExperienceBtn.addEventListener('click', () => addWorkExperienceEntry());

  const toolsList = document.getElementById('toolsList');
  const addToolBtn = document.getElementById('addToolBtn');
  addToolBtn.addEventListener('click', () => addToolEntry());

  const videoLinkInput = document.getElementById('videoLinkInput');
  videoLinkInput.addEventListener('blur', () => saveResume());
  const hireWorkingSchedule = document.getElementById('hire-working-schedule');
  const hirePTO = document.getElementById('hire-pto');
  const hireStartDate = document.getElementById('hire-start-date');
  const video_link = videoLinkInput.innerHTML.trim();

  hireWorkingSchedule.addEventListener('blur', () => updateHireField('working_schedule', hireWorkingSchedule.value));
  hirePTO.addEventListener('blur', () => updateHireField('pto', hirePTO.value));
  if (hireStartDate) {
    hireStartDate.addEventListener('blur', () => updateHireField('start_date', hireStartDate.value));
  }

  // === Fetch candidate info ===
fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`)
  .then(response => response.json())
  .then(data => {
    const overviewFields = {
      'field-name': 'name',
      'field-country': 'country',
      'field-phone': 'phone',
      'field-email': 'email',
      'field-english-level': 'english_level',
      'field-salary-range': 'salary_range',
    };

    Object.entries(overviewFields).forEach(([elementId, fieldName]) => {
      const el = document.getElementById(elementId);
      if (el) {
        if (fieldName === 'country') {
          el.addEventListener('change', () => {
            fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ country: el.value })
            });
          });
        } else {
          // Asigna el valor directamente desde la base
          const value = data[fieldName];
          if (value) el.innerText = value;

          el.contentEditable = true;
          el.addEventListener('blur', () => {
            const updatedValue = el.innerText.trim();
            fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ [fieldName]: updatedValue })
            });
          });
        }
      }
    });

    const openBtn = document.getElementById('linkedin-open-btn');
    let linkedinUrl = (data.linkedin || '').trim();
    linkedinUrl = linkedinUrl.replace(/^[-–—\s]+/, ''); // elimina guiones largos y espacios del inicio

    console.log("🔗 Clean LinkedIn:", linkedinUrl);

    if (linkedinUrl.startsWith('http')) {
      openBtn.href = linkedinUrl;
      openBtn.style.display = 'inline-flex';
      openBtn.style.visibility = 'visible';
      openBtn.style.opacity = 1;
      openBtn.addEventListener('click', (e) => {
        e.preventDefault(); // evita conflictos si el href no es válido
        if (linkedinUrl && linkedinUrl.startsWith('http')) {
          window.open(linkedinUrl, '_blank');
        } else {
          console.warn("❌ Invalid LinkedIn URL:", linkedinUrl);
        }
      });
    } else {
      openBtn.style.display = 'none';
    }
    console.log("🎯 Valor desde DB:", data.country);

    const flagEmoji = getFlagEmoji(data.country || '');
    const countryFlagSpan = document.getElementById('country-flag');
    countryFlagSpan.textContent = flagEmoji;
    const countrySelect = document.getElementById('field-country');

    countrySelect.addEventListener('change', () => {
      countryFlagSpan.textContent = getFlagEmoji(countrySelect.value);
    });

    // === Guardar cambios de comentarios y red flags ===
    ['redFlags', 'comments'].forEach(id => {
      const textarea = document.getElementById(id);
      textarea.addEventListener('blur', () => {
        const field = id === 'redFlags' ? 'red_flags' : 'comments';
        fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [field]: textarea.value.trim() })
        });
      });
    });

    document.querySelectorAll('#overview .field').forEach(field => {
      const label = field.querySelector('label');
      const div = field.querySelector('div, select, input, span');
      const id = label ? label.textContent.replace(/[^\w\s]/gi, '').trim().toLowerCase() : '';

      if (!div) return; // Evita errores si no hay ningún div/select/input/span

      switch (id) {
        case 'name':
          div.textContent = data.name || '—';
          break;
        case 'country':
          const select = document.getElementById('field-country');
          if (select && data.country) {
            select.value = data.country;
            const flagSpan = document.getElementById('country-flag');
            if (flagSpan) flagSpan.textContent = getFlagEmoji(data.country);
          }
          break;
        case 'phone number':
          div.textContent = data.phone || '—';
          break;
        case 'email':
          div.textContent = data.email || '—';
          break;
        case 'linkedin':
          const linkedinField = document.getElementById('field-linkedin');
          if (linkedinField) linkedinField.textContent = data.linkedin || '—';
          break;
        case 'english level':
          div.textContent = data.english_level || '—';
          break;
        case 'min salary':
          div.textContent = data.salary_range || '—';
          break;
      }
    });

    document.getElementById('redFlags').value = data.red_flags || '';
    document.getElementById('comments').value = data.comments || '';
    document.getElementById("field-created-by").textContent = data.created_by || '—';
    document.getElementById("field-created-at").textContent = data.created_at ? new Date(data.created_at).toLocaleString() : '—';
  })
  .catch(err => {
    console.error('❌ Error fetching candidate:', err);
  });


  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`)
    .then(res => res.json())
    .then(data => {
      aboutP.innerText = data.about || '';
      JSON.parse(data.work_experience || '[]').forEach(entry => addWorkExperienceEntry(entry));
      JSON.parse(data.education || '[]').forEach(entry => addEducationEntry(entry));
      JSON.parse(data.tools || '[]').forEach(entry => addToolEntry(entry));
      videoLinkInput.value = data.video_link || '';
    });

function addEducationEntry(entry = { institution: '', title: '', start_date: '', end_date: '', current: false, description: '' }) {
  const div = document.createElement('div');
  div.className = 'cv-card-entry pulse';
  div.innerHTML = `
    <div style="display: flex; gap: 20px; flex-wrap: wrap;">
      <div style="flex: 2.5; min-width: 320px;">
        <input type="text" class="edu-title" value="${entry.institution}" placeholder="Institution" />
        <input type="text" class="edu-degree" value="${entry.title || ''}" placeholder="Title/Degree" style="margin-top: 6px;" />
      </div>

      <div style="flex: 1.5; min-width: 300px;">
        <div style="display: flex; gap: 10px;">
          <label style="flex: 1;">Start<br/><input type="date" class="edu-start" value="${entry.start_date}" /></label>
          <label style="flex: 1;">End<br/><input type="date" class="edu-end" value="${entry.end_date}" ${entry.current ? 'disabled' : ''} /></label>
        </div>
        <div style="display: flex; justify-content: flex-end; padding-right: 62px; padding-top: -52px">
          <label style="display: flex; align-items: center; gap: 4px; font-size: 13px; white-space: nowrap; text-transform: none;">
            <input type="checkbox" class="edu-current" ${entry.current ? 'checked' : ''}/> Current
          </label>
        </div>
      </div>
    </div>
    <div class="rich-toolbar">
      <button type="button" data-command="bold"><b>B</b></button>
      <button type="button" data-command="italic"><i>I</i></button>
      <button type="button" data-command="insertUnorderedList">• List</button>
    </div>
    <div class="edu-desc rich-input" contenteditable="true" placeholder="Description" style="min-height: 240px;">${entry.description}</div>
    <button class="remove-entry">🗑️</button>
  `;
  div.querySelectorAll('.rich-toolbar button').forEach(button => {
    button.addEventListener('click', () => {
      const command = button.getAttribute('data-command');
      const targetId = button.getAttribute('data-target');
      const target = targetId ? document.getElementById(targetId) : document.getSelection().focusNode?.parentElement;

      if (target && target.isContentEditable) {
        target.focus();
        document.execCommand(command, false, null);
      }
      const isActive = document.queryCommandState(command);
      button.classList.toggle('active', isActive);
    });
  });

  setTimeout(() => div.classList.remove('pulse'), 500);
  div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
  div.querySelector('.edu-current').onchange = e => {
    div.querySelector('.edu-end').disabled = e.target.checked;
    saveResume();
  };
  div.querySelectorAll('input, .rich-input').forEach(el => el.addEventListener('blur', saveResume));
  educationList.appendChild(div);
}


function addWorkExperienceEntry(entry = { title: '', company: '', start_date: '', end_date: '', current: false, description: '' }) {
  const div = document.createElement('div');
  div.className = 'cv-card-entry pulse';
  div.innerHTML = `
    <div style="display: flex; gap: 20px; flex-wrap: wrap;">
      <div style="flex: 2.5; min-width: 320px;">
        <input type="text" class="work-title" value="${entry.title}" placeholder="Title" />
        <input type="text" class="work-company" value="${entry.company}" placeholder="Company" style="margin-top: 6px;" />
      </div>

      <div style="flex: 1.5; min-width: 300px;">
        <div style="display: flex; gap: 10px;">
          <label style="flex: 1;">Start<br/><input type="date" class="work-start" value="${entry.start_date}" /></label>
          <label style="flex: 1;">End<br/><input type="date" class="work-end" value="${entry.end_date}" ${entry.current ? 'disabled' : ''} /></label>
        </div>
        <div style="display: flex; justify-content: flex-end; padding-top: -52px; padding-right: 62px;">
          <label style="display: flex; align-items: center; gap: 4px; font-size: 13px; white-space: nowrap;">
            <input type="checkbox" class="work-current" ${entry.current ? 'checked' : ''}/> Current
          </label>
        </div>
      </div>
    </div>
    <div class="rich-toolbar">
      <button type="button" data-command="bold"><b>B</b></button>
      <button type="button" data-command="italic"><i>I</i></button>
      <button type="button" data-command="insertUnorderedList">• List</button>
    </div>
    <div class="work-desc rich-input" contenteditable="true" placeholder="Description" style="min-height: 240px;">${entry.description}</div>
    <button class="remove-entry">🗑️</button>
  `;

  div.querySelectorAll('.rich-toolbar button').forEach(button => {
    button.addEventListener('click', () => {
      const command = button.getAttribute('data-command');
      const targetId = button.getAttribute('data-target');
      const target = targetId ? document.getElementById(targetId) : document.getSelection().focusNode?.parentElement;

      if (target && target.isContentEditable) {
        target.focus();
        document.execCommand(command, false, null);
      }
      const isActive = document.queryCommandState(command);
      button.classList.toggle('active', isActive);
    });
  });

  setTimeout(() => div.classList.remove('pulse'), 500);
  div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
  div.querySelector('.work-current').onchange = e => {
    div.querySelector('.work-end').disabled = e.target.checked;
    saveResume();
  };
  div.querySelectorAll('input, .rich-input').forEach(el => el.addEventListener('blur', saveResume));
  workExperienceList.appendChild(div);
}


  function addToolEntry(entry = { tool: '', level: 'Basic' }) {
    const div = document.createElement('div');
    div.className = 'cv-card-entry pulse';
    div.innerHTML = `
      <input type="text" class="tool-name" value="${entry.tool}" placeholder="Tool Name"/>
      <select class="tool-level">
        <option value="Basic" ${entry.level === 'Basic' ? 'selected' : ''}>Basic</option>
        <option value="Intermediate" ${entry.level === 'Intermediate' ? 'selected' : ''}>Intermediate</option>
        <option value="Advanced" ${entry.level === 'Advanced' ? 'selected' : ''}>Advanced</option>
      </select>
      <button class="remove-entry">🗑️</button>
    `;
    setTimeout(() => div.classList.remove('pulse'), 500);
    div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
    div.querySelectorAll('input, select').forEach(el => {
      el.addEventListener('blur', saveResume);
      el.addEventListener('change', saveResume);
    });
    toolsList.appendChild(div);
  }

  function saveResume() {
    const about = document.getElementById('aboutField').innerText.trim();

      const education = Array.from(document.querySelectorAll('#educationList .cv-card-entry')).map(div => ({
        institution: div.querySelector('.edu-title').value.trim(),
        title: div.querySelector('.edu-degree').value.trim(),
        start_date: div.querySelector('.edu-start').value,
        end_date: div.querySelector('.edu-end').value,
        current: div.querySelector('.edu-current').checked,
        description: div.querySelector('.edu-desc').innerHTML.trim(),
      }));


    const work_experience = Array.from(document.querySelectorAll('#workExperienceList .cv-card-entry')).map(div => ({
      title: div.querySelector('.work-title').value.trim(),
      company: div.querySelector('.work-company').value.trim(),
      start_date: div.querySelector('.work-start').value,
      end_date: div.querySelector('.work-end').value,
      current: div.querySelector('.work-current').checked,
      description: div.querySelector('.work-desc').innerHTML.trim(),
    }));

    const tools = Array.from(document.querySelectorAll('#toolsList .cv-card-entry')).map(div => ({
      tool: div.querySelector('.tool-name').value.trim(),
      level: div.querySelector('.tool-level').value,
    }));

    const videoLinkDiv = document.getElementById('videoLinkInput');
    const video_link = videoLinkDiv?.innerText?.trim() || null;
    console.log("📝 Saving resume with:", {
      about,
      education,
      work_experience,
      tools,
      video_link,
    });

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        about,
        education,  // sin JSON.stringify
        work_experience,
        tools,
        video_link,
      }),
    });

  }
  // === AI Popup Logic ===
  const aiButton = document.getElementById('ai-action-button');
  aiButton.classList.add('hidden');
  const aiPopup = document.getElementById('ai-popup');
  const aiLinkedInScrap = document.getElementById('ai-linkedin-scrap');
  const aiCvScrap = document.getElementById('ai-cv-scrap');

  aiButton.addEventListener('click', () => {
    aiPopup.classList.toggle('hidden');
  });

  // Obtener los datos del backend
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`)
    .then(res => res.json())
    .then(data => {
      aiLinkedInScrap.value = data.linkedin_scrapper || '';
      aiCvScrap.value = data.cv_pdf_scrapper || '';
      const bothEmpty = !data.linkedin_scrapper && !data.cv_pdf_scrapper;
      // ⭐ Habilitar solo botón de About si existe entry en tabla resume
      const aboutStarBtn = document.querySelector('#about-star-button');
      if (aboutStarBtn) {
        fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`)
          .then(res => {
            if (!res.ok) throw new Error("No resume found");
            return res.json();
          })
          .then(() => {
            aboutStarBtn.classList.remove('disabled-star');
          })
          .catch(() => {
            aboutStarBtn.classList.add('disabled-star');
            aboutStarBtn.addEventListener('click', e => {
              e.preventDefault();
              e.stopPropagation();
            });
            aboutStarBtn.addEventListener('mouseenter', () => showStarTooltip(aboutStarBtn, 'Please complete resume first.'));
            aboutStarBtn.addEventListener('mouseleave', hideStarTooltip);
          });
      }

      document.querySelectorAll('.star-button').forEach(btn => {
        if (bothEmpty) {
          btn.classList.add('disabled-star');

          // Tooltip + bloquear acción
          btn.addEventListener('click', e => {
            e.preventDefault();
            e.stopPropagation();
          });

          btn.addEventListener('mouseenter', () => {
            showStarTooltip(btn);
          });

          btn.addEventListener('mouseleave', hideStarTooltip);
        }
      });
    });
    

  // Guardar en blur
  aiLinkedInScrap.addEventListener('blur', () => {
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ linkedin_scrapper: aiLinkedInScrap.value.trim() })
    });
  });

  aiCvScrap.addEventListener('blur', () => {
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cv_pdf_scrapper: aiCvScrap.value.trim() })
    });
  });
  document.getElementById('ai-close').addEventListener('click', () => {
  document.getElementById('ai-popup').classList.add('hidden');
});
if (document.querySelector('.tab.active')?.dataset.tab === 'resume') {
  aiButton.classList.remove('hidden');
  clientBtn.classList.remove('hidden');
  clientBtn.style.display = 'inline-block';
}

  // 👇 AGREGAR ESTO AL FINAL DEL DOMContentLoaded
  if (document.querySelector('.tab.active')?.dataset.tab === 'opportunities') {
    loadOpportunitiesForCandidate();
  }
  // Verifica si el candidato está contratado y oculta la pestaña Hire si no lo está
fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/is_hired`)
  .then(res => res.json())
  .then(data => {
    if (!data.is_hired) {
      const hireTab = document.querySelector('.tab[data-tab="hire"]');
      const hireContent = document.getElementById('hire');
      if (hireTab) hireTab.style.display = 'none';
      if (hireContent) hireContent.style.display = 'none';
    }
  });

  const hireSalary = document.getElementById('hire-salary');
const hireFee = document.getElementById('hire-fee');
const hireComputer = document.getElementById('hire-computer');
const hirePerks = document.getElementById('hire-extraperks');
console.log(document.getElementById('hire-extraperks').innerHTML)

if (document.querySelector('.tab.active')?.dataset.tab === 'hire') {
  loadHireData();
}

hireComputer.addEventListener('change', () => updateHireField('computer', hireComputer.value));
hirePerks.addEventListener('blur', () => {
  updateHireField('extraperks', hirePerks.innerHTML);
});
const hash = window.location.hash;
if (hash === '#hire') {
  const hireTab = document.querySelector('.tab[data-tab="hire"]');
  if (hireTab) hireTab.click();

  // 🎉 Mostrar fuegos artificiales y mensaje SOLO si viene desde Close Win
  if (localStorage.getItem('fromCloseWin') === 'true') {
    localStorage.removeItem('fromCloseWin'); // Limpiamos el flag para que no se repita

    // 🎆 Animación de fuegos artificiales
    const msg = document.createElement('div');
    msg.className = 'apple-hire-notice';
    msg.textContent = 'Now please complete the Hire fields';
    document.body.appendChild(msg);
    setTimeout(() => msg.remove(), 6000);
  }
}
// === SALARY UPDATES ===
const salaryUpdatesBox = document.getElementById('salary-updates-box');
const addSalaryUpdateBtn = document.getElementById('add-salary-update');
const popup = document.getElementById('salary-update-popup');
const saveUpdateBtn = document.getElementById('save-salary-update');
const salaryInput = document.getElementById('update-salary');
const feeInput = document.getElementById('update-fee');

function loadSalaryUpdates() {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/salary_updates`)
    .then(res => res.json())
    .then(data => {
      salaryUpdatesBox.innerHTML = '';
      data.forEach(update => {
        const div = document.createElement('div');
        div.className = 'salary-entry';
        div.innerHTML = `
          <span>💰 Salary updated to $${update.salary}, Fee to $${update.fee} on ${new Date(update.date).toLocaleDateString()}</span>
          <button data-id="${update.update_id}" class="delete-salary-update">🗑️</button>
        `;
        salaryUpdatesBox.appendChild(div);
      });

      document.querySelectorAll('.delete-salary-update').forEach(btn => {
        btn.addEventListener('click', () => {
          const id = btn.dataset.id;
          fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/salary_updates/${id}`, {
            method: 'DELETE'
          }).then(() => loadSalaryUpdates());
        });
      });
    });
}
hireSalary.addEventListener('blur', async () => {
  const salary = parseFloat(hireSalary.value);
  if (!salary || isNaN(salary)) return;

  await updateHireField('employee_salary', salary);

  const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
  const fee = parseFloat(hireFee.value);
  if (model?.includes('staffing') && !isNaN(fee)) {
    const revenue = salary + fee;
    document.getElementById('hire-revenue').value = revenue;
    await updateHireField('employee_revenue', revenue);
  }
});

hireFee.addEventListener('blur', async () => {
  const fee = parseFloat(hireFee.value);
  if (!fee || isNaN(fee)) return;

  await updateHireField('employee_fee', fee);

  const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
  const salary = parseFloat(hireSalary.value);
  if (model?.includes('staffing') && !isNaN(salary)) {
    const revenue = salary + fee;
    document.getElementById('hire-revenue').value = revenue;
    await updateHireField('employee_revenue', revenue);
  }
});

addSalaryUpdateBtn.addEventListener('click', () => {
  popup.classList.remove('hidden');
});

saveUpdateBtn.addEventListener('click', () => {
  const salary = parseFloat(salaryInput.value);
  const fee = parseFloat(feeInput.value);
  const date = document.getElementById('update-date').value;
  if (salaryInput.value === '' || feeInput.value === '' || !date) {
      return alert('Please fill all fields');
    }


  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/salary_updates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ salary, fee, date })
  }).then(() => {
    popup.classList.add('hidden');
    salaryInput.value = '';
    feeInput.value = '';
    document.getElementById('update-date').value = '';
    loadSalaryUpdates();
  });
});


if (document.querySelector('.tab.active')?.dataset.tab === 'hire') {
  loadSalaryUpdates();
}
document.getElementById('ai-submit').addEventListener('click', async () => {
  const linkedin_scrapper = document.getElementById('ai-linkedin-scrap').value.trim();
  const cv_pdf_scrapper = document.getElementById('ai-cv-scrap').value.trim();
  const candidateId = new URLSearchParams(window.location.search).get('id');
  if (!linkedin_scrapper && !cv_pdf_scrapper) return;

  // 👉 Mostrar mensaje de carga
  startResumeLoader();

  try {
    const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/generate_resume_fields', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId, linkedin_scrapper, cv_pdf_scrapper })
    });

    const result = await response.json();

    if (result.about) document.getElementById('aboutField').innerText = result.about;

    if (result.education) {
      document.getElementById('educationList').innerHTML = '';
      JSON.parse(result.education).forEach(entry => addEducationEntry(entry));
    }

    if (result.work_experience) {
      document.getElementById('workExperienceList').innerHTML = '';
      JSON.parse(result.work_experience).forEach(entry => addWorkExperienceEntry(entry));
    }

    if (result.tools) {
      document.getElementById('toolsList').innerHTML = '';
      JSON.parse(result.tools).forEach(entry => addToolEntry(entry));
    }

    // ✅ Cerrar popup
    document.getElementById('ai-popup').classList.add('hidden');
  } catch (err) {
    console.error('❌ Error generating resume:', err);
    alert("Something went wrong while generating the resume. Please try again.");
  } finally {
    // ✅ Ocultar loader sin importar si funcionó o falló
    stopResumeLoader();
  }
});
document.querySelectorAll('.star-button').forEach(button => {
  const popupId = button.getAttribute('data-target');

  button.addEventListener('click', e => {
    if (button.classList.contains('disabled-star')) {
      e.preventDefault();
      e.stopPropagation();
      return;
    }

    document.querySelectorAll('.star-popup').forEach(p => p.classList.add('hidden'));
    document.getElementById(popupId).classList.remove('hidden');
  });
});

document.querySelectorAll('.star-popup .generate-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const popup = btn.closest('.star-popup');
    const textarea = popup.querySelector('textarea');
    console.log('💬 Generate comment for:', popup.id, 'Text:', textarea.value);
    popup.classList.add('hidden');
  });
});

window.addEventListener('click', (e) => {
  if (e.target.classList.contains('star-popup')) {
    e.target.classList.add('hidden');
  }
});
document.querySelectorAll('.close-star-popup').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.closest('.star-popup').classList.add('hidden');
  });
});
document.querySelector('#popup-about .generate-btn').addEventListener('click', async () => {
  const candidateId = new URLSearchParams(window.location.search).get('id');
  const textarea = document.querySelector('#popup-about textarea');
  const userPrompt = textarea.value.trim();
  const loader = document.getElementById('about-loader');

  loader.classList.remove('hidden');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/ai/improve_about', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId, user_prompt: userPrompt })
    });

    const data = await res.json();
    if (data.about) {
      document.getElementById('aboutField').innerText = data.about;
    }

    document.getElementById('popup-about').classList.add('hidden');
  } catch (err) {
    console.error("❌ Error updating about:", err);
    alert("Error improving About section. Try again.");
  } finally {
    loader.classList.add('hidden');
  }
});
document.querySelector('#popup-education .generate-btn').addEventListener('click', async () => {
  const candidateId = new URLSearchParams(window.location.search).get('id');
  const textarea = document.querySelector('#popup-education textarea');
  const userPrompt = textarea.value.trim();
  const loader = document.getElementById('about-loader'); // reutilizamos este loader

  if (!userPrompt) return alert("Please add a comment before generating.");

  loader.querySelector('span').innerText = "Improving Education section...";
  loader.classList.remove('hidden');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/ai/improve_education', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId, user_prompt: userPrompt })
    });

    const data = await res.json();
    if (data.education) {
      document.getElementById('educationList').innerHTML = '';
      JSON.parse(data.education).forEach(entry => addEducationEntry(entry));
    }

    document.getElementById('popup-education').classList.add('hidden');
  } catch (err) {
    console.error("❌ Error updating education:", err);
    alert("Error improving Education section. Try again.");
  } finally {
    loader.classList.add('hidden');
  }
});
document.querySelector('#popup-work .generate-btn').addEventListener('click', async () => {
  const candidateId = new URLSearchParams(window.location.search).get('id');
  const textarea = document.querySelector('#popup-work textarea');
  const userPrompt = textarea.value.trim();
  const loader = document.getElementById('work-loader');

  if (!userPrompt) return alert("Please add a comment before generating.");

  loader.classList.remove('hidden');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/ai/improve_work_experience', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId, user_prompt: userPrompt })
    });

    const data = await res.json();
    if (data.work_experience) {
      document.getElementById('workExperienceList').innerHTML = '';
      JSON.parse(data.work_experience).forEach(entry => addWorkExperienceEntry(entry));
    }

    document.getElementById('popup-work').classList.add('hidden');
  } catch (err) {
    console.error("❌ Error improving work experience:", err);
    alert("Error improving Work Experience section. Try again.");
  } finally {
    loader.classList.add('hidden');
  }
});
document.querySelector('#popup-tools .generate-btn').addEventListener('click', async () => {
  const candidateId = new URLSearchParams(window.location.search).get('id');
  const textarea = document.querySelector('#popup-tools textarea');
  const userPrompt = textarea.value.trim();
  const loader = document.getElementById('tools-loader');

  if (!userPrompt) return alert("Please add a comment before generating.");

  loader.classList.remove('hidden');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/ai/improve_tools', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId, user_prompt: userPrompt })
    });

    const data = await res.json();
    if (data.tools) {
      document.getElementById('toolsList').innerHTML = '';
      JSON.parse(data.tools).forEach(entry => addToolEntry(entry));
    }

    document.getElementById('popup-tools').classList.add('hidden');
  } catch (err) {
    console.error("❌ Error improving tools:", err);
    alert("Error improving Tools section. Try again.");
  } finally {
    loader.classList.add('hidden');
  }
});
function showStarTooltip(button) {
  const tooltip = document.createElement('div');
  tooltip.className = 'star-tooltip';
  tooltip.textContent = 'Please use the AI Assistant button first.';
  button.appendChild(tooltip);
}

function hideStarTooltip() {
  document.querySelectorAll('.star-tooltip').forEach(el => el.remove());
}
const referencesDiv = document.getElementById('hire-references');

// Guardar en blur
referencesDiv.addEventListener('blur', () => {
  updateHireField('references_notes', referencesDiv.innerHTML);
});

// Toolbar logic
document.querySelectorAll('.rich-toolbar button').forEach(button => {
  button.addEventListener('click', () => {
    const command = button.getAttribute('data-command');
    const targetId = button.getAttribute('data-target');
    const target = targetId ? document.getElementById(targetId) : document.getSelection().focusNode?.parentElement;

    if (target && target.isContentEditable) {
      target.focus();
      document.execCommand(command, false, null);
    }
    const isActive = document.queryCommandState(command);
    button.classList.toggle('active', isActive);
  });
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
const phrases = [
  "Las chicas lindas saben esperar 💅✨",
  "Gracias por tu paciencia, sos la mejor Vinttituta 💖👑",
  "Keep calm and deja que Vinttihub te lo solucione 😌🛠️",
  "Tranquila reina, tu CV está en buenas manos 📄👑",
  "Si esto fuera un casting de modelos, ya estarías contratada 😍 Solo falta tu resume 👑",
  "Las Vinttitutas no se apuran, se hacen desear 💁‍♀️💫",
  "Generando algo genial para que le mandes a tu clientito ✨📤💌"
];

let currentPhraseIndex = 0;
const phraseEl = document.getElementById('resume-loader-phrase');

function startResumeLoader() {
  document.getElementById('resume-loader').classList.remove('hidden');
  updatePhrase();
}

function stopResumeLoader() {
  document.getElementById('resume-loader').classList.add('hidden');
  currentPhraseIndex = 0;
}

function updatePhrase() {
  phraseEl.style.opacity = 0;
  setTimeout(() => {
    phraseEl.innerText = phrases[currentPhraseIndex];
    phraseEl.style.opacity = 1;
    currentPhraseIndex = (currentPhraseIndex + 1) % phrases.length;
  }, 400);

  setTimeout(updatePhrase, 3000); // Cambia cada 5 segundos (2.5s de lectura x2)
}









});

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const tabId = tab.dataset.tab;

    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    tab.classList.add('active');
    document.getElementById(tabId).classList.add('active');

    // Mostrar / ocultar el botón de AI Assistant solo en Resume
    const aiButton = document.getElementById('ai-action-button');
    const aiPopup = document.getElementById('ai-popup');
    const clientBtn = document.getElementById('client-version-btn');

    if (tabId === 'resume') {
      aiButton.classList.remove('hidden');
      clientBtn.classList.remove('hidden');
      clientBtn.style.display = 'inline-block';
    } else {
      aiButton.classList.add('hidden');
      clientBtn.style.display = 'none';
    }

    if (tabId === 'opportunities') {
      loadOpportunitiesForCandidate();
    }
    if (tabId === 'hire') {
      loadHireData();
    }
  });
});

window.loadOpportunitiesForCandidate = function () {
  const candidateId = new URLSearchParams(window.location.search).get('id');
  if (!candidateId) return;
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/opportunities`)
    .then(res => res.json())
    .then(data => {
      const tbody = document.querySelector("#opportunitiesTable tbody");
      tbody.innerHTML = "";
      data.forEach(opp => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${opp.opportunity_id}</td>
          <td>${opp.opp_model || ''}</td>
          <td>${opp.opp_position_name || ''}</td>
          <td>${opp.opp_sales_lead || ''}</td>
          <td>${opp.opp_stage || ''}</td>
          <td>${opp.client_name || ''}</td>
          <td>${opp.opp_hr_lead || ''}</td>
        `;
        row.addEventListener('click', () => {
          window.location.href = `./opportunity-detail.html?id=${opp.opportunity_id}`;
        });
        tbody.appendChild(row);
      });
    });
};
function loadHireData() {
  const candidateId = new URLSearchParams(window.location.search).get('id');
  if (!candidateId) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`)
    .then(res => res.json())
.then(data => {
  const salaryInput = document.getElementById('hire-salary');
  const feeInput = document.getElementById('hire-fee');

  salaryInput.value = data.employee_salary || '';
  feeInput.value = data.employee_fee || '';
  document.getElementById('hire-computer').value = data.computer || '';
  document.getElementById('hire-extraperks').innerHTML = data.extraperks || '';
  console.log(document.getElementById('hire-extraperks').innerHTML)
  document.getElementById('hire-revenue').value = (data.employee_revenue || 0);
  document.getElementById('hire-working-schedule').value = data.working_schedule || '';
  document.getElementById('hire-pto').value = data.pto || '';
  document.getElementById('hire-start-date').value = data.start_date || '';
  document.getElementById('hire-references').innerHTML = data.references_notes || '';


  // Deshabilitar salary y fee si ya tienen valores
  if (data.employee_salary && parseFloat(data.employee_salary) > 0) {
    salaryInput.disabled = true;
  }
  if (data.employee_fee && parseFloat(data.employee_fee) > 0) {
    feeInput.disabled = true;
  }
});

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/opportunities`)
  .then(res => res.json())
  .then(data => {
    const model = data[0]?.opp_model;
    if (model) {
      document.getElementById('opp-model-pill').textContent = `Model: ${model}`;
      adaptHireFieldsByModel(model);
    }
  });
const salaryInput = document.getElementById('hire-salary');
const feeInput = document.getElementById('hire-fee');
const tipMessage = "To update salary or fee, please use the 'Salary Updates' section below.";
[salaryInput, feeInput].forEach(input => {
  input.addEventListener('mouseenter', () => {
    if (input.disabled) showTooltip(input, tipMessage);
  });

  input.addEventListener('mouseleave', hideTooltip);
  input.addEventListener('click', () => {
    if (input.disabled) showTooltip(input, tipMessage);
  });
});



function showTooltip(input, message) {
  if (document.querySelector('.input-tooltip')) return;
  const tooltip = document.createElement('div');
  tooltip.className = 'input-tooltip';
  tooltip.textContent = message;

  const rect = input.getBoundingClientRect();
  tooltip.style.position = 'absolute';
  tooltip.style.left = `${rect.left + window.scrollX}px`;
  tooltip.style.top = `${rect.bottom + 5 + window.scrollY}px`;
  tooltip.style.backgroundColor = '#333';
  tooltip.style.color = '#fff';
  tooltip.style.padding = '6px 10px';
  tooltip.style.borderRadius = '6px';
  tooltip.style.fontSize = '13px';
  tooltip.style.zIndex = 1000;
  tooltip.style.boxShadow = '0 2px 6px rgba(0,0,0,0.2)';
  tooltip.style.pointerEvents = 'none';

  document.body.appendChild(tooltip);
}

function hideTooltip() {
  const tooltip = document.querySelector('.input-tooltip');
  if (tooltip) tooltip.remove();
}

}
function adaptHireFieldsByModel(model) {
  const feeField = document.getElementById('hire-fee').closest('.field');
  const revenueInput = document.getElementById('hire-revenue');

  if (model.toLowerCase() === 'recruiting') {
    // Oculta el campo fee
    feeField.style.display = 'none';

    // Hace revenue editable
    revenueInput.disabled = false;

    // Actualizar ambos con blur
    ['hire-salary', 'hire-revenue'].forEach(id => {
      const el = document.getElementById(id);
      el.addEventListener('blur', () => {
        const field = id === 'hire-salary' ? 'employee_salary' : 'employee_revenue';
        updateHireField(field, el.value);
      });
    });

  } else if (model.toLowerCase() === 'staffing') {
    // Mostrar fee
    feeField.style.display = 'block';

    // Desactiva edición manual en revenue
    revenueInput.disabled = true;

    // Calcular revenue automáticamente
    ['hire-salary', 'hire-fee'].forEach(id => {
      const el = document.getElementById(id);
      el.addEventListener('blur', async () => {
        const salary = Number(document.getElementById('hire-salary').value);
        const fee = Number(document.getElementById('hire-fee').value);
        if (!salary || !fee) return;

        // Actualiza campos individuales
        const field = id === 'hire-salary' ? 'employee_salary' : 'employee_fee';
        await updateHireField(field, el.value);

        const revenue = salary + fee;
        document.getElementById('hire-revenue').value = revenue;

        await updateHireField('employee_revenue', revenue);
      });
    });
  }
}
document.querySelectorAll('.tab').forEach(button => {
  button.addEventListener('click', () => {
    const selectedTab = button.getAttribute('data-tab');

    const aiButton = document.getElementById('ai-action-button');
    const clientBtn = document.getElementById('client-version-btn');
    clientBtn.classList.add('hidden');
    const candidateId = new URLSearchParams(window.location.search).get('id');
    
    if (clientBtn && candidateId) {
      clientBtn.href = `resume-readonly.html?id=${candidateId}`;
    }

    if (selectedTab === 'resume') {
      aiButton.style.display = 'flex';
      clientBtn.style.display = 'inline-block';
      clientBtn.classList.remove('hidden');

    } else {
      aiButton.style.display = 'none';
      clientBtn.style.display = 'none';
    }
  });
});

function getFlagEmoji(countryName) {
  const flags = {
    "Argentina": "🇦🇷", "Bolivia": "🇧🇴", "Brazil": "🇧🇷", "Chile": "🇨🇱",
    "Colombia": "🇨🇴", "Costa Rica": "🇨🇷", "Cuba": "🇨🇺", "Dominican Republic": "🇩🇴",
    "Ecuador": "🇪🇨", "El Salvador": "🇸🇻", "Guatemala": "🇬🇹", "Honduras": "🇭🇳",
    "Mexico": "🇲🇽", "Nicaragua": "🇳🇮", "Panama": "🇵🇦", "Paraguay": "🇵🇾",
    "Peru": "🇵🇪", "Uruguay": "🇺🇾", "Venezuela": "🇻🇪"
  };
  return flags[countryName] || '';
}
