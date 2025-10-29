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

async function searchCandidates(tools){
  const params = new URLSearchParams();
  if (tools && tools.length) params.set('tools', tools.join(','));
  const full = `${API_BASE}/search/candidates?`+params.toString();
  console.log('➡️ GET', full);
  const res = await fetch(full, { credentials:'include' });
  if (!res.ok) throw new Error('Search failed');
  const json = await res.json();
  // espejo mínimo para ver cuántos items vinieron
  console.log('📦 items:', (json.items||[]).length);
  return json;
}
async function coresignalSearch(parsed, page=1){
  const body = {
    title: parsed.title || "",
    skills: (parsed.tools || []).map(s => String(s).toLowerCase().trim()).filter(Boolean),
    location: parsed.location || "",          // si luego extraes lugar
    years_min: parsed.years_experience ?? null,
    page
  };
  const res = await fetch(`${API_BASE}/ext/coresignal/search`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    credentials:'include',
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error('Coresignal search failed');
  return await res.json();
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

    // Campos típicos de preview (dependerán del response; ajusta si cambia):
    const name  = it.name || it.full_name || it.public_identifier || 'Profile';
    const loc   = it.location || it.country || '—';
    const head  = it.headline || '';
    const eid   = it.employee_id || it.id;

    node.querySelector('.cs-card-name').textContent = name;
    node.querySelector('.cs-card-meta').textContent = loc;
    node.querySelector('.cs-card-notes').textContent = head || '—';
    // click: podrías abrir tu modal y llamar /collect
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
        // TODO: abre un modal lindo con info clave (linkedin, skills, exp…)
      }catch(err){ console.error('collect error', err); }
    });

    csList.appendChild(node);
  }
}

  function renderChips({ title, tools, years_experience }){
    chips.innerHTML = '';
    const items = [];
    if (title) items.push({label:title});
    (tools || []).forEach(t => items.push({label:t}));
    if (Number.isFinite(years_experience)) items.push({label:`${years_experience} yrs`});
    if (!items.length){ chips.classList.add('hidden'); return; }
    for (const it of items){
      const s = document.createElement('span');
      s.className = 'chip';
      s.textContent = it.label;
      chips.appendChild(s);
    }
    chips.classList.remove('hidden');
  }

  function renderCards(results){
    cards.innerHTML = '';
    if (!results?.length){
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    for (const row of results){
      const node = tpl.content.firstElementChild.cloneNode(true);
      node.href = `https://vinttihub.vintti.com/candidate-details.html?id=${encodeURIComponent(row.candidate_id)}`;
      node.querySelector('.card-name').textContent = row.name || '(sin nombre)';
      node.querySelector('.card-meta').textContent = row.country || '—';
      node.querySelector('.card-notes').textContent = (row.comments || '').trim() || 'No comments yet.';
      cards.appendChild(node);
    }
  }

async function doSearch(){
  const q = input.value.trim();
  if (!q){ input.focus(); return; }

  // —— DEBUG: entrada del usuario
  console.groupCollapsed('%cAI Candidate Search','color:#6b5b95;font-weight:bold');
  console.log('🔎 Query (usuario) →', q);

  btn.disabled = true; btn.textContent = 'Buscando…';
  try{
    // —— DEBUG: petición al parser
    console.groupCollapsed('🧠 Llamada a /ai/parse_candidate_query');
    const parsed = await parseQuery(q);
    console.log('↩️ Respuesta parser:', parsed);
    console.groupEnd();

    renderChips(parsed);

    const tools = (parsed.tools || []).map(s => String(s).toLowerCase().trim()).filter(Boolean);

    // —— DEBUG: tools normalizadas
    console.groupCollapsed('🧰 Tools normalizadas para buscar');
    console.log('tools →', tools);
    console.groupEnd();

    // —— DEBUG: request a /search/candidates
    const params = new URLSearchParams();
    if (tools.length) params.set('tools', tools.join(','));
    const url = `${API_BASE}/search/candidates?${params.toString()}`;
    console.groupCollapsed('📡 Fetch /search/candidates');
    console.log('URL →', url);

    const data = await searchCandidates(tools);
    console.log('↩️ Respuesta search:', data);
    console.groupEnd();
    renderCards(data.items || []);

    // —— Coresignal (preview)
    _csState = { lastParsed: parsed, page: 1, hasMore: true };
    csList.innerHTML = ''; csEmpty.classList.add('hidden');
    csMore.classList.add('hidden');

    const csRes = await coresignalSearch(parsed, 1);
    const csItems = (csRes?.data?.items) || [];
    renderCs(csItems, {append:false});

    // control de paginación de preview (1..5)
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

});
