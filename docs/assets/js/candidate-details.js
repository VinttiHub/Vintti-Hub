// —— Global DnD unlock (necesario para Safari) ——
(function enableGlobalDnD(){
  if (window.__DNDSAFARI_PATCH__) return;
  window.__DNDSAFARI_PATCH__ = true;

  const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
  ['dragenter','dragover','dragleave','drop'].forEach(ev => {
    window.addEventListener(ev, stop, false);
    document.addEventListener(ev, stop, false);
  });
})();
// === WhatsApp (handler único y “live”) ===
const waBtn   = document.getElementById('wa-btn-overview');
const phoneEl = document.getElementById('field-phone');

function currentDigits(){
  return (phoneEl?.innerText || '').replace(/\D/g, '');
}

// Handler único: lee el valor en el momento del click
if (waBtn) {
  waBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();

    const digits = currentDigits();
    if (!digits) {
      // feedback opcional si no hay número
      waBtn.classList.remove('is-visible'); // o muestra un tooltip si prefieres
      return;
    }
    window.open(`https://wa.me/${digits}`, '_blank');
  });
}

// Pinta estado visual (solo muestra/oculta)
function paintWaBtn(){
  if (!waBtn || !phoneEl) return;
  const hasDigits = !!currentDigits();
  waBtn.classList.toggle('is-visible', hasDigits);
}

// Llamadas que mantienen el estado correcto:
paintWaBtn();                       // al cargar
phoneEl?.addEventListener('blur', paintWaBtn);     // al editar y salir
phoneEl?.addEventListener('input', paintWaBtn);    // mientras escriben

window.__VINTTI_WIRED = window.__VINTTI_WIRED || {};

function showCuteToast(messageHtml, duration = 5000) {
  const toast = document.getElementById('cuteToast');
  if (!toast) return;
  toast.innerHTML = messageHtml;
  toast.classList.add('show');
  if (toast.__hideTimer) clearTimeout(toast.__hideTimer);
  toast.__hideTimer = setTimeout(() => {
    toast.classList.remove('show');
    toast.__hideTimer = null;
  }, duration);
}

function showCuteConfirmDialog({
  title = 'Are you sure?',
  message = '',
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  tone = 'default'
} = {}) {
  return new Promise((resolve) => {
    const body = document.body;
    if (!body) {
      resolve(window.confirm(`${title}\n\n${message}`.trim()));
      return;
    }

    const previous = document.querySelector('.cute-confirm-overlay');
    previous?.remove();

    const overlay = document.createElement('div');
    overlay.className = 'cute-confirm-overlay';
    const accent = tone === 'danger' ? '⚠️' : '🤔';
    overlay.innerHTML = `
      <div class="cute-confirm-card" role="dialog" aria-modal="true">
        <div class="cute-confirm-icon" aria-hidden="true">${accent}</div>
        <div class="cute-confirm-copy">
          <h3>${title}</h3>
          <p>${message}</p>
        </div>
        <div class="cute-confirm-actions">
          <button type="button" class="cute-confirm-cancel">${cancelText}</button>
          <button type="button" class="cute-confirm-confirm">${confirmText}</button>
        </div>
        <div class="cute-confirm-note">You can always undo this later.</div>
      </div>
    `;

    body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('is-visible'));

    const confirmBtn = overlay.querySelector('.cute-confirm-confirm');
    const cancelBtn = overlay.querySelector('.cute-confirm-cancel');

    const cleanup = (result) => {
      overlay.classList.remove('is-visible');
      overlay.addEventListener('transitionend', () => overlay.remove(), { once: true });
      document.removeEventListener('keydown', keyHandler);
      resolve(result);
    };

    const keyHandler = (ev) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        cleanup(false);
      } else if (ev.key === 'Enter' && document.activeElement === confirmBtn) {
        ev.preventDefault();
        cleanup(true);
      }
    };

    confirmBtn?.addEventListener('click', () => cleanup(true));
    cancelBtn?.addEventListener('click', () => cleanup(false));
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) cleanup(false);
    });
    document.addEventListener('keydown', keyHandler);
    confirmBtn?.focus();
  });
}

const EQUIPMENT_OPTIONS = [
  { value: "Laptop",     emoji: "💻" },
  { value: "Monitor",    emoji: "🖥️" },
  { value: "Mouse",      emoji: "🖱️" },
  { value: "Keyboard",   emoji: "⌨️" },
  { value: "Headphones", emoji: "🎧" },
  { value: "Dock",       emoji: "🧩" },
  { value: "Phone",      emoji: "📱" },
  { value: "Tablet",     emoji: "📱" },
  { value: "Router",     emoji: "📶" },
  { value: "Chair",      emoji: "💺" }
];
const EQUIP_EMOJI = Object.fromEntries(EQUIPMENT_OPTIONS.map(o => [o.value.toLowerCase(), o.emoji]));
function equipmentEmoji(name){
  if (!name) return '📦';
  return EQUIP_EMOJI[String(name).toLowerCase()] || '📦';
}
// === Helpers para crear salary_update desde inputs ==========================
async function fetchHire(candidateId, apiBase='https://7m6mw95m8y.us-east-2.awsapprunner.com', opportunityId=null){
  const url = new URL(`${apiBase}/candidates/${candidateId}/hire`);
  if (opportunityId) url.searchParams.set('opportunity_id', opportunityId);
  const r = await fetch(url.toString());
  if (!r.ok) throw new Error(`GET hire failed ${r.status}`);
  return r.json();
}
// global cache
window.__currentOppId = null;

async function ensureCurrentOppId(candidateId, apiBase='https://7m6mw95m8y.us-east-2.awsapprunner.com'){
  if (window.__currentOppId) return window.__currentOppId;
  const r = await fetch(`${apiBase}/candidates/${candidateId}/hire_opportunity`);
  const data = await r.json();
  const oppId = Number(data?.opportunity_id) || null;
  if (!oppId) throw new Error('No opportunity_id for this candidate (hire_opportunity not set)');
  window.__currentOppId = oppId;
  return oppId;
}

function todayYmd(){
  const d = new Date();
  const mm = String(d.getMonth()+1).padStart(2,'0');
  const dd = String(d.getDate()).padStart(2,'0');
  return `${d.getFullYear()}-${mm}-${dd}`;
}
function coerceNum(x){
  if (x === undefined || x === null) return null;
  const s = String(x).trim();
  if (s === '') return null;
  let cleaned = s.replace(/[^\d.-]/g, '');

  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}


function isValidNum(n){ return typeof n === 'number' && Number.isFinite(n); }

async function createSalaryUpdateFromInputs(source, candidateId, apiBase='https://7m6mw95m8y.us-east-2.awsapprunner.com'){
  // Modelo confiable (API/caché), NO del pill crudo
  const modelLower = await ensureOppModelLower(candidateId, apiBase);
  const isRecruiting = (modelLower === 'recruiting');
  const isStaffing   = (modelLower === 'staffing');

  // leer inputs actuales
  const salIn = document.getElementById('hire-salary');
  const feeIn = document.getElementById('hire-fee');
  const revIn = document.getElementById('hire-revenue');

  const uiSalary  = coerceNum(salIn?.value);
  const uiFee     = coerceNum(feeIn?.value);
  const uiRevenue = coerceNum(revIn?.value);

  // obtener start_date del hire (fallback a hoy)
  let startYmd = null;
  try {
    const hire = await fetchHire(candidateId, apiBase);
    startYmd = (hire.start_date || '').slice(0,10) || null;
  } catch {}
  const dateYmd = startYmd || todayYmd();

const body = { date: dateYmd };

if (isStaffing){
  if (source === 'revenue'){
    if (isValidNum(uiSalary) && isValidNum(uiRevenue)){
      body.salary = uiSalary;
      body.fee    = uiRevenue - uiSalary;
    } else {
      if (isValidNum(uiSalary)) body.salary = uiSalary;
      if (isValidNum(uiFee))    body.fee    = uiFee;
    }
  } else {
    if (isValidNum(uiSalary)) body.salary = uiSalary;
    if (isValidNum(uiFee))    body.fee    = uiFee;
  }
} else {
  // Recruiting
  if (isValidNum(uiSalary)) body.salary = uiSalary;

  // 🔒 Anti-400: algunos backends esperan ver al menos UNO; manda fee=0 explícito
  if (!isValidNum(body.fee)) body.fee = 0;
}

// ⛔️ Si NO hay nada real que guardar (salary ni fee numéricos), no postees
if (!isValidNum(body.salary) && !isValidNum(body.fee)) return;

// 🔐 Backend-safe: siempre manda ambas claves numéricas (0 si faltan)
//    así evitamos 'null' por NaN y validaciones estrictas del server.
body.salary = isValidNum(body.salary) ? Number(body.salary) : 0;
body.fee    = isValidNum(body.fee)    ? Number(body.fee)    : 0;

// Asegura fecha simple (algunos servers esperan 'YYYY-MM-DD')
if (/^\d{4}-\d{2}-\d{2}$/.test(body.date)) {
  body.date = body.date; // ok
} else {
  body.date = todayYmd();
}

console.debug('POST /salary_updates payload →', body);

const resp = await fetch(`${apiBase}/candidates/${candidateId}/salary_updates`, {
  method:'POST',
  headers:{'Content-Type':'application/json'},
  body: JSON.stringify(body)
});
if (!resp.ok){
  const t = await resp.text().catch(()=> '');
  throw new Error(`POST salary_update failed ${resp.status}: ${t}`);
}


  // si no hay nada que guardar, salimos silenciosamente
  if (body.salary == null && body.fee == null) return;

  // refrescar la lista visual
  if (typeof window.loadSalaryUpdates === 'function'){
    await window.loadSalaryUpdates();
  }
  // sincronizar HIRE con el update de fecha más reciente
  await syncHireFromLatestSalaryUpdate(candidateId, apiBase);
}
// Modelo cacheado global para no depender del texto del pill
window.__oppModelLower = ''; // 'staffing' | 'recruiting' | ''

async function ensureOppModelLower(candidateId, apiBase='https://7m6mw95m8y.us-east-2.awsapprunner.com'){
  if (window.__oppModelLower) return window.__oppModelLower;
  try{
    const ho = await fetch(`${apiBase}/candidates/${candidateId}/hire_opportunity`).then(r=>r.json());
    const raw = String(ho?.opp_model||'').toLowerCase().trim();
    // normaliza valores comunes
    if (raw.startsWith('staff')) window.__oppModelLower = 'staffing';
    else if (raw.startsWith('recr')) window.__oppModelLower = 'recruiting';
    else window.__oppModelLower = '';
  }catch{ /* ignore */ }

  // Fallback muy estricto al pill: solo si empieza por la palabra
  if (!window.__oppModelLower){
    const txt = (document.getElementById('opp-model-pill')?.textContent || '').toLowerCase().trim();
    if (/^\s*staffing\b/.test(txt)) window.__oppModelLower = 'staffing';
    else if (/^\s*recruiting\b/.test(txt)) window.__oppModelLower = 'recruiting';
  }
  return window.__oppModelLower;
}

// Devuelve 'staffing' | 'recruiting' | '' leyendo el pill (o '' si no hay)
function getOppModelLower(){
  const txt = (document.getElementById('opp-model-pill')?.textContent || '').toLowerCase();
  if (txt.includes('staffing')) return 'staffing';
  if (txt.includes('recruiting')) return 'recruiting';
  return '';
}

// --- FECHAS ROBUSTAS PARA SALARY UPDATES ----------------------------------
// Convierte "YYYY-MM-DD", "YYYY/MM/DD", "YYYY-MM-DDTHH:mm..." a una clave numérica YYYYMMDD
function ymdKey(dateLike){
  const s = String(dateLike || '').trim();
  // Busca 3 grupos numéricos en formato Y-M-D con separador '-' o '/'
  const m = s.match(/(\d{4})[\/-](\d{1,2})[\/-](\d{1,2})/);
  if (!m) return -Infinity;
  const y = Number(m[1]), mm = Number(m[2]), dd = Number(m[3]);
  if (!y || !mm || !dd) return -Infinity;
  return y * 10000 + mm * 100 + dd; // p.ej. 2025-09-04 → 20250904
}

// Devuelve timestamp ms (o 0)
function ts(x){
  const t = Date.parse(x || '');
  return Number.isFinite(t) ? t : 0;
}

// ⬇️ Reemplaza compareYmd, _latestSortKey y pickLatestSalaryUpdate por esto:
function pickLatestSalaryUpdate(updates){
  const arr = Array.isArray(updates) ? updates.filter(u => u && u.date) : [];
  if (!arr.length) return null;

  // Ordena DESC por fecha efectiva; desempata por created_at DESC y update_id DESC
  arr.sort((a, b) => {
    const ka = ymdKey(a.date);
    const kb = ymdKey(b.date);
    if (ka !== kb) return kb - ka;
    const ca = ts(a.created_at);
    const cb = ts(b.created_at);
    if (ca !== cb) return cb - ca;
    const ua = Number(a.update_id) || 0;
    const ub = Number(b.update_id) || 0;
    return ub - ua;
  });

  return arr[0] || null;
}



// Calcula revenue sólo para Staffing (recruiting no se toca aquí)
function calcRevenueForStaffing(salary, fee){
  const s = Number(salary); const f = Number(fee);
  if (!Number.isFinite(s)) return null;
  if (!Number.isFinite(f)) return null;
  return s + f;
}

// Aplica un salary update al HIRE vía PATCH (respeta el modelo)
async function patchHireFromUpdate(candidateId, update, apiBase='https://7m6mw95m8y.us-east-2.awsapprunner.com'){
  if (!candidateId || !update) return;

  const oppId = await ensureCurrentOppId(candidateId, apiBase); // 🔑
  const model = getOppModelLower();

  const payload = { opportunity_id: oppId }; // 🔑 base
  if (update.salary != null && update.salary !== '') payload.employee_salary = Number(update.salary);

  if (model === 'staffing' && update.fee != null && update.fee !== '') {
    payload.employee_fee = Number(update.fee);
    const rev = calcRevenueForStaffing(update.salary, update.fee);
    if (rev != null) payload.employee_revenue = rev;
  }

  if (Object.keys(payload).length <= 1) return; // nothing but opp_id

  await fetch(`${apiBase}/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
}

// Trae todos los salary_updates, elige el más reciente y lo aplica al Hire
// Trae todos los salary_updates, elige el más reciente y lo aplica al Hire
async function syncHireFromLatestSalaryUpdate(candidateId, apiBase='https://7m6mw95m8y.us-east-2.awsapprunner.com'){
  if (!candidateId) return;
  try {
    // 1) updates y último
    const list   = await fetch(`${apiBase}/candidates/${candidateId}/salary_updates`).then(r=>r.json());
    const latest = pickLatestSalaryUpdate(list);
    if (!latest) return;

    // 2) hire actual
    const hire  = await fetch(`${apiBase}/candidates/${candidateId}/hire`).then(x=>x.json());

    // 3) modelo desde la API (fallback al pill si algo falla)
    let modelLower = '';
    try {
      const ho = await fetch(`${apiBase}/candidates/${candidateId}/hire_opportunity`).then(r=>r.json());
      modelLower = String(ho?.opp_model || '').toLowerCase();
    } catch {}
    if (!modelLower) {
      const txt = (document.getElementById('opp-model-pill')?.textContent || '').toLowerCase();
      if (txt.includes('staffing')) modelLower = 'staffing';
      else if (txt.includes('recruiting')) modelLower = 'recruiting';
    }

    // 4) números
    const latestSalary = Number(latest.salary);
    const latestFee    = Number(latest.fee);
    const hasLatestSalary = Number.isFinite(latestSalary);
    const hasLatestFee    = Number.isFinite(latestFee);

    const hireSalary   = Number(hire.employee_salary);
    const hireFee      = Number(hire.employee_fee);
    const hireRev      = Number(hire.employee_revenue);

    // 5) decidir qué setear
    const shouldSetSalary = hasLatestSalary && latestSalary !== hireSalary;

    // fee/revenue sólo para staffing; si no sabemos el modelo pero hay fee válido, lo aplicamos igual
    const isStaffing = (modelLower === 'staffing') || (!modelLower && hasLatestFee);

    let shouldSetFee = false, shouldSetRev = false, newRev = null;
    if (isStaffing) {
      if (hasLatestFee) shouldSetFee = latestFee !== hireFee;
      if (hasLatestSalary && hasLatestFee) {
        newRev = latestSalary + latestFee;
        if (Number.isFinite(newRev)) shouldSetRev = newRev !== hireRev;
      }
    }

    // 6) PATCH si hay algo por cambiar
if (shouldSetSalary || shouldSetFee || shouldSetRev) {
  // 🔑 Asegura opp_id para el backend
  const oppId = await ensureCurrentOppId(candidateId, apiBase); // <- usa apiBase

  const payload = { opportunity_id: oppId };
  if (shouldSetSalary) payload.employee_salary = latestSalary;
  if (isStaffing) {
    if (shouldSetFee) payload.employee_fee = latestFee;
    if (shouldSetRev && newRev != null) payload.employee_revenue = newRev;
  }

  console.debug('PATCH /hire payload →', payload);

  const r = await fetch(`${apiBase}/candidates/${candidateId}/hire`, { // <- usa apiBase
    method: 'PATCH',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });

  if (!r.ok){
    const msg = await r.text().catch(()=> '');
    console.error('❌ PATCH /hire failed', r.status, msg);
    throw new Error(`PATCH /hire ${r.status}: ${msg}`);
  }
}


    // 7) refrescar UI si existe
    if (typeof window.loadHireData === 'function') window.loadHireData();
  } catch(e){
    console.warn('syncHireFromLatestSalaryUpdate failed', e);
  }
}



function normalizeDateForAPI(ymd) {
  const s = String(ymd || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return s; 
  return `${s}T12:00:00`;
}

const INACTIVE_EMAIL_TO = ['angie@vintti.com', 'lara@vintti.com'];
const SEND_EMAIL_ENDPOINT = 'https://7m6mw95m8y.us-east-2.awsapprunner.com/send_email';
let candidateOverviewData = null;

function notifyCandidateInactiveEmail({
  candidateId,
  candidateName,
  clientName,
  roleName,
  endDate,
  opportunityId
}) {
  if (!endDate) return Promise.resolve();

  const displayName = (candidateName || '').trim() || `Candidate #${candidateId}`;
  const subject = `Inactive candidate – ${displayName}`;
  const detailRows = [
    { label: 'End date', value: endDate },
    { label: 'Client', value: clientName },
    { label: 'Role', value: roleName },
    { label: 'Opportunity ID', value: opportunityId }
  ].filter(item => item.value);

  const detailHtml = detailRows.length
    ? `<div style="background:#f5f7fa;border-radius:14px;padding:18px 20px;margin:0 0 20px;">
        ${detailRows.map(item => `<p style="margin:0 0 10px;font-size:15px;color:#111927;">
          <span style="font-weight:600;">${item.label}:</span> ${item.value}
        </p>`).join('')}
      </div>`
    : '';

  const htmlBody = `
    <div style="font-family:'Inter','Segoe UI',Arial,sans-serif;font-size:15px;line-height:1.65;color:#243B53;">
      <p style="margin:0 0 18px;font-size:16px;">Hi Lara,</p>
      <p style="margin:0 0 18px;">
        <strong>${displayName}</strong> has just been marked as
        <strong style="color:#b42318;">inactive</strong>.
      </p>
      ${detailHtml}
      <p style="margin:0 0 16px;">
        Please proceed with the <strong>billing adjustments</strong> and coordinate the
        <strong>laptop pickup</strong> with the client.
      </p>
      <p style="margin:0;font-size:14px;color:#52606d;">
        Thanks,<br/>
        <strong>Vintti Hub</strong>
      </p>
    </div>
  `.trim();

  return fetch(SEND_EMAIL_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      to: INACTIVE_EMAIL_TO,
      subject,
      body: htmlBody
    })
  })
  .then(res => {
    if (!res.ok) {
      return res.text().then(text => {
        throw new Error(`send_email failed ${res.status}: ${text}`);
      });
    }
    console.log(`📨 Notified Lara about inactive candidate ${candidateId}`);
  })
  .catch(err => console.error('❌ Failed to notify Lara about inactive candidate', err));
}

