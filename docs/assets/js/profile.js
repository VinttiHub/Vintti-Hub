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
// ===== Team PTO (helpers) =====
const TEAM_ALLOWED = new Set([8,2,1,6]); // who can see the tab
const _nz = (n) => (Number.isFinite(Number(n)) ? Number(n) : 0);

function calcVacation(user){
  const acc  = _nz(user.vacaciones_acumuladas);
  const work = _nz(user.vacaciones_habiles);
  const used = _nz(user.vacaciones_consumidas);
  const total = Math.max(0, acc + work);
  const avail = Math.max(0, total - used);
  return { acc, work, total, used, avail };
}
function calcVintti(user){
  const total = _nz(user.vintti_days);
  const used  = _nz(user.vintti_days_consumidos);
  const avail = Math.max(0, total - used);
  return { total, used, avail };
}
function calcHoliday(user){
  const total = _nz(user.feriados_totales);
  const used  = _nz(user.feriados_consumidos);
  const avail = Math.max(0, total - used);
  return { total, used, avail };
}

function renderTeamPtoTable(users){
  const host = document.getElementById("teamPtoTable");
  if (!host) return;

  // helper for zero-dimming
  const valEl = (n) => {
    const v = Number(n) || 0;
    const cls = v === 0 ? "mono zero" : "mono";
    return `<span class="${cls}">${v}</span>`;
  };

  // Header (with group markers + rounded corners handled by CSS)
  const header = `
    <div class="th th--name">Name</div>

    <div class="th th--vac group-vac" data-col="vac-acc"  title="Vacation Accrued">VAC ACC</div>
    <div class="th th--vac group-vac" data-col="vac-work" title="Vacation Current">VAC</div>
    <div class="th th--vac group-vac" data-col="vac-tot"  title="Vacation Total">VAC TOTAL</div>
    <div class="th th--vac group-vac" data-col="vac-used" title="Vacation Used">VAC USED</div>
    <div class="th th--vac group-vac" data-col="vac-left" title="Vacation Left">VAC LEFT</div>

    <div class="th th--vd  group-vd"  data-col="vd-tot"  title="Vintti Days Total">VD TOTAL</div>
    <div class="th th--vd  group-vd"  data-col="vd-used" title="Vintti Days Used">VD USED</div>
    <div class="th th--vd  group-vd"  data-col="vd-left" title="Vintti Days Left">VD LEFT</div>

    <div class="th th--hol group-hol" data-col="hol-tot"  title="Holiday Total">HOL TOTAL</div>
    <div class="th th--hol group-hol" data-col="hol-used" title="Holiday Used">HOL USED</div>
    <div class="th th--hol group-hol" data-col="hol-left" title="Holiday Left">HOL LEFT</div>
  `;

  if (!users?.length){
    host.innerHTML = header + `
      <div class="cell plain" style="grid-column:1/-1;justify-content:center;">No data.</div>
    `;
    return;
  }

  // sort A→Z
  users.sort((a,b)=> String(a.user_name||"").localeCompare(String(b.user_name||"")));

  // compute row data + collect totals for summary
  let totals = {
    vac_acc:0, vac_work:0, vac_total:0, vac_used:0, vac_left:0,
    vd_total:0, vd_used:0,  vd_left:0,
    hol_total:0, hol_used:0, hol_left:0
  };

  const rows = users.map(u=>{
    const name = u.user_name || "—";

    const vac = calcVacation(u); // {acc, work, total, used, avail}
    const vd  = calcVintti(u);   // {total, used, avail}
    const hol = calcHoliday(u);  // {total, used, avail}

    // accumulate totals
    totals.vac_acc   += vac.acc;
    totals.vac_work  += vac.work;
    totals.vac_total += vac.total;
    totals.vac_used  += vac.used;
    totals.vac_left  += vac.avail;

    totals.vd_total  += vd.total;
    totals.vd_used   += vd.used;
    totals.vd_left   += vd.avail;

    totals.hol_total += hol.total;
    totals.hol_used  += hol.used;
    totals.hol_left  += hol.avail;

    // one row (display: contents so hover/background applies to all 12 cells)
    return `
      <div class="row" data-uid="${u.user_id || ''}">
        <div class="cell cell--name">
          <button class="name-link" data-uid="${u.user_id || ''}" type="button" title="View profile">${name}</button>
        </div>

        <div class="cell t-center group-vac border-l">${valEl(vac.acc)}</div>
        <div class="cell t-center group-vac">${valEl(vac.work)}</div>
        <div class="cell t-center group-vac">${valEl(vac.total)}</div>
        <div class="cell t-center group-vac">${valEl(vac.used)}</div>
        <div class="cell t-center group-vac">${valEl(vac.avail)}</div>

        <div class="cell t-center group-vd  border-l">${valEl(vd.total)}</div>
        <div class="cell t-center group-vd">${valEl(vd.used)}</div>
        <div class="cell t-center group-vd">${valEl(vd.avail)}</div>

        <div class="cell t-center group-hol border-l">${valEl(hol.total)}</div>
        <div class="cell t-center group-hol">${valEl(hol.used)}</div>
        <div class="cell t-center group-hol">${valEl(hol.avail)}</div>
      </div>
    `;
  }).join("");

  // summary row (highlighted)
  const summary = `
    <div class="row summary">
      <div class="cell cell--name summary__label">Team Total</div>

      <div class="cell t-center group-vac border-l">${valEl(totals.vac_acc)}</div>
      <div class="cell t-center group-vac">${valEl(totals.vac_work)}</div>
      <div class="cell t-center group-vac">${valEl(totals.vac_total)}</div>
      <div class="cell t-center group-vac">${valEl(totals.vac_used)}</div>
      <div class="cell t-center group-vac">${valEl(totals.vac_left)}</div>

      <div class="cell t-center group-vd  border-l">${valEl(totals.vd_total)}</div>
      <div class="cell t-center group-vd">${valEl(totals.vd_used)}</div>
      <div class="cell t-center group-vd">${valEl(totals.vd_left)}</div>

      <div class="cell t-center group-hol border-l">${valEl(totals.hol_total)}</div>
      <div class="cell t-center group-hol">${valEl(totals.hol_used)}</div>
      <div class="cell t-center group-hol">${valEl(totals.hol_left)}</div>
    </div>
  `;

  host.innerHTML = header + rows + summary;
}
// —— Quick Profile helpers —— //
function openUserQuick(){ const m = $("#userQuickModal"); m?.classList.add("active"); m?.setAttribute("open",""); }
function closeUserQuick(){ const m = $("#userQuickModal"); m?.classList.remove("active"); m?.removeAttribute("open"); }

