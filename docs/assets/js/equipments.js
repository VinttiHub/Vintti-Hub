// ---------- links (ajusta si tus rutas son otras) ----------
const LINKS = {
  candidate: (id) => `/candidate-details.html?id=${encodeURIComponent(id)}`,
  account:   (id) => `/account-details.html?id=${encodeURIComponent(id)}`
};

// ---------- config ----------
const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com"; // cambia si tu API vive en otra URL
const TABLE_IDS = { tbody: "equipmentsTbody", empty: "emptyState" };

// Estado visual para la badge de "estado"
const statusMap = {
  nueva: { label: "New", cls: "new" },
  vieja: { label: "Used", cls: "used" },
  stockeada: { label: "Stocked", cls: "stocked" },
};

// Proveedores soportados (para dot color)
const providers = { quipteams: "Quipteams", bord: "Bord" };

// Latin America country list (English display, stored as shown)
const LATAM_COUNTRIES = [
  "Argentina","Bolivia","Brazil","Chile","Colombia","Costa Rica","Cuba",
  "Dominican Republic","Ecuador","El Salvador","Guatemala","Haiti","Honduras",
  "Mexico","Nicaragua","Panama","Paraguay","Peru","Puerto Rico","Uruguay","Venezuela"
];

// ============================================================
// Utilities (DOM, feedback, formatting, network)
// ============================================================
const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

function toast(msg, ms = 2500) {
  const t = $("#toast");
  if (!t) return;
  t.textContent = msg;
  t.hidden = false;
  setTimeout(() => (t.hidden = true), ms);
}

function fmtDate(d) {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "2-digit" });
  } catch {
    return d;
  }
}

// Convierte a YYYY-MM-DD (para payloads), null si vacío
function toISO(input) {
  return input ? new Date(input).toISOString().slice(0, 10) : null;
}

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  // Maneja respuestas vacías con 204
  if (res.status === 204) return null;
  return res.json();
}

function debounce(fn, ms = 250) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, m => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[m]));
}

// Pequeño caché para evitar lookups repetidos
const cache = {
  candidateName: new Map(),  // id -> name
  accountName:   new Map(),  // id -> client_name
};

// ============================================================
// Data mapping & visuals
// ============================================================
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

const emojiFor = (v) => (EQUIPMENT_OPTIONS.find(o => o.value.toLowerCase() === String(v).toLowerCase())?.emoji || "📦");

// Normaliza texto/JSON/array a array de strings no vacíos
function parseEquipos(raw) {
  if (!raw) return [];
  if (Array.isArray(raw)) return raw.map(String).filter(Boolean);
  const s = String(raw).trim();
  try { const j = JSON.parse(s); if (Array.isArray(j)) return j.map(String).filter(Boolean); } catch {}
  return s.split(",").map(x => x.trim()).filter(Boolean);
}

// País -> bandera
const COUNTRY_FLAGS = {
  "Argentina":"🇦🇷","Bolivia":"🇧🇴","Brazil":"🇧🇷","Chile":"🇨🇱","Colombia":"🇨🇴",
  "Costa Rica":"🇨🇷","Cuba":"🇨🇺","Dominican Republic":"🇩🇴","Ecuador":"🇪🇨",
  "El Salvador":"🇸🇻","Guatemala":"🇬🇹","Haiti":"🇭🇹","Honduras":"🇭🇳",
  "Mexico":"🇲🇽","Nicaragua":"🇳🇮","Panama":"🇵🇦","Paraguay":"🇵🇾","Peru":"🇵🇪",
  "Puerto Rico":"🇵🇷","Uruguay":"🇺🇾","Venezuela":"🇻🇪"
};
function flagEmoji(country){ return COUNTRY_FLAGS[country] || ""; }

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

function providerDotClass(p){ return (p === "quipteams" || p === "bord") ? p : ""; }

function dateCell(d, icon){
  if (!d) return "—";
  return `<span class="cell-ico">${icon}</span><span class="date-txt">${fmtDate(d)}</span>`;
}

