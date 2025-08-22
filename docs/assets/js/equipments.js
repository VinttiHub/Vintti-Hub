// ---------- config ----------
const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com"; // cambia si tu API vive en otra URL
const TABLE_IDS = {
  tbody: "equipmentsTbody",
  empty: "emptyState",
};

const statusMap = {
  nueva: { label: "New", cls: "new" },
  vieja: { label: "Used", cls: "used" },
  stockeada: { label: "Stocked", cls: "stocked" },
};
const providers = { quipteams: "Quipteams", bord: "Bord" };

// Latin America country list (English display, stored as shown)
const LATAM_COUNTRIES = [
  "Argentina","Bolivia","Brazil","Chile","Colombia","Costa Rica","Cuba",
  "Dominican Republic","Ecuador","El Salvador","Guatemala","Haiti","Honduras",
  "Mexico","Nicaragua","Panama","Paraguay","Peru","Puerto Rico","Uruguay","Venezuela"
];

// ---------- helpers ----------
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function toast(msg, ms = 2500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  setTimeout(() => (t.hidden = true), ms);
}
function fmtDate(d) {
  if (!d) return "—";
  try { return new Date(d).toLocaleDateString("en-US", {year:"numeric", month:"short", day:"2-digit"}); }
  catch { return d; }
}
function toISO(input) {
  return input ? new Date(input).toISOString().slice(0, 10) : null; // YYYY-MM-DD
}
async function fetchJSON(url, opts={}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
// small debounce
function debounce(fn, ms=250){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),ms); }; }

// tiny cache to avoid repeated lookups
const cache = {
  candidateName: new Map(),  // id -> name
  accountName: new Map(),    // id -> client_name
};

// ---------- initial boot ----------
document.addEventListener("DOMContentLoaded", () => {
  // fill countries datalist
  const dl = $("#laCountries");
  LATAM_COUNTRIES.forEach(c => {
    const o = document.createElement("option");
    o.value = c; dl.appendChild(o);
  });

  // hooks
  $("#backBtn").addEventListener("click", () => history.back());
  $("#newBtn").addEventListener("click", openModal);
  $$("#newModal [data-close]").forEach(b => b.addEventListener("click", closeModal));
  $("#newForm").addEventListener("submit", onSaveNew);

  // candidate search
  $("#candidateSearch").addEventListener("input", debounce(onCandidateType, 200));

  loadEquipments().catch(err => {
    console.error(err);
    toast("Failed to load equipments");
  });
});

// ---------- load & render table ----------
async function loadEquipments() {
  const tbody = document.getElementById(TABLE_IDS.tbody);
  tbody.innerHTML = "";

  let rows = [];
  try {
    rows = await fetchJSON(`${API_BASE}/equipments`);
  } catch (e) {
    console.warn("GET /equipments failed. If you haven't built it yet, seed with mock data.", e);
    rows = []; // keep empty gracefully
  }

  // toggle empty state
  document.getElementById(TABLE_IDS.empty).hidden = rows.length > 0;

  for (const r of rows) {
    const candName = await getCandidateName(r.candidate_id);
    const accName  = await getAccountName(r.account_id);
    const tr = document.createElement("tr");

    const status = statusMap[r.estado] || { label: r.estado || "—", cls: "" };
    const providerLabel = providers[r.proveedor] || (r.proveedor || "—");

    tr.innerHTML = `
      <td>${escapeHTML(candName || "—")}</td>
      <td>${escapeHTML(accName || "—")}</td>
      <td>${escapeHTML(providerLabel)}</td>
      <td class="compact">${fmtDate(r.pedido)}</td>
      <td class="compact">${fmtDate(r.entrega)}</td>
      <td class="compact">${fmtDate(r.retiro)}</td>
      <td class="compact">${fmtDate(r.almacenamiento)}</td>
      <td><span class="badge ${status.cls}">${escapeHTML(status.label)}</span></td>
      <td>${escapeHTML(r.pais || "—")}</td>
      <td>${r.costo != null ? Number(r.costo).toLocaleString("en-US") : "—"}</td>
      <td>${escapeHTML(r.equipos || "—")}</td>
    `;
    tbody.appendChild(tr);
  }
}

function escapeHTML(s){ return String(s).replace(/[&<>"']/g, m=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;" }[m])); }

// ---------- lookups ----------
async function getCandidateName(id){
  if(!id) return null;
  if(cache.candidateName.has(id)) return cache.candidateName.get(id);
  // try /candidates/:id
  try{
    const d = await fetchJSON(`${API_BASE}/candidates/${id}`);
    const name = d?.name || d?.full_name || null;
    cache.candidateName.set(id, name);
    return name;
  }catch(e){
    console.warn("candidate fetch failed", e);
    return null;
  }
}
async function getAccountName(id){
  if(!id) return null;
  if(cache.accountName.has(id)) return cache.accountName.get(id);
  try{
    const d = await fetchJSON(`${API_BASE}/accounts/${id}`);
    const name = d?.client_name || d?.name || null;
    cache.accountName.set(id, name);
    return name;
  }catch(e){
    console.warn("account fetch failed", e);
    return null;
  }
}