document.addEventListener("DOMContentLoaded", () => {

  // --- URL / Candidate id ---
  const urlParams   = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get('id'); // ⚠️ NO hagas return todavía

  // --- AI Button / Client Version / Popup wiring (independiente de candidateId) ---
  const aiPopup   = document.getElementById('ai-popup');
  const aiClose   = document.getElementById('ai-close');
  // --- Tabs + visibilidad de pills (UNA sola implementación) ---
  const aiButton   = document.getElementById('ai-action-button');
  const clientBtn  = document.getElementById('client-version-btn');

  function setActiveTab(tabId) {
    // pestañas
    document.querySelectorAll('.tab')
      .forEach(t => t.classList.toggle('active', t.dataset.tab === tabId));
    document.querySelectorAll('.tab-content')
      .forEach(c => c.classList.toggle('active', c.id === tabId));

    // cargas perezosas
    if (tabId === 'opportunities') window.loadOpportunitiesForCandidate?.();
    if (tabId === 'hire')          window.loadHireData?.();
    if (tabId === 'overview') {
      window.loadCVs?.();
      window.loadCandidateTests?.();
    }

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
  const API_BASE =
  (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
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

  const introLinkEl = document.getElementById('ai-intro-call-link');
  const introEl = document.getElementById('ai-intro-call-transcript');
  const deepDiveLinkEl = document.getElementById('ai-deep-dive-link');
  const deepDiveEl = document.getElementById('ai-deep-dive-transcript');
  const firstInterviewLinkEl = document.getElementById('ai-first-interview-link');
  const firstInterviewEl = document.getElementById('ai-first-interview-transcript');
  const commentsEl = document.getElementById('ai-comments');

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
      let linkedin_scrapper = '';
      let cv_pdf_scrapper   = '';
      const intro_call_link = (introLinkEl?.value || '').trim();
      const intro_call_transcript = (introEl?.value || '').trim();
      const deep_dive_link = (deepDiveLinkEl?.value || '').trim();
      const deep_dive_transcript = (deepDiveEl?.value || '').trim();
      const first_interview_link = (firstInterviewLinkEl?.value || '').trim();
      const first_interview_transcript = (firstInterviewEl?.value || '').trim();
      const notes = (commentsEl?.value || '').trim();
      let hasLinkedinUrl = false, hasAnyCvFile = false;

      try {
        const cand = await fetch(`${API_BASE}/candidates/${candidateId}`).then(r=>r.json());
        linkedin_scrapper = (cand.linkedin_scrapper || cand.coresignal_scrapper || '').trim();
        cv_pdf_scrapper = (cand.cv_pdf_scrapper || cand.affinda_scrapper || '').trim();
        hasLinkedinUrl = !!(cand.linkedin || '').trim();
      } catch {}
      try {
        const files = await fetch(`${API_BASE}/candidates/${candidateId}/cvs`).then(r=>r.json());
        hasAnyCvFile = Array.isArray(files) && files.length>0;
      } catch {}

      const hasAnySource = !!(
        linkedin_scrapper ||
        cv_pdf_scrapper ||
        intro_call_link ||
        intro_call_transcript ||
        deep_dive_link ||
        deep_dive_transcript ||
        first_interview_link ||
        first_interview_transcript ||
        hasLinkedinUrl ||
        hasAnyCvFile
      );
      if (!hasAnySource) {
        alert('Please add LinkedIn, CV, or call transcript info before generating.');
        return;
      }

      // 3) generar
      const resp = await fetch(`${API_BASE}/generate_resume_fields`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({
          candidate_id: candidateId,
          linkedin_scrapper,
          cv_pdf_scrapper,
          intro_call_link,
          intro_call_transcript,
          deep_dive_link,
          deep_dive_transcript,
          first_interview_link,
          first_interview_transcript,
          notes
        })
      });
      if (!resp.ok) {
        const errText = await resp.text();
        throw new Error(errText || 'Failed to generate resume');
      }
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
      alert(err?.message || 'Something went wrong while generating the resume.');
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
  const CD_US_STATES = [
    { code: 'AL', name: 'Alabama' },
    { code: 'AK', name: 'Alaska' },
    { code: 'AZ', name: 'Arizona' },
    { code: 'AR', name: 'Arkansas' },
    { code: 'CA', name: 'California' },
    { code: 'CO', name: 'Colorado' },
    { code: 'CT', name: 'Connecticut' },
    { code: 'DE', name: 'Delaware' },
    { code: 'FL', name: 'Florida' },
    { code: 'GA', name: 'Georgia' },
    { code: 'HI', name: 'Hawaii' },
    { code: 'ID', name: 'Idaho' },
    { code: 'IL', name: 'Illinois' },
    { code: 'IN', name: 'Indiana' },
    { code: 'IA', name: 'Iowa' },
    { code: 'KS', name: 'Kansas' },
    { code: 'KY', name: 'Kentucky' },
    { code: 'LA', name: 'Louisiana' },
    { code: 'ME', name: 'Maine' },
    { code: 'MD', name: 'Maryland' },
    { code: 'MA', name: 'Massachusetts' },
    { code: 'MI', name: 'Michigan' },
    { code: 'MN', name: 'Minnesota' },
    { code: 'MS', name: 'Mississippi' },
    { code: 'MO', name: 'Missouri' },
    { code: 'MT', name: 'Montana' },
    { code: 'NE', name: 'Nebraska' },
    { code: 'NV', name: 'Nevada' },
    { code: 'NH', name: 'New Hampshire' },
    { code: 'NJ', name: 'New Jersey' },
    { code: 'NM', name: 'New Mexico' },
    { code: 'NY', name: 'New York' },
    { code: 'NC', name: 'North Carolina' },
    { code: 'ND', name: 'North Dakota' },
    { code: 'OH', name: 'Ohio' },
    { code: 'OK', name: 'Oklahoma' },
    { code: 'OR', name: 'Oregon' },
    { code: 'PA', name: 'Pennsylvania' },
    { code: 'RI', name: 'Rhode Island' },
    { code: 'SC', name: 'South Carolina' },
    { code: 'SD', name: 'South Dakota' },
    { code: 'TN', name: 'Tennessee' },
    { code: 'TX', name: 'Texas' },
    { code: 'UT', name: 'Utah' },
    { code: 'VT', name: 'Vermont' },
    { code: 'VA', name: 'Virginia' },
    { code: 'WA', name: 'Washington' },
    { code: 'WV', name: 'West Virginia' },
    { code: 'WI', name: 'Wisconsin' },
    { code: 'WY', name: 'Wyoming' },
    { code: 'DC', name: 'District of Columbia' }
  ];
  const CD_US_STATE_MAP = CD_US_STATES.reduce((acc, entry) => {
    acc[entry.code] = entry.name;
    return acc;
  }, {});
  const CD_US_STATE_LABEL_TO_CODE = CD_US_STATES.reduce((acc, entry) => {
    const label = `${entry.name} (${entry.code})`.toLowerCase();
    acc[label] = entry.code;
    acc[entry.code.toLowerCase()] = entry.code;
    return acc;
  }, {});
  const CD_USA_STATE_REGEX = /^USA\s+([A-Z]{2})$/i;
  const WORLD_COUNTRIES = [
    { name: 'Afghanistan', code: 'AF' },
    { name: 'Albania', code: 'AL' },
    { name: 'Algeria', code: 'DZ' },
    { name: 'Andorra', code: 'AD' },
    { name: 'Angola', code: 'AO' },
    { name: 'Antigua and Barbuda', code: 'AG' },
    { name: 'Argentina', code: 'AR' },
    { name: 'Armenia', code: 'AM' },
    { name: 'Australia', code: 'AU' },
    { name: 'Austria', code: 'AT' },
    { name: 'Azerbaijan', code: 'AZ' },
    { name: 'Bahamas', code: 'BS' },
    { name: 'Bahrain', code: 'BH' },
    { name: 'Bangladesh', code: 'BD' },
    { name: 'Barbados', code: 'BB' },
    { name: 'Belarus', code: 'BY' },
    { name: 'Belgium', code: 'BE' },
    { name: 'Belize', code: 'BZ' },
    { name: 'Benin', code: 'BJ' },
    { name: 'Bhutan', code: 'BT' },
    { name: 'Bolivia', code: 'BO' },
    { name: 'Bosnia and Herzegovina', code: 'BA' },
    { name: 'Botswana', code: 'BW' },
    { name: 'Brazil', code: 'BR' },
    { name: 'Brunei', code: 'BN' },
    { name: 'Bulgaria', code: 'BG' },
    { name: 'Burkina Faso', code: 'BF' },
    { name: 'Burundi', code: 'BI' },
    { name: 'Cabo Verde', code: 'CV' },
    { name: 'Cambodia', code: 'KH' },
    { name: 'Cameroon', code: 'CM' },
    { name: 'Canada', code: 'CA' },
    { name: 'Central African Republic', code: 'CF' },
    { name: 'Chad', code: 'TD' },
    { name: 'Chile', code: 'CL' },
    { name: 'China', code: 'CN' },
    { name: 'Colombia', code: 'CO' },
    { name: 'Comoros', code: 'KM' },
    { name: 'Congo', code: 'CG' },
    { name: 'Costa Rica', code: 'CR' },
    { name: "Cote d'Ivoire", code: 'CI' },
    { name: 'Croatia', code: 'HR' },
    { name: 'Cuba', code: 'CU' },
    { name: 'Cyprus', code: 'CY' },
    { name: 'Czechia', code: 'CZ' },
    { name: 'Democratic Republic of the Congo', code: 'CD' },
    { name: 'Denmark', code: 'DK' },
    { name: 'Djibouti', code: 'DJ' },
    { name: 'Dominica', code: 'DM' },
    { name: 'Dominican Republic', code: 'DO' },
    { name: 'Ecuador', code: 'EC' },
    { name: 'Egypt', code: 'EG' },
    { name: 'El Salvador', code: 'SV' },
    { name: 'Equatorial Guinea', code: 'GQ' },
    { name: 'Eritrea', code: 'ER' },
    { name: 'Estonia', code: 'EE' },
    { name: 'Eswatini', code: 'SZ' },
    { name: 'Ethiopia', code: 'ET' },
    { name: 'Fiji', code: 'FJ' },
    { name: 'Finland', code: 'FI' },
    { name: 'France', code: 'FR' },
    { name: 'Gabon', code: 'GA' },
    { name: 'Gambia', code: 'GM' },
    { name: 'Georgia', code: 'GE' },
    { name: 'Germany', code: 'DE' },
    { name: 'Ghana', code: 'GH' },
    { name: 'Greece', code: 'GR' },
    { name: 'Grenada', code: 'GD' },
    { name: 'Guatemala', code: 'GT' },
    { name: 'Guinea', code: 'GN' },
    { name: 'Guinea-Bissau', code: 'GW' },
    { name: 'Guyana', code: 'GY' },
    { name: 'Haiti', code: 'HT' },
    { name: 'Honduras', code: 'HN' },
    { name: 'Hungary', code: 'HU' },
    { name: 'Iceland', code: 'IS' },
    { name: 'India', code: 'IN' },
    { name: 'Indonesia', code: 'ID' },
    { name: 'Iran', code: 'IR' },
    { name: 'Iraq', code: 'IQ' },
    { name: 'Ireland', code: 'IE' },
    { name: 'Israel', code: 'IL' },
    { name: 'Italy', code: 'IT' },
    { name: 'Jamaica', code: 'JM' },
    { name: 'Japan', code: 'JP' },
    { name: 'Jordan', code: 'JO' },
    { name: 'Kazakhstan', code: 'KZ' },
    { name: 'Kenya', code: 'KE' },
    { name: 'Kiribati', code: 'KI' },
    { name: 'Kuwait', code: 'KW' },
    { name: 'Kyrgyzstan', code: 'KG' },
    { name: 'Laos', code: 'LA' },
    { name: 'Latvia', code: 'LV' },
    { name: 'Lebanon', code: 'LB' },
    { name: 'Lesotho', code: 'LS' },
    { name: 'Liberia', code: 'LR' },
    { name: 'Libya', code: 'LY' },
    { name: 'Liechtenstein', code: 'LI' },
    { name: 'Lithuania', code: 'LT' },
    { name: 'Luxembourg', code: 'LU' },
    { name: 'Madagascar', code: 'MG' },
    { name: 'Malawi', code: 'MW' },
    { name: 'Malaysia', code: 'MY' },
    { name: 'Maldives', code: 'MV' },
    { name: 'Mali', code: 'ML' },
    { name: 'Malta', code: 'MT' },
    { name: 'Marshall Islands', code: 'MH' },
    { name: 'Mauritania', code: 'MR' },
    { name: 'Mauritius', code: 'MU' },
    { name: 'Mexico', code: 'MX' },
    { name: 'Micronesia', code: 'FM' },
    { name: 'Moldova', code: 'MD' },
    { name: 'Monaco', code: 'MC' },
    { name: 'Mongolia', code: 'MN' },
    { name: 'Montenegro', code: 'ME' },
    { name: 'Morocco', code: 'MA' },
    { name: 'Mozambique', code: 'MZ' },
    { name: 'Myanmar', code: 'MM' },
    { name: 'Namibia', code: 'NA' },
    { name: 'Nauru', code: 'NR' },
    { name: 'Nepal', code: 'NP' },
    { name: 'Netherlands', code: 'NL' },
    { name: 'New Zealand', code: 'NZ' },
    { name: 'Nicaragua', code: 'NI' },
    { name: 'Niger', code: 'NE' },
    { name: 'Nigeria', code: 'NG' },
    { name: 'North Korea', code: 'KP' },
    { name: 'North Macedonia', code: 'MK' },
    { name: 'Norway', code: 'NO' },
    { name: 'Oman', code: 'OM' },
    { name: 'Pakistan', code: 'PK' },
    { name: 'Palau', code: 'PW' },
    { name: 'Palestine', code: 'PS' },
    { name: 'Panama', code: 'PA' },
    { name: 'Papua New Guinea', code: 'PG' },
    { name: 'Paraguay', code: 'PY' },
    { name: 'Peru', code: 'PE' },
    { name: 'Philippines', code: 'PH' },
    { name: 'Poland', code: 'PL' },
    { name: 'Portugal', code: 'PT' },
    { name: 'Qatar', code: 'QA' },
    { name: 'Romania', code: 'RO' },
    { name: 'Russia', code: 'RU' },
    { name: 'Rwanda', code: 'RW' },
    { name: 'Saint Kitts and Nevis', code: 'KN' },
    { name: 'Saint Lucia', code: 'LC' },
    { name: 'Saint Vincent and the Grenadines', code: 'VC' },
    { name: 'Samoa', code: 'WS' },
    { name: 'San Marino', code: 'SM' },
    { name: 'Sao Tome and Principe', code: 'ST' },
    { name: 'Saudi Arabia', code: 'SA' },
    { name: 'Senegal', code: 'SN' },
    { name: 'Serbia', code: 'RS' },
    { name: 'Seychelles', code: 'SC' },
    { name: 'Sierra Leone', code: 'SL' },
    { name: 'Singapore', code: 'SG' },
    { name: 'Slovakia', code: 'SK' },
    { name: 'Slovenia', code: 'SI' },
    { name: 'Solomon Islands', code: 'SB' },
    { name: 'Somalia', code: 'SO' },
    { name: 'South Africa', code: 'ZA' },
    { name: 'South Korea', code: 'KR' },
    { name: 'South Sudan', code: 'SS' },
    { name: 'Spain', code: 'ES' },
    { name: 'Sri Lanka', code: 'LK' },
    { name: 'Sudan', code: 'SD' },
    { name: 'Suriname', code: 'SR' },
    { name: 'Sweden', code: 'SE' },
    { name: 'Switzerland', code: 'CH' },
    { name: 'Syria', code: 'SY' },
    { name: 'Taiwan', code: 'TW' },
    { name: 'Tajikistan', code: 'TJ' },
    { name: 'Tanzania', code: 'TZ' },
    { name: 'Thailand', code: 'TH' },
    { name: 'Timor-Leste', code: 'TL' },
    { name: 'Togo', code: 'TG' },
    { name: 'Tonga', code: 'TO' },
    { name: 'Trinidad and Tobago', code: 'TT' },
    { name: 'Tunisia', code: 'TN' },
    { name: 'Turkey', code: 'TR' },
    { name: 'Turkmenistan', code: 'TM' },
    { name: 'Tuvalu', code: 'TV' },
    { name: 'Uganda', code: 'UG' },
    { name: 'Ukraine', code: 'UA' },
    { name: 'United Arab Emirates', code: 'AE' },
    { name: 'United Kingdom', code: 'GB' },
    { name: 'United States', code: 'US' },
    { name: 'Uruguay', code: 'UY' },
    { name: 'Uzbekistan', code: 'UZ' },
    { name: 'Vanuatu', code: 'VU' },
    { name: 'Vatican City', code: 'VA' },
    { name: 'Venezuela', code: 'VE' },
    { name: 'Vietnam', code: 'VN' },
    { name: 'Yemen', code: 'YE' },
    { name: 'Zambia', code: 'ZM' },
    { name: 'Zimbabwe', code: 'ZW' }
  ];
  const COUNTRY_CODE_BY_NAME = WORLD_COUNTRIES.reduce((acc, item) => {
    acc[item.name] = item.code;
    return acc;
  }, {});
  const WORLD_COUNTRY_NAMES = WORLD_COUNTRIES.map((item) => item.name);

  function getCountryFlag(countryName) {
    const base = normalizeCountryKey(countryName);
    const code = COUNTRY_CODE_BY_NAME[base];
    if (!code) return '';
    return code
      .toUpperCase()
      .replace(/[A-Z]/g, (char) => String.fromCodePoint(127397 + char.charCodeAt(0)));
  }

  function renderCountryOptions(selectEl, countries, selectedValue) {
    if (!selectEl) return;
    const list = countries.slice();
    if (selectedValue && !list.includes(selectedValue)) {
      list.unshift(selectedValue);
    }
    const fragment = document.createDocumentFragment();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '—';
    fragment.appendChild(placeholder);

    if (!list.length) {
      const emptyOption = document.createElement('option');
      emptyOption.value = '';
      emptyOption.textContent = 'No countries match';
      emptyOption.disabled = true;
      fragment.appendChild(emptyOption);
    } else {
      list.forEach((country) => {
        const option = document.createElement('option');
        option.value = country;
        const flag = getCountryFlag(country);
        option.textContent = flag ? `${flag} ${country}` : country;
        fragment.appendChild(option);
      });
    }

    selectEl.innerHTML = '';
    selectEl.appendChild(fragment);
  }

  function normalizeCountryKey(country){
    const value = (country || '').trim();
    if (!value) return '';
    const match = CD_USA_STATE_REGEX.exec(value);
    if (match) return 'United States';
    if (value.toUpperCase() === 'USA') return 'United States';
    return value;
  }

  function extractUsStateCode(country){
    const match = CD_USA_STATE_REGEX.exec(country || '');
    return match ? match[1].toUpperCase() : '';
  }

  function formatCountryDisplay(country){
    if (!country) return '—';
    const code = extractUsStateCode(country);
    if (code) {
    const name = CD_US_STATE_MAP[code] || code;
      return `USA · ${name} (${code})`;
    }
    return country;
  }

  function resolveUsStateCodeFromInput(value){
    if (!value) return '';
    const normalized = value.trim().toLowerCase();
    if (CD_US_STATE_LABEL_TO_CODE[normalized]) return CD_US_STATE_LABEL_TO_CODE[normalized];
    const direct = value.trim().toUpperCase();
    if (CD_US_STATE_MAP[direct]) return direct;
    const match = /\(([A-Z]{2})\)\s*$/.exec(value.trim());
    if (match) {
      const code = match[1].toUpperCase();
      if (CD_US_STATE_MAP[code]) return code;
    }
    return '';
  }

  function getFlagEmoji(countryName) {
    return getCountryFlag(countryName);
  }

  function setUsStateInputValue(inputEl, code) {
    if (!inputEl) return;
    const label = code && CD_US_STATE_MAP[code] ? `${CD_US_STATE_MAP[code]} (${code})` : '';
    inputEl.value = label;
    inputEl.dataset.code = code || '';
  }

  function populateUsStatesDatalist(listEl) {
    if (!listEl) return;
    listEl.innerHTML = '';
    CD_US_STATES.forEach(state => {
      const option = document.createElement('option');
      option.value = `${state.name} (${state.code})`;
      option.dataset.code = state.code;
      listEl.appendChild(option);
    });
  }

  function buildCountryPayload(baseCountry, stateInput) {
    if (normalizeCountryKey(baseCountry) === 'United States') {
      const code = resolveUsStateCodeFromInput(stateInput?.value || '');
      if (!code) return null;
      return `USA ${code}`;
    }
    return baseCountry || '';
  }

  function toggleUsStateField(countryValue, fieldEl, inputEl) {
    if (!fieldEl) return;
    const shouldShow = normalizeCountryKey(countryValue) === 'United States';
    fieldEl.classList.toggle('hidden', !shouldShow);
    if (!shouldShow && inputEl) {
      setUsStateInputValue(inputEl, '');
      inputEl.classList.remove('input-error');
    }
  }

  // --- Patch helpers (Hire) ---
async function patchHireFields(fields = {}, options = {}) {
  if (!candidateId) return;
  const entries = Object.entries(fields || {}).filter(([, value]) => value !== undefined);
  if (!entries.length) return;
  const referenceFieldNames = new Set([
    'reference_1_name',
    'reference_1_position',
    'reference_1_phone',
    'reference_1_email',
    'reference_1_linkedin',
    'reference_2_name',
    'reference_2_position',
    'reference_2_phone',
    'reference_2_email',
    'reference_2_linkedin',
  ]);

  const oppId = await ensureCurrentOppId(candidateId);  // 🔑
  const payload = entries.reduce(
    (acc, [key, value]) => {
      acc[key] = value;
      return acc;
    },
    { opportunity_id: oppId }
  );

  const r = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!r.ok) {
    const t = await r.text().catch(() => '');
    console.error('PATCH /hire failed', r.status, t);
    alert('We couldn’t save this field. Please try again.');
    return;
  }
  const result = await r.json().catch(() => ({}));
  if (entries.every(([key]) => referenceFieldNames.has(key))) {
    if (result && result.updated === false) {
      if (!window.__hireReferenceSaveWarningShown) {
        window.__hireReferenceSaveWarningShown = true;
        console.warn('PATCH /hire did not update reference fields. The deployed backend may need the reference-field changes and DB migration.', { payload, result });
      }
    }
    return;
  }
  if (options.skipReload) return;
  if (typeof window.loadHireData === 'function') window.loadHireData();
}

window.patchHireFields = patchHireFields;
window.updateHireField = function(field, value, options = {}) {
  return patchHireFields({ [field]: value }, options);
};

async function captureInactiveMetadataFromModal({ candidateName, clientName, roleName } = {}) {
  if (typeof window.openInactiveInfoModal !== 'function') return null;
  try {
    const modalResult = await window.openInactiveInfoModal({
      candidateName,
      clientName,
      roleName
    });
    if (!modalResult) return null;

    const trimmedComments = modalResult.comments?.trim();
    const normalizedComments = trimmedComments ? trimmedComments : null;
    await patchHireFields({
      inactive_reason: modalResult.reason,
      inactive_comments: normalizedComments,
      inactive_vinttierror: Boolean(modalResult.vinttiError)
    });
    if (typeof showCuteToast === 'function') {
      showCuteToast('Offboarding info saved ✅');
    }
    return {
      reason: modalResult.reason,
      comments: normalizedComments,
      vinttiError: Boolean(modalResult.vinttiError)
    };
  } catch (err) {
    console.error('❌ Failed to store inactive metadata', err);
    alert('We saved the end date but could not store the offboarding info. Please try again.');
    return null;
  }
}

  // --- Restore Hire dates con <input type="date"> nativo ---
  (function restoreHireDates() {
    const hostStart = document.getElementById('hire-start-picker');
    const hostEnd   = document.getElementById('hire-end-picker');

    // Montar inputs nativos si no existen
    if (hostStart && !hostStart.querySelector('input[type="date"]')) {
      hostStart.innerHTML = '<input type="date" id="hire-start-date" />';
    }
    if (hostEnd && !hostEnd.querySelector('input[type="date"]')) {
      hostEnd.innerHTML = '<input type="date" id="hire-end-date" />';
    }

    const startInp = document.getElementById('hire-start-date');
    const endInp   = document.getElementById('hire-end-date');
    if (endInp) {
      endInp.dataset.previousEndDate = endInp.value || '';
    }

    // ⬅️ cuando cambia START_DATE → guardar start_date y carga_active_date
    if (startInp) {
      startInp.addEventListener('change', async () => {
        const ymd = startInp.value || '';

        // 1) actualiza start_date normal
        await updateHireField(
          'start_date',
          ymd ? normalizeDateForAPI(ymd) : ''
        );

        // 2) registra la “fecha de carga active”
        //    (usa hoy; si prefieres usar la misma ymd, cambia todayYmd() por ymd)
        if (ymd) {
          const today = todayYmd();
          await updateHireField(
            'carga_active',    
            normalizeDateForAPI(today)
          );
        } else {
          // si borran la fecha, limpiamos el campo de carga
          await updateHireField('carga_active', '');
        }
      });
    }

    // ⬅️ cuando cambia END_DATE → guardar end_date y carga_inactive_date
    if (endInp) {
      endInp.addEventListener('change', async () => {
        const ymd = endInp.value || '';
        const prevValue = endInp.dataset.previousEndDate || '';
        const shouldNotify = !prevValue && !!ymd;
        const normalizedEndDate = ymd ? normalizeDateForAPI(ymd) : '';

        const clientName =
          candidateOverviewData?.account_name ||
          candidateOverviewData?.client_name ||
          candidateOverviewData?.account ||
          '';
        const roleName =
          candidateOverviewData?.opp_position_name ||
          candidateOverviewData?.current_position ||
          candidateOverviewData?.title ||
          '';
        const candidateName = candidateOverviewData?.name;

        const persistEndDateFields = async () => {
          await updateHireField('end_date', normalizedEndDate);
          if (ymd) {
            const today = todayYmd();
            await updateHireField('carga_inactive', normalizeDateForAPI(today));
          } else {
            await updateHireField('carga_inactive', '');
          }
        };

        try {
          if (shouldNotify) {
            const modalResult = await captureInactiveMetadataFromModal({
              candidateName,
              clientName,
              roleName
            });
            if (!modalResult) {
              endInp.value = prevValue;
              endInp.dataset.previousEndDate = prevValue;
              return;
            }
          }

          await persistEndDateFields();

          if (shouldNotify) {
            let oppIdForEmail = null;
            try {
              oppIdForEmail = await ensureCurrentOppId(candidateId);
            } catch (err) {
              console.error('Missing opportunity_id while preparing inactive email', err);
            }

            await notifyCandidateInactiveEmail({
              candidateId,
              candidateName,
              clientName,
              roleName,
              endDate: ymd,
              opportunityId: oppIdForEmail
            });
          }

          endInp.dataset.previousEndDate = ymd;
        } catch (err) {
          console.error('Failed to process hire end date change', err);
          endInp.value = prevValue;
          endInp.dataset.previousEndDate = prevValue;
        }
      });
    }
  })();

  // --- Overview: cargar datos del candidato ---
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`)
    .then(r => r.json())
    .then(data => {
      candidateOverviewData = data;
      window.__referenceFeedbackSubmittedRefs = parseSubmittedReferenceFeedbackFromNotes(data.references_notes || '');
      hireReferenceFields.forEach(([id, field]) => {
        const input = document.getElementById(id);
        if (input && input !== document.activeElement) input.value = data[field] || '';
      });
      const candidateReferenceOverviewValues = extractReferenceOverviewValues(data);
      renderReferenceOverview(candidateReferenceOverviewValues);
      loadReferenceFeedbackRequests(window.__currentOppId).catch(console.error);
      if (!hasAnyReferenceOverviewValue(candidateReferenceOverviewValues)) {
        loadCandidateReferenceOverviewFallback().catch(console.error);
      }
      const isBlacklisted = Boolean(data && data.is_blacklisted);
      if (typeof window.__applyBlacklistState === 'function') {
        window.__applyBlacklistState({
          is_blacklisted: isBlacklisted,
          blacklist_id: data && data.blacklist_id ? data.blacklist_id : null
        });
      } else {
        const statusText = document.getElementById('blacklist-status-text');
        if (statusText) {
          statusText.textContent = isBlacklisted
            ? 'Candidate is currently blacklisted.'
            : 'Candidate is not blacklisted.';
          statusText.style.display = 'block';
        }
      }


      updateLinkedInUI(data.linkedin || '');
      // === Address & DNI (tabla candidates, pestaña Hire) ===
      const hireAddressInput = document.getElementById('hire-address');
      const hireDniInput     = document.getElementById('hire-dni');
      const API_CANDIDATES   = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
      const timezoneSelect = document.getElementById('timezoneSelect');
      const timezoneTrigger = document.getElementById('timezoneTrigger');
      const timezoneTriggerLabel = document.getElementById('timezoneTriggerLabel');
      const timezoneDropdown = document.getElementById('timezoneDropdown');
      const timezoneInputs = timezoneSelect ? Array.from(timezoneSelect.querySelectorAll('input[type="checkbox"]')) : [];
      const parseTimezoneValue = (value) => (value || '')
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean);
      const formatTimezoneLabel = (values) => {
        if (!values.length) return 'Select timezones';
        if (values.length === 1) return values[0];
        return `${values.length} selected`;
      };
      const setDropdownOpen = (isOpen) => {
        if (!timezoneDropdown || !timezoneTrigger) return;
        timezoneDropdown.hidden = !isOpen;
        timezoneTrigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      };

      if (timezoneSelect && timezoneTrigger && timezoneDropdown) {
        const selections = new Set(parseTimezoneValue(data.timezone));
        timezoneInputs.forEach((input) => {
          input.checked = selections.has(input.value);
        });
        if (timezoneTriggerLabel) {
          const selected = timezoneInputs.filter((input) => input.checked).map((input) => input.value);
          timezoneTriggerLabel.textContent = formatTimezoneLabel(selected);
        }

        timezoneTrigger.addEventListener('click', (event) => {
          event.preventDefault();
          event.stopPropagation();
          setDropdownOpen(timezoneDropdown.hidden);
        });

        timezoneDropdown.addEventListener('change', () => {
          const selected = timezoneInputs.filter((input) => input.checked).map((input) => input.value);
          if (timezoneTriggerLabel) {
            timezoneTriggerLabel.textContent = formatTimezoneLabel(selected);
          }
          const payload = selected.length ? selected.join(', ') : null;
          fetch(`${API_CANDIDATES}/candidates/${candidateId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ timezone: payload })
          });
        });

        document.addEventListener('click', (event) => {
          if (!timezoneSelect.contains(event.target)) {
            setDropdownOpen(false);
          }
        });
      }

      // Pre-cargar valores desde candidates.address y candidates.dni
      if (hireAddressInput) {
        hireAddressInput.value = data.address || '';
        hireAddressInput.addEventListener('blur', () => {
          const val = hireAddressInput.value.trim();
          fetch(`${API_CANDIDATES}/candidates/${candidateId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address: val || null })
          });
        });
      }

      if (hireDniInput) {
        if (data.dni !== undefined && data.dni !== null) {
          hireDniInput.value = data.dni;
        }
        hireDniInput.addEventListener('blur', () => {
          const raw = hireDniInput.value.trim();

          // Si está vacío, mandamos null; si es número, mandamos número; si no, string
          let num = raw === '' ? null : Number(raw);
          let payloadValue =
            raw === ''            ? null :
            Number.isFinite(num)  ? num  :
                                    raw;

          fetch(`${API_CANDIDATES}/candidates/${candidateId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dni: payloadValue })
          });
        });
      }

      const ownComputerToggle = document.getElementById('own-computer-toggle');
      if (ownComputerToggle) {
        ownComputerToggle.checked = Boolean(data.compu_propia);
        ownComputerToggle.addEventListener('change', () => {
          fetch(`${API_CANDIDATES}/candidates/${candidateId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ compu_propia: ownComputerToggle.checked })
          });
        });
      }
      // Mapeo de campos (overview)
      const overviewFields = {
        'field-name': 'name',
        'field-phone': 'phone',
        'field-email': 'email',
        'field-english-level': 'english_level',
        'field-salary-range': 'salary_range',
        'field-linkedin':      'linkedin',  
      };
            // === WhatsApp (simple como en la tabla) =========================
      const waBtn   = document.getElementById('wa-btn-overview');
      const phoneEl = document.getElementById('field-phone');

      // helper: solo dígitos
      function onlyDigits(s){ return String(s||'').replace(/\D/g, ''); }

function paintWaBtn(){
  if (!waBtn || !phoneEl) return;
  const digits = (phoneEl.innerText || '').replace(/\D/g, '');
  if (digits) {
    waBtn.classList.add('is-visible');
    waBtn.onclick = (e) => {
      e.stopPropagation();
      window.open(`https://wa.me/${digits}`, '_blank');
    };
  } else {
    waBtn.classList.remove('is-visible');
    waBtn.onclick = null;
  }
}

      // refrescar cuando editen el teléfono (tu blur ya hace PATCH)
      phoneEl.addEventListener('blur', paintWaBtn);
      paintWaBtn();
      Object.entries(overviewFields).forEach(([elementId, fieldName]) => {
        const el = document.getElementById(elementId);
        if (!el) return;

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
      });

      // País → bandera
      const countrySelect = document.getElementById('field-country');
      const countrySearchInput = document.getElementById('country-search');
      const countryFlagSpan = document.getElementById('country-flag');
      const usStateField = document.getElementById('us-state-field');
      const usStateInput = document.getElementById('us-state-input');
      const usStateList = document.getElementById('us-states-list');
      populateUsStatesDatalist(usStateList);

      const initialBaseCountry = normalizeCountryKey(data.country || '');
      const initialStateCode = extractUsStateCode(data.country);
      const setCountrySelectExpanded = (expanded, visibleCount = 8) => {
        if (!countrySelect) return;
        if (expanded) {
          countrySelect.size = Math.max(4, Math.min(visibleCount, 8));
          countrySelect.classList.add('country-select--expanded');
        } else {
          countrySelect.size = 1;
          countrySelect.classList.remove('country-select--expanded');
        }
      };
      const renderCountriesForTerm = (term = '') => {
        if (!countrySelect) return;
        const normalized = term.trim().toLowerCase();
        const matches = normalized
          ? WORLD_COUNTRY_NAMES.filter((country) => country.toLowerCase().includes(normalized))
          : WORLD_COUNTRY_NAMES.slice();
        const selectedValue = countrySelect.value || initialBaseCountry;
        renderCountryOptions(countrySelect, matches, selectedValue);
        if (selectedValue) {
          countrySelect.value = selectedValue;
        }
        const shouldExpand = countrySearchInput
          && (document.activeElement === countrySearchInput || (countrySearchInput.value || '').trim());
        if (shouldExpand) {
          setCountrySelectExpanded(true, matches.length + 1);
        }
      };

      renderCountriesForTerm('');
      if (countrySearchInput) {
        countrySearchInput.addEventListener('focus', () => {
          renderCountriesForTerm(countrySearchInput.value);
        });
        countrySearchInput.addEventListener('input', (event) => {
          renderCountriesForTerm(event.target.value);
        });
        countrySearchInput.addEventListener('blur', () => {
          setTimeout(() => {
            if (document.activeElement !== countrySelect) {
              setCountrySelectExpanded(false);
            }
          }, 0);
        });
      }
      if (countrySelect) {
        countrySelect.value = initialBaseCountry;
        countrySelect.addEventListener('change', () => {
          setCountrySelectExpanded(false);
        });
        countrySelect.addEventListener('blur', () => {
          setCountrySelectExpanded(false);
        });
      }
      if (usStateInput) {
        setUsStateInputValue(usStateInput, initialStateCode);
      }
      toggleUsStateField(initialBaseCountry, usStateField, usStateInput);
      if (countryFlagSpan) {
        countryFlagSpan.textContent = getFlagEmoji(data.country || initialBaseCountry);
      }

      const persistCountryValue = (requireState = false) => {
        if (!countrySelect) return;
        const payloadValue = buildCountryPayload(countrySelect.value, usStateInput);
        if (payloadValue === null) {
          if (requireState && usStateInput) {
            usStateInput.classList.add('input-error');
            if (usStateInput.reportValidity) {
              usStateInput.setCustomValidity('Select a valid state for United States');
              usStateInput.reportValidity();
            }
          }
          return;
        }
        if (usStateInput) {
          usStateInput.classList.remove('input-error');
          if (usStateInput.setCustomValidity) usStateInput.setCustomValidity('');
        }
        fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ country: payloadValue })
        });
        if (countryFlagSpan) countryFlagSpan.textContent = getFlagEmoji(payloadValue || countrySelect.value);
      };

      if (countrySelect) {
        countrySelect.addEventListener('change', () => {
          toggleUsStateField(countrySelect.value, usStateField, usStateInput);
          if (normalizeCountryKey(countrySelect.value) !== 'United States') {
            persistCountryValue(false);
          }
        });
      }
      if (usStateInput) {
        usStateInput.addEventListener('input', () => {
          usStateInput.dataset.code = resolveUsStateCodeFromInput(usStateInput.value) || '';
        });
        usStateInput.addEventListener('change', () => {
          if (normalizeCountryKey(countrySelect?.value || '') === 'United States') {
            persistCountryValue(false);
          }
        });
        usStateInput.addEventListener('blur', () => {
          if (normalizeCountryKey(countrySelect?.value || '') === 'United States') {
            persistCountryValue(true);
          }
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

      const richFactory = window.RichComments && typeof window.RichComments.enhance === 'function';
      const ensureCandidatePatch = (field, value) => {
        if (!candidateId) return;
        const payloadValue = value === undefined || value === null ? '' : value;
        fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [field]: payloadValue })
        }).catch((err) => console.warn(`Failed to update ${field}`, err));
      };

      if (richFactory) {
        const redFlagsEditor = window.RichComments.enhance('redFlags', {
          placeholder: 'No red flags',
          onBlur: (html) => ensureCandidatePatch('red_flags', html)
        });
        if (redFlagsEditor) redFlagsEditor.setHTML(data.red_flags || '');

        const commentsEditor = window.RichComments.enhance('comments', {
          placeholder: 'No comments',
          onBlur: (html) => ensureCandidatePatch('comments', html)
        });
        if (commentsEditor) commentsEditor.setHTML(data.comments || '');
      } else {
        (['redFlags','comments']).forEach((id) => {
          const ta = document.getElementById(id);
          if (!ta) return;
          ta.value = id === 'redFlags' ? (data.red_flags || '') : (data.comments || '');
          ta.addEventListener('blur', () => {
            const field = id === 'redFlags' ? 'red_flags' : 'comments';
            ensureCandidatePatch(field, ta.value.trim());
          });
        });
      }

      const otherProcessInput = document.getElementById('other-process');
      if (otherProcessInput) {
        otherProcessInput.value = data.other_process || '';
        otherProcessInput.addEventListener('blur', () => {
          ensureCandidatePatch('other_process', otherProcessInput.value.trim());
        });
      }

      const vacationsInput = document.getElementById('vacations');
      if (vacationsInput) {
        vacationsInput.value = data.vacations || '';
        vacationsInput.addEventListener('blur', () => {
          ensureCandidatePatch('vacations', vacationsInput.value.trim());
        });
      }

      const usaNationalityInput = document.getElementById('usa-nationality');
      if (usaNationalityInput) {
        usaNationalityInput.checked = Boolean(data.usa_nationality);
        usaNationalityInput.addEventListener('change', () => {
          ensureCandidatePatch('usa_nationality', usaNationalityInput.checked);
        });
      }

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
function renderEquipmentChips(items){
  const host = document.getElementById('equipments-chips');
  if (!host) return;
  host.innerHTML = '';
  const arr = Array.isArray(items) ? items : (items ? [items] : []);
  if (!arr.length) { host.textContent = '—'; return; }

  arr.forEach(val => {
    const chip = document.createElement('span');
    chip.className = 'chip equip-chip';
    const emoji = equipmentEmoji(val);
    chip.textContent = `${emoji} ${val}`;
    host.appendChild(chip);
  });
}

