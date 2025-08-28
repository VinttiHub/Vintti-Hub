async function ensureResumeExists() {
    const candidateId = new URLSearchParams(location.search).get('id');
    const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  // 1) ¿ya existe?
  const head = await fetch(`${API_BASE}/resumes/${candidateId}`, { method: 'GET' });
  if (head.ok) return true;

  // 2) crear (idempotente)
  const r = await fetch(`${API_BASE}/resumes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId })
  });
  return r.ok;
}
(() => {
  'use strict';

  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const qs = (sel, root=document) => root.querySelector(sel);
  const qsa = (sel, root=document) => Array.from(root.querySelectorAll(sel));
  const byId = (id) => document.getElementById(id);
  const nowYear = new Date().getFullYear();

  // ---------- Guard-rails ----------
  const candidateId = new URLSearchParams(location.search).get('id');
  const resumeRoot = byId('resume');
  if (!candidateId || !resumeRoot) return; // no-op fuera de la pestaña Resume

  // ---------- State ----------
  let snapshot = null;            // {about, education[], work_experience[], tools[], languages[], video_link}
  let touched  = { about:false, education:false, work_experience:false, tools:false, languages:false, video_link:false };
  let saving   = false;
  let savePending = false;
  let hydrated = false;

  // ---------- Utils ----------
  const debounce = (fn, wait=400) => { let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),wait); }; };

  function deepEqual(a,b){ try { return JSON.stringify(a)===JSON.stringify(b); } catch { return a===b; } }

  function normalizeText(s){
    return (s ?? '').replace(/\u00A0/g,' ').replace(/\s+/g,' ').trim();
  }

  function stripHtmlToText(html){
    const d=document.createElement('div'); d.innerHTML=html||''; return (d.textContent||'').trim();
  }

function sanitizeHTML(html){
  if (!html) return '';
  html = normalizeWeirdBullets(html);   // ← añade esto
  // limpia caracteres de control (menos \n y \t)
  html = String(html)
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, ' ')
    .replace(/\u00A0/g, '&nbsp;');

  // ✅ ahora permitimos <p>
  const allowed = new Set(['B','I','STRONG','EM','UL','OL','LI','BR','A','P']);
  const tmp = document.createElement('div');
  tmp.innerHTML = html;

  // quitamos elementos no permitidos pero preservando contenido y saltos
  const walker = document.createTreeWalker(tmp, NodeFilter.SHOW_ELEMENT, null);
  const toRemove = [];
  let node;
  while (node = walker.nextNode()){
    if (!allowed.has(node.tagName)) {
      if (node.tagName === 'DIV' || node.tagName === 'SPAN') {
        // unwrap e inserta un <br> como separador suave
        const br = document.createElement('br');
        node.parentNode.insertBefore(br, node.nextSibling);
        while (node.firstChild) node.parentNode.insertBefore(node.firstChild, node);
        toRemove.push(node);
      } else {
        while (node.firstChild) node.parentNode.insertBefore(node.firstChild, node);
        toRemove.push(node);
      }
      continue;
    }
    // atributos: solo href seguro en <a>
    for (const attr of Array.from(node.attributes)) {
      if (node.tagName === 'A' && attr.name === 'href' && /^(https?:|mailto:)/i.test(node.getAttribute('href')||'')) continue;
      node.removeAttribute(attr.name);
    }
  }
  toRemove.forEach(n=>n.remove());

  // asegura que LI estén dentro de UL/OL
  tmp.querySelectorAll('li').forEach(li=>{
    const p = li.parentElement;
    if (!p || !/^(UL|OL)$/.test(p.tagName)) {
      const ul = document.createElement('ul');
      li.replaceWith(ul);
      ul.appendChild(li);
    }
  });

  // limpia estilos inline fantasmas
  tmp.querySelectorAll('*').forEach(n=>n.removeAttribute('style'));

  return tmp.innerHTML
    .replace(/<p>\s*<\/p>/g,'')           // elimina p vacíos
    .replace(/(?:\s*<br>\s*){2,}/g,'<br>'); // colapsa múltiples <br>
}


  function isRichEmpty(html){
    const txt = stripHtmlToText(html);
    return txt === '';
  }

  function normalizeISO15(raw){
    if (!raw || raw==='Present') return '';
    if (/^\d{4}-\d{2}$/.test(raw)) return `${raw}-15`;
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return raw.replace(/-\d{2}$/, '-15');
    return raw;
  }

  function safeParseArray(raw, fallback=[]){
    try{
      if (raw==null || raw==='') return fallback;
      if (Array.isArray(raw)) return raw;
      if (typeof raw==='object') return raw;
      let s=String(raw).trim().replace(/[“”]/g,'"').replace(/[‘’]/g,"'");
      // decode basic entities
      if (/[&][a-z]+;/.test(s)){ const ta=document.createElement('textarea'); ta.innerHTML=s; s=ta.value; }
      try { return JSON.parse(s); } catch { /* try python repr */ }
      if (/^[\[\{]/.test(s) && /'/.test(s) && !/"/.test(s)) return JSON.parse(s.replace(/'/g,'"'));
      return fallback;
    }catch{ return fallback; }
  }
function mapToolLevel(lvl) {
  const n = (lvl || '').toString().toLowerCase();
  if (/adv|expert|senior|4|5/.test(n)) return 'Advanced';
  if (/basic|begin|junior|1|low/.test(n)) return 'Basic';
  return 'Intermediate';
}

function coerceTools(raw) {
  let arr = safeParseArray(raw, []);
  if (!Array.isArray(arr) && typeof raw === 'string') {
    arr = raw.split(/[,\n]/).map(s => s.trim()).filter(Boolean);
  }
  return arr.map(x => {
    if (typeof x === 'string') return { tool: x, level: 'Intermediate' };
    if (x && typeof x === 'object') {
      const name = (x.tool || x.name || x.skill || x.title || '').toString().trim();
      if (!name) return null;
      const lvl = mapToolLevel(x.level || x.proficiency || x.seniority || '');
      return { tool: name, level: lvl };
    }
    return null;
  }).filter(Boolean);
}

function mapLangLevel(lvl) {
  const n = (lvl || '').toString().toLowerCase();
  if (/native|mother|nativo|^c2$/.test(n)) return 'Native';
  if (/c1|b2|fluent|avanzad/.test(n))     return 'Fluent';
  if (/b1|a2|regular|intermed/.test(n))   return 'Regular';
  return 'Basic';
}

function coerceLanguages(raw) {
  let arr = safeParseArray(raw, []);
  if (!Array.isArray(arr) && typeof raw === 'string') {
    arr = raw.split(/[,\n]/).map(s => s.trim()).filter(Boolean);
  }
  return arr.map(x => {
    if (typeof x === 'string') {
      // soporta "English (C1)"
      const m = x.match(/\(([^)]+)\)\s*$/);
      const name = x.replace(/\([^)]+\)\s*$/, '').trim();
      const lvl  = mapLangLevel(m ? m[1] : '');
      return name ? { language: name, level: lvl } : null;
    }
    if (x && typeof x === 'object') {
      const name = (x.language || x.name || x.lang || '').toString().trim();
      if (!name) return null;
      const lvl = mapLangLevel(x.level || x.fluency || x.proficiency || x.cefr || '');
      return { language: name, level: lvl };
    }
    return null;
  }).filter(Boolean);
}

  const EDU_COUNTRIES = ["","Argentina","Bolivia","Brazil","Chile","Colombia","Costa Rica","Cuba","Dominican Republic","Ecuador","El Salvador","Guatemala","Honduras","Mexico","Nicaragua","Panama","Paraguay","Peru","Uruguay","Venezuela","United States","Canada","Spain","Portugal","United Kingdom","Germany","France","Italy","Netherlands","Poland","India","China","Japan","Australia"];
  const countryOptions = (sel="") => EDU_COUNTRIES.map(c=>`<option value="${c}" ${c===sel?'selected':''}>${c||'Select country'}</option>`).join('');

  // ---------- Month-Year Picker (self-contained) ----------
  function mountMonthYearPicker(root, { initial='', allowEmpty=true, onChange }={}){
    const months = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const monthSel=document.createElement('select'); monthSel.className='month mini-select';
    const yearSel =document.createElement('select'); yearSel.className='year mini-select';
    const clearBtn=document.createElement('button'); clearBtn.type='button'; clearBtn.className='btn-clear'; clearBtn.textContent='Clear';
    clearBtn.style.display = allowEmpty ? '' : 'none';

    monthSel.innerHTML = `<option value="">Month</option>` + months.slice(1).map((m,i)=>`<option value="${String(i+1).padStart(2,'0')}">${m}</option>`).join('');
    yearSel.innerHTML = `<option value="">Year</option>` + Array.from({length: (nowYear+5)-1990+1},(_,k)=>nowYear+5-k)
      .map(y=>`<option value="${y}">${y}</option>`).join('');

    root.replaceChildren(monthSel, yearSel, clearBtn);

    function val(){ const y=yearSel.value, m=monthSel.value; if (!y||!m) return allowEmpty ? '' : ''; return `${y}-${m}-15`; }
    function emit(){ if (typeof onChange==='function'){ const y=yearSel.value, m=monthSel.value; if (allowEmpty && !y && !m) onChange(''); else if (y&&m) onChange(val()); } }

    monthSel.addEventListener('change', ()=>{ if (!yearSel.value) yearSel.value=String(nowYear); else emit(); });
    yearSel.addEventListener('change', emit);
    clearBtn.addEventListener('click', ()=>{ monthSel.value=''; yearSel.value=''; emit(); });

    // set initial
    if (initial){ const [d]=initial.split('T'); const [y,m]=d.split('-'); yearSel.value=y||''; monthSel.value=m||''; }

    return { set(iso){ if(!iso){ monthSel.value=''; yearSel.value=''; return; } const [d]=iso.split('T'); const [y,m]=d.split('-'); yearSel.value=y||''; monthSel.value=m||''; }, get:val };
  }

  // ---------- DOM refs ----------
  const aboutEl = byId('aboutField');
  const eduList = byId('educationList');
  const addEduBtn = byId('addEducationBtn');
  const workList = byId('workExperienceList');
  const addWorkBtn = byId('addWorkExperienceBtn');
  const toolsList = byId('toolsList');
  const addToolBtn = byId('addToolBtn');
  const langsList = byId('languagesList');
  const addLangBtn = byId('addLanguageBtn');
  const videoEl = byId('videoLinkInput');

  // ---------- Builders ----------
function addEducationEntry(entry={ institution:'', title:'', country:'', start_date:'', end_date:'', current:false, description:'' }){
  const card = document.createElement('div');
  card.className='cv-card-entry';
  card.innerHTML = `
    <div style="display:flex;gap:20px;flex-wrap:wrap">
      <div style="flex:2.2;min-width:320px;">
        <input type="text" class="edu-inst"   placeholder="Institution" value="${entry.institution||''}">
        <input type="text" class="edu-title"  placeholder="Title/Degree" value="${entry.title||''}" style="margin-top:6px;">
        <select class="edu-country" style="margin-top:6px;width:100%;">${countryOptions(entry.country||'')}</select>
      </div>
      <div style="flex:2;min-width:360px;">
        <div style="display:flex;gap:10px;">
          <label style="flex:1;">Start<br><div class="picker-start"></div><input type="hidden" class="edu-start"></label>
          <label style="flex:1;">End<br><div class="picker-end"></div><input type="hidden" class="edu-end"></label>
        </div>
        <div style="display:flex;justify-content:flex-end;padding-right:62px;">
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;"><input type="checkbox" class="edu-current" ${entry.current?'checked':''}> Current</label>
        </div>
      </div>
    </div>
    <div class="rich-toolbar"><button data-cmd="bold"><b>B</b></button><button data-cmd="italic"><i>I</i></button><button data-cmd="insertUnorderedList">• List</button></div>
    <div class="edu-desc rich-input" contenteditable="true" placeholder="Description" style="min-height:160px;">${sanitizeHTML(entry.description||'')}</div>
    <button class="remove-entry" title="Remove">🗑️</button>
  `;

  // Editor de descripción
  const desc = card.querySelector('.edu-desc');
  wireDescEditors(desc, 'education');
  card.querySelectorAll('.rich-toolbar button').forEach(b=>b.addEventListener('click', ()=>{
    desc.focus();
    document.execCommand(b.dataset.cmd,false,null);
    touched.education = true; scheduleSave();
  }));

  // Botón borrar
  card.querySelector('.remove-entry').addEventListener('click', ()=>{
    card.remove(); touched.education = true; scheduleSave();
  });

  // Pickers
  const hStart = card.querySelector('.edu-start');
  const hEnd   = card.querySelector('.edu-end');
  const curCb  = card.querySelector('.edu-current');

  const pStart = mountMonthYearPicker(card.querySelector('.picker-start'), { initial: entry.start_date||'', onChange:(iso)=>{ hStart.value=iso; touched.education=true; scheduleSave(); }});
  const pEnd   = mountMonthYearPicker(card.querySelector('.picker-end'),   { initial: entry.current?'':(entry.end_date||''), onChange:(iso)=>{ hEnd.value=iso; touched.education=true; scheduleSave(); }});

  hStart.value = entry.start_date||'';
  hEnd.value   = entry.current ? 'Present' : (entry.end_date||'');

  const toggleCurrent = (checked)=>{
    if (checked){
      hEnd.dataset.lastIso = (hEnd.value && hEnd.value!=='Present') ? hEnd.value : '';
      hEnd.value='Present';
      card.querySelectorAll('.picker-end select').forEach(s=>s.disabled=true);
    } else {
      card.querySelectorAll('.picker-end select').forEach(s=>s.disabled=false);
      const last = hEnd.dataset.lastIso||'';
      if (last){ pEnd.set(last); hEnd.value=last; } else { pEnd.set(''); hEnd.value=''; }
    }
  };
  toggleCurrent(!!entry.current);
  curCb.addEventListener('change', e=>{ toggleCurrent(e.target.checked); touched.education=true; scheduleSave(); });

  // Inputs
  card.querySelectorAll('input,select').forEach(el=>{
    el.addEventListener('input',  ()=>{ touched.education=true; });
    el.addEventListener('change', ()=>{ touched.education=true; scheduleSave(); });
  });

  eduList.appendChild(card);
}


function addWorkExperienceEntry(entry={ title:'', company:'', start_date:'', end_date:'', current:false, description:'' }){
  const card = document.createElement('div');
  card.className='cv-card-entry';
  card.innerHTML = `
    <div style="display:flex;gap:20px;flex-wrap:wrap">
      <div style="flex:2.2;min-width:320px;">
        <input type="text" class="work-title"   placeholder="Title" value="${entry.title||''}">
        <input type="text" class="work-company" placeholder="Company" value="${entry.company||''}" style="margin-top:6px;">
      </div>
      <div style="flex:2;min-width:360px;">
        <div style="display:flex;gap:10px;">
          <label style="flex:1;">Start<br><div class="picker-start"></div><input type="hidden" class="work-start"></label>
          <label style="flex:1;">End<br><div class="picker-end"></div><input type="hidden" class="work-end"></label>
        </div>
        <div style="display:flex;justify-content:flex-end;padding-right:62px;">
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;"><input type="checkbox" class="work-current" ${entry.current?'checked':''}> Current</label>
        </div>
      </div>
    </div>
    <div class="rich-toolbar"><button data-cmd="bold"><b>B</b></button><button data-cmd="italic"><i>I</i></button><button data-cmd="insertUnorderedList">• List</button></div>
    <div class="work-desc rich-input" contenteditable="true" placeholder="Description" style="min-height:200px;">${sanitizeHTML(entry.description||'')}</div>
    <button class="remove-entry" title="Remove">🗑️</button>
  `;

  const desc = card.querySelector('.work-desc');
  wireDescEditors(desc, 'work_experience');
  card.querySelectorAll('.rich-toolbar button').forEach(b=>b.addEventListener('click', ()=>{
    desc.focus();
    document.execCommand(b.dataset.cmd,false,null);
    touched.work_experience = true; scheduleSave();
  }));

  card.querySelector('.remove-entry').addEventListener('click', ()=>{
    card.remove(); touched.work_experience = true; scheduleSave();
  });

  const hStart = card.querySelector('.work-start');
  const hEnd   = card.querySelector('.work-end');
  const curCb  = card.querySelector('.work-current');

  const pStart = mountMonthYearPicker(card.querySelector('.picker-start'), { initial: entry.start_date||'', onChange:(iso)=>{ hStart.value=iso; touched.work_experience=true; scheduleSave(); }});
  const pEnd   = mountMonthYearPicker(card.querySelector('.picker-end'),   { initial: entry.current?'':(entry.end_date||''), onChange:(iso)=>{ hEnd.value=iso; touched.work_experience=true; scheduleSave(); }});

  hStart.value = entry.start_date||'';
  hEnd.value   = entry.current ? 'Present' : (entry.end_date||'');

  const toggleCurrent = (checked)=>{
    if (checked){
      hEnd.dataset.lastIso = (hEnd.value && hEnd.value!=='Present') ? hEnd.value : '';
      hEnd.value='Present';
      card.querySelectorAll('.picker-end select').forEach(s=>s.disabled=true);
    } else {
      card.querySelectorAll('.picker-end select').forEach(s=>s.disabled=false);
      const last = hEnd.dataset.lastIso||'';
      if (last){ pEnd.set(last); hEnd.value=last; } else { pEnd.set(''); hEnd.value=''; }
    }
  };
  toggleCurrent(!!entry.current);
  curCb.addEventListener('change', e=>{ toggleCurrent(e.target.checked); touched.work_experience=true; scheduleSave(); });

  card.querySelectorAll('input').forEach(el=>{
    el.addEventListener('input',  ()=>{ touched.work_experience=true; });
    el.addEventListener('change', ()=>{ touched.work_experience=true; scheduleSave(); });
  });

  workList.appendChild(card);
}


  function addToolEntry(entry={ tool:'', level:'Basic' }){
    const row = document.createElement('div');
    row.className='cv-card-entry';
    row.innerHTML = `
      <input type="text" class="tool-name" placeholder="Tool Name" value="${entry.tool||''}">
      <select class="tool-level">
        <option value="Basic" ${entry.level==='Basic'?'selected':''}>Basic</option>
        <option value="Intermediate" ${entry.level==='Intermediate'?'selected':''}>Intermediate</option>
        <option value="Advanced" ${entry.level==='Advanced'?'selected':''}>Advanced</option>
      </select>
      <button class="remove-entry" title="Remove">🗑️</button>
    `;
    row.querySelector('.remove-entry').addEventListener('click', ()=>{ row.remove(); touched.tools=true; scheduleSave(); });
row.querySelectorAll('input,select').forEach(el=>{
  el.addEventListener('input',  () => { touched.tools = true; scheduleSave(); });
  el.addEventListener('change', () => { touched.tools = true; scheduleSave(); });
});

    toolsList.appendChild(row);
    const name = row.querySelector('.tool-name'); if (name && !entry.tool) name.focus();
  }

  function addLanguageEntry(entry={ language:'', level:'Basic' }){
    const row = document.createElement('div');
    row.className='cv-card-entry';
    row.innerHTML = `
      <select class="language-name">
        <option value="">Select Language</option>
        <option value="English" ${entry.language==='English'?'selected':''}>English</option>
        <option value="Spanish" ${entry.language==='Spanish'?'selected':''}>Spanish</option>
        <option value="Portuguese" ${entry.language==='Portuguese'?'selected':''}>Portuguese</option>
        <option value="French" ${entry.language==='French'?'selected':''}>French</option>
        <option value="German" ${entry.language==='German'?'selected':''}>German</option>
      </select>
      <select class="language-level">
        <option value="Basic" ${entry.level==='Basic'?'selected':''}>Basic</option>
        <option value="Regular" ${entry.level==='Regular'?'selected':''}>Regular</option>
        <option value="Fluent" ${entry.level==='Fluent'?'selected':''}>Fluent</option>
        <option value="Native" ${entry.level==='Native'?'selected':''}>Native</option>
      </select>
      <button class="remove-entry" title="Remove">🗑️</button>
    `;
    row.querySelector('.remove-entry').addEventListener('click', ()=>{ row.remove(); touched.languages=true; scheduleSave(); });
row.querySelectorAll('select').forEach(el=>{
  el.addEventListener('input',  () => { touched.languages = true; scheduleSave(); });
  el.addEventListener('change', () => { touched.languages = true; scheduleSave(); });
});

    langsList.appendChild(row);
  }
function maybeAutolist(html){
  const escape = (s) => { const t = document.createElement('textarea'); t.textContent = s || ''; return t.innerHTML; };
  if (/<\/?(ul|ol|li)\b/i.test(html || '')) return html; // ya es una lista

  const txt = (html || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<[^>]+>/g, '');

  const lines = txt.split(/\n+/).map(s => s.trim()).filter(Boolean);
  const bulletRE = /^([\-*•·])\s+/;

  const bulletCount = lines.filter(l => bulletRE.test(l)).length;

  // requiere al menos 2 bullets y que sean ≥ 60% de las líneas
  if (lines.length >= 2 && bulletCount >= 2 && bulletCount / lines.length >= 0.6) {
    const items = lines
      .map(l => l.replace(bulletRE, ''))
      .filter(Boolean)
      .map(it => `<li>${escape(it)}</li>`)
      .join('');
    return `<ul>${items}</ul>`;
  }
  return html;
}


  // ---------- DOM → Data (normalized, filtered) ----------
  function readResumeFromDOM(){
    const about = normalizeText(stripHtmlToText(aboutEl?.innerHTML || ''));

    const education = qsa('#educationList .cv-card-entry').map(card=>{
      const inst = normalizeText(card.querySelector('.edu-inst')?.value);
      const title= normalizeText(card.querySelector('.edu-title')?.value);
      const country = normalizeText(card.querySelector('.edu-country')?.value);
      const start = normalizeISO15(card.querySelector('.edu-start')?.value?.trim()||'');
      const end   = normalizeISO15(card.querySelector('.edu-end')?.value?.trim()||'');
      const current = !!card.querySelector('.edu-current')?.checked;
      const descHtml = sanitizeHTML(card.querySelector('.edu-desc')?.innerHTML||'');
      const desc = isRichEmpty(descHtml) ? '' : descHtml;
      const empty = !(inst||title||country||start||end||current||desc);
      if (empty) return null;
      return { institution:inst, title, country, start_date:start, end_date:end, current, description:desc };
    }).filter(Boolean);

    const work_experience = qsa('#workExperienceList .cv-card-entry').map(card=>{
      const title = normalizeText(card.querySelector('.work-title')?.value);
      const company = normalizeText(card.querySelector('.work-company')?.value);
      const start = normalizeISO15(card.querySelector('.work-start')?.value?.trim()||'');
      const endRaw= (card.querySelector('.work-end')?.value?.trim()||'');
      const end   = normalizeISO15(endRaw);
      const current = !!card.querySelector('.work-current')?.checked;
const rawHtml  = card.querySelector('.work-desc')?.innerHTML || '';
const descHtml = sanitizeHTML(maybeAutolist(rawHtml));   // (con la versión nueva arriba)

      const desc = isRichEmpty(descHtml) ? '' : descHtml;
      const empty = !(title||company||start||end||current||desc);
      if (empty) return null;
      return { title, company, start_date:start, end_date:end, current, description:desc };
    }).filter(Boolean);

    const tools = qsa('#toolsList .cv-card-entry').map(row=>{
      const tool = normalizeText(row.querySelector('.tool-name')?.value);
      const level = row.querySelector('.tool-level')?.value || 'Basic';
      if (!tool) return null;
      return { tool, level };
    }).filter(Boolean);

    const languages = qsa('#languagesList .cv-card-entry').map(row=>{
      const language = normalizeText(row.querySelector('.language-name')?.value);
      const level    = row.querySelector('.language-level')?.value || 'Basic';
      if (!language) return null;
      return { language, level };
    }).filter(Boolean);

    const video_link = normalizeText(stripHtmlToText(videoEl?.innerHTML || ''));

    return { about, education, work_experience, tools, languages, video_link };
  }

  // ---------- DIFF & SAVE ----------
async function saveNow(){
  if (!hydrated) return;

  const current = readResumeFromDOM();

  // arma patch solo con cambios
  const patch = {};
  function maybe(field, val, stringify=false, touchKey=field){
    if (!touched[touchKey]) return;
    const prev = snapshot[field];
    if (!deepEqual(prev, val)){
      patch[field] = stringify ? JSON.stringify(val) : val;
    }
  }

  maybe('about', current.about);
  maybe('education', current.education, true);
  maybe('work_experience', current.work_experience, true);
  maybe('tools', current.tools, true);
  maybe('languages', current.languages, true);
  maybe('video_link', current.video_link);

  if (Object.keys(patch).length === 0) return;

  // --- NUEVO: detectar si se vació alguna description dentro de los arrays
  const eduPrev = snapshot.education || [];
  const eduCurr = current.education || [];
  const workPrev = snapshot.work_experience || [];
  const workCurr = current.work_experience || [];

  const workChanges = _findDescChanges(workPrev, workCurr, 'work');
  const eduChanges  = _findDescChanges(eduPrev,  eduCurr,  'edu');

  const anyDescCleared = [...workChanges, ...eduChanges]
    .some(ch => ch.type === 'cleared');

  // allow_clear si: arrays en [] / campos en '' / o alguna description fue limpiada
  const clearsTopLevel = Object.entries(patch).some(([k, v]) => {
    if (['education','work_experience','tools','languages'].includes(k)) {
      return v === '[]' || (Array.isArray(v) && v.length === 0);
    }
    if (k === 'video_link' || k === 'about') {
      return v === '' || v == null;
    }
    return false;
  });
  const needAllowClear = clearsTopLevel || anyDescCleared;

  const url = `${API_BASE}/resumes/${candidateId}${needAllowClear ? '?allow_clear=true' : ''}`;

  // --- LOG PREVIO AL PATCH ---
  if (DEBUG_SAVE){
    const changedKeys = Object.keys(patch);
    console.groupCollapsed(
      `💾 Guardar cambios → ${changedKeys.join(', ')} ${needAllowClear ? '(allow_clear)' : ''}`
    );
    if (workChanges.length){
      console.groupCollapsed(`✍️ work_experience (${workChanges.length} cambio/s)`);
      workChanges.forEach(ch=>{
        console.log(`[${ch.type}] #${ch.index} ${ch.label}`);
        console.log('  before:', _previewText(ch.before));
        console.log('  after :', _previewText(ch.after));
        console.log(`  lens  : ${ch.beforeLen} → ${ch.afterLen}`);
      });
      console.groupEnd();
    }
    if (eduChanges.length){
      console.groupCollapsed(`✍️ education (${eduChanges.length} cambio/s)`);
      eduChanges.forEach(ch=>{
        console.log(`[${ch.type}] #${ch.index} ${ch.label}`);
        console.log('  before:', _previewText(ch.before));
        console.log('  after :', _previewText(ch.after));
        console.log(`  lens  : ${ch.beforeLen} → ${ch.afterLen}`);
      });
      console.groupEnd();
    }
    console.groupEnd();
  }

  try {
    saving = true;

    let triedCreate = false;
    let lastRes = null;
    while (true) {
      lastRes = await fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type':'application/json' },
        body: JSON.stringify(patch)
      });
      if (lastRes.ok) break;
      if (lastRes.status === 404 && !triedCreate) {
        triedCreate = true;
        await ensureResumeExists(); // crea y reintenta
        continue;
      }
      console.error('❌ PATCH /resumes failed', lastRes.status, await lastRes.text().catch(()=>'')); 
      break;
    }

    if (DEBUG_SAVE){
      if (lastRes?.ok) {
        console.info(`✅ PATCH /resumes (${needAllowClear ? 'allow_clear' : 'normal'}) OK`);
      } else {
        console.warn('⚠️ PATCH /resumes terminó con error');
      }
    }

    // merge al snapshot: parsea arrays que enviamos como strings
    const merged = { ...snapshot };
    for (const [k, v] of Object.entries(patch)){
      if (['education','work_experience','tools','languages'].includes(k)){
        merged[k] = safeParseArray(v, []);
      } else {
        merged[k] = v;
      }
    }
    snapshot = merged;

  } catch(e){
    console.error('❌ PATCH /resumes failed', e);
  } finally{
    saving = false;
    if (savePending){ savePending=false; saveNow(); }
  }
}