// Avatar for quick card
function setQuickAvatar({ user_name, avatar_url }){
  const img = $("#uqAvatarImg");
  const ini = $("#uqAvatarInitials");
  if (avatar_url){
    img.src = avatar_url;
    img.onload = ()=>{ img.style.display="block"; ini.style.display="none"; };
    img.onerror = ()=>{ img.style.display="none"; ini.style.display="grid"; ini.textContent = initialsFromName(user_name); };
  }else{
    img.style.display="none";
    ini.style.display="grid";
    ini.textContent = initialsFromName(user_name);
  }
}

function fmtLongDate(v){
  if (!v) return "—";
  const d = new Date(v);
  if (isNaN(d)) return String(v);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "2-digit" });
}

// Fill modal content
function renderUserQuick(u){
  $("#userQuickTitle").textContent = u.user_name || "Team Member";
  $("#uqName").textContent = u.user_name || "—";
  $("#uqEmail").textContent = u.email_vintti || "—";
  $("#uqRole").textContent = u.role || "—";
  $("#uqTeam").textContent = u.team || "—";
  $("#uqEmergency").textContent = u.emergency_contact || "—";
  $("#uqBirth").textContent = fmtLongDate(u.fecha_nacimiento);
  $("#uqStart").textContent = fmtLongDate(u.ingreso_vintti_date);

  // totals: Vacation total = accrued + current (habiles); VD total = vintti_days; Holiday total = feriados_totales
  const vacTotal = _nz(u.vacaciones_acumuladas) + _nz(u.vacaciones_habiles);
  $("#uqVacTotal").textContent = String(vacTotal);
  $("#uqVdTotal").textContent  = String(_nz(u.vintti_days));
  $("#uqHolTotal").textContent = String(_nz(u.feriados_totales));

  setQuickAvatar({ user_name: u.user_name, avatar_url: u.avatar_url });
}

