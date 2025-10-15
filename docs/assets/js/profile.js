function getUidFromQuery() {
  try {
    const q = new URLSearchParams(location.search).get('user_id');
    return q && /^\d+$/.test(q) ? Number(q) : null;
  } catch { return null; }
}

async function ensureUserIdInURL() {
  let uid = getUidFromQuery();

  if (!uid) {
    // 1) intenta cache
    uid = Number(localStorage.getItem('user_id')) || null;
  }
  if (!uid && typeof window.getCurrentUserId === 'function') {
    // 2) resuélvelo por email -> /users
    try { uid = await window.getCurrentUserId(); } catch { uid = null; }
  }

  if (!uid) {
    console.warn("No user_id available (no URL, no cache, no resolver)");
    console.info("Hint: inicia sesión para poblar user_email y poder resolver user_id.");
    return null;
  }

  // cachea por si acaso
  localStorage.setItem('user_id', String(uid));

  // si la URL no lo tiene, la reescribimos sin recargar
  const url = new URL(location.href);
  if (url.searchParams.get('user_id') !== String(uid)) {
    url.searchParams.set('user_id', String(uid));
    history.replaceState(null, '', url.toString());
  }

  return uid;
}

// ===== Config =====
const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com"; // your Flask API base

// ===== Utilities =====
const $ = (sel, root=document) => root.querySelector(sel);
const $all = (sel, root=document) => [...root.querySelectorAll(sel)];

function showToast(el, text, ok=true){
  el.textContent = text;
  el.style.color = ok ? "#0f766e" : "#b91c1c";
  setTimeout(()=> el.textContent = "", 3500);
}

function initialsFromName(name=""){
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0]||"").toUpperCase() + (parts[1]?.[0]||"").toUpperCase();
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

// ===== Profile Load/Save =====
let CURRENT_USER_ID = null;

async function loadMe(uid){
  if (!uid) throw new Error("Missing uid for /profile/me");

  // Primero intenta con header, tu helper api() ya lo hace
  let r = await api(`/profile/me`, { headers: {} });
  if (r.status === 401) {
    // fallback query (api() ya lo hace también, pero por si acaso)
    r = await fetch(`${API_BASE}/profile/me?user_id=${encodeURIComponent(uid)}`, { credentials: "include" });
  }
  if (!r.ok) throw new Error("Failed to load profile");

  const me = await r.json();
  CURRENT_USER_ID = me.user_id ?? uid;

  // Fill form
  $("#user_name").value = me.user_name || "";
  $("#email_vintti").value = me.email_vintti || "";
  $("#role").value = me.role || "";
  $("#emergency_contact").value = me.emergency_contact || "";
  $("#ingreso_vintti_date").value = toInputDate(me.ingreso_vintti_date);
  $("#fecha_nacimiento").value = toInputDate(me.fecha_nacimiento);

  setAvatar({ user_name: me.user_name, avatar_url: me.avatar_url });
}

async function loadMyRequests(uid){
  const list = $("#timeoffList");
  list.innerHTML = `<li>Loading…</li>`;
  try{
    // usa el helper api() para que envíe header y, si hace falta, agregue ?user_id=
    const r = await api(`/time_off_requests`);
    if (!r.ok) throw new Error(await r.text());
    const arr = await r.json();
    if (!arr.length){
      list.innerHTML = `<li>No requests yet.</li>`;
      return;
    }
    list.innerHTML = "";
    arr.forEach(x=>{
      const li = document.createElement("li");
      li.innerHTML = `
        <div>
          <div><strong>${x.kind}</strong> • ${x.start_date} → ${x.end_date}</div>
          <div style="color:#475569; font-size:12px">${x.reason ? x.reason : ""}</div>
        </div>
        <div><span class="badge ${x.status}">${x.status}</span></div>
      `;
      list.appendChild(li);
    });
  }catch(err){
    console.error(err);
    list.innerHTML = `<li>Could not load requests.</li>`;
  }
}

