// =========================
// Interviewing popup
// =========================
let _interviewingOppId = null;
let _interviewingDropdownEl = null;

const STAGE_ORDER_PRIORITY = [
  'Signed',
  'Negotiating',
  'Sourcing',
  'Interviewing',
  'Stop',
  'NDA Sent',
  'Deep Dive',
  'Close Win',
  'Closed Lost'
];

function openInterviewingPopup(opportunityId, dropdownElement) {
  _interviewingOppId = Number(opportunityId);
  _interviewingDropdownEl = dropdownElement;

  const popup = document.getElementById('interviewingPopup');
  const input = document.getElementById('interviewingStartDate');
  const saveBtn = document.getElementById('saveInterviewingStartDate');

  if (!popup || !input || !saveBtn) {
    console.error('❌ Interviewing popup elements not found in HTML');
    return;
  }

  // reset
  input.value = '';

  popup.style.display = 'flex';

  // IMPORTANT: asignar onclick para no duplicar listeners
  saveBtn.onclick = async () => {
    if (saveBtn.disabled) return;

    const date = (input.value || '').trim();
    if (!date) {
      alert('Please select a start date.');
      return;
    }

    try {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';

      // 1) Insert en tabla interviewing
      const res = await fetch(`${API_BASE}/interviewing`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          opportunity_id: _interviewingOppId,
          since_interviewing: date
        })
      });

      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        console.error('❌ /interviewing failed:', res.status, txt);
        alert('Error saving interviewing start date. Please try again.');
        return;
      }

      // 2) Cambiar stage
      await patchOpportunityStage(_interviewingOppId, 'Interviewing', _interviewingDropdownEl);

      // 3) Cerrar
      closeInterviewingPopup();

    } catch (err) {
      console.error('❌ Interviewing save error:', err);
      alert('Network error. Please try again.');
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save';
    }
  };
}

function closeInterviewingPopup() {
  const popup = document.getElementById('interviewingPopup');
  if (popup) popup.style.display = 'none';
  _interviewingOppId = null;
  _interviewingDropdownEl = null;
}

// (Opcional) cerrar al clickear el overlay (background)
document.addEventListener('click', (e) => {
  const overlay = document.getElementById('interviewingPopup');
  if (overlay && e.target === overlay) closeInterviewingPopup();
});
// === Helper: traer el nombre del cliente desde accounts usando account_id ===
async function resolveAccountName(opp) {
  // si ya viene correcto, úsalo
  const direct = (opp.client_name || '').trim();
  if (direct) return direct;

  const accountId = opp.account_id ?? opp.accountId ?? opp.accountid ?? null;
  if (!accountId) return 'the client';

  try {
    // intenta endpoint REST de item único
    let r = await fetch(`${API_BASE}/accounts/${encodeURIComponent(accountId)}`, { credentials: 'include' });
    if (r.ok) {
      const acc = await r.json();
      return (acc.client_name || acc.account_name || acc.name || '').trim() || 'the client';
    }

    // fallback: buscar en lista si no tienes endpoint por id
    r = await fetch(`${API_BASE}/accounts`, { credentials: 'include' });
    if (r.ok) {
      const list = await r.json();
      const acc = (list || []).find(a =>
        String(a.account_id ?? a.id ?? '').trim() === String(accountId).trim()
      );
      if (acc) return (acc.client_name || acc.account_name || acc.name || '').trim() || 'the client';
    }
  } catch (e) {
    console.warn('resolveAccountName() failed:', e);
  }
  return 'the client';
}

// ——— Current user helpers ———
function getCurrentUserEmail(){
  return (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase()
    .trim();
}

const BIRTHDAY_CELEBRATION_PREFIX = 'birthday_celebration_seen';
let birthdayCelebrationShownInSession = false;
const birthdayCelebrationProfilePromises = new Map();

function getTodayLocalIso() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function normalizeBirthdayIso(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  return raw.slice(0, 10);
}

function isBirthdayToday(value) {
  const iso = normalizeBirthdayIso(value);
  if (!iso) return false;
  const [, month, day] = iso.split('-');
  const today = getTodayLocalIso();
  return month === today.slice(5, 7) && day === today.slice(8, 10);
}

function birthdayCelebrationKey(userId) {
  return `${BIRTHDAY_CELEBRATION_PREFIX}:${userId != null ? String(userId) : 'unknown'}`;
}

function alreadySawBirthdayCelebration(userId) {
  return localStorage.getItem(birthdayCelebrationKey(userId)) === getTodayLocalIso();
}

function markBirthdayCelebrationSeen(userId) {
  localStorage.setItem(birthdayCelebrationKey(userId), getTodayLocalIso());
}

async function getCurrentUserProfileForBirthday(email) {
  const normalizedEmail = String(email || getCurrentUserEmail() || '').trim().toLowerCase();
  if (!normalizedEmail) return null;

  if (!birthdayCelebrationProfilePromises.has(normalizedEmail)) {
    const request = fetch(`${API_BASE}/users?email=${encodeURIComponent(normalizedEmail)}`, {
      credentials: 'include'
    })
      .then(async (res) => {
        if (!res.ok) return null;
        const users = await res.json();
        if (!Array.isArray(users)) return null;
        return users.find((user) => String(user.email_vintti || '').toLowerCase() === normalizedEmail) || null;
      })
      .catch((error) => {
        console.warn('Birthday celebration profile lookup failed:', error);
        return null;
      });
    birthdayCelebrationProfilePromises.set(normalizedEmail, request);
  }

  return birthdayCelebrationProfilePromises.get(normalizedEmail) || null;
}

function ensureBirthdayCelebrationStyles() {
  if (document.getElementById('birthdayCelebrationStyles')) return;

  const style = document.createElement('style');
  style.id = 'birthdayCelebrationStyles';
  style.textContent = `
    .birthday-celebration-overlay {
      position: fixed;
      inset: 0;
      z-index: 12000;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      overflow: hidden;
      background:
        radial-gradient(circle at 15% 18%, rgba(220, 255, 89, 0.22), transparent 18%),
        radial-gradient(circle at 84% 16%, rgba(255, 142, 107, 0.18), transparent 18%),
        linear-gradient(135deg, rgba(7, 19, 60, 0.64), rgba(17, 32, 88, 0.5));
      backdrop-filter: blur(14px);
      animation: birthdayOverlayFadeIn .4s ease;
    }
    .birthday-celebration-overlay::before,
    .birthday-celebration-overlay::after {
      content: '';
      position: absolute;
      width: 420px;
      height: 420px;
      border-radius: 50%;
      filter: blur(36px);
      opacity: .38;
      pointer-events: none;
    }
    .birthday-celebration-overlay::before {
      top: -140px;
      left: -110px;
      background: radial-gradient(circle, rgba(211, 255, 60, 0.95), transparent 60%);
    }
    .birthday-celebration-overlay::after {
      right: -140px;
      bottom: -180px;
      background: radial-gradient(circle, rgba(255, 143, 109, 0.9), transparent 60%);
    }
    .birthday-celebration-card {
      position: relative;
      width: min(720px, calc(100vw - 32px));
      overflow: hidden;
      border-radius: 36px;
      padding: 38px 42px 36px;
      text-align: center;
      background:
        linear-gradient(160deg, rgba(255,255,255,0.98) 0%, rgba(255,249,236,0.98) 44%, rgba(255,236,229,0.98) 100%);
      box-shadow:
        0 32px 120px rgba(5, 12, 43, 0.38),
        inset 0 1px 0 rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(255, 255, 255, 0.4);
      animation: birthdayCardPop .55s cubic-bezier(.2,.8,.2,1);
      font-family: 'Onest', sans-serif;
      z-index: 2;
    }
    .birthday-celebration-card::before {
      content: '';
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 18% 18%, rgba(213, 255, 75, 0.28), transparent 18%),
        radial-gradient(circle at 82% 16%, rgba(255, 152, 118, 0.24), transparent 18%),
        radial-gradient(circle at 50% 118%, rgba(0, 40, 255, 0.12), transparent 32%);
      pointer-events: none;
    }
    .birthday-celebration-card::after {
      content: '';
      position: absolute;
      inset: 16px;
      border-radius: 28px;
      border: 1px solid rgba(13, 42, 109, 0.06);
      pointer-events: none;
    }
    .birthday-celebration-sky {
      position: absolute;
      inset: 0;
      pointer-events: none;
      z-index: 1;
    }
    .birthday-celebration-balloon {
      position: absolute;
      width: var(--balloon-size, 92px);
      height: calc(var(--balloon-size, 92px) * 1.18);
      border-radius: 50% 50% 46% 46%;
      pointer-events: none;
      background: var(--balloon-fill, linear-gradient(180deg, #5b7bff 0%, #0028ff 100%));
      box-shadow:
        inset -10px -16px 24px rgba(0, 0, 0, 0.08),
        inset 10px 12px 18px rgba(255, 255, 255, 0.22),
        0 20px 40px rgba(12, 25, 72, 0.18);
      opacity: .96;
      animation:
        birthdayBalloonRise var(--rise-duration, 15s) linear infinite,
        birthdayBalloonSway var(--sway-duration, 4.8s) ease-in-out infinite;
      animation-delay: var(--delay, 0s), var(--delay, 0s);
    }
    .birthday-celebration-balloon::before {
      content: '';
      position: absolute;
      top: 16%;
      left: 18%;
      width: 28%;
      height: 20%;
      border-radius: 50%;
      background: rgba(255, 255, 255, 0.34);
      transform: rotate(-24deg);
    }
    .birthday-celebration-balloon::after {
      content: '';
      position: absolute;
      left: 50%;
      top: 100%;
      width: 2px;
      height: 90px;
      background: linear-gradient(180deg, rgba(26, 42, 92, 0.28), rgba(26, 42, 92, 0.04));
      transform: translateX(-50%);
    }
    .birthday-celebration-balloon.is-blue {
      --balloon-fill: linear-gradient(180deg, #6d87ff 0%, #173eff 100%);
    }
    .birthday-celebration-balloon.is-lime {
      --balloon-fill: linear-gradient(180deg, #efff9d 0%, #d8ff4d 100%);
    }
    .birthday-celebration-balloon.is-coral {
      --balloon-fill: linear-gradient(180deg, #ffb194 0%, #ff7f5a 100%);
    }
    .birthday-celebration-balloon.is-blush {
      --balloon-fill: linear-gradient(180deg, #ffd9e6 0%, #f4a9c1 100%);
    }
    .birthday-celebration-balloon.is-soft {
      opacity: .72;
    }
    .birthday-celebration-topline {
      display: flex;
      justify-content: center;
      align-items: center;
      gap: 16px;
      margin-bottom: 18px;
    }
    .birthday-celebration-topline::before,
    .birthday-celebration-topline::after {
      content: '';
      width: 72px;
      height: 1px;
      background: linear-gradient(90deg, transparent, rgba(0, 40, 255, 0.22), transparent);
    }
    .birthday-celebration-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 9px 18px;
      border-radius: 999px;
      background: rgba(255,255,255,0.9);
      color: #18346a;
      font-size: .84rem;
      font-weight: 700;
      letter-spacing: .12em;
      text-transform: uppercase;
      box-shadow: 0 14px 26px rgba(20, 38, 92, 0.08);
    }
    .birthday-celebration-title {
      margin: 8px 0 0;
      color: #0028ff;
      font-size: clamp(2.4rem, 5vw, 4.6rem);
      line-height: .92;
      font-weight: 800;
      letter-spacing: -.04em;
      max-width: 560px;
      margin-left: auto;
      margin-right: auto;
      text-wrap: balance;
    }
    .birthday-celebration-copy {
      margin: 20px auto 0;
      max-width: 520px;
      color: #20304f;
      font-size: 1.08rem;
      line-height: 1.72;
      text-wrap: balance;
    }
    .birthday-celebration-dismiss {
      margin-top: 28px;
      border: none;
      border-radius: 999px;
      padding: 15px 28px;
      background: linear-gradient(90deg, #d8ff4d 0%, #efffa5 100%);
      color: #102040;
      font-size: 1rem;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 18px 36px rgba(211, 255, 60, 0.28);
      transition: transform .2s ease, box-shadow .2s ease;
    }
    .birthday-celebration-dismiss:hover {
      transform: translateY(-1px) scale(1.02);
      box-shadow: 0 22px 40px rgba(211, 255, 60, 0.34);
    }
    .birthday-celebration-confetti,
    .birthday-celebration-confetti::before,
    .birthday-celebration-confetti::after {
      position: absolute;
      inset: 0;
      pointer-events: none;
    }
    .birthday-celebration-confetti::before,
    .birthday-celebration-confetti::after {
      content: '';
      top: auto;
      bottom: -12%;
      width: 240px;
      height: 56%;
      background-image:
        radial-gradient(circle, #0028ff 0 3px, transparent 3.6px),
        radial-gradient(circle, #ff8f6d 0 4px, transparent 4.6px),
        radial-gradient(circle, #dfff65 0 4px, transparent 4.6px),
        radial-gradient(circle, rgba(255,255,255,0.9) 0 3px, transparent 3.6px);
      background-size: 62px 62px, 68px 68px, 58px 58px, 52px 52px;
      opacity: .24;
      animation: birthdayConfettiFloat 10s linear infinite;
    }
    .birthday-celebration-confetti::before {
      left: -2%;
    }
    .birthday-celebration-confetti::after {
      right: -2%;
      animation-duration: 12s;
      animation-direction: reverse;
    }
    .birthday-celebration-confetti.is-delayed::before,
    .birthday-celebration-confetti.is-delayed::after {
      animation-delay: 1.8s;
      opacity: .18;
    }
    @keyframes birthdayOverlayFadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes birthdayCardPop {
      0% { opacity: 0; transform: translateY(28px) scale(.92) rotate(-1deg); }
      70% { opacity: 1; transform: translateY(-4px) scale(1.01) rotate(.3deg); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    @keyframes birthdayConfettiFloat {
      0% { transform: translateY(18px); }
      50% { transform: translateY(-8px); }
      100% { transform: translateY(18px); }
    }
    @keyframes birthdayBalloonRise {
      0% { transform: translate3d(0, 105vh, 0); }
      100% { transform: translate3d(0, -130vh, 0); }
    }
    @keyframes birthdayBalloonSway {
      0%, 100% { margin-left: 0; }
      50% { margin-left: 18px; }
    }
    @keyframes birthdaySparkleFloat {
      0%, 100% { transform: translateY(0) scale(1); opacity: .75; }
      50% { transform: translateY(-8px) scale(1.2); opacity: 1; }
    }
  `;
  document.head.appendChild(style);
}

function showBirthdayCelebrationOverlay(displayName, { onDismiss } = {}) {
  ensureBirthdayCelebrationStyles();

  const existing = document.getElementById('birthdayCelebrationOverlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'birthdayCelebrationOverlay';
  overlay.className = 'birthday-celebration-overlay';
  overlay.innerHTML = `
    <div class="birthday-celebration-sky" aria-hidden="true">
      <span class="birthday-celebration-balloon is-blue" style="left:6%; --balloon-size:90px; --delay:-1s; --rise-duration:15s; --sway-duration:4.6s;"></span>
      <span class="birthday-celebration-balloon is-lime" style="left:14%; --balloon-size:74px; --delay:-7s; --rise-duration:18s; --sway-duration:5.2s;"></span>
      <span class="birthday-celebration-balloon is-coral" style="left:22%; --balloon-size:106px; --delay:-3s; --rise-duration:17s; --sway-duration:4.9s;"></span>
      <span class="birthday-celebration-balloon is-soft is-blush" style="left:31%; --balloon-size:68px; --delay:-11s; --rise-duration:20s; --sway-duration:5.8s;"></span>
      <span class="birthday-celebration-balloon is-blue" style="left:41%; --balloon-size:82px; --delay:-5s; --rise-duration:16s; --sway-duration:4.7s;"></span>
      <span class="birthday-celebration-balloon is-lime" style="left:53%; --balloon-size:118px; --delay:-9s; --rise-duration:19s; --sway-duration:6s;"></span>
      <span class="birthday-celebration-balloon is-coral" style="left:64%; --balloon-size:78px; --delay:-14s; --rise-duration:18s; --sway-duration:5.1s;"></span>
      <span class="birthday-celebration-balloon is-soft is-blue" style="left:74%; --balloon-size:66px; --delay:-2s; --rise-duration:21s; --sway-duration:6.2s;"></span>
      <span class="birthday-celebration-balloon is-blush" style="left:84%; --balloon-size:98px; --delay:-12s; --rise-duration:17s; --sway-duration:5.4s;"></span>
      <span class="birthday-celebration-balloon is-lime" style="left:92%; --balloon-size:72px; --delay:-6s; --rise-duration:20s; --sway-duration:6s;"></span>
    </div>
    <div class="birthday-celebration-card" role="dialog" aria-modal="true" aria-label="Birthday celebration">
      <div class="birthday-celebration-confetti"></div>
      <div class="birthday-celebration-confetti is-delayed"></div>
      <span class="birthday-celebration-sparkle is-one"></span>
      <span class="birthday-celebration-sparkle is-two"></span>
      <span class="birthday-celebration-sparkle is-three"></span>
      <div class="birthday-celebration-topline" aria-hidden="true">
        <span class="birthday-celebration-badge">Happy Birthday</span>
      </div>
      <h2 class="birthday-celebration-title">${escapeHtml(displayName ? `${displayName}, this one is for you.` : 'Today is worth celebrating.')}</h2>
      <p class="birthday-celebration-copy">Wishing you a day full of wins, good energy, sweet moments and a little extra Vintti magic.</p>
      <button type="button" class="birthday-celebration-dismiss">Start the day</button>
    </div>
  `;

  const dismiss = () => {
    if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    if (typeof onDismiss === 'function') {
      try { onDismiss(); } catch (error) { console.warn('Birthday dismiss callback failed:', error); }
    }
  };

  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) dismiss();
  });
  overlay.querySelector('.birthday-celebration-dismiss')?.addEventListener('click', dismiss);

  document.body.appendChild(overlay);
}