// Click on a name → fetch + open
document.addEventListener("click", async (e)=>{
  const t = e.target;
  if (t.matches(".name-link")){
    e.preventDefault();
    const uid = Number(t.dataset.uid);
    if (!uid) return;

    // optimistic skeleton fill (optional)
    renderUserQuick({
      user_name: "Loading…",
      email_vintti: "—",
      role: "—",
      team: "—",
      emergency_contact: "—",
      fecha_nacimiento: null,
      ingreso_vintti_date: null,
      vacaciones_acumuladas: 0, vacaciones_habiles: 0,
      vintti_days: 0, feriados_totales: 0,
      avatar_url: null
    });
    openUserQuick();

    try{
      const r = await api(`/users/${encodeURIComponent(uid)}`, { method:'GET' });
      if (!r.ok) throw new Error(await r.text());
      const u = await r.json();
      renderUserQuick(u);
    }catch(err){
      console.error("quick profile load error:", err);
      $("#userQuickTitle").textContent = "Could not load profile";
    }
  }

  // close handlers reuse your generic [data-close-modal]
  if (t.matches("#userQuickModal [data-close-modal]")) { closeUserQuick(); }
});

// ✅ Keep ONE copy only
async function loadTeamPto(){
  const host = document.getElementById("teamPtoTable");
  if (host){
    host.innerHTML = `<div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>`;
  }
  try{
    const r = await api(`/users`, { method: 'GET' });
    if (!r.ok) throw new Error(await r.text());
    const arr = await r.json();

    // include vacation, vintti days AND holidays
    const slim = arr.map(u => ({
      user_id: u.user_id,
      user_name: u.user_name,
      email_vintti: u.email_vintti,
      role: u.role,
      emergency_contact: u.emergency_contact,
      team: u.team,
      fecha_nacimiento: u.fecha_nacimiento,
      ingreso_vintti_date: u.ingreso_vintti_date,
      avatar_url: u.avatar_url,

      // Vacation
      vacaciones_acumuladas: u.vacaciones_acumuladas,
      vacaciones_habiles: u.vacaciones_habiles,
      vacaciones_consumidas: u.vacaciones_consumidas,
      // Vintti Days
      vintti_days: u.vintti_days,
      vintti_days_consumidos: u.vintti_days_consumidos,
      // Holidays
      feriados_totales: u.feriados_totales,
      feriados_consumidos: u.feriados_consumidos,
    }));

    renderTeamPtoTable(slim);
  }catch(err){
    console.error('loadTeamPto error:', err);
    if (host){
      host.innerHTML = `
        <div class="th">Name</div><div class="th t-right">Vac Acc</div><div class="th t-right">Vac</div>
        <div class="th t-right">Vac Total</div><div class="th t-right">Vac Used</div><div class="th t-right">Vac Left</div>
        <div class="th t-right">VD Total</div><div class="th t-right">VD Used</div><div class="th t-right">VD Left</div>
        <div class="th t-right">Hol Total</div><div class="th t-right">Hol Used</div><div class="th t-right">Hol Left</div>
        <div class="cell plain" style="grid-column:1/-1;justify-content:center;">Could not load team PTO.</div>
      `;
    }
  }
}
// ===== Leaders' Approvals Tab =====