async function loadEquipmentsForCandidate(cid){
  try{
    const r = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${cid}/equipments`);
    const data = await r.json();
    renderEquipmentChips(data);
  } catch(e){
    console.warn('equipments load failed', e);
  }
}
// Equipments: chips + link "Details"
loadEquipmentsForCandidate(candidateId);
const eqLink = document.getElementById('equipments-details-link');
if (eqLink) eqLink.href = `equipments.html?candidate_id=${encodeURIComponent(candidateId)}`;
function wireRichToolbar(toolbarId){
  const tb = document.getElementById(toolbarId);
  if (!tb || tb.__wired) return;
  tb.__wired = true;

  tb.querySelectorAll('button[data-command]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const targetId = btn.getAttribute('data-target');
      const cmd = btn.getAttribute('data-command');
      const target = document.getElementById(targetId);
      if (!target) return;
      target.focus();
      document.execCommand(cmd, false, null);
    });
  });
}
// === Candidate success: cargar, toolbar, guardar ===
wireRichToolbar('candidate-succes-toolbar');

const successDiv = document.getElementById('candidate-succes');
if (successDiv) {
  successDiv.innerHTML = (data.candidate_succes || '');

  // Guardar al salir de foco
  successDiv.addEventListener('blur', () => {
    const html = successDiv.innerHTML.trim();
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
      method: 'PATCH',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ candidate_succes: html })
    });
  });

  // Sanea estilos pegados: ya tienes un listener global para contenteditable;
  // con eso alcanzaría. Si quieres, re-aplicas el mismo estilo aquí.
}

    })
    .catch(err => console.error('❌ Error fetching candidate:', err));

  // Ocultar pestaña Hire si no está contratado
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/is_hired`)
    .then(res => res.json())
  .then(d => {
    const hireTab = document.querySelector('.tab[data-tab="hire"]');
    const hireContent = document.getElementById('hire');
    if (!d.is_hired) {
      if (hireTab) hireTab.style.display = 'none';
      if (hireContent) hireContent.style.display = 'none';
      return;
    }
    loadHireData();
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
(function salaryUpdatesSection(){
  const API = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid = new URLSearchParams(location.search).get('id');

  const box   = document.getElementById('salary-updates-box');
  const open  = document.getElementById('add-salary-update');
  const popup = document.getElementById('salary-update-popup');
  const save  = document.getElementById('save-salary-update');
  const close = document.getElementById('close-salary-update');
  const salIn = document.getElementById('update-salary');
  const feeIn = document.getElementById('update-fee');
  const dateIn= document.getElementById('update-date');

  if (!cid) return;

  // —— helper: formatea "YYYY-MM-DD" sin usar new Date() (evita TZ shi
function formatDateHumanES(isoLike){
  if (!isoLike) return '';
  const ymd = String(isoLike).slice(0, 10); // "YYYY-MM-DD"
  const [y, m, d] = ymd.split('-').map(n => Number(n));
  if (!y || !m || !d) return ymd;
  const meses = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
  return `${String(d).padStart(2,'0')} ${meses[m - 1]} ${y}`;
}



  async function loadSalaryUpdates(){
    if (!box) return;
    const r = await fetch(`${API}/candidates/${cid}/salary_updates`);
    const data = await r.json();

    box.innerHTML = '';
    const header = document.createElement('div');
    header.className = 'salary-entry';
    header.style.fontWeight = 'bold';
    header.innerHTML = `<span>Salary</span><span>Fee</span><span>Date</span><span></span>`;
    box.appendChild(header);

    (data || []).forEach(up => {
      const row = document.createElement('div');
      row.className = 'salary-entry';
      const d = (window.formatDateHumanES ? window.formatDateHumanES(up.date) : formatDateHumanES(up.date));
      row.innerHTML = `
        <span>$${up.salary}</span>
        <span>${up.fee != null ? '$'+up.fee : ''}</span>
        <span>${d}</span>
        <button class="delete-salary-update" data-id="${up.update_id}">🗑️</button>
      `;
      box.appendChild(row);
    });

    // borrar
box.querySelectorAll('.delete-salary-update').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    const id = btn.dataset.id;
    await fetch(`${API}/salary_updates/${id}`, { method:'DELETE' });
    await loadSalaryUpdates();
    await syncHireFromLatestSalaryUpdate(cid, API); // <-- asegura que el HIRE refleje el nuevo “último”
  });
});

  }
  window.loadSalaryUpdates = loadSalaryUpdates;

  // abrir
  if (open && popup){
    open.addEventListener('click', () => {
      popup.classList.remove('hidden');

      // ocultar Fee si el modelo es Recruiting
      const modelText = document.getElementById('opp-model-pill')?.textContent?.toLowerCase() || '';
      const isRecruiting = modelText.includes('recruiting');
      const labels = popup.querySelectorAll('label');
      const feeLabel = labels[1]; // 2° label es "Fee ($)" en tu HTML
      if (feeLabel && feeIn){
        feeLabel.style.display = isRecruiting ? 'none' : '';
        feeIn.style.display    = isRecruiting ? 'none' : '';
      }
    });
  }

  // ❌ cerrar con la X
  function wireSalaryPopupClose(){
    if (!close || !popup) return;
    close.addEventListener('click', ()=> popup.classList.add('hidden'));
    // opcional: Esc para cerrar
    document.addEventListener('keydown', (e)=>{
      if (!popup.classList.contains('hidden') && e.key === 'Escape'){
        popup.classList.add('hidden');
      }
    });
  }
  wireSalaryPopupClose();

  // guardar
if (save){
  save.addEventListener('click', async () => {
    const salary = parseFloat(salIn?.value || '');
    const fee    = parseFloat(feeIn?.value || '');
    const date   = dateIn?.value; // "YYYY-MM-DD"

    const isRecruiting = (document.getElementById('opp-model-pill')?.textContent || '')
                          .toLowerCase().includes('recruiting');

    if (!date || isNaN(salary) || (!isRecruiting && (feeIn?.value === '' || isNaN(fee)))){
      return alert('Please fill all required fields');
    }

    const body = {
      date,
      salary: Number.isFinite(salary) ? Number(salary) : 0,
      // manda fee siempre; 0 en recruiting o si no hay valor
      fee: (!isRecruiting && Number.isFinite(fee)) ? Number(fee) : 0
    };

    await fetch(`${API}/candidates/${cid}/salary_updates`, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });

    // reset + refresco de la lista
    popup?.classList.add('hidden');
    if (salIn)  salIn.value  = '';
    if (feeIn)  feeIn.value  = '';
    if (dateIn) dateIn.value = '';
    await loadSalaryUpdates();

    // ⬇️ NUEVO: sincroniza Hire con el último update y refresca UI
    await syncHireFromLatestSalaryUpdate(cid, API);
  });
}

  // primera carga si estás en Hire, o deja expuesto window.loadSalaryUpdates()
  if (document.querySelector('.tab.active')?.dataset.tab === 'hire') {
    loadSalaryUpdates();
  }
  // ✅ Resignation & References (check_hr_lead) — estado inicial desde BD
