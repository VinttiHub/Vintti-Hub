const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

// 🔸 Correos que NO deben aparecer nunca en el dropdown
const EXCLUDED_EMAILS = new Set([
  "sol@vintti.com",
  "agustin@vintti.com",
  "bahia@vintti.com",
  "agustina.ferrari@vintti.com",
  "jazmin@vintti.com",
]);

// 🔸 Personas que sólo deben ver SU propia opción
const RESTRICTED_EMAILS = new Set([
  "agustina.barbero@vintti.com",
  "constanza@vintti.com",
  "pilar@vintti.com",
  "pilar.fernandez@vintti.com",
  "agostina@vintti.com",
  "julieta@vintti.com",
]);
const RECRUITER_POWER_ALLOWED = new Set([
  "angie@vintti.com",
  "agostina@vintti.com",
  "agustin@vintti.com",
  "lara@vintti.com",
]);

const metricsState = {
  byLead: {},            // { email: { ...metrics } }
  orderedLeadEmails: [], // [ email, email, ... ]
  monthStart: null,
  monthEnd: null,
  currentUserEmail: null,
  rangeStart: null, // YYYY-MM-DD inclusive
  rangeEnd: null,   // YYYY-MM-DD inclusive
  churnDetails: [],
  churnSummary: null,
  selectedLead: "",
  recruiterDirectory: [],
  recruiterLookup: {},
  left90RangeStart: null,
  left90RangeEnd: null,
  opportunityDetails: {},
  durationDetails: {},
  pipelineDetails: {},
};
const detailModalRefs = {
  root: null,
  overlay: null,
  title: null,
  context: null,
  summary: null,
  list: null,
  empty: null,
  closeBtn: null,
};
let detailModalKeyListener = null;
let previousBodyOverflow = "";
function isoToYMD(iso) {
  if (!iso) return "";
  return String(iso).slice(0, 10);
}