async function maybeShowBirthdayCelebration({ email, fallbackName = '', delayMs = 0, onDismiss = null } = {}) {
  if (birthdayCelebrationShownInSession) return false;

  const normalizedEmail = String(email || getCurrentUserEmail() || '').trim().toLowerCase();
  if (!normalizedEmail) return false;

  const user = await getCurrentUserProfileForBirthday(normalizedEmail);
  if (!user?.fecha_nacimiento || !isBirthdayToday(user.fecha_nacimiento)) return false;

  const userId = user.user_id ?? localStorage.getItem('user_id') ?? 'unknown';
  if (alreadySawBirthdayCelebration(userId)) return false;

  birthdayCelebrationShownInSession = true;
  markBirthdayCelebrationSeen(userId);

  const displayName = String(user.nickname || fallbackName || user.user_name || '').trim();
  window.setTimeout(() => showBirthdayCelebrationOverlay(displayName, { onDismiss }), Math.max(0, Number(delayMs) || 0));
  return true;
}

window.maybeShowBirthdayCelebration = maybeShowBirthdayCelebration;

function queueMonthlyMoodRecap({ delayMs = 0, force = false } = {}) {
  if (typeof window.maybeShowMonthlyMoodRecap !== 'function') return Promise.resolve(false);
  return window.maybeShowMonthlyMoodRecap({ delayMs, force }).catch((error) => {
    console.warn('Monthly mood recap failed:', error);
    return false;
  });
}

const _plainTextParser = document.createElement('div');
function htmlToPlainText(value) {
  if (value === null || value === undefined) return '';
  _plainTextParser.innerHTML = value;
  const text = _plainTextParser.textContent || _plainTextParser.innerText || '';
  _plainTextParser.textContent = '';
  return text;
}

function escapeAttribute(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\n/g, '&#10;');
}

function normalizeDateOnly(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const parsed = raw.length <= 10 ? new Date(`${raw}T00:00:00`) : new Date(raw);
  if (Number.isNaN(parsed.getTime())) return null;
  parsed.setHours(0, 0, 0, 0);
  return parsed;
}

function toIsoDate(value) {
  const d = normalizeDateOnly(value);
  if (!d) return '';
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function getOpportunityReferenceDate(opp) {
  if (!opp || typeof opp !== 'object') return '';
  const candidates = [
    opp._sort_date,
    opp.latest_sourcing_date,
    opp.nda_signature_or_start_date,
    opp.opp_close_date,
  ];
  for (const candidate of candidates) {
    const iso = toIsoDate(candidate);
    if (iso) return iso;
  }
  return '';
}

function csvEscape(value) {
  if (value === null || value === undefined) return '';
  let text = value;
  if (typeof value === 'object') {
    try {
      text = JSON.stringify(value);
    } catch (err) {
      text = String(value);
    }
  }
  const clean = String(text);
  if (/[",\n]/.test(clean)) {
    return `"${clean.replace(/"/g, '""')}"`;
  }
  return clean;
}

function downloadTextFile(filename, content, mimeType = 'text/plain;charset=utf-8;') {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function fetchOpportunityBatchSourcingDates() {
  const res = await fetch(`${API_BASE}/opportunities/batch-sourcing-dates`, {
    credentials: 'include'
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`batch-sourcing-dates failed ${res.status}: ${text}`);
  }

  const rows = await res.json();
  const grouped = new Map();
  (Array.isArray(rows) ? rows : []).forEach((row) => {
    const key = String(row?.opportunity_id || '');
    if (!key) return;
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(row);
  });
  return grouped;
}

function hydrateClosedLostMotives(opportunities) {
  if (!Array.isArray(opportunities) || opportunities.length === 0) return;
  const pendingIds = opportunities
    .filter((opp) => String(opp?.opp_stage || '').trim() === 'Closed Lost')
    .filter((opp) => !String(opp?.motive_close_lost || '').trim())
    .map((opp) => String(opp?.opportunity_id || '').trim())
    .filter(Boolean);

  if (!pendingIds.length) return;

  Promise.all(pendingIds.map(async (id) => {
    try {
      const res = await fetch(`${API_BASE}/opportunities/${encodeURIComponent(id)}`, { credentials: 'include' });
      if (!res.ok) return;
      const fullOpp = await res.json();
      const target = opportunities.find((opp) => String(opp?.opportunity_id || '') === id);
      if (!target) return;
      if (fullOpp && typeof fullOpp === 'object') {
        Object.assign(target, fullOpp);
      }
    } catch (err) {
      console.warn('Unable to hydrate closed lost motive for opp', id, err);
    }
  })).catch(() => {});
}
// --- Email cuando se asigna / cambia HR Lead en una oportunidad ---
async function sendHRLeadAssignmentEmail(opportunityId, hrEmail) {
  try {
    const cleanEmail = String(hrEmail || '').toLowerCase().trim();
    if (!cleanEmail) {
      console.warn('⚠️ No HR Lead email to notify for opp', opportunityId);
      return;
    }

    // 1) Traer detalles de la oportunidad
    const r = await fetch(`${API_BASE}/opportunities/${opportunityId}`, { 
      credentials: 'include' 
    });
    if (!r.ok) throw new Error(`GET opp ${opportunityId} failed ${r.status}`);
    const opp = await r.json();

    // 2) Resolver client_name desde accounts
    const clientName = await resolveAccountName(opp);
    const position   = opp.opp_position_name || 'Role';
    const model      = opp.opp_model || '';

    // 3) Subject info de client & position
    const subject = `You’ve been assigned a new search – ${clientName} | ${position}`;

    // Por si quieres usar escapeHtml del helper global
    const esc = s => String(s || '').replace(/[&<>"]/g, ch => (
      {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]
    ));

    // 4) Cuerpo en HTML, amigable y cute
    const htmlBody = `
<div style="font-family: Inter, Arial, sans-serif; font-size: 14px; color: #222; line-height: 1.6;">
  <p>Hi there 💕</p>

  <p>
    You’ve just been assigned a brand new search in Vintti Hub – how exciting! ✨
  </p>

  <p style="margin: 12px 0;">
    <strong>Client:</strong> ${esc(clientName)}<br/>
    <strong>Position:</strong> ${esc(position)}<br/>
    <strong>Model:</strong> ${esc(model)}
  </p>

  <p>
    You’re going to do amazing on this one – as always. 🌸<br/>
  </p>

  <p style="margin-top: 16px; font-size: 12px; color: #777;">
    - Vintti Hub
  </p>
</div>
    `.trim();

    // 5) Enviar email a HR Lead + Angie
    const payload = {
      to: [cleanEmail]
        .filter((v, i, arr) => v && arr.indexOf(v) === i),
      subject,
      body: htmlBody,
      body_html: htmlBody,
      content_type: 'text/html',
      html: true
    };

    const res = await fetch(`${API_BASE}/send_email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      throw new Error(`send_email failed ${res.status}: ${errText}`);
    }

    console.info('✅ HR Lead assignment email sent to', cleanEmail, 'for opp', opportunityId);
  } catch (err) {
    console.error('❌ Failed to send HR Lead assignment email:', err);
  }
}

//const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
const API_BASE =
  (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

// const batchCountCache = new Map();

const candidatesCountCache = new Map();
const interviewedCountCache = new Map();

// function requestBatchCount(opportunityId) {
//   if (!opportunityId) return Promise.resolve(null);
//   if (!batchCountCache.has(opportunityId)) {
//     const promise = fetch(`${API_BASE}/opportunities/${encodeURIComponent(opportunityId)}/batches`)
//       .then((res) => (res.ok ? res.json() : []))
//       .then((rows) => (Array.isArray(rows) ? rows.length : null))
//       .catch((err) => {
//         console.error('Error fetching batches for opportunity', opportunityId, err);
//         return null;
//       });
//     batchCountCache.set(opportunityId, promise);
//   }
//   return batchCountCache.get(opportunityId);
// }

function requestCandidatesCount(opportunityId) {
  if (!opportunityId) return Promise.resolve(0);

  if (!candidatesCountCache.has(opportunityId)) {
    const promise = fetch(
      `${API_BASE}/opportunities/${encodeURIComponent(opportunityId)}/candidates_count`
    )
      .then(res => res.ok ? res.json() : { candidates_count: 0 })
      .then(data => Number(data.candidates_count || 0))
      .catch(err => {
        console.error('Error fetching candidates count', err);
        return 0;
      });

    candidatesCountCache.set(opportunityId, promise);
  }

  return candidatesCountCache.get(opportunityId);
}

function requestInterviewedCount(opportunityId) {
  if (!opportunityId) return Promise.resolve(0);

  if (!interviewedCountCache.has(opportunityId)) {
    const promise = fetch(
      `${API_BASE}/opportunities/${encodeURIComponent(opportunityId)}/interviewed_count`
    )
      .then(res => res.ok ? res.json() : { interviewed_count: 0 })
      .then(data => Number(data.interviewed_count || 0))
      .catch(err => {
        console.error('Error fetching interviewed count', err);
        return 0;
      });

    interviewedCountCache.set(opportunityId, promise);
  }

  return interviewedCountCache.get(opportunityId);
}


async function hydrateCandidatesCountCell(opportunityId, cell) {
  if (!cell) return;

  if (!opportunityId) {
    cell.textContent = '—';
    cell.removeAttribute('data-candidates-count');
    return;
  }

  cell.textContent = '…';

  const count = await requestCandidatesCount(opportunityId);

  if (typeof count === 'number') {
    cell.textContent = String(count);
    cell.dataset.candidatesCount = String(count);
  } else {
    cell.textContent = '—';
    cell.removeAttribute('data-candidates-count');
  }
}

async function hydrateInterviewedCountCell(opportunityId, cell) {
  if (!cell) return;

  if (!opportunityId) {
    cell.textContent = '—';
    cell.removeAttribute('data-interviewed-count');
    return;
  }

  cell.textContent = '…';

  const count = await requestInterviewedCount(opportunityId);

  if (typeof count === 'number') {
    cell.textContent = String(count);
    cell.dataset.interviewedCount = String(count);
  } else {
    cell.textContent = '—';
    cell.removeAttribute('data-interviewed-count');
  }
}

// async function hydrateBatchCountCell(opportunityId, cell) {
//   if (!cell) return;
//   if (!opportunityId) {
//     cell.textContent = '—';
//     cell.removeAttribute('data-batch-count');
//     return;
//   }
//   cell.textContent = '…';
//   const count = await requestBatchCount(opportunityId);
//   if (typeof count === 'number') {
//     cell.textContent = count;
//     cell.dataset.batchCount = count;
//   } else {
//     cell.textContent = '—';
//     cell.removeAttribute('data-batch-count');
//   }
// }

// Try to get user_id from storage; if missing, resolve by email and cache it
// Usa getCurrentUserId({force:true}) para ignorar cache.
async function getCurrentUserId({ force = false } = {}) {
  const email = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase()
    .trim();

  // invalida cache si cambió el email o si piden "force"
  const cachedUid = localStorage.getItem('user_id');
  const cachedOwner = localStorage.getItem('user_id_owner_email');
  if (force || (cachedOwner && cachedOwner !== email)) {
    localStorage.removeItem('user_id');
  }

  // 1) ¿Sigue habiendo cache válido?
  const cached = localStorage.getItem('user_id');
  console.debug('[uid] cached:', cached, '(owner:', localStorage.getItem('user_id_owner_email'), ')');
  if (cached) return Number(cached);

  if (!email) {
    console.warn('[uid] No email available to resolve user_id');
    return null;
  }

  // 2) Fast path: /users?email=
  try {
    const fast = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/users?email=${encodeURIComponent(email)}`);
    console.debug('[uid] /users?email status:', fast.status);
    if (fast.ok) {
      const arr = await fast.json(); // [] o [ { user_id, email_vintti, ... } ]
      const hit = Array.isArray(arr) ? arr.find(u => (u.email_vintti || '').toLowerCase() === email) : null;
      console.debug('[uid] hit (by email):', hit?.user_id);
      if (hit?.user_id != null) {
        localStorage.setItem('user_id', String(hit.user_id));
        localStorage.setItem('user_id_owner_email', email);
        return Number(hit.user_id);
      }
    }
  } catch (e) {
    console.debug('users?email lookup failed (will try full list):', e);
  }

  // 3) Fallback: /users (full) y match por email
  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users');
    console.debug('[uid] /users status:', res.status);
    if (!res.ok) return null;
    const users = await res.json();
    const me = (users || []).find(u => String(u.email_vintti || '').toLowerCase() === email);
    console.debug('[uid] hit (by full list):', me?.user_id);
    if (me?.user_id != null) {
      localStorage.setItem('user_id', String(me.user_id));
      localStorage.setItem('user_id_owner_email', email);
      return Number(me.user_id);
    }
  } catch (e) {
    console.error('Could not resolve current user_id:', e);
  }
  return null;
}
window.getCurrentUserId = getCurrentUserId;
// ——— API helper que SIEMPRE intenta enviar el usuario ———
async function api(path, opts = {}) {
  const uid = await window.getCurrentUserId(); // puede ser null
  const url = `${API_BASE}${path}`;

  // 1) Intento con cookie + header X-User-Id si lo tengo
  let headers = { ...(opts.headers || {}) };
  if (uid != null) headers['X-User-Id'] = String(uid);

  let r = await fetch(url, {
    ...opts,
    headers,
    credentials: 'include'
  });

  // 2) Si el backend/proxy quitó headers o hay 401, reintenta con ?user_id=
  if (r.status === 401 && uid != null) {
    const sep = url.includes('?') ? '&' : '?';
    const urlWithQuery = `${url}${sep}user_id=${encodeURIComponent(uid)}`;
    r = await fetch(urlWithQuery, {
      ...opts,
      credentials: 'include'
    });
  }

  return r;
}
window.api = api;

async function logOpportunityTrack(buttonId, page = 'opp principal') {
  if (!buttonId) return;
  try {
    const userId = await getCurrentUserId();
    if (userId == null) return;
    await fetch(`${API_BASE}/tracks`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, button: String(buttonId), page: String(page) }),
      credentials: 'include'
    });
  } catch (err) {
    console.debug('Track log failed:', err);
  }
}