// ✅ Estado inicial del checkbox desde BD (autónomo)
(async function loadResigRefInitial(){
  const check = document.getElementById('resig-ref-check');
  if (!check) return;

  const API  = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid  = new URLSearchParams(window.location.search).get('id');
  if (!cid) return;

  try {
    const r = await fetch(`${API}/candidates/${cid}`);
    if (!r.ok) throw 0;
    const row = await r.json();
    const raw = row?.check_hr_lead;

    // normalización flexible → booleano
    const initial = (typeof raw === 'boolean')
      ? raw
      : /^(1|y|yes|true|✓|\[v\])$/i.test(String(raw ?? '').trim());

    check.checked = !!initial;
  } catch(e) {
    console.warn('No se pudo leer check_hr_lead inicial', e);
  }
})();

})(); 

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
const hirePriceType = document.getElementById('hire-price-type');
const hireSetupFee = document.getElementById('hire-setup-fee');
const referencesDiv = document.getElementById('hire-references');
const hireReferenceFields = [
  ['hire-reference-1-name', 'reference_1_name'],
  ['hire-reference-1-position', 'reference_1_position'],
  ['hire-reference-1-phone', 'reference_1_phone'],
  ['hire-reference-1-email', 'reference_1_email'],
  ['hire-reference-1-linkedin', 'reference_1_linkedin'],
  ['hire-reference-2-name', 'reference_2_name'],
  ['hire-reference-2-position', 'reference_2_position'],
  ['hire-reference-2-phone', 'reference_2_phone'],
  ['hire-reference-2-email', 'reference_2_email'],
  ['hire-reference-2-linkedin', 'reference_2_linkedin'],
];

