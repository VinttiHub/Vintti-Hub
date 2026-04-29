const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
const FLAG_STORAGE_KEYS = {
  reviewed: "talentum_reviewed_applicants",
  contacted: "talentum_contacted_applicants",
  rejected: "talentum_rejected_applicants",
};
const FLAG_LABELS = {
  reviewed: { on: "Reviewed", off: "Not reviewed" },
  contacted: { on: "Contacted", off: "Not contacted" },
  rejected: { on: "Rejected", off: "Not rejected" },
};
const FLAG_ORDER = ["reviewed", "contacted", "rejected"];

const state = {
  currentOpportunity: null,
  currentUserEmail: "",
  ui: {
    chatExpanded: false,
    genderFilter: "all",
    flagFilters: {
      reviewed: "all",
      contacted: "all",
      rejected: "all",
    },
  },
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
  paginationIndex: 0,
};

const els = {
  userPill: document.getElementById("userPill"),
  chatSubtitle: document.getElementById("chatSubtitle"),
  chatStatus: document.getElementById("chatStatus"),
  chatMessages: document.getElementById("chatMessages"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  chatPanel: document.getElementById("chatPanel"),
  chatFab: document.getElementById("chatFab"),
  candidateSubtitle: document.getElementById("candidateSubtitle"),
  candidateCount: document.getElementById("candidateCount"),
  filtersGrid: document.getElementById("filtersGrid"),
  filtersStatus: document.getElementById("filtersStatus"),
  candidatesGrid: document.getElementById("candidatesGrid"),
  candidatesEmpty: document.getElementById("candidatesEmpty"),
  candidateGenderFilter: document.getElementById("candidateGenderFilter"),
  flagFilterSections: document.querySelectorAll("[data-flag-filter-section]"),
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
  prevCandidateBtn: document.getElementById("prevCandidateBtn"),
  nextCandidateBtn: document.getElementById("nextCandidateBtn"),
  paginatorCounter: document.getElementById("paginatorCounter"),
  paginator: document.getElementById("paginator"),
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

function readFlagMap(flag) {
  const key = FLAG_STORAGE_KEYS[flag];
  if (!key) return {};
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) {
    console.warn(`Failed to read ${flag} applicants from storage`, err);
    return {};
  }
}

function writeFlagMap(flag, map) {
  const key = FLAG_STORAGE_KEYS[flag];
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(map || {}));
  } catch (err) {
    console.warn(`Failed to persist ${flag} applicants`, err);
  }
}

function isApplicantFlagged(flag, applicantId) {
  if (!Number.isFinite(Number(applicantId))) return false;
  const map = readFlagMap(flag);
  return Boolean(map[String(applicantId)]);
}

function setApplicantFlag(flag, applicantId, value) {
  const normalizedId = Number(applicantId);
  if (!Number.isFinite(normalizedId)) return;
  const map = readFlagMap(flag);
  map[String(normalizedId)] = Boolean(value);
  writeFlagMap(flag, map);
}

function getApplicantById(applicantId) {
  const normalizedId = Number(applicantId);
  if (!Number.isFinite(normalizedId)) return null;
  return state.candidates.find((entry) => Number(entry?.pipeline?.applicant_id) === normalizedId) || null;
}

function buildPipelineCandidatePayload(applicant) {
  const firstName = applicant.first_name || "";
  const lastName = applicant.last_name || "";
  const name = `${firstName} ${lastName}`.trim() || applicant.email || "Applicant";
  return {
    name,
    email: applicant.email || "",
    phone: applicant.phone || "",
    linkedin: applicant.linkedin_url || "",
    country: applicant.location || "",
    english_level: applicant.english_level || "",
    stage: "Contactado",
    created_by: state.currentUserEmail || getStoredEmail() || undefined,
    candidate_source: "Talentum",
    candidate_origin: "Talentum applicant",
  };
}

async function createPipelineCandidateFromApplicant(opportunityId, applicant) {
  const payload = buildPipelineCandidatePayload(applicant);
  const res = await fetch(`${API_BASE}/opportunities/${opportunityId}/candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.error || `Failed to create pipeline candidate (${res.status})`);
  }
  return data?.candidate_id;
}

async function createOrFindPipelineCandidate(opportunityId, applicant) {
  if (applicant.candidate_id) return applicant.candidate_id;

  const payload = buildPipelineCandidatePayload(applicant);
  const res = await fetch(`${API_BASE}/candidates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));

  if (res.status === 409) {
    const existingId = data?.candidate?.candidate_id;
    if (!existingId) throw new Error(data?.error || "Duplicate candidate without candidate ID");
    return existingId;
  }

  if (!res.ok) {
    const error = String(data?.error || "");
    if (res.status === 400 && /missing required fields/i.test(error)) {
      return createPipelineCandidateFromApplicant(opportunityId, applicant);
    }
    throw new Error(error || `Failed to create candidate (${res.status})`);
  }

  return data?.candidate_id;
}

async function setPipelineCandidateStage(opportunityId, candidateId, stage) {
  await fetchJSON(`${API_BASE}/opportunities/${opportunityId}/candidates/${candidateId}/stage`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ stage_pipeline: stage }),
  });
}