function showRangeError(msg) {
  const el = document.getElementById("rangeError");
  if (!el) return;
  if (!msg) {
    el.style.display = "none";
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.style.display = "";
}

function setRangeInputs(startYMD, endYMD) {
  const s = document.getElementById("rangeStart");
  const e = document.getElementById("rangeEnd");
  if (s) s.value = startYMD || "";
  if (e) e.value = endYMD || "";
}

// ===== user_id helpers (copiados de Profile, versión mini) =====
function getUidFromQuery() {
  try {
    const q = new URLSearchParams(location.search).get("user_id");
    return q && /^\d+$/.test(q) ? Number(q) : null;
  } catch {
    return null;
  }
}

async function ensureUserIdInURL() {
  let uid = getUidFromQuery();
  if (!uid) uid = Number(localStorage.getItem("user_id")) || null;

  // si existe un resolver global, lo usamos (como en otras páginas)
  if (!uid && typeof window.getCurrentUserId === "function") {
    try {
      uid = await window.getCurrentUserId();
    } catch {
      uid = null;
    }
  }

  if (!uid) {
    console.warn(
      "[recruiter-metrics] No user_id available (no URL, no cache, no resolver)"
    );
    return null;
  }

  localStorage.setItem("user_id", String(uid));

  const url = new URL(location.href);
  if (url.searchParams.get("user_id") !== String(uid)) {
    url.searchParams.set("user_id", String(uid));
    history.replaceState(null, "", url.toString());
  }

  console.debug("[recruiter-metrics] using user_id =", uid);
  return uid;
}

// --- API helper: añade ?user_id= y credentials: 'include'
async function api(path, opts = {}) {
  const url = new URL(API_BASE + path);
  const uid = Number(localStorage.getItem("user_id")) || getUidFromQuery();

  if (uid && !url.searchParams.has("user_id")) {
    url.searchParams.set("user_id", String(uid));
  }

  return fetch(url.toString(), {
    credentials: "include",
    ...opts,
    headers: {
      ...(opts.headers || {}),
    },
  });
}

async function loadCurrentUserEmail() {
  try {
    const resp = await api("/profile/me", { method: "GET" });
    if (!resp.ok) throw new Error(await resp.text());
    const me = await resp.json();

    metricsState.currentUserEmail = (me.email_vintti || "").toLowerCase();
    console.debug(
      "[recruiter-metrics] current user:",
      metricsState.currentUserEmail
    );
  } catch (err) {
    console.warn("[recruiter-metrics] Could not resolve current user email:", err);
    metricsState.currentUserEmail = null;
  }
}

async function loadRecruiterDirectory() {
  try {
    const resp = await fetch(`${API_BASE}/users/recruiters`, {
      credentials: "include",
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    const directory = (Array.isArray(data) ? data : [])
      .filter((row) => row?.email_vintti)
      .map((row) => ({
        email: String(row.email_vintti).trim().toLowerCase(),
        name: row.user_name || row.email_vintti || "",
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
    metricsState.recruiterDirectory = directory;
    metricsState.recruiterLookup = directory.reduce((acc, person) => {
      if (!EXCLUDED_EMAILS.has(person.email)) {
        acc[person.email] = person.name;
      }
      return acc;
    }, {});
  } catch (err) {
    console.error("[recruiter-metrics] Could not load recruiter directory:", err);
    metricsState.recruiterDirectory = [];
    metricsState.recruiterLookup = {};
  }
}
function toggleRecruiterLabButton() {
  const btn = document.getElementById("recruiterLabBtn");
  if (!btn) return;

  const email = (metricsState.currentUserEmail || "").toLowerCase();
  btn.style.display = email && RECRUITER_POWER_ALLOWED.has(email) ? "" : "none";
}
function updateDynamicRangeLabels() {
  const a = document.getElementById("winRangeLabel");
  const b = document.getElementById("lostRangeLabel");
  const c = document.getElementById("convRangeLabel");

  if (!metricsState.rangeStart || !metricsState.rangeEnd) return;

  const txt = "Selected Range";
  if (a) a.textContent = `Closed Win · ${txt}`;
  if (b) b.textContent = `Closed Lost · ${txt}`;
  if (c) c.textContent = `Conversion · ${txt}`;
}

function formatYMDForDisplay(ymd) {
  if (!ymd) return "";
  const parts = String(ymd).split("-");
  if (parts.length !== 3) return ymd;
  const [year, month, day] = parts.map((n) => Number(n));
  if (!year || !month || !day) return ymd;
  const prettyDay = String(day).padStart(2, "0");
  const prettyMonth = String(month).padStart(2, "0");
  return `${prettyDay}/${prettyMonth}/${year}`;
}

function computeTrend(current, previous, goodWhenHigher = true) {
  if (previous == null) {
    return { label: "–", className: "neutral" };
  }

  const diff = current - previous;

  if (diff === 0) {
    return { label: "same", className: "neutral" };
  }

  const arrow = diff > 0 ? "↑" : "↓";
  const absDiff = Math.abs(diff);

  let isImprovement;
  if (goodWhenHigher) {
    isImprovement = diff > 0;
  } else {
    isImprovement = diff < 0;
  }

  const cls = isImprovement ? "up" : "down";
  const verb = diff > 0 ? "up" : "down";

  // Ejemplos:
  // "↑ up 3"
  // "↓ down 2"
  return {
    label: `${arrow} ${verb} ${absDiff}`,
    className: cls,
  };
}

function $(sel, root = document) {
  return root.querySelector(sel);
}

function formatPercent(value) {
  if (value == null) return "–";
  const pct = value * 100;
  if (pct === 0) return "0%";
  if (pct === 100) return "100%";
  return pct.toFixed(1).replace(".0", "") + "%";
}

function formatDateISO(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const year = d.getFullYear();
  return `${day}/${month}/${year}`;
}

// 🔹 helper para el label: muestra el user_name si existe
function getLeadLabel(email) {
  const key = (email || "").toLowerCase();
  const row = metricsState.byLead[key];
  if (row) {
    return row.hr_lead_name || row.hr_lead || email;
  }
  return metricsState.recruiterLookup[key] || email;
}

/* 🌟 NUEVO: helpers de animación numérica */
function parseIntSafe(text) {
  const n = parseInt(String(text).replace(/[^\d-]/g, ""), 10);
  return Number.isNaN(n) ? 0 : n;
}

function parseFloatSafe(text) {
  const n = parseFloat(String(text).replace(/[^\d.-]/g, ""));
  return Number.isNaN(n) ? 0 : n;
}

function parsePercentSafe(text) {
  const n = parseFloat(String(text).replace("%", "").trim());
  if (Number.isNaN(n)) return 0;
  return n / 100; // lo devolvemos como 0–1
}

function formatDaysValue(value) {
  if (value == null || Number.isNaN(value)) return "–";
  const rounded = Math.round(value * 10) / 10;
  const text = Number.isInteger(rounded) ? rounded.toString() : rounded.toFixed(1);
  return `${text} d`;
}

function formatRatioSubtext(numerator, denominator) {
  if (!denominator) return "(— / —)";
  const safeNum = Number(numerator || 0).toLocaleString("en-US");
  const safeDen = Number(denominator || 0).toLocaleString("en-US");
  return `(${safeNum} / ${safeDen})`;
}
function formatDisplayDate(dateString) {
  if (!dateString) return "";
  const [year, month, day] = String(dateString).split("-");
  if (!year || !month || !day) return formatDateISO(dateString);
  return `${day}/${month}/${year}`;
}
function formatDaysSummary(value) {
  if (value == null) return "No data";
  const num = Number(value);
  if (!Number.isFinite(num)) return "No data";
  const rounded = Math.round(num * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${text} day${rounded === 1 ? "" : "s"}`;
}
function formatDaysLong(value) {
  if (value == null) return "Duration not documented";
  const num = Number(value);
  if (!Number.isFinite(num)) return "Duration not documented";
  const abs = Math.round(num);
  return `${abs} day${abs === 1 ? "" : "s"}`;
}
function setDetailCardsEnabled(enabled) {
  const cards = document.querySelectorAll("[data-metric-detail]");
  cards.forEach((card) => {
    const nextTabIndex = enabled ? 0 : -1;
    card.classList.toggle("metric-card--detail-disabled", !enabled);
    card.setAttribute("aria-disabled", enabled ? "false" : "true");
    card.tabIndex = nextTabIndex;
  });
}
function getLeadOpportunities(hrLeadEmail) {
  const key = (hrLeadEmail || "").toLowerCase();
  return metricsState.opportunityDetails[key] || [];
}
function getLeadDurationDetails(hrLeadEmail) {
  const key = (hrLeadEmail || "").toLowerCase();
  return metricsState.durationDetails[key] || {};
}
function getPipelineDetails(hrLeadEmail) {
  const key = (hrLeadEmail || "").toLowerCase();
  return metricsState.pipelineDetails[key] || [];
}
function normalizeCandidateStatus(status) {
  return (status || "").trim().toLowerCase();
}
function getStatusLabel(status) {
  const trimmed = (status || "").trim();
  return trimmed || "Status unavailable";
}
function isClientRejectedCvStatus(status) {
  return normalizeCandidateStatus(status) === "client rejected cv";
}
function isClientHiredStatus(status) {
  return normalizeCandidateStatus(status) === "client hired";
}
function getInterviewStatusInfo(entry = {}) {
  const label = getStatusLabel(entry.candidate_status);
  if (isClientRejectedCvStatus(entry.candidate_status)) {
    return { variant: "negative", label };
  }
  return { variant: "positive", label };
}
function getHireStatusInfo(entry = {}) {
  const label = getStatusLabel(entry.candidate_status);
  if (isClientHiredStatus(entry.candidate_status)) {
    return { variant: "positive", label };
  }
  return { variant: "negative", label };
}
function computeInterviewPipelineInsights(entries = []) {
  const eligibleEntries = entries.filter((entry) => entry.is_interview_eligible);
  let greenCount = 0;
  let redCount = 0;
  eligibleEntries.forEach((entry) => {
    if (isClientRejectedCvStatus(entry.candidate_status)) {
      redCount += 1;
    } else {
      greenCount += 1;
    }
  });
  const totalEligible = eligibleEntries.length;
  return {
    items: eligibleEntries,
    totalEligible,
    totalSent: entries.length,
    greenCount,
    redCount,
    pct: totalEligible ? greenCount / totalEligible : null,
  };
}
function computeHirePipelineInsights(entries = []) {
  let greenCount = 0;
  entries.forEach((entry) => {
    if (isClientHiredStatus(entry.candidate_status)) {
      greenCount += 1;
    }
  });
  const totalSent = entries.length;
  const redCount = Math.max(totalSent - greenCount, 0);
  return {
    items: entries,
    totalSent,
    greenCount,
    redCount,
    pct: totalSent ? greenCount / totalSent : null,
  };
}
function normalizeStage(stage) {
  return (stage || "").trim().toLowerCase();
}
function formatStageLabel(stage) {
  const normalized = normalizeStage(stage);
  if (normalized === "close win") return "Closed Win";
  if (normalized === "closed lost") return "Closed Lost";
  return stage || "Status unavailable";
}
function sortOpportunitiesByDate(opps = []) {
  return opps.slice().sort((a, b) => {
    const aDate = a.close_date || "";
    const bDate = b.close_date || "";
    if (aDate === bDate) return 0;
    if (!aDate) return 1;
    if (!bDate) return -1;
    return bDate.localeCompare(aDate);
  });
}
function filterOpportunities(opps = [], { stage, start, end } = {}) {
  const normalizedStage = stage ? normalizeStage(stage) : null;
  const hasRange = Boolean(start && end);
  return opps.filter((item) => {
    if (normalizedStage && normalizeStage(item.opportunity_stage) !== normalizedStage) {
      return false;
    }
    if (hasRange) {
      const closeDate = item.close_date;
      if (!closeDate) return false;
      if (closeDate < start || closeDate > end) return false;
    }
    return true;
  });
}
function createOpportunityItems(opps = []) {
  return sortOpportunitiesByDate(opps).map((item, index) => {
    const title = item.opportunity_title || "Untitled opportunity";
    const client = item.opportunity_client_name || "";
    const metaStage = formatStageLabel(item.opportunity_stage);
    const dateText = item.close_date ? formatDisplayDate(item.close_date) : "Close date not documented";
    return {
      key: item.opportunity_id || `opportunity-${index}`,
      primary: title,
      secondary: client,
      meta: `${metaStage} · ${dateText}`,
    };
  });
}
function describeRange(start, end) {
  if (start && end) {
    return `${formatDisplayDate(start)} — ${formatDisplayDate(end)}`;
  }
  return "the last 30 days";
}
function createDurationItems(entries = [], type) {
  return entries.map((entry, index) => {
    const title = entry.opportunity_title || "Untitled opportunity";
    const client = entry.opportunity_client_name || "";
    const stageLabel = formatStageLabel(entry.opportunity_stage);
    const daysText = formatDaysLong(entry.duration_days);
    const timelineParts = [];
    if (entry.start_reference_date) {
      timelineParts.push(`Start ${formatDisplayDate(entry.start_reference_date)}`);
    }
    const endLabel = type === "avgBatchOpen" || type === "avgBatchClosed" ? "First batch" : "Close";
    const endDate =
      type === "avgBatchOpen" || type === "avgBatchClosed" ? entry.first_batch_date : entry.close_date;
    if (endDate) {
      timelineParts.push(`${endLabel} ${formatDisplayDate(endDate)}`);
    }
    const timeline = timelineParts.length ? timelineParts.join(" → ") : "";
    const metaPieces = [];
    if (daysText !== "Duration not documented") {
      const action = endLabel === "Close" ? "to close" : "to send first batch";
      metaPieces.push(`Took ${daysText} ${action}`);
    } else {
      metaPieces.push(daysText);
    }
    if (timeline) metaPieces.push(timeline);
    if (stageLabel) metaPieces.push(stageLabel);
    return {
      key: entry.opportunity_id || `duration-${type}-${index}`,
      primary: title,
      secondary: client,
      meta: metaPieces.join(" · "),
    };
  });
}
function createPipelineItems(entries = [], options = {}) {
  const { statusResolver } = options;
  return entries
    .slice()
    .sort((a, b) => {
      const aDate = a.sent_date || "";
      const bDate = b.sent_date || "";
      if (aDate === bDate) return 0;
      if (!aDate) return 1;
      if (!bDate) return -1;
      return bDate.localeCompare(aDate);
    })
    .map((entry, index) => {
      const fallbackId =
        entry.candidate_id != null ? `#${entry.candidate_id}` : `entry-${index + 1}`;
      const candidateLabel =
        entry.candidate_name || entry.candidate_email || `Candidate ${fallbackId}`;
      const secondaryParts = [];
      if (entry.opportunity_title) secondaryParts.push(entry.opportunity_title);
      if (entry.opportunity_client_name) secondaryParts.push(entry.opportunity_client_name);
      if (entry.batch_number != null) secondaryParts.push(`Batch #${entry.batch_number}`);
      const metaParts = [];
      if (entry.sent_date) metaParts.push(`Sent ${formatDisplayDate(entry.sent_date)}`);
      const tags = [];
      if (entry.is_hired) tags.push("Hired");
      else if (entry.is_interviewed) tags.push("Interviewing/testing");
      else if (entry.is_interview_eligible && entry.candidate_status) tags.push(entry.candidate_status);
      if (tags.length) metaParts.push(tags.join(" · "));
      else if (entry.candidate_status) metaParts.push(entry.candidate_status);
      const statusInfo =
        typeof statusResolver === "function" ? statusResolver(entry) : { variant: null, label: null };
      return {
        key: entry.candidate_id
          ? `candidate-${entry.candidate_id}-${entry.batch_id || index}`
          : `candidate-${index}`,
        primary: candidateLabel,
        secondary: secondaryParts.join(" · "),
        meta: metaParts.join(" · "),
        statusVariant: statusInfo?.variant || null,
        statusLabel: statusInfo?.label || null,
      };
    });
}
function describeLeft90Window() {
  const start = metricsState.left90RangeStart;
  const end = metricsState.left90RangeEnd;
  if (start && end) {
    return `${formatDisplayDate(start)} — ${formatDisplayDate(end)}`;
  }
  return "this window";
}
function getLeadChurnDetails(hrLeadEmail) {
  const key = (hrLeadEmail || "").toLowerCase();
  if (!key) return [];
  return (metricsState.churnDetails || []).filter(
    (row) => (row.hr_lead_email || "").toLowerCase() === key
  );
}
function filterChurnEntries(entries = [], { within90Days = null } = {}) {
  return entries.filter((row) => {
    if (within90Days == null) return true;
    return Boolean(row.left_within_90_days) === Boolean(within90Days);
  });
}
function sortChurnEntries(entries = []) {
  return entries.slice().sort((a, b) => {
    const aDate = a.end_date || "";
    const bDate = b.end_date || "";
    if (aDate === bDate) return 0;
    if (!aDate) return 1;
    if (!bDate) return -1;
    return bDate.localeCompare(aDate);
  });
}
function formatChurnTenure(days) {
  if (days == null || Number.isNaN(Number(days))) return "Tenure not documented";
  const parsed = Math.round(Number(days));
  return `Tenure: ${parsed} day${parsed === 1 ? "" : "s"}`;
}
function createChurnDetailItems(entries = []) {
  return sortChurnEntries(entries).map((row, index) => {
    const identifier = row.candidate_id != null ? row.candidate_id : `row-${index}`;
    const candidateName =
      row.candidate_name || row.candidate_email || `Candidate #${identifier}`;
    const candidateEmail = row.candidate_email || "";
    const opportunityParts = [];
    if (row.opportunity_title) opportunityParts.push(row.opportunity_title);
    if (row.opportunity_client_name) opportunityParts.push(row.opportunity_client_name);
    const opportunityLabel = opportunityParts.join(" · ") || "Opportunity not documented";
    const opportunityContent = row.opportunity_id
      ? `<a href="./opportunity-detail.html?id=${encodeURIComponent(
          row.opportunity_id
        )}" target="_blank" rel="noopener">${opportunityLabel}</a>`
      : opportunityLabel;
    const secondaryParts = [];
    if (candidateEmail) secondaryParts.push(candidateEmail);
    if (opportunityContent) secondaryParts.push(opportunityContent);
    const metaParts = [];
    metaParts.push(
      row.start_date
        ? `Started ${formatDisplayDate(row.start_date)}`
        : "Start date missing"
    );
    metaParts.push(
      row.end_date ? `Ended ${formatDisplayDate(row.end_date)}` : "End date missing"
    );
    metaParts.push(formatChurnTenure(row.tenure_days));
    if (row.left_within_90_days) metaParts.push("Left within 90 days");
    const hrLeadLabel = row.hr_lead_name || row.hr_lead_email || "";
    if (hrLeadLabel) metaParts.push(`HR lead: ${hrLeadLabel}`);
    return {
      key: `churn-${identifier}-${index}`,
      primary: candidateName,
      secondary: secondaryParts.join(" · "),
      meta: metaParts.join(" · "),
    };
  });
}

function animateValue(el, from, to, { duration = 650, formatter }) {
  if (!el) return;
  if (from === to) {
    // nada que animar
    el.textContent = formatter ? formatter(to) : to;
    return;
  }

  const start = performance.now();

  function frame(now) {
    const t = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic 💅
    const current = from + (to - from) * eased;
    el.textContent = formatter ? formatter(current) : Math.round(current);

    if (t < 1) {
      requestAnimationFrame(frame);
    }
  }

  requestAnimationFrame(frame);
}

function animateCardsFlash() {
  const cards = document.querySelectorAll(".metric-card");
  cards.forEach((card) => {
    card.classList.remove("is-updating");
    // fuerza reflow para reiniciar animación
    void card.offsetWidth;
    card.classList.add("is-updating");
  });
}
function buildDetailModalPayload(type) {
  const key = (metricsState.selectedLead || "").toLowerCase();
  if (!key) return null;
  const selectedMetrics = metricsState.byLead[key];
  if (!selectedMetrics) return null;
  const recruiterName = getLeadLabel(key);
  const recruiterSuffix = recruiterName ? ` for ${recruiterName}` : "";
  const opportunities = getLeadOpportunities(key);
  const rangeStart = metricsState.rangeStart;
  const rangeEnd = metricsState.rangeEnd;
  const readableRange = describeRange(rangeStart, rangeEnd);
  const durationDetails = getLeadDurationDetails(key);
  const getDurationItems = (metricKey) => createDurationItems(durationDetails[metricKey] || [], metricKey);
  const getDurationCount = (metricKey) => (durationDetails[metricKey] || []).length;
  const pipelineEntries = getPipelineDetails(key);
  const churnEntries = getLeadChurnDetails(key);

  switch (type) {
    case "closedWinRange":
      return {
        title: rangeStart && rangeEnd ? "Closed Win · Selected Range" : "Closed Win · Last 30 Days",
        context: `Closed Win opportunities${recruiterSuffix} between ${readableRange}.`,
        summaryLines: [`Count: ${selectedMetrics.closed_win_month ?? 0}`],
        items: createOpportunityItems(
          filterOpportunities(opportunities, { stage: "Close Win", start: rangeStart, end: rangeEnd })
        ),
        emptyMessage: "No Closed Win opportunities for this recruiter in the selected window.",
      };
    case "closedLostRange":
      return {
        title: rangeStart && rangeEnd ? "Closed Lost · Selected Range" : "Closed Lost · Last 30 Days",
        context: `Closed Lost opportunities${recruiterSuffix} between ${readableRange}.`,
        summaryLines: [`Count: ${selectedMetrics.closed_lost_month ?? 0}`],
        items: createOpportunityItems(
          filterOpportunities(opportunities, { stage: "Closed Lost", start: rangeStart, end: rangeEnd })
        ),
        emptyMessage: "No Closed Lost opportunities for this recruiter in the selected window.",
      };
    case "closedWinTotal":
      return {
        title: "Total Closed Win",
        context: `Lifetime Closed Win opportunities${recruiterSuffix}.`,
        summaryLines: [`Lifetime total: ${selectedMetrics.closed_win_total ?? 0}`],
        items: createOpportunityItems(filterOpportunities(opportunities, { stage: "Close Win" })),
        emptyMessage: "No Closed Win opportunities recorded for this recruiter.",
      };
    case "closedLostTotal":
      return {
        title: "Total Closed Lost",
        context: `Lifetime Closed Lost opportunities${recruiterSuffix}.`,
        summaryLines: [`Lifetime total: ${selectedMetrics.closed_lost_total ?? 0}`],
        items: createOpportunityItems(filterOpportunities(opportunities, { stage: "Closed Lost" })),
        emptyMessage: "No Closed Lost opportunities recorded for this recruiter.",
      };
    case "conversionRange": {
      const total = selectedMetrics.last_20_count ?? 0;
      const wins = selectedMetrics.last_20_win ?? 0;
      const losses = Math.max(0, total - wins);
      return {
        title: rangeStart && rangeEnd ? "Conversion · Selected Range" : "Conversion · Last 30 Days",
        context: `Conversion covers every closed opportunity${recruiterSuffix} between ${readableRange}.`,
        summaryLines: [
          `Wins: ${wins}`,
          `Losses: ${losses}`,
          `Conversion: ${formatPercent(selectedMetrics.conversion_rate_last_20)}`,
        ],
        items: createOpportunityItems(filterOpportunities(opportunities, { start: rangeStart, end: rangeEnd })),
        emptyMessage: "No closed opportunities for this recruiter in the selected window.",
      };
    }
    case "conversionLifetime": {
      const lifetimeWins = selectedMetrics.closed_win_total ?? 0;
      const lifetimeLosses = selectedMetrics.closed_lost_total ?? 0;
      const lifetimeTotal = lifetimeWins + lifetimeLosses;
      return {
        title: "Conversion · Lifetime",
        context: `Lifetime conversion is calculated with every closed opportunity${recruiterSuffix}.`,
        summaryLines: [
          `Wins: ${lifetimeWins}`,
          `Losses: ${lifetimeLosses}`,
          `Conversion: ${formatPercent(selectedMetrics.conversion_rate_lifetime)}`,
          `Total closed: ${lifetimeTotal}`,
        ],
        items: createOpportunityItems(filterOpportunities(opportunities)),
        emptyMessage: "No closed opportunities on record for this recruiter.",
      };
    }
    case "avgCloseWin": {
      const items = getDurationItems("avgCloseWin");
      return {
        title: "Average days to close (Win)",
        context: `Time elapsed from opportunity start to Closed Win${recruiterSuffix} within ${readableRange}.`,
        summaryLines: [
          `Average: ${formatDaysSummary(selectedMetrics.avg_days_to_close_win)}`,
          `Opportunities included: ${getDurationCount("avgCloseWin")}`,
        ],
        items,
        emptyMessage: "No Closed Win opportunities with documented start and close dates in the selected window.",
      };
    }
    case "avgCloseLost": {
      const items = getDurationItems("avgCloseLost");
      return {
        title: "Average days to close (Lost)",
        context: `Time elapsed from opportunity start to Closed Lost${recruiterSuffix} within ${readableRange}.`,
        summaryLines: [
          `Average: ${formatDaysSummary(selectedMetrics.avg_days_to_close_lost)}`,
          `Opportunities included: ${getDurationCount("avgCloseLost")}`,
        ],
        items,
        emptyMessage: "No Closed Lost opportunities with documented start and close dates in the selected window.",
      };
    }
    case "avgBatchOpen": {
      const items = getDurationItems("avgBatchOpen");
      return {
        title: "Average days to first batch (Open)",
        context: `Open opportunities${recruiterSuffix} with start dates inside ${readableRange}, tracking how long it took to send the first batch.`,
        summaryLines: [
          `Average: ${formatDaysSummary(selectedMetrics.avg_days_to_first_batch_open)}`,
          `Opportunities included: ${getDurationCount("avgBatchOpen")}`,
        ],
        items,
        emptyMessage: "No open opportunities with a first batch recorded in the selected window.",
      };
    }
    case "avgBatchClosed": {
      const items = getDurationItems("avgBatchClosed");
      return {
        title: "Average days to first batch (Closed)",
        context: `Closed opportunities${recruiterSuffix} that had a first batch before closing, limited to ${readableRange}.`,
        summaryLines: [
          `Average: ${formatDaysSummary(selectedMetrics.avg_days_to_first_batch_closed)}`,
          `Opportunities included: ${getDurationCount("avgBatchClosed")}`,
        ],
        items,
        emptyMessage: "No closed opportunities with a documented first batch in the selected window.",
      };
    }
    case "interviewRate": {
      const totalSent = pipelineEntries.length;
      const interviewInsights = computeInterviewPipelineInsights(pipelineEntries);
      const computedRate =
        interviewInsights.pct ??
        (typeof selectedMetrics.interview_rate?.pct === "number"
          ? selectedMetrics.interview_rate.pct
          : null);
      return {
        title: "Interview rate",
        context: `Candidate batches sent${recruiterSuffix} between ${readableRange}.`,
        summaryLines: [
          `Green candidates: ${interviewInsights.greenCount}`,
          `Red candidates: ${interviewInsights.redCount}`,
          `Rate: ${formatPercent(computedRate)}`,
          `Eligible candidates: ${interviewInsights.totalEligible}`,
          `Total sent: ${totalSent}`,
        ],
        items: createPipelineItems(interviewInsights.items, {
          statusResolver: getInterviewStatusInfo,
        }),
        emptyMessage: "No interview-eligible candidates sent in the selected window.",
      };
    }
    case "hireRate": {
      const totalSent = pipelineEntries.length;
      const hireInsights = computeHirePipelineInsights(pipelineEntries);
      const computedRate =
        hireInsights.pct ??
        (typeof selectedMetrics.hire_rate?.pct === "number"
          ? selectedMetrics.hire_rate.pct
          : null);
      return {
        title: "Hire rate",
        context: `Sent candidates${recruiterSuffix} between ${readableRange}.`,
        summaryLines: [
          `Green candidates: ${hireInsights.greenCount}`,
          `Red candidates: ${hireInsights.redCount}`,
          `Rate: ${formatPercent(computedRate)}`,
          `Sent candidates: ${totalSent}`,
        ],
        items: createPipelineItems(hireInsights.items, {
          statusResolver: getHireStatusInfo,
        }),
        emptyMessage: "No candidates were sent in the selected window.",
      };
    }
    case "churnRange": {
      const known = selectedMetrics.churn_tenure_known ?? 0;
      const missing = selectedMetrics.churn_tenure_unknown ?? 0;
      return {
        title: "Total churn · Selected range",
        context: `Churned hires${recruiterSuffix} whose end date falls between ${readableRange}.`,
        summaryLines: [
          `Count: ${selectedMetrics.churn_total ?? 0}`,
        ],
        items: createChurnDetailItems(churnEntries),
        emptyMessage: "No churn recorded for this recruiter in the selected range.",
      };
    }
    case "churn90Days": {
      const windowLabel = describeLeft90Window();
      const within90Entries = filterChurnEntries(churnEntries, { within90Days: true });
      return {
        title: "Total churn · 90-day tenure",
        context: `Churned hires${recruiterSuffix} whose end date falls between ${windowLabel} and whose tenure was under 90 days.`,
        summaryLines: [
          `Left within 90 days: ${selectedMetrics.left90_within_90 ?? 0}`,
          `Rate: ${formatPercent(selectedMetrics.left90_rate)}`,
          `Start dates available: ${selectedMetrics.left90_tenure_known ?? 0}`,
        ],
        items: createChurnDetailItems(within90Entries),
        emptyMessage: "No hires left within 90 days for this recruiter.",
      };
    }
    default:
      return null;
  }
}
function renderDetailModalContent(detail) {
  if (!detailModalRefs.root) return;
  detailModalRefs.title.textContent = detail.title || "Metric detail";
  detailModalRefs.context.textContent = detail.context || "";

  detailModalRefs.summary.innerHTML = "";
  (detail.summaryLines || []).forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    detailModalRefs.summary.appendChild(li);
  });
  detailModalRefs.summary.style.display = detail.summaryLines?.length ? "" : "none";

  detailModalRefs.list.innerHTML = "";
  (detail.items || []).forEach((item) => {
    const li = document.createElement("li");
    li.className = "metric-detail-modal__item";
    if (item.statusVariant) {
      li.classList.add(`metric-detail-modal__item--${item.statusVariant}`);
    }
    li.innerHTML = `
      <div>${item.primary}</div>
      ${item.secondary ? `<div class="metric-detail-modal__item-secondary">${item.secondary}</div>` : ""}
      ${item.statusLabel ? `<div class="metric-detail-modal__badge">${item.statusLabel}</div>` : ""}
      ${item.meta ? `<div class="metric-detail-modal__item-meta">${item.meta}</div>` : ""}
    `;
    detailModalRefs.list.appendChild(li);
  });

  if (detail.items?.length) {
    detailModalRefs.list.style.display = "";
    detailModalRefs.empty.textContent = "";
    detailModalRefs.empty.style.display = "none";
  } else {
    detailModalRefs.list.style.display = "none";
    detailModalRefs.empty.textContent = detail.emptyMessage || "No records available for this metric.";
    detailModalRefs.empty.style.display = "";
  }
}
function openMetricDetailModal(detail) {
  if (!detailModalRefs.root || !detail) return;
  renderDetailModalContent(detail);
  detailModalRefs.root.hidden = false;
  detailModalRefs.root.classList.add("is-visible");
  previousBodyOverflow = document.body.style.overflow;
  document.body.style.overflow = "hidden";

  detailModalKeyListener = (event) => {
    if (event.key === "Escape") {
      closeMetricDetailModal();
    }
  };
  document.addEventListener("keydown", detailModalKeyListener);
}
function closeMetricDetailModal() {
  if (!detailModalRefs.root) return;
  detailModalRefs.root.hidden = true;
  detailModalRefs.root.classList.remove("is-visible");
  document.body.style.overflow = previousBodyOverflow || "";
  if (detailModalKeyListener) {
    document.removeEventListener("keydown", detailModalKeyListener);
    detailModalKeyListener = null;
  }
}
function setupMetricDetailModal() {
  const root = document.getElementById("metricDetailModal");
  if (!root) return;
  detailModalRefs.root = root;
  detailModalRefs.overlay = root.querySelector("[data-modal-overlay]");
  detailModalRefs.title = document.getElementById("metricDetailTitle");
  detailModalRefs.context = document.getElementById("metricDetailContext");
  detailModalRefs.summary = document.getElementById("metricDetailSummary");
  detailModalRefs.list = document.getElementById("metricDetailList");
  detailModalRefs.empty = document.getElementById("metricDetailEmpty");
  detailModalRefs.closeBtn = document.getElementById("metricDetailCloseBtn");

  [detailModalRefs.overlay, detailModalRefs.closeBtn].forEach((el) => {
    if (el) {
      el.addEventListener("click", () => closeMetricDetailModal());
    }
  });
}
function requestMetricDetail(kind) {
  if (!kind || !metricsState.selectedLead) return;
  const detail = buildDetailModalPayload(kind);
  if (detail) {
    openMetricDetailModal(detail);
  }
}
function wireMetricDetailCards() {
  const cards = document.querySelectorAll("[data-metric-detail]");
  cards.forEach((card) => {
    const kind = card.getAttribute("data-metric-detail");
    const handler = () => {
      if (card.classList.contains("metric-card--detail-disabled")) return;
      requestMetricDetail(kind);
    };
    card.addEventListener("click", handler);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handler();
      }
    });
  });
}

