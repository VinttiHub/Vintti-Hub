const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

const companyGrid = document.querySelector("[data-company-grid]");
const industryFilter = document.querySelector("[data-filter-industry]");
const searchInput = document.querySelector("[data-filter-search]");
const clearFilters = document.querySelector("[data-clear-filters]");
const refreshButton = document.querySelector("[data-refresh]");
const emptyState = document.querySelector("[data-empty-state]");
const refreshOverlay = document.querySelector("[data-refresh-overlay]");
const refreshBar = document.querySelector("[data-refresh-bar]");
const refreshText = document.querySelector("[data-refresh-text]");
const refreshStatus = document.querySelector("[data-refresh-status]");

let companies = [];
let refreshInterval = null;
let refreshProgress = 0;
let statusInterval = null;
let statusIndex = 0;

const refreshStatuses = [
  "Loading companies...",
  "Looking up LinkedIn...",
  "Classifying industries...",
  "Mapping company trails...",
];

if (refreshOverlay) {
  refreshOverlay.hidden = true;
}

const safeList = (value) => {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed) return [];
    try {
      const parsed = JSON.parse(trimmed);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return trimmed.split(",").map((item) => item.trim()).filter(Boolean);
    }
  }
  return [];
};

const normalizeRow = (row) => {
  const candidates = safeList(row.candidates)
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  const candidateDetails = safeList(row.candidate_details)
    .map((item) => {
      if (item && typeof item === "object") {
        const id = Number(item.id ?? item.candidate_id);
        return {
          id,
          name: item.name ? String(item.name) : null,
          position: item.position ? String(item.position) : null,
        };
      }
      return { id: Number(item), name: null, position: null };
    })
    .filter((item) => Number.isFinite(item.id));
  const candidateProfiles = candidateDetails.length
    ? candidateDetails
    : candidates.map((id) => ({ id, name: null, position: null }));
  const accountDetails = safeList(row.account_details)
    .map((item) => {
      if (item && typeof item === "object") {
        const id = Number(item.id ?? item.account_id);
        return {
          id,
          name: item.name ? String(item.name) : null,
        };
      }
      return { id: Number(item), name: null };
    })
    .filter((item) => Number.isFinite(item.id));
  const accounts = accountDetails.length
    ? accountDetails
    : safeList(row.accounts)
        .map((value) => ({ id: Number(value), name: null }))
        .filter((item) => Number.isFinite(item.id));
  const amount = Number(row.amount_candidates);

  return {
    hunterId: row.hunter_id,
    name: row.company || "N/A",
    industry: row.industry || "Uncategorized",
    candidatesCount: Number.isFinite(amount) ? amount : candidates.length,
    candidateIds: candidates,
    candidateProfiles,
    accounts,
    linkedin: row.company_linkedin,
  };
};

const setRefreshState = (isLoading) => {
  if (!refreshButton) return;
  refreshButton.disabled = isLoading;
  refreshButton.textContent = isLoading ? "Refreshing..." : "Refresh";
};

const showRefreshOverlay = () => {
  if (!refreshOverlay || !refreshBar || !refreshText) return;
  refreshOverlay.hidden = false;
  refreshProgress = 0;
  refreshBar.style.width = "0%";
  refreshText.textContent = "0%";
  statusIndex = 0;
  if (refreshStatus) {
    refreshStatus.textContent = refreshStatuses[statusIndex];
  }

  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(() => {
    refreshProgress = Math.min(95, refreshProgress + Math.random() * 8 + 3);
    refreshBar.style.width = `${Math.round(refreshProgress)}%`;
    refreshText.textContent = `${Math.round(refreshProgress)}%`;
  }, 320);

  if (statusInterval) clearInterval(statusInterval);
  statusInterval = setInterval(() => {
    statusIndex = (statusIndex + 1) % refreshStatuses.length;
    if (refreshStatus) {
      refreshStatus.textContent = refreshStatuses[statusIndex];
    }
  }, 2000);
};

const hideRefreshOverlay = () => {
  if (!refreshOverlay || !refreshBar || !refreshText) return;
  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = null;
  if (statusInterval) clearInterval(statusInterval);
  statusInterval = null;
  refreshProgress = 100;
  refreshBar.style.width = "100%";
  refreshText.textContent = "100%";

  setTimeout(() => {
    refreshOverlay.hidden = true;
  }, 350);
};

const fetchHunterRows = async () => {
  const res = await fetch(`${API_BASE}/hunter`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error("Failed to load hunter data");
  }
  const data = await res.json();
  return Array.isArray(data.rows) ? data.rows : [];
};

