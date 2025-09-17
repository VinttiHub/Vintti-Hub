let emailToChoices = null;
let emailCcChoices = null;
// === Emoji Picker boot + helpers ===
async function ensureEmojiPickerLoaded() {
  if (customElements.get('emoji-picker')) return;
  await new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.type = 'module';
    s.src = 'https://unpkg.com/emoji-picker-element@^1/dist/index.js';
    s.onload = resolve;
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

// Cierra pickers al hacer click fuera o con ESC
document.addEventListener('click', (e) => {
  document.querySelectorAll('.popup-emoji').forEach(p => {
    if (!p.closest('.emoji-anchor')?.contains(e.target)) p.style.display = 'none';
  });
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.popup-emoji').forEach(p => p.style.display = 'none');
  }
});

const CAREER_TOOLS = [
  { label: "Problem Solving",      value: "problem-solving" },
  { label: "Teamwork",             value: "teamwork" },
  { label: "Time Management",      value: "time-management" },
  { label: "Adaptability",         value: "adaptability" },
  { label: "Critical Thinking",    value: "critical-thinking" },
  { label: "Leadership",           value: "leadership" },
  { label: "Creativity",           value: "creativity" },
  { label: "Technical Skills",     value: "technical-skills" },
  { label: "Interpersonal Skills", value: "interpersonal-skills" },
  { label: "Communication Skills", value: "communication-skills" }
];

// Helpers de normalización
const _toKey = s => (s||'').toString().trim().toLowerCase().replace(/\s+/g,'-').replace(/[^a-z0-9-]/g,'');
const LABEL_BY_SLUG = CAREER_TOOLS.reduce((m,o)=> (m[o.value]=o.label, m), {});
const SLUG_BY_LABEL = CAREER_TOOLS.reduce((m,o)=> (m[_toKey(o.label)]=o.value, m), {});

// Convierte entrada diversa → slug del Sheet
function toToolSlug(v){
  if (!v) return '';
  const s = String(v).trim();
  const asIs = LABEL_BY_SLUG[s] ? s : null;              // ya es slug válido
  if (asIs) return s;
  // ¿vino con label bonito?
  const fromLabel = SLUG_BY_LABEL[_toKey(s)];
  if (fromLabel) return fromLabel;
  // ¿vino algo libre? lo “slugificamos” para no romper:
  return _toKey(s);
}

// Prefill tolerante: acepta ['Problem Solving','problem-solving', ...]
function normalizeToolsArray(arr){
  if (!arr) return [];
  const raw = Array.isArray(arr) ? arr : parseToolsValue(arr);
  const slugs = raw.map(toToolSlug).filter(Boolean);
  // quita duplicados conservando orden
  return [...new Set(slugs)];
}

// --- HTML cleaner para Webflow (mantiene: ul/ol/li/p/br/b/strong/i/em/a) ---
function cleanHtmlForWebflow(raw) {
  if (!raw) return '';
  let s = String(raw);

  // normaliza NBSP
  s = s.replace(/\u00A0|&nbsp;/g, ' ');

  // quita spans y sus estilos inline
  s = s.replace(/<\s*span[^>]*>/gi, '').replace(/<\s*\/\s*span\s*>/gi, '');

  // elimina TODOS los atributos style="..."
  s = s.replace(/\sstyle="[^"]*"/gi, '');

  // elimina atributos event-handler (onClick, onMouseOver, etc) por seguridad
  s = s.replace(/\son[a-z]+\s*=\s*"[^"]*"/gi, '');

  // permite solo tags whitelisted, removiendo otras etiquetas pero dejando su contenido
  // (whitelist simple: ul,ol,li,p,br,b,strong,i,em,a)
  s = s.replace(/<(?!\/?(ul|ol|li|p|br|b|strong|i|em|a)(\s|>|\/))/gi, '&lt;');

  // limpia anchors peligrosos (javascript:) y deja solo href seguros
  s = s.replace(/<a([^>]+)>/gi, (m, attrs) => {
    // extrae href
    const hrefMatch = attrs.match(/\shref="([^"]*)"/i);
    const href = hrefMatch ? hrefMatch[1] : '';
    if (!href || /^javascript:/i.test(href)) {
      return '<a>';
    }
    // elimina todo atributo que no sea href/target/rel
    const safeAttrs = [];
    const hrefAttr   = ` href="${href}"`;
    const targetAttr = /\starget="/i.test(attrs) ? attrs.match(/\starget="[^"]*"/i)[0] : ' target="_blank"';
    const relAttr    = /\srel="/i.test(attrs) ? attrs.match(/\srel="[^"]*"/i)[0] : ' rel="noopener"';
    safeAttrs.push(hrefAttr, targetAttr, relAttr);
    return `<a${safeAttrs.join('')}>`;
  });

  // colapsa espacios múltiples
  s = s.replace(/[ \t]{2,}/g, ' ').trim();

  // micro-limpiezas de listas (opcional)
  s = s.replace(/<li>\s+/g, '<li>').replace(/\s+<\/li>/g, '</li>');

  return s;
}

// Monta Choices en #career-tools SIN permitir crear valores nuevos
function mountToolsDropdown(selected = []) {
  const sel = document.getElementById('career-tools');
  if (!sel) return;

  // opciones (value = slug, texto = label)
  sel.innerHTML = CAREER_TOOLS.map(o => `<option value="${o.value}">${o.label}</option>`).join('');

  if (window.toolsChoices) {
    try { window.toolsChoices.destroy(); } catch {}
  }

  window.toolsChoices = new Choices(sel, {
    removeItemButton: true,
    shouldSort: false,
    searchEnabled: true,
    allowHTML: true,
    duplicateItemsAllowed: false
  });

  // preselección (normaliza a slugs)
  normalizeToolsArray(selected).forEach(slug => {
    try { window.toolsChoices.setChoiceByValue(slug); } catch {}
  });

  // autosave siempre en SLUGS
  sel.addEventListener('change', () => {
    const slugs = window.toolsChoices.getValue(true); // ya son slugs (values del <option>)
    saveCareerField('career_tools', slugs);
  }, { signal: (window.__publishCareerAC || {}).signal });
}


async function refreshOpportunityData() {
  const oppId = getOpportunityId();
  if (!oppId) return null;
  try {
    const res = await fetch(`${API_BASE}/opportunities/${oppId}`, { cache: 'no-store' });
    const fresh = await res.json();
    window.currentOpportunityData = fresh || {};
    return fresh;
  } catch (e) {
    console.warn('⚠️ Could not refresh opportunity data before opening popup', e);
    return window.currentOpportunityData || {};
  }
}

function getOpportunityId() {
  const el = document.getElementById('opportunity-id-text');
  const fromDataset = (el?.getAttribute('data-id') || '').trim();
  if (fromDataset && fromDataset !== '—') return fromDataset;

  const fromQS = new URLSearchParams(location.search).get('id');
  if (fromQS) return fromQS;

  const fromText = (el?.textContent || '').trim();
  if (fromText && fromText !== '—') return fromText;

  return '';
}

window.hireCandidateId = null;
function stripHtmlToText(html) {
  if (!html) return '';
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  const text = tmp.textContent || tmp.innerText || '';
  return text.replace(/\s+/g, ' ').trim();
}

