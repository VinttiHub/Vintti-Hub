/* =====================================================================
   Vintti — public job application page (Hirex Slice 5)

   Reads ?t=<public_token>, renders the role + the form the recruiter
   configured in Hirex, and posts the application as multipart/form-data.
   No auth: the token IS the credential.

   ?src=linkedin (or any value) is stored on the application, so the same
   job can be posted in several places and still be attributed correctly.
   ===================================================================== */
(function () {
  "use strict";

  const API_BASE = window.HIREX_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1")
      ? "http://localhost:5000"
      : "https://7m6mw95m8y.us-east-2.awsapprunner.com");

  const params = new URLSearchParams(location.search);
  const token = (params.get("t") || "").trim();
  const src = (params.get("src") || "").trim();

  // How each standard field is presented. The server decides WHICH fields appear
  // (required/optional/off) and which are dropdowns; this only adds the hints.
  const FIELD_UI = {
    first_name:      { placeholder: "Jane", autocomplete: "given-name" },
    last_name:       { placeholder: "Doe", autocomplete: "family-name" },
    email:           { placeholder: "jane@email.com", autocomplete: "email" },
    phone:           { placeholder: "+54 11 5555 5555", autocomplete: "tel" },
    country:         { prompt: "Select your location", autocomplete: "country-name" },
    role_position:   { placeholder: "Sales & Marketing Assistant" },
    area:            { placeholder: "Marketing" },
    english_level:   { prompt: "What's your English level?" },
    found_via:       { prompt: "Select an option" },
    linkedin:        { placeholder: "linkedin.com/in/janedoe" },
    current_company: { placeholder: "Acme Inc." },
    desired_salary:  { placeholder: "USD 4,000 / month" },
  };

  const MAX_CV_BYTES = 8 * 1024 * 1024;
  const CV_EXTS = ["pdf", "doc", "docx"];

  const $ = (id) => document.getElementById(id);
  let els = {};
  let job = null;
  let cvFile = null;

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els = {
      loading: $("vapLoading"), gone: $("vapGone"), goneTitle: $("vapGoneTitle"),
      goneText: $("vapGoneText"), main: $("vapMain"),
      title: $("vapTitle"), dept: $("vapDept"), spec: $("vapSpec"), jd: $("vapJd"),
      form: $("vapForm"), fields: $("vapFields"), questions: $("vapQuestions"),
      formErr: $("vapFormErr"), submit: $("vapSubmit"),
      done: $("vapDone"), doneRole: $("vapDoneRole"),
    };
    if (!token) return showGone("This link isn't complete",
      "The address is missing its job code. Ask whoever shared it for the full link.");

    els.form.addEventListener("submit", onSubmit);
    loadJob();
  }

  // --- Load ----------------------------------------------------------------
  async function loadJob() {
    try {
      const res = await fetch(`${API_BASE}/public/hirex/jobs/${encodeURIComponent(token)}`);
      if (res.status === 410) {
        const body = await res.json().catch(() => ({}));
        return showGone("This role is closed",
          body.title ? `${body.title} isn't accepting applications anymore.`
                     : "This role isn't accepting applications anymore.");
      }
      if (!res.ok) throw new Error();
      job = await res.json();
      render();
    } catch {
      showGone("This link isn't active",
        "The role may have been filled or the link may be incomplete. If someone sent you this link, ask them for the current one.");
    }
  }

  function showGone(title, text) {
    els.loading.hidden = true;
    els.goneTitle.textContent = title;
    els.goneText.textContent = text;
    els.gone.hidden = false;
  }

  // --- Render ---------------------------------------------------------------
  function render() {
    document.title = `${job.title} · Apply · Vintti`;
    els.title.textContent = job.title;
    if (job.department) { els.dept.textContent = job.department; els.dept.hidden = false; }

    const specs = [
      ["Work mode", pretty(job.work_mode)],
      ["Type", pretty(job.employment_type)],
      ["Seniority", pretty(job.seniority)],
      ["Location", job.location],
      ["Language", job.language],
    ].filter(([, v]) => v);
    els.spec.innerHTML = specs
      .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
      .join("");

    let jd = "";
    if (job.description)  jd += `<h2>About the role</h2><p>${esc(job.description)}</p>`;
    if (job.requirements) jd += `<h2>What we're looking for</h2><p>${esc(job.requirements)}</p>`;
    if (job.benefits)     jd += `<h2>What's on offer</h2><p>${esc(job.benefits)}</p>`;
    if (Array.isArray(job.skills) && job.skills.length) {
      jd += `<h2>Skills</h2><div class="vap-skills">` +
        job.skills.map((s) => `<span class="vap-skill">${esc(s)}</span>`).join("") + `</div>`;
    }
    els.jd.innerHTML = jd || `<p>${esc("Full details are in the original job post.")}</p>`;

    renderFields();
    renderQuestions();
    els.loading.hidden = true;
    els.main.hidden = false;
  }

  function renderFields() {
    const modes = job.form || {};
    els.fields.innerHTML = "";
    (job.fields || []).forEach((f) => {
      const mode = modes[f.key] || "off";
      if (mode === "off") return;
      els.fields.insertAdjacentHTML("beforeend",
        f.input === "file" ? cvFieldHtml(mode)
          : f.input === "select" ? selectFieldHtml(f, mode)
          : textFieldHtml(f, mode));
    });
    if (modes.cv && modes.cv !== "off") wireDropzone();
  }

  function textFieldHtml(f, mode) {
    const ui = FIELD_UI[f.key] || {};
    return `
      <label class="vap-field" data-key="${f.key}">
        <span class="vap-label">${esc(f.label)}${optTag(mode)}</span>
        <input type="${f.input === "email" ? "email" : f.input === "tel" ? "tel" : "text"}"
               name="${f.key}" placeholder="${esc(ui.placeholder || "")}"
               ${ui.autocomplete ? `autocomplete="${ui.autocomplete}"` : ""} />
        <span class="vap-err" hidden></span>
      </label>`;
  }

  function selectFieldHtml(f, mode) {
    const ui = FIELD_UI[f.key] || {};
    return `
      <label class="vap-field" data-key="${f.key}">
        <span class="vap-label">${esc(f.label)}${optTag(mode)}</span>
        <select name="${f.key}" ${ui.autocomplete ? `autocomplete="${ui.autocomplete}"` : ""}>
          <option value="">${esc(ui.prompt || "Select an option")}</option>
          ${(f.options || []).map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("")}
        </select>
        <span class="vap-err" hidden></span>
      </label>`;
  }

  function cvFieldHtml(mode) {
    return `
      <div class="vap-field" data-key="cv">
        <span class="vap-label">CV / Resume${optTag(mode)}</span>
        <div class="vap-drop" id="vapDrop" tabindex="0" role="button"
             aria-label="Upload your CV">
          <span class="vap-drop-main">Choose a file</span>
          <span class="vap-drop-sub">or drop it here · PDF, DOC or DOCX · up to 8 MB</span>
        </div>
        <div id="vapFileBox"></div>
        <input type="file" id="vapFile" accept=".pdf,.doc,.docx" hidden />
        <span class="vap-err" hidden></span>
      </div>`;
  }

  function renderQuestions() {
    const qs = job.questions || [];
    els.questions.innerHTML = qs.map(questionHtml).join("");
  }

  function questionHtml(q) {
    const label = `<span class="vap-label">${esc(q.label)}${q.required ? "" : optTag("optional")}</span>` +
                  (q.help ? `<span class="vap-help">${esc(q.help)}</span>` : "");
    const name = `q_${q.id}`;
    let control = "";

    if (q.type === "paragraph") {
      control = `<textarea name="${name}" rows="4"></textarea>`;
    } else if (q.type === "short_answer") {
      control = `<input type="text" name="${name}" />`;
    } else if (q.type === "number") {
      control = `<input type="number" name="${name}" step="any" />`;
    } else if (q.type === "dropdown") {
      control = `<select name="${name}">` +
        `<option value="">Select an option</option>` +
        (q.options || []).map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("") +
        `</select>`;
    } else if (q.type === "yes_no") {
      control = choicesHtml(name, ["Yes", "No"], "radio");
    } else if (q.type === "single_select") {
      control = choicesHtml(name, q.options || [], "radio");
    } else if (q.type === "multi_select") {
      control = choicesHtml(name, q.options || [], "checkbox");
    }

    return `<div class="vap-field" data-q="${esc(q.id)}" data-type="${esc(q.type)}"
                 data-required="${q.required ? "1" : ""}">
              ${label}${control}<span class="vap-err" hidden></span>
            </div>`;
  }

  function choicesHtml(name, options, inputType) {
    return `<div class="vap-choices">` + options.map((o) => `
      <label class="vap-choice">
        <input type="${inputType}" name="${name}" value="${esc(o)}" />
        <span>${esc(o)}</span>
      </label>`).join("") + `</div>`;
  }

  function optTag(mode) {
    return mode === "optional" ? ` <span class="vap-opt">(optional)</span>` : "";
  }

  // --- CV dropzone ----------------------------------------------------------
  function wireDropzone() {
    const drop = $("vapDrop"), input = $("vapFile");
    if (!drop || !input) return;

    const pick = () => input.click();
    drop.addEventListener("click", pick);
    drop.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); }
    });
    input.addEventListener("change", () => { takeFile(input.files[0]); input.value = ""; });

    ["dragenter", "dragover"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
    ["dragleave", "drop"].forEach((ev) =>
      drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("is-over"); }));
    drop.addEventListener("drop", (e) => {
      const f = e.dataTransfer && e.dataTransfer.files[0];
      if (f) takeFile(f);
    });
  }

  function takeFile(file) {
    if (!file) return;
    const ext = file.name.includes(".") ? file.name.split(".").pop().toLowerCase() : "";
    if (!CV_EXTS.includes(ext)) return setFieldError("cv", "That file type isn't supported. Use PDF, DOC or DOCX.");
    if (file.size > MAX_CV_BYTES) return setFieldError("cv", "That file is over 8 MB. Try a smaller version.");
    clearFieldError("cv");
    cvFile = file;
    drawFile();
  }

  function drawFile() {
    const box = $("vapFileBox"), drop = $("vapDrop");
    if (!box) return;
    if (!cvFile) { box.innerHTML = ""; if (drop) drop.hidden = false; return; }
    if (drop) drop.hidden = true;
    box.innerHTML = `
      <div class="vap-file">
        <span class="vap-file-name">${esc(cvFile.name)}</span>
        <span class="vap-file-size">${fmtSize(cvFile.size)}</span>
        <button type="button" class="vap-file-x" id="vapFileX" aria-label="Remove file">&times;</button>
      </div>`;
    $("vapFileX").addEventListener("click", () => { cvFile = null; drawFile(); });
  }

  // --- Validate + submit ----------------------------------------------------
  function fieldEl(key) { return els.form.querySelector(`.vap-field[data-key="${key}"]`); }

  function setFieldError(key, msg) {
    const el = fieldEl(key);
    if (!el) return;
    el.classList.add("is-bad");
    const err = el.querySelector(".vap-err");
    if (err) { err.textContent = msg; err.hidden = false; }
  }
  function clearFieldError(key) {
    const el = fieldEl(key);
    if (!el) return;
    el.classList.remove("is-bad");
    const err = el.querySelector(".vap-err");
    if (err) { err.hidden = true; }
  }
  function clearAllErrors() {
    els.form.querySelectorAll(".vap-field.is-bad").forEach((el) => el.classList.remove("is-bad"));
    els.form.querySelectorAll(".vap-err").forEach((el) => { el.hidden = true; });
    els.formErr.hidden = true;
  }

  function validate() {
    clearAllErrors();
    const modes = job.form || {};
    let firstBad = null;

    (job.fields || []).forEach((f) => {
      const mode = modes[f.key] || "off";
      if (mode !== "required") return;
      if (f.key === "cv") {
        if (!cvFile) { setFieldError("cv", "Add your CV to continue."); firstBad = firstBad || fieldEl("cv"); }
        return;
      }
      const input = els.form.querySelector(`[name="${f.key}"]`);
      if (input && !input.value.trim()) {
        setFieldError(f.key, `${f.label} is required.`);
        firstBad = firstBad || fieldEl(f.key);
      }
    });

    const email = els.form.querySelector('[name="email"]');
    if (email && email.value.trim() && !/^[^@\s]+@[^@\s.]+\.[^@\s]+$/.test(email.value.trim())) {
      setFieldError("email", "Check the email address — we use it to reach you.");
      firstBad = firstBad || fieldEl("email");
    }

    (job.questions || []).forEach((q) => {
      if (!q.required) return;
      const wrap = els.form.querySelector(`.vap-field[data-q="${q.id}"]`);
      if (!wrap) return;
      const ctl = wrap.querySelector("input, textarea, select");
      const answered = ["multi_select", "single_select", "yes_no"].includes(q.type)
        ? !!wrap.querySelector("input:checked")
        : !!(ctl && ctl.value.trim());
      if (!answered) {
        wrap.classList.add("is-bad");
        const err = wrap.querySelector(".vap-err");
        if (err) { err.textContent = "This one's required."; err.hidden = false; }
        firstBad = firstBad || wrap;
      }
    });

    if (firstBad) firstBad.scrollIntoView({ behavior: "smooth", block: "center" });
    return !firstBad;
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!validate()) return;

    const fd = new FormData(els.form);
    if (cvFile) fd.append("cv", cvFile, cvFile.name);
    if (src) fd.append("src", src);

    setSubmitting(true);
    try {
      const url = `${API_BASE}/public/hirex/jobs/${encodeURIComponent(token)}/apply` +
                  (src ? `?src=${encodeURIComponent(src)}` : "");
      const res = await fetch(url, { method: "POST", body: fd });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "Something went wrong. Please try again.");
      showDone();
    } catch (err) {
      els.formErr.textContent = err.message || "Something went wrong. Please try again.";
      els.formErr.hidden = false;
      els.formErr.scrollIntoView({ behavior: "smooth", block: "center" });
    } finally {
      setSubmitting(false);
    }
  }

  function setSubmitting(on) {
    els.submit.disabled = on;
    els.submit.textContent = on ? "Sending…" : "Send application";
  }

  function showDone() {
    els.form.hidden = true;
    els.doneRole.textContent = `We've got your application for ${job.title}.`;
    els.done.hidden = false;
    els.done.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // --- Utils ----------------------------------------------------------------
  function pretty(s) {
    return s ? String(s).replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()) : "";
  }
  function fmtSize(bytes) {
    return bytes < 1024 * 1024
      ? `${Math.max(1, Math.round(bytes / 1024))} KB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
})();
