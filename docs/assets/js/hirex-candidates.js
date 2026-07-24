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
      cvInput: $("hxCvInput"), toasts: $("hxToasts"),
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
    els.cvInput.addEventListener("change", () => {
      const f = els.cvInput.files[0];
      if (f && cvUploadCandidateId) uploadCv(cvUploadCandidateId, f);
      els.cvInput.value = "";
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeProfile(); });

    loadCandidates();
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
        <td>${c.source ? `<span class="hx-src-chip">${esc(SOURCE_LABEL[c.source] || c.source)}</span>` : dash()}</td>
        <td class="hx-col-openings">${c.has_cv ? `<i class="fa-solid fa-paperclip hx-cv-flag" title="CV on file"></i>` : dash()}</td>
      </tr>`;
  }

  function jobChips(jobs) {
    if (!Array.isArray(jobs) || !jobs.length) return dash();
    const shown = jobs.slice(0, 2).map((j) => `<span class="hx-job-chip">${esc(j.title)}</span>`);
    if (jobs.length > 2) shown.push(`<span class="hx-job-chip more">+${jobs.length - 2}</span>`);
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

    const contact = [];
    if (c.email) contact.push(`<a href="mailto:${esc(c.email)}"><i class="fa-solid fa-envelope"></i>${esc(c.email)}</a>`);
    if (c.phone) contact.push(`<span><i class="fa-solid fa-phone"></i>${esc(c.phone)}</span>`);
    if (c.linkedin_url) contact.push(`<a href="${esc(linkUrl(c.linkedin_url))}" target="_blank" rel="noopener"><i class="fa-brands fa-linkedin"></i>LinkedIn</a>`);
    if (c.location) contact.push(`<span><i class="fa-solid fa-location-dot"></i>${esc(c.location)}</span>`);
    if (c.source) contact.push(`<span><i class="fa-solid fa-signal"></i>${esc(SOURCE_LABEL[c.source] || c.source)}</span>`);
    els.profContact.innerHTML = contact.join("") || `<span class="hx-cell-muted">No contact details</span>`;

    renderProfCv(c);
    renderProfApps(c);
    openDrawer(els.profScrim, els.profDrawer);
  }
  function closeProfile() { closeDrawer(els.profScrim, els.profDrawer); currentProfile = null; }

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
      els.profCv.innerHTML = `
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
            <div class="hx-app-meta">${esc(STAGE_LABEL[j.stage] || j.stage)}${j.ai_score != null ? ` · AI ${j.ai_score}` : ""}${j.applied_at ? ` · Applied ${fmtDate(j.applied_at)}` : ""}</div>
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
