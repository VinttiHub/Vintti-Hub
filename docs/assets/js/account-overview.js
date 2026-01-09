const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
const CLOSED_STAGES = new Set(["close win", "closed lost", "lost", "closewon"]);
const STAGE_ORDER = ["Negotiating", "Interviewing", "Sourcing", "Deep Dive", "NDA Sent", "Close Win", "Closed Lost"];

const els = {
  breadcrumb: document.getElementById("breadcrumbTrail"),
  accountName: document.getElementById("accountName"),
  accountTagline: document.getElementById("accountTagline"),
  metaIndustry: document.getElementById("metaIndustry"),
  metaTimezone: document.getElementById("metaTimezone"),
  metaContact: document.getElementById("metaContact"),
  metaEngagement: document.getElementById("metaEngagement"),
  highlightOpps: document.getElementById("highlightOpportunities"),
  highlightCandidates: document.getElementById("highlightCandidates"),
  highlightSync: document.getElementById("highlightSync"),
  opportunityGrid: document.getElementById("opportunityGrid"),
  opportunitiesEmpty: document.getElementById("opportunitiesEmpty"),
  panel: document.querySelector(".candidate-panel"),
  panelTitle: document.querySelector(".candidate-panel__title"),
  panelBatch: document.querySelector(".candidate-panel__batch"),
  panelBody: document.querySelector(".candidate-panel__body"),
};

const opportunityCache = new Map();
let currentAccount = null;

document.addEventListener("DOMContentLoaded", () => {
  const accountId = new URLSearchParams(window.location.search).get("id");
  if (!accountId) {
    showMissingAccountMessage();
    return;
  }

  els.opportunitiesEmpty.textContent = "Loading opportunities…";
  initializePanelControls();
  hydratePage(accountId);
});

async function hydratePage(accountId) {
  try {
    const [account, opportunities] = await Promise.all([
      fetchJSON(`${API_BASE}/accounts/${accountId}`),
      fetchJSON(`${API_BASE}/accounts/${accountId}/opportunities`),
    ]);

    currentAccount = account;
    updateAccountHeader(account);
    const enriched = await enrichWithBatches(opportunities);
    updateHighlights(enriched);
    renderOpportunities(enriched);
  } catch (error) {
    console.error("Failed to load account overview", error);
    showErrorState("We couldn’t load this overview. Please refresh or try later.");
  }
}