// Helpers para IDs/fechas en inputs
const getEquipmentId = (obj) => obj?.equipment_id ?? obj?.id ?? obj?.equipmentId ?? null;
const normalizeDateForInput = (v) => {
  if (!v) return "";
  if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}/.test(v)) return v.slice(0, 10);
  const d = new Date(v);
  return isNaN(d) ? "" : d.toISOString().slice(0, 10);
};

// ============================================================
// Multi-select (equipos)
// ============================================================
function createMultiSelect(initial = []) {
  const root = document.createElement("div");
  root.className = "ms-root";
  root.tabIndex = 0;

  const state = new Set(initial);

  const input = document.createElement("input");
  input.className = "ms-input";
  input.placeholder = state.size ? "" : "Select equipment…";

  const dd = document.createElement("div");
  dd.className = "ms-dd";
  dd.hidden = true;

  function renderChips() {
    [...root.querySelectorAll(".ms-chip,.ms-plus")].forEach(n => n.remove());
    const items = [...state];
    items.forEach(v => {
      const chip = document.createElement("span");
      chip.className = "ms-chip";
      chip.innerHTML = `<span class="e">${emojiFor(v)}</span><span class="t">${v}</span><span class="x" aria-label="remove">✕</span>`;
      chip.querySelector(".x").addEventListener("click", (e) => {
        e.stopPropagation();
        state.delete(v);
        renderChips(); renderDD();
        root.dispatchEvent(new CustomEvent("change"));
      });
      root.insertBefore(chip, input);
    });
    if (items.length === 0) {
      const hint = document.createElement("span");
      hint.className = "ms-plus";
      hint.textContent = "Select equipment…";
      root.insertBefore(hint, input);
    }
  }

  function renderDD() {
    dd.innerHTML = "";
    EQUIPMENT_OPTIONS.forEach(opt => {
      const row = document.createElement("div");
      row.className = "ms-opt";
      row.innerHTML = `<span class="ms-emoji">${opt.emoji}</span><span>${opt.value}</span><input type="checkbox" ${state.has(opt.value) ? "checked" : ""} style="margin-left:auto">`;
      row.addEventListener("click", () => {
        if (state.has(opt.value)) state.delete(opt.value); else state.add(opt.value);
        renderChips(); renderDD();
        root.dispatchEvent(new CustomEvent("change"));
      });
      dd.appendChild(row);
    });
  }

  function open(){ dd.hidden = false; renderDD(); }
  function close(){ dd.hidden = true; }

  root.addEventListener("click", () => open());
  input.addEventListener("focus", () => open());
  document.addEventListener("click", (e) => { if (!root.contains(e.target)) close(); });

  root.appendChild(input);
  root.appendChild(dd);
  renderChips();

  // API pública
  root.getValues = () => [...state];
  root.setValues = (arr = []) => { state.clear(); arr.forEach(v => state.add(v)); renderChips(); renderDD(); };
  return root;
}

function inputEquipmentMulti(value) {
  const selected = parseEquipos(value);
  const root = createMultiSelect(selected);
  root.dataset.ms = "equipos"; // para detection en payloadFromEditRow
  return root;
}

// ============================================================
// Boot (DOMContentLoaded)
// ============================================================
document.addEventListener("DOMContentLoaded", () => {
  // datalist de países (reutilizado en modal y edición en línea)
  const dl = $("#laCountries");
  if (dl && !dl.dataset.filled) {
    const frag = document.createDocumentFragment();
    LATAM_COUNTRIES.forEach(c => { const o = document.createElement("option"); o.value = c; frag.appendChild(o); });
    dl.appendChild(frag);
    dl.dataset.filled = "1";
  }

  // hooks modal
  $("#backBtn")?.addEventListener("click", () => history.back());
  $("#newBtn")?.addEventListener("click", openModal);
  $$("#newModal [data-close]").forEach(b => b.addEventListener("click", closeModal));
  $("#newForm")?.addEventListener("submit", onSaveNew);

  // candidate search (solo modal)
  $("#candidateSearch")?.addEventListener("input", debounce(onCandidateType, 200));

  // render inicial de tabla
  loadEquipments().catch(err => {
    console.error(err);
    toast("Failed to load equipments");
  });

  // montar multiselect en el modal (si existe)
  const msMount = document.getElementById("equipmentMulti");
  if (msMount && !msMount.dataset.ready) {
    const ms = createMultiSelect([]);
    ms.id = "equipmentMultiInner";
    msMount.appendChild(ms);
    msMount.dataset.ready = "1";
  }
});

