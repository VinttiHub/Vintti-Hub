
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


  const hireWorkingSchedule = document.getElementById('hire-working-schedule');
  const hirePTO = document.getElementById('hire-pto');
  const hireStartDate = document.getElementById('hire-start-date');
  const hireEndDate = document.getElementById('hire-end-date');

  hireWorkingSchedule.addEventListener('blur', () => updateHireField('working_schedule', hireWorkingSchedule.value));
  hirePTO.addEventListener('blur', () => updateHireField('pto', hirePTO.value));
// === HIRE DATES: usar input nativo día/mes/año y aislar del estilo de Resume ===
(function restoreHireDates() {
  const hostStart = document.getElementById('hire-start-picker');
  const hostEnd   = document.getElementById('hire-end-picker');

  // Inyecta inputs nativos dentro de los contenedores existentes (no cambia HTML)
  if (hostStart && !hostStart.querySelector('input[type="date"]')) {
    hostStart.innerHTML = '<input type="date" id="hire-start-date" />';
  }
  if (hostEnd && !hostEnd.querySelector('input[type="date"]')) {
    hostEnd.innerHTML = '<input type="date" id="hire-end-date" />';
  }

  const startInp = document.getElementById('hire-start-date');
  const endInp   = document.getElementById('hire-end-date');

  if (startInp) {
    startInp.addEventListener('change', () => {
      updateHireField('start_date', startInp.value || '');
    });
  }
  if (endInp) {
    endInp.addEventListener('change', () => {
      updateHireField('end_date', endInp.value || '');
    });
  }

  // Asegura que nada intente usar los pickers de mes/año en Hire
  window._startPicker = undefined;
  window._endPicker = undefined;
})();

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
          const value = data[fieldName];
          
          if (el.tagName === 'SELECT') {
            if (value) el.value = value;

            el.addEventListener('change', () => {
              fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [fieldName]: el.value })
              });
            });
          } else {
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
      }
    });

    const openBtn = document.getElementById('linkedin-open-btn');
    let linkedinUrl = (data.linkedin || '').trim();
    // limpia guiones/espacios iniciales (— – -)
    linkedinUrl = linkedinUrl.replace(/^[-–—\s]+/, '');

    console.log("🔗 Clean LinkedIn:", linkedinUrl);

    if (openBtn) {
      if (linkedinUrl.startsWith('www')) linkedinUrl = 'https://' + linkedinUrl;
      if (linkedinUrl.startsWith('http')) {
        openBtn.href = linkedinUrl;
        openBtn.style.display = 'inline-flex';
        openBtn.style.visibility = 'visible';
        openBtn.style.opacity = 1;
        openBtn.onclick = (e) => {
          e.preventDefault();
          window.open(linkedinUrl, '_blank');
        };
      } else {
        openBtn.style.display = 'none';
      }
    }

    // Llama a Coresignal solo si NO hay coresignal_scrapper y el LinkedIn es válido
    if (!data.coresignal_scrapper && linkedinUrl && linkedinUrl.startsWith('http')) {
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/coresignal/candidates/${candidateId}/sync`, { method: 'POST' })
        .then(async r => {
          let payload;
          try { payload = await r.json(); } catch { payload = await r.text(); }
          console.log('🔄 Coresignal sync:', { ok: r.ok, status: r.status, payload });
        })
              .then(r => r.json())
            .then(d => console.log('🔄 Coresignal sync:', d))
        .catch(e => console.warn('⚠️ Coresignal sync failed', e));
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
          const englishSelect = document.getElementById('field-english-level');
          if (englishSelect && data.english_level) {
            englishSelect.value = data.english_level;
          }
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
// ✅ VIDEO LINK: carga y guardado desacoplado del resto del resume
const videoLinkEl = document.getElementById('videoLinkInput');
if (videoLinkEl) {
  const normalizeUrl = (u) => {
    let v = (u || '').trim();
    // quitar espacios internos comunes al pegar
    v = v.replace(/\s+/g, '');
    if (v && !/^https?:\/\//i.test(v)) v = 'https://' + v.replace(/^\/+/, '');
    return v;
  };

  // Exponer al scope global para refrescar cuando cambias de pestaña
  window.loadVideoLink = async function () {
    const cid = new URLSearchParams(window.location.search).get('id');
    if (!cid) return;
    try {
      const r = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${cid}`);
      const d = await r.json();
      const v = (d.video_link ?? '').toString();
      if (videoLinkEl.textContent !== v) videoLinkEl.textContent = v; // 👈 contenteditable usa textContent
      videoLinkEl.dataset.original = v; // guarda valor original
    } catch (e) {
      console.warn('⚠️ No se pudo cargar video_link:', e);
    }
  };

  async function persistVideoLink() {
    const cid = new URLSearchParams(window.location.search).get('id');
    if (!cid) return;

    let val = normalizeUrl(videoLinkEl.textContent); // 👈 leer del contenteditable
    videoLinkEl.textContent = val;

    // Evita PATCH si no cambió
    if ((videoLinkEl.dataset.original || '') === val) return;

    try {
      await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${cid}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ video_link: val })
      });
      videoLinkEl.dataset.original = val; // sincronizado
    } catch (e) {
      console.error('❌ Error guardando video_link:', e);
    }
  }

  // Disparadores de guardado
  videoLinkEl.addEventListener('blur', persistVideoLink);
  // En contenteditable "change" NO dispara; no lo uses
  videoLinkEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); videoLinkEl.blur(); }
  });

  // Carga inicial
  loadVideoLink();
}
    // 🔁 Autogenerar linkedin_scrapper DESDE coresignal_scrapper si aplica
    const apiBase = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
    const hasCore = (data.coresignal_scrapper || '').trim().length > 0;
    const hasLinkedinScrap = (data.linkedin_scrapper || '').trim().length > 0;

    if (hasCore && !hasLinkedinScrap) {
      // Opcional: pequeño indicador no bloqueante en la esquina (reutiliza si ya tienes algo similar)
      console.log('🧠 Building linkedin_scrapper from coresignal_scrapper…');

      fetch(`${apiBase}/ai/coresignal_to_linkedin_scrapper`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ candidate_id: candidateId })
      })
      .then(r => r.json())
      .then(r => {
        // Actualiza UI en caliente si existe el textarea oculto/visible
        const aiLinkedInScrap = document.getElementById('ai-linkedin-scrap');
        if (aiLinkedInScrap) {
          aiLinkedInScrap.addEventListener('blur', () => {
            fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ linkedin_scrapper: aiLinkedInScrap.value.trim() })
            });
          });
        }
        if (aiLinkedInScrap && r.linkedin_scrapper) {
          aiLinkedInScrap.value = r.linkedin_scrapper;
        }
        console.log('✅ linkedin_scrapper updated from coresignal:', !!r.linkedin_scrapper);
      })
      .catch(err => console.warn('⚠️ coresignal_to_linkedin_scrapper failed', err));
    }

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
      JSON.parse(data.languages || '[]').forEach(entry => addLanguageEntry(entry));
const videoLinkEl2 = document.getElementById('videoLinkInput');
if (videoLinkEl2) {
  const v = (data.video_link ?? '').toString();
  if (videoLinkEl2.textContent !== v) videoLinkEl2.textContent = v; // 👈 usar textContent
  videoLinkEl2.dataset.original = v;
}

    });