function escapeReferenceHtml(value) {
  return String(value || '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

function stripStructuredReferencesHtml(html = '') {
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html || '';
  wrapper.querySelectorAll('[data-structured-references="true"]').forEach((node) => node.remove());
  return wrapper.innerHTML.trim();
}

function buildStructuredReferencesHtml() {
  const values = Object.fromEntries(hireReferenceFields.map(([id, field]) => [
    field,
    document.getElementById(id)?.value?.trim() || ''
  ]));
  const hasAnyValue = Object.values(values).some(Boolean);
  if (!hasAnyValue) return '';

  const linesFor = (idx) => {
    const prefix = `reference_${idx}`;
    const fields = [
      ['Name', `${prefix}_name`],
      ['Position', `${prefix}_position`],
      ['Phone', `${prefix}_phone`],
      ['Email', `${prefix}_email`],
      ['LinkedIn', `${prefix}_linkedin`],
    ];
    if (!fields.some(([, field]) => values[field])) return '';
    return `
      <p>
        <strong>Reference ${idx}</strong><br>
        ${fields.map(([label, field]) => (
          `<span data-reference-field="${field}"><strong>${label}:</strong> ${escapeReferenceHtml(values[field] || '-')}</span>`
        )).join('<br>')}
      </p>
    `;
  };

  return `<div data-structured-references="true">${linesFor(1)}${linesFor(2)}</div>`;
}

function mergeStructuredReferencesIntoNotes() {
  if (!referencesDiv) return '';
  const manualNotes = stripStructuredReferencesHtml(referencesDiv.innerHTML);
  const structuredReferences = buildStructuredReferencesHtml();
  const merged = [structuredReferences, manualNotes].filter(Boolean).join('<br>');
  referencesDiv.innerHTML = merged;
  return merged;
}

function parseStructuredReferencesFromNotes(html = '') {
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html || '';
  const values = {};
  wrapper.querySelectorAll('[data-reference-field]').forEach((node) => {
    const field = node.getAttribute('data-reference-field');
    const raw = (node.textContent || '').replace(/^[^:]+:\s*/, '').trim();
    values[field] = raw === '-' ? '' : raw;
  });
  return values;
}

function normalizeReferenceLink(value) {
  const clean = String(value || '').trim();
  if (!clean) return '';
  if (/^https?:\/\//i.test(clean)) return clean;
  return `https://${clean.replace(/^\/+/, '')}`;
}

window.__referenceFeedbackRequests = {};
window.__currentReferenceOverviewValues = {};
window.__referenceFeedbackDraft = null;
window.__referenceFeedbackSubmittedRefs = new Set();
const REFERENCE_DELETE_ALLOWED_EMAILS = new Set([
  'agostina@vintti.com',
  'lara@vintti.com',
  'pgonzales@vintti.com',
]);

function referenceFeedbackStorageKey(opportunityId = null) {
  return `reference_feedback_requests:${candidateId}:${opportunityId || 'latest'}`;
}

function encodeReferenceFeedbackPayload(payload) {
  return btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
}

function decodeReferenceFeedbackPayload(value) {
  try {
    return JSON.parse(decodeURIComponent(escape(atob(value))));
  } catch {
    return null;
  }
}

function getStoredReferenceFeedbackRequests(opportunityId = null) {
  try {
    const raw = localStorage.getItem(referenceFeedbackStorageKey(opportunityId));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function setStoredReferenceFeedbackRequests(requests, opportunityId = null) {
  try {
    localStorage.setItem(referenceFeedbackStorageKey(opportunityId), JSON.stringify(requests || {}));
  } catch {}
}

function parseSubmittedReferenceFeedbackFromNotes(html = '') {
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html || '';
  const submitted = new Set();
  wrapper.querySelectorAll('[data-reference-feedback-section]').forEach((node) => {
    const refNum = Number(node.getAttribute('data-reference-feedback-section'));
    if (Number.isFinite(refNum)) submitted.add(refNum);
  });
  return submitted;
}

function extractReferenceOverviewValues(source = {}) {
  return {
    reference_1_name: source.reference_1_name || '',
    reference_1_position: source.reference_1_position || '',
    reference_1_phone: source.reference_1_phone || '',
    reference_1_email: source.reference_1_email || '',
    reference_1_linkedin: source.reference_1_linkedin || '',
    reference_2_name: source.reference_2_name || '',
    reference_2_position: source.reference_2_position || '',
    reference_2_phone: source.reference_2_phone || '',
    reference_2_email: source.reference_2_email || '',
    reference_2_linkedin: source.reference_2_linkedin || '',
  };
}

function hasAnyReferenceOverviewValue(values = {}) {
  return Object.values(values || {}).some((value) => String(value || '').trim());
}

async function loadCandidateReferenceOverviewFallback() {
  try {
    const url = new URL('https://7m6mw95m8y.us-east-2.awsapprunner.com/public/candidate_references/context');
    url.searchParams.set('candidate_id', candidateId);
    if (window.__currentOppId) url.searchParams.set('opportunity_id', window.__currentOppId);
    const res = await fetch(url.toString());
    if (!res.ok) return;
    const data = await res.json();
    const refs = extractReferenceOverviewValues(data?.references || {});
    if (!hasAnyReferenceOverviewValue(refs)) return;

    hireReferenceFields.forEach(([id, field]) => {
      const input = document.getElementById(id);
      if (input && input !== document.activeElement && !String(input.value || '').trim()) {
        input.value = refs[field] || '';
      }
    });

    renderReferenceOverview({
      ...(window.__currentReferenceOverviewValues || {}),
      ...refs,
    });
  } catch (err) {
    console.warn('Unable to load candidate reference overview fallback', err);
  }
}

function getCandidateDisplayName() {
  const current = (document.getElementById('field-name')?.textContent || '').trim();
  return current && current !== '—' ? current : 'the candidate';
}

function getReferenceValuesFromForm(idx) {
  const prefix = `hire-reference-${idx}`;
  return {
    reference_number: idx,
    reference_name: document.getElementById(`${prefix}-name`)?.value?.trim() || '',
    reference_position: document.getElementById(`${prefix}-position`)?.value?.trim() || '',
    reference_phone: document.getElementById(`${prefix}-phone`)?.value?.trim() || '',
    reference_email: document.getElementById(`${prefix}-email`)?.value?.trim() || '',
    reference_linkedin: document.getElementById(`${prefix}-linkedin`)?.value?.trim() || '',
  };
}

function getDefaultReferenceQuestions(candidateName) {
  const label = candidateName || 'the candidate';
  return [
    `What was your working relationship with ${label}? Could you please tell me ${label}'s weaknesses and strengths?`,
    `How would you describe ${label}'s overall performance?`,
    `Why did ${label} leave the company (or why did you stop working together)?`,
    `Would you rehire or work with ${label} again? Why or why not?`,
    `Are there any areas where you feel ${label} might need additional support or development?`,
    `Is there anything else you'd like to share about ${label}'s work style or personality?`,
  ];
}

async function loadReferenceFeedbackRequests(opportunityId = null) {
  try {
    const url = new URL('https://7m6mw95m8y.us-east-2.awsapprunner.com/public/reference_feedback/candidate');
    url.searchParams.set('candidate_id', candidateId);
    const res = await fetch(url.toString());
    if (!res.ok) throw new Error(`Failed to load reference feedback requests (${res.status})`);
    const data = await res.json();
    const requestMap = {};
    const submittedRefs = new Set();
    (data?.items || []).forEach((item) => {
      requestMap[String(item.reference_number)] = item;
      if (item?.submitted_at) submittedRefs.add(Number(item.reference_number));
    });
    window.__referenceFeedbackRequests = requestMap;
    window.__referenceFeedbackSubmittedRefs = submittedRefs;
    setStoredReferenceFeedbackRequests(requestMap, opportunityId);
  } catch (err) {
    console.warn('Failed to load reference feedback requests from backend', err);
    window.__referenceFeedbackRequests = getStoredReferenceFeedbackRequests(opportunityId);
  }
  renderReferenceOverview(window.__currentReferenceOverviewValues || {});
  return window.__referenceFeedbackRequests;
}

function renderReferenceFeedbackActions(idx, hasReference = false) {
  const host = document.getElementById(`overview-reference-${idx}-actions`);
  if (!host) return;

  const requestInfo = window.__referenceFeedbackRequests?.[String(idx)] || null;
  const submitted = window.__referenceFeedbackSubmittedRefs?.has(idx) || Boolean(requestInfo?.submitted_at);
  if (!hasReference) {
    host.innerHTML = '<span class="reference-overview-chip">Complete reference info to create the form</span>';
    return;
  }

  const statusText = submitted
    ? 'Response received'
    : requestInfo
    ? 'Form ready to share'
    : 'No feedback form yet';
  const statusClass = submitted ? 'reference-overview-chip is-complete' : 'reference-overview-chip';
  const buttonLabel = requestInfo ? 'Edit / share feedback form' : 'Create feedback form';
  const viewButton = submitted && requestInfo
    ? `<button type="button" class="reference-overview-action-btn is-secondary" data-reference-feedback-view="${idx}">View responses</button>`
    : '';
  const currentUserEmail = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '').toLowerCase().trim();
  const deleteButton = REFERENCE_DELETE_ALLOWED_EMAILS.has(currentUserEmail)
    ? `<button type="button" class="reference-overview-action-btn is-danger" data-reference-delete="${idx}">Delete reference</button>`
    : '';

  host.innerHTML = `
    <span class="${statusClass}">${statusText}</span>
    ${viewButton}
    <button type="button" class="reference-overview-action-btn" data-reference-feedback-builder="${idx}">
      ${buttonLabel}
    </button>
    ${deleteButton}
  `;
}

async function deleteReference(referenceNumber) {
  const referenceName = window.__currentReferenceOverviewValues?.[`reference_${referenceNumber}_name`] || `Reference ${referenceNumber}`;
  if (!window.confirm(`Delete ${referenceName} and its feedback?`)) return;

  const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/public/candidate_references/delete_reference', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      candidate_id: Number(candidateId),
      opportunity_id: window.__currentOppId || null,
      reference_number: referenceNumber,
    }),
  });
  if (!response.ok) {
    const txt = await response.text().catch(() => '');
    alert(`We could not delete this reference.\n${txt}`);
    return;
  }

  delete window.__referenceFeedbackRequests[String(referenceNumber)];
  window.__referenceFeedbackSubmittedRefs.delete(referenceNumber);
  setStoredReferenceFeedbackRequests(window.__referenceFeedbackRequests, window.__currentOppId);

  const emptyValues = { ...(window.__currentReferenceOverviewValues || {}) };
  ['name', 'position', 'phone', 'email', 'linkedin'].forEach((field) => {
    emptyValues[`reference_${referenceNumber}_${field}`] = '';
  });
  window.__currentReferenceOverviewValues = emptyValues;

  hireReferenceFields.forEach(([id, field]) => {
    if (field.startsWith(`reference_${referenceNumber}_`)) {
      const input = document.getElementById(id);
      if (input) input.value = '';
    }
  });

  renderReferenceOverview(window.__currentReferenceOverviewValues || {});
  if (typeof loadHireData === 'function') {
    loadHireData();
  }
  showCuteToast(`Reference ${referenceNumber} deleted.`);
}

function renderReferenceFeedbackQuestionPreview() {
  const preview = document.getElementById('reference-feedback-question-preview');
  if (!preview) return;
  const draft = window.__referenceFeedbackDraft;
  const questions = Array.isArray(draft?.questions) ? draft.questions : [];
  preview.innerHTML = questions.map((question, index) => `
    <div class="reference-feedback-question-item">
      <div class="reference-feedback-question-number">${index + 1}</div>
      <div class="reference-feedback-question-content">
        <div class="reference-feedback-question-kicker">Question ${index + 1}</div>
        <div class="reference-feedback-question-text">${escapeReferenceHtml(question)}</div>
      </div>
      <button type="button" title="Remove question" data-remove-reference-question="${index}">×</button>
    </div>
  `).join('');
}

function setReferenceFeedbackLink(url = '') {
  const input = document.getElementById('reference-feedback-link');
  if (input) input.value = url || '';
}

function openReferenceFeedbackBuilder(referenceNumber) {
  const modal = document.getElementById('reference-feedback-builder');
  if (!modal) return;

  const reference = getReferenceValuesFromForm(referenceNumber);
  if (!reference.reference_name) {
    alert(`Please complete Reference ${referenceNumber} first.`);
    return;
  }

  const candidateName = getCandidateDisplayName();
  const existing = window.__referenceFeedbackRequests?.[String(referenceNumber)] || null;
  window.__referenceFeedbackDraft = {
    referenceNumber,
    reference,
    candidateName,
    questions: existing?.questions?.length ? [...existing.questions] : getDefaultReferenceQuestions(candidateName),
    publicUrl: existing?.public_url || '',
    submittedAt: existing?.submitted_at || null,
  };

  const target = document.getElementById('reference-feedback-builder-target');
  if (target) target.textContent = `Reference ${referenceNumber} • ${reference.reference_name}`;

  const status = document.getElementById('reference-feedback-builder-status');
  if (status) status.textContent = window.__referenceFeedbackSubmittedRefs?.has(referenceNumber)
    ? 'Response received'
    : (existing ? 'Form ready to share' : 'Draft');

  setReferenceFeedbackLink(existing?.public_url || '');
  if (referenceFeedbackQuestionInput) referenceFeedbackQuestionInput.value = '';
  renderReferenceFeedbackQuestionPreview();
  modal.classList.remove('hidden');
}

async function generateReferenceFeedbackForm() {
  const draft = window.__referenceFeedbackDraft;
  if (!draft) return;

  const generateButton = document.getElementById('reference-feedback-generate');
  const status = document.getElementById('reference-feedback-builder-status');

  if (generateButton) {
    generateButton.disabled = true;
    generateButton.textContent = 'Generating...';
  }
  if (status) status.textContent = 'Generating link';

  try {
    let opportunityId = window.__currentOppId || null;
    if (!opportunityId) {
      try {
        opportunityId = await ensureCurrentOppId(candidateId);
        window.__currentOppId = opportunityId;
      } catch (err) {
        console.warn('Failed to resolve opportunity_id for feedback form', err);
      }
    }

    const payload = {
      candidate_id: Number(candidateId),
      opportunity_id: opportunityId,
      api_base: 'https://7m6mw95m8y.us-east-2.awsapprunner.com',
      reference_number: draft.referenceNumber,
      reference_name: draft.reference.reference_name,
      reference_position: draft.reference.reference_position,
      reference_email: draft.reference.reference_email,
      reference_phone: draft.reference.reference_phone,
      reference_linkedin: draft.reference.reference_linkedin,
      candidate_name: draft.candidateName,
      questions: draft.questions,
    };

    const url = new URL('reference-feedback-form.html', window.location.href);
    url.searchParams.set('data', encodeReferenceFeedbackPayload(payload));
    draft.publicUrl = url.toString();
    draft.submittedAt = null;
    window.__referenceFeedbackRequests[String(draft.referenceNumber)] = {
      reference_number: draft.referenceNumber,
      public_url: draft.publicUrl,
      candidate_id: payload.candidate_id,
      opportunity_id: payload.opportunity_id,
      reference_name: payload.reference_name,
      questions: [...payload.questions],
      answers: [],
      submitted_at: null,
    };
    setStoredReferenceFeedbackRequests(window.__referenceFeedbackRequests, opportunityId);
    setReferenceFeedbackLink(draft.publicUrl);
    if (status) status.textContent = 'Form ready to share';
    showCuteToast('Feedback form link generated successfully.');
    renderReferenceOverview(window.__currentReferenceOverviewValues || {});
  } catch (err) {
    console.error('generateReferenceFeedbackForm failed', err);
    if (status) status.textContent = 'Draft';
    alert('We could not generate the feedback form link. Please try again.');
  } finally {
    if (generateButton) {
      generateButton.disabled = false;
      generateButton.textContent = draft.publicUrl ? 'Regenerate form' : 'Generate form';
    }
  }
}