$("#profileForm").addEventListener("submit", async (e)=>{
  e.preventDefault();
  const payload = {
    user_name: $("#user_name").value.trim(),
    email_vintti: $("#email_vintti").value.trim(),
    role: $("#role").value.trim(),
    emergency_contact: $("#emergency_contact").value.trim(),
    ingreso_vintti_date: $("#ingreso_vintti_date").value || null,
    fecha_nacimiento: $("#fecha_nacimiento").value || null,
  };
  const toast = $("#profileToast");
  try{
    const r = await fetch(`${API_BASE}/users/${encodeURIComponent(CURRENT_USER_ID)}`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-User-Id": String(CURRENT_USER_ID)
      },
      credentials: "include",
      body: JSON.stringify(payload)
    });
    if (!r.ok) throw new Error(await r.text());
    showToast(toast, "Saved. Done & dusted 💫");
    // Update avatar if name changed
    setAvatar({ user_name: payload.user_name });
  }catch(err){
    console.error(err);
    showToast(toast, "Could not save changes.", false);
  }
});

// ===== Time Off: Submit + List =====
async function loadMyRequests(){
  const list = $("#timeoffList");
  list.innerHTML = `<li>Loading…</li>`;
  try{
    const r = await fetch(`${API_BASE}/time_off_requests?user_id=${encodeURIComponent(CURRENT_USER_ID)}`, { credentials: "include" });
    if (!r.ok) throw new Error(await r.text());
    const arr = await r.json();
    if (!arr.length){
      list.innerHTML = `<li>No requests yet.</li>`;
      return;
    }
    list.innerHTML = "";
    arr.forEach(x=>{
      const li = document.createElement("li");
      li.innerHTML = `
        <div>
          <div><strong>${x.kind}</strong> • ${x.start_date} → ${x.end_date}</div>
          <div style="color:#475569; font-size:12px">${x.reason ? x.reason : ""}</div>
        </div>
        <div><span class="badge ${x.status}">${x.status}</span></div>
      `;
      list.appendChild(li);
    });
  }catch(err){
    console.error(err);
    list.innerHTML = `<li>Could not load requests.</li>`;
  }
}
// ——— Time Off Balances (read-only) ———
// Source columns in DB (table: users):
// - vacaciones_acumuladas
// - vacaciones_habiles
// - vacaciones_consumidas
// - vintti_days
// - vintti_days_consumidos
//
// Display labels (EN):
// Accrued Vacation (vacaciones_acumuladas)
// Business-day Vacation (vacaciones_habiles)
// Total Vacation (sum)
// Vacation Used (vacaciones_consumidas)
// Vacation Available (Total - Used)
// Total Vintti Days (vintti_days)
// Vintti Days Used (vintti_days_consumidos)
// Vintti Days Available (Total - Used)

