// === Config ===
const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
const USA_PATTERN = /^usa\s+([a-z]{2})$/i;
function normalizeCountryForComparison(country) {
  if (!country) return '';
  const value = country.toString().trim().toLowerCase();
  if (!value) return '';
  if (
    value === 'usa' ||
    value === 'us' ||
    value === 'u.s.' ||
    USA_PATTERN.test(value)
  ) return 'united states';
  return value;
}

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

  // 🔹 location que sacó el parser
  if (opts.location) {
    params.set('location', opts.location);
  }

  // 🔹 nuevo: title / posición que sacó el parser
  if (opts.title) {
    params.set('title', opts.title);
  }

  const full = `${API_BASE}/search/candidates?` + params.toString();
  console.log('➡️ GET', full);
  const res = await fetch(full, { credentials:'include' });
  if (!res.ok) throw new Error('Search failed');
  const json = await res.json();
  console.log('📦 items:', (json.items||[]).length);
  return json;
}
async function coresignalSearch(parsed, page = 1, locationOverride = null){
  const body = {
    title: parsed.title || "",
    skills: (parsed.tools || [])
      .map(s => String(s).toLowerCase().trim())
      .filter(Boolean),
    // 👇 si viene override (México/Argentina/Colombia), lo usamos;
    // si no, usamos la location que sacó el parser
    location: locationOverride || parsed.location || "",
    years_min: parsed.years_experience ?? null,
    page,
    debug: true,
    allow_fallback: true // ← ya lo tenías
  };

  console.groupCollapsed(
    `%c🌐 POST /ext/coresignal/search (page=${page}, loc=${body.location || 'LATAM gate'})`,
    'color:#1f7a8c;font-weight:bold'
  );
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

async function coresignalMultiSearch(parsed){
  const order = [
    { tag: '🇲🇽 Mexico',       loc: 'Mexico'        },
    { tag: '🇺🇸 United States',loc: 'United States' },
    { tag: '🇨🇦 Canada',       loc: 'Canada'        },
    { tag: '🇦🇷 Argentina',    loc: 'Argentina'     },
    { tag: '🇨🇴 Colombia',     loc: 'Colombia'      },
    { tag: '🌎 General LATAM', loc: null }          // null → gate LATAM en backend
  ];

  const seen = new Set();
  let firstBatch = true;
  let total = 0;

  for (const cfg of order){
    console.groupCollapsed(
      `%c🌐 Coresignal ${cfg.tag}`,
      'color:#1f7a8c;font-weight:bold'
    );

    let res, arr;
    try {
      res = await coresignalSearch(parsed, 1, cfg.loc);
      arr = Array.isArray(res?.data) ? res.data : (res?.data?.items || []);
      console.log(`📦 ${cfg.tag} items (raw) →`, arr.length);
    } catch (err) {
      console.error(`❌ Error en coresignalSearch para ${cfg.tag}`, err);
      console.groupEnd();
      continue;
    }

    // 👉 quitar duplicados entre países
    const unique = [];
    for (const it of arr){
      const id =
        it.employee_id ||
        it.id ||
        it.public_identifier ||
        it.publicIdentifier ||
        it.canonical_shorthand_name;

      if (!id) continue;
      if (seen.has(id)) continue;
      seen.add(id);
      unique.push(it);
    }

    console.log(`✅ ${cfg.tag} únicos →`, unique.length);

    if (unique.length){
      // La primera búsqueda limpia la lista, las demás solo agregan
      renderCs(unique, { append: !firstBatch });
      firstBatch = false;
      total += unique.length;
    }

    console.groupEnd();
  }

  console.log('📦 Total Coresignal combinados (sin duplicados) →', total);
  return total;
}

function renderCs(items, {append=false}={}){
  if (!append) csList.innerHTML = '';
  if (!items || !items.length){
    if (!append) csEmpty.classList.remove('hidden');
    return;
  }
  csEmpty.classList.add('hidden');

  // 🔥 Ordenar por país: 1) México 2) United States 3) Canada 4) Argentina 5) Colombia 6) resto
  const countryPriority = (it) => {
    const raw = (it.country || '').toString().toLowerCase();
    const normalized = normalizeCountryForComparison(it.country);

    if (!raw && !normalized) return 6;

    if (
      raw.includes('mexico') ||
      raw.includes('méxico') ||
      raw === 'mx' ||
      raw === 'mex'
    ) return 1;

    if (normalized === 'united states') return 2;

    if (raw.includes('canada') || raw === 'ca') return 3;

    if (
      raw.includes('argentina') ||
      raw === 'ar'
    ) return 4;

    if (
      raw.includes('colombia') ||
      raw === 'co'
    ) return 5;

    return 6;
  };

  const sorted = [...items].sort((a, b) => {
    const pa = countryPriority(a);
    const pb = countryPriority(b);
    if (pa !== pb) return pa - pb;
    // tie-breaker suave por nombre para que no quede random
    const na = (a.name || a.full_name || a.public_identifier || '').toLowerCase();
    const nb = (b.name || b.full_name || b.public_identifier || '').toLowerCase();
    return na.localeCompare(nb);
  });

  // 👇 aquí usamos sorted en lugar de items
  for (const it of sorted){
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

    node.target = '_blank';
    node.rel = 'noopener';

    if (liHref) {
      node.href = liHref;
      node.title = 'Abrir perfil en LinkedIn';
      node.addEventListener('click', (e) => {
        // dejamos el comportamiento por defecto
      });
      } else {
    node.href = '#';
    node.title = 'Ver detalles (intentará abrir LinkedIn)';

    node.addEventListener('click', async (e) => {
      e.preventDefault();
      if (!eid) return;

      try {
        const det = await fetch(`${API_BASE}/ext/coresignal/collect`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ employee_id: eid })
        }).then(r => r.json());

        console.log('🧾 collect →', det);

        const dLi =
          det.linkedin_url || det.linkedin || det.linkedinUrl || null;
        const dPublic =
          det.public_identifier || det.publicIdentifier || null;
        const dProfile =
          det.profile_url || det.profileUrl || null;

        let finalUrl = null;

        if (dLi && /^https?:\/\//i.test(dLi)) {
          finalUrl = dLi;
        } else if (dProfile && /^https?:\/\//i.test(dProfile)) {
          finalUrl = dProfile;
        } else if (dPublic) {
          finalUrl = `https://www.linkedin.com/in/${encodeURIComponent(dPublic)}`;
        }

        if (finalUrl) {
          // 👇 solo abrimos UNA pestaña con el LinkedIn
          window.open(finalUrl, '_blank', 'noopener');
        } else {
          console.warn('No se encontró LinkedIn en preview ni en collect.');
        }
      } catch (err) {
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
// 👇 prioridad por país: 1) Mexico 2) United States 3) Canada 4) Argentina 5) Colombia 6) resto
const countryRank = (country) => {
  const c = (country || '').toString().toLowerCase();
  const normalized = normalizeCountryForComparison(country);

  if (c.includes('mexico') || c.includes('méxico')) return 1; // México primero
  if (normalized === 'united states') return 2;               // luego United States
  if (c.includes('canada')) return 3;                         // luego Canada
  if (c.includes('argentina')) return 4;                      // luego Argentina
  if (c.includes('colombia')) return 5;                       // luego Colombia
  return 6;                                                   // el resto
};

function applyExperienceFilterAndRender(){
  // Limpiamos las tarjetas
  cards.innerHTML = '';

  // Si no hay resultados cargados aún
  if (!_vinttiAll || !_vinttiAll.length){
    empty.classList.remove('hidden');
    return;
  }

  // 👇 empezamos con una copia para no mutar el array original
  let filtered = Array.isArray(_vinttiAll) ? [..._vinttiAll] : [];

  // 1) Filtro por años de experiencia (si hay valor en el dropdown)
  if (expFilter && expFilter.value !== '') {
    const minYears = parseInt(expFilter.value, 10);
    if (!Number.isNaN(minYears)) {
      filtered = filtered.filter(row => {
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

  // 2) 👇 Ordenar por país (México, Argentina, Colombia, resto) y luego por salario deseado
  const parseSalary = (val) => {
    if (!val) return Infinity; // sin salario → van al final
    const str = String(val).trim();
    const match = str.match(/\d+/); // primer número que aparezca
    if (!match) return Infinity;
    const num = parseInt(match[0], 10);
    return Number.isNaN(num) ? Infinity : num;
  };

  filtered.sort((a, b) => {
    const ra = countryRank(a.country);
    const rb = countryRank(b.country);

    // 1️⃣ primero por prioridad de país
    if (ra !== rb) return ra - rb;

    // 2️⃣ dentro del mismo país, por salario deseado (menor → mayor)
    const sa = parseSalary(a.salary_range);
    const sb = parseSalary(b.salary_range);
    if (sa !== sb) return sa - sb;

    // 3️⃣ tie-breaker: nombre (para que sea estable y bonito)
    const nameA = (a.name || '').toLowerCase();
    const nameB = (b.name || '').toLowerCase();
    return nameA.localeCompare(nameB);
  });

  empty.classList.add('hidden');

  // 3) Render de tarjetas (ya filtradas y ordenadas)
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

    const title = (parsed.title || '').trim();
    const tools = (parsed.tools || [])
      .map(s => String(s).toLowerCase().trim())
      .filter(Boolean);

    const location = (parsed.location || '').trim();
    const yearsFromParser = parsed.years_experience;

    console.groupCollapsed('🧰 Filtros normalizados para Vintti Talent');
    console.log('title →', title);
    console.log('tools →', tools);
    console.log('location →', location);
    console.log('years_experience →', yearsFromParser);
    console.groupEnd();

    console.groupCollapsed('🧰 Filtros normalizados para Vintti Talent');
    console.log('tools →', tools);
    console.log('location →', location);
    console.log('years_experience →', yearsFromParser);
    console.groupEnd();

    // 2) Buscar en Vintti Talent, pasando también la location
    console.groupCollapsed('📡 Fetch /search/candidates');
    const data = await searchCandidates(tools, { location, title });
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

    // 3) Coresignal: multi-búsqueda (México, Argentina, Colombia, LATAM)
    _csState = { lastParsed: parsed, page: 1, hasMore: false }; // desactivamos paginación preview
    csList.innerHTML = '';
    csEmpty.classList.add('hidden');
    csMore.classList.add('hidden'); // ocultamos "Cargar más" en este modo

    const totalCs = await coresignalMultiSearch(parsed);

    if (totalCs === 0){
      // si ninguna de las 4 búsquedas devolvió nada
      csEmpty.classList.remove('hidden');
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
