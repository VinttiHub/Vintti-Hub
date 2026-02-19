const API_BASE =
  (location.hostname === "127.0.0.1" || location.hostname === "localhost")
    ? "http://127.0.0.1:5000"
    : "https://7m6mw95m8y.us-east-2.awsapprunner.com";

(() => {
  // ✅ Ajusta si usas API_BASE en tu hub:


  const form = document.getElementById("bonusForm");
  const targetWrap = document.getElementById("targetMonthWrap");
  const invoiceTarget = form.elements["invoice_target"];

  const employeeSelect = document.getElementById("employeeSelect");
  const employeeOtherWrap = document.getElementById("employeeOtherWrap");
  const employeeNameManual = document.getElementById("employeeNameManual");

  function qs(name){
    return new URLSearchParams(window.location.search).get(name);
  }

  function fmtDate(val){
    if(!val) return "—";
    try {
      const d = new Date(val + "T00:00:00");
      return d.toLocaleDateString("en-US", { year:"numeric", month:"short", day:"2-digit" });
    } catch { return val; }
  }

  function toggleTargetMonth(){
    const isSpecific = invoiceTarget.value === "specific_month";
    targetWrap.classList.toggle("hidden", !isSpecific);
    form.elements["target_month"].required = isSpecific;
    updateReview();
  }

  function toggleEmployeeOther(){
    const isOther = employeeSelect.value === "__other__";
    employeeOtherWrap.classList.toggle("hidden", !isOther);
    employeeNameManual.required = isOther;
    if (!isOther) employeeNameManual.value = "";
    updateReview();
  }

  function updateReview(){
    const currency = form.elements["currency"].value || "";
    const amount = form.elements["amount"].value ? Number(form.elements["amount"].value).toFixed(2) : "";
    const payout = form.elements["payout_date"].value || "";
    const inv = form.elements["invoice_target"].value || "";

    const employeeLabel =
      employeeSelect.value && employeeSelect.value !== "__other__"
        ? employeeSelect.options[employeeSelect.selectedIndex]?.textContent
        : (employeeNameManual.value || "—");

    const amountText = amount ? `${currency} ${amount}` : "—";
    const rAmount = document.querySelector('[data-review="amount"]');
    const rPayout = document.querySelector('[data-review="payout_date"]');
    const rEmp   = document.querySelector('[data-review="employee_name"]');
    const rInv   = document.querySelector('[data-review="invoice_target"]');

    if (rAmount) rAmount.textContent = amountText;
    if (rPayout) rPayout.textContent = payout ? fmtDate(payout) : "—";
    if (rEmp) rEmp.textContent = employeeLabel || "—";
    if (rInv) {
      rInv.textContent =
        inv === "specific_month"
          ? `Specific month (${form.elements["target_month"].value || "—"})`
          : "Next invoice";
    }
  }

 async function loadPublicContext(){
  const token = qs("t");
  const accountId = getAccountIdFromUrl(); // si vas por account_id

  // Decide cómo vas a pedir el contexto:
  // ✅ con token:
  let url = token
    ? `${API_BASE}/public/bonus_request/context?t=${encodeURIComponent(token)}`
    : null;

  // ✅ o con account_id:
  if (!url && accountId) {
    url = `${API_BASE}/public/bonus_request/context?account_id=${encodeURIComponent(accountId)}`;
  }

  if (!url) {
    employeeSelect.innerHTML = `<option value="__other__">Other (type manually)</option>`;
    toggleEmployeeOther();
    return;
  }

  const res = await fetch(url);
  if (!res.ok) {
    employeeSelect.innerHTML = `<option value="__other__">Other (type manually)</option>`;
    toggleEmployeeOther();
    return;
  }

  const ctx = await res.json();

  console.log("CTX", ctx);
console.log("candidates length", (ctx.candidates || []).length);


  // 👇 ahora vienen como candidates
  const candidates = Array.isArray(ctx.candidates) ? ctx.candidates : [];

  employeeSelect.innerHTML = `<option value="">Select a candidate...</option>`;

  // si quieres separar “active/inactive”
  const active = candidates.filter(c => (c.status || "").toLowerCase() === "active");
  const inactive = candidates.filter(c => (c.status || "").toLowerCase() !== "active");

  const addGroup = (label, list) => {
    if (!list.length) return;
    const og = document.createElement("optgroup");
    og.label = label;
    list.forEach(c => {
      const opt = document.createElement("option");
      opt.value = String(c.candidate_id);        // 👈 ID del candidato
      opt.textContent = c.full_name;             // 👈 nombre
      og.appendChild(opt);
    });
    employeeSelect.appendChild(og);
  };

  addGroup("Active", active);
  addGroup("Inactive", inactive);

  const other = document.createElement("option");
  other.value = "__other__";
  other.textContent = "Other (type manually)";
  employeeSelect.appendChild(other);

  employeeSelect.value = "";
  toggleEmployeeOther();
}

  function getAccountIdFromUrl(){
  const p = new URLSearchParams(window.location.search);
  return p.get("account_id") || p.get("id") || null;
}

async function submitPublicRequest(){
  // 1) payload primero
  const payload = Object.fromEntries(new FormData(form).entries());

  // 2) account_id desde URL
  const accountId = getAccountIdFromUrl();
  if (!accountId) {
    alert("Missing account_id in URL. Example: bonus-form.html?account_id=32");
    return;
  }
  payload.account_id = Number(accountId);

  // 3) normalizar employee
  if (payload.employee_id && payload.employee_id !== "__other__") {
    payload.employee_name_manual = "";
  } else {
    payload.employee_id = null;
  }

  // 4) POST (sin token)
  const url = `${API_BASE}/public/bonus_request/submit`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    alert("Something went wrong. Please try again or contact billing@vintti.com.\n" + txt);
    return;
  }

  showSuccess();

  form.reset();
  toggleTargetMonth();
  // si ya no usas token, NO recargues contexto por token:
  // await loadPublicContext();
  updateReview();
}

  // events
  invoiceTarget.addEventListener("change", toggleTargetMonth);
  employeeSelect.addEventListener("change", toggleEmployeeOther);
  form.addEventListener("input", updateReview);

  const btnClear = document.getElementById("btnClear");
  if (btnClear){
    btnClear.addEventListener("click", async () => {
      form.reset();
      toggleTargetMonth();
      await loadPublicContext();
      updateReview();
    });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitPublicRequest().catch(console.error);
  });

    // ✅ Success box (hide by default)
  const successBox = document.createElement("div");
  successBox.className = "success-box hidden";
  successBox.textContent = "Bonus request submitted successfully.";
  form.prepend(successBox);

  function showSuccess(){
    successBox.classList.remove("hidden");
    setTimeout(() => successBox.classList.add("hidden"), 3500);
  }


  // init
  toggleTargetMonth();
  loadPublicContext().then(updateReview).catch(console.error);


//   function getAccountIdFromUrl(){
//   const p = new URLSearchParams(window.location.search);
//   return p.get("account_id") || p.get("id") || null;
// }

})();


