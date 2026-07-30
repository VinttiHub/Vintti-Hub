/* =====================================================================
   Hirex ATS — Candidates directory (global, across all jobs)
   ===================================================================== */
(function () {
  "use strict";

  const API_BASE = window.HIREX_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1")
      ? "http://localhost:5000"
      : "https://7m6mw95m8y.us-east-2.awsapprunner.com");

  function currentUserEmail() {
    return (localStorage.getItem("user_email") || sessionStorage.getItem("user_email") || "").toLowerCase().trim();
  }

  const SOURCE_LABEL = { referral: "Referral", linkedin: "LinkedIn", job_board: "Job board", inbound: "Inbound", sourced: "Sourced" };
  const STAGE_LABEL = { applied: "Applied", screening: "Screening", interview: "Interview", offer: "Offer", hired: "Hired", rejected: "Rejected" };
  // Same colours as the pipeline board, so a stage looks identical wherever you meet it.
  const STAGE_COLOR = {
    applied: "#4ba9ff", screening: "#6c38ff", interview: "#0028ff",
    offer: "#d99a1c", hired: "#8bd33a", rejected: "#9aa2ad",
  };
  const ENGLISH_LEVELS = ["Beginner", "Intermediate", "Advanced", "Fluent", "Native"];
  const stageLabel = (s) => STAGE_LABEL[s] || String(s || "—");
  // Mixed casing arrives from different sources ("LinkedIn" vs "Linkedin").
  const sourceLabel = (s) => SOURCE_LABEL[String(s || "").toLowerCase()] || String(s || "");
  const stageColor = (s) => STAGE_COLOR[s] || "#9aa2ad";

  let candidates = [];
  const filters = { q: "", has_cv: false };
  let currentProfile = null;
  let cvUploadCandidateId = null;
  let searchTimer = null;

  const $ = (id) => document.getElementById(id);
  let els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els = {
      search: $("hxSearch"), hasCv: $("fHasCv"), clearFilters: $("hxClearFilters"),
      count: $("hxCount"), body: $("hxCandBody"), table: document.querySelector(".hx-table-wrap"),
      loading: $("hxLoading"), empty: $("hxEmpty"), emptyTitle: $("hxEmptyTitle"), emptyText: $("hxEmptyText"),
      error: $("hxError"), retry: $("hxRetry"),
      profScrim: $("hxProfScrim"), profDrawer: $("hxProfDrawer"), profClose: $("hxProfClose"),
      profAvatar: $("hxProfAvatar"), profName: $("hxProfName"), profSub: $("hxProfSub"),
      profContact: $("hxProfContact"), profCv: $("hxProfCv"), profApps: $("hxProfApps"),
      profEdit: $("hxProfEdit"), profFoot: $("hxProfFoot"),
      profSave: $("hxProfSave"), profCancel: $("hxProfCancel"),
      cvInput: $("hxCvInput"), toasts: $("hxToasts"),
      newBtn: $("hxNewCand"), newScrim: $("hxNewScrim"), newDrawer: $("hxNewDrawer"),
      newForm: $("hxNewForm"), newClose: $("hxNewClose"), newCancel: $("hxNewCancel"),
      newSave: $("hxNewSave"), newJobSel: $("hxNewJobSel"), newStage: $("hxNewStage"),
      newEnglish: $("hxNewEnglish"), newSource: $("hxNewSource"),
    };

    els.retry.addEventListener("click", loadCandidates);
    els.hasCv.addEventListener("change", () => { filters.has_cv = els.hasCv.checked; syncClear(); loadCandidates(); });
    els.clearFilters.addEventListener("click", clearFilters);
    els.search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { filters.q = els.search.value.trim(); syncClear(); loadCandidates(); }, 280);
    });
    els.profClose.addEventListener("click", closeProfile);
    els.profScrim.addEventListener("click", closeProfile);
    els.profSave.addEventListener("click", saveProfile);
    els.profCancel.addEventListener("click", () => renderProfContact(currentProfile));
    els.cvInput.addEventListener("change", () => {
      const f = els.cvInput.files[0];
      if (f && cvUploadCandidateId) uploadCv(cvUploadCandidateId, f);
      els.cvInput.value = "";
    });
    // New candidate
    els.newEnglish.innerHTML = `<option value="">—</option>` +
      ENGLISH_LEVELS.map((l) => `<option value="${l}">${l}</option>`).join("");
    els.newSource.innerHTML = `<option value="">—</option>` +
      Object.entries(SOURCE_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
    els.newStage.innerHTML = Object.entries(STAGE_LABEL)
      .map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
    els.newBtn.addEventListener("click", openNewDrawer);
    els.newClose.addEventListener("click", closeNewDrawer);
    els.newCancel.addEventListener("click", closeNewDrawer);
    els.newScrim.addEventListener("click", closeNewDrawer);
    els.newSave.addEventListener("click", createCandidate);

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (els.newDrawer.getAttribute("aria-hidden") === "false") return closeNewDrawer();
      closeProfile();
    });

    loadCandidates();
  }

  /* =======================================================================
     Create a candidate straight from the directory. Picking a job is optional:
     you can bank someone good now and decide where they fit later.
     ======================================================================= */
  async function openNewDrawer() {
    els.newForm.reset();
    clearErr(els.newForm);
    els.newStage.value = "applied";
    els.newJobSel.innerHTML = `<option value="">Loading jobs…</option>`;
    openDrawer(els.newScrim, els.newDrawer);
    setTimeout(() => els.newForm.querySelector('[name="first_name"]').focus(), 30);

    try {
      const res = await fetch(`${API_BASE}/hirex/jobs`, { credentials: "include" });
      const jobs = res.ok ? await res.json() : [];
      // Open roles first — that's where a new candidate almost always belongs.
      const rank = { open: 0, draft: 1, on_hold: 2, closed: 3, archived: 4 };
      jobs.sort((a, b) => (rank[a.status] ?? 9) - (rank[b.status] ?? 9) ||
                          a.title.localeCompare(b.title));
      els.newJobSel.innerHTML = `<option value="">Don't add to a job yet</option>` +
        jobs.map((j) => `<option value="${j.job_id}">${esc(j.title)}${
          j.status !== "open" ? ` (${esc(j.status.replace("_", " "))})` : ""}</option>`).join("");
    } catch {
      els.newJobSel.innerHTML = `<option value="">Couldn't load jobs</option>`;
    }
  }

  function closeNewDrawer() { closeDrawer(els.newScrim, els.newDrawer); }

  async function createCandidate() {
    const f = els.newForm;
    const val = (n) => (f.elements[n] ? f.elements[n].value.trim() : "");
    clearErr(f);
    if (!val("first_name")) { showErr(f, "first_name", "A first name is required"); return; }

    const payload = { stage: val("stage") || "applied" };
    ["first_name", "last_name", "email", "phone", "headline", "current_company",
     "area", "location", "country", "english_level", "desired_salary",
     "linkedin_url", "source", "notes"].forEach((n) => {
      const v = val(n);
      if (v) payload[n] = v;
    });
    if (val("job_id")) payload.job_id = Number(val("job_id"));

    els.newSave.disabled = true; els.newSave.textContent = "Creating…";
    try {
      const res = await apiWrite("/hirex/candidates", "POST", payload);
      const body = await res.json().catch(() => ({}));
      if (res.status === 409) { showErr(f, "email", body.error || "That email is taken"); return; }
      if (!res.ok) throw new Error(body.error || "");
      closeNewDrawer();
      toast("ok", body.job_id
        ? `${body.full_name} created and added to the pipeline`
        : `${body.full_name} created`);
      loadCandidates();
    } catch (err) {
      toast("err", err.message || "Couldn't create the candidate");
    } finally {
      els.newSave.disabled = false; els.newSave.textContent = "Create candidate";
    }
  }

  function clearErr(form) {
    form.querySelectorAll(".hx-err").forEach((e) => { e.textContent = ""; });
    form.querySelectorAll(".has-error").forEach((e) => e.classList.remove("has-error"));
  }
  function showErr(form, key, msg) {
    const em = form.querySelector(`.hx-err[data-err="${key}"]`);
    if (!em) return;
    em.textContent = msg;
    const field = em.closest(".hx-field");
    if (field) field.classList.add("has-error");
  }

  // --- Data ----------------------------------------------------------------
  function buildQuery() {
    const p = new URLSearchParams();
    if (filters.q) p.set("q", filters.q);
    if (filters.has_cv) p.set("has_cv", "1");
    const s = p.toString();
    return s ? `?${s}` : "";
  }

  async function loadCandidates() {
    showState("loading");
    try {
      const res = await fetch(`${API_BASE}/hirex/candidates${buildQuery()}`, { credentials: "include" });
      if (!res.ok) throw new Error();
      candidates = await res.json();
      render();
    } catch { showState("error"); }
  }

  function showState(which) {
    els.loading.hidden = which !== "loading";
    els.error.hidden = which !== "error";
    els.empty.hidden = which !== "empty";
    els.table.style.display = which === "table" ? "" : "none";
  }

  // --- Render --------------------------------------------------------------
  function render() {
    if (!candidates.length) {
      const filtered = filters.q || filters.has_cv;
      els.emptyTitle.textContent = filtered ? "No matching candidates" : "No candidates yet";
      els.emptyText.textContent = filtered
        ? "Try adjusting or clearing your filters."
        : "Add candidates to a job's pipeline and they'll show up here.";
      showState("empty");
      els.count.innerHTML = "";
      return;
    }
    showState("table");
    els.count.innerHTML = `<b>${candidates.length}</b> ${candidates.length === 1 ? "candidate" : "candidates"}`;
    els.body.innerHTML = candidates.map(rowHtml).join("");
    els.body.querySelectorAll("tr").forEach((tr) => {
      const id = Number(tr.dataset.id);
      tr.addEventListener("click", () => openProfile(candidates.find((c) => c.candidate_id === id)));
    });
  }

  function rowHtml(c) {
    return `
      <tr data-id="${c.candidate_id}">
        <td class="hx-col-title">
          <div class="hx-cand-cell">
            <span class="hx-avatar" style="background:${avatarColor(c.full_name)}">${initials(c.full_name)}</span>
            <div class="hx-cand-cell-txt">
              <div class="hx-cand-cell-name">${esc(c.full_name)}</div>
              ${c.headline ? `<div class="hx-cand-cell-sub">${esc(c.headline)}</div>` : ""}
            </div>
          </div>
        </td>
        <td>${c.email ? esc(c.email) : dash()}</td>
        <td class="hx-col-apps"><span class="hx-openings">${Number(c.applications) || 0}</span></td>
        <td>${c.last_applied ? `<span class="hx-cell-muted">${fmtDate(c.last_applied)}</span>` : dash()}</td>
        <td>${jobChips(c.jobs)}</td>
        <td>${c.source ? `<span class="hx-src-chip">${esc(sourceLabel(c.source))}</span>` : dash()}</td>
        <td class="hx-col-openings">${c.has_cv ? `<i class="fa-solid fa-paperclip hx-cv-flag" title="CV on file"></i>` : dash()}</td>
      </tr>`;
  }

  /** A candidate can sit at a different stage in every pipeline they're in, so
   *  the stage rides on each job chip rather than in a column of its own. */
  function jobChips(jobs) {
    if (!Array.isArray(jobs) || !jobs.length) return dash();
    const shown = jobs.slice(0, 2).map((j) => `
      <span class="hx-job-chip" title="${esc(j.title)} · ${esc(stageLabel(j.stage))}">
        <span class="hx-job-chip-title">${esc(j.title)}</span>
        <span class="hx-stage-tag" style="--s:${stageColor(j.stage)}">${esc(stageLabel(j.stage))}</span>
      </span>`);
    if (jobs.length > 2) {
      const rest = jobs.slice(2)
        .map((j) => `${j.title} · ${stageLabel(j.stage)}`).join("\n");
      shown.push(`<span class="hx-job-chip more" title="${esc(rest)}">+${jobs.length - 2}</span>`);
    }
    return `<div class="hx-job-chips">${shown.join("")}</div>`;
  }

  // --- Profile drawer ------------------------------------------------------
  function openProfile(c) {
    if (!c) return;
    currentProfile = c;
    els.profAvatar.textContent = initials(c.full_name);
    els.profAvatar.style.background = avatarColor(c.full_name);
    els.profName.textContent = c.full_name;
    els.profSub.textContent = c.headline || "";

    renderProfContact(c);
    renderProfCv(c);
    renderProfApps(c);
    openDrawer(els.profScrim, els.profDrawer);
  }
  function closeProfile() { closeDrawer(els.profScrim, els.profDrawer); currentProfile = null; }

  /* =======================================================================
     Editing the person's record. This is their global profile, so a change
     here shows up in every pipeline they're in.
     ======================================================================= */
  const EDITABLE_FIELDS = [
    "first_name", "last_name", "email", "phone", "headline", "current_company",
    "location", "country", "english_level", "linkedin_url", "area",
    "desired_salary", "source", "notes",
  ];

  function renderProfContact(c) {
    if (!c) return;
    const bits = [];
    if (c.email) bits.push(`<a href="mailto:${esc(c.email)}"><i class="fa-solid fa-envelope"></i>${esc(c.email)}</a>`);
    if (c.phone) bits.push(`<span><i class="fa-solid fa-phone"></i>${esc(c.phone)}</span>`);
    if (c.linkedin_url) bits.push(`<a href="${esc(linkUrl(c.linkedin_url))}" target="_blank" rel="noopener"><i class="fa-brands fa-linkedin"></i>LinkedIn</a>`);
    const where = [c.location, c.country].filter(Boolean).join(", ");
    if (where) bits.push(`<span><i class="fa-solid fa-location-dot"></i>${esc(where)}</span>`);
    if (c.current_company) bits.push(`<span><i class="fa-solid fa-building"></i>${esc(c.current_company)}</span>`);
    if (c.english_level) bits.push(`<span><i class="fa-solid fa-language"></i>${esc(c.english_level)}</span>`);
    if (c.source) bits.push(`<span title="Where we originally found this person"><i class="fa-solid fa-signal"></i>Found via ${esc(sourceLabel(c.source))}</span>`);

    els.profContact.innerHTML =
      (bits.join("") || `<span class="hx-cell-muted">No contact details yet</span>`) +
      `<button type="button" class="hx-cand-editbtn" id="hxProfEditBtn">
         <i class="fa-solid fa-pen"></i> Edit details
       </button>`;
    els.profEdit.hidden = true;
    els.profEdit.innerHTML = "";
    els.profFoot.hidden = true;
    // Toggle: pressing it again collapses the form and drops the edits.
    $("hxProfEditBtn").addEventListener("click", () => {
      if (els.profEdit.hidden) openProfileForm(c);
      else renderProfContact(c);
    });
  }

  /** The button says what pressing it will do next. */
  function setEditBtnState(btn, open) {
    if (!btn) return;
    btn.innerHTML = open
      ? `<i class="fa-solid fa-xmark"></i> Cancel edit`
      : `<i class="fa-solid fa-pen"></i> Edit details`;
    btn.classList.toggle("is-open", open);
  }

  function openProfileForm(c) {
    const text = (name, label, placeholder = "") => `
      <label class="hx-field">
        <span>${label}</span>
        <input type="text" data-cand="${name}" value="${esc(c[name] || "")}" placeholder="${esc(placeholder)}" />
      </label>`;

    els.profEdit.innerHTML = `
      <div class="hx-grid">
        ${text("first_name", "First name")}
        ${text("last_name", "Last name")}
        ${text("email", "Email", "jane@email.com")}
        ${text("phone", "Phone")}
        ${text("headline", "Role / position", "Senior Backend Engineer")}
        ${text("current_company", "Current company")}
        ${text("location", "City")}
        ${text("country", "Country")}
        <label class="hx-field">
          <span>English level</span>
          <select data-cand="english_level">
            <option value="">—</option>
            ${ENGLISH_LEVELS.map((l) =>
              `<option value="${l}" ${c.english_level === l ? "selected" : ""}>${l}</option>`).join("")}
          </select>
        </label>
        ${text("area", "Area", "Marketing")}
        ${text("linkedin_url", "LinkedIn", "linkedin.com/in/…")}
        ${text("desired_salary", "Desired salary")}
        <label class="hx-field hx-col-2">
          <span>Source</span>
          <select data-cand="source">
            <option value="">—</option>
            ${Object.entries(SOURCE_LABEL).map(([k, v]) =>
              `<option value="${k}" ${c.source === k ? "selected" : ""}>${v}</option>`).join("")}
            ${c.source && !SOURCE_LABEL[c.source]
              ? `<option value="${esc(c.source)}" selected>${esc(c.source)}</option>` : ""}
          </select>
        </label>
        <label class="hx-field hx-col-2">
          <span>Notes</span>
          <textarea data-cand="notes" rows="3" placeholder="Anything worth remembering about them">${esc(c.notes || "")}</textarea>
        </label>
      </div>
      <em class="hx-err" data-err="cand"></em>`;
    els.profEdit.hidden = false;
    els.profFoot.hidden = false;
    setEditBtnState($("hxProfEditBtn"), true);
    const first = els.profEdit.querySelector("input");
    if (first) first.focus();
  }

  async function saveProfile() {
    if (!currentProfile || els.profEdit.hidden) return;
    const before = currentProfile;
    const patch = {};
    EDITABLE_FIELDS.forEach((name) => {
      const el = els.profEdit.querySelector(`[data-cand="${name}"]`);
      if (!el) return;
      const value = el.value.trim();
      if (value !== String(before[name] ?? "")) patch[name] = value || null;
    });

    if ("first_name" in patch && !patch.first_name) {
      const err = els.profEdit.querySelector('[data-err="cand"]');
      if (err) err.textContent = "A first name is required";
      return;
    }
    if (!Object.keys(patch).length) { renderProfContact(before); return; }

    els.profSave.disabled = true; els.profSave.textContent = "Saving…";
    try {
      const res = await apiWrite(`/hirex/candidates/${before.candidate_id}`, "PATCH", patch);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      toast("ok", "Saved");
      closeProfile();
      loadCandidates();   // the row, the name and the chips all come from this list
    } catch (err) {
      toast("err", err.message || "Couldn't save the changes");
    } finally {
      els.profSave.disabled = false; els.profSave.textContent = "Save changes";
    }
  }

  function renderProfCv(c) {
    if (c.has_cv) {
      els.profCv.innerHTML = `
        <div class="hx-cv-box">
          <span class="hx-cv-ic"><i class="fa-solid fa-file-lines"></i></span>
          <div class="hx-cv-info"><div class="hx-cv-name">${esc(c.cv_file_name || "CV on file")}</div><div class="hx-cv-sub">On file</div></div>
          <div class="hx-cv-actions">
            <button class="hx-btn hx-btn-ghost" id="hxCvView" type="button">View</button>
            <button class="hx-btn hx-btn-ghost" id="hxCvReplace" type="button">Replace</button>
          </div>
        </div>`;
      $("hxCvView").addEventListener("click", () => viewCv(c.candidate_id));
      $("hxCvReplace").addEventListener("click", () => triggerCvUpload(c.candidate_id));
    } else {
      // No file doesn't mean nothing to read: imported candidates carry profile
      // text the AI rubric uses. Name the source so "No CV" isn't misleading.
      els.profCv.innerHTML = c.has_text ? `
        <div class="hx-cv-empty hx-cv-text">
          <span class="hx-cv-ic" style="margin:0 auto"><i class="fa-solid fa-file-lines"></i></span>
          <p><b>No CV file</b>, but we have their profile text from
             ${esc(c.cv_text_source || "an imported profile")}, which is what AI screening reads.</p>
          <button class="hx-btn hx-btn-soft" id="hxCvUpload" type="button"><i class="fa-solid fa-upload"></i> Upload CV</button>
        </div>` : `
        <div class="hx-cv-empty">
          <span class="hx-cv-ic" style="margin:0 auto"><i class="fa-solid fa-file-arrow-up"></i></span>
          <p>No CV on file.</p>
          <button class="hx-btn hx-btn-soft" id="hxCvUpload" type="button"><i class="fa-solid fa-upload"></i> Upload CV</button>
        </div>`;
      $("hxCvUpload").addEventListener("click", () => triggerCvUpload(c.candidate_id));
    }
  }

  function renderProfApps(c) {
    const jobs = c.jobs || [];
    let html = `<h5>Applications (${jobs.length})</h5>`;
    if (!jobs.length) {
      html += `<p class="hx-cell-muted" style="font-size:12.5px;margin:0">Not in any pipeline yet.</p>`;
    } else {
      html += jobs.map((j) => `
        <a class="hx-app-row" href="hirex-job-detail.html?id=${j.job_id}">
          <div class="hx-app-info">
            <div class="hx-app-title">${esc(j.title)}</div>
            <div class="hx-app-meta">
              <span class="hx-stage-tag" style="--s:${stageColor(j.stage)}">${esc(stageLabel(j.stage))}</span>
              ${j.ai_score != null ? `<span>AI ${j.ai_score}</span>` : ""}
              ${j.applied_at ? `<span>Applied ${fmtDate(j.applied_at)}</span>` : ""}
            </div>
          </div>
          <i class="fa-solid fa-arrow-right hx-app-open"></i>
        </a>`).join("");
    }
    els.profApps.innerHTML = html;
  }

  // --- CV ------------------------------------------------------------------
  function triggerCvUpload(id) { cvUploadCandidateId = id; els.cvInput.click(); }

  async function uploadCv(id, file) {
    els.profCv.innerHTML = `<div class="hx-ai-loading"><div class="hx-spinner"></div> Uploading &amp; parsing CV…</div>`;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("actor_email", currentUserEmail());
    try {
      const res = await fetch(`${API_BASE}/hirex/candidates/${id}/cv`, {
        method: "POST", credentials: "include",
        headers: { "X-User-Email": currentUserEmail() }, body: fd,
      });
      const b = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(b.error || "");
      toast("ok", b.has_text ? "CV uploaded & parsed" : "CV uploaded");
      if (currentProfile && currentProfile.candidate_id === id) {
        currentProfile.has_cv = true; currentProfile.cv_file_name = b.cv_file_name;
        renderProfCv(currentProfile);
      }
      loadCandidates();
    } catch (err) {
      toast("err", err.message || "Couldn't upload the CV");
      if (currentProfile) renderProfCv(currentProfile);
    }
  }

  async function viewCv(id) {
    try {
      const res = await fetch(`${API_BASE}/hirex/candidates/${id}/cv`, { credentials: "include" });
      const b = await res.json();
      if (!res.ok || !b.url) throw new Error();
      window.open(b.url, "_blank", "noopener");
    } catch { toast("err", "Couldn't open the CV"); }
  }

  // --- Filters -------------------------------------------------------------
  function syncClear() { els.clearFilters.hidden = !(filters.q || filters.has_cv); }
  function clearFilters() {
    filters.q = ""; filters.has_cv = false;
    els.search.value = ""; els.hasCv.checked = false;
    syncClear(); loadCandidates();
  }

  // --- Drawer helpers ------------------------------------------------------
  /** Same shape as the write helper in hirex-detail.js: the backend reads the
   *  actor from the X-User-Email header. */
  function apiWrite(path, method, payload) {
    return fetch(`${API_BASE}${path}`, {
      method,
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-User-Email": currentUserEmail() },
      body: JSON.stringify({ ...payload, actor_email: currentUserEmail() }),
    });
  }

  function openDrawer(scrim, drawer) {
    scrim.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => { scrim.classList.add("is-open"); drawer.classList.add("is-open"); });
  }
  function closeDrawer(scrim, drawer) {
    if (drawer.getAttribute("aria-hidden") === "true") return;
    scrim.classList.remove("is-open");
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    setTimeout(() => { scrim.hidden = true; }, 260);
  }

  // --- Toast ---------------------------------------------------------------
  function toast(kind, msg) {
    const el = document.createElement("div");
    el.className = `hx-toast hx-toast-${kind === "ok" ? "ok" : "err"}`;
    el.innerHTML = `<i class="fa-solid ${kind === "ok" ? "fa-circle-check" : "fa-circle-exclamation"}"></i><span>${esc(msg)}</span>`;
    els.toasts.appendChild(el);
    setTimeout(() => { el.style.transition = "opacity .25s, transform .25s"; el.style.opacity = "0"; el.style.transform = "translateY(6px)"; setTimeout(() => el.remove(), 260); }, 2600);
  }

  // --- Utils ---------------------------------------------------------------
  function dash() { return `<span class="hx-cell-muted">—</span>`; }
  function initials(name) {
    const p = String(name || "").trim().split(/\s+/);
    return ((p[0]?.[0] || "") + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase() || "?";
  }
  function avatarColor(name) {
    const palette = ["#0028ff", "#6c38ff", "#4ba9ff", "#ff1fdb", "#d99a1c", "#12a150", "#e0115f"];
    let h = 0; for (const ch of String(name || "")) h = (h * 31 + ch.charCodeAt(0)) % 997;
    return palette[h % palette.length];
  }
  function linkUrl(u) { return /^https?:\/\//i.test(u) ? u : "https://" + u; }
  function fmtDate(iso) { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? "—" : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
})();
