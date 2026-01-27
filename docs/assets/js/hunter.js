const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

const companyGrid = document.querySelector("[data-company-grid]");
const industryFilter = document.querySelector("[data-filter-industry]");
const candidateFilter = document.querySelector("[data-filter-candidates]");
const searchInput = document.querySelector("[data-filter-search]");
const clearFilters = document.querySelector("[data-clear-filters]");
const refreshButton = document.querySelector("[data-refresh]");
const emptyState = document.querySelector("[data-empty-state]");
const modalOverlay = document.querySelector("[data-modal-overlay]");
const modalBody = document.querySelector("[data-modal-body]");
const modalClose = document.querySelector("[data-modal-close]");

const candidateRanges = {
  "0-5": (count) => count >= 0 && count <= 5,
  "6-10": (count) => count >= 6 && count <= 10,
  "11-15": (count) => count >= 11 && count <= 15,
  "16-20": (count) => count >= 16 && count <= 20,
  "21+": (count) => count >= 21,
};

let companies = [];

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
  const accounts = safeList(row.accounts).map((value) => String(value));
  const amount = Number(row.amount_candidates);

  return {
    hunterId: row.hunter_id,
    name: row.company || "N/A",
    industry: row.industry || "Uncategorized",
    candidatesCount: Number.isFinite(amount) ? amount : candidates.length,
    candidateIds: candidates,
    accounts,
    linkedin: row.company_linkedin,
  };
};

const setRefreshState = (isLoading) => {
  if (!refreshButton) return;
  refreshButton.disabled = isLoading;
  refreshButton.textContent = isLoading ? "Refreshing..." : "Refresh";
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
    ? company.accounts.map((account) => `<span class="account-pill">${account}</span>`).join("")
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
        <span class="meta-label">Candidates sourced</span>
        <button class="candidate-count" type="button" data-hire-count>
          ${company.candidatesCount}
        </button>
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

const openModal = (company) => {
  modalBody.innerHTML = "";
  const list = document.createElement("div");
  list.className = "modal-list";

  if (!company.candidateIds.length) {
    list.innerHTML = `<div class="modal-row">No candidates yet.</div>`;
  } else {
    list.innerHTML = company.candidateIds
      .map(
        (candidateId) => `
          <div class="modal-row">
            <div class="modal-name">Candidate #${candidateId}</div>
            <a class="modal-role" href="candidate-details.html?id=${encodeURIComponent(candidateId)}" target="_blank" rel="noopener">
              Open profile
            </a>
          </div>
        `
      )
      .join("");
  }

  modalBody.appendChild(list);
  modalOverlay.classList.add("is-visible");
};

const closeModal = () => {
  modalOverlay.classList.remove("is-visible");
};

const matchesFilters = (company) => {
  const searchValue = searchInput.value.trim().toLowerCase();
  const selectedIndustry = industryFilter.value;
  const selectedRange = candidateFilter.value;

  const matchesSearch = company.name.toLowerCase().includes(searchValue);
  const matchesIndustry = selectedIndustry ? company.industry === selectedIndustry : true;
  const matchesCandidates = selectedRange ? candidateRanges[selectedRange](company.candidatesCount) : true;

  return matchesSearch && matchesIndustry && matchesCandidates;
};

const render = () => {
  const filtered = companies.filter(matchesFilters);

  companyGrid.innerHTML = "";
  filtered.forEach((company) => {
    const card = buildCard(company);
    const countButton = card.querySelector("[data-hire-count]");
    countButton.addEventListener("click", () => openModal(company));
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
  candidateFilter.value = "";
  searchInput.value = "";
  render();
};

const loadCompanies = async () => {
  try {
    const rows = await fetchHunterRows();
    companies = rows.map(normalizeRow);
    fillIndustries();
    render();
  } catch (err) {
    console.error("Hunter load failed", err);
    companies = [];
    render();
  }
};

const refreshCompanies = async () => {
  setRefreshState(true);
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
  }
};

loadCompanies();

[industryFilter, candidateFilter].forEach((select) => {
  select.addEventListener("change", render);
});

searchInput.addEventListener("input", render);
clearFilters.addEventListener("click", resetFilters);
if (refreshButton) refreshButton.addEventListener("click", refreshCompanies);

modalOverlay.addEventListener("click", (event) => {
  if (event.target === modalOverlay) {
    closeModal();
  }
});

modalClose.addEventListener("click", closeModal);