const debouncedSave = debounce(saveNow, 250); // antes 500

const scheduleSave  = () => { 
  if (saving) { savePending = true; return; } 
  debouncedSave(); 
};

// --- Exponer internos para helpers globales ---
window.__resume = Object.assign(window.__resume || {}, {
  touch: (k) => { try { if (k) touched[k] = true; } catch {} },
  scheduleSave,
  saveNow,
  debouncedSave,
  sanitizeHTML,
  maybeAutolist,
  isRichEmpty,
  stripHtmlToText,   // ← exportado
  normalizeText      // ← opcional, útil tenerlo afuera
});


  // ---------- Load ----------
  async function loadResume(){
    try{
      const r = await fetch(`${API_BASE}/resumes/${candidateId}`);
      const d = await r.json();
      snapshot = {
        about: d.about || '',
        education: safeParseArray(d.education, []),
        work_experience: safeParseArray(d.work_experience, []),
        tools: safeParseArray(d.tools, []),
        languages: safeParseArray(d.languages, []),
        video_link: (d.video_link ?? '').toString()
      };

      // Pintar
      if (aboutEl) aboutEl.innerHTML = snapshot.about || 'Click here to edit your About section.';
      (snapshot.education||[]).forEach(addEducationEntry);
      (snapshot.work_experience||[]).forEach(addWorkExperienceEntry);
      (snapshot.tools||[]).forEach(addToolEntry);
      (snapshot.languages||[]).forEach(addLanguageEntry);
      if (videoEl) videoEl.innerHTML = snapshot.video_link || '';

      hydrated = true;
    }catch(e){
      console.warn('⚠️ GET /resumes failed', e);
      snapshot = { about:'', education:[], work_experience:[], tools:[], languages:[], video_link:'' };
      hydrated = true;
    }
  }

  // ---------- Events (mark touched) ----------