function enableApprovalsTab(){
  const tabsBar = document.getElementById('tabsBar');
  const panel = document.getElementById('panel-approvals');
  if (!tabsBar || !panel) return;
  if (tabsBar.querySelector('[data-tab="approvals"]')) return; // already added

  const btn = document.createElement('button');
  btn.className = 'tab';
  btn.dataset.tab = 'approvals';
  btn.id = 'tab-approvals';
  btn.type = 'button';
  btn.setAttribute('aria-selected', 'false');
  btn.textContent = 'Approvals';
  tabsBar.appendChild(btn);

  wireTabs(); // rebind to include this tab
}

function fmtDateShort(s){
  if (!s) return "";
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleDateString(undefined, { weekday:"short", month:"short", day:"2-digit" });
}
function daysInclusive(a, b){
  const da = new Date(a), db = new Date(b);
  if (isNaN(da) || isNaN(db)) return 0;
  return Math.max(0, Math.round((db - da)/86400000)) + 1;
}
const kindBadgeClass = (k) => ({ vacation:"badge--vac", holiday:"badge--hol", vintti_day:"badge--vd" }[k] || "");
const kindLabel = (k) => String(k||"").replace("_"," ").replace(/\b\w/g, m=>m.toUpperCase());

function showApprovalsToast(text, ok=true){
  const t = document.getElementById("approvalsToast");
  if (!t) return;
  t.textContent = text;
  t.style.color = ok ? "#0f766e" : "#b91c1c";
  setTimeout(()=> t.textContent = "", 3500);
}
function renderApprovalsTable(items){
  const host = document.getElementById("approvalsTable");
  if (!host) return;

  const header = `
    <div class="th">User</div>
    <div class="th">Type & Dates</div>
    <div class="th t-right">Status</div>
    <div class="th t-right">Actions</div>
  `;

  if (!items?.length){
    host.innerHTML = header + `
      <div class="cell plain" style="grid-column:1/-1;justify-content:center;">No requests from your team.</div>
    `;
    return;
  }

  host.innerHTML = header + items.map(r=>{
    const days = daysInclusive(r.start_date, r.end_date);
    const initials = String(r.user_name||"")
      .trim().split(/\s+/).slice(0,2).map(p=>p[0]||"").join("").toUpperCase();
    const rowTone = r.status === 'approved' ? 'row--approved' : r.status === 'rejected' ? 'row--rejected' : '';
    return `
      <div class="row ${rowTone}" data-id="${r.id}">
        <div class="cell user">
          <div class="avatar-min">${initials || "—"}</div>
          <div class="uinfo">
            <div class="uname">${r.user_name || "—"}</div>
            <div class="uteam">${r.team ? "Team: " + r.team : ""}</div>
          </div>
        </div>
        <div class="cell when">
          <span class="badge-soft ${kindBadgeClass(r.kind)}">${kindLabel(r.kind)}</span>
          <span class="dates">
            <time datetime="${r.start_date}">${fmtDateShort(r.start_date)}</time>
            <span class="sep">→</span>
            <time datetime="${r.end_date}">${fmtDateShort(r.end_date)}</time>
            <span class="days">(${days} day${days===1?'':'s'})</span>
          </span>
          ${r.reason ? `<div class="note" title="Note">${r.reason}</div>` : ``}
        </div>
        <div class="cell t-right">
          <span class="status ${r.status}">${r.status}</span>
        </div>
        <div class="cell t-right actions">
          <button class="btn tiny approve" data-action="approve">Approve</button>
          <button class="btn tiny reject"  data-action="reject">Reject</button>
        </div>
      </div>
    `;
  }).join("");

  // wire buttons
  host.querySelectorAll("[data-action]").forEach(btn=>{
    btn.onclick = async ()=>{
      const row = btn.closest(".row");
      const id = row?.dataset?.id;
      const action = btn.dataset.action; // approve | reject
      if (!id) return;

      // optimistic paint
      row.classList.remove("row--approved","row--rejected");
      if (action === "approve") row.classList.add("row--approved");
      if (action === "reject")  row.classList.add("row--rejected");

      try{
        const r = await api(`/leader/time_off_requests/${encodeURIComponent(id)}`, {
          method: "PATCH",
          headers: { "Content-Type":"application/json" },
          body: JSON.stringify({ status: action === "approve" ? "approved" : "rejected" })
        });
        if (!r.ok) throw new Error(await r.text());
        const j = await r.json();

        const chip = row.querySelector(".status");
        chip.classList.remove("pending","approved","rejected");
        chip.classList.add(j.status);
        chip.textContent = j.status;
        try { loadTeamPto(); } catch {}
      }catch(err){
        // revert tone
        row.classList.remove("row--approved","row--rejected");
        showApprovalsToast("Could not update: " + (err?.message || "error"), false);
      }
    };
  });
}
async function loadLeaderApprovals(){
  const host = document.getElementById("approvalsTable");
  if (host){
    host.innerHTML = `<div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>`;
  }
  try{
    // Try listing — if 403, the viewer isn’t a leader
    const r = await api(`/leader/time_off_requests`, { method:'GET' });
    if (r.status === 403) return false; // not a leader → don’t show tab
    if (!r.ok) throw new Error(await r.text());
    const rows = await r.json();

    // Team pill: prefer your /profile/me.team; else fallback to first row.team
    try{
      const meRes = await api(`/profile/me`, { method:'GET' });
      if (meRes.ok){
        const me = await meRes.json();
        if (me?.team){
          document.getElementById("approvalsTeamName").textContent = me.team;
          document.getElementById("approvalsTeamPill").hidden = false;
        }
      }
    }catch{}

    if (!document.getElementById("approvalsTeamPill").hidden && !document.getElementById("approvalsTeamName").textContent){
      // fallback to first row's team
      const firstTeam = rows?.[0]?.team;
      if (firstTeam){
        document.getElementById("approvalsTeamName").textContent = firstTeam;
        document.getElementById("approvalsTeamPill").hidden = false;
      }
    }

    renderApprovalsTable(rows);
    return true;
  }catch(err){
    console.error('loadLeaderApprovals error:', err);
    if (host){
      host.innerHTML = `<div class="cell plain" style="grid-column:1/-1;justify-content:center;">Could not load approvals.</div>`;
    }
    return false;
  }
}