async function linkCandidateToContactedStage(opportunityId, candidateId) {
  const res = await fetch(`${API_BASE}/opportunities/${opportunityId}/candidates/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      candidate_id: candidateId,
      stage: "Contactado",
      created_by: state.currentUserEmail || getStoredEmail() || undefined,
    }),
  });

  if (res.status === 409) {
    await setPipelineCandidateStage(opportunityId, candidateId, "Contactado");
    return;
  }

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
}

async function syncApplicantToContactedPipeline(applicantId) {
  const opportunityId = getOpportunityId();
  const entry = getApplicantById(applicantId);
  const applicant = entry?.pipeline;
  if (!opportunityId || !applicant) return;

  try {
    setCandidateSubtitle("Adding applicant to contacted pipeline...");
    const candidateId = await createOrFindPipelineCandidate(opportunityId, applicant);
    if (!candidateId) throw new Error("Candidate ID was not returned");
    applicant.candidate_id = candidateId;
    await linkCandidateToContactedStage(opportunityId, candidateId);
    setCandidateSubtitle("Applicant added to contacted pipeline.");
  } catch (err) {
    console.error("Failed to sync applicant to pipeline", err);
    setCandidateSubtitle("Could not add applicant to pipeline.");
  }
}

function handleFlagCheckboxChange(checkbox) {
  const flag = checkbox.dataset.flag;
  if (!flag || !FLAG_STORAGE_KEYS[flag]) return;

  const applicantId = Number(checkbox.dataset.applicantId);
  setApplicantFlag(flag, applicantId, checkbox.checked);

  if (flag === "contacted" && checkbox.checked) {
    syncApplicantToContactedPipeline(applicantId);
  }
}

function buildFlagTogglesHtml(applicantId, options = {}) {
  const layout = options.layout || "stacked";
  const togglesHtml = FLAG_ORDER.map((flag) => {
    const active = isApplicantFlagged(flag, applicantId);
    const labels = FLAG_LABELS[flag];
    const label = active ? labels.on : labels.off;
    return `
      <label class="candidate-flag-toggle candidate-flag-toggle--${flag} ${active ? "is-active" : ""}" data-stop="true">
        <input
          class="candidate-flag-checkbox"
          type="checkbox"
          data-applicant-id="${applicantId}"
          data-flag="${flag}"
          ${active ? "checked" : ""}
        />
        <span>${label}</span>
      </label>
    `;
  }).join("");
  return `<div class="candidate-flag-toggles candidate-flag-toggles--${layout}">${togglesHtml}</div>`;
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

function setChatExpanded(isExpanded) {
  state.ui.chatExpanded = Boolean(isExpanded);
  document.body.classList.toggle("chat-expanded", state.ui.chatExpanded);
  if (els.chatPanel) {
    els.chatPanel.setAttribute("aria-hidden", state.ui.chatExpanded ? "false" : "true");
  }
  if (els.chatFab) {
    els.chatFab.textContent = state.ui.chatExpanded ? "Ver candidatos" : "Abrir chat";
    els.chatFab.setAttribute("aria-label", state.ui.chatExpanded ? "Ver candidatos" : "Abrir chat");
  }
  if (state.ui.chatExpanded && els.chatInput) {
    requestAnimationFrame(() => els.chatInput.focus());
  }
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
  els.refreshApplicantsBtn.textContent = isBusy ? "Syncing..." : "Sync applicants";
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
  setRefreshApplicantsStatus("Syncing applicants...");

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
    { label: "Position", value: state.filters.position },
    { label: "Salary", value: state.filters.salary },
    { label: "Years", value: state.filters.years_experience },
    { label: "Industry", value: state.filters.industry },
    { label: "Country", value: state.filters.country },
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

function normalizeCountryLookup(value) {
  return normalizeAscii(value)
    .replace(/[^a-z\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRegex(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function hasExactCountryTerm(haystack, term) {
  if (!haystack || !term) return false;
  const normalizedTerm = normalizeCountryLookup(term);
  if (!normalizedTerm) return false;
  const pattern = new RegExp(`(^|\\s)${escapeRegex(normalizedTerm)}(?=\\s|$)`, "i");
  return pattern.test(haystack);
}

function resolveCountryInfo(location) {
  const needle = normalizeCountryLookup(location);
  if (!needle) return null;

  for (const entry of COUNTRY_DIRECTORY) {
    if (hasExactCountryTerm(needle, entry.name)) return entry;
  }

  for (const entry of COUNTRY_DIRECTORY) {
    if ((entry.aliases || []).some((alias) => hasExactCountryTerm(needle, alias))) return entry;
  }

  return null;
}

const LATAM_COUNTRIES = new Set(
  COUNTRY_DIRECTORY
    .filter((entry) => entry.code && !["US", "CA", "ES"].includes(entry.code))
    .map((entry) => entry.name)
);

function isLatinAmericaFilter(value) {
  const needle = normalizeAscii(value).replace(/[^a-z\s]/g, " ");
  return (
    needle.includes("latin america") ||
    needle.includes("latam") ||
    needle.includes("lata") ||
    needle.includes("latinoamerica") ||
    needle.includes("latino america") ||
    needle.includes("america latina")
  );
}

function isLatinAmericaLocation(value) {
  const needle = normalizeAscii(value);
  if (!needle) return false;
  return Array.from(LATAM_COUNTRIES).some((name) => needle.includes(name));
}

function formatPhoneNumber(phone, countryInfo) {
  if (!phone) return "—";
  const cleaned = String(phone).trim();
  if (!cleaned) return "—";
  if (cleaned.startsWith("+")) return cleaned;
  if (cleaned.startsWith("00")) return `+${cleaned.slice(2)}`;
  const digits = cleaned.replace(/\D/g, "");
  const dialDigits = String(countryInfo?.dial || "").replace(/\D/g, "");
  if (dialDigits) {
    if (digits.startsWith(dialDigits)) return `+${digits}`;
    return `${countryInfo.dial} ${digits || cleaned}`;
  }
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

function normalizeGenderValue(value) {
  const normalized = normalizeAscii(value);
  if (!normalized) return "";
  if (["male", "man", "hombre", "masculino", "m"].includes(normalized)) return "male";
  if (["female", "woman", "mujer", "femenino", "f"].includes(normalized)) return "female";
  return "";
}

const COMMON_FEMALE_NAMES = new Set([
  "abby", "adriana", "agustina", "alejandra", "alexandra", "alexa", "alicia", "allison",
  "amanda", "ana", "anabel", "andrea", "angela", "angie", "anna", "ashley", "barbara",
  "beatriz", "brenda", "camila", "carla", "carolina", "cassandra", "catalina", "cecilia",
  "clara", "claudia", "cristina", "daniela", "diana", "emilia", "erika", "estefania",
  "evelin", "evelyn", "fabiana", "fernanda", "flor", "gabriela", "gisela", "gloria",
  "helen", "ingrid", "isabel", "isabella", "ivonne", "jennifer", "jessica", "jimena",
  "joana", "johana", "julia", "juliana", "karen", "karina", "karen", "kate", "katherine",
  "kathleen", "laura", "leslie", "liliana", "lina", "lorena", "lucia", "luisa", "luz",
  "madison", "mafer", "margarita", "maria", "mariana", "maribel", "mariela", "maritza",
  "melanie", "melissa", "micaela", "monica", "natalia", "nicole", "noelia", "paola",
  "patricia", "paula", "paulina", "rebecca", "rosa", "sabrina", "samantha", "sara",
  "sarah", "shirley", "silvia", "sofia", "stephanie", "susana", "tatiana", "tiffany",
  "valentina", "valeria", "vanessa", "veronica", "victoria", "ximena", "yessica", "yuliana"
]);

const COMMON_MALE_NAMES = new Set([
  "aaron", "adrian", "agustin", "alan", "alberto", "alejandro", "alex", "alonso",
  "andres", "anthony", "antonio", "benjamin", "brayan", "bryan", "camilo", "carlos",
  "christian", "cristian", "daniel", "danny", "david", "diego", "edgar", "eduardo",
  "emmanuel", "enzo", "esteban", "fabian", "felipe", "fernando", "francisco", "gabriel",
  "gary", "gerardo", "gerson", "giovanni", "gustavo", "harold", "hector", "henry",
  "hugo", "ian", "isaac", "ivan", "javier", "jean", "jesus", "john", "jonathan",
  "jorge", "jose", "juan", "julian", "kevin", "leo", "leonardo", "luis", "manuel",
  "marco", "marcos", "martin", "mateo", "mauricio", "max", "miguel", "nelson", "nicolas",
  "oscar", "pablo", "paul", "pedro", "rafael", "raul", "ricardo", "roberto", "rodrigo",
  "samuel", "santiago", "sebastian", "sergio", "tomas", "victor", "walter", "william"
]);

function inferGenderFromName(name) {
  const normalized = normalizeAscii(name)
    .replace(/[^a-z\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) return "";

  const [firstToken] = normalized.split(" ").filter(Boolean);
  if (!firstToken) return "";

  if (COMMON_FEMALE_NAMES.has(firstToken)) return "female";
  if (COMMON_MALE_NAMES.has(firstToken)) return "male";

  if (firstToken.endsWith("ette") || firstToken.endsWith("elly") || firstToken.endsWith("lly")) return "female";
  if (firstToken.endsWith("son") || firstToken.endsWith("ton")) return "male";
  if (firstToken.endsWith("a")) return "female";
  if (firstToken.endsWith("o")) return "male";
  if (firstToken.endsWith("el") || firstToken.endsWith("er") || firstToken.endsWith("an")) return "male";
  if (firstToken.endsWith("is") || firstToken.endsWith("ys") || firstToken.endsWith("lin")) return "female";

  return "";
}

function inferGenderFromText(text) {
  const normalized = normalizeAscii(text);
  if (!normalized) return "";

  const femalePattern = /\b(she|her|hers|woman|female|ms|mrs)\b/i;
  const malePattern = /\b(he|him|his|man|male|mr)\b/i;
  const femaleMatch = femalePattern.test(normalized);
  const maleMatch = malePattern.test(normalized);

  if (femaleMatch && !maleMatch) return "female";
  if (maleMatch && !femaleMatch) return "male";
  return "";
}

function resolveApplicantGender(applicant) {
  const explicitGender = normalizeGenderValue(
    applicant.gender ||
    applicant.sexo ||
    applicant.sex ||
    applicant.preferred_gender ||
    applicant.pronouns
  );
  if (explicitGender) return explicitGender;

  const nameGender = inferGenderFromName(
    applicant.first_name ||
    applicant.name ||
    `${applicant.first_name || ""} ${applicant.last_name || ""}`.trim()
  );
  if (nameGender) return nameGender;

  const textGender = inferGenderFromText([
    applicant.first_name,
    applicant.last_name,
    applicant.linkedin_url,
    applicant.extracted_pdf,
  ].filter(Boolean).join(" "));
  if (textGender) return textGender;

  return "female";
}

function matchesGenderFilter(candidate) {
  const activeFilter = state.ui.genderFilter || "all";
  if (activeFilter === "all") return true;
  return (candidate.profile.gender || "unknown") === activeFilter;
}

function getGenderCounts() {
  return state.candidates.reduce((acc, candidate) => {
    const gender = candidate?.profile?.gender || "female";
    acc.all += 1;
    if (gender === "male") acc.male += 1;
    else acc.female += 1;
    return acc;
  }, { all: 0, male: 0, female: 0 });
}

function syncGenderFilterButtons() {
  if (!els.candidateGenderFilter) return;
  const counts = getGenderCounts();
  const buttons = els.candidateGenderFilter.querySelectorAll("[data-gender-filter]");
  buttons.forEach((button) => {
    const filterKey = button.dataset.genderFilter || "all";
    const isActive = filterKey === state.ui.genderFilter;
    const baseLabel = (
      filterKey === "all" ? "Todos" :
      filterKey === "male" ? "Hombre" :
      "Mujer"
    );
    const count = Number.isFinite(counts[filterKey]) ? counts[filterKey] : 0;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-pressed", isActive ? "true" : "false");
    button.textContent = `${baseLabel} (${count})`;
  });
}

const FLAG_FILTER_LABELS = {
  reviewed: { yes: "Revisados", no: "No revisados" },
  contacted: { yes: "Contactados", no: "No contactados" },
  rejected: { yes: "Rechazados", no: "No rechazados" },
};

function getFlagFilterValue(flag) {
  return state.ui.flagFilters?.[flag] || "all";
}

function matchesFlagFilters(candidate) {
  const id = candidate?.profile?.id;
  return FLAG_ORDER.every((flag) => {
    const value = getFlagFilterValue(flag);
    if (value === "all") return true;
    const flagged = isApplicantFlagged(flag, id);
    return value === "yes" ? flagged : !flagged;
  });
}

function getFlagFilterCounts(flag) {
  return state.candidates.reduce((acc, candidate) => {
    acc.all += 1;
    if (isApplicantFlagged(flag, candidate?.profile?.id)) acc.yes += 1;
    else acc.no += 1;
    return acc;
  }, { all: 0, yes: 0, no: 0 });
}

function syncFlagFilterButtons() {
  if (!els.flagFilterSections) return;
  els.flagFilterSections.forEach((section) => {
    const flag = section.dataset.flagFilterSection;
    if (!flag || !FLAG_STORAGE_KEYS[flag]) return;
    const counts = getFlagFilterCounts(flag);
    const active = getFlagFilterValue(flag);
    const labels = FLAG_FILTER_LABELS[flag] || { yes: "Sí", no: "No" };
    section.querySelectorAll("[data-flag-filter-value]").forEach((button) => {
      const value = button.dataset.flagFilterValue || "all";
      const isActive = value === active;
      const baseLabel = value === "all" ? "Todos" : (labels[value] || value);
      const count = Number.isFinite(counts[value]) ? counts[value] : 0;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", isActive ? "true" : "false");
      button.textContent = `${baseLabel} (${count})`;
    });
  });
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

function buildApplicantProfile(applicant) {
  const fullName = `${applicant.first_name || ""} ${applicant.last_name || ""}`.trim();
  const fallbackName = fullName || applicant.email || "Unnamed";
  const cvText = applicant.extracted_pdf || "";
  const searchableText = [
    applicant.role_position,
    applicant.area,
    applicant.location,
    applicant.english_level,
    applicant.referral_source,
    applicant.question_1,
    applicant.question_2,
    applicant.question_3,
    cvText,
  ]
    .filter(Boolean)
    .join(" ");

  return {
    id: applicant.applicant_id,
    name: fallbackName,
    gender: resolveApplicantGender(applicant),
    country: applicant.location || "",
    position: applicant.role_position || "",
    industry: applicant.area || "",
    years: null,
    salaryRange: null,
    searchableText,
    cvText,
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
  return Object.values(state.filters || {}).some((value) => String(value || "").trim());
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
  points.push(scoreTextMatch(profile.position, state.filters.position, profile.searchableText));
  points.push(scoreTextMatch(profile.industry, state.filters.industry, profile.searchableText));
  points.push(scoreTextMatch(profile.country, state.filters.country, profile.searchableText));
  points.push(scoreYearsMatch(profile));
  points.push(scoreSalaryMatch(profile));

  const scored = points.filter((value) => value != null);
  const maxPoints = scored.length * 2;
  if (!maxPoints) return 10;
  const total = scored.reduce((sum, value) => sum + value, 0);
  const ratio = total / maxPoints;
  const scaled = Math.round(ratio * 9) + 1;
  return Math.min(10, Math.max(1, scaled));
}

function getDisplayScore(score) {
  return Number.isFinite(score) ? score : null;
}

function getMatchSummary(profile) {
  const parts = [];
  if (state.filters.country) {
    if (isLatinAmericaFilter(state.filters.country)) {
      parts.push(isLatinAmericaLocation(profile.country || profile.searchableText) ? "based in Latin America" : "location outside Latin America");
    } else if (matchesTextFilter(profile.country, state.filters.country, profile.searchableText)) {
      parts.push("location matches");
    } else {
      parts.push("location not mentioned");
    }
  }
  if (state.filters.position) {
    parts.push(
      matchesTextFilter(profile.position, state.filters.position, profile.searchableText)
        ? "position matches"
        : "position not mentioned"
    );
  }
  if (state.filters.industry) {
    parts.push(
      matchesTextFilter(profile.industry, state.filters.industry, profile.searchableText)
        ? "industry matches"
        : "industry not mentioned"
    );
  }
  if (state.filters.years_experience) {
    const yearScore = scoreYearsMatch(profile);
    if (yearScore === 2) parts.push("years of experience match");
    else if (yearScore === 1) parts.push("years of experience are close");
    else parts.push("years of experience not found");
  }
  if (state.filters.salary) {
    const salaryScore = scoreSalaryMatch(profile);
    if (salaryScore === 2) parts.push("salary aligns");
    else if (salaryScore === 1) parts.push("salary is close");
    else parts.push("salary not found");
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
      percent: null,
      detail: "Filtro no definido para esta vacante.",
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
  const roleHave = profile.position || "";
  const industryHave = profile.industry || "";
  const countryHave = profile.country || "";
  const yearsHave = resolveCandidateYears(profile);
  const percentLabel = `${percent || 0}%`;
  const experienceInfo = extractExperienceFromText(profile.searchableText);
  const educationSnippet = "";

  const leadSentence = includePercent
    ? `Resumen del CV para esta comparación (${percentLabel}).`
    : "Resumen del CV para esta comparación.";

  const roleSentence = roleHave
    ? `La persona ha trabajado como ${roleHave} y esa experiencia es el eje principal del perfil.`
    : "El rol específico no está declarado de forma explícita, pero el CV sugiere experiencia relevante en funciones similares.";

  const industrySentence = industryHave
    ? `En industria, se observa experiencia en ${industryHave}, lo cual aporta contexto sobre los sectores en los que se ha desempeñado.`
    : "No se identifica una industria concreta en el CV, por lo que el foco queda en las funciones y responsabilidades descritas.";

  const yearsSentence = yearsHave != null
    ? `El CV sugiere alrededor de ${formatExperienceDuration(yearsHave)} de experiencia profesional, lo que permite estimar el nivel de seniority.`
    : "No hay una cifra clara de años de experiencia, por lo que se resume la trayectoria cualitativamente.";

  const countrySentence = countryHave
    ? `En ubicación, el perfil indica ${countryHave}.`
    : "La ubicación no está detallada en el CV.";

  const experienceSentence = experienceInfo
    ? `Al revisar las fechas de las posiciones laborales, se estiman ${formatExperienceDuration(experienceInfo.totalMonths / 12)} de experiencia acumulada, con tramos que van aproximadamente entre ${experienceInfo.earliestYear} y ${experienceInfo.latestYear}.`
    : (yearsHave != null
      ? `En experiencia profesional, el perfil sugiere aproximadamente ${formatExperienceDuration(yearsHave)} de trayectoria.`
      : "En experiencia profesional, el CV describe roles y responsabilidades, pero no se detectaron rangos de fechas claros para estimar la duración total.");

  const studiesSentence = educationSnippet
    ? `En estudios, se identifica formación académica como: "${educationSnippet}".`
    : "En estudios, no se encontró una referencia académica clara en el texto disponible.";

  const closingSentence = "El resumen se basa en la información explícita del CV y en los datos que se pueden inferir de su trayectoria.";

  return `${leadSentence} ${roleSentence} ${industrySentence} ${experienceSentence} ${yearsSentence} ${countrySentence} ${studiesSentence} ${closingSentence}`.trim();
}

function buildYearsBreakdown(profile) {
  const filterValue = state.filters.years_experience;
  if (!filterValue) {
    return {
      category: "Años de experiencia (filtro)",
      percent: null,
      detail: "Filtro no definido para esta vacante.",
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

  const locationScore = scoreTextMatch(profile.country, state.filters.country, profile.searchableText);
  breakdown.push(
    buildFilterBreakdown(
      "Ubicación",
      state.filters.country,
      locationScore,
      {
        match: "La ubicación del candidato coincide con la requerida.",
        close: "La ubicación es cercana o parcialmente compatible.",
        miss: "No coincide con la ubicación requerida.",
        missing: "No se encontró ubicación suficiente para evaluar.",
      }
    )
  );

  breakdown.push(
    buildFilterBreakdown(
      "Posición (filtro)",
      state.filters.position,
      scoreTextMatch(profile.position, state.filters.position, profile.searchableText),
      {
        match: "La posición coincide con el filtro principal.",
        close: "La posición es similar pero no exacta.",
        miss: "No coincide con el filtro de posición.",
        missing: "No se encontró posición suficiente para evaluar.",
      }
    )
  );

  breakdown.push(
    buildFilterBreakdown(
      "Industria (filtro)",
      state.filters.industry,
      scoreTextMatch(profile.industry, state.filters.industry, profile.searchableText),
      {
        match: "La industria coincide con la requerida.",
        close: "La industria es parcialmente compatible.",
        miss: "No coincide con la industria requerida.",
        missing: "No se encontró industria suficiente para evaluar.",
      }
    )
  );

  breakdown.push(buildYearsBreakdown(profile));

  breakdown.push(
    buildFilterBreakdown(
      "Salario (filtro)",
      state.filters.salary,
      scoreSalaryMatch(profile),
      {
        match: "La expectativa salarial está alineada.",
        close: "La expectativa salarial es cercana.",
        miss: "La expectativa salarial no coincide.",
        missing: "No se encontró información salarial.",
      }
    )
  );

  breakdown.push(
    buildFilterBreakdown(
      "País (filtro)",
      state.filters.country,
      locationScore,
      {
        match: "El país coincide con el filtro definido.",
        close: "El país es cercano o parcialmente compatible.",
        miss: "El país no coincide con el filtro.",
        missing: "No se encontró país suficiente para evaluar.",
      }
    )
  );

  return breakdown;
}

function buildDefaultSummary(profile, percent) {
  return buildJdExplanation(profile, percent, true);
}

function buildMatchModel(profile, score, reasonsRaw) {
  const parsed = parseReasonsPayload(reasonsRaw);
  const percentFallback = scoreToPercent(score);
  const overallPercent = normalizePercent(parsed?.overallPercent, percentFallback);
  const summary = parsed?.summary || (
    Number.isFinite(overallPercent)
      ? buildDefaultSummary(profile, overallPercent)
      : "Este applicant todavía no tiene un score validado. Refresca el CV para evaluarlo con los filtros actuales."
  );
  const breakdownSource = parsed?.breakdown?.length
    ? parsed.breakdown
    : (Number.isFinite(score) ? buildFallbackBreakdown(profile, score) : []);
  const breakdown = breakdownSource
    .filter((item) => normalizeText(item?.category) !== "similitud con la jd")
    .map((item) => ({
      ...item,
      percent: normalizePercent(item.percent, item.percent == null ? null : 0),
    }));
  return {
    percent: overallPercent,
    summary,
    breakdown,
  };
}

function getScoreTone(percent) {
  if (!Number.isFinite(percent)) return "score-na";
  if (percent >= 70) return "score-high";
  if (percent >= 40) return "score-mid";
  return "score-low";
}

function buildInitials(name) {
  return (
    String(name || "")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase() || "")
      .join("") || "?"
  );
}

function buildCandidateRowEl(candidate) {
  const questions = state.applicantQuestions || {};
  const applicant = candidate.pipeline || {};
  const profile = candidate.profile;
  const contacted = isApplicantFlagged("contacted", profile.id);
  const initials = buildInitials(profile.name);

  const countryInfo = resolveCountryInfo(profile.country);
  const flag = countryInfo?.code ? countryCodeToFlag(countryInfo.code) : "";
  const locationLabel = [flag, profile.country].filter(Boolean).join(" ").trim() || "Location unknown";


  const fallbackScore = computeMatchScore(profile);
  const effectiveScore = Number.isFinite(candidate.score) ? candidate.score : fallbackScore;
  const matchModel = buildMatchModel(profile, effectiveScore, candidate.reasons || applicant.reasons || "");
  const scorePercent = matchModel.percent;
  const scoreTone = getScoreTone(scorePercent);
  const scoreText = Number.isFinite(scorePercent) ? `${scorePercent}%` : "—";

  const skillTags = [profile.position, profile.industry, profile.country]
    .filter(Boolean)
    .slice(0, 4)
    .map((tag) => `<span class="candidate-row__chip">${escapeHtml(tag)}</span>`)
    .join("");
  const englishLevel = applicant.english_level
    ? `<span class="candidate-row__chip candidate-row__chip--muted">${escapeHtml(`English: ${applicant.english_level}`)}</span>`
    : "";
  const skillChipsHtml = skillTags + englishLevel;

  const phoneLabel = applicant.phone ? formatPhoneNumber(applicant.phone, countryInfo) : "";
  const contactBits = [
    applicant.email ? escapeHtml(applicant.email) : null,
    phoneLabel ? escapeHtml(phoneLabel) : null,
  ]
    .filter(Boolean)
    .join(" · ") || "—";

  const screeningPairs = [
    { q: questions.question_1, a: applicant.question_1 },
    { q: questions.question_2, a: applicant.question_2 },
    { q: questions.question_3, a: applicant.question_3 },
  ].filter((pair) => pair.a && String(pair.a).trim());
  const screeningHtml = screeningPairs.length
    ? `
      <div class="candidate-row__field">
        <span class="candidate-row__field-label">Screening</span>
        <div class="candidate-row__field-value">
          <div class="candidate-row__qa">
            ${screeningPairs
              .map(
                (pair, idx) => `
                  <div class="candidate-row__qa-item">
                    <p class="candidate-row__qa-q">${escapeHtml(pair.q || `Question ${idx + 1}`)}</p>
                    <p class="candidate-row__qa-a">${escapeHtml(pair.a)}</p>
                  </div>
                `
              )
              .join("")}
          </div>
        </div>
      </div>
    `
    : "";

  const linkedinAction = profile.linkedin
    ? `<a class="candidate-row__action-btn" href="${escapeHtml(profile.linkedin)}" target="_blank" rel="noopener" data-stop="true">LinkedIn ↗</a>`
    : `<span class="candidate-row__action-btn candidate-row__action-btn--muted">No LinkedIn</span>`;
  const cvAction = applicant.cv_s3_key
    ? `<button class="candidate-row__action-btn" data-action="download-cv" data-applicant-id="${applicant.applicant_id}" type="button">CV</button>`
    : "";
  const referralRow = applicant.referral_source
    ? `<div class="candidate-row__field"><span class="candidate-row__field-label">Source</span><span class="candidate-row__field-value">${escapeHtml(applicant.referral_source)}</span></div>`
    : "";

  const breakdownRowsHtml = (matchModel.breakdown || [])
    .map((item) => {
      const percentValue = normalizePercent(item.percent, null);
      const tone = getScoreTone(percentValue);
      const percentLabel = percentValue == null ? "N/A" : `${percentValue}%`;
      return `
        <div class="candidate-row__breakdown-row ${tone}">
          <div class="candidate-row__breakdown-head">
            <span>${escapeHtml(item.category)}</span>
            <span>${escapeHtml(percentLabel)}</span>
          </div>
          <p class="candidate-row__breakdown-detail">${escapeHtml(item.detail || "Sin detalle adicional.")}</p>
        </div>
      `;
    })
    .join("");
  const breakdownHtml = breakdownRowsHtml
    ? `
      <div class="candidate-row__breakdown" hidden>
        <div class="candidate-row__breakdown-summary">${escapeHtml(matchModel.summary || "")}</div>
        <div class="candidate-row__breakdown-list">${breakdownRowsHtml}</div>
      </div>
    `
    : "";

  const row = document.createElement("article");
  row.className = "candidate-row";
  row.dataset.applicantId = profile.id;
  row.innerHTML = `
    <div class="candidate-row__avatar">
      <div class="candidate-row__avatar-circle">${escapeHtml(initials)}</div>
    </div>
    <div class="candidate-row__main">
      <div class="candidate-row__heading">
        <span class="candidate-row__name">${escapeHtml(profile.name)}</span>
        <span class="candidate-row__status ${contacted ? "is-contacted" : ""}">${contacted ? "Contacted" : "New applicant"}</span>
      </div>
      <div class="candidate-row__subline">
        <span>${escapeHtml(profile.position || "Role unknown")}</span>
        <span class="dot">·</span>
        <span>${escapeHtml(locationLabel)}</span>
        ${profile.industry ? `<span class="dot">·</span><span>${escapeHtml(profile.industry)}</span>` : ""}
      </div>
      ${skillChipsHtml ? `
      <div class="candidate-row__field">
        <span class="candidate-row__field-label">Skills match</span>
        <div class="candidate-row__field-value"><div class="candidate-row__chips">${skillChipsHtml}</div></div>
      </div>` : ""}
      <div class="candidate-row__field">
        <span class="candidate-row__field-label">Contact</span>
        <span class="candidate-row__field-value">${contactBits}</span>
      </div>
      ${screeningHtml}
      ${referralRow}
      ${breakdownHtml}
    </div>
    <div class="candidate-row__side">
      <div class="candidate-row__score-card ${scoreTone}" data-action="toggle-breakdown" role="button" tabindex="0" aria-expanded="false" aria-label="Toggle match score breakdown">
        <div class="candidate-row__score-value">${escapeHtml(scoreText)}</div>
        <div class="candidate-row__score-label">Match score</div>
        <span class="candidate-row__score-link" data-toggle-label>View reasons →</span>
      </div>
      ${buildFlagTogglesHtml(profile.id, { layout: "stacked" })}
      <div class="candidate-row__actions">
        ${linkedinAction}
        ${cvAction}
      </div>
    </div>
  `;
  return row;
}

function getOrderedCandidates() {
  return state.candidates
    .map((candidate) => {
      const score = getDisplayScore(candidate.score);
      return { ...candidate, score };
    })
    .filter((candidate) => matchesGenderFilter(candidate))
    .filter((candidate) => matchesFlagFilters(candidate))
    .sort((a, b) => {
      const aRejected = isApplicantFlagged("rejected", a.profile?.id);
      const bRejected = isApplicantFlagged("rejected", b.profile?.id);
      if (aRejected !== bRejected) return aRejected ? 1 : -1;
      if (Number.isFinite(a.score) && Number.isFinite(b.score)) return b.score - a.score;
      if (Number.isFinite(a.score)) return -1;
      if (Number.isFinite(b.score)) return 1;
      return 0;
    });
}

function updatePaginatorUI(total) {
  if (!els.paginator || !els.paginatorCounter) return;
  if (!total) {
    els.paginatorCounter.textContent = "– / –";
    if (els.prevCandidateBtn) els.prevCandidateBtn.disabled = true;
    if (els.nextCandidateBtn) els.nextCandidateBtn.disabled = true;
    els.paginator.style.visibility = "hidden";
    return;
  }
  els.paginator.style.visibility = "visible";
  els.paginatorCounter.textContent = `${state.paginationIndex + 1} / ${total}`;
  if (els.prevCandidateBtn) els.prevCandidateBtn.disabled = state.paginationIndex <= 0;
  if (els.nextCandidateBtn) els.nextCandidateBtn.disabled = state.paginationIndex >= total - 1;
}

function renderCandidates() {
  const ordered = getOrderedCandidates();

  syncGenderFilterButtons();
  syncFlagFilterButtons();

  if (state.paginationIndex >= ordered.length) state.paginationIndex = Math.max(0, ordered.length - 1);
  if (state.paginationIndex < 0) state.paginationIndex = 0;

  els.candidatesGrid.innerHTML = "";
  els.candidatesEmpty.style.display = ordered.length ? "none" : "block";
  els.candidatesEmpty.textContent = ordered.length
    ? ""
    : (state.candidates.length ? "No hay candidatos para ese filtro." : "No applicants yet.");
  els.candidateCount.textContent = `${ordered.length} applicants`;

  if (ordered.length) {
    const candidate = ordered[state.paginationIndex];
    els.candidatesGrid.appendChild(buildCandidateRowEl(candidate));
  }

  updatePaginatorUI(ordered.length);
}

function changeCandidatePage(delta) {
  const ordered = getOrderedCandidates();
  if (!ordered.length) return;
  const next = Math.min(ordered.length - 1, Math.max(0, state.paginationIndex + delta));
  if (next === state.paginationIndex) return;
  state.paginationIndex = next;
  renderCandidates();
  if (els.candidatesGrid) {
    els.candidatesGrid.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
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
    state.paginationIndex = 0;
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
    entry.score,
    entry.reasons || applicant.reasons || ""
  );
  const breakdownHtml = match.breakdown
    .map((item) => {
      const percentValue = normalizePercent(item.percent, null);
      const tone = getScoreTone(percentValue);
      const percentLabel = percentValue == null ? "N/A" : `${percentValue}%`;
      return `
        <div class="score-row ${tone}">
          <div class="score-row-head">
            <span class="score-category">${escapeHtml(item.category)}</span>
            <span class="score-percent">${escapeHtml(percentLabel)}</span>
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
      <div class="drawer-item drawer-item-contacted">
        <span class="drawer-label">Status</span>
        ${buildFlagTogglesHtml(applicant.applicant_id, { layout: "stacked" })}
      </div>
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
            <div class="score-value">${Number.isFinite(match.percent) ? escapeHtml(match.percent) + "%" : "—"}</div>
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
      state.paginationIndex = 0;
      renderFilters();
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
  setChatExpanded(false);
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

  if (els.candidateGenderFilter) {
    els.candidateGenderFilter.addEventListener("click", (event) => {
      const button = event.target.closest("[data-gender-filter]");
      if (!button) return;
      state.ui.genderFilter = button.dataset.genderFilter || "all";
      state.paginationIndex = 0;
      syncGenderFilterButtons();
      renderCandidates();
    });
    syncGenderFilterButtons();
  }

  if (els.flagFilterSections && els.flagFilterSections.length) {
    els.flagFilterSections.forEach((section) => {
      const flag = section.dataset.flagFilterSection;
      if (!flag || !FLAG_STORAGE_KEYS[flag]) return;
      section.addEventListener("click", (event) => {
        const button = event.target.closest("[data-flag-filter-value]");
        if (!button) return;
        const value = button.dataset.flagFilterValue || "all";
        if (!state.ui.flagFilters) state.ui.flagFilters = {};
        state.ui.flagFilters[flag] = value;
        state.paginationIndex = 0;
        syncFlagFilterButtons();
        renderCandidates();
      });
    });
    syncFlagFilterButtons();
  }

  if (els.prevCandidateBtn) {
    els.prevCandidateBtn.addEventListener("click", () => changeCandidatePage(-1));
  }
  if (els.nextCandidateBtn) {
    els.nextCandidateBtn.addEventListener("click", () => changeCandidatePage(1));
  }
  document.addEventListener("keydown", (event) => {
    if (event.target && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
    if (event.target && event.target.isContentEditable) return;
    if (document.body.classList.contains("drawer-open")) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      changeCandidatePage(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      changeCandidatePage(1);
    }
  });

  if (els.chatFab) {
    els.chatFab.addEventListener("click", () => {
      setChatExpanded(!state.ui.chatExpanded);
    });
  }

  if (els.candidatesGrid) {
    const toggleBreakdown = (trigger) => {
      const row = trigger.closest(".candidate-row");
      if (!row) return;
      const panel = row.querySelector(".candidate-row__breakdown");
      if (!panel) return;
      const expanded = !panel.hasAttribute("hidden");
      if (expanded) {
        panel.setAttribute("hidden", "");
      } else {
        panel.removeAttribute("hidden");
      }
      const card = trigger.closest('[data-action="toggle-breakdown"]') || trigger;
      card.setAttribute("aria-expanded", expanded ? "false" : "true");
      const label = card.querySelector("[data-toggle-label]");
      if (label) label.textContent = expanded ? "View reasons →" : "Hide reasons ↑";
    };

    els.candidatesGrid.addEventListener("click", async (event) => {
      if (event.target.closest("[data-stop]")) return;
      if (event.target.closest(".candidate-flag-toggle")) return;

      const cvBtn = event.target.closest('[data-action="download-cv"]');
      if (cvBtn) {
        event.preventDefault();
        // Open the popup synchronously inside the click handler so the
        // browser preserves the user-gesture and doesn't block it.
        const popup = window.open("", "_blank");
        const applicantId = Number(cvBtn.dataset.applicantId);
        const original = cvBtn.textContent;
        cvBtn.disabled = true;
        cvBtn.textContent = "Loading…";
        try {
          const data = await fetchJSON(`${API_BASE}/applicants/${applicantId}/cv`);
          if (data?.url) {
            if (popup && !popup.closed) {
              popup.location.href = data.url;
            } else {
              window.location.href = data.url;
            }
          } else if (popup && !popup.closed) {
            popup.close();
          }
        } catch (err) {
          console.warn("CV download failed", err);
          if (popup && !popup.closed) popup.close();
          cvBtn.textContent = "Unavailable";
          setTimeout(() => { cvBtn.textContent = original; cvBtn.disabled = false; }, 1500);
          return;
        }
        cvBtn.textContent = original;
        cvBtn.disabled = false;
        return;
      }

      const breakdownTrigger = event.target.closest('[data-action="toggle-breakdown"]');
      if (breakdownTrigger) {
        toggleBreakdown(breakdownTrigger);
        return;
      }
    });

    els.candidatesGrid.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const trigger = event.target.closest('[data-action="toggle-breakdown"]');
      if (!trigger) return;
      event.preventDefault();
      toggleBreakdown(trigger);
    });

    els.candidatesGrid.addEventListener("change", (event) => {
      const checkbox = event.target.closest(".candidate-flag-checkbox");
      if (!checkbox) return;
      handleFlagCheckboxChange(checkbox);
      renderCandidates();
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
    els.drawerBody.addEventListener("change", (event) => {
      const checkbox = event.target.closest(".candidate-flag-checkbox");
      if (!checkbox) return;
      handleFlagCheckboxChange(checkbox);
      renderCandidates();
      const selected = state.candidates.find(
        (entry) => entry.profile.id === state.selectedApplicantId
      );
      if (selected?.pipeline) {
        const fallback = computeMatchScore(selected.profile);
        const score = Number.isFinite(selected.score) ? selected.score : fallback;
        renderApplicantDrawer({ ...selected, score });
      }
    });
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