function parseToolsValue(val) {
  if (!val) return [];
  if (Array.isArray(val)) return val.filter(Boolean).map(String);

  if (typeof val === 'string') {
    let s = val.trim();

    // Caso JSON: '["book","node"]'
    if (s.startsWith('[')) {
      try {
        const arr = JSON.parse(s);
        return Array.isArray(arr) ? arr.filter(Boolean).map(v => String(v).trim()) : [];
      } catch { /* fall through */ }
    }

    // Caso Postgres text[]: '{book,"react,js",node}'
    if (s.startsWith('{') && s.endsWith('}')) s = s.slice(1, -1);

    // Split simple por comas + quitar comillas externas
    return s
      .split(',')
      .map(t => t.replace(/^"(.*)"$/,'$1').replace(/\\"/g, '"').trim())
      .filter(Boolean);
  }

  return [];
}

function toggleActiveButton(command, button) {
  document.execCommand(command, false, '');
  button.classList.toggle('active');
}
// --- SPEED UPS: caché + prewarm de candidatos para búsquedas instantáneas ---
const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
const CAND_CACHE_TTL = 5 * 60 * 1000; // 5 min

let __cands = { data: [], idx: [], ts: 0 };
let __candsInFlight = null;

const quickDebounce = (fn, ms = 120) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
const norm = s => (s || '').toLowerCase().normalize('NFD').replace(/\p{Diacritic}/gu, '');
// ===== AUTOSAVE infra para Career fields =====
const AUTOSAVE_MS = 350; // debounce
const _autosaveAbort = new Map(); // por-campo -> AbortController

const saveCareerField = quickDebounce(async (field, value) => {
  const oppId = getOpportunityId();
  if (!oppId) return;

  // Cancela petición previa del mismo campo
  try { _autosaveAbort.get(field)?.abort(); } catch {}
  const ac = new AbortController();
  _autosaveAbort.set(field, ac);

  const payload = { [field]: value };
  try {
    const res = await fetch(`${API_BASE}/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: ac.signal
    });
    if (!res.ok) {
      const t = await res.text();
      console.warn(`❌ Autosave ${field} failed:`, t);
      showTinyToast('⚠️ error saving');
      return;
    }
    // keep local cache fresh
    window.currentOpportunityData = window.currentOpportunityData || {};
    window.currentOpportunityData[field] = value;
    showTinyToast('✅ saved');
  } catch (err) {
    if (err.name !== 'AbortError') {
      console.error(`❌ Autosave ${field}:`, err);
      showTinyToast('⚠️ network error');
    }
  }
}, AUTOSAVE_MS);
// 💾 Guardado inmediato (sin debounce) de múltiples campos career_*
async function saveCareerFieldsNow(patchObj) {
  const oppId = getOpportunityId();
  if (!oppId) throw new Error('Invalid Opportunity ID');

  const res = await fetch(`${API_BASE}/opportunities/${oppId}/fields`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patchObj)
  });
  if (!res.ok) {
    const t = await res.text();
    throw new Error(t || 'Failed to save career fields');
  }

  // Mantén el cache local coherente
  window.currentOpportunityData = Object.assign({}, window.currentOpportunityData || {}, patchObj);
}

// Mini toast sutil (esquina inferior)
function showTinyToast(msg){
  const el = document.createElement('div');
  el.textContent = msg;
  el.style.cssText = `
    position: fixed; left: 16px; bottom: 16px; z-index: 99999;
    background: #f6e9ff; color:#6b21a8; border:1px solid #e9d5ff;
    padding:8px 12px; border-radius:14px; font:600 12px/1.1 Inter, sans-serif;
    box-shadow:0 4px 12px rgba(0,0,0,.08); opacity:.98; transform: translateY(0);
    transition: all .25s ease;
  `;
  document.body.appendChild(el);
  setTimeout(()=>{ el.style.opacity=.0; el.style.transform='translateY(6px)'; setTimeout(()=>el.remove(), 220); }, 900);
}

function buildIndex(list) {
  return list.map(c => ({ ...c, _haystack: norm(`${c.name} ${c.linkedin} ${c.phone}`) }));
}

async function fetchAllCandidates() {
  const r = await fetch(`${API_BASE}/candidates`, { cache: 'no-store' });
  const data = await r.json();
  __cands = { data, idx: buildIndex(data), ts: Date.now() };
  try { localStorage.setItem('all_candidates_cache', JSON.stringify({ ts: __cands.ts, data })); } catch {}
  return __cands;
}

async function getCandidatesCached() {
  const fresh = (Date.now() - __cands.ts) < CAND_CACHE_TTL && __cands.idx.length;
  if (fresh) return __cands;
  if (__candsInFlight) return __candsInFlight; // ya hay una petición andando

  // Warm start desde localStorage si existe
  if (!__cands.data.length) {
    try {
      const raw = localStorage.getItem('all_candidates_cache');
      if (raw) {
        const parsed = JSON.parse(raw);
        __cands = { data: parsed.data || [], idx: buildIndex(parsed.data || []), ts: parsed.ts || 0 };
      }
    } catch {}
  }
  __candsInFlight = fetchAllCandidates().finally(() => { __candsInFlight = null; });
  return __candsInFlight;
}

// 🔥 Precalienta en cuanto carga la página (mitiga cold start del backend)
document.addEventListener('DOMContentLoaded', () => { getCandidatesCached(); });

document.addEventListener('DOMContentLoaded', () => {
  // 🔹 Mostrar popup para elegir acción
document.getElementById('createCandidateBtn').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.remove('hidden');
});
document.getElementById('closeSignOffPopup').addEventListener('click', () => {
  document.getElementById('signOffPopup').classList.add('hidden');
});

// 🔹 Cerrar popup de elección
document.getElementById('closeChoosePopup').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');
});

document.getElementById('openNewCandidatePopup').addEventListener('click', () => {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');

  // Mostrar campos
  document.getElementById('extra-fields').style.display = 'block';
  document.getElementById('popupcreateCandidateBtn').style.display = 'block';
  document.getElementById('popupAddExistingBtn').style.display = 'none';
  const nameWarning = document.getElementById('name-warning');
  if (nameWarning) {
    nameWarning.style.display = 'none'; // o 'block' si es el otro caso
  }
  document.getElementById('name-warning').style.display = 'none';
  document.getElementById('pipelineCandidateSearchResults').innerHTML = '';

  // Campo de nombre como input normal (sin buscador)
  const input = document.getElementById('candidate-name');
  input.value = '';
  input.placeholder = 'Full name';
  input.removeAttribute('data-candidate-id');

  // ⚠️ Eliminar cualquier buscador anterior
  const newInput = input.cloneNode(true);
  input.parentNode.replaceChild(newInput, input);
});
function openPreCreateModal() {
  document.getElementById('chooseCandidateActionPopup').classList.add('hidden');
  document.getElementById('preCreateCheckPopup').classList.remove('hidden');

  const input = document.getElementById('precreate-search');
  const results = document.getElementById('precreate-results');
  const foundMsg = document.getElementById('precreate-found-msg');
  const noMatch = document.getElementById('precreate-no-match');

  input.value = '';
  results.innerHTML = '';
  foundMsg.style.display = 'none';
  noMatch.style.display = 'none';

  // Un (1) único listener siempre, sin duplicados en reaperturas
  input.oninput = quickDebounce(async () => {
    const termRaw = input.value.trim();
    const term = norm(termRaw);
    results.innerHTML = '';
    foundMsg.style.display = 'none';
    noMatch.style.display = 'none';
    if (!term || term.length < 2) return;

    const tokens = term.split(/\s+/).filter(Boolean);
    const { idx } = await getCandidatesCached();

    // filtro ultra rápido + top 50 para no saturar el DOM
    const matches = [];
    for (const c of idx) {
      if (tokens.every(t => c._haystack.includes(t))) {
        matches.push(c);
        if (matches.length >= 50) break;
      }
    }

    if (!matches.length && term.length >= 3) {
      noMatch.style.display = 'block';
      return;
    }

    foundMsg.style.display = 'block';
    for (const c of matches) {
      const li = document.createElement('li');
      li.className = 'search-result-item';
      li.dataset.candidateId = c.candidate_id;
      li.innerHTML = `
        <div style="font-weight:600;">${c.name || '(no name)'}</div>
        <div style="font-size:12px;color:#666;">🔍 Match</div>
      `;
      li.addEventListener('click', async () => {
        const opportunityId = getOpportunityId();
        if (!opportunityId || !c.candidate_id) return alert('❌ Invalid candidate or opportunity');

        await fetch(`${API_BASE}/opportunities/${opportunityId}/candidates`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ candidate_id: c.candidate_id })
        });

        const tpl = document.getElementById('candidate-card-template');
        const frag = tpl.content.cloneNode(true);
        frag.querySelectorAll('.candidate-name').forEach(el => el.textContent = c.name);
        frag.querySelector('.candidate-email').textContent = c.email || '';
        frag.querySelector('.candidate-img').src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;
        frag.querySelector('.candidate-status-dropdown')?.remove();
        document.querySelector('#contacted').appendChild(frag);

        document.getElementById('preCreateCheckPopup').classList.add('hidden');
        showFriendlyPopup(`✅ ${c.name} added to pipeline`);
        loadPipelineCandidates?.();
      });
      results.appendChild(li);
    }
  }, 120);
}

document.getElementById('openNewCandidatePopup').addEventListener('click', openPreCreateModal);


document.getElementById('goToCreateCandidateBtn').addEventListener('click', () => {
  document.getElementById('preCreateCheckPopup').classList.add('hidden');
  document.getElementById('candidatePopup').classList.remove('hidden');

  document.getElementById('extra-fields').style.display = 'block';
  document.getElementById('popupcreateCandidateBtn').style.display = 'block';
  document.getElementById('popupAddExistingBtn').style.display = 'none';

  const input = document.getElementById('candidate-name');
  const precreateValue = document.getElementById('precreate-search').value;

  input.value = precreateValue || ''; // copiar el valor buscado si existe
  input.placeholder = 'Full name';
  input.removeAttribute('data-candidate-id');
});
document.getElementById('closePreCreatePopup').addEventListener('click', () => {
  document.getElementById('preCreateCheckPopup').classList.add('hidden');
});

// 🔹 Agregar candidato existente al pipeline
document.getElementById('popupAddExistingBtn').addEventListener('click', async () => {
  const input = document.getElementById('candidate-name');
  const candidateId = input.getAttribute('data-candidate-id');
  const name = input.value;
  const opportunityId = getOpportunityId();
  if (!candidateId || !opportunityId) return alert('❌ Select a candidate first');

  // Crear en tabla intermedia
  await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ candidate_id: candidateId })
  });

  // Mostrar tarjeta en el pipeline
  const cardTemplate = document.getElementById('candidate-card-template');
  const newCard = cardTemplate.content.cloneNode(true);
  newCard.querySelectorAll('.candidate-name').forEach(el => el.textContent = name);
  newCard.querySelector('.candidate-email').textContent = ''; // puedes mejorar esto si tienes el email
  newCard.querySelector('.candidate-img').src = `https://randomuser.me/api/portraits/lego/${candidateId % 10}.jpg`;
  newCard.querySelector('.candidate-status-dropdown')?.remove();
  document.querySelector('#contacted').appendChild(newCard); // agregar a columna inicial

  document.getElementById('candidatePopup').classList.add('hidden');
});
  const tabs = document.querySelectorAll('.nav-item');
  const sections = document.querySelectorAll('.detail-section');
  const indicator = document.querySelector('.nav-indicator');

  function activateTab(index) {
    tabs.forEach((t, i) => {
      t.classList.toggle('active', i === index);
      sections[i].classList.toggle('hidden', i !== index);
    });

    const tab = tabs[index];
    indicator.style.left = `${tab.offsetLeft}px`;
    indicator.style.width = `${tab.offsetWidth}px`;
  }

    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => {
        activateTab(index);

        // Si la pestaña es "Pipeline", cargar los candidatos
        if (tab.textContent.trim() === 'Pipeline') {
          loadPipelineCandidates();
        }
      });
    });

  activateTab(0);

  // ✅ Card toggle
  document.querySelectorAll('.card-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const card = btn.closest('.overview-card');
      card.classList.toggle('open');
    });
  });

  // ✅ Copy button
  document.querySelectorAll('.copy-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const id = btn.parentElement.querySelector('span').innerText;
      navigator.clipboard.writeText(id).then(() => {
        btn.title = "Copied!";
        setTimeout(() => btn.title = "Copy to clipboard", 2000);
      });
    });
  });

  // ✅ Cargar datos reales de la oportunidad
  loadOpportunityData();
  console.log('🔎 hireCandidateId after load:', window.hireCandidateId);

  document.querySelector('.job-header-right .header-btn').addEventListener('click', async () => {
  document.getElementById('emailPopup').classList.remove('hidden');

  const jobDesc = document.getElementById('job-description-textarea').innerText || '—';
  const clientName = document.getElementById('client-name-input').value || '—';
  const positionName = document.getElementById('details-opportunity-name').value || '—';

  // 📩 Mensaje
  const message = `Hi<br><br>Job description ready, please review:<br><br>${jobDesc}`;
  document.getElementById('email-message').innerHTML = message;

  // 📝 Asunto
  const subject = `${clientName} - ${positionName} - Job Description`;
  document.getElementById('email-subject').value = subject;


  const toSelect = document.getElementById('email-to');
  const ccSelect = document.getElementById('email-cc');
  toSelect.innerHTML = '';
  ccSelect.innerHTML = '';

  const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users');
  const users = await res.json();

  users.forEach(user => {
    const optionTo = document.createElement('option');
    optionTo.value = user.email_vintti;
    optionTo.textContent = user.user_name;
    toSelect.appendChild(optionTo);

    const optionCc = optionTo.cloneNode(true);
    ccSelect.appendChild(optionCc);
  });

if (emailToChoices) emailToChoices.destroy();
if (emailCcChoices) emailCcChoices.destroy();

emailToChoices = new Choices(toSelect, {
  removeItemButton: true,
  placeholder: true,
  shouldSort: false
});
emailCcChoices = new Choices(ccSelect, {
  removeItemButton: true,
  placeholder: true,
  shouldSort: false
});

// 🔹 Forzar clase visual compacta para que no colapse
document.querySelectorAll('.choices').forEach(el => {
  el.classList.add('compact-choices');
});


});

document.getElementById('closeEmailPopup').addEventListener('click', () => {
  document.getElementById('emailPopup').classList.add('hidden');
  
  // Limpiar campos del formulario
  if (emailToChoices) emailToChoices.clearStore();
  if (emailCcChoices) emailCcChoices.clearStore();
  document.getElementById('email-subject').value = '';
  document.getElementById('email-message').value = '';
});

const overlay = document.getElementById('email-overlay');
const overlayText = document.getElementById('email-overlay-message');

document.getElementById('sendEmailBtn').addEventListener('click', async () => {
  const btn = document.getElementById('sendEmailBtn');
  const toChoices = emailToChoices.getValue().map(o => o.value);
  const ccChoices = emailCcChoices.getValue().map(o => o.value);
  const subject = document.getElementById('email-subject').value;
  const message = document.getElementById('email-message').innerHTML;

  if (!toChoices.length || !subject || !message) {
    alert("❌ Fill in all required fields (To, Subject, Message)");
    return;
  }


  btn.disabled = true;
  overlayText.textContent = "Sending email...";
  overlay.classList.remove('hidden');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ to: toChoices, cc: ccChoices, subject, body: message })
    });

    const result = await res.json();
    if (res.ok) {
      overlayText.textContent = "✅ Email sent successfully";
      setTimeout(() => {
        overlay.classList.add('hidden');
        document.getElementById('emailPopup').classList.add('hidden');
        
        // Limpiar campos del formulario
        if (emailToChoices) emailToChoices.clearStore();
        if (emailCcChoices) emailCcChoices.clearStore();
        document.getElementById('email-subject').value = '';
        document.getElementById('email-message').value = '';

        btn.disabled = false;
      }, 2000);
    } else {
      overlay.classList.add('hidden');
      alert("❌ Error sending email: " + (result.error || 'Unknown error'));
      btn.disabled = false;
    }
  } catch (err) {
    overlay.classList.add('hidden');
    console.error("❌ Error:", err);
    alert("❌ Failed to send email");
    btn.disabled = false;
  }
});


document.getElementById('comments-overview-textarea').addEventListener('blur', async (e) => {
  await updateOpportunityField('comments', e.target.value);
});
document.getElementById('interviewing-process-editor').addEventListener('blur', e => {
  updateOpportunityField('client_interviewing_process', e.target.innerHTML);
});

document.getElementById('start-date-input').addEventListener('blur', async (e) => {
  await updateOpportunityField('nda_signature_or_start_date', e.target.value);
});
document.getElementById('job-description-textarea').addEventListener('blur', e =>
  updateOpportunityField('hr_job_description', e.target.innerHTML));