if (aboutEl){
  aboutEl.contentEditable = 'true';
  aboutEl.addEventListener('input', () => markAndSave('about'));
  aboutEl.addEventListener('blur',  () => markAndSave('about'));
}
if (videoEl){
  videoEl.contentEditable = 'true';
  videoEl.addEventListener('keydown', e => { if (e.key === 'Enter'){ e.preventDefault(); videoEl.blur(); }});
  videoEl.addEventListener('input', () => markAndSave('video_link'));
  videoEl.addEventListener('blur',  () => markAndSave('video_link'));
}

  addEduBtn?.addEventListener('click', ()=>{ addEducationEntry(); touched.education=true; scheduleSave(); });
  addWorkBtn?.addEventListener('click', ()=>{ addWorkExperienceEntry(); touched.work_experience=true; scheduleSave(); });
  addToolBtn?.addEventListener('click', ()=>{ addToolEntry(); touched.tools=true; scheduleSave(); });
  addLangBtn?.addEventListener('click', ()=>{ addLanguageEntry(); touched.languages=true; scheduleSave(); });

  // Pegar texto plano en todos los contenteditable del resume

function escapeHtml(s){ const t=document.createElement('textarea'); t.textContent = s || ''; return t.innerHTML; }

qsa('#resume [contenteditable="true"]').forEach(el=>{
  el.addEventListener('paste', (e)=>{
    e.preventDefault();
let text = (e.clipboardData||window.clipboardData).getData('text') || '';
text = text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, ' ').trim();
// convierte 'ì ' (copiada de Word/Docs) a '- ' para bullets simples
text = text.replace(/(^|\n)\s*ì\s+/g, '$1- ');


    const lines = text.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    let html = '';

    // si detecta bullets estilo "- ", "* " o "• " → crea <ul><li>…</li></ul>
    if (lines.some(l => /^[-*•]\s+/.test(l))) {
      const items = lines.map(l => l.replace(/^[-*•]\s+/, '')).filter(Boolean);
      html = `<ul>${items.map(it => `<li>${escapeHtml(it)}</li>`).join('')}</ul>`;
    } else if (lines.length > 1) {
      // varias líneas → párrafos
      html = lines.map(l => `<p>${escapeHtml(l)}</p>`).join('');
    } else {
      // una sola línea
      html = escapeHtml(text);
    }

    document.execCommand('insertHTML', false, html);
  });

  el.addEventListener('input', ()=>{
    // limpia estilos inline
    el.querySelectorAll('*').forEach(node=>node.removeAttribute('style'));
  });
});


  // ---------- AI Generate (usa tus ids existentes) ----------
