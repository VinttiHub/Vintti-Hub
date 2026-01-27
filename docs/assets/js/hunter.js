const companies = [
  {
    name: "AtlasPay",
    industry: "Fintech",
    candidates: 12,
    accounts: ["Luna L.", "Dario K.", "Mati G."],
    linkedin: "https://www.linkedin.com/company/atlaspay",
    location: "New York, NY",
    signal: "Elephant herd spotted: finance ops + data.",
  },
  {
    name: "Northwind Logistics",
    industry: "Logistics",
    candidates: 7,
    accounts: ["Camila R.", "Josefina M."],
    linkedin: "https://www.linkedin.com/company/northwind-logistics",
    location: "Chicago, IL",
    signal: "Zebra stampede of ops roles.",
  },
  {
    name: "BluePeak Health",
    industry: "Healthtech",
    candidates: 18,
    accounts: ["Paz S.", "Juliana B.", "Lara T."],
    linkedin: "https://www.linkedin.com/company/bluepeak-health",
    location: "Austin, TX",
    signal: "Lion pride: clinical ops growth.",
  },
  {
    name: "Crimson Harbor",
    industry: "Retail",
    candidates: 5,
    accounts: ["Agus L."],
    linkedin: "https://www.linkedin.com/company/crimson-harbor",
    location: "Miami, FL",
    signal: "Gazelle sprint into LATAM retail.",
  },
  {
    name: "Lumen Arcade",
    industry: "Gaming",
    candidates: 9,
    accounts: ["Felipe N.", "Angie D."],
    linkedin: "https://www.linkedin.com/company/lumen-arcade",
    location: "Seattle, WA",
    signal: "Playful pack forming two squads.",
  },
  {
    name: "Nimbus Freight",
    industry: "Logistics",
    candidates: 21,
    accounts: ["Julieta P.", "Constanza V.", "Mariano F."],
    linkedin: "https://www.linkedin.com/company/nimbus-freight",
    location: "Dallas, TX",
    signal: "Rhino-sized hunt for leads + BI.",
  },
  {
    name: "VerdeCraft",
    industry: "Sustainability",
    candidates: 6,
    accounts: ["Agustina V.", "Pilar A."],
    linkedin: "https://www.linkedin.com/company/verdecrafthq",
    location: "Denver, CO",
    signal: "Green corridor: growth backfills.",
  },
  {
    name: "Cobalt Studios",
    industry: "Media",
    candidates: 14,
    accounts: ["Jaz L.", "Mora S."],
    linkedin: "https://www.linkedin.com/company/cobalt-studios",
    location: "Los Angeles, CA",
    signal: "Creative safari, fresh tracks.",
  },
];

const companyGrid = document.querySelector("[data-company-grid]");
const industryFilter = document.querySelector("[data-filter-industry]");
const candidateFilter = document.querySelector("[data-filter-candidates]");
const searchInput = document.querySelector("[data-filter-search]");
const clearFilters = document.querySelector("[data-clear-filters]");
const summaryCount = document.querySelector("[data-summary-count]");
const summaryCandidates = document.querySelector("[data-summary-candidates]");
const emptyState = document.querySelector("[data-empty-state]");

const candidateRanges = {
  "0-5": (count) => count >= 0 && count <= 5,
  "6-10": (count) => count >= 6 && count <= 10,
  "11-15": (count) => count >= 11 && count <= 15,
  "16-20": (count) => count >= 16 && count <= 20,
  "21+": (count) => count >= 21,
};

const buildCard = (company) => {
  const card = document.createElement("article");
  card.className = "company-card";

  card.innerHTML = `
    <div class="card-top">
      <div>
        <h3 class="company-name">${company.name}</h3>
        <div class="signal">${company.location}</div>
      </div>
      <div class="industry-chip">${company.industry}</div>
    </div>
    <div class="card-meta">
      <div class="meta-row">
        <span class="meta-label">Candidates hunted</span>
        <span class="candidate-count">${company.candidates}</span>
      </div>
      <div class="meta-row">
        <span class="meta-label">Vintti accounts</span>
      </div>
      <div class="account-list">
        ${company.accounts.map((account) => `<span class="account-pill">${account}</span>`).join("")}
      </div>
      <div class="signal">${company.signal}</div>
    </div>
    <div class="card-actions">
      <a class="linkedin-btn" href="${company.linkedin}" target="_blank" rel="noopener">
        <img src="./assets/img/linkedin.png" alt="LinkedIn" />
        Open LinkedIn
      </a>
      <span class="signal">Last tracks: today</span>
    </div>
  `;

  return card;
};

const matchesFilters = (company) => {
  const searchValue = searchInput.value.trim().toLowerCase();
  const selectedIndustry = industryFilter.value;
  const selectedRange = candidateFilter.value;

  const matchesSearch = company.name.toLowerCase().includes(searchValue);
  const matchesIndustry = selectedIndustry ? company.industry === selectedIndustry : true;
  const matchesCandidates = selectedRange ? candidateRanges[selectedRange](company.candidates) : true;

  return matchesSearch && matchesIndustry && matchesCandidates;
};

const render = () => {
  const filtered = companies.filter(matchesFilters);

  companyGrid.innerHTML = "";
  filtered.forEach((company) => companyGrid.appendChild(buildCard(company)));

  summaryCount.textContent = filtered.length;
  summaryCandidates.textContent = filtered.reduce((sum, company) => sum + company.candidates, 0);

  emptyState.style.display = filtered.length ? "none" : "block";
};

const fillIndustries = () => {
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

fillIndustries();
render();

[industryFilter, candidateFilter].forEach((select) => {
  select.addEventListener("change", render);
});

searchInput.addEventListener("input", render);
clearFilters.addEventListener("click", resetFilters);
