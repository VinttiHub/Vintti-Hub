// === Config ===
const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

const $ = (s, r=document)=>r.querySelector(s);
const $all = (s, r=document)=>[...r.querySelectorAll(s)];

document.addEventListener('DOMContentLoaded', () => {
  const input = $('#nl-query');
  const btn   = $('#search-btn');
  const chips = $('#chips');
  const cards = $('#vintti-results');
  const empty = $('#vintti-empty');
  const tpl   = $('#card-tpl');
  const expFilter = $('#exp-filter');
  let _vinttiAll = []; // ← guardamos todos los candidatos internos de la última búsqueda
  const csWrap   = document.querySelector('#coresignal-wrap');
  const csList   = document.querySelector('#cs-results');
  const csEmpty  = document.querySelector('#cs-empty');
  const csMore   = document.querySelector('#cs-more');
  const csTpl    = document.querySelector('#cs-card-tpl');
  let   _csState = { lastParsed: null, page: 1, hasMore: true };

async function parseQuery(q){
  console.log('➡️ POST /ai/parse_candidate_query body:', { query: q });
  const res = await fetch(`${API_BASE}/ai/parse_candidate_query`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    credentials:'include',
    body: JSON.stringify({ query: q })
  });
  if (!res.ok) throw new Error('Parse failed');
  return await res.json();
}
async function searchCandidates(tools, opts = {}) {
  const params = new URLSearchParams();
  if (tools && tools.length) params.set('tools', tools.join(','));

  // 🔹 nuevo: pasamos la location que sacó el parser al backend
  if (opts.location) {
    params.set('location', opts.location);
  }

  const full = `${API_BASE}/search/candidates?` + params.toString();
  console.log('➡️ GET', full);
  const res = await fetch(full, { credentials:'include' });
  if (!res.ok) throw new Error('Search failed');
  const json = await res.json();
  console.log('📦 items:', (json.items||[]).length);
  return json;
}
async function coresignalSearch(parsed, page=1){
  const body = {
    title: parsed.title || "",
    skills: (parsed.tools || []).map(s => String(s).toLowerCase().trim()).filter(Boolean),
    location: parsed.location || "",
    years_min: parsed.years_experience ?? null,
    page,
    debug: true,
    allow_fallback: true // ← activa E1→E2→E3 automáticamente
  };

  console.groupCollapsed('%c🌐 POST /ext/coresignal/search','color:#1f7a8c;font-weight:bold');
  console.log('➡️ body →', body);

  const res = await fetch(`${API_BASE}/ext/coresignal/search`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    credentials:'include',
    body: JSON.stringify(body)
  });

  console.log('⬅️ status →', res.status, res.statusText);
  const json = await res.json();

  const arr = Array.isArray(json?.data) ? json.data : (json?.data?.items || []);
  const count = arr.length;
  console.log('📦 items_count →', count);
  console.log('🧭 strategy_used →', json.strategy_used);

  if (json.debug){
    console.table(json.debug.attempts || []);
    console.log('⏱️ total_ms →', json.debug.duration_ms_total);
    console.log('🔎 sample →', json.debug.sample);
  }

  if (count === 0){
    console.warn('⚠️ Coresignal devolvió 0 items en todas las estrategias. Revisa filtros/title/location/years.');
  }
  console.groupEnd();
  return json;
}

