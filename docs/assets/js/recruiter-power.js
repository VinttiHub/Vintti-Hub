const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
const metricsState = {
  byLead: {}, // { hr_lead: { ...metrics } }
  orderedLeads: [],
  monthStart: null,
  monthEnd: null,
};

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

function updateCardsForLead(hrLead) {
  const m = metricsState.byLead[hrLead];

  const winMonthEl = $("#closedWinMonthValue");
  const lostMonthEl = $("#closedLostMonthValue");
  const winTotalEl = $("#closedWinTotalValue");
  const lostTotalEl = $("#closedLostTotalValue");
  const convEl = $("#conversionRateValue");
  const helperEl = $("#conversionHelper");

  if (!m) {
    winMonthEl.textContent = "–";
    lostMonthEl.textContent = "–";
    winTotalEl.textContent = "–";
    lostTotalEl.textContent = "–";
    convEl.textContent = "–";
    helperEl.textContent =
      "No data available for this recruiter yet. Keep an eye on new opportunities!";
    return;
  }

  winMonthEl.textContent = m.closed_win_month ?? 0;
  lostMonthEl.textContent = m.closed_lost_month ?? 0;
  winTotalEl.textContent = m.closed_win_total ?? 0;
  lostTotalEl.textContent = m.closed_lost_total ?? 0;

  convEl.textContent = formatPercent(m.conversion_rate_last_20);

  const total = m.last_20_count ?? 0;
  const wins = m.last_20_win ?? 0;
  if (total === 0) {
    helperEl.textContent =
      "No closed opportunities yet to compute the last 20 conversion rate.";
  } else {
    helperEl.textContent = `Last 20 closed opportunities: ${wins} Closed Win out of ${total}.`;
  }
}

function populateDropdown() {
  const select = $("#hrLeadSelect");
  select.innerHTML = "";

  // Option placeholder
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "Select recruiter…";
  defaultOpt.disabled = true;
  defaultOpt.selected = true;
  select.appendChild(defaultOpt);

  metricsState.orderedLeads.forEach((lead) => {
    const opt = document.createElement("option");
    opt.value = lead;
    opt.textContent = lead;
    select.appendChild(opt);
  });

  select.addEventListener("change", (ev) => {
    const hrLead = ev.target.value;
    updateCardsForLead(hrLead);
  });
}

function updatePeriodInfo() {
  const el = $("#periodInfo");
  if (!el) return;
  const { monthStart, monthEnd } = metricsState;
  if (!monthStart || !monthEnd) {
    el.textContent = "";
    return;
  }
  const prettyStart = formatDateISO(monthStart);
  const prettyEnd = formatDateISO(monthEnd);
  el.textContent = `Current month period: ${prettyStart} — ${prettyEnd} (opp_close_date in this range).`;
}

async function fetchMetrics() {
  try {
    const resp = await fetch(`${API_BASE}/recruiter-metrics`);
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    const data = await resp.json();
    if (data.status !== "ok") {
      throw new Error(data.message || "Unexpected response");
    }

    metricsState.monthStart = data.month_start;
    metricsState.monthEnd = data.month_end;

    const byLead = {};
    const leads = [];
    for (const row of data.metrics || []) {
      const lead = row.hr_lead || "Unassigned";
      byLead[lead] = row;
      leads.push(lead);
    }

    metricsState.byLead = byLead;
    metricsState.orderedLeads = leads.sort((a, b) =>
      a.localeCompare(b, undefined, { sensitivity: "base" })
    );

    populateDropdown();
    updatePeriodInfo();
  } catch (err) {
    console.error("Error loading recruiter metrics:", err);
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

document.addEventListener("DOMContentLoaded", () => {
  fetchMetrics();
});
