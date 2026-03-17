const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

const state = {
  currentOpportunity: null,
  currentUserEmail: "",
  filters: {
    position: "",
    salary: "",
    years_experience: "",
    industry: "",
    country: "",
  },
  candidates: [],
  applicantQuestions: {
    question_1: "Question 1",
    question_2: "Question 2",
    question_3: "Question 3",
  },
  selectedApplicantId: null,
};

const els = {
  userPill: document.getElementById("userPill"),
  chatSubtitle: document.getElementById("chatSubtitle"),
  chatStatus: document.getElementById("chatStatus"),
  chatMessages: document.getElementById("chatMessages"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  candidateSubtitle: document.getElementById("candidateSubtitle"),
  candidateCount: document.getElementById("candidateCount"),
  filtersGrid: document.getElementById("filtersGrid"),
  filtersStatus: document.getElementById("filtersStatus"),
  candidatesGrid: document.getElementById("candidatesGrid"),
  candidatesEmpty: document.getElementById("candidatesEmpty"),
  refreshApplicantsBtn: document.getElementById("refreshApplicantsBtn"),
  refreshApplicantsStatus: document.getElementById("refreshApplicantsStatus"),
  applicantDrawer: document.getElementById("applicantDrawer"),
  drawerClose: document.getElementById("drawerClose"),
  drawerTitle: document.getElementById("drawerTitle"),
  drawerBody: document.getElementById("drawerBody"),
  matchDrawerBtn: document.getElementById("matchDrawerBtn"),
  matchDrawer: document.getElementById("matchDrawer"),
  matchDrawerClose: document.getElementById("matchDrawerClose"),
  matchDrawerBody: document.getElementById("matchDrawerBody"),
  loadingGame: document.getElementById("loadingGame"),
  loadingGameBoard: document.getElementById("loadingGameBoard"),
  loadingGameTarget: document.getElementById("loadingGameTarget"),
  loadingGameHits: document.getElementById("loadingGameHits"),
  loadingGameStreak: document.getElementById("loadingGameStreak"),
};

const loadingGameState = {
  active: false,
  hits: 0,
  streak: 0,
  moveTimer: null,
};

function getStoredEmail() {
  return (
    localStorage.getItem("user_email") ||
    sessionStorage.getItem("user_email") ||
    ""
  )
    .toLowerCase()
    .trim();
}

function getOpportunityId() {
  const params = new URLSearchParams(window.location.search);
  const id = params.get("id");
  return id ? Number(id) : null;
}

async function fetchJSON(url, options = {}) {
  const res = await fetch(url, {
    credentials: "include",
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}


function setChatStatus(text) {
  if (els.chatStatus) els.chatStatus.textContent = text;
}

function setFiltersStatus(text) {
  if (els.filtersStatus) els.filtersStatus.textContent = text;
}

function setCandidateSubtitle(text) {
  if (els.candidateSubtitle) els.candidateSubtitle.textContent = text;
}

function setRefreshApplicantsStatus(text) {
  if (els.refreshApplicantsStatus) els.refreshApplicantsStatus.textContent = text || "";
}

function setUserPill(text) {
  if (els.userPill) els.userPill.textContent = text;
}

function escapeHtml(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => {
    const map = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return map[char] || char;
  });
}

function stripHtmlToText(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function appendMessage(role, text, options = {}) {
  if (!els.chatMessages) return null;
  const message = document.createElement("div");
  message.className = `chat-message ${role}`;
  if (options.typing) message.classList.add("typing");
  message.textContent = text;
  els.chatMessages.appendChild(message);
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
  return message;
}

function normalizeText(value) {
  return String(value || "").toLowerCase().trim();
}

function setRefreshApplicantsBusy(isBusy) {
  if (!els.refreshApplicantsBtn) return;
  els.refreshApplicantsBtn.disabled = Boolean(isBusy);
  els.refreshApplicantsBtn.textContent = isBusy ? "Refreshing..." : "Refresh CVs";
}

function updateLoadingGameStats() {
  if (els.loadingGameHits) els.loadingGameHits.textContent = `${loadingGameState.hits}`;
  if (els.loadingGameStreak) els.loadingGameStreak.textContent = `${loadingGameState.streak}`;
}

function moveLoadingGameTarget() {
  if (!els.loadingGameBoard || !els.loadingGameTarget) return;
  const rect = els.loadingGameBoard.getBoundingClientRect();
  const targetSize = els.loadingGameTarget.offsetWidth || 40;
  const maxX = Math.max(0, rect.width - targetSize);
  const maxY = Math.max(0, rect.height - targetSize);
  const nextX = Math.random() * maxX;
  const nextY = Math.random() * maxY;
  els.loadingGameTarget.style.left = `${nextX}px`;
  els.loadingGameTarget.style.top = `${nextY}px`;
}

function startLoadingGame(options = {}) {
  if (!els.loadingGame) return;
  const shouldReset = options.reset !== false;
  loadingGameState.active = true;
  if (shouldReset) {
    loadingGameState.hits = 0;
    loadingGameState.streak = 0;
  }
  updateLoadingGameStats();
  els.loadingGame.classList.add("is-visible");
  els.loadingGame.setAttribute("aria-hidden", "false");
  moveLoadingGameTarget();
  if (loadingGameState.moveTimer) clearInterval(loadingGameState.moveTimer);
  loadingGameState.moveTimer = setInterval(moveLoadingGameTarget, 900);
}

function stopLoadingGame() {
  if (!els.loadingGame) return;
  loadingGameState.active = false;
  if (loadingGameState.moveTimer) {
    clearInterval(loadingGameState.moveTimer);
    loadingGameState.moveTimer = null;
  }
  els.loadingGame.classList.remove("is-visible");
  els.loadingGame.setAttribute("aria-hidden", "true");
}

function initLoadingGame() {
  if (!els.loadingGameBoard || !els.loadingGameTarget) return;
  els.loadingGameTarget.addEventListener("click", (event) => {
    event.stopPropagation();
    if (!loadingGameState.active) return;
    loadingGameState.hits += 1;
    loadingGameState.streak += 1;
    updateLoadingGameStats();
    moveLoadingGameTarget();
  });
  els.loadingGameBoard.addEventListener("click", (event) => {
    if (!loadingGameState.active) return;
    if (event.target !== els.loadingGameBoard) return;
    loadingGameState.streak = 0;
    updateLoadingGameStats();
  });
  window.addEventListener("resize", () => {
    if (!loadingGameState.active) return;
    moveLoadingGameTarget();
  });
}

async function refreshSingleApplicantAI(applicantId) {
  if (!applicantId) return;
  const statusEl = document.getElementById("drawerRefreshStatus");
  const btn = document.getElementById("drawerRefreshBtn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Refreshing...";
  }
  if (statusEl) statusEl.textContent = "Refreshing CV...";

  try {
    const result = await fetchJSON(`${API_BASE}/applicants/${applicantId}/refresh_ai_fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filters: state.filters }),
    });
    const status = result.updated ? "Updated" : "No changes";
    if (statusEl) {
      statusEl.textContent = `${status} · score ${result.match_score ?? "—"}`;
    }
    await loadApplicants(getOpportunityId());
  } catch (err) {
    console.error("Single applicant refresh failed", err);
    if (statusEl) statusEl.textContent = "Refresh failed. Try again.";
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Refresh CV";
    }
  }
}

async function backfillApplicantsAI(opportunityId) {
  if (!opportunityId) {
    setRefreshApplicantsStatus("Missing opportunity id.");
    return;
  }

  setRefreshApplicantsBusy(true);
  setRefreshApplicantsStatus("Refreshing CVs...");

  try {
    const result = await fetchJSON(`${API_BASE}/applicants/backfill_ai_fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        opportunity_id: opportunityId,
        filters: state.filters,
      }),
    });
    setRefreshApplicantsStatus(
      `Updated ${result.updated || 0} · extracted ${result.extracted || 0} · scored ${result.scored || 0}`
    );
    await loadApplicants(opportunityId);
  } catch (err) {
    console.error("Applicant refresh failed", err);
    setRefreshApplicantsStatus("Refresh failed. Try again.");
  } finally {
    setRefreshApplicantsBusy(false);
  }
}