function renderCs(items, {append=false}={}){
  if (!append) csList.innerHTML = '';
  if (!items || !items.length){
    if (!append) csEmpty.classList.remove('hidden');
    return;
  }
  csEmpty.classList.add('hidden');

  for (const it of (items || [])){
    const node = csTpl.content.firstElementChild.cloneNode(true);

    // Campos típicos de preview (ajusta si tu respuesta cambia):
    const name  = it.name || it.full_name || it.public_identifier || 'Profile';
    const loc   = it.location || it.country || '—';
    const head  = it.headline || '';
    const eid   = it.employee_id || it.id || it.public_identifier;

    node.querySelector('.cs-card-name').textContent = name;
    node.querySelector('.cs-card-meta').textContent = loc;
    node.querySelector('.cs-card-notes').textContent = head || '—';

    // === LinkedIn href directo, si está en el preview ===
    // Posibles campos: linkedin_url directo, o public_identifier para armar la URL
    const liRaw =
      it.linkedin_url || it.linkedin || it.linkedinUrl || null;
    const publicId =
      it.public_identifier || it.publicIdentifier || null;

    let liHref = null;
    if (liRaw && /^https?:\/\//i.test(liRaw)) {
      liHref = liRaw;
    } else if (publicId) {
      liHref = `https://www.linkedin.com/in/${encodeURIComponent(publicId)}`;
    }

    // Asegurar que abra en nueva pestaña de manera segura
    node.target = '_blank';
    node.rel = 'noopener';

    if (liHref) {
      // Si ya tenemos LinkedIn, enlazamos directamente la tarjeta
      node.href = liHref;
      node.title = 'Abrir perfil en LinkedIn';
      // (opcional): quitar cualquier handler para evitar bloquear el default
      node.addEventListener('click', (e) => {
        // Permitir el comportamiento por defecto del <a>
      });
    } else {
      // Si no tenemos LinkedIn en el preview, usamos collect al hacer click
      node.href = '#';
      node.title = 'Ver detalles (intentará abrir LinkedIn)';
      node.addEventListener('click', async (e)=>{
        e.preventDefault();
        if (!eid) return;

        try{
          const det = await fetch(`${API_BASE}/ext/coresignal/collect`, {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            credentials:'include',
            body: JSON.stringify({ employee_id: eid })
          }).then(r=>r.json());

          console.log('🧾 collect →', det);
          // Intentar resolver LinkedIn desde el collect:
          const dLi =
            det.linkedin_url || det.linkedin || det.linkedinUrl || null;
          const dPublic =
            det.public_identifier || det.publicIdentifier || null;
          const dProfile =
            det.profile_url || det.profileUrl || null; // 👈 este es el que estás viendo en el log

          let finalUrl = null;

          // 1) Si viene un URL directo (linkedin_url o profile_url)
          if (dLi && /^https?:\/\//i.test(dLi)) {
            finalUrl = dLi;
          } else if (dProfile && /^https?:\/\//i.test(dProfile)) {
            finalUrl = dProfile;
          // 2) Si no, lo armamos con public_identifier
          } else if (dPublic) {
            finalUrl = `https://www.linkedin.com/in/${encodeURIComponent(dPublic)}`;
          }

          if (finalUrl) {
            window.open(finalUrl, '_blank', 'noopener');
            return;
          }

          // Fallback: si tampoco viene en collect, mantén tu modal / log
          console.warn('No se encontró LinkedIn en preview ni en collect.');

          // Fallback: si tampoco viene en collect, mantén tu modal
          // TODO: abre un modal lindo con info clave (linkedin, skills, exp…)
          console.warn('No se encontró LinkedIn en preview ni en collect.');
        }catch(err){
          console.error('collect error', err);
        }
      });
    }

    csList.appendChild(node);
  }
}

function renderChips({ title, tools, years_experience, location }){
  chips.innerHTML = '';
  const items = [];

  // 💼 Posición / título
  if (title) {
    items.push({ label: `💼 ${title}` });
  }

  // 🧰 Tools / skills
  (tools || []).forEach(t => {
    items.push({ label: `🧰 ${t}` });
  });

  // ⏳ Años de experiencia
  if (Number.isFinite(years_experience)) {
    items.push({ label: `⏳ ${years_experience} yrs` });
  }

  // 📍 Location (ya lo tenías)
  if (location) {
    items.push({ label: `📍 ${location}` });
  }

  if (!items.length){
    chips.classList.add('hidden');
    return;
  }

  for (const it of items){
    const s = document.createElement('span');
    s.className = 'chip';
    s.textContent = it.label;
    chips.appendChild(s);
  }
  chips.classList.remove('hidden');
}
  function applyExperienceFilterAndRender(){
    // Limpiamos las tarjetas
    cards.innerHTML = '';

    // Si no hay resultados cargados aún
    if (!_vinttiAll || !_vinttiAll.length){
      empty.classList.remove('hidden');
      return;
    }

    let filtered = _vinttiAll;

    if (expFilter && expFilter.value !== '') {
      const minYears = parseInt(expFilter.value, 10);
      if (!Number.isNaN(minYears)) {
        filtered = _vinttiAll.filter(row => {
          const y = (typeof row.years_experience === 'number' && Number.isFinite(row.years_experience))
            ? row.years_experience
            : 0; // si no tenemos info, lo tratamos como 0 años
          return y >= minYears;
        });
      }
    }

    if (!filtered.length){
      empty.classList.remove('hidden');
      return;
    }

    empty.classList.add('hidden');

    for (const row of filtered){
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.href = `https://vinttihub.vintti.com/candidate-details.html?id=${encodeURIComponent(row.candidate_id)}`;
      
      // Nombre
      node.querySelector('.card-name').textContent = row.name || '(sin nombre)';
      
      // País + nivel de inglés
      node.querySelector('.card-meta').textContent =
        (row.country || '—') + (row.english_level ? ` · 🇬🇧 ${row.english_level}` : '');
      
      // 💸 Salario deseado (salary_range)
      const notesEl = node.querySelector('.card-notes');
      const salary = row.salary_range && String(row.salary_range).trim();
      if (salary) {
        // Puedes ajustar el texto como prefieras
        notesEl.textContent = `Desired salary: ${salary}`;
      } else {
        notesEl.textContent = '';
      }

      cards.appendChild(node);
    }
  }

  function renderCards(results){
    // Guardamos todos los resultados de la búsqueda actual
    _vinttiAll = results || [];
    // Renderizamos aplicando (o no) el filtro actual de experiencia
    applyExperienceFilterAndRender();
  }
