const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

// 🔸 Correos que NO deben aparecer nunca en el dropdown
const EXCLUDED_EMAILS = new Set([
  "sol@vintti.com",
  "agustin@vintti.com",
  "bahia@vintti.com",
  "agustina.ferrari@vintti.com",
]);

// 🔸 Personas que sólo deben ver SU propia opción
const RESTRICTED_EMAILS = new Set([
  "agustina.barbero@vintti.com",
  "constanza@vintti.com",
  "pilar@vintti.com",
  "pilar.fernandez@vintti.com",
  "agostina@vintti.com",
  "julieta@vintti.com",
]);

const metricsState = {
  byLead: {},            // { email: { ...metrics } }
  orderedLeadEmails: [], // [ email, email, ... ]
  monthStart: null,
  monthEnd: null,
  currentUserEmail: null,
};

function computeTrend(current, previous, goodWhenHigher = true) {
  if (previous == null || previous === 0) {
    return { label: "–", className: "neutral" };
  }

  const diff = current - previous;
  const pct = Math.round((diff / previous) * 100);

  if (pct === 0) {
    return { label: "→ 0%", className: "neutral" };
  }

  const arrow = pct > 0 ? "↑" : "↓";
  const absPct = Math.abs(pct);

  // 👉 “mejora” depende de si es mejor que suba o que baje
  let isImprovement;
  if (goodWhenHigher) {
    // ejemplo: Closed Win → más es mejor
    isImprovement = pct > 0;
  } else {
    // ejemplo: Closed Lost → menos es mejor
    isImprovement = pct < 0;
  }

  const cls = isImprovement ? "up" : "down";

  return { label: `${arrow} ${absPct}%`, className: cls };
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
function getLeadLabel(email) {
  const row = metricsState.byLead[email];
  if (!row) return email;
  return row.hr_lead_name || row.hr_lead || email;
}

/* 🌟 NUEVO: helpers de animación numérica */
function parseIntSafe(text) {
  const n = parseInt(String(text).replace(/[^\d-]/g, ""), 10);
  return Number.isNaN(n) ? 0 : n;
}

function parsePercentSafe(text) {
  const n = parseFloat(String(text).replace("%", "").trim());
  if (Number.isNaN(n)) return 0;
  return n / 100; // lo devolvemos como 0–1
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

function updateCardsForLead(hrLeadEmail) {
  const m = metricsState.byLead[hrLeadEmail];

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

  /* 🌟 NUEVO: animamos los números en vez de cambiarlos brusco */

  // --- Closed Win · This Month ---
  const newWinMonth = m.closed_win_month ?? 0;
  const fromWinMonth = parseIntSafe(winMonthEl.textContent);
  animateValue(winMonthEl, fromWinMonth, newWinMonth, {
    formatter: (v) => Math.round(v),
  });

  // --- Closed Lost · This Month ---
  const newLostMonth = m.closed_lost_month ?? 0;
  const fromLostMonth = parseIntSafe(lostMonthEl.textContent);
  animateValue(lostMonthEl, fromLostMonth, newLostMonth, {
    formatter: (v) => Math.round(v),
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
  const fromWinTotal = parseIntSafe(winTotalEl.textContent);
  animateValue(winTotalEl, fromWinTotal, newWinTotal, {
    formatter: (v) => Math.round(v),
  });

  // --- Total Closed Lost ---
  const newLostTotal = m.closed_lost_total ?? 0;
  const fromLostTotal = parseIntSafe(lostTotalEl.textContent);
  animateValue(lostTotalEl, fromLostTotal, newLostTotal, {
    formatter: (v) => Math.round(v),
  });

  // --- Conversion · Last 20 ---
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
    helperEl.textContent =
      "No closed opportunities yet to compute the last 20 conversion rate.";
  } else {
    helperEl.textContent = `Last 20 closed opportunities: ${wins} Closed Win out of ${total}.`;
  }

  // ✨ pequeño “glow” en todas las cards cuando cambian
  animateCardsFlash();
}

function populateDropdown() {
  const select = $("#hrLeadSelect");
  if (!select) return;

  select.innerHTML = "";

  // Option placeholder
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "Select recruiter…";
  defaultOpt.disabled = true;
  defaultOpt.selected = true;
  select.appendChild(defaultOpt);

  let emails = metricsState.orderedLeadEmails.slice();
  const currentEmail = (metricsState.currentUserEmail || "").toLowerCase();

  // 🔒 Si el usuario está en la lista restringida, sólo ve su propia opción
  if (currentEmail && RESTRICTED_EMAILS.has(currentEmail)) {
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

  // Si es usuario restringido y su opción existe, la seleccionamos por defecto
  if (currentEmail && RESTRICTED_EMAILS.has(currentEmail)) {
    const ownOption = [...select.options].find(
      (o) => o.value.toLowerCase() === currentEmail
    );
    if (ownOption) {
      ownOption.selected = true;
      defaultOpt.disabled = true;
      defaultOpt.hidden = true;
      updateCardsForLead(ownOption.value);
    }
  }

  select.addEventListener("change", (ev) => {
    const hrLeadEmail = ev.target.value;
    updateCardsForLead(hrLeadEmail);
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
  el.textContent = `Current month period: ${prettyStart} — ${prettyEnd}`;
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
    metricsState.currentUserEmail = data.current_user_email || null;

    const byLead = {};
    const emails = [];

    for (const row of data.metrics || []) {
      // soporte backward: si no viniera hr_lead_email usamos hr_lead
      const email = (row.hr_lead_email || row.hr_lead || "").toLowerCase();
      if (!email) continue;

      // ⛔ excluir ciertos correos del dropdown
      if (EXCLUDED_EMAILS.has(email)) continue;

      byLead[email] = row;
      emails.push(email);
    }

    metricsState.byLead = byLead;
    metricsState.orderedLeadEmails = emails;

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
