
document.addEventListener("DOMContentLoaded", () => {

  // --- URL / Candidate id ---
  const urlParams   = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get('id'); // ⚠️ NO hagas return todavía

  // --- AI Button / Client Version / Popup wiring (independiente de candidateId) ---
  const aiPopup   = document.getElementById('ai-popup');
  const aiClose   = document.getElementById('ai-close');
  // --- Tabs + visibilidad de pills (UNA sola implementación) ---
  const aiButton  = document.getElementById('ai-action-button');
  const clientBtn = document.getElementById('client-version-btn');

  function setActiveTab(tabId) {
    // pestañas
    document.querySelectorAll('.tab')
      .forEach(t => t.classList.toggle('active', t.dataset.tab === tabId));
    document.querySelectorAll('.tab-content')
      .forEach(c => c.classList.toggle('active', c.id === tabId));

    // cargas perezosas
    if (tabId === 'opportunities') window.loadOpportunitiesForCandidate?.();
    if (tabId === 'hire')          window.loadHireData?.();
    if (tabId === 'overview')      window.loadCVs?.();

    // pills
    const onResume = tabId === 'resume';
    aiButton?.classList.toggle('hidden', !onResume);
    clientBtn?.classList.toggle('hidden', !onResume);
  }

document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => setActiveTab(t.dataset.tab));
});

// estado inicial (respeta la marcada en el HTML)
setActiveTab(document.querySelector('.tab.active')?.dataset.tab || 'overview');


  // --- Abrir/cerrar popup AI ---
  aiButton?.addEventListener('click', () => aiPopup?.classList.remove('hidden'));
  aiClose?.addEventListener('click', () => aiPopup?.classList.add('hidden'));
  // --- LET'S GO (AI Assistant) ---