document.getElementById('close-date-input').addEventListener('blur', async (e) => {
  await updateOpportunityField('opp_close_date', e.target.value);
});

// CLIENT
document.getElementById('client-name-input').addEventListener('blur', async (e) => {
  await updateAccountField('client_name', e.target.value);
});

document.getElementById('client-size-input').addEventListener('blur', async (e) => {
  await updateAccountField('size', e.target.value);
});

document.getElementById('client-state-input').addEventListener('blur', async (e) => {
  await updateAccountField('state', e.target.value);
});

document.getElementById('client-linkedin-input').addEventListener('blur', async (e) => {
  await updateAccountField('linkedin', e.target.value);
});

document.getElementById('client-website-input').addEventListener('blur', async (e) => {
  await updateAccountField('website', e.target.value);
});

document.getElementById('client-mail-input').addEventListener('blur', async (e) => {
  await updateAccountField('mail', e.target.value);
});

document.getElementById('client-about-textarea').addEventListener('blur', async (e) => {
  await updateAccountField('comments', e.target.value);
});

// DETAILS
document.getElementById('details-opportunity-name').addEventListener('blur', async (e) => {
  await updateOpportunityField('opp_position_name', e.target.value);
});
document.getElementById('min-budget-input').addEventListener('blur', e =>
  updateOpportunityField('min_budget', e.target.value));

document.getElementById('max-budget-input').addEventListener('blur', e =>
  updateOpportunityField('max_budget', e.target.value));

document.getElementById('min-salary-input').addEventListener('blur', e =>
  updateOpportunityField('min_salary', e.target.value));

document.getElementById('max-salary-input').addEventListener('blur', e =>
  updateOpportunityField('max_salary', e.target.value));

document.getElementById('model-select').addEventListener('change', e =>
  updateOpportunityField('opp_model', e.target.value));

document.getElementById('years-experience-input').addEventListener('blur', e =>
  updateOpportunityField('years_experience', e.target.value));

document.getElementById('fee-input').addEventListener('blur', e =>
  updateOpportunityField('fee', e.target.value));

document.getElementById('comments-firstmeeting-textarea').addEventListener('blur', e =>
  updateOpportunityField('opp_comments', e.target.value));

document.getElementById('recording-input').addEventListener('blur', e =>
  updateOpportunityField('first_meeting_recording', e.target.value));
document.getElementById('deepdive-recording-input').addEventListener('blur', e =>
  updateOpportunityField('deepdive_recording', e.target.value));

document.getElementById('timezone-input').addEventListener('blur', e =>
  updateAccountField('timezone', e.target.value));

document.getElementById('details-sales-lead').addEventListener('change', async (e) => {
  const emailValue = e.target.value; // el value es el email
  console.log('🟡 Sales Lead changed:', emailValue);

  await updateOpportunityField('opp_sales_lead', emailValue);
});

document.getElementById('details-hr-lead').addEventListener('change', async (e) => {
  const emailValue = e.target.value;
  console.log('🟡 HR Lead changed:', emailValue);

  await updateOpportunityField('opp_hr_lead', emailValue);

  // ✅ Si se asigna, eliminar la alerta si existe
  const alertBox = document.getElementById('hr-alert');
  if (alertBox) alertBox.remove();
});


document.getElementById('details-model').addEventListener('change', async (e) => {
  await updateOpportunityField('opp_model', e.target.value);
});
// AI Assistant logic
const aiBtn = document.getElementById('ai-assistant-btn');
const aiPopup = document.getElementById('ai-assistant-popup');
const aiClose = document.getElementById('ai-assistant-close');
const aiGo = document.getElementById('ai-assistant-go');

// Mostrar solo en pestaña "Job Description"
function showAIAssistantButton(tabName) {
  if (tabName === 'Job Description') {
    aiBtn.style.display = 'block';
  } else {
    aiBtn.style.display = 'none';
  }
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => {
    activateTab(index);

    const tabName = tab.textContent.trim();
    showAIAssistantButton(tabName);

    if (tabName === 'Pipeline') loadPipelineCandidates();
if (tabName === 'Candidates') {
  const opportunityId = getOpportunityId();
  if (opportunityId && opportunityId !== '—') {
    loadBatchesForOpportunity(opportunityId);
    loadPresentationTable(opportunityId);
  } else {
    console.error('Opportunity ID is invalid:', opportunityId);
  }
}
  });
});

// Botón abre popup
aiBtn.addEventListener('click', () => {
  aiPopup.classList.remove('hidden');
});

// Botón Close
aiClose.addEventListener('click', () => {
  aiPopup.classList.add('hidden');
});

aiGo.addEventListener('click', async () => {
  const intro = document.querySelector('#ai-assistant-popup textarea[placeholder="00:00 Speaker: Text here..."]').value;
  const deepDive = document.querySelector('#ai-assistant-popup input[placeholder="2nd_Call_Transcript"]').value;
  const notes = document.querySelector('#ai-assistant-popup textarea[placeholder="Your notes here..."]').value;

  console.log("📤 Enviando a AI Assistant:", { intro, deepDive, notes });

  if (!intro && !deepDive && !notes) {
    alert("❌ Please fill at least one field");
    return;
  }

  aiGo.textContent = '⏳ Generating...';
  aiGo.disabled = true;

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/ai/generate_jd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ intro, deepDive, notes })
    });

    const data = await res.json();
    console.log("📥 Respuesta de AI Assistant:", data);

    if (data.job_description) {
      const jd = data.job_description;

      // Mostrar y guardar en textarea
      document.getElementById('job-description-textarea').innerHTML = jd;

      // Guardar en la base de datos
      await updateOpportunityField('hr_job_description', jd);
      console.log("✅ Job description saved in DB");

      alert("✅ Job description generated!");
    } else {
      alert("⚠️ Unexpected response from AI");
    }
  } catch (err) {
    console.error("❌ AI Assistant error:", err);
    alert("❌ Error generating job description");
  } finally {
    aiGo.textContent = "Let's Go 🚀";
    aiGo.disabled = false;
    aiPopup.classList.add('hidden');
  }
});

    // Cerrar popup
    document.getElementById("closeBatchPopup").addEventListener("click", () => {
      document.getElementById("batchCandidatePopup").classList.add("hidden");
    });
    // Cargar batches si estamos ya en la pestaña "Candidates"
    const activeTab = document.querySelector(".nav-item.active");
    if (activeTab && activeTab.textContent.trim() === "Candidates") {
      const opportunityId = getOpportunityId();
      if (opportunityId && opportunityId !== '—') {
        loadBatchesForOpportunity(opportunityId);
      }
    }

    document.getElementById('signOffBtn').addEventListener('click', async () => {
  const opportunityId = getOpportunityId();
  if (!opportunityId) return;

  document.getElementById('signOffPopup').classList.remove('hidden');

  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`);
  const candidates = await res.json();

  const select = document.getElementById('signoff-to');
  select.innerHTML = '';
  candidates.forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.email;
    opt.textContent = c.name;
    select.appendChild(opt);
  });

  if (window.signoffChoices) window.signoffChoices.destroy();
  window.signoffChoices = new Choices(select, { removeItemButton: true });
});
let isSpanish = false;
document.getElementById('toggleLangBtn').addEventListener('click', () => {
  const subject = document.getElementById('signoff-subject');
  const message = document.getElementById('signoff-message');

  if (!isSpanish) {
    subject.value = 'Actualización sobre tu aplicación';
    message.value = `Querido candidato,\n\nGracias por haber participado en nuestro proceso en Vintti. Tras una cuidadosa evaluación, hemos decidido continuar con otro candidato.\n\n¡Apreciamos mucho tu tiempo e interés!\nSi deseas compartir tu experiencia con el proceso de selección, aquí hay una encuesta anónima muy corta (menos de 3 minutos):\n🔗 https://tally.so/r/w7K859\n\n¡Te deseamos lo mejor en tu camino! ✨\nCon cariño,\nel equipo de Vintti`;
  } else {
    subject.value = 'Update on your application';
    message.value = `Dear applicant,\n\nThank you so much for being part of our process at Vintti. After careful consideration, we’ve decided to move forward with another candidate.\n\nWe truly appreciate your time and interest!\nIf you'd like to share your experience with the selection process, here’s a short anonymous survey (under 3 minutes):\n🔗 https://tally.so/r/w7K859\n\nWishing you all the best in your journey! ✨\nWarmly,\nthe Vintti team`;
  }
  isSpanish = !isSpanish;
});
document.getElementById('sendSignOffBtn').addEventListener('click', async () => {
  const to = signoffChoices.getValue().map(o => o.value);
  const subject = document.getElementById('signoff-subject').value;
  const body = document.getElementById('signoff-message').value;

  if (!to.length || !subject || !body) {
    alert("❌ Fill in all fields");
    return;
  }

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to, subject, body })
    });

    if (res.ok) {
      alert("✅ Email sent successfully");
      document.getElementById('signOffPopup').classList.add('hidden');
    } else {
      const err = await res.json();
      alert("❌ Error: " + err.detail || err.error);
    }
  } catch (err) {
    console.error(err);
    alert("❌ Failed to send email");
  }
});
document.getElementById('closeApprovalEmailPopup').addEventListener('click', () => {
  document.getElementById('approvalEmailPopup').classList.add('hidden');
});

document.getElementById('sendApprovalEmailBtn').addEventListener('click', async () => {
  const to = approvalToChoices.getValue().map(o => o.value);
  const cc = approvalCcChoices.getValue().map(o => o.value);
  const subject = document.getElementById('approval-subject').value;
  const body = document.getElementById('approval-message').innerHTML;

  if (!to.length || !subject || !body) {
    alert('❌ Please fill all required fields');
    return;
  }

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to, cc, subject, body })
    });

    if (res.ok) {
      alert('✅ Email sent!');
      document.getElementById('approvalEmailPopup').classList.add('hidden');
    } else {
      alert('❌ Error sending email');
    }
  } catch (err) {
    alert('❌ Failed to send email');
  }
});
async function loadPresentationTable(opportunityId) {
  const tableBody = document.getElementById("presentation-batch-table-body");
  if (!tableBody) return;
  tableBody.innerHTML = '';

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const batches = await res.json();

    batches
      .filter(b => b.presentation_date)
      .forEach(batch => {
        const tr = document.createElement("tr");

        // Batch #
        const tdBatch = document.createElement("td");
        tdBatch.className = "col-narrow";
        tdBatch.textContent = `#${batch.batch_number}`;

        // Presentation Date
        const tdDate = document.createElement("td");
        const inputDate = document.createElement("input");
        inputDate.type = "date";
        inputDate.value = formatDate(batch.presentation_date); // usa tu helper
        inputDate.addEventListener("blur", async () => {
          const updated = { presentation_date: inputDate.value || null };
          await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batch.batch_id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updated)
          });
          // recalcula días tras editar
          const daysCell = tr.querySelector('td.time-col');
          daysCell.textContent = calcDaysSince(inputDate.value);
        });
        tdDate.appendChild(inputDate);

        // Time (days)
        const tdTime = document.createElement("td");
        tdTime.className = "time-col";
        tdTime.textContent = calcDaysSince(batch.presentation_date);

        tr.appendChild(tdBatch);
        tr.appendChild(tdDate);
        tr.appendChild(tdTime);
        tableBody.appendChild(tr);
      });

  } catch (err) {
    console.error("❌ Error loading batches for presentation table:", err);
  }

  function calcDaysSince(iso) {
    if (!iso) return '—';
    const now = new Date();                   // 👈 FIX: “hoy” dentro de la función
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '—';
    const diffMs = now.getTime() - d.getTime();
    const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    return Number.isFinite(days) ? String(days) : '—';
  }
}



// Marcar activo si el estilo está aplicado al soltar selección
document.getElementById('job-description-textarea').addEventListener('mouseup', () => {
  document.querySelectorAll('.toolbar button').forEach(btn => {
    const command = btn.getAttribute('data-command');
    if (!command) return;

    const isActive = document.queryCommandState(command);
    btn.classList.toggle('active', isActive);
  });
});