function _toNum(v){
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function _fmtDays(n){
  const v = Math.max(0, n);
  return `${v} day${v===1?'':'s'}`;
}

function renderBalances({
  vacaciones_acumuladas = 0,
  vacaciones_habiles = 0,
  vacaciones_consumidas = 0,
  vintti_days = 0,
  vintti_days_consumidos = 0
}){
  const acc = _toNum(vacaciones_acumuladas);
  const work = _toNum(vacaciones_habiles);
  const usedVac = _toNum(vacaciones_consumidas);
  const totalVac = Math.max(0, acc + work);
  const availVac = Math.max(0, totalVac - usedVac);

  const totalVD = _toNum(vintti_days);
  const usedVD = _toNum(vintti_days_consumidos);
  const availVD = Math.max(0, totalVD - usedVD);

  const host = document.getElementById('balancesTable');
  if (!host) return;

  host.innerHTML = `
    <div class="th">Metric</div>
    <div class="th hide-m">Value</div>
    <div class="th hide-m">Notes</div>

    <!-- Vacation block -->
    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vacation</span>
          <span class="name">Accrued Vacation</span>
        </div>
        <span class="kpi">${_fmtDays(acc)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(acc)}</span></div>
      <div class="cell hide-m"><span class="hint">DB: vacaciones_acumuladas</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vacation</span>
          <span class="name">Business-day Vacation</span>
        </div>
        <span class="kpi">${_fmtDays(work)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(work)}</span></div>
      <div class="cell hide-m"><span class="hint">DB: vacaciones_habiles</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vacation</span>
          <span class="name">Total Vacation</span>
        </div>
        <span class="kpi">${_fmtDays(totalVac)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(totalVac)}</span></div>
      <div class="cell hide-m"><span class="hint">Accrued + Business-day</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vacation</span>
          <span class="name">Vacation Used</span>
        </div>
        <span class="kpi">${_fmtDays(usedVac)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(usedVac)}</span></div>
      <div class="cell hide-m"><span class="hint">DB: vacaciones_consumidas</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vacation</span>
          <span class="name">Vacation Available</span>
        </div>
        <span class="kpi">${_fmtDays(availVac)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(availVac)}</span></div>
      <div class="cell hide-m"><span class="hint">Total - Used</span></div>
    </div>

    <!-- Vintti Days block -->
    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vintti Days</span>
          <span class="name">Total Vintti Days</span>
        </div>
        <span class="kpi">${_fmtDays(totalVD)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(totalVD)}</span></div>
      <div class="cell hide-m"><span class="hint">DB: vintti_days</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vintti Days</span>
          <span class="name">Vintti Days Used</span>
        </div>
        <span class="kpi">${_fmtDays(usedVD)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(usedVD)}</span></div>
      <div class="cell hide-m"><span class="hint">DB: vintti_days_consumidos</span></div>
    </div>

    <div class="row">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft">Vintti Days</span>
          <span class="name">Vintti Days Available</span>
        </div>
        <span class="kpi">${_fmtDays(availVD)}</span>
      </div>
      <div class="cell hide-m"><span class="kpi">${_fmtDays(availVD)}</span></div>
      <div class="cell hide-m"><span class="hint">Total - Used</span></div>
    </div>
  `;
}

async function loadBalances(uid){
  const host = document.getElementById('balancesTable');
  if (host) host.innerHTML = `<div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>`;

  try{
    // Si tienes helper api(), úsalo para que pase X-User-Id y fallback ?user_id=
    let r = typeof api === "function"
      ? await api(`/users/${encodeURIComponent(uid)}`)
      : await fetch(`${API_BASE}/users/${encodeURIComponent(uid)}`, { credentials: "include" });

    if (!r.ok){
      // fallback por query si el backend lo requiere
      r = await fetch(`${API_BASE}/users/${encodeURIComponent(uid)}?user_id=${encodeURIComponent(uid)}`, { credentials: "include" });
    }
    if (!r.ok) throw new Error(await r.text());

    const u = await r.json();
    renderBalances({
      vacaciones_acumuladas: u.vacaciones_acumuladas,
      vacaciones_habiles: u.vacaciones_habiles,
      vacaciones_consumidas: u.vacaciones_consumidas,
      vintti_days: u.vintti_days,
      vintti_days_consumidos: u.vintti_days_consumidos
    });
  }catch(err){
    console.error('loadBalances error:', err);
    if (host) host.innerHTML = `<div class="th">Metric</div><div class="th hide-m">Value</div><div class="th hide-m">Notes</div>
      <div class="cell" style="grid-column:1/-1; justify-content:center">Could not load balances.</div>`;
  }
}
async function onTimeoffSubmit(e){
  e.preventDefault();
  const toast = $("#timeoffToast");
  const start = $("#start_date").value;
  const end   = $("#end_date").value;
  if (end < start){
    showToast(toast, "End date must be after start date.", false);
    return;
  }
  const payload = {
    user_id: CURRENT_USER_ID,
    kind: $("#kind").value,
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
    if (!r.ok) throw new Error(await r.text());
    showToast(toast, "Request sent. You got it! ✅");
    $("#timeoffForm").reset();
    await loadMyRequests(CURRENT_USER_ID);
  }catch(err){
    console.error(err);
    showToast(toast, "Could not submit request.", false);
  }
}

// ===== Init =====
(async function init(){
  try{
    const uid = await ensureUserIdInURL();
    if (!uid) return;
    CURRENT_USER_ID = uid;

    await loadMe(uid);
    await loadMyRequests(uid);
    await loadBalances(uid);

    // Engancha el submit AHORA (el DOM ya existe)
    const form = document.getElementById("timeoffForm");
    if (form && !form.dataset.bound){
      form.addEventListener("submit", onTimeoffSubmit);
      form.dataset.bound = "1"; // evita doble binding si recargas parciales
    }
  }catch(err){
    console.error(err);
    alert("Could not load your profile. Please refresh.");
  }
})();

// ===== Init =====
(async function init(){
  try{
    const uid = await ensureUserIdInURL();
    if (!uid) return;                  // no seguimos sin id
    CURRENT_USER_ID = uid;

    await loadMe(uid);                 // pásalo explícito
    await loadMyRequests(uid);         // pásalo explícito
    await loadBalances(uid);
  }catch(err){
    console.error(err);
    alert("Could not load your profile. Please refresh.");
  }
})();
