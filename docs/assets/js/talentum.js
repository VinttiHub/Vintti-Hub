const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

const state = {
  opportunities: [],
  currentOpportunity: null,
  currentUserEmail: "",
  isHrLead: false,
  hrLeadDirectory: {},
  filters: {
    stages: new Set(),
    salesLeads: new Set(),
    hrLeads: new Set(),
    types: new Set(),
    daysRange: { min: null, max: null },
    accountText: "",
    positionText: "",
  },
  filterOptions: {
    stages: [],
    salesLeads: [],
    hrLeads: [],
    types: [],
  },
};

const els = {
  userPill: document.getElementById("userPill"),
  opportunitiesBody: document.getElementById("opportunitiesBody"),
  opportunityHint: document.getElementById("opportunityHint"),
  hrFilterPill: document.getElementById("hrFilterPill"),
  filterStageMenu: document.getElementById("filterStageMenu"),
  filterSalesMenu: document.getElementById("filterSalesMenu"),
  filterHrMenu: document.getElementById("filterHrMenu"),
  filterTypeMenu: document.getElementById("filterTypeMenu"),
  daysRangeFilter: document.getElementById("daysRangeFilter"),
  accountSearchInput: document.getElementById("accountSearchInput"),
  positionSearchInput: document.getElementById("positionSearchInput"),
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

function prettyNameFromEmail(email) {
  const raw = String(email || "").split("@")[0].replace(/[._-]+/g, " ").trim();
  if (!raw) return "";
  return raw
    .split(" ")
    .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
    .join(" ");
}

function displaySalesLead(opp) {
  return opp.sales_lead_name || opp.opp_sales_lead || "Unassigned";
}

function displayHrLead(opp) {
  const email = normalizeText(opp.opp_hr_lead);
  return state.hrLeadDirectory[email] || prettyNameFromEmail(opp.opp_hr_lead) || "Unassigned";
}

function parseDaysRangeValue(value) {
  const clean = String(value || "").trim();
  if (!clean) return { min: null, max: null };
  if (clean.endsWith("+")) {
    const min = parseInt(clean.slice(0, -1), 10);
    return { min: Number.isNaN(min) ? null : min, max: null };
  }
  const parts = clean.split("-").map((part) => parseInt(part, 10));
  const min = Number.isNaN(parts[0]) ? null : parts[0];
  const max = Number.isNaN(parts[1]) ? null : parts[1];
  return { min, max };
}

function daysSince(dateValue) {
  if (!dateValue) return null;
  const d = new Date(dateValue);
  if (Number.isNaN(d.getTime())) return null;
  const today = new Date();
  const diff = Math.ceil((today - d) / (1000 * 60 * 60 * 24)) - 1;
  return Number.isFinite(diff) ? diff : null;
}

async function hydrateSourcingDates(opportunities) {
  const sourcingOpps = opportunities.filter((opp) => opp.opp_stage === "Sourcing");
  if (!sourcingOpps.length) return;
  await Promise.all(
    sourcingOpps.map(async (opp) => {
      try {
        const data = await fetchJSON(
          `${API_BASE}/opportunities/${encodeURIComponent(opp.opportunity_id)}/latest_sourcing_date`
        );
        opp.latest_sourcing_date = data.latest_sourcing_date || null;
      } catch (err) {
        console.warn("Sourcing date fetch failed", err);
      }
    })
  );
}

function computeOppDays(opp) {
  const stage = opp.opp_stage || "";
  if (stage === "Close Win" || stage === "Closed Lost") {
    return daysSince(opp.opp_close_date || opp.nda_signature_or_start_date);
  }
  if (stage === "Sourcing") {
    return daysSince(opp.latest_sourcing_date || opp.nda_signature_or_start_date);
  }
  return daysSince(opp.nda_signature_or_start_date);
}

function buildFilterOptions(opportunities) {
  const stages = new Set();
  const salesLeads = new Set();
  const hrLeads = new Set();
  const types = new Set();

  opportunities.forEach((opp) => {
    if (opp.opp_stage) stages.add(opp.opp_stage);
    if (displaySalesLead(opp)) salesLeads.add(displaySalesLead(opp));
    if (displayHrLead(opp)) hrLeads.add(displayHrLead(opp));
    if (opp.opp_type) types.add(opp.opp_type);
  });

  state.filterOptions = {
    stages: Array.from(stages).sort((a, b) => a.localeCompare(b)),
    salesLeads: Array.from(salesLeads).sort((a, b) => a.localeCompare(b)),
    hrLeads: Array.from(hrLeads).sort((a, b) => a.localeCompare(b)),
    types: Array.from(types).sort((a, b) => a.localeCompare(b)),
  };

  state.filters.stages = new Set(state.filterOptions.stages.map((v) => v.toLowerCase()));
  state.filters.salesLeads = new Set(state.filterOptions.salesLeads.map((v) => v.toLowerCase()));
  state.filters.hrLeads = new Set(state.filterOptions.hrLeads.map((v) => v.toLowerCase()));
  state.filters.types = new Set(state.filterOptions.types.map((v) => v.toLowerCase()));
}

function renderFilterMenu(targetEl, options, stateSet, onChange) {
  if (!targetEl) return;
  targetEl.innerHTML = "";
  const controls = document.createElement("div");
  controls.className = "filter-controls";

  const selectAllBtn = document.createElement("button");
  selectAllBtn.type = "button";
  selectAllBtn.textContent = "Select all";
  selectAllBtn.addEventListener("click", () => {
    stateSet.clear();
    options.forEach((label) => stateSet.add(String(label || "").toLowerCase()));
    renderFilterMenu(targetEl, options, stateSet, onChange);
    onChange();
  });

  const clearBtn = document.createElement("button");
  clearBtn.type = "button";
  clearBtn.textContent = "Clear";
  clearBtn.addEventListener("click", () => {
    stateSet.clear();
    renderFilterMenu(targetEl, options, stateSet, onChange);
    onChange();
  });

  controls.appendChild(selectAllBtn);
  controls.appendChild(clearBtn);
  targetEl.appendChild(controls);

  options.forEach((label) => {
    const option = document.createElement("label");
    option.className = "filter-option";
    const value = String(label || "");
    const key = value.toLowerCase();
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = value;
    input.checked = stateSet.has(key);
    input.addEventListener("change", () => {
      if (input.checked) {
        stateSet.add(key);
      } else {
        stateSet.delete(key);
      }
      onChange();
    });
    option.appendChild(input);
    option.appendChild(document.createTextNode(value));
    targetEl.appendChild(option);
  });
}

function toggleMenu(menuEl) {
  if (!menuEl) return;
  menuEl.classList.toggle("open");
}

function closeAllMenus() {
  document.querySelectorAll(".filter-menu.open").forEach((menu) => menu.classList.remove("open"));
}

function bindFilterMenus() {
  document.querySelectorAll(".filter-toggle").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const filter = button.dataset.filter;
      const map = {
        stage: els.filterStageMenu,
        sales: els.filterSalesMenu,
        hr: els.filterHrMenu,
        type: els.filterTypeMenu,
      };
      const menu = map[filter];
      if (!menu) return;
      const isOpen = menu.classList.contains("open");
      closeAllMenus();
      if (!isOpen) toggleMenu(menu);
    });
  });

  document.addEventListener("click", closeAllMenus);
}

