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
  // === Fetch candidate info ===
fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates/${candidateId}`)
  .then(response => response.json())
  .then(data => {
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


  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/resumes/${candidateId}`)
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

    fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/resumes/${candidateId}`, {
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
    fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates/${candidateId}`)
      .then(response => response.json())
      .then(data => {
        aiLinkedIn.value = data.linkedin || '';
      });

    aiButton.addEventListener('click', () => {
      aiPopup.classList.toggle('hidden');
    });

    document.getElementById('ai-submit').addEventListener('click', () => {
      const pdfFile = document.getElementById('ai-pdf').files[0];
      const comments = document.getElementById('ai-comments').value.trim();

      console.log('🚀 AI Action Triggered');
      console.log('LinkedIn:', aiLinkedIn.value);
      console.log('PDF File:', pdfFile);
      console.log('Comments:', comments);

      // Aquí puedes agregar la lógica para subir el PDF y enviar los datos si quieres.
      alert('AI Action sent! 🚀');

      // Opcional: cerrar popup
      aiPopup.classList.add('hidden');
    });
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
  });
});

