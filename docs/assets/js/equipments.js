// ---------- links (ajusta si tus rutas son otras) ----------
const LINKS = {
  candidate: (id) => `/candidate-details.html?id=${encodeURIComponent(id)}`,
  account:   (id) => `/crm/account-details.html?id=${encodeURIComponent(id)}`
};

// ---------- config ----------
const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com"; // cambia si tu API vive en otra URL
const TABLE_IDS = { tbody: "equipmentsTbody", empty: "emptyState" };

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
function debounce(fn, ms=250){ let t; return (...a)=>{ clearTimeout(t); t=setTimeout(()=>fn(...a),ms); }; }
function escapeHTML(s){ return String(s).replace(/[&<>"']/g, m=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;" }[m])); }

// tiny cache to avoid repeated lookups
const cache = {
  candidateName: new Map(),  // id -> name
  accountName: new Map(),    // id -> client_name
};

// ---------- initial boot ----------
document.addEventListener("DOMContentLoaded", () => {
  // fill countries datalist (reutilizado para modal y edición en línea)
  const dl = $("#laCountries");
  if (dl && !dl.dataset.filled) {
    LATAM_COUNTRIES.forEach(c => {
      const o = document.createElement("option");
      o.value = c; dl.appendChild(o);
    });
    dl.dataset.filled = "1";
  }

  // hooks modal
  $("#backBtn")?.addEventListener("click", () => history.back());
  $("#newBtn")?.addEventListener("click", openModal);
  $$("#newModal [data-close]").forEach(b => b.addEventListener("click", closeModal));
  $("#newForm")?.addEventListener("submit", onSaveNew);

  // candidate search
  $("#candidateSearch")?.addEventListener("input", debounce(onCandidateType, 200));

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
    console.warn("GET /equipments failed", e);
    rows = [];
  }

  document.getElementById(TABLE_IDS.empty).hidden = rows.length > 0;

  for (const r of rows) {
    const tr = await renderRow(r);
    tbody.appendChild(tr);
  }
}

async function renderRow(r) {
  const tr = document.createElement("tr");
  tr.dataset.id = r.equipment_id ?? "";
  tr.dataset.status = r.estado || "";

  // ✅ fetch both in parallel to avoid TDZ + speed up
  const [candName, accName] = await Promise.all([
    getCandidateName(r.candidate_id),
    getAccountName(r.account_id),
  ]);

  const candCell = (r.candidate_id && candName)
    ? `<a class="cell-link" href="${LINKS.candidate(r.candidate_id)}" data-candidate-id="${r.candidate_id}">${escapeHTML(candName)}</a>`
    : "—";

  const accCell = (r.account_id && accName)
    ? `<a class="cell-link" href="${LINKS.account(r.account_id)}" data-account-id="${r.account_id}">${escapeHTML(accName)}</a>`
    : "—";

  const status         = statusMap[r.estado] || { label: r.estado || "—", cls: "" };
  const providerLabel  = providers[r.proveedor] || (r.proveedor || "—");
  const costCls        = costGrade(r.costo);
  const equipEmoji     = equipmentEmoji(r.equipos);
  const flag           = flagEmoji(r.pais);

  tr.innerHTML = `
    <td data-col="candidate">${candCell}</td>
    <td data-col="account">${accCell}</td>

    <td data-col="provider">
      <span class="inline-cell">
        <span class="dot ${providerDotClass(r.proveedor)}"></span>
        <span>${escapeHTML(providerLabel)}</span>
      </span>
    </td>

    <td data-col="pedido" class="compact">${dateCell(r.pedido, "🛒")}</td>
    <td data-col="entrega" class="compact">${dateCell(r.entrega, "📦")}</td>
    <td data-col="retiro" class="compact">${dateCell(r.retiro, "📤")}</td>
    <td data-col="almacenamiento" class="compact">${dateCell(r.almacenamiento, "🏬")}</td>

    <td data-col="estado"><span class="badge ${status.cls}">${escapeHTML(status.label)}</span></td>

    <td data-col="pais">
      <span class="inline-cell">
        ${flag ? `<span class="flag">${flag}</span>` : ""}
        <span>${escapeHTML(r.pais || "—")}</span>
      </span>
    </td>

    <td data-col="costo" class="compact">
      <span class="cost ${costCls}">${fmtCurrency(r.costo)}</span>
    </td>

    <td data-col="equipos">
      ${r.equipos ? `<span class="inline-cell"><span class="eq-emoji">${equipEmoji}</span><span>${escapeHTML(r.equipos)}</span></span>` : "—"}
    </td>

    <td class="actions">
      <button class="btn ghost sm" data-edit aria-label="Edit">✎ Edit</button>
      <button class="btn danger sm" data-del aria-label="Delete">🗑 Delete</button>
    </td>
  `;

  tr.querySelector("[data-edit]").addEventListener("click", () => enterEditMode(tr, r));
  tr.querySelector("[data-del]").addEventListener("click", () => onDeleteEquipment(r.equipment_id));
  return tr;
}