function trackIdFromEl(el, fallback) {
  return el?.id || el?.getAttribute('data-track-id') || fallback || '';
}
// ——— Helpers de nombre/escape ———
function escapeHtml(s){
  return String(s || '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));
}

function prettyNameFromEmail(email, fallback = 'Assign HR Lead') {
  const local = String(email || '').split('@')[0];
  if (!local) return fallback;
  const cleaned = local.replace(/[_\-.]+/g, ' ').trim();
  if (!cleaned) return fallback;
  return cleaned.split(/\s+/).map(part => part ? part[0].toUpperCase() + part.slice(1) : '').join(' ') || fallback;
}

function displayNameForHR(email){
  const key = String(email||'').toLowerCase();
  if (!key) return 'Assign HR Lead';
  if (HIDDEN_HR_FILTER_EMAILS.has(key)) return 'Assign HR Lead';
  const directoryName = (window.userDirectoryByEmail || {})[key];
  if (directoryName) return directoryName;
  const u = (window.allowedHRUsers||[]).find(x => String(x.email_vintti||'').toLowerCase() === key);
  if (u?.user_name) return u.user_name;
  return prettyNameFromEmail(email, 'Assign HR Lead');
}

function displayNameForSales(value){
  const key = String(value||'').toLowerCase();

  // 1) Si viene email -> busca por email
  let u = (window.allowedSalesUsers||[]).find(x => String(x.email_vintti||'').toLowerCase() === key);
  if (u?.user_name) return u.user_name;

  // 2) Si viene nombre -> busca por nombre
  u = (window.allowedSalesUsers||[]).find(x => String(x.user_name||'').toLowerCase() === key);
  if (u?.user_name) return u.user_name;

  // 3) Fallback heurístico legacy
  if (key.includes('bahia'))   return 'Bahía';
  if (key.includes('lara'))    return 'Lara';
  if (key.includes('agustin')) return 'Agustín';
  if (key.includes('mariano')) return 'Mariano';
  if (key.includes('mia'))     return 'Mia Cavanagh';

  // 4) Último recurso
  return String(value||'Unassigned');
}

const HIDDEN_HR_FILTER_EMAILS = new Set([
  'bahia@vintti.com',
  'sol@vintti.com',
  'agustin@vintti.com',
  'agustina.barbero@vintti.com',
  'agustina.ferrari@vintti.com',
  'pilar.fernandez@vintti.com',
].map((email) => email.toLowerCase()));

const SALES_ALLOWED_EMAILS = new Set([
  'agustin@vintti.com',
  'bahia@vintti.com',
  'lara@vintti.com',
  'mariano@vintti.com',
  'mia@vintti.com',
].map((email) => email.toLowerCase()));

const SALES_ALLOWED_NAME_OVERRIDES = new Map([
  ['agustin@vintti.com', 'Agustín'],
  ['bahia@vintti.com', 'Bahía'],
  ['lara@vintti.com', 'Lara'],
  ['mariano@vintti.com', 'Mariano'],
  ['mia@vintti.com', 'Mia Cavanagh'],
]);

function buildDefaultSalesUsers() {
  return Array.from(SALES_ALLOWED_EMAILS)
    .map((email) => ({
      user_id: null,
      user_name: SALES_ALLOWED_NAME_OVERRIDES.get(email) || prettyNameFromEmail(email, email),
      email_vintti: email,
    }))
    .sort((a, b) => (a.user_name || '').localeCompare(b.user_name || ''));
}
window.allowedSalesUsers = (window.allowedSalesUsers && window.allowedSalesUsers.length)
  ? window.allowedSalesUsers
  : buildDefaultSalesUsers();
window.allowedHRUsers = window.allowedHRUsers || [];
window.userDirectoryByEmail = window.userDirectoryByEmail || {};
let roleDirectoryPromise = null;

function normalizeRoleDirectory(users) {
  const deduped = [];
  const seen = new Set();
  (Array.isArray(users) ? users : []).forEach(user => {
    const email = String(user?.email_vintti || '').trim().toLowerCase();
    if (!email || seen.has(email)) return;
    seen.add(email);
    deduped.push({
      user_id: user.user_id,
      user_name: user.user_name || user.email_vintti || email,
      email_vintti: email
    });
  });
  deduped.sort((a, b) => (a.user_name || '').localeCompare(b.user_name || ''));
  return deduped;
}

function buildUserDirectoryMap(users) {
  const map = {};
  (Array.isArray(users) ? users : []).forEach((user) => {
    const email = String(user?.email_vintti || '').trim().toLowerCase();
    if (!email || map[email]) return;
    if (user?.user_name) map[email] = user.user_name;
  });
  return map;
}

function ensureSalesUser(email, users = []) {
  const normalizedEmail = String(email || '').trim().toLowerCase();
  if (!normalizedEmail) return;
  const existing = (window.allowedSalesUsers || []).some(
    (user) => String(user.email_vintti || '').trim().toLowerCase() === normalizedEmail
  );
  if (existing) return;

  const directoryUser = (Array.isArray(users) ? users : []).find(
    (user) => String(user?.email_vintti || '').trim().toLowerCase() === normalizedEmail
  );
  window.allowedSalesUsers.push({
    user_id: directoryUser?.user_id || null,
    user_name: directoryUser?.user_name || SALES_ALLOWED_NAME_OVERRIDES.get(normalizedEmail) || prettyNameFromEmail(normalizedEmail, normalizedEmail),
    email_vintti: normalizedEmail
  });
  window.allowedSalesUsers.sort((a, b) => (a.user_name || '').localeCompare(b.user_name || ''));
}

async function fetchRoleDirectories() {
  const [hrRes, salesRes, usersRes] = await Promise.all([
    fetch(`${API_BASE}/users/recruiters`, { credentials: 'include' }),
    fetch(`${API_BASE}/users/sales-leads`, { credentials: 'include' }),
    fetch(`${API_BASE}/users`, { credentials: 'include' }),
  ]);
  if (!hrRes.ok) throw new Error(`Recruiter directory failed: ${hrRes.status}`);
  if (!salesRes.ok) throw new Error(`Sales directory failed: ${salesRes.status}`);
  if (!usersRes.ok) throw new Error(`Users directory failed: ${usersRes.status}`);
  const [hrData, salesData, usersData] = await Promise.all([hrRes.json(), salesRes.json(), usersRes.json()]);
  window.allowedHRUsers = normalizeRoleDirectory(hrData);
  window.allowedSalesUsers = normalizeRoleDirectory(salesData);
  window.userDirectoryByEmail = buildUserDirectoryMap(usersData);

  if (!window.allowedSalesUsers.length) {
    const fallbackFromUsers = (Array.isArray(usersData) ? usersData : []).filter((user) => {
      const email = String(user?.email_vintti || '').trim().toLowerCase();
      return email && SALES_ALLOWED_EMAILS.has(email);
    });
    if (fallbackFromUsers.length) {
      window.allowedSalesUsers = normalizeRoleDirectory(fallbackFromUsers);
    } else {
      window.allowedSalesUsers = buildDefaultSalesUsers();
    }
  }
  ensureSalesUser('mia@vintti.com', usersData);
}

function ensureRoleDirectoryPromise() {
  if (!roleDirectoryPromise) {
    roleDirectoryPromise = fetchRoleDirectories().catch(err => {
      console.error('Error loading role directories:', err);
      throw err;
    });
  }
  return roleDirectoryPromise;
}

async function ensureRoleDirectoriesLoaded() {
  if ((window.allowedHRUsers?.length || 0) && (window.allowedSalesUsers?.length || 0)) return;
  await ensureRoleDirectoryPromise();
}

ensureRoleDirectoryPromise();

window.generateSalesOptions = function generateSalesOptions(currentValue) {
  const normalized = String(currentValue || '').trim().toLowerCase();
  const allowedEmails = new Set((window.allowedSalesUsers || []).map(u => u.email_vintti));
  const isKnown = !!normalized && allowedEmails.has(normalized);

  let html = `<option disabled ${isKnown ? '' : 'selected'}>Assign Sales Lead</option>`;
  (window.allowedSalesUsers || []).forEach(user => {
    const email = user.email_vintti;
    const selected = (isKnown && email === normalized) ? 'selected' : '';
    html += `<option value="${email}" ${selected}>${escapeHtml(user.user_name)}</option>`;
  });
  return html;
};

window.generateHROptions = function generateHROptions(currentValue) {
  const normalized = String(currentValue || '').trim().toLowerCase();
  const visibleHrUsers = (window.allowedHRUsers || []).filter((user) => !HIDDEN_HR_FILTER_EMAILS.has(user.email_vintti));
  const allowedEmails = new Set(visibleHrUsers.map((u) => u.email_vintti));
  const isKnown = !!normalized && allowedEmails.has(normalized);
  const isHiddenSelection = !!normalized && HIDDEN_HR_FILTER_EMAILS.has(normalized);

  const shouldSelectDefault = !isKnown && (!normalized || isHiddenSelection);
  let html = `<option value="" ${shouldSelectDefault ? 'selected' : ''}>Assign HR Lead</option>`;
  visibleHrUsers.forEach((user) => {
    const email = user.email_vintti;
    const selected = normalized && email === normalized ? 'selected' : '';
    html += `<option value="${email}" ${selected}>${escapeHtml(user.user_name)}</option>`;
  });

  if (normalized && !isKnown && !isHiddenSelection) {
    const fallbackLabel = displayNameForHR(normalized) || prettyNameFromEmail(normalized);
    if (fallbackLabel && fallbackLabel !== 'Assign HR Lead') {
      html += `<option value="${normalized}" selected>${escapeHtml(fallbackLabel)}</option>`;
    }
  }
  return html;
};

document.addEventListener('DOMContentLoaded', () => {
  // --- Replacement UI wiring ---
    const el = document.getElementById('click-sound');
  el?.load();
const oppTypeSelect = document.getElementById('opp_type');
const replacementFields = document.getElementById('replacementFields');
const replacementCandidateInput = document.getElementById('replacementCandidate');
const replacementCandidatesList  = document.getElementById('replacementCandidates');
const replacementEndDateInput    = document.getElementById('replacementEndDate');

function toggleReplacementFields() {
  const isReplacement = oppTypeSelect && oppTypeSelect.value === 'Replacement';
  if (replacementFields) replacementFields.style.display = isReplacement ? 'block' : 'none';
  if (!isReplacement) {
    if (replacementCandidateInput) replacementCandidateInput.value = '';
    if (replacementEndDateInput) replacementEndDateInput.value = '';
  }
}
oppTypeSelect?.addEventListener('change', toggleReplacementFields);
toggleReplacementFields();

// Small debounce helper
function debounce(fn, wait = 250) {
  let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), wait); };
}

