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

const NEW_YORK_TIMEZONE = "America/New_York";

const els = {
  breadcrumb: document.getElementById("breadcrumbTrail"),
  accountName: document.getElementById("accountName"),
  accountTagline: document.getElementById("accountTagline"),
  metaTimezone: document.getElementById("metaTimezone"),
  metaContact: document.getElementById("metaContact"),
  metaRefreshedAt: document.getElementById("metaRefreshedAt"),
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
  refreshButton: document.getElementById("refreshOverview"),
  refreshOverlay: document.getElementById("refreshOverlay"),
  refreshProgressBar: document.getElementById("refreshProgressBar"),
  refreshProgressLabel: document.getElementById("refreshProgressLabel"),
};

const opportunityCache = new Map();
const candidateTestsCache = new Map();
const candidateTestsRequests = new Map();
let currentAccount = null;
const panelState = {
  view: "candidates",
  selectedBatchId: null,
  opportunityId: null,
  opportunity: null,
};
const pageState = {
  opportunities: [],
  filter: "open",
  accountId: null,
  snapshotCache: new Map(),
  lastRefreshedAt: null,
  refreshing: false,
};
const REFRESH_PROGRESS_DEFAULT_LABEL = "Preparing sync…";

document.addEventListener("DOMContentLoaded", () => {
  const accountId = new URLSearchParams(window.location.search).get("id");
  if (!accountId) {
    showMissingAccountMessage();
    return;
  }

  els.opportunitiesEmpty.textContent = "Loading opportunities…";
  initializePanelControls();
  initializeFilterControls();
  initializeRefreshControls();
  pageState.accountId = accountId;
  hydratePage(accountId);
});