function applyFilters(opportunities) {
  return opportunities.filter((opp) => {
    const stage = String(opp.opp_stage || "").toLowerCase();
    const sales = String(displaySalesLead(opp)).toLowerCase();
    const hr = String(displayHrLead(opp)).toLowerCase();
    const type = String(opp.opp_type || "").toLowerCase();
    const account = String(opp.client_name || "").toLowerCase();
    const position = String(opp.opp_position_name || "").toLowerCase();

    if (state.filters.stages.size && !state.filters.stages.has(stage)) return false;
    if (state.filters.salesLeads.size && !state.filters.salesLeads.has(sales)) return false;
    if (state.filters.hrLeads.size && !state.filters.hrLeads.has(hr)) return false;
    if (state.filters.types.size && !state.filters.types.has(type)) return false;

    if (state.filters.accountText && !account.includes(state.filters.accountText)) return false;
    if (state.filters.positionText && !position.includes(state.filters.positionText)) return false;

    const days = opp._days_since;
    const range = state.filters.daysRange;
    if (range.min != null || range.max != null) {
      if (days == null) return false;
      if (range.min != null && days < range.min) return false;
      if (range.max != null && days > range.max) return false;
    }

    return true;
  });
}

function renderOpportunities(opportunities) {
  const list = applyFilters(opportunities);
  els.opportunitiesBody.innerHTML = "";
  if (!list.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5">No opportunities available.</td>';
    els.opportunitiesBody.appendChild(row);
    return;
  }

  list.forEach((opp) => {
    const row = document.createElement("tr");
    row.dataset.oppId = opp.opportunity_id;
    row.innerHTML = `
      <td>${escapeHtml(opp.opp_position_name || "Untitled")}</td>
      <td>${escapeHtml(opp.client_name || "—")}</td>
      <td>${escapeHtml(opp.opp_stage || "—")}</td>
      <td>${escapeHtml(displayHrLead(opp) || "—")}</td>
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

  await hydrateSourcingDates(list);
  list.forEach((opp) => {
    opp._days_since = computeOppDays(opp);
  });

  let visible = list;
  if (state.isHrLead && email) {
    visible = list.filter((opp) => normalizeText(opp.opp_hr_lead) === email);
    els.hrFilterPill.textContent = "Filter: my HR lead";
  } else {
    els.hrFilterPill.textContent = "Filter: all HR leads";
  }

  state.opportunities = visible;
  buildFilterOptions(visible);
  renderFilterMenu(els.filterStageMenu, state.filterOptions.stages, state.filters.stages, () =>
    renderOpportunities(state.opportunities)
  );
  renderFilterMenu(els.filterSalesMenu, state.filterOptions.salesLeads, state.filters.salesLeads, () =>
    renderOpportunities(state.opportunities)
  );
  renderFilterMenu(els.filterHrMenu, state.filterOptions.hrLeads, state.filters.hrLeads, () =>
    renderOpportunities(state.opportunities)
  );
  renderFilterMenu(els.filterTypeMenu, state.filterOptions.types, state.filters.types, () =>
    renderOpportunities(state.opportunities)
  );
  bindFilterMenus();

  if (els.daysRangeFilter) {
    els.daysRangeFilter.addEventListener("change", () => {
      state.filters.daysRange = parseDaysRangeValue(els.daysRangeFilter.value);
      renderOpportunities(state.opportunities);
    });
  }
  if (els.accountSearchInput) {
    els.accountSearchInput.addEventListener("input", () => {
      state.filters.accountText = normalizeText(els.accountSearchInput.value);
      renderOpportunities(state.opportunities);
    });
  }
  if (els.positionSearchInput) {
    els.positionSearchInput.addEventListener("input", () => {
      state.filters.positionText = normalizeText(els.positionSearchInput.value);
      renderOpportunities(state.opportunities);
    });
  }

  renderOpportunities(visible);
  setOpportunityHint(visible.length ? "Select an opportunity to start." : "No opportunities found.");

  return visible;
}

async function loadRecruiters() {
  try {
    const recruiters = await fetchJSON(`${API_BASE}/users/recruiters`);
    const list = Array.isArray(recruiters) ? recruiters : [];
    const emails = list
      .map((user) => normalizeText(user.email_vintti))
      .filter(Boolean);
    state.isHrLead = emails.includes(state.currentUserEmail);
    state.hrLeadDirectory = list.reduce((acc, user) => {
      const email = normalizeText(user.email_vintti);
      if (email && user.user_name) acc[email] = user.user_name;
      return acc;
    }, {});
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