// --- Sustituye COMPLETO el bloque (function wireAiLetsGo(){...}) por:
(function wireAiGenerate(){
  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const letsGoBtn =
    document.getElementById('ai-lets-go') ||
    document.getElementById('ai-submit') ||
    document.querySelector('#ai-popup [data-ai="lets-go"]') ||
    document.querySelector('#ai-popup .ai-lets-go') ||
    document.querySelector('#ai-popup button[type="submit"]');

  const aiPopup = document.getElementById('ai-popup');

  // 💬 Frases bonitas + loader
  const phrases = [
    "Las chicas lindas saben esperar 💅✨",
    "Gracias por tu paciencia, sos la mejor Vinttituta 💖👑",
    "Keep calm and deja que Vinttihub te lo solucione 😌🛠️",
    "Tranquila reina, tu CV está en buenas manos 📄👑",
    "Si esto fuera un casting de modelos, ya estarías contratada 😍",
    "Las Vinttitutas no se apuran, se hacen desear 💁‍♀️💫",
    "Generando algo genial para tu clientito ✨📤💌"
  ];
  let phraseIdx = 0;
  const loaderBox   = document.getElementById('resume-loader');         // <div id="resume-loader" class="hidden">
  const loaderLabel = document.getElementById('resume-loader-phrase');  // <div id="resume-loader-phrase"></div>
  let phraseTimer;

  function startResumeLoader(){
    if (!loaderBox || !loaderLabel) return;
    loaderBox.classList.remove('hidden');
    phraseIdx = 0;
    const tick = () => {
      loaderLabel.style.opacity = 0;
      setTimeout(() => {
        loaderLabel.textContent = phrases[phraseIdx];
        loaderLabel.style.opacity = 1;
        phraseIdx = (phraseIdx + 1) % phrases.length;
      }, 200);
    };
    tick();
    phraseTimer = setInterval(tick, 3000);
  }
  function stopResumeLoader(){
    if (!loaderBox) return;
    loaderBox.classList.add('hidden');
    if (phraseTimer) clearInterval(phraseTimer);
  }

  if (!letsGoBtn) {
    console.warn('AI Assistant: no se encontró el botón de generación');
    return;
  }

  // Enter en el popup = click
  aiPopup?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); letsGoBtn.click(); }
  });

  // Parcheo de textareas → guardar en /candidates al salir
  const linEl = document.getElementById('ai-linkedin-scrap');
  const cvEl  = document.getElementById('ai-cv-scrap');
  const saveScrap = (field, val) => fetch(`${API_BASE}/candidates/${candidateId}`, {
    method:'PATCH', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ [field]: (val||'').trim() })
  });
  linEl?.addEventListener('blur', ()=> saveScrap('linkedin_scrapper', linEl.value));
  cvEl?.addEventListener('blur',  ()=> saveScrap('cv_pdf_scrapper',   cvEl.value));

  // Asegurar helper
  const ensureFn = window.Resume?.ensure || (typeof ensureResumeExists==='function' ? ensureResumeExists : async()=>true);

  letsGoBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    if (!candidateId) return alert('Missing candidate id');

    const prev = letsGoBtn.textContent;
    letsGoBtn.disabled = true;
    letsGoBtn.textContent = 'Working…';
    startResumeLoader();

    try {
      // 1) crea resume si no existe
      await ensureFn();

      // 2) recolecta fuentes
      let linkedin_scrapper = (linEl?.value || '').trim();
      let cv_pdf_scrapper   = (cvEl?.value  || '').trim();
      let hasLinkedinUrl = false, hasAnyCvFile = false;

      if (!linkedin_scrapper || !cv_pdf_scrapper) {
        try {
          const cand = await fetch(`${API_BASE}/candidates/${candidateId}`).then(r=>r.json());
          if (!linkedin_scrapper) linkedin_scrapper = (cand.linkedin_scrapper || cand.coresignal_scrapper || '').trim();
          if (!cv_pdf_scrapper)   cv_pdf_scrapper   = (cand.cv_pdf_scrapper   || cand.affinda_scrapper   || '').trim();
          hasLinkedinUrl = !!(cand.linkedin || '').trim();
        } catch {}
        try {
          const files = await fetch(`${API_BASE}/candidates/${candidateId}/cvs`).then(r=>r.json());
          hasAnyCvFile = Array.isArray(files) && files.length>0;
        } catch {}
      }

      const hasAnySource = !!(linkedin_scrapper || cv_pdf_scrapper || hasLinkedinUrl || hasAnyCvFile);
      if (!hasAnySource) {
        alert('Please add LinkedIn or CV info before generating.');
        return;
      }

      // 3) generar
      const resp = await fetch(`${API_BASE}/generate_resume_fields`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ candidate_id: candidateId, linkedin_scrapper, cv_pdf_scrapper })
      });
      const out = await resp.json();

      // 4) pintar + guardar con la API del resume
      if (window.Resume?.applyGenerated) {
        window.Resume.applyGenerated(out);
      }

      // 5) UI: ir a Resume, cerrar popup
      if (typeof setActiveTab === 'function') setActiveTab('resume');
      aiPopup?.classList.add('hidden');

    } catch (err) {
      console.error('❌ AI generate failed', err);
      alert('Something went wrong while generating the resume.');
    } finally {
      stopResumeLoader();
      letsGoBtn.disabled = false;
      letsGoBtn.textContent = prev;
    }
  });
})();
// --- STAR FLOWS: About / Education / Work / Tools --------------------------
(function wireStarFlows(){
  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid = new URLSearchParams(location.search).get('id');

  // helpers tooltip
  function showStarTooltip(el, msg='Please use the AI Assistant button first.') {
    const tip = document.createElement('div');
    tip.className = 'star-tooltip';
    tip.textContent = msg;
    Object.assign(tip.style, {
      position:'absolute', zIndex:1000, background:'#111', color:'#fff',
      padding:'6px 10px', borderRadius:'8px', fontSize:'12px',
      whiteSpace:'nowrap', boxShadow:'0 2px 8px rgba(0,0,0,.2)'
    });
    const r = el.getBoundingClientRect();
    tip.style.left = `${r.left + window.scrollX}px`;
    tip.style.top  = `${r.bottom + 6 + window.scrollY}px`;
    document.body.appendChild(tip);
    el.__starTip = tip;
  }
  function hideStarTooltip(){ document.querySelectorAll('.star-tooltip').forEach(x=>x.remove()); }
// 0) Lista de estrellas a deshabilitar SIEMPRE (hard-disable)
const HARD_DISABLED = new Set(['popup-work','popup-education','popup-tools','popup-languages']);

function disableStar(btn, msg='Este botón está deshabilitado temporalmente.'){
  btn.classList.add('disabled-star','hard-disabled');
  btn.setAttribute('aria-disabled','true');
  const block = (e)=>{ e.preventDefault(); e.stopPropagation(); };
  btn.__block = block;
  btn.addEventListener('click', block);
  btn.addEventListener('mouseenter', ()=>showStarTooltip(btn, msg));
  btn.addEventListener('mouseleave', hideStarTooltip);
}
function enableStar(btn){
  // Nunca re-habilitar las hard
  if (btn.classList.contains('hard-disabled')) return;
  btn.classList.remove('disabled-star');
  btn.removeAttribute('aria-disabled');
  if (btn.__block){ btn.removeEventListener('click', btn.__block); btn.__block = null; }
}

// Marcar como deshabilitadas las que estén en HARD_DISABLED
document.querySelectorAll('.star-button[data-target]').forEach(btn=>{
  const id = btn.getAttribute('data-target');
  if (HARD_DISABLED.has(id)) disableStar(btn, 'Este botón está deshabilitado por ahora.');
});

  // abrir/cerrar popups
  document.querySelectorAll('.star-button[data-target]').forEach(btn=>{
    btn.addEventListener('click', (e)=>{
      if (btn.classList.contains('disabled-star')) { e.preventDefault(); e.stopPropagation(); return; }
      const id = btn.getAttribute('data-target');
      const pop = document.getElementById(id);
      if (pop) pop.classList.remove('hidden');
    });
  });
  document.querySelectorAll('.star-popup .close-star-popup').forEach(x=>{
    x.addEventListener('click', ()=> x.closest('.star-popup')?.classList.add('hidden'));
  });
  document.querySelectorAll('.star-popup').forEach(pop=>{
    pop.addEventListener('click', (e)=>{ if (e.target === pop) pop.classList.add('hidden'); });
  });

  // deshabilitar si faltan fuentes (linkedin/cv/affinda/coresignal/url)
  (async function gateStarsBySources(){
    try{
      const cand = await fetch(`${API_BASE}/candidates/${cid}`).then(r=>r.json());
      const hasAnySource =
        (cand.linkedin_scrapper && cand.linkedin_scrapper.trim()) ||
        (cand.cv_pdf_scrapper   && cand.cv_pdf_scrapper.trim())   ||
        (cand.affinda_scrapper  && cand.affinda_scrapper.trim())  ||
        (cand.coresignal_scrapper && cand.coresignal_scrapper.trim()) ||
        (cand.linkedin && cand.linkedin.trim());

      const allStars = document.querySelectorAll('.star-button');
      if (!hasAnySource){
        allStars.forEach(btn=>{
          btn.classList.add('disabled-star');
          const block = (e)=>{ e.preventDefault(); e.stopPropagation(); };
          btn.addEventListener('click', block);
          btn.addEventListener('mouseenter', ()=>showStarTooltip(btn, 'Please use the AI Assistant button first.'));
          btn.addEventListener('mouseleave', hideStarTooltip);
        });
      } else {
        allStars.forEach(btn=> btn.classList.remove('disabled-star'));
      }

      // Requisito extra para About: que exista fila en resume
      const aboutStar = document.getElementById('about-star-button');
      if (aboutStar){
        try{
          const r = await fetch(`${API_BASE}/resumes/${cid}`, { method:'GET' });
          if (!r.ok) throw 0;
          aboutStar.classList.remove('disabled-star');
        } catch {
          aboutStar.classList.add('disabled-star');
          const block = (e)=>{ e.preventDefault(); e.stopPropagation(); };
          aboutStar.addEventListener('click', block);
          aboutStar.addEventListener('mouseenter', ()=>showStarTooltip(aboutStar, 'Please complete resume first.'));
          aboutStar.addEventListener('mouseleave', hideStarTooltip);
        }
      }
    } catch(e){ console.warn('gateStarsBySources:', e); }
  })();

  // ---- handlers de generación por popup -----------------------------------
  function getTextArea(popupId){
    return document.querySelector(`#${popupId} textarea`);
  }
  function loaderOn(id){ const el=document.getElementById(id); if (el) el.classList.remove('hidden'); }
  function loaderOff(id){ const el=document.getElementById(id); if (el) el.classList.add('hidden'); }

  // About
  const aboutBtn = document.querySelector('#popup-about .generate-btn');
  if (aboutBtn){
    aboutBtn.addEventListener('click', async ()=>{
      const ta = getTextArea('popup-about');
      const user_prompt = (ta?.value || '').trim();
      const L = 'about-loader';
      loaderOn(L);
      try{
        const res = await fetch(`${API_BASE}/ai/improve_about`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ candidate_id: cid, user_prompt })
        });
        const data = await res.json();
        if (data.about){
          // pinta + guarda usando tu API expuesta por resume.js
          window.Resume?.applyGenerated({ about: data.about });
        }
        document.getElementById('popup-about')?.classList.add('hidden');
      } catch(e){
        console.error('improve_about failed', e);
        alert('Error improving About section. Try again.');
      } finally { loaderOff(L); }
    });
  }

  // Education
  const eduBtn = document.querySelector('#popup-education .generate-btn');
  if (eduBtn){
    eduBtn.addEventListener('click', async ()=>{
      const ta = getTextArea('popup-education');
      const user_prompt = (ta?.value || '').trim();
      if (!user_prompt) return alert('Please add a comment before generating.');
      const L = 'about-loader'; // reusamos
      loaderOn(L);
      try{
        const res = await fetch(`${API_BASE}/ai/improve_education`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ candidate_id: cid, user_prompt })
        });
        const data = await res.json();
        if (data.education){
          window.Resume?.applyGenerated({ education: data.education });
        }
        document.getElementById('popup-education')?.classList.add('hidden');
      } catch(e){
        console.error('improve_education failed', e);
        alert('Error improving Education section. Try again.');
      } finally { loaderOff(L); }
    });
  }

  // Work Experience
  const workBtn = document.querySelector('#popup-work .generate-btn');
  if (workBtn){
    workBtn.addEventListener('click', async ()=>{
      const ta = getTextArea('popup-work');
      const user_prompt = (ta?.value || '').trim();
      if (!user_prompt) return alert('Please add a comment before generating.');
      const L = 'work-loader';
      loaderOn(L);
      try{
        const res = await fetch(`${API_BASE}/ai/improve_work_experience`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ candidate_id: cid, user_prompt })
        });
        const data = await res.json();
        if (data.work_experience){
          window.Resume?.applyGenerated({ work_experience: data.work_experience });
        }
        document.getElementById('popup-work')?.classList.add('hidden');
      } catch(e){
        console.error('improve_work_experience failed', e);
        alert('Error improving Work Experience section. Try again.');
      } finally { loaderOff(L); }
    });
  }

  // Tools
  const toolsBtn = document.querySelector('#popup-tools .generate-btn');
  if (toolsBtn){
    toolsBtn.addEventListener('click', async ()=>{
      const ta = getTextArea('popup-tools');
      const user_prompt = (ta?.value || '').trim();
      if (!user_prompt) return alert('Please add a comment before generating.');
      const L = 'tools-loader';
      loaderOn(L);
      try{
        const res = await fetch(`${API_BASE}/ai/improve_tools`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ candidate_id: cid, user_prompt })
        });
        const data = await res.json();
        if (data.tools){
          // Acepta string JSON o array; applyGenerated ya normaliza/coercea
          window.Resume?.applyGenerated({ tools: data.tools });
        }
        document.getElementById('popup-tools')?.classList.add('hidden');
      } catch(e){
        console.error('improve_tools failed', e);
        alert('Error improving Tools section. Try again.');
      } finally { loaderOff(L); }
    });
  }
})();


  aiPopup?.addEventListener('click', (e) => {
    if (e.target === aiPopup) aiPopup.classList.add('hidden'); // click fuera cierra
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') aiPopup?.classList.add('hidden');
  });

  // ========================
  // A PARTIR DE AQUÍ, LO QUE SÍ REQUIERE candidateId
  // ========================
  if (!candidateId) {
    console.warn('No candidateId in URL; skipping data fetches.');
    return; // ya quedó todo el UI wiring arriba
  }

  // --- Helpers LinkedIn ---
