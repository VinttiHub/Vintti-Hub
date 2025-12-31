// cache de los últimos balances calculados para la tabla de detalles
let LAST_BALANCES = null
let MY_REQUESTS = [];
// ===== Utilities =====
const $ = (sel, root=document) => root.querySelector(sel);
const $all = (sel, root=document) => [...root.querySelectorAll(sel)];
// --- Date-only helpers (local, sin UTC) ---
const _ISO_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function parseISODateLocal(s){
  if (!s) return null;
  if (_ISO_ONLY.test(s)) {
    const [y,m,d] = s.split('-').map(Number);
    return new Date(y, m - 1, d); // <-- local midnight
  }
  // Si llega otro formato, normalizamos a fecha local (tirando hora)
  const d = new Date(s);
  if (isNaN(d)) return null;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function toLocalISO(d){
  if (!(d instanceof Date) || isNaN(d)) return "";
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// ===== US Federal Holidays (observed) for UI =====
// utilidades para calcular n-ésimo día de la semana y último lunes, etc.
function nthWeekday(year, month /*1-12*/, weekday /*0=Sun..6=Sat*/, n /*1..4*/){
  const first = new Date(year, month-1, 1);
  const firstW = first.getDay();
  const offset = (weekday - firstW + 7) % 7;
  const day = 1 + offset + (n - 1) * 7;
  return new Date(year, month-1, day);
}
function lastWeekday(year, month /*1-12*/, weekday){
  const last = new Date(year, month, 0); // last day of month
  const w = last.getDay();
  const offset = (w - weekday + 7) % 7;
  return new Date(year, month-1, last.getDate() - offset);
}
function observed(d){
  // Sat -> Fri, Sun -> Mon
  const w = d.getDay();
  if (w === 6) { const x=new Date(d); x.setDate(d.getDate()-1); return x; }
  if (w === 0) { const x=new Date(d); x.setDate(d.getDate()+1); return x; }
  return d;
}
function computeUSHolidaysObserved(year){
  const set = new Set();
  function add(dt){ set.add(toLocalISO(dt)); }
  // fijos con observancia
  add(observed(new Date(year,0,1)));   // New Year's Day
  add(observed(new Date(year,5,19)));  // Juneteenth
  add(observed(new Date(year,6,4)));   // Independence Day
  add(observed(new Date(year,10,11))); // Veterans Day
  add(observed(new Date(year,11,25))); // Christmas
  // móviles
  add(nthWeekday(year,1,1,3));  // MLK (Mon=1, 3rd)
  add(nthWeekday(year,2,1,3));  // Presidents (3rd Mon Feb)
  add(lastWeekday(year,5,1));   // Memorial (last Mon May)
  add(nthWeekday(year,9,1,1));  // Labor (1st Mon Sep)
  add(nthWeekday(year,10,1,2)); // Columbus/Indigenous (2nd Mon Oct)
  add(nthWeekday(year,11,4,4)); // Thanksgiving (4th Thu Nov)  (Thu=4)
  return set;
}
// Cuenta business days (Mon-Fri, sin feriados US observados)
function businessDaysBetweenISO(startISO, endISO){
  const a = parseISODateLocal(startISO), b = parseISODateLocal(endISO);
  if (!a || !b || b < a) return 0;

  const years = [];
  for(let y=a.getFullYear(); y<=b.getFullYear(); y++) years.push(y);

  const hols = new Set();
  years.forEach(y=>{
    const s = computeUSHolidaysObserved(y);
    for (const d of s) hols.add(d);
  });

  let cnt = 0;
  const cur = new Date(a.getFullYear(), a.getMonth(), a.getDate());
  while (cur <= b){
    const w = cur.getDay();
    const iso = toLocalISO(cur);
    if (w>=1 && w<=5 && !hols.has(iso)) cnt++;
    cur.setDate(cur.getDate()+1);
  }
  return cnt;
}
// Wrapper: si es vacation => business days; otro => inclusivo calendario
function daysForKind(kind, startISO, endISO){
  const k = String(kind || "").toLowerCase();
  if (k === "vacation") return businessDaysBetweenISO(startISO, endISO);
  // VD/Holiday: inclusivo calendario **en local**
  const da = parseISODateLocal(startISO);
  const db = parseISODateLocal(endISO);
  if (!da || !db || db < da) return 0;
  return Math.round((db - da)/86400000) + 1;
}

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
  const removeBtn = t.closest?.("[data-leaderof-remove]");
  if (removeBtn){
    e.preventDefault();
    const id = Number(removeBtn.getAttribute("data-leaderof-remove"));
    if (id){
      ADMIN_LEADER_OF_SELECTED.delete(id);
      renderLeaderOfTags();
    }
  }
});

function initialsFromName(name=""){
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0]||"").toUpperCase() + (parts[1]?.[0]||"").toUpperCase();
}
function resolveInitials(name="", provided=""){
  const clean = String(provided || "").trim();
  if (clean) return clean.toUpperCase();
  return initialsFromName(name);
}
// ===== Team PTO (helpers) =====
const TEAM_ALLOWED = new Set([8,2,1,6]); // who can see the tab
const ADMIN_ALLOWED_EMAILS = new Set([
  "agustin@vintti.com",
  "lara@vintti.com",
  "bahia@vintti.com",
  "agostina@vintti.com",
  "jazmin@vintti.com"
]);
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/i;
let ADMIN_STATUS_TIMER = null;
const ADMIN_LEADER_LOOKUP = new Map();
const ADMIN_LEADER_BY_ID = new Map();
const ADMIN_LEADER_OF_SELECTED = new Map();
let ADMIN_LEADER_OPTIONS = [];
let ADMIN_LEADER_LOADED = false;
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
  const used  = _nz(user.vintti_days_consumidos);
  const total = 2;                          
  const avail = Math.max(0, total - used);  
  return { total, used, avail };
}