async function openReferenceFeedbackResponses(referenceNumber) {
  const modal = document.getElementById('reference-feedback-response-modal');
  const content = document.getElementById('reference-feedback-response-content');
  const subtitle = document.getElementById('reference-feedback-response-subtitle');
  if (!modal || !content) return;

  await loadReferenceFeedbackRequests(window.__currentOppId).catch(console.error);
  const requestInfo = window.__referenceFeedbackRequests?.[String(referenceNumber)];
  if (!requestInfo || !requestInfo.submitted_at) {
    alert('No submitted responses found for this reference yet.');
    return;
  }

  const title = `Reference ${referenceNumber}${requestInfo.reference_name ? ` - ${requestInfo.reference_name}` : ''}`;
  if (subtitle) subtitle.textContent = `${title} • Submitted feedback`;

  const questions = Array.isArray(requestInfo.questions) ? requestInfo.questions : [];
  const answers = Array.isArray(requestInfo.answers) ? requestInfo.answers : [];
  content.innerHTML = questions.map((question, index) => `
    <article class="reference-feedback-response-item">
      <div class="reference-feedback-response-label">Question ${index + 1}</div>
      <div class="reference-feedback-response-question">${escapeReferenceHtml(question)}</div>
      <div class="reference-feedback-response-answer">${escapeReferenceHtml(answers[index] || '—')}</div>
    </article>
  `).join('');

  modal.classList.remove('hidden');
}

function buildReferenceOverviewMarkup(idx, values = {}) {
  const body = document.getElementById(`overview-reference-${idx}`);
  if (!body) return;

  const prefix = `reference_${idx}_`;
  const name = values[`${prefix}name`] || '';
  const position = values[`${prefix}position`] || '';
  const phone = values[`${prefix}phone`] || '';
  const email = values[`${prefix}email`] || '';
  const linkedin = values[`${prefix}linkedin`] || '';
  const hasAny = [name, position, phone, email, linkedin].some(Boolean);

  body.classList.toggle('is-empty', !hasAny);
  if (!hasAny) {
    body.textContent = 'No information yet.';
    renderReferenceFeedbackActions(idx, false);
    return;
  }

  const lines = [];
  if (name) lines.push(`<div><strong>Name:</strong> ${escapeReferenceHtml(name)}</div>`);
  if (position) lines.push(`<div><strong>Position:</strong> ${escapeReferenceHtml(position)}</div>`);
  if (phone) lines.push(`<div><strong>Phone:</strong> ${escapeReferenceHtml(phone)}</div>`);
  if (email) lines.push(`<div><strong>Email:</strong> <a href="mailto:${escapeReferenceHtml(email)}">${escapeReferenceHtml(email)}</a></div>`);
  if (linkedin) {
    const href = normalizeReferenceLink(linkedin);
    lines.push(`<div><strong>LinkedIn:</strong> <a href="${escapeReferenceHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeReferenceHtml(linkedin)}</a></div>`);
  }
  body.innerHTML = lines.join('');
  renderReferenceFeedbackActions(idx, hasAny);
}

function renderReferenceOverview(values = {}) {
  window.__currentReferenceOverviewValues = values;
  buildReferenceOverviewMarkup(1, values);
  buildReferenceOverviewMarkup(2, values);

  const statusEl = document.getElementById('overview-reference-status');
  if (!statusEl) return;

  const isComplete = [1, 2].every((idx) => (
    ['name', 'position', 'phone', 'email', 'linkedin'].every((field) => values[`reference_${idx}_${field}`])
  ));
  statusEl.textContent = isComplete ? 'References received' : 'Waiting for references';
  statusEl.classList.toggle('is-complete', isComplete);
}

if (hireWorkingSchedule) hireWorkingSchedule.addEventListener('blur', () => updateHireField('working_schedule', hireWorkingSchedule.value));
if (hirePTO) hirePTO.addEventListener('blur', () => updateHireField('pto', hirePTO.value));
if (hireComputer) hireComputer.addEventListener('change', () => updateHireField('computer', hireComputer.value));
if (hirePriceType) hirePriceType.addEventListener('change', () => updateHireField('price_type', hirePriceType.value));
if (hirePerks) hirePerks.addEventListener('blur', () => updateHireField('extraperks', hirePerks.innerHTML));
if (hireSetupFee) hireSetupFee.addEventListener('blur', () => { const v = parseFloat(hireSetupFee.value); if (!isNaN(v)) updateHireField('setup_fee', v); });
if (referencesDiv) referencesDiv.addEventListener('blur', () => updateHireField('references_notes', referencesDiv.innerHTML));
hireReferenceFields.forEach(([id, field]) => {
  const input = document.getElementById(id);
  if (input) {
    input.addEventListener('blur', () => patchHireFields({
      [field]: input.value
    }, { skipReload: true }));
  }
});

/**
 * NUEVO COMPORTAMIENTO:
 * - Editar Salary/Fee/Revenue crea un salary_update con date = start_date del Hire (o hoy)
 * - Luego sincroniza el Hire tomando el update más reciente
 * - Recruiting: revenue_recruiting sigue siendo manual y se guarda directo en Hire
 */
if (hireSalary){
  hireSalary.addEventListener('blur', async () => {
    const v = hireSalary.value.trim();
    if (!v) return;
    try {
      await createSalaryUpdateFromInputs('salary', candidateId);
    } catch(e){
      console.error('❌ salary→salary_update failed', e);
      alert('Error saving salary update from Salary field.');
    }
  });
}

if (hireFee){
  hireFee.addEventListener('blur', async () => {
    const modelTxt = (document.getElementById('opp-model-pill')?.textContent || '').toLowerCase();
    if (!modelTxt.includes('staffing')) return; // fee sólo aplica en Staffing
    const v = hireFee.value.trim();
    if (!v) return;
    try {
      await createSalaryUpdateFromInputs('fee', candidateId);
    } catch(e){
      console.error('❌ fee→salary_update failed', e);
      alert('Error saving salary update from Fee field.');
    }
  });
}

if (hireRevenue){
  hireRevenue.addEventListener('blur', async () => {
    const modelTxt = (document.getElementById('opp-model-pill')?.textContent || '').toLowerCase();
    // Recruiting: revenue_recruiting se guarda directo y NO crea salary_update
    if (modelTxt.includes('recruiting')){
      await updateHireField('employee_revenue_recruiting', hireRevenue.value);
      return;
    }

    // Staffing: revenue deriva fee y crea salary_update
    const v = hireRevenue.value.trim();
    if (!v) return;
    try {
      await createSalaryUpdateFromInputs('revenue', candidateId);
    } catch(e){
      console.error('❌ revenue→salary_update failed', e);
      alert('Error saving salary update from Revenue field.');
    }
  });
}

  // Cargar Hire + Opportunity model
  function adaptHireFieldsByModel(model) {
    window.__oppModelLower = String(model||'').toLowerCase().startsWith('recr') ? 'recruiting'
                        : String(model||'').toLowerCase().startsWith('staff') ? 'staffing'
                        : '';

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
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire_opportunity`)
      .then(res => res.json())
      .then(async (oppData) => {
        window.__currentOppId = Number(oppData?.opportunity_id) || window.__currentOppId;
        if (referenceRequestLink) {
          const refUrl = new URL('reference-request.html', window.location.href);
          refUrl.searchParams.set('candidate_id', candidateId);
          if (window.__currentOppId) refUrl.searchParams.set('opportunity_id', window.__currentOppId);
          referenceRequestLink.href = refUrl.toString();
        }
        const model = oppData?.opp_model;
        if (model) {
          const pill = document.getElementById('opp-model-pill');
          if (pill) pill.textContent = `Model: ${model}`;
          adaptHireFieldsByModel(model);
        }

        return fetchHire(candidateId, 'https://7m6mw95m8y.us-east-2.awsapprunner.com', window.__currentOppId);
      })
      .then(data => {
        const salaryInput = document.getElementById('hire-salary');
        const feeInput = document.getElementById('hire-fee');
        const setupEl = document.getElementById('hire-setup-fee');

        if (setupEl) setupEl.value = data.setup_fee || '';
        if (salaryInput) salaryInput.value = data.employee_salary || '';
        if (feeInput)    feeInput.value    = data.employee_fee    || '';
        const priceType = document.getElementById('hire-price-type'); if (priceType) priceType.value = data.price_type || '';
        const comp = document.getElementById('hire-computer');      if (comp) comp.value = data.computer || '';
        const perks = document.getElementById('hire-extraperks');   if (perks) perks.innerHTML = data.extraperks || '';
        const ws = document.getElementById('hire-working-schedule');if (ws) ws.value = data.working_schedule || '';
        const pto = document.getElementById('hire-pto');            if (pto) pto.value = data.pto || '';
        const ref = document.getElementById('hire-references');     if (ref) ref.innerHTML = data.references_notes || '';
        window.__referenceFeedbackSubmittedRefs = parseSubmittedReferenceFeedbackFromNotes(data.references_notes || '');
        const fallbackReferenceValues = parseStructuredReferencesFromNotes(data.references_notes || '');
        const existingOverviewValues = window.__currentReferenceOverviewValues || {};
        hireReferenceFields.forEach(([id, field]) => {
          const input = document.getElementById(id);
          if (input && input !== document.activeElement) input.value = data[field] || fallbackReferenceValues[field] || existingOverviewValues[field] || '';
        });
        renderReferenceOverview({
          reference_1_name: data.reference_1_name || fallbackReferenceValues.reference_1_name || existingOverviewValues.reference_1_name || '',
          reference_1_position: data.reference_1_position || fallbackReferenceValues.reference_1_position || existingOverviewValues.reference_1_position || '',
          reference_1_phone: data.reference_1_phone || fallbackReferenceValues.reference_1_phone || existingOverviewValues.reference_1_phone || '',
          reference_1_email: data.reference_1_email || fallbackReferenceValues.reference_1_email || existingOverviewValues.reference_1_email || '',
          reference_1_linkedin: data.reference_1_linkedin || fallbackReferenceValues.reference_1_linkedin || existingOverviewValues.reference_1_linkedin || '',
          reference_2_name: data.reference_2_name || fallbackReferenceValues.reference_2_name || existingOverviewValues.reference_2_name || '',
          reference_2_position: data.reference_2_position || fallbackReferenceValues.reference_2_position || existingOverviewValues.reference_2_position || '',
          reference_2_phone: data.reference_2_phone || fallbackReferenceValues.reference_2_phone || existingOverviewValues.reference_2_phone || '',
          reference_2_email: data.reference_2_email || fallbackReferenceValues.reference_2_email || existingOverviewValues.reference_2_email || '',
          reference_2_linkedin: data.reference_2_linkedin || fallbackReferenceValues.reference_2_linkedin || existingOverviewValues.reference_2_linkedin || '',
        });
        loadReferenceFeedbackRequests(window.__currentOppId);

        // fechas (YYYY-MM-DD)
        const startInp = document.getElementById('hire-start-date');
        const endInp   = document.getElementById('hire-end-date');
        if (startInp) startInp.value = (data.start_date || '').slice(0,10);
        if (endInp) {
          const endVal = (data.end_date || '').slice(0,10);
          endInp.value = endVal;
          endInp.dataset.previousEndDate = endVal || '';
        }

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
  }
  window.loadHireData = loadHireData;

  const referenceRequestLink = document.getElementById('reference-request-link');
  if (referenceRequestLink) {
    referenceRequestLink.href = `reference-request.html?candidate_id=${encodeURIComponent(candidateId)}`;
  }

  const referenceFeedbackBuilder = document.getElementById('reference-feedback-builder');
  const referenceFeedbackQuestionInput = document.getElementById('reference-feedback-question-input');
  document.addEventListener('click', async (event) => {
    const builderBtn = event.target.closest('[data-reference-feedback-builder]');
    if (builderBtn) {
      event.preventDefault();
      openReferenceFeedbackBuilder(Number(builderBtn.getAttribute('data-reference-feedback-builder')));
      return;
    }

    const viewBtn = event.target.closest('[data-reference-feedback-view]');
    if (viewBtn) {
      event.preventDefault();
      openReferenceFeedbackResponses(Number(viewBtn.getAttribute('data-reference-feedback-view'))).catch(console.error);
      return;
    }

    const deleteBtn = event.target.closest('[data-reference-delete]');
    if (deleteBtn) {
      event.preventDefault();
      deleteReference(Number(deleteBtn.getAttribute('data-reference-delete'))).catch(console.error);
      return;
    }

    const removeBtn = event.target.closest('[data-remove-reference-question]');
    if (removeBtn && window.__referenceFeedbackDraft) {
      const index = Number(removeBtn.getAttribute('data-remove-reference-question'));
      if (Number.isFinite(index)) {
        window.__referenceFeedbackDraft.questions.splice(index, 1);
        renderReferenceFeedbackQuestionPreview();
      }
    }
  });

  document.getElementById('reference-feedback-add-question')?.addEventListener('click', () => {
    const question = referenceFeedbackQuestionInput?.value?.trim();
    if (!question || !window.__referenceFeedbackDraft) return;
    window.__referenceFeedbackDraft.questions.push(question);
    if (referenceFeedbackQuestionInput) referenceFeedbackQuestionInput.value = '';
    renderReferenceFeedbackQuestionPreview();
  });

  referenceFeedbackQuestionInput?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      document.getElementById('reference-feedback-add-question')?.click();
    }
  });

  document.getElementById('reference-feedback-generate')?.addEventListener('click', () => {
    const questions = window.__referenceFeedbackDraft?.questions || [];
    if (!questions.length) {
      alert('Please keep at least one question in the form.');
      return;
    }
    generateReferenceFeedbackForm().catch(console.error);
  });

  document.getElementById('reference-feedback-copy-link')?.addEventListener('click', async () => {
    const link = document.getElementById('reference-feedback-link')?.value?.trim();
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      showCuteToast('Feedback form link copied to clipboard.');
    } catch (err) {
      console.warn('Clipboard write failed', err);
    }
  });

  document.getElementById('reference-feedback-open-link')?.addEventListener('click', () => {
    const link = document.getElementById('reference-feedback-link')?.value?.trim();
    if (!link) return;
    window.open(link, '_blank', 'noopener,noreferrer');
  });

  referenceFeedbackBuilder?.querySelector('.close-star-popup')?.addEventListener('click', () => {
    referenceFeedbackBuilder.classList.add('hidden');
  });
  referenceFeedbackBuilder?.addEventListener('click', (event) => {
    if (event.target === referenceFeedbackBuilder) {
      referenceFeedbackBuilder.classList.add('hidden');
    }
  });

  const referenceFeedbackResponseModal = document.getElementById('reference-feedback-response-modal');
  referenceFeedbackResponseModal?.querySelector('.reference-feedback-response-close')?.addEventListener('click', () => {
    referenceFeedbackResponseModal.classList.add('hidden');
  });
  referenceFeedbackResponseModal?.addEventListener('click', (event) => {
    if (event.target === referenceFeedbackResponseModal) {
      referenceFeedbackResponseModal.classList.add('hidden');
    }
  });

  // Cargar salary updates si estás en Hire
  if (document.querySelector('.tab.active')?.dataset.tab === 'hire') {
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
        const uniqueOpps = []; // keep display order while filtering duplicates
        const seenIds = new Set();
        (data || []).forEach(opp => {
          const oppId = opp?.opportunity_id;
          if (!oppId || seenIds.has(oppId)) return;
          seenIds.add(oppId);
          uniqueOpps.push(opp);
        });
        uniqueOpps.forEach(opp => {
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

// ✅ Un solo sanitizador global de paste para TODOS los contenteditable
if (!window.__VINTTI_WIRED) window.__VINTTI_WIRED = {};
if (!window.__VINTTI_WIRED.globalPasteOnce) {
  window.__VINTTI_WIRED.globalPasteOnce = true;

  document.addEventListener('paste', (e) => {
    const target = e.target?.closest?.('[contenteditable="true"]');
    if (!target || target.id === 'videoLinkInput') return; // videoLinkInput ya maneja su propio paste
    e.preventDefault();
    const text = (e.clipboardData || window.clipboardData).getData('text') || '';
    document.execCommand('insertText', false, text);
  }, true);
}
// ✅ Dedupe del campo de Video Link (blindado)
function wireVideoLinkDedupe() {
  const el = document.getElementById('videoLinkInput');
  if (!el || el.__dedupeWired) return;
  el.__dedupeWired = true;

  // Si al pegar queda URL+URL (back-to-back), dejar solo una
  const dedupe = () => {
    const s = (el.textContent || '').trim();
    const m = s.match(/https?:\/\/\S+/g);
    if (m && m.length >= 2 && m[0] === m[1] && s === (m[0] + m[1])) {
      el.textContent = m[0];
    }
  };

  el.addEventListener('input', dedupe, { passive: true });
  el.addEventListener('blur', dedupe);

  // 👇 plus: si pega una URL, sustituimos TODO el contenido por UNA sola URL limpia
  el.addEventListener('paste', (e) => {
    e.preventDefault();
    const raw = (e.clipboardData || window.clipboardData).getData('text') || '';
    const url = (raw.match(/https?:\/\/\S+/) || [raw.trim()])[0];
    document.execCommand('insertText', false, url);
    // forzamos dedupe por si el otro archivo también insertó
    setTimeout(dedupe, 0);
  });
}
// === Resignation & References: checkbox + toast + PATCH =====================
(function wireResigRefCheck(){
  const check = document.getElementById('resig-ref-check');
  if (!check) return;

  const API  = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid  = new URLSearchParams(window.location.search).get('id');

  check.addEventListener('change', async () => {
    if (!cid) return;
    const val = !!check.checked;

    try {
      const r = await fetch(`${API}/candidates/${cid}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ check_hr_lead: val })
      });
      if (!r.ok) throw new Error(await r.text().catch(()=> 'PATCH failed'));

      if (val) {
        showCuteToast(
          `🎀 You rock! Task completed — resignation letter & references are on track.<br/>
           You’re the cutest recruiter ever 💖✨`,
          5000
        );
      }
    } catch (e) {
      console.error('❌ Saving check_hr_lead failed', e);
      check.checked = !val; // revertir si falló
      alert('We could not save this change. Please try again.');
    }
  });
})();