// Live search against /candidates?search=
replacementCandidateInput?.addEventListener('input', debounce(async (e) => {
  const q = e.target.value.trim();
  if (q.length < 2) return; // avoid spam
  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates?search=${encodeURIComponent(q)}`);
    const items = await res.json();
    replacementCandidatesList.innerHTML = '';
    items.forEach(({ candidate_id, name }) => {
      const opt = document.createElement('option');
      opt.value = `${candidate_id} - ${name}`;
      replacementCandidatesList.appendChild(opt);
    });
  } catch (err) {
    console.error('Error searching candidates:', err);
  }
}, 250));

function getReplacementCandidateId() {
  if (!replacementCandidateInput?.value) return null;
  const idStr = replacementCandidateInput.value.split(' - ')[0];
  const id = parseInt(idStr, 10);
  return Number.isInteger(id) ? id : null;
}

/* =========================
   10) Sidebar toggle with memory
   ========================= */

(() => {
  const sidebarToggleBtn = document.getElementById('sidebarToggle');
  const sidebarToggleIcon = document.getElementById('sidebarToggleIcon');
  const sidebarEl = document.querySelector('.sidebar');
  const mainContentEl = document.querySelector('.main-content');
  if (!sidebarToggleBtn || !sidebarToggleIcon || !sidebarEl || !mainContentEl) return;

  const isSidebarHidden = localStorage.getItem('sidebarHidden') === 'true';
  if (isSidebarHidden) {
    sidebarEl.classList.add('custom-sidebar-hidden');
    mainContentEl.classList.add('custom-main-expanded');
    sidebarToggleIcon.classList.remove('fa-chevron-left');
    sidebarToggleIcon.classList.add('fa-chevron-right');
    sidebarToggleBtn.style.left = '12px';
  } else {
    sidebarToggleBtn.style.left = '220px';
  }

  sidebarToggleBtn.addEventListener('click', () => {
    const hidden = sidebarEl.classList.toggle('custom-sidebar-hidden');
    mainContentEl.classList.toggle('custom-main-expanded', hidden);
    sidebarToggleIcon.classList.toggle('fa-chevron-left', !hidden);
    sidebarToggleIcon.classList.toggle('fa-chevron-right', hidden);
    sidebarToggleBtn.style.left = hidden ? '12px' : '220px';
    localStorage.setItem('sidebarHidden', hidden);
  });
})();


function setupFilterToggle(header, targetIdOverride) {
  if (!header || header.dataset.filterToggleBound === 'true') return;
  const targetId = targetIdOverride || header.getAttribute('data-target');
  if (!targetId) return;
  const icon = header.querySelector('i');

  function toggle() {
    const target = document.getElementById(targetId);
    if (!target) return;
    const isHidden = target.classList.toggle('hidden');
    if (icon) {
      icon.classList.toggle('rotate-up', !isHidden);
    }
  }

  header.addEventListener('click', toggle);
  const button = header.querySelector('button');
  if (button) {
    button.addEventListener('click', (event) => {
      event.stopPropagation();
      toggle();
    });
  }
  header.dataset.filterToggleBound = 'true';
}

document.querySelectorAll('.filter-header').forEach((header) => setupFilterToggle(header));
  const toggleButton = document.getElementById('toggleFilters');
  const filtersCard = document.getElementById('filtersCard');

  if (toggleButton && filtersCard) {
    toggleButton.addEventListener('click', () => {
      const isExpanded = filtersCard.classList.contains('expanded');
      filtersCard.classList.toggle('expanded', !isExpanded);
      filtersCard.classList.toggle('hidden', isExpanded);
      toggleButton.textContent = isExpanded ? '🔍 Filters' : '✖ Close Filters';
    });
  }
  const onOppPage = !!document.getElementById('opportunityTableBody');
  if (onOppPage) {
  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light')
    .then(response => response.json())
    .then(async data => {
      
      const tbody = document.getElementById('opportunityTableBody');
      tbody.innerHTML = '';
      // 🔄 Enriquecer con latest_sourcing_date solo para oportunidades en 'Sourcing'
      await Promise.all(data.map(async opp => {
        if (opp.opp_stage === 'Sourcing') {
          try {
            const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opp.opportunity_id}/latest_sourcing_date`);
            const result = await res.json();
            if (result.latest_sourcing_date) {
              opp.latest_sourcing_date = result.latest_sourcing_date;
            }
          } catch (err) {
            console.error(`Error fetching sourcing date for opp ${opp.opportunity_id}`, err);
          }
        }
      }));
      hydrateClosedLostMotives(data);
      // ✅ Precalcular días para ordenar Sourcing
      const today = new Date();
      for (const opp of data) {
        if (opp.opp_stage === 'Sourcing') {
          const ref = opp.latest_sourcing_date || opp.nda_signature_or_start_date || null;
          if (ref) {
            const d = new Date(ref);
            opp._days_since_batch = Math.ceil((today - d) / (1000 * 60 * 60 * 24)) - 1;
          } else {
            opp._days_since_batch = null; // sin fecha aún
          }
        }
      }

      if (!Array.isArray(data) || data.length === 0) {
        tbody.innerHTML = '<tr><td colspan="12">No data available</td></tr>';
        return;
      }

    // 👇 Orden de etapas personalizado
    const stageOrder = STAGE_ORDER_PRIORITY;

    // 👇 Agrupar oportunidades por stage
    const grouped = {};
    data.forEach(opp => {
      const stage = opp.opp_stage || '—';

      // Para Sourcing: usar exclusivamente nda_signature_or_start_date
      if (stage === 'Sourcing') {
        opp._sort_date = opp.nda_signature_or_start_date || null;
      }

      // Para Signed / Close Win / Closed Lost: usar opp_close_date
      else if (stage === 'Signed' || stage === 'Close Win' || stage === 'Closed Lost') {
        opp._sort_date = opp.opp_close_date || null;
      }

      // Otros stages: usar nda_signature_or_start_date como respaldo
      else {
        opp._sort_date = opp.nda_signature_or_start_date || null;
      }

      if (!grouped[stage]) grouped[stage] = [];
      grouped[stage].push(opp);
    });


    // 👇 Vaciar tbody
    tbody.innerHTML = '';
    // Ordenar internamente cada grupo por la fecha relevante
    Object.keys(grouped).forEach(stage => {
      grouped[stage].sort((a, b) => {
        if (stage === 'Sourcing') {
          const A = (typeof a._days_since_batch === 'number') ? a._days_since_batch : -Infinity;
          const B = (typeof b._days_since_batch === 'number') ? b._days_since_batch : -Infinity;
          return B - A; // 👈 mayor a menor por Days Since Batch
        }
        // 🔁 el resto queda con tu lógica por fecha
        const dateA = a._sort_date ? new Date(a._sort_date) : new Date(0);
        const dateB = b._sort_date ? new Date(b._sort_date) : new Date(0);
        return dateB - dateA;
      });
    });

    // 👇 Insertar oportunidades en orden
    stageOrder.forEach(stage => {
      if (grouped[stage]) {
        grouped[stage].forEach(opp => {
          let daysAgo = '';

          // 👉 Si la opp está en Signed / Close Win / Closed Lost:
          //    Days = diferencia entre start date y close date
          if (opp.opp_stage === 'Signed' || opp.opp_stage === 'Close Win' || opp.opp_stage === 'Closed Lost') {
            if (opp.nda_signature_or_start_date && opp.opp_close_date) {
              daysAgo = calculateDaysBetween(
                opp.nda_signature_or_start_date,
                opp.opp_close_date
              );
            } else if (opp.nda_signature_or_start_date) {
              // fallback si por alguna razón no hay close_date
              daysAgo = calculateDaysAgo(opp.nda_signature_or_start_date);
            } else {
              daysAgo = '-';
            }
          }
          // 👉 Para el resto de etapas: se mantiene la lógica actual
          else if (opp.nda_signature_or_start_date) {
            daysAgo = calculateDaysAgo(opp.nda_signature_or_start_date);
          } else {
            daysAgo = '-';
          }

          const tr = document.createElement('tr');
          let daysSinceBatch = (opp.opp_stage === 'Sourcing' && typeof opp._days_since_batch === 'number')
            ? opp._days_since_batch
            : '-';

          async function fetchDaysSinceBatch(opp, tr) {
            const oppId = opp.opportunity_id;

            // 👉 celda de "Days Since Sourcing"
            const daysCell = tr.querySelector('.days-since-cell');
            if (!daysCell) return;

            try {
              // 1) Intentar usar la fecha ya enriquecida o el start_date
              let referenceDate = null;
              if (opp.latest_sourcing_date) {
                referenceDate = new Date(opp.latest_sourcing_date);
              } else if (opp.nda_signature_or_start_date) {
                referenceDate = new Date(opp.nda_signature_or_start_date);
              } else {
                // 2) Fallback: pedirla al backend
                const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/latest_sourcing_date`);
                const result = await res.json();
                if (result.latest_sourcing_date) {
                  referenceDate = new Date(result.latest_sourcing_date);
                }
              }
              // 3) Si no hay fecha, no contamos
              if (!referenceDate) {
                colorizeSourcingCell(daysCell, null);
                return;
              }

              // 4) Calcular días (misma fórmula que usas en Days)
              const today = new Date();
              const diffTime = today - referenceDate;
              const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1;

              // 5) Pintar con semáforo (verde / amarillo / rojo)
              colorizeSourcingCell(daysCell, diffDays);
            } catch (err) {
              console.error(`Error fetching sourcing date para opp ${oppId}:`, err);
            }
          }

          const isClosedLost = String(opp.opp_stage || '').trim() === 'Closed Lost';
          const commentField = isClosedLost ? 'motive_close_lost' : 'comments';
          const plainComment = htmlToPlainText(opp[commentField] || '');
          const typeLabel = opp.opp_type || '';
          tr.innerHTML = `
            <td>${getStageDropdown(opp.opp_stage, opp.opportunity_id)}</td>
            <td>${opp.client_name || ''}</td>
            <td>${opp.opp_position_name || ''}</td>
            <td data-type-value="${escapeAttribute(typeLabel)}">
              ${getTypeBadge(typeLabel)}
              <span class="sr-only type-label">${escapeHtml(typeLabel)}</span>
            </td>
            <td>${opp.opp_model || ''}</td>
            <td class="sales-lead-cell">${getSalesLeadCell(opp)}</td>
            <td class="hr-lead-cell">
              ${getHRLeadCell(opp)}
            </td>
            <td>
              <input
                type="text"
                class="comment-input"
                data-id="${opp.opportunity_id}"
                data-field="${commentField}"
                id="opp-comment-${opp.opportunity_id}"
                data-original-value="${escapeAttribute(plainComment)}"
                value="${escapeAttribute(plainComment)}"
              />
            </td>
            <td>${daysAgo}</td>
            <td class="days-since-cell">${daysSinceBatch}</td>
            <td class="candidates-count-cell" data-candidates-count="—">—</td>
            <td class="interviewed-count-cell" data-interviewed-count="—">—</td>

          `;
          tr.dataset.filterDate = getOpportunityReferenceDate(opp);

          // const batchCell = tr.querySelector('.batch-count-cell');
          // hydrateBatchCountCell(opp.opportunity_id, batchCell);
          const cCell = tr.querySelector('.candidates-count-cell');
          hydrateCandidatesCountCell(opp.opportunity_id, cCell);
          const iCell = tr.querySelector('.interviewed-count-cell');
          hydrateInterviewedCountCell(opp.opportunity_id, iCell);


          tr.querySelectorAll('td').forEach((cell, index) => {
            cell.setAttribute('data-col-index', index);
          });

          tr.addEventListener('click', (e) => {
            const td = e.target.closest('td');
            if (!td) return;
            const cellIndex = parseInt(td.getAttribute('data-col-index'), 10);
            if ([0, 5, 6, 7].includes(cellIndex)) return; // 5 = Sales Lead
            openOpportunity(opp.opportunity_id);
          });

          tbody.appendChild(tr);
          tr.style.opacity = 1;
          tr.style.animation = 'none';
            if (opp.opp_stage === 'Sourcing') {
              const daysCell = tr.querySelector('.days-since-cell');
              if (typeof opp._days_since_batch === 'number') {
                colorizeSourcingCell(daysCell, opp._days_since_batch);
              } else {
                // Sin fecha luego del enriquecimiento → usar tu fallback asíncrono existente
                fetchDaysSinceBatch(opp, tr);
              }
            }
          if (opp.opp_stage === 'Sourcing') {
            fetchDaysSinceBatch(opp, tr);
          }
        });
      }
    });
console.info("🔢 Fetched opportunities:", data.length); // justo antes de crear la tabla

const table = $('#opportunityTable').DataTable({

  responsive: true,
  pageLength: 50,                         // puedes dejar 50 por defecto…
  lengthMenu: [[50, 100, 150, -1], [50, 100, 150, 'All']], // …pero permite ver “All”
  dom: 'lrtip',
  ordering: false,
  columnDefs: [
    { targets: [0], width: "8%" },
    { targets: [1, 2, 3, 4, 5, 6, 8, 9, 10, 11], width: "10%" },
    { targets: 7, width: "25%" },
    {
      targets: 0,
      render: function (data, type) {
        if (type === 'filter' || type === 'sort') {
          const div = document.createElement('div');
          div.innerHTML = data;
          const select = div.querySelector('select');
          return select ? select.options[select.selectedIndex].textContent : data;
        }
        return data;
      }
    },
    {
      targets: 5,
      render: function (data, type) {
        if (type === 'filter' || type === 'sort') {
          const div = document.createElement('div');
          div.innerHTML = data;
          const hidden = div.querySelector('.sr-only');
          return hidden ? hidden.textContent : div.textContent || data;
        }
        return data;
      }
    },
    {
      targets: 6,
      render: function (data, type) {
        if (type === 'filter' || type === 'sort') {
          const div = document.createElement('div');
          div.innerHTML = data;
          const select = div.querySelector('select');
          return select ? select.options[select.selectedIndex].textContent : data;
        }
        return data;
      }
    }
  ],
  language: {
    search: "🔍 Buscar:",
    lengthMenu: "Mostrar _MENU_ registros por página",
    zeroRecords: "No se encontraron resultados",
    info: "Mostrando _START_ a _END_ de _TOTAL_ registros",
    paginate: { first: "Primero", last: "Último", next: "Siguiente", previous: "Anterior" }
  }
});
   table.search('');
 table.columns().search('');
 table.draw();
const uniqueTypes = [...new Set(
  data
    .map(d => (d.opp_type || '').trim())
    .filter(Boolean)
)].sort((a, b) => a.localeCompare(b));

window.__typeFilterState = {
  selected: new Set(uniqueTypes.map((type) => type.toLowerCase())),
};

if (!window.__typeFilterExtRegistered && $.fn?.dataTable?.ext?.search) {
  $.fn.dataTable.ext.search.push((settings, rowData, rowIndex) => {
    if (!settings?.nTable || settings.nTable.id !== 'opportunityTable') return true;
    const selection = window.__typeFilterState?.selected;
    if (!selection || selection.size === 0) return true;
    const row = settings.aoData?.[rowIndex]?.nTr;
    const cell = row?.querySelector('[data-type-value]');
    const value = String(cell?.getAttribute('data-type-value') || '')
      .trim()
      .toLowerCase();
    return selection.has(value);
  });
  window.__typeFilterExtRegistered = true;
}

window.__daysRangeFilterState = window.__daysRangeFilterState || { min: null, max: null };

if (!window.__daysRangeFilterExtRegistered && $.fn?.dataTable?.ext?.search) {
  $.fn.dataTable.ext.search.push((settings, rowData, rowIndex) => {
    if (!settings?.nTable || settings.nTable.id !== 'opportunityTable') return true;
    const range = window.__daysRangeFilterState;
    if (!range || (range.min == null && range.max == null)) return true;
    const row = settings.aoData?.[rowIndex]?.nTr;
    const cell = row?.children?.[8];
    const raw = String(cell?.textContent || '').trim();
    const value = parseInt(raw, 10);
    if (Number.isNaN(value)) return false;
    if (range.min != null && value < range.min) return false;
    if (range.max != null && value > range.max) return false;
    return true;
  });
  window.__daysRangeFilterExtRegistered = true;
}

const accountSearchInput = document.getElementById('accountSearchInput');
if (accountSearchInput) {
  accountSearchInput.addEventListener('input', () => {
    const value = accountSearchInput.value;
    table.column(1).search(value, true, false).draw(); // columna 1 = Account
  });
}

const positionSearchInput = document.getElementById('positionSearchInput');
if (positionSearchInput) {
  positionSearchInput.addEventListener('input', () => {
    const value = positionSearchInput.value;
    table.column(2).search(value, true, false).draw(); // columna 2 = Position
  });
}

function parseDaysRangeValue(value) {
  const clean = String(value || '').trim();
  if (!clean) return { min: null, max: null };
  if (clean.endsWith('+')) {
    const min = parseInt(clean.slice(0, -1), 10);
    return { min: Number.isNaN(min) ? null : min, max: null };
  }
  const parts = clean.split('-').map((part) => parseInt(part, 10));
  const min = Number.isNaN(parts[0]) ? null : parts[0];
  const max = Number.isNaN(parts[1]) ? null : parts[1];
  return { min, max };
}

const daysRangeFilter = document.getElementById('daysRangeFilter');
if (daysRangeFilter) {
  daysRangeFilter.addEventListener('change', () => {
    window.__daysRangeFilterState = parseDaysRangeValue(daysRangeFilter.value);
    table.draw();
  });
}

window.__dateRangeFilterState = window.__dateRangeFilterState || { from: null, to: null };

if (!window.__dateFromFilterExtRegistered && $.fn?.dataTable?.ext?.search) {
  $.fn.dataTable.ext.search.push((settings, rowData, rowIndex) => {
    if (!settings?.nTable || settings.nTable.id !== 'opportunityTable') return true;
    const from = window.__dateRangeFilterState?.from || null;
    const explicitTo = window.__dateRangeFilterState?.to || null;
    if (!from && !explicitTo) return true;
    const to = explicitTo || normalizeDateOnly(new Date());

    const row = settings.aoData?.[rowIndex]?.nTr;
    const rowDate = normalizeDateOnly(row?.dataset?.filterDate || '');
    if (!rowDate) return false;

    if (from && rowDate < from) return false;
    if (rowDate > to) return false;
    return true;
  });
  window.__dateFromFilterExtRegistered = true;
}

const dateFromFilter = document.getElementById('dateFromFilter');
const dateToFilter = document.getElementById('dateToFilter');

function updateDateRangeFilterState() {
  const from = normalizeDateOnly(dateFromFilter?.value || '');
  const rawTo = normalizeDateOnly(dateToFilter?.value || '');
  const today = normalizeDateOnly(new Date());
  const to = rawTo || today;

  window.__dateRangeFilterState = { from, to: rawTo };

  if (dateFromFilter) {
    dateFromFilter.max = toIsoDate(to);
  }
  if (dateToFilter) {
    dateToFilter.max = toIsoDate(today);
    dateToFilter.min = from ? toIsoDate(from) : '';
  }

  if (table?.draw) table.draw();
}

if (dateFromFilter || dateToFilter) {
  const todayIso = toIsoDate(new Date());
  if (dateFromFilter) {
    dateFromFilter.max = todayIso;
    dateFromFilter.addEventListener('change', updateDateRangeFilterState);
  }
  if (dateToFilter) {
    dateToFilter.max = todayIso;
    dateToFilter.addEventListener('change', updateDateRangeFilterState);
  }
  updateDateRangeFilterState();
}

const downloadCsvBtn = document.getElementById('downloadCsvBtn');
if (downloadCsvBtn) {
  downloadCsvBtn.addEventListener('click', async () => {
    try {
      downloadCsvBtn.disabled = true;
      downloadCsvBtn.textContent = 'Preparing CSV...';

      const filteredNodes = table.rows({ search: 'applied', order: 'applied' }).nodes().toArray();
      if (!filteredNodes.length) {
        alert('No rows available to export with the current filters.');
        return;
      }

      const opportunitiesById = new Map(
        (Array.isArray(data) ? data : []).map((opp) => [String(opp.opportunity_id), opp])
      );

      const batchSourcingByOpp = await fetchOpportunityBatchSourcingDates();

      const headers = [
        'opportunity_id',
        'stage_visible',
        'account_visible',
        'position_visible',
        'type_visible',
        'model_visible',
        'sales_lead_visible',
        'hr_lead_visible',
        'comment_visible',
        'days_visible',
        'days_since_batch_visible',
        'candidates_count_visible',
        'interviewed_count_visible',
        'motive_close_lost',
        'matching_sourcing_date',
        'batch_presentation_date',
        'days_from_sourcing_to_batch',
        'batch_number',
        'raw_expected_fee',
        'raw_expected_revenue',
        'raw_latest_sourcing_date',
        'raw_nda_signature_or_start_date',
        'raw_opp_close_date',
      ];

      const lines = [headers.map(csvEscape).join(',')];

      filteredNodes.forEach((row) => {
        const stageSelect = row.querySelector('.stage-dropdown');
        const opportunityId = String(stageSelect?.dataset?.id || '');
        const opp = opportunitiesById.get(opportunityId) || {};
        const batchSourcingRows = batchSourcingByOpp.get(opportunityId) || [];

        const batchRows = batchSourcingRows.length ? batchSourcingRows : [{}];

        batchRows.forEach((batchRow) => {
          const values = {
            opportunity_id: opportunityId,
            stage_visible: stageSelect?.selectedOptions?.[0]?.textContent?.trim() || '',
            account_visible: row.children?.[1]?.textContent?.trim() || '',
            position_visible: row.children?.[2]?.textContent?.trim() || '',
            type_visible: row.querySelector('[data-type-value]')?.getAttribute('data-type-value') || '',
            model_visible: row.children?.[4]?.textContent?.trim() || '',
            sales_lead_visible: row.querySelector('.sales-lead-cell .sr-only')?.textContent?.trim() || row.children?.[5]?.textContent?.trim() || '',
            hr_lead_visible: row.querySelector('.hr-lead-dropdown')?.selectedOptions?.[0]?.textContent?.trim() || row.children?.[6]?.textContent?.trim() || '',
            comment_visible: row.querySelector('.comment-input')?.value?.trim() || '',
            days_visible: row.children?.[8]?.textContent?.trim() || '',
            days_since_batch_visible: row.children?.[9]?.textContent?.trim() || '',
            candidates_count_visible: row.children?.[10]?.textContent?.trim() || '',
            interviewed_count_visible: row.children?.[11]?.textContent?.trim() || '',
            motive_close_lost: opp?.motive_close_lost || opp?.details_close_lost || '',
            matching_sourcing_date: batchRow?.matching_sourcing_date ?? '',
            batch_presentation_date: batchRow?.batch_presentation_date ?? '',
            days_from_sourcing_to_batch: batchRow?.days_from_sourcing_to_batch ?? '',
            batch_number: batchRow?.batch_number ?? '',
            raw_expected_fee: opp?.expected_fee ?? '',
            raw_expected_revenue: opp?.expected_revenue ?? '',
            raw_latest_sourcing_date: toIsoDate(opp?.latest_sourcing_date),
            raw_nda_signature_or_start_date: toIsoDate(opp?.nda_signature_or_start_date),
            raw_opp_close_date: toIsoDate(opp?.opp_close_date),
          };

          const line = headers.map((header) => csvEscape(values[header])).join(',');
          lines.push(line);
        });
      });

      const today = toIsoDate(new Date()) || 'today';
      downloadTextFile(`opportunities_${today}.csv`, `${lines.join('\n')}\n`, 'text/csv;charset=utf-8;');
    } catch (err) {
      console.error('CSV export failed:', err);
      alert('Could not export CSV. Please try again.');
    } finally {
      downloadCsvBtn.disabled = false;
      downloadCsvBtn.textContent = 'Download CSV';
    }
  });
}
// 🔒 Asegura que allowedHRUsers esté cargado (el fetch /users arriba puede no haber terminado)
if (!window.allowedHRUsers || !window.allowedHRUsers.length) {
  try {
    await ensureRoleDirectoriesLoaded();
  } catch (e) {
    console.error('Error reloading HR Leads:', e);
  }
}

// Mapa email->nombre priorizando tabla users
const emailToNameMap = { ...(window.userDirectoryByEmail || {}) };
(window.allowedHRUsers || []).forEach(u => {
  const email = String(u.email_vintti || '').toLowerCase();
  if (email && !emailToNameMap[email]) emailToNameMap[email] = u.user_name;
});

// STAGES (igual que antes)
const uniqueStages = [...new Set([
  ...data.map(d => d.opp_stage).filter(Boolean),
  'Signed'
])].sort((a, b) => {
  const idxA = STAGE_ORDER_PRIORITY.indexOf(a);
  const idxB = STAGE_ORDER_PRIORITY.indexOf(b);
  if (idxA === -1 && idxB === -1) return a.localeCompare(b);
  if (idxA === -1) return 1;
  if (idxB === -1) return -1;
  return idxA - idxB;
});

// SALES LEAD: agrega 'Unassigned' si hay filas sin nombre
let uniqueSalesLeads = [...new Set(data.map(d => d.sales_lead_name).filter(Boolean))];
if (data.some(d => !d.sales_lead_name)) {
  uniqueSalesLeads.push('Unassigned'); // coincide con regex ^$ que pondremos abajo
}

// HR LEAD: mostrar nombre completo y ocultar ciertos correos
const hrLeadNameToEmail = {};
let uniqueHRLeads = [...new Set(
  data.map(d => {
    const hrEmailRaw = String(d.opp_hr_lead || '').trim();
    const hrEmail = hrEmailRaw.toLowerCase();
    if (!hrEmail) return 'Assign HR Lead';
    if (HIDDEN_HR_FILTER_EMAILS.has(hrEmail)) return null;
    const label = emailToNameMap[hrEmail] || displayNameForHR(hrEmailRaw);
    if (label && label !== 'Assign HR Lead') {
      hrLeadNameToEmail[label.toLowerCase()] = hrEmail;
      return label;
    }
    return 'Assign HR Lead';
  }).filter(Boolean)
)];
if (!uniqueHRLeads.includes('Assign HR Lead')) uniqueHRLeads.unshift('Assign HR Lead');
window.hrLeadNameToEmail = hrLeadNameToEmail;
const filterRegistry = [];
// Llama a los filtros con estas opciones
buildMultiFilter('filterStage',     uniqueStages,     0, 'Stage',      'Stage',    table);
buildMultiFilter('filterSalesLead', uniqueSalesLeads, 5, 'Sales Lead', 'SalesLead',table);
buildMultiFilter('filterHRLead',    uniqueHRLeads,    6, 'HR Lead',    'HRLead',   table);
buildMultiFilter('filterType',      uniqueTypes,      3, 'Type',       'Type',     table);

const dtLength = document.querySelector('#opportunityTable_length');
const dtTarget = document.getElementById('dataTablesLengthTarget');
if (dtLength && dtTarget) dtTarget.appendChild(dtLength);

   const selectedFilters = { Stage: [], SalesLead: [], HRLead: [] };

 function renderActiveFilters() {
   const bar = document.getElementById('activeFilters');
   if (!bar) return;
   const groups = Object.entries(selectedFilters).filter(([_, arr]) => arr.length);
   if (!groups.length) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
   bar.style.display = 'flex';
   bar.innerHTML = groups.map(([group, arr]) =>
     arr.map(val => `
       <span class="filter-chip" data-group="${group}" data-value="${val}">
         <strong>${group}:</strong> ${val} <span class="x" title="Remove">✕</span>
       </span>
     `).join('')
   ).join('');
 }

 // click en "x" del chip para quitarlo
 document.addEventListener('click', (e) => {
   const x = e.target.closest('.filter-chip .x');
   if (!x) return;
   const chip = x.parentElement;
   const group = chip.getAttribute('data-group');
   const value = chip.getAttribute('data-value');
   const idMap = { Stage: 'filterStage', SalesLead: 'filterSalesLead', HRLead: 'filterHRLead' };
   const cont = document.getElementById(idMap[group]);
  if (cont) {
    const cb = Array.from(cont.querySelectorAll('input[type="checkbox"]')).find(c => c.value === value);
    if (cb) { cb.checked = false; cb.dispatchEvent(new Event('change', { bubbles: true })); }
   }
 });



// Mapa de clases CSS para cada Stage → puntito
const STAGE_DOT_CLASS = {
  'Negotiating': 'stage-dot--negotiating',
  'Interviewing': 'stage-dot--interviewing',
  'Sourcing': 'stage-dot--sourcing',
  'Stop': 'stage-dot--stop',
  'NDA Sent': 'stage-dot--nda',
  'Deep Dive': 'stage-dot--deep-dive',
  'Signed': 'stage-dot--signed',
  'Close Win': 'stage-dot--close-win',
  'Closed Lost': 'stage-dot--closed-lost'
};

function buildMultiFilter(containerId, options, columnIndex, displayName, filterKey, dataTable) {
  const DOT_CLASS = {
    'Negotiating': 'stage-dot--negotiating',
    'Interviewing': 'stage-dot--interviewing',
    'Sourcing': 'stage-dot--sourcing',
    'Stop': 'stage-dot--stop',
    'NDA Sent': 'stage-dot--nda',
    'Deep Dive': 'stage-dot--deep-dive',
    'Signed': 'stage-dot--signed',
    'Close Win': 'stage-dot--close-win',
    'Closed Lost': 'stage-dot--closed-lost'
  };

  const IS_STAGE = (containerId === 'filterStage');
  const IS_SALES = (containerId === 'filterSalesLead');
  const IS_HR    = (containerId === 'filterHRLead');
  const IS_TYPE  = (containerId === 'filterType');

  const container = document.getElementById(containerId);
  if (!container) return;

  const column = dataTable.column(columnIndex);
  if (typeof filterRegistry !== 'undefined' && Array.isArray(filterRegistry)) {
    filterRegistry.push({ containerId, columnIndex });
  }

  // Header del filtro
  const headerWrap =
    document.querySelector(`#${containerId}Container .filter-header`) ||
    document.querySelector(`.filter-header[data-target="${containerId}"]`);
  if (headerWrap) setupFilterToggle(headerWrap, containerId);

  // Barras de puntitos en el header:
  // - Stage usa .stage-dot-bar (ya la tienes en el HTML; si no, la creo)
  // - HR y Sales usan .lead-dot-bar (creadas aquí)
  let stageDotBar = null;
  if (IS_STAGE && headerWrap) {
    stageDotBar = headerWrap.querySelector('.stage-dot-bar');
    if (!stageDotBar) {
      stageDotBar = document.createElement('span');
      stageDotBar.className = 'stage-dot-bar';
      headerWrap.insertBefore(stageDotBar, headerWrap.querySelector('button') || null);
    }
  }

  let leadDotBar = null;
  if ((IS_SALES || IS_HR) && headerWrap) {
    leadDotBar = headerWrap.querySelector('.lead-dot-bar');
    if (!leadDotBar) {
      leadDotBar = document.createElement('span');
      leadDotBar.className = 'lead-dot-bar';
      leadDotBar.id = containerId + 'DotBar';
      headerWrap.insertBefore(leadDotBar, headerWrap.querySelector('button') || null);
    }
  }

  // Botón select/deselect all
  const selectToggle = document.createElement('button');
  selectToggle.className = 'select-toggle';
  container.appendChild(selectToggle);

  // Lista de checkboxes
  const checkboxWrapper = document.createElement('div');
  checkboxWrapper.classList.add('checkbox-list');
  container.appendChild(checkboxWrapper);

  // Initial selection: Stage deselects wins/losses, others select all
  const DEFAULT_EXCLUDED = IS_STAGE ? new Set(['Close Win', 'Closed Lost']) : null;
  const initialSelection = new Set(
    options.filter((val) => !(DEFAULT_EXCLUDED && DEFAULT_EXCLUDED.has(val)))
  );
  if (initialSelection.size === 0) {
    options.forEach((val) => initialSelection.add(val));
  }
  const anyUnchecked = initialSelection.size !== options.length;
  selectToggle.textContent = anyUnchecked ? 'Select All' : 'Deselect All';

  // Render checkboxes
  options.forEach(val => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = val;
    checkbox.checked = initialSelection.has(val);
    label.appendChild(checkbox);
    label.append(' ' + val);
    checkboxWrapper.appendChild(label);
  });

  if (IS_TYPE && window.__typeFilterState) {
    window.__typeFilterState.selected = new Set(
      Array.from(initialSelection).map((val) => String(val || '').trim().toLowerCase())
    );
  }

  function escapeRegex(s){ return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

  // Helpers para HR/Sales avatar-dots
  function computeInitials(name){
    return (String(name||'')
      .trim()
      .split(/\s+/)
      .map(w => w[0] || '')
      .join('')
      .slice(0,2) || '—').toUpperCase();
  }
function nameToEmail(label, isHR){
  const lower = String(label||'').toLowerCase();
  if (isHR && window.hrLeadNameToEmail) {
    const mapped = window.hrLeadNameToEmail[lower];
    if (mapped) return mapped;
  }

  const arr = isHR ? (window.allowedHRUsers||[]) : (window.allowedSalesUsers||[]);
  const match = arr.find(u => String(u.user_name||'').toLowerCase() === lower);
  if (match?.email_vintti) return match.email_vintti;

  if (isHR) {
    // ➕ primero casos específicos
    if (lower.includes('paz'))                                    return 'paz@vintti.com';
    if (lower.includes('pilar'))                                 return 'pilar@vintti.com';

    if (lower.includes('jazmin'))                                 return 'jazmin@vintti.com';
    if (lower.includes('agostina') && lower.includes('ferrari'))  return 'agustina.ferrari@vintti.com';
    if (lower === 'agustina ferrari')                             return 'agustina.ferrari@vintti.com';
    if (lower.includes('agostina'))                               return 'agostina@vintti.com';
  } else {
    if (lower.includes('bahia'))   return 'bahia@vintti.com';
    if (lower.includes('lara'))    return 'lara@vintti.com';
    if (lower.includes('agustin')) return 'agustin@vintti.com';
    if (lower.includes('mariano')) return 'mariano@vintti.com';
    if (lower.includes('mia'))     return 'mia@vintti.com';
  }

  return '';
}


  // Pintar puntitos de Stage (colores)
  function paintStageDots(selectedList) {
    if (!IS_STAGE || !stageDotBar) return;
    stageDotBar.innerHTML = '';
    if (!selectedList.length) return;

    selectedList.forEach(stage => {
      const span = document.createElement('span');
      span.className = 'stage-dot ' + (DOT_CLASS[stage] || 'stage-dot--default');
      span.setAttribute('data-tip', stage);
      span.setAttribute('aria-label', stage);
      span.setAttribute('tabindex', '0');
      stageDotBar.appendChild(span);
    });
  }

  // Pintar avatar-dots para HR & Sales
function paintLeadDots(selectedList) {
  if (!(IS_SALES || IS_HR) || !leadDotBar) return;
  leadDotBar.innerHTML = '';
  if (!selectedList.length) return;

  selectedList.forEach(label => {
    const span = document.createElement('span');
    span.className = 'lead-dot';

    const isPlaceholder = /^(Unassigned|Assign HR Lead|Assign Sales Lead)$/i.test(label);

    // email (para avatar) y nombre bonito (para tooltip)
    const email   = isPlaceholder ? '' : nameToEmail(label, IS_HR);
    const fallbackLabel = label || (IS_HR ? 'Assign HR Lead' : 'Unassigned');
    const tipText = isPlaceholder
      ? fallbackLabel
      : (IS_HR
          ? (email ? displayNameForHR(email) : fallbackLabel)
          : displayNameForSales(label));

    // ✅ tooltip + accesibilidad + foco por teclado
    span.setAttribute('data-tip', escapeHtml(tipText));
    span.setAttribute('title',     tipText);         // fallback nativo
    span.setAttribute('aria-label',tipText);
    span.setAttribute('tabindex',  '0');

    if (!isPlaceholder) {
      const avatar = email ? resolveAvatar(email) : null;
      if (avatar) {
        span.innerHTML = `<img src="${avatar}" alt="${escapeHtml(tipText)}">`;
      } else {
        // iniciales si no hay avatar
        span.textContent = (tipText || '')
          .trim().split(/\s+/).map(w => w[0]||'').join('').slice(0,2).toUpperCase() || '—';
      }
    } else {
      span.textContent = '—';
    }

    leadDotBar.appendChild(span);
  });
}

  // Aplicar filtro + refrescar barras
  function applyFilter() {
    const cbs = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const selected = Array.from(cbs).filter(c => c.checked).map(c => c.value);
    const pieces = selected.map(v => (v === 'Unassigned') ? '^$' : escapeRegex(v));
    const pattern = selected.length ? pieces.join('|') : '';

    if (IS_TYPE) {
      if (window.__typeFilterState) {
        window.__typeFilterState.selected = new Set(
          selected.map((val) => String(val || '').trim().toLowerCase()),
        );
      }
      dataTable.draw();
    } else {
      column.search(pattern, true, false).draw();
    }

    if (IS_STAGE) paintStageDots(selected);
    if (IS_HR || IS_SALES) paintLeadDots(selected);

    const allChecked = Array.from(cbs).every(c => c.checked);
    selectToggle.textContent = allChecked ? 'Deselect All' : 'Select All';
  }

  checkboxWrapper.addEventListener('change', applyFilter);
  selectToggle.addEventListener('click', () => {
    const all = checkboxWrapper.querySelectorAll('input[type="checkbox"]');
    const isDeselecting = selectToggle.textContent === 'Deselect All';
    all.forEach(cb => cb.checked = !isDeselecting);
    applyFilter();
  });

  // Aplica inmediatamente (Stage mantiene CW/CL desmarcados por defecto)
  applyFilter();
}

      document.getElementById('opportunityTable').addEventListener('click', function(e) {
        const target = e.target.closest('.column-filter');
        if (target) {
          e.preventDefault();
          e.stopPropagation();
          const columnIndex = parseInt(target.getAttribute('data-column'), 10);
          createColumnFilter(columnIndex, table);
        }
      });
const uniqueAccounts = [...new Set(data.map(d => d.client_name).filter(Boolean))];
    })
    .catch(err => {
      console.error('Error fetching opportunities:', err);
      const spinner = document.getElementById('spinner-overlay');
      if (spinner) spinner.classList.add('hidden');
    });
} else {
  // Opcional: silencio/diagnóstico en index
  console.debug('No hay tabla de oportunidades en esta página; omito inicialización.');
}

const CLOSE_WIN_CELEBRATION_DURATION = 3200;
let closeWinCelebrationTimer = null;
let closeWinCelebrationFrame = null;

function playCloseWinCelebration(onDone) {
  if (closeWinCelebrationTimer) {
    clearTimeout(closeWinCelebrationTimer);
    closeWinCelebrationTimer = null;
  }
  if (closeWinCelebrationFrame) {
    cancelAnimationFrame(closeWinCelebrationFrame);
    closeWinCelebrationFrame = null;
  }

  const existing = document.getElementById('closeWinCelebrationOverlay');
  if (existing) existing.remove();

  const overlay = document.createElement('div');
  overlay.id = 'closeWinCelebrationOverlay';
  overlay.className = 'close-win-celebration';
  overlay.setAttribute('aria-hidden', 'true');

  const canvas = document.createElement('canvas');
  canvas.className = 'close-win-celebration__canvas';
  overlay.appendChild(canvas);

  (document.body || document.documentElement).appendChild(overlay);

  const ctx = canvas.getContext('2d');
  const colors = ['#14b8a6', '#22c55e', '#f59e0b', '#ef4444', '#3b82f6', '#ec4899'];
  const pieces = [];
  const pieceCount = 220;

  const resize = () => {
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const w = window.innerWidth;
    const h = window.innerHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  resize();
  window.addEventListener('resize', resize);

  const rand = (min, max) => Math.random() * (max - min) + min;
  for (let i = 0; i < pieceCount; i += 1) {
    pieces.push({
      x: rand(0, window.innerWidth),
      y: rand(-window.innerHeight, 0),
      vx: rand(-2.6, 2.6),
      vy: rand(1.5, 4.7),
      size: rand(5, 11),
      rot: rand(0, Math.PI * 2),
      vr: rand(-0.2, 0.2),
      color: colors[Math.floor(Math.random() * colors.length)],
      tilt: rand(-0.5, 0.5),
    });
  }

  const cleanup = () => {
    window.removeEventListener('resize', resize);
    if (closeWinCelebrationFrame) {
      cancelAnimationFrame(closeWinCelebrationFrame);
      closeWinCelebrationFrame = null;
    }
    overlay.remove();
  };

  const animate = () => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    ctx.clearRect(0, 0, w, h);

    for (let i = 0; i < pieces.length; i += 1) {
      const p = pieces[i];
      p.x += p.vx;
      p.y += p.vy;
      p.rot += p.vr;
      p.vy += 0.02;
      p.vx *= 0.998;

      if (p.y > h + 20) {
        p.y = rand(-60, -10);
        p.x = rand(0, w);
        p.vy = rand(1.5, 4.3);
        p.vx = rand(-2.4, 2.4);
      }
      if (p.x < -20) p.x = w + 20;
      if (p.x > w + 20) p.x = -20;

      ctx.save();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rot);
      ctx.fillStyle = p.color;
      ctx.globalAlpha = 0.95;
      ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * (1 + p.tilt));
      ctx.restore();
    }

    closeWinCelebrationFrame = requestAnimationFrame(animate);
  };

  animate();

  closeWinCelebrationTimer = window.setTimeout(() => {
    closeWinCelebrationTimer = null;
    cleanup();
    if (typeof onDone === 'function') {
      onDone();
    }
  }, CLOSE_WIN_CELEBRATION_DURATION);
}

function updateStageDropdownStyle(select, stage) {
  if (!select) return;
  select.classList.forEach((cls) => {
    if (cls.startsWith('stage-color-')) select.classList.remove(cls);
  });
  const newClass = 'stage-color-' + String(stage || '').toLowerCase().replace(/\s/g, '-');
  if (newClass !== 'stage-color-') select.classList.add(newClass);
}
if (typeof window !== 'undefined') {
  window.updateStageDropdownStyle = updateStageDropdownStyle;
}

function requiresStageConfirm(stage) {
  return !['Sourcing', 'Interviewing', 'Stop', 'Close Win', 'Closed Lost'].includes(stage);
}

function openStageConfirmPopup({ newStage, onConfirm, onCancel }) {
  const popup = document.getElementById('stageConfirmPopup');
  const message = document.getElementById('stageConfirmMessage');
  const yesBtn = document.getElementById('stageConfirmYes');
  const noBtn = document.getElementById('stageConfirmNo');
  if (!popup || !message || !yesBtn || !noBtn) return;

  message.textContent = `Are you sure you want to change this stage to "${newStage}"?`;
  popup.style.display = 'flex';

  const cleanup = () => {
    popup.style.display = 'none';
    yesBtn.onclick = null;
    noBtn.onclick = null;
  };

  yesBtn.onclick = async () => {
    cleanup();
    if (typeof onConfirm === 'function') await onConfirm();
  };

  noBtn.onclick = () => {
    cleanup();
    if (typeof onCancel === 'function') onCancel();
  };
}

document.addEventListener('change', async (e) => {
    if (e.target && e.target.classList.contains('stage-dropdown')) {
      const newStage = e.target.value;
      const opportunityId = e.target.getAttribute('data-id');
      const previousStage = e.target.getAttribute('data-current-stage') || '';

      if (e.target.disabled) {
        alert("This stage is final and cannot be changed.");
        return;
      }

    console.log('🟡 Stage dropdown changed! Opportunity ID:', opportunityId, 'New Stage:', newStage);

    if (newStage === 'Sourcing') {
      openSourcingPopup(opportunityId, e.target);
      return;
    }    
    if (newStage === 'Interviewing') {
      openInterviewingPopup(opportunityId, e.target);
      return;
    }
    if (newStage === 'Signed') {
      playCloseWinCelebration(() => openCloseWinPopup(opportunityId, e.target, { mode: 'signed' }));
      return;
    }
    if (newStage === 'Close Win') {
      playCloseWinCelebration(() => openCloseWinPopup(opportunityId, e.target, { mode: 'close-win' }));
      return;
    }
    if (newStage === 'Closed Lost') {
      openCloseLostPopup(opportunityId, e.target);
      return;
    }
    if (newStage === 'Stop') {
      try {
        await patchOppFields(opportunityId, { nda_signature_or_start_date: null });
      } catch (err) {
        alert(err.message || 'Failed to clear start date.');
        e.target.value = previousStage;
        updateStageDropdownStyle(e.target, previousStage);
        return;
      }
    }
    if (requiresStageConfirm(newStage)) {
      e.target.value = previousStage;
      updateStageDropdownStyle(e.target, previousStage);
      openStageConfirmPopup({
        newStage,
        onConfirm: async () => {
          e.target.value = newStage;
          updateStageDropdownStyle(e.target, newStage);
          const ok = await patchOpportunityStage(opportunityId, newStage, e.target);
          if (!ok) {
            e.target.value = previousStage;
            updateStageDropdownStyle(e.target, previousStage);
          }
        },
        onCancel: () => {
          e.target.value = previousStage;
          updateStageDropdownStyle(e.target, previousStage);
        }
      });
      return;
    }

    const ok = await patchOpportunityStage(opportunityId, newStage, e.target);
    if (!ok) {
      e.target.value = previousStage;
      updateStageDropdownStyle(e.target, previousStage);
    }

  }
});
document.addEventListener('change', async e => {
  if (!e.target.classList.contains('hr-lead-dropdown')) return;

  const oppId   = e.target.dataset.id;
  const rawLead = (e.target.value || '').toLowerCase().trim();
  const newLead = rawLead || null;

  try {
    // 1) Persistir en backend
    const res = await fetch(`${API_BASE}/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opp_hr_lead: newLead })
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      console.error('❌ Error updating opp_hr_lead:', res.status, txt);
      alert('Error updating HR Lead. Please try again.');
      return;
    }

    // 2) Refrescar display (inicial + avatar) en la misma celda
    const wrap = e.target.closest('.hr-lead-cell-wrap');
    if (wrap) {
      const current = wrap.querySelector('.hr-lead');
      if (current) current.outerHTML = hrDisplayHTML(newLead || '');
    }

    // 3) Enviar email de asignación de búsqueda (HR Lead + Angie)
    if (newLead) {
      sendHRLeadAssignmentEmail(oppId, newLead);
      logOpportunityTrack(trackIdFromEl(e.target, `opp-hr-lead-${oppId}`));
    }

  } catch (err) {
    console.error('❌ Network error updating HR Lead:', err);
    alert('Network error. Please try again.');
  }
});
document.addEventListener('change', async e => {
  const el = e.target;
  if (!el.classList.contains('sales-lead-dropdown')) return;

  const oppId   = el.dataset.id;
  const newLead = (el.value || '').toLowerCase();

  try {
    // 1) Persistir en backend
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opp_sales_lead: newLead })
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`PATCH sales_lead failed ${res.status}: ${t}`);
    }

    // 2) Refrescar display en la misma celda (iniciales + avatar)
    const wrap = el.closest('.sales-lead-cell-wrap');
    if (wrap) {
      const current = wrap.querySelector('.sales-lead');
      if (current) current.outerHTML = salesDisplayHTML(newLead);
    }
    logOpportunityTrack(trackIdFromEl(el, `opp-sales-lead-${oppId}`));
  } catch (err) {
    console.error('❌ Error updating sales lead:', err);
    alert('Error updating Sales Lead. Please try again.');
  }
});

// Evita que el click en el select burbujee y dispare la redirección por fila
document.addEventListener('click', e => {
  if (e.target.closest('.sales-lead-dropdown')) {
    e.stopPropagation();
  }
}, true);

document.addEventListener('blur', async (e) => {
  if (!e.target.classList.contains('comment-input')) return;
  const input = e.target;
  const oppId = input.dataset.id;
  const field = input.dataset.field === 'motive_close_lost' ? 'motive_close_lost' : 'comments';
  const newComment = input.value;
  const original = input.dataset.originalValue ?? '';
  if (newComment === original) return;

  try {
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: newComment })
    });
    if (!res.ok) {
      console.error('Failed to update plain comment', res.status);
      return;
    }
    input.dataset.originalValue = newComment;
    logOpportunityTrack(trackIdFromEl(input, `opp-comment-${oppId}`));
  } catch (err) {
    console.error('Error updating comment', err);
  }
}, true);

  const helloBtn = document.getElementById('helloGPT');
  const chatResponse = document.getElementById('chatResponse');

  if (helloBtn && chatResponse) {
helloBtn.addEventListener('click', async () => {
  console.log("🚀 Enviando solicitud a /ai/hello...");

  try {
    const res = await fetch('https://vinttihub.vintti.com/ai/hello', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({})
    });

    if (!res.ok) {
      const errorText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errorText}`);
    }

    const data = await res.json();
    console.log("📥 Respuesta recibida:", data);
    chatResponse.innerText = data.message || '❌ No se recibió mensaje.';
  } catch (err) {
    console.error("❌ Error al contactar ChatGPT:", err);
    chatResponse.innerText = 'Ocurrió un error al hablar con ChatGPT.';
  }
});
  }