const picker = document.getElementById('emoji-picker');
const trigger = document.getElementById('emoji-trigger');
const editor = document.getElementById('job-description-textarea');

trigger.addEventListener('click', () => {
  picker.style.display = picker.style.display === 'block' ? 'none' : 'block';
});

picker.addEventListener('emoji-click', event => {
  const emoji = event.detail.unicode; 
  editor.focus();
  document.execCommand('insertText', false, emoji);
  picker.style.display = 'none';
});
// Botón de Go Back
const goBackButton = document.getElementById('goBackButton');
if (goBackButton) {
  goBackButton.addEventListener('click', (e) => {
    e.preventDefault();

    // 1) permite pasar la URL de retorno por querystring: ?from=/opportunities.html
    const fromParam = new URLSearchParams(location.search).get('from');
    if (fromParam) {
      location.assign(fromParam);
      return;
    }

    // 2) referrer (sirve aunque se haya abierto en otra pestaña)
    if (document.referrer) {
      location.assign(document.referrer);
      return;
    }

    // 3) última URL conocida de la tabla (si la guardas en sessionStorage)
    const lastOpps = sessionStorage.getItem('last_opps_url');
    if (lastOpps) {
      location.assign(lastOpps);
      return;
    }

    // 4) fallback fijo (ajústalo si tu ruta es distinta)
    const fallback = goBackButton.dataset.fallback || '/opportunities.html';
    location.assign(fallback);
  });
}
// 🔗 Redirección robusta al perfil del hire
document.addEventListener('click', (e) => {
  const el = e.target.closest('#hire-display');
  if (!el) return;

  const id = (window.hireCandidateId || el.dataset.candidateId || el.getAttribute('data-candidate-id') || '').trim();

  if (!id) {
    alert('❌ No hired candidate linked yet');
    return;
  }
  window.location.href = `/candidate-details.html?id=${encodeURIComponent(id)}`;
});
// ====== Career publish – setup ======
let countryChoices = null;
let cityChoices = null;
let toolsChoices = null;

// Lista de países de LATAM (inglés corto)
const LATAM_COUNTRIES = [
  "Latin America", 
  "Argentina","Bolivia","Brazil","Chile","Colombia","Costa Rica","Cuba","Ecuador",
  "El Salvador","Guatemala","Honduras","Mexico","Nicaragua","Panama","Paraguay",
  "Peru","Puerto Rico","Dominican Republic","Uruguay","Venezuela"
];


// Ciudades por país (principales) — puedes ampliar cuando quieras
const CITIES_BY_COUNTRY = {
  "Argentina": ["Buenos Aires","Córdoba","Rosario","Mendoza","La Plata"],
  "Bolivia": ["La Paz","Santa Cruz de la Sierra","Cochabamba"],
  "Brazil": ["São Paulo","Rio de Janeiro","Belo Horizonte","Brasília","Curitiba","Porto Alegre","Recife","Salvador"],
  "Chile": ["Santiago","Valparaíso","Viña del Mar","Concepción"],
  "Colombia": ["Bogotá","Medellín","Cali","Barranquilla","Bucaramanga","Cartagena"],
  "Costa Rica": ["San José","Alajuela","Heredia","Cartago"],
  "Cuba": ["La Habana","Santiago de Cuba","Camagüey"],
  "Ecuador": ["Quito","Guayaquil","Cuenca"],
  "El Salvador": ["San Salvador","Santa Ana","San Miguel"],
  "Guatemala": ["Guatemala City","Quetzaltenango","Mixco"],
  "Honduras": ["Tegucigalpa","San Pedro Sula","La Ceiba"],
  "Mexico": ["Mexico City","Guadalajara","Monterrey","Puebla","Querétaro","Tijuana"],
  "Nicaragua": ["Managua","León","Masaya"],
  "Panama": ["Panama City","Colón","David"],
  "Paraguay": ["Asunción","Ciudad del Este","Encarnación"],
  "Peru": ["Lima","Arequipa","Trujillo"],
  "Puerto Rico": ["San Juan","Ponce","Mayagüez"],
  "Dominican Republic": ["Santo Domingo","Santiago de los Caballeros","La Romana"],
  "Uruguay": ["Montevideo","Punta del Este","Salto"],
  "Venezuela": ["Caracas","Maracaibo","Valencia","Barquisimeto"]
};

async function openPublishCareerPopup() {
  const pop = document.getElementById('publishCareerPopup');
  pop.classList.remove('hidden');

  // 🔄 Trae datos frescos del server
  const data = await refreshOpportunityData();

  // ✅ Toma referencias ANTES de usarlas
  const countryEl = document.getElementById('career-country');
  const cityEl    = document.getElementById('career-city');
  if (!countryEl || !cityEl) {
    console.error('❌ career-country or career-city not found in DOM');
    return;
  }

  // Prefills desde la página / DB
  const oppId    = getOpportunityId();
  const jobTitle = document.getElementById('details-opportunity-name').value || '';

  const desc = data.career_description || data.hr_job_description || '';
  const reqs = data.career_requirements || '';
  const addi = data.career_additional_info || '';

  const savedCountry = data.career_country || '';
  const savedCity    = data.career_city || '';
  const savedTools   = parseToolsValue(data.career_tools);
// --- Helpers de selección tolerante ---
const _normKey = s => (s || '')
  .toString()
  .toLowerCase()
  .normalize('NFD')
  .replace(/\p{Diacritic}/gu, '')
  .replace(/[\s\-_]/g, ''); // quita espacios/guiones

function setSelectByApproxValue(selectEl, rawValue, { synonyms = {} } = {}) {
  if (!selectEl) return;
  const valRaw = (rawValue ?? '').toString().trim();
  if (!valRaw) { selectEl.value = ''; return; }

  const key = _normKey(valRaw);

  // 1) sinónimos (normalizados)
  const synHit = Object.entries(synonyms).find(([from]) => _normKey(from) === key);
  const desired = synHit ? synonyms[synHit[0]] : valRaw;

  // 2) intentos de match por value/text normalizados
  const opts = Array.from(selectEl.options);
  const desiredKey = _normKey(desired);

  // 2a) match estricto por value normalizado
  let opt = opts.find(o => _normKey(o.value) === desiredKey);
  if (!opt) {
    // 2b) match por label/texto mostrado
    opt = opts.find(o => _normKey(o.textContent || '') === desiredKey);
  }
  if (opt) {
    opt.selected = true;
    selectEl.value = opt.value; // asegura .value correcto
    return;
  }

  // 3) si no existe esa opción, la creamos para reflejar lo que hay en BD
  const created = document.createElement('option');
  created.value = desired;
  created.textContent = desired;
  selectEl.appendChild(created);
  selectEl.value = desired;
}

// Mapas de sinónimos útiles
const SYN_JOB_TYPE = {
  'Full time': 'Full-time',
  'Fulltime': 'Full-time',
  'Part time': 'Part-time',
  'Parttime': 'Part-time'
};
const SYN_MODALITY = {
  'On site': 'On-site',
  'Onsite': 'On-site',
  'Remote only': 'Remote',
  'Hybrid/remote': 'Hybrid'
};
const SYN_SENIORITY = {
  'Semi senior': 'Semi-senior',
  'Semisenior': 'Semi-senior',
  'Mid': 'Semi-senior',
  'Manager/Senior': 'Manager'
};
const SYN_EXP_LEVEL = {
  'Entry level': 'Entry level job',
  'Entry-level': 'Entry level job',
  'Experienced': 'Experienced'
};
const SYN_FIELD = {
  'IT': 'it',
  'I.T.': 'it',
  'Marketing & Sales': 'marketing',
  'Virtual Assistant': 'virtual assistant',
  'Legal Dept': 'legal'
};

  // Campos base
  document.getElementById('career-jobid').value        = oppId;
  document.getElementById('career-job').value          = data.career_job || jobTitle || '';
  document.getElementById('career-description').value  = desc;
  document.getElementById('career-requirements').value = reqs;
  document.getElementById('career-additional').value   = addi;

  // Selects varios
setSelectByApproxValue(document.getElementById('career-jobtype'),   data.career_job_type,        { synonyms: SYN_JOB_TYPE });
setSelectByApproxValue(document.getElementById('career-seniority'), data.career_seniority,       { synonyms: SYN_SENIORITY });
setSelectByApproxValue(document.getElementById('career-exp-level'), data.career_experience_level,{ synonyms: SYN_EXP_LEVEL });
setSelectByApproxValue(document.getElementById('career-field'),     data.career_field,           { synonyms: SYN_FIELD });
setSelectByApproxValue(document.getElementById('career-modality'),  data.career_modality,        { synonyms: SYN_MODALITY });

  document.getElementById('career-years').value     = data.career_years_experience || '';

  // ===== Country (Choices) =====
  countryEl.innerHTML =
    '<option value="">Select country...</option>' +
    LATAM_COUNTRIES.map(c => `<option value="${c}">${c}</option>`).join('');

  if (savedCountry && !LATAM_COUNTRIES.includes(savedCountry)) {
    countryEl.insertAdjacentHTML('beforeend', `<option value="${savedCountry}">${savedCountry}</option>`);
  }
  countryEl.value = savedCountry || '';

  if (window.countryChoices) window.countryChoices.destroy();
  window.countryChoices = new Choices(countryEl, {
    searchEnabled: true,
    shouldSort: true,
    removeItemButton: false,
    searchPlaceholderValue: 'Search country…'
  });
  // 👇 Fuerza el valor seleccionado en Choices (evita que quede el anterior)
  try { window.countryChoices.setChoiceByValue(savedCountry || ''); } catch {}

  // Helper para poblar ciudades
  const buildCityChoices = (country, presetCity='') => {
      if (country === 'Latin America') {
    if (window.cityChoices) window.cityChoices.destroy();
    cityEl.disabled = false;
    cityEl.innerHTML = `<option value="Any Country">Any Country</option>`;
    window.cityChoices = new Choices(cityEl, { searchEnabled: false, shouldSort: false });
    try { window.cityChoices.setChoiceByValue('Any Country'); } catch {}
    saveCareerField('career_city', 'Any Country');
    return;
  }
    const cities = CITIES_BY_COUNTRY[country] || [];
    if (window.cityChoices) window.cityChoices.destroy();
    cityEl.innerHTML = '';
    if (cities.length) {
      cityEl.disabled = false;
      const list = [...cities];
      if (presetCity && !list.includes(presetCity)) list.unshift(presetCity);

      cityEl.insertAdjacentHTML('beforeend',
        `<option value="">Select city…</option>` +
        list.map(ct => `<option value="${ct}">${ct}</option>`).join('')
      );
      cityEl.value = presetCity || '';
      window.cityChoices = new Choices(cityEl, {
        searchEnabled: true,
        shouldSort: true,
        removeItemButton: false,
        searchPlaceholderValue: 'Search city…'
      });
      // 👇 Igual que arriba: asegura selección real
      try { window.cityChoices.setChoiceByValue(presetCity || ''); } catch {}
    } else {
      cityEl.disabled = true;
      cityEl.insertAdjacentHTML('beforeend', `<option value="">Select a country first</option>`);
      window.cityChoices = new Choices(cityEl, { searchEnabled: true, shouldSort: true, removeItemButton: false });
      window.cityChoices.disable();
    }
  };

  // Construir ciudades con el país guardado
  buildCityChoices(savedCountry, savedCity);

  // Cambio de país → reconstruye ciudades
  countryEl.addEventListener('change', () => {
    const country = countryEl.value;
    buildCityChoices(country, '');
    saveCareerField('career_city', ''); // limpia en DB
  }, { signal: (window.__publishCareerAC || {}).signal });

  // ===== Tools & Skills con chips =====
  mountToolsDropdown(savedTools);

  // === AUTOSAVE bindings for Publish Career popup ===
  if (window.__publishCareerAC) {
    try { window.__publishCareerAC.abort(); } catch {}
  }
  window.__publishCareerAC = new AbortController();
  const SIG = { signal: window.__publishCareerAC.signal };
// ⚙️ Upgradear los 3 textareas a rich editors con autosave HTML
const descEditor = createRichEditor('career-description', 'career_description', SIG.signal);
const reqsEditor = createRichEditor('career-requirements', 'career_requirements', SIG.signal);
const addiEditor = createRichEditor('career-additional', 'career_additional_info', SIG.signal);

// pero si quieres forzar contenido de la última carga:
if (descEditor) descEditor.innerHTML = (data.career_description || data.hr_job_description || '');
if (reqsEditor) reqsEditor.innerHTML = (data.career_requirements || '');
if (addiEditor) addiEditor.innerHTML = (data.career_additional_info || '');
// 👉 Enganche del botón ⭐ dentro de openPublishCareerPopup()
const aiStarBtn   = document.getElementById('career-ai-btn');
const aiStarStatus = document.getElementById('career-ai-status');

if (aiStarBtn) {
  aiStarBtn.onclick = async () => {
    const oppId = getOpportunityId();
    if (!oppId) return alert('❌ Invalid Opportunity ID');

    // Fuente del JD: editor visible de la página (preferido), o BD.
    const jdFromPage = document.getElementById('job-description-textarea')?.innerHTML || '';
    const jd = stripHtmlToText(jdFromPage).length ? jdFromPage : (window.currentOpportunityData?.hr_job_description || '');

    if (!stripHtmlToText(jd).length) {
      return alert('❌ No Job Description to use');
    }

    // UI feedback
    aiStarBtn.disabled = true;
    const _orig = aiStarBtn.innerHTML;
    aiStarBtn.innerHTML = '⭐ Generating…';
    if (aiStarStatus) { aiStarStatus.style.display = 'inline-block'; aiStarStatus.textContent = '⏳ Generating…'; }

    try {
      // Llamada directa al endpoint de AI (evitamos runJDClassifierAndPersist porque rellena <textarea> ocultos)
      const r = await fetch(`${API_BASE}/ai/jd_to_career_fields`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_description: jd })
      });
      if (!r.ok) {
        const t = await r.text();
        throw new Error(t || 'AI error');
      }
      const out = await r.json();

      // 🔮 Rellenar los 3 editores ricos
    const descEditor = document.getElementById('career-description')?.previousElementSibling?.querySelector('.job-description-editor');
    const reqsEditor = document.getElementById('career-requirements')?.previousElementSibling?.querySelector('.job-description-editor');
    const addiEditor = document.getElementById('career-additional')?.previousElementSibling?.querySelector('.job-description-editor');

    if (descEditor) descEditor.innerHTML = out.career_description || '';
    if (reqsEditor) reqsEditor.innerHTML = out.career_requirements || '';
    if (addiEditor) addiEditor.innerHTML = out.career_additional_info || '';

    // (opcional) sincroniza los <textarea> ocultos para evitar inconsistencias visuales
    const descTA = document.getElementById('career-description');
    const reqsTA = document.getElementById('career-requirements');
    const addiTA = document.getElementById('career-additional');
    if (descTA) descTA.value = descEditor?.innerHTML || '';
    if (reqsTA) reqsTA.value = reqsEditor?.innerHTML || '';
    if (addiTA) addiTA.value = addiEditor?.innerHTML || '';

    // 💾 Guarda inmediatamente en una sola llamada (sin debounce)
    await saveCareerFieldsNow({
      career_description: descEditor?.innerHTML || '',
      career_requirements: reqsEditor?.innerHTML || '',
      career_additional_info: addiEditor?.innerHTML || ''
    });

    // feedback UI
    if (aiStarStatus) aiStarStatus.textContent = '✅ Ready';
    setTimeout(() => { if (aiStarStatus) aiStarStatus.style.display = 'none'; }, 900);
    alert('✅ Campos generados y guardados');

    } catch (err) {
      console.error('❌ Error generating career fields:', err);
      if (aiStarStatus) { aiStarStatus.textContent = '❌ Error'; setTimeout(()=> aiStarStatus.style.display='none', 1200); }
      alert('❌ Error generando los campos');
    } finally {
      aiStarBtn.disabled = false;
      aiStarBtn.innerHTML = _orig;
    }
  };
}

  const bind = (selector, field, evt = 'input', xform = v => v) => {
    const el = document.querySelector(selector);
    if (!el) return;
    el.addEventListener(evt, () => {
      const raw = (el.type === 'checkbox') ? el.checked : (el.value ?? '');
      saveCareerField(field, xform(raw));
    }, SIG);
  };

  // Text inputs / selects
  bind('#career-job',               'career_job', 'input');
  bind('#career-country',           'career_country', 'change');
  bind('#career-city',              'career_city', 'change');
  bind('#career-jobtype',           'career_job_type', 'change');
  bind('#career-seniority',         'career_seniority', 'change');
  bind('#career-years',             'career_years_experience', 'input');
  bind('#career-exp-level',         'career_experience_level', 'change');
  bind('#career-field',             'career_field', 'change');
  bind('#career-modality',          'career_modality', 'change');

  // Si cambia el país, limpia city en DB (además de la UI)
  countryEl.addEventListener('change', () => {
    saveCareerField('career_city', '');
  }, SIG);
  // 👉 mover el bloque de acciones justo arriba de Description