function addEducationEntry(entry = { institution: '', title: '', country: '', start_date: '', end_date: '', current: false, description: '' }) {
  const id = uniqId('edu');
  const startCid = `edu-start-${id}`;
  const endCid   = `edu-end-${id}`;

  const div = document.createElement('div');
  div.className = 'cv-card-entry pulse';

  div.innerHTML = `
    <div style="display:flex; gap:20px; flex-wrap:wrap;">
      <div style="flex:2.2; min-width:320px;">
        <input type="text" class="edu-title" value="${entry.institution || ''}" placeholder="Institution" />
        <input type="text" class="edu-degree" value="${entry.title || ''}" placeholder="Title/Degree" style="margin-top:6px;" />
        <select class="edu-country" style="margin-top:6px; width:100%;">${makeCountryOptions(entry.country || '')}</select>
      </div>

      <div style="flex:2; min-width:360px;">
        <div style="display:flex; gap:10px;">
          <label style="flex:1;">Start<br/>
            <div id="${startCid}" class="month-year"></div>
            <input type="hidden" class="edu-start" value="">
          </label>
          <label style="flex:1;">End<br/>
            <div id="${endCid}" class="month-year"></div>
            <input type="hidden" class="edu-end" value="">
          </label>
        </div>
        <div style="display:flex; justify-content:flex-end; padding-right:62px;">
          <label style="display:flex; align-items:center; gap:4px; font-size:13px; white-space:nowrap;">
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
    <div class="edu-desc rich-input" contenteditable="true" placeholder="Description" style="min-height:240px;">${entry.description || ''}</div>
    <button class="remove-entry">🗑️</button>
  `;

  // Toolbar rich text
  div.querySelectorAll('.rich-toolbar button').forEach(btn => {
    btn.addEventListener('click', () => {
      const cmd = btn.getAttribute('data-command');
      const target = document.getSelection().focusNode?.parentElement;
      if (target && target.isContentEditable) { target.focus(); document.execCommand(cmd, false, null); }
      btn.classList.toggle('active', document.queryCommandState(cmd));
    });
  });

  setTimeout(() => div.classList.remove('pulse'), 500);

  // Eventos de entry
  div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
  div.querySelector('.edu-country').addEventListener('change', saveResume);
  div.querySelectorAll('input, .rich-input').forEach(el => el.addEventListener('blur', saveResume));

  educationList.appendChild(div);

  // 🔗 Hidden inputs que usará saveResume()
  const hiddenStart = div.querySelector('.edu-start');
  const hiddenEnd   = div.querySelector('.edu-end');

  // 🗓️ Montar pickers (Start/End) — forzamos día 15 en el valor emitido
  const startPicker = mountMonthYearPicker(startCid, {
    allowEmpty: true,
    initialValue: entry.start_date || '',
    onChange: (iso) => { hiddenStart.value = iso; saveResume(); }
  });

  const endPicker = mountMonthYearPicker(endCid, {
    allowEmpty: true,
    initialValue: entry.current ? '' : (entry.end_date || ''),
    onChange: (iso) => { hiddenEnd.value = iso; saveResume(); }
  });

  // Inicializar hidden con lo que vino del backend
  hiddenStart.value = entry.start_date || '';
  hiddenEnd.value   = entry.current ? 'Present' : (entry.end_date || '');

  // ✅ Current toggle: deshabilita el picker de End y guarda "Present"
  const currentCb = div.querySelector('.edu-current');
  currentCb.addEventListener('change', e => {
    if (e.target.checked) {
      // recuerda el último iso para volver si desmarcan
      hiddenEnd.dataset.lastIso = hiddenEnd.value && hiddenEnd.value !== 'Present' ? hiddenEnd.value : '';
      hiddenEnd.value = 'Present';
      disableMonthYear(endCid, true, 'Education marked as current.');
    } else {
      disableMonthYear(endCid, false);
      const last = hiddenEnd.dataset.lastIso || '';
      if (last) { endPicker.setValue(last); hiddenEnd.value = last; }
      else { endPicker.setValue(''); hiddenEnd.value = ''; }
    }
    saveResume();
  });

  // Si ya venía "current", deshabilita el picker de End
  if (entry.current) disableMonthYear(endCid, true, 'Education marked as current.');

  // Ordenar tras agregar
  sortEntriesByEndDate('educationList', '.cv-card-entry', '.edu-end', '.edu-current');
}


