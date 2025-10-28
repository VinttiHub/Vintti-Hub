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
});