function calcHoliday(user){
  const used  = _nz(user.feriados_consumidos);
  const total = 4;                          
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
// ===== PTO Calendar (Approvals) =====

// stable color per person (by user_id or name)
function personColor(seedStr){
  const s = String(seedStr || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h*31 + s.charCodeAt(i)) >>> 0;

  let hue = h % 360;
  if (hue >= 70 && hue <= 120) hue = (hue + 100) % 360;

  return `oklch(0.6 0.10 ${hue}deg)`;
}

const PTO_KIND_LABEL = { vacation: "VAC", holiday: "HOL", vintti_day: "VD" };

function firstOfMonth(d){ return new Date(d.getFullYear(), d.getMonth(), 1); }
function lastOfMonth(d){ return new Date(d.getFullYear(), d.getMonth()+1, 0); }

function fmtMonthLabel(d){
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function expandEventsToDays(events, viewDate){
  // returns Map(key=YYYY-MM-DD, value=[items])
  const map = new Map();
  const start = firstOfMonth(viewDate);
  const end   = lastOfMonth(viewDate);
  const startTs = new Date(start.getFullYear(), start.getMonth(), 1).setHours(0,0,0,0);
  const endTs   = new Date(end.getFullYear(),   end.getMonth(),   end.getDate()).setHours(23,59,59,999);

  for (const ev of events){
    const a = parseISODateLocal(ev.start_date);
    const b = parseISODateLocal(ev.end_date);
    if (isNaN(a) || isNaN(b)) continue;

    // clip to visible month window
    let cur = new Date(Math.max(a, startTs));
    const to  = new Date(Math.min(b,   endTs));
    const isBusinessDayLocal = (d) => {
  const w = d.getDay();               // 0=Sun..6=Sat (local)
  if (w === 0 || w === 6) return false;
  const hols = computeUSHolidaysObserved(d.getFullYear());
  return !hols.has(toLocalISO(d));
};
while (cur <= to){
  const iso = toLocalISO(cur);

  // solo vacaciones: filtrar a días hábiles US; otros tipos, todos los días
  const ok = (String(ev.kind || '').toLowerCase() === 'vacation')
    ? isBusinessDayLocal(cur)
    : true;

  if (ok){
    if (!map.has(iso)) map.set(iso, []);
    map.get(iso).push(ev);
  }

  cur.setDate(cur.getDate()+1);
}
  }
  return map;
}

function renderApprovalsCalendarFromRows(rows){
  // filter only approved
  const approved = (rows || []).filter(r => String(r.status).toLowerCase() === 'approved');

  // build person palette & legend data
  const people = [];
  const byPerson = new Map();
  for (const r of approved){
    const key = String(r.user_id);
    if (!byPerson.has(key)){
      const color = personColor(key || r.user_name || r.user_email);
      byPerson.set(key, { name: r.user_name || "—", color });
      people.push({ id: key, name: r.user_name || "—", color });
    }
  }
  // legend
  const leg = document.getElementById("calLegend");
  if (leg){
    leg.innerHTML = people
      .sort((a,b)=> a.name.localeCompare(b.name))
      .map(p=> `<span class="leg"><span class="dot" style="background:${p.color}"></span>${p.name}</span>`)
      .join("") || `<span class="leg">No approved PTO yet.</span>`;
  }

  const host = document.getElementById("approvalsCalendar");
  const label = document.getElementById("calMonthLabel");
  const tip = document.getElementById("calTooltip");
  if (!host || !label || !tip) return;

  // view state
  let view = new Date(); // today
  view.setDate(1);

  function draw(){
    label.textContent = fmtMonthLabel(view);

    // build grid dates (start on Sunday)
    const first = firstOfMonth(view);
    const last  = lastOfMonth(view);
    const padStart = first.getDay(); // 0=Sun
    const padEnd   = 6 - last.getDay();

    const cells = [];
    // prev month tail
    for (let i=padStart; i>0; i--){
      const d = new Date(first); d.setDate(first.getDate() - i);
      cells.push({ date: d, out: true });
    }
    // month days
    for (let d=1; d<=last.getDate(); d++){
      cells.push({ date: new Date(view.getFullYear(), view.getMonth(), d), out:false });
    }
    // next month head
    for (let i=1; i<=padEnd; i++){
      const d = new Date(last); d.setDate(last.getDate() + i);
      cells.push({ date: d, out: true });
    }

    // date -> events today
    const map = expandEventsToDays(
      approved.map(r => ({
        ...r,
        _person: byPerson.get(String(r.user_id)) || { color: personColor(r.user_id), name: r.user_name || "—" }
      })),
      view
    );

    host.innerHTML = cells.map(({date, out})=>{
      const iso = toLocalISO(date);
      const todays = map.get(iso) || [];
      const evs = todays.slice(0,3).map(ev=>{
        const color = ev._person.color;
        const kind  = PTO_KIND_LABEL[ev.kind] || ev.kind;
        const title = `${ev.user_name || "—"} • ${kind}`;
        return `<div class="cal-badge" data-iso="${iso}" data-name="${ev.user_name||"-"}" data-kind="${kind}" style="--clr:${color}" title="${title}">
                  <span class="kind">${kind}</span><span class="who" style="overflow:hidden;text-overflow:ellipsis;">${ev.user_name||"—"}</span>
                </div>`;
      }).join("");

      // if more than 3, show a tiny counter
      const extra = todays.length > 3 ? `<div class="cal-badge" style="--clr:#cbd5e1">+${todays.length-3} more</div>` : "";

      return `
        <div class="cal-cell ${out ? 'cal-out':''}" data-date="${iso}">
          <div class="cal-daynum">${date.getDate()}</div>
          <div class="cal-events">${evs}${extra}</div>
        </div>`;
    }).join("");

    // hover tooltip
    host.querySelectorAll(".cal-badge").forEach(b=>{
      b.addEventListener("mouseenter", (e)=>{
        const name = b.dataset.name || "—";
        const kind = b.dataset.kind || "";
        const iso  = b.dataset.iso || "";
        tip.innerHTML = `<b>${name}</b><br><span style="opacity:.85">${kind} • ${iso}</span>`;
        tip.style.display = "block";
        const rect = b.getBoundingClientRect();
        tip.style.left = `${rect.left + rect.width/2 + window.scrollX}px`;
        tip.style.top  = `${rect.top + window.scrollY - 10}px`;
        tip.setAttribute("aria-hidden","false");
      });
      b.addEventListener("mouseleave", ()=>{
        tip.style.display = "none";
        tip.setAttribute("aria-hidden","true");
      });
    });
  }

  // nav
  const prev = document.getElementById("calPrev");
  const next = document.getElementById("calNext");
  prev?.addEventListener("click", ()=>{ view.setMonth(view.getMonth()-1); draw(); });
  next?.addEventListener("click", ()=>{ view.setMonth(view.getMonth()+1); draw(); });

  draw();
}

// —— Quick Profile helpers —— //
function openUserQuick(){ const m = $("#userQuickModal"); m?.classList.add("active"); m?.setAttribute("open",""); }
function closeUserQuick(){ const m = $("#userQuickModal"); m?.classList.remove("active"); m?.removeAttribute("open"); }

// Avatar for quick card
function setQuickAvatar({ user_name, avatar_url, initials }){
  const img = $("#uqAvatarImg");
  const ini = $("#uqAvatarInitials");
  if (!img || !ini) return;

  const resolved = resolveInitials(user_name, initials);
  const showInitials = ()=>{
    img.style.display = "none";
    img.removeAttribute("src");
    ini.style.display = "grid";
    ini.textContent = resolved;
  };

  ini.textContent = resolved;

  const trimmed = typeof avatar_url === "string" ? avatar_url.trim() : "";
  if (trimmed){
    img.alt = user_name || "User avatar";
    img.loading = "lazy";
    img.decoding = "async";
    img.style.display = "block";
    ini.style.display = "none";
    img.onload = ()=>{
      img.style.display = "block";
      ini.style.display = "none";
    };
    img.onerror = showInitials;
    if (img.src !== trimmed){
      img.src = trimmed;
    } else if (img.complete && img.naturalWidth === 0){
      showInitials();
    }
  }else{
    showInitials();
  }
}

function fmtLongDate(v){
  if (!v) return "—";
  const d = _ISO_ONLY.test(v) ? parseISODateLocal(v) : new Date(v);
  if (!d || isNaN(d)) return String(v);
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

  // Vacation available = acumuladas + hábiles - consumidas
  const vacTotal = _nz(u.vacaciones_acumuladas) + _nz(u.vacaciones_habiles);
  const vacAvail = Math.max(0, vacTotal - _nz(u.vacaciones_consumidas || 0));
  $("#uqVacTotal").textContent = String(vacAvail);

  // Vintti Days: total fijo = 2
  const vdTotal = 2;
  $("#uqVdTotal").textContent  = String(vdTotal);

  // Holidays: total fijo = 2
  const holTotal = 2;
  $("#uqHolTotal").textContent = String(holTotal);

  setQuickAvatar({ user_name: u.user_name, avatar_url: u.avatar_url, initials: u.initials });
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
      vacaciones_acumuladas: 0,
      vacaciones_habiles: 0,
      vacaciones_consumidas: 0,
      vintti_days_consumidos: 0,
      feriados_consumidos: 0,
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
      initials: u.initials,

      // Vacation
      vacaciones_acumuladas: u.vacaciones_acumuladas,
      vacaciones_habiles: u.vacaciones_habiles,
      vacaciones_consumidas: u.vacaciones_consumidas,
      // Vintti Days (solo consumidos)
      vintti_days_consumidos: u.vintti_days_consumidos,
      // Holidays (solo consumidos)
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
  const d = parseISODateLocal(s);
  if (!d) return s;
  return d.toLocaleDateString(undefined, { weekday:"short", month:"short", day:"2-digit" });
}
function daysInclusive(a, b){
  const da = parseISODateLocal(a), db = parseISODateLocal(b);
  if (!da || !db) return 0;
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

function hydrateAvatarImages(root){
  if (!root) return;
  root.querySelectorAll("[data-avatar-img]").forEach(img => {
    const fallback = img.nextElementSibling;
    const showFallback = ()=>{
      img.style.display = "none";
      if (fallback) fallback.style.display = "grid";
    };
    img.onload = ()=>{
      img.style.display = "block";
      if (fallback) fallback.style.display = "none";
    };
    img.onerror = showFallback;
    if (img.complete && img.naturalWidth === 0){
      showFallback();
    }
  });
}

function renderApprovalsTable(items){
  const hostPending = document.getElementById("approvalsTable");
  if (!hostPending) return;
  const hostHistory = document.getElementById("approvalsHistoryTable");

  hostPending.classList.add("approvals-grid");
  if (hostHistory) hostHistory.classList.add("approvals-grid");

  // Header para la tabla de pendientes (con acciones)
const headerPending = `
  <div class="hdr hdr--employee">Employee</div>
  <div class="hdr hdr--request">Request Date</div>
  <div class="hdr hdr--return">Return Date</div>
  <div class="hdr hdr--days">Days</div>
  <div class="hdr hdr--type">Type</div>
  <div class="hdr hdr--status">Status</div>
  <div class="hdr hdr--action">Action</div>
`;

// Histórico: 6 columnas (sin Action)
const headerHistory = `
  <div class="hdr hdr--employee">Employee</div>
  <div class="hdr hdr--request">Request Date</div>
  <div class="hdr hdr--return">Return Date</div>
  <div class="hdr hdr--days">Days</div>
  <div class="hdr hdr--type">Type</div>
  <div class="hdr hdr--status">Status</div>
`;


  const pending = (items || []).filter(r => String(r.status || "").toLowerCase() === "pending");
  const processed = (items || []).filter(r => {
    const s = String(r.status || "").toLowerCase();
    return s === "approved" || s === "rejected";
  });

  function esc(s){
    return String(s).replace(/[&<>"']/g, function(m){
      return ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      })[m];
    });
  }

  function avatarMarkup(name, avatarUrl, initials){
    const fallback = resolveInitials(name || "", initials);
    if (!avatarUrl){
      return `<div class="avatar-min">${esc(fallback)}</div>`;
    }
    const safeUrl = esc(avatarUrl);
    const safeName = esc(name || "User avatar");
    const safeInitials = esc(fallback);
    return `
      <div class="avatar-min">
        <img data-avatar-img class="avatar-img" src="${safeUrl}" alt="${safeName}" loading="lazy" />
        <span class="avatar-fallback" aria-hidden="true" style="display:none;">${safeInitials}</span>
      </div>
    `;
  }

function buildRow(r, withActions){
  const avatar = avatarMarkup(r.user_name, r.avatar_url, r.initials);

  const startLbl = fmtDateShort(r.start_date);
  const endLbl   = fmtDateShort(r.end_date);
  const days = (String(r.kind || '').toLowerCase() === 'vacation')
    ? businessDaysBetweenISO(r.start_date, r.end_date)
    : diffDaysInclusive(r.start_date, r.end_date);

  const kClass = ({ vacation:"badge--vac", holiday:"badge--hol", vintti_day:"badge--vd" }[r.kind] || "");
  const kLabel = String(r.kind || "").replace("_"," ").replace(/\b\w/g, m=>m.toUpperCase());
  const statusLower = String(r.status || "").toLowerCase();

  const noteBtn = r.reason
    ? '<button class="note-dot" type="button" aria-label="View note" title="' +
        esc(r.reason) + '" data-note="' + esc(r.reason) + '">💬</button>'
    : '';

  // 👉 sólo agregamos columna de acciones si withActions === true
  const actionsCell = withActions
    ? `
      <div class="cell col-actions">
        <div class="actions t-right">
          <button class="btn tiny approve" data-action="approve">✔️</button>
          <button class="btn tiny reject"  data-action="reject">❌</button>
        </div>
      </div>
    `
    : "";   // histórico: nada

  return `
    <div class="row ${statusLower}" data-id="${r.id}">
      <div class="cell col-employee">
        ${avatar}
        <div class="uinfo">
          <div class="uname">
            ${r.user_name || "—"}
            ${noteBtn}
          </div>
          <div class="uteam">${r.team ? "Team: " + r.team : ""}</div>
        </div>
      </div>
      <div class="cell col-request"><time>${startLbl}</time></div>
      <div class="cell col-return"><time>${endLbl}</time></div>
      <div class="cell col-days">${days} day${days===1?'':'s'}</div>
      <div class="cell col-type"><span class="badge-soft ${kClass}">${kLabel}</span></div>
      <div class="cell col-status"><span class="status ${statusLower}">${r.status}</span></div>
      ${actionsCell}
    </div>
  `;
}

  // === Tabla de pendientes ===
  if (!pending.length){
    hostPending.innerHTML = headerPending + `
      <div class="cell plain" style="grid-column:1/-1;justify-content:center;">
        No requests from your team.
      </div>
    `;
  } else {
    hostPending.innerHTML = headerPending + pending.map(r => buildRow(r, true)).join("");
  }
  hydrateAvatarImages(hostPending);

  // === Tabla de histórico ===
  if (hostHistory){
    if (!processed.length){
      hostHistory.innerHTML = headerHistory + `
        <div class="cell plain" style="grid-column:1/-1;justify-content:center;">
          No approved or rejected requests yet.
        </div>
      `;
    } else {
      hostHistory.innerHTML = headerHistory + processed.map(r => buildRow(r, false)).join("");
    }
    hydrateAvatarImages(hostHistory);
  }

  // Wire de botones solo en la tabla de pendientes
  hostPending.querySelectorAll("[data-action]").forEach(btn=>{
    btn.onclick = async ()=>{
      const row = btn.closest(".row");
      const id = row?.dataset?.id;
      const action = btn.dataset.action; // approve | reject
      if (!id) return;

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

        try {
          loadTeamPto();
          // 🔄 recarga ambas tablas, así el item pasa de "pending" → histórico
          loadLeaderApprovals();
        } catch {}
      }catch(err){
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
    const r = await api(`/leader/time_off_requests`, { method:'GET' });
    if (r.status === 403) return false;
    if (!r.ok) throw new Error(await r.text());
    const rows = await r.json();

    // team pill (unchanged) ...
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
      const firstTeam = rows?.[0]?.team;
      if (firstTeam){
        document.getElementById("approvalsTeamName").textContent = firstTeam;
        document.getElementById("approvalsTeamPill").hidden = false;
      }
    }

    renderApprovalsTable(rows);
    // NEW: calendar right below
    renderApprovalsCalendarFromRows(rows);

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

function enableAdminTab(){
  const tabsBar = document.getElementById('tabsBar');
  const panel = document.getElementById('panel-admin');
  if (!tabsBar || !panel) return;
  if (tabsBar.querySelector('[data-tab="admin"]')) return;

  const btn = document.createElement('button');
  btn.className = 'tab';
  btn.dataset.tab = 'admin';
  btn.id = 'tab-admin';
  btn.type = 'button';
  btn.setAttribute('aria-selected', 'false');
  btn.textContent = 'Admin';
  tabsBar.appendChild(btn);
  wireTabs();
}

function buildLeaderLabel(user){
  const name = (user?.user_name || "").trim() || "—";
  const email = (user?.email_vintti || "").trim().toLowerCase();
  return email ? `${name} · ${email}` : name;
}

function renderLeaderOfTags(){
  const host = document.getElementById("adminLeaderOfTags");
  const hidden = document.getElementById("adminLeaderOfUserIds");
  if (hidden){
    const ids = Array.from(ADMIN_LEADER_OF_SELECTED.keys());
    hidden.value = ids.length ? ids.join(",") : "";
  }
  if (!host) return;
  host.innerHTML = "";
  ADMIN_LEADER_OF_SELECTED.forEach((label, id)=>{
    const pill = document.createElement("span");
    pill.className = "leader-tag";
    const text = document.createElement("span");
    text.textContent = label;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.setAttribute("data-leaderof-remove", String(id));
    btn.setAttribute("aria-label", `Remove ${label}`);
    btn.textContent = "×";
    pill.append(text, btn);
    host.appendChild(pill);
  });
}

function clearLeaderOfSelection(){
  ADMIN_LEADER_OF_SELECTED.clear();
  renderLeaderOfTags();
  const input = document.getElementById("adminLeaderOfInput");
  if (input) input.value = "";
}

function addLeaderOfById(candidateId){
  const idNum = Number(candidateId);
  if (!idNum || ADMIN_LEADER_OF_SELECTED.has(idNum)) return false;
  const label = ADMIN_LEADER_BY_ID.get(idNum) || `ID ${idNum}`;
  ADMIN_LEADER_OF_SELECTED.set(idNum, label);
  renderLeaderOfTags();
  return true;
}

function commitLeaderOfSelection(){
  const input = document.getElementById("adminLeaderOfInput");
  if (!input) return;
  const raw = (input.value || "").trim();
  if (!raw) return;
  const id = ADMIN_LEADER_LOOKUP.get(raw.toLowerCase());
  if (!id) return;
  if (addLeaderOfById(id)){
    input.value = "";
  }
}

function syncAdminLeaderSelection(){
  const input = document.getElementById("adminLeaderInput");
  const hidden = document.getElementById("adminLeaderUserId");
  if (!input || !hidden) return;
  const key = (input.value || "").trim().toLowerCase();
  const leaderId = ADMIN_LEADER_LOOKUP.get(key);
  hidden.value = leaderId ? String(leaderId) : "";
}

function wireAdminLeaderInput(){
  const input = document.getElementById("adminLeaderInput");
  if (input && !input.dataset.bound){
    input.addEventListener("input", syncAdminLeaderSelection);
    input.addEventListener("change", syncAdminLeaderSelection);
    input.dataset.bound = "1";
  }
  const multi = document.getElementById("adminLeaderOfInput");
  if (multi && !multi.dataset.bound){
    const commit = () => commitLeaderOfSelection();
    multi.addEventListener("change", commit);
    multi.addEventListener("blur", commit);
    multi.addEventListener("keydown", (ev)=>{
      if (ev.key === "Enter" || ev.key === ","){
        ev.preventDefault();
        commit();
      }
    });
    multi.dataset.bound = "1";
  }
}

async function ensureAdminLeaderOptions(force=false){
  if (ADMIN_LEADER_LOADED && !force) return;
  const listEl = document.getElementById("adminLeaderOptions");
  const input = document.getElementById("adminLeaderInput");
  if (!listEl || !input) return;
  try{
    const res = await api(`/users`, { method: "GET" });
    if (!res.ok) throw new Error("Could not load leaders");
    const rows = await res.json();
    ADMIN_LEADER_OPTIONS = Array.isArray(rows) ? rows : [];
    ADMIN_LEADER_LOOKUP.clear();
    ADMIN_LEADER_BY_ID.clear();
    listEl.replaceChildren();
    const frag = document.createDocumentFragment();
    ADMIN_LEADER_OPTIONS.forEach((user)=>{
      if (!user?.user_id) return;
      const label = buildLeaderLabel(user);
      const idNum = Number(user.user_id);
      ADMIN_LEADER_LOOKUP.set(label.toLowerCase(), idNum);
      ADMIN_LEADER_BY_ID.set(idNum, label);
      const opt = document.createElement("option");
      opt.value = label;
      frag.appendChild(opt);
    });
    listEl.appendChild(frag);
    ADMIN_LEADER_LOADED = true;
    syncAdminLeaderSelection();
    const current = Array.from(ADMIN_LEADER_OF_SELECTED.entries());
    let changed = false;
    current.forEach(([id, label])=>{
      if (!ADMIN_LEADER_BY_ID.has(id)){
        ADMIN_LEADER_OF_SELECTED.delete(id);
        changed = true;
      }else{
        const canonical = ADMIN_LEADER_BY_ID.get(id);
        if (canonical && canonical !== label){
          ADMIN_LEADER_OF_SELECTED.set(id, canonical);
          changed = true;
        }
      }
    });
    if (changed) renderLeaderOfTags();
  }catch(err){
    console.error("admin leader options error:", err);
    ADMIN_LEADER_LOADED = false;
  }
}

function setupAdminForm(){
  const form = document.getElementById("adminCreateForm");
  if (!form || form.dataset.bound) return;
  form.addEventListener("submit", onAdminCreateSubmit);
  form.dataset.bound = "1";
  wireAdminLeaderInput();
  renderLeaderOfTags();
  ensureAdminLeaderOptions();
}

function setAdminStatus(text, ok=true){
  const toast = document.getElementById("adminStatus");
  if (!toast) return;
  toast.textContent = text;
  toast.style.color = ok ? "#0f766e" : "#b91c1c";
  if (ADMIN_STATUS_TIMER){
    clearTimeout(ADMIN_STATUS_TIMER);
  }
  if (text){
    ADMIN_STATUS_TIMER = setTimeout(()=> {
      toast.textContent = "";
    }, 4500);
  }
}

async function onAdminCreateSubmit(ev){
  ev.preventDefault();
  const form = ev.currentTarget;
  const submitBtn = form.querySelector('button[type="submit"]');
  const fullName = (document.getElementById("adminFullName")?.value || "").trim();
  const email = (document.getElementById("adminEmail")?.value || "").trim().toLowerCase();
  const role = (document.getElementById("adminRole")?.value || "").trim();
  const active = document.getElementById("adminActive")?.checked ?? true;
  const isRecruiter = document.getElementById("adminIsRecruiter")?.checked ?? false;
  const isSalesLead = document.getElementById("adminIsSalesLead")?.checked ?? false;
  const sendInviteInput = document.getElementById("adminSendInvite");
  const shouldInvite = active ? (sendInviteInput?.checked ?? true) : false;
  const leaderInput = document.getElementById("adminLeaderInput");
  const leaderIdInput = document.getElementById("adminLeaderUserId");
  const typedLeader = (leaderInput?.value || "").trim();
  const leaderId = Number(leaderIdInput?.value) || null;
  const leaderOfIds = Array.from(ADMIN_LEADER_OF_SELECTED.keys());

  if (!fullName){
    setAdminStatus("Enter the person's full name.", false);
    return;
  }
  if (!email || !EMAIL_RE.test(email)){
    setAdminStatus("Enter a valid email address.", false);
    return;
  }
  if (typedLeader && !leaderId){
    setAdminStatus("Please pick a leader from the suggestions.", false);
    leaderInput?.focus();
    return;
  }

  const roleTags = [];
  if (isRecruiter) roleTags.push("recruiter");
  if (isSalesLead) roleTags.push("sales_lead");

  const payload = {
    full_name: fullName,
    email,
    role: role || undefined,
    is_active: Boolean(active),
    send_invite: Boolean(shouldInvite),
    leader_user_id: leaderId || undefined,
    leader_of_user_ids: leaderOfIds.length ? leaderOfIds : undefined,
    roles: roleTags.length ? roleTags : undefined,
    is_recruiter: isRecruiter,
    is_sales_lead: isSalesLead
  };

  if (submitBtn) submitBtn.disabled = true;
  setAdminStatus("Creating user…", true);

  try{
    const res = await api(`/admin/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json().catch(()=>null);
    if (!res.ok || !data?.ok){
      const msg = data?.error || data?.message || "Could not create user.";
      throw new Error(msg);
    }
    form.reset();
    document.getElementById("adminActive").checked = true;
    document.getElementById("adminSendInvite").checked = true;
    document.getElementById("adminIsRecruiter").checked = false;
    document.getElementById("adminIsSalesLead").checked = false;
    if (leaderIdInput) leaderIdInput.value = "";
    if (leaderInput) leaderInput.value = "";
    syncAdminLeaderSelection();
    clearLeaderOfSelection();
    setAdminStatus(data.message || "User created.", true);
    await ensureAdminLeaderOptions(true);
  }catch(err){
    console.error("admin create error:", err);
    setAdminStatus(err?.message || "Could not create user.", false);
  }finally{
    if (submitBtn) submitBtn.disabled = false;
  }
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

function setAvatar({ user_name, avatar_url, initials }){
  const img = $("#avatarImg");
  const ini = $("#avatarInitials");
  if (!img || !ini) return;

  const resolved = resolveInitials(user_name, initials);
  const showInitials = ()=>{
    img.style.display = "none";
    img.removeAttribute("src");
    ini.style.display = "grid";
    ini.textContent = resolved;
  };

  ini.textContent = resolved;

  const trimmed = typeof avatar_url === "string" ? avatar_url.trim() : "";
  if (trimmed){
    img.alt = user_name || "User avatar";
    img.loading = "lazy";
    img.decoding = "async";
    img.style.display = "block";
    ini.style.display = "none";
    img.onload = ()=>{
      img.style.display = "block";
      ini.style.display = "none";
    };
    img.onerror = showInitials;
    if (img.src !== trimmed){
      img.src = trimmed;
    } else if (img.complete && img.naturalWidth === 0){
      showInitials();
    }
  }else{
    showInitials();
  }
}

function ensureAvatarField(){
  let input = document.getElementById("avatar_url");
  if (input) return input;
  const form = document.getElementById("profileForm");
  const grid = form?.querySelector(".grid");
  if (!grid) return null;
  const wrapper = document.createElement("label");
  wrapper.className = "field";
  wrapper.innerHTML = `
    <span class="label">Avatar URL</span>
    <input name="avatar_url" id="avatar_url" type="url" placeholder="https://example.com/photo.jpg" inputmode="url" />
  `;
  grid.appendChild(wrapper);
  input = wrapper.querySelector("input");
  return input;
}

// Format helpers for date inputs (YYYY-MM-DD)
function toInputDate(v){
  if (!v) return "";
  if (_ISO_ONLY.test(v)) return v; // ya está bien
  const d = parseISODateLocal(v);
  if (!d) return "";
  return toLocalISO(d);
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

  setAvatar({ user_name: me.user_name, avatar_url: me.avatar_url, initials: me.initials });
}

// ——— Time Off: listar ———
function fmtDateNice(s){
  if (!s) return "";
  const d = parseISODateLocal(s);
  if (!d) return String(s);
  return d.toLocaleDateString(undefined, { weekday:"short", month:"short", day:"2-digit" });
}
function diffDaysInclusive(a, b){
  const da = parseISODateLocal(a), db = parseISODateLocal(b);
  if (!da || !db) return 0;
  return Math.max(0, Math.round((db - da)/86400000)) + 1;
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
    MY_REQUESTS = arr || [];
    // 🔸 5 columnas: Type | Request Date | Return Date | Days | Status
const header = `
  <div class="th icon icon--type">Type</div>
  <div class="th icon icon--request">Request Date</div>
  <div class="th icon icon--return">Return Date</div>
  <div class="th icon icon--days">Days</div>
  <div class="th icon icon--status">Status</div>
  <div class="th icon icon--action">Action</div>
`;


    if (!arr.length){
      host.innerHTML = header + `
        <div class="cell plain" style="grid-column:1/-1; justify-content:center">No requests yet.</div>
      `;
      return;
    }

host.innerHTML = header + arr.map(x=>{
  const start = fmtDateNice(x.start_date);
  const end   = fmtDateNice(x.end_date);

  const days = (String(x.kind || '').toLowerCase() === 'vacation')
    ? businessDaysBetweenISO(x.start_date, x.end_date)
    : diffDaysInclusive(x.start_date, x.end_date);

  const statusCls = String(x.status || '').toLowerCase(); // approved | rejected | pending
  const rowCls = statusCls ? `row--${statusCls}` : '';

  const canDelete = statusCls === "pending"; // 👈 solo pending
  const actionCell = canDelete
    ? `<button class="btn-delete" type="button" data-delete-req="${x.id}" aria-label="Delete request" title="Delete">🗑️</button>`
    : `<span class="muted">—</span>`;

  return `
    <div class="row ${rowCls}" data-req-id="${x.id}">
      <div class="cell">
        <span class="badge-soft ${kindClass(x.kind)}">${kindLabel(x.kind)}</span>
      </div>
      <div class="cell"><time datetime="${x.start_date}">${start}</time></div>
      <div class="cell"><time datetime="${x.end_date}">${end}</time></div>
      <div class="cell t-right"><b class="days">${days} day${days===1?'':'s'}</b></div>
      <div class="cell t-center"><span class="status ${statusCls}">${x.status}</span></div>
      <div class="cell t-center">${actionCell}</div>
    </div>
  `;
}).join("");

  }catch(err){
    console.error(err);
    host.innerHTML = `
      <div class="th">Type</div>
      <div class="th">Request Date</div>
      <div class="th">Return Date</div>
      <div class="th t-right">Days</div>
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

// ——— Time Off Balances (read-only) ———
function _toNum(v){ const n = Number(v); return Number.isFinite(n) ? n : 0; }

function renderBalances({
  // VACATION
  vacaciones_acumuladas = 0,
  vacaciones_habiles = 0,
  vacaciones_consumidas = 0,
  // VINTTI DAYS
  vintti_days_consumidos = 0,
  // HOLIDAYS
  feriados_consumidos = 0,
} = {}){
  const host = document.getElementById('balancesTable');
  if (!host) return;

  // 🔹 Vacations
  const acc       = _toNum(vacaciones_acumuladas);
  const work      = _toNum(vacaciones_habiles);
  const usedVac   = _toNum(vacaciones_consumidas);
  const totalVac  = Math.max(0, acc + work);
  const availVac  = Math.max(0, totalVac - usedVac);

  // 🔹 Vintti Days (total fijo = 2)
  const totalVD   = 2;
  const usedVD    = _toNum(vintti_days_consumidos);
  const availVD   = Math.max(0, totalVD - usedVD);

  // 🔹 Holidays (total fijo = 4)
  const totalHol  = 4;
  const usedHol   = _toNum(feriados_consumidos);
  const availHol  = Math.max(0, totalHol - usedHol);

  // 👉 guardamos todo para usarlo al hacer click en las tarjetas
  LAST_BALANCES = {
    vac_acc: acc,
    vac_work: work,
    vac_used: usedVac,         
    vac_available: availVac,

    vd_total: totalVD,
    vd_used: usedVD,
    vd_available: availVD,

    hol_total: totalHol,
    hol_used: usedHol,
    hol_available: availHol,
  };

  // 👇 estructura igual que antes (solo añadimos data-kind en cada .row)
  host.innerHTML = `
    <div class="th">Metric</div>
    <div class="th t-right">Days</div>

    <!-- 🔹 1. Vacations Available -->
    <div class="row" data-kind="vacation">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vac">Vacation</span>
          <span class="name">Vacations Available</span>
        </div>
      </div>
      <div class="cell t-right">
        <span class="kpi chip">${availVac} Days</span>
      </div>
    </div>

    <!-- 🔹 2. Vintti Days Available -->
    <div class="row" data-kind="vintti_day">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--vd">Vintti Days</span>
          <span class="name">Vintti Days Available</span>
        </div>
      </div>
      <div class="cell t-right">
        <span class="kpi chip">${availVD} Days</span>
      </div>
    </div>

    <!-- 🔹 3. Holiday Available -->
    <div class="row" data-kind="holiday">
      <div class="cell">
        <div class="metric">
          <span class="badge-soft badge--hol">Public Holidays</span>
          <span class="name">Public Holidays Available</span>
        </div>
      </div>
      <div class="cell t-right">
        <span class="kpi chip">${availHol} Days</span>
      </div>
    </div>
  `;
}

async function loadBalances(uid){
  try{
    const r = await api(`/users/${encodeURIComponent(uid)}`, { method: 'GET' });
    if (!r.ok) throw new Error(await r.text());
    const u = await r.json();
    renderBalances({
      vacaciones_acumuladas: u.vacaciones_acumuladas,
      vacaciones_habiles: u.vacaciones_habiles,
      vacaciones_consumidas: u.vacaciones_consumidas,
      vintti_days_consumidos: u.vintti_days_consumidos,
      feriados_consumidos: u.feriados_consumidos
    });
  }catch(err){
    console.error('loadBalances error:', err);
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

// ============================= PROFILEEEE =============================
$("#profileForm").addEventListener("submit", async (e)=>{
  e.preventDefault();
  const avatarInput = ensureAvatarField();
  const avatarUrlValue = avatarInput ? avatarInput.value.trim() : "";
  const payload = {
    user_id: CURRENT_USER_ID, // opcional, el backend ya lo acepta por body
    user_name: $("#user_name").value.trim(),
    email_vintti: $("#email_vintti").value.trim(),
    role: $("#role").value.trim(),
    emergency_contact: $("#emergency_contact").value.trim(),
    ingreso_vintti_date: $("#ingreso_vintti_date").value || null,
    fecha_nacimiento: $("#fecha_nacimiento").value || null,
    avatar_url: avatarUrlValue || null,
  };
  const toast = $("#profileToast");
  try{
    const r = await fetch(
      `${API_BASE}/users/${encodeURIComponent(CURRENT_USER_ID)}?user_id=${encodeURIComponent(CURRENT_USER_ID)}`,
      {
        method: "PATCH",                      
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload)
      }
    );
    if (!r.ok) throw new Error(await r.text());
    showToast(toast, "Saved. Done & dusted 💫");
    PROFILE_CACHE = {
      ...(PROFILE_CACHE || {}),
      user_id: CURRENT_USER_ID,
      user_name: payload.user_name,
      email_vintti: payload.email_vintti,
      role: payload.role,
      emergency_contact: payload.emergency_contact,
      ingreso_vintti_date: payload.ingreso_vintti_date,
      fecha_nacimiento: payload.fecha_nacimiento,
      avatar_url: payload.avatar_url,
      initials: resolveInitials(payload.user_name)
    };
    renderProfileView(PROFILE_CACHE);
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
    setupBalanceCardTables();

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


// cache global de perfil (raw del backend)
let PROFILE_CACHE = null;

function fmtLongDateSafe(v){
  if (!v) return "—";

  // si viene como "YYYY-MM-DD" la parseamos en local
  const d = _ISO_ONLY.test(v) ? parseISODateLocal(v) : new Date(v);

  if (!d || isNaN(d)) return "—";
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

function renderProfileView(me){
  if (!me) return;
  // Header
  $("#v_user_name")?.replaceChildren(document.createTextNode(me.user_name || "—"));
  $("#v_role")?.replaceChildren(document.createTextNode(me.role || "—"));

  // Card fields
  $("#v_full_name")?.replaceChildren(document.createTextNode(me.user_name || "—"));
  $("#v_email")?.replaceChildren(document.createTextNode(me.email_vintti || "—"));
  $("#v_role_2")?.replaceChildren(document.createTextNode(me.role || "—"));
  $("#v_emergency")?.replaceChildren(document.createTextNode(me.emergency_contact || "—"));
  $("#v_start")?.replaceChildren(document.createTextNode(fmtLongDateSafe(me.ingreso_vintti_date)));
  $("#v_birth")?.replaceChildren(document.createTextNode(fmtLongDateSafe(me.fecha_nacimiento)));

  // Avatar
  setAvatar({ user_name: me.user_name, avatar_url: me.avatar_url, initials: me.initials });
}

function showProfileView(){
  $("#profileView")?.removeAttribute("hidden");
  $("#profileEdit")?.setAttribute("hidden", "");
}
function showProfileEdit(){
  $("#profileView")?.setAttribute("hidden", "");
  $("#profileEdit")?.removeAttribute("hidden");
  $("#user_name")?.focus();
}

async function loadMe(uid){
  if (!uid) throw new Error("Missing uid for /profile/me");

  const r = await api(`/profile/me`, { method: 'GET' });
  if (!r.ok) throw new Error("Failed to load profile");
  const me = await r.json();
  CURRENT_USER_ID = me.user_id ?? uid;

  // Guarda RAW en cache para vista/cancel
  PROFILE_CACHE = {
    user_id: CURRENT_USER_ID,
    user_name: me.user_name || "",
    email_vintti: me.email_vintti || "",
    role: me.role || "",
    emergency_contact: me.emergency_contact || "",
    ingreso_vintti_date: me.ingreso_vintti_date || null, // RAW
    fecha_nacimiento: me.fecha_nacimiento || null,       // RAW
    avatar_url: me.avatar_url || null,
    initials: resolveInitials(me.user_name, me.initials)
  };

  // Inputs con formato input-date
  $("#user_name").value = PROFILE_CACHE.user_name;
  $("#email_vintti").value = PROFILE_CACHE.email_vintti;
  $("#role").value = PROFILE_CACHE.role;
  $("#emergency_contact").value = PROFILE_CACHE.emergency_contact;
  $("#ingreso_vintti_date").value = toInputDate(PROFILE_CACHE.ingreso_vintti_date);
  $("#fecha_nacimiento").value  = toInputDate(PROFILE_CACHE.fecha_nacimiento);
  const avatarInput = ensureAvatarField();
  if (avatarInput) avatarInput.value = PROFILE_CACHE.avatar_url || "";

  const normalizedEmail = (PROFILE_CACHE.email_vintti || "").toLowerCase();
  if (ADMIN_ALLOWED_EMAILS.has(normalizedEmail)){
    enableAdminTab();
    setupAdminForm();
  }

  // Vista
  renderProfileView(PROFILE_CACHE);
  showProfileView();
}

document.addEventListener("click", (e)=>{
  if (e.target.matches("#btnEditHeader, #btnEditPersonal")){
    e.preventDefault();
    if (PROFILE_CACHE){
      $("#user_name").value = PROFILE_CACHE.user_name || "";
      $("#email_vintti").value = PROFILE_CACHE.email_vintti || "";
      $("#role").value = PROFILE_CACHE.role || "";
      $("#emergency_contact").value = PROFILE_CACHE.emergency_contact || "";
      $("#ingreso_vintti_date").value = toInputDate(PROFILE_CACHE.ingreso_vintti_date);
      $("#fecha_nacimiento").value  = toInputDate(PROFILE_CACHE.fecha_nacimiento);
      const avatarInput = ensureAvatarField();
      if (avatarInput) avatarInput.value = PROFILE_CACHE.avatar_url || "";
    }
    showProfileEdit();
  }

  if (e.target.matches("#btnCancelEdit")){
    e.preventDefault();
    renderProfileView(PROFILE_CACHE); // restaura vista
    showProfileView();
  }
});

// Actualiza cache desde los inputs (lo guardamos crudo y que la vista lo formatee)
const _avatarFieldInit = ensureAvatarField();
PROFILE_CACHE = {
  user_id: CURRENT_USER_ID,
  user_name: $("#user_name").value.trim(),
  email_vintti: $("#email_vintti").value.trim(),
  role: $("#role").value.trim(),
  emergency_contact: $("#emergency_contact").value.trim(),
  // guardamos las fechas como las entrega el <input type="date"> (YYYY-MM-DD)
  ingreso_vintti_date: $("#ingreso_vintti_date").value || null,
  fecha_nacimiento: $("#fecha_nacimiento").value || null,
  avatar_url: (_avatarFieldInit ? _avatarFieldInit.value.trim() : "") || null,
  initials: resolveInitials($("#user_name").value.trim())
};

// Repinta tarjeta y vuelve a modo vista
renderProfileView(PROFILE_CACHE);
showProfileView();
// —— Tabla genérica al hacer click en las tarjetas de Time Off Balances —— //
function setupBalanceCardTables(){
  const container = document.getElementById("balancesTable");
  const details   = document.getElementById("balancesDetails");
  if (!container || !details) return;

  const theadRow = details.querySelector("thead tr");
  const tbody    = details.querySelector("tbody");
  if (!theadRow || !tbody) return;

  // 👉 nueva tabla de historial
  const histTable = details.querySelector("#balancesHistoryTable");
  const histBody  = histTable ? histTable.querySelector("tbody") : null;

  // usamos data-current-kind para saber qué tarjeta está abierta
  details.dataset.currentKind = details.dataset.currentKind || "";

  container.addEventListener("click", (ev) => {
    const row = ev.target.closest(".row");
    if (!row || !container.contains(row)) return;
    if (!LAST_BALANCES) return;

    const kind = row.dataset.kind; // vacation | vintti_day | holiday
    if (!kind) return;

    const current = details.dataset.currentKind || "";

    // 👉 si ya está visible y se vuelve a hacer click en la misma tarjeta, ocultamos
    if (!details.hidden && current === kind){
      details.hidden = true;
      details.dataset.currentKind = "";
      return;
    }

    let headers = [];
    let values  = [];

    if (kind === "vacation"){
      headers = [
        "Vacaciones acumuladas",
        "Vacaciones hábiles",
        "Vacaciones consumidas",     // 👈 NUEVA COLUMNA
        "Vacaciones disponibles"
      ];
      values = [
        LAST_BALANCES.vac_acc,
        LAST_BALANCES.vac_work,
        LAST_BALANCES.vac_used,      // 👈 usa vacaciones_consumidas
        LAST_BALANCES.vac_available
      ];
    } else if (kind === "vintti_day"){
      headers = [
        "Vintti Days totales",
        "Vintti Days consumidas",
        "Vintti Days disponibles"
      ];
      values = [
        LAST_BALANCES.vd_total,
        LAST_BALANCES.vd_used,
        LAST_BALANCES.vd_available
      ];
    } else if (kind === "holiday"){
      headers = [
        "Holidays totales",
        "Holidays consumidos",
        "Holidays disponibles"
      ];
      values = [
        LAST_BALANCES.hol_total,
        LAST_BALANCES.hol_used,
        LAST_BALANCES.hol_available
      ];
    }

    // rellenar head y body (3 columnas siempre)
    theadRow.innerHTML = headers.map(h => `<th>${h}</th>`).join("");
    tbody.innerHTML = `
      <tr>
        ${values.map(v => `<td>${v}</td>`).join("")}
      </tr>
    `;

    // 🔹 rellenar historial con días aprobados de ese tipo
    if (histBody){
      const kindLower = String(kind).toLowerCase();
      const approvedOfKind = (MY_REQUESTS || []).filter(r =>
        String(r.kind || "").toLowerCase() === kindLower &&
        String(r.status || "").toLowerCase() === "approved"
      );

      if (!approvedOfKind.length){
        histBody.innerHTML = `
          <tr>
            <td colspan="3">No approved ${kindLower.replace("_"," ")} days yet.</td>
          </tr>
        `;
      } else {
        const rowsHtml = approvedOfKind.map(r => {
          const startLabel = fmtDateNice(r.start_date);
          const endLabel   = fmtDateNice(r.end_date);
          const days = (kindLower === "vacation")
            ? businessDaysBetweenISO(r.start_date, r.end_date)
            : diffDaysInclusive(r.start_date, r.end_date);

          return `
            <tr>
              <td>${startLabel}</td>
              <td>${endLabel}</td>
              <td class="t-right">${days}</td>
            </tr>
          `;
        }).join("");
        histBody.innerHTML = rowsHtml;
      }
    }

    details.hidden = false;
    details.dataset.currentKind = kind;
  });
}
document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-delete-req]");
  if (!btn) return;

  const reqId = btn.getAttribute("data-delete-req");
  if (!reqId) return;

  if (!confirm("Delete this request?")) return;

  btn.disabled = true;

  try{
    const r = await api(`/time_off_requests/${encodeURIComponent(reqId)}`, {
      method: "DELETE"
    });

    if (r.status === 409) {
      alert("This request can’t be deleted anymore.");
      return;
    }
    if (!r.ok) throw new Error(await r.text());

    // Refresh table
    await loadMyRequests(CURRENT_USER_ID);
  }catch(err){
    console.error("delete request error:", err);
    alert("Could not delete request.");
  }finally{
    btn.disabled = false;
  }
});