const grid = document.querySelector('#publishCareerPopup .overview-grid');
const actions = document.getElementById('career-ai-btn')?.closest('.career-actions');
const descAnchor = grid.querySelector('.field-desc');
if (grid && actions && descAnchor && actions.nextElementSibling !== descAnchor) {
  grid.insertBefore(actions, descAnchor);
  actions.style.gridColumn = '1 / -1';
  actions.style.margin = '6px 0 2px';
}

}
// 🧰 Crea un editor rico desde un <textarea> existente
function createRichEditor(textareaId, fieldName, acSignal) {
  const ta = document.getElementById(textareaId);
  if (!ta) return;

  // ✅ Si ya se “enhanced”, reutiliza el editor existente
  if (ta.dataset.enhanced === '1') {
    const existing = ta.nextElementSibling?.classList?.contains('rich-wrap')
      ? ta.nextElementSibling.querySelector('.job-description-editor')
      : null;
    return existing || null;
  }

  // contenedor
  const wrap = document.createElement('div');
  wrap.className = 'rich-wrap';
  ta.parentNode.insertBefore(wrap, ta);
  ta.style.display = 'none';
  ta.dataset.enhanced = '1'; // ← marca como convertido

  // toolbar (compacta)
  const bar = document.createElement('div');
  bar.className = 'toolbar small-toolbar';
  bar.style.marginBottom = '6px';
  bar.innerHTML = `
    <button type="button" data-cmd="bold"><b>B</b></button>
    <button type="button" data-cmd="italic"><i>I</i></button>
    <button type="button" data-cmd="ul">• List</button>

    <div class="emoji-anchor" style="display:inline-block; position:relative;">
      <button type="button" data-emoji id="emoji-toggle-btn" aria-label="Insert emoji">😊</button>
      <emoji-picker class="popup-emoji" style="
        display:none; position:absolute; z-index:100000;
        top:0; right:calc(100% + 8px); /* 👈 abre hacia la IZQUIERDA del botón */
        width:320px; max-height:340px; overflow:auto; background:#fff; border:1px solid #e2e8f0; border-radius:12px; box-shadow:0 10px 30px rgba(0,0,0,.12);
      "></emoji-picker>
    </div>
  `;


  // editor
  const ed = document.createElement('div');
  ed.className = 'job-description-editor';
  ed.contentEditable = 'true';
  ed.style.minHeight = '120px';
  ed.style.border = '1px solid #e2e8f0';
  ed.style.borderRadius = '10px';
  ed.style.padding = '10px';
  ed.style.background = '#fff';
  ed.innerHTML = ta.value || '';

  // wire toolbar (un solo handler, delegación)
  bar.addEventListener('click', async (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;

    const cmd = btn.dataset.cmd;
    if (cmd) {
      // comandos de formato
      if (cmd === 'ul') document.execCommand('insertUnorderedList', false, null);
      else document.execCommand(cmd, false, null);
      btn.classList.toggle('active');
      return;
    }

    if (btn.hasAttribute('data-emoji')) {
      // ⚙️ asegura que el custom element esté cargado
      try { await ensureEmojiPickerLoaded(); } catch {}
      const picker = bar.querySelector('.popup-emoji');
      const anchor = btn.closest('.emoji-anchor');

      // toggle
      const willShow = picker.style.display !== 'block';
      // cierra otros pickers visibles
      document.querySelectorAll('.popup-emoji').forEach(p => p.style.display = 'none');

      if (willShow) {
        // Posiciona hacia la izquierda del botón y CLAMPEA dentro del modal
        picker.style.display = 'block';

        // Ajuste anti-desborde horizontal dentro de .popup-content
        const popup = btn.closest('.popup-content') || document.body;
        const popupRect = popup.getBoundingClientRect();
        const pickRect  = picker.getBoundingClientRect();
        const btnRect   = btn.getBoundingClientRect();

        // si aun así se sale por la izquierda, cae a abrir debajo del botón (anclado al borde derecho)
        if (pickRect.left < popupRect.left + 8) {
          picker.style.top = '100%';
          picker.style.right = '0';
        } else {
          picker.style.top = '0';
          picker.style.right = 'calc(100% + 8px)';
        }
      }
    }
  }, { signal: acSignal });

  // 🎯 Inserción del emoji dentro del editor rico (una sola vez)
  const picker = bar.querySelector('emoji-picker');
  picker.addEventListener('emoji-click', (ev) => {
    ed.focus();
    document.execCommand('insertText', false, ev.detail.unicode);
    picker.style.display = 'none';
  }, { signal: acSignal });

  // autosave HTML
  const onChange = () => saveCareerField(fieldName, ed.innerHTML);
  ed.addEventListener('input', onChange, { signal: acSignal });
  ed.addEventListener('blur', onChange, { signal: acSignal });

  // montar
  wrap.appendChild(bar);
  wrap.appendChild(ed);
  return ed;
}
function getRichEditor(textareaId) {
  const ta = document.getElementById(textareaId);
  if (!ta) return null;
  // cuando createRichEditor corre, inserta .rich-wrap ANTES del textarea
  const wrap = ta.previousElementSibling;
  if (wrap && wrap.classList && wrap.classList.contains('rich-wrap')) {
    return wrap.querySelector('.job-description-editor');
  }
  return null;
}


function closePublishCareerPopup() {
  if (window.__publishCareerAC) {
    try { window.__publishCareerAC.abort(); } catch {}
    window.__publishCareerAC = null;
  }
  document.getElementById('publishCareerPopup').classList.add('hidden');
}

// 🔧 Evita doble submit en Publish (deja SOLO uno)
const publishBtn = document.getElementById('publishCareerBtn');
publishBtn.replaceWith(publishBtn.cloneNode(true));


