// ===== Utilities =====
const $ = (sel, root=document) => root.querySelector(sel);
const $all = (sel, root=document) => [...root.querySelectorAll(sel)];

function showToast(el, text, ok=true){
  el.textContent = text;
  el.style.color = ok ? "#0f766e" : "#b91c1c";
  setTimeout(()=> el.textContent = "", 3500);
}
function openTimeoffModal(){ $("#timeoffModal").classList.add("active"); $("#timeoffModal").setAttribute("open",""); }
function closeTimeoffModal(){
  const m = $("#timeoffModal");
  m.classList.remove("active"); m.removeAttribute("open");
}

function showSuccessSplash(){
  const s = $("#timeoffCongrats");
  if (!s) return;
  s.classList.add("active");
  setTimeout(()=> s.classList.remove("active"), 2200);
}

// Wire modal triggers
document.addEventListener("click", (e)=>{
  const t = e.target;
  if (t.matches("#btnOpenTimeoff")) { e.preventDefault(); openTimeoffModal(); }
  if (t.matches("[data-close-modal]")) { e.preventDefault(); closeTimeoffModal(); }
});

function initialsFromName(name=""){
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0]||"").toUpperCase() + (parts[1]?.[0]||"").toUpperCase();
}

// --- API helper (SIN headers custom; añade ?user_id= si existe) ---
async function api(path, opts={}){
  const url = new URL(API_BASE + path);
  const uid = Number(localStorage.getItem('user_id')) || getUidFromQuery();

  if (uid && !url.searchParams.has('user_id')) {
    url.searchParams.set('user_id', String(uid));
  }

  return fetch(url.toString(), {
    credentials: 'include',
    ...opts,
    headers: {
      ...(opts.headers || {}) // NO agregamos X-User-Id
    }
  });
}

function setAvatar({ user_name, avatar_url }){
  const img = $("#avatarImg");
  const ini = $("#avatarInitials");
  if (avatar_url){
    img.src = avatar_url;
    img.onload = ()=> { img.style.display = "block"; ini.style.display = "none"; };
    img.onerror = ()=> { img.style.display = "none"; ini.style.display = "block"; ini.textContent = initialsFromName(user_name); };
  }else{
    img.style.display = "none";
    ini.style.display = "block";
    ini.textContent = initialsFromName(user_name);
  }
}

