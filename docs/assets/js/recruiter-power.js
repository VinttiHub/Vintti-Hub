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
  "paz@vintti.com",
]);
const RESTRICTION_EXCEPTIONS = new Set([
  "agostina@vintti.com",
]);
const RECRUITER_POWER_ALLOWED = new Set([
  "angie@vintti.com",
  "agostina@vintti.com",
  "agustin@vintti.com",
  "lara@vintti.com"
]);
const GLOBAL_AVERAGE_KEY = "__all_recruiters_average__";
const GLOBAL_AVERAGE_LABEL = "All recruiters · average view";

const metricsState = {
  byLead: {},            // { email: { ...metrics } }
  orderedLeadEmails: [], // [ email, email, ... ]
  monthStart: null,
  monthEnd: null,
  currentUserEmail: null,
  rangeStart: null, // YYYY-MM-DD inclusive
  rangeEnd: null,   // YYYY-MM-DD inclusive
  churnDetails: [],
  left90ChurnDetails: [],
  churnSummary: null,
  selectedLead: "",
  recruiterDirectory: [],
  recruiterLookup: {},
  left90RangeStart: null,
  left90RangeEnd: null,
  opportunityDetails: {},
  durationDetails: {},
  pipelineDetails: {},
  sentVsInterviewDetails: {},
  historyMonthlyWindows: [],
  historyCache: {},
  historyRangeStart: "",
  historyRangeEnd: "",
  historyError: "",
  historyLoading: false,
  activeTab: "summary",
  historyDetailCache: {},
  globalAverageSummary: null,
};
const HISTORY_START_YEAR = 2025;
const HISTORY_START_MONTH_INDEX = 0;
const historyDom = {
  panel: null,
  subtitle: null,
  globalFilters: null,
  startInput: null,
  endInput: null,
  quickActions: null,
  error: null,
  empty: null,
  highlights: null,
  loading: null,
  grid: null,
  tableCard: null,
  tableHead: null,
  tableBody: null,
  currentCards: [],
  chartModal: null,
  chartModalTitle: null,
  chartModalDescription: null,
  chartModalContent: null,
};
let historyChartModalPrevOverflow = "";
metricsState.historyMonthlyWindows = buildMonthlyWindows(
  HISTORY_START_YEAR,
  HISTORY_START_MONTH_INDEX
);
if (metricsState.historyMonthlyWindows.length) {
  metricsState.historyRangeStart = metricsState.historyMonthlyWindows[0].key;
  metricsState.historyRangeEnd =
    metricsState.historyMonthlyWindows[metricsState.historyMonthlyWindows.length - 1].key;
}
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