function mountToolsChips(initial=[]) {
  const holder = document.querySelector('#publishCareerPopup .field-tools');
  if (!holder) return;

  // limpia y vuelve a construir (no rompemos el <label>)
  const label = holder.querySelector('label');
  const hints = holder.querySelector('small');
  holder.querySelectorAll('.tools-chips, .tools-input').forEach(n => n.remove());

  const chips = document.createElement('div');
  chips.className = 'tools-chips';
  chips.style.display = 'flex';
  chips.style.flexWrap = 'wrap';
  chips.style.gap = '8px';
  chips.style.padding = '8px 10px';
  chips.style.border = '1px solid #e2e8f0';
  chips.style.borderRadius = '12px';
  chips.style.background = '#fff';

  const input = document.createElement('input');
  input.className = 'tools-input';
  input.type = 'text';
  input.placeholder = 'Type a tool and press Enter';
  input.style.border = 'none';
  input.style.outline = 'none';
  input.style.flex = '1';
  input.style.minWidth = '160px';
  input.style.padding = '6px 4px';
  input.autocomplete = 'off';

  // estado en memoria
  window.__careerTools = Array.isArray(initial) ? [...initial] : [];

  const render = () => {
    // borra chips existentes (menos el input)
    chips.querySelectorAll('.chip').forEach(n => n.remove());
    window.__careerTools.forEach((t, idx) => {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = t;
      chip.style.padding = '6px 10px';
      chip.style.borderRadius = '16px';
      chip.style.background = '#dce9f8';
      chip.style.color = '#0a1f44';
      chip.style.fontSize = '12px';
      chip.style.display = 'inline-flex';
      chip.style.alignItems = 'center';
      chip.style.gap = '8px';

      const x = document.createElement('button');
      x.type = 'button';
      x.textContent = '✕';
      x.style.border = 'none';
      x.style.background = 'transparent';
      x.style.cursor = 'pointer';
      x.style.fontSize = '12px';
      x.onclick = () => {
        window.__careerTools.splice(idx, 1);
        render();
        saveCareerField('career_tools', [...window.__careerTools]);
      };

      chip.appendChild(x);
      // Insertar chip antes del input
      chips.insertBefore(chip, input);
    });
  };

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const val = input.value.trim();
      if (!val) return;
      if (!window.__careerTools.includes(val)) {
        window.__careerTools.push(val);
        render();
        saveCareerField('career_tools', [...window.__careerTools]);
      }
      input.value = '';
    }
  });

  // Ensambla
  chips.appendChild(input);
  // Recolocar dentro del holder
  if (hints) holder.insertBefore(chips, hints);
  else holder.appendChild(chips);

  render();
}

function closePublishCareerPopup() {
  // ❌ corta todos los listeners de esta sesión de popup
  if (window.__publishCareerAC) {
    try { window.__publishCareerAC.abort(); } catch {}
    window.__publishCareerAC = null;
  }
  document.getElementById('publishCareerPopup').classList.add('hidden');
}

// Abrir / Cerrar
document.getElementById('publish-career-btn').addEventListener('click', openPublishCareerPopup);
document.getElementById('closePublishCareerPopup').addEventListener('click', closePublishCareerPopup);

async function saveCareerPayload(publish = false) {
  const oppId = getOpportunityId();
  if (!oppId) return alert('❌ Invalid Opportunity ID');

  const toolsFromChips   = (window.__careerTools || []).filter(Boolean);
  const toolsFromChoices = (window.toolsChoices ? window.toolsChoices.getValue(true) : []).filter(Boolean);
  // Siempre envía slugs exactos para que el Sheet pinte chips
const finalTools = normalizeToolsArray(
  window.toolsChoices ? window.toolsChoices.getValue(true) : []
);

const descEditorEl = getRichEditor('career-description');
const reqsEditorEl = getRichEditor('career-requirements');
const addiEditorEl = getRichEditor('career-additional');
  const payload = {
    career_job_id: document.getElementById('career-jobid').value || '',
    career_job: document.getElementById('career-job').value || '',
    career_country: document.getElementById('career-country').value || '',
    career_city: document.getElementById('career-city').value || '',
    career_job_type: document.getElementById('career-jobtype').value || '',
    career_seniority: document.getElementById('career-seniority').value || '',
    career_years_experience: document.getElementById('career-years').value || '',
    career_experience_level: document.getElementById('career-exp-level').value || '',
    career_field: document.getElementById('career-field').value || '',
    career_modality: document.getElementById('career-modality').value || '',
  career_tools: finalTools,
  career_description: (descEditorEl?.innerHTML ?? document.getElementById('career-description').value ?? ''),
  career_requirements: (reqsEditorEl?.innerHTML ?? document.getElementById('career-requirements').value ?? ''),
  career_additional_info: (addiEditorEl?.innerHTML ?? document.getElementById('career-additional').value ?? '')
  };

  if (publish) payload.career_published = true;

  try {
    const res = await fetch(`${API_BASE}/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(t || 'Failed to save');
    }

    // 🟢 **IMPORTANTE**: sincroniza cache local para que openPublishCareerPopup use los valores nuevos
    window.currentOpportunityData = Object.assign({}, window.currentOpportunityData || {}, payload);

    showFriendlyPopup(publish ? '✅ Published to Career Site (saved in DB)' : '💾 Draft saved');
    closePublishCareerPopup();
  } catch (err) {
    console.error(err);
    alert('❌ Error saving career data');
  }
}


document.getElementById('saveDraftCareerBtn').addEventListener('click', () => saveCareerPayload(false));

document.getElementById('publishCareerBtn').addEventListener('click', () => publishCareerNow());
function htmlToPlainWithNewlines(html) {
  if (!html) return '';
  let s = String(html);

  // <br> → \n
  s = s.replace(/<\s*br\s*\/?>/gi, '\n');

  // Bloques que implican salto
  const blocks = ['p','section','article','header','footer','aside','h1','h2','h3','h4','h5','h6','table','tr','ul','ol','li','div'];
  blocks.forEach(tag => {
    const reOpen  = new RegExp(`<\\s*${tag}[^>]*>`, 'gi');
    const reClose = new RegExp(`<\\/\\s*${tag}\\s*>`, 'gi');
    s = s.replace(reOpen, '\n').replace(reClose, '\n');
  });

  // Listas
  s = s.replace(/<\s*li[^>]*>\s*/gi, '\n• ').replace(/<\s*\/\s*li\s*>/gi, '');

  // Quitar etiquetas restantes
  s = s.replace(/<[^>]+>/g, '');

  // Decodificar entidades
  const tmp = document.createElement('textarea');
  tmp.innerHTML = s;
  s = tmp.value;

  // Normalizaciones
  s = s
    .replace(/\u00A0/g, ' ')     // &nbsp; → espacio normal
    .replace(/\r\n/g, '\n')
    .replace(/[ \t]+\n/g, '\n')  // espacios antes del salto
    .replace(/\n{3,}/g, '\n\n'); // máximo 2 saltos seguidos

  // ❗️ NO quites el salto inicial: solo recorta al final
  s = s.replace(/[ \t]+$/gm, '').replace(/\s+$/,'');
  return s;
}


async function publishCareerNow() {
  const oppId = getOpportunityId();
  if (!oppId) return alert('❌ Invalid Opportunity ID');

  const descHTML = getRichEditor('career-description')?.innerHTML
                ?? document.getElementById('career-description').value ?? '';
  const reqsHTML = getRichEditor('career-requirements')?.innerHTML
                ?? document.getElementById('career-requirements').value ?? '';
  const addiHTML = getRichEditor('career-additional')?.innerHTML
                ?? document.getElementById('career-additional').value ?? '';

  // 🔹 limpiamos para Webflow (sin <span>, sin styles)
  const descHTML_CLEAN = cleanHtmlForWebflow(descHTML);
  const reqsHTML_CLEAN = cleanHtmlForWebflow(reqsHTML);
  const addiHTML_CLEAN = cleanHtmlForWebflow(addiHTML);

  const finalTools = (window.toolsChoices ? window.toolsChoices.getValue(true) : []).filter(Boolean);

  const payload = {
    publish_mode: 'sheet_only',
    // meta
    career_job_id: document.getElementById('career-jobid').value || oppId,
    career_job: document.getElementById('career-job').value || '',
    career_country: document.getElementById('career-country').value || '',
    career_city: document.getElementById('career-city').value || '',
    career_job_type: document.getElementById('career-jobtype').value || '',
    career_seniority: document.getElementById('career-seniority').value || '',
    career_years_experience: document.getElementById('career-years').value || '',
    career_experience_level: document.getElementById('career-exp-level').value || '',
    career_field: document.getElementById('career-field').value || '',
    career_modality: document.getElementById('career-modality').value || '',
    career_tools: finalTools,

    // 🔹 para el Sheet: **HTML limpio** (lo que Webflow necesita)
    sheet_description_html: descHTML_CLEAN,
    sheet_requirements_html: reqsHTML_CLEAN,
    sheet_additional_html: addiHTML_CLEAN
  };

  const btn = document.getElementById('publishCareerBtn');
  btn.disabled = true;
  btn.textContent = 'Publishing…';

  try {
    const res = await fetch(`${API_BASE}/careers/${oppId}/publish`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Publish failed');

    showFriendlyPopup(`✅ Published! Item ID: ${data.career_id}`);
    window.currentOpportunityData = Object.assign({}, window.currentOpportunityData || {}, {
      career_id: data.career_id, career_published: true
    });
    closePublishCareerPopup();
  } catch (err) {
    console.error(err);
    alert('❌ Error publishing to Sheet');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Publish';
  }
}

// ✅ Delegación global para TODAS las toolbars
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.toolbar button');
  if (!btn) return;

  // Soporta data-command y data-cmd (ambos los usas en distintos lugares)
  const cmd = btn.getAttribute('data-command') || btn.getAttribute('data-cmd');
  if (!cmd) return;

  // Encuentra el editor más cercano: primero el rich editor de la popup,
  // si no, cae al Job Description principal
  const wrap = btn.closest('.rich-wrap');
  const editor = wrap?.querySelector('.job-description-editor') ||
                 document.getElementById('job-description-textarea');

  if (!editor) return;
  editor.focus();

  // Normaliza comandos
  if (cmd === 'ul' || cmd === 'insertUnorderedList') {
    document.execCommand('insertUnorderedList', false, null);
  } else {
    document.execCommand(cmd, false, null);
  }

  // Feedback visual opcional
  btn.classList.toggle('active');
  e.preventDefault();
});

// ✅ Mantiene botones “activos” acorde a la selección del usuario
document.addEventListener('mouseup', () => {
  const editor = document.querySelector('.job-description-editor') || document.getElementById('job-description-textarea');
  if (!editor) return;
  document.querySelectorAll('.toolbar button').forEach(btn => {
    const cmd = btn.getAttribute('data-command') || btn.getAttribute('data-cmd');
    if (!cmd) return;
    try {
      const state = document.queryCommandState(cmd === 'ul' ? 'insertUnorderedList' : cmd);
      btn.classList.toggle('active', !!state);
    } catch {}
  });
});




});

async function loadOpportunityData() {
  const params = new URLSearchParams(window.location.search);
  const opportunityId = params.get('id');
  if (!opportunityId) return;

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`);
    const data = await res.json();
    window.currentOpportunityData = data;
    // Overview section
    document.getElementById('opportunity-id-text').textContent = data.opportunity_id || '—';
    document.getElementById('opportunity-id-text').setAttribute('data-id', data.opportunity_id);
    document.getElementById('start-date-input').value = formatDate(data.nda_signature_or_start_date);
    document.getElementById('close-date-input').value = formatDate(data.opp_close_date);
    document.getElementById('comments-overview-textarea').value = data.comments || '';

    // Client section
    document.getElementById('client-name-input').value = data.account_name || '';
    document.getElementById('client-size-input').value = data.account_size || '';
    document.getElementById('client-state-input').value = data.account_state || '';
    document.getElementById('client-linkedin-input').value = data.account_linkedin || '';
    document.getElementById('client-website-input').value = data.account_website || '';
    document.getElementById('client-mail-input').value = data.account_mail || '';
    document.getElementById('client-about-textarea').value = data.account_about || '';

    // DETAILS
    document.getElementById('details-opportunity-name').value = data.opp_position_name || '';
    document.getElementById('details-account-name').value = data.account_name || '';
    document.getElementById('details-model').value = data.opp_model || '';
    
    // JOB DESCRIPTION
    document.getElementById('job-description-textarea').innerHTML = data.hr_job_description || '';

    // FIRST MEETING INFO
    document.getElementById('min-budget-input').value = data.min_budget || '';
    document.getElementById('max-budget-input').value = data.max_budget || '';
    document.getElementById('min-salary-input').value = data.min_salary || '';
    document.getElementById('max-salary-input').value = data.max_salary || '';
    document.getElementById('model-select').value = data.opp_model || '';
    document.getElementById('years-experience-input').value = data.years_experience || '';
    document.getElementById('fee-input').value = data.fee || '';
    document.getElementById('timezone-input').value = data.account_timezone || '';
    document.getElementById('comments-firstmeeting-textarea').value = data.opp_comments || '';
    document.getElementById('recording-input').value = data.first_meeting_recording || '';
    document.getElementById('deepdive-recording-input').value = data.deepdive_recording || '';
    document.getElementById('interviewing-process-editor').innerHTML = data.client_interviewing_process || '';

    // Signed: si tienes un campo de fecha de firma, calcula días
    if (data.nda_signature_or_start_date) {
      const signedDays = calculateDaysAgo(data.nda_signature_or_start_date);
      document.getElementById('signed-tag').textContent = `${signedDays} days ago`;
    } else {
      document.getElementById('signed-tag').textContent = '—';
    }

    // 🔹 Mostrar el HIRE y guardar id en dataset + variable global (con fallback)
    try {
      const hireDisplay = document.getElementById('hire-display');
      const hiredId = Number(data.candidato_contratado) || null;

      if (hireDisplay) {
        // limpia estado
        hireDisplay.removeAttribute('data-candidate-id');
        hireDisplay.dataset.candidateId = '';
        if ('value' in hireDisplay) hireDisplay.value = '—';
        hireDisplay.textContent = '—';
      }

      if (hireDisplay && hiredId) {
        const r = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${hiredId}`);
        if (r.ok) {
          const cand = await r.json();
          console.log('👤 Candidate API payload:', cand);

          // pinta nombre (sirve si hireDisplay es input o span/div)
          if ('value' in hireDisplay) hireDisplay.value = cand.name || '—';
          hireDisplay.textContent = cand.name || '—';

          // ⚠️ toma id con fallback por si el payload no trae candidate_id
          const cidRaw = (cand.candidate_id ?? cand.id ?? cand.candidateId ?? hiredId);
          const cid = String(cidRaw);

          // guarda en dataset, atributo y variable global
          hireDisplay.dataset.candidateId = cid;
          hireDisplay.setAttribute('data-candidate-id', cid);
          window.hireCandidateId = cid;

          console.log('👤 Hired candidate set:', cid, '-', cand.name);
        } else {
          window.hireCandidateId = null;
        }
      } else {
        window.hireCandidateId = null;
      }
    } catch (error) {
      console.error('Error loading hire candidate:', error);
      window.hireCandidateId = null;
    }
      window.currentAccountId = data.account_id;
        try {
          const resUsers = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/users`);
          const users = await resUsers.json();

          const salesLeadSelect = document.getElementById('details-sales-lead');
          const hrLeadSelect = document.getElementById('details-hr-lead');

          salesLeadSelect.innerHTML = `<option value="">Select Sales Lead...</option>`;
          hrLeadSelect.innerHTML = `<option value="">Select HR Lead...</option>`;

          const allowedSubstrings = ['Pilar', 'Jazmin', 'Agostina', 'Agustina'];

          users.forEach(user => {
            const option1 = document.createElement('option');
            option1.value = user.email_vintti;
            option1.textContent = user.user_name;
            salesLeadSelect.appendChild(option1);

            // Solo agregar al dropdown de HR Lead si coincide con los nombres permitidos
            if (allowedSubstrings.some(name => user.user_name.includes(name))) {
              const option2 = document.createElement('option');
              option2.value = user.email_vintti;
              option2.textContent = user.user_name;
              hrLeadSelect.appendChild(option2);
            }
          });

          // Ahora cruzas: en data.opp_sales_lead y opp_hr_lead tienes el EMAIL → debes setear el value del <select> con ese email:
          salesLeadSelect.value = data.opp_sales_lead || '';
          hrLeadSelect.value = data.opp_hr_lead || '';
          if (data.opportunity_id) {
            reloadBatchCandidates();
          }
          // 🚨 Mostrar alerta si no hay HR Lead asignado
          if (!data.opp_hr_lead) {
            const alertBox = document.createElement('div');
            alertBox.textContent = "⚠️ This opportunity doesn't have an HR Lead assigned. Please assign one.";
            alertBox.style.background = '#fff3cd';
            alertBox.style.color = '#856404';
            alertBox.style.border = '1px solid #ffeeba';
            alertBox.style.padding = '12px';
            alertBox.style.borderRadius = '10px';
            alertBox.style.margin = '15px 0';
            alertBox.style.fontWeight = '500';
            alertBox.style.textAlign = 'center';

            const container = document.querySelector('.detail-main');
            container.insertBefore(alertBox, container.firstChild);
          }

        } catch (err) {
          console.error('Error loading users for Sales/HR Lead:', err);
        }

        } catch (err) {
          console.error("Error loading opportunity:", err);
        }
        try {
  const lightRes = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light');
  const lightData = await lightRes.json();
  const currentId = opportunityId;
  const opp = lightData.find(o => o.opportunity_id == currentId); // usa comparación flexible con ==

  if (opp && opp.opp_stage) {
    const stageText = opp.opp_stage;
    const stageTag = document.getElementById('stage-tag');
    const stageSpan = document.getElementById('stage-text');

    stageSpan.textContent = stageText;

    // Limpiar clases anteriores por si hay recarga
    stageTag.className = 'opportunity-stage-card';

    // Generar clase CSS dinámicamente
    const cssClass = `stage-color-${stageText.toLowerCase().replace(/\s+/g, '-').replace(/[^\w-]/g, '')}`;
    stageTag.classList.add(cssClass);
  }
} catch (err) {
  console.error("❌ Error loading stage from opportunities/light:", err);
}
      }
      function formatDate(dateStr) {
        if (!dateStr) return '';
        
        const parsed = Date.parse(dateStr);
        if (isNaN(parsed)) return '';

        const date = new Date(parsed);

        // Aquí se usa getFullYear(), getMonth() + 1, getDate() → muestra la fecha tal como la tienes en el JSON
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');

        return `${year}-${month}-${day}`;
      }