async function hydratePage(accountId) {
  try {
    const [account, snapshotPayload] = await Promise.all([
      fetchJSON(`${API_BASE}/accounts/${accountId}`),
      fetchOverviewSnapshotCache(accountId),
    ]);

    currentAccount = account;
    updateAccountHeader(account);
    pageState.snapshotCache = snapshotPayload.cache;
    pageState.lastRefreshedAt = snapshotPayload.updatedAt ?? null;
    updateRefreshMeta(pageState.lastRefreshedAt);
    const hydratedOpportunities = buildOpportunitiesFromSnapshots(snapshotPayload.cache);
    const visibleOpportunities = hydratedOpportunities.filter(
      (opp) => classifyOpportunity(opp) !== "lost"
    );
    pageState.opportunities = visibleOpportunities;
    syncOpportunityCache(visibleOpportunities);
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

function initializeRefreshControls() {
  if (!els.refreshButton) return;
  els.refreshButton.dataset.defaultLabel = els.refreshButton.textContent.trim() || "Refresh data";
  if (els.refreshProgressLabel && !els.refreshProgressLabel.dataset.defaultLabel) {
    els.refreshProgressLabel.dataset.defaultLabel =
      els.refreshProgressLabel.textContent.trim() || REFRESH_PROGRESS_DEFAULT_LABEL;
  }
  els.refreshButton.addEventListener("click", handleRefreshClick);
}

function setRefreshState(isRefreshing) {
  pageState.refreshing = Boolean(isRefreshing);
  if (els.refreshButton) {
    if (isRefreshing) {
      els.refreshButton.disabled = true;
      els.refreshButton.textContent = "Refreshing…";
    } else {
      els.refreshButton.disabled = false;
      els.refreshButton.textContent = els.refreshButton.dataset.defaultLabel || "Refresh data";
    }
  }
  if (isRefreshing) {
    resetRefreshProgress();
  } else {
    setTimeout(resetRefreshProgress, 400);
  }
  toggleRefreshOverlay(pageState.refreshing);
}

function resetRefreshProgress() {
  updateRefreshProgress(0, REFRESH_PROGRESS_DEFAULT_LABEL, true);
}

function updateRefreshProgress(value, message, forceLabel = false) {
  const progressValue = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  const percent = Math.round(progressValue * 100);
  if (els.refreshProgressBar) {
    const bar = els.refreshProgressBar.querySelector("span");
    if (bar) {
      bar.style.width = `${progressValue * 100}%`;
    }
    els.refreshProgressBar.setAttribute("aria-valuenow", String(percent));
  }
  if ((message || forceLabel) && els.refreshProgressLabel) {
    els.refreshProgressLabel.textContent =
      message || els.refreshProgressLabel.dataset.defaultLabel || REFRESH_PROGRESS_DEFAULT_LABEL;
  }
}

function toggleRefreshOverlay(isVisible) {
  const overlay = els.refreshOverlay;
  if (!overlay) return;
  const show = Boolean(isVisible);
  overlay.classList.toggle("is-visible", show);
  overlay.setAttribute("aria-hidden", show ? "false" : "true");
  document.body.classList.toggle("refresh-active", show);
}

async function handleRefreshClick() {
  if (pageState.refreshing || !pageState.accountId) return;
  const refreshTimestamp = getNewYorkTimestampISO();
  setRefreshState(true);
  updateRefreshProgress(0.05, "Fetching live opportunities…");
  try {
    const opportunities = await fetchJSON(`${API_BASE}/accounts/${pageState.accountId}/opportunities`);
    const list = Array.isArray(opportunities) ? opportunities : [];
    if (!list.length) {
      console.info("No opportunities to refresh for this account");
      updateRefreshProgress(0.6, "No open opportunities found for this refresh.");
    } else {
      updateRefreshProgress(0.2, `Syncing ${list.length} ${list.length === 1 ? "opportunity" : "opportunities"}…`);
      const progressWindow = { start: 0.2, end: 0.78 };
      const { snapshotsToPersist } = await enrichWithBatches(list, pageState.snapshotCache, {
        forceRefreshClosed: true,
        persistStages: ["open", "closed"],
        refreshTimestamp,
        onProgress: ({ completed, total, message }) => {
          const ratio = total ? completed / total : 1;
          const value =
            progressWindow.start + ratio * Math.max(0, progressWindow.end - progressWindow.start);
          updateRefreshProgress(value, message);
        },
      });
      if (snapshotsToPersist.length) {
        updateRefreshProgress(0.82, "Saving refreshed batches…");
        await persistOverviewSnapshots(pageState.accountId, snapshotsToPersist);
        updateRefreshProgress(0.88, "Cached overview updated.");
      } else {
        console.info("Opportunity cache already up to date");
        updateRefreshProgress(0.85, "Cache already up to date.");
      }
    }
    updateRefreshProgress(0.9, "Pruning inactive hires…");
    await pruneInactiveOverviewSnapshots(pageState.accountId);
  } catch (error) {
    console.error("Failed to refresh cached opportunities", error);
    updateRefreshProgress(0.85, "Something went wrong. Retrying state…");
  } finally {
    try {
      updateRefreshProgress(0.92, "Rebuilding overview…");
      await hydratePage(pageState.accountId);
      updateRefreshProgress(1, "Overview updated!");
    } catch (refreshError) {
      console.error("Failed to reload overview after refresh", refreshError);
      updateRefreshProgress(1, "Overview updated with warnings.");
    }
    setRefreshState(false);
  }
}

function getNewYorkTimestampISO() {
  try {
    const localized = new Date().toLocaleString("en-US", { timeZone: NEW_YORK_TIMEZONE });
    const zoned = new Date(localized);
    return Number.isNaN(zoned.getTime()) ? new Date().toISOString() : zoned.toISOString();
  } catch (error) {
    return new Date().toISOString();
  }
}

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Request failed ${res.status}: ${text}`);
  }
  return res.json();
}

async function fetchOverviewSnapshotCache(accountId) {
  if (!accountId) return { cache: new Map(), updatedAt: null };
  try {
    const res = await fetch(`${API_BASE}/accounts/${accountId}/overview-cache`);
    if (!res.ok) {
      console.warn("Client overview cache request failed with status", res.status);
      return { cache: new Map(), updatedAt: null };
    }
    const data = await res.json();
    const cache = new Map();
    let latestUpdatedAt = null;
    if (Array.isArray(data)) {
      data.forEach((entry) => {
        if (entry?.opportunity_id == null) return;
        const normalized = normalizeCachedSnapshot(entry);
        cache.set(String(entry.opportunity_id), normalized);
        if (normalized.updated_at) {
          if (!latestUpdatedAt) {
            latestUpdatedAt = normalized.updated_at;
          } else if (new Date(normalized.updated_at) > new Date(latestUpdatedAt)) {
            latestUpdatedAt = normalized.updated_at;
          }
        }
      });
    }
    return { cache, updatedAt: latestUpdatedAt };
  } catch (error) {
    console.warn("Failed to load client overview cache", error);
    return { cache: new Map(), updatedAt: null };
  }
}

async function persistOverviewSnapshots(accountId, snapshots) {
  if (!accountId || !Array.isArray(snapshots) || !snapshots.length) return;
  try {
    const payload = snapshots
      .map((entry) => ({
        opportunity_id: entry.opportunity_id,
        client_overview_id: entry.client_overview_id ?? null,
        snapshot: entry.snapshot,
        stage: entry.stage || entry.snapshot?.stage || null,
        updated_at: entry.updated_at ?? entry.snapshot?.updated_at ?? null,
      }))
      .filter((entry) => entry.opportunity_id && entry.snapshot);
    if (!payload.length) return;
    const res = await fetch(`${API_BASE}/accounts/${accountId}/overview-cache`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ opportunities: payload }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "Unknown error");
    }
  } catch (error) {
    console.warn("Failed to persist client overview cache", error);
  }
}

async function pruneInactiveOverviewSnapshots(accountId) {
  if (!accountId) return null;
  try {
    const res = await fetch(`${API_BASE}/accounts/${accountId}/overview-cache/prune-inactive`, {
      method: "POST",
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "Unknown error");
    }
    return res.json();
  } catch (error) {
    console.warn("Failed to prune inactive hired snapshots", error);
    return null;
  }
}

function normalizeCachedSnapshot(entry) {
  const payload = entry?.snapshot ?? entry?.candidates_batches ?? null;
  let snapshot = payload;
  if (typeof payload === "string") {
    try {
      snapshot = JSON.parse(payload);
    } catch (error) {
      snapshot = null;
    }
  }
  if (!snapshot || typeof snapshot !== "object") snapshot = {};
  const batches = Array.isArray(snapshot.batches) ? snapshot.batches : [];
  const opportunity = snapshot.opportunity && typeof snapshot.opportunity === "object"
    ? snapshot.opportunity
    : null;
  const stage = normalizeSnapshotStage(snapshot.stage ?? entry?.stage);
  if (stage && snapshot.stage !== stage) {
    snapshot.stage = stage;
  }
  const updatedAt = entry?.updated_at ?? snapshot.updated_at ?? null;
  if (updatedAt && snapshot.updated_at !== updatedAt) {
    snapshot.updated_at = updatedAt;
  }
  return {
    client_overview_id: entry?.client_overview_id ?? snapshot.client_overview_id ?? null,
    opportunity_id: entry?.opportunity_id ?? snapshot.opportunity_id ?? null,
    batches,
    opportunity,
    updated_at: updatedAt,
    rawSnapshot: snapshot,
    serialized: stableSerialize(snapshot),
    stage,
  };
}

function normalizeSnapshotStage(value) {
  if (value === undefined || value === null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (normalized === "closed") return "closed";
  if (normalized === "open") return "open";
  return null;
}

function makeSnapshotForPersistence(opportunity, clientOverviewId = null, stage = null) {
  if (!opportunity || typeof opportunity !== "object") {
    return { opportunity: {}, batches: [] };
  }
  const { batches = [], ...opportunitySnapshot } = opportunity;
  const snapshot = {
    opportunity: deepClone(opportunitySnapshot),
    batches: sanitizeBatchesForSnapshot(batches),
  };
  const resolvedStage =
    normalizeSnapshotStage(stage) ||
    (classifyOpportunity(opportunity) === "closed" ? "closed" : "open");
  snapshot.stage = resolvedStage;
  if (clientOverviewId != null) {
    snapshot.client_overview_id = clientOverviewId;
    if (snapshot.opportunity && typeof snapshot.opportunity === "object") {
      snapshot.opportunity.client_overview_id = clientOverviewId;
    }
  }
  return snapshot;
}

function sanitizeBatchesForSnapshot(batches) {
  if (!Array.isArray(batches)) return [];
  return batches.map((batch) => {
    const entry = { ...batch };
    entry.candidates = Array.isArray(batch?.candidates)
      ? batch.candidates.map((candidate) => ({ ...candidate }))
      : [];
    return deepClone(entry);
  });
}

function stableSerialize(value) {
  try {
    return JSON.stringify(sortObject(value ?? null));
  } catch (error) {
    return "";
  }
}

function sortObject(value) {
  if (Array.isArray(value)) {
    return value.map((item) => sortObject(item));
  }
  if (value && typeof value === "object") {
    const sorted = {};
    Object.keys(value)
      .sort()
      .forEach((key) => {
        sorted[key] = sortObject(value[key]);
      });
    return sorted;
  }
  return value;
}

function deepClone(payload) {
  try {
    const serialized = JSON.stringify(payload);
    if (typeof serialized === "undefined") {
      return payload;
    }
    return JSON.parse(serialized);
  } catch (error) {
    return payload;
  }
}

function showMissingAccountMessage() {
  els.accountName.textContent = "No account selected";
  els.accountTagline.textContent = "Use the Client overview button from Account Details to open this page.";
  els.opportunitiesEmpty.textContent = "Select an account to see its candidates.";
  updateRefreshMeta(null);
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

function updateRefreshMeta(timestamp) {
  if (!els.metaRefreshedAt) return;
  const label = timestamp ? formatNewYorkTimestamp(timestamp) : "Not refreshed yet";
  els.metaRefreshedAt.textContent = label;
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

function formatNewYorkTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date)) return "Not refreshed yet";
  const options = {
    timeZone: NEW_YORK_TIMEZONE,
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  };
  const dateLabel = date.toLocaleString("en-US", options);
  const tzLabel = new Intl.DateTimeFormat("en-US", {
    timeZone: NEW_YORK_TIMEZONE,
    timeZoneName: "short",
  })
    .formatToParts(date)
    .find((part) => part.type === "timeZoneName")?.value;
  return tzLabel ? `${dateLabel} ${tzLabel}` : dateLabel;
}

function buildOpportunitiesFromSnapshots(cacheMap) {
  if (!(cacheMap instanceof Map)) return [];
  const opportunities = Array.from(cacheMap.values())
    .map((entry) => snapshotEntryToOpportunity(entry))
    .filter(Boolean);
  return sortOpportunitiesForDisplay(opportunities);
}

function snapshotEntryToOpportunity(entry) {
  if (!entry) return null;
  const snapshot = entry.rawSnapshot || {};
  const fromEntry =
    entry.opportunity && typeof entry.opportunity === "object"
      ? { ...entry.opportunity }
      : null;
  const fromSnapshot =
    snapshot.opportunity && typeof snapshot.opportunity === "object"
      ? { ...snapshot.opportunity }
      : null;
  const base = fromEntry || fromSnapshot || {};
  const fallbackId =
    entry.opportunity_id ??
    base.opportunity_id ??
    snapshot.opportunity_id ??
    (snapshot.opportunity && snapshot.opportunity.opportunity_id) ??
    null;
  if (!base.opportunity_id && fallbackId != null) {
    base.opportunity_id = fallbackId;
  }
  if (!base.opportunity_id) return null;
  const batches = Array.isArray(entry.batches)
    ? entry.batches
    : Array.isArray(snapshot.batches)
    ? snapshot.batches
    : [];
  base.batches = batches;
  if (entry.client_overview_id != null) {
    base.client_overview_id = entry.client_overview_id;
  } else if (snapshot.client_overview_id != null) {
    base.client_overview_id = snapshot.client_overview_id;
  }
  const normalizedStage = normalizeSnapshotStage(entry.stage ?? snapshot.stage);
  if (normalizedStage) {
    base.__client_overview_stage = normalizedStage;
  }
  if (entry.updated_at) {
    base.__client_overview_updated_at = entry.updated_at;
  }
  return base;
}

function syncOpportunityCache(opportunities) {
  opportunityCache.clear();
  (Array.isArray(opportunities) ? opportunities : []).forEach((opportunity) => {
    if (!opportunity || opportunity.opportunity_id == null) return;
    opportunityCache.set(String(opportunity.opportunity_id), opportunity);
  });
}

function sortOpportunitiesForDisplay(list) {
  const source = Array.isArray(list) ? list.slice() : [];
  const stageRank = buildStageRank();
  return source.sort((a, b) => {
    const rankA = stageRank.get(a?.opp_stage) ?? stageRank.get("__fallback");
    const rankB = stageRank.get(b?.opp_stage) ?? stageRank.get("__fallback");
    if (rankA !== rankB) return rankA - rankB;
    const dateA = new Date(a?.nda_signature_or_start_date || a?.created_at || 0);
    const dateB = new Date(b?.nda_signature_or_start_date || b?.created_at || 0);
    return dateB - dateA;
  });
}

async function enrichWithBatches(opportunities, snapshotCache = new Map(), options = {}) {
  const list = Array.isArray(opportunities) ? opportunities : [];
  const forceRefreshClosed = Boolean(options.forceRefreshClosed);
  const progressCallback = typeof options.onProgress === "function" ? options.onProgress : null;
  const refreshTimestamp =
    typeof options.refreshTimestamp === "string" && options.refreshTimestamp.trim()
      ? options.refreshTimestamp
      : null;
  const stagesToPersist =
    Array.isArray(options.persistStages) && options.persistStages.length
      ? options.persistStages
      : ["closed"];
  const persistStages = new Set(
    stagesToPersist
      .map((stage) => normalizeSnapshotStage(stage))
      .filter(Boolean)
  );
  if (!persistStages.size) {
    persistStages.add("closed");
  }

  const sorted = sortOpportunitiesForDisplay(list);

  const enriched = [];
  const cacheMap = snapshotCache instanceof Map ? snapshotCache : new Map();
  const snapshotsToPersist = [];
  for (const opp of sorted) {
    const item = { ...opp, batches: [] };
    const cacheKey = String(item.opportunity_id || "");
    const classification = classifyOpportunity(opp);
    const cachedEntry = cacheKey ? cacheMap.get(cacheKey) : null;
    const shouldUseCache =
      classification === "closed" && cachedEntry && !forceRefreshClosed;

    if (shouldUseCache) {
      if (cachedEntry.opportunity && typeof cachedEntry.opportunity === "object") {
        Object.assign(item, cachedEntry.opportunity);
      }
      item.batches = Array.isArray(cachedEntry.batches) ? cachedEntry.batches : [];
      item.client_overview_id = cachedEntry.client_overview_id ?? null;
    }

    const needsNetworkFetch =
      classification !== "closed" || !cachedEntry || forceRefreshClosed;

    if (needsNetworkFetch) {
      try {
        const batches = await fetchJSON(`${API_BASE}/opportunities/${opp.opportunity_id}/batches`);
        if (Array.isArray(batches)) {
          const enrichedBatches = [];
          for (const batch of batches) {
            try {
              const batchCandidates = await fetchJSON(`${API_BASE}/batches/${batch.batch_id}/candidates`);
              const normalizedCandidates = Array.isArray(batchCandidates)
                ? batchCandidates.map((candidate) => {
                    const normalizedTests = normalizeCandidateTests(candidate?.tests_documents_s3);
                    return {
                      ...candidate,
                      batch_status: candidate.batch_status ?? candidate.status ?? "",
                      batch_number: batch.batch_number,
                      presentation_date: batch.presentation_date,
                      tests_documents_s3: normalizedTests,
                    };
                  })
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
    }

    if (persistStages.has(classification)) {
      const snapshot = makeSnapshotForPersistence(
        item,
        cachedEntry?.client_overview_id ?? item.client_overview_id ?? null,
        classification
      );
      const entryUpdatedAt = refreshTimestamp || snapshot.updated_at || new Date().toISOString();
      snapshot.updated_at = entryUpdatedAt;
      const previousSerialized = cachedEntry?.serialized || null;
      const nextSerialized = stableSerialize(snapshot);
      if (previousSerialized !== nextSerialized) {
        snapshotsToPersist.push({
          opportunity_id: item.opportunity_id,
          client_overview_id: cachedEntry?.client_overview_id ?? null,
          snapshot,
          stage: snapshot.stage,
          updated_at: entryUpdatedAt,
        });
      }
    }

    if (
      !item.__client_overview_stage &&
      (classification === "open" || classification === "closed")
    ) {
      item.__client_overview_stage = classification;
    }
    enriched.push(item);
    opportunityCache.set(String(item.opportunity_id), item);
    if (progressCallback) {
      try {
        const name = fallbackText(item?.opp_position_name || "opportunity", "Opportunity");
        const prefix = sorted.length > 1 ? `Syncing ${name}` : `Syncing ${name}`;
        const label =
          sorted.length > 1
            ? `${prefix} (${enriched.length}/${sorted.length})…`
            : `${prefix}…`;
        progressCallback({
          completed: enriched.length,
          total: sorted.length,
          opportunity: item,
          classification,
          message: label,
        });
      } catch (error) {
        console.warn("Refresh progress callback error", error);
      }
    }
  }
  return { enriched, snapshotsToPersist };
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
  if (els.highlightCandidates) {
    els.highlightCandidates.textContent = padCount(hiredCandidates);
  }
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
        ? "No hired candidates are ready to showcase yet."
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
          batch_id: batch.batch_id,
          batch_status: candidate.batch_status ?? candidate.status ?? "",
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
    return { label: "Hired", className: "status-pill--closed" };
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
    return { label: "Hired", date: formatTimelineDate(closedDate) };
  }
  const openDate =
    opportunity?.opp_start_date ||
    opportunity?.nda_signature_or_start_date ||
    opportunity?.created_at ||
    opportunity?.updated_at;
  return { label: "Opened", date: formatTimelineDate(openDate) };
}

function classifyOpportunity(opportunity) {
  const overrideStage = normalizeSnapshotStage(
    opportunity?.__client_overview_stage ?? opportunity?.stage_override
  );
  if (overrideStage) return overrideStage;
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
  panelState.view = "candidates";
  panelState.selectedBatchId = null;
  const batches = getSortedBatches(data);
  const candidates = collectCandidates(data);
  els.panelTitle.textContent = data.opp_position_name || "Opportunity";
  if (!candidates.length) {
    els.panelBatch.textContent = "No candidates recorded yet";
  } else {
    const candidateLabel = candidates.length === 1 ? "candidate" : "candidates";
    const batchLabel = batches.length
      ? `${batches.length} ${batches.length === 1 ? "batch" : "batches"}`
      : "no batches";
    els.panelBatch.textContent = `${candidates.length} ${candidateLabel} · ${batchLabel}`;
  }

  renderCandidateListFromOpportunity(candidates);

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

function renderCandidateListFromOpportunity(candidates) {
  els.panelBody.innerHTML = "";
  if (!Array.isArray(candidates) || !candidates.length) {
    const empty = document.createElement("p");
    empty.className = "candidate-panel__empty";
    empty.textContent = "No candidates are assigned to this opportunity yet.";
    els.panelBody.appendChild(empty);
    return;
  }
  const sorted = candidates.slice().sort((a, b) => {
    const nameA = (a?.name || "").toLowerCase();
    const nameB = (b?.name || "").toLowerCase();
    return nameA.localeCompare(nameB);
  });
  sorted.forEach((candidate) => {
    els.panelBody.appendChild(buildCandidateCard(candidate));
  });
}

function buildBackButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "back-button";
  button.innerHTML = "&larr; Back to batches";
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
  const defaultStatus = "Client interviewing/testing";
  let statusRaw = candidate?.batch_status || candidate?.status || defaultStatus;
  if (translateStatus(statusRaw) === "Contacted") {
    statusRaw = defaultStatus;
  }
  const statusLabel = translateStatus(statusRaw);
  const statusChip = buildStatusChip(statusLabel, statusRaw);
  const countryLabel = formatCandidateCountry(candidate);
  const presentationDate = candidate?.presentation_date || batch?.presentation_date || null;
  const presentationLabel = presentationDate ? `Presented ${formatDate(presentationDate)}` : "Presentation date TBD";
  const testsDocuments = normalizeCandidateTests(candidate?.tests_documents_s3);
  const shouldHydrateTests = needsCandidateTestsHydration(candidate, testsDocuments);
  if (!shouldHydrateTests && candidate?.candidate_id && testsDocuments.length) {
    candidateTestsCache.set(candidate.candidate_id, testsDocuments);
  }
  const testsSection = renderCandidateTestsSection(testsDocuments, {
    candidateId: candidate?.candidate_id,
    state: shouldHydrateTests ? "loading" : null,
    statusLabel: shouldHydrateTests ? "Generating download links…" : null,
    statusVariant: shouldHydrateTests ? "info" : null,
  });

  card.innerHTML = `
    <header>
      <div class="avatar avatar--large" data-initials="${initials}"></div>
      <div>
        <p class="candidate-card__presentation">${presentationLabel}</p>
        <p class="candidate-name">${fallbackText(candidate?.name, "Unnamed candidate")}</p>
      </div>
      ${statusChip}
    </header>
    <ul class="candidate-meta">
      <li><span>Status 🧭</span>${fallbackText(statusLabel)}</li>
      <li><span>Expected salary 💵</span>${salaryLabel}</li>
      <li><span>Country</span>${countryLabel}</li>
    </ul>
    ${testsSection}
    <div class="candidate-actions">
      <a class="primary" href="${resumeUrl}" target="_blank" rel="noopener">Client resume ↗</a>
      ${
        linkedinUrl
          ? `<a class="ghost" href="${linkedinUrl}" target="_blank" rel="noopener">LinkedIn</a>`
          : ""
      }
    </div>
  `;
  if (shouldHydrateTests) {
    hydrateCandidateTestsSection(card, candidate, testsDocuments);
  }
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
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
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
  const status = String(candidate?.batch_status || candidate?.status || "").toLowerCase();
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

function normalizeCandidateTests(rawValue) {
  if (!rawValue) return [];
  let entries = rawValue;
  if (typeof rawValue === "string") {
    try {
      entries = JSON.parse(rawValue);
    } catch (error) {
      return [];
    }
  }
  if (!Array.isArray(entries)) return [];
  const normalized = [];
  entries.forEach((entry) => {
    if (!entry && entry !== "") return;
    if (typeof entry === "string") {
      const label = entry.split("/").pop() || entry;
      normalized.push({
        key: entry,
        name: label,
        url: entry.startsWith("http") ? entry : null,
      });
      return;
    }
    if (typeof entry === "object") {
      const key = entry.key && typeof entry.key === "string" ? entry.key : null;
      const url = entry.url && typeof entry.url === "string" ? entry.url : null;
      const nameFromKey = key ? key.split("/").pop() : null;
      const name =
        (entry.name && String(entry.name).trim()) || nameFromKey || (url || "Document");
      const sizeValue = Number(entry.size);
      normalized.push({
        key,
        name,
        url,
        content_type:
          entry.content_type && typeof entry.content_type === "string"
            ? entry.content_type
            : null,
        size: Number.isFinite(sizeValue) ? sizeValue : null,
        uploaded_at:
          entry.uploaded_at && typeof entry.uploaded_at === "string"
            ? entry.uploaded_at
            : null,
        uploaded_by:
          entry.uploaded_by && typeof entry.uploaded_by === "string"
            ? entry.uploaded_by
            : null,
      });
    }
  });
  return normalized;
}

function renderCandidateTestsSection(documents, options = {}) {
  const normalized = Array.isArray(documents) ? documents.filter(Boolean) : [];
  if (!normalized.length) return "";
  const items = normalized
    .map((doc, index) => renderCandidateTestRow(doc, index))
    .filter(Boolean)
    .join("");
  if (!items) return "";
  const candidateAttr = options.candidateId ? ` data-candidate-tests="${options.candidateId}"` : "";
  const stateAttr = options.state ? ` data-tests-state="${options.state}"` : "";
  const statusClass = options.statusVariant ? ` candidate-tests__status--${options.statusVariant}` : "";
  const statusLabel = options.statusLabel
    ? `<p class="candidate-tests__status${statusClass}">${escapeHTML(options.statusLabel)}</p>`
    : "";
  return `
    <section class="candidate-tests"${candidateAttr}${stateAttr} aria-label="Tests and supporting files">
      <p class="candidate-tests__title">Tests & assessments</p>
      ${statusLabel}
      <ul class="candidate-tests__list">
        ${items}
      </ul>
    </section>
  `;
}

function needsCandidateTestsHydration(candidate, documents) {
  const candidateId = candidate?.candidate_id;
  if (!candidateId || !Array.isArray(documents) || !documents.length) return false;
  if (candidateTestsCache.has(candidateId)) return false;
  return documents.some((doc) => !doc || !doc.url);
}

async function hydrateCandidateTestsSection(card, candidate, fallbackDocuments = []) {
  const candidateId = candidate?.candidate_id;
  if (!candidateId || !card) return;
  const section = card.querySelector(`.candidate-tests[data-candidate-tests="${candidateId}"]`);
  if (!section) return;
  section.dataset.testsState = "loading";
  try {
    const documents = await fetchCandidateTestsPayload(candidateId);
    if (!documents.length) {
      updateCandidateTestSections(candidateId, documents);
      return;
    }
    candidateTestsCache.set(candidateId, documents);
    updateCandidateTestSections(candidateId, documents);
  } catch (error) {
    console.warn("Failed to load candidate tests", candidateId, error);
    const fallback =
      (Array.isArray(fallbackDocuments) && fallbackDocuments.length && fallbackDocuments) ||
      normalizeCandidateTests(candidate?.tests_documents_s3);
    updateCandidateTestSections(candidateId, fallback, {
      candidateId,
      state: "error",
      statusLabel: "Unable to generate download links.",
      statusVariant: "error",
    });
  }
}

function updateCandidateTestSections(candidateId, documents, options = {}) {
  const list =
    typeof candidateId !== "undefined"
      ? document.querySelectorAll(`.candidate-tests[data-candidate-tests="${candidateId}"]`)
      : [];
  if (!list || !list.length) return;
  const html = renderCandidateTestsSection(documents, { candidateId, ...options });
  if (!html) {
    list.forEach((node) => node.remove());
    return;
  }
  list.forEach((node) => {
    if (!node.isConnected) return;
    node.outerHTML = html;
  });
}

async function fetchCandidateTestsPayload(candidateId) {
  if (!candidateId) return [];
  if (candidateTestsCache.has(candidateId)) {
    return candidateTestsCache.get(candidateId);
  }
  if (candidateTestsRequests.has(candidateId)) {
    return candidateTestsRequests.get(candidateId);
  }
  const request = fetchJSON(`${API_BASE}/candidates/${candidateId}/tests`)
    .then((payload) => normalizeCandidateTests(payload))
    .then((documents) => {
      candidateTestsCache.set(candidateId, documents);
      candidateTestsRequests.delete(candidateId);
      return documents;
    })
    .catch((error) => {
      candidateTestsRequests.delete(candidateId);
      throw error;
    });
  candidateTestsRequests.set(candidateId, request);
  return request;
}

function renderCandidateTestRow(doc, index = 0) {
  if (!doc) return "";
  const title =
    (doc.name && String(doc.name).trim()) ||
    (doc.key && String(doc.key).split("/").pop()) ||
    `Document ${index + 1}`;
  const escapedTitle = escapeHTML(title);
  const link = doc.url
    ? `<a href="${doc.url}" target="_blank" rel="noopener">${escapedTitle}</a>`
    : `<span>${escapedTitle}</span>`;
  const metaText = buildCandidateTestMeta(doc);
  const badge = buildCandidateTestBadge(doc);
  return `
    <li>
      <div>
        <p class="candidate-tests__name">${link}</p>
        ${metaText ? `<p class="candidate-tests__meta">${metaText}</p>` : ""}
      </div>
      ${badge}
    </li>
  `;
}

function buildCandidateTestMeta(doc) {
  const parts = [];
  const uploaded = doc.uploaded_at ? formatCandidateTestDate(doc.uploaded_at) : "";
  if (uploaded) parts.push(`Uploaded ${uploaded}`);
  const sizeLabel = formatCandidateTestSize(doc.size);
  if (sizeLabel) parts.push(sizeLabel);
  const owner =
    doc.uploaded_by && String(doc.uploaded_by).trim()
      ? `By ${escapeHTML(String(doc.uploaded_by).trim())}`
      : "";
  if (owner) parts.push(owner);
  return parts.join(" • ");
}

function buildCandidateTestBadge(doc) {
  const type =
    doc?.content_type && typeof doc.content_type === "string"
      ? doc.content_type.split("/").pop()
      : null;
  if (!type) return "";
  return `<span class="candidate-tests__badge">${escapeHTML(type.toUpperCase())}</span>`;
}

function formatCandidateTestDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date)) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatCandidateTestSize(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const precision = size >= 10 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[unitIndex]}`;
}
