const API_BASE =
  (location.hostname === "127.0.0.1" || location.hostname === "localhost")
    ? "http://127.0.0.1:5000"
    : "https://7m6mw95m8y.us-east-2.awsapprunner.com";

(() => {
  const form = document.getElementById("billingForm");
  const emailInput = document.getElementById("billingEmailInput");
  const emailHint = document.getElementById("billingEmailHint");
  const btnSubmit = document.getElementById("btnSubmit");
  const btnClear = document.getElementById("btnClear");
  const errorBox = document.getElementById("formError");

  // Se completa desde /context y es lo unico que se vuelve a poner al limpiar.
  let currentBillingEmail = "";

  function qs(name){
    return new URLSearchParams(window.location.search).get(name);
  }

  function getAccountIdFromUrl(){
    return qs("account_id") || qs("id") || null;
  }

  function showError(message){
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
  }

  function clearError(){
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  // Sin cuenta valida no tiene sentido dejar enviar: el bonus form de hoy deja
  // mandar igual y falla recien en el submit con un alert crudo.
  function disableForm(message){
    showError(message);
    btnSubmit.disabled = true;
    emailInput.disabled = true;
  }

  function setField(key, value){
    const row = document.querySelector(`[data-row="${key}"]`);
    const target = document.querySelector(`[data-field="${key}"]`);
    const clean = (value || "").trim();
    if (!row || !target) return;
    // Un campo vacio se esconde: mostrar "—" haria ver el formulario a medio llenar.
    if (!clean){
      row.classList.add("hidden");
      return;
    }
    target.textContent = clean;
    row.classList.remove("hidden");
  }

  function applyCurrentEmail(){
    if (!currentBillingEmail) return;
    emailInput.value = currentBillingEmail;
    emailHint.textContent =
      `We currently have ${currentBillingEmail} on file. Submitting will replace it.`;
    emailHint.classList.add("replacing");
  }

  async function loadPublicContext(){
    const accountId = getAccountIdFromUrl();
    if (!accountId){
      disableForm("This link is missing the account it belongs to. Please use the link Vintti sent you, or contact finance@vintti.com.");
      return;
    }

    let res;
    try {
      res = await fetch(`${API_BASE}/public/billing_email/context?account_id=${encodeURIComponent(accountId)}`);
    } catch {
      disableForm("We couldn't load your account details. Please check your connection and reload the page.");
      return;
    }

    if (res.status === 404){
      disableForm("We couldn't find this account. Please contact finance@vintti.com.");
      return;
    }
    if (!res.ok){
      disableForm("We couldn't load your account details. Please reload the page or contact finance@vintti.com.");
      return;
    }

    const ctx = await res.json();
    clearError();

    setField("client_name", ctx.client_name);
    setField("contact_name", ctx.contact_name);
    setField("contact_mail", ctx.contact_mail);
    setField("state", ctx.state);
    setField("industry", ctx.industry);
    setField("contract", ctx.contract);

    currentBillingEmail = (ctx.billing_email || "").trim();
    applyCurrentEmail();
  }

  async function submitBillingEmail(){
    const accountId = getAccountIdFromUrl();
    if (!accountId) return;

    const payload = {
      account_id: Number(accountId),
      billing_email: (emailInput.value || "").trim(),
    };

    btnSubmit.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/public/billing_email/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok){
        const body = await res.json().catch(() => ({}));
        showError(body.error || "Something went wrong. Please try again or contact finance@vintti.com.");
        return;
      }

      clearError();
      currentBillingEmail = payload.billing_email;
      showSuccess();
      applyCurrentEmail();
    } catch {
      showError("Something went wrong. Please try again or contact finance@vintti.com.");
    } finally {
      btnSubmit.disabled = false;
    }
  }

  // events
  if (btnClear){
    btnClear.addEventListener("click", () => {
      form.reset();
      clearError();
      applyCurrentEmail();
    });
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    submitBillingEmail().catch(console.error);
  });

  // Success box (hide by default)
  const successBox = document.createElement("div");
  successBox.className = "success-box hidden";
  successBox.textContent = "Thank you! Your billing email was saved.";
  form.prepend(successBox);

  function showSuccess(){
    successBox.classList.remove("hidden");
    setTimeout(() => successBox.classList.add("hidden"), 3500);
  }

  // init
  loadPublicContext().catch(console.error);
})();