function isRestrictedEmail(email) {
  if (!email) return false;
  const normalized = String(email).toLowerCase();
  return (
    RESTRICTED_EMAILS.has(normalized) &&
    !RESTRICTION_EXCEPTIONS.has(normalized)
  );
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
function getLeadLabel(email, state = metricsState) {
  const key = (email || "").toLowerCase();
  const byLead = state.byLead || metricsState.byLead || {};
  const lookup = state.recruiterLookup || metricsState.recruiterLookup || {};
  const row = byLead[key];
  if (row) {
    return row.hr_lead_name || row.hr_lead || email;
  }
  return lookup[key] || email;
}

/* 🌟 NUEVO: helpers de animación numérica */
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
function formatAverageCount(value) {
  if (value == null || Number.isNaN(value)) return "0";
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
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
function getLeadOpportunities(hrLeadEmail, state = metricsState) {
  const key = (hrLeadEmail || "").toLowerCase();
  return (state.opportunityDetails && state.opportunityDetails[key]) || [];
}
function getLeadDurationDetails(hrLeadEmail, state = metricsState) {
  const key = (hrLeadEmail || "").toLowerCase();
  return (state.durationDetails && state.durationDetails[key]) || {};
}
function getPipelineDetails(hrLeadEmail, state = metricsState) {
  const key = (hrLeadEmail || "").toLowerCase();
  return (state.pipelineDetails && state.pipelineDetails[key]) || [];
}
function getSentVsInterviewDetails(hrLeadEmail, state = metricsState) {
  const key = (hrLeadEmail || "").toLowerCase();
  return (state.sentVsInterviewDetails && state.sentVsInterviewDetails[key]) || [];
}
function normalizeCandidateStatus(status) {
  return (status || "").trim().toLowerCase();
}
function getStatusLabel(status) {
  const trimmed = (status || "").trim();
  return trimmed || "Client interviewing/testing";
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
  return stage || "Client interviewing/testing";
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
function normalizeDateToYMD(value) {
  if (!value) return "";
  if (typeof value === "string") {
    const match = value.match(/^\d{4}-\d{2}(?:-\d{2})?/);
    if (match) {
      const token = match[0];
      if (token.length === 7) {
        return `${token}-01`;
      }
      return token;
    }
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 10);
}
function createDateRangeChecker(start, end) {
  const normalizedStart = normalizeDateToYMD(start);
  const normalizedEnd = normalizeDateToYMD(end);
  if (!normalizedStart && !normalizedEnd) return null;
  if (normalizedStart && normalizedEnd && normalizedStart > normalizedEnd) return null;
  return (value) => {
    const normalizedValue = normalizeDateToYMD(value);
    if (!normalizedValue) return false;
    if (normalizedStart && normalizedValue < normalizedStart) return false;
    if (normalizedEnd && normalizedValue > normalizedEnd) return false;
    return true;
  };
}
function filterEntriesWithinRange(entries = [], rangeChecker, resolver) {
  if (!rangeChecker || typeof resolver !== "function") return entries;
  return entries.filter((entry) => {
    const resolved = resolver(entry);
    if (!resolved) return false;
    return rangeChecker(resolved);
  });
}
function filterOpportunities(opps = [], { stage, start, end } = {}) {
  const normalizedStage = stage ? normalizeStage(stage) : null;
  const isWithinRange = createDateRangeChecker(start, end);
  return opps.filter((item) => {
    if (normalizedStage && normalizeStage(item.opportunity_stage) !== normalizedStage) {
      return false;
    }
    if (isWithinRange) {
      const closeDate = item.close_date;
      if (!closeDate || !isWithinRange(closeDate)) return false;
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
  if (start && !end) {
    return `${formatDisplayDate(start)}`;
  }
  if (!start && end) {
    return `${formatDisplayDate(end)}`;
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
function resolveDurationEntryDate(entry = {}, metricKey) {
  if (!entry) return null;
  if (metricKey === "avgBatchOpen" || metricKey === "avgBatchClosed") {
    return entry.first_batch_date || entry.close_date || entry.start_reference_date || null;
  }
  return entry.close_date || entry.first_batch_date || entry.start_reference_date || null;
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
function createSentVsInterviewItems(entries = []) {
  return entries
    .slice()
    .sort((a, b) => {
      const aRatio = typeof a.ratio === "number" ? a.ratio : -1;
      const bRatio = typeof b.ratio === "number" ? b.ratio : -1;
      return bRatio - aRatio;
    })
    .map((entry, index) => {
      const title = entry.opportunity_title || "Untitled opportunity";
      const client = entry.opportunity_client_name || "";
      const sent = Number(entry.sent_candidate_count ?? 0);
      let interviewed = "—";
      if (!(entry.interviewed_count === null || entry.interviewed_count === undefined)) {
        const interviewedValue = Number(entry.interviewed_count);
        if (!Number.isNaN(interviewedValue)) interviewed = interviewedValue;
      }
      const ratioText =
        typeof entry.ratio === "number" ? formatPercent(entry.ratio) : "Ratio not documented";
      return {
        key: entry.opportunity_id || `sent-vs-interview-${index}`,
        primary: title,
        secondary: client,
        meta: `${ratioText} · ${sent} sent / ${interviewed} interviewed`,
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
function getLeadChurnDetails(hrLeadEmail, { source = "range" } = {}) {
  const key = (hrLeadEmail || "").toLowerCase();
  if (!key) return [];
  const sourceList =
    source === "left90" ? metricsState.left90ChurnDetails : metricsState.churnDetails;
  return (sourceList || []).filter(
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
function buildDetailModalPayload(type, options = {}, state = metricsState) {
  const leadKeyExplicit = options.leadKey ? options.leadKey.toLowerCase() : null;
  const effectiveLead =
    leadKeyExplicit ||
    (state.selectedLead && state.selectedLead.toLowerCase()) ||
    (metricsState.selectedLead && metricsState.selectedLead.toLowerCase()) ||
    "";
  if (!effectiveLead) return null;
  const byLead = state.byLead || metricsState.byLead || {};
  const selectedMetrics = byLead[effectiveLead];
  if (!selectedMetrics) return null;
  const recruiterName = getLeadLabel(effectiveLead, state);
  const recruiterSuffix = recruiterName ? ` for ${recruiterName}` : "";
  const rangeStart = options.rangeStart ?? metricsState.rangeStart;
  const rangeEnd = options.rangeEnd ?? metricsState.rangeEnd;
  const historyRangeMode = options.historyRangeMode || null;
  const filterRangeStart = historyRangeMode === "capEnd" ? null : rangeStart;
  const filterRangeEnd = rangeEnd || null;
  const readableRange = describeRange(rangeStart, rangeEnd);
  const rangeChecker = createDateRangeChecker(filterRangeStart, filterRangeEnd);
  const filterDetailEntries = (entries, resolver) =>
    filterEntriesWithinRange(entries, rangeChecker, resolver);
  const opportunities = getLeadOpportunities(effectiveLead, state);
  const durationDetails = getLeadDurationDetails(effectiveLead, state);
  const durationCache = {};
  const getDurationEntries = (metricKey) => {
    if (!durationCache[metricKey]) {
      const rows = durationDetails[metricKey] || [];
      durationCache[metricKey] = filterDetailEntries(rows, (entry) =>
        resolveDurationEntryDate(entry, metricKey)
      );
    }
    return durationCache[metricKey];
  };
  const getDurationItems = (metricKey) => createDurationItems(getDurationEntries(metricKey), metricKey);
  const getDurationCount = (metricKey) => getDurationEntries(metricKey).length;
  const pipelineEntries = filterDetailEntries(getPipelineDetails(effectiveLead, state), (entry) => entry.sent_date);
  const sentVsInterviewDetails = filterDetailEntries(
    getSentVsInterviewDetails(effectiveLead, state),
    (entry) => entry.sent_date || entry.close_date || entry.last_activity_date
  );

  switch (type) {
    case "closedWinRange":
      return {
        title: rangeStart && rangeEnd ? "Closed Win · Selected Range" : "Closed Win · Last 30 Days",
        context: `Closed Win opportunities${recruiterSuffix} between ${readableRange}.`,
        summaryLines: [`Count: ${selectedMetrics.closed_win_month ?? 0}`],
        items: createOpportunityItems(
          filterOpportunities(opportunities, { stage: "Close Win", start: filterRangeStart, end: filterRangeEnd })
        ),
        emptyMessage: "No Closed Win opportunities for this recruiter in the selected window.",
      };
    case "closedLostRange":
      return {
        title: rangeStart && rangeEnd ? "Closed Lost · Selected Range" : "Closed Lost · Last 30 Days",
        context: `Closed Lost opportunities${recruiterSuffix} between ${readableRange}.`,
        summaryLines: [`Count: ${selectedMetrics.closed_lost_month ?? 0}`],
        items: createOpportunityItems(
          filterOpportunities(opportunities, { stage: "Closed Lost", start: filterRangeStart, end: filterRangeEnd })
        ),
        emptyMessage: "No Closed Lost opportunities for this recruiter in the selected window.",
      };
    case "closedWinTotal":
      return {
        title: "Total Closed Win",
        context: `Lifetime Closed Win opportunities${recruiterSuffix}.`,
        summaryLines: [`Lifetime total: ${selectedMetrics.closed_win_total ?? 0}`],
        items: createOpportunityItems(
          filterOpportunities(opportunities, { stage: "Close Win", start: filterRangeStart, end: filterRangeEnd })
        ),
        emptyMessage: "No Closed Win opportunities recorded for this recruiter.",
      };
    case "closedLostTotal":
      return {
        title: "Total Closed Lost",
        context: `Lifetime Closed Lost opportunities${recruiterSuffix}.`,
        summaryLines: [`Lifetime total: ${selectedMetrics.closed_lost_total ?? 0}`],
        items: createOpportunityItems(
          filterOpportunities(opportunities, { stage: "Closed Lost", start: filterRangeStart, end: filterRangeEnd })
        ),
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
        items: createOpportunityItems(
          filterOpportunities(opportunities, { start: filterRangeStart, end: filterRangeEnd })
        ),
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
        items: createOpportunityItems(
          filterOpportunities(opportunities, { start: filterRangeStart, end: filterRangeEnd })
        ),
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
          `Interviewied candidates: ${interviewInsights.greenCount}`,
          `Client rejected cv: ${interviewInsights.redCount}`,
          `Rate: ${formatPercent(computedRate)}`,
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
          `Hired candidates: ${hireInsights.greenCount}`,
          `Not hired candidates: ${hireInsights.redCount}`,
          `Rate: ${formatPercent(computedRate)}`,
          `Sent candidates: ${totalSent}`,
        ],
        items: createPipelineItems(hireInsights.items, {
          statusResolver: getHireStatusInfo,
        }),
        emptyMessage: "No candidates were sent in the selected window.",
      };
    }
    case "sentVsInterview": {
      const sample = selectedMetrics.sent_vs_interview_sample_count || 0;
      const totals = selectedMetrics.sent_vs_interview_totals || {};
      const sentTotal = Number(totals.sent ?? 0);
      const interviewedNumber = Number(totals.interviewed);
      const interviewedDisplay = Number.isFinite(interviewedNumber) ? interviewedNumber : "—";
      const avgRatio =
        typeof selectedMetrics.avg_sent_vs_interview_ratio === "number"
          ? formatPercent(selectedMetrics.avg_sent_vs_interview_ratio)
          : "No data";
      return {
        title: "Sent vs Interviewed",
        context: `Average batches sent${recruiterSuffix} compared with recruiter-documented interview counts between ${readableRange}.`,
        summaryLines: [
          `Average ratio: ${avgRatio}`,
          `Opportunities analyzed: ${sample}`,
          `Totals: ${sentTotal} sent / ${interviewedDisplay} interviewed`,
        ],
        items: createSentVsInterviewItems(sentVsInterviewDetails),
        emptyMessage: "No opportunities with recruiter interview counts in this window.",
      };
    }
    case "churnRange": {
      const churnEntries = getLeadChurnDetails(effectiveLead);
      const lifetimeHires = Number(
        selectedMetrics.closed_win_total ?? selectedMetrics.hire_total_lifetime ?? 0
      );
      const churnTotal = Number(selectedMetrics.churn_total ?? 0);
      let churnRate = null;
      if (typeof selectedMetrics.churn_lifetime_rate === "number") {
        churnRate = selectedMetrics.churn_lifetime_rate;
      } else if (lifetimeHires > 0) {
        churnRate = churnTotal / lifetimeHires;
      }
      const summaryLines = [
        `Lifetime hires: ${lifetimeHires}`,
        `Hires who left: ${churnTotal}`,
        `Churn rate: ${formatPercent(churnRate)}`,
      ];
      const known = selectedMetrics.churn_tenure_known ?? 0;
      const missing = selectedMetrics.churn_tenure_unknown ?? 0;
      if (known || missing) {
        summaryLines.push(`Start date available: ${known} · Missing: ${missing}`);
      }
      return {
        title: "Total churn · Lifetime",
        context: `All documented hires${recruiterSuffix} and how many have left since tracking began.`,
        summaryLines,
        items: createChurnDetailItems(churnEntries),
        emptyMessage: lifetimeHires
          ? "No hires have left for this recruiter yet."
          : "No hires recorded for this recruiter.",
      };
    }
    case "churn90Days": {
      const left90Entries = getLeadChurnDetails(effectiveLead, { source: "left90" });
      const windowLabel = describeLeft90Window();
      return {
        title: "Total churn · 90-day tenure",
        context: `Churned hires${recruiterSuffix} whose end date falls between ${windowLabel}.`,
        summaryLines: [
          `Churn count: ${selectedMetrics.left90_total ?? selectedMetrics.left90_within_90 ?? 0}`,
        ],
        items: createChurnDetailItems(left90Entries),
        emptyMessage: "No hires left in this window for this recruiter.",
      };
    }
    default:
      return null;
  }
}

const TEAM_METRIC_DETAIL_CONFIG = {
  closedWinRange: {
    title: "Closed Win · Selected range",
    aggregator: "average",
    metricKey: "closed_win_month",
    getValue: (row) => safeNumber(row?.closed_win_month),
    formatValue: (value) => formatIntegerDisplay(value),
    summaryLabel: "Team average",
    formatSummaryValue: (value) => formatAverageCount(value),
  },
  closedLostRange: {
    title: "Closed Lost · Selected range",
    aggregator: "average",
    metricKey: "closed_lost_month",
    getValue: (row) => safeNumber(row?.closed_lost_month),
    formatValue: (value) => formatIntegerDisplay(value),
    summaryLabel: "Team average",
    formatSummaryValue: (value) => formatAverageCount(value),
  },
  closedWinTotal: {
    title: "Total Closed Win",
    aggregator: "sum",
    metricKey: "closed_win_total",
    getValue: (row) => safeNumber(row?.closed_win_total),
    formatValue: (value) => formatIntegerDisplay(value),
    summaryLabel: "Team total",
  },
  closedLostTotal: {
    title: "Total Closed Lost",
    aggregator: "sum",
    metricKey: "closed_lost_total",
    getValue: (row) => safeNumber(row?.closed_lost_total),
    formatValue: (value) => formatIntegerDisplay(value),
    summaryLabel: "Team total",
  },
  conversionRange: {
    title: "Conversion · Last 30 Days",
    aggregator: "average",
    metricKey: "conversion_rate_last_20",
    getValue: (row) => safeNumber(row?.conversion_rate_last_20),
    formatValue: (value) => formatPercent(value),
  },
  conversionLifetime: {
    title: "Conversion · Lifetime",
    aggregator: "average",
    metricKey: "conversion_rate_lifetime",
    getValue: (row) => safeNumber(row?.conversion_rate_lifetime),
    formatValue: (value) => formatPercent(value),
  },
  avgCloseWin: {
    title: "Average days to close (Win)",
    aggregator: "average",
    metricKey: "avg_days_to_close_win",
    getValue: (row) => safeNumber(row?.avg_days_to_close_win),
    formatValue: (value) => formatDaysValue(value),
  },
  avgCloseLost: {
    title: "Average days to close (Lost)",
    aggregator: "average",
    metricKey: "avg_days_to_close_lost",
    getValue: (row) => safeNumber(row?.avg_days_to_close_lost),
    formatValue: (value) => formatDaysValue(value),
  },
  avgBatchOpen: {
    title: "Average days to first batch (Open)",
    aggregator: "average",
    metricKey: "avg_days_to_first_batch_open",
    getValue: (row) => safeNumber(row?.avg_days_to_first_batch_open),
    formatValue: (value) => formatDaysValue(value),
  },
  avgBatchClosed: {
    title: "Average days to first batch (Closed)",
    aggregator: "average",
    metricKey: "avg_days_to_first_batch_closed",
    getValue: (row) => safeNumber(row?.avg_days_to_first_batch_closed),
    formatValue: (value) => formatDaysValue(value),
  },
  interviewRate: {
    title: "Interview rate",
    aggregator: "average",
    getValue: (row, leadKey, state) => {
      const insights = computeInterviewPipelineInsights(getPipelineDetails(leadKey, state));
      const pct = insights.pct ?? safeNumber(row?.interview_rate?.pct);
      return {
        value: pct,
        meta: {
          numerator: insights.greenCount,
          denominator: insights.totalEligible,
        },
      };
    },
    getSummaryValue: (metrics) => safeNumber(metrics?.interview_rate?.pct),
    formatValue: (value) => formatPercent(value),
    buildMeta: ({ metaContext, calcLabel }) => {
      const ratioText = formatRatioSubtext(metaContext?.numerator, metaContext?.denominator);
      return ratioText ? `${calcLabel} · ${ratioText}` : calcLabel;
    },
  },
  hireRate: {
    title: "Hire rate",
    aggregator: "average",
    getValue: (row, leadKey, state) => {
      const insights = computeHirePipelineInsights(getPipelineDetails(leadKey, state));
      const pct = insights.pct ?? safeNumber(row?.hire_rate?.pct);
      return {
        value: pct,
        meta: {
          numerator: insights.greenCount,
          denominator: insights.totalSent,
        },
      };
    },
    getSummaryValue: (metrics) => safeNumber(metrics?.hire_rate?.pct),
    formatValue: (value) => formatPercent(value),
    buildMeta: ({ metaContext, calcLabel }) => {
      const ratioText = formatRatioSubtext(metaContext?.numerator, metaContext?.denominator);
      return ratioText ? `${calcLabel} · ${ratioText}` : calcLabel;
    },
  },
  sentVsInterview: {
    title: "Sent vs Interviewed",
    aggregator: "average",
    metricKey: "avg_sent_vs_interview_ratio",
    getValue: (row) => safeNumber(row?.avg_sent_vs_interview_ratio),
    formatValue: (value) => formatPercent(value),
    buildMeta: ({ row, calcLabel }) => {
      const sample = row?.sent_vs_interview_sample_count || 0;
      const totals = row?.sent_vs_interview_totals || {};
      const sent = Number(totals.sent ?? 0);
      const interviewed = totals.interviewed;
      const interviewedDisplay =
        interviewed === null || interviewed === undefined || Number.isNaN(Number(interviewed))
          ? "—"
          : Number(interviewed);
      const parts = [calcLabel];
      if (sample) parts.push(`Sample: ${sample} opp${sample === 1 ? "" : "s"}`);
      parts.push(`Totals: ${sent} sent / ${interviewedDisplay} interviewed`);
      return parts.join(" · ");
    },
  },
  churnRange: {
    title: "Total churn · Lifetime",
    aggregator: "sum",
    metricKey: "churn_total",
    getValue: (row) => ({
      value: safeNumber(row?.churn_total),
      meta: {
        hires: row?.closed_win_total ?? row?.hire_total_lifetime ?? 0,
        rate: typeof row?.churn_lifetime_rate === "number" ? row.churn_lifetime_rate : null,
      },
    }),
    formatValue: (value) => formatIntegerDisplay(value),
    summaryLabel: "Team total",
    buildMeta: ({ metaContext, calcLabel }) => {
      const parts = [calcLabel];
      if (metaContext?.hires != null) parts.push(`Hires: ${metaContext.hires}`);
      if (metaContext?.rate != null) parts.push(`Rate: ${formatPercent(metaContext.rate)}`);
      return parts.join(" · ");
    },
  },
  churn90Days: {
    title: "Total churn · 90-day tenure",
    aggregator: "sum",
    metricKey: "left90_total",
    getValue: (row) => ({
      value: safeNumber(row?.left90_total ?? row?.left90_within_90),
      meta: {
        rate: typeof row?.left90_rate === "number" ? row.left90_rate : null,
        known: row?.left90_tenure_known ?? 0,
        missing: row?.left90_tenure_unknown ?? 0,
      },
    }),
    formatValue: (value) => formatIntegerDisplay(value),
    summaryLabel: "Team total",
    buildMeta: ({ metaContext, calcLabel }) => {
      const parts = [calcLabel];
      if (metaContext?.rate != null) parts.push(`Rate: ${formatPercent(metaContext.rate)}`);
      parts.push(`Known: ${metaContext?.known ?? 0}`);
      parts.push(`Missing: ${metaContext?.missing ?? 0}`);
      return parts.join(" · ");
    },
  },
};

function normalizeAverageDetailValue(result) {
  if (result && typeof result === "object" && Object.prototype.hasOwnProperty.call(result, "value")) {
    return {
      value: result.value,
      meta: result.meta || null,
    };
  }
  return { value: result, meta: null };
}

function buildAverageDetailModalPayload(type, overrides = {}, state = metricsState) {
  const config = TEAM_METRIC_DETAIL_CONFIG[type];
  const summary = state.globalAverageSummary;
  if (!config || !summary) return null;
  const leads = (state.orderedLeadEmails || []).filter((email) => state.byLead[email]);
  if (!leads.length) return null;
  const calcLabel = config.aggregator === "sum" ? "Adds to team total" : "Included in average calculation";
  const items = [];
  leads.forEach((leadKey) => {
    const row = state.byLead[leadKey];
    if (!row) return;
    const raw = typeof config.getValue === "function" ? config.getValue(row, leadKey, state) : null;
    const { value, meta } = normalizeAverageDetailValue(raw);
    if (value == null) return;
    const itemFormatter =
      typeof config.formatValue === "function"
        ? config.formatValue
        : (val) => String(val);
    const formattedValue = itemFormatter(value, row, leadKey, state);
    const metaText =
      typeof config.buildMeta === "function"
        ? config.buildMeta({ row, leadKey, state, value, formattedValue, metaContext: meta, calcLabel })
        : calcLabel;
    items.push({
      key: leadKey,
      primary: getLeadLabel(leadKey, state),
      secondary: formattedValue,
      meta: metaText,
    });
  });
  items.sort((a, b) => a.primary.localeCompare(b.primary, undefined, { sensitivity: "base" }));

  if (!items.length) {
    return {
      title: config.title,
      context: "Aggregated team view. No recruiter metrics recorded yet.",
      summaryLines: [],
      items: [],
      emptyMessage: "No recruiter metrics contributed to this calculation yet.",
    };
  }

  const summaryMetrics = summary.metrics || {};
  let summaryValue = null;
  if (typeof config.getSummaryValue === "function") {
    summaryValue = config.getSummaryValue(summaryMetrics, summary);
  } else if (config.metricKey) {
    summaryValue = summaryMetrics[config.metricKey];
  }
  const summaryLabel = config.summaryLabel || (config.aggregator === "sum" ? "Team total" : "Team average");
  const summaryFormatter =
    typeof config.formatSummaryValue === "function"
      ? config.formatSummaryValue
      : typeof config.formatValue === "function"
      ? config.formatValue
      : (val) => String(val);
  const formattedSummary = summaryValue == null ? "–" : summaryFormatter(summaryValue);
  const contributorCount = items.length;
  const summaryLines = [
    `${summaryLabel}: ${formattedSummary}`,
    config.aggregator === "sum"
      ? `Calculation: Sum of ${contributorCount} recruiter${contributorCount === 1 ? "" : "s"}.`
      : `Calculation: Average of ${contributorCount} recruiter${contributorCount === 1 ? "" : "s"}.`,
  ];
  const context =
    overrides.context ||
    `Aggregated across ${summary.leadCount} recruiter${summary.leadCount === 1 ? "" : "s"} for this metric.`;
  return {
    title: config.title,
    context,
    summaryLines,
    items,
    emptyMessage: "No recruiter metrics contributed to this calculation yet.",
  };
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
function requestMetricDetail(kind, overrides = {}, sourceState = metricsState) {
  if (!kind) return;
  let detail = null;
  if (metricsState.selectedLead) {
    detail = buildDetailModalPayload(kind, overrides, sourceState);
  } else if (metricsState.globalAverageSummary) {
    detail = buildAverageDetailModalPayload(kind, overrides, sourceState);
  }
  if (!detail) return;
  if (detail) {
    if (overrides.titleSuffix) {
      detail.title = `${detail.title || "Metric detail"} · ${overrides.titleSuffix}`;
    }
    if (overrides.appendContext) {
      const base = detail.context || "";
      detail.context = `${overrides.appendContext} ${base}`.trim();
    } else if (overrides.context) {
      detail.context = overrides.context;
    }
    if (overrides.rangeStart || overrides.rangeEnd) {
      detail.context = detail.context || `Period ${describeRange(overrides.rangeStart, overrides.rangeEnd)}`;
    }
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
  const normalizedKey = (hrLeadEmail || "").toLowerCase();
  const isAverageView = !normalizedKey;
  const effectiveKey = isAverageView ? GLOBAL_AVERAGE_KEY : normalizedKey;
  const m = metricsState.byLead[effectiveKey];
  const averageSummary = metricsState.globalAverageSummary;
  const isAverageActive = isAverageView && Boolean(averageSummary && m);
  metricsState.selectedLead = isAverageView ? "" : normalizedKey;
  const canShowDetails = Boolean(m && (!isAverageView || isAverageActive));
  setDetailCardsEnabled(canShowDetails);

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
  const sentVsInterviewEl = $("#sentVsInterviewValue");
  const sentVsInterviewHelperEl = $("#sentVsInterviewHelper");

  if (!m) {
    winMonthEl.textContent = "–";
    lostMonthEl.textContent = "–";
    winTotalEl.textContent = "–";
    lostTotalEl.textContent = "–";
    convEl.textContent = "–";
    helperEl.textContent =
      isAverageView
        ? "Team average will appear once recruiter metrics finish loading."
        : "No data available for this recruiter yet. Keep an eye on new opportunities!";
    if (convLifetimeEl) convLifetimeEl.textContent = "–";
    if (churnTotalEl) churnTotalEl.textContent = "–";
    if (churnTotalHelperEl)
      churnTotalHelperEl.textContent = "Lifetime churn will appear once hires are recorded.";
    if (left90CountEl) left90CountEl.textContent = "–";
    if (left90RateEl) {
      left90RateEl.textContent = "";
      left90RateEl.style.display = "none";
    }
    if (left90HelperEl)
      left90HelperEl.textContent = "Start dates documented: – · Missing: –";
    if (avgCloseWinEl) avgCloseWinEl.textContent = "–";
    if (avgCloseLostEl) avgCloseLostEl.textContent = "–";
    if (avgBatchOpenEl) avgBatchOpenEl.textContent = "–";
    if (avgBatchClosedEl) avgBatchClosedEl.textContent = "–";
    if (interviewRateEl) interviewRateEl.textContent = "–";
    if (interviewHelperEl) interviewHelperEl.textContent = "(— / —)";
    if (hireRateEl) hireRateEl.textContent = "–";
    if (hireHelperEl) hireHelperEl.textContent = "(— / —)";
    if (sentVsInterviewEl) sentVsInterviewEl.textContent = "–";
    if (sentVsInterviewHelperEl)
      sentVsInterviewHelperEl.textContent = "No opportunities with recruiter interview counts yet.";
    return;
  }

  const pipelineEntries = isAverageActive ? [] : getPipelineDetails(effectiveKey);
  const interviewInsights = isAverageActive
    ? averageSummary?.interviewInsights || createEmptyInterviewInsights()
    : computeInterviewPipelineInsights(pipelineEntries);
  const hireInsights = isAverageActive
    ? averageSummary?.hireInsights || createEmptyHireInsights()
    : computeHirePipelineInsights(pipelineEntries);
  const averageHelperLabel = isAverageActive
    ? averageSummary?.leadCount
      ? `Average per recruiter (${averageSummary.leadCount})`
      : "Average per recruiter"
    : "";
  const averageHelperPrefix = averageHelperLabel ? `${averageHelperLabel} · ` : "";
  const totalHelperLabel = isAverageActive
    ? averageSummary?.leadCount
      ? `Team total (${averageSummary.leadCount} recruiter${averageSummary.leadCount === 1 ? "" : "s"})`
      : "Team total"
    : "";
  const totalHelperPrefix = totalHelperLabel ? `${totalHelperLabel} · ` : "";
  const countFormatter = isAverageActive
    ? (value) => formatIntegerDisplay(value)
    : (value) => Math.round(value);
  const sumFormatter = isAverageActive
    ? (value) => formatIntegerDisplay(value)
    : (value) => Math.round(value);

  /* 🌟 NUEVO: animamos los números en vez de cambiarlos brusco */

  // --- Closed Win · This Month ---
  const newWinMonth = m.closed_win_month ?? 0;
  const fromWinMonth = parseFloatSafe(winMonthEl.textContent);
  animateValue(winMonthEl, fromWinMonth, newWinMonth, {
    formatter: countFormatter,
  });

  // --- Closed Lost · This Month ---
  const newLostMonth = m.closed_lost_month ?? 0;
  const fromLostMonth = parseFloatSafe(lostMonthEl.textContent);
  animateValue(lostMonthEl, fromLostMonth, newLostMonth, {
    formatter: countFormatter,
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
  const fromWinTotal = parseFloatSafe(winTotalEl.textContent);
  animateValue(winTotalEl, fromWinTotal, newWinTotal, {
    formatter: sumFormatter,
  });

  // --- Total Closed Lost ---
  const newLostTotal = m.closed_lost_total ?? 0;
  const fromLostTotal = parseFloatSafe(lostTotalEl.textContent);
  animateValue(lostTotalEl, fromLostTotal, newLostTotal, {
    formatter: sumFormatter,
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
    helperEl.textContent = isAverageActive
      ? "Team average unavailable: no closed opportunities recorded in this window."
      : "No closed opportunities in the last 30 days to compute this rate.";
  } else {
    if (isAverageActive) {
      helperEl.textContent = `${averageHelperLabel || "Average per recruiter"}: ${formatAverageCount(
        wins
      )} Closed Win out of ${formatAverageCount(total)} closed opportunities.`;
    } else {
      helperEl.textContent = `Selected range: ${wins} Closed Win out of ${total} closed opportunities.`;
    }
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
    if (isAverageActive && interviewHelperEl.textContent) {
      interviewHelperEl.textContent = `${averageHelperPrefix}${interviewHelperEl.textContent}`;
    }
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
    if (isAverageActive && hireHelperEl.textContent) {
      hireHelperEl.textContent = `${averageHelperPrefix}${hireHelperEl.textContent}`;
    }
  }

  if (sentVsInterviewEl && sentVsInterviewHelperEl) {
    const avgRatio = m.avg_sent_vs_interview_ratio;
    if (avgRatio == null) {
      sentVsInterviewEl.textContent = "–";
    } else {
      const fromRatio = parsePercentSafe(sentVsInterviewEl.textContent);
      animateValue(sentVsInterviewEl, fromRatio, avgRatio, {
        duration: 750,
        formatter: (v) => formatPercent(v),
      });
    }
    const sampleCount = m.sent_vs_interview_sample_count || 0;
    const totals = m.sent_vs_interview_totals || {};
    const sentTotal = Number(totals.sent ?? 0);
    const interviewedRaw = totals.interviewed;
    const interviewedDisplay =
      interviewedRaw === null ||
      interviewedRaw === undefined ||
      Number.isNaN(Number(interviewedRaw))
        ? "—"
        : Number(interviewedRaw);
    const interviewedNumber = interviewedDisplay === "—" ? null : Number(interviewedDisplay);
    if (!sampleCount) {
      sentVsInterviewHelperEl.textContent = isAverageActive
        ? "Team average unavailable: no recruiter interview logs recorded in this window."
        : "No opportunities with recruiter interview counts yet.";
    } else {
      if (isAverageActive) {
        const sentAverage = formatAverageCount(sentTotal);
        const interviewedAverage =
          interviewedNumber == null ? "—" : formatAverageCount(interviewedNumber);
        sentVsInterviewHelperEl.textContent = `${averageHelperPrefix}Avg sample: ${formatAverageCount(
          sampleCount
        )} opps · ${sentAverage} sent / ${interviewedAverage} interviewed (recruiter logs)`;
      } else {
        sentVsInterviewHelperEl.textContent = `Avg of ${sampleCount} opp${
          sampleCount === 1 ? "" : "s"
        } · ${sentTotal} sent / ${interviewedDisplay} interviewed (recruiter logs)`;
      }
    }
  }

  // --- Churn · Lifetime ---
  if (churnTotalEl && churnTotalHelperEl) {
    const newChurnTotal = m.churn_total ?? 0;
    const fromChurnTotal = parseFloatSafe(churnTotalEl.textContent);
    animateValue(churnTotalEl, fromChurnTotal, newChurnTotal, {
      formatter: sumFormatter,
    });

    const totalHires = m.closed_win_total ?? m.hire_total_lifetime ?? 0;
    const churnRate = typeof m.churn_lifetime_rate === "number" ? m.churn_lifetime_rate : null;
    if (totalHires > 0) {
      const helperParts = [];
      if (totalHelperLabel) helperParts.push(totalHelperLabel);
      helperParts.push(
        `Hires: ${isAverageActive ? formatIntegerDisplay(totalHires) : totalHires}`,
        `Left: ${isAverageActive ? formatIntegerDisplay(newChurnTotal) : newChurnTotal}`
      );
      if (churnRate != null) {
        helperParts.push(`Rate: ${formatPercent(churnRate)}`);
      }
      churnTotalHelperEl.textContent = helperParts.join(" · ");
    } else {
      churnTotalHelperEl.textContent = isAverageActive
        ? "No lifetime hires recorded yet across this recruiter set."
        : "No lifetime hires recorded for this recruiter.";
    }
  }

  // --- Window churn count (90-day card) ---
  if (left90CountEl && left90RateEl) {
    const newLeftCount = m.left90_total ?? m.left90_within_90 ?? 0;
    const fromLeftCount = parseFloatSafe(left90CountEl.textContent);
    animateValue(left90CountEl, fromLeftCount, newLeftCount, {
      formatter: sumFormatter,
    });

    const newLeftRate = m.left90_rate;
    if (newLeftRate == null) {
      left90RateEl.textContent = "";
      left90RateEl.style.display = "none";
    } else {
      left90RateEl.style.display = "";
      const fromLeftRate = parsePercentSafe(left90RateEl.textContent);
      animateValue(left90RateEl, fromLeftRate, newLeftRate, {
        duration: 750,
        formatter: (v) => formatPercent(v),
      });
    }

    if (left90HelperEl) {
      const known = m.left90_tenure_known ?? 0;
      const missing = m.left90_tenure_unknown ?? 0;
      if (isAverageActive) {
        const prefix = totalHelperPrefix || "";
        left90HelperEl.textContent = `${prefix}Start dates documented: ${formatIntegerDisplay(
          known
        )} · Missing: ${formatIntegerDisplay(missing)}`;
      } else {
        left90HelperEl.textContent = `Start dates documented: ${known} · Missing: ${missing}`;
      }
    }
  }

  // ✨ pequeño “glow” en todas las cards cuando cambian
  animateCardsFlash();

  updatePeriodInfo();
  updateHistoryGlobalMeta();
  if (metricsState.activeTab === "history") {
    refreshHistoryPanel();
  } else if (!metricsState.selectedLead) {
    resetHistoryView();
  }
}

function populateDropdown() {
  const select = $("#hrLeadSelect");
  if (!select) return;

  const previousSelection = metricsState.selectedLead || "";

  select.innerHTML = "";

  // Option placeholder
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = GLOBAL_AVERAGE_LABEL;
  defaultOpt.selected = true;
  select.appendChild(defaultOpt);

  let emails = metricsState.orderedLeadEmails.slice();
  const currentEmail = (metricsState.currentUserEmail || "").toLowerCase();

  // 🔒 Si el usuario está en la lista restringida, sólo ve su propia opción
  if (isRestrictedEmail(currentEmail)) {
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
  if (isRestrictedEmail(currentEmail)) {
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
  } else {
    updateCardsForLead("");
  }
}

function updatePeriodInfo() {
  const el = $("#periodInfo");
  if (!el) return;

  const start = metricsState.rangeStart;
  const end = metricsState.rangeEnd;
  let averageNotice = "";
  if (!metricsState.selectedLead && metricsState.globalAverageSummary?.leadCount) {
    const count = metricsState.globalAverageSummary.leadCount;
    averageNotice = `Aggregated across ${count} recruiter${count === 1 ? "" : "s"}`;
  }

  if (!start || !end) {
    el.textContent = averageNotice;
    return;
  }

  const prettyStart = formatYMDForDisplay(start);
  const prettyEnd = formatYMDForDisplay(end);

  let text = `Selected window: ${prettyStart} — ${prettyEnd}`;
  if (averageNotice) {
    text += ` · ${averageNotice}`;
  }
  el.textContent = text;
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
    metricsState.left90ChurnDetails = Array.isArray(data.left90_churn_details)
      ? data.left90_churn_details
      : [];
    metricsState.churnSummary = data.churn_summary || null;
    metricsState.opportunityDetails = normalizeOpportunityDetails(data.opportunity_details);
    metricsState.durationDetails = normalizeDurationDetails(data.duration_details);
    metricsState.pipelineDetails = normalizePipelineDetails(data.pipeline_details);
    metricsState.sentVsInterviewDetails = normalizeSentVsInterviewDetails(
      data.sent_vs_interview_details
    );
    metricsState.globalAverageSummary = buildGlobalAverageSummary(metricsState);
    if (metricsState.globalAverageSummary?.metrics) {
      metricsState.byLead[GLOBAL_AVERAGE_KEY] = metricsState.globalAverageSummary.metrics;
    } else if (metricsState.byLead[GLOBAL_AVERAGE_KEY]) {
      delete metricsState.byLead[GLOBAL_AVERAGE_KEY];
    }

    populateDropdown();
    updatePeriodInfo();
    updateDynamicRangeLabels();
    updateLeft90RangeLabel();
    updateHistoryGlobalMeta();
    if (metricsState.activeTab === "history" && metricsState.selectedLead) {
      refreshHistoryPanel();
    }
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
function normalizeSentVsInterviewDetails(raw) {
  const normalized = {};
  if (!raw || typeof raw !== "object") return normalized;
  Object.entries(raw).forEach(([email, rows]) => {
    const key = String(email || "").toLowerCase();
    if (!key) return;
    normalized[key] = (rows || []).map((row, index) => {
      const sent = Number(row?.sent_candidate_count ?? 0);
      const interviewedRaw = row?.interviewed_count;
      const interviewed =
        interviewedRaw === null || interviewedRaw === undefined
          ? null
          : Number.isFinite(Number(interviewedRaw))
          ? Number(interviewedRaw)
          : null;
      const ratioRaw = Number(row?.ratio);
      const ratio = Number.isFinite(ratioRaw) ? ratioRaw : null;
      return {
        opportunity_id: row?.opportunity_id || `sent-vs-interview-${index}`,
        opportunity_title: row?.opportunity_title || "Untitled opportunity",
        opportunity_client_name: row?.opportunity_client_name || "",
        sent_candidate_count: sent,
        interviewed_count: interviewed,
        ratio,
        sent_date: row?.sent_date || row?.first_sent_date || null,
        close_date: row?.close_date || null,
        last_activity_date: row?.last_activity_date || null,
      };
    });
  });
  return normalized;
}

function createEmptyInterviewInsights() {
  return {
    items: [],
    totalEligible: 0,
    totalSent: 0,
    greenCount: 0,
    redCount: 0,
    pct: null,
  };
}

function createEmptyHireInsights() {
  return {
    items: [],
    totalSent: 0,
    greenCount: 0,
    redCount: 0,
    pct: null,
  };
}

function buildAverageInterviewInsights(leads, state) {
  if (!leads.length) return createEmptyInterviewInsights();
  const stats = leads.map((email) => computeInterviewPipelineInsights(getPipelineDetails(email, state)));
  const avg = (selector) => averageValues(stats.map((item) => selector(item)));
  const avgPct = averageValues(
    stats.map((ins, index) => {
      if (typeof ins.pct === "number") return ins.pct;
      const row = state.byLead[leads[index]];
      return typeof row?.interview_rate?.pct === "number" ? row.interview_rate.pct : null;
    })
  );
  return {
    items: [],
    totalEligible: avg((item) => item.totalEligible ?? null) ?? 0,
    totalSent: avg((item) => item.totalSent ?? null) ?? 0,
    greenCount: avg((item) => item.greenCount ?? null) ?? 0,
    redCount: avg((item) => item.redCount ?? null) ?? 0,
    pct: avgPct ?? null,
  };
}

function buildAverageHireInsights(leads, state) {
  if (!leads.length) return createEmptyHireInsights();
  const stats = leads.map((email) => computeHirePipelineInsights(getPipelineDetails(email, state)));
  const avg = (selector) => averageValues(stats.map((item) => selector(item)));
  const avgPct = averageValues(
    stats.map((ins, index) => {
      if (typeof ins.pct === "number") return ins.pct;
      const row = state.byLead[leads[index]];
      return typeof row?.hire_rate?.pct === "number" ? row.hire_rate.pct : null;
    })
  );
  return {
    items: [],
    totalSent: avg((item) => item.totalSent ?? null) ?? 0,
    greenCount: avg((item) => item.greenCount ?? null) ?? 0,
    redCount: avg((item) => item.redCount ?? null) ?? 0,
    pct: avgPct ?? null,
  };
}

function buildGlobalAverageSummary(state = metricsState) {
  const leads = (state.orderedLeadEmails || []).filter((email) => state.byLead[email]);
  if (!leads.length) return null;
  const rows = leads.map((email) => state.byLead[email]);
  const averageFromRows = (selector) => {
    const values = [];
    rows.forEach((row, index) => {
      const raw = selector(row, index);
      if (raw === null || raw === undefined) return;
      const numeric = Number(raw);
      if (Number.isFinite(numeric)) values.push(numeric);
    });
    return averageValues(values);
  };

  const metrics = {
    hr_lead: GLOBAL_AVERAGE_LABEL,
    hr_lead_name: GLOBAL_AVERAGE_LABEL,
    hr_lead_email: GLOBAL_AVERAGE_KEY,
  };

  const numericFields = [
    "closed_win_month",
    "closed_lost_month",
    "prev_closed_win_month",
    "prev_closed_lost_month",
    "closed_win_total",
    "closed_lost_total",
    "conversion_rate_last_20",
    "last_20_count",
    "last_20_win",
    "conversion_rate_lifetime",
    "avg_days_to_close_win",
    "avg_days_to_close_lost",
    "avg_days_to_first_batch_open",
    "avg_days_to_first_batch_closed",
    "sent_vs_interview_sample_count",
    "churn_total",
    "hire_total_lifetime",
    "churn_tenure_known",
    "churn_tenure_unknown",
    "left90_total",
    "left90_within_90",
    "left90_tenure_known",
    "left90_tenure_unknown",
  ];

  const sumFields = new Set([
    "closed_win_month",
    "closed_lost_month",
    "prev_closed_win_month",
    "prev_closed_lost_month",
    "closed_win_total",
    "closed_lost_total",
    "churn_total",
    "hire_total_lifetime",
    "churn_tenure_known",
    "churn_tenure_unknown",
    "left90_total",
    "left90_within_90",
    "left90_tenure_known",
    "left90_tenure_unknown",
  ]);
  numericFields.forEach((field) => {
    if (sumFields.has(field)) {
      const values = rows
        .map((row) => safeNumber(row?.[field]))
        .filter((value) => value != null);
      if (values.length) {
        metrics[field] = values.reduce((acc, value) => acc + value, 0);
      } else {
        metrics[field] = 0;
      }
      return;
    }
    const avgValue = averageFromRows((row) => row[field]);
    if (avgValue != null) {
      metrics[field] = avgValue;
    }
  });

  const avgInterviewPct = averageFromRows((row) => row?.interview_rate?.pct);
  if (avgInterviewPct != null) {
    metrics.interview_rate = { pct: avgInterviewPct };
  }
  const avgHirePct = averageFromRows((row) => row?.hire_rate?.pct);
  if (avgHirePct != null) {
    metrics.hire_rate = { pct: avgHirePct };
  }
  const avgSentTotals = averageFromRows((row) => row?.sent_vs_interview_totals?.sent);
  const avgInterviewTotals = averageFromRows((row) => row?.sent_vs_interview_totals?.interviewed);
  if (avgSentTotals != null || avgInterviewTotals != null) {
    metrics.sent_vs_interview_totals = {};
    if (avgSentTotals != null) metrics.sent_vs_interview_totals.sent = avgSentTotals;
    if (avgInterviewTotals != null) metrics.sent_vs_interview_totals.interviewed = avgInterviewTotals;
  }

  const avgChurnRate = averageFromRows((row) => row?.churn_lifetime_rate);
  if (avgChurnRate != null) {
    metrics.churn_lifetime_rate = avgChurnRate;
  }
  const avgLeft90Rate = averageFromRows((row) => row?.left90_rate);
  if (avgLeft90Rate != null) {
    metrics.left90_rate = avgLeft90Rate;
  }
  const avgSentInterviewRatio = averageFromRows((row) => row?.avg_sent_vs_interview_ratio);
  if (avgSentInterviewRatio != null) {
    metrics.avg_sent_vs_interview_ratio = avgSentInterviewRatio;
  }

  return {
    key: GLOBAL_AVERAGE_KEY,
    label: GLOBAL_AVERAGE_LABEL,
    leadCount: leads.length,
    metrics,
    interviewInsights: buildAverageInterviewInsights(leads, state),
    hireInsights: buildAverageHireInsights(leads, state),
  };
}

function buildDetailStateFromPayload(payload) {
  const state = {
    byLead: {},
    opportunityDetails: normalizeOpportunityDetails(payload.opportunity_details),
    durationDetails: normalizeDurationDetails(payload.duration_details),
    pipelineDetails: normalizePipelineDetails(payload.pipeline_details),
    sentVsInterviewDetails: normalizeSentVsInterviewDetails(payload.sent_vs_interview_details),
    recruiterLookup: metricsState.recruiterLookup,
    selectedLead: metricsState.selectedLead,
  };
  (payload.metrics || []).forEach((row) => {
    const email = (row.hr_lead_email || row.hr_lead || "").toLowerCase();
    if (!email || EXCLUDED_EMAILS.has(email)) return;
    state.byLead[email] = row;
  });
  return state;
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
    if (!sel || !sel.value) {
      updateHistoryGlobalMeta();
      if (metricsState.activeTab === "history") {
        resetHistoryView();
      }
    }
  });
}

/* ==========================================================================
   Historic trends dashboard
   ========================================================================== */

function safeNumber(value) {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatIntegerDisplay(value) {
  if (value === null || value === undefined) return "–";
  const rounded = Math.round(value);
  return Number.isFinite(rounded) ? rounded.toLocaleString("en-US") : "–";
}

function formatPercentNumber(value) {
  if (value === null || value === undefined) return "–";
  const fixed = Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(1);
  return `${fixed.replace(/\.0$/, "")}%`;
}

function convertPercentValue(value) {
  const numeric = safeNumber(value);
  if (numeric === null) return null;
  return numeric * 100;
}

function accumulateSeries(points = []) {
  let running = 0;
  return points.map((point) => {
    if (point.value != null) {
      running += point.value;
    }
    return { ...point, value: point.value == null ? null : running };
  });
}

function getLineChartData(points, width, height) {
  if (!points.length) {
    return { pathPoints: [], areaPath: "" };
  }
  const values = points.map((point) => point.value).filter((value) => value != null);
  if (!values.length) {
    return { pathPoints: [], areaPath: "" };
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const total = points.length;
  const pathPoints = [];
  points.forEach((point, index) => {
    if (point.value == null) return;
    const x = total > 1 ? (index / (total - 1)) * width : width / 2;
    const y = height - ((point.value - min) / range) * height;
    pathPoints.push({
      x: Number(x.toFixed(2)),
      y: Number(y.toFixed(2)),
      label: point.label || point.key || "",
      key: point.key,
      value: point.value,
      rangeStart: point.start,
      rangeEnd: point.end,
    });
  });
  const pathSequence = pathPoints.map((pt) => `${pt.x},${pt.y}`);
  const startPoint = pathSequence[0];
  const lineSegment = pathSequence.slice(1).map((point) => `L ${point}`).join(" ");
  const areaPath = startPoint ? `M ${startPoint} ${lineSegment} L ${width},${height} L 0,${height} Z` : "";
  return { pathPoints, areaPath };
}

function getColumnChartData(points, width, height) {
  if (!points.length) {
    return [];
  }
  const values = points.map((point) => point.value).filter((value) => value != null);
  if (!values.length) {
    return [];
  }
  const max = Math.max(...values) || 1;
  const total = points.length;
  const slotWidth = total ? width / total : width;
  const columnWidth = Math.max(slotWidth * 0.6, 6);
  return points
    .map((point, index) => {
      if (point.value == null) return null;
      const scaled = (point.value / max) * height;
      const center = total > 0 ? index * slotWidth + slotWidth / 2 : width / 2;
      return {
        key: point.key,
        label: point.label || point.key || "",
        value: point.value,
        rangeStart: point.start,
        rangeEnd: point.end,
        x: Number((center - columnWidth / 2).toFixed(2)),
        y: Number((height - scaled).toFixed(2)),
        width: columnWidth,
        height: Math.max(scaled, 2),
      };
    })
    .filter(Boolean);
}

function findExtremum(list = [], getter, lookForMax) {
  let best = null;
  list.forEach((entry) => {
    const value = getter(entry);
    if (value == null) return;
    if (!best) {
      best = { label: entry.label, value };
      return;
    }
    if (lookForMax ? value > best.value : value < best.value) {
      best = { label: entry.label, value };
    }
  });
  return best;
}

function averageValues(values = []) {
  const usable = values.filter((value) => value != null);
  if (!usable.length) return null;
  const total = usable.reduce((sum, value) => sum + value, 0);
  return total / usable.length;
}

function buildMonthlyWindows(startYear, startMonthIndex) {
  const windows = [];
  const formatter = new Intl.DateTimeFormat("en", { month: "short", year: "numeric" });
  const now = new Date();
  const endCursor = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1);
  for (let cursor = Date.UTC(startYear, startMonthIndex, 1); cursor <= endCursor; ) {
    const currentDate = new Date(cursor);
    const year = currentDate.getUTCFullYear();
    const monthIndex = currentDate.getUTCMonth();
    const key = `${year}-${String(monthIndex + 1).padStart(2, "0")}`;
    const start = `${year}-${String(monthIndex + 1).padStart(2, "0")}-01`;
    const monthEndDate = new Date(Date.UTC(year, monthIndex + 1, 0));
    const end = monthEndDate.toISOString().slice(0, 10);
    windows.push({
      key,
      label: formatter.format(currentDate),
      start,
      end,
    });
    cursor = Date.UTC(year, monthIndex + 1, 1);
  }
  return windows;
}

function buildQuickRanges(months) {
  if (!months?.length) return [];
  const ranges = [];
  const lastIndex = months.length - 1;
  const computeRangeFromEnd = (length) => {
    const startIndex = Math.max(months.length - length, 0);
    return { start: months[startIndex].key, end: months[lastIndex].key };
  };
  const computeYearToDate = () => {
    const latest = months[lastIndex];
    const [year] = latest.key.split("-");
    const firstIndex = months.findIndex((item) => item.key.startsWith(`${year}-`));
    if (firstIndex === -1) return null;
    return { start: months[firstIndex].key, end: latest.key };
  };
  const last6 = computeRangeFromEnd(6);
  const last12 = computeRangeFromEnd(12);
  const ytd = computeYearToDate();
  if (last6) ranges.push({ id: "6m", label: "Last 6 months", range: last6 });
  if (last12) ranges.push({ id: "12m", label: "Last 12 months", range: last12 });
  if (ytd) ranges.push({ id: "ytd", label: "Year to date", range: ytd });
  ranges.push({
    id: "full",
    label: "Full history",
    range: { start: months[0].key, end: months[lastIndex].key },
  });
  return ranges;
}

const HISTORY_METRICS = [
  {
    id: "closed_win_month",
    title: "Closed Win",
    description: "Deals marked as Closed Win each month.",
    chart: "column",
    color: "#6c5ce7",
    goodWhenHigher: true,
    extractor: (metrics) => safeNumber(metrics?.closed_win_month ?? 0),
    formatter: formatIntegerDisplay,
  },
  {
    id: "closed_lost_month",
    title: "Closed Lost",
    description: "Closed Lost opportunities per month.",
    chart: "column",
    color: "#f06595",
    goodWhenHigher: false,
    extractor: (metrics) => safeNumber(metrics?.closed_lost_month ?? 0),
    formatter: formatIntegerDisplay,
  },
  {
    id: "closed_win_total",
    title: "Total Closed Win",
    description: "Cumulative wins since Jan 2025.",
    chart: "line",
    color: "#9775fa",
    goodWhenHigher: true,
    extractor: (metrics) => safeNumber(metrics?.closed_win_month ?? 0),
    formatter: formatIntegerDisplay,
    accumulate: true,
  },
  {
    id: "closed_lost_total",
    title: "Total Closed Lost",
    description: "Cumulative Closed Lost since Jan 2025.",
    chart: "line",
    color: "#ff8fa3",
    goodWhenHigher: false,
    extractor: (metrics) => safeNumber(metrics?.closed_lost_month ?? 0),
    formatter: formatIntegerDisplay,
    accumulate: true,
  },
  {
    id: "conversion_range",
    title: "Conversion · Range",
    description: "Share of Closed Win over closed opps each month.",
    chart: "line",
    color: "#0ea5e9",
    goodWhenHigher: true,
    extractor: (metrics) => convertPercentValue(metrics?.conversion_rate_last_20),
    formatter: formatPercentNumber,
  },
  {
    id: "conversion_lifetime",
    title: "Conversion · Lifetime",
    description: "Lifetime conversion snapshot per month.",
    chart: "line",
    color: "#38bdf8",
    goodWhenHigher: true,
    extractor: (metrics) => convertPercentValue(metrics?.conversion_rate_lifetime),
    formatter: formatPercentNumber,
  },
  {
    id: "avg_days_to_close_win",
    title: "Avg days to close · Win",
    description: "From start to Closed Win per month.",
    chart: "line",
    color: "#1abcfe",
    goodWhenHigher: false,
    extractor: (metrics) => safeNumber(metrics?.avg_days_to_close_win),
    formatter: (value) => formatDaysValue(value),
  },
  {
    id: "avg_days_to_close_lost",
    title: "Avg days to close · Lost",
    description: "From start to Closed Lost per month.",
    chart: "line",
    color: "#ff6b6b",
    goodWhenHigher: false,
    extractor: (metrics) => safeNumber(metrics?.avg_days_to_close_lost),
    formatter: (value) => formatDaysValue(value),
  },
  {
    id: "avg_days_to_first_batch_open",
    title: "Avg days to first batch · Open",
    description: "Open opps reaching first batch.",
    chart: "line",
    color: "#f7b731",
    goodWhenHigher: false,
    extractor: (metrics) => safeNumber(metrics?.avg_days_to_first_batch_open),
    formatter: (value) => formatDaysValue(value),
  },
  {
    id: "avg_days_to_first_batch_closed",
    title: "Avg days to first batch · Closed",
    description: "Closed opps reaching first batch.",
    chart: "line",
    color: "#f39c12",
    goodWhenHigher: false,
    extractor: (metrics) => safeNumber(metrics?.avg_days_to_first_batch_closed),
    formatter: (value) => formatDaysValue(value),
  },
  {
    id: "interview_rate",
    title: "Interview rate",
    description: "Interview-eligible candidates who advanced.",
    chart: "line",
    color: "#10b981",
    goodWhenHigher: true,
    extractor: (metrics = {}) => {
      const eligible = safeNumber(metrics.interview_eligible_candidate_count);
      const interviewed = safeNumber(metrics.interviewed_candidate_count);
      if (!eligible) return null;
      return (interviewed / eligible) * 100;
    },
    formatter: formatPercentNumber,
  },
  {
    id: "hire_rate",
    title: "Hire rate",
    description: "Sent candidates that converted into hires.",
    chart: "line",
    color: "#f97316",
    goodWhenHigher: true,
    extractor: (metrics = {}) => {
      const sent = safeNumber(metrics.sent_candidate_count);
      const hired = safeNumber(metrics.hired_candidate_count);
      if (!sent) return null;
      return (hired / sent) * 100;
    },
    formatter: formatPercentNumber,
  },
  {
    id: "sent_vs_interview_ratio",
    title: "Sent vs Interviewed",
    description: "Average share of candidates interviewed vs sent.",
    chart: "line",
    color: "#f59e0b",
    goodWhenHigher: true,
    extractor: (metrics) => convertPercentValue(metrics?.avg_sent_vs_interview_ratio),
    formatter: formatPercentNumber,
  },
];

const HISTORY_METRIC_DETAIL_MAP = {
  closed_win_month: "closedWinRange",
  closed_lost_month: "closedLostRange",
  closed_win_total: "closedWinTotal",
  closed_lost_total: "closedLostTotal",
  conversion_range: "conversionRange",
  conversion_lifetime: "conversionLifetime",
  avg_days_to_close_win: "avgCloseWin",
  avg_days_to_close_lost: "avgCloseLost",
  avg_days_to_first_batch_open: "avgBatchOpen",
  avg_days_to_first_batch_closed: "avgBatchClosed",
  interview_rate: "interviewRate",
  hire_rate: "hireRate",
  sent_vs_interview_ratio: "sentVsInterview",
};

function setupTabs() {
  const tabs = document.querySelectorAll("[data-tab-target]");
  const panels = document.querySelectorAll("[data-tab-panel]");
  if (!tabs.length || !panels.length) return;

  const activateTab = (target) => {
    metricsState.activeTab = target;
    tabs.forEach((tab) => {
      const isActive = tab.dataset.tabTarget === target;
      tab.classList.toggle("is-active", isActive);
      tab.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    panels.forEach((panel) => {
      const isActive = panel.getAttribute("data-tab-panel") === target;
      panel.classList.toggle("is-active", isActive);
      panel.setAttribute("aria-hidden", isActive ? "false" : "true");
    });
    if (target === "history") {
      refreshHistoryPanel();
    } else {
      hideHistoryTooltip();
    }
  };

  tabs.forEach((tab, index) => {
    if (!tab.hasAttribute("role")) {
      tab.setAttribute("role", "tab");
    }
    const isActive = tab.classList.contains("is-active");
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
    if (!isActive && index === 0) {
      tab.setAttribute("tabindex", "-1");
    }
    tab.addEventListener("click", () => {
      const target = tab.dataset.tabTarget;
      if (!target || metricsState.activeTab === target) return;
      activateTab(target);
    });
  });

  panels.forEach((panel) => {
    if (!panel.hasAttribute("role")) {
      panel.setAttribute("role", "tabpanel");
    }
    const isActive = panel.classList.contains("is-active");
    panel.setAttribute("aria-hidden", isActive ? "false" : "true");
  });
}

function initializeHistoryUI() {
  historyDom.panel = document.getElementById("historyPanel");
  if (!historyDom.panel) return;
  historyDom.subtitle = document.getElementById("historySubtitle");
  historyDom.globalFilters = document.getElementById("historyGlobalFilters");
  historyDom.startInput = document.getElementById("historyRangeStart");
  historyDom.endInput = document.getElementById("historyRangeEnd");
  historyDom.quickActions = document.getElementById("historyQuickActions");
  historyDom.error = document.getElementById("historyError");
  historyDom.empty = document.getElementById("historyEmpty");
  historyDom.highlights = document.getElementById("historyHighlights");
  historyDom.loading = document.getElementById("historyLoading");
  historyDom.grid = document.getElementById("historyGrid");
  historyDom.tableCard = document.getElementById("historyTableContainer");
  historyDom.tableHead = document.getElementById("historyTableHead");
  historyDom.tableBody = document.getElementById("historyTableBody");

  if (historyDom.startInput) {
    historyDom.startInput.addEventListener("change", (event) =>
      handleHistoryRangeChange("start", event.target.value)
    );
  }
  if (historyDom.endInput) {
    historyDom.endInput.addEventListener("change", (event) =>
      handleHistoryRangeChange("end", event.target.value)
    );
  }

  renderHistoryQuickActions();
  syncHistoryRangeInputs();
  updateHistoryGlobalMeta();
  resetHistoryView();
}

function setupHistoryChartModal() {
  historyDom.chartModal = document.getElementById("historyChartModal");
  if (!historyDom.chartModal) return;
  historyDom.chartModalTitle = document.getElementById("historyChartModalTitle");
  historyDom.chartModalDescription = document.getElementById("historyChartModalDescription");
  historyDom.chartModalContent = document.getElementById("historyChartModalContent");
  const closers = historyDom.chartModal.querySelectorAll("[data-chart-modal-close]");
  closers.forEach((element) => {
    element.addEventListener("click", closeHistoryChartModal);
  });
  historyDom.chartModal.addEventListener("click", (event) => {
    if (event.target.dataset && event.target.dataset.chartModalClose !== undefined) {
      closeHistoryChartModal();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && historyDom.chartModal && !historyDom.chartModal.hidden) {
      closeHistoryChartModal();
    }
  });
  attachHistoryHoverHandlers(historyDom.chartModalContent);
}

function openHistoryChartModal(cardId) {
  if (!historyDom.chartModal || !historyDom.chartModalContent) return;
  const card = (historyDom.currentCards || []).find((item) => item.id === cardId);
  if (!card) return;
  const hasData = card.points.some((point) => point.value != null);
  if (!hasData) return;

  historyDom.chartModalTitle.textContent = card.title || "Metric detail";
  historyDom.chartModalDescription.textContent = card.description || "";
  const chartMarkup =
    card.chart === "column"
      ? renderColumnChart(card, { width: 900, height: 320 })
      : renderLineChart(card, { width: 900, height: 320, pointRadius: 9 });
  historyDom.chartModalContent.innerHTML = chartMarkup;
  attachHistoryHoverHandlers(historyDom.chartModalContent);
  historyChartModalPrevOverflow = document.body.style.overflow || "";
  document.body.style.overflow = "hidden";
  historyDom.chartModal.hidden = false;
}

function closeHistoryChartModal() {
  if (!historyDom.chartModal) return;
  historyDom.chartModal.hidden = true;
  if (historyDom.chartModalContent) {
    historyDom.chartModalContent.innerHTML = "";
  }
  hideHistoryTooltip();
  document.body.style.overflow = historyChartModalPrevOverflow || "";
  historyChartModalPrevOverflow = "";
}

function syncHistoryRangeInputs() {
  if (historyDom.startInput) {
    historyDom.startInput.value = metricsState.historyRangeStart || "";
    historyDom.startInput.max = metricsState.historyRangeEnd || "";
  }
  if (historyDom.endInput) {
    historyDom.endInput.value = metricsState.historyRangeEnd || "";
    historyDom.endInput.min = metricsState.historyRangeStart || "";
  }
}

function renderHistoryQuickActions() {
  if (!historyDom.quickActions) return;
  const quickRanges = buildQuickRanges(metricsState.historyMonthlyWindows);
  historyDom.quickActions.innerHTML = "";
  quickRanges.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-quick-btn";
    btn.textContent = item.label;
    btn.addEventListener("click", () => {
      metricsState.historyRangeStart = item.range.start;
      metricsState.historyRangeEnd = item.range.end;
      syncHistoryRangeInputs();
      if (metricsState.activeTab === "history" && metricsState.selectedLead) {
        refreshHistoryPanel();
      }
    });
    historyDom.quickActions.appendChild(btn);
  });
}

function handleHistoryRangeChange(kind, rawValue) {
  if (!rawValue) return;
  const value = rawValue;
  if (kind === "start") {
    metricsState.historyRangeStart = value;
    if (metricsState.historyRangeEnd && metricsState.historyRangeEnd < value) {
      metricsState.historyRangeEnd = value;
    }
  } else {
    metricsState.historyRangeEnd = value;
    if (metricsState.historyRangeStart && metricsState.historyRangeStart > value) {
      metricsState.historyRangeStart = value;
    }
  }
  syncHistoryRangeInputs();
  if (metricsState.activeTab === "history" && metricsState.selectedLead) {
    refreshHistoryPanel();
  }
}

function setHistoryLoading(isLoading) {
  metricsState.historyLoading = isLoading;
  if (historyDom.loading) {
    historyDom.loading.hidden = !isLoading;
  }
}

function showHistoryError(message) {
  metricsState.historyError = message || "";
  if (!historyDom.error) return;
  if (!message) {
    historyDom.error.hidden = true;
    historyDom.error.textContent = "";
    return;
  }
  historyDom.error.hidden = false;
  historyDom.error.textContent = message;
}

function setHistoryEmptyState(show, message) {
  if (!historyDom.empty) return;
  historyDom.empty.hidden = !show;
  if (message) {
    historyDom.empty.textContent = message;
  }
}

function updateHistoryGlobalMeta() {
  if (!historyDom.globalFilters) return;
  const leadLabel = metricsState.selectedLead
    ? getLeadLabel(metricsState.selectedLead)
    : metricsState.globalAverageSummary?.label || "—";
  let rangeLabel = "Rolling 30 days";
  if (metricsState.rangeStart && metricsState.rangeEnd) {
    rangeLabel = `${formatYMDForDisplay(metricsState.rangeStart)} — ${formatYMDForDisplay(
      metricsState.rangeEnd
    )}`;
  }
  historyDom.globalFilters.textContent = `${leadLabel || "—"} · ${rangeLabel}`;
}

function updateHistorySubtitleText(monthCount) {
  if (!historyDom.subtitle) return;
  if (!metricsState.selectedLead) {
    historyDom.subtitle.textContent = "Pick a recruiter to explore their timeline.";
    return;
  }
  const label = getLeadLabel(metricsState.selectedLead) || "Recruiter";
  if (monthCount == null) {
    historyDom.subtitle.textContent = `${label} · Loading timeline…`;
    return;
  }
  const suffix = `${monthCount} month${monthCount === 1 ? "" : "s"} loaded`;
  historyDom.subtitle.textContent = `${label} · ${suffix}`;
}

function resetHistoryView() {
  if (!historyDom.panel) return;
  if (!metricsState.selectedLead) {
    updateHistorySubtitleText(0);
    setHistoryEmptyState(true, "Select a recruiter above to render the dashboard.");
  }
  renderHistoryHighlights([]);
  renderHistoryCards([]);
  renderHistoryTable([]);
  hideHistoryTooltip();
}

async function refreshHistoryPanel() {
  if (!historyDom.panel) return;
  updateHistoryGlobalMeta();
  showHistoryError("");

  if (!metricsState.selectedLead) {
    resetHistoryView();
    return;
  }

  setHistoryEmptyState(false);
  updateHistorySubtitleText(null);

  await ensureHistoryDataForLead(metricsState.selectedLead);

  const timeline = getFilteredHistoryTimeline(metricsState.selectedLead);
  updateHistorySubtitleText(timeline.length);

  if (!timeline.length) {
    renderHistoryHighlights([]);
    renderHistoryCards([]);
    renderHistoryTable([]);
    setHistoryEmptyState(true, "No history found for this recruiter within the selected months.");
    return;
  }

  const highlights = buildHistoryHighlights(timeline);
  const cards = buildHistoryMetricCards(timeline);
  const tableRows = buildHistoryTableRows(timeline);

  renderHistoryHighlights(highlights);
  renderHistoryCards(cards);
  renderHistoryTable(tableRows, cards);
  setHistoryEmptyState(false);
}

async function ensureHistoryDataForLead(leadEmail) {
  const key = (leadEmail || "").toLowerCase();
  if (!key) return {};
  const windows = metricsState.historyMonthlyWindows;
  if (!windows.length) return {};
  const cache = metricsState.historyCache[key] || {};
  const missing = windows.filter((window) => !cache[window.key]);
  if (!missing.length) {
    metricsState.historyCache[key] = cache;
    return cache;
  }
  setHistoryLoading(true);
  showHistoryError("");
  try {
    const responses = await Promise.all(
      missing.map((window) => fetchHistoryWindow(window.start, window.end))
    );
    missing.forEach((window, index) => {
      const payload = responses[index] || {};
      const row = extractLeadHistoryRow(payload.metrics, key);
      cache[window.key] = {
        key: window.key,
        label: window.label,
        start: window.start,
        end: window.end,
        metrics: row,
      };
    });
    metricsState.historyCache[key] = cache;
  } catch (err) {
    console.error("[recruiter-metrics] Failed to load historic data:", err);
    showHistoryError("Could not load historic data. Please try again.");
  } finally {
    setHistoryLoading(false);
  }
  return cache;
}

function extractLeadHistoryRow(rows = [], leadKey) {
  if (!Array.isArray(rows)) return null;
  const target = (leadKey || "").toLowerCase();
  return (
    rows.find(
      (row) => (row?.hr_lead_email || row?.hr_lead || "").toLowerCase() === target
    ) || null
  );
}

async function fetchHistoryWindow(startYMD, endYMD) {
  const url = new URL(`${API_BASE}/recruiter-metrics`);
  url.searchParams.set("start", startYMD);
  url.searchParams.set("end", endYMD);
  const resp = await fetch(url.toString(), { credentials: "include" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

async function getHistoryDetailState(leadKey, rangeStart, rangeEnd) {
  const normalizedLead = (leadKey || "").toLowerCase();
  if (!normalizedLead || !rangeStart || !rangeEnd) return null;
  const leadCache =
    metricsState.historyDetailCache[normalizedLead] ||
    (metricsState.historyDetailCache[normalizedLead] = {});
  const cacheKey = `${rangeStart}::${rangeEnd}`;
  if (leadCache[cacheKey]) {
    return leadCache[cacheKey];
  }
  const data = await fetchRecruiterMetrics({ start: rangeStart, end: rangeEnd });
  const detailState = buildDetailStateFromPayload(data);
  detailState.selectedLead = normalizedLead;
  leadCache[cacheKey] = detailState;
  return detailState;
}

function getHistoryTimelineForLead(leadKey) {
  const windows = metricsState.historyMonthlyWindows || [];
  if (!windows.length) return [];
  const cache = metricsState.historyCache[leadKey] || {};
  return windows.map((window) => {
    const entry = cache[window.key];
    return {
      monthKey: window.key,
      label: window.label,
      start: window.start,
      end: window.end,
      metrics: entry?.metrics || null,
    };
  });
}

function getFilteredHistoryTimeline(leadKey) {
  const key = (leadKey || "").toLowerCase();
  if (!key) return [];
  const timeline = getHistoryTimelineForLead(key);
  return timeline.filter((entry) => {
    if (!entry) return false;
    if (metricsState.historyRangeStart && entry.monthKey < metricsState.historyRangeStart) {
      return false;
    }
    if (metricsState.historyRangeEnd && entry.monthKey > metricsState.historyRangeEnd) {
      return false;
    }
    return true;
  });
}

function buildHistoryMetricCards(timeline = []) {
  return HISTORY_METRICS.map((config) => {
    const basePoints = timeline.map((entry) => ({
      key: entry.monthKey,
      label: entry.label,
      start: entry.start,
      end: entry.end,
      value: config.extractor(entry.metrics),
    }));
    const points = config.accumulate ? accumulateSeries(basePoints) : basePoints;
    const populated = points.filter((pt) => pt.value != null);
    const latest = populated.length ? populated[populated.length - 1].value : null;
    const previous = populated.length > 1 ? populated[populated.length - 2].value : null;
    const average =
      populated.length > 0
        ? populated.reduce((sum, pt) => sum + pt.value, 0) / populated.length
        : null;
    return {
      ...config,
      points,
      latest,
      previous,
      average,
    };
  });
}

function buildHistoryHighlights(timeline = []) {
  const bestWin = findExtremum(
    timeline,
    (entry) => safeNumber(entry?.metrics?.closed_win_month ?? 0),
    true
  );
  const calmLost = findExtremum(
    timeline,
    (entry) => safeNumber(entry?.metrics?.closed_lost_month ?? 0),
    false
  );
  const latestConversion = timeline.length
    ? convertPercentValue(timeline[timeline.length - 1]?.metrics?.conversion_rate_last_20)
    : null;
  const avgSentInterview = averageValues(
    timeline.map((entry) => convertPercentValue(entry?.metrics?.avg_sent_vs_interview_ratio))
  );

  return [
    {
      id: "best-win",
      label: "Best month · Closed Win",
      value: bestWin?.value != null ? formatIntegerDisplay(bestWin.value) : "–",
      helper: bestWin?.label || "No win data yet",
    },
    {
      id: "lowest-lost",
      label: "Calmest month · Closed Lost",
      value: calmLost?.value != null ? formatIntegerDisplay(calmLost.value) : "–",
      helper: calmLost?.label || "No lost data yet",
    },
    {
      id: "latest-conv",
      label: "Latest conversion",
      value: latestConversion != null ? formatPercentNumber(latestConversion) : "–",
      helper: timeline.length ? timeline[timeline.length - 1].label : "Not enough data",
    },
    {
      id: "avg-sent",
      label: "Avg. Sent → Interview",
      value: avgSentInterview != null ? formatPercentNumber(avgSentInterview) : "–",
      helper: "Across selected months",
    },
  ];
}

function buildHistoryTableRows(timeline = []) {
  if (!timeline.length) return [];
  return timeline.slice(-6).reverse();
}

function renderHistoryHighlights(items = []) {
  if (!historyDom.highlights) return;
  if (!items.length) {
    historyDom.highlights.innerHTML = "";
    historyDom.highlights.hidden = true;
    return;
  }
  historyDom.highlights.hidden = false;
  historyDom.highlights.innerHTML = items
    .map(
      (item) => `
        <div class="history-spotlight">
          <span class="history-spotlight__label">${item.label}</span>
          <span class="history-spotlight__value">${item.value}</span>
          <span class="history-spotlight__meta">${item.helper}</span>
        </div>`
    )
    .join("");
}

function renderHistoryCards(cards = []) {
  if (!historyDom.grid) return;
  if (!cards.length) {
    historyDom.grid.innerHTML = "";
    historyDom.grid.hidden = true;
    hideHistoryTooltip();
    historyDom.currentCards = [];
    return;
  }
  historyDom.grid.hidden = false;
  historyDom.grid.innerHTML = cards.map((card) => createHistoryCardMarkup(card)).join("");
  historyDom.currentCards = cards;
  const cardElements = historyDom.grid.querySelectorAll("[data-history-card-id]");
  cardElements.forEach((element) => {
    const cardId = element.getAttribute("data-history-card-id");
    const clickHandler = (event) => {
      if (event && event.target.closest("[data-history-point]")) return;
      openHistoryChartModal(cardId);
    };
    element.addEventListener("click", clickHandler);
    element.addEventListener("keydown", (event) => {
      if (event.target.closest("[data-history-point]")) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openHistoryChartModal(cardId);
      }
    });
  });
  attachHistoryHoverHandlers(historyDom.grid);
}

function renderHistoryTable(rows = [], cards = historyDom.currentCards || []) {
  if (!historyDom.tableCard || !historyDom.tableBody || !historyDom.tableHead) return;
  if (!rows.length) {
    historyDom.tableBody.innerHTML = "";
    historyDom.tableHead.innerHTML = "";
    historyDom.tableCard.hidden = true;
    return;
  }
  const columns = HISTORY_METRICS;
  const cardLookup = cards.reduce((acc, card) => {
    acc[card.id] = {
      formatter: card.formatter,
      points: card.points.reduce((map, point) => {
        map[point.key] = point.value;
        return map;
      }, {}),
    };
    return acc;
  }, {});

  historyDom.tableHead.innerHTML =
    "<th>Month</th>" +
    columns.map((metric) => `<th>${metric.title}</th>`).join("");

  historyDom.tableCard.hidden = false;
  historyDom.tableBody.innerHTML = rows
    .map((entry) => {
      const cells = columns
        .map((metric) => {
          const card = cardLookup[metric.id];
          const value = card?.points?.[entry.monthKey];
          const formatted = card ? card.formatter(value) : "–";
          return `<td>${formatted}</td>`;
        })
        .join("");
      return `<tr><td>${entry.label}</td>${cells}</tr>`;
    })
    .join("");
}

function createHistoryCardMarkup(card) {
  const trend = computeHistoryTrend(
    card.latest,
    card.previous,
    card.goodWhenHigher !== false,
    card.formatter
  );
  const chartMarkup =
    card.chart === "column"
      ? renderColumnChart(card)
      : renderLineChart(card);
  return `
    <article class="history-card" data-history-card-id="${card.id}" role="button" tabindex="0" aria-label="View ${card.title} in detail">
      <div class="history-card__header">
        <div>
          <span class="history-card__label">${card.title}</span>
          <p class="history-card__description">${card.description}</p>
        </div>
        ${
          trend
            ? `<span class="history-card__trend ${trend.className}">${trend.label}</span>`
            : ""
        }
      </div>
      <div class="history-chart">
        ${chartMarkup}
      </div>
      <div class="history-card__metrics">
        <div>
          <span class="history-card__value">${card.formatter(card.latest)}</span>
          <span class="history-card__meta-label">Latest month</span>
        </div>
        <div>
          <span class="history-card__value">${card.formatter(card.average)}</span>
          <span class="history-card__meta-label">Average</span>
        </div>
      </div>
    </article>`;
}

function renderLineChart(card, options = {}) {
  const width = options.width || 320;
  const chartHeight = options.height || 120;
  const axisHeight = options.axisHeight ?? 24;
  const pointRadius = options.pointRadius || 5;
  const svgHeight = chartHeight + axisHeight;
  const { pathPoints, areaPath } = getLineChartData(card.points, width, chartHeight);
  if (!pathPoints.length) {
    return `<div class="history-chart__empty">No data for this range.</div>`;
  }
  const gradientId = `historyLine-${card.id}`;
  const ticks = buildAxisTicks(card.points, width);
  const polylinePoints = pathPoints.map((pt) => `${pt.x},${pt.y}`).join(" ");
  const circles = pathPoints
    .map(
      (pt) =>
        `<circle class="history-point" data-history-point="true" data-history-metric-id="${card.id}" data-history-key="${escapeAttribute(
          pt.key
        )}" data-history-range-start="${pt.rangeStart || ""}" data-history-range-end="${pt.rangeEnd || ""}" data-history-label="${escapeAttribute(
          pt.label
        )}" data-history-value="${escapeAttribute(card.formatter(pt.value))}" cx="${pt.x}" cy="${pt.y}" r="${pointRadius}" fill="${card.color}" />`
    )
    .join("");
  const axisMarkup = renderAxis(ticks, width, chartHeight);
  return `
    <svg viewBox="0 0 ${width} ${svgHeight}" class="history-line" role="img" aria-hidden="true" preserveAspectRatio="none" data-history-hover-root="true">
      <defs>
        <linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${card.color}" stop-opacity="0.35"></stop>
          <stop offset="100%" stop-color="${card.color}" stop-opacity="0"></stop>
        </linearGradient>
      </defs>
      <path d="${areaPath}" fill="url(#${gradientId})" stroke="none"></path>
      <polyline points="${polylinePoints}" fill="none" stroke="${card.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
      ${circles}
      ${axisMarkup}
    </svg>`;
}

function renderColumnChart(card, options = {}) {
  const width = options.width || 320;
  const chartHeight = options.height || 120;
  const axisHeight = options.axisHeight ?? 24;
  const svgHeight = chartHeight + axisHeight;
  const bars = getColumnChartData(card.points, width, chartHeight);
  if (!bars.length) {
    return `<div class="history-chart__empty">No data for this range.</div>`;
  }
  const ticks = buildAxisTicks(card.points, width);
  const axisMarkup = renderAxis(ticks, width, chartHeight);
  return `
    <svg viewBox="0 0 ${width} ${svgHeight}" class="history-column" role="img" aria-hidden="true" preserveAspectRatio="none" data-history-hover-root="true">
      ${bars
        .map(
          (bar) =>
            `<rect class="history-bar" data-history-point="true" data-history-metric-id="${card.id}" data-history-key="${escapeAttribute(
              bar.key
            )}" data-history-range-start="${bar.rangeStart || ""}" data-history-range-end="${bar.rangeEnd || ""}" data-history-label="${escapeAttribute(
              bar.label
            )}" data-history-value="${escapeAttribute(card.formatter(bar.value))}" x="${bar.x}" y="${bar.y}" width="${bar.width}" height="${bar.height}" rx="6" fill="${card.color}" opacity="0.82"></rect>`
        )
        .join("")}
      ${axisMarkup}
    </svg>`;
}

function renderAxis(ticks, width, chartHeight) {
  if (!ticks.length) return "";
  return `
    <g class="history-axis" aria-hidden="true">
      <line class="history-axis__line" x1="0" y1="${chartHeight}" x2="${width}" y2="${chartHeight}"></line>
      ${ticks
        .map(
          (tick) => `
        <line class="history-axis__tick" x1="${tick.x}" y1="${chartHeight}" x2="${tick.x}" y2="${chartHeight + 5}"></line>
        <text class="history-axis__label" x="${tick.x}" y="${chartHeight + 16}">${tick.label}</text>`
        )
        .join("")}
    </g>`;
}

function buildAxisTicks(points = [], width) {
  if (!points.length) return [];
  const total = points.length;
  const maxTicks = Math.min(total, 6);
  const step = Math.max(1, Math.round(total / maxTicks));
  const ticks = [];
  points.forEach((point, index) => {
    const isEdge = index === 0 || index === total - 1;
    if (index % step !== 0 && !isEdge) {
      return;
    }
    const x = total > 1 ? (index / (total - 1)) * width : width / 2;
    ticks.push({
      x,
      label: simplifyAxisLabel(point.label || point.key || ""),
    });
  });
  return ticks;
}

function simplifyAxisLabel(label) {
  if (!label) return "";
  const parts = label.split(" ");
  if (parts.length <= 2) return label;
  return `${parts[0]} ${parts[parts.length - 1]}`;
}

function escapeAttribute(value) {
  if (value == null) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

let historyTooltipEl = null;
let historyHoverTarget = null;

function attachHistoryHoverHandlers(root) {
  if (!root || root._historyHoverAttached) return;
  root.addEventListener("pointermove", handleHistoryPointerMove);
  root.addEventListener("pointerleave", hideHistoryTooltip);
  root.addEventListener("click", handleHistoryPointClick);
  root._historyHoverAttached = true;
}

function setHistoryHoverTarget(target) {
  if (historyHoverTarget === target) return;
  if (historyHoverTarget) {
    historyHoverTarget.classList.remove("is-hovered");
  }
  historyHoverTarget = target;
  if (target) {
    target.classList.add("is-hovered");
  }
}

function handleHistoryPointerMove(event) {
  const root = event.currentTarget;
  let target = event.target.closest("[data-history-point]");
  if (!target && root) {
    target = findNearestHistoryPoint(root, event.clientX, event.clientY);
  }
  if (!target) {
    hideHistoryTooltip();
    return;
  }
  setHistoryHoverTarget(target);
  showHistoryTooltip({
    label: target.getAttribute("data-history-label"),
    value: target.getAttribute("data-history-value"),
    anchorRect: target.getBoundingClientRect(),
    pointerX: event.clientX,
    pointerY: event.clientY,
  });
}

function getHistoryTooltipElement() {
  if (historyTooltipEl) return historyTooltipEl;
  const tooltip = document.createElement("div");
  tooltip.className = "history-tooltip";
  tooltip.hidden = true;
  document.body.appendChild(tooltip);
  historyTooltipEl = tooltip;
  return tooltip;
}

function showHistoryTooltip(dataset) {
  if (!dataset) return;
  const tooltip = getHistoryTooltipElement();
  const label = dataset.label || "";
  const value = dataset.value || "";
  tooltip.innerHTML = `<strong class="history-tooltip__value">${value}</strong><span class="history-tooltip__date">${label}</span>`;
  tooltip.hidden = false;
  const tooltipRect = tooltip.getBoundingClientRect();
  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  const offset = 14;
  let x;
  let y;
  if (dataset.anchorRect) {
    const anchor = dataset.anchorRect;
    x = anchor.left + anchor.width / 2 - tooltipRect.width / 2;
    y = anchor.top - tooltipRect.height - offset;
    if (y < 8) {
      y = anchor.bottom + offset;
    }
  } else if (typeof dataset.pointerX === "number" && typeof dataset.pointerY === "number") {
    x = dataset.pointerX + offset;
    y = dataset.pointerY + offset;
  } else {
    x = 0;
    y = 0;
  }
  const maxX = window.innerWidth - tooltipRect.width - 8;
  const maxY = window.innerHeight - tooltipRect.height - 8;
  tooltip.style.transform = `translate(${clamp(x, 8, maxX)}px, ${clamp(y, 8, maxY)}px)`;
}

function hideHistoryTooltip() {
  if (historyTooltipEl) {
    historyTooltipEl.hidden = true;
  }
  setHistoryHoverTarget(null);
}

function findNearestHistoryPoint(root, clientX, clientY) {
  const candidates = root.querySelectorAll("[data-history-point]");
  let nearest = null;
  let minDistance = Infinity;
  candidates.forEach((candidate) => {
    const rect = candidate.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const distance = Math.hypot(clientX - cx, clientY - cy);
    if (distance < minDistance) {
      minDistance = distance;
      nearest = candidate;
    }
  });
  if (minDistance <= 40) {
    return nearest;
  }
  return null;
}

async function handleHistoryPointClick(event) {
  const target = event.target.closest("[data-history-point]");
  if (!target) return;
  const metricId = target.getAttribute("data-history-metric-id");
  if (!metricId) return;
  const detailKey = HISTORY_METRIC_DETAIL_MAP[metricId];
  if (!detailKey) return;
  const cardConfig = (historyDom.currentCards || []).find((card) => card.id === metricId);
  const needsCumulativeRange = Boolean(cardConfig && cardConfig.accumulate);
  const monthLabel = target.getAttribute("data-history-label") || "";
  const titleSuffix = monthLabel || null;
  const appendContext = monthLabel ? `Month selected: ${monthLabel}.` : "";
  const overrideStart = target.getAttribute("data-history-range-start") || null;
  const overrideEnd = target.getAttribute("data-history-range-end") || null;
  const firstHistoryWindowStart =
    metricsState.historyMonthlyWindows && metricsState.historyMonthlyWindows.length
      ? metricsState.historyMonthlyWindows[0].start
      : null;
  const cumulativeStart = firstHistoryWindowStart || overrideStart;
  const detailOptions = {
    titleSuffix,
    appendContext,
    rangeStart: overrideStart || undefined,
    rangeEnd: overrideEnd || undefined,
    historyRangeMode: needsCumulativeRange ? "capEnd" : undefined,
  };
  if (historyDom.chartModal && !historyDom.chartModal.hidden) {
    closeHistoryChartModal();
  }
  const leadKey = metricsState.selectedLead;
  if (overrideStart && overrideEnd && leadKey) {
    try {
      const fetchStart = needsCumulativeRange ? cumulativeStart || overrideStart : overrideStart;
      const detailState = await getHistoryDetailState(leadKey, fetchStart, overrideEnd);
      if (detailState) {
        requestMetricDetail(detailKey, detailOptions, detailState);
        return;
      }
    } catch (err) {
      console.error("[recruiter-metrics] Could not load detail for month", err);
    }
  }
  requestMetricDetail(detailKey, detailOptions);
}

function computeHistoryTrend(latest, previous, goodWhenHigher, formatter) {
  if (latest == null || previous == null) return null;
  const diff = latest - previous;
  if (diff === 0) return { label: "steady", className: "is-neutral" };
  const arrow = diff > 0 ? "↑" : "↓";
  const formattedDiff = formatter(Math.abs(diff));
  const improvement = goodWhenHigher ? diff > 0 : diff < 0;
  return {
    label: `${arrow} ${formattedDiff}`,
    className: improvement ? "is-up" : "is-down",
  };
}

document.addEventListener("DOMContentLoaded", () => {
  setupMetricDetailModal();
  wireMetricDetailCards();
  setupTabs();
  initializeHistoryUI();
  setupHistoryChartModal();
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
