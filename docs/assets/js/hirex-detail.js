/* =====================================================================
   Hirex ATS — Job detail + pipeline board (Slice 2)
   ===================================================================== */
(function () {
  "use strict";

  // Resolved by hirex-config.js (loaded first). Fallback keeps the page working
  // if that file is ever missing.
  const API_BASE = window.HIREX_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1")
      ? "http://localhost:5000"
      : "https://7m6mw95m8y.us-east-2.awsapprunner.com");

  function currentUserEmail() {
    return (localStorage.getItem("user_email") || sessionStorage.getItem("user_email") || "").toLowerCase().trim();
  }

  const STAGES = [
    { key: "applied",   label: "Applied",   color: "#4ba9ff" },
    { key: "screening", label: "Screening", color: "#6c38ff" },
    { key: "interview", label: "Interview", color: "#0028ff" },
    { key: "offer",     label: "Offer",     color: "#d99a1c" },
    { key: "hired",     label: "Hired",     color: "#8bd33a" },
    { key: "rejected",  label: "Rejected",  color: "#9aa2ad" },
  ];
  const STAGE_LABEL = Object.fromEntries(STAGES.map((s) => [s.key, s.label]));

  const SOURCE_LABEL = {
    referral: "Referral", linkedin: "LinkedIn", job_board: "Job board",
    inbound: "Inbound", sourced: "Sourced",
  };

  // Scorecards
  const COMPETENCIES = ["Technical skills", "Problem solving", "Communication",
                        "Culture & values fit", "Experience relevance"];
  const SCALE_LABELS = { 1: "Strong No", 2: "No", 3: "Yes", 4: "Strong Yes" };
  const REC_ORDER = ["strong_no", "no", "yes", "strong_yes"];
  const REC_LABEL = { strong_no: "Strong No", no: "No", yes: "Yes", strong_yes: "Strong Yes" };

  // --- State ---------------------------------------------------------------
  const jobId = Number(new URLSearchParams(location.search).get("id"));
  let job = null;
  let apps = [];
  let activityLoaded = false;
  let currentCand = null;   // application obj open in the candidate drawer
  let draggedAppId = null;

  const $ = (id) => document.getElementById(id);
  let els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    if (!jobId) { location.replace("hirex.html"); return; }
    els = {
      ref: $("hxRef"), title: $("hxTitle"), meta: $("hxMeta"), editBtn: $("hxEditBtn"),
      addCand: $("hxAddCand"),
      board: $("hxBoard"), pipeLoading: $("hxPipeLoading"), pipeCount: $("hxPipeCount"),
      activity: $("hxActivity"), about: $("hxAbout"),
      addScrim: $("hxAddScrim"), addDrawer: $("hxAddDrawer"), addForm: $("hxAddForm"),
      addStage: $("hxAddStage"), addClose: $("hxAddClose"), addCancel: $("hxAddCancel"), addSave: $("hxAddSave"),
      candScrim: $("hxCandScrim"), candDrawer: $("hxCandDrawer"), candClose: $("hxCandClose"),
      candAvatar: $("hxCandAvatar"), candName: $("hxCandName"), candSub: $("hxCandSub"),
      candStage: $("hxCandStage"), candStars: $("hxCandStars"), candContact: $("hxCandContact"),
      candCv: $("hxCandCv"), cvInput: $("hxCvInput"), candAi: $("hxCandAi"),
      scorecards: $("hxScorecards"),
      scScrim: $("hxScScrim"), scDrawer: $("hxScDrawer"), scTitle: $("hxScTitle"),
      scBody: $("hxScBody"), scClose: $("hxScClose"), scCancel: $("hxScCancel"),
      scSave: $("hxScSave"), scDelete: $("hxScDelete"),
      candNotes: $("hxCandNotes"), candRemove: $("hxCandRemove"), candSave: $("hxCandSave"),
      toasts: $("hxToasts"),
      tabs: Array.from(document.querySelectorAll(".hx-mod[data-tab]")),
    };
    els.editBtn.href = `hirex.html?edit=${jobId}`;

    // Fill stage selects
    els.addStage.innerHTML = STAGES.map((s) => `<option value="${s.key}">${s.label}</option>`).join("");
    els.candStage.innerHTML = STAGES.map((s) => `<option value="${s.key}">${s.label}</option>`).join("");

    // Tabs
    els.tabs.forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

    // Add drawer
    els.addCand.addEventListener("click", openAddDrawer);
    els.addClose.addEventListener("click", closeAddDrawer);
    els.addCancel.addEventListener("click", closeAddDrawer);
    els.addScrim.addEventListener("click", closeAddDrawer);
    els.addSave.addEventListener("click", saveNewCandidate);

    // Candidate drawer
    els.candClose.addEventListener("click", closeCandDrawer);
    els.candScrim.addEventListener("click", closeCandDrawer);
    els.candSave.addEventListener("click", saveCandidate);
    els.candRemove.addEventListener("click", removeCandidate);
    els.cvInput.addEventListener("change", () => {
      const f = els.cvInput.files[0];
      if (f && cvUploadCandidateId) uploadCv(cvUploadCandidateId, f);
      els.cvInput.value = "";
    });

    // Scorecard editor
    els.scClose.addEventListener("click", closeScorecardEditor);
    els.scCancel.addEventListener("click", closeScorecardEditor);
    els.scScrim.addEventListener("click", closeScorecardEditor);
    els.scSave.addEventListener("click", saveScorecard);
    els.scDelete.addEventListener("click", deleteMyScorecard);

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      // Close the top-most open layer first.
      if (els.scDrawer.getAttribute("aria-hidden") === "false") return closeScorecardEditor();
      closeAddDrawer(); closeCandDrawer();
    });

    loadJob();
    loadPipeline();
  }

  // --- Load ----------------------------------------------------------------
  async function loadJob() {
    try {
      const res = await fetch(`${API_BASE}/hirex/jobs/${jobId}`, { credentials: "include" });
      if (res.status === 404) { location.replace("hirex.html"); return; }
      if (!res.ok) throw new Error();
      job = await res.json();
      renderHead();
      renderAbout();
    } catch { toast("err", "Couldn't load the job"); }
  }

  async function loadPipeline() {
    els.pipeLoading.hidden = false;
    try {
      const res = await fetch(`${API_BASE}/hirex/jobs/${jobId}/pipeline`, { credentials: "include" });
      if (!res.ok) throw new Error();
      const data = await res.json();
      apps = data.applications || [];
      renderBoard();
    } catch {
      toast("err", "Couldn't load the pipeline");
    } finally {
      els.pipeLoading.hidden = true;
    }
  }

  async function loadActivity() {
    els.activity.innerHTML = `<div class="hx-state"><div class="hx-spinner"></div></div>`;
    try {
      const res = await fetch(`${API_BASE}/hirex/jobs/${jobId}/activity`, { credentials: "include" });
      if (!res.ok) throw new Error();
      renderActivity(await res.json());
      activityLoaded = true;
    } catch { els.activity.innerHTML = `<p class="hx-cell-muted" style="padding:20px 0">Couldn't load activity.</p>`; }
  }

  // --- Head + About --------------------------------------------------------
  function renderHead() {
    els.ref.textContent = jobRef(job.job_id);
    els.title.textContent = job.title;
    const st = { draft: "Draft", open: "Open", on_hold: "On hold", closed: "Closed", archived: "Archived" }[job.status] || job.status;
    const bits = [`<span class="hx-status hx-status-${job.status}">${st}</span>`];
    if (job.department) bits.push(`<span><i class="fa-solid fa-people-group"></i>${esc(job.department)}</span>`);
    if (job.location) bits.push(`<span><i class="fa-solid fa-location-dot"></i>${esc(job.location)}</span>`);
    if (job.recruiter_email) bits.push(`<span><i class="fa-solid fa-user-tie"></i>${esc(job.recruiter_email)}</span>`);
    bits.push(`<span><i class="fa-solid fa-users"></i>${Number(job.openings) || 1} opening${(Number(job.openings) || 1) > 1 ? "s" : ""}</span>`);
    els.meta.innerHTML = bits.join('<span class="hx-dot"></span>');
    document.title = `Hirex · ${job.title}`;
  }

  function renderAbout() {
    const money = (job.salary_min != null || job.salary_max != null)
      ? `${fmtNum(job.salary_min)}–${fmtNum(job.salary_max)} ${job.salary_currency || ""} ${job.salary_period ? "/ " + job.salary_period : ""}`.trim()
      : "—";
    const items = [
      ["Status", cap(job.status)],
      ["Priority", cap(job.priority)],
      ["Work mode", pretty(job.work_mode)],
      ["Employment", pretty(job.employment_type)],
      ["Seniority", cap(job.seniority)],
      ["Language", job.language || "—"],
      ["Compensation", money],
      ["Openings", String(job.openings ?? 1)],
      ["Recruiter", job.recruiter_email || "—"],
      ["Hiring manager", job.hiring_manager_email || "—"],
      ["Created by", job.created_by || "—"],
      ["Created", fmtDate(job.created_at)],
    ];
    let html = `<div class="hx-about-grid">` +
      items.map(([k, v]) => `<div class="hx-about-item"><span class="k">${k}</span><span class="v">${esc(v)}</span></div>`).join("") +
      `</div>`;
    const block = (title, txt) => txt ? `<div class="hx-about-block"><h4>${title}</h4><p>${esc(txt)}</p></div>` : "";
    html += block("Description", job.description);
    html += block("Requirements", job.requirements);
    html += block("Benefits", job.benefits);
    const chips = (title, arr) => (Array.isArray(arr) && arr.length)
      ? `<div class="hx-about-block"><h4>${title}</h4><div class="hx-chips">${arr.map((s) => `<span class="hx-chip">${esc(s)}</span>`).join("")}</div></div>` : "";
    html += chips("Skills", job.skills);
    html += chips("Tags", job.tags);
    els.about.innerHTML = html;
  }

  // --- Board ---------------------------------------------------------------
  function renderBoard() {
    els.pipeCount.textContent = apps.length;
    els.board.innerHTML = STAGES.map((s) => {
      const list = apps.filter((a) => a.stage === s.key);
      const cards = list.length
        ? list.map(cardHtml).join("")
        : `<div class="hx-col-empty">Drop here</div>`;
      return `
        <div class="hx-col" data-stage="${s.key}">
          <div class="hx-col-head">
            <span class="hx-col-dot" style="background:${s.color}"></span>
            <span class="hx-col-name">${s.label}</span>
            <span class="hx-col-count">${list.length}</span>
          </div>
          <div class="hx-col-body" data-stage="${s.key}">${cards}</div>
        </div>`;
    }).join("");
    wireBoard();
  }

  function cardHtml(a) {
    const c = a.candidate;
    return `
      <div class="hx-card" draggable="true" data-app-id="${a.application_id}">
        <div class="hx-card-top">
          <span class="hx-avatar" style="background:${avatarColor(c.full_name)}">${initials(c.full_name)}</span>
          <div style="min-width:0">
            <div class="hx-card-name">${esc(c.full_name)}</div>
            ${c.headline ? `<div class="hx-card-headline">${esc(c.headline)}</div>` : ""}
          </div>
        </div>
        <div class="hx-card-foot">
          ${c.source ? `<span class="hx-src-chip">${esc(SOURCE_LABEL[c.source] || c.source)}</span>` : ""}
          ${c.has_cv ? `<span class="hx-cv-flag" title="CV on file"><i class="fa-solid fa-paperclip"></i></span>` : ""}
          ${a.ai_score != null ? `<span class="hx-ai-chip" style="--c:${scoreColor(a.ai_score)}">AI ${a.ai_score}</span>` : ""}
          ${starsHtml(a.rating)}
        </div>
      </div>`;
  }

  function wireBoard() {
    els.board.querySelectorAll(".hx-card").forEach((card) => {
      const appId = Number(card.dataset.appId);
      card.addEventListener("click", () => { if (!draggedAppId) openCandDrawer(appId); });
      card.addEventListener("dragstart", (e) => {
        draggedAppId = appId; card.classList.add("is-dragging");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", String(appId)); } catch (_) {}
      });
      card.addEventListener("dragend", () => {
        card.classList.remove("is-dragging");
        setTimeout(() => { draggedAppId = null; }, 0);
      });
    });

    els.board.querySelectorAll(".hx-col").forEach((col) => {
      const stage = col.dataset.stage;
      const body = col.querySelector(".hx-col-body");
      col.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; col.classList.add("is-drop"); });
      col.addEventListener("dragleave", (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove("is-drop"); });
      col.addEventListener("drop", (e) => {
        e.preventDefault(); col.classList.remove("is-drop");
        if (draggedAppId != null) moveApp(draggedAppId, stage);
      });
      body.addEventListener("dragover", (e) => e.preventDefault());
    });
  }

  async function moveApp(appId, stage) {
    const a = apps.find((x) => x.application_id === appId);
    if (!a || a.stage === stage) return;
    const prev = a.stage;
    a.stage = stage;                 // optimistic
    renderBoard();
    try {
      const res = await apiWrite(`/hirex/applications/${appId}`, "PATCH", { stage });
      if (!res.ok) throw new Error();
      activityLoaded = false;        // activity changed
      const name = a.candidate.full_name;
      toast("ok", `${name} → ${STAGE_LABEL[stage]}`);
    } catch {
      a.stage = prev; renderBoard();
      toast("err", "Couldn't move the candidate");
    }
  }

  // --- Tabs ----------------------------------------------------------------
  function switchTab(tab) {
    els.tabs.forEach((t) => t.classList.toggle("is-active", t.dataset.tab === tab));
    ["pipeline", "activity", "about"].forEach((t) => { $(`tab-${t}`).hidden = t !== tab; });
    if (tab === "activity" && !activityLoaded) loadActivity();
  }

  // --- Activity ------------------------------------------------------------
  function renderActivity(events) {
    if (!events.length) { els.activity.innerHTML = `<p class="hx-cell-muted" style="padding:20px 0">No activity yet.</p>`; return; }
    const ICON = {
      created: "fa-plus", updated: "fa-pen", status_changed: "fa-flag",
      duplicated: "fa-copy", candidate_added: "fa-user-plus",
      candidate_moved: "fa-arrows-left-right", candidate_removed: "fa-user-minus",
      candidate_analyzed: "fa-wand-magic-sparkles", scorecard_submitted: "fa-clipboard-check",
    };
    els.activity.innerHTML = events.map((e) => `
      <div class="hx-act-item">
        <div class="hx-act-icon"><i class="fa-solid ${ICON[e.action] || "fa-circle"}"></i></div>
        <div class="hx-act-body">
          <div class="hx-act-text">${actText(e)}</div>
          <div class="hx-act-time">${e.actor_email ? esc(e.actor_email) + " · " : ""}${fmtDateTime(e.created_at)}</div>
        </div>
      </div>`).join("");
  }

  function actText(e) {
    const d = e.detail || {};
    switch (e.action) {
      case "created": return "Job created";
      case "updated": return "Job details updated";
      case "status_changed": return `Status changed <b>${pretty(d.from)}</b> → <b>${pretty(d.to)}</b>`;
      case "duplicated": return `Duplicated from job #${d.source_job_id}`;
      case "candidate_added": return `Added <b>${esc(d.candidate)}</b> to ${pretty(d.stage)}`;
      case "candidate_moved": return `Moved <b>${esc(d.candidate)}</b> ${pretty(d.from)} → ${pretty(d.to)}`;
      case "candidate_removed": return `Removed <b>${esc(d.candidate)}</b> from the pipeline`;
      case "candidate_analyzed": return `AI screened <b>${esc(d.candidate)}</b>${d.score != null ? ` — score ${d.score}` : ""}`;
      case "scorecard_submitted": return `Submitted a scorecard${d.recommendation ? ` — <b>${esc(REC_LABEL[d.recommendation] || d.recommendation)}</b>` : ""}`;
      default: return esc(e.action);
    }
  }

  // --- Add candidate -------------------------------------------------------
  function openAddDrawer() {
    els.addForm.reset();
    els.addStage.value = "applied";
    clearErr(els.addForm);
    openDrawer(els.addScrim, els.addDrawer, () => els.addForm.querySelector('[name="full_name"]').focus());
  }
  function closeAddDrawer() { closeDrawer(els.addScrim, els.addDrawer); }

  async function saveNewCandidate() {
    const f = els.addForm;
    const v = (n) => (f.elements[n] ? f.elements[n].value.trim() : "");
    clearErr(f);
    if (!v("full_name")) { showErr(f, "full_name", "A name is required"); return; }
    const payload = {
      full_name: v("full_name"), email: v("email") || null, phone: v("phone") || null,
      headline: v("headline") || null, location: v("location") || null,
      linkedin_url: v("linkedin_url") || null, source: v("source") || null, stage: v("stage") || "applied",
    };
    els.addSave.disabled = true; els.addSave.textContent = "Adding…";
    try {
      const res = await apiWrite(`/hirex/jobs/${jobId}/candidates`, "POST", payload);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      toast("ok", `Added ${payload.full_name}`);
      closeAddDrawer();
      activityLoaded = false;
      loadPipeline();
    } catch (err) {
      toast("err", err.message || "Couldn't add the candidate");
    } finally {
      els.addSave.disabled = false; els.addSave.textContent = "Add to pipeline";
    }
  }

  // --- Candidate drawer ----------------------------------------------------
  function openCandDrawer(appId) {
    const a = apps.find((x) => x.application_id === appId);
    if (!a) return;
    currentCand = a;
    const c = a.candidate;
    els.candAvatar.textContent = initials(c.full_name);
    els.candAvatar.style.background = avatarColor(c.full_name);
    els.candAvatar.className = "hx-avatar hx-avatar-lg";
    els.candName.textContent = c.full_name;
    els.candSub.textContent = c.headline || "";
    els.candStage.value = a.stage;
    renderStarPicker(a.rating || 0);
    els.candNotes.value = c.notes || "";

    const contact = [];
    if (c.email) contact.push(`<a href="mailto:${esc(c.email)}"><i class="fa-solid fa-envelope"></i>${esc(c.email)}</a>`);
    if (c.phone) contact.push(`<span><i class="fa-solid fa-phone"></i>${esc(c.phone)}</span>`);
    if (c.linkedin_url) contact.push(`<a href="${esc(linkUrl(c.linkedin_url))}" target="_blank" rel="noopener"><i class="fa-brands fa-linkedin"></i>LinkedIn</a>`);
    if (c.location) contact.push(`<span><i class="fa-solid fa-location-dot"></i>${esc(c.location)}</span>`);
    if (c.source) contact.push(`<span><i class="fa-solid fa-signal"></i>${esc(SOURCE_LABEL[c.source] || c.source)}</span>`);
    els.candContact.innerHTML = contact.join("") || `<span class="hx-cell-muted">No contact details</span>`;

    els.candCv.innerHTML = "";
    els.candAi.innerHTML = "";
    els.scorecards.innerHTML = "";
    openDrawer(els.candScrim, els.candDrawer);
    loadAppDetail(appId);
    renderScorecards(appId);
  }
  function closeCandDrawer() { closeDrawer(els.candScrim, els.candDrawer); currentCand = null; currentDetail = null; }

  // --- CV + AI (per application) -------------------------------------------
  let currentDetail = null;
  let cvUploadCandidateId = null;

  async function loadAppDetail(appId) {
    els.candAi.innerHTML = `<div class="hx-ai-loading"><div class="hx-spinner"></div> Loading…</div>`;
    try {
      const res = await fetch(`${API_BASE}/hirex/applications/${appId}`, { credentials: "include" });
      if (!res.ok) throw new Error();
      const detail = await res.json();
      if (!currentCand || currentCand.application_id !== appId) return; // drawer moved on
      currentDetail = detail;
      renderCv(detail.candidate);
      renderAi(detail);
    } catch {
      els.candAi.innerHTML = "";
      renderCv((currentCand && currentCand.candidate) || {});
    }
  }

  function renderCv(c) {
    if (c.has_cv) {
      els.candCv.innerHTML = `
        <div class="hx-cv-box">
          <span class="hx-cv-ic"><i class="fa-solid fa-file-lines"></i></span>
          <div class="hx-cv-info">
            <div class="hx-cv-name">${esc(c.cv_file_name || "CV on file")}</div>
            <div class="hx-cv-sub">On file</div>
          </div>
          <div class="hx-cv-actions">
            <button class="hx-btn hx-btn-ghost" id="hxCvView" type="button">View</button>
            <button class="hx-btn hx-btn-ghost" id="hxCvReplace" type="button">Replace</button>
          </div>
        </div>`;
      $("hxCvView").addEventListener("click", () => viewCv(c.candidate_id));
      $("hxCvReplace").addEventListener("click", () => triggerCvUpload(c.candidate_id));
    } else {
      els.candCv.innerHTML = `
        <div class="hx-cv-empty">
          <span class="hx-cv-ic" style="margin:0 auto"><i class="fa-solid fa-file-arrow-up"></i></span>
          <p>No CV yet. Upload a PDF to enable AI screening.</p>
          <button class="hx-btn hx-btn-soft" id="hxCvUpload" type="button"><i class="fa-solid fa-upload"></i> Upload CV</button>
        </div>`;
      $("hxCvUpload").addEventListener("click", () => triggerCvUpload(c.candidate_id));
    }
  }

  function triggerCvUpload(candidateId) { cvUploadCandidateId = candidateId; els.cvInput.click(); }

  async function uploadCv(candidateId, file) {
    els.candCv.innerHTML = `<div class="hx-ai-loading"><div class="hx-spinner"></div> Uploading &amp; parsing CV…</div>`;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("actor_email", currentUserEmail());
    try {
      const res = await fetch(`${API_BASE}/hirex/candidates/${candidateId}/cv`, {
        method: "POST", credentials: "include",
        headers: { "X-User-Email": currentUserEmail() },
        body: fd,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      toast("ok", body.has_text ? "CV uploaded & parsed" : "CV uploaded");
      if (currentCand) loadAppDetail(currentCand.application_id);
      loadPipeline();
    } catch (err) {
      toast("err", err.message || "Couldn't upload the CV");
      if (currentDetail) renderCv(currentDetail.candidate);
    }
  }

  async function viewCv(candidateId) {
    try {
      const res = await fetch(`${API_BASE}/hirex/candidates/${candidateId}/cv`, { credentials: "include" });
      const body = await res.json();
      if (!res.ok || !body.url) throw new Error();
      window.open(body.url, "_blank", "noopener");
    } catch { toast("err", "Couldn't open the CV"); }
  }

  function renderAi(detail) {
    const a = detail.ai_analysis;
    if (!a) {
      const canAnalyze = detail.candidate && detail.candidate.has_cv;
      els.candAi.innerHTML = `
        <div class="hx-ai-cta">
          <span class="hx-ai-spark"><i class="fa-solid fa-wand-magic-sparkles"></i></span>
          <div class="hx-ai-cta-txt">
            <h4>AI screening</h4>
            <p>${canAnalyze ? "Score this candidate against the job description." : "Upload a CV to enable AI screening."}</p>
          </div>
          <button class="hx-btn hx-btn-primary" id="hxAnalyze" type="button" ${canAnalyze ? "" : "disabled"}>Analyze</button>
        </div>`;
      if (canAnalyze) $("hxAnalyze").addEventListener("click", () => analyze(detail.application_id));
      return;
    }
    els.candAi.innerHTML = aiPanelHtml(a, detail.ai_analyzed_at);
    const re = $("hxReanalyze");
    if (re) re.addEventListener("click", () => analyze(detail.application_id));
  }

  async function analyze(appId) {
    els.candAi.innerHTML = `<div class="hx-ai-loading"><div class="hx-spinner"></div> Analyzing CV against the job… this can take ~15s.</div>`;
    try {
      const res = await apiWrite(`/hirex/applications/${appId}/analyze`, "POST", {});
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      toast("ok", "AI analysis ready");
      if (currentDetail) { currentDetail.ai_analysis = body.ai_analysis; currentDetail.ai_score = body.ai_score; currentDetail.ai_analyzed_at = body.ai_analyzed_at; }
      renderAi(currentDetail || { application_id: appId, ai_analysis: body.ai_analysis, ai_analyzed_at: body.ai_analyzed_at, candidate: { has_cv: true } });
      activityLoaded = false;
      loadPipeline();
    } catch (err) {
      toast("err", err.message || "Analysis failed");
      if (currentDetail) renderAi(currentDetail);
    }
  }

  function aiPanelHtml(a, analyzedAt) {
    const score = clampScore(a._composite_score != null ? a._composite_score : a.match_score);
    const col = scoreColor(score);
    const rec = String(a.recommendation || "hold").toLowerCase();
    const sec = (title, icon, body) => `<div class="hx-ai-sec"><h5><i class="fa-solid ${icon}"></i>${title}</h5>${body}</div>`;

    // Evidence-aware list: items may be plain strings (old) or {point/flag, evidence} (v2).
    const gList = (arr, cls, keyName) => (Array.isArray(arr) && arr.length)
      ? `<ul class="hx-ai-list ${cls || ""}">${arr.map((it) => {
          const point = typeof it === "string" ? it : (it[keyName] || it.point || it.flag || "");
          const ev = (typeof it === "object" && it) ? it.evidence : "";
          const showEv = ev && ev !== "Not found in CV";
          return `<li>${esc(point)}${showEv ? `<span class="hx-ev">“${esc(ev)}”</span>` : ""}</li>`;
        }).join("")}</ul>`
      : `<p class="hx-cell-muted" style="font-size:12.5px;margin:0">—</p>`;
    const skills = (arr, cls, icon) => (Array.isArray(arr) && arr.length)
      ? `<div class="hx-skill-chips">${arr.map((s) => `<span class="hx-skill ${cls}"><i class="fa-solid ${icon}"></i>${esc(s)}</span>`).join("")}</div>` : "";

    // Rubric breakdown
    let rubricHtml = "";
    if (Array.isArray(a._rubric) && a._rubric.length) {
      const byKey = {};
      (a.criteria || []).forEach((c) => { if (c && c.key) byKey[c.key] = c; });
      rubricHtml = sec("Score breakdown", "fa-sliders", a._rubric.map((r) => {
        const c = byKey[r.key] || {};
        const na = !!c.not_applicable;
        const sc = na ? 0 : clampScore(c.score);
        const barCol = na ? "#c7ccd4" : scoreColor(sc);
        const ev = c.evidence && c.evidence !== "Not found in CV" ? `<div class="hx-ev">“${esc(c.evidence)}”</div>` : (c.verdict ? `<div class="hx-crit-verdict">${esc(c.verdict)}</div>` : "");
        return `<div class="hx-crit">
          <div class="hx-crit-head">
            <span class="hx-crit-label">${esc(r.label)} <em>×${r.weight}</em></span>
            <span class="hx-crit-score">${na ? "N/A" : sc}</span>
          </div>
          <div class="hx-crit-bar"><span style="width:${na ? 0 : sc}%;background:${barCol}"></span></div>
          ${ev}
        </div>`;
      }).join(""));
    }

    const meta = [];
    if (a.seniority) meta.push(["Seniority", a.seniority]);
    if (a.years_experience) meta.push(["Experience", a.years_experience]);
    if (a.english_level) meta.push(["English", a.english_level]);
    if (a.leadership) meta.push(["Leadership", a.leadership]);
    const jh = a.job_hopping;
    const jhEv = jh && (jh.evidence || jh.note);

    let html = `
      <div class="hx-ai-head">
        <div class="hx-score-ring" style="--v:${score};--col:${col}"><span class="hx-score-val">${score}<small>/100</small></span></div>
        <div class="hx-ai-verdict">
          <span class="hx-rec hx-rec-${rec}">${recLabel(rec)}</span>
          ${a.recommendation_reason ? `<p class="hx-ai-reason">${esc(a.recommendation_reason)}</p>` : ""}
          <div class="hx-ai-analyzed">Weighted rubric${analyzedAt ? " · analyzed " + fmtDateTime(analyzedAt) : ""}</div>
        </div>
      </div>`;
    if (a.summary) html += `<div class="hx-ai-summary">${esc(a.summary)}</div>`;
    if (meta.length) html += `<div class="hx-ai-meta">${meta.map(([k, v]) => `<div class="m"><span class="k">${k}</span><span class="v">${esc(v)}</span></div>`).join("")}</div>`;
    html += rubricHtml;
    if (jh && jh.detected) html += sec("Job hopping", "fa-person-walking-arrow-right", `<p class="hx-ai-reason" style="margin:0">${esc(jhEv || "Detected")}</p>`);
    html += sec("Strengths", "fa-thumbs-up", gList(a.strengths, "pos", "point"));
    html += sec("Weaknesses", "fa-thumbs-down", gList(a.weaknesses, "neg", "point"));
    if (Array.isArray(a.gaps) && a.gaps.length) html += sec("Gaps vs JD", "fa-circle-half-stroke", gList(a.gaps, "neg", "point"));
    if ((a.matched_skills && a.matched_skills.length) || (a.missing_skills && a.missing_skills.length))
      html += sec("Skills", "fa-code", skills(a.matched_skills, "match", "fa-check") + skills(a.missing_skills, "miss", "fa-xmark"));
    if (Array.isArray(a.red_flags) && a.red_flags.length) html += sec("Red flags", "fa-flag", gList(a.red_flags, "flag", "flag"));
    if (Array.isArray(a.suggested_questions) && a.suggested_questions.length) html += sec("Suggested questions", "fa-comments", gList(a.suggested_questions, "q", "point"));
    html += `<div style="margin-top:14px"><button class="hx-btn hx-btn-ghost" id="hxReanalyze" type="button"><i class="fa-solid fa-rotate"></i> Re-analyze</button></div>`;
    return html;
  }
  function clampScore(v) { const n = Number(v); return isNaN(n) ? 0 : Math.max(0, Math.min(100, Math.round(n))); }
  function scoreColor(s) { return s >= 75 ? "#12a150" : s >= 50 ? "#d99a1c" : "#e0115f"; }
  function recLabel(r) { return { advance: "Advance", hold: "Hold", reject: "Reject" }[r] || cap(r); }

  let pickRating = 0;
  function renderStarPicker(rating) {
    pickRating = rating;
    els.candStars.innerHTML = [1, 2, 3, 4, 5]
      .map((n) => `<i class="fa-solid fa-star${n <= rating ? " on" : ""}" data-n="${n}"></i>`).join("");
    els.candStars.querySelectorAll("i").forEach((star) => {
      star.addEventListener("click", () => {
        const n = Number(star.dataset.n);
        renderStarPicker(n === pickRating ? 0 : n);
      });
    });
  }

  async function saveCandidate() {
    if (!currentCand) return;
    const a = currentCand;
    const newStage = els.candStage.value;
    const newNotes = els.candNotes.value.trim();
    els.candSave.disabled = true; els.candSave.textContent = "Saving…";
    try {
      const r1 = await apiWrite(`/hirex/applications/${a.application_id}`, "PATCH", { stage: newStage, rating: pickRating });
      if (!r1.ok) throw new Error();
      if ((a.candidate.notes || "") !== newNotes) {
        const r2 = await apiWrite(`/hirex/candidates/${a.candidate_id}`, "PATCH", { notes: newNotes || null });
        if (!r2.ok) throw new Error();
      }
      toast("ok", "Saved");
      activityLoaded = false;
      closeCandDrawer();
      loadPipeline();
    } catch {
      toast("err", "Couldn't save changes");
    } finally {
      els.candSave.disabled = false; els.candSave.textContent = "Save";
    }
  }

  async function removeCandidate() {
    if (!currentCand) return;
    const a = currentCand;
    if (!confirm(`Remove ${a.candidate.full_name} from this pipeline?`)) return;
    try {
      const res = await apiWrite(`/hirex/applications/${a.application_id}`, "DELETE", {});
      if (!res.ok) throw new Error();
      toast("ok", `Removed ${a.candidate.full_name}`);
      activityLoaded = false;
      closeCandDrawer();
      loadPipeline();
    } catch { toast("err", "Couldn't remove the candidate"); }
  }

  // --- Scorecards ----------------------------------------------------------
  let scData = { scorecards: [], summary: null };
  let scEditing = null;

  async function renderScorecards(appId) {
    els.scorecards.innerHTML = `<div class="hx-ai-loading"><div class="hx-spinner"></div> Loading evaluations…</div>`;
    try {
      const res = await fetch(`${API_BASE}/hirex/applications/${appId}/scorecards`, { credentials: "include" });
      if (!res.ok) throw new Error();
      const data = await res.json();
      if (!currentCand || currentCand.application_id !== appId) return;
      scData = data;
      drawScorecards();
    } catch { els.scorecards.innerHTML = ""; }
  }

  function drawScorecards() {
    const cards = scData.scorecards || [];
    const sum = scData.summary || {};
    const me = currentUserEmail();
    const mine = cards.find((c) => (c.reviewer_email || "").toLowerCase() === me);

    let html = `<div class="hx-sc-head">
        <h5><i class="fa-solid fa-clipboard-check"></i> Evaluations ${cards.length ? `<span class="hx-sc-count">${cards.length}</span>` : ""}</h5>
        <button class="hx-btn hx-btn-soft" id="hxScAdd" type="button">${mine ? "Edit your evaluation" : "Add your evaluation"}</button>
      </div>`;

    if (!cards.length) {
      html += `<div class="hx-sc-empty">No evaluations yet. Be the first to score this candidate.</div>`;
    } else {
      if (sum.consensus) {
        html += `<div class="hx-sc-consensus">
          <span class="hx-sc-verdict hx-sc-${sum.consensus}">${REC_LABEL[sum.consensus]}</span>
          <span class="hx-sc-avg">consensus · avg ${sum.avg_recommendation}/4 · ${cards.length} reviewer${cards.length > 1 ? "s" : ""}</span>
        </div>`;
      }
      if (Array.isArray(sum.competencies) && sum.competencies.length) {
        html += `<div class="hx-sc-comps">` + sum.competencies.map((c) => `
          <div class="hx-sc-comp">
            <span class="hx-sc-comp-label">${esc(c.competency)}</span>
            <span class="hx-sc-comp-bar"><span style="width:${(c.avg / 4 * 100).toFixed(0)}%"></span></span>
            <span class="hx-sc-comp-val">${c.avg}</span>
          </div>`).join("") + `</div>`;
      }
      html += `<div class="hx-sc-reviewers">` + cards.map((c) => {
        const isMine = (c.reviewer_email || "").toLowerCase() === me;
        return `<div class="hx-sc-rev ${isMine ? "hx-sc-mine" : ""}">
          <span class="hx-sc-rev-email">${esc(c.reviewer_email)}${isMine ? " (you)" : ""}</span>
          ${c.recommendation ? `<span class="hx-sc-verdict hx-sc-${c.recommendation}">${REC_LABEL[c.recommendation]}</span>` : ""}
          ${isMine ? `<button class="hx-sc-rev-edit" type="button" data-edit="1">Edit</button>` : ""}
        </div>`;
      }).join("") + `</div>`;
    }

    els.scorecards.innerHTML = html;
    $("hxScAdd").addEventListener("click", () => openScorecardEditor(mine || null));
    els.scorecards.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => openScorecardEditor(mine || null)));
  }

  function openScorecardEditor(existing) {
    scEditing = { ratings: {}, comments: {}, rec: existing ? existing.recommendation : null,
                  overall: existing ? (existing.overall_comment || "") : "",
                  id: existing ? existing.scorecard_id : null };
    if (existing && Array.isArray(existing.ratings)) {
      existing.ratings.forEach((r) => {
        if (r.rating != null) scEditing.ratings[r.competency] = r.rating;
        if (r.comment) scEditing.comments[r.competency] = r.comment;
      });
    }
    const name = currentDetail && currentDetail.candidate ? currentDetail.candidate.full_name : "candidate";
    els.scTitle.textContent = `Evaluate ${name}`;
    els.scDelete.hidden = !existing;
    buildScorecardForm();
    openDrawer(els.scScrim, els.scDrawer);
  }
  function closeScorecardEditor() { closeDrawer(els.scScrim, els.scDrawer); scEditing = null; }

  function buildScorecardForm() {
    let html = `<p class="hx-cell-muted" style="font-size:12.5px;margin:2px 0 10px">Rate each competency — 1 = Strong No, 4 = Strong Yes. All optional.</p>`;
    html += COMPETENCIES.map((comp) => {
      const sel = scEditing.ratings[comp];
      const scale = [1, 2, 3, 4].map((v) =>
        `<button type="button" data-comp="${esc(comp)}" data-v="${v}" class="${sel === v ? "on" : ""}"><b>${v}</b>${SCALE_LABELS[v]}</button>`).join("");
      return `<div class="hx-sc-crit">
        <div class="hx-sc-crit-label">${esc(comp)}</div>
        <div class="hx-sc-scale">${scale}</div>
        <input class="hx-sc-comment" data-comp-comment="${esc(comp)}" placeholder="Optional note" value="${esc(scEditing.comments[comp] || "")}" />
      </div>`;
    }).join("");
    html += `<div class="hx-sc-overall"><span>Overall recommendation</span><div class="hx-sc-recs">` +
      REC_ORDER.map((r) => `<button type="button" data-rec="${r}" class="${scEditing.rec === r ? "on" : ""}">${REC_LABEL[r]}</button>`).join("") +
      `</div><textarea class="hx-sc-comment" id="hxScOverall" rows="3" placeholder="Overall comments…">${esc(scEditing.overall)}</textarea></div>`;
    els.scBody.innerHTML = html;

    els.scBody.querySelectorAll(".hx-sc-scale button").forEach((b) => b.addEventListener("click", () => {
      const comp = b.dataset.comp, v = Number(b.dataset.v);
      scEditing.ratings[comp] = scEditing.ratings[comp] === v ? null : v;
      b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", Number(x.dataset.v) === scEditing.ratings[comp]));
    }));
    els.scBody.querySelectorAll(".hx-sc-recs button").forEach((b) => b.addEventListener("click", () => {
      scEditing.rec = scEditing.rec === b.dataset.rec ? null : b.dataset.rec;
      b.parentElement.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x.dataset.rec === scEditing.rec));
    }));
  }

  async function saveScorecard() {
    if (!currentCand || !scEditing) return;
    els.scBody.querySelectorAll("[data-comp-comment]").forEach((inp) => {
      const c = inp.dataset.compComment, v = inp.value.trim();
      if (v) scEditing.comments[c] = v; else delete scEditing.comments[c];
    });
    const overallEl = $("hxScOverall");
    scEditing.overall = overallEl ? overallEl.value.trim() : "";
    const ratings = COMPETENCIES
      .map((comp) => ({ competency: comp, rating: scEditing.ratings[comp] || null, comment: scEditing.comments[comp] || null }))
      .filter((r) => r.rating != null || r.comment);

    if (!scEditing.rec && !ratings.length && !scEditing.overall) {
      toast("err", "Add at least a rating or a recommendation");
      return;
    }
    const payload = { recommendation: scEditing.rec || null, overall_comment: scEditing.overall || null, ratings };
    els.scSave.disabled = true; els.scSave.textContent = "Saving…";
    try {
      const res = await apiWrite(`/hirex/applications/${currentCand.application_id}/scorecards`, "POST", payload);
      if (!res.ok) { const b = await res.json().catch(() => ({})); throw new Error(b.error || ""); }
      toast("ok", "Evaluation saved");
      activityLoaded = false;
      closeScorecardEditor();
      renderScorecards(currentCand.application_id);
    } catch (err) {
      toast("err", err.message || "Couldn't save the evaluation");
    } finally {
      els.scSave.disabled = false; els.scSave.textContent = "Save evaluation";
    }
  }

  async function deleteMyScorecard() {
    if (!scEditing || !scEditing.id) return closeScorecardEditor();
    if (!confirm("Delete your evaluation?")) return;
    try {
      const res = await apiWrite(`/hirex/scorecards/${scEditing.id}`, "DELETE", {});
      if (!res.ok) throw new Error();
      toast("ok", "Evaluation deleted");
      const appId = currentCand && currentCand.application_id;
      closeScorecardEditor();
      if (appId) renderScorecards(appId);
    } catch { toast("err", "Couldn't delete the evaluation"); }
  }

  // --- Drawer helpers ------------------------------------------------------
  function openDrawer(scrim, drawer, afterOpen) {
    scrim.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => {
      scrim.classList.add("is-open");
      drawer.classList.add("is-open");
      if (afterOpen) afterOpen();
    });
  }
  function closeDrawer(scrim, drawer) {
    if (drawer.getAttribute("aria-hidden") === "true") return;
    scrim.classList.remove("is-open");
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    setTimeout(() => { scrim.hidden = true; }, 260);
  }
  function showErr(form, key, msg) {
    const em = form.querySelector(`.hx-err[data-err="${key}"]`);
    if (em) { em.textContent = msg; em.closest(".hx-field").classList.add("has-error"); }
  }
  function clearErr(form) {
    form.querySelectorAll(".hx-err").forEach((e) => (e.textContent = ""));
    form.querySelectorAll(".has-error").forEach((e) => e.classList.remove("has-error"));
  }

  // --- HTTP ----------------------------------------------------------------
  function apiWrite(path, method, payload) {
    return fetch(`${API_BASE}${path}`, {
      method, credentials: "include",
      headers: { "Content-Type": "application/json", "X-User-Email": currentUserEmail() },
      body: JSON.stringify({ ...payload, actor_email: currentUserEmail() }),
    });
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
  function starsHtml(rating) {
    if (!rating) return "";
    let s = '<span class="hx-stars">';
    for (let n = 1; n <= 5; n++) s += `<i class="fa-solid fa-star${n <= rating ? " on" : ""}"></i>`;
    return s + "</span>";
  }
  function jobRef(id) { return `HX-${String(id).padStart(4, "0")}`; }
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
  function fmtNum(n) { return n == null ? "—" : Number(n).toLocaleString("en-US"); }
  function pretty(s) { return s ? String(s).replace(/_/g, " ").replace(/\b\w/g, (m) => m.toUpperCase()) : "—"; }
  function cap(s) { return s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : "—"; }
  function fmtDate(iso) { if (!iso) return "—"; const d = new Date(iso); return isNaN(d) ? "—" : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }); }
  function fmtDateTime(iso) { if (!iso) return ""; const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
})();
