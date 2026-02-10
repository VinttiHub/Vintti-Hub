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

function normalizeStage(value) {
  return normalizeText(value).replace(/\s+/g, "-");
}

async function loadOpportunity(opportunityId) {
  setChatStatus("Loading");
  setFiltersStatus("Extracting");
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
    await loadApplicants(opportunityId);
  } catch (err) {
    console.error("Failed to load candidates", err);
    setCandidateSubtitle("Unable to load applicants.");
  }

  if (state.candidates.length) {
    setCandidateSubtitle("Applicants sorted by match score.");
  }
  setChatStatus("Ready");
  setFiltersStatus("Ready");
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

function parseJSONSafe(value) {
  if (!value) return null;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function flattenStrings(value, bucket) {
  if (value == null) return;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed) bucket.push(trimmed);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item) => flattenStrings(item, bucket));
    return;
  }
  if (typeof value === "object") {
    Object.values(value).forEach((item) => flattenStrings(item, bucket));
  }
}

function extractFirstFromKeys(source, keys) {
  if (!source || typeof source !== "object") return "";
  for (const key of keys) {
    if (source[key]) return String(source[key]);
  }
  return "";
}

function extractPosition(core) {
  if (!core) return "";
  const headline = extractFirstFromKeys(core, ["headline", "title", "position"]);
  if (headline) return headline;
  const positions = core.positions || core.position || [];
  if (Array.isArray(positions)) {
    const first = positions.find((item) => item && (item.title || item.position));
    return first ? String(first.title || first.position) : "";
  }
  return "";
}

function extractIndustry(core) {
  return extractFirstFromKeys(core || {}, ["industry", "industry_name", "sector"]);
}