// --- inputs de edición: prellenar fechas correctamente
function inputDate(value) {
  const el = document.createElement("input");
  el.type = "date";
  el.value = normalizeDateForInput(value);
  return el;
}
function inputSelectStatus(value) {
  const el = document.createElement("select");
  el.innerHTML = `
    <option value="nueva">New</option>
    <option value="vieja">Used</option>
    <option value="stockeada">Stocked</option>
  `;
  el.value = value || "";
  return el;
}
function inputCountry(value) {
  const el = document.createElement("input");
  el.setAttribute("list", "laCountries");
  el.value = value || "";
  el.placeholder = "Type…";
  return el;
}
function inputNumber(value) {
  const el = document.createElement("input");
  el.type = "number";
  el.step = "1";
  el.min = "0";
  el.placeholder = "0";
  el.value = value ?? "";
  return el;
}
function inputText(value) {
  const el = document.createElement("input");
  el.type = "text";
  el.value = value || "";
  el.placeholder = "e.g., Laptop, Monitor";
  return el;
}

// --- enterEditMode: toma el id de la fila (no del objeto r)
function enterEditMode(tr, r) {
  if (tr.dataset.editing === "1") return;
  tr.dataset.editing = "1";

  const cells = {
    pedido: inputDate(r.pedido),
    entrega: inputDate(r.entrega),
    retiro: inputDate(r.retiro),
    almacenamiento: inputDate(r.almacenamiento),
    estado: inputSelectStatus(r.estado),
    pais: inputCountry(r.pais),
    costo: inputNumber(r.costo),
    equipos: inputText(r.equipos),
  };

  Object.entries(cells).forEach(([col, el]) => {
    const td = tr.querySelector(`[data-col="${col}"]`);
    if (td) { td.innerHTML = ""; td.appendChild(el); }
  });

  const act = tr.querySelector(".actions");
  act.innerHTML = `
    <button class="btn primary sm" data-save>Save</button>
    <button class="btn ghost sm" data-cancel>Cancel</button>
  `;

  const id = tr.dataset.id || getEquipmentId(r);

  act.querySelector("[data-save]").addEventListener("click", async () => {
    try {
      if (!id || id === "null" || id === "undefined") throw new Error("Missing equipment_id");
      const payload = payloadFromEditRow(tr);
      await updateEquipment(id, payload);
      toast("Equipment updated");
      const fresh = await fetchJSON(`${API_BASE}/equipments/${id}`);
      const newTr = await renderRow(fresh);
      tr.replaceWith(newTr);
    } catch (e) {
      console.error(e);
      toast("Failed to update");
    }
  });

  act.querySelector("[data-cancel]").addEventListener("click", async () => {
    const fresh = await fetchJSON(`${API_BASE}/equipments/${id}`);
    const newTr = await renderRow(fresh);
    tr.replaceWith(newTr);
  });
}

function payloadFromEditRow(tr) {
  const get = (col) => tr.querySelector(`[data-col="${col}"] input, [data-col="${col}"] select`);

  const pedido = toISO(get("pedido")?.value);
  const entrega = toISO(get("entrega")?.value);
  const retiro = toISO(get("retiro")?.value);
  const almacenamiento = toISO(get("almacenamiento")?.value);
  const estado = get("estado")?.value || null;
  const pais = (get("pais")?.value || "").trim() || null;
  const costoRaw = get("costo")?.value;
  const costo = (costoRaw === "" || costoRaw == null) ? null : Number(costoRaw);
  const equipos = (get("equipos")?.value || "").trim() || null;

  return { pedido, entrega, retiro, almacenamiento, estado, pais, costo, equipos };
}

