const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
const CLOSED_WIN_STAGES = new Set([
  "close win",
  "close won",
  "closed win",
  "closed won",
  "won",
  "closewon",
  "closedwon",
]);
const LOST_STAGES = new Set(["closed lost", "close lost", "lost", "closelost"]);
const STAGE_ORDER = ["Negotiating", "Interviewing", "Sourcing", "Deep Dive", "NDA Sent", "Close Win"];
const STATUS_TRANSLATIONS = [
  { match: "contactado", label: "Contacted" },
  { match: "entrevista", label: "Interviewing" },
  { match: "en revision", label: "Under review" },
  { match: "revision", label: "Under review" },
  { match: "cliente rechaz", label: "Client rejected" },
  { match: "contratad", label: "Hired" },
  { match: "en proceso", label: "In process" },
  { match: "negociacion", label: "Negotiating" },
  { match: "oferta", label: "Offer stage" },
  { match: "pipeline", label: "Pipeline" },
];
const COUNTRY_ALIASES = {
  argentina: "AR",
  brazil: "BR",
  brasil: "BR",
  mexico: "MX",
  colombia: "CO",
  chile: "CL",
  peru: "PE",
  uruguay: "UY",
  paraguay: "PY",
  bolivia: "BO",
  "united states": "US",
  usa: "US",
  canada: "CA",
  spain: "ES",
  portugal: "PT",
  "united kingdom": "GB",
  uk: "GB",
  ireland: "IE",
  france: "FR",
  germany: "DE",
  italy: "IT",
  netherlands: "NL",
};

const els = {
  breadcrumb: document.getElementById("breadcrumbTrail"),
  accountName: document.getElementById("accountName"),
  accountTagline: document.getElementById("accountTagline"),
  metaTimezone: document.getElementById("metaTimezone"),
  metaContact: document.getElementById("metaContact"),
  highlightOpps: document.getElementById("highlightOpportunities"),
  highlightClosed: document.getElementById("highlightClosed"),
  highlightCandidates: document.getElementById("highlightCandidates"),
  opportunityGrid: document.getElementById("opportunityGrid"),
  opportunitiesEmpty: document.getElementById("opportunitiesEmpty"),
  filterControls: document.querySelectorAll(".filters [data-filter]"),
  panel: document.querySelector(".candidate-panel"),
  panelTitle: document.querySelector(".candidate-panel__title"),
  panelBatch: document.querySelector(".candidate-panel__batch"),
  panelBody: document.querySelector(".candidate-panel__body"),
};

const opportunityCache = new Map();
let currentAccount = null;
const panelState = {
  view: "batches",
  selectedBatchId: null,
  opportunityId: null,
  opportunity: null,
};
const pageState = {
  opportunities: [],
  filter: "open",
};