const summaryLink = document.getElementById('summaryLink');
const currentUserEmail = localStorage.getItem('user_email');
const allowedEmails = ['agustin@vintti.com', 'bahia@vintti.com', 'angie@vintti.com', 
  'lara@vintti.com','agostina@vintti.com','mariano@vintti.com','mia@vintti.com','jazmin@vintti.com'];

if (summaryLink && allowedEmails.includes(currentUserEmail)) {
  summaryLink.style.display = 'flex';  // o '' para usar el de CSS
}
// --- Candidate Search button visibility ---
const candidateSearchLink = document.getElementById('candidateSearchLink');

if (candidateSearchLink) {
  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  const CANDIDATE_SEARCH_ALLOWED = new Set([
    'agustin@vintti.com',
    'lara@vintti.com',
    'constanza@vintti.com',
    'pilar@vintti.com',
    'angie@vintti.com',
    'agostina@vintti.com',
    'julieta@vintti.com',
    'paz@vintti.com' 
  ]);

  candidateSearchLink.style.display = CANDIDATE_SEARCH_ALLOWED.has(email) ? 'flex' : 'none';
}

async function initSidebarProfile(){
  // helpers
  function initialsFromName(name=""){
    const parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '—';
    const a = (parts[0]?.[0]||'').toUpperCase();
    const b = (parts[1]?.[0]||'').toUpperCase();
    return (a + b) || a || '—';
  }
  function initialsFromEmail(email=""){
    const local = String(email).split('@')[0] || '';
    if (!local) return '—';
    const bits = local.split(/[._-]+/).filter(Boolean);
    return (bits.length >= 2)
      ? (bits[0][0] + bits[1][0]).toUpperCase()
      : local.slice(0,2).toUpperCase();
  }

  let tile = document.getElementById('sidebarProfile');
  const sidebar = document.querySelector('.sidebar');
  if (!tile && sidebar){
    sidebar.insertAdjacentHTML('beforeend', `
      <a href="profile.html" class="profile-tile" id="sidebarProfile">
        <span class="profile-avatar">
          <img id="profileAvatarImg" alt="" />
          <span id="profileAvatarInitials" class="profile-initials" aria-hidden="true">—</span>
        </span>
        <span class="profile-meta">
          <span id="profileName" class="profile-name">Profile</span>
          <span id="profileEmail" class="profile-email"></span>
        </span>
      </a>
    `);
    tile = document.getElementById('sidebarProfile');
  }
  if (!tile) return;

  const $init   = document.getElementById('profileAvatarInitials');
  const $name   = document.getElementById('profileName');
  const $emailE = document.getElementById('profileEmail');
  const $img    = document.getElementById('profileAvatarImg');

  if ($emailE) { $emailE.textContent = ''; $emailE.style.display = 'none'; }

  const showInitials = (value) => {
    if (!$init || !$img) return;
    $init.style.display = 'grid';
    $init.textContent = value || '—';
    $img.removeAttribute('src');
    $img.style.display = 'none';
  };

  const showAvatar = (src) => {
    if (!$img || !$init) return;
    if (src) {
      $img.src = src;
      $img.style.display = 'block';
      $init.style.display = 'none';
    } else {
      showInitials($init?.textContent || '—');
    }
  };

  // resolve uid
  let uid = null;
  try {
    uid = (typeof window.getCurrentUserId === 'function')
      ? (await window.getCurrentUserId())
      : (Number(localStorage.getItem('user_id')) || null);
  } catch {
    uid = Number(localStorage.getItem('user_id')) || null;
  }

  // link
  const base = 'profile.html';
  tile.href = uid != null ? `${base}?user_id=${encodeURIComponent(uid)}` : base;

  // show email initials immediately
  const email = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '').toLowerCase();
  if ($init) {
    $init.textContent = initialsFromEmail(email);
    $init.style.display = 'grid';
  }

  const cachedAvatar = localStorage.getItem('user_avatar');
  if (cachedAvatar) {
    showAvatar(cachedAvatar);
  } else {
    showInitials($init?.textContent || initialsFromEmail(email));
  }

  // try /users/<uid>, fallback to /profile/me
  let user = null;
  try {
    if (uid != null) {
      const r = await fetch(`${API_BASE}/users/${encodeURIComponent(uid)}?user_id=${encodeURIComponent(uid)}`, { credentials:'include' });
      if (r.ok) user = await r.json();
      else console.debug('[sidebar] /users/<uid> failed:', r.status);
    }
    if (!user) {
      const r2 = await fetch(`${API_BASE}/profile/me${uid!=null?`?user_id=${encodeURIComponent(uid)}`:''}`, { credentials:'include' });
      if (r2.ok) user = await r2.json();
      else console.debug('[sidebar] /profile/me failed:', r2.status);
    }
  } catch (e) {
    console.debug('[sidebar] fetch error:', e);
  }

  const userName = user?.user_name || '';
  if (userName) {
    if ($name) $name.textContent = userName;
    if ($init) $init.textContent = initialsFromName(userName);
  } else if ($name) {
    $name.textContent = 'Profile'; // graceful fallback label
  }

  const avatarSrc = typeof window.resolveUserAvatar === 'function'
    ? window.resolveUserAvatar({
        avatar_url: user?.avatar_url,
        email_vintti: user?.email_vintti || email,
        email: user?.email_vintti || email,
        user_id: user?.user_id ?? uid
      })
    : (user?.avatar_url || '');

  if (avatarSrc) {
    localStorage.setItem('user_avatar', avatarSrc);
    showAvatar(avatarSrc);
  } else {
    showInitials(initialsFromName(userName) || initialsFromEmail(email));
  }

  // ensure visible
  const cs = window.getComputedStyle(tile);
  if (cs.display === 'none') tile.style.display = 'flex';
}
initSidebarProfile();
// === Password reset popup (index) ===
const resetModal       = document.getElementById('passwordResetModal');
const openResetBtn     = document.getElementById('open-reset-modal');
const closeResetBtn    = document.getElementById('close-reset-modal');
const resetForm        = document.getElementById('passwordResetForm');
const resetEmailInput  = document.getElementById('resetEmail');
const resetFeedback    = document.getElementById('resetFeedback');

