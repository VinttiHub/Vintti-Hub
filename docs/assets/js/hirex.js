/* =====================================================================
   Hirex ATS — Jobs module (Slice 1)
   Talks to the Flask backend blueprint at /hirex/*.
   ===================================================================== */
(function () {
  "use strict";

  // Resolved by hirex-config.js (loaded first). Fallback keeps the page working
  // if that file is ever missing. See hirex-config.js for the resolution rules.
  const API_BASE = window.HIREX_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1")
      ? "http://localhost:5000"
      : "https://7m6mw95m8y.us-east-2.awsapprunner.com");

  // --- Identity ------------------------------------------------------------
  function currentUserEmail() {
    return (localStorage.getItem("user_email") ||
            sessionStorage.getItem("user_email") || "").toLowerCase().trim();
  }

  // --- Status / priority metadata -----------------------------------------
  const STATUS = {
    draft:    { label: "Draft",    rail: "#4a5566" },
    open:     { label: "Open",     rail: "#8bd33a" },
    on_hold:  { label: "On hold",  rail: "#d99a1c" },
    closed:   { label: "Closed",   rail: "#a11488" },
    archived: { label: "Archived", rail: "#9aa2ad" },
  };
  const PRIORITY = { urgent: "Urgent", high: "High", medium: "Medium", low: "Low" };

  // --- State ---------------------------------------------------------------
  let jobs = [];
  const filters = { status: "", priority: "", q: "" };
  let editingId = null;   // null = create mode
  let searchTimer = null;

  // --- DOM refs ------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  let els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els = {
      search: $("hxSearch"),
      fStatus: $("fStatus"),
      fPriority: $("fPriority"),
      clearFilters: $("hxClearFilters"),
      count: $("hxCount"),
      body: $("hxJobsBody"),
      table: document.querySelector(".hx-table-wrap"),
      loading: $("hxLoading"),
      empty: $("hxEmpty"),
      emptyTitle: $("hxEmptyTitle"),
      emptyText: $("hxEmptyText"),
      error: $("hxError"),
      errorText: $("hxErrorText"),
      newBtn: $("hxNewJob"),
      emptyNew: $("hxEmptyNew"),
      retry: $("hxRetry"),
      scrim: $("hxScrim"),
      drawer: $("hxDrawer"),
      drawerTitle: $("hxDrawerTitle"),
      drawerRef: $("hxDrawerRef"),
      drawerClose: $("hxDrawerClose"),
      form: $("hxForm"),
      cancel: $("hxCancel"),
      saveDraft: $("hxSaveDraft"),
      savePrimary: $("hxSavePrimary"),
      rowMenu: $("hxRowMenu"),
      toasts: $("hxToasts"),
      delScrim: $("hxDelScrim"),
      delName: $("hxDelName"),
      delRef: $("hxDelRef"),
      delInput: $("hxDelInput"),
      delCancel: $("hxDelCancel"),
      delConfirm: $("hxDelConfirm"),
      fromOpp: $("hxFromOpp"),
      oppScrim: $("hxOppScrim"),
      oppSearch: $("hxOppSearch"),
      oppAll: $("hxOppAll"),
      oppList: $("hxOppList"),
      oppCancel: $("hxOppCancel"),
      recruiterSel: $("hxRecruiterSel"),
      hiringSel: $("hxHiringSel"),
    };

    els.newBtn.addEventListener("click", () => openDrawer(null));
    els.emptyNew.addEventListener("click", () => openDrawer(null));

    // Create from an existing CRM opportunity
    els.fromOpp.addEventListener("click", openOppPicker);
    els.oppCancel.addEventListener("click", closeOppPicker);
    els.oppScrim.addEventListener("click", (e) => { if (e.target === els.oppScrim) closeOppPicker(); });
    els.oppAll.addEventListener("change", loadOpportunities);
    els.oppSearch.addEventListener("input", () => {
      clearTimeout(oppTimer);
      oppTimer = setTimeout(loadOpportunities, 280);
    });
    els.retry.addEventListener("click", loadJobs);

    els.fStatus.addEventListener("change", () => { filters.status = els.fStatus.value; syncClear(); loadJobs(); });
    els.fPriority.addEventListener("change", () => { filters.priority = els.fPriority.value; syncClear(); loadJobs(); });
    els.clearFilters.addEventListener("click", clearFilters);
    els.search.addEventListener("input", () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { filters.q = els.search.value.trim(); syncClear(); loadJobs(); }, 280);
    });

    els.drawerClose.addEventListener("click", closeDrawer);
    els.cancel.addEventListener("click", closeDrawer);
    els.scrim.addEventListener("click", closeDrawer);
    els.saveDraft.addEventListener("click", () => saveJob("draft"));
    els.savePrimary.addEventListener("click", () => saveJob(editingId ? null : "open"));

    // Delete confirmation modal
    els.delCancel.addEventListener("click", closeDeleteModal);
    els.delScrim.addEventListener("click", (e) => { if (e.target === els.delScrim) closeDeleteModal(); });
    els.delInput.addEventListener("input", () => {
      els.delConfirm.disabled = els.delInput.value !== "DELETE";
    });
    els.delConfirm.addEventListener("click", performDelete);

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!els.oppScrim.hidden) return closeOppPicker();
      closeRowMenu(); closeDeleteModal(); closeDrawer();
    });
    document.addEventListener("click", (e) => {
      if (!els.rowMenu.hidden && !els.rowMenu.contains(e.target) && !e.target.closest(".hx-row-more")) {
        closeRowMenu();
      }
    });

    loadLeads();
    loadJobs();
  }

  /* =======================================================================
     People — Recruiter and Hiring manager come from the same lists that
     Opportunities uses, so a job can never point at someone who left.
       /users/recruiters  → HR leads    → Recruiter
       /users/sales-leads → sales leads → Hiring manager
     Both endpoints already exclude inactive accounts.
     ======================================================================= */
  let leadsReady = null;   // promise, so the edit drawer can await the options

  function normalizePeople(list) {
    const seen = new Set();
    return (Array.isArray(list) ? list : [])
      .map((p) => {
        const email = String(p.email_vintti || p.email || p.email_work || "").trim().toLowerCase();
        return { email, name: p.user_name || p.name || p.full_name || email };
      })
      .filter((p) => p.email && !seen.has(p.email) && seen.add(p.email))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  function fillPeopleSelect(select, people, placeholder) {
    const current = select.value;
    select.innerHTML = `<option value="">${placeholder}</option>` +
      people.map((p) => `<option value="${esc(p.email)}">${esc(p.name)}</option>`).join("");
    if (current) select.value = current;
  }

  function loadLeads() {
    leadsReady = Promise.all([
      fetch(`${API_BASE}/users/recruiters`, { credentials: "include" }).then((r) => r.json()),
      fetch(`${API_BASE}/users/sales-leads`, { credentials: "include" }).then((r) => r.json()),
    ])
      .then(([recruiters, salesLeads]) => {
        fillPeopleSelect(els.recruiterSel, normalizePeople(recruiters), "Assign a recruiter");
        fillPeopleSelect(els.hiringSel, normalizePeople(salesLeads), "Assign a hiring manager");
      })
      .catch(() => {
        // Never leave the drawer unusable: fall back to free-text emails.
        [els.recruiterSel, els.hiringSel].forEach((sel) => {
          sel.innerHTML = `<option value="">Couldn't load the list</option>`;
        });
        toast("err", "Couldn't load recruiters and sales leads");
      });
    return leadsReady;
  }

  /** A job may point at someone no longer in the list (they left, or the job
   *  came from an old opportunity). Keep the value visible instead of losing it. */
  function ensureOption(select, email) {
    if (!email) return;
    const value = String(email).trim().toLowerCase();
    if ([...select.options].some((o) => o.value === value)) return;
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = `${email} (not in the list)`;
    select.appendChild(opt);
  }

  /* =======================================================================
     Create from an opportunity
     ======================================================================= */
  let oppTimer = null;

  function openOppPicker() {
    els.oppScrim.hidden = false;
    els.oppSearch.value = "";
    els.oppAll.checked = false;
    loadOpportunities();
    setTimeout(() => els.oppSearch.focus(), 30);
  }
  function closeOppPicker() { els.oppScrim.hidden = true; els.oppList.innerHTML = ""; }

  async function loadOpportunities() {
    els.oppList.innerHTML = `<div class="hx-state"><div class="hx-spinner"></div></div>`;
    const p = new URLSearchParams();
    const q = els.oppSearch.value.trim();
    if (q) p.set("q", q);
    if (els.oppAll.checked) p.set("all", "1");
    try {
      const res = await fetch(`${API_BASE}/hirex/opportunities?${p}`, { credentials: "include" });
      if (!res.ok) throw new Error();
      renderOpportunities(await res.json());
    } catch {
      els.oppList.innerHTML = `<p class="hx-opp-empty">Couldn't load opportunities.</p>`;
    }
  }

  function renderOpportunities(rows) {
    if (!rows.length) {
      els.oppList.innerHTML = `<p class="hx-opp-empty">${
        els.oppAll.checked ? "No opportunities match that search."
                           : "No active opportunities. Tick “Include closed deals” to see the rest."
      }</p>`;
      return;
    }
    els.oppList.innerHTML = rows.map((o) => {
      const money = (o.min_salary || o.max_salary)
        ? `${fmtMoney(o.min_salary)}–${fmtMoney(o.max_salary)}` : "";
      const people = [o.recruiter_name || o.opp_hr_lead, o.sales_lead_name || o.opp_sales_lead]
        .filter(Boolean).join(" · ");
      return `
        <div class="hx-opp ${o.existing_job_id ? "is-taken" : ""}" data-id="${o.opportunity_id}"
             data-job="${o.existing_job_id || ""}">
          <div class="hx-opp-main">
            <div class="hx-opp-title">${esc(o.opp_position_name || "Untitled position")}</div>
            <div class="hx-opp-meta">
              ${o.client_name ? `<span class="hx-opp-client">${esc(o.client_name)}</span>` : ""}
              ${o.opp_stage ? `<span class="hx-opp-stage">${esc(o.opp_stage)}</span>` : ""}
              ${money ? `<span>${esc(money)}</span>` : ""}
              ${people ? `<span>${esc(people)}</span>` : ""}
            </div>
          </div>
          ${o.existing_job_id
            ? `<span class="hx-opp-taken">Already in Hirex</span>`
            : `<span class="hx-opp-go"><i class="fa-solid fa-arrow-right"></i></span>`}
        </div>`;
    }).join("");

    els.oppList.querySelectorAll(".hx-opp").forEach((el) => {
      el.addEventListener("click", () => {
        if (el.dataset.job) { location.href = `hirex-job-detail.html?id=${el.dataset.job}`; return; }
        createFromOpportunity(Number(el.dataset.id), el);
      });
    });
  }

  async function createFromOpportunity(opportunityId, rowEl) {
    rowEl.classList.add("is-busy");
    try {
      const res = await apiWrite("/hirex/jobs/from-opportunity", "POST", { opportunity_id: opportunityId });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409 && body.job_id) {
        closeOppPicker();
        location.href = `hirex-job-detail.html?id=${body.job_id}`;
        return;
      }
      if (!res.ok) throw new Error(body.error || "");
      closeOppPicker();
      toast("ok", `Created “${body.title}” from the opportunity`);
      await loadJobs();
      openDrawer(body);          // straight into edit, so gaps get filled now
    } catch (err) {
      rowEl.classList.remove("is-busy");
      toast("err", err.message || "Couldn't create the job");
    }
  }

  function fmtMoney(n) {
    return n == null ? "—" : `$${Number(n).toLocaleString("en-US")}`;
  }

  // --- Data ----------------------------------------------------------------
  function buildQuery() {
    const p = new URLSearchParams();
    if (filters.status) p.set("status", filters.status);
    if (filters.priority) p.set("priority", filters.priority);
    if (filters.q) p.set("q", filters.q);
    const s = p.toString();
    return s ? `?${s}` : "";
  }

  async function loadJobs() {
    showState("loading");
    try {
      const res = await fetch(`${API_BASE}/hirex/jobs${buildQuery()}`, { credentials: "include" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      jobs = await res.json();
      render();
      maybeOpenEditFromUrl();
    } catch (err) {
      els.errorText.textContent = "Something went wrong reaching the server. Try again.";
      showState("error");
    }
  }

  // Deep-link: hirex.html?edit=<id> opens that job's drawer once (e.g. the
  // "Edit" button on the detail page links here).
  let editDeepLinkHandled = false;
  function maybeOpenEditFromUrl() {
    if (editDeepLinkHandled) return;
    const id = Number(new URLSearchParams(location.search).get("edit"));
    if (!id) return;
    editDeepLinkHandled = true;
    const job = jobs.find((j) => j.job_id === id);
    if (job) openDrawer(job);
    history.replaceState(null, "", location.pathname);
  }

  function showState(which) {
    els.loading.hidden = which !== "loading";
    els.error.hidden = which !== "error";
    els.empty.hidden = which !== "empty";
    els.table.style.display = which === "table" ? "" : "none";
  }

  // --- Render --------------------------------------------------------------
  function render() {
    if (!jobs.length) {
      const filtered = filters.status || filters.priority || filters.q;
      els.emptyTitle.textContent = filtered ? "No matching jobs" : "No jobs yet";
      els.emptyText.textContent = filtered
        ? "Try adjusting or clearing your filters."
        : "Open your first vacancy to start building the pipeline.";
      els.emptyNew.style.display = filtered ? "none" : "";
      showState("empty");
      els.count.innerHTML = "";
      return;
    }
    showState("table");
    els.count.innerHTML = `<b>${jobs.length}</b> ${jobs.length === 1 ? "job" : "jobs"}`;
    els.body.innerHTML = jobs.map(rowHtml).join("");

    els.body.querySelectorAll("tr").forEach((tr) => {
      const id = Number(tr.dataset.id);
      tr.addEventListener("click", (e) => {
        if (e.target.closest(".hx-row-more")) return;
        location.href = `hirex-job-detail.html?id=${id}`;
      });
      tr.querySelector(".hx-row-more").addEventListener("click", (e) => {
        e.stopPropagation();
        openRowMenu(e.currentTarget, jobs.find((j) => j.job_id === id));
      });
    });
  }

  function rowHtml(j) {
    const st = STATUS[j.status] || STATUS.draft;
    const prio = (j.priority || "medium").toLowerCase();
    return `
      <tr data-id="${j.job_id}">
        <td class="hx-ref-cell" style="--rail:${st.rail}">
          <span class="hx-ref">${jobRef(j.job_id)}</span>
        </td>
        <td class="hx-col-title">
          <div class="hx-role">
            <span class="hx-prio-dot hx-prio-${prio}" title="${PRIORITY[prio] || "Medium"} priority"></span>
            <span class="hx-role-title">${esc(j.title)}</span>
          </div>
        </td>
        <td>${j.department ? esc(j.department) : dash()}</td>
        <td>${j.location ? esc(j.location) : dash()}</td>
        <td>${j.recruiter_email ? esc(j.recruiter_email) : dash()}</td>
        <td class="hx-col-openings"><span class="hx-openings">${Number(j.openings) || 1}</span></td>
        <td><span class="hx-status hx-status-${j.status}">${st.label}</span></td>
        <td class="hx-col-actions">
          <button class="hx-row-more" aria-label="Actions"><i class="fa-solid fa-ellipsis"></i></button>
        </td>
      </tr>`;
  }

  // --- Row action menu -----------------------------------------------------
  function openRowMenu(anchor, job) {
    closeRowMenu();
    const items = [];
    items.push(mi("edit", "fa-pen", "Edit"));
    items.push(mi("duplicate", "fa-copy", "Duplicate"));
    items.push("<hr>");
    if (job.status !== "open") items.push(mi("open", "fa-play", job.status === "closed" || job.status === "archived" ? "Reopen" : "Mark open"));
    if (job.status === "open") items.push(mi("on_hold", "fa-pause", "Put on hold"));
    if (job.status !== "closed" && job.status !== "archived") items.push(mi("closed", "fa-flag-checkered", "Close"));
    if (job.status !== "archived") items.push(mi("archived", "fa-box-archive", "Archive"));
    items.push("<hr>");
    items.push(mi("delete", "fa-trash-can", "Delete", true));

    els.rowMenu.innerHTML = items.join("");
    els.rowMenu.hidden = false;

    // Position under the anchor, within the app.
    const app = document.getElementById("hirexApp");
    const a = anchor.getBoundingClientRect();
    const base = app.getBoundingClientRect();
    els.rowMenu.style.top = `${a.bottom - base.top + 6}px`;
    els.rowMenu.style.left = `${Math.max(8, a.right - base.left - els.rowMenu.offsetWidth)}px`;

    els.rowMenu.querySelectorAll("button").forEach((b) => {
      b.addEventListener("click", () => handleMenuAction(b.dataset.action, job));
    });
  }
  function mi(action, icon, label, danger) {
    return `<button data-action="${action}" class="${danger ? "hx-danger" : ""}"><i class="fa-solid ${icon}"></i>${label}</button>`;
  }
  function closeRowMenu() { els.rowMenu.hidden = true; els.rowMenu.innerHTML = ""; }

  function handleMenuAction(action, job) {
    closeRowMenu();
    if (action === "edit") return openDrawer(job);
    if (action === "duplicate") return duplicateJob(job);
    if (action === "delete") return openDeleteModal(job);
    return changeStatus(job, action);
  }

  async function duplicateJob(job) {
    try {
      const res = await apiWrite(`/hirex/jobs/${job.job_id}/duplicate`, "POST", {});
      if (!res.ok) throw new Error();
      toast("ok", `Duplicated “${job.title}”`);
      loadJobs();
    } catch { toast("err", "Couldn't duplicate the job"); }
  }

  // --- Delete (type-to-confirm) -------------------------------------------
  let pendingDelete = null;

  function openDeleteModal(job) {
    pendingDelete = job;
    els.delName.textContent = job.title;
    els.delRef.textContent = jobRef(job.job_id);
    els.delInput.value = "";
    els.delConfirm.disabled = true;
    els.delScrim.hidden = false;
    requestAnimationFrame(() => els.delInput.focus());
  }

  function closeDeleteModal() {
    els.delScrim.hidden = true;
    pendingDelete = null;
  }

  async function performDelete() {
    if (!pendingDelete || els.delInput.value !== "DELETE") return;
    const job = pendingDelete;
    els.delConfirm.disabled = true;
    els.delConfirm.textContent = "Deleting…";
    try {
      const res = await apiWrite(`/hirex/jobs/${job.job_id}`, "DELETE", {});
      if (!res.ok) throw new Error();
      toast("ok", `Deleted “${job.title}”`);
      closeDeleteModal();
      loadJobs();
    } catch {
      toast("err", "Couldn't delete the job");
    } finally {
      els.delConfirm.textContent = "Delete job";
    }
  }

  async function changeStatus(job, status) {
    try {
      const res = await apiWrite(`/hirex/jobs/${job.job_id}/status`, "POST", { status });
      if (!res.ok) throw new Error();
      toast("ok", `${esc(job.title)} → ${STATUS[status].label}`);
      loadJobs();
    } catch { toast("err", "Couldn't update the status"); }
  }

  // --- Drawer --------------------------------------------------------------
  function openDrawer(job) {
    closeRowMenu();
    editingId = job ? job.job_id : null;
    clearErrors();
    els.form.reset();

    if (job) {
      els.drawerTitle.textContent = "Edit job";
      els.drawerRef.textContent = jobRef(job.job_id);
      fillForm(job);
      els.saveDraft.style.display = "none";
      els.savePrimary.textContent = "Save changes";
    } else {
      els.drawerTitle.textContent = "New job";
      els.drawerRef.textContent = "New";
      els.saveDraft.style.display = "";
      els.savePrimary.textContent = "Save & open";
      // Open Basics + Job Description on a fresh form (the two that matter most).
      els.form.querySelectorAll(".hx-section").forEach((s, i) => { s.open = i < 2; });
    }

    els.scrim.hidden = false;
    els.drawer.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => {
      els.scrim.classList.add("is-open");
      els.drawer.classList.add("is-open");
      els.form.querySelector('[name="title"]').focus();
    });
  }

  function closeDrawer() {
    if (els.drawer.getAttribute("aria-hidden") === "true") return;
    els.scrim.classList.remove("is-open");
    els.drawer.classList.remove("is-open");
    els.drawer.setAttribute("aria-hidden", "true");
    setTimeout(() => { els.scrim.hidden = true; }, 260);
  }

  async function fillForm(job) {
    const f = els.form;
    const set = (name, val) => { if (f.elements[name]) f.elements[name].value = val ?? ""; };
    ["title", "department", "location", "work_mode", "employment_type", "seniority",
     "language", "salary_min", "salary_max", "salary_currency", "salary_period",
     "priority", "openings",
     "description", "requirements", "benefits"].forEach((k) => set(k, job[k]));
    set("skills", Array.isArray(job.skills) ? job.skills.join(", ") : "");
    set("tags", Array.isArray(job.tags) ? job.tags.join(", ") : "");
    // Reveal sections that carry data so nothing hides silently.
    f.querySelectorAll(".hx-section").forEach((s) => { s.open = true; });

    // The people selects may still be loading; wait, then select — otherwise the
    // assignment lands on an empty <select> and silently drops.
    if (leadsReady) await leadsReady;
    ensureOption(els.recruiterSel, job.recruiter_email);
    ensureOption(els.hiringSel, job.hiring_manager_email);
    set("recruiter_email", (job.recruiter_email || "").toLowerCase());
    set("hiring_manager_email", (job.hiring_manager_email || "").toLowerCase());
  }

  function readForm() {
    const f = els.form;
    const val = (name) => (f.elements[name] ? f.elements[name].value.trim() : "");
    const orNull = (v) => (v === "" ? null : v);
    const num = (name) => { const v = val(name); return v === "" ? null : Number(v); };
    const list = (name) => val(name).split(",").map((s) => s.trim()).filter(Boolean);

    return {
      title: val("title"),
      department: orNull(val("department")),
      location: orNull(val("location")),
      work_mode: orNull(val("work_mode")),
      employment_type: orNull(val("employment_type")),
      seniority: orNull(val("seniority")),
      language: orNull(val("language")),
      salary_min: num("salary_min"),
      salary_max: num("salary_max"),
      salary_currency: orNull(val("salary_currency")),
      salary_period: orNull(val("salary_period")),
      recruiter_email: orNull(val("recruiter_email")),
      hiring_manager_email: orNull(val("hiring_manager_email")),
      priority: orNull(val("priority")) || "medium",
      openings: num("openings") ?? 1,
      description: orNull(val("description")),
      requirements: orNull(val("requirements")),
      benefits: orNull(val("benefits")),
      skills: list("skills"),
      tags: list("tags"),
    };
  }

  function validate(data) {
    clearErrors();
    let ok = true;
    if (!data.title) { setError("title", "A role title is required"); ok = false; }
    if (data.salary_min != null && data.salary_max != null && data.salary_min > data.salary_max) {
      setError("salary", "Min can't be greater than max"); ok = false;
    }
    if (data.openings != null && data.openings < 1) { setError("openings", "At least 1 opening"); ok = false; }
    return ok;
  }

  async function saveJob(statusOverride) {
    const data = readForm();
    if (!validate(data)) {
      // Make sure the section holding the first error is visible.
      const firstErr = els.form.querySelector(".has-error");
      if (firstErr) { const sec = firstErr.closest(".hx-section"); if (sec) sec.open = true; firstErr.scrollIntoView({ block: "center", behavior: "smooth" }); }
      return;
    }
    if (statusOverride) data.status = statusOverride;

    setSaving(true);
    try {
      let res;
      if (editingId) {
        res = await apiWrite(`/hirex/jobs/${editingId}`, "PATCH", data);
      } else {
        res = await apiWrite("/hirex/jobs", "POST", data);
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || "save failed");
      }
      toast("ok", editingId ? "Changes saved" : "Job created");
      closeDrawer();
      loadJobs();
    } catch (err) {
      toast("err", err.message === "save failed" ? "Couldn't save the job" : err.message);
    } finally {
      setSaving(false);
    }
  }

  function setSaving(on) {
    els.savePrimary.disabled = on;
    els.saveDraft.disabled = on;
    els.savePrimary.style.opacity = on ? ".7" : "";
  }

  // --- Errors --------------------------------------------------------------
  function setError(key, msg) {
    const em = els.form.querySelector(`.hx-err[data-err="${key}"]`);
    if (em) { em.textContent = msg; em.closest(".hx-field").classList.add("has-error"); }
  }
  function clearErrors() {
    els.form.querySelectorAll(".hx-err").forEach((e) => (e.textContent = ""));
    els.form.querySelectorAll(".has-error").forEach((e) => e.classList.remove("has-error"));
  }

  // --- Filters -------------------------------------------------------------
  function syncClear() {
    els.clearFilters.hidden = !(filters.status || filters.priority || filters.q);
  }
  function clearFilters() {
    filters.status = ""; filters.priority = ""; filters.q = "";
    els.fStatus.value = ""; els.fPriority.value = ""; els.search.value = "";
    syncClear(); loadJobs();
  }

  // --- HTTP helper ---------------------------------------------------------
  function apiWrite(path, method, payload) {
    return fetch(`${API_BASE}${path}`, {
      method,
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-User-Email": currentUserEmail() },
      body: JSON.stringify({ ...payload, actor_email: currentUserEmail() }),
    });
  }

  // --- Toast ---------------------------------------------------------------
  function toast(kind, msg) {
    const el = document.createElement("div");
    el.className = `hx-toast hx-toast-${kind === "ok" ? "ok" : "err"}`;
    el.innerHTML = `<i class="fa-solid ${kind === "ok" ? "fa-circle-check" : "fa-circle-exclamation"}"></i><span>${msg}</span>`;
    els.toasts.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity .25s, transform .25s";
      el.style.opacity = "0"; el.style.transform = "translateY(6px)";
      setTimeout(() => el.remove(), 260);
    }, 2600);
  }

  // --- Utils ---------------------------------------------------------------
  function jobRef(id) { return `HX-${String(id).padStart(4, "0")}`; }
  function dash() { return `<span class="hx-cell-muted">—</span>`; }
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
})();