function calculateDaysAgo(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffTime = Math.abs(now - date);
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
  return diffDays;
}
async function updateOpportunityField(fieldName, fieldValue) {
  const opportunityId = getOpportunityId();
  if (opportunityId === '—' || opportunityId === '') {
    console.error('Opportunity ID not found');
    return;
  }

  const payload = {};
  payload[fieldName] = fieldValue;

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/fields`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errorText = await res.text();
      console.error(`❌ Error updating ${fieldName}:`, errorText);
    } else {
      console.log(`✅ ${fieldName} updated successfully`);
    }

  } catch (err) {
    console.error(`Error updating ${fieldName}:`, err);
  }
}

async function updateAccountField(fieldName, fieldValue) {
  const accountId = getAccountId();

  if (!accountId) {
    console.error('Account ID not found');
    return;
  }

  const payload = {};
  payload[fieldName] = fieldValue;

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      console.error(`Failed to update ${fieldName} in account`);
    }

  } catch (err) {
    console.error(`Error updating ${fieldName} in account:`, err);
  }
}
async function runJDClassifierAndPersist(opportunityData) {
  const oppId = getOpportunityId();
  if (!oppId) return;

  const jdHtml = opportunityData.hr_job_description || '';
  const payload = { job_description: jdHtml };

  // Llama a tu nuevo endpoint AI
  const r = await fetch(`${API_BASE.replace(/\/$/, '')}/ai/jd_to_career_fields`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!r.ok) {
    const t = await r.text();
    console.warn('⚠️ jd_to_career_fields returned non-OK:', t);
    return;
  }

  const { career_description, career_requirements, career_additional_info } = await r.json();

  // Pinta si existen los campos (en la popup o en la página)
  const descEl = document.getElementById('career-description');
  const reqsEl = document.getElementById('career-requirements');
  const addiEl = document.getElementById('career-additional');

  if (descEl) descEl.value = career_description || '';
  if (reqsEl) reqsEl.value = career_requirements || '';
  if (addiEl) addiEl.value = career_additional_info || '';

  // Persiste en DB (usa tu endpoint PATCH de fields)
  // Importante: no cambies nada si vino vacío; pero si quieres forzar guardado igual, elimina los "if (..)"
  if (typeof career_description === 'string') {
    await updateOpportunityField('career_description', career_description);
  }
  if (typeof career_requirements === 'string') {
    await updateOpportunityField('career_requirements', career_requirements);
  }
  if (typeof career_additional_info === 'string') {
    await updateOpportunityField('career_additional_info', career_additional_info);
  }

  console.log('✅ JD classified & saved.');
}

function getAccountId() {
  return window.currentAccountId || null;
}
document.querySelector('.btn-create').addEventListener('click', () => {
  document.getElementById('presentationDateInput').value = ''; // limpia fecha previa
  document.getElementById('createBatchPopup').classList.remove('hidden');
});

document.getElementById('closeCreateBatchPopup').addEventListener('click', () => {
  document.getElementById('createBatchPopup').classList.add('hidden');
});

document.getElementById('confirmCreateBatchBtn').addEventListener('click', async () => {
  const presentationDate = document.getElementById('presentationDateInput').value;
  const opportunityId = getOpportunityId();

  if (!presentationDate) return alert('❌ Please select a presentation date');

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ presentation_date: presentationDate })  // ← ahora se envía la fecha
    });

    const data = await res.json();

    if (res.ok) {
      const batchContainer = document.createElement('div');
      batchContainer.classList.add('batch-box');
      batchContainer.innerHTML = `
        <div class="batch-actions">
          <h3>Batch #${data.batch_number}</h3>
          <div>
            <button class="btn-add">Add candidate</button>
            <button class="btn-send">Send for Approval</button>
          </div>
        </div>
      `;
      document.getElementById('batch-detail-container').appendChild(batchContainer);
      document.getElementById('createBatchPopup').classList.add('hidden');
      showFriendlyPopup("✅ Batch created successfully");
      setTimeout(() => location.reload(), 1000);
    } else {
      alert('❌ Failed to create batch');
    }
  } catch (err) {
    console.error('Error creating batch:', err);
    alert('❌ Could not create batch');
  }
});
async function loadBatchesForOpportunity(opportunityId) {
  try {
    const batchesRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`);
    const batches = await batchesRes.json();

    const container = document.getElementById('batch-detail-container');
    container.innerHTML = '';

    for (const batch of batches) {
      const box = createBatchBox(batch);
      const candidateContainer = box.querySelector('.batch-candidates');

      const batchCandidatesRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batch.batch_id}/candidates`);
      const batchCandidates = await batchCandidatesRes.json();

      batchCandidates.forEach(c => {
        const cardElement = createCandidateCard(c, batch.batch_id);
        candidateContainer.appendChild(cardElement);
      });

      container.appendChild(box);
    }
  } catch (err) {
    console.error('Error loading batches:', err);
  }
}

async function reloadBatchCandidates() {
  const opportunityId = getOpportunityId();
  if (opportunityId && opportunityId !== '—') {
    await loadBatchesForOpportunity(opportunityId);
  }
}

function createBatchBox(batch) {
  const box = document.createElement('div');
  box.classList.add('batch-box');
  box.setAttribute('data-batch-id', batch.batch_id);

  box.innerHTML = `
    <div class="batch-actions">
      <h3>Batch #${batch.batch_number}</h3>
      <div>
        <button class="btn-add">Add candidate</button>
        <button class="btn-send">Send for Approval</button>
        <button class="btn-delete" data-batch-id="${batch.batch_id}" title="Delete Batch">🗑️</button>
      </div>
    </div>
    <div class="batch-candidates"></div>
  `;

  box.querySelector('.btn-add').addEventListener('click', async (e) => {
  // Lógica para abrir la popup de agregar candidato
  console.log("🟢 Add Candidate clicked for batch:", batch.batch_id);
  const batchBox = e.target.closest(".batch-box");
  if (!batchBox) return;

  const batchId = batchBox.getAttribute("data-batch-id");
  if (!batchId) return;

  // Muestra la popup de agregar candidato (batchCandidatePopup)
  document.getElementById("batchCandidatePopup").classList.remove("hidden");

  // Llama a la función para cargar los candidatos disponibles a asignar a ese batch
  await loadAvailableCandidatesForBatch(batchId);
});


  box.querySelector('.btn-send').addEventListener('click', () => openApprovalPopup(batch.batch_id));
  box.querySelector('.btn-delete').addEventListener('click', async (e) => {
    const confirmed = confirm('⚠️ Are you sure you want to delete this batch?');
    if (!confirmed) return;
    await deleteBatch(e.target.getAttribute('data-batch-id'));
  });

  return box;
}

function createCandidateCard(c, batchId) {
  const template = document.getElementById('candidate-card-template');
  const cardFragment = template.content.cloneNode(true);
  const cardElement = cardFragment.querySelector('.candidate-card');
  cardElement.setAttribute('data-candidate-id', c.candidate_id);

  cardElement.querySelectorAll('.candidate-name').forEach(el => el.textContent = c.name);
  const flag = getFlagEmoji(c.country);
  cardElement.querySelector('.candidate-country').textContent = c.country ? `${flag} ${c.country}` : '—';
  cardElement.querySelector('.candidate-salary').textContent = c.salary_range ? `$${c.salary_range}` : '—';
  cardElement.querySelector('.candidate-email').textContent = c.email || '';
  cardElement.querySelector('.candidate-img').src = `https://randomuser.me/api/portraits/lego/${c.candidate_id % 10}.jpg`;

  const dropdown = cardElement.querySelector('.candidate-status-dropdown');
  dropdown.value = c.status || "Client interviewing/testing";
  setDropdownValue(dropdown, c.status);

  dropdown.addEventListener('change', () => updateCandidateStatus(c.candidate_id, batchId, dropdown.value));

  cardElement.addEventListener('click', (e) => {
    if (e.target.classList.contains('candidate-status-dropdown') || e.target.classList.contains('delete-candidate-btn')) return;
    window.location.href = `/candidate-details.html?id=${c.candidate_id}`;
  });

  const trash = document.createElement('button');
  trash.innerHTML = '🗑️';
  trash.classList.add('delete-candidate-btn');
  trash.title = 'Remove from batch';
  trash.style.marginLeft = 'auto';
  trash.style.background = 'none';
  trash.style.border = 'none';
  trash.style.cursor = 'pointer';
  trash.style.fontSize = '18px';
  trash.addEventListener('click', async () => {
    const confirmed = confirm(`⚠️ Remove ${c.name} from this batch?`);
    if (!confirmed) return;
    await removeCandidateFromBatch(c.candidate_id, batchId);
  });

  const header = cardElement.querySelector('.candidate-card-header');
  header.insertBefore(trash, header.firstChild);

  return cardElement;
}