const refreshHunterRows = async () => {
  const res = await fetch(`${API_BASE}/hunter/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source: "hunter-ui" }),
  });
  if (!res.ok) {
    throw new Error("Failed to refresh hunter data");
  }
  const data = await res.json();
  return Array.isArray(data.rows) ? data.rows : [];
};

const buildCard = (company) => {
  const card = document.createElement("article");
  card.className = "company-card";

  const accountsMarkup = company.accounts.length
    ? company.accounts
        .map((account) => {
          const label = account.name || `Account #${account.id}`;
          return `<span class="account-pill">${label}</span>`;
        })
        .join("")
    : `<span class="account-pill">N/A</span>`;

  const linkedinMarkup = company.linkedin
    ? `<a class="linkedin-btn" href="${company.linkedin}" target="_blank" rel="noopener">\
        <img src="./assets/img/linkedin.png" alt="LinkedIn" />\
        Open LinkedIn\
      </a>`
    : `<span class="linkedin-btn is-disabled">\
        <img src="./assets/img/linkedin.png" alt="LinkedIn" />\
        LinkedIn unavailable\
      </span>`;

  card.innerHTML = `
    <div class="card-top">
      <div>
        <h3 class="company-name">${company.name}</h3>
        <div class="signal">Hunter #${company.hunterId ?? "N/A"}</div>
      </div>
      <div class="industry-chip">${company.industry}</div>
    </div>
    <div class="card-meta">
      <div class="meta-stack">
        <span class="meta-label">Candidates hired</span>
        <button class="candidate-toggle" type="button" data-candidate-toggle aria-expanded="false" aria-controls="candidate-panel-${company.hunterId}">
          <span class="candidate-count">${company.candidatesCount}</span>
          <span class="candidate-arrow" aria-hidden="true">▾</span>
        </button>
      </div>
      <div class="candidate-panel" id="candidate-panel-${company.hunterId}" data-candidate-panel hidden>
        ${renderCandidatePanel(company)}
      </div>
      <div class="meta-row">
        <span class="meta-label">Vintti clients</span>
      </div>
      <div class="account-list">
        ${accountsMarkup}
      </div>
    </div>
    <div class="card-actions">
      ${linkedinMarkup}
    </div>
  `;

  return card;
};

const renderCandidatePanel = (company) => {
  if (!company.candidateProfiles.length) {
    return `<div class="candidate-empty">No candidates yet.</div>`;
  }

  return company.candidateProfiles
    .map((candidate) => {
      const name = candidate.name || `Candidate #${candidate.id}`;
      const position = candidate.position || "Role not set";
      return `
        <div class="candidate-row">
          <div class="candidate-info">
            <div class="candidate-name">${name}</div>
            <div class="candidate-position">${position}</div>
          </div>
          <a class="candidate-link" href="candidate-details.html?id=${encodeURIComponent(candidate.id)}" target="_blank" rel="noopener">
            Open profile
          </a>
        </div>
      `;
    })
    .join("");
};

const matchesFilters = (company) => {
  const searchValue = searchInput.value.trim().toLowerCase();
  const selectedIndustry = industryFilter.value;

  const matchesSearch = company.name.toLowerCase().includes(searchValue);
  const matchesIndustry = selectedIndustry ? company.industry === selectedIndustry : true;

  return matchesSearch && matchesIndustry;
};

const render = () => {
  const filtered = companies
    .filter(matchesFilters)
    .sort((a, b) => {
      if (b.candidatesCount !== a.candidatesCount) {
        return b.candidatesCount - a.candidatesCount;
      }
      return a.name.localeCompare(b.name);
    });

  companyGrid.innerHTML = "";
  filtered.forEach((company) => {
    const card = buildCard(company);
    const toggleButton = card.querySelector("[data-candidate-toggle]");
    const panel = card.querySelector("[data-candidate-panel]");
    if (toggleButton && panel) {
      toggleButton.addEventListener("click", () => {
        const isExpanded = toggleButton.getAttribute("aria-expanded") === "true";
        toggleButton.setAttribute("aria-expanded", String(!isExpanded));
        panel.hidden = isExpanded;
        card.classList.toggle("is-open", !isExpanded);
      });
    }
    companyGrid.appendChild(card);
  });

  emptyState.style.display = filtered.length ? "none" : "block";
};

const fillIndustries = () => {
  const keep = industryFilter.querySelector("option[value='']");
  industryFilter.innerHTML = "";
  if (keep) industryFilter.appendChild(keep);

  const industries = Array.from(new Set(companies.map((company) => company.industry))).sort();
  industries.forEach((industry) => {
    const option = document.createElement("option");
    option.value = industry;
    option.textContent = industry;
    industryFilter.appendChild(option);
  });
};

const resetFilters = () => {
  industryFilter.value = "";
  searchInput.value = "";
  render();
};

const loadCompanies = async () => {
  showRefreshOverlay();
  try {
    const rows = await fetchHunterRows();
    companies = rows.map(normalizeRow);
    fillIndustries();
    render();
  } catch (err) {
    console.error("Hunter load failed", err);
    companies = [];
    render();
  } finally {
    hideRefreshOverlay();
  }
};

const refreshCompanies = async () => {
  setRefreshState(true);
  showRefreshOverlay();
  try {
    const rows = await refreshHunterRows();
    companies = rows.map(normalizeRow);
    fillIndustries();
    render();
  } catch (err) {
    console.error("Hunter refresh failed", err);
    alert("Failed to refresh hunter data. Please try again.");
  } finally {
    setRefreshState(false);
    hideRefreshOverlay();
  }
};

loadCompanies();

[industryFilter].forEach((select) => {
  select.addEventListener("change", render);
});

searchInput.addEventListener("input", render);
clearFilters.addEventListener("click", resetFilters);
if (refreshButton) refreshButton.addEventListener("click", refreshCompanies);
