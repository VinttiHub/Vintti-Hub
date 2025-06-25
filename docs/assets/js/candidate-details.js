document.addEventListener("DOMContentLoaded", () => {
  const savedTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);

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

  hireWorkingSchedule.addEventListener('blur', () => updateHireField('working_schedule', hireWorkingSchedule.value));
  hirePTO.addEventListener('blur', () => updateHireField('pto', hirePTO.value));

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
      const div = field.querySelector('div');
      const id = label ? label.textContent.trim().toLowerCase() : '';

      switch (id) {
        case 'name':
          div.textContent = data.name || '—';
          break;
        case 'country':
          div.textContent = data.country || '—';
          break;
        case 'phone number':
          div.textContent = data.phone || '—';
          break;
        case 'email':
          div.textContent = data.email || '—';
          break;
        case 'linkedin':
          const linkedinLink = document.getElementById('linkedin');
          if (linkedinLink) {
            linkedinLink.href = data.linkedin || '#';
          }
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
  })
  .catch(err => {
    console.error('❌ Error fetching candidate:', err);
  });


  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`)
    .then(res => res.json())
    .then(data => {
      aboutP.innerText = data.about || '';
      JSON.parse(data.education || '[]').forEach(entry => addEducationEntry(entry));
      JSON.parse(data.work_experience || '[]').forEach(entry => addWorkExperienceEntry(entry));
      JSON.parse(data.tools || '[]').forEach(entry => addToolEntry(entry));
      videoLinkInput.value = data.video_link || '';
    });

  function addEducationEntry(entry = { institution: '', start_date: '', end_date: '', current: false, description: '' }) {
    const div = document.createElement('div');
    div.className = 'cv-card-entry pulse';
    div.innerHTML = `
      <input type="text" class="edu-title" value="${entry.institution}" placeholder="Institution"/>
      <label>Start Date: <input type="date" class="edu-start" value="${entry.start_date}"></label>
      <label>End Date: <input type="date" class="edu-end" value="${entry.end_date}" ${entry.current ? 'disabled' : ''}></label>
      <label><input type="checkbox" class="edu-current" ${entry.current ? 'checked' : ''}/> Current</label>
      <textarea class="edu-desc" placeholder="Description">${entry.description}</textarea>
      <button class="remove-entry">🗑️</button>
    `;
    setTimeout(() => div.classList.remove('pulse'), 500);
    div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
    div.querySelector('.edu-current').onchange = e => {
      div.querySelector('.edu-end').disabled = e.target.checked;
      saveResume();
    };
    div.querySelectorAll('input, textarea').forEach(el => el.addEventListener('blur', saveResume));
    educationList.appendChild(div);
  }

  function addWorkExperienceEntry(entry = { title: '', company: '', start_date: '', end_date: '', current: false, description: '' }) {
    const div = document.createElement('div');
    div.className = 'cv-card-entry pulse';
    div.innerHTML = `
      <input type="text" class="work-title" value="${entry.title}" placeholder="Title"/>
      <input type="text" class="work-company" value="${entry.company}" placeholder="Company"/>
      <label>Start Date: <input type="date" class="work-start" value="${entry.start_date}"></label>
      <label>End Date: <input type="date" class="work-end" value="${entry.end_date}" ${entry.current ? 'disabled' : ''}></label>
      <label><input type="checkbox" class="work-current" ${entry.current ? 'checked' : ''}/> Current</label>
      <textarea class="work-desc" placeholder="Description">${entry.description}</textarea>
      <button class="remove-entry">🗑️</button>
    `;
    setTimeout(() => div.classList.remove('pulse'), 500);
    div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
    div.querySelector('.work-current').onchange = e => {
      div.querySelector('.work-end').disabled = e.target.checked;
      saveResume();
    };
    div.querySelectorAll('input, textarea').forEach(el => el.addEventListener('blur', saveResume));
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
      start_date: div.querySelector('.edu-start').value,
      end_date: div.querySelector('.edu-end').value,
      current: div.querySelector('.edu-current').checked,
      description: div.querySelector('.edu-desc').value.trim(),
    }));

    const work_experience = Array.from(document.querySelectorAll('#workExperienceList .cv-card-entry')).map(div => ({
      title: div.querySelector('.work-title').value.trim(),
      company: div.querySelector('.work-company').value.trim(),
      start_date: div.querySelector('.work-start').value,
      end_date: div.querySelector('.work-end').value,
      current: div.querySelector('.work-current').checked,
      description: div.querySelector('.work-desc').value.trim(),
    }));

    const tools = Array.from(document.querySelectorAll('#toolsList .cv-card-entry')).map(div => ({
      tool: div.querySelector('.tool-name').value.trim(),
      level: div.querySelector('.tool-level').value,
    }));

    const video_link = document.getElementById('videoLinkInput').value.trim();

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        about,
        education: JSON.stringify(education),
        work_experience: JSON.stringify(work_experience),
        tools: JSON.stringify(tools),
        video_link,
      }),
    });
  }
  // === AI Popup Logic ===
    const aiButton = document.getElementById('ai-action-button');
    const aiPopup = document.getElementById('ai-popup');
    const aiLinkedIn = document.getElementById('ai-linkedin');

    // Mostrar LinkedIn automáticamente en popup
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`)
      .then(response => response.json())
      .then(data => {
        aiLinkedIn.value = data.linkedin || '';
      });

    aiButton.addEventListener('click', () => {
      aiPopup.classList.toggle('hidden');
    });

    document.getElementById('ai-submit').addEventListener('click', () => {
      const pdfFile = document.getElementById('ai-pdf').files[0];
      if (pdfFile) {
        const formData = new FormData();
        formData.append('candidate_id', candidateId);
        formData.append('pdf', pdfFile);

        // 1️⃣ Primero subir a S3
        fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/upload_pdf', {
          method: 'POST',
          body: formData,
        })
        .then(response => response.json())
        .then(data => {
          console.log('✅ PDF uploaded:', data.pdf_url);
          alert('PDF uploaded successfully!');

          // 2️⃣ Después enviar a Affinda
          return fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/extract_pdf_affinda', {
            method: 'POST',
            body: formData
          });
        })
        .then(res => res.json())
        .then(data => {
          console.log('✅ Extracción completa', data.extracted);
        })
        .catch(error => {
          console.error('❌ Error en el flujo de carga y extracción:', error);
          alert('Error uploading or extracting PDF');
        });
      }

      const comments = document.getElementById('ai-comments').value.trim();

      console.log('🚀 AI Action Triggered');
      console.log('LinkedIn:', aiLinkedIn.value);
      console.log('PDF File:', pdfFile);
      console.log('Comments:', comments);
      // 3️⃣ Obtener extract_cv_pdf y cv_pdf_s3 del backend
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`)
        .then(res => res.json())
        .then(data => {
          const extractCvPdf = data.extract_cv_pdf || '';
          const cvPdfS3 = data.cv_pdf_s3 || '';

          // 4️⃣ Enviar todo a ChatGPT a través de tu nuevo endpoint
          return fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/generate_resume_fields', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              candidate_id: candidateId,
              extract_cv_pdf: extractCvPdf,
              cv_pdf_s3: cvPdfS3,
              comments: comments
            })
          });
        })
        .then(res => res.json())
        .then(aiData => {
          console.log('✅ AI completed:', aiData);

          // 5️⃣ Guardar automáticamente la respuesta en la tabla resume
          return fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              about: aiData.about,
              work_experience: JSON.stringify(aiData.work_experience),
              education: JSON.stringify(aiData.education),
              tools: JSON.stringify(aiData.tools),
            })
          });
        })
        .then(() => {
          alert('Resume fields updated successfully!');
          location.reload(); // refrescar para ver los nuevos datos
        })
        .catch(err => {
          console.error('❌ Error in AI flow:', err);
          alert('Error generating resume fields');
        });

      // Opcional: cerrar popup
      aiPopup.classList.add('hidden');
    });
  // 👇 AGREGAR ESTO AL FINAL DEL DOMContentLoaded
  if (document.querySelector('.tab.active')?.dataset.tab === 'opportunities') {
    loadOpportunitiesForCandidate();
  }
  const hireSalary = document.getElementById('hire-salary');
const hireFee = document.getElementById('hire-fee');
const hireRevenue = document.getElementById('hire-revenue');
const hireComputer = document.getElementById('hire-computer');
const hirePerks = document.getElementById('hire-extraperks');

if (document.querySelector('.tab.active')?.dataset.tab === 'hire') {
  loadHireData();
}
function updateHireField(field, value) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ [field]: value })
  }).then(() => loadHireData());
}

[hireSalary, hireFee].forEach(input => {
  input.addEventListener('blur', () => {
    updateHireField(input.id === 'hire-salary' ? 'employee_salary' : 'employee_fee', Number(input.value));
  });
});

hireComputer.addEventListener('change', () => updateHireField('computer', hireComputer.value));
hirePerks.addEventListener('blur', () => updateHireField('extraperks', hirePerks.value));
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

addSalaryUpdateBtn.addEventListener('click', () => {
  popup.classList.remove('hidden');
});

saveUpdateBtn.addEventListener('click', () => {
  const salary = parseFloat(salaryInput.value);
  const fee = parseFloat(feeInput.value);
  if (!salary || !fee) return alert('Please fill both fields');

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/salary_updates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ salary, fee })
  }).then(() => {
    popup.classList.add('hidden');
    salaryInput.value = '';
    feeInput.value = '';
    loadSalaryUpdates();
  });
});

if (document.querySelector('.tab.active')?.dataset.tab === 'hire') {
  loadSalaryUpdates();
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
    
    if (tabId === 'resume') {
      aiButton.style.display = 'flex';
    } else {
      aiButton.style.display = 'none';
      aiPopup.classList.add('hidden'); // Cierra popup si cambian de pestaña
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
        `;
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
      document.getElementById('hire-salary').value = data.employee_salary || '';
      document.getElementById('hire-fee').value = data.employee_fee || '';
      document.getElementById('hire-computer').value = data.computer || '';
      document.getElementById('hire-extraperks').value = data.extraperks || '';
      document.getElementById('hire-revenue').value = (data.employee_revenue || 0);
      document.getElementById('hire-working-schedule').value = data.working_schedule || '';
      document.getElementById('hire-pto').value = data.pto || '';
    });
}