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
  // Values arrive with mixed casing ("LinkedIn" from the apply form, "Linkedin"
  // from Vintti), so match on lowercase and fall back to what's stored.
  const sourceLabel = (s) =>
    SOURCE_LABEL[String(s || "").toLowerCase()] || String(s || "");

  /* Two different questions share the word "source":
       candidate.source   — where we originally found this person
       application.source — how they got into THIS pipeline
     Showing only the first is what made an imported candidate read "LinkedIn". */
  const APP_SOURCE_LABEL = {
    careers:   "Applied through the apply page",
    linkedin:  "Applied via the LinkedIn link",
    referral:  "Applied via a referral link",
    job_board: "Applied via a job-board link",
    sourced:   "Sourced from LinkedIn",
    vintti:    "Added from Vintti",
    hirex:     "Added from another pipeline",
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
      overview: $("hxOverview"), activity: $("hxActivity"), about: $("hxAbout"),
      addScrim: $("hxAddScrim"), addDrawer: $("hxAddDrawer"), addForm: $("hxAddForm"),
      addStage: $("hxAddStage"), addClose: $("hxAddClose"), addCancel: $("hxAddCancel"), addSave: $("hxAddSave"),
      candScrim: $("hxCandScrim"), candDrawer: $("hxCandDrawer"), candClose: $("hxCandClose"),
      candAvatar: $("hxCandAvatar"), candName: $("hxCandName"), candSub: $("hxCandSub"),
      candStage: $("hxCandStage"), candStars: $("hxCandStars"), candContact: $("hxCandContact"),
      candCv: $("hxCandCv"), cvInput: $("hxCvInput"), candAi: $("hxCandAi"),
      candAnswers: $("hxCandAnswers"), candEdit: $("hxCandEdit"),
      scorecards: $("hxScorecards"),
      scScrim: $("hxScScrim"), scDrawer: $("hxScDrawer"), scTitle: $("hxScTitle"),
      scBody: $("hxScBody"), scClose: $("hxScClose"), scCancel: $("hxScCancel"),
      scSave: $("hxScSave"), scDelete: $("hxScDelete"),
      candNotes: $("hxCandNotes"), candRemove: $("hxCandRemove"), candSave: $("hxCandSave"),
      apply: $("hxApply"),
      peopleSearch: $("hxPeopleSearch"), peopleResults: $("hxPeopleResults"),
      sourceBtn: $("hxSourceBtn"), srcScrim: $("hxSrcScrim"), srcUrl: $("hxSrcUrl"),
      srcStage: $("hxSrcStage"), srcCancel: $("hxSrcCancel"), srcGo: $("hxSrcGo"),
      qScrim: $("hxQScrim"), qDrawer: $("hxQDrawer"), qTitle: $("hxQTitle"), qBody: $("hxQBody"),
      qClose: $("hxQClose"), qCancel: $("hxQCancel"), qSave: $("hxQSave"),
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

    // Reuse someone we already have
    els.peopleSearch.addEventListener("input", () => {
      clearTimeout(peopleTimer);
      peopleTimer = setTimeout(searchPeople, 260);
    });

    // Source from LinkedIn
    els.srcStage.innerHTML = STAGES.map((s) => `<option value="${s.key}">${s.label}</option>`).join("");
    els.sourceBtn.addEventListener("click", openSourceModal);
    els.srcCancel.addEventListener("click", closeSourceModal);
    els.srcScrim.addEventListener("click", (e) => { if (e.target === els.srcScrim) closeSourceModal(); });
    els.srcGo.addEventListener("click", sourceFromLinkedIn);
    els.srcUrl.addEventListener("keydown", (e) => { if (e.key === "Enter") sourceFromLinkedIn(); });

    // Screening-question editor
    els.qClose.addEventListener("click", closeQuestionEditor);
    els.qCancel.addEventListener("click", closeQuestionEditor);
    els.qScrim.addEventListener("click", closeQuestionEditor);
    els.qSave.addEventListener("click", saveQuestion);

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      // Close the top-most open layer first.
      if (!els.srcScrim.hidden) return closeSourceModal();
      if (els.qDrawer.getAttribute("aria-hidden") === "false") return closeQuestionEditor();
      if (els.scDrawer.getAttribute("aria-hidden") === "false") return closeScorecardEditor();
      closeAddDrawer(); closeCandDrawer();
    });

    loadJob();
    loadPipeline();
    loadOverview();
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
      if (!$("tab-apply").hidden) renderApplyTab();   // tab opened before the job landed
    } catch { toast("err", "Couldn't load the job"); }
  }

  async function loadPipeline() {
    overviewLoaded = false;   // data changed → refresh overview on next visit
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
    if (job.opportunity_id) {
      bits.push(`<a class="hx-opp-link" href="opportunity-detail.html?id=${job.opportunity_id}"
                    title="This job came from an opportunity">
                   <i class="fa-solid fa-briefcase"></i>Opportunity #${job.opportunity_id}
                 </a>`);
    }
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
          ${c.source ? `<span class="hx-src-chip">${esc(sourceLabel(c.source))}</span>` : ""}
          ${c.has_cv ? `<span class="hx-cv-flag" title="CV on file"><i class="fa-solid fa-paperclip"></i></span>` : ""}
          ${(a.knockout_flags || []).length ? `<span class="hx-ko-flag" title="Doesn't meet: ${esc((a.knockout_flags || []).join(" · "))}"><i class="fa-solid fa-flag"></i></span>` : ""}
          ${a.ai_score != null ? `<span class="hx-ai-chip" style="--c:${scoreColor(a.ai_score)}">AI ${a.ai_score}</span>` : ""}
          ${consensusChip(a.scorecards)}
          ${starsHtml(a.rating)}
        </div>
      </div>`;
  }

  /** What the interviewers concluded, as a chip on the board card.
   *  Shows the consensus rather than a number: "Yes" is what a human said,
   *  3.0 is an implementation detail. The reviewer count comes along so a
   *  single opinion doesn't read like a verdict. */
  function consensusChip(sc) {
    // A scorecard saved without a recommendation has no verdict yet — show
    // nothing rather than an empty chip.
    if (!sc || !sc.count || !sc.consensus) return "";
    const label = REC_LABEL[sc.consensus] || cap(sc.consensus);
    const title = `${sc.count} evaluation${sc.count > 1 ? "s" : ""} · consensus ${label}`;
    return `<span class="hx-sc-chip hx-sc-${esc(sc.consensus)}" title="${esc(title)}">
              ${esc(label)}${sc.count > 1 ? ` <b>${sc.count}</b>` : ""}
            </span>`;
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
    ["overview", "pipeline", "apply", "activity", "about"].forEach((t) => { $(`tab-${t}`).hidden = t !== tab; });
    if (tab === "activity" && !activityLoaded) loadActivity();
    if (tab === "overview" && !overviewLoaded) loadOverview();
    if (tab === "apply") renderApplyTab();
  }

  // --- Overview ------------------------------------------------------------
  let overviewLoaded = false;

  async function loadOverview() {
    els.overview.innerHTML = `<div class="hx-state"><div class="hx-spinner"></div><p>Loading overview…</p></div>`;
    try {
      const res = await fetch(`${API_BASE}/hirex/jobs/${jobId}/overview`, { credentials: "include" });
      if (!res.ok) throw new Error();
      renderOverview(await res.json());
      overviewLoaded = true;
    } catch {
      els.overview.innerHTML = `<div class="hx-state"><p class="hx-cell-muted">Couldn't load the overview.</p></div>`;
    }
  }

  function renderOverview(o) {
    const kpi = (big, label, sub) =>
      `<div class="hx-ov-card hx-ov-kpi"><div class="hx-ov-big">${big}</div><div class="hx-ov-label">${label}</div>${sub ? `<div class="hx-ov-sub">${sub}</div>` : ""}</div>`;

    // Listing duration
    let durBig = "—", durSub = "";
    const created = o.job && o.job.created_at ? new Date(o.job.created_at) : null;
    if (created && !isNaN(created)) {
      const days = Math.max(0, Math.floor((Date.now() - created.getTime()) / 86400000));
      durBig = `${days}<span style="font-size:15px;font-weight:600"> day${days === 1 ? "" : "s"}</span>`;
      durSub = `Open since ${created.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })}`;
    }
    const t = o.totals || {}, ai = o.ai || {}, sc = o.scorecards || {};

    const kpis = kpi(t.total ?? 0, "Candidates", `<b>${t.today ?? 0}</b> today · ${t.week ?? 0} this week`)
      + kpi(durBig, "Listing duration", durSub)
      + kpi(ai.avg_score != null ? ai.avg_score : "—", "Avg AI score", `${ai.analyzed ?? 0} analyzed`)
      + kpi(sc.count ?? 0, "Evaluations", `${sc.reviewers ?? 0} reviewer${(sc.reviewers ?? 0) === 1 ? "" : "s"}`);

    // Daily chart — fill a 14-day window
    const map = {}; (o.daily || []).forEach((d) => { map[d.date] = d.count; });
    const days = [];
    for (let i = 6; i >= 0; i--) {
      const dt = new Date(); dt.setHours(0, 0, 0, 0); dt.setDate(dt.getDate() - i);
      const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
      days.push({ key, count: map[key] || 0, label: dt.toLocaleDateString("en-US", { month: "short", day: "numeric" }) });
    }
    const maxD = Math.max(1, ...days.map((d) => d.count));
    const chart = days.map((d) => `<span class="hx-ov-daybar" title="${d.label}: ${d.count}"><span style="height:${(d.count / maxD * 100).toFixed(1)}%"></span></span>`).join("");

    // Stage bars
    const stageCounts = o.by_stage || {};
    const maxStage = Math.max(1, ...STAGES.map((s) => stageCounts[s.key] || 0));
    const stageBars = STAGES.map((s) => {
      const n = stageCounts[s.key] || 0;
      return `<div class="hx-ov-bar-row">
        <span class="hx-ov-bar-label"><span class="hx-col-dot" style="background:${s.color}"></span>${s.label}</span>
        <span class="hx-ov-bar"><span style="width:${(n / maxStage * 100).toFixed(1)}%;background:${s.color}"></span></span>
        <span class="hx-ov-bar-n">${n}</span>
      </div>`;
    }).join("");

    // Source bars
    const srcs = o.by_source || [];
    const maxSrc = Math.max(1, ...srcs.map((s) => s.count));
    const srcBars = srcs.length
      ? srcs.map((s) => {
          const label = s.source === "unknown" ? "Unknown" : sourceLabel(s.source);
          return `<div class="hx-ov-bar-row">
            <span class="hx-ov-bar-label">${esc(label)}</span>
            <span class="hx-ov-bar"><span style="width:${(s.count / maxSrc * 100).toFixed(1)}%"></span></span>
            <span class="hx-ov-bar-n">${s.count}</span>
          </div>`;
        }).join("")
      : `<p class="hx-ov-none">No source data yet.</p>`;

    els.overview.innerHTML = `
      <div class="hx-ov-section">
        <h3>Job performance</h3>
        <div class="hx-ov-kpis">${kpis}</div>
        <div class="hx-ov-card">
          <h4>Applications · last 7 days</h4>
          <div class="hx-ov-chart">${chart}</div>
          <div class="hx-ov-chart-foot"><span>${days[0].label}</span><span>Today</span></div>
        </div>
      </div>
      <div class="hx-ov-section">
        <h3>Candidate pipeline</h3>
        <div class="hx-ov-grid2">
          <div class="hx-ov-card"><h4>By stage</h4><div class="hx-ov-bars">${stageBars}</div></div>
          <div class="hx-ov-card"><h4>Sources</h4><div class="hx-ov-bars">${srcBars}</div></div>
        </div>
      </div>`;
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
    els.peopleSearch.value = "";
    els.peopleResults.innerHTML = "";
    clearErr(els.addForm);
    openDrawer(els.addScrim, els.addDrawer, () => els.addForm.querySelector('[name="first_name"]').focus());
  }
  function closeAddDrawer() { closeDrawer(els.addScrim, els.addDrawer); }

  async function saveNewCandidate() {
    const f = els.addForm;
    const v = (n) => (f.elements[n] ? f.elements[n].value.trim() : "");
    clearErr(f);
    if (!v("first_name")) { showErr(f, "first_name", "A first name is required"); return; }
    const payload = {
      first_name: v("first_name"), last_name: v("last_name") || null,
      email: v("email") || null, phone: v("phone") || null,
      headline: v("headline") || null, location: v("location") || null,
      linkedin_url: v("linkedin_url") || null, source: v("source") || null, stage: v("stage") || "applied",
    };
    els.addSave.disabled = true; els.addSave.textContent = "Adding…";
    try {
      const res = await apiWrite(`/hirex/jobs/${jobId}/candidates`, "POST", payload);
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      toast("ok", `Added ${[payload.first_name, payload.last_name].filter(Boolean).join(" ")}`);
      closeAddDrawer();
      activityLoaded = false;
      loadPipeline();
    } catch (err) {
      toast("err", err.message || "Couldn't add the candidate");
    } finally {
      els.addSave.disabled = false; els.addSave.textContent = "Add to pipeline";
    }
  }

  /* =======================================================================
     Reuse a person we already have — from Hirex or from Vintti.
     Same question either way ("do we already have them?"), so one search.
     ======================================================================= */
  let peopleTimer = null;

  async function searchPeople() {
    const q = els.peopleSearch.value.trim();
    if (q.length < 2) { els.peopleResults.innerHTML = ""; return; }
    els.peopleResults.innerHTML = `<div class="hx-people-note">Searching…</div>`;
    try {
      const res = await fetch(
        `${API_BASE}/hirex/people?q=${encodeURIComponent(q)}&job_id=${jobId}`,
        { credentials: "include" });
      if (!res.ok) throw new Error();
      renderPeople(await res.json());
    } catch {
      els.peopleResults.innerHTML = `<div class="hx-people-note">Couldn't search right now.</div>`;
    }
  }

  function renderPeople(people) {
    if (!people.length) {
      els.peopleResults.innerHTML =
        `<div class="hx-people-note">Nobody found — fill the form below to add them.</div>`;
      return;
    }
    els.peopleResults.innerHTML = people.map((p, i) => `
      <button type="button" class="hx-person" data-i="${i}" ${p.in_this_job ? "disabled" : ""}>
        <span class="hx-avatar" style="background:${avatarColor(p.full_name)}">${initials(p.full_name)}</span>
        <span class="hx-person-txt">
          <span class="hx-person-name">${esc(p.full_name)}</span>
          <span class="hx-person-sub">
            ${p.email ? esc(p.email) : ""}${p.headline ? ` · ${esc(p.headline)}` : ""}
          </span>
          ${p.also_in_vintti_as
            ? `<span class="hx-person-aka">In Vintti as “${esc(p.also_in_vintti_as)}”</span>` : ""}
        </span>
        <span class="hx-person-tags">
          ${p.in_this_job
            ? `<span class="hx-person-tag is-in">Already here</span>`
            : `<span class="hx-person-tag hx-person-${p.source}">${p.source === "hirex" ? "Hirex" : "Vintti"}</span>`}
          ${p.source === "hirex" && p.pipelines
            ? `<span class="hx-person-tag">${p.pipelines} pipeline${p.pipelines > 1 ? "s" : ""}</span>` : ""}
          ${p.has_text
            ? `<span class="hx-person-tag is-ai" title="We already have text the AI can score">AI ready</span>` : ""}
        </span>
      </button>`).join("");

    els.peopleResults.querySelectorAll(".hx-person:not([disabled])").forEach((btn) => {
      btn.addEventListener("click", () => addExisting(people[Number(btn.dataset.i)], btn));
    });
  }

  async function addExisting(person, btn) {
    btn.disabled = true;
    btn.classList.add("is-busy");
    try {
      const res = await apiWrite(`/hirex/jobs/${jobId}/candidates/existing`, "POST", {
        source: person.source, id: person.id,
        stage: els.addForm.elements.stage ? els.addForm.elements.stage.value : "applied",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      closeAddDrawer();
      activityLoaded = false;
      await loadPipeline();
      toast("ok", body.text_from
        ? `${body.full_name} added — the AI can score them using ${body.text_from}`
        : `${body.full_name} added`);
      if (body.application_id) openCandDrawer(body.application_id);
    } catch (err) {
      btn.disabled = false;
      btn.classList.remove("is-busy");
      toast("err", err.message || "Couldn't add that person");
    }
  }

  /* =======================================================================
     Source from LinkedIn
     The URL only yields the public slug; the profile itself comes from
     Coresignal, which also gives us the text the AI rubric can score.
     ======================================================================= */
  function openSourceModal() {
    els.srcScrim.hidden = false;
    els.srcUrl.value = "";
    els.srcStage.value = "applied";
    clearErr(els.srcScrim);
    setTimeout(() => els.srcUrl.focus(), 30);
  }
  function closeSourceModal() { els.srcScrim.hidden = true; }

  async function sourceFromLinkedIn() {
    const url = els.srcUrl.value.trim();
    clearErr(els.srcScrim);
    if (!/linkedin\.com\/(in|pub)\//i.test(url)) {
      showErr(els.srcScrim, "url", "Paste a profile link, like linkedin.com/in/janedoe");
      return;
    }

    els.srcGo.disabled = true;
    els.srcGo.textContent = "Looking them up…";
    try {
      const res = await apiWrite(`/hirex/jobs/${jobId}/candidates/from-linkedin`, "POST",
                                 { linkedin_url: url, stage: els.srcStage.value });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "Couldn't add that profile");
      closeSourceModal();
      activityLoaded = false;
      await loadPipeline();
      toast("ok", body.has_profile_text
        ? `${body.full_name} added — profile ready to score`
        : `${body.full_name} added`);
      if (body.application_id) openCandDrawer(body.application_id);
    } catch (err) {
      showErr(els.srcScrim, "url", err.message || "Couldn't add that profile");
    } finally {
      els.srcGo.disabled = false;
      els.srcGo.textContent = "Add to pipeline";
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

    renderContact(c);

    els.candCv.innerHTML = "";
    els.candAnswers.innerHTML = "";
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
      renderAnswers(detail);
      renderAi(detail);
    } catch {
      els.candAi.innerHTML = "";
      renderCv((currentCand && currentCand.candidate) || {});
    }
  }

  /* =======================================================================
     Candidate details — read-only summary that flips into a form.
     Kept collapsed by default: this drawer is mostly for reviewing someone,
     not for data entry, and a wall of inputs would bury the AI and scorecards.
     ======================================================================= */
  const ENGLISH_LEVELS = ["Beginner", "Intermediate", "Advanced", "Fluent", "Native"];
  const EDITABLE_CAND_FIELDS = [
    "first_name", "last_name", "email", "phone", "headline", "current_company",
    "location", "country", "english_level", "linkedin_url", "area",
    "desired_salary", "source",
  ];

  function renderContact(c) {
    const bits = [];
    if (c.email) bits.push(`<a href="mailto:${esc(c.email)}"><i class="fa-solid fa-envelope"></i>${esc(c.email)}</a>`);
    if (c.phone) bits.push(`<span><i class="fa-solid fa-phone"></i>${esc(c.phone)}</span>`);
    if (c.linkedin_url) bits.push(`<a href="${esc(linkUrl(c.linkedin_url))}" target="_blank" rel="noopener"><i class="fa-brands fa-linkedin"></i>LinkedIn</a>`);
    const where = [c.location, c.country].filter(Boolean).join(", ");
    if (where) bits.push(`<span><i class="fa-solid fa-location-dot"></i>${esc(where)}</span>`);
    if (c.current_company) bits.push(`<span><i class="fa-solid fa-building"></i>${esc(c.current_company)}</span>`);
    if (c.english_level) bits.push(`<span><i class="fa-solid fa-language"></i>${esc(c.english_level)}</span>`);
    if (c.source) {
      bits.push(`<span title="Where we originally found this person"><i class="fa-solid fa-signal"></i>Found via ${esc(sourceLabel(c.source))}</span>`);
    }
    // How they landed in this particular pipeline — a different fact.
    const how = currentCand && currentCand.source;
    if (how) {
      bits.push(`<span title="How they entered this pipeline"><i class="fa-solid fa-arrow-right-to-bracket"></i>${
        esc(APP_SOURCE_LABEL[String(how).toLowerCase()] || sourceLabel(how))}</span>`);
    }

    els.candContact.innerHTML =
      (bits.join("") || `<span class="hx-cell-muted">No contact details yet</span>`) +
      `<button type="button" class="hx-cand-editbtn" id="hxCandEditBtn">
         <i class="fa-solid fa-pen"></i> Edit details
       </button>`;
    els.candEdit.hidden = true;
    els.candEdit.innerHTML = "";
    // Toggle: pressing it again collapses the form and drops the edits.
    $("hxCandEditBtn").addEventListener("click", () => {
      if (els.candEdit.hidden) openContactForm(c);
      else renderContact(c);
    });
  }

  function openContactForm(c) {
    const text = (name, label, placeholder = "") => `
      <label class="hx-field">
        <span>${label}</span>
        <input type="text" data-cand="${name}" value="${esc(c[name] || "")}" placeholder="${esc(placeholder)}" />
      </label>`;

    els.candEdit.innerHTML = `
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
      </div>
      <em class="hx-err" data-err="cand"></em>`;
    els.candEdit.hidden = false;
    setEditBtnState($("hxCandEditBtn"), true);
    const first = els.candEdit.querySelector("input");
    if (first) first.focus();
  }

  /** The button says what pressing it will do next. */
  function setEditBtnState(btn, open) {
    if (!btn) return;
    btn.innerHTML = open
      ? `<i class="fa-solid fa-xmark"></i> Cancel edit`
      : `<i class="fa-solid fa-pen"></i> Edit details`;
    btn.classList.toggle("is-open", open);
  }

  /** Only the fields the recruiter actually changed. */
  function readContactForm() {
    if (els.candEdit.hidden || !currentCand) return {};
    const before = currentCand.candidate || {};
    const patch = {};
    EDITABLE_CAND_FIELDS.forEach((name) => {
      const el = els.candEdit.querySelector(`[data-cand="${name}"]`);
      if (!el) return;
      const value = el.value.trim();
      if (value !== String(before[name] ?? "")) patch[name] = value || null;
    });
    return patch;
  }

  /** Screening answers from the public apply page, plus any knockout flags.
   *  Flags are informational: nothing here was auto-rejected. */
  function renderAnswers(detail) {
    const answers = detail.answers || [];
    const flags = (currentCand && currentCand.knockout_flags) || [];
    if (!answers.length && !flags.length) { els.candAnswers.innerHTML = ""; return; }

    const flagBox = flags.length ? `
      <div class="hx-ko-banner">
        <i class="fa-solid fa-flag"></i>
        <div>
          <b>Doesn't meet ${flags.length === 1 ? "a requirement" : `${flags.length} requirements`}</b>
          <span>${flags.map(esc).join(" · ")}</span>
        </div>
      </div>` : "";

    const rows = answers.map((a) => {
      const val = Array.isArray(a.answer) ? a.answer.join(", ") : a.answer;
      return `
        <div class="hx-answer">
          <span class="hx-answer-q">${esc(a.label)}</span>
          <span class="hx-answer-a">${val ? esc(val) : `<em class="hx-cell-muted">No answer</em>`}</span>
        </div>`;
    }).join("");

    els.candAnswers.innerHTML = flagBox + (answers.length
      ? `<div class="hx-answers-box"><h4>Application answers</h4>${rows}</div>` : "");
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
      els.candCv.innerHTML = c.has_text ? `
        <div class="hx-cv-empty">
          <span class="hx-cv-ic" style="margin:0 auto"><i class="fa-brands fa-linkedin"></i></span>
          <p>Sourced from LinkedIn. Their profile stands in for a CV, so AI screening works — upload one if you get it.</p>
          <button class="hx-btn hx-btn-soft" id="hxCvUpload" type="button"><i class="fa-solid fa-upload"></i> Upload CV</button>
        </div>` : `
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
      // A sourced candidate has no CV file but does have their LinkedIn profile
      // as text, which is what the rubric actually reads.
      const c = detail.candidate || {};
      const canAnalyze = !!(c.has_cv || c.has_text);
      els.candAi.innerHTML = `
        <div class="hx-ai-cta">
          <span class="hx-ai-spark"><i class="fa-solid fa-wand-magic-sparkles"></i></span>
          <div class="hx-ai-cta-txt">
            <h4>AI screening</h4>
            <p>${canAnalyze
                  ? `Score this candidate against the job description${!c.has_cv ? ", using their LinkedIn profile" : ""}.`
                  : "Upload a CV to enable AI screening."}</p>
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
    // Anything edited in the details form travels with the notes in one PATCH.
    const candPatch = readContactForm();
    if ((a.candidate.notes || "") !== newNotes) candPatch.notes = newNotes || null;
    if ("first_name" in candPatch && !candPatch.first_name) {
      showErr(els.candEdit, "cand", "A first name is required");
      return;
    }

    els.candSave.disabled = true; els.candSave.textContent = "Saving…";
    try {
      const r1 = await apiWrite(`/hirex/applications/${a.application_id}`, "PATCH", { stage: newStage, rating: pickRating });
      if (!r1.ok) throw new Error();
      if (Object.keys(candPatch).length) {
        const r2 = await apiWrite(`/hirex/candidates/${a.candidate_id}`, "PATCH", candPatch);
        const body = await r2.json().catch(() => ({}));
        if (!r2.ok) throw new Error(body.error || "");
      }
      toast("ok", "Saved");
      activityLoaded = false;
      closeCandDrawer();
      loadPipeline();
    } catch (err) {
      toast("err", err.message || "Couldn't save changes");
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
  /* =======================================================================
     Application form builder (Slice 5)
     Configures what the public apply page asks. The recruiter edits a draft
     here and saves it onto the job as custom_form + knockout_questions.
     ======================================================================= */

  // Mirrors STANDARD_FIELDS in backend/routes/hirex_public_routes.py — that
  // file is the source of truth; keep the keys in sync.
  const APPLY_FIELDS = [
    { key: "first_name",      label: "First name",      locked: true },
    { key: "last_name",       label: "Last name",       locked: true },
    { key: "email",           label: "Email address",   locked: true },
    { key: "phone",           label: "Phone number" },
    { key: "country",         label: "Location",        note: "Country dropdown" },
    { key: "cv",              label: "CV / Resume" },
    { key: "role_position",   label: "Role / position" },
    { key: "area",            label: "Area" },
    { key: "english_level",   label: "English level",   note: "Beginner → Native" },
    { key: "found_via",       label: "How did you find out about this position?",
                              note: "LinkedIn · Referral · Website · Social Media · Other" },
    { key: "linkedin",        label: "LinkedIn profile" },
    { key: "current_company", label: "Current company" },
    { key: "desired_salary",  label: "Desired salary" },
  ];
  const MODES = ["required", "optional", "off"];
  const MODE_LABEL = { required: "Required", optional: "Optional", off: "Off" };

  const Q_TYPES = [
    { key: "short_answer",  label: "Short answer" },
    { key: "paragraph",     label: "Paragraph" },
    { key: "dropdown",      label: "Dropdown" },
    { key: "single_select", label: "Single selection" },
    { key: "multi_select",  label: "Multiple selection" },
    { key: "yes_no",        label: "Yes / No" },
    { key: "number",        label: "Number" },
  ];
  const Q_TYPE_LABEL = Object.fromEntries(Q_TYPES.map((t) => [t.key, t.label]));
  const CHOICE_TYPES = ["dropdown", "single_select", "multi_select"];

  // Each button copies the public link with ?src= already appended, so the
  // recruiter never has to hand-edit a URL. The value lands on the application.
  const SOURCE_TAGS = [
    { key: "linkedin", label: "LinkedIn", icon: "fa-briefcase" },
    { key: "referral", label: "a referral", icon: "fa-user-group" },
    { key: "job_board", label: "a job board", icon: "fa-list" },
  ];

  let draft = null;         // { form: {key:mode}, questions: [...] }
  let draftDirty = false;
  let qEditing = null;      // question being edited in the drawer (null = new)

  // Mirrors DEFAULT_FORM in hirex_public_routes.py — Vintti's usual application.
  function defaultForm() {
    return {
      first_name: "required", last_name: "required", email: "required",
      phone: "required", country: "required", cv: "required",
      role_position: "optional", area: "optional", english_level: "required",
      found_via: "optional", linkedin: "optional",
      current_company: "off", desired_salary: "off",
    };
  }

  function initDraft() {
    const stored = (job && job.custom_form) || {};
    const form = defaultForm();
    Object.keys(form).forEach((k) => {
      if (MODES.includes(stored[k])) form[k] = stored[k];
    });
    APPLY_FIELDS.filter((f) => f.locked).forEach((f) => { form[f.key] = "required"; });
    draft = {
      form,
      questions: Array.isArray(job && job.knockout_questions) ? deepCopy(job.knockout_questions) : [],
    };
    draftDirty = false;
  }

  function renderApplyTab() {
    if (!job) {
      els.apply.innerHTML = `<div class="hx-state"><div class="hx-spinner"></div><p>Loading…</p></div>`;
      return;
    }
    if (!draft) initDraft();

    els.apply.innerHTML = publishHtml() + fieldsHtml() + questionsHtml() + saveBarHtml();
    wireApplyTab();
  }

  function publishHtml() {
    const live = !!(job.published_at && job.public_token);
    const url = job.public_url || "";
    const previewUrl = job.public_token ? `apply.html?t=${job.public_token}` : "";

    if (!live) {
      return `
        <div class="hx-af-pub">
          <div class="hx-af-pub-head">
            <span class="hx-af-dot"></span>
            <div>
              <h3>Not published</h3>
              <p>Publish the job to get a link candidates can apply through.</p>
            </div>
            <button class="hx-btn hx-btn-primary" id="hxPubBtn">
              <i class="fa-solid fa-globe"></i> Publish
            </button>
          </div>
          ${job.status === "draft" ? `<p class="hx-af-note">
            <i class="fa-solid fa-circle-info"></i>
            <span>This job is a draft. Publishing also moves it to Open, so the link works right away.</span>
          </p>` : ""}
        </div>`;
    }

    return `
      <div class="hx-af-pub is-live">
        <div class="hx-af-pub-head">
          <span class="hx-af-dot is-live"></span>
          <div>
            <h3>Live since ${esc(fmtDate(job.published_at))}</h3>
            <p>Anyone with this link can apply.</p>
          </div>
          <button class="hx-btn hx-btn-ghost" id="hxUnpubBtn">Unpublish</button>
        </div>
        <div class="hx-af-link">
          <input type="text" id="hxPubUrl" readonly value="${esc(url)}" />
          <button class="hx-btn hx-btn-ghost" id="hxCopyBtn"><i class="fa-regular fa-copy"></i> Copy</button>
          <a class="hx-btn hx-btn-ghost" id="hxPreviewBtn" href="${esc(previewUrl)}" target="_blank" rel="noopener">
            <i class="fa-solid fa-arrow-up-right-from-square"></i> Preview
          </a>
        </div>
        <p class="hx-af-note">
          <i class="fa-brands fa-linkedin"></i>
          <span>In your LinkedIn post, choose <b>Apply on company website</b> and paste the link there.</span>
        </p>
        <div class="hx-af-sources">
          <span class="hx-af-sources-label">Tag the link so you know where each applicant came from</span>
          <div class="hx-af-source-btns">
            ${SOURCE_TAGS.map((s) => `
              <button type="button" class="hx-af-source" data-src="${s.key}">
                <i class="fa-solid ${s.icon}"></i> Copy for ${s.label}
              </button>`).join("")}
          </div>
        </div>
      </div>`;
  }

  function fieldsHtml() {
    const rows = APPLY_FIELDS.map((f) => {
      const mode = draft.form[f.key] || "off";
      const segs = MODES.map((m) => `
        <button type="button" class="hx-af-seg${mode === m ? " is-on" : ""}${f.locked ? " is-locked" : ""}"
                data-field="${f.key}" data-mode="${m}"${f.locked ? " disabled" : ""}>${MODE_LABEL[m]}</button>`).join("");
      return `
        <div class="hx-af-row">
          <div class="hx-af-row-label">
            <span class="hx-af-row-name">
              ${esc(f.label)}
              ${f.locked ? `<span class="hx-af-lock" title="Always required — we can't build a candidate record without it"><i class="fa-solid fa-lock"></i></span>` : ""}
            </span>
            ${f.note ? `<span class="hx-af-row-note">${esc(f.note)}</span>` : ""}
          </div>
          <div class="hx-af-segs">${segs}</div>
        </div>`;
    }).join("");

    return `
      <section class="hx-af-block">
        <div class="hx-af-block-head">
          <h3>Candidate details</h3>
          <p>What the apply page asks everyone.</p>
        </div>
        <div class="hx-af-rows">${rows}</div>
      </section>`;
  }

  function questionsHtml() {
    const list = draft.questions.length
      ? draft.questions.map(questionRowHtml).join("")
      : `<div class="hx-af-empty">
           No screening questions yet. Add one to ask about work authorization,
           availability, salary expectations — anything the CV won't tell you.
         </div>`;

    return `
      <section class="hx-af-block">
        <div class="hx-af-block-head">
          <h3>Screening questions</h3>
          <p>Asked after the standard fields. Answers show up on the candidate.</p>
          <button class="hx-btn hx-btn-ghost" id="hxAddQ"><i class="fa-solid fa-plus"></i> Add question</button>
        </div>
        <div class="hx-af-qs">${list}</div>
      </section>`;
  }

  function questionRowHtml(q, i) {
    const ko = q.knockout
      ? `<span class="hx-af-ko" title="Applications that fail this get flagged, never auto-rejected">
           <i class="fa-solid fa-flag"></i> Knockout
         </span>`
      : "";
    return `
      <div class="hx-af-q" data-i="${i}">
        <div class="hx-af-q-main">
          <div class="hx-af-q-label">${esc(q.label)}</div>
          <div class="hx-af-q-meta">
            <span class="hx-af-type">${esc(Q_TYPE_LABEL[q.type] || q.type)}</span>
            ${q.required ? `<span class="hx-af-req-chip">Required</span>` : ""}
            ${ko}
            ${(q.options || []).length ? `<span class="hx-af-optcount">${q.options.length} options</span>` : ""}
          </div>
        </div>
        <div class="hx-af-q-actions">
          <button class="hx-icon-btn" data-act="up"   ${i === 0 ? "disabled" : ""} aria-label="Move up"><i class="fa-solid fa-chevron-up"></i></button>
          <button class="hx-icon-btn" data-act="down" ${i === draft.questions.length - 1 ? "disabled" : ""} aria-label="Move down"><i class="fa-solid fa-chevron-down"></i></button>
          <button class="hx-icon-btn" data-act="edit" aria-label="Edit"><i class="fa-solid fa-pen"></i></button>
          <button class="hx-icon-btn" data-act="del"  aria-label="Delete"><i class="fa-solid fa-trash-can"></i></button>
        </div>
      </div>`;
  }

  function saveBarHtml() {
    return `
      <div class="hx-af-savebar${draftDirty ? " is-dirty" : ""}">
        <span class="hx-af-save-note">${draftDirty ? "Unsaved changes" : "All changes saved"}</span>
        <button class="hx-btn hx-btn-primary" id="hxAfSave"${draftDirty ? "" : " disabled"}>Save form</button>
      </div>`;
  }

  function wireApplyTab() {
    const pub = $("hxPubBtn"), unpub = $("hxUnpubBtn"), copy = $("hxCopyBtn");
    if (pub) pub.addEventListener("click", () => setPublished(true));
    if (unpub) unpub.addEventListener("click", () => setPublished(false));
    if (copy) copy.addEventListener("click", () => copyPublicUrl());
    els.apply.querySelectorAll(".hx-af-source").forEach((btn) => {
      btn.addEventListener("click", () => copyPublicUrl(btn.dataset.src, btn));
    });

    els.apply.querySelectorAll(".hx-af-seg:not(.is-locked)").forEach((btn) => {
      btn.addEventListener("click", () => {
        draft.form[btn.dataset.field] = btn.dataset.mode;
        markDirty();
      });
    });

    const addQ = $("hxAddQ");
    if (addQ) addQ.addEventListener("click", () => openQuestionEditor(null));

    els.apply.querySelectorAll(".hx-af-q").forEach((row) => {
      const i = Number(row.dataset.i);
      row.querySelectorAll("[data-act]").forEach((btn) => {
        btn.addEventListener("click", () => questionAction(btn.dataset.act, i));
      });
    });

    const save = $("hxAfSave");
    if (save) save.addEventListener("click", saveApplyForm);
  }

  function markDirty() { draftDirty = true; renderApplyTab(); }

  function questionAction(act, i) {
    const qs = draft.questions;
    if (act === "edit") return openQuestionEditor(i);
    if (act === "del") {
      qs.splice(i, 1);
      return markDirty();
    }
    const j = act === "up" ? i - 1 : i + 1;
    if (j < 0 || j >= qs.length) return;
    [qs[i], qs[j]] = [qs[j], qs[i]];
    markDirty();
  }

  /** Copy the public link, optionally tagged with a source. */
  async function copyPublicUrl(src, btn) {
    const input = $("hxPubUrl");
    if (!input) return;
    const url = src ? `${input.value}&src=${encodeURIComponent(src)}` : input.value;
    try {
      await navigator.clipboard.writeText(url);
    } catch {
      // Clipboard API needs a secure context; fall back to selecting the field.
      input.value = url;
      input.select();
      document.execCommand("copy");
      input.value = url.split("&src=")[0];
    }
    if (btn) {
      const original = btn.innerHTML;
      btn.innerHTML = `<i class="fa-solid fa-check"></i> Copied`;
      btn.classList.add("is-copied");
      setTimeout(() => { btn.innerHTML = original; btn.classList.remove("is-copied"); }, 1600);
    }
    const label = (SOURCE_TAGS.find((s) => s.key === src) || {}).label;
    toast("ok", label ? `Link copied, tagged for ${label}` : "Link copied");
  }

  async function setPublished(on) {
    const btn = $(on ? "hxPubBtn" : "hxUnpubBtn");
    if (btn) { btn.disabled = true; btn.textContent = on ? "Publishing…" : "Unpublishing…"; }
    try {
      const res = await apiWrite(`/hirex/jobs/${jobId}/${on ? "publish" : "unpublish"}`, "POST", {});
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      job = body;
      activityLoaded = false;
      renderHead();
      renderApplyTab();
      toast("ok", on ? "The apply page is live" : "The apply page is offline");
    } catch (err) {
      toast("err", err.message || `Couldn't ${on ? "publish" : "unpublish"} the job`);
      renderApplyTab();
    }
  }

  async function saveApplyForm() {
    const btn = $("hxAfSave");
    if (btn) { btn.disabled = true; btn.textContent = "Saving…"; }
    try {
      const res = await apiWrite(`/hirex/jobs/${jobId}`, "PATCH", {
        custom_form: draft.form,
        knockout_questions: draft.questions,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "");
      job = body;
      activityLoaded = false;
      initDraft();                 // re-sync with what the server actually stored
      renderApplyTab();
      toast("ok", "Form saved");
    } catch (err) {
      toast("err", err.message || "Couldn't save the form");
      renderApplyTab();
    }
  }

  // --- Question editor ------------------------------------------------------
  function openQuestionEditor(index) {
    qEditing = index == null ? null : index;
    const q = index == null ? null : draft.questions[index];
    els.qTitle.textContent = index == null ? "Add question" : "Edit question";
    els.qBody.innerHTML = questionFormHtml(q);
    wireQuestionForm();
    openDrawer(els.qScrim, els.qDrawer, () => {
      const first = els.qBody.querySelector("#hxQLabel");
      if (first) first.focus();
    });
  }

  function closeQuestionEditor() { closeDrawer(els.qScrim, els.qDrawer); qEditing = null; }

  function questionFormHtml(q) {
    const type = (q && q.type) || "short_answer";
    const opts = (q && q.options) || [];
    return `
      <div class="hx-grid" style="padding-top:12px">
        <label class="hx-field hx-col-2">
          <span>Question <b class="hx-req">*</b></span>
          <input type="text" id="hxQLabel" placeholder="Do you have a valid work permit for the US?"
                 value="${esc((q && q.label) || "")}" />
          <em class="hx-err" data-err="label"></em>
        </label>

        <label class="hx-field">
          <span>Format</span>
          <select id="hxQType">
            ${Q_TYPES.map((t) => `<option value="${t.key}"${t.key === type ? " selected" : ""}>${t.label}</option>`).join("")}
          </select>
        </label>

        <label class="hx-field">
          <span>Required</span>
          <select id="hxQReq">
            <option value="">Optional</option>
            <option value="1"${q && q.required ? " selected" : ""}>Required</option>
          </select>
        </label>

        <label class="hx-field hx-col-2">
          <span>Help text</span>
          <input type="text" id="hxQHelp" placeholder="Shown in small print under the question"
                 value="${esc((q && q.help) || "")}" />
        </label>

        <label class="hx-field hx-col-2" id="hxQOptsWrap" ${CHOICE_TYPES.includes(type) ? "" : "hidden"}>
          <span>Options <b class="hx-req">*</b></span>
          <textarea id="hxQOpts" rows="4" placeholder="One per line&#10;Yes, immediately&#10;Within 30 days&#10;Not available">${esc(opts.join("\n"))}</textarea>
          <em class="hx-err" data-err="options"></em>
        </label>

        <div class="hx-field hx-col-2" id="hxQKoWrap">
          <span>Knockout rule</span>
          <div class="hx-af-ko-box">
            <label class="hx-af-ko-toggle">
              <input type="checkbox" id="hxQKoOn" ${q && q.knockout ? "checked" : ""} />
              <span>Flag applicants who don't answer this the way you need</span>
            </label>
            <div id="hxQKoDetail" ${q && q.knockout ? "" : "hidden"}></div>
            <p class="hx-af-ko-help">
              Flagged applications still land in <b>Applied</b> with a red marker — Hirex never
              rejects anyone on its own.
            </p>
          </div>
        </div>
      </div>`;
  }

  function wireQuestionForm() {
    const typeSel = $("hxQType");
    typeSel.addEventListener("change", () => {
      $("hxQOptsWrap").hidden = !CHOICE_TYPES.includes(typeSel.value);
      renderKoDetail();
    });
    $("hxQOpts").addEventListener("input", renderKoDetail);
    $("hxQKoOn").addEventListener("change", () => {
      $("hxQKoDetail").hidden = !$("hxQKoOn").checked;
      renderKoDetail();
    });
    renderKoDetail();
  }

  /** The knockout control depends on the question format — a Yes/No needs a
   *  Yes-or-No expectation, a number needs a minimum, and free text can't be
   *  matched reliably, so it gets no rule at all. */
  function renderKoDetail() {
    const box = $("hxQKoDetail"), on = $("hxQKoOn");
    if (!box) return;
    const type = $("hxQType").value;
    const existing = qEditing != null ? (draft.questions[qEditing] || {}).knockout : null;

    if (!CHOICE_TYPES.includes(type) && type !== "yes_no" && type !== "number") {
      on.checked = false;
      on.disabled = true;
      box.hidden = true;
      box.innerHTML = "";
      box.closest(".hx-af-ko-box").querySelector(".hx-af-ko-toggle span").textContent =
        "Free-text answers can't be matched automatically";
      return;
    }
    on.disabled = false;
    box.closest(".hx-af-ko-box").querySelector(".hx-af-ko-toggle span").textContent =
      "Flag applicants who don't answer this the way you need";
    if (!on.checked) { box.hidden = true; return; }
    box.hidden = false;

    if (type === "number") {
      box.innerHTML = `
        <div class="hx-af-ko-rule">
          <span>Flag unless the answer is at least</span>
          <input type="number" id="hxQKoVal" step="any"
                 value="${esc(existing && existing.op === "min" ? existing.value : "")}" />
        </div>`;
      return;
    }

    const options = type === "yes_no"
      ? ["Yes", "No"]
      : ($("hxQOpts").value || "").split("\n").map((s) => s.trim()).filter(Boolean);

    if (!options.length) {
      box.innerHTML = `<p class="hx-af-ko-warn">Add the options above first.</p>`;
      return;
    }
    const multi = type === "multi_select";
    const current = existing ? existing.value : null;
    const currentList = Array.isArray(current) ? current : (current != null ? [current] : []);
    box.innerHTML = `
      <div class="hx-af-ko-rule">
        <span>${multi ? "Flag unless they select at least one of" : "Flag unless the answer is"}</span>
        ${multi
          ? `<div class="hx-af-ko-multi" id="hxQKoMulti">${options.map((o) => `
              <label><input type="checkbox" value="${esc(o)}"${currentList.includes(o) ? " checked" : ""} /> ${esc(o)}</label>`).join("")}</div>`
          : `<select id="hxQKoVal">${options.map((o) =>
              `<option value="${esc(o)}"${currentList[0] === o ? " selected" : ""}>${esc(o)}</option>`).join("")}</select>`}
      </div>`;
  }

  function saveQuestion() {
    clearErr(els.qBody);
    const label = $("hxQLabel").value.trim();
    const type = $("hxQType").value;
    if (!label) return showErr(els.qBody, "label", "Write the question first.");

    const q = {
      id: (qEditing != null && draft.questions[qEditing] && draft.questions[qEditing].id) || null,
      type,
      label,
      help: $("hxQHelp").value.trim() || null,
      required: $("hxQReq").value === "1",
    };

    if (CHOICE_TYPES.includes(type)) {
      q.options = ($("hxQOpts").value || "").split("\n").map((s) => s.trim()).filter(Boolean);
      if (q.options.length < 2) return showErr(els.qBody, "options", "Give it at least two options.");
    }

    const koOn = $("hxQKoOn");
    if (koOn && koOn.checked && !koOn.disabled) {
      if (type === "number") {
        const v = ($("hxQKoVal") || {}).value;
        if (v !== "" && v != null) q.knockout = { op: "min", value: Number(v) };
      } else if (type === "multi_select") {
        const picked = Array.from(document.querySelectorAll("#hxQKoMulti input:checked")).map((i) => i.value);
        if (picked.length) q.knockout = { op: "includes", value: picked };
      } else {
        const v = ($("hxQKoVal") || {}).value;
        if (v) q.knockout = { op: "equals", value: v };
      }
    }

    if (qEditing == null) draft.questions.push(q);
    else draft.questions[qEditing] = q;

    closeQuestionEditor();
    markDirty();
  }

  function deepCopy(v) { return JSON.parse(JSON.stringify(v)); }

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
    if (!em) return;
    em.textContent = msg;
    // Not every error message sits inside a field wrapper.
    const field = em.closest(".hx-field");
    if (field) field.classList.add("has-error");
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