// ============================================================
// Load & render table
// ============================================================
async function loadEquipments() {
  const tbody = document.getElementById(TABLE_IDS.tbody);
  if (!tbody) return;
  tbody.innerHTML = "";

  let rows = [];
  try {
    rows = await fetchJSON(`${API_BASE}/equipments`) || [];
  } catch (e) {
    console.warn("GET /equipments failed", e);
    rows = [];
  }

  const emptyEl = document.getElementById(TABLE_IDS.empty);
  if (emptyEl) emptyEl.hidden = rows.length > 0;

  for (const r of rows) {
    const tr = await renderRow(r);
    tbody.appendChild(tr);
  }
}

async function renderRow(r) {
  const tr = document.createElement("tr");
  tr.dataset.id = r.equipment_id ?? "";
  tr.dataset.status = r.estado || "";

  // fetch name lookups en paralelo
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

  const status        = statusMap[r.estado] || { label: r.estado || "—", cls: "" };
  const providerLabel = providers[r.proveedor] || (r.proveedor || "—");
  const costCls       = costGrade(r.costo);
  const flag          = flagEmoji(r.pais);
  const eqArr         = parseEquipos(r.equipos);

  const eqHtml = (() => {
    if (!eqArr.length) return "—";
    const shown = eqArr.slice(0, 3);
    const more = eqArr.length - shown.length;
    const pills = shown.map(v => `<span class="eq-pill"><span>${emojiFor(v)}</span><span>${escapeHTML(v)}</span></span>`).join("");
    return `<div class="eq-list">${pills}${more > 0 ? `<span class=\"eq-pill eq-more\">+${more}</span>` : ""}</div>`;
  })();

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

    <td data-col="equipos">${eqHtml}</td>

    <td class="actions">
      <button class="btn ghost sm" data-edit aria-label="Edit">✎ Edit</button>
      <button class="btn danger sm" data-del aria-label="Delete">🗑 Delete</button>
    </td>
  `;

  tr.querySelector("[data-edit]").addEventListener("click", () => enterEditMode(tr, r));
  tr.querySelector("[data-del]").addEventListener("click", () => onDeleteEquipment(r.equipment_id));
  return tr;
}

// ============================================================
// Edit mode inputs
// ============================================================
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

function enterEditMode(tr, r) {
  if (tr.dataset.editing === "1") return;
  tr.dataset.editing = "1";

  const cells = {
    pedido:          inputDate(r.pedido),
    entrega:         inputDate(r.entrega),
    retiro:          inputDate(r.retiro),
    almacenamiento:  inputDate(r.almacenamiento),
    estado:          inputSelectStatus(r.estado),
    pais:            inputCountry(r.pais),
    costo:           inputNumber(r.costo),
    equipos:         inputEquipmentMulti(r.equipos),
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
  const get = (col) => tr.querySelector(`[data-col="${col}"] input, [data-col="${col}"] select, [data-col="${col}"] .ms-root`);

  const pedido          = toISO(get("pedido")?.value);
  const entrega         = toISO(get("entrega")?.value);
  const retiro          = toISO(get("retiro")?.value);
  const almacenamiento  = toISO(get("almacenamiento")?.value);
  const estado          = get("estado")?.value || null;
  const pais            = (get("pais")?.value || "").trim() || null;
  const costoRaw        = get("costo")?.value;
  const costo           = (costoRaw === "" || costoRaw == null) ? null : Number(costoRaw);

  let equipos = null;
  const eqNode = get("equipos");
  if (eqNode?.dataset?.ms === "equipos") {
    equipos = eqNode.getValues(); // array
  } else {
    const txt = (eqNode?.value || "").trim();
    equipos = txt ? parseEquipos(txt) : null; // array o null
  }
  return { pedido, entrega, retiro, almacenamiento, estado, pais, costo, equipos };
}

async function updateEquipment(id, payload){
  return fetchJSON(`${API_BASE}/equipments/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
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

// ============================================================
// Lookups (candidates / accounts) con caching
// ============================================================
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

// ============================================================
// Candidate search (modal) con fallback
// ============================================================
async function onCandidateType(e){
  const q = e.target.value.trim();
  const box  = $("#candidateSuggestions");
  if (!box) return;

  $("#candidateId").value = "";
  $("#accountName").value = "";
  $("#accountId").value = "";

  if(q.length < 2){ box.hidden = true; box.innerHTML = ""; return; }

  let results = [];
  try{
    results = await fetchJSON(`${API_BASE}/search/candidates-in-hire?q=${encodeURIComponent(q)}`) || [];
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
    cands = await fetchJSON(`${API_BASE}/candidates/search?q=${encodeURIComponent(q)}`) || [];
  }catch{
    try{
      cands = await fetchJSON(`${API_BASE}/candidates?q=${encodeURIComponent(q)}`) || [];
    }catch{
      console.warn("No search endpoint available");
      return [];
    }
  }

  // Resolver cuentas activas en paralelo para performance
  const limited = cands.slice(0, 30);
  const resolved = await Promise.all(limited.map(async (c) => {
    const cid = c.id || c.candidate_id;
    if(!cid) return null;
    const active = await resolveActiveAccountForCandidate(cid);
    if(!active) return null;
    return { candidate_id: cid, name: c.name || c.full_name, account_id: active.account_id, account_name: active.account_name };
  }));

  return resolved.filter(Boolean);
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

// ============================================================
// Modal (crear nuevo)
// ============================================================
function openModal(){
  $("#newModal").classList.add("show");
  $("#candidateSearch").focus();
}

function closeModal(){
  $("#newModal").classList.remove("show");
  $("#newForm")?.reset();
  const box = $("#candidateSuggestions");
  if (box){ box.hidden = true; box.innerHTML = ""; }
  $("#candidateId").value = "";
  $("#accountId").value = "";
  $("#accountName").value = "";
}

async function onSaveNew(e){
  e.preventDefault();

  const candidate_id  = Number($("#candidateId").value || 0);
  const account_id    = Number($("#accountId").value || 0);
  const proveedor     = $("#provider").value || null;                 // 'quipteams' | 'bord'
  const estado        = $("#status").value || null;                   // 'nueva' | 'vieja' | 'stockeada'
  const pedido        = toISO($("#orderDate").value);
  const entrega       = toISO($("#deliveryDate").value);
  const retiro        = toISO($("#pickupDate").value);
  const almacenamiento= toISO($("#storageDate").value);
  const pais          = $("#country").value || null;
  const costo         = $("#cost").value !== "" ? Number($("#cost").value) : null;

  const ms = document.querySelector("#equipmentMulti .ms-root") || document.getElementById("equipmentMultiInner");
  const equipos = ms ? ms.getValues() : parseEquipos($("#equipmentTxt").value || "");

  if(!candidate_id){ toast("Select a candidate"); return; }
  if(!account_id){ toast("No active account for this candidate"); return; }
  if(!proveedor){ toast("Select a provider"); return; }
  if(!estado){ toast("Select a status"); return; }

  const payload = { candidate_id, account_id, proveedor, pedido, entrega, retiro, almacenamiento, estado, pais, costo, equipos };

  try{
    await fetchJSON(`${API_BASE}/equipments`, { method: "POST", body: JSON.stringify(payload) });
    toast("Equipment saved");
    closeModal();
    await loadEquipments();
  }catch(e){
    console.error(e);
    toast("Failed to save equipment");
  }
}