function updateCardsForLead(hrLeadEmail) {
  const key = (hrLeadEmail || "").toLowerCase();
  const m = metricsState.byLead[key];
  metricsState.selectedLead = key || "";
  setDetailCardsEnabled(Boolean(key && m));

  const winMonthEl = $("#closedWinMonthValue");
  const lostMonthEl = $("#closedLostMonthValue");
  const winTotalEl = $("#closedWinTotalValue");
  const lostTotalEl = $("#closedLostTotalValue");
  const convEl = $("#conversionRateValue");
  const helperEl = $("#conversionHelper");
  const convLifetimeEl = $("#conversionLifetimeValue");
  const churnTotalEl = $("#churnRangeCount");
  const churnTotalHelperEl = $("#churnRangeHelper");
  const left90CountEl = $("#left90Count");
  const left90RateEl = $("#left90Rate");
  const left90HelperEl = $("#left90Helper");
  const avgCloseWinEl = $("#avgCloseWinValue");
  const avgCloseLostEl = $("#avgCloseLostValue");
  const avgBatchOpenEl = $("#avgBatchOpenValue");
  const avgBatchClosedEl = $("#avgBatchClosedValue");
  const interviewRateEl = $("#interviewRateValue");
  const interviewHelperEl = $("#interviewRateHelper");
  const hireRateEl = $("#hireRateValue");
  const hireHelperEl = $("#hireRateHelper");

  if (!m) {
    winMonthEl.textContent = "–";
    lostMonthEl.textContent = "–";
    winTotalEl.textContent = "–";
    lostTotalEl.textContent = "–";
    convEl.textContent = "–";
    helperEl.textContent =
      "No data available for this recruiter yet. Keep an eye on new opportunities!";
    if (convLifetimeEl) convLifetimeEl.textContent = "–";
    if (churnTotalEl) churnTotalEl.textContent = "–";
    if (churnTotalHelperEl)
      churnTotalHelperEl.textContent = "People who left within the selected dates.";
    if (left90CountEl) left90CountEl.textContent = "–";
    if (left90RateEl) left90RateEl.textContent = "–";
    if (left90HelperEl)
      left90HelperEl.textContent = "Based on – churned hires with a start date.";
    if (avgCloseWinEl) avgCloseWinEl.textContent = "–";
    if (avgCloseLostEl) avgCloseLostEl.textContent = "–";
    if (avgBatchOpenEl) avgBatchOpenEl.textContent = "–";
    if (avgBatchClosedEl) avgBatchClosedEl.textContent = "–";
    if (interviewRateEl) interviewRateEl.textContent = "–";
    if (interviewHelperEl) interviewHelperEl.textContent = "(— / —)";
    if (hireRateEl) hireRateEl.textContent = "–";
    if (hireHelperEl) hireHelperEl.textContent = "(— / —)";
    return;
  }

  const pipelineEntries = getPipelineDetails(key);
  const interviewInsights = computeInterviewPipelineInsights(pipelineEntries);
  const hireInsights = computeHirePipelineInsights(pipelineEntries);

  /* 🌟 NUEVO: animamos los números en vez de cambiarlos brusco */

  // --- Closed Win · This Month ---
  const newWinMonth = m.closed_win_month ?? 0;
  const fromWinMonth = parseIntSafe(winMonthEl.textContent);
  animateValue(winMonthEl, fromWinMonth, newWinMonth, {
    formatter: (v) => Math.round(v),
  });

  // --- Closed Lost · This Month ---
  const newLostMonth = m.closed_lost_month ?? 0;
  const fromLostMonth = parseIntSafe(lostMonthEl.textContent);
  animateValue(lostMonthEl, fromLostMonth, newLostMonth, {
    formatter: (v) => Math.round(v),
  });

  /* ✅ COMPARACIÓN CON MES ANTERIOR (texto, sin animación numérica) */
  const winCompareEl = $("#winMonthCompare");
  const lostCompareEl = $("#lostMonthCompare");

  const prevWin = m.prev_closed_win_month ?? null;
  const prevLost = m.prev_closed_lost_month ?? null;

  // WIN → más es mejor
  const winTrend = computeTrend(m.closed_win_month ?? 0, prevWin, true);
  winCompareEl.textContent = winTrend.label;
  winCompareEl.className = `metric-compare ${winTrend.className}`;

  // LOST → menos es mejor
  const lostTrend = computeTrend(m.closed_lost_month ?? 0, prevLost, false);
  lostCompareEl.textContent = lostTrend.label;
  lostCompareEl.className = `metric-compare ${lostTrend.className}`;

  // --- Total Closed Win ---
  const newWinTotal = m.closed_win_total ?? 0;
  const fromWinTotal = parseIntSafe(winTotalEl.textContent);
  animateValue(winTotalEl, fromWinTotal, newWinTotal, {
    formatter: (v) => Math.round(v),
  });

  // --- Total Closed Lost ---
  const newLostTotal = m.closed_lost_total ?? 0;
  const fromLostTotal = parseIntSafe(lostTotalEl.textContent);
  animateValue(lostTotalEl, fromLostTotal, newLostTotal, {
    formatter: (v) => Math.round(v),
  });

  // --- Conversion · Last 30 days (antes “Last 20”) ---
  const newConv = m.conversion_rate_last_20;
  if (newConv == null) {
    convEl.textContent = "–";
  } else {
    const fromConv = parsePercentSafe(convEl.textContent); // 0–1
    animateValue(convEl, fromConv, newConv, {
      duration: 750,
      formatter: (v) => formatPercent(v),
    });
  }

  const total = m.last_20_count ?? 0;
  const wins = m.last_20_win ?? 0;
  if (total === 0) {
    helperEl.textContent =
      "No closed opportunities in the last 30 days to compute this rate.";
  } else {
    helperEl.textContent = `Selected range: ${wins} Closed Win out of ${total} closed opportunities.`;
  }

  // --- 🌟 NUEVO: Conversion · Lifetime ---
  if (convLifetimeEl) {
    const newConvLifetime = m.conversion_rate_lifetime;
    if (newConvLifetime == null) {
      convLifetimeEl.textContent = "–";
    } else {
      const fromConvLifetime = parsePercentSafe(convLifetimeEl.textContent);
      animateValue(convLifetimeEl, fromConvLifetime, newConvLifetime, {
        duration: 750,
        formatter: (v) => formatPercent(v),
      });
    }
  }

  // --- Average days to close ---
  if (avgCloseWinEl) {
    const newAvgWin = m.avg_days_to_close_win;
    if (newAvgWin == null) {
      avgCloseWinEl.textContent = "–";
    } else {
      const fromAvgWin = parseFloatSafe(avgCloseWinEl.textContent);
      animateValue(avgCloseWinEl, fromAvgWin, newAvgWin, {
        formatter: (v) => formatDaysValue(v),
      });
    }
  }

  if (avgCloseLostEl) {
    const newAvgLost = m.avg_days_to_close_lost;
    if (newAvgLost == null) {
      avgCloseLostEl.textContent = "–";
    } else {
      const fromAvgLost = parseFloatSafe(avgCloseLostEl.textContent);
      animateValue(avgCloseLostEl, fromAvgLost, newAvgLost, {
        formatter: (v) => formatDaysValue(v),
      });
    }
  }

  // --- Average days to first batch ---
  if (avgBatchOpenEl) {
    const newBatchOpen = m.avg_days_to_first_batch_open;
    if (newBatchOpen == null) {
      avgBatchOpenEl.textContent = "–";
    } else {
      const fromBatchOpen = parseFloatSafe(avgBatchOpenEl.textContent);
      animateValue(avgBatchOpenEl, fromBatchOpen, newBatchOpen, {
        formatter: (v) => formatDaysValue(v),
      });
    }
  }

  if (avgBatchClosedEl) {
    const newBatchClosed = m.avg_days_to_first_batch_closed;
    if (newBatchClosed == null) {
      avgBatchClosedEl.textContent = "–";
    } else {
      const fromBatchClosed = parseFloatSafe(avgBatchClosedEl.textContent);
      animateValue(avgBatchClosedEl, fromBatchClosed, newBatchClosed, {
        formatter: (v) => formatDaysValue(v),
      });
    }
  }

  // --- Interview / Hire rates (ratios) ---
  if (interviewRateEl && interviewHelperEl) {
    const interviewRate = m.interview_rate || {};
    const newInterviewPct =
      interviewInsights.pct ??
      (typeof interviewRate.pct === "number" ? interviewRate.pct : null);
    if (newInterviewPct == null) {
      interviewRateEl.textContent = "–";
    } else {
      const fromInterviewPct = parsePercentSafe(interviewRateEl.textContent);
      animateValue(interviewRateEl, fromInterviewPct, newInterviewPct, {
        duration: 750,
        formatter: (v) => formatPercent(v),
      });
    }
    interviewHelperEl.textContent = formatRatioSubtext(
      interviewInsights.greenCount,
      interviewInsights.totalEligible
    );
  }

  if (hireRateEl && hireHelperEl) {
    const hireRate = m.hire_rate || {};
    const newHirePct =
      hireInsights.pct ?? (typeof hireRate.pct === "number" ? hireRate.pct : null);
    if (newHirePct == null) {
      hireRateEl.textContent = "–";
    } else {
      const fromHirePct = parsePercentSafe(hireRateEl.textContent);
      animateValue(hireRateEl, fromHirePct, newHirePct, {
        duration: 750,
        formatter: (v) => formatPercent(v),
      });
    }
    hireHelperEl.textContent = formatRatioSubtext(
      hireInsights.greenCount,
      hireInsights.totalSent
    );
  }

  // --- Churn · Selected range ---
  if (churnTotalEl && churnTotalHelperEl) {
    const newChurnTotal = m.churn_total ?? 0;
    const fromChurnTotal = parseIntSafe(churnTotalEl.textContent);
    animateValue(churnTotalEl, fromChurnTotal, newChurnTotal, {
      formatter: (v) => Math.round(v),
    });

    const known = m.churn_tenure_known ?? 0;
    const missing = m.churn_tenure_unknown ?? 0;
  }

  // --- Left within 90 days ---
  if (left90CountEl && left90RateEl && left90HelperEl) {
    const newLeftCount = m.left90_within_90 ?? 0;
    const fromLeftCount = parseIntSafe(left90CountEl.textContent);
    animateValue(left90CountEl, fromLeftCount, newLeftCount, {
      formatter: (v) => Math.round(v),
    });

    const newLeftRate = m.left90_rate;
    if (newLeftRate == null) {
      left90RateEl.textContent = "–";
    } else {
      const fromLeftRate = parsePercentSafe(left90RateEl.textContent);
      animateValue(left90RateEl, fromLeftRate, newLeftRate, {
        duration: 750,
        formatter: (v) => formatPercent(v),
      });
    }

    const known = m.left90_tenure_known ?? 0;
    left90HelperEl.textContent =
      known === 0
        ? "No start dates available for this range."
        : `Based on ${known} churned hires with a start date.`;
  }

  // ✨ pequeño “glow” en todas las cards cuando cambian
  animateCardsFlash();
}