document.addEventListener("DOMContentLoaded", () => {
  const accountId = new URLSearchParams(window.location.search).get("id");
  if (!accountId) {
    showMissingAccountMessage();
    return;
  }

  els.opportunitiesEmpty.textContent = "Loading opportunities…";
  initializePanelControls();
  initializeFilterControls();
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
    const visibleOpportunities = enriched.filter(
      (opp) => classifyOpportunity(opp) !== "lost"
    );
    pageState.opportunities = visibleOpportunities;
    updateHighlights(visibleOpportunities);
    applyOpportunityFilter(pageState.filter);
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

function initializeFilterControls() {
  els.filterControls.forEach((button) => {
    button.addEventListener("click", () => {
      const filter = button.dataset.filter;
      if (!filter || filter === pageState.filter) return;
      applyOpportunityFilter(filter);
    });
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
  els.accountTagline.textContent = "Your Vintti overview is curated for every engagement.";
  els.metaTimezone.textContent = formatLocation(account);
  els.metaContact.textContent = formatContact(account);
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
                  batch_number: batch.batch_number,
                  presentation_date: batch.presentation_date,
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
  const openOpps = list.filter((opp) => classifyOpportunity(opp) === "open");
  const closedOpps = list.filter((opp) => classifyOpportunity(opp) === "closed");
  els.highlightOpps.textContent = padCount(openOpps.length);
  els.highlightClosed.textContent = padCount(closedOpps.length);

  const hiredCandidates = list.reduce((acc, opp) => {
    const hired = collectCandidates(opp).filter(isHiredCandidate);
    return acc + hired.length;
  }, 0);
  els.highlightCandidates.textContent = padCount(hiredCandidates);
}

function applyOpportunityFilter(filter = "open") {
  pageState.filter = filter;
  updateFilterButtons(filter);
  const matches = pageState.opportunities.filter(
    (opp) => classifyOpportunity(opp) === filter
  );
  renderOpportunities(matches, filter);
}

function updateFilterButtons(activeFilter) {
  els.filterControls.forEach((button) => {
    const isActive = button.dataset.filter === activeFilter;
    button.classList.toggle("is-active", Boolean(isActive));
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function renderOpportunities(opportunities, filter) {
  const grid = els.opportunityGrid;
  grid.innerHTML = "";
  if (!Array.isArray(opportunities) || !opportunities.length) {
    els.opportunitiesEmpty.hidden = false;
    els.opportunitiesEmpty.textContent =
      filter === "closed"
        ? "No closed opportunities are ready to showcase yet."
        : "No open opportunities are live for this account yet.";
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

  const statusInfo = getOpportunityStatus(opportunity);
  const timelineInfo = getOpportunityTimeline(opportunity);
  const batchInfo = getLatestBatch(opportunity);
  const candidates = collectCandidates(opportunity);
  const batchLabel = batchInfo
    ? `Batch #${batchInfo.batch_number || "—"}`
    : "Batch in progress";
  const timelineText = timelineInfo.date
    ? `${timelineInfo.label} · ${timelineInfo.date}`
    : timelineInfo.label;

  card.innerHTML = `
    <div class="card-body">
      <div class="card-title">
        <div>
          <p class="eyebrow">${fallbackText(opportunity?.opp_model || "Opportunity", "Opportunity")}</p>
          <h3>${fallbackText(opportunity?.opp_position_name || "Unnamed opportunity", "Unnamed opportunity")}</h3>
        </div>
        <span class="status-pill ${statusInfo.className}">${statusInfo.label}</span>
      </div>
      <ul class="card-meta">
        <li><span>Model</span>${fallbackText(opportunity?.opp_model)}</li>
        <li><span>Stage</span>${fallbackText(opportunity?.opp_stage)}</li>
        <li><span>Comp band</span>${formatSalaryBand(opportunity)}</li>
      </ul>
      <div class="batch-row">
        <div>
          <span class="batch-pill ${batchInfo ? "" : "batch-pill--empty"}">${batchLabel}</span>
          <div class="batch-subtext">${timelineText}</div>
        </div>
        ${renderCandidateCount(candidates.length)}
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

function renderCandidateCount(count) {
  const normalized = Number(count) || 0;
  const padded = padCount(normalized);
  const label = normalized === 1 ? "candidate" : "candidates";
  return `
    <div class="candidate-count" aria-label="${normalized} ${label}">
      <span class="candidate-count__number">${padded}</span>
      <span class="candidate-count__label">${label}</span>
    </div>
  `;
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

function getSortedBatches(opportunity) {
  if (!opportunity || !Array.isArray(opportunity.batches) || !opportunity.batches.length) {
    return [];
  }
  return opportunity.batches.slice().sort((a, b) => {
    const numA = a.batch_number || 0;
    const numB = b.batch_number || 0;
    if (numA !== numB) return numB - numA;
    const dateA = new Date(a.presentation_date || 0);
    const dateB = new Date(b.presentation_date || 0);
    return dateB - dateA;
  });
}

function getLatestBatch(opportunity) {
  const sorted = getSortedBatches(opportunity);
  return sorted.length ? sorted[0] : null;
}

function getOpportunityStatus(opportunity) {
  const classification = classifyOpportunity(opportunity);
  if (classification === "closed") {
    return { label: "Closed", className: "status-pill--closed" };
  }
  return { label: "Open", className: "status-pill--open" };
}

function getOpportunityTimeline(opportunity) {
  const classification = classifyOpportunity(opportunity);
  if (classification === "closed") {
    const closedDate =
      opportunity?.closed_date ||
      opportunity?.opp_closed_date ||
      opportunity?.updated_at ||
      opportunity?.nda_signature_or_start_date;
    return { label: "Closed", date: formatTimelineDate(closedDate) };
  }
  const openDate =
    opportunity?.opp_start_date ||
    opportunity?.nda_signature_or_start_date ||
    opportunity?.created_at ||
    opportunity?.updated_at;
  return { label: "Opened", date: formatTimelineDate(openDate) };
}

function classifyOpportunity(opportunity) {
  const stage = normalizeStage(opportunity?.opp_stage);
  if (LOST_STAGES.has(stage) || stage.includes("lost")) return "lost";
  if (CLOSED_WIN_STAGES.has(stage)) return "closed";
  return "open";
}

function normalizeStage(stage) {
  return normalizeText(stage);
}

function openPanel(opportunityId) {
  const data = opportunityCache.get(String(opportunityId));
  if (!data) return;
  panelState.opportunityId = opportunityId;
  panelState.opportunity = data;
  panelState.view = "batches";
  panelState.selectedBatchId = null;
  const batches = getSortedBatches(data);
  els.panelTitle.textContent = data.opp_position_name || "Opportunity";
  els.panelBatch.textContent = batches.length
    ? `${batches.length} ${batches.length === 1 ? "batch" : "batches"} ready for review`
    : "No batches recorded yet";

  renderBatchList(batches);

  els.panel?.setAttribute("aria-hidden", "false");
  els.panel?.classList.add("is-visible");
  document.body.classList.add("panel-open");
}

function closePanel() {
  els.panel?.classList.remove("is-visible");
  els.panel?.setAttribute("aria-hidden", "true");
  document.body.classList.remove("panel-open");
}

function renderBatchList(batches) {
  els.panelBody.innerHTML = "";
  if (!Array.isArray(batches) || !batches.length) {
    els.panelBody.innerHTML =
      '<p class="candidate-panel__empty">No batches have been curated yet.</p>';
    return;
  }
  batches.forEach((batch) => {
    els.panelBody.appendChild(buildBatchCard(batch));
  });
}

function buildBatchCard(batch) {
  const card = document.createElement("article");
  card.className = "batch-card";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  const candidateCount = (batch?.candidates || []).length;
  const label = candidateCount === 1 ? "candidate" : "candidates";
  const presentation = batch?.presentation_date ? formatDate(batch.presentation_date) : "Date TBD";
  card.innerHTML = `
    <div>
      <p class="eyebrow">Batch #${batch?.batch_number || "—"}</p>
      <p class="batch-card__title">${candidateCount} ${label}</p>
      <p class="batch-card__meta">Presented ${presentation}</p>
    </div>
    <span class="batch-card__cta">Review</span>
  `;
  const openBatch = () => showBatchCandidates(batch);
  card.addEventListener("click", openBatch);
  card.addEventListener("keypress", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openBatch();
    }
  });
  return card;
}

function showBatchCandidates(batch) {
  panelState.view = "candidates";
  panelState.selectedBatchId = batch?.batch_id || null;
  const descriptor = batch?.presentation_date
    ? ` · ${formatDate(batch.presentation_date)}`
    : "";
  els.panelBatch.textContent = `Batch #${batch?.batch_number || "—"}${descriptor}`;
  renderCandidateList(batch);
}

function renderCandidateList(batch) {
  els.panelBody.innerHTML = "";
  els.panelBody.appendChild(buildBackButton());
  const candidates = Array.isArray(batch?.candidates) ? batch.candidates : [];
  if (!candidates.length) {
    const empty = document.createElement("p");
    empty.className = "candidate-panel__empty";
    empty.textContent = "No candidates are assigned to this batch yet.";
    els.panelBody.appendChild(empty);
    return;
  }
  const sorted = candidates.slice().sort((a, b) => {
    const nameA = (a?.name || "").toLowerCase();
    const nameB = (b?.name || "").toLowerCase();
    return nameA.localeCompare(nameB);
  });
  sorted.forEach((candidate) => {
    els.panelBody.appendChild(buildCandidateCard(candidate, batch));
  });
}

function buildBackButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "back-button";
  button.textContent = "Back to batches";
  button.addEventListener("click", () => {
    panelState.view = "batches";
    panelState.selectedBatchId = null;
    const batches = getSortedBatches(panelState.opportunity);
    els.panelBatch.textContent = batches.length
      ? `${batches.length} ${batches.length === 1 ? "batch" : "batches"} ready for review`
      : "No batches recorded yet";
    renderBatchList(batches);
  });
  return button;
}

function buildCandidateCard(candidate, batch) {
  const card = document.createElement("article");
  card.className = "candidate-card";
  const initials = getInitials(candidate?.name || "");
  const resumeUrl = candidate?.candidate_id
    ? `resume-readonly.html?id=${encodeURIComponent(candidate.candidate_id)}`
    : "#";
  const linkedinUrl = normalizeLinkedin(candidate?.linkedin);
  const salaryLabel = candidate?.salary_range ? `$${candidate.salary_range}` : "—";
  const statusRaw = candidate?.batch_status || candidate?.stage || "Batch ready";
  const statusLabel = translateStatus(statusRaw);
  const statusChip = buildStatusChip(statusLabel, statusRaw);
  const countryLabel = formatCandidateCountry(candidate);
  const batchNumber = candidate?.batch_number || batch?.batch_number;

  card.innerHTML = `
    <header>
      <div class="avatar avatar--large" data-initials="${initials}"></div>
      <div>
        <p class="eyebrow candidate-card__batch">${
          batchNumber ? `Batch #${batchNumber}` : "Batch"
        }</p>
        <p class="candidate-name">${fallbackText(candidate?.name, "Unnamed candidate")}</p>
        <p class="candidate-role">${fallbackText(candidate?.stage || candidate?.role || candidate?.title, "Pipeline candidate")}</p>
      </div>
      ${statusChip}
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
  if (key.includes("hire") || key.includes("contrat")) return "status-chip--positive";
  if (key.includes("client") || key.includes("review")) return "status-chip--warm";
  if (key.includes("interview") || key.includes("panel")) return "status-chip--active";
  if (key.includes("sourcing") || key.includes("new")) return "status-chip--cool";
  return "status-chip--neutral";
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

function translateStatus(value) {
  const status = String(value || "").trim();
  if (!status) return "Status pending";
  const normalized = normalizeText(status);
  const match = STATUS_TRANSLATIONS.find((entry) => normalized.includes(entry.match));
  return match ? match.label : status;
}

function buildStatusChip(displayLabel, rawStatus) {
  const cssClass = candidateStatusClass(rawStatus);
  const tooltip = rawStatus || displayLabel;
  return `<span class="status-chip ${cssClass}" title="${escapeHTML(tooltip)}"><span>${escapeHTML(
    displayLabel
  )}</span></span>`;
}

function formatTimelineDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date)) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function padCount(value) {
  return Number(value || 0).toString().padStart(2, "0");
}

function isHiredCandidate(candidate) {
  const status = String(candidate?.batch_status || candidate?.stage || "").toLowerCase();
  return status.includes("hire") || status.includes("contrat");
}

function formatCandidateCountry(candidate) {
  const name =
    (candidate?.country && String(candidate.country).trim()) ||
    (candidate?.country_name && String(candidate.country_name).trim()) ||
    (candidate?.country_code && String(candidate.country_code).trim());
  if (!name) return "Not available";
  const flag = countryToFlag(candidate?.country_code || name);
  if (!flag) return escapeHTML(name);
  return `<span class="country-flag" role="img" aria-label="${escapeHTML(
    name
  )}">${flag}</span><span>${escapeHTML(name)}</span>`;
}

function countryToFlag(value) {
  if (!value) return "";
  const trimmed = String(value).trim();
  if (!trimmed) return "";
  if (trimmed.length === 2) {
    return [...trimmed.toUpperCase()]
      .map((char) => String.fromCodePoint(127397 + char.charCodeAt(0)))
      .join("");
  }
  const normalized = normalizeText(trimmed);
  const alias = COUNTRY_ALIASES[normalized];
  if (!alias) return "";
  return countryToFlag(alias);
}

function escapeHTML(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function normalizeText(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
}