// Abrir popup
openResetBtn?.addEventListener('click', () => {
  // precargar email desde el campo de login si ya está
  const loginEmail = (document.getElementById('email')?.value || '').trim();
  if (loginEmail) resetEmailInput.value = loginEmail;

  resetFeedback.textContent = '';
  resetFeedback.className = 'reset-feedback';
  resetModal.style.display = 'flex';
});

// Cerrar popup
closeResetBtn?.addEventListener('click', () => {
  resetModal.style.display = 'none';
});

// Cerrar si hacen click en el fondo
resetModal?.addEventListener('click', (e) => {
  if (e.target === resetModal) {
    resetModal.style.display = 'none';
  }
});

// Enviar petición de reset
resetForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = resetEmailInput.value.trim().toLowerCase();

  resetFeedback.textContent = '';
  resetFeedback.className = 'reset-feedback';

  if (!email) {
    resetFeedback.textContent = 'Please enter your email.';
    resetFeedback.classList.add('error');
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/password_reset_request`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email })
    });

    // Por seguridad, aunque el email no exista el backend debe devolver 200
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      console.error('❌ password_reset_request failed:', res.status, txt);
      resetFeedback.textContent = 'There was an error sending the reset email. Please try again.';
      resetFeedback.classList.add('error');
      return;
    }

    resetFeedback.textContent = 'If this email exists, a reset link has been sent.';
    resetFeedback.classList.add('ok');
  } catch (err) {
    console.error('❌ Network error in password_reset_request:', err);
    resetFeedback.textContent = 'Network error. Please try again.';
    resetFeedback.classList.add('error');
  }
});





});

function openPopup() {
  document.getElementById('popup').style.display = 'flex';
}

function closePopup() {
  document.getElementById('popup').style.display = 'none';
}

function openOpportunity(id) {
  const url = `opportunity-detail.html?id=${id}`;
  window.open(url, '_blank'); // 👉 abre en nueva pestaña
}

function navigateTo(section) {
  alert(`Navigation to "${section}" would happen here.`);
}

function createColumnFilter(columnIndex, table) {
  document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());

  const columnData = table
  .column(columnIndex)
  .data()
  .toArray()
  .map(item => extractTextFromHTML(item).trim())
  .filter((v, i, a) => v && a.indexOf(v) === i)
  .sort();


  const container = document.createElement('div');
  container.classList.add('filter-dropdown');

  const searchInput = document.createElement('input');
  searchInput.type = 'text';
  searchInput.placeholder = 'Search...';
  container.appendChild(searchInput);

  const checkboxContainer = document.createElement('div');
  checkboxContainer.classList.add('checkbox-list');

  columnData.forEach(value => {
    const label = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.value = value;
    label.appendChild(checkbox);
    label.append(' ' + value);
    checkboxContainer.appendChild(label);
  });

  container.appendChild(checkboxContainer);

  const headerCell = document.querySelectorAll('#opportunityTable thead th')[columnIndex];
  headerCell.appendChild(container);

  searchInput.addEventListener('input', () => {
    const searchTerm = searchInput.value.toLowerCase();
    checkboxContainer.querySelectorAll('label').forEach(label => {
      const text = label.textContent.toLowerCase();
      label.style.display = text.includes(searchTerm) ? 'block' : 'none';
    });
  });

  checkboxContainer.addEventListener('change', () => {
    const selected = Array.from(checkboxContainer.querySelectorAll('input:checked')).map(c => c.value);
    table.column(columnIndex).search(selected.length ? selected.join('|') : '', true, false).draw();
  });
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.filter-dropdown') && !e.target.classList.contains('column-filter')) {
    document.querySelectorAll('.filter-dropdown').forEach(e => e.remove());
  }
});

document.getElementById('login-form')?.addEventListener('submit', async function (e) {
  e.preventDefault();                          // ✅ evita que la página se recargue (causante del "Load failed")
  const form = e.currentTarget;
  const email = form.email.value.trim();
  const password = form.password.value;

  // evitemos rechazos del audio en Safari si falla la carga
  document.getElementById('click-sound')?.play().catch(() => {});

  const submitBtn = form.querySelector('button[type="submit"]');
  submitBtn?.setAttribute('disabled', 'disabled');

  try {
    const res = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password })
    });

    // leer el cuerpo con fallback por si no es JSON (para logs útiles)
    const raw = await res.text();
    let data = {};
    try { data = JSON.parse(raw); } catch {}

    if (!res.ok || !data.success) {
      const msg = (data && (data.message || data.error)) || `HTTP ${res.status}: ${raw}`;
      alert(msg);
      return;
    }

    const nickname = data.nickname;
    localStorage.setItem('user_email', email.toLowerCase());
    // If backend sent user_id, store it; otherwise resolve & cache now
    if (typeof data.user_id === 'number') {
      localStorage.setItem('user_id', String(data.user_id));
    } else {
      getCurrentUserId().catch(()=>{});
    }
    // Si el backend no mandó user_id, resuélvelo fresco (sin cache)
const finalUid = typeof data.user_id === 'number'
  ? Number(data.user_id)
  : (await getCurrentUserId({ force: true })) ?? null;

if (finalUid != null) {
  localStorage.setItem('user_id', String(finalUid));
  localStorage.setItem('user_id_owner_email', email.toLowerCase());
  console.info('✅ [login] user_id (fresh):', finalUid);
} else {
  console.warn('⚠️ [login] Could not resolve user_id for', email);
}

    const avatarSrc = resolveAvatar(email);
    if (avatarSrc) localStorage.setItem('user_avatar', avatarSrc);
    document.getElementById('personalized-greeting').textContent = `Hey ${nickname}, `;
    document.getElementById('login-container').style.display = 'none';
    document.getElementById('welcome-container').style.display = 'block';
    showWelcomeAvatar(email);
    maybeShowBirthdayCelebration({
      email,
      fallbackName: nickname,
      delayMs: 1850,
      onDismiss: () => queueMonthlyMoodRecap({ delayMs: 220 }),
    })
      .then((shown) => {
        if (!shown) return queueMonthlyMoodRecap({ delayMs: 1850 });
        return shown;
      })
      .catch(() => {});
  } catch (err) {
    console.error('Error en login:', err);
    alert('Ocurrió un error inesperado. Intenta de nuevo más tarde.');
  } finally {
    submitBtn?.removeAttribute('disabled');
  }
});
// 🔧 HAZ GLOBAL el helper para que exista donde lo usas
window.getReplacementCandidateId = function () {
  const input = document.getElementById('replacementCandidate');
  if (!input || !input.value) return null;
  const idStr = String(input.value).split(' - ')[0].trim();
  const id = parseInt(idStr, 10);
  return Number.isFinite(id) ? id : null;
};

// --- Create Opportunity form (drop-in fix de scope) ---
const createOpportunityForm = document.getElementById('createOpportunityForm');
const createButton = createOpportunityForm?.querySelector('.create-btn');
const creditLoopPreviewBanner = document.getElementById('creditLoopPreviewBanner');

// helper seguro para leer el end date del replacement
const getReplacementEndDateEl = () => document.getElementById('replacementEndDate');

if (createOpportunityForm && createButton) {
  let creditLoopPreviewToken = 0;

  const renderCreditLoopPreview = (payload = null) => {
    if (!creditLoopPreviewBanner) return;
    const credits = Number(payload?.available_credits || 0);
    if (!payload?.eligible || credits <= 0) {
      creditLoopPreviewBanner.hidden = true;
      creditLoopPreviewBanner.textContent = '';
      return;
    }
    creditLoopPreviewBanner.textContent = `This account has ${credits} Credit Loop credit available for this model.`;
    creditLoopPreviewBanner.hidden = false;
  };

  const refreshCreditLoopPreview = async () => {
    const clientName = createOpportunityForm.client_name.value.trim();
    const oppModel = createOpportunityForm.opp_model.value;
    const token = ++creditLoopPreviewToken;

    if (!clientName || !oppModel) {
      renderCreditLoopPreview(null);
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/credit-loop/opportunity-preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_name: clientName, opp_model: oppModel }),
        credentials: 'include',
      });
      const payload = await res.json().catch(() => ({}));
      if (token !== creditLoopPreviewToken) return;
      if (!res.ok) {
        renderCreditLoopPreview(null);
        return;
      }
      renderCreditLoopPreview(payload);
    } catch (err) {
      if (token !== creditLoopPreviewToken) return;
      renderCreditLoopPreview(null);
    }
  };

  // Habilitar/deshabilitar botón según campos
  createOpportunityForm.addEventListener('input', () => {
    const clientName   = createOpportunityForm.client_name.value.trim();
    const oppModel     = createOpportunityForm.opp_model.value;
    const positionName = createOpportunityForm.position_name.value.trim();
    const salesLead    = createOpportunityForm.sales_lead.value;
    const oppType      = createOpportunityForm.opp_type.value;

    const needsReplacement = oppType === 'Replacement';
    const hasRepCandidate  = !!getReplacementCandidateId();
    const hasRepEndDate    = !!getReplacementEndDateEl()?.value;

    const allFilled = clientName && oppModel && positionName && salesLead && oppType &&
                      (!needsReplacement || (hasRepCandidate && hasRepEndDate));

    createButton.disabled = !allFilled;
    refreshCreditLoopPreview();
  });

  createOpportunityForm.client_name?.addEventListener('change', refreshCreditLoopPreview);
  createOpportunityForm.opp_model?.addEventListener('change', refreshCreditLoopPreview);

  // Submit
  createOpportunityForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = {
      client_name:   createOpportunityForm.client_name.value.trim(),
      opp_model:     createOpportunityForm.opp_model.value,
      position_name: createOpportunityForm.position_name.value.trim(),
      sales_lead:    createOpportunityForm.sales_lead.value,
      opp_type:      createOpportunityForm.opp_type.value,
      opp_stage:     'Deep Dive'
    };

    if (formData.opp_type === 'Replacement') {
      const repId = getReplacementCandidateId();
      const endEl = getReplacementEndDateEl();

      if (!repId) {
        alert('Please select a valid candidate to replace (pick from the list).');
        return;
      }
      if (!endEl?.value) {
        alert('Please select the replacement end date.');
        return;
      }
      formData.replacement_of = repId;
      formData.replacement_end_date = endEl.value;
    }

    try {
      const response = await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      const result = await response.json();

      if (response.ok) {
        alert('Opportunity created successfully!');
        logOpportunityTrack('createOpportunityBtn');
        closePopup();
        location.reload();
      } else {
        console.log("🔴 Backend error:", result.error);
        alert('Error: ' + (result.error || 'Unexpected error'));
      }
    } catch (err) {
      console.error('Error creating opportunity:', err);
      alert('Connection error. Please try again.');
    }
  });
}


fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts')
  .then(response => response.json())
  .then(accounts => {
    const datalist = document.getElementById('accountList');
    if (!datalist) return;
    accounts.forEach(account => {
      const option = document.createElement('option');
      option.value = account.account_name;
      datalist.appendChild(option);
    });
  })
  .catch(err => {
    console.error('Error loading accounts:', err);
  });
fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users')
  .then(response => response.json())
  .then(users => {
    const salesDropdown = document.getElementById('sales_lead');
    if (!salesDropdown) return;

fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/users')
  .then(response => response.json())
  .then(users => {
    const salesDropdown = document.getElementById('sales_lead');
    if (!salesDropdown) return;

    // ✅ Allow-list estricta por email (evita confundir Agustin vs Agustina)
    const allowedEmails = new Set([
      'agustin@vintti.com',
      'bahia@vintti.com',
      'lara@vintti.com',
      'mariano@vintti.com',
      'mia@vintti.com'
    ]);

    // Limpia opciones previas y agrega placeholder
    salesDropdown.innerHTML = '<option disabled selected>Select Sales Lead</option>';

    // Filtra por email exacto (case-insensitive)
    users
      .filter(u => allowedEmails.has((u.email_vintti || '').toLowerCase()))
      // (opcional) orden alfabético por nombre
      .sort((a, b) => a.user_name.localeCompare(b.user_name))
      .forEach(user => {
        const option = document.createElement('option');
        option.value = (user.email_vintti || '').toLowerCase();
        option.textContent = user.user_name; 
        salesDropdown.appendChild(option);
      });

    // 🔒 Defensa extra (por si el backend cambia nombres):
    // elimina cualquier opción que contenga "agustina" en el label
    Array.from(salesDropdown.options).forEach(opt => {
      if (/agustina\b/i.test(opt.textContent)) opt.remove();
    });
  })
  .catch(err => console.error('Error loading sales leads:', err));
  })
  .catch(err => console.error('Error loading sales leads:', err));


function getStagePill(stage) {
  switch (stage) {
    case 'Signed':
      return '<span class="stage-pill stage-signed">Signed</span>';
    case 'Close Win':
      return '<span class="stage-pill stage-closewin">Close Win</span>';
    case 'Closed Lost':
      return '<span class="stage-pill stage-closewin">Closed Lost</span>';
    case 'Negotiating':
      return '<span class="stage-pill stage-negotiating">Negotiating</span>';
    case 'Interviewing':
      return '<span class="stage-pill stage-interviewing">Interviewing</span>';
    case 'Stop':
      return '<span class="stage-pill stage-stop">⏸️ Stop</span>';
    case 'Sourcing':
      return '<span class="stage-pill stage-sourcing">Sourcing</span>';
    case 'NDA Sent':
      return '<span class="stage-pill stage-nda">NDA Sent</span>';
    case 'Deep Dive':
      return '<span class="stage-pill stage-deepdive">Deep Dive</span>';
    default:
      return stage ? `<span class="stage-pill">${stage}</span>` : '—';
  }
}
function extractTextFromHTML(htmlString) {
  const div = document.createElement('div');
  div.innerHTML = htmlString;

  // Caso especial para la columna Stage con <select>
  const select = div.querySelector('select');
  if (select) {
    return select.options[select.selectedIndex].textContent;
  }

  return div.textContent || div.innerText || '';
}

// Particle trail en hover para las burbujas
document.querySelectorAll('.bubble-button').forEach(bubble => {
  bubble.addEventListener('mousemove', e => {
    const particle = document.createElement('span');
    particle.classList.add('bubble-particle');
    particle.style.left = `${e.offsetX}px`;
    particle.style.top = `${e.offsetY}px`;

    bubble.appendChild(particle);

    setTimeout(() => {
      particle.remove();
    }, 500); // la partícula desaparece en 500ms
  });
});
function getStageDropdown(currentStage, opportunityId) {
  const stages = [
    'Signed',
    'Close Win',
    'Closed Lost',
    'Negotiating',
    'Interviewing',
    'Stop',
    'Sourcing',
    'NDA Sent',
    'Deep Dive'
  ];

  const normalized = currentStage?.toLowerCase().replace(/\s/g, '-') || '';
  const isFinalStage = currentStage === 'Close Win' || currentStage === 'Closed Lost';

  let dropdown = `<select class="stage-dropdown stage-color-${normalized}" id="opp-stage-${opportunityId}" data-id="${opportunityId}" data-current-stage="${escapeAttribute(currentStage || '')}" ${isFinalStage ? 'disabled' : ''}>`;

  stages.forEach(stage => {
    const selected = stage === currentStage ? 'selected' : '';
    const label = stage === 'Stop' ? '⏸️ Stop' : stage;
    dropdown += `<option value="${stage}" ${selected}>${label}</option>`;
  });

  dropdown += `</select>`;

  return dropdown;
}

function calculateDaysAgo(dateStr) {
  const date = new Date(dateStr);
  const now = new Date();
  const diffTime = Math.abs(now - date);
  const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) - 1;
  return diffDays;
}
function calculateDaysBetween(startStr, endStr) {
  if (!startStr || !endStr) return '-';

  const start = new Date(startStr);
  const end   = new Date(endStr);

  if (isNaN(start) || isNaN(end)) return '-';

  const diffMs   = end - start;
  const msPerDay = 1000 * 60 * 60 * 24;

  // diferencia “normal” en días (0 si fue el mismo día, 1 si fue al día siguiente, etc.)
  const diffDays = Math.floor(diffMs / msPerDay);
  return diffDays;
}
function computeDaysSinceBatch(refDateStr) {
  if (!refDateStr) return null;
  const ref = new Date(refDateStr);
  const today = new Date();
  const diffDays = Math.ceil((today - ref) / (1000 * 60 * 60 * 24)) - 1; // mismo criterio que usas
  return diffDays;
}
function colorizeSourcingCell(cell, days) {
  if (!cell) return;

  // Limpia clases previas
  cell.classList.remove('green-cell', 'yellow-cell', 'red-cell');

  // Si no hay días válidos, muestra guion
  if (days == null || Number.isNaN(Number(days))) {
    cell.textContent = '-';
    cell.removeAttribute('title');
    return;
  }

  const n = Number(days);
  let label = String(n);

  // 🎨 Lógica de colores:
  // 0–1 días  → verde
  // 2–3 días  → amarillo
  // 4+ días   → rojo + ⚠️
  if (n >= 4) {
    cell.classList.add('red-cell');
    label = `${n} ⚠️`;
  } else if (n >= 2) {
    cell.classList.add('yellow-cell');
    label = `${n} ⏳`;
  } else if (n >= 0) {
    cell.classList.add('green-cell');
    label = `${n} 🌱`;
  }

  cell.textContent = label;
  cell.title = `Days since sourcing: ${n}`;
}


function openSourcingPopup(opportunityId, dropdownElement) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`)
    .then(res => res.json())
    .then(opportunity => {
      const hasStartDate = opportunity.nda_signature_or_start_date;

      if (!hasStartDate) {
        // 🟢 Primera vez: abrir popup antigua
        const popup = document.getElementById('sourcingPopup');
        popup.style.display = 'flex';

        const saveBtn = document.getElementById('saveSourcingDate');
        saveBtn.onclick = async () => {
          const date = document.getElementById('sourcingDate').value;
          if (!date) return alert('Please select a date.');

          await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/fields`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nda_signature_or_start_date: date })
          });

          await patchOpportunityStage(opportunityId, 'Sourcing', dropdownElement);
          logOpportunityTrack('saveSourcingDate');
          closeSourcingPopup();
        };
      } else {
        // 🔁 Ya tiene start_date: abrir nueva popup
        const popup = document.getElementById('newSourcingPopup');
        popup.style.display = 'flex';

        const saveNewBtn = document.getElementById('saveNewSourcing');
        saveNewBtn.onclick = async () => {
          const date = document.getElementById('newSourcingDate').value;
          if (!date) return alert('Please select a date.');

          const hr_lead = opportunity.opp_hr_lead;
          if (!hr_lead) return alert('HR Lead is missing.');

          await fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/sourcing', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              opportunity_id: opportunityId,
              user_id: hr_lead,
              since_sourcing: date
            })
          });

          await patchOpportunityStage(opportunityId, 'Sourcing', dropdownElement);
          logOpportunityTrack('saveNewSourcing');
          closeNewSourcingPopup();
        };
      }
    });
}
// —— Close Win: autocomplete rápido ——
const CW_CACHE = new Map(); // término -> resultados [{id,name}]
let cwAbort = null;
let cwSelIndex = -1;
let cwResults = [];
let cwSelectedId = null;

function renderCloseWinList(items){
  const list = document.getElementById('closeWinHireList');
  list.innerHTML = '';

  if (!items.length){
    list.innerHTML = `<div class="autocomplete-empty">No results…</div>`;
  } else {
    items.forEach((it, idx) => {
      const row = document.createElement('div');
      row.className = 'autocomplete-item';
      row.setAttribute('role','option');
      row.setAttribute('data-id', it.candidate_id);
      row.textContent = `${it.candidate_id} - ${it.name}`;
      row.addEventListener('mousedown', (e) => {
        // mousedown para que no pierda foco el input antes de click
        pickCloseWinCandidate(idx);
        e.preventDefault();
      });
      list.appendChild(row);
    });
  }
  list.style.display = 'block';
}

function highlightCloseWinItem(newIndex){
  const list = document.getElementById('closeWinHireList');
  const items = Array.from(list.querySelectorAll('.autocomplete-item'));
  items.forEach((el,i)=> el.setAttribute('aria-selected', i===newIndex ? 'true':'false'));
}

function pickCloseWinCandidate(index){
  const input = document.getElementById('closeWinHireInput');
  const list  = document.getElementById('closeWinHireList');
  const item  = cwResults[index];
  if (!item) return;
  input.value = `${item.candidate_id} - ${item.name}`;
  cwSelectedId = item.candidate_id;
  list.style.display = 'none';
}

async function queryCandidates(term){
  const q = term.trim();
  if (q.length < 2) return [];
  if (CW_CACHE.has(q)) return CW_CACHE.get(q);

  // cancela request anterior
  if (cwAbort) cwAbort.abort();
  cwAbort = new AbortController();

  const url = `https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates?search=${encodeURIComponent(q)}`;
  const res = await fetch(url, { signal: cwAbort.signal });
  const data = await res.json();
  CW_CACHE.set(q, data || []);
  return data || [];
}

function setupCloseWinAutocomplete(){
  const input = document.getElementById('closeWinHireInput');
  const list  = document.getElementById('closeWinHireList');
  if (!input || !list) return;

  let t = null;
  input.addEventListener('input', () => {
    cwSelectedId = null;      // si cambia el texto, invalida selección previa
    clearTimeout(t);
    const term = input.value;
    if (term.trim().length < 2){
      list.style.display = 'none';
      return;
    }
    t = setTimeout(async () => {
      try{
        cwResults = await queryCandidates(term);
        cwSelIndex = -1;
        renderCloseWinList(cwResults);
      } catch(e){
        if (e.name !== 'AbortError') {
          console.error('CW search error:', e);
        }
      }
    }, 220); // debounce
  });

  input.addEventListener('keydown', (e) => {
    if (list.style.display !== 'block') return;
    const max = cwResults.length - 1;
    if (e.key === 'ArrowDown'){
      e.preventDefault();
      cwSelIndex = Math.min(max, cwSelIndex + 1);
      highlightCloseWinItem(cwSelIndex);
    } else if (e.key === 'ArrowUp'){
      e.preventDefault();
      cwSelIndex = Math.max(0, cwSelIndex - 1);
      highlightCloseWinItem(cwSelIndex);
    } else if (e.key === 'Enter'){
      if (cwSelIndex >= 0){
        e.preventDefault();
        pickCloseWinCandidate(cwSelIndex);
      }
    } else if (e.key === 'Escape'){
      list.style.display = 'none';
    }
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('#closeWinHireBox')) {
      list.style.display = 'none';
    }
  });
}


// Popup Signed / Close Win (same modal, different required fields)
function openCloseWinPopup(opportunityId, dropdownElement, { mode = 'signed' } = {}) {
  const popup = document.getElementById('closeWinPopup');
  const titleEl = document.getElementById('closeWinTitle');
  const hireLabel = document.querySelector('label[for="closeWinHireInput"]');
  const hireBox = document.getElementById('closeWinHireBox');
  const dateLabel = document.querySelector('label[for="closeWinDate"]');
  const dateInput = document.getElementById('closeWinDate');
  const hireInput = document.getElementById('closeWinHireInput');
  popup.style.display = 'flex';

  const isSignedMode = mode === 'signed';
  popup.classList.toggle('signed-mode', isSignedMode);
  popup.classList.toggle('close-win-mode', !isSignedMode);

  if (titleEl) titleEl.textContent = isSignedMode ? 'Select Hired Candidate' : 'Set Close Win Date';
  if (hireLabel) hireLabel.style.display = isSignedMode ? '' : 'none';
  if (hireBox) hireBox.style.display = isSignedMode ? '' : 'none';
  if (dateLabel) dateLabel.style.display = isSignedMode ? 'none' : '';
  if (dateInput) dateInput.style.display = isSignedMode ? 'none' : '';

  if (isSignedMode) {
    // inicializa autocomplete solo cuando se necesita seleccionar candidato
    setupCloseWinAutocomplete();
    cwSelectedId = null;
    if (hireInput) hireInput.value = '';
  }
  if (dateInput) dateInput.value = '';
  const hireList = document.getElementById('closeWinHireList');
  if (hireList) hireList.style.display = 'none';

  const saveBtn = document.getElementById('saveCloseWin');
  saveBtn.onclick = async () => {
    const date = document.getElementById('closeWinDate').value;

    try {
      if (isSignedMode) {
        // ✅ tomamos el ID “real” (no split de texto)
        const candidateId = cwSelectedId;
        if (!candidateId) {
          alert('Please select a hire.');
          return;
        }

        // 1) Guardar contratado en opportunity (sin close date en Signed)
        await patchOppFields(opportunityId, {
          candidato_contratado: candidateId
        });

        // 2) Asegurar hire_opportunity
        const res2 = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/hire`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ opportunity_id: Number(opportunityId) })
        });
        if (!res2.ok) throw new Error(await res2.text());

        // 3) Cambiar stage
        await patchOpportunityStage(opportunityId, 'Signed', dropdownElement);
        logOpportunityTrack('saveSigned');

        // 4) Cerrar y redirigir
        popup.style.display = 'none';
        localStorage.setItem('fromCloseWin', 'true');
        window.location.href = `candidate-details.html?id=${candidateId}#hire`;
        return;
      }

      if (!date) {
        alert('Please select a close date.');
        return;
      }

      // Close Win: solo guardar fecha de cierre y cambiar stage
      await patchOppFields(opportunityId, {
        opp_close_date: date
      });
      await patchOpportunityStage(opportunityId, 'Close Win', dropdownElement);
      logOpportunityTrack('saveCloseWin');
      popup.style.display = 'none';

      const hiredCandidateId = await getHiredCandidateIdFromOpportunity(opportunityId);
      if (hiredCandidateId) {
        localStorage.setItem('fromCloseWin', 'true');
        window.location.href = `candidate-details.html?id=${hiredCandidateId}#hire`;
      } else {
        alert('Close Win saved, but no hired candidate is linked yet.');
      }
    } catch (err) {
      console.error(`❌ ${isSignedMode ? 'Signed' : 'Close Win'} flow failed:`, err);
      alert(`${isSignedMode ? 'Signed' : 'Close Win'} failed:\n${err.message}`);
    }
  };
}