// ---------- candidate search (only those in hire_opportunity) ----------
async function onCandidateType(e){
  const q = e.target.value.trim();
  const box = $("#candidateSuggestions");
  const form = $("#newForm");
  $("#candidateId").value = "";
  $("#accountName").value = "";
  $("#accountId").value = "";

  if(q.length < 2){ box.hidden = true; box.innerHTML = ""; return; }

  // First try a backend that returns only candidates present in hire_opportunity + their active account
  // Expected response: [{candidate_id, name, account_id, account_name}]
  let results = [];
  try{
    results = await fetchJSON(`${API_BASE}/search/candidates-in-hire?q=${encodeURIComponent(q)}`);
  }catch{
    results = await fallbackSearchCandidates(q);
  }

  if(!results.length){
    box.hidden = false;
    box.innerHTML = `<div class="hint">No matches</div>`;
    return;
  }

  box.hidden = false;
  box.innerHTML = results.slice(0, 20).map(r => `
    <div class="opt" data-cid="${r.candidate_id}" data-aid="${r.account_id || ""}" data-aname="${escapeHTML(r.account_name || "")}">
      ${escapeHTML(r.name)} ${r.account_name ? `<span style="color:#64748b">— ${escapeHTML(r.account_name)}</span>` : ""}
    </div>
  `).join("");

  box.querySelectorAll(".opt").forEach(opt => {
    opt.addEventListener("click", async () => {
      const cid = Number(opt.dataset.cid);
      $("#candidateSearch").value = opt.textContent.replace(/—.*$/,"").trim();
      $("#candidateId").value = String(cid);

      let aid = opt.dataset.aid ? Number(opt.dataset.aid) : null;
      let aname = opt.dataset.aname || "";

      // If backend didn't provide account, resolve from hire_opportunity by picking the row with end_date = null
      if(!aid){
        const resolved = await resolveActiveAccountForCandidate(cid);
        aid = resolved?.account_id || null;
        aname = resolved?.account_name || "";
      }
      $("#accountId").value = aid || "";
      $("#accountName").value = aname || (aid ? (await getAccountName(aid)) : "");

      box.hidden = true; box.innerHTML = "";
    });
  });
}

// Fallback: search candidates by name, then filter/resolve through hire_opportunity
async function fallbackSearchCandidates(q){
  // Try server-side search endpoint
  let cands = [];
  try{
    cands = await fetchJSON(`${API_BASE}/candidates/search?q=${encodeURIComponent(q)}`);
  }catch{
    try{
      // as a last resort, a generic /candidates?q=
      cands = await fetchJSON(`${API_BASE}/candidates?q=${encodeURIComponent(q)}`);
    }catch{
      console.warn("No search endpoint available");
      return [];
    }
  }

  // Map & enrich with active account
  const out = [];
  for(const c of cands.slice(0, 30)){
    const cid = c.id || c.candidate_id;
    if(!cid) continue;
    const active = await resolveActiveAccountForCandidate(cid);
    if(active){ // only include if present in hire_opportunity
      out.push({ candidate_id: cid, name: c.name || c.full_name, account_id: active.account_id, account_name: active.account_name });
    }
  }
  return out;
}

async function resolveActiveAccountForCandidate(candidateId){
  try{
    const list = await fetchJSON(`${API_BASE}/hire_opportunity?candidate_id=${candidateId}`);
    if(!Array.isArray(list) || !list.length) return null;

    // Pick the row with null/empty end_date, else the most recent by end_date/start_date
    let active = list.find(r => !r.end_date || r.end_date === "null" || r.end_date === null);
    if(!active){
      active = list.slice().sort((a,b)=> new Date(b.end_date || b.start_date) - new Date(a.end_date || a.start_date))[0];
    }
    const account_id = active.account_id;
    const account_name = await getAccountName(account_id);
    return { account_id, account_name };
  }catch(e){
    console.warn("resolveActiveAccountForCandidate failed", e);
    return null;
  }
}

// ---------- modal ----------
function openModal(){
  $("#newModal").classList.add("show");
  $("#candidateSearch").focus();
}
function closeModal(){
  $("#newModal").classList.remove("show");
  // clear form
  $("#newForm").reset();
  $("#candidateSuggestions").hidden = true;
  $("#candidateSuggestions").innerHTML = "";
  $("#candidateId").value = "";
  $("#accountId").value = "";
  $("#accountName").value = "";
}

// ---------- submit ----------
async function onSaveNew(e){
  e.preventDefault();

  const candidate_id = Number($("#candidateId").value || 0);
  const account_id   = Number($("#accountId").value || 0);
  const proveedor    = $("#provider").value || null;                 // 'quipteams' | 'bord'
  const estado       = $("#status").value || null;                   // 'nueva' | 'vieja' | 'stockeada'
  const pedido       = toISO($("#orderDate").value);
  const entrega      = toISO($("#deliveryDate").value);
  const retiro       = toISO($("#pickupDate").value);
  const almacenamiento = toISO($("#storageDate").value);
  const pais         = $("#country").value || null;
  const costo        = $("#cost").value !== "" ? Number($("#cost").value) : null;
  const equipos      = $("#equipmentTxt").value || null;

  if(!candidate_id){ toast("Select a candidate"); return; }
  if(!account_id){ toast("No active account for this candidate"); return; }
  if(!proveedor){ toast("Select a provider"); return; }
  if(!estado){ toast("Select a status"); return; }

  const payload = {
    candidate_id, account_id, proveedor, pedido, entrega, retiro, almacenamiento,
    estado, pais, costo, equipos
  };

  try{
    await fetchJSON(`${API_BASE}/equipments`, {
      method:"POST",
      body: JSON.stringify(payload),
    });
    toast("Equipment saved");
    closeModal();
    await loadEquipments();
  }catch(e){
    console.error(e);
    toast("Failed to save equipment");
  }
}