async function recalculateApplicants(opportunityId) {
  if (!opportunityId) return;
  try {
    await fetchJSON(`${API_BASE}/applicants/recalculate_scores`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        opportunity_id: opportunityId,
        filters: state.filters,
      }),
    });
  } catch (err) {
    console.warn("Failed to recalculate applicants", err);
  }
}

async function loadOpportunity(opportunityId) {
  setChatStatus("Loading");
  setFiltersStatus("Extracting");
  startLoadingGame({ reset: false });
  const opportunity = await fetchJSON(`${API_BASE}/opportunities/${opportunityId}`);
  state.currentOpportunity = opportunity;

  const oppName = opportunity.opp_position_name || "Opportunity";
  if (els.chatSubtitle) {
    els.chatSubtitle.textContent = `Filters for ${oppName}`;
  }

  try {
    const extracted = await extractFiltersFromOpportunity(opportunity);
    if (extracted) {
      appendMessage("assistant", "Listo, extraje los filtros del job description.");
    }
  } catch (err) {
    console.warn(
      "Filter extraction failed",
      {
        opportunityId: opportunity?.opportunity_id,
        position: opportunity?.opp_position_name,
        hasHrJD: Boolean(opportunity?.hr_job_description),
        hasCareerDesc: Boolean(opportunity?.career_description),
        hasCareerReqs: Boolean(opportunity?.career_requirements),
        rawError: err,
      }
    );
    appendMessage("assistant", "Esta opp no tiene job description.");
  }

  try {
    await recalculateApplicants(opportunityId);
    await loadApplicants(opportunityId);
  } catch (err) {
    console.error("Failed to load candidates", err);
    setCandidateSubtitle("Unable to load applicants.");
  } finally {
    stopLoadingGame();
  }

  try {
    await loadApplicantQuestions(opportunityId);
  } catch (err) {
    console.warn("Failed to load applicant questions", err);
  }

  if (state.candidates.length) {
    setCandidateSubtitle("Applicants sorted by match score.");
  }
  setChatStatus("Ready");
  setFiltersStatus("Ready");
}

async function loadApplicantQuestions(opportunityId) {
  const data = await fetchJSON(`${API_BASE}/linkedin_hub?opportunity_id=${opportunityId}`);
  state.applicantQuestions = {
    question_1: data?.question_1 || "Question 1",
    question_2: data?.question_2 || "Question 2",
    question_3: data?.question_3 || "Question 3",
  };
}