async function doSearch(){
  const q = input.value.trim();
  if (!q){ input.focus(); return; }

  console.groupCollapsed('%cAI Candidate Search','color:#6b5b95;font-weight:bold');
  console.log('🔎 Query (usuario) →', q);

  btn.disabled = true; btn.textContent = 'Buscando…';
  try{
    // 1) Parser
    console.groupCollapsed('🧠 Llamada a /ai/parse_candidate_query');
    const parsed = await parseQuery(q);
    console.log('↩️ Respuesta parser:', parsed);
    console.groupEnd();

    renderChips(parsed);

    const tools = (parsed.tools || [])
      .map(s => String(s).toLowerCase().trim())
      .filter(Boolean);

    const location = (parsed.location || '').trim();
    const yearsFromParser = parsed.years_experience;

    console.groupCollapsed('🧰 Filtros normalizados para Vintti Talent');
    console.log('tools →', tools);
    console.log('location →', location);
    console.log('years_experience →', yearsFromParser);
    console.groupEnd();

    // 2) Buscar en Vintti Talent, pasando también la location
    console.groupCollapsed('📡 Fetch /search/candidates');
    const data = await searchCandidates(tools, { location });
    console.log('↩️ Respuesta search:', data);

    // 🔹 nuevo: setear el dropdown de años según lo que detectó el parser
    if (expFilter) {
      if (Number.isFinite(yearsFromParser)) {
        expFilter.value = String(yearsFromParser);   // ej: "3"
        console.log('🎚️ exp-filter seteado a', expFilter.value);
      } else {
        // si no hay filtro de años en el query, dejamos el dropdown en blanco
        expFilter.value = '';
        console.log('🎚️ exp-filter limpiado (sin filtro de años en query)');
      }
    }

    console.groupEnd();

    // Renderizamos usando el filtro actual (que ya apunta a years_experience del parser si existe)
    renderCards(data.items || []);

    // 3) Coresignal (se queda igual, usando parsed completo)
    _csState = { lastParsed: parsed, page: 1, hasMore: true };
    csList.innerHTML = ''; csEmpty.classList.add('hidden');
    csMore.classList.add('hidden');

    const csRes = await coresignalSearch(parsed, 1);
    const csItems = Array.isArray(csRes?.data) ? csRes.data : (csRes?.data?.items || []);
    renderCs(csItems, { append:false });

    if (csItems.length > 0){
      csMore.classList.remove('hidden');
    }else{
      csEmpty.classList.remove('hidden');
      csMore.classList.add('hidden');
    }

  }catch(err){
    console.error('❌ Error en doSearch:', err);
    renderCards([]);
  }finally{
    btn.disabled = false; btn.textContent = 'Buscar';
    console.groupEnd(); // AI Candidate Search
  }
}


  btn.addEventListener('click', doSearch);
  input.addEventListener('keydown', (e)=>{ if(e.key==='Enter') doSearch(); });
    if (csMore){
    csMore.addEventListener('click', async ()=>{
      try{
        csMore.disabled = true; csMore.textContent = 'Cargando…';
        _csState.page += 1;
        const pageRes = await coresignalSearch(_csState.lastParsed, _csState.page);
        const items = (pageRes?.data?.items) || [];
        renderCs(items, {append:true});
        // preview tiene hasta 5 páginas
        const totalPages = 5;
        if (_csState.page >= totalPages || items.length === 0) {
          _csState.hasMore = false;
          csMore.classList.add('hidden');
        } else {
          csMore.classList.remove('hidden');
        }
      } finally {
        csMore.disabled = false; csMore.textContent = 'Cargar más';
      }
    });
  }
  if (expFilter){
    expFilter.addEventListener('change', () => {
      applyExperienceFilterAndRender();
    });
  }
});
