const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

const state = {
  opportunities: [],
  currentOpportunity: null,
  currentUserEmail: "",
  isHrLead: false,
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
  opportunitiesBody: document.getElementById("opportunitiesBody"),
  opportunityHint: document.getElementById("opportunityHint"),
  hrFilterPill: document.getElementById("hrFilterPill"),
  chatSubtitle: null,
  chatStatus: null,
  chatMessages: null,
  chatForm: null,
  chatInput: null,
  candidateSubtitle: null,
  candidateCount: null,
  filtersGrid: null,
  filtersStatus: null,
  candidatesGrid: null,
  candidatesEmpty: null,
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

function setChatStatus() {}
function setFiltersStatus() {}
function setCandidateSubtitle() {}

function setOpportunityHint(text) {
  if (els.opportunityHint) els.opportunityHint.textContent = text;
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

function appendMessage() {
  return null;
}

function normalizeText(value) {
  return String(value || "").toLowerCase().trim();
}

function normalizeStage(value) {
  return normalizeText(value).replace(/\s+/g, "-");
}

function renderOpportunities(opportunities) {
  els.opportunitiesBody.innerHTML = "";
  if (!opportunities.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5">No opportunities available.</td>';
    els.opportunitiesBody.appendChild(row);
    return;
  }

  opportunities.forEach((opp) => {
    const row = document.createElement("tr");
    row.dataset.oppId = opp.opportunity_id;
    row.innerHTML = `
      <td>${escapeHtml(opp.opp_position_name || "Untitled")}</td>
      <td>${escapeHtml(opp.client_name || "—")}</td>
      <td>${escapeHtml(opp.opp_stage || "—")}</td>
      <td>${escapeHtml(opp.opp_hr_lead || "—")}</td>
      <td>${escapeHtml(opp.opp_model || "—")}</td>
    `;
    row.addEventListener("click", () => selectOpportunity(opp));
    els.opportunitiesBody.appendChild(row);
  });
}

function highlightOpportunity(opportunityId) {
  document.querySelectorAll("#opportunitiesBody tr").forEach((row) => {
    row.classList.toggle("active", String(row.dataset.oppId) === String(opportunityId));
  });
}

async function selectOpportunity(opp) {
  if (!opp?.opportunity_id) return;
  const target = `talentum-detail.html?id=${encodeURIComponent(opp.opportunity_id)}`;
  window.open(target, "_blank", "noopener,noreferrer");
}

async function extractFiltersFromOpportunity() {}

function renderFilters() {}

function renderCandidates() {}

async function loadOpportunities() {
  setOpportunityHint("Loading opportunities…");
  const opportunities = await fetchJSON(`${API_BASE}/opportunities/light`);
  const list = Array.isArray(opportunities) ? opportunities : [];
  const email = state.currentUserEmail;

  let visible = list;
  if (state.isHrLead && email) {
    visible = list.filter((opp) => normalizeText(opp.opp_hr_lead) === email);
    els.hrFilterPill.textContent = "Filter: my HR lead";
  } else {
    els.hrFilterPill.textContent = "Filter: all HR leads";
  }

  state.opportunities = visible;
  renderOpportunities(visible);
  setOpportunityHint(visible.length ? "Select an opportunity to start." : "No opportunities found.");

  return visible;
}

async function loadRecruiters() {
  try {
    const recruiters = await fetchJSON(`${API_BASE}/users/recruiters`);
    const emails = (Array.isArray(recruiters) ? recruiters : [])
      .map((user) => normalizeText(user.email_vintti))
      .filter(Boolean);
    state.isHrLead = emails.includes(state.currentUserEmail);
  } catch (err) {
    console.warn("Recruiter list failed", err);
  }
}

function handleChatSubmit() {}

async function init() {
  state.currentUserEmail = getStoredEmail();
  setUserPill(state.currentUserEmail ? state.currentUserEmail : "Guest");

  await loadRecruiters();
  await loadOpportunities();
}

init().catch((err) => {
  console.error("Talentum init failed", err);
  setOpportunityHint("Unable to load data.");
});