function normalizeUrl(u) {
  let v = (u || '').trim();
  if (!v) return '';
  v = v.replace(/^\s*[-–—]+/, ''); // quita guiones/espacios iniciales
  v = v.replace(/\s+/g, '');      // quita espacios internos
  // si no tiene esquema, anteponer https:// (soporta "linkedin.com/..." también)
  if (!/^https?:\/\//i.test(v)) v = 'https://' + v.replace(/^\/+/, '');
  return v;
}

function updateLinkedInUI(raw) {
  const openBtn = document.getElementById('linkedin-open-btn');
  const fld     = document.getElementById('field-linkedin');
  const url     = normalizeUrl(raw);

  // Muestra el texto en el field
  if (fld) fld.innerText = (raw || '').trim() || '—';

  // Configura botón "Open"
  if (!openBtn) return;
  if (url && /^https?:\/\//i.test(url)) {
    openBtn.href = url;
    openBtn.style.display   = 'inline-flex';
    openBtn.style.visibility= 'visible';
    openBtn.style.opacity   = 1;
    openBtn.onclick = (e) => { e.preventDefault(); window.open(url, '_blank'); };
  } else {
    openBtn.style.display = 'none';
  }
}

  // Tema
  document.documentElement.setAttribute('data-theme', 'light');
  if (!candidateId) return;

  // --- Helpers de UI ---
  function showTooltip(input, message) {
    if (document.querySelector('.input-tooltip')) return;
    const tooltip = document.createElement('div');
    tooltip.className = 'input-tooltip';
    tooltip.textContent = message;

    const rect = input.getBoundingClientRect();
    Object.assign(tooltip.style, {
      position: 'absolute',
      left: `${rect.left + window.scrollX}px`,
      top: `${rect.bottom + 5 + window.scrollY}px`,
      backgroundColor: '#333',
      color: '#fff',
      padding: '6px 10px',
      borderRadius: '6px',
      fontSize: '13px',
      zIndex: 1000,
      boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
      pointerEvents: 'none'
    });
    document.body.appendChild(tooltip);
  }
  function hideTooltip() {
    const tooltip = document.querySelector('.input-tooltip');
    if (tooltip) tooltip.remove();
  }
  function getFlagEmoji(countryName) {
    const flags = {
      "Argentina":"🇦🇷","Bolivia":"🇧🇴","Brazil":"🇧🇷","Chile":"🇨🇱","Colombia":"🇨🇴","Costa Rica":"🇨🇷",
      "Cuba":"🇨🇺","Dominican Republic":"🇩🇴","Ecuador":"🇪🇨","El Salvador":"🇸🇻","Guatemala":"🇬🇹",
      "Honduras":"🇭🇳","Mexico":"🇲🇽","Nicaragua":"🇳🇮","Panama":"🇵🇦","Paraguay":"🇵🇾","Peru":"🇵🇪",
      "Uruguay":"🇺🇾","Venezuela":"🇻🇪"
    };
    return flags[countryName] || '';
  }

  // --- Patch helpers (Hire) ---
  window.updateHireField = function(field, value) {
    if (!candidateId) return;
    return fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value })
    }).then(() => window.loadHireData && window.loadHireData());
  };

  // --- Restore Hire dates con <input type="date"> nativo ---
  (function restoreHireDates() {
    const hostStart = document.getElementById('hire-start-picker');
    const hostEnd   = document.getElementById('hire-end-picker');
    if (hostStart && !hostStart.querySelector('input[type="date"]')) {
      hostStart.innerHTML = '<input type="date" id="hire-start-date" />';
    }
    if (hostEnd && !hostEnd.querySelector('input[type="date"]')) {
      hostEnd.innerHTML = '<input type="date" id="hire-end-date" />';
    }
    const startInp = document.getElementById('hire-start-date');
    const endInp   = document.getElementById('hire-end-date');
    if (startInp) startInp.addEventListener('change', () => updateHireField('start_date', startInp.value || ''));
    if (endInp)   endInp.addEventListener('change', () => updateHireField('end_date',   endInp.value   || ''));
  })();

  // --- Overview: cargar datos del candidato ---
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`)
    .then(r => r.json())
    .then(data => {
      updateLinkedInUI(data.linkedin || '');
      // Mapeo de campos (overview)
      const overviewFields = {
        'field-name': 'name',
        'field-country': 'country',
        'field-phone': 'phone',
        'field-email': 'email',
        'field-english-level': 'english_level',
        'field-salary-range': 'salary_range',
        'field-linkedin':      'linkedin',  
      };
      Object.entries(overviewFields).forEach(([elementId, fieldName]) => {
        const el = document.getElementById(elementId);
        if (!el) return;

        if (fieldName === 'country') {
          if (data.country) el.value = data.country;
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
            if (value) el.innerText = value;
            el.contentEditable = "true";
            el.addEventListener('blur', () => {
              const updated = el.innerText.trim();
              fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [fieldName]: updated })
              });

              // Si este field es LinkedIn, refresca botón + normaliza visualmente
              if (fieldName === 'linkedin') {
                updateLinkedInUI(updated);
              }
            });
          }
        }
      });

      // País → bandera
      const countrySelect = document.getElementById('field-country');
      const countryFlagSpan = document.getElementById('country-flag');
      if (countryFlagSpan) countryFlagSpan.textContent = getFlagEmoji(data.country || '');
      if (countrySelect) {
        countrySelect.addEventListener('change', () => {
          if (countryFlagSpan) countryFlagSpan.textContent = getFlagEmoji(countrySelect.value);
        });
      }

      // LinkedIn (limpio + abrir)
      const openBtn = document.getElementById('linkedin-open-btn');
      let linkedinUrl = (data.linkedin || '').trim().replace(/^[-–—\s]+/, '');
      if (openBtn) {
        if (linkedinUrl.startsWith('www')) linkedinUrl = 'https://' + linkedinUrl;
        if (/^https?:\/\//i.test(linkedinUrl)) {
          openBtn.href = linkedinUrl;
          openBtn.style.display = 'inline-flex';
          openBtn.style.visibility = 'visible';
          openBtn.style.opacity = 1;
          openBtn.onclick = (e) => { e.preventDefault(); window.open(linkedinUrl, '_blank'); };
        } else {
          openBtn.style.display = 'none';
        }
      }

      // Red flags / comments (blur)
      (['redFlags','comments']).forEach(id => {
        const ta = document.getElementById(id);
        if (!ta) return;
        ta.value = id === 'redFlags' ? (data.red_flags || '') : (data.comments || '');
        ta.addEventListener('blur', () => {
          const field = id === 'redFlags' ? 'red_flags' : 'comments';
          fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: ta.value.trim() })
          });
        });
      });

      // Otros metadatos
      const by = document.getElementById("field-created-by");
      const at = document.getElementById("field-created-at");
      if (by) by.textContent = data.created_by || '—';
      if (at) at.textContent = data.created_at ? new Date(data.created_at).toLocaleString() : '—';
      // --- Normalizador ligero (igual a lo que ya usabas) ---
function normalizeLinkedinUrl(u) {
  let v = (u || '').trim();
  v = v.replace(/^\s*[-–—]+/, ''); // quita guiones al inicio
  v = v.replace(/\s+/g, '');       // quita espacios internos
  if (!v) return '';
  if (!/^https?:\/\//i.test(v)) v = 'https://' + v.replace(/^\/+/, '');
  return v;
}

// --- Guard central para decidir si correr Coresignal ---
function shouldSyncCoresignal(candidate, candidateId) {
  // 1) Misma condición que tu JS anterior:
  const hasCore = !!(candidate.coresignal_scrapper && candidate.coresignal_scrapper.trim());
  if (hasCore) return false;

  const linkedinUrl = normalizeLinkedinUrl(candidate.linkedin);
  const looksLinkedin = /^https?:\/\/(?:www\.)?[\w.-]*linkedin\.com\/.+/i.test(linkedinUrl);
  if (!looksLinkedin) return false;

  // 2) Deduplicado opcional (evita múltiples POST en segundos/minutos):
  const key = `coresignal:sync:${candidateId}`;
  const last = Number(localStorage.getItem(key) || 0);
  const FIVE_MIN = 5 * 60 * 1000;
  if (Date.now() - last < FIVE_MIN) return false;          // ya lo intentaste hace <5min
  if (window.__coreSyncInFlight) return false;             // ya hay una llamada en curso

  return { linkedinUrl, storeKey: key };
}

// --- Uso: idéntico a tu flujo de Overview ---
const gate = shouldSyncCoresignal(data, candidateId);
if (gate) {
  window.__coreSyncInFlight = true;
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/coresignal/candidates/${candidateId}/sync`, {
    method: 'POST'
  })
  .then(async (r) => {
    let payload;
    try { payload = await r.json(); } catch { payload = await r.text(); }
    console.log('🔄 Coresignal sync:', { ok: r.ok, status: r.status, payload });
  })
  .catch(e => console.warn('⚠️ Coresignal sync failed', e))
  .finally(() => {
    window.__coreSyncInFlight = false;
    try { localStorage.setItem(gate.storeKey, String(Date.now())); } catch {}
  });
}

    })
    .catch(err => console.error('❌ Error fetching candidate:', err));

  // Ocultar pestaña Hire si no está contratado
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/is_hired`)
    .then(res => res.json())
    .then(d => {
      if (!d.is_hired) {
        const hireTab = document.querySelector('.tab[data-tab="hire"]');
        const hireContent = document.getElementById('hire');
        if (hireTab) hireTab.style.display = 'none';
        if (hireContent) hireContent.style.display = 'none';
      }
    });

  // Go Back
  const goBackButton = document.getElementById('goBackButton');
  if (goBackButton) {
    goBackButton.addEventListener('click', () => {
      if (document.referrer) window.history.back();
      else window.location.href = '/';
    });
  }

  // --- Salary Updates (Hire) ---
  const salaryUpdatesBox = document.getElementById('salary-updates-box');
  const addSalaryUpdateBtn = document.getElementById('add-salary-update');
  const popup = document.getElementById('salary-update-popup');
  const saveUpdateBtn = document.getElementById('save-salary-update');
  const salaryInput = document.getElementById('update-salary');
  const feeInput = document.getElementById('update-fee');

  async function loadSalaryUpdates() {
    if (!salaryUpdatesBox) return;
    const r = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/salary_updates`);
    const data = await r.json();
    salaryUpdatesBox.innerHTML = '';
    const header = document.createElement('div');
    header.className = 'salary-entry';
    header.style.fontWeight = 'bold';
    header.innerHTML = `<span>Salary</span><span>Fee</span><span>Date</span><span></span>`;
    salaryUpdatesBox.appendChild(header);
    (data || []).forEach(update => {
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
        fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/salary_updates/${id}`, { method: 'DELETE' })
          .then(loadSalaryUpdates);
      });
    });
  }
  window.loadSalaryUpdates = loadSalaryUpdates;

  if (addSalaryUpdateBtn && popup) {
    addSalaryUpdateBtn.addEventListener('click', () => {
      popup.classList.remove('hidden');
      // ocultar fee si modelo es Recruiting
      const modelText = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
      const feeLabel = popup.querySelector('label[for="update-fee"]') || popup.querySelectorAll('label')[1];
      const feeIn = document.getElementById('update-fee');
      const isRecruiting = modelText?.includes('recruiting');
      if (feeLabel && feeIn) {
        feeLabel.style.display = isRecruiting ? 'none' : '';
        feeIn.style.display    = isRecruiting ? 'none' : '';
      }
    });
  }

  if (saveUpdateBtn) {
    saveUpdateBtn.addEventListener('click', () => {
      const sal = parseFloat(salaryInput?.value || '');
      const fee = parseFloat(feeInput?.value || '');
      const date = document.getElementById('update-date')?.value;

      const modelText = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
      const isRecruiting = modelText?.includes('recruiting');

      if (!date || isNaN(sal) || (!isRecruiting && (feeInput?.value === '' || isNaN(fee)))) {
        return alert('Please fill all required fields');
      }
      const body = { salary: sal, date };
      if (!isRecruiting) body.fee = fee;

      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/salary_updates`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      }).then(() => {
        popup?.classList.add('hidden');
        if (salaryInput) salaryInput.value = '';
        if (feeInput) feeInput.value = '';
        const d = document.getElementById('update-date'); if (d) d.value = '';
        loadSalaryUpdates();
      });
    });
  }

  // Si llegaste con #hire desde Close Win → mensaje
  if (window.location.hash === '#hire') {
    const hireTab = document.querySelector('.tab[data-tab="hire"]');
    hireTab?.click();
    if (localStorage.getItem('fromCloseWin') === 'true') {
      localStorage.removeItem('fromCloseWin');
      const msg = document.createElement('div');
      msg.className = 'apple-hire-notice';
      msg.textContent = 'Now please complete the Hire fields';
      document.body.appendChild(msg);
      setTimeout(() => msg.remove(), 6000);
    }
  }

  // --- Wire Hire inputs básicos ---
  const hireWorkingSchedule = document.getElementById('hire-working-schedule');
  const hirePTO = document.getElementById('hire-pto');
  const hireComputer = document.getElementById('hire-computer');
  const hirePerks = document.getElementById('hire-extraperks');
  const hireSalary = document.getElementById('hire-salary');
  const hireFee = document.getElementById('hire-fee');
  const hireRevenue = document.getElementById('hire-revenue');
  const hireSetupFee = document.getElementById('hire-setup-fee');
  const referencesDiv = document.getElementById('hire-references');

  if (hireWorkingSchedule) hireWorkingSchedule.addEventListener('blur', () => updateHireField('working_schedule', hireWorkingSchedule.value));
  if (hirePTO) hirePTO.addEventListener('blur', () => updateHireField('pto', hirePTO.value));
  if (hireComputer) hireComputer.addEventListener('change', () => updateHireField('computer', hireComputer.value));
  if (hirePerks) hirePerks.addEventListener('blur', () => updateHireField('extraperks', hirePerks.innerHTML));
  if (hireSetupFee) hireSetupFee.addEventListener('blur', () => { const v = parseFloat(hireSetupFee.value); if (!isNaN(v)) updateHireField('setup_fee', v); });

  if (referencesDiv) {
    referencesDiv.addEventListener('blur', () => updateHireField('references_notes', referencesDiv.innerHTML));
  }

  // Autocálculo revenue para Staffing
  if (hireSalary) hireSalary.addEventListener('blur', async () => {
    const salary = parseFloat(hireSalary.value);
    if (!salary || isNaN(salary)) return;
    await updateHireField('employee_salary', salary);
    const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
    if (model?.includes('staffing')) {
      const fee = parseFloat(hireFee?.value || '');
      if (!isNaN(fee)) {
        const revenue = salary + fee;
        if (hireRevenue) hireRevenue.value = revenue;
        await updateHireField('employee_revenue', revenue);
      }
    }
  });
  if (hireFee) hireFee.addEventListener('blur', async () => {
    const fee = parseFloat(hireFee.value);
    if (!fee || isNaN(fee)) return;
    await updateHireField('employee_fee', fee);
    const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
    if (model?.includes('staffing')) {
      const salary = parseFloat(hireSalary?.value || '');
      if (!isNaN(salary)) {
        const revenue = salary + fee;
        if (hireRevenue) hireRevenue.value = revenue;
        await updateHireField('employee_revenue', revenue);
      }
    }
  });

  // Cargar Hire + Opportunity model
  function adaptHireFieldsByModel(model) {
    const feeField = document.getElementById('hire-fee')?.closest('.field');
    const revenueInput = document.getElementById('hire-revenue');
    const setupField = document.getElementById('setup-fee-field');
    const isRecruiting = model.toLowerCase() === 'recruiting';

    if (feeField) feeField.style.display = isRecruiting ? 'none' : 'block';
    if (setupField) setupField.style.display = isRecruiting ? 'none' : 'block';
    if (revenueInput) {
      revenueInput.disabled = !isRecruiting;
      revenueInput.classList.toggle('disabled-hover', !isRecruiting);
    }

    // Ocultar campos irrelevantes en Recruiting
    const hideInRecruiting = ['hire-working-schedule','hire-pto','hire-computer','hire-extraperks'];
    hideInRecruiting.forEach(id => {
      const f = document.getElementById(id)?.closest('.field');
      if (f) f.style.display = isRecruiting ? 'none' : '';
    });

    if (isRecruiting && revenueInput) {
      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`)
        .then(res => res.json())
        .then(data => { revenueInput.value = data.employee_revenue_recruiting || ''; });

      revenueInput.addEventListener('blur', () => updateHireField('employee_revenue_recruiting', revenueInput.value));
    }

    // Tooltips cuando están bloqueados
    [document.getElementById('hire-salary'), document.getElementById('hire-fee')].forEach(input => {
      if (!input) return;
      const tipMessage = "To update salary or fee, please use the 'Salary Updates' section below.";
      input.addEventListener('mouseenter', () => { if (input.disabled) showTooltip(input, tipMessage); });
      input.addEventListener('mouseleave', hideTooltip);
      input.addEventListener('click', () => { if (input.disabled) showTooltip(input, tipMessage); });
    });
  }

  function loadHireData() {
    const revenueInput = document.getElementById('hire-revenue');
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`)
      .then(res => res.json())
      .then(data => {
        const salaryInput = document.getElementById('hire-salary');
        const feeInput = document.getElementById('hire-fee');
        const setupEl = document.getElementById('hire-setup-fee');

        if (setupEl) setupEl.value = data.setup_fee || '';
        if (salaryInput) salaryInput.value = data.employee_salary || '';
        if (feeInput)    feeInput.value    = data.employee_fee    || '';
        const comp = document.getElementById('hire-computer');      if (comp) comp.value = data.computer || '';
        const perks = document.getElementById('hire-extraperks');   if (perks) perks.innerHTML = data.extraperks || '';
        const ws = document.getElementById('hire-working-schedule');if (ws) ws.value = data.working_schedule || '';
        const pto = document.getElementById('hire-pto');            if (pto) pto.value = data.pto || '';
        const ref = document.getElementById('hire-references');     if (ref) ref.innerHTML = data.references_notes || '';

        // fechas (YYYY-MM-DD)
        const startInp = document.getElementById('hire-start-date');
        const endInp   = document.getElementById('hire-end-date');
        if (startInp) startInp.value = (data.start_date || '').slice(0,10);
        if (endInp)   endInp.value   = (data.end_date   || '').slice(0,10);

        const model = document.getElementById('opp-model-pill')?.textContent?.toLowerCase();
        if (model?.includes('recruiting')) {
          if (revenueInput) revenueInput.value = data.employee_revenue_recruiting || '';
        } else {
          if (revenueInput) revenueInput.value = data.employee_revenue || '';
        }

        // Deshabilitar si ya hay valores
        if (salaryInput && data.employee_salary && parseFloat(data.employee_salary) > 0) {
          salaryInput.disabled = true;
        }
        if (feeInput && data.employee_fee && parseFloat(data.employee_fee) > 0) {
          feeInput.disabled = true;
        }

        loadSalaryUpdates();
      });

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire_opportunity`)
      .then(res => res.json())
      .then(data => {
        const model = data.opp_model;
        if (model) {
          const pill = document.getElementById('opp-model-pill');
          if (pill) pill.textContent = `Model: ${model}`;
          adaptHireFieldsByModel(model);
        }
      });
  }
  window.loadHireData = loadHireData;

  // Cargar si estás en Hire
  if (document.querySelector('.tab.active')?.dataset.tab === 'hire') {
    loadHireData();
    loadSalaryUpdates();
  }

  // --- Opportunities del candidato ---
  window.loadOpportunitiesForCandidate = function () {
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/opportunities`)
      .then(res => res.json())
      .then(data => {
        const tbody = document.querySelector("#opportunitiesTable tbody");
        if (!tbody) return;
        tbody.innerHTML = "";
        (data || []).forEach(opp => {
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
  if (document.querySelector('.tab.active')?.dataset.tab === 'opportunities') {
    loadOpportunitiesForCandidate();
  }

  // --- Tabs (sin lógica de resume/AI) ---
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const tabId = tab.dataset.tab;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(tabId)?.classList.add('active');

    });
  });

  // --- Sanitizar pegado en contenteditable (sin estilos pegados) ---
  document.querySelectorAll('[contenteditable="true"]').forEach(el => {
    el.addEventListener('paste', function(e) {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData('text');
      document.execCommand('insertText', false, text);
    });
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
  // ====== Candidate CVs (listar / subir / abrir) — sin AI ni extracción ======
(() => {
  const apiBase = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid     = new URLSearchParams(window.location.search).get('id');
  const drop        = document.getElementById('cv-drop');
  const input       = document.getElementById('cv-input');
  const browseBtn   = document.getElementById('cv-browse');
  const refreshBtn  = document.getElementById('cv-refresh');
  const list        = document.getElementById('cv-list');
  if (!cid || !list) return; // si no existe el widget, salimos silenciosamente

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
        await fetch(`${apiBase}/candidates/${cid}/cvs`, {
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
      const r = await fetch(`${apiBase}/candidates/${cid}/cvs`);
      const data = await r.json();
      render(Array.isArray(data) ? data : []);
    } catch (e) {
      console.warn('Failed to load CVs', e);
      render([]);
    }
  }
  window.loadCVs = loadCVs; // por si lo llamas desde cambios de pestaña

  async function uploadFile(file) {
    const allowedMimes = new Set([
      'application/pdf','image/png','image/jpeg','image/webp','application/octet-stream',''
    ]);
    const extOk = /\.(pdf|png|jpe?g|webp)$/i.test(file?.name || '');
    const typeOk = allowedMimes.has(file?.type || '');
    if (!extOk && !typeOk) { alert('Only PDF, PNG, JPG/JPEG or WEBP are allowed.'); return; }

    const fd = new FormData();
    fd.append('file', file);

    try {
      drop?.classList.add('dragover');
      const r = await fetch(`${apiBase}/candidates/${cid}/cvs`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text().catch(()=>'Upload failed'));
      const data = await r.json();
      render(data.items || []);
    } catch (e) {
      console.error('Upload failed', e); alert('Upload failed');
    } finally {
      drop?.classList.remove('dragover');
      if (input) input.value = '';
    }
  }

  // Drag & Drop
  if (drop) {
    ['dragenter','dragover'].forEach(ev => drop.addEventListener(ev, e => {
      e.preventDefault(); e.stopPropagation(); drop.classList.add('dragover');
    }));
    ['dragleave','dragend','drop'].forEach(ev => drop.addEventListener(ev, e => {
      e.preventDefault(); e.stopPropagation(); drop.classList.remove('dragover');
    }));
    drop.addEventListener('drop', e => {
      const files = e.dataTransfer?.files;
      if (files?.length) uploadFile(files[0]);
    });
    drop.addEventListener('click', (e) => {
      if ((e.target instanceof HTMLElement) && e.target.closest('.cv-actions')) return;
      input?.click();
    });
  }

  // Browse
  browseBtn?.addEventListener('click', () => input?.click());
  input?.addEventListener('change', () => { const f = input.files?.[0]; if (f) uploadFile(f); });

  // Refresh
  refreshBtn?.addEventListener('click', loadCVs);

  // Carga inicial (también la haremos al entrar a Overview)
  loadCVs();
})();

// configura el link del client version (solo lectura)
if (clientBtn && candidateId) {
  clientBtn.href = `resume-readonly.html?id=${candidateId}`;
}

// muéstralos solo cuando la pestaña activa sea "resume"
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const tabId = tab.dataset.tab;
    const show = tabId === 'resume';
    if (aiButton)  aiButton.classList.toggle('hidden', !show);
    if (clientBtn) clientBtn.classList.toggle('hidden', !show);
  });
});

// si ya estás en "resume" al cargar
if (document.querySelector('.tab.active')?.dataset.tab === 'resume') {
  if (aiButton)  aiButton.classList.remove('hidden');
  if (clientBtn) clientBtn.classList.remove('hidden');
}

});