function addWorkExperienceEntry(entry = { title: '', company: '', start_date: '', end_date: '', current: false, description: '' }) {
  const id = uniqId('work');
  const startCid = `work-start-${id}`;
  const endCid   = `work-end-${id}`;

  const div = document.createElement('div');
  div.className = 'cv-card-entry pulse';
  // guardamos ids para localizar filas luego
  div.dataset.workStartCid = startCid;
  div.dataset.workEndCid = endCid;

  div.innerHTML = `
    <div style="display:flex; gap:20px; flex-wrap:wrap;">
      <div style="flex:2.2; min-width:320px;">
        <input type="text" class="work-title" value="${entry.title || ''}" placeholder="Title" />
        <input type="text" class="work-company" value="${entry.company || ''}" placeholder="Company" style="margin-top:6px;" />
        <div class="cv-switch" style="margin-top:10px;">
          <span>Multiple roles in this company</span>
          <input type="checkbox" class="mr-toggle"/>
        </div>
      </div>

      <div style="flex:2; min-width:360px;">
        <div style="display:flex; gap:10px;">
          <label style="flex:1;">Start<br/>
            <div id="${startCid}" class="month-year"></div>
            <input type="hidden" class="work-start" value="">
          </label>
          <label style="flex:1;">End<br/>
            <div id="${endCid}" class="month-year"></div>
            <input type="hidden" class="work-end" value="">
          </label>
        </div>
        <div style="display:flex; justify-content:flex-end; padding-right:62px;">
          <label style="display:flex; align-items:center; gap:4px; font-size:13px; white-space:nowrap;">
            <input type="checkbox" class="work-current" ${entry.current ? 'checked' : ''}/> Current
          </label>
        </div>
      </div>
    </div>

    <div class="mr-wrap">
      <div class="mr-list"></div>
      <button type="button" class="btn-soft mr-add">Add role</button>
    </div>

    <div class="rich-toolbar">
      <button type="button" data-command="bold"><b>B</b></button>
      <button type="button" data-command="italic"><i>I</i></button>
      <button type="button" data-command="insertUnorderedList">• List</button>
    </div>
    <div class="work-desc rich-input" contenteditable="true" placeholder="Description" style="min-height:240px;">${entry.description || ''}</div>
    <button class="remove-entry">🗑️</button>
  `;

  // Toolbar rich text (solo aplica si NO está en modo multi-roles)
  div.querySelectorAll('.rich-toolbar button').forEach(btn => {
    btn.addEventListener('click', () => {
      if (div.dataset.mr === '1') return; // description lo generamos en MR
      const cmd = btn.getAttribute('data-command');
      const target = div.querySelector('.work-desc');
      target.focus(); document.execCommand(cmd, false, null);
      btn.classList.toggle('active', document.queryCommandState(cmd));
      saveResume();
    });
  });

  setTimeout(() => div.classList.remove('pulse'), 500);
  div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
  div.querySelectorAll('input, .rich-input').forEach(el => el.addEventListener('blur', ()=>{ if (div.dataset.mr!=='1') saveResume(); }));

  workExperienceList.appendChild(div);
  // Hidden que usa saveResume()
  const hiddenStart = div.querySelector('.work-start');
  const hiddenEnd   = div.querySelector('.work-end');

  // Montar pickers principales
  const startPicker = mountMonthYearPicker(startCid, {
    allowEmpty: true,
    initialValue: entry.start_date || '',
    onChange: (iso) => { hiddenStart.value = iso; if (div.dataset.mr!=='1') saveResume(); }
  });

  const endPicker = mountMonthYearPicker(endCid, {
    allowEmpty: true,
    initialValue: entry.current ? '' : (entry.end_date || ''),
    onChange: (iso) => { hiddenEnd.value = iso; if (div.dataset.mr!=='1') saveResume(); }
  });

  // Inicial
  hiddenStart.value = entry.start_date || '';
  hiddenEnd.value   = entry.current ? 'Present' : (entry.end_date || '');

  // Current toggle principal
  const currentCb = div.querySelector('.work-current');
  currentCb.addEventListener('change', e => {
    if (div.dataset.mr === '1') return; // en MR lo controlan los sub-roles
    if (e.target.checked) {
      hiddenEnd.dataset.lastIso = hiddenEnd.value && hiddenEnd.value !== 'Present' ? hiddenEnd.value : '';
      hiddenEnd.value = 'Present';
      disableMonthYear(endCid, true, 'Work experience marked as current.');
    } else {
      disableMonthYear(endCid, false);
      const last = hiddenEnd.dataset.lastIso || '';
      if (last) { endPicker.setValue(last); hiddenEnd.value = last; }
      else { endPicker.setValue(''); hiddenEnd.value = ''; }
    }
    saveResume();
  });
  if (entry.current) disableMonthYear(endCid, true, 'Work experience marked as current.');

  // === MULTI-ROLES wiring
  const mrToggle = div.querySelector('.mr-toggle');
  const mrAddBtn = div.querySelector('.mr-add');

mrToggle.addEventListener('change', ()=>{
  enableMultiRolesOnCard(div, mrToggle.checked);
  if (mrToggle.checked){
    if (!div.querySelector('.mr-entry')) addMiniRole(div);
    // 🔥 fuerza sincronización inmediata para que se guarde el pack:
    syncMultiRolesToDescription(div);
  } else {
    saveResume();
  }
});

  mrAddBtn.addEventListener('click', ()=>{
    addMiniRole(div);
    syncMultiRolesToDescription(div);
  });

  // Hidratar desde description si ya trae paquete MR
  const hydrated = tryHydrateMultiFromDescription(div, entry.description || '');
  if (!hydrated){
    // Si no está en MR, habilita edición normal
    enableMultiRolesOnCard(div, false);
  }

  // Ordenar tras agregar
  sortEntriesByEndDate('workExperienceList', '.cv-card-entry', '.work-end', '.work-current');
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
function addLanguageEntry(entry = { language: '', level: 'Basic' }) {
  const div = document.createElement('div');
  div.className = 'cv-card-entry pulse';
  div.innerHTML = `
    <select class="language-name">
      <option value="">Select Language</option>
      <option value="English" ${entry.language === 'English' ? 'selected' : ''}>English</option>
      <option value="Spanish" ${entry.language === 'Spanish' ? 'selected' : ''}>Spanish</option>
      <option value="Portuguese" ${entry.language === 'Portuguese' ? 'selected' : ''}>Portuguese</option>
      <option value="French" ${entry.language === 'French' ? 'selected' : ''}>French</option>
      <option value="German" ${entry.language === 'German' ? 'selected' : ''}>German</option>
    </select>
    <select class="language-level">
      <option value="Basic" ${entry.level === 'Basic' ? 'selected' : ''}>Basic</option>
      <option value="Regular" ${entry.level === 'Regular' ? 'selected' : ''}>Regular</option>
      <option value="Fluent" ${entry.level === 'Fluent' ? 'selected' : ''}>Fluent</option>
      <option value="Native" ${entry.level === 'Native' ? 'selected' : ''}>Native</option>
    </select>
    <button class="remove-entry">🗑️</button>
  `;
  setTimeout(() => div.classList.remove('pulse'), 500);
  div.querySelector('.remove-entry').onclick = () => { div.remove(); saveResume(); };
  div.querySelectorAll('select').forEach(el => {
    el.addEventListener('blur', saveResume);
    el.addEventListener('change', saveResume);
  });
  document.getElementById('languagesList').appendChild(div);
}

function saveResume() {
  const about = document.getElementById('aboutField').innerText.trim();

  const education = Array.from(document.querySelectorAll('#educationList .cv-card-entry')).map(div => {
    const startRaw = (div.querySelector('.edu-start')?.value || '').trim();
    const endRaw   = (div.querySelector('.edu-end')?.value || '').trim();
    return {
      institution: div.querySelector('.edu-title').value.trim(),
      title:       div.querySelector('.edu-degree').value.trim(),
      country:     (div.querySelector('.edu-country')?.value || '').trim(),
      start_date:  normalizeISO15(startRaw),
      end_date:    normalizeISO15(endRaw),
      current:     div.querySelector('.edu-current').checked,
      description: div.querySelector('.edu-desc').innerHTML.trim(),
    };
  });

  const work_experience = Array.from(document.querySelectorAll('#workExperienceList .cv-card-entry')).map(div => {
    const startRaw = (div.querySelector('.work-start')?.value || '').trim();
    const endRaw   = (div.querySelector('.work-end')?.value || '').trim();
    return {
      title:       div.querySelector('.work-title').value.trim(),
      company:     div.querySelector('.work-company').value.trim(),
      start_date:  normalizeISO15(startRaw),
      end_date:    normalizeISO15(endRaw),
      current:     div.querySelector('.work-current').checked,
      // 👇 En modo multi-roles, .work-desc contiene el <div class="mr-pack"> que ya sincronizamos.
      description: div.querySelector('.work-desc').innerHTML.trim(),
    };
  });

  const tools = Array.from(document.querySelectorAll('#toolsList .cv-card-entry')).map(div => ({
    tool:  div.querySelector('.tool-name').value.trim(),
    level: div.querySelector('.tool-level').value,
  }));

  const languages = Array.from(document.querySelectorAll('#languagesList .cv-card-entry')).map(div => ({
    language: div.querySelector('.language-name').value.trim(),
    level:    div.querySelector('.language-level').value
  }));

  // ✅ IMPORTANTE: enviar como STRINGS JSON (tu backend devuelve strings y luego los parseas)
  const payload = {
    about,
    education: JSON.stringify(education),
    work_experience: JSON.stringify(work_experience),
    tools: JSON.stringify(tools),
    languages: JSON.stringify(languages),
  };

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${candidateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  .then(async (r) => {
    const txt = await r.text().catch(()=> '');
    if (!r.ok) {
      console.error('❌ PATCH /resumes fallo', r.status, txt);
    } else {
      console.debug('✅ Resume guardado (incluye multi-roles)');
    }
  })
  .then(() => {
    // Reordenar después de guardar
    sortEntriesByEndDate('workExperienceList', '.cv-card-entry', '.work-end', '.work-current');
    sortEntriesByEndDate('educationList', '.cv-card-entry', '.edu-end', '.edu-current');
  });
}
window.saveResume = saveResume;
  // === AI Popup Logic ===
  const aiButton = document.getElementById('ai-action-button');
  if (aiButton) {
    aiButton.classList.add('hidden');
    aiButton.addEventListener('click', () => {
      const aiPopup = document.getElementById('ai-popup');
      if (aiPopup) aiPopup.classList.toggle('hidden');
    });
  }

  const aiLinkedInScrap = document.getElementById('ai-linkedin-scrap');
  const aiCvScrap       = document.getElementById('ai-cv-scrap');

  const setAIScrapsFrom = (d) => {
    if (aiLinkedInScrap) aiLinkedInScrap.value = d.linkedin_scrapper || '';
    if (aiCvScrap)       aiCvScrap.value       = d.cv_pdf_scrapper   || '';
  };


  // Obtener los datos del backend
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`)
    .then(res => res.json())
    .then(data => {
      setAIScrapsFrom(data);
        const hasAnySource =
          (data.linkedin_scrapper && data.linkedin_scrapper.trim()) ||
          (data.cv_pdf_scrapper && data.cv_pdf_scrapper.trim()) ||
          (data.affinda_scrapper && data.affinda_scrapper.trim()) ||
          (data.coresignal_scrapper && data.coresignal_scrapper.trim()) ||
          (data.linkedin && data.linkedin.trim());
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

    // 👇 calcula si NO hay ninguna fuente (linkedin/cv/affinda/coresignal/url)
    const bothEmpty = !(
      (data.linkedin_scrapper && data.linkedin_scrapper.trim()) ||
      (data.cv_pdf_scrapper && data.cv_pdf_scrapper.trim()) ||
      (data.affinda_scrapper && data.affinda_scrapper.trim()) ||
      (data.coresignal_scrapper && data.coresignal_scrapper.trim()) ||
      (data.linkedin && data.linkedin.trim())
    );

    // Aplica estado + bloqueo + tooltip en un solo paso
    document.querySelectorAll('.star-button').forEach(btn => {
      btn.classList.toggle('disabled-star', bothEmpty);

      if (bothEmpty) {
        const block = (e) => { e.preventDefault(); e.stopPropagation(); };
        btn.addEventListener('click', block);
        btn.addEventListener('mouseenter', () => showStarTooltip(btn));
        btn.addEventListener('mouseleave', hideStarTooltip);
      }
    });

    });
    if (aiLinkedInScrap) {
    aiLinkedInScrap.addEventListener('blur', () => {
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ linkedin_scrapper: aiLinkedInScrap.value.trim() })
      });
    });
  }
  if (aiCvScrap) {
    aiCvScrap.addEventListener('blur', () => {
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cv_pdf_scrapper: aiCvScrap.value.trim() })
      });
    });
  }
const clientBtn = document.getElementById('client-version-btn'); // ✅ defínelo aquí
if (document.querySelector('.tab.active')?.dataset.tab === 'resume') {
  aiButton.classList.remove('hidden');
  if (clientBtn) {
    clientBtn.classList.remove('hidden');
    clientBtn.style.display = 'inline-block';
  }
}
// ❌ No uses 'tabId' aquí (no existe en este scope)

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
const hireSetupFee = document.getElementById('hire-setup-fee');
if (hireSetupFee) {
  hireSetupFee.addEventListener('blur', () => {
    const val = parseFloat(hireSetupFee.value);
    if (isNaN(val)) return;
    updateHireField('setup_fee', val);
  });
}

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
      const salaryUpdatesBox = document.getElementById('salary-updates-box');
      salaryUpdatesBox.innerHTML = '';

      const header = document.createElement('div');
      header.className = 'salary-entry';
      header.style.fontWeight = 'bold';
      header.innerHTML = `
        <span>Salary</span>
        <span>Fee</span>
        <span>Date</span>
        <span></span>
      `;
      salaryUpdatesBox.appendChild(header);

      data.forEach(update => {
        const div = document.createElement('div');
        div.className = 'salary-entry';
        div.innerHTML = `
          <span>$${update.salary}</span>
          <span>$${update.fee ?? ''}</span>
          <span>${new Date(update.date).toLocaleDateString()}</span>
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
window.loadSalaryUpdates = loadSalaryUpdates; // opcional, por si la llamas como global


hireSalary.addEventListener('blur', async () => {
  const salary = parseFloat(hireSalary.value);
  if (!salary || isNaN(salary)) return;

  await updateHireField('employee_salary', salary);

  const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
  if (model?.includes('staffing')) {
    const fee = parseFloat(hireFee.value);
    if (!isNaN(fee)) {
      const revenue = salary + fee;
      document.getElementById('hire-revenue').value = revenue;
      await updateHireField('employee_revenue', revenue);
    }
  }
  // ➜ No recalcular revenue si es Recruiting
});
hireFee.addEventListener('blur', async () => {
  const fee = parseFloat(hireFee.value);
  if (!fee || isNaN(fee)) return;

  await updateHireField('employee_fee', fee);

  const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
  if (model?.includes('staffing')) {
    const salary = parseFloat(hireSalary.value);
    if (!isNaN(salary)) {
      const revenue = salary + fee;
      document.getElementById('hire-revenue').value = revenue;
      await updateHireField('employee_revenue', revenue);
    }
  }
  // ➜ No recalcular revenue si es Recruiting
});

addSalaryUpdateBtn.addEventListener('click', () => {
  popup.classList.remove('hidden');

  // Oculta fee si modelo es Recruiting
  const modelText = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
  const feeLabel = popup.querySelector('label[for="update-fee"]') || popup.querySelectorAll('label')[1];
  const feeInput = document.getElementById('update-fee');

  if (modelText?.includes('recruiting')) {
    feeLabel.style.display = 'none';
    feeInput.style.display = 'none';
  } else {
    feeLabel.style.display = '';
    feeInput.style.display = '';
  }

});

saveUpdateBtn.addEventListener('click', () => {
  const salary = parseFloat(salaryInput.value);
  const fee = parseFloat(feeInput.value);
  const date = document.getElementById('update-date').value;

  const modelText = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
  const isRecruiting = modelText?.includes('recruiting');

  if (salaryInput.value === '' || !date || (!isRecruiting && feeInput.value === '')) {
    return alert('Please fill all required fields');
  }

  const body = {
    salary,
    date
  };

  if (!isRecruiting) {
    body.fee = fee;
  }

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/salary_updates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
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
// ✅ Handler robusto para el botón de AI
// ✅ Handler robusto para el botón de AI (reemplazo)
const aiSubmitBtn = document.getElementById('ai-submit');
if (aiSubmitBtn) {
  aiSubmitBtn.addEventListener('click', async () => {
    const apiBase = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
    const candidateId = new URLSearchParams(window.location.search).get('id');
    if (!candidateId) return;

    // 1) Intentar leer de los textareas si existen
    const linEl = document.getElementById('ai-linkedin-scrap');
    const cvEl  = document.getElementById('ai-cv-scrap');
    let linkedin_scrapper = (linEl?.value || '').trim();
    let cv_pdf_scrapper   = (cvEl?.value  || '').trim();

    // 2) Fallback: leer del backend si está vacío o no hay inputs
    let hasLinkedinUrl = false;
    let hasAnyCvFile   = false;
    if (!linkedin_scrapper || !cv_pdf_scrapper) {
      try {
        const cand = await fetch(`${apiBase}/candidates/${candidateId}`).then(r => r.json());
        // usar scrappers si existen; si no, usar fuentes equivalentes
        if (!linkedin_scrapper) {
          linkedin_scrapper = (cand.linkedin_scrapper || cand.coresignal_scrapper || '').trim();
        }
        if (!cv_pdf_scrapper) {
          cv_pdf_scrapper = (cand.cv_pdf_scrapper || cand.affinda_scrapper || '').trim();
        }
        hasLinkedinUrl = !!(cand.linkedin || '').trim();
      } catch (e) {
        console.warn('⚠️ Fallback read failed', e);
      }

      // 3) Último recurso: ¿hay algún CV subido?
      try {
        const files = await fetch(`${apiBase}/candidates/${candidateId}/cvs`).then(r => r.json());
        hasAnyCvFile = Array.isArray(files) && files.length > 0;
      } catch {}
    }

    // 4) Validación: permitir si hay al menos UNA fuente (scrapper/linkedin/cv)
    const hasAnySource =
      !!linkedin_scrapper ||
      !!cv_pdf_scrapper   ||
      hasLinkedinUrl      ||
      hasAnyCvFile;

    if (!hasAnySource) {
      alert('Please add LinkedIn or CV info before generating.');
      return;
    }

    // 5) Generar: enviar lo que tengamos (el backend también recibe candidate_id)
    startResumeLoader();
    try {
      const response = await fetch(`${apiBase}/generate_resume_fields`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_id: candidateId,
          linkedin_scrapper: linkedin_scrapper || '',   // puede ir vacío si no hay
          cv_pdf_scrapper:   cv_pdf_scrapper   || ''    // idem
        })
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

      // cerrar popup si existe
      document.getElementById('ai-popup')?.classList.add('hidden');
    } catch (err) {
      console.error('❌ Error generating resume:', err);
      alert("Something went wrong while generating the resume. Please try again.");
    } finally {
      stopResumeLoader();
    }
  });
}


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
const addLanguageBtn = document.getElementById('addLanguageBtn');
addLanguageBtn.addEventListener('click', () => addLanguageEntry());
// ====== Candidate CVs (upload/list/delete/open) ======
(() => {
  const apiBase = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const drop = document.getElementById('cv-drop');
  const input = document.getElementById('cv-input');
  const browseBtn = document.getElementById('cv-browse');
  const refreshBtn = document.getElementById('cv-refresh');
  const list = document.getElementById('cv-list');
  // === Mini indicador abajo-derecha ===
  const cvIndicator = (() => {
    const el = document.createElement('div');
    el.className = 'cv-indicator';
    el.innerHTML = `<span class="spinner"></span><span class="msg">Extracting info from CV…</span>`;
    document.body.appendChild(el);

    const setIcon = (type) => {
      const first = el.firstElementChild;
      if (!first) return;
      if (type === 'spinner') {
        first.className = 'spinner';
      } else if (type === 'check') {
        first.className = 'check';
      }
    };

    return {
      show(msg = 'Extracting info from CV…') {
        setIcon('spinner');
        el.querySelector('.msg').textContent = msg;
        el.classList.add('show');
      },
      success(msg = 'Extracted') {
        setIcon('check');
        el.querySelector('.msg').textContent = msg;
      },
      hide() {
        el.classList.remove('show');
      }
    };
  })();

  if (!drop || !input || !list) return;

  function render(items = []) {
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = `<div class="cv-item"><span class="cv-name" style="opacity:.65">No files yet</span></div>`;
      return;
    }
    items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'cv-item';
      row.innerHTML = `
        <span class="cv-name" title="${it.name}">${it.name}</span>
        <div class="cv-actions">
          <a class="btn" href="${it.url}" target="_blank" rel="noopener">Open</a>
          <button class="btn danger" data-key="${it.key}" type="button">Delete</button>
        </div>
      `;
      row.querySelector('.danger').addEventListener('click', async (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        if (!key) return;
        if (!confirm('Delete this file?')) return;
        await fetch(`${apiBase}/candidates/${candidateId}/cvs`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key })
        });
        await loadCVs();
      });
      list.appendChild(row);
    });
  }

  async function loadCVs() {
    try {
      const r = await fetch(`${apiBase}/candidates/${candidateId}/cvs`);
      const data = await r.json();
      render(Array.isArray(data) ? data : []);
    } catch (e) {
      console.warn('Failed to load CVs', e);
      render([]);
    }
  }
  // Exponer para refrescos cuando cambias de pestaña
  window.loadCVs = loadCVs;