/* =========================
   CVs (upload/list/delete/open) + Auto-extract PDF → cv_pdf_scrapper
   ========================= */
(() => {
  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const candidateId = new URLSearchParams(location.search).get('id');
  const drop = document.getElementById('cv-drop');
  const input = document.getElementById('cv-input');
  const browseBtn = document.getElementById('cv-browse');
  const refreshBtn = document.getElementById('cv-refresh');
  const list = document.getElementById('cv-list');
  if (!candidateId || !drop || !input || !list) return;

  const cvIndicator = (() => {
    const el = document.createElement('div');
    el.className = 'cv-indicator';
    el.innerHTML = `<span class="spinner"></span><span class="msg">Extracting info from CV…</span>`;
    document.body.appendChild(el);
    const setIcon = (t) => { const first=el.firstElementChild; if (!first) return; first.className = (t==='check') ? 'check' : 'spinner'; };
    return {
      show(msg='Extracting info from CV…'){ setIcon('spinner'); el.querySelector('.msg').textContent=msg; el.classList.add('show'); },
      success(msg='Done'){ setIcon('check'); el.querySelector('.msg').textContent=msg; },
      hide(){ el.classList.remove('show'); }
    };
  })();

  function render(items=[]){
    list.innerHTML='';
    if (!items.length){
      list.innerHTML = `<div class="cv-item"><span class="cv-name" style="opacity:.65">No files yet</span></div>`;
      return;
    }
    items.forEach(it=>{
      const row = document.createElement('div');
      row.className = 'cv-item';
      row.innerHTML = `
        <span class="cv-name" title="${it.name}">${it.name}</span>
        <div class="cv-actions">
          <a class="btn" href="${it.url}" target="_blank" rel="noopener">Open</a>
          <button class="btn danger" data-key="${it.key}" type="button">Delete</button>
        </div>
      `;
      row.querySelector('.danger').addEventListener('click', async (e)=>{
        const key = e.currentTarget.getAttribute('data-key');
        if (!key) return;
        if (!confirm('Delete this file?')) return;
        await fetch(`${API_BASE}/candidates/${candidateId}/cvs`, {
          method:'DELETE', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ key })
        });
        await loadCVs();
      });
      list.appendChild(row);
    });
  }

  async function loadCVs(){
    try{
      const r = await fetch(`${API_BASE}/candidates/${candidateId}/cvs`);
      const data = await r.json();
      render(Array.isArray(data)?data:[]);
    }catch(e){ console.warn('Failed to load CVs', e); render([]); }
  }
  window.loadCVs = loadCVs; // para llamadas desde tabs

  async function uploadFile(file){
    const allowedMimes = new Set(['application/pdf','image/png','image/jpeg','image/webp','application/octet-stream','']);
    const extOk = /\.(pdf|png|jpe?g|webp)$/i.test(file.name || '');
    if (!allowedMimes.has(file.type) && !extOk){ alert('Only PDF, PNG, JPG/JPEG or WEBP are allowed.'); return; }
    const isPdf = file.type==='application/pdf' || /\.pdf$/i.test(file.name||'');

    const fd = new FormData(); fd.append('file', file);
    try{
      drop.classList.add('dragover');
      cvIndicator.show(isPdf ? 'Extracting info from CV…' : 'Uploading file…');
      const r = await fetch(`${API_BASE}/candidates/${candidateId}/cvs`, { method:'POST', body: fd });
      if (!r.ok){ const t=await r.text().catch(()=> ''); throw new Error(t||`Upload failed (${r.status})`); }
      const data = await r.json();
      render(data.items || []);
      cvIndicator.success(isPdf ? 'CV extracted' : 'Uploaded');
      setTimeout(()=>cvIndicator.hide(), 900);
    }catch(e){ console.error('Upload failed', e); alert('Upload failed'); cvIndicator.hide(); }
    finally{ drop.classList.remove('dragover'); input.value=''; }
  }

  // Drag & Drop
  ;['dragenter','dragover'].forEach(ev=>drop.addEventListener(ev, e=>{ e.preventDefault(); e.stopPropagation(); drop.classList.add('dragover'); }));
  ;['dragleave','dragend','drop'].forEach(ev=>drop.addEventListener(ev, e=>{ e.preventDefault(); e.stopPropagation(); drop.classList.remove('dragover'); }));
  drop.addEventListener('drop', e=>{ const f=e.dataTransfer?.files?.[0]; if (f) uploadFile(f); });

  // Click/browse
  browseBtn?.addEventListener('click', ()=> input.click());
  drop.addEventListener('click', (e)=>{ if ((e.target instanceof HTMLElement) && e.target.closest('.cv-actions')) return; input.click(); });
  input.addEventListener('change', ()=>{ const f=input.files?.[0]; if (f) uploadFile(f); });
  refreshBtn?.addEventListener('click', async ()=>{
    const ic = refreshBtn.querySelector('.btn-icon');
    refreshBtn.disabled = true; ic?.classList.add('spin');
    await loadCVs();
    setTimeout(()=>ic?.classList.remove('spin'), 400);
    refreshBtn.disabled = false;
  });

  // Auto-extract 1: si NO hay affinda_scrapper y hay un PDF ya subido
  (async function autoExtractFromPdfOnLoad(){
    try{
      const cand = await fetch(`${API_BASE}/candidates/${candidateId}`).then(r=>r.json());
      const hasAffinda = (cand.affinda_scrapper || '').trim().length > 0;
      if (hasAffinda) return;

      const items = await fetch(`${API_BASE}/candidates/${candidateId}/cvs`).then(r=>r.json()).catch(()=>[]);
      const pdf = (Array.isArray(items)?items:[]).find(it => /\.pdf$/i.test(it.name||'')) || null;
      if (!pdf || !pdf.url) return;

      cvIndicator.show('Extracting info from CV…');
      const res = await fetch(`${API_BASE}/ai/extract_cv_from_pdf`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ candidate_id: candidateId, pdf_url: pdf.url })
      });
      const out = await res.json();
      if (out.extracted_text){
        const aiCvScrap = document.getElementById('ai-cv-scrap');
        if (aiCvScrap){
          aiCvScrap.value = out.extracted_text;
          aiCvScrap.dispatchEvent(new Event('blur')); // dispara el PATCH
        }
        cvIndicator.success('CV extracted');
        setTimeout(()=>cvIndicator.hide(), 900);
      } else {
        cvIndicator.hide();
      }
    }catch(e){ console.warn('autoExtractFromPdfOnLoad:', e); try{ cvIndicator.hide(); }catch{} }
  })();

  // Carga inicial si ya estás en Overview
  if (document.querySelector('.tab.active')?.dataset.tab === 'overview') loadCVs();

})();


  // ---------- Boot ----------