(function wireBlacklistToggle(){
  const checkbox = document.getElementById('blacklist-toggle');
  const card = document.getElementById('blacklist-card');
  if (!checkbox || !card) return;

  const statusText = document.getElementById('blacklist-status-text');
  const cardTitle = card.querySelector('.blacklist-card-title');
  const cardDescription = card.querySelector('.blacklist-card-description');
  const defaultTitleCopy = cardTitle ? cardTitle.textContent.trim() : '';
  const defaultDescriptionCopy = cardDescription ? cardDescription.textContent.trim() : '';
  const params = new URLSearchParams(window.location.search);
  const candidateParam = params.get('id');
  const candidateId = candidateParam ? Number(candidateParam) : NaN;
  const API  = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  if (!candidateParam || Number.isNaN(candidateId)) {
    checkbox.disabled = true;
    if (statusText) {
      statusText.textContent = 'Missing candidate id.';
      statusText.style.display = 'block';
    }
    return;
  }

  const state = {
    candidateId,
    blacklistId: null,
    isBlacklisted: false,
    busy: false
  };

  async function ensureBlacklistId() {
    if (state.blacklistId) return state.blacklistId;
    try {
      const resp = await fetch(
        `${API}/api/blacklist/status?candidate_id=${state.candidateId}`,
        { cache: 'no-store' }
      );
      if (!resp.ok) return null;
      const payload = await resp.json();
      const serverId = payload?.blacklist_id || null;
      if (serverId) {
        state.blacklistId = serverId;
      }
      return serverId;
    } catch (err) {
      console.error('❌ Unable to refresh blacklist id before deletion', err);
      return null;
    }
  }

  function setStatusMessage(message) {
    if (!statusText) return;
    statusText.textContent = message;
    statusText.style.display = message ? 'block' : 'none';
  }

  function confirmBlacklistAddition() {
    return showCuteConfirmDialog({
      title: 'Add this candidate to your blacklist?',
      message: 'We will hide this profile from searches and alerts. Are you sure you want to continue?',
      confirmText: 'Yes, blacklist',
      cancelText: 'No, keep visible',
      tone: 'danger'
    });
  }

  function paintState() {
    const checked = Boolean(state.isBlacklisted);
    checkbox.checked = checked;
    card.classList.toggle('is-blacklisted', checked);
    card.classList.toggle('not-blacklisted', !checked);
    if (cardTitle) {
      cardTitle.textContent = checked
        ? defaultTitleCopy || 'Blacklist (dangerous)'
        : 'Candidate is not blacklisted.';
    }
    if (cardDescription) {
      if (checked) {
        cardDescription.textContent = defaultDescriptionCopy || 'Keep risky candidates hidden from searches.';
        cardDescription.style.display = 'block';
      } else {
        cardDescription.textContent = '';
        cardDescription.style.display = 'none';
      }
    }
    setStatusMessage(checked ? 'Candidate is currently blacklisted.' : '');
  }

  window.__applyBlacklistState = function applyBlacklistState(payload) {
    if (!payload) return;
    state.blacklistId = payload.blacklist_id || null;
    state.isBlacklisted = Boolean(payload.is_blacklisted);
    paintState();
  };

  setStatusMessage('Loading blacklist status...');

  checkbox.addEventListener('change', async () => {
    if (state.busy) {
      checkbox.checked = state.isBlacklisted;
      return;
    }
    const shouldBlacklist = checkbox.checked;
    if (shouldBlacklist) {
      const confirmed = await confirmBlacklistAddition();
      if (!confirmed) {
        checkbox.checked = state.isBlacklisted;
        paintState();
        return;
      }
    }
    state.busy = true;
    checkbox.disabled = true;
    setStatusMessage(shouldBlacklist ? 'Adding candidate to blacklist...' : 'Removing candidate from blacklist...');

    try {
      if (shouldBlacklist) {
        if (!state.blacklistId) {
          const resp = await fetch(`${API}/api/blacklist`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ candidate_id: state.candidateId })
          });
          if (!resp.ok) throw new Error(await resp.text().catch(() => 'Failed to create blacklist entry'));
          const payload = await resp.json();
          state.blacklistId = payload?.blacklist_id || state.blacklistId;
        }
        showCuteToast('Candidate added to blacklist ⚠️', 4000);
      } else {
        const blacklistId = state.blacklistId || (await ensureBlacklistId());
        if (blacklistId) {
          const resp = await fetch(`${API}/api/blacklist/${blacklistId}`, { method: 'DELETE' });
          if (!resp.ok) throw new Error(await resp.text().catch(() => 'Failed to delete blacklist entry'));
        } else {
          console.warn('⚠️ No blacklist entry found for candidate, skipping delete');
        }
        state.blacklistId = null;
        showCuteToast('Candidate removed from blacklist ✅', 4000);
      }
      state.isBlacklisted = shouldBlacklist;
      paintState();
    } catch (err) {
      console.error('❌ Unable to save blacklist change', err);
      checkbox.checked = state.isBlacklisted;
      paintState();
      alert('We could not update the blacklist status. Please try again.');
    } finally {
      checkbox.disabled = false;
      state.busy = false;
    }
  });
})();

//  Llamar de inmediato 
wireVideoLinkDedupe();


  // ====== Candidate CVs (listar / subir / abrir) — sin AI ni extracción ======
(() => {
  // ✅ Flag global realmente compartido entre archivos
  if (!window.__VINTTI_WIRED) window.__VINTTI_WIRED = {};
  if (window.__VINTTI_WIRED.cvWidgetOnce) return;
  window.__VINTTI_WIRED.cvWidgetOnce = true;

  const apiBase = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid     = new URLSearchParams(window.location.search).get('id');
  const drop      = document.getElementById('cv-drop');
  const input     = document.getElementById('cv-input');
  const browseBtn = document.getElementById('cv-browse');
  const refreshBtn= document.getElementById('cv-refresh');
  const list      = document.getElementById('cv-list');
  if (!cid || !list) return;

  let inFlight = false;               // bloqueo duro por request
  const BIND = (el, type, fn) => {    // helper para no duplicar listeners
    if (!el) return;
    el.__wired = el.__wired || {};
    const key = `on:${type}`;
    if (el.__wired[key]) return;
    el.addEventListener(type, fn);
    el.__wired[key] = true;
  };

function render(items = []) {
  list.innerHTML = '';
  if (!items.length) {
    list.innerHTML = `<div class="cv-item"><span class="cv-name" style="opacity:.65">No files yet</span></div>`;
    return;
  }
  items.forEach(it => {
    if (!it || !it.name || !it.url) { console.warn('item malformado:', it); return; }
    const row = document.createElement('div');
    row.className = 'cv-item';
    row.innerHTML = `
      <span class="cv-name" title="${it.name}">${it.name}</span>
      <div class="cv-actions">
        <a class="btn" href="${it.url}" target="_blank" rel="noopener">Open</a>
        <button class="btn danger" data-key="${it.key}" type="button">Delete</button>
      </div>
    `;
    const delBtn = row.querySelector('.danger');
    BIND(delBtn, 'click', async (e) => {
      const key = e.currentTarget.getAttribute('data-key');
      if (!key) return;
      if (!confirm('Delete this CV?')) return;
      await fetch(`${apiBase}/candidates/${cid}/cvs`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key })
      });
      await loadCVs(); // 👈 recarga la lista de CVs (no resignations)
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
  window.loadCVs = loadCVs;

    async function uploadFile(file) {
      if (!file) return;

      // 🔒 De-dupe: si es exactamente el mismo archivo en < 3s, ignorar
      const sig = [file.name, file.size, file.lastModified].join(':');
      const now = Date.now();
      if (sig === lastUploadSig && (now - lastUploadTs) < 3000) {
        console.debug('⛔️ Ignorado: intento duplicado de upload', sig);
        return;
      }
      lastUploadSig = sig;
      lastUploadTs  = now;

      if (inFlight) {
        console.debug('⛔️ Ignorado: upload en curso');
        return;
      }
      inFlight = true;

    const allowedMimes = new Set([
      'application/pdf','image/png','image/jpeg','image/webp','application/octet-stream',''
    ]);
    const extOk = /\.(pdf|png|jpe?g|webp)$/i.test(file?.name || '');
    const typeOk = allowedMimes.has(file?.type || '');
    if (!extOk && !typeOk) { alert('Only PDF, PNG, JPG/JPEG or WEBP are allowed.'); inFlight = false; return; }

    const fd = new FormData();
    fd.append('file', file);

    try {
      drop?.classList.add('dragover');
      const r = await fetch(`${apiBase}/candidates/${cid}/cvs`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text().catch(()=> 'Upload failed'));
      const data = await r.json();
      render(data.items || []);
    } catch (e) {
      console.error('Upload failed', e); alert('Upload failed');
    } finally {
      drop?.classList.remove('dragover');
      if (input) input.value = '';
      setTimeout(() => { inFlight = false; }, 600); // antes estaba en 200ms
    }
  }

  // Drag & Drop (con BIND para no repetir listeners)
  if (drop) {
    ['dragenter','dragover'].forEach(ev => BIND(drop, ev, e => {
      e.preventDefault(); e.stopPropagation(); drop.classList.add('dragover');
    }));
    ['dragleave','dragend','drop'].forEach(ev => BIND(drop, ev, e => {
      e.preventDefault(); e.stopPropagation(); drop.classList.remove('dragover');
    }));
    BIND(drop, 'drop', (e) => {
      const files = e.dataTransfer?.files;
      if (files?.length) uploadFile(files[0]);
    });
    BIND(drop, 'click', (e) => {
      if ((e.target instanceof HTMLElement) && e.target.closest('.cv-actions')) return;
      input?.click();
    });
  }

  // Browse
  BIND(browseBtn, 'click', () => input?.click());
  BIND(input, 'change', () => { const f = input.files?.[0]; if (f) uploadFile(f); });

  // Refresh
  BIND(refreshBtn, 'click', loadCVs);

  // Carga inicial
  loadCVs();
})();

// ====== Candidate Tests documents (any file type) ==========================
(() => {
  if (!window.__VINTTI_WIRED) window.__VINTTI_WIRED = {};
  if (window.__VINTTI_WIRED.testsWidgetOnce) return;
  window.__VINTTI_WIRED.testsWidgetOnce = true;

  const apiBase = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid = new URLSearchParams(window.location.search).get('id');

  const drop = document.getElementById('tests-drop');
  const input = document.getElementById('tests-input');
  const browseBtn = document.getElementById('tests-browse');
  const refreshBtn = document.getElementById('tests-refresh');
  const list = document.getElementById('tests-list');
  const errorBox = document.getElementById('tests-error');

  if (!cid || !drop || !list) return;

  let busy = false;

  function setError(message) {
    if (!errorBox) return;
    errorBox.textContent = message || '';
  }

  function formatDateLabel(value) {
    if (!value) return '';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function formatFileSize(bytes) {
    const num = Number(bytes);
    if (!Number.isFinite(num) || num <= 0) return '';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = num;
    let idx = 0;
    while (value >= 1024 && idx < units.length - 1) {
      value /= 1024;
      idx += 1;
    }
    const precision = value >= 10 ? 0 : 1;
    return `${value.toFixed(precision)} ${units[idx]}`;
  }

  function render(items = []) {
    list.innerHTML = '';
    const normalized = Array.isArray(items) ? items : [];
    if (!normalized.length) {
      const empty = document.createElement('div');
      empty.className = 'tests-empty';
      empty.textContent = 'No files yet.';
      list.appendChild(empty);
      return;
    }
    normalized.forEach((doc) => {
      if (!doc || !doc.key) return;
      const row = document.createElement('div');
      row.className = 'tests-row';

      const info = document.createElement('div');
      info.className = 'tests-row-info';

      const link = document.createElement('a');
      link.href = doc.url || '#';
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = doc.name || (doc.key.split('/').pop() || 'File');
      info.appendChild(link);

      const metaParts = [];
      const label = formatDateLabel(doc.uploaded_at);
      if (label) metaParts.push(`Uploaded ${label}`);
      const sizeLabel = formatFileSize(doc.size);
      if (sizeLabel) metaParts.push(sizeLabel);
      const typeLabel = (doc.content_type || '').split(';')[0];
      if (typeLabel) metaParts.push(typeLabel);
      if (metaParts.length) {
        const note = document.createElement('span');
        note.className = 'tests-row-note';
        note.textContent = metaParts.join(' • ');
        info.appendChild(note);
      }

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.className = 'tests-remove';
      removeBtn.dataset.key = doc.key;
      removeBtn.textContent = 'Remove';

      row.appendChild(info);
      row.appendChild(removeBtn);
      list.appendChild(row);
    });
  }

  async function loadCandidateTests() {
    setError('');
    try {
      const resp = await fetch(`${apiBase}/candidates/${cid}/tests`);
      const data = await resp.json();
      const items = Array.isArray(data) ? data : (data?.items || []);
      render(items);
    } catch (err) {
      console.warn('Failed to load candidate tests', err);
      setError('Unable to load files right now.');
      render([]);
    }
  }
  window.loadCandidateTests = loadCandidateTests;

  function setBusy(flag) {
    busy = !!flag;
    drop?.classList.toggle('is-uploading', busy);
    drop?.classList.remove('dragover');
    if (browseBtn) browseBtn.disabled = busy;
    if (refreshBtn) refreshBtn.disabled = busy;
    if (input) input.disabled = busy;
  }

  async function uploadTests(fileList) {
    const files = Array.from(fileList || []).filter(Boolean);
    if (!files.length || busy) return;

    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    setBusy(true);
    setError('');
    try {
      const resp = await fetch(`${apiBase}/candidates/${cid}/tests`, {
        method: 'POST',
        body: formData,
      });
      if (!resp.ok) throw new Error(await resp.text().catch(() => 'Upload failed'));
      const data = await resp.json();
      const items = Array.isArray(data) ? data : (data?.items || []);
      render(items);
    } catch (err) {
      console.error('Failed to upload tests', err);
      setError(err?.message || 'Unable to upload files.');
    } finally {
      setBusy(false);
      if (input) input.value = '';
    }
  }

  async function deleteTest(key) {
    if (!key) return;
    try {
      const resp = await fetch(`${apiBase}/candidates/${cid}/tests`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key }),
      });
      if (!resp.ok) throw new Error(await resp.text().catch(() => 'Delete failed'));
      const data = await resp.json();
      const items = Array.isArray(data) ? data : (data?.items || []);
      render(items);
    } catch (err) {
      console.error('Failed to delete test file', err);
      setError('Unable to delete file right now.');
    }
  }

  drop.addEventListener('dragenter', (e) => {
    e.preventDefault();
    e.stopPropagation();
    drop.classList.add('dragover');
  });
  drop.addEventListener('dragover', (e) => {
    e.preventDefault();
    e.stopPropagation();
    drop.classList.add('dragover');
  });
  drop.addEventListener('dragleave', (e) => {
    if (e.target === drop) {
      drop.classList.remove('dragover');
    }
  });
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    drop.classList.remove('dragover');
    if (busy) return;
    const files = e.dataTransfer?.files;
    if (files?.length) uploadTests(files);
  });

  browseBtn?.addEventListener('click', () => input?.click());
  input?.addEventListener('change', (e) => {
    if (busy) return;
    uploadTests(e.target.files);
  });
  refreshBtn?.addEventListener('click', () => loadCandidateTests());

  list.addEventListener('click', (event) => {
    const btn = event.target.closest('.tests-remove');
    if (!btn) return;
    const key = btn.dataset.key;
    if (!key) return;
    if (!window.confirm('Delete this file?')) return;
    deleteTest(key);
  });

  loadCandidateTests();
})();
(() => {
  // Evita doble wiring
  if (!window.__VINTTI_WIRED) window.__VINTTI_WIRED = {};
  if (window.__VINTTI_WIRED.resigWidgetOnce) return;
  window.__VINTTI_WIRED.resigWidgetOnce = true;

  const apiBase   = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid       = new URLSearchParams(window.location.search).get('id');

  const drop      = document.getElementById('resig-drop');
  const input     = document.getElementById('resig-input');
  const browseBtn = document.getElementById('resig-browse');
  const refreshBtn= document.getElementById('resig-refresh');
  const list      = document.getElementById('resig-list');

  if (!cid || !list) return;

  let inFlight = false;
  let lastUploadSig = null;     // firma (nombre+tamaño+mtime) del último archivo
  let lastUploadTs  = 0;        // timestamp del último intento (ms)
  const BIND = (el, type, fn) => {
    if (!el) return;
    el.__wired = el.__wired || {};
    const key = `on:${type}`;
    if (el.__wired[key]) return;
    el.addEventListener(type, fn);
    el.__wired[key] = true;
  };

  function render(items = []) {
    // De-dupe por key (o por nombre si no hay key)
    const seen = new Set();
    items = (items || []).filter(it => {
      const k = it?.key || `name:${it?.name}`;
      if (!k) return false;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });

    list.innerHTML = '';
    if (!items.length) {
      list.innerHTML = `<div class="cv-item"><span class="cv-name" style="opacity:.65">No files yet</span></div>`;
      return;
    }
    items.forEach(it => {
      const row = document.createElement('div');
      row.className = 'cv-item';
      // Asumimos que _list_s3_with_prefix devuelve {name,url,key}
      row.innerHTML = `
        <span class="cv-name" title="${it.name}">${it.name}</span>
        <div class="cv-actions">
          <a class="btn" href="${it.url}" target="_blank" rel="noopener">Open</a>
          <button class="btn danger" data-key="${it.key}" type="button">Delete</button>
        </div>
      `;
      const delBtn = row.querySelector('.danger');
      BIND(delBtn, 'click', async (e) => {
        const key = e.currentTarget.getAttribute('data-key');
        if (!key) return;
        if (!confirm('Delete this resignation letter?')) return;
        await fetch(`${apiBase}/candidates/${cid}/resignations`, {
          method: 'DELETE',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ key })
        });
        await loadResignations();
      });
      list.appendChild(row);
    });
  }