async function uploadFile(file) {
  // ✅ Acepta PDFs/imágenes aunque Safari no ponga MIME
  const allowedMimes = new Set([
    'application/pdf',
    'image/png',
    'image/jpeg',
    'image/webp',
    'application/octet-stream', // Safari a veces
    '' // Safari a veces lo deja vacío
  ]);
  const extOk = /\.(pdf|png|jpe?g|webp)$/i.test((file.name || ''));
  const typeOk = allowedMimes.has(file.type);

  if (!typeOk && !extOk) {
    alert('Only PDF, PNG, JPG/JPEG or WEBP are allowed.');
    return;
  }

  // Detectar si es PDF para el indicador
  const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name || '');

  const fd = new FormData();
  fd.append('file', file);

  try {
    drop.classList.add('dragover');

    // 🔔 Indicador no bloqueante
    if (isPdf) {
      cvIndicator.show('Extracting info from CV…');
    } else {
      cvIndicator.show('Uploading file…');
    }

    const r = await fetch(`${apiBase}/candidates/${candidateId}/cvs`, {
      method: 'POST',
      body: fd
    });

    if (!r.ok) {
      const t = await r.text().catch(() => '');
      throw new Error(t || `Upload failed (${r.status})`);
    }

    const data = await r.json();
    render(data.items || []);

    // ✅ feedback de éxito
    cvIndicator.success(isPdf ? 'CV extracted' : 'Uploaded');
    setTimeout(() => cvIndicator.hide(), 900);
  } catch (e) {
    console.error('Upload failed', e);
    alert('Upload failed');
    cvIndicator.hide();
  } finally {
    drop.classList.remove('dragover');
    // ✅ Importante: permite re-seleccionar el mismo archivo
    input.value = '';
  }
}

  // Drag & Drop
  ;['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation();
    drop.classList.add('dragover');
  }));
  ;['dragleave','dragend','drop'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation();
    drop.classList.remove('dragover');
  }));
  drop.addEventListener('drop', e => {
    const files = e.dataTransfer?.files;
    if (files?.length) uploadFile(files[0]);
  });

  // Click/browse
  browseBtn.addEventListener('click', () => input.click());
  drop.addEventListener('click', (e) => {
    // Evita abrir si se hace click en acciones
    if ((e.target instanceof HTMLElement) && e.target.closest('.cv-actions')) return;
    input.click();
  });
  input.addEventListener('change', () => {
    const f = input.files?.[0];
    if (f) uploadFile(f);
  });

  refreshBtn.addEventListener('click', async () => {
  const ic = refreshBtn.querySelector('.btn-icon');
  refreshBtn.disabled = true;
  ic?.classList.add('spin');
  await loadCVs();
  setTimeout(() => ic?.classList.remove('spin'), 400);
  refreshBtn.disabled = false;
});
// 🔁 Auto-extracción del PDF con OpenAI si affinda_scrapper está vacío
(async function autoExtractFromPdfOnLoad() {
  try {
    const base = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
    const cid = new URLSearchParams(window.location.search).get('id');
    if (!cid) return;

    // 1) Leer candidato para saber si affinda_scrapper ya tiene valor
    const cand = await fetch(`${base}/candidates/${cid}`).then(r => r.json());
    const hasAffinda = (cand.affinda_scrapper || '').trim().length > 0;
    if (hasAffinda) return;

    // 2) Buscar un PDF en la lista de CVs
    const items = await fetch(`${base}/candidates/${cid}/cvs`).then(r => r.json()).catch(() => []);
    const pdf = (Array.isArray(items) ? items : []).find(it => /\.pdf$/i.test(it.name || '')) || null;
    if (!pdf || !pdf.url) return;

    // 3) Indicador + llamada al backend
    cvIndicator.show('Extracting info from CV…');
    const res = await fetch(`${base}/ai/extract_cv_from_pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: cid, pdf_url: pdf.url })
    });
    const out = await res.json();

    // 4) Pintar en el textarea de la AI si existe y cerramos indicador
    if (out.extracted_text) {
      const aiCvScrap = document.getElementById('ai-cv-scrap');
        if (aiCvScrap) {
          aiCvScrap.addEventListener('blur', () => {
            fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ cv_pdf_scrapper: aiCvScrap.value.trim() })
            });
          });
        }
      if (aiCvScrap) aiCvScrap.value = out.extracted_text;
      cvIndicator.success('CV extracted');
      setTimeout(() => cvIndicator.hide(), 900);
    } else {
      cvIndicator.hide();
    }
  } catch (e) {
    console.warn('⚠️ autoExtractFromPdfOnLoad failed', e);
    try { cvIndicator.hide(); } catch {}
  }
})();

  // Carga inicial si ya estás en Overview
if (document.querySelector('.tab.active')?.dataset.tab === 'overview') {
  if (typeof loadCVs === 'function') loadCVs();
  if (typeof loadResignations === 'function') loadResignations();
}

})();
// === Close buttons (X) for Salary Update + AI Assistant popups ===
const aiPopupEl = document.getElementById('ai-popup');
const salaryPopupEl = document.getElementById('salary-update-popup');

// Soporta varios selectores por si ya tienes distinto markup
const aiCloseBtns = [
  document.getElementById('ai-close'),
  ...(aiPopupEl?.querySelectorAll('.close-ai-popup,[data-close="ai-popup"]') ?? [])
];

const salaryCloseBtns = [
  document.getElementById('close-salary-update'),
  ...(salaryPopupEl?.querySelectorAll('.close-salary-popup,[data-close="salary-update-popup"]') ?? [])
];

// Cerrar AI popup
aiCloseBtns.forEach(btn => btn && btn.addEventListener('click', (e) => {
  e.preventDefault(); e.stopPropagation();
  aiPopupEl?.classList.add('hidden');
}));

// Cerrar Salary Update popup + limpiar inputs
salaryCloseBtns.forEach(btn => btn && btn.addEventListener('click', (e) => {
  e.preventDefault(); e.stopPropagation();
  if (!salaryPopupEl) return;
  salaryPopupEl.classList.add('hidden');
  const s = document.getElementById('update-salary');
  const f = document.getElementById('update-fee');
  const d = document.getElementById('update-date');
  if (s) s.value = '';
  if (f) f.value = '';
  if (d) d.value = '';
}));

// Cerrar haciendo click fuera (en el overlay)
[aiPopupEl, salaryPopupEl].forEach(el => {
  el?.addEventListener('click', (e) => {
    // cierra solo si el click fue en el contenedor/overlay, no dentro del contenido
    if (e.target === el) el.classList.add('hidden');
  });
});
// ====== Candidate Resignation Letters (upload/list/delete/open) ======
(() => {
  const apiBase = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const candidateId = new URLSearchParams(window.location.search).get('id');
  const drop = document.getElementById('resig-drop');
  const input = document.getElementById('resig-input');
  const browseBtn = document.getElementById('resig-browse');
  const refreshBtn = document.getElementById('resig-refresh');
  const list = document.getElementById('resig-list');

  // indicador mini (independiente del de CV)
  const resIndicator = (() => {
    const el = document.createElement('div');
    el.className = 'cv-indicator';
    el.innerHTML = `<span class="spinner"></span><span class="msg">Uploading…</span>`;
    document.body.appendChild(el);

    const setIcon = (type) => {
      const first = el.firstElementChild;
      if (!first) return;
      first.className = (type === 'check') ? 'check' : 'spinner';
    };
    return {
      show(msg = 'Uploading…'){ setIcon('spinner'); el.querySelector('.msg').textContent = msg; el.classList.add('show'); },
      success(msg = 'Uploaded'){ setIcon('check'); el.querySelector('.msg').textContent = msg; },
      hide(){ el.classList.remove('show'); }
    };
  })();

  if (!candidateId || !drop || !input || !list) return;

  function render(items = []) {
    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = `<div class="cv-item"><span class="cv-name" style="opacity:.65">No files yet</span></div>`;
      return;
    }
    items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'cv-item';
      row.innerHTML = `
        <span class="cv-name" title="${it.name}">${it.name}</span>
        <div class="cv-actions">
          <a class="btn" href="${it.url}" target="_blank" rel="noopener">Open</a>
          <button class="btn danger" data-key="${it.key}" type="button">Delete</button>
        </div>
      `;
      row.querySelector('.danger').addEventListener('click', async (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        if (!key) return;
        if (!confirm('Delete this file?')) return;
        await fetch(`${apiBase}/candidates/${candidateId}/resignations`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key })
        });
        await loadResignations();
      });
      list.appendChild(row);
    });
  }

  async function loadResignations() {
    try {
      const r = await fetch(`${apiBase}/candidates/${candidateId}/resignations`);
      const data = await r.json();
      render(Array.isArray(data) ? data : []);
    } catch (e) {
      console.warn('Failed to load resignations', e);
      render([]);
    }
  }
  window.loadResignations = loadResignations;

  async function uploadResignation(file) {
    // Solo PDF
    const isPdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name || '');
    if (!isPdf) {
      alert('Only PDF is allowed.');
      return;
    }
    const fd = new FormData();
    fd.append('file', file);
    try {
      drop.classList.add('dragover');
      resIndicator.show('Uploading resignation letter…');
      const r = await fetch(`${apiBase}/candidates/${candidateId}/resignations`, {
        method: 'POST',
        body: fd
      });
      if (!r.ok) {
        const t = await r.text().catch(()=>'');
        throw new Error(t || `Upload failed (${r.status})`);
      }
      await loadResignations();
      resIndicator.success('Uploaded');
      setTimeout(() => resIndicator.hide(), 900);
    } catch (e) {
      console.error('Upload failed', e);
      alert('Upload failed');
      resIndicator.hide();
    } finally {
      drop.classList.remove('dragover');
      input.value = '';
    }
  }

  // Drag & Drop
  ;['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation(); drop.classList.add('dragover');
  }));
  ;['dragleave','dragend','drop'].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); e.stopPropagation(); drop.classList.remove('dragover');
  }));
  drop.addEventListener('drop', e => {
    const files = e.dataTransfer?.files;
    if (files?.length) uploadResignation(files[0]);
  });

  // Click/browse
  browseBtn.addEventListener('click', () => input.click());
  drop.addEventListener('click', (e) => {
    if ((e.target instanceof HTMLElement) && e.target.closest('.cv-actions')) return;
    input.click();
  });
  input.addEventListener('change', () => {
    const f = input.files?.[0];
    if (f) uploadResignation(f);
  });

  // Refresh
  refreshBtn.addEventListener('click', async () => {
    const ic = refreshBtn.querySelector('.btn-icon');
    refreshBtn.disabled = true;
    ic?.classList.add('spin');
    await loadResignations();
    setTimeout(() => ic?.classList.remove('spin'), 400);
    refreshBtn.disabled = false;
  });

  // carga inicial si ya estás en Overview
  if (document.querySelector('.tab.active')?.dataset.tab === 'overview') {
    loadResignations();
  }
})();












});
function mountMonthYearPicker(containerId, { initialValue = '', allowEmpty = false, onChange } = {}) {
  const root = document.getElementById(containerId);
  if (!root) return null;

  const months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  const clearBtn = document.createElement('button');
  const monthSel = document.createElement('select');
  const yearSel  = document.createElement('select');

  monthSel.className = 'month mini-select';
  yearSel.className  = 'year mini-select';

  // placeholders
  monthSel.innerHTML = `<option value="">Month</option>` + months.slice(1)
    .map((m,i)=>`<option value="${String(i+1).padStart(2,'0')}">${m}</option>`).join('');
  yearSel.innerHTML = `<option value="">Year</option>`;
  const nowYear = new Date().getFullYear();
  for (let y = nowYear + 5; y >= 1990; y--) {
    const opt = document.createElement('option');
    opt.value = String(y);
    opt.textContent = String(y);
    yearSel.appendChild(opt);
  }

  clearBtn.type = 'button';
  clearBtn.className = 'btn-clear';
  clearBtn.setAttribute('aria-label', 'Clear date');
  clearBtn.title = 'Clear';
  clearBtn.textContent = 'Clear';
  if (!allowEmpty) clearBtn.style.display = 'none';

  root.replaceChildren(monthSel, yearSel, clearBtn);

  function toISO() {
    const y = yearSel.value, m = monthSel.value;
    if (!y || !m) return allowEmpty ? '' : '';
    return `${y}-${m}-15`; // día 15 forzado
  }
  function emit() {
    if (typeof onChange !== 'function') return;
    const y = yearSel.value, m = monthSel.value;
    if (allowEmpty && !y && !m) { onChange(''); return; }
    if (y && m) onChange(toISO());
  }

  // 🆕 UX: si el usuario elige MES primero y no hay AÑO, colocamos el año actual automáticamente.
  monthSel.addEventListener('change', () => {
    if (!yearSel.value) yearSel.value = String(nowYear);
    emit();
  });
  yearSel.addEventListener('change', emit);

  clearBtn.addEventListener('click', () => { monthSel.value=''; yearSel.value=''; emit(); });

  function setValue(iso) {
    if (!iso) { monthSel.value=''; yearSel.value=''; return; }
    const [datePart] = iso.split('T');
    const [y,m] = datePart.split('-');
    if (y) yearSel.value = y;
    if (m) monthSel.value = m;
  }
  setValue(initialValue);

  return { setValue, getValue: toISO };
}

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
      // 🔁 Refresca usando el loader centralizado
if (typeof loadVideoLink === 'function') loadVideoLink();
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
    if (tabId === 'overview') {
  if (typeof loadCVs === 'function') loadCVs();
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
  const revenueInput = document.getElementById('hire-revenue');
  if (!candidateId) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`)
    .then(res => res.json())
.then(data => {
  const salaryInput = document.getElementById('hire-salary');
  const feeInput = document.getElementById('hire-fee');
const setupEl = document.getElementById('hire-setup-fee');
if (setupEl) setupEl.value = data.setup_fee || '';

  salaryInput.value = data.employee_salary || '';
  feeInput.value = data.employee_fee || '';
  document.getElementById('hire-computer').value = data.computer || '';
  document.getElementById('hire-extraperks').innerHTML = data.extraperks || '';
  console.log(document.getElementById('hire-extraperks').innerHTML)
  const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
  if (model?.includes('recruiting')) {
    document.getElementById('hire-revenue').value = data.employee_revenue_recruiting || '';
  } else {
    document.getElementById('hire-revenue').value = data.employee_revenue || '';
  }
  const isRecruiting = model?.includes('recruiting');
  if (isRecruiting)  {
  document.getElementById('hire-working-schedule').closest('.field').style.display = 'none';
  document.getElementById('hire-pto').closest('.field').style.display = 'none';
  document.getElementById('hire-computer').closest('.field').style.display = 'none';
  document.getElementById('hire-extraperks').closest('.field').style.display = 'none';
}

  document.getElementById('hire-working-schedule').value = data.working_schedule || '';
  document.getElementById('hire-pto').value = data.pto || '';
  document.getElementById('hire-references').innerHTML = data.references_notes || '';
const startInp = document.getElementById('hire-start-date');
const endInp   = document.getElementById('hire-end-date');
// backend puede traer 'YYYY-MM-DD' o con hora → recorta a 10
if (startInp) startInp.value = (data.start_date || '').slice(0, 10);
if (endInp)   endInp.value   = (data.end_date   || '').slice(0, 10);


const modelText = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();

// Solo aplica esta lógica si es Recruiting
if (isRecruiting) {
  if (data.employee_salary && parseFloat(data.employee_salary) > 0) {
    salaryInput.disabled = true;
    salaryInput.addEventListener('mouseenter', () => showTooltip(salaryInput, "To update salary, please use the 'Salary Updates' section below"));
    salaryInput.addEventListener('mouseleave', hideTooltip);
    salaryInput.addEventListener('click', () => showTooltip(salaryInput, "To update salary, please use the 'Salary Updates' section below"));
  }

  if (data.employee_revenue_recruiting && parseFloat(data.employee_revenue_recruiting) > 0) {
    revenueInput.disabled = true;
    revenueInput.addEventListener('mouseenter', () => showTooltip(revenueInput, "To update revenue, please use the 'Salary Updates' section below"));
    revenueInput.addEventListener('mouseleave', hideTooltip);
    revenueInput.addEventListener('click', () => showTooltip(revenueInput, "To update revenue, please use the 'Salary Updates' section below"));
  }
}

  // Deshabilitar salary y fee si ya tienen valores
  if (data.employee_salary && parseFloat(data.employee_salary) > 0) {
    salaryInput.disabled = true;
  }
  if (data.employee_fee && parseFloat(data.employee_fee) > 0) {
    feeInput.disabled = true;
  }
  loadSalaryUpdates();
});

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire_opportunity`)
    .then(res => res.json())
    .then(data => {
      const model = data.opp_model;
    if (model) {
      document.getElementById('opp-model-pill').textContent = `Model: ${model}`;
      adaptHireFieldsByModel(model);
    }
  });
const salaryInput = document.getElementById('hire-salary');
const feeInput = document.getElementById('hire-fee');
const tipMessage = "To update salary or fee, please use the 'Salary Updates' section below.";
const revenueMessage = "You can't edit revenue manually. It's auto-calculated.";

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
  const setupField = document.getElementById('setup-fee-field');

  if (model.toLowerCase() === 'recruiting') {
    feeField.style.display = 'none';
    if (setupField) setupField.style.display = 'none';
    revenueInput.disabled = false;

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`)
      .then(res => res.json())
      .then(data => {
        revenueInput.value = data.employee_revenue_recruiting || '';
      });

    revenueInput.addEventListener('blur', () => {
      updateHireField('employee_revenue_recruiting', revenueInput.value);
    });
  document.getElementById('hire-working-schedule').closest('.field').style.display = 'none';
  document.getElementById('hire-pto').closest('.field').style.display = 'none';
  document.getElementById('hire-computer').closest('.field').style.display = 'none';
  document.getElementById('hire-extraperks').closest('.field').style.display = 'none';
    revenueInput.classList.remove('disabled-hover');
  } else if (model.toLowerCase() === 'staffing') {
    feeField.style.display = 'block';
    if (setupField) setupField.style.display = 'block';
    revenueInput.disabled = true;
    revenueInput.classList.add('disabled-hover');

    ['hire-salary', 'hire-fee'].forEach(id => {
      const el = document.getElementById(id);
      el.addEventListener('blur', async () => {
        const salary = Number(document.getElementById('hire-salary').value);
        const fee = Number(document.getElementById('hire-fee').value);
        if (!salary || !fee) return;

        const field = id === 'hire-salary' ? 'employee_salary' : 'employee_fee';
        await updateHireField(field, el.value);

        const revenue = salary + fee;
        revenueInput.value = revenue;
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
document.querySelectorAll('[contenteditable="true"]').forEach(el => {
  el.addEventListener('paste', function(e) {
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text');
    document.execCommand('insertText', false, text);
  });
});
document.querySelectorAll('[contenteditable="true"]').forEach(el => {
  el.addEventListener('input', function() {
    this.querySelectorAll('*').forEach(child => {
      child.removeAttribute('style');
      child.style.fontFamily = 'Onest';
      child.style.fontSize = '14px';
      child.style.color = '#333';
      child.style.fontWeight = '400';
    });
  });
});
const candidateId = new URLSearchParams(window.location.search).get('id');
function sortEntriesByEndDate(containerId, cardSelector, endDateSelector, currentCheckboxSelector) {
  const container = document.getElementById(containerId);
  const cards = Array.from(container.querySelectorAll(cardSelector));

  cards.sort((a, b) => {
    const endA = a.querySelector(endDateSelector).value;
    const currentA = a.querySelector(currentCheckboxSelector)?.checked;
    const endB = b.querySelector(endDateSelector).value;
    const currentB = b.querySelector(currentCheckboxSelector)?.checked;

    const dateA = currentA || endA === 'Present' || endA === '' ? new Date(2100, 0, 1) : new Date(endA);
    const dateB = currentB || endB === 'Present' || endB === '' ? new Date(2100, 0, 1) : new Date(endB);

    return dateB - dateA; // Sort descending
  });

  // Re-append sorted cards
  cards.forEach(card => container.appendChild(card));
}
// 🌎 Países para Education
const EDU_COUNTRIES = [
  "", "Argentina","Bolivia","Brazil","Chile","Colombia","Costa Rica","Cuba","Dominican Republic",
  "Ecuador","El Salvador","Guatemala","Honduras","Mexico","Nicaragua","Panama","Paraguay","Peru",
  "Uruguay","Venezuela","United States","Canada","Spain","Portugal","United Kingdom","Germany",
  "France","Italy","Netherlands","Poland","India","China","Japan","Australia"
];
function makeCountryOptions(selected = "") {
  return EDU_COUNTRIES.map(c =>
    `<option value="${c}" ${c === selected ? "selected" : ""}>${c || "Select country"}</option>`
  ).join("");
}
// 🔧 Helpers para los pickers dinámicos
function uniqId(prefix='uid') {
  if (window.crypto?.randomUUID) return `${prefix}-${crypto.randomUUID()}`;
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}
function disableMonthYear(containerId, disabled, tooltipText = 'Marked as current.') {
  const root = document.getElementById(containerId);
  if (!root) return;
  root.querySelectorAll('select').forEach(s => s.disabled = disabled);
  if (disabled) {
    root.setAttribute('title', tooltipText);
    root.classList.add('is-disabled');
  } else {
    root.removeAttribute('title');
    root.classList.remove('is-disabled');
  }
}
function normalizeISO15(raw) {
  if (!raw || raw === 'Present') return '';
  if (/^\d{4}-\d{2}$/.test(raw)) return `${raw}-15`;
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw.replace(/-\d{2}$/, '-15');
  return raw;
}
function syncMultiRolesToDescription(card){
  const list  = card.querySelector('.mr-list');
  const desc  = card.querySelector('.work-desc');
  const items = Array.from(list.querySelectorAll('.mr-entry'));

  const pack = document.createElement('div');
  pack.className = 'mr-pack';
  pack.setAttribute('data-type','multi-roles');

  const roles = [];

  items.forEach(it => {
    const title   = it.querySelector('.mr-title')?.value.trim() || '';
    const start   = (it.querySelector('.mr-start')?.value || '').trim();
    const endIso  = (it.querySelector('.mr-end')?.value   || '').trim();
    const current = !!it.querySelector('.mr-current')?.checked;
    const end     = current ? 'Present' : endIso;
    const descHtml= it.querySelector('.mr-desc')?.innerHTML.trim() || '';

    const isEmpty = !(title || descHtml || start || endIso || current);
    if (isEmpty) return;

    // HTML para re-hidratar
    const node = document.createElement('div');
    node.className = 'mr-item';
    node.setAttribute('data-start', start);
    node.setAttribute('data-end', end);
    node.innerHTML = `
      <div class="mr-title-txt">${escapeHtmlText(title)}</div>
      <div class="mr-desc-html">${descHtml}</div>
    `;
    pack.appendChild(node);

    // JSON paralelo (útil para backend/reportes)
    roles.push({
      title, start_date: start, end_date: current ? '' : endIso, current, description_html: descHtml
    });
  });

  if (pack.children.length > 0) {
    // mini-JSON embebido para quien lo necesite (URL-encoded para seguridad)
    try { pack.setAttribute('data-roles', encodeURIComponent(JSON.stringify(roles))); } catch {}
    desc.innerHTML = pack.outerHTML;
  } else {
    desc.innerHTML = '';
  }

  // Actualiza fechas agregadas del card padre
  updateAggregateDatesFromMultiRoles(card);

  // 💾 Persistir (ya funciona porque ahora saveResume está en window)
  if (typeof window.saveResume === 'function') window.saveResume();
}


function updateAggregateDatesFromMultiRoles(card){
  const items = Array.from(card.querySelectorAll('.mr-entry'));
  if (!items.length) return;

  // earliest start y latest end (Present > cualquier fecha)
  let minStart = null;
  let maxEnd = null;
  let hasPresent = false;

  items.forEach(it=>{
    const s = (it.querySelector('.mr-start')?.value || '').trim();
    const e = (it.querySelector('.mr-end')?.value || '').trim();
    const cur = it.querySelector('.mr-current')?.checked;

    if (s) minStart = !minStart ? s : (new Date(s) < new Date(minStart) ? s : minStart);
    if (cur) { hasPresent = true; }
    else if (e) { maxEnd = !maxEnd ? e : (new Date(e) > new Date(maxEnd) ? e : maxEnd); }
  });

  // Escribe en los hidden del entry padre (los que saveResume ya usa)
  const hiddenStart = card.querySelector('.work-start');
  const hiddenEnd   = card.querySelector('.work-end');
  const currentCb   = card.querySelector('.work-current');

  if (hiddenStart) hiddenStart.value = minStart || '';
  if (hiddenEnd)   hiddenEnd.value   = hasPresent ? 'Present' : (maxEnd || '');
  if (currentCb)   currentCb.checked = !!hasPresent;
}

// Crea una mini-tarjeta (rol)
function addMiniRole(card, data = { title:'', start_date:'', end_date:'', current:false, description:'' }){
  const id = uniqId('mr');
  const startCid = `mr-start-${id}`;
  const endCid   = `mr-end-${id}`;

  const entry = document.createElement('div');
  entry.className = 'mr-entry';
  entry.innerHTML = `
    <button type="button" class="remove-entry" title="Remove">🗑️</button>
    <div class="mr-row">
      <div class="mr-col">
        <input type="text" class="mr-title" placeholder="Role title" value="${data.title || ''}">
      </div>
      <div class="mr-col">
        <label style="display:block;">Start</label>
        <div id="${startCid}" class="month-year"></div>
        <input type="hidden" class="mr-start" value="">
      </div>
      <div class="mr-col">
        <label style="display:block;">End</label>
        <div id="${endCid}" class="month-year"></div>
        <input type="hidden" class="mr-end" value="">
      </div>
      <div class="mr-col" style="display:flex;align-items:flex-end;">
        <label style="display:flex;align-items:center;gap:6px;">
          <input type="checkbox" class="mr-current" ${data.current ? 'checked' : ''}/> Current
        </label>
      </div>
    </div>
    <div class="mr-toolbar">
      <button type="button" data-command="bold"><b>B</b></button>
      <button type="button" data-command="italic"><i>I</i></button>
      <button type="button" data-command="insertUnorderedList">• List</button>
    </div>
    <div class="mr-desc" contenteditable="true" placeholder="Description...">${data.description || ''}</div>
  `;

  // ➜ Primero insertar en el DOM
  card.querySelector('.mr-list').appendChild(entry);

  // Toolbar
  entry.querySelectorAll('.mr-toolbar button').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const cmd = btn.getAttribute('data-command');
      const target = entry.querySelector('.mr-desc');
      target.focus(); document.execCommand(cmd, false, null);
      btn.classList.toggle('active', document.queryCommandState(cmd));
      syncMultiRolesToDescription(card);
    });
  });

  // Eliminar mini-rol
  entry.querySelector('.remove-entry').addEventListener('click', ()=>{
    entry.remove();
    syncMultiRolesToDescription(card);
  });

  // Hidden que reflejan el valor
  const hiddenStart = entry.querySelector('.mr-start');
  const hiddenEnd   = entry.querySelector('.mr-end');

  // 🗓️ Montar pickers (ahora sí existen en el DOM)
  const startPicker = mountMonthYearPicker(startCid, {
    allowEmpty: true,
    initialValue: data.start_date || '',
    onChange: (iso)=>{ hiddenStart.value = iso; syncMultiRolesToDescription(card); }
  });

  const endPicker = mountMonthYearPicker(endCid, {
    allowEmpty: true,
    initialValue: data.current ? '' : (data.end_date || ''),
    onChange: (iso)=>{ hiddenEnd.value = iso; syncMultiRolesToDescription(card); }
  });

  // Iniciales
  hiddenStart.value = data.start_date || '';
  hiddenEnd.value   = data.current ? 'Present' : (data.end_date || '');

  // Current toggle del mini-rol
  const cur = entry.querySelector('.mr-current');
  cur.addEventListener('change', e=>{
    if (e.target.checked){
      hiddenEnd.dataset.lastIso = hiddenEnd.value && hiddenEnd.value !== 'Present' ? hiddenEnd.value : '';
      hiddenEnd.value = 'Present';
      disableMonthYear(endCid, true, 'Role marked as current.');
    } else {
      disableMonthYear(endCid, false);
      const last = hiddenEnd.dataset.lastIso || '';
      if (last){ endPicker.setValue(last); hiddenEnd.value = last; }
      else { endPicker.setValue(''); hiddenEnd.value=''; }
    }
    syncMultiRolesToDescription(card);
  });
  if (data.current) disableMonthYear(endCid, true, 'Role marked as current.');

  // Sincronizar en blur / input
  entry.querySelector('.mr-title').addEventListener('blur', ()=> syncMultiRolesToDescription(card));
  entry.querySelector('.mr-desc').addEventListener('blur', ()=> syncMultiRolesToDescription(card));
  // 📌 Guardado en vivo mientras se escribe/cambia
const syncNow = () => syncMultiRolesToDescription(card);
const syncSoft = debounce(syncNow, 600);

// Título y descripción del mini-rol
entry.querySelector('.mr-title').addEventListener('input', syncSoft);
entry.querySelector('.mr-desc').addEventListener('input',  syncSoft);

// Por si el usuario usa Enter o sale del campo
entry.querySelector('.mr-title').addEventListener('blur', syncNow);
entry.querySelector('.mr-desc').addEventListener('blur',  syncNow);

// Los pickers ya llaman a syncNow en su onChange; mantenlo así.

}

function enableMultiRolesOnCard(card, enabled){
  const wrap    = card.querySelector('.mr-wrap');
  const toggle  = card.querySelector('.mr-toggle');
  const titleEl = card.querySelector('.work-title');
const companyEl = card.querySelector('.work-company'); 
  const startHost = document.getElementById(card.dataset.workStartCid || '');
  const datesRow  = startHost ? startHost.parentElement?.parentElement : null;
  const currentRow= card.querySelector('.work-current')?.closest('div');
  const descEl    = card.querySelector('.work-desc');

  // toolbar del card principal
  const cardToolbar = card.querySelector(':scope > .rich-toolbar');

  toggle.checked = !!enabled;
  wrap.classList.toggle('active', !!enabled);

  if (enabled){
    companyEl?.classList.remove('mr-hidden'); // mostrar Company en MR

    // 📦 Guarda snapshot para restaurar luego (solo 1 vez)
    if (!card.dataset.mrBackup){
      const backup = {
        title:   titleEl?.value || '',
        start:   card.querySelector('.work-start')?.value || '',
        end:     card.querySelector('.work-end')?.value   || '',
        current: !!card.querySelector('.work-current')?.checked,
        desc:    descEl?.innerHTML || ''
      };
      card.dataset.mrBackup = JSON.stringify(backup);
    }

    // Oculta controles "single"
    titleEl?.classList.add('mr-hidden');
    datesRow?.classList.add('mr-hidden');
    currentRow?.classList.add('mr-hidden');
    descEl?.classList.add('mr-hidden');
    cardToolbar?.classList.add('mr-hidden');

    card.dataset.mr = '1';
  } else {
    companyEl?.classList.add('mr-hidden');   
    // 🔙 Restaurar si hay backup
    const backup = card.dataset.mrBackup ? JSON.parse(card.dataset.mrBackup) : null;

    // Limpia la UI de mini-roles
    wrap.querySelector('.mr-list')?.replaceChildren();

    // Si description tenía un .mr-pack, lo quitamos y volvemos al desc "single"
    if (descEl && descEl.querySelector('.mr-pack')) {
      descEl.innerHTML = backup?.desc || '';
    }

    if (backup){
      // Campos base
      if (titleEl) titleEl.value = backup.title;
      const hs = card.querySelector('.work-start');
      const he = card.querySelector('.work-end');
      const wc = card.querySelector('.work-current');

      if (hs) hs.value = backup.start || '';
      if (he) he.value = backup.current ? 'Present' : (backup.end || '');
      if (wc) wc.checked = !!backup.current;

      // Reflejar en los selects del picker
      if (card.dataset.workStartCid) setMonthYearUIFromISO(card.dataset.workStartCid, backup.start || '');
      if (card.dataset.workEndCid)   setMonthYearUIFromISO(card.dataset.workEndCid, backup.current ? '' : (backup.end || ''));

      // Habilitar/deshabilitar picker End según current
      if (backup.current && card.dataset.workEndCid) {
        disableMonthYear(card.dataset.workEndCid, true, 'Work experience marked as current.');
      } else if (card.dataset.workEndCid) {
        disableMonthYear(card.dataset.workEndCid, false);
      }
    }

    // Mostrar controles "single" de nuevo
    titleEl?.classList.remove('mr-hidden');
    datesRow?.classList.remove('mr-hidden');
    currentRow?.classList.remove('mr-hidden');
    descEl?.classList.remove('mr-hidden');
    cardToolbar?.classList.remove('mr-hidden');

    card.dataset.mr = '';
    delete card.dataset.mrBackup;

    // 💾 Guarda inmediatamente tras salir de MR
    if (typeof window.saveResume === 'function') window.saveResume();
  }
}

// Intenta hidratar desde description si ya trae un paquete multi-roles
function tryHydrateMultiFromDescription(card, descHtml){
  if (!descHtml) return false;
  const tmp = document.createElement('div');
  tmp.innerHTML = descHtml;
  const pack = tmp.querySelector('.mr-pack[data-type="multi-roles"]');
  if (!pack) return false;

  enableMultiRolesOnCard(card, true);
  const items = Array.from(pack.querySelectorAll('.mr-item'));
  if (!items.length){ addMiniRole(card); return true; }

  items.forEach(it=>{
    const title = (it.querySelector('.mr-title-txt')?.textContent || '').trim();
    const start = it.getAttribute('data-start') || '';
    const end   = it.getAttribute('data-end') || '';
    const current = end === 'Present';
    const desc = it.querySelector('.mr-desc-html')?.innerHTML || '';
    addMiniRole(card, { title, start_date:start, end_date: current ? '' : end, current, description:desc });
  });

  // Asegura que agreguemos fechas agregadas
  updateAggregateDatesFromMultiRoles(card);
  return true;
}

// Utilidad chiquita
function escapeHtmlText(s=''){
  // Mantén tags fuera del título por seguridad
  const d = document.createElement('div'); d.textContent = s; return d.textContent;
}
function debounce(fn, wait = 500) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
}
function setMonthYearUIFromISO(containerId, iso){
  const root = document.getElementById(containerId);
  if (!root) return;
  const monthSel = root.querySelector('select.month');
  const yearSel  = root.querySelector('select.year');
  if (!monthSel || !yearSel) return;

  if (!iso) {
    monthSel.value = '';
    yearSel.value  = '';
    return;
  }
  const [datePart] = iso.split('T');
  const [y, m] = datePart.split('-');
  yearSel.value  = y || '';
  monthSel.value = m || '';
}