async function extractFiltersFromOpportunity(opportunity) {
  const rawJD =
    opportunity.hr_job_description ||
    opportunity.career_description ||
    opportunity.career_requirements ||
    "";

  const plainJD = stripHtmlToText(rawJD);
  if (!plainJD) {
    state.filters = {
      position: opportunity.opp_position_name || "",
      salary: "",
      years_experience: "",
      industry: "",
      country: opportunity.career_country || "",
    };
    renderFilters();
    appendMessage("assistant", "Esta opp no tiene job description.");
    return false;
  }

  const result = await fetchJSON(`${API_BASE}/ai/jd_to_talentum_filters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_description: rawJD, opportunity_id: opportunity?.opportunity_id }),
  });

  state.filters = {
    position: result.position || opportunity.opp_position_name || "",
    salary: result.salary || "",
    years_experience: result.years_experience || opportunity.years_experience || "",
    industry: result.industry || "",
    country: result.country || opportunity.career_country || "",
  };

  renderFilters();
  return true;
}

function renderFilters() {
  if (!els.filtersGrid) return;
  const entries = [
    { label: "Years", value: state.filters.years_experience },
  ];

  els.filtersGrid.innerHTML = "";
  entries.forEach((entry) => {
    const chip = document.createElement("div");
    chip.className = "filter-chip";
    chip.innerHTML = `<span>${entry.label}</span>${escapeHtml(entry.value || "—")}`;
    els.filtersGrid.appendChild(chip);
  });
}

function parseNumber(value) {
  if (!value) return null;
  const cleaned = String(value).toLowerCase().replace(/[ ,]/g, "");
  const match = cleaned.match(/(\d+(?:\.\d+)?)(k|m)?/);
  if (!match) return null;
  let num = Number(match[1]);
  if (Number.isNaN(num)) return null;
  if (match[2] === "k") num *= 1000;
  if (match[2] === "m") num *= 1000000;
  return num;
}

function parseSalaryRange(value) {
  if (!value) return null;
  const nums = String(value)
    .replace(/[^0-9kKmM\-\.]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .map(parseNumber)
    .filter((n) => Number.isFinite(n));
  if (!nums.length) return null;
  const min = Math.min(...nums);
  const max = Math.max(...nums);
  return { min, max };
}

const COUNTRY_DIRECTORY = [
  { name: "argentina", code: "AR", dial: "+54", aliases: ["arg", "ar"] },
  { name: "bolivia", code: "BO", dial: "+591", aliases: ["bol"] },
  { name: "brazil", code: "BR", dial: "+55", aliases: ["brasil", "bra", "br"] },
  { name: "chile", code: "CL", dial: "+56", aliases: ["chi", "cl"] },
  { name: "colombia", code: "CO", dial: "+57", aliases: ["col", "co"] },
  { name: "costa rica", code: "CR", dial: "+506", aliases: ["cr"] },
  { name: "dominican republic", code: "DO", dial: "+1", aliases: ["dominicana", "do"] },
  { name: "ecuador", code: "EC", dial: "+593", aliases: ["ec"] },
  { name: "el salvador", code: "SV", dial: "+503", aliases: ["sv"] },
  { name: "guatemala", code: "GT", dial: "+502", aliases: ["gt"] },
  { name: "honduras", code: "HN", dial: "+504", aliases: ["hn"] },
  { name: "mexico", code: "MX", dial: "+52", aliases: ["méxico", "mx"] },
  { name: "nicaragua", code: "NI", dial: "+505", aliases: ["ni"] },
  { name: "panama", code: "PA", dial: "+507", aliases: ["panamá", "pa"] },
  { name: "paraguay", code: "PY", dial: "+595", aliases: ["py"] },
  { name: "peru", code: "PE", dial: "+51", aliases: ["perú", "pe"] },
  { name: "puerto rico", code: "PR", dial: "+1", aliases: ["pr"] },
  { name: "spain", code: "ES", dial: "+34", aliases: ["españa", "espana", "es"] },
  { name: "uruguay", code: "UY", dial: "+598", aliases: ["uy"] },
  { name: "venezuela", code: "VE", dial: "+58", aliases: ["ve"] },
  { name: "united states", code: "US", dial: "+1", aliases: ["usa", "u.s.", "us", "united states of america", "estados unidos"] },
  { name: "canada", code: "CA", dial: "+1", aliases: ["can", "ca"] },
];

function countryCodeToFlag(code) {
  if (!code || code.length !== 2) return "";
  const upper = code.toUpperCase();
  const first = upper.charCodeAt(0) - 65 + 0x1f1e6;
  const second = upper.charCodeAt(1) - 65 + 0x1f1e6;
  return String.fromCodePoint(first, second);
}

function resolveCountryInfo(location) {
  const needle = normalizeText(location);
  if (!needle) return null;
  for (const entry of COUNTRY_DIRECTORY) {
    if (needle.includes(entry.name)) return entry;
    if ((entry.aliases || []).some((alias) => needle.includes(alias))) return entry;
  }
  return null;
}

const LATAM_COUNTRIES = new Set(
  COUNTRY_DIRECTORY
    .filter((entry) => entry.code && !["US", "CA", "ES"].includes(entry.code))
    .map((entry) => entry.name)
);

function isLatinAmericaFilter(value) {
  const needle = normalizeText(value);
  return needle.includes("latin america") || needle.includes("latam");
}

function isLatinAmericaLocation(value) {
  const needle = normalizeText(value);
  if (!needle) return false;
  return Array.from(LATAM_COUNTRIES).some((name) => needle.includes(name));
}

function formatPhoneNumber(phone, countryInfo) {
  if (!phone) return "—";
  const cleaned = String(phone).trim();
  if (!cleaned) return "—";
  if (cleaned.startsWith("+")) return cleaned;
  if (countryInfo?.dial) return `${countryInfo.dial} ${cleaned}`;
  return cleaned;
}

function formatBytes(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  if (num < 1024) return `${num} B`;
  const units = ["KB", "MB", "GB"];
  let size = num;
  let unitIndex = -1;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
}

function findYearsFromText(text) {
  const match = String(text || "").match(/(\d{1,2})\s*(?:\+?\s*)?(?:years|year|anos|años)/i);
  if (!match) return null;
  const num = Number(match[1]);
  return Number.isFinite(num) ? num : null;
}

function normalizeAscii(value) {
  return normalizeText(value)
    .replace(/[áàäâ]/g, "a")
    .replace(/[éèëê]/g, "e")
    .replace(/[íìïî]/g, "i")
    .replace(/[óòöô]/g, "o")
    .replace(/[úùüû]/g, "u")
    .replace(/ñ/g, "n");
}

const MONTH_MAP = {
  jan: 1,
  january: 1,
  ene: 1,
  enero: 1,
  feb: 2,
  febrero: 2,
  february: 2,
  mar: 3,
  marzo: 3,
  march: 3,
  apr: 4,
  abril: 4,
  april: 4,
  may: 5,
  mayo: 5,
  jun: 6,
  junio: 6,
  june: 6,
  jul: 7,
  julio: 7,
  july: 7,
  aug: 8,
  ago: 8,
  agosto: 8,
  august: 8,
  sep: 9,
  sept: 9,
  septiembre: 9,
  september: 9,
  oct: 10,
  octubre: 10,
  october: 10,
  nov: 11,
  noviembre: 11,
  november: 11,
  dec: 12,
  dic: 12,
  diciembre: 12,
  december: 12,
};

function resolveMonth(token) {
  const key = normalizeAscii(token || "").replace(/\./g, "");
  return MONTH_MAP[key] || null;
}

function parsePresentToken(token) {
  return ["present", "current", "actualidad", "hoy"].includes(normalizeAscii(token || ""));
}

function toMonthIndex(year, month) {
  return year * 12 + (month - 1);
}

function extractDateRangesFromText(text) {
  const clean = normalizeAscii(text);
  if (!clean) return [];

  const ranges = [];
  const now = new Date();
  const nowYear = now.getFullYear();
  const nowMonth = now.getMonth() + 1;

  const yearRange = /(\b\d{4}\b)\s*(?:-|–|—|to|a|hasta)\s*(\b\d{4}\b|present|current|actualidad|hoy)/g;
  let match = null;
  while ((match = yearRange.exec(clean))) {
    const startYear = Number(match[1]);
    const endToken = match[2];
    const endYear = parsePresentToken(endToken) ? nowYear : Number(endToken);
    const endMonth = parsePresentToken(endToken) ? nowMonth : 12;
    if (!Number.isFinite(startYear) || !Number.isFinite(endYear)) continue;
    ranges.push({ startYear, startMonth: 1, endYear, endMonth });
  }

  const monthYearRange = /(\b[a-z]{3,9}\b)\s+(\d{4})\s*(?:-|–|—|to|a|hasta)\s*(\b[a-z]{3,9}\b)?\s*(\d{4}|present|current|actualidad|hoy)/g;
  while ((match = monthYearRange.exec(clean))) {
    const startMonth = resolveMonth(match[1]);
    const startYear = Number(match[2]);
    const endMonthToken = match[3];
    const endToken = match[4];
    if (!startMonth || !Number.isFinite(startYear)) continue;
    const endIsPresent = parsePresentToken(endToken);
    const endYear = endIsPresent ? nowYear : Number(endToken);
    if (!Number.isFinite(endYear)) continue;
    const endMonth = endIsPresent
      ? nowMonth
      : (resolveMonth(endMonthToken) || 12);
    ranges.push({ startYear, startMonth, endYear, endMonth });
  }

  const numericRange = /(\b\d{1,2})[\/\-](\d{4})\s*(?:-|–|—|to|a|hasta)\s*(\b\d{1,2})[\/\-](\d{4}|present|current|actualidad|hoy)/g;
  while ((match = numericRange.exec(clean))) {
    const startMonth = Number(match[1]);
    const startYear = Number(match[2]);
    const endMonth = Number(match[3]);
    const endToken = match[4];
    const endIsPresent = parsePresentToken(endToken);
    const endYear = endIsPresent ? nowYear : Number(endToken);
    const finalEndMonth = endIsPresent ? nowMonth : endMonth;
    if (!Number.isFinite(startMonth) || !Number.isFinite(startYear) || !Number.isFinite(finalEndMonth) || !Number.isFinite(endYear)) {
      continue;
    }
    ranges.push({ startYear, startMonth, endYear, endMonth: finalEndMonth });
  }

  return ranges;
}

function mergeMonthRanges(ranges) {
  if (!ranges.length) return [];
  const normalized = ranges
    .map((range) => {
      const startIndex = toMonthIndex(range.startYear, range.startMonth);
      const endIndex = toMonthIndex(range.endYear, range.endMonth);
      if (!Number.isFinite(startIndex) || !Number.isFinite(endIndex)) return null;
      if (endIndex < startIndex) return null;
      return { startIndex, endIndex };
    })
    .filter(Boolean)
    .sort((a, b) => a.startIndex - b.startIndex);

  if (!normalized.length) return [];
  const merged = [normalized[0]];
  for (let i = 1; i < normalized.length; i += 1) {
    const last = merged[merged.length - 1];
    const current = normalized[i];
    if (current.startIndex <= last.endIndex + 1) {
      last.endIndex = Math.max(last.endIndex, current.endIndex);
    } else {
      merged.push({ ...current });
    }
  }
  return merged;
}

function extractExperienceFromText(text) {
  const ranges = extractDateRangesFromText(text);
  const merged = mergeMonthRanges(ranges);
  if (!merged.length) return null;
  const totalMonths = merged.reduce((sum, range) => sum + (range.endIndex - range.startIndex + 1), 0);
  const earliestIndex = merged[0].startIndex;
  const latestIndex = merged[merged.length - 1].endIndex;
  const earliestYear = Math.floor(earliestIndex / 12);
  const latestYear = Math.floor(latestIndex / 12);
  return {
    totalMonths,
    earliestYear,
    latestYear,
    rangesCount: merged.length,
  };
}

function formatExperienceDuration(valueYears) {
  if (!Number.isFinite(valueYears)) return "—";
  const months = Math.round(valueYears * 12);
  if (months < 12) return `${months} meses`;
  const rounded = Math.round(valueYears * 10) / 10;
  const label = `${rounded}`.replace(/\.0$/, "");
  return `${label} años`;
}

function extractEducationSnippet(text) {
  const raw = String(text || "");
  if (!raw) return "";
  const regex = /(licenciatura|ingenieria|ingeniería|maestria|maestría|mba|master|bachelor|degree|universidad|university|college|instituto|diplomatura|doctorado|phd)/i;
  const match = raw.match(regex);
  if (!match || match.index == null) return "";
  const start = Math.max(0, match.index - 60);
  const end = Math.min(raw.length, match.index + 120);
  return raw
    .slice(start, end)
    .replace(/\s+/g, " ")
    .trim();
}

function buildApplicantProfile(applicant) {
  const fullName = `${applicant.first_name || ""} ${applicant.last_name || ""}`.trim();
  const fallbackName = fullName || applicant.email || "Unnamed";
  const searchableText = [
    applicant.role_position,
    applicant.area,
    applicant.location,
    applicant.english_level,
    applicant.referral_source,
    applicant.question_1,
    applicant.question_2,
    applicant.question_3,
    applicant.extracted_pdf,
  ]
    .filter(Boolean)
    .join(" ");

  return {
    id: applicant.applicant_id,
    name: fallbackName,
    country: applicant.location || "",
    position: applicant.role_position || "",
    industry: applicant.area || "",
    years: null,
    salaryRange: null,
    searchableText,
    linkedin: applicant.linkedin_url || "",
    core: null,
  };
}

function matchesTextFilter(candidateValue, filterValue, fallbackText) {
  if (!filterValue) return true;
  const haystack = normalizeText(candidateValue || fallbackText);
  const needle = normalizeText(filterValue);
  return haystack.includes(needle);
}

function hasActiveFilters() {
  const activeKeys = ["years_experience"];
  return activeKeys.some((key) => String(state.filters?.[key] || "").trim());
}

function scoreTextMatch(candidateValue, filterValue, fallbackText) {
  if (!filterValue) return null;
  if (isLatinAmericaFilter(filterValue)) {
    return isLatinAmericaLocation(candidateValue || fallbackText) ? 2 : 0;
  }
  const haystack = normalizeText(candidateValue || fallbackText);
  const needle = normalizeText(filterValue);
  if (!haystack || !needle) return 0;
  if (haystack.includes(needle)) return 2;
  const tokens = needle.split(/[\s,\/\-]+/).filter(Boolean);
  if (!tokens.length) return 0;
  return tokens.some((token) => haystack.includes(token)) ? 1 : 0;
}

function resolveCandidateYears(profile) {
  if (profile.years != null) return profile.years;
  const inferred = extractExperienceFromText(profile.searchableText);
  if (inferred?.totalMonths) {
    return inferred.totalMonths / 12;
  }
  return findYearsFromText(profile.searchableText);
}

function scoreYearsMatch(profile) {
  if (!state.filters.years_experience) return null;
  const filterYears = parseNumber(state.filters.years_experience) || findYearsFromText(state.filters.years_experience);
  if (filterYears == null) return 0;
  const candidateYears = resolveCandidateYears(profile);
  if (candidateYears != null) {
    if (candidateYears >= filterYears) return 2;
    if (filterYears - candidateYears <= 2) return 1;
    return 0;
  }
  return matchesTextFilter("", state.filters.years_experience, profile.searchableText) ? 1 : 0;
}

function isRangeNear(range, target) {
  if (!range || !target) return false;
  if (range.max < target.min) {
    return (target.min - range.max) / Math.max(target.min, 1) <= 0.1;
  }
  if (range.min > target.max) {
    return (range.min - target.max) / Math.max(target.max, 1) <= 0.1;
  }
  return false;
}

function scoreSalaryMatch(profile) {
  if (!state.filters.salary) return null;
  const filterRange = parseSalaryRange(state.filters.salary);
  if (filterRange && profile.salaryRange) {
    const overlap = !(profile.salaryRange.max < filterRange.min || profile.salaryRange.min > filterRange.max);
    if (overlap) return 2;
    return isRangeNear(profile.salaryRange, filterRange) ? 1 : 0;
  }
  return matchesTextFilter("", state.filters.salary, profile.searchableText) ? 1 : 0;
}

function computeMatchScore(profile) {
  if (!hasActiveFilters()) return 10;

  const points = [];
  points.push(scoreYearsMatch(profile));

  const scored = points.filter((value) => value != null);
  const maxPoints = scored.length * 2;
  if (!maxPoints) return 10;
  const total = scored.reduce((sum, value) => sum + value, 0);
  const ratio = total / maxPoints;
  const scaled = Math.round(ratio * 9) + 1;
  return Math.min(10, Math.max(1, scaled));
}

function getMatchSummary(profile) {
  const parts = [];
  if (state.filters.years_experience) {
    const yearScore = scoreYearsMatch(profile);
    if (yearScore === 2) parts.push("years of experience match");
    else if (yearScore === 1) parts.push("years of experience are close");
    else parts.push("years of experience not found");
  }
  return parts.filter(Boolean);
}

function scoreToPercent(score) {
  if (!Number.isFinite(score)) return null;
  const bounded = Math.max(0, Math.min(10, score));
  return Math.round((bounded / 10) * 100);
}

function normalizePercent(value, fallback = null) {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function parseReasonsPayload(reasonsRaw) {
  const raw = String(reasonsRaw || "").trim();
  if (!raw) return null;
  if (!raw.startsWith("{") && !raw.startsWith("[")) {
    return { summary: raw, breakdown: null, overallPercent: null };
  }
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { summary: raw, breakdown: null, overallPercent: null };
    }
    const summary = typeof parsed.summary === "string" ? parsed.summary.trim() : "";
    const overallPercent = normalizePercent(parsed.overall_percent, null);
    const breakdown = Array.isArray(parsed.breakdown)
      ? parsed.breakdown
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const category = typeof item.category === "string" ? item.category.trim() : "";
          const detail = typeof item.detail === "string" ? item.detail.trim() : "";
          const percent = normalizePercent(item.percent, null);
          if (!category) return null;
          return { category, detail, percent };
        })
        .filter(Boolean)
      : null;
    return { summary, breakdown, overallPercent };
  } catch (err) {
    return { summary: raw, breakdown: null, overallPercent: null };
  }
}

function mapScoreToPercent(scoreValue) {
  if (scoreValue === 2) return 100;
  if (scoreValue === 1) return 60;
  if (scoreValue === 0) return 0;
  return null;
}

function buildFilterBreakdown(label, filterValue, scoreValue, details) {
  if (!filterValue) {
    return {
      category: label,
      percent: 0,
      detail: "Filtro no definido.",
    };
  }
  if (scoreValue == null) {
    return {
      category: label,
      percent: 0,
      detail: details.missing,
    };
  }
  if (scoreValue === 2) {
    return {
      category: label,
      percent: 100,
      detail: details.match,
    };
  }
  if (scoreValue === 1) {
    return {
      category: label,
      percent: 60,
      detail: details.close,
    };
  }
  return {
    category: label,
    percent: 0,
    detail: details.miss,
  };
}

function buildJdExplanation(profile, percent, includePercent = true) {
  const roleWanted = state.filters.position || "";
  const roleHave = profile.position || "";
  const industryWanted = state.filters.industry || "";
  const industryHave = profile.industry || "";
  const yearsWanted = state.filters.years_experience || "";
  const yearsHave = resolveCandidateYears(profile);
  const percentLabel = `${percent || 0}%`;
  const experienceInfo = extractExperienceFromText(profile.searchableText);
  const educationSnippet = extractEducationSnippet(profile.searchableText);

  const leadSentence = includePercent
    ? `Resumen del CV para esta comparación (${percentLabel}).`
    : "Resumen del CV para esta comparación.";

  const roleSentence = roleHave
    ? `La persona ha trabajado como ${roleHave} y esa experiencia es el eje principal del perfil.`
    : "El rol específico no está declarado de forma explícita, pero el CV sugiere experiencia relevante en funciones similares.";

  const roleFitSentence = roleWanted
    ? `La posición buscada es ${roleWanted}, por lo que se revisan tareas y responsabilidades del CV que se alineen con ese tipo de rol.`
    : "No hay una posición objetivo definida en la JD, así que se toma la experiencia general del perfil como referencia.";

  const industrySentence = industryHave
    ? `En industria, se observa experiencia en ${industryHave}, lo cual aporta contexto sobre los sectores en los que se ha desempeñado.`
    : "No se identifica una industria concreta en el CV, por lo que la evaluación se apoya más en el tipo de rol que en el sector.";

  const industryFitSentence = industryWanted
    ? `La industria solicitada es ${industryWanted}, por lo que se considera si la experiencia previa está en ese mismo sector o en uno compatible.`
    : "La JD no fija una industria específica, así que la compatibilidad se valora principalmente por responsabilidades y resultados.";

  const yearsSentence = yearsWanted
    ? (yearsHave != null
      ? `En años de experiencia, el perfil indica ${formatExperienceDuration(yearsHave)} frente a ${yearsWanted} solicitados, lo que ayuda a dimensionar la seniority esperada.`
      : `La JD pide ${yearsWanted}, pero el CV no detalla años concretos; se toma como referencia la trayectoria descrita.`)
    : (yearsHave != null
      ? `El CV sugiere alrededor de ${formatExperienceDuration(yearsHave)} de experiencia, lo que permite estimar el nivel de seniority.`
      : "No hay una cifra clara de años de experiencia, por lo que se resume la trayectoria cualitativamente.");

  const experienceSentence = experienceInfo
    ? `Al revisar las fechas de las posiciones laborales, se estiman ${formatExperienceDuration(experienceInfo.totalMonths / 12)} de experiencia acumulada, con tramos que van aproximadamente entre ${experienceInfo.earliestYear} y ${experienceInfo.latestYear}.`
    : (yearsHave != null
      ? `En experiencia profesional, el perfil sugiere aproximadamente ${formatExperienceDuration(yearsHave)} de trayectoria.`
      : "En experiencia profesional, el CV describe roles y responsabilidades, pero no se detectaron rangos de fechas claros para estimar la duración total.");

  const studiesSentence = educationSnippet
    ? `En estudios, se identifica formación académica como: "${educationSnippet}".`
    : "En estudios, no se encontró una referencia académica clara en el texto disponible.";

  const closingSentence = "Este resumen prioriza lo que el CV declara explícitamente y lo que se puede inferir de su trayectoria, para explicar por qué el perfil se aproxima a la posición.";

  return `${leadSentence} ${roleSentence} ${roleFitSentence} ${industrySentence} ${industryFitSentence} ${experienceSentence} ${yearsSentence} ${studiesSentence} ${closingSentence}`.trim();
}

function buildYearsBreakdown(profile) {
  const filterValue = state.filters.years_experience;
  if (!filterValue) {
    return {
      category: "Años de experiencia (filtro)",
      percent: 0,
      detail: "Filtro no definido.",
    };
  }

  const filterYears = parseNumber(filterValue) || findYearsFromText(filterValue);
  if (filterYears == null) {
    return {
      category: "Años de experiencia (filtro)",
      percent: 0,
      detail: "No se pudo interpretar el requisito de años.",
    };
  }

  const candidateYears = resolveCandidateYears(profile);
  if (candidateYears == null) {
    return {
      category: "Años de experiencia (filtro)",
      percent: 0,
      detail: "No se encontró experiencia suficiente para evaluar.",
    };
  }

  const ratio = filterYears > 0 ? Math.min(candidateYears / filterYears, 1) : 0;
  const percent = normalizePercent(Math.round(ratio * 100), 0);
  if (candidateYears >= filterYears) {
    return {
      category: "Años de experiencia (filtro)",
      percent,
      detail: "Cumple con los años de experiencia solicitados.",
    };
  }
  return {
    category: "Años de experiencia (filtro)",
    percent,
    detail: `Tiene ${formatExperienceDuration(candidateYears)} frente a ${filterYears} años solicitados, cubre aproximadamente el ${percent}% del requisito.`,
  };
}

function buildFallbackBreakdown(profile, score) {
  const breakdown = [];
  const overallPercent = scoreToPercent(score);
  breakdown.push({
    category: "Similitud con la JD",
    percent: normalizePercent(overallPercent, 0),
    detail: buildJdExplanation(profile, overallPercent),
  });

  breakdown.push(buildYearsBreakdown(profile));

  return breakdown;
}

function buildDefaultSummary(profile, percent) {
  return buildJdExplanation(profile, percent, true);
}

function buildMatchModel(profile, score, reasonsRaw) {
  const parsed = parseReasonsPayload(reasonsRaw);
  const percentFallback = scoreToPercent(score) ?? 0;
  const overallPercent = normalizePercent(parsed?.overallPercent, percentFallback);
  const summary = parsed?.summary || buildDefaultSummary(profile, overallPercent);
  const breakdownSource = parsed?.breakdown?.length
    ? parsed.breakdown
    : buildFallbackBreakdown(profile, score);
  const breakdown = breakdownSource.map((item) => ({
    ...item,
    percent: normalizePercent(item.percent, 0),
  }));
  return {
    percent: overallPercent,
    summary,
    breakdown,
  };
}

function getScoreTone(percent) {
  if (percent >= 70) return "score-high";
  if (percent >= 40) return "score-mid";
  return "score-low";
}

function renderCandidates() {
  const scored = state.candidates
    .map((candidate) => {
      const fallback = computeMatchScore(candidate.profile);
      const score = Number.isFinite(candidate.score) ? candidate.score : fallback;
      return { ...candidate, score };
    })
    .sort((a, b) => b.score - a.score);

  els.candidatesGrid.innerHTML = "";
  els.candidatesEmpty.style.display = scored.length ? "none" : "block";
  els.candidatesEmpty.textContent = scored.length
    ? ""
    : "No applicants yet.";
  els.candidateCount.textContent = `${scored.length} applicants`;

  scored.forEach((candidate) => {
    const card = document.createElement("div");
    card.className = "candidate-card";
    card.dataset.applicantId = candidate.profile.id;
    const tags = [candidate.profile.position, candidate.profile.industry, candidate.profile.country]
      .filter(Boolean)
      .slice(0, 3)
      .map((tag) => `<span class="candidate-tag">${escapeHtml(tag)}</span>`)
      .join("");
    const profileLink = candidate.profile.linkedin
      ? `<a class="candidate-link" href="${escapeHtml(candidate.profile.linkedin)}" target="_blank" rel="noopener">Open LinkedIn →</a>`
      : `<span class="candidate-link muted">No LinkedIn</span>`;

    const scorePercent = scoreToPercent(candidate.score) ?? 0;
    const scoreTone = getScoreTone(scorePercent);
    card.innerHTML = `
      <h4>${escapeHtml(candidate.profile.name)}</h4>
      <div class="candidate-score ${scoreTone}">Match ${scorePercent}%</div>
      <p class="candidate-meta">${escapeHtml(candidate.profile.position || "Role unknown")}</p>
      <p class="candidate-meta">${escapeHtml(candidate.profile.country || "Location unknown")}</p>
      <div class="candidate-tags">${tags}</div>
      ${profileLink}
    `;
    els.candidatesGrid.appendChild(card);
  });
}

async function loadApplicants(opportunityId) {
  setCandidateSubtitle("Fetching applicants…");
  startLoadingGame();
  try {
    const applicants = await fetchJSON(`${API_BASE}/applicants?opportunity_id=${opportunityId}`);
    const list = Array.isArray(applicants) ? applicants : [];

    if (!list.length) {
      state.candidates = [];
      renderCandidates();
      setCandidateSubtitle("No applicants in pipeline.");
      return;
    }

    setCandidateSubtitle("Scoring applicants…");
    state.candidates = list.map((applicant) => ({
      pipeline: applicant,
      detail: applicant,
      profile: buildApplicantProfile(applicant),
      score: Number.isFinite(applicant.match_score) ? applicant.match_score : null,
      reasons: applicant.reasons || "",
    }));
    renderCandidates();
  } finally {
    stopLoadingGame();
  }
}

function renderApplicantDrawer(entry) {
  if (!entry || !els.drawerBody || !els.drawerTitle) return;
  const applicant = entry.pipeline;
  const profile = entry.profile;
  const name = `${applicant.first_name || ""} ${applicant.last_name || ""}`.trim() || applicant.email || "Applicant";
  els.drawerTitle.textContent = name;

  const questions = state.applicantQuestions || {};
  const countryInfo = resolveCountryInfo(applicant.location);
  const locationLabel = countryInfo?.code
    ? `${countryCodeToFlag(countryInfo.code)} ${applicant.location || "—"}`
    : (applicant.location || "—");
  const phoneLabel = formatPhoneNumber(applicant.phone, countryInfo);
  const linkedinUrl = applicant.linkedin_url || "";
  const linkedinLink = linkedinUrl
    ? `<a class="drawer-link" href="${escapeHtml(linkedinUrl)}" target="_blank" rel="noopener">Open LinkedIn →</a>`
    : "<span class=\"drawer-value\">—</span>";
  const cvName = escapeHtml(applicant.cv_file_name || "CV file");
  const cvLink = applicant.cv_s3_key
    ? `<a class="drawer-link" id="cvDownloadLink" href="#" target="_blank" rel="noopener">Download ${cvName}</a>`
    : "<span class=\"drawer-value\">—</span>";
  const match = buildMatchModel(
    profile,
    entry.score ?? computeMatchScore(profile),
    entry.reasons || applicant.reasons || ""
  );
  const breakdownHtml = match.breakdown
    .map((item) => {
      const percentValue = normalizePercent(item.percent, 0);
      const tone = getScoreTone(percentValue);
      return `
        <div class="score-row ${tone}">
          <div class="score-row-head">
            <span class="score-category">${escapeHtml(item.category)}</span>
            <span class="score-percent">${escapeHtml(percentValue)}%</span>
          </div>
          <p class="score-detail">${escapeHtml(item.detail || "Sin detalle adicional.")}</p>
        </div>
      `;
    })
    .join("");

  els.drawerBody.innerHTML = `
    <div class="drawer-section">
      <h4>Overview</h4>
      <div class="drawer-item">
        <span class="drawer-label">Email</span>
        <span class="drawer-value copy-value" data-copy="${escapeHtml(applicant.email || "")}">
          <button class="copy-btn" type="button" aria-label="Copy email" title="Copy to clipboard" data-copy="${escapeHtml(applicant.email || "")}">📋</button>
          ${escapeHtml(applicant.email || "—")}
        </span>
      </div>
      <div class="drawer-item">
        <span class="drawer-label">Phone</span>
        <span class="drawer-value copy-value" data-copy="${escapeHtml(phoneLabel)}">
          <button class="copy-btn" type="button" aria-label="Copy phone" title="Copy to clipboard" data-copy="${escapeHtml(phoneLabel)}">📋</button>
          ${escapeHtml(phoneLabel)}
        </span>
      </div>
      <div class="drawer-item"><span class="drawer-label">Location</span><span class="drawer-value">${escapeHtml(locationLabel)}</span></div>
      <div class="drawer-item">
        <span class="drawer-label">LinkedIn</span>
        <span class="drawer-value copy-value" data-copy="${escapeHtml(linkedinUrl)}">
          <button class="copy-btn" type="button" aria-label="Copy LinkedIn" title="Copy to clipboard" data-copy="${escapeHtml(linkedinUrl)}">📋</button>
          ${linkedinLink}
        </span>
      </div>
    </div>
    <div class="drawer-section">
      <h4>Role</h4>
      <div class="drawer-item"><span class="drawer-label">Position</span><span class="drawer-value">${escapeHtml(applicant.role_position || "—")}</span></div>
      <div class="drawer-item"><span class="drawer-label">Area</span><span class="drawer-value">${escapeHtml(applicant.area || "—")}</span></div>
      <div class="drawer-item"><span class="drawer-label">English</span><span class="drawer-value">${escapeHtml(applicant.english_level || "—")}</span></div>
      <div class="drawer-item"><span class="drawer-label">Referral</span><span class="drawer-value">${escapeHtml(applicant.referral_source || "—")}</span></div>
    </div>
    <div class="drawer-section">
      <h4>Files</h4>
      <div class="drawer-item"><span class="drawer-label">CV</span>${cvLink}</div>
      <div class="drawer-item"><span class="drawer-label">Size</span><span class="drawer-value">${formatBytes(applicant.cv_size_bytes)}</span></div>
      <div class="drawer-item drawer-actions">
        <button class="drawer-refresh-btn" id="drawerRefreshBtn" type="button" data-applicant-id="${applicant.applicant_id}">
          Refresh CV
        </button>
        <span class="drawer-refresh-status" id="drawerRefreshStatus"></span>
      </div>
    </div>
    <div class="drawer-section">
      <h4>Screening</h4>
      <div class="screening-item">
        <p class="screening-question">${escapeHtml(questions.question_1 || "Question 1")}</p>
        <p class="screening-answer">${escapeHtml(applicant.question_1 || "—")}</p>
      </div>
      <div class="screening-item">
        <p class="screening-question">${escapeHtml(questions.question_2 || "Question 2")}</p>
        <p class="screening-answer">${escapeHtml(applicant.question_2 || "—")}</p>
      </div>
      <div class="screening-item">
        <p class="screening-question">${escapeHtml(questions.question_3 || "Question 3")}</p>
        <p class="screening-answer">${escapeHtml(applicant.question_3 || "—")}</p>
      </div>
    </div>
  `;

  if (applicant.cv_s3_key) {
    loadApplicantCvLink(applicant.applicant_id);
  }

  if (els.matchDrawerBody) {
    const matchTone = getScoreTone(match.percent);
    els.matchDrawerBody.innerHTML = `
      <div class="drawer-section">
        <div class="score-header ${matchTone}">
          <div>
            <div class="score-value">${escapeHtml(match.percent)}%</div>
            <div class="score-label">Match general</div>
          </div>
        </div>
        <p class="score-summary">${escapeHtml(match.summary)}</p>
        <div class="score-breakdown">
          ${breakdownHtml}
        </div>
      </div>
    `;
  }
}

async function loadApplicantCvLink(applicantId) {
  const link = document.getElementById("cvDownloadLink");
  if (!link) return;
  link.textContent = "Loading CV…";
  try {
    const data = await fetchJSON(`${API_BASE}/applicants/${applicantId}/cv`);
    link.href = data.url;
    link.textContent = `Download ${data.file_name || "CV"}`;
    if (data.file_name) link.setAttribute("download", data.file_name);
  } catch (err) {
    console.warn("Failed to load CV link", err);
    link.textContent = "CV unavailable";
    link.removeAttribute("href");
  }
}

function openApplicantDrawer(applicant) {
  state.selectedApplicantId = applicant?.pipeline?.applicant_id || null;
  renderApplicantDrawer(applicant);
  if (els.applicantDrawer) els.applicantDrawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("drawer-open");
  closeMatchDrawer();
}

function closeApplicantDrawer() {
  state.selectedApplicantId = null;
  if (els.applicantDrawer) els.applicantDrawer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("drawer-open");
  closeMatchDrawer();
}

function openMatchDrawer() {
  if (!els.matchDrawer || !els.applicantDrawer) return;
  els.matchDrawer.setAttribute("aria-hidden", "false");
  els.applicantDrawer.classList.add("match-drawer-open");
}

function closeMatchDrawer() {
  if (!els.matchDrawer || !els.applicantDrawer) return;
  els.matchDrawer.setAttribute("aria-hidden", "true");
  els.applicantDrawer.classList.remove("match-drawer-open");
}

async function handleChatSubmit(event) {
  event.preventDefault();
  const message = els.chatInput.value.trim();
  if (!message) return;

  appendMessage("user", message);
  els.chatInput.value = "";
  setChatStatus("Thinking");
  setFiltersStatus("Updating");

  const typing = appendMessage("assistant", "Actualizando filtros…", { typing: true });

  try {
    const resp = await fetchJSON(`${API_BASE}/ai/talentum_chat_update`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        current_filters: state.filters,
        opportunity_id: state.currentOpportunity?.opportunity_id,
      }),
    });
    if (typing) typing.remove();
    if (resp.updated_filters) {
      state.filters = { ...state.filters, ...resp.updated_filters };
      renderFilters();
      await recalculateApplicants(getOpportunityId());
      await loadApplicants(getOpportunityId());
    }
    appendMessage("assistant", resp.response || "Filtros actualizados.");
  } catch (err) {
    console.warn("Chat update failed", err);
    if (typing) typing.remove();
    appendMessage("assistant", "No pude actualizar los filtros, sigo con los actuales.");
  } finally {
    setChatStatus("Ready");
    setFiltersStatus("Ready");
    setCandidateSubtitle("Applicants sorted by match score.");
  }
}

async function init() {
  state.currentUserEmail = getStoredEmail();
  setUserPill(state.currentUserEmail ? state.currentUserEmail : "Guest");
  setChatStatus("Idle");
  setFiltersStatus("Idle");
  initLoadingGame();

  const opportunityId = getOpportunityId();
  if (!opportunityId) {
    setChatStatus("Missing ID");
    setCandidateSubtitle("Missing opportunity id.");
    appendMessage("assistant", "Falta el id de opportunity en el link.");
    return;
  }

  await loadOpportunity(opportunityId);

  if (els.chatForm) {
    els.chatForm.addEventListener("submit", handleChatSubmit);
  }

  if (els.refreshApplicantsBtn) {
    els.refreshApplicantsBtn.addEventListener("click", () => backfillApplicantsAI(opportunityId));
  }

  if (els.candidatesGrid) {
    els.candidatesGrid.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      const card = event.target.closest(".candidate-card");
      if (!card) return;
      const applicantId = Number(card.dataset.applicantId);
      const selected = state.candidates.find((entry) => entry.profile.id === applicantId);
      if (selected?.pipeline) {
        const fallback = computeMatchScore(selected.profile);
        const score = Number.isFinite(selected.score) ? selected.score : fallback;
        openApplicantDrawer({ ...selected, score });
      }
    });
  }

  if (els.drawerClose) {
    els.drawerClose.addEventListener("click", closeApplicantDrawer);
  }

  if (els.matchDrawerBtn) {
    els.matchDrawerBtn.addEventListener("click", () => openMatchDrawer());
  }

  if (els.matchDrawerClose) {
    els.matchDrawerClose.addEventListener("click", () => closeMatchDrawer());
  }

  if (els.drawerBody) {
    els.drawerBody.addEventListener("click", async (event) => {
      const button = event.target.closest(".copy-btn");
      if (!button) return;
      const value = button.dataset.copy || "";
      if (!value || value === "—") return;
      try {
        await navigator.clipboard.writeText(value);
        const original = button.textContent;
        button.textContent = "✅";
        setTimeout(() => {
          button.textContent = original;
        }, 1200);
      } catch (err) {
        console.warn("Copy failed", err);
      }
    });
    els.drawerBody.addEventListener("click", (event) => {
      const btn = event.target.closest(".drawer-refresh-btn");
      if (!btn) return;
      const applicantId = Number(btn.dataset.applicantId);
      refreshSingleApplicantAI(applicantId);
    });
  }
}

init().catch((err) => {
  console.error("Talentum detail init failed", err);
  setChatStatus("Error");
  setCandidateSubtitle("Unable to load data.");
});