function enableTeamTab(){
  const tabsBar = document.getElementById('tabsBar');
  const panel = document.getElementById('panel-teampto');
  if (!tabsBar || !panel) return;

  // Avoid duplicating if already present
  if (tabsBar.querySelector('[data-tab="teampto"]')) return;

  const btn = document.createElement('button');
  btn.className = 'tab';
  btn.dataset.tab = 'teampto';
  btn.id = 'tab-teampto';
  btn.type = 'button';
  btn.setAttribute('aria-selected', 'false');
  btn.textContent = 'Team PTO'; // short & clear

  tabsBar.appendChild(btn);
  wireTabs(); // rebind events including this new tab
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

// ===== Tabs (re-usable) =====
function wireTabs(){
  $all(".tab").forEach(btn=>{
    btn.onclick = () => {
      $all(".tab").forEach(b=> b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      $all(".panel").forEach(p=>{
        const isActive = p.id === `panel-${tab}`;
        p.toggleAttribute("hidden", !isActive);
        p.classList.toggle("active", isActive);
      });
    };
  });
}
wireTabs();

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

    // Existing: enable Team PTO for certain user_ids
    if (TEAM_ALLOWED.has(Number(uid))) {
      enableTeamTab();
      loadTeamPto();
    }

    // NEW: Try to enable Approvals tab only if user is truly leader (API decides)
    const isLeader = await loadLeaderApprovals(); // preloads too
    if (isLeader) {
      enableApprovalsTab();
      // re-load once tab exists (optional; we already preloaded)
      // await loadLeaderApprovals();
    }

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