async function updateEquipment(id, payload){
  // Enviar solo campos de edición
  return fetchJSON(`${API_BASE}/equipments/${id}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

async function onDeleteEquipment(id){
  if (!id) return;
  const ok = confirm("Delete this equipment entry? This cannot be undone.");
  if (!ok) return;
  try{
    await fetchJSON(`${API_BASE}/equipments/${id}`, { method: "DELETE" });
    toast("Deleted");
    await loadEquipments();
  }catch(e){
    console.error(e);
    toast("Failed to delete");
  }
}

// ---------- lookups ----------
async function getCandidateName(id){
  if(!id) return null;
  if(cache.candidateName.has(id)) return cache.candidateName.get(id);
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

// ---------- candidate search (solo en modal) ----------
async function onCandidateType(e){
  const q = e.target.value.trim();
  const box = $("#candidateSuggestions");
  const form = $("#newForm");
  $("#candidateId").value = "";
  $("#accountName").value = "";
  $("#accountId").value = "";

  if(q.length < 2){ box.hidden = true; box.innerHTML = ""; return; }

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

async function fallbackSearchCandidates(q){
  let cands = [];
  try{
    cands = await fetchJSON(`${API_BASE}/candidates/search?q=${encodeURIComponent(q)}`);
  }catch{
    try{
      cands = await fetchJSON(`${API_BASE}/candidates?q=${encodeURIComponent(q)}`);
    }catch{
      console.warn("No search endpoint available");
      return [];
    }
  }

  const out = [];
  for(const c of cands.slice(0, 30)){
    const cid = c.id || c.candidate_id;
    if(!cid) continue;
    const active = await resolveActiveAccountForCandidate(cid);
    if(active){
      out.push({ candidate_id: cid, name: c.name || c.full_name, account_id: active.account_id, account_name: active.account_name });
    }
  }
  return out;
}

async function resolveActiveAccountForCandidate(candidateId){
  try{
    const list = await fetchJSON(`${API_BASE}/hire_opportunity?candidate_id=${candidateId}`);
    if(!Array.isArray(list) || !list.length) return null;

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

// ---------- modal (crear nuevo) ----------
function openModal(){
  $("#newModal").classList.add("show");
  $("#candidateSearch").focus();
}
function closeModal(){
  $("#newModal").classList.remove("show");
  $("#newForm").reset();
  $("#candidateSuggestions").hidden = true;
  $("#candidateSuggestions").innerHTML = "";
  $("#candidateId").value = "";
  $("#accountId").value = "";
  $("#accountName").value = "";
}
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
function fmtCurrency(n){
  if (n == null || n === "") return "—";
  try { return new Intl.NumberFormat("en-US", { style:"currency", currency:"USD", maximumFractionDigits:0 }).format(Number(n)); }
  catch { return `$${Number(n).toLocaleString("en-US")}`; }
}
function costGrade(n){
  if (n == null) return "mid";
  const v = Number(n);
  if (v < 1000) return "low";
  if (v > 3000) return "high";
  return "mid";
}
const COUNTRY_FLAGS = {
  "Argentina":"🇦🇷","Bolivia":"🇧🇴","Brazil":"🇧🇷","Chile":"🇨🇱","Colombia":"🇨🇴",
  "Costa Rica":"🇨🇷","Cuba":"🇨🇺","Dominican Republic":"🇩🇴","Ecuador":"🇪🇨",
  "El Salvador":"🇸🇻","Guatemala":"🇬🇹","Haiti":"🇭🇹","Honduras":"🇭🇳",
  "Mexico":"🇲🇽","Nicaragua":"🇳🇮","Panama":"🇵🇦","Paraguay":"🇵🇾","Peru":"🇵🇪",
  "Puerto Rico":"🇵🇷","Uruguay":"🇺🇾","Venezuela":"🇻🇪"
};
function flagEmoji(country){ return COUNTRY_FLAGS[country] || ""; }

function equipmentEmoji(txt=""){
  const s = (txt||"").toLowerCase();
  if (s.includes("laptop") || s.includes("notebook")) return "💻";
  if (s.includes("monitor") || s.includes("screen"))   return "🖥️";
  if (s.includes("mouse"))                              return "🖱️";
  if (s.includes("keyboard"))                           return "⌨️";
  if (s.includes("headset") || s.includes("audif"))     return "🎧";
  if (s.includes("phone") || s.includes("mobile"))      return "📱";
  if (s.includes("tablet") || s.includes("ipad"))       return "📱";
  if (s.includes("dock") || s.includes("hub"))          return "🧩";
  if (s.includes("router") || s.includes("modem"))      return "📶";
  if (s.includes("chair") || s.includes("silla"))       return "💺";
  return "📦";
}
function providerDotClass(p){ return (p === "quipteams" || p === "bord") ? p : ""; }

function dateCell(d, icon){
  if (!d) return "—";
  return `<span class="cell-ico">${icon}</span><span class="date-txt">${fmtDate(d)}</span>`;
}
// --- helpers nuevos arriba del archivo ---
const getEquipmentId = (obj) => obj?.equipment_id ?? obj?.id ?? obj?.equipmentId ?? null;

const normalizeDateForInput = (v) => {
  if (!v) return "";
  // si ya viene YYYY-MM-DD, úsalo tal cual
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return v.slice(0, 10);
  const d = new Date(v);
  return isNaN(d) ? "" : d.toISOString().slice(0, 10);
};