function populateDropdown() {
  const select = $("#hrLeadSelect");
  if (!select) return;

  const previousSelection = metricsState.selectedLead || "";

  select.innerHTML = "";

  // Option placeholder
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "Select recruiter…";
  defaultOpt.disabled = true;
  defaultOpt.selected = true;
  select.appendChild(defaultOpt);

  let emails = metricsState.orderedLeadEmails.slice();
  const currentEmail = (metricsState.currentUserEmail || "").toLowerCase();

  // 🔒 Si el usuario está en la lista restringida, sólo ve su propia opción
  if (currentEmail && RESTRICTED_EMAILS.has(currentEmail)) {
    emails = emails.filter((e) => e.toLowerCase() === currentEmail);
  }

  // Ordenamos por nombre visible (user_name)
  emails.sort((a, b) =>
    getLeadLabel(a).localeCompare(getLeadLabel(b), undefined, {
      sensitivity: "base",
    })
  );

  emails.forEach((email) => {
    const opt = document.createElement("option");
    opt.value = email;              // clave = email
    opt.textContent = getLeadLabel(email); // label = user_name
    select.appendChild(opt);
  });

  let shouldRefreshCards = false;

  // Si es usuario restringido y su opción existe, la seleccionamos por defecto
  if (currentEmail && RESTRICTED_EMAILS.has(currentEmail)) {
    const ownOption = [...select.options].find(
      (o) => o.value.toLowerCase() === currentEmail
    );
    if (ownOption) {
      ownOption.selected = true;
      defaultOpt.disabled = true;
      defaultOpt.hidden = true;
      metricsState.selectedLead = ownOption.value;
      shouldRefreshCards = true;
    }
  } else if (previousSelection) {
    const existing = [...select.options].find(
      (opt) => opt.value === previousSelection
    );
    if (existing) {
      existing.selected = true;
      defaultOpt.selected = false;
      metricsState.selectedLead = previousSelection;
      shouldRefreshCards = true;
    } else {
      metricsState.selectedLead = "";
    }
  } else {
    metricsState.selectedLead = "";
  }

  select.onchange = (ev) => {
    const hrLeadEmail = ev.target.value;
    metricsState.selectedLead = hrLeadEmail;
    updateCardsForLead(hrLeadEmail);
  };

  if (shouldRefreshCards) {
    updateCardsForLead(metricsState.selectedLead);
  }
}