// Format helpers for date inputs (YYYY-MM-DD)
function toInputDate(v){
  if (!v) return "";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "";
  const mm = String(d.getMonth()+1).padStart(2,"0");
  const dd = String(d.getDate()).padStart(2,"0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

// ===== Tabs =====
$all(".tab").forEach(btn=>{
  btn.addEventListener("click", ()=>{
    $all(".tab").forEach(b=> b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    $all(".panel").forEach(p=>{
      const isActive = p.id === `panel-${tab}`;
      p.toggleAttribute("hidden", !isActive);
      p.classList.toggle("active", isActive);
    });
  });
});

// ===== user_id helpers =====
function getUidFromQuery() {
  try {
    const q = new URLSearchParams(location.search).get('user_id');
    return q && /^\d+$/.test(q) ? Number(q) : null;
  } catch { return null; }
}

async function ensureUserIdInURL() {
  let uid = getUidFromQuery();
  if (!uid) uid = Number(localStorage.getItem('user_id')) || null;
  if (!uid && typeof window.getCurrentUserId === 'function') {
    try { uid = await window.getCurrentUserId(); } catch { uid = null; }
  }
  if (!uid) {
    console.warn("No user_id available (no URL, no cache, no resolver)");
    console.info("Hint: inicia sesión para poblar user_email y poder resolver user_id.");
    return null;
  }
  localStorage.setItem('user_id', String(uid));

  const url = new URL(location.href);
  if (url.searchParams.get('user_id') !== String(uid)) {
    url.searchParams.set('user_id', String(uid));
    history.replaceState(null, '', url.toString());
  }
  console.debug('[profile] using user_id =', uid);
  return uid;
}

// ===== Profile Load/Save =====
let CURRENT_USER_ID = null;

async function loadMe(uid){
  if (!uid) throw new Error("Missing uid for /profile/me");

  // GET sin header custom; api() añade ?user_id=
  const r = await api(`/profile/me`, { method: 'GET' });
  if (!r.ok) throw new Error("Failed to load profile");

  const me = await r.json();
  CURRENT_USER_ID = me.user_id ?? uid;

  $("#user_name").value = me.user_name || "";
  $("#email_vintti").value = me.email_vintti || "";
  $("#role").value = me.role || "";
  $("#emergency_contact").value = me.emergency_contact || "";
  $("#ingreso_vintti_date").value = toInputDate(me.ingreso_vintti_date);
  $("#fecha_nacimiento").value = toInputDate(me.fecha_nacimiento);

  setAvatar({ user_name: me.user_name, avatar_url: me.avatar_url });
}

// ——— Time Off: listar ———
function fmtDateNice(s){
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleDateString(undefined, { weekday:"short", month:"short", day:"2-digit" }); // e.g. Thu, Oct 16
}
function diffDaysInclusive(a, b){
  const da = new Date(a), db = new Date(b);
  if (isNaN(da) || isNaN(db)) return 0;
  const ms = (db - da) / 86400000;
  return Math.max(0, Math.round(ms)) + 1; // inclusive
}

async function loadMyRequests(uid){
  const host = document.getElementById("requestsTable");
  if (!host) return;

  // skeleton while loading
  host.innerHTML = `
    <div class="skeleton-row"></div>
    <div class="skeleton-row"></div>
    <div class="skeleton-row"></div>
  `;

  const kindClass = (k) => ({ vacation:"badge--vac", holiday:"badge--hol", vintti_day:"badge--vd" }[k] || "");
  const kindLabel = (k) => String(k || "").replace("_"," ");

  try{
    const r = await api(`/time_off_requests`, { method: 'GET' });
    if (!r.ok) throw new Error(await r.text());
    const arr = await r.json();

    // 🔸 Only 3 columns now: Type | Dates | Status
    const header = `
      <div class="th">Type</div>
      <div class="th">Dates</div>
      <div class="th t-right">Status</div>
    `;

    if (!arr.length){
      host.innerHTML = header + `
        <div class="cell plain" style="grid-column:1/-1; justify-content:center">No requests yet.</div>
      `;
      return;
    }

    host.innerHTML = header + arr.map(x => {
      const start = fmtDateNice(x.start_date);
      const end   = fmtDateNice(x.end_date);
      const days  = diffDaysInclusive(x.start_date, x.end_date);
      const daysTxt = `${days} day${days === 1 ? "" : "s"}`;

      return `
        <!-- Type -->
        <div class="cell plain">
          <div class="metric">
            <span class="badge-soft ${kindClass(x.kind)}">${kindLabel(x.kind)}</span>
          </div>
        </div>

        /* Dates — super minimal */
        <div class="cell plain">
          <div class="dates-min">
            <time class="d" datetime="${x.start_date}">${start}</time>
            <span class="sep">→</span>
            <time class="d" datetime="${x.end_date}">${end}</time>
            <span class="days">(${days} day${days===1?'':'s'})</span>
          </div>
        </div>

        <!-- Status -->
        <div class="cell plain t-right">
          <span class="status ${String(x.status||'').toLowerCase()}">${x.status}</span>
        </div>
      `;
    }).join("");
  }catch(err){
    console.error(err);
    host.innerHTML = `
      <div class="th">Type</div>
      <div class="th">Dates</div>
      <div class="th t-right">Status</div>
      <div class="cell plain" style="grid-column:1/-1; justify-content:center">Could not load requests.</div>
    `;
  }
}

// ——— Time Off Balances (read-only) ———
function _toNum(v){ const n = Number(v); return Number.isFinite(n) ? n : 0; }
function _fmtDays(n){ const v = Math.max(0, n); return `${v} day${v===1?'':'s'}`; }

 // ——— Time Off Balances (read-only) ———
function _toNum(v){ const n = Number(v); return Number.isFinite(n) ? n : 0; }
function _fmtDays(n){ const v = Math.max(0, n); return `${v} day${v===1?'':'s'}`; }

function renderBalances({
  // VACATION
  vacaciones_acumuladas = 0,
  vacaciones_habiles = 0,
  vacaciones_consumidas = 0,
  // VINTTI DAYS
  vintti_days = 0,
  vintti_days_consumidos = 0,
  // HOLIDAYS (DB: feriados_totales, feriados_consumidos)
  feriados_totales = 0,
  feriados_consumidos = 0,
}){
  // Vacation
  const acc = _toNum(vacaciones_acumuladas);
  const work = _toNum(vacaciones_habiles);
  const usedVac = _toNum(vacaciones_consumidas);
  const totalVac = Math.max(0, acc + work);
  const availVac = Math.max(0, totalVac - usedVac);

  // Vintti Days
  const totalVD = _toNum(vintti_days);
  const usedVD  = _toNum(vintti_days_consumidos);
  const availVD = Math.max(0, totalVD - usedVD);

  // Holidays
  const holAvail = _toNum(feriados_totales);       // “Holiday Available” (DB: feriados_totales)
  const holUsed  = _toNum(feriados_consumidos);    // “Holiday Used”      (DB: feriados_consumidos)
  const holTotal = Math.max(0, holAvail - holUsed);// “Holiday Total” (remaining)

  const host = document.getElementById('balancesTable');
  if (!host) return;

  host.innerHTML = `
    <div class="th">Metric</div>
    <div class="th t-right">Days</div>

    <!-- Vacation -->
    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vac">Vacation</span>
          <span class="name">Accrued Vacation</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(acc)}</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vac">Vacation</span>
          <span class="name">Current year Vacation</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(work)}</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vac">Vacation</span>
          <span class="name">Total Vacation</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(totalVac)}</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vac">Vacation</span>
          <span class="name">Vacation Used</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(usedVac)}</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vac">Vacation</span>
          <span class="name">Vacation Available</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(availVac)}</span></div>
    </div>

    <!-- Vintti Days -->
    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vd">Vintti Days</span>
          <span class="name">Total Vintti Days</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(totalVD)}</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vd">Vintti Days</span>
          <span class="name">Vintti Days Used</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(usedVD)}</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vd">Vintti Days</span>
          <span class="name">Vintti Days Available</span>
        </div>
      </div>
      <div class="cell t-right"><span class="kpi chip">${_fmtDays(availVD)}</span></div>
    </div>

    <!-- Holidays -->
<div class="row">
  <div class="cell">
    <div class="metric">
      <span class="badge-soft badge--hol">Holiday</span>
      <span class="name">Holiday Available</span>
    </div>
  </div>
  <div class="cell t-right"><span class="kpi chip">${_fmtDays(holAvail)}</span></div>
</div>

<div class="row">
  <div class="cell">
    <div class="metric">
      <span class="badge-soft badge--hol">Holiday</span>
      <span class="name">Holiday Used</span>
    </div>
  </div>
  <div class="cell t-right"><span class="kpi chip">${_fmtDays(holUsed)}</span></div>
</div>

<div class="row">
  <div class="cell">
    <div class="metric">
      <span class="badge-soft badge--hol">Holiday</span>
      <span class="name">Holiday Total</span>
    </div>
  </div>
  <div class="cell t-right"><span class="kpi chip">${_fmtDays(holTotal)}</span></div>
</div>

  `;
}

async function loadBalances(uid){
  const host = document.getElementById('balancesTable');
  if (host) host.innerHTML = `<div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>`;
  try{
    const r = await api(`/users/${encodeURIComponent(uid)}`, { method: 'GET' });
    if (!r.ok) throw new Error(await r.text());
    const u = await r.json();
    renderBalances({
      vacaciones_acumuladas: u.vacaciones_acumuladas,
      vacaciones_habiles: u.vacaciones_habiles,
      vacaciones_consumidas: u.vacaciones_consumidas,
      vintti_days: u.vintti_days,
      vintti_days_consumidos: u.vintti_days_consumidos,
      feriados_totales: u.feriados_totales,           // NEW
      feriados_consumidos: u.feriados_consumidos      // NEW
    });
  }catch(err){
    console.error('loadBalances error:', err);
    if (host) host.innerHTML = `
      <div class="th">Metric</div><div class="th t-right">Days</div>
      <div class="cell" style="grid-column:1/-1; justify-content:center">Could not load balances.</div>`;
  }
}

// ——— Time Off: Submit ———
async function onTimeoffSubmit(e){
  e.preventDefault();
  const toast = $("#timeoffToast");
  const start = $("#start_date").value;
  const end   = $("#end_date").value;
  if (!start || !end){
    showToast(toast, "Please pick start & end dates.", false);
    return;
  }
  if (end < start){
    showToast(toast, "End date must be after start date.", false);
    return;
  }

  const payload = {
    user_id: CURRENT_USER_ID,
    kind: $("#kind").value,               // "vacation" | "holiday" | "vintti_day"
    start_date: start,
    end_date: end,
    reason: ($("#reason").value || "").trim() || null
  };

  try{
    const r = await fetch(`${API_BASE}/time_off_requests`, {
      method: "POST",
      headers: { "Content-Type":"application/json" },
      credentials: "include",
      body: JSON.stringify(payload)
    });
    if (!r.ok){
      const msg = await r.text();
      throw new Error(msg || "Failed");
    }

    showToast(toast, "Request sent. You got it! ✅");
    $("#timeoffForm").reset();
    closeTimeoffModal();
    showSuccessSplash();

    await loadMyRequests(CURRENT_USER_ID);
  }catch(err){
    console.error(err);
    showToast(toast, "Could not submit request.", false);
  }
}

// ===== Profile save (PUT) — sin header custom =====
$("#profileForm").addEventListener("submit", async (e)=>{
  e.preventDefault();
  const payload = {
    user_id: CURRENT_USER_ID, // opcional, el backend ya lo acepta por body
    user_name: $("#user_name").value.trim(),
    email_vintti: $("#email_vintti").value.trim(),
    role: $("#role").value.trim(),
    emergency_contact: $("#emergency_contact").value.trim(),
    ingreso_vintti_date: $("#ingreso_vintti_date").value || null,
    fecha_nacimiento: $("#fecha_nacimiento").value || null,
  };
  const toast = $("#profileToast");
  try{
    const r = await fetch(
      `${API_BASE}/users/${encodeURIComponent(CURRENT_USER_ID)}?user_id=${encodeURIComponent(CURRENT_USER_ID)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" }, // <- sin X-User-Id
        credentials: "include",
        body: JSON.stringify(payload)
      }
    );
    if (!r.ok) throw new Error(await r.text());
    showToast(toast, "Saved. Done & dusted 💫");
    setAvatar({ user_name: payload.user_name });
  }catch(err){
    console.error(err);
    showToast(toast, "Could not save changes.", false);
  }
});

// ===== Init (solo UNA vez) =====
(async function init(){
  try{
    const uid = await ensureUserIdInURL();
    if (!uid) return;
    CURRENT_USER_ID = uid;

    await loadMe(uid);
    await loadMyRequests(uid);
    await loadBalances(uid);

    const form = document.getElementById("timeoffForm");
    if (form && !form.dataset.bound){
      form.addEventListener("submit", onTimeoffSubmit);
      form.dataset.bound = "1";
    }
  }catch(err){
    console.error(err);
    alert("Could not load your profile. Please refresh.");
  }
})();