async function getHiredCandidateIdFromOpportunity(opportunityId) {
  try {
    const res = await fetch(`${API_BASE}/opportunities/${encodeURIComponent(opportunityId)}`, {
      credentials: 'include'
    });
    if (!res.ok) return null;
    const opp = await res.json();
    const hiredId = Number(opp?.candidato_contratado);
    return Number.isFinite(hiredId) && hiredId > 0 ? hiredId : null;
  } catch (err) {
    console.warn('Could not resolve hired candidate for Close Win redirect:', err);
    return null;
  }
}

function loadCandidatesForCloseWin() {
  fetch('https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates')
    .then(response => response.json())
    .then(candidates => {
      const datalist = document.getElementById('closeWinCandidates');
      datalist.innerHTML = '';
      candidates.forEach(candidate => {
        const option = document.createElement('option');
        option.value = candidate.candidate_id + ' - ' + candidate.name;
        datalist.appendChild(option);
      });
    });
}
function closeSourcingPopup() {
  document.getElementById('sourcingPopup').style.display = 'none';
}
function closeNewSourcingPopup() {
  document.getElementById('newSourcingPopup').style.display = 'none';
}

function closeCloseWinPopup() {
  document.getElementById('closeWinPopup').style.display = 'none';
}
async function patchOpportunityStage(opportunityId, newStage, dropdownElement) {
  try {
    const response = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ opp_stage: newStage })
    });

    const result = await response.json();

    if (response.ok) {
      if (dropdownElement) {
        dropdownElement.setAttribute('data-current-stage', newStage);
        if (typeof window.updateStageDropdownStyle === 'function') {
          window.updateStageDropdownStyle(dropdownElement, newStage);
        }
      }
      const toast = document.getElementById('stage-toast');
      toast.textContent = '✨ Stage updated!';
      toast.style.display = 'inline-block';
      toast.classList.remove('sparkle-show'); // para reiniciar si se repite
      void toast.offsetWidth; // forzar reflow
      toast.classList.add('sparkle-show');

      logOpportunityTrack(trackIdFromEl(dropdownElement, `opp-stage-${opportunityId}`));

      setTimeout(() => {
        toast.style.display = 'none';
      }, 3000);
      return true;
    } else {
      console.error('❌ Error updating stage:', result.error || result);
      alert('Error updating stage: ' + (result.error || 'Unexpected error'));
      return false;
    }
  } catch (err) {
    console.error('❌ Network error updating stage:', err);
    alert('Network error. Please try again.');
    return false;
  }
}
function openCloseLostPopup(opportunityId, dropdownElement) {
  const popup = document.getElementById('closeLostPopup');
  popup.style.display = 'flex';

  const saveBtn = document.getElementById('saveCloseLost');
  saveBtn.onclick = async () => {
    const closeDate = document.getElementById('closeLostDate').value;
    const motive    = document.getElementById('closeLostReason').value;
    const details   = (document.getElementById('closeLostDetails')?.value || '').trim();

    if (!closeDate || !motive) {
      alert("Please fill in both date and reason.");
      return;
    }

    // Construimos el payload
    const payload = {
      opp_close_date:   closeDate,
      motive_close_lost: motive
    };

    // Solo mandamos details si hay algo escrito (opcional)
    if (details) {
      payload.details_close_lost = details;
    }

    // Guardar en DB
    await fetch(`${API_BASE}/opportunities/${opportunityId}/fields`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    await patchOpportunityStage(opportunityId, 'Closed Lost', dropdownElement);
    logOpportunityTrack('saveCloseLost');
    closeCloseLostPopup();
  };
}

function closeCloseLostPopup() {
  document.getElementById('closeLostPopup').style.display = 'none';
}
async function patchOppFields(oppId, payload) {
  console.log("📤 PATCH /opportunities/%s/fields", oppId, payload);
  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${oppId}/fields`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const text = await res.text();
  if (!res.ok) {
    console.error('❌ fields PATCH failed:', res.status, text);
    throw new Error(`fields PATCH ${res.status}: ${text}`);
  }
  try { return JSON.parse(text); } catch { return text; }
}
// --- Equipments(visibilidad por email) ---
(() => {
  const eq = document.getElementById('equipmentsLink');
  if (!eq) return;

  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase();
  const equipmentsAllowed = [
    'angie@vintti.com',
    'jazmin@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com'
  ];

  eq.style.display = equipmentsAllowed.includes(currentUserEmail) ? 'flex' : 'none';
})();
// --- Dashboard + Management Metrics (usar botones del HTML con iconos) ---
(() => {
  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase();
  const DASH_ALLOWED = new Set([
    'agustin@vintti.com',
    'angie@vintti.com',
    'lara@vintti.com',
    'bahia@vintti.com',
    'agostina@vintti.com',
    'mia@vintti.com',
    'jazmin@vintti.com'
  ]);

  const dash = document.getElementById('dashboardLink');
  const mgmt = document.getElementById('managementMetricsLink');

  if (!DASH_ALLOWED.has(currentUserEmail)) {
    if (dash) dash.style.display = 'none';
    if (mgmt) mgmt.style.display = 'none';
    return;
  }

  if (dash) dash.style.display = 'flex';
  if (mgmt) mgmt.style.display = 'flex';
})();
// --- Sales Metrics ---
(() => {
  const currentUserEmail = (localStorage.getItem('user_email') || '').toLowerCase();
  const SALES_ALLOWED = new Set([
    'agustin@vintti.com',
    'angie@vintti.com',
    'lara@vintti.com',
    'bahia@vintti.com',
    'mariano@vintti.com',
    'mia@vintti.com'
  ]);

  const sales = document.getElementById('salesLink');

  if (!SALES_ALLOWED.has(currentUserEmail)) {
    if (sales) sales.style.display = 'none';
    return;
  }

  if (sales) sales.style.display = 'flex';
})();
// --- Recruiter Power (visibilidad por email) ---
(() => {
  const link = document.getElementById('recruiterPowerLink');
  if (!link) return;

  const email = (localStorage.getItem('user_email') || '').toLowerCase().trim();

  const RECRUITER_POWER_ALLOWED = new Set([
    'angie@vintti.com',
    'agostina@vintti.com',
    'agostin@vintti.com',
    'agustin@vintti.com',
    'lara@vintti.com',
    'constanza@vintti.com',
    'pilar@vintti.com',
    'julieta@vintti.com',
    'paz@vintti.com',
    'valentina@vintti.com'
  ]);

  // Mantener flex para icono + texto alineados
  link.style.display = RECRUITER_POWER_ALLOWED.has(email) ? 'flex' : 'none';
})();

window.addEventListener('pageshow', () => {
  const tableCard = document.querySelector('.table-card');
  if (!tableCard) return;                 // ⬅️ evita el error en index
  if (tableCard.classList.contains('exit-left')) {
    tableCard.classList.remove('exit-left');
    tableCard.style.opacity = '1';
    tableCard.style.transform = 'translateX(0)';
  }
});
// --- HR initials (dos letras) ---
const HR_INITIALS_BY_EMAIL = {
  'agostina@vintti.com':                'AC',
  'jazmin@vintti.com':                  'JP',
  'pilar@vintti.com':                   'PL',
  'josefina@vintti.com':                'JP',
  'constanza@vintti.com':               'CL',
  'julieta@vintti.com':                 'JG',
  'paz@vintti.com':                     'PL',
  'valentina@vintti.com':               'VV'
};

function initialsForHRLead(emailOrName) {
  const s = String(emailOrName || '').trim().toLowerCase();

  if (!s) return '—';

  if (HR_INITIALS_BY_EMAIL[s]) return HR_INITIALS_BY_EMAIL[s];

  // Distinción por nombre
  if (s.includes('pilar') && s.includes('flores'))     return 'PL'; // si la Pilar anterior es López
  // fallback histórico (si solo dice "Pilar", asumimos la de siempre)
  if (s === 'pilar' || s.includes('pilar')) return 'PL';

  if (s.includes('agostina') && s.includes('ferrari'))  return 'AF';
  if (s.includes('agostina')) return 'AC';
  if (s.includes('jazmin'))   return 'JP';
  if (s.includes('valentina')) return 'VV';
  if (s.includes('paz'))      return 'PZ';

  return '—';
}

// HTML visible (inicial + avatar). El select va encima, invisible, para que abra con nombres completos.
function hrDisplayHTML(email) {
  const initials = initialsForHRLead(email);
  const avatar   = resolveAvatar(email);
  const nameTip  = displayNameForHR(email);

  const img = avatar ? `<img class="lead-avatar" src="${avatar}" alt="">` : '';
  return `
    <div class="hr-lead lead-tip" data-tip="${escapeHtml(nameTip)}">
      <span class="lead-bubble">${initials}</span>
      ${img}
    </div>
  `;
}

function salesDisplayHTML(emailOrName) {
  const key      = String(emailOrName || '').toLowerCase();
  const initials = initialsForSalesLead(key);
  const bubbleCl = badgeClassForSalesLead(key);
  const avatar   = resolveAvatar(key);
  const nameTip  = displayNameForSales(emailOrName);

  const img = avatar ? `<img class="lead-avatar" src="${avatar}" alt="">` : '';
  return `
    <div class="sales-lead lead-tip" data-tip="${escapeHtml(nameTip)}">
      <span class="lead-bubble ${bubbleCl}">${initials}</span>
      ${img}
    </div>
  `;
}

// Celda completa: display visible + <select> (opciones con nombres completos)
function getHRLeadCell(opp) {
  const email = opp.opp_hr_lead || '';
  return `
    <div class="hr-lead-cell-wrap" style="position:relative;min-height:28px;">
      ${hrDisplayHTML(email)}
      <select class="hr-lead-dropdown"
              id="opp-hr-lead-${opp.opportunity_id}"
              data-id="${opp.opportunity_id}"
              style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;">
        ${generateHROptions(opp.opp_hr_lead)}
      </select>
    </div>
  `;
}


function showLoginAvatar(email) {
  const img = document.getElementById('login-avatar');
  if (!img) return;
  const src = resolveAvatar(email);
  if (src) {
    img.src = src;
    img.style.display = 'block';
  } else {
    img.removeAttribute('src');
    img.style.display = 'none';
  }
}

function showWelcomeAvatar(email) {
  const img = document.getElementById('welcome-avatar');
  if (!img) return;
  const src = resolveAvatar(email);
  if (src) {
    img.src = src;
    img.style.display = 'inline-block';
  } else {
    img.removeAttribute('src');
    img.style.display = 'none';
  }
}

// Mientras el usuario escribe el email en el login
const emailInputEl = document.getElementById('email');
emailInputEl?.addEventListener('input', () => {
  showLoginAvatar(emailInputEl.value);
});
emailInputEl?.addEventListener('blur', () => {
  showLoginAvatar(emailInputEl.value);
});

// Si ya había un email prellenado (autofill del navegador), refleja el avatar
if (emailInputEl && emailInputEl.value) {
  showLoginAvatar(emailInputEl.value);
}
function safePlay(id) {
  const el = document.getElementById(id);
  if (!el) return;
  try {
    el.currentTime = 0;
    const p = el.play();
    if (p && typeof p.catch === 'function') {
      p.catch(err => console.debug('🔇 Click sound blocked/failed:', err));
    }
  } catch (e) {
    console.debug('🔇 Click sound exception:', e);
  }
}
// Map de email -> avatar ya lo tienes en AVATAR_BY_EMAIL y resolveAvatar()

// Detecta email del sales lead si viene en el objeto; si no, infiere por el nombre
function emailForSalesLead(opp) {
  if (opp?.opp_sales_lead) return String(opp.opp_sales_lead).toLowerCase();
  if (opp?.sales_lead) return String(opp.sales_lead).toLowerCase();
  const name = (opp?.sales_lead_name || '').toLowerCase();
  if (name) {
    const match = (window.allowedSalesUsers || []).find(u => String(u.user_name || '').toLowerCase() === name);
    if (match?.email_vintti) return match.email_vintti;
  }
  if (name.includes('bahia'))   return 'bahia@vintti.com';
  if (name.includes('lara'))    return 'lara@vintti.com';
  if (name.includes('agustin')) return 'agustin@vintti.com';
  if (name.includes('mariano')) return 'mariano@vintti.com';
  if (name.includes('mia'))     return 'mia@vintti.com';
  return '';
}

// Iniciales pedidas: Bahía → BL, Lara → LR, Agustín → AR
function initialsForSalesLead(key) {
  if (key.includes('bahia')   || key.includes('bahia@'))   return 'BL';
  if (key.includes('lara')    || key.includes('lara@'))    return 'LR';
  if (key.includes('mariano')    || key.includes('marian@'))    return 'MS';
  if (key.includes('mia')) return 'MC';
  if (key.includes('agustin')) return 'AM';
  return '--';
}

// Clase de color de la burbuja
function badgeClassForSalesLead(key) {
  if (key.includes('bahia')   || key.includes('bahia@'))   return 'bl';
  if (key.includes('lara')    || key.includes('lara@'))    return 'lr';
  if (key.includes('mariano')    || key.includes('marian@'))    return 'ms';
  if (key.includes('mia')) return '';
  if (key.includes('agustin')) return 'am';
  return '';
}

function getSalesLeadCell(opp) {
  // email guardado o inferido
  const email = (emailForSalesLead(opp) || '').toLowerCase();
  const fullName = opp.sales_lead_name || ''; // para filtros

  return `
    <div class="sales-lead-cell-wrap" style="position:relative;min-height:28px;">
      ${salesDisplayHTML(email || fullName)}
      <span class="sr-only" style="display:none">${fullName}</span>
      <select class="sales-lead-dropdown"
              id="opp-sales-lead-${opp.opportunity_id}"
              data-id="${opp.opportunity_id}"
              style="position:absolute;inset:0;opacity:0;width:100%;height:100%;cursor:pointer;">
        ${window.generateSalesOptions(email)}
      </select>
    </div>
  `;
}


function getTypeBadge(type) {
  const t = String(type || '').toLowerCase();
  if (t.startsWith('new'))         return '<span class="type-badge N">N</span>';
  if (t.startsWith('replacement')) return '<span class="type-badge R">R</span>';
  return type || '';
}

window.getCurrentUserEmail = getCurrentUserEmail;
window.getCurrentUserId    = getCurrentUserId;

// --- evita duplicados por cambios rápidos / re-renders ---
window._negotiatingEmailSent = window._negotiatingEmailSent || new Set();
window._closeWinStageEmailSent = window._closeWinStageEmailSent || new Set();
window._closedLostStageEmailSent = window._closedLostStageEmailSent || new Set();
window._signedResigRefReminderTriggered = window._signedResigRefReminderTriggered || new Set();

/**
 * Obtiene info clave de la opp, resuelve el client_name desde accounts y envía email en HTML.
 */
async function sendNegotiatingReminder(opportunityId){
  try {
    // evita re-envíos en la misma sesión
    if (window._negotiatingEmailSent.has(opportunityId)) return;

    // 1) Traer detalles de la oportunidad
    const r = await fetch(`${API_BASE}/opportunities/${opportunityId}`, { credentials: 'include' });
    if (!r.ok) throw new Error(`GET opp ${opportunityId} failed ${r.status}`);
    const opp = await r.json();

    const hrEmail = String(opp.opp_hr_lead || '').toLowerCase().trim();
    if (!hrEmail) {
      console.warn('⚠️ No HR Lead email on opp', opportunityId);
      return; // sin HR lead asignada, no enviamos
    }

    // 2) Resolver nombre de cliente desde accounts (via account_id)
    const client = await resolveAccountName(opp);

    // 3) Rol/posición
    const role   = opp.opp_position_name || 'the role';

    // 4) Asunto + cuerpo en HTML (negritas reales)
    const subject = `Heads up: ${client} — ${role} moved to Negotiating ✨`;

    // pequeño escape por seguridad
    const esc = s => String(s || '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch]));

    const htmlBody = `
<div style="font-family:Inter, Arial, sans-serif; font-size:14px; color:#222; line-height:1.5;">
  <p>Hi there! 🌸</p>
  <p>
    Quick note to share that the opportunity
    <strong>${esc(client)} — ${esc(role)}</strong>
    has just moved to <strong>Negotiating</strong>. 🎉
  </p>
  <p>This is a reminder to:</p>
  <ul>
    <li>Request and upload the <strong>resignation letter</strong> 📝</li>
    <li>Collect and upload the <strong>references</strong> 📎</li>
  </ul>
  <p>Once both are in the hub, please check the box in the candidate overview page. 💕</p>
  <p style="margin-top:16px">— Vintti HUB</p>
</div>`.trim();

    // 5) Enviar email.
    // 🔸 En muchos backends el campo se llama "body" y si huele a HTML lo mandan como HTML.
    // 🔸 Para mayor compatibilidad añadimos también "body_html" y una pista "content_type".
    const payload = {
      to: [hrEmail, 'angie@vintti.com', 'pgonzales@vintti.com'].filter((v, i, arr) => v && arr.indexOf(v) === i),
      subject,
      body: htmlBody,              // si tu /send_email usa esto, verá HTML
      body_html: htmlBody,         // alternativo común
      content_type: 'text/html',   // pista para el backend
      html: true                   // pista opcional
      // cc: ['jazmin@vintti.com'] // descomenta si quieres copia
    };

    const res = await fetch(`${API_BASE}/send_email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errText = await res.text().catch(()=> '');
      throw new Error(`send_email failed ${res.status}: ${errText}`);
    }

    // marca como enviado para no duplicar
    window._negotiatingEmailSent.add(opportunityId);
    console.info('✅ Negotiating reminder sent to', hrEmail);

  } catch (e) {
    console.error('❌ Failed to send negotiating reminder:', e);
  }
}