async function loadResignations() {
  try {
    const r = await fetch(`${apiBase}/candidates/${cid}/resignations`);
    const data = await r.json();
    console.debug('🔎 resignations GET →', data);
    // Acepta {items:[...]} o lista directa
    const items = Array.isArray(data) ? data : (Array.isArray(data.items) ? data.items : []);
    render(items);
  } catch (e) {
    console.warn('Failed to load resignations', e);
    render([]);
  }
}

  window.loadResignations = loadResignations;

  async function uploadResignationFile(file) {
    if (inFlight) return;
    inFlight = true;

    const isPdfByExt  = /\.(pdf)$/i.test(file?.name || '');
    const isPdfByMime = (file?.type || '').toLowerCase().startsWith('application/pdf');

    if (!isPdfByExt && !isPdfByMime) {
      alert('Only PDF is allowed for resignation letters.');
      inFlight = false;
      return;
    }

    const fd = new FormData();
    fd.append('file', file);

    try {
      drop?.classList.add('dragover');
      const r = await fetch(`${apiBase}/candidates/${cid}/resignations`, { method: 'POST', body: fd });
      const text = await r.text();
      if (!r.ok) throw new Error(text || 'Upload failed');
      // El backend devuelve {message, items}; podemos refrescar con loadResignations():
      await loadResignations();
    } catch (e) {
      console.error('Resignation upload failed', e);
      alert('Upload failed');
    } finally {
      drop?.classList.remove('dragover');
      if (input) input.value = '';
      setTimeout(() => { inFlight = false; }, 200);
    }
  }

  // Drag & Drop
  if (drop) {
    ['dragenter','dragover'].forEach(ev => BIND(drop, ev, e => {
      e.preventDefault(); e.stopPropagation(); drop.classList.add('dragover');
    }));
    ['dragleave','dragend','drop'].forEach(ev => BIND(drop, ev, e => {
      e.preventDefault(); e.stopPropagation(); drop.classList.remove('dragover');
    }));
    BIND(drop, 'drop', (e) => {
      const files = e.dataTransfer?.files;
      if (files?.length) uploadResignationFile(files[0]);
    });
    BIND(drop, 'click', (e) => {
      if ((e.target instanceof HTMLElement) && e.target.closest('.cv-actions')) return;
      input?.click();
    });
  }

  // Browse
  BIND(browseBtn, 'click', () => input?.click());
  BIND(input, 'change', () => { const f = input.files?.[0]; if (f) uploadResignationFile(f); });

  // Refresh
  BIND(refreshBtn, 'click', loadResignations);

  // Carga inicial
  loadResignations();
  // Drag & Drop (zona específica)
if (drop) {
  ['dragenter','dragover'].forEach(ev => BIND(drop, ev, e => {
    e.preventDefault(); e.stopPropagation();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    drop.classList.add('dragover');
  }));
  ['dragleave','dragend'].forEach(ev => BIND(drop, ev, e => {
    e.preventDefault(); e.stopPropagation();
    drop.classList.remove('dragover');
  }));
  BIND(drop, 'drop', (e) => {
    e.preventDefault(); e.stopPropagation();
    drop.classList.remove('dragover');

    // Safari: preferir items si existen
    const dt = e.dataTransfer;
    let file = null;
    if (dt?.items && dt.items.length) {
      for (const it of dt.items) {
        if (it.kind === 'file') { file = it.getAsFile(); break; }
      }
    } else if (dt?.files && dt.files.length) {
      file = dt.files[0];
    }
    if (file) uploadResignationFile(file);
  });

  // Click en la zona → abrir file picker
  BIND(drop, 'click', (e) => {
    if ((e.target instanceof HTMLElement) && e.target.closest('.cv-actions')) return;
    input?.click();
  });
}

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
    if (aiButton) aiButton.classList.toggle('hidden', !show);
    if (clientBtn) clientBtn.classList.toggle('hidden', !show);
  });
});

// si ya estás en "resume" al cargar
if (document.querySelector('.tab.active')?.dataset.tab === 'resume') {
  if (aiButton) aiButton.classList.remove('hidden');
  if (clientBtn) clientBtn.classList.remove('hidden');
}

(function wireHireReminders(){
  const API = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const cid = new URLSearchParams(location.search).get('id');
  if (!cid) return;

  const btn   = document.getElementById('btn-send-reminders');
  const cbLar = document.getElementById('rem-lara');
  const cbJaz = document.getElementById('rem-jazmin');
  // Lucia desactivada: hire reminders queda solo con Lara y Jazmin.
  // const cbAgs = document.getElementById('rem-agustin');

  const cdLar = document.getElementById('cd-lar');
  const cdJaz = document.getElementById('cd-jaz');
  // const cdAgs = document.getElementById('cd-agus');

  const msgLar = document.getElementById('msg-lar');
  const msgJaz = document.getElementById('msg-jaz');
  // const msgAgs = document.getElementById('msg-agus');

  let currentReminder = null;
  let tickTimer = null;

  function showFireworks(msg="Thanks for completing — Vintti Hub appreciates you! 🎆"){
    const pop = document.createElement('div');
    pop.className = 'fireworks-pop';
    pop.innerHTML = `
      <div class="bubble">
        <img src="https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExa3JvZ2trdXZ0ZTNkdG1wdnBseG4xN3lqY2V3Z3g4cGZiaGd5bTNtZSZlcD12MV9naWZzX3NlYXJjaCZjdD1n/3o6Zt6ML6BklcajjsA/giphy.gif" alt="fireworks"/>
        <div style="font-weight:600; margin-top:6px">${msg}</div>
      </div>`;
    pop.addEventListener('click', ()=> pop.remove());
    document.body.appendChild(pop);
    setTimeout(()=> pop.remove(), 3500);
  }

  function fmtLeft(ms){
    if (ms <= 0) return "now";
    const s = Math.floor(ms/1000);
    const d = Math.floor(s/86400);
    const h = Math.floor((s%86400)/3600);
    const m = Math.floor((s%3600)/60);
    if (d>0) return `${d}d ${h}h`;
    if (h>0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  function nextDue(pressISO, lastISO){
    // siguiente reminder = max(press_date, last_sent_at) + 24h
    const base = new Date(lastISO || pressISO || Date.now());
    return new Date(base.getTime() + 24*60*60*1000);
  }

  function paintCountdown(){
    if (!currentReminder) return;
    const press = currentReminder.press_date;
    const now = Date.now();

    const dueLar = nextDue(press, currentReminder.last_lar_sent_at);
    const dueJaz = nextDue(press, currentReminder.last_jaz_sent_at);
    // const dueAgs = nextDue(press, currentReminder.last_agus_sent_at);

    if (cdLar) cdLar.textContent = currentReminder.lar ? "Mission complete 🛸" : `Next reminder in ${fmtLeft(dueLar - now)}`;
    if (cdJaz) cdJaz.textContent = currentReminder.jaz ? "Mission complete 🛸" : `Next reminder in ${fmtLeft(dueJaz - now)}`;
    // if (cdAgs) cdAgs.textContent = currentReminder.agus ? "Mission complete 🛸" : `Next reminder in ${fmtLeft(dueAgs - now)}`;
  }

  function startTicker(){
    if (tickTimer) clearInterval(tickTimer);
    tickTimer = setInterval(paintCountdown, 1000*30); // cada 30s es suficiente
    paintCountdown();
  }

async function loadReminder(){
  // 1) intenta cargar la fila actual
  let r = await fetch(`${API}/candidates/${cid}/hire_reminders`);
  let data = await r.json();

  // 2) si no existe, crea una (ensure) sin enviar mails
  if (!data || !data.reminder_id){
    const ens = await fetch(`${API}/candidates/${cid}/hire_reminders/ensure`, { method:'POST' });
    const out = await ens.json();
    // puede devolver created:false si ya existía
    data = (out && out.row) ? out.row : data;
  }

  currentReminder = data && data.reminder_id ? data : null;

  // 3) pinta UI
  if (!currentReminder){
    [cbLar, cbJaz].forEach(cb=> cb && (cb.checked = false));
    [cdLar, cdJaz].forEach(c=> c && (c.textContent = '—'));
    return;
  }
  cbLar && (cbLar.checked = !!currentReminder.lar);
  cbJaz && (cbJaz.checked = !!currentReminder.jaz);
  // cbAgs && (cbAgs.checked = !!currentReminder.agus);

  msgLar.textContent = currentReminder.lar ? "Congrats — no more reminders 😎" : "";
  msgJaz.textContent = currentReminder.jaz ? "Congrats — no more reminders 😎" : "";
  // msgAgs.textContent = currentReminder.agus ? "Congrats — no more reminders 😎" : "";

  startTicker();
}

async function createAndSend(){
  if (!currentReminder || !currentReminder.reminder_id){
    // por robustez, intenta ensure de nuevo
    await fetch(`${API}/candidates/${cid}/hire_reminders/ensure`, { method:'POST' });
  }

  btn.disabled = true;
  btn.textContent = 'Sending...';
  try{
    const r = await fetch(`${API}/candidates/${cid}/hire_reminders/press`, {
      method:'POST',
      headers:{'Content-Type':'application/json'}
      // ya no enviamos opportunity_id aquí
    });
    const out = await r.json();
    if (!r.ok) throw new Error(out?.error || 'Failed');

    currentReminder = out.row;
    // Al “press”, los checks siguen como estén (no los reseteamos)
    [msgLar, msgJaz].forEach(m=> m && (m.textContent = '')); // limpio mensajes
    startTicker();
    showFireworks("Kickoff sent — Vintti Hub on it! 🎉"); // feedback UX
  }catch(e){
    console.error(e);
    alert('Failed to send reminders');
  }finally{
    btn.disabled = false;
    btn.textContent = 'Information Complete — Send Reminders';
  }
}

  async function patchCheck(field, value){
    if (!currentReminder?.reminder_id) return;
    const r = await fetch(`${API}/hire_reminders/${currentReminder.reminder_id}`, {
      method:'PATCH', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ [field]: !!value })
    });
    const row = await r.json();
    currentReminder = row;
    // mensaje + fueguitos si quedó en true
    if (value){
      const who = field === 'lar' ? 'Lara' : 'Jazmin';
      const el = field === 'lar' ? msgLar : msgJaz;
      if (el) el.textContent = "Congrats — no more reminders 😎";
      showFireworks(`Thanks ${who}! Vintti Hub loves completed checkboxes ✨`);
    }
    paintCountdown();
  }

  // wire
  btn && btn.addEventListener('click', createAndSend);
  cbLar && cbLar.addEventListener('change', ()=> patchCheck('lar', cbLar.checked));
  cbJaz && cbJaz.addEventListener('change', ()=> patchCheck('jaz', cbJaz.checked));
  // cbAgs && cbAgs.addEventListener('change', ()=> patchCheck('agus', cbAgs.checked));

  // primera carga
  loadReminder();

  // refresco suave cada 2 min (por si un reminder se envió desde el cron)
  setInterval(loadReminder, 120000);
})();

});
/* === Normalizador global de fechas → "dd mmm yyyy" (es) ================== */
// Mapea "Sep", "Sept", "Set" → 9, etc (acepta esp/eng abreviado)
const _MES_IDX = {
  ene:1, jan:1,
  feb:2,
  mar:3,
  abr:4, apr:4,
  may:5, may_:5, // por si acaso
  jun:6,
  jul:7,
  ago:8, aug:8,
  sep:9, set:9, sept:9, sep_:9,
  oct:10,
  nov:11,
  dic:12, dec:12
};
const _MES_ES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];

function formatDateHumanES(isoLikeOrPretty){
  if (!isoLikeOrPretty) return '';
  const s = String(isoLikeOrPretty).trim();

  // 1) ISO: YYYY-MM-DD o YYYY-MM-DDTHH:mm...
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    const y = +m[1], mm = +m[2], dd = +m[3];
    if (y && mm && dd) return `${String(dd).padStart(2,'0')} ${_MES_ES[mm-1]} ${y}`;
  }

  // 2) “Mon, 01 Sep 2025” | “Lun, 01 Sep 2025” | “Mon 01 Sep 2025” | “01 Sep 2025” | “01 Sep”
  m = s.match(/(?:[A-Za-zÀ-ÿ]{2,3},?\s*)?(\d{1,2})[\s\/\-\.]+([A-Za-zÀ-ÿ\.]{3,5})\.?(?:[\s\/\-\.]+(\d{4}))?/);
  if (m) {
    const dd = +m[1];
    const monKey = m[2].toLowerCase().replace(/\./g,'').slice(0,4); // 'sept' → 'sept'
    const mm = _MES_IDX[monKey] || _MES_IDX[monKey.slice(0,3)];
    const y  = m[3] ? +m[3] : new Date().getFullYear();
    if (dd && mm) return `${String(dd).padStart(2,'0')} ${_MES_ES[mm-1]} ${y}`;
  }

  // 3) Si viene algo como “01/09/2025”
  m = s.match(/^(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})$/);
  if (m) {
    const dd = +m[1], mm = +m[2], y = +m[3];
    if (dd && mm && y) return `${String(dd).padStart(2,'0')} ${_MES_ES[mm-1]} ${y}`;
  }

  return s; // no se pudo parsear, deja tal cual
}

// Reemplaza texto en nodos que ya están pintados
function _replaceDateText(node){
  if (!node) return;
  const raw = (node.textContent || '').trim();
  const pretty = formatDateHumanES(raw);
  if (pretty && pretty !== raw) node.textContent = pretty;
}

// ➊ Normaliza las fechas de la lista de salary updates (3ra columna)
(function forceSalaryListDates(){
  const box = document.getElementById('salary-updates-box');
  if (!box) return;

  const run = () => {
    box.querySelectorAll('.salary-entry').forEach((row, i) => {
      if (i === 0) return; // header
      const dateCell = row.querySelector('span:nth-child(3)');
      if (dateCell) _replaceDateText(dateCell);
    });
  };

  // correr ahora y observar cambios futuros
  run();
  const mo = new MutationObserver(run);
  mo.observe(box, { childList:true, subtree:true });
})();

// ➋ Normaliza cualquier “campo Date” en el tab Hire con layout Label arriba / valor abajo
(function normalizeGenericHireDates(){
  const hire = document.getElementById('hire');
  if (!hire) return;

  const run = () => {
    hire.querySelectorAll('.field').forEach(f => {
      const lab = f.querySelector('label');
      if (!lab) return;
      const txt = (lab.textContent || '').trim().toLowerCase();
      if (txt === 'date' || txt === 'fecha') {
        // valor suele estar en el primer elemento no-label dentro del field (evitamos inputs)
        const val = Array.from(f.children).find(el => el !== lab && el.tagName !== 'INPUT' && el.tagName !== 'SELECT' && el.tagName !== 'TEXTAREA');
        if (val) _replaceDateText(val);
      }
    });
  };

  // correr ahora y observar cambios en todo el tab
  run();
  const mo = new MutationObserver(run);
  mo.observe(hire, { childList:true, subtree:true });
})();