function setDropdownValue(dropdown, status) {
  if (!status) return;
  const options = dropdown.options;
  let found = false;
  for (let i = 0; i < options.length; i++) {
    if (options[i].value.trim() === status.trim()) {
      options[i].selected = true;
      found = true;
      break;
    }
  }
  if (!found) {
    console.warn('⚠️ Status not found in options:', status);
  }
}

async function updateCandidateStatus(candidateId, batchId, newStatus) {
  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates_batches/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId, batch_id: batchId, status: newStatus })
    });

    const result = await res.json();
    if (res.ok) {
      showFriendlyPopup('✅ Status updated');
    } else {
      showFriendlyPopup('❌ Error updating status');
    }
  } catch (err) {
    console.error('❌ Error updating status:', err);
  }
}

async function deleteBatch(batchId) {
  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batchId}`, { method: 'DELETE' });
    if (res.ok) {
      alert('✅ Batch deleted successfully');
      await reloadBatchCandidates();
    } else {
      alert('❌ Error deleting batch');
    }
  } catch (err) {
    console.error('Error deleting batch:', err);
    alert('❌ Could not delete batch');
  }
}

async function removeCandidateFromBatch(candidateId, batchId) {
  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates_batches', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ candidate_id: candidateId, batch_id: batchId })
    });

    if (res.ok) {
      showFriendlyPopup('✅ Candidate removed from batch');
      await reloadBatchCandidates();
    } else {
      alert('❌ Failed to remove candidate');
    }
  } catch (err) {
    console.error('❌ Error removing candidate:', err);
    alert('❌ Could not remove candidate');
  }
}

async function openApprovalPopup(batchId) {
  const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
// Obtener info completa de la oportunidad, incluyendo client_name
const [opportunityInfoRes, batchListRes] = await Promise.all([
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`),
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/batches`)
]);
const opportunityInfo = await opportunityInfoRes.json();
const batchList = await batchListRes.json();
const batchInfo = batchList.find(b => b.batch_id === batchId);

const subject = `Batch#${batchInfo.batch_number} – ${opportunityInfo.opp_position_name} – ${opportunityInfo.account_name}`;

const [usersRes, batchCandidatesRes] = await Promise.all([
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/users`),
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/batches/${batchId}/candidates`)
]);

const users = await usersRes.json();
const batchCandidates = await batchCandidatesRes.json();


  const toSelect = document.getElementById('approval-to');
  const ccSelect = document.getElementById('approval-cc');
  toSelect.innerHTML = '';
  ccSelect.innerHTML = '';

  users.forEach(user => {
    const option = document.createElement('option');
    option.value = user.email_vintti;
    option.textContent = user.user_name;
    toSelect.appendChild(option);

    const optionCc = option.cloneNode(true);
    ccSelect.appendChild(optionCc);
  });

  if (window.approvalToChoices) approvalToChoices.destroy();
  if (window.approvalCcChoices) approvalCcChoices.destroy();

  window.approvalToChoices = new Choices(toSelect, { removeItemButton: true });
  window.approvalCcChoices = new Choices(ccSelect, { removeItemButton: true });

  const yourName = localStorage.getItem('nickname') || 'The Vintti Team';

let candidateBlocks = '';

for (let c of batchCandidates) {
  try {
    const resumeUrl = `https://vinttihub.vintti.com/resume-readonly.html?id=${c.candidate_id}`;
    const aboutRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/resumes/${c.candidate_id}`);
    const aboutData = await aboutRes.json();

    candidateBlocks += `
      <li style="margin-bottom: 10px;">
        <strong>Name:</strong> ${c.name}<br>
        <strong>Monthly Cost:</strong> $${c.salary_range || '—'}<br>
        <strong>Resume:</strong> <em><a href="${resumeUrl}" target="_blank">${resumeUrl}</a></em><br>
      </li>
    `;
  } catch (error) {
    console.error(`❌ Error procesando candidato ID ${c.candidate_id}:`, error);
  }
}

const body = `
  <p>Hi XXX,</p>
  <p>Hope you're doing great!</p>
  <p>
    XXX has handpicked a shortlist of candidates who align with everything you outlined — from experience to budget. 
    We’re confident you’ll find strong potential here.
  </p>
  <p>Please let us know your availability, and XXX will take care of scheduling the first round of interviews.</p>
  <p><strong>Candidates:</strong></p>
  <ul>${candidateBlocks}</ul>
  <p>
    Let us know what times work best and we’ll get things moving. Looking forward to your thoughts!
  </p>
  <p>Best,<br>${yourName}</p>
`;

document.getElementById('approval-message').innerHTML = body;


document.getElementById('approval-subject').value = subject;

document.getElementById('approvalEmailPopup').classList.remove('hidden');

}
function closeAiPopup() {
  document.getElementById('ai-assistant-popup').classList.add('hidden');
}
function showFriendlyPopup(message) {
  const popup = document.createElement('div');
  popup.textContent = message;
  popup.style.position = 'fixed';
  popup.style.top = '20px';
  popup.style.right = '20px';
  popup.style.backgroundColor = '#ffe4ec';
  popup.style.color = '#b3005f';
  popup.style.padding = '14px 20px';
  popup.style.borderRadius = '20px';
  popup.style.fontWeight = '600';
  popup.style.boxShadow = '0 4px 10px rgba(0,0,0,0.1)';
  popup.style.zIndex = '9999';
  popup.style.transition = 'opacity 0.3s ease';
  popup.style.opacity = '1';
  popup.style.fontFamily = 'Quicksand, sans-serif';

  document.body.appendChild(popup);

  setTimeout(() => {
    popup.style.opacity = '0';
    setTimeout(() => popup.remove(), 300);
  }, 3000);
}
function insertEmoji(emoji) {
  const editor = document.getElementById('job-description-textarea');
  editor.focus();
  document.execCommand('insertText', false, emoji);
}
function getFlagEmoji(country) {
  const flags = {
    "Argentina": "🇦🇷", "Bolivia": "🇧🇴", "Brazil": "🇧🇷", "Chile": "🇨🇱",
    "Colombia": "🇨🇴", "Costa Rica": "🇨🇷", "Cuba": "🇨🇺", "Ecuador": "🇪🇨",
    "El Salvador": "🇸🇻", "Guatemala": "🇬🇹", "Honduras": "🇭🇳", "Mexico": "🇲🇽",
    "Nicaragua": "🇳🇮", "Panama": "🇵🇦", "Paraguay": "🇵🇾", "Peru": "🇵🇪",
    "Puerto Rico": "🇵🇷", "Dominican Republic": "🇩🇴", "Uruguay": "🇺🇾", "Venezuela": "🇻🇪"
  };
  return flags[country] || "";
}
function toggleActiveButton(command, button) {
  document.execCommand(command, false, '');
  button.classList.toggle('active');
}
async function loadAvailableCandidatesForBatch(batchId) {
  try {
    const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");
    if (!opportunityId) {
      console.error("No opportunityId");
      return;
    }

    // Trae candidatos de la oportunidad y, EN PARALELO, los ya asignados a cualquier batch de esta opp
    const [oppCands, assignedSet] = await Promise.all([
      fetch(`${API_BASE}/opportunities/${opportunityId}/candidates`).then(r => r.json()),
      getAssignedCandidateIdsForOpportunity(opportunityId)
    ]);

    // Filtra: solo "En proceso con Cliente" y NO en ningún batch de esta opp
    const available = (oppCands || []).filter(c =>
      c.stage === "En proceso con Cliente" && !assignedSet.has(c.candidate_id)
    );

    // Pinta lista
    const resultsList = document.getElementById("candidateSearchResults");
    resultsList.innerHTML = "";

    if (!available.length) {
      resultsList.innerHTML = "<li>No candidates available</li>";
    } else {
      available.forEach(c => {
        const li = document.createElement("li");
        li.className = "search-result-item";
        li.dataset.candidateId = c.candidate_id;

        li.innerHTML = `
          <div style="font-weight:600;">${c.name || "(no name)"}</div>
          <div style="font-size:12px;color:#666;">📌 Status: ${c.stage || "—"}</div>
        `;

        li.addEventListener("click", async () => {
          const ok = confirm(`Add ${c.name} to this batch?`);
          if (!ok) return;

          const patchRes = await fetch(`${API_BASE}/candidates/${c.candidate_id}/batch`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ batch_id: batchId })
          });

          if (patchRes.ok) {
            showFriendlyPopup(`✅ ${c.name} added to batch`);
            document.getElementById("batchCandidatePopup").classList.add("hidden");
            await reloadBatchCandidates();
          } else {
            alert(`❌ Error adding ${c.name} to batch`);
          }
        });

        resultsList.appendChild(li);
      });
    }

    // 🔎 Buscador con un único listener (evitamos duplicados en reaperturas)
    const searchInput = document.getElementById("candidateSearchInput");
    searchInput.value = "";
    searchInput.oninput = quickDebounce(() => {
      const term = (searchInput.value || "").toLowerCase();
      document.querySelectorAll(".search-result-item").forEach(item => {
        item.style.display = item.textContent.toLowerCase().includes(term) ? "block" : "none";
      });
    }, 120);

    // Muestra la popup
    document.getElementById("batchCandidatePopup").classList.remove("hidden");
  } catch (err) {
    console.error("Error loading available candidates for batch:", err);
  }
}

async function getAssignedCandidateIdsForOpportunity(opportunityId) {
  // Trae todos los batches de la oportunidad y junta los candidates de cada uno
  const rBatches = await fetch(`${API_BASE}/opportunities/${opportunityId}/batches`);
  const batches = await rBatches.json();
  if (!Array.isArray(batches) || !batches.length) return new Set();

  const lists = await Promise.all(
    batches.map(b =>
      fetch(`${API_BASE}/batches/${b.batch_id}/candidates`).then(r => r.json())
    )
  );

  return new Set(lists.flat().map(c => c.candidate_id));
}