function initializePanelControls() {
  const closeTriggers = document.querySelectorAll("[data-panel-close]");
  closeTriggers.forEach((node) => node.addEventListener("click", closePanel));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && els.panel?.classList.contains("is-visible")) {
      closePanel();
    }
  });
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Request failed ${res.status}: ${text}`);
  }
  return res.json();
}

function showMissingAccountMessage() {
  els.accountName.textContent = "No account selected";
  els.accountTagline.textContent = "Use the Client overview button from Account Details to open this page.";
  els.opportunitiesEmpty.textContent = "Select an account to see its batched candidates.";
}

function showErrorState(message) {
  els.opportunityGrid.innerHTML = "";
  els.opportunitiesEmpty.hidden = false;
  els.opportunitiesEmpty.textContent = message;
}

function updateAccountHeader(account) {
  const clientName = account?.client_name || "Client";
  els.breadcrumb.textContent = `Accounts › ${clientName}`;
  els.accountName.textContent = clientName;
  els.accountTagline.textContent = account?.comments?.trim
    ? account.comments.trim()
    : "Every open search, every curated batch.";

  els.metaIndustry.textContent = fallbackText(account?.industry);
  els.metaTimezone.textContent = formatLocation(account);
  els.metaContact.textContent = formatContact(account);
  els.metaEngagement.textContent = formatEngagement(account);

  const lastTouch = account?.updated_at || account?.created_at;
  els.highlightSync.textContent = formatRelativeDate(lastTouch);
}

function fallbackText(value, placeholder = "Not available") {
  if (typeof value === "number" && !Number.isNaN(value)) return value.toString();
  return value && String(value).trim() ? String(value).trim() : placeholder;
}

function formatLocation(account) {
  const chunks = [account?.city, account?.state, account?.country]
    .filter(Boolean)
    .join(", ");
  const tz = account?.timezone ? account.timezone : "";
  if (!chunks && !tz) return "Not available";
  return [chunks || null, tz || null].filter(Boolean).join(" · ");
}

function formatContact(account) {
  const nameParts = [account?.name, account?.surname].filter(Boolean);
  const email = account?.mail?.trim();
  if (!nameParts.length && !email) return "Not available";
  if (nameParts.length && email) return `${nameParts.join(" ")} · ${email}`;
  return nameParts.join(" ") || email;
}

function formatEngagement(account) {
  const pieces = [account?.type, account?.size].filter((piece) => piece && piece !== "null");
  return pieces.length ? pieces.join(" · ") : "Not available";
}

async function enrichWithBatches(opportunities) {
  const list = Array.isArray(opportunities) ? opportunities : [];
  const stageRank = buildStageRank();
  const sorted = list.slice().sort((a, b) => {
    const rankA = stageRank.get(a?.opp_stage) ?? stageRank.get("__fallback");
    const rankB = stageRank.get(b?.opp_stage) ?? stageRank.get("__fallback");
    if (rankA !== rankB) return rankA - rankB;
    const dateA = new Date(a?.nda_signature_or_start_date || a?.created_at || 0);
    const dateB = new Date(b?.nda_signature_or_start_date || b?.created_at || 0);
    return dateB - dateA;
  });

  const enriched = [];
  for (const opp of sorted) {
    const item = { ...opp, batches: [] };
    try {
      const batches = await fetchJSON(`${API_BASE}/opportunities/${opp.opportunity_id}/batches`);
      if (Array.isArray(batches)) {
        const enrichedBatches = [];
        for (const batch of batches) {
          try {
            const batchCandidates = await fetchJSON(`${API_BASE}/batches/${batch.batch_id}/candidates`);
            const normalizedCandidates = Array.isArray(batchCandidates)
              ? batchCandidates.map((candidate) => ({
                  ...candidate,
                  batch_status: candidate.status || candidate.stage || "",
                }))
              : [];
            enrichedBatches.push({ ...batch, candidates: normalizedCandidates });
          } catch (err) {
            console.error(`Failed to load batch candidates for batch ${batch.batch_id}`, err);
            enrichedBatches.push({ ...batch, candidates: [] });
          }
        }
        item.batches = enrichedBatches;
      }
    } catch (error) {
      console.warn(`Batches not available for opportunity ${opp.opportunity_id}`, error);
    }
    enriched.push(item);
    opportunityCache.set(String(item.opportunity_id), item);
  }
  return enriched;
}

function buildStageRank() {
  const rank = new Map();
  STAGE_ORDER.forEach((stage, index) => rank.set(stage, index));
  rank.set("__fallback", STAGE_ORDER.length + 1);
  return rank;
}

function updateHighlights(opportunities) {
  const list = Array.isArray(opportunities) ? opportunities : [];
  const openOpps = list.filter(
    (opp) => !CLOSED_STAGES.has(String(opp?.opp_stage || "").toLowerCase())
  );
  els.highlightOpps.textContent = openOpps.length.toString().padStart(2, "0");

  const totalCandidates = list.reduce((acc, opp) => acc + collectCandidates(opp).length, 0);
  els.highlightCandidates.textContent = totalCandidates.toString().padStart(2, "0");
}

function renderOpportunities(opportunities) {
  const grid = els.opportunityGrid;
  grid.innerHTML = "";
  if (!Array.isArray(opportunities) || !opportunities.length) {
    els.opportunitiesEmpty.hidden = false;
    els.opportunitiesEmpty.textContent = "No opportunities are live for this account yet.";
    return;
  }

  els.opportunitiesEmpty.hidden = true;
  opportunities.forEach((opp) => {
    const card = buildOpportunityCard(opp);
    grid.appendChild(card);
  });
}

function buildOpportunityCard(opportunity) {
  const card = document.createElement("article");
  card.className = "opportunity-card";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute(
    "aria-label",
    `Open ${opportunity?.opp_position_name || "opportunity"} candidates`
  );
  card.dataset.opportunityId = opportunity?.opportunity_id;

  const stageClass = stageToPillClass(opportunity?.opp_stage);
  const batchInfo = getLatestBatch(opportunity);
  const candidates = collectCandidates(opportunity);
  const batchLabel = batchInfo
    ? `Batch #${batchInfo.batch_number || "—"}`
    : "No batches yet";
  const batchMeta = batchInfo?.presentation_date
    ? formatDate(batchInfo.presentation_date)
    : "Awaiting kickoff";

  card.innerHTML = `
    <div class="card-body">
      <div class="card-title">
        <div>
          <p class="eyebrow">${fallbackText(opportunity?.opp_model || "Opportunity", "Opportunity")}</p>
          <h3>${fallbackText(opportunity?.opp_position_name || "Unnamed opportunity", "Unnamed opportunity")}</h3>
        </div>
        <span class="status-pill ${stageClass}">${fallbackText(opportunity?.opp_stage, "Active")}</span>
      </div>
      <ul class="card-meta">
        <li><span>Model</span>${fallbackText(opportunity?.opp_model)}</li>
        <li><span>Stage</span>${fallbackText(opportunity?.opp_stage)}</li>
        <li><span>Comp band</span>${formatSalaryBand(opportunity)}</li>
      </ul>
      <div class="batch-row">
        <div>
          <span class="batch-pill ${batchInfo ? "" : "batch-pill--empty"}">${batchLabel}</span>
          <div class="batch-subtext">${batchInfo ? batchMeta : "Batch launch in progress"}</div>
        </div>
        ${renderAvatars(candidates)}
      </div>
    </div>
  `;

  const open = () => openPanel(opportunity.opportunity_id);
  card.addEventListener("click", open);
  card.addEventListener("keypress", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });

  return card;
}