(async function init(){
  await loadResume();                 // ← sólo lee; no crees nada aquí
  // deja que candidate-details.js maneje la visibilidad del botón por pestaña
})();

  // Expose for debugging
// --- al final de resume.js ---
window.Resume = {
  read: readResumeFromDOM,
  get snapshot(){ return snapshot; },
  ensure: ensureResumeExists,

  applyGenerated(result = {}) {
    const has = (k) => Object.prototype.hasOwnProperty.call(result, k);

    // About
    if (has('about') && result.about != null) {
      if (aboutEl) aboutEl.innerHTML = result.about;
      touched.about = true;
    }

    // Education (solo si la clave viene)
    if (has('education')) {
      const edu = safeParseArray(result.education, null); // null ≠ []
      if (Array.isArray(edu)) {
        if (eduList) eduList.innerHTML = '';
        edu.forEach(addEducationEntry);
        touched.education = true;
      }
    }

    // Work Experience (solo si la clave viene)
    if (has('work_experience')) {
      const work = safeParseArray(result.work_experience, null);
      if (Array.isArray(work)) {
        if (workList) workList.innerHTML = '';
        work.forEach(addWorkExperienceEntry);
        touched.work_experience = true;
      }
    }

    // Tools (solo si la clave viene)
    if (has('tools')) {
      const tools = safeParseArray(result.tools, null);
      if (Array.isArray(tools)) {
        if (toolsList) toolsList.innerHTML = '';
        tools.forEach(addToolEntry);
        touched.tools = true;
      }
    }

    // Languages (solo si la clave viene)
    if (has('languages')) {
      const langs = safeParseArray(result.languages, null);
      if (Array.isArray(langs)) {
        if (langsList) langsList.innerHTML = '';
        langs.forEach(addLanguageEntry);
        touched.languages = true;
      }
    }

    (typeof scheduleSave === 'function' ? scheduleSave : debouncedSave)();
  }
};




})();