function updatePeriodInfo() {
  const el = $("#periodInfo");
  if (!el) return;

  const start = metricsState.rangeStart;
  const end = metricsState.rangeEnd;

  if (!start || !end) {
    el.textContent = "";
    return;
  }

  const prettyStart = formatYMDForDisplay(start);
  const prettyEnd = formatYMDForDisplay(end);

  el.textContent = `Selected window: ${prettyStart} — ${prettyEnd}`;
}

function updateLeft90RangeLabel() {
  const el = $("#left90RangeLabel");
  if (!el) return;

  const start = metricsState.left90RangeStart;
  const end = metricsState.left90RangeEnd;

  if (!start || !end) {
    el.textContent = "";
    return;
  }

  const prettyStart = formatYMDForDisplay(start);
  const prettyEnd = formatYMDForDisplay(end);
  el.textContent = `Window: ${prettyStart} — ${prettyEnd}`;
}

async function fetchMetrics(rangeStartYMD = null, rangeEndYMD = null) {
  try {
    showRangeError(null);

    const url = new URL(`${API_BASE}/recruiter-metrics`);
    if (rangeStartYMD && rangeEndYMD) {
      url.searchParams.set("start", rangeStartYMD);
      url.searchParams.set("end", rangeEndYMD);
    }

    const resp = await fetch(url.toString(), {
      credentials: "include",
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.status !== "ok") throw new Error(data.message || "Unexpected response");

    metricsState.monthStart = data.month_start; // exclusivo end viene del backend
    metricsState.monthEnd = data.month_end;

    metricsState.rangeStart = data.range_start || isoToYMD(data.month_start);
    metricsState.rangeEnd = data.range_end || null;
    metricsState.left90RangeStart = data.left90_range_start || null;
    metricsState.left90RangeEnd = data.left90_range_end || null;

    setRangeInputs(metricsState.rangeStart, metricsState.rangeEnd);

    if (!metricsState.currentUserEmail && data.current_user_email) {
      metricsState.currentUserEmail = data.current_user_email.toLowerCase();
    }

    const byLead = {};
    const orderedEmails = [];
    const seenEmails = new Set();

    const addEmail = (raw) => {
      const email = String(raw || "").toLowerCase();
      if (!email || EXCLUDED_EMAILS.has(email) || seenEmails.has(email)) return;
      seenEmails.add(email);
      orderedEmails.push(email);
    };

    for (const row of data.metrics || []) {
      const email = (row.hr_lead_email || row.hr_lead || "").toLowerCase();
      if (!email || EXCLUDED_EMAILS.has(email)) continue;
      byLead[email] = row;
      addEmail(email);
    }

    (metricsState.recruiterDirectory || []).forEach((person) => addEmail(person.email));

    metricsState.byLead = byLead;
    metricsState.orderedLeadEmails = orderedEmails;
    metricsState.churnDetails = Array.isArray(data.churn_details) ? data.churn_details : [];
    metricsState.churnSummary = data.churn_summary || null;
    metricsState.opportunityDetails = normalizeOpportunityDetails(data.opportunity_details);
    metricsState.durationDetails = normalizeDurationDetails(data.duration_details);
    metricsState.pipelineDetails = normalizePipelineDetails(data.pipeline_details);

    populateDropdown();
    updatePeriodInfo();
    updateDynamicRangeLabels();
    updateLeft90RangeLabel();
  } catch (err) {
    console.error("Error loading recruiter metrics:", err);
    showRangeError("Couldn’t load metrics for that range. Try again.");
    const select = $("#hrLeadSelect");
    if (select) {
      select.innerHTML = "";
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Error loading metrics";
      opt.disabled = true;
      opt.selected = true;
      select.appendChild(opt);
    }
  }
}

function normalizeOpportunityDetails(raw) {
  const normalized = {};
  if (!raw || typeof raw !== "object") return normalized;
  Object.entries(raw).forEach(([email, rows]) => {
    const key = String(email || "").toLowerCase();
    if (!key) return;
    normalized[key] = (rows || []).map((row, index) => ({
      opportunity_id: row.opportunity_id || `opportunity-${index}`,
      opportunity_title: row.opportunity_title || "Untitled opportunity",
      opportunity_client_name: row.opportunity_client_name || "",
      opportunity_stage: row.opportunity_stage || "",
      close_date: row.close_date || null,
    }));
  });
  return normalized;
}
function normalizeDurationDetails(raw) {
  const normalized = {};
  if (!raw || typeof raw !== "object") return normalized;
  Object.entries(raw).forEach(([email, bucket]) => {
    const leadKey = String(email || "").toLowerCase();
    if (!leadKey) return;
    const perMetric = {};
    Object.entries(bucket || {}).forEach(([metricKey, rows]) => {
      perMetric[metricKey] = (rows || []).map((row, index) => ({
        opportunity_id: row.opportunity_id || `duration-${metricKey}-${index}`,
        opportunity_title: row.opportunity_title || "Untitled opportunity",
        opportunity_client_name: row.opportunity_client_name || "",
        opportunity_stage: row.opportunity_stage || "",
        duration_days: row.duration_days ?? null,
        close_date: row.close_date || null,
        first_batch_date: row.first_batch_date || null,
        start_reference_date: row.start_reference_date || null,
      }));
    });
    normalized[leadKey] = perMetric;
  });
  return normalized;
}
function normalizePipelineDetails(raw) {
  const normalized = {};
  if (!raw || typeof raw !== "object") return normalized;
  Object.entries(raw).forEach(([email, rows]) => {
    const key = String(email || "").toLowerCase();
    if (!key) return;
    normalized[key] = (rows || []).map((row, index) => ({
      candidate_id: row.candidate_id ?? null,
      candidate_name: row.candidate_name || "",
      candidate_email: row.candidate_email || "",
      candidate_status: row.candidate_status || "",
      opportunity_id: row.opportunity_id ?? null,
      opportunity_title: row.opportunity_title || "",
      opportunity_client_name: row.opportunity_client_name || "",
      batch_id: row.batch_id ?? null,
      batch_number: row.batch_number ?? null,
      sent_date: row.sent_date || null,
      is_interview_eligible: Boolean(row.is_interview_eligible),
      is_interviewed: Boolean(row.is_interviewed),
      is_hired: Boolean(row.is_hired),
    }));
  });
  return normalized;
}

function wireRangePicker() {
  const btn = document.getElementById("applyRangeBtn");
  const s = document.getElementById("rangeStart");
  const e = document.getElementById("rangeEnd");
  if (!btn || !s || !e) return;

  btn.addEventListener("click", async () => {
    const start = (s.value || "").trim();
    const end = (e.value || "").trim();

    if (!start || !end) {
      showRangeError("Pick both start and end dates.");
      return;
    }
    if (end < start) {
      showRangeError("End date must be after start date.");
      return;
    }

    metricsState.rangeStart = start;
    metricsState.rangeEnd = end;

    await fetchMetrics(start, end);

    const sel = document.getElementById("hrLeadSelect");
    if (sel && sel.value) updateCardsForLead(sel.value);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupMetricDetailModal();
  wireMetricDetailCards();
  (async () => {
    const uid = await ensureUserIdInURL();
    await loadRecruiterDirectory();
    if (!uid) {
      await fetchMetrics();
      return;
    }

    await loadCurrentUserEmail(); 
    toggleRecruiterLabButton(); 
    await fetchMetrics();
    wireRangePicker();
  })();
});