async function sendCloseWinStageEmail(opportunityId){
  try {
    if (window._closeWinStageEmailSent.has(opportunityId)) return;
    const res = await fetch(`${API_BASE}/reminders/close_win/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ opportunity_id: opportunityId })
    });

    if (!res.ok) {
      const errText = await res.text().catch(()=> '');
      throw new Error(`close_win trigger failed ${res.status}: ${errText}`);
    }

    const result = await res.json().catch(() => ({}));
    if (!result?.sent) {
      throw new Error(result?.reason || 'close_win_email_not_sent');
    }

    window._closeWinStageEmailSent.add(opportunityId);
    console.info('✅ Close Win stage email sent for opp', opportunityId);
  } catch (e) {
    console.error('❌ Failed to send Close Win stage email:', e);
  }
}

async function sendClosedLostStageEmail(opportunityId){
  try {
    if (window._closedLostStageEmailSent.has(opportunityId)) return;
    const res = await fetch(`${API_BASE}/reminders/closed_lost/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ opportunity_id: opportunityId })
    });

    if (!res.ok) {
      const errText = await res.text().catch(()=> '');
      throw new Error(`closed_lost trigger failed ${res.status}: ${errText}`);
    }

    const result = await res.json().catch(() => ({}));
    if (!result?.sent) {
      throw new Error(result?.reason || 'closed_lost_email_not_sent');
    }

    window._closedLostStageEmailSent.add(opportunityId);
    console.info('✅ Closed Lost stage email sent for opp', opportunityId);
  } catch (e) {
    console.error('❌ Failed to send Closed Lost stage email:', e);
  }
}

async function syncCloseWinCreditLoop(opportunityId){
  try {
    const res = await fetch(`${API_BASE}/opportunities/${opportunityId}/credit-loop/sync`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include'
    });
    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      throw new Error(`credit_loop sync failed ${res.status}: ${errText}`);
    }
    return await res.json().catch(() => ({}));
  } catch (e) {
    console.error('❌ Failed to sync Close Win Credit Loop:', e);
    return null;
  }
}

async function triggerSignedResigRefReminder(opportunityId){
  try {
    if (window._signedResigRefReminderTriggered.has(opportunityId)) return;

    const res = await fetch(`${API_BASE}/reminders/hr_lead_signed_resig_ref/trigger`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ opportunity_id: opportunityId, force: true })
    });

    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      throw new Error(`hr_lead_signed_resig_ref trigger failed ${res.status}: ${errText}`);
    }

    window._signedResigRefReminderTriggered.add(opportunityId);
    console.info('✅ Signed HR Lead resignation/reference reminder trigger processed for opp', opportunityId);
  } catch (e) {
    console.error('❌ Failed to trigger Signed HR Lead resignation/reference reminder:', e);
  }
}

/**
 * Hook: después de actualizar el stage, dispara mails automáticos por etapa.
 * (Usa tu patchOpportunityStage existente y solo añadimos la llamada)
 */
const _origPatchOpportunityStage = patchOpportunityStage;
patchOpportunityStage = async function(opportunityId, newStage, dropdownElement){
  const ok = await _origPatchOpportunityStage.call(this, opportunityId, newStage, dropdownElement);
  if (!ok) return ok;

  if (String(newStage) === 'Signed') {
    await triggerSignedResigRefReminder(opportunityId);
  }
  if (String(newStage) === 'Close Win') {
    await syncCloseWinCreditLoop(opportunityId);
    await sendCloseWinStageEmail(opportunityId);
  }
  if (String(newStage) === 'Closed Lost') {
    await sendClosedLostStageEmail(opportunityId);
  }
  return ok;
};
if (typeof window !== 'undefined') {
  window.patchOpportunityStage = patchOpportunityStage;
}
// === Log out button ===
document.addEventListener('DOMContentLoaded', () => {
  const logoutFab = document.getElementById('logoutFab');
  if (!logoutFab) return;

  logoutFab.addEventListener('click', () => {
    // limpiar sesión local
    localStorage.removeItem('user_email');
    localStorage.removeItem('user_id');
    localStorage.removeItem('user_id_owner_email');
    localStorage.removeItem('user_avatar');

    sessionStorage.clear();

    // redirigir al login
    window.location.href = 'index.html';
  });
});

document.addEventListener('DOMContentLoaded', () => {
  const pathname = (window.location.pathname || '').toLowerCase();
  if (pathname.endsWith('/index.html') || pathname === '/' || pathname.endsWith('/docs/')) return;
  maybeShowBirthdayCelebration({
    delayMs: 700,
    onDismiss: () => queueMonthlyMoodRecap({ delayMs: 200 }),
  })
    .then((shown) => {
      if (!shown) return queueMonthlyMoodRecap({ delayMs: 700 });
      return shown;
    })
    .catch(() => {});
});