// Helper para compatibilidad con el código antiguo
function markAndSave(field) {
  try { window.__resume?.touch?.(field); } catch {}
  if (typeof window.__resume?.scheduleSave === 'function') {
    window.__resume.scheduleSave();
  } else if (typeof window.__resume?.debouncedSave === 'function') {
    window.__resume.debouncedSave();
  } else if (typeof window.__resume?.saveNow === 'function') {
    window.__resume.saveNow();
  }
}

function normalizeWeirdBullets(html) {
  // quita 'ì ' sólo cuando aparece al inicio de línea o justo después de una etiqueta
  return String(html || '').replace(/(^|>|\n|\r)\s*ì\s+/g, '$1');
}
// ==== DEBUG / LOGGING ==== 
const DEBUG_SAVE = true;

function _previewText(html, max = 140) {
  const strip = (window.__resume && window.__resume.stripHtmlToText)
    ? window.__resume.stripHtmlToText
    : (h => { const d = document.createElement('div'); d.innerHTML = h || ''; return (d.textContent || '').trim(); });

  const t = strip(html || '');
  return t.length > max ? t.slice(0, max) + '…' : t;
}

function _descLen(html) {
  const strip = (window.__resume && window.__resume.stripHtmlToText)
    ? window.__resume.stripHtmlToText
    : (h => { const d = document.createElement('div'); d.innerHTML = h || ''; return (d.textContent || '').trim(); });

  return strip(html || '').length;
}