function renderAvatars(candidates) {
  if (!candidates.length) {
    return `<span class="batch-empty-text">0 batched</span>`;
  }
  const visible = candidates.slice(0, 3);
  const avatars = visible
    .map((candidate) => {
      const initials = getInitials(candidate.name || "");
      return `<span class="avatar" aria-hidden="true" data-initials="${initials}"></span>`;
    })
    .join("");
  const remainder = Math.max(0, candidates.length - visible.length);
  const remainderNode =
    remainder > 0 ? `<span class="avatar avatar--more">+${remainder}</span>` : "";
  return `<div class="avatars">${avatars}${remainderNode}</div>`;
}

function collectCandidates(opportunity) {
  if (!opportunity || !Array.isArray(opportunity.batches)) return [];
  const map = new Map();
  opportunity.batches.forEach((batch) => {
    (batch?.candidates || []).forEach((candidate) => {
      const existing = map.get(candidate.candidate_id);
      if (!existing || (batch.batch_number || 0) >= (existing.batch_number || 0)) {
        map.set(candidate.candidate_id, {
          ...candidate,
          batch_number: batch.batch_number,
          presentation_date: batch.presentation_date,
        });
      }
    });
  });
  return Array.from(map.values()).sort(
    (a, b) => (b.batch_number || 0) - (a.batch_number || 0)
  );
}

function getLatestBatch(opportunity) {
  if (!opportunity || !Array.isArray(opportunity.batches) || !opportunity.batches.length) {
    return null;
  }
  const sorted = opportunity.batches.slice().sort((a, b) => {
    const numA = a.batch_number || 0;
    const numB = b.batch_number || 0;
    if (numA !== numB) return numB - numA;
    const dateA = new Date(a.presentation_date || 0);
    const dateB = new Date(b.presentation_date || 0);
    return dateB - dateA;
  });
  return sorted[0];
}

function stageToPillClass(stage) {
  const key = String(stage || "").toLowerCase();
  if (key.includes("interview")) return "status-pill--warm";
  if (key.includes("negotiat") || key.includes("contract")) return "status-pill--hot";
  if (key.includes("sourcing") || key.includes("nda") || key.includes("deep")) {
    return "status-pill--cool";
  }
  if (key.includes("closed") || key.includes("lost")) return "status-pill--neutral";
  return "status-pill--neutral";
}

function openPanel(opportunityId) {
  const data = opportunityCache.get(String(opportunityId));
  if (!data) return;
  const candidates = collectCandidates(data);
  els.panelTitle.textContent = data.opp_position_name || "Opportunity";
  const latestBatch = getLatestBatch(data);
  els.panelBatch.textContent = latestBatch
    ? `Batch #${latestBatch.batch_number || "—"} · ${formatDate(latestBatch.presentation_date)}`
    : "No batches recorded yet";

  els.panelBody.innerHTML = "";
  if (!candidates.length) {
    els.panelBody.innerHTML =
      '<p class="candidate-panel__empty">No candidates have been placed into a batch yet.</p>';
  } else {
    candidates.forEach((candidate) => {
      els.panelBody.appendChild(buildCandidateCard(candidate));
    });
  }

  els.panel?.setAttribute("aria-hidden", "false");
  els.panel?.classList.add("is-visible");
  document.body.classList.add("panel-open");
}