function extractCountry(core, fallback) {
  const direct = extractFirstFromKeys(core || {}, ["country", "location_country"]);
  if (direct) return direct;
  const location = extractFirstFromKeys(core || {}, ["location", "location_name"]);
  if (location && location.includes(",")) {
    return location.split(",").pop().trim();
  }
  return fallback || location || "";
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

function findYearsFromText(text) {
  const match = String(text || "").match(/(\d{1,2})\s*(?:\+?\s*)?(?:years|year|anos|años)/i);
  if (!match) return null;
  const num = Number(match[1]);
  return Number.isFinite(num) ? num : null;
}

function extractYears(core, fallbackText) {
  if (!core) return findYearsFromText(fallbackText);
  const numericKeys = ["total_experience", "years_experience", "experience_years"];
  for (const key of numericKeys) {
    if (core[key] != null) {
      const num = Number(core[key]);
      if (Number.isFinite(num)) return num;
    }
  }
  const summary = extractFirstFromKeys(core, ["summary", "headline"]);
  return findYearsFromText(summary || fallbackText);
}

function buildCandidateProfile(pipelineCandidate, detailCandidate) {
  const core = parseJSONSafe(detailCandidate?.coresignal_scrapper);
  const texts = [];
  flattenStrings(core, texts);
  const searchableText = `${texts.join(" ")} ${detailCandidate?.country || ""} ${detailCandidate?.salary_range || ""}`;

  return {
    id: pipelineCandidate.candidate_id,
    name: detailCandidate?.name || pipelineCandidate.name || "Unnamed",
    country: detailCandidate?.country || pipelineCandidate.country || "",
    position: extractPosition(core) || detailCandidate?.position || "",
    industry: extractIndustry(core) || "",
    years: extractYears(core, searchableText),
    salaryRange: parseSalaryRange(detailCandidate?.salary_range || pipelineCandidate.employee_salary),
    searchableText,
    linkedin: detailCandidate?.linkedin || "",
    core,
  };
}

function matchesTextFilter(candidateValue, filterValue, fallbackText) {
  if (!filterValue) return true;
  const haystack = normalizeText(candidateValue || fallbackText);
  const needle = normalizeText(filterValue);
  return haystack.includes(needle);
}

function matchesFilters(profile) {
  if (!matchesTextFilter(profile.position, state.filters.position, profile.searchableText)) return false;
  if (!matchesTextFilter(profile.industry, state.filters.industry, profile.searchableText)) return false;
  if (!matchesTextFilter(profile.country, state.filters.country, profile.searchableText)) return false;

  if (state.filters.years_experience) {
    const filterYears = parseNumber(state.filters.years_experience) || findYearsFromText(state.filters.years_experience);
    if (filterYears != null) {
      if (profile.years != null) {
        if (profile.years < filterYears) return false;
      } else if (!matchesTextFilter("", state.filters.years_experience, profile.searchableText)) {
        return false;
      }
    }
  }

  if (state.filters.salary) {
    const filterRange = parseSalaryRange(state.filters.salary);
    if (filterRange && profile.salaryRange) {
      if (profile.salaryRange.max < filterRange.min || profile.salaryRange.min > filterRange.max) return false;
    } else if (!matchesTextFilter("", state.filters.salary, profile.searchableText)) {
      return false;
    }
  }

  return true;
}

function renderCandidates() {
  const filtered = state.candidates.filter((candidate) => matchesFilters(candidate.profile));
  els.candidatesGrid.innerHTML = "";
  els.candidatesEmpty.style.display = filtered.length ? "none" : "block";
  els.candidatesEmpty.textContent = filtered.length
    ? ""
    : "No candidates match the active filters.";
  els.candidateCount.textContent = `${filtered.length} matches`;

  filtered.forEach((candidate) => {
    const card = document.createElement("div");
    card.className = "candidate-card";
    const tags = [candidate.profile.position, candidate.profile.industry, candidate.profile.country]
      .filter(Boolean)
      .slice(0, 3)
      .map((tag) => `<span class="candidate-tag">${escapeHtml(tag)}</span>`)
      .join("");

    card.innerHTML = `
      <h4>${escapeHtml(candidate.profile.name)}</h4>
      <p class="candidate-meta">${escapeHtml(candidate.profile.position || "Role unknown")}</p>
      <p class="candidate-meta">${escapeHtml(candidate.profile.country || "Location unknown")}</p>
      <div class="candidate-tags">${tags}</div>
      <a class="candidate-link" href="candidate-details.html?id=${candidate.profile.id}" target="_blank" rel="noopener">Open profile →</a>
    `;
    els.candidatesGrid.appendChild(card);
  });
}

async function hydrateCandidate(pipelineCandidate) {
  const detail = await fetchJSON(`${API_BASE}/candidates/${pipelineCandidate.candidate_id}`);
  const hasCore = detail?.coresignal_scrapper && String(detail.coresignal_scrapper).trim();

  if (!hasCore && detail?.linkedin) {
    try {
      await fetch(`${API_BASE}/coresignal/candidates/${pipelineCandidate.candidate_id}/sync`, {
        method: "POST",
      });
      return await fetchJSON(`${API_BASE}/candidates/${pipelineCandidate.candidate_id}`);
    } catch (err) {
      console.warn("Coresignal sync failed", err);
    }
  }

  return detail;
}

async function loadApplicants(opportunityId) {
  setCandidateSubtitle("Fetching applicants…");
  const candidates = await fetchJSON(`${API_BASE}/opportunities/${opportunityId}/candidates`);
  const applicants = (Array.isArray(candidates) ? candidates : []).filter((candidate) => {
    const stage = normalizeStage(candidate.stage || candidate.stage_pipeline);
    return stage === "applicant";
  });

  if (!applicants.length) {
    state.candidates = [];
    renderCandidates();
    setCandidateSubtitle("No applicants in pipeline.");
    return;
  }

  setCandidateSubtitle("Syncing CoreSignal and filtering applicants…");
  const detailed = await Promise.all(
    applicants.map(async (candidate) => {
      try {
        const detail = await hydrateCandidate(candidate);
        return {
          pipeline: candidate,
          detail,
          profile: buildCandidateProfile(candidate, detail),
        };
      } catch (err) {
        console.warn("Candidate hydrate failed", err);
        const fallbackDetail = { name: candidate.name, country: candidate.country };
        return {
          pipeline: candidate,
          detail: fallbackDetail,
          profile: buildCandidateProfile(candidate, fallbackDetail),
        };
      }
    })
  );

  state.candidates = detailed;
  renderCandidates();
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
      body: JSON.stringify({ message, current_filters: state.filters }),
    });
    if (typing) typing.remove();
    if (resp.updated_filters) {
      state.filters = { ...state.filters, ...resp.updated_filters };
      renderFilters();
      renderCandidates();
    }
    appendMessage("assistant", resp.response || "Filtros actualizados.");
  } catch (err) {
    console.warn("Chat update failed", err);
    if (typing) typing.remove();
    appendMessage("assistant", "No pude actualizar los filtros, sigo con los actuales.");
  } finally {
    setChatStatus("Ready");
    setFiltersStatus("Ready");
    setCandidateSubtitle("Applicants filtered by active filters.");
  }
}

async function init() {
  state.currentUserEmail = getStoredEmail();
  setUserPill(state.currentUserEmail ? state.currentUserEmail : "Guest");
  setChatStatus("Idle");
  setFiltersStatus("Idle");

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
}

init().catch((err) => {
  console.error("Talentum detail init failed", err);
  setChatStatus("Error");
  setCandidateSubtitle("Unable to load data.");
});