function _summarizeEntry(kind, e){
  if (kind === 'work') {
    const t = (e?.title || '').trim() || '(sin título)';
    const c = (e?.company || '').trim();
    return c ? `${t} @ ${c}` : t;
  } else {
    const t = (e?.title || '').trim() || '(sin título)';
    const i = (e?.institution || '').trim();
    return i ? `${t} – ${i}` : t;
  }
}
function _findDescChanges(prevList=[], currList=[], kind='work'){
  const changes = [];
  const maxLen = Math.max(prevList.length, currList.length);
  for (let i=0;i<maxLen;i++){
    const prev = prevList[i];
    const curr = currList[i];

    // agregado o removido
    if (!prev && curr){
      changes.push({ type:'added', index:i, label:_summarizeEntry(kind, curr),
                     before:'', after:curr.description||'', beforeLen:0, afterLen:_descLen(curr.description) });
      continue;
    }
    if (prev && !curr){
      changes.push({ type:'removed', index:i, label:_summarizeEntry(kind, prev),
                     before:prev.description||'', after:'', beforeLen:_descLen(prev.description), afterLen:0 });
      continue;
    }

    // actualizado
    const b = prev?.description || '';
    const a = curr?.description || '';
    if (JSON.stringify(b) !== JSON.stringify(a)){
      const bl = _descLen(b), al = _descLen(a);
      const type = (bl>0 && al===0) ? 'cleared' : 'updated';
      changes.push({ type, index:i, label:_summarizeEntry(kind, curr||prev),
                     before:b, after:a, beforeLen:bl, afterLen:al });
    }
  }
  return changes;
}
function wireDescEditors(descEl, touchKey) {
  if (!descEl) return;

  const R = window.__resume || {};

  const flushIfEmpty = () => {
    const html = descEl.innerHTML || '';
    const cleaned = (R.sanitizeHTML || (x => x))((R.maybeAutolist || (x => x))(html));
    const isEmpty = (R.isRichEmpty || (() => false))(cleaned);
    if (isEmpty) {
      descEl.innerHTML = '';
      try { R.touch?.(touchKey); } catch {}
      R.saveNow?.();
      return true;
    }
    return false;
  };

  descEl.addEventListener('input', () => {
    try { R.touch?.(touchKey); } catch {}
    if (!flushIfEmpty()) R.debouncedSave?.();
  });

  descEl.addEventListener('blur', () => {
    try { R.touch?.(touchKey); } catch {}
    R.saveNow?.();
  });

  descEl.addEventListener('paste', () => {
    try { R.touch?.(touchKey); } catch {}
    setTimeout(() => { if (!flushIfEmpty()) R.saveNow?.(); }, 0);
  });
}