function closePanel() {
  els.panel?.classList.remove("is-visible");
  els.panel?.setAttribute("aria-hidden", "true");
  document.body.classList.remove("panel-open");
}

function buildCandidateCard(candidate) {
  const card = document.createElement("article");
  card.className = "candidate-card";
  const initials = getInitials(candidate?.name || "");
  const resumeUrl = candidate?.candidate_id
    ? `resume-readonly.html?id=${encodeURIComponent(candidate.candidate_id)}`
    : "#";
  const linkedinUrl = normalizeLinkedin(candidate?.linkedin);
  const countryLabel = candidate?.country ? `${candidate.country}` : "—";
  const salaryLabel = candidate?.salary_range ? `$${candidate.salary_range}` : "—";
  const statusClass = candidateStatusClass(candidate?.batch_status || candidate?.stage);
  const statusLabel = candidate?.batch_status || candidate?.stage || "Batch ready";

  card.innerHTML = `
    <header>
      <div class="avatar avatar--large" data-initials="${initials}"></div>
      <div>
        <p class="eyebrow candidate-card__batch">${
          candidate.batch_number ? `Batch #${candidate.batch_number}` : "Batch"
        }</p>
        <p class="candidate-name">${fallbackText(candidate?.name, "Unnamed candidate")}</p>
        <p class="candidate-role">${fallbackText(candidate?.stage || candidate?.role || candidate?.title, "Pipeline candidate")}</p>
      </div>
      <span class="status-pill ${statusClass}">${statusLabel}</span>
    </header>
    <ul class="candidate-meta">
      <li><span>Status</span>${fallbackText(statusLabel)}</li>
      <li><span>Expected salary</span>${salaryLabel}</li>
      <li><span>Country</span>${countryLabel}</li>
      <li><span>Email</span>${candidate.email ? `<a href="mailto:${candidate.email}">${candidate.email}</a>` : "—"}</li>
    </ul>
    <div class="candidate-actions">
      <a class="primary" href="${resumeUrl}" target="_blank" rel="noopener">Client resume ↗</a>
      ${
        linkedinUrl
          ? `<a class="ghost" href="${linkedinUrl}" target="_blank" rel="noopener">LinkedIn</a>`
          : ""
      }
    </div>
  `;
  return card;
}

function getInitials(name) {
  const parts = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  if (!parts.length) return "••";
  return parts.map((p) => p[0]?.toUpperCase() || "").join("");
}

function normalizeLinkedin(url) {
  if (!url) return "";
  const trimmed = url.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

function candidateStatusClass(status) {
  const key = String(status || "").toLowerCase();
  if (key.includes("client") || key.includes("review")) return "status-pill--warm";
  if (key.includes("interview") || key.includes("panel")) return "status-pill--hot";
  if (key.includes("sourcing") || key.includes("new")) return "status-pill--cool";
  return "status-pill--neutral";
}

function formatSalaryBand(opportunity) {
  const min = sanitizeCurrency(opportunity?.min_salary);
  const max = sanitizeCurrency(opportunity?.max_salary);
  if (min && max) {
    if (min === max) return formatCurrency(min);
    return `${formatCurrency(min)} – ${formatCurrency(max)}`;
  }
  if (min) return formatCurrency(min);
  if (max) return formatCurrency(max);
  if (opportunity?.salary_range) return opportunity.salary_range;
  return "Align budget";
}

function sanitizeCurrency(value) {
  if (value === null || value === undefined) return null;
  const num = Number(String(value).replace(/[^\d.-]/g, ""));
  return Number.isFinite(num) && num > 0 ? num : null;
}

function formatCurrency(value, currency = "USD") {
  if (!value) return "";
  return Number(value).toLocaleString("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  });
}

function formatDate(value) {
  if (!value) return "TBD";
  const date = new Date(value);
  if (Number.isNaN(date)) return "TBD";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatRelativeDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date)) return "—";
  const now = new Date();
  const diffMs = now - date;
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays <= 0) return "Today";
  if (diffDays === 1) return "1 day ago";
  if (diffDays < 7) return `${diffDays} days ago`;
  if (diffDays < 30) {
    const weeks = Math.round(diffDays / 7);
    return `${weeks}w ago`;
  }
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
