const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";

// 🔸 Correos que NO deben aparecer nunca en el dropdown
const EXCLUDED_EMAILS = new Set([
  "sol@vintti.com",
  "agustin@vintti.com",
  "bahia@vintti.com",
  "agustina.ferrari@vintti.com",
  "jazmin@vintti.com",
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
const RECRUITER_POWER_ALLOWED = new Set([
  "angie@vintti.com",
  "agostina@vintti.com",
  "agustin@vintti.com",
  "lara@vintti.com",
]);

const metricsState = {
  byLead: {},            // { email: { ...metrics } }
  orderedLeadEmails: [], // [ email, email, ... ]
  monthStart: null,
  monthEnd: null,
  currentUserEmail: null,
  rangeStart: null, // YYYY-MM-DD inclusive
  rangeEnd: null,   // YYYY-MM-DD inclusive

};
function isoToYMD(iso) {
  if (!iso) return "";
  return String(iso).slice(0, 10);
}

function showRangeError(msg) {
  const el = document.getElementById("rangeError");
  if (!el) return;
  if (!msg) {
    el.style.display = "none";
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.style.display = "";
}

function setRangeInputs(startYMD, endYMD) {
  const s = document.getElementById("rangeStart");
  const e = document.getElementById("rangeEnd");
  if (s) s.value = startYMD || "";
  if (e) e.value = endYMD || "";
}

// ===== user_id helpers (copiados de Profile, versión mini) =====
function getUidFromQuery() {
  try {
    const q = new URLSearchParams(location.search).get("user_id");
    return q && /^\d+$/.test(q) ? Number(q) : null;
  } catch {
    return null;
  }
}

async function ensureUserIdInURL() {
  let uid = getUidFromQuery();
  if (!uid) uid = Number(localStorage.getItem("user_id")) || null;

  // si existe un resolver global, lo usamos (como en otras páginas)
  if (!uid && typeof window.getCurrentUserId === "function") {
    try {
      uid = await window.getCurrentUserId();
    } catch {
      uid = null;
    }
  }

  if (!uid) {
    console.warn(
      "[recruiter-metrics] No user_id available (no URL, no cache, no resolver)"
    );
    return null;
  }

  localStorage.setItem("user_id", String(uid));

  const url = new URL(location.href);
  if (url.searchParams.get("user_id") !== String(uid)) {
    url.searchParams.set("user_id", String(uid));
    history.replaceState(null, "", url.toString());
  }

  console.debug("[recruiter-metrics] using user_id =", uid);
  return uid;
}

// --- API helper: añade ?user_id= y credentials: 'include'
async function api(path, opts = {}) {
  const url = new URL(API_BASE + path);
  const uid = Number(localStorage.getItem("user_id")) || getUidFromQuery();

  if (uid && !url.searchParams.has("user_id")) {
    url.searchParams.set("user_id", String(uid));
  }

  return fetch(url.toString(), {
    credentials: "include",
    ...opts,
    headers: {
      ...(opts.headers || {}),
    },
  });
}

async function loadCurrentUserEmail() {
  try {
    const resp = await api("/profile/me", { method: "GET" });
    if (!resp.ok) throw new Error(await resp.text());
    const me = await resp.json();

    metricsState.currentUserEmail = (me.email_vintti || "").toLowerCase();
    console.debug(
      "[recruiter-metrics] current user:",
      metricsState.currentUserEmail
    );
  } catch (err) {
    console.warn("[recruiter-metrics] Could not resolve current user email:", err);
    metricsState.currentUserEmail = null;
  }
}
function toggleRecruiterLabButton() {
  const btn = document.getElementById("recruiterLabBtn");
  if (!btn) return;

  const email = (metricsState.currentUserEmail || "").toLowerCase();
  btn.style.display = email && RECRUITER_POWER_ALLOWED.has(email) ? "" : "none";
}
function updateDynamicRangeLabels() {
  const a = document.getElementById("winRangeLabel");
  const b = document.getElementById("lostRangeLabel");
  const c = document.getElementById("convRangeLabel");

  if (!metricsState.rangeStart || !metricsState.rangeEnd) return;

  const txt = "Selected Range";
  if (a) a.textContent = `Closed Win · ${txt}`;
  if (b) b.textContent = `Closed Lost · ${txt}`;
  if (c) c.textContent = `Conversion · ${txt}`;
}

function computeTrend(current, previous, goodWhenHigher = true) {
  if (previous == null) {
    return { label: "–", className: "neutral" };
  }

  const diff = current - previous;

  if (diff === 0) {
    return { label: "same", className: "neutral" };
  }

  const arrow = diff > 0 ? "↑" : "↓";
  const absDiff = Math.abs(diff);

  let isImprovement;
  if (goodWhenHigher) {
    isImprovement = diff > 0;
  } else {
    isImprovement = diff < 0;
  }

  const cls = isImprovement ? "up" : "down";
  const verb = diff > 0 ? "up" : "down";

  // Ejemplos:
  // "↑ up 3"
  // "↓ down 2"
  return {
    label: `${arrow} ${verb} ${absDiff}`,
    className: cls,
  };
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
  const convLifetimeEl = $("#conversionLifetimeValue");

  if (!m) {
    winMonthEl.textContent = "–";
    lostMonthEl.textContent = "–";
    winTotalEl.textContent = "–";
    lostTotalEl.textContent = "–";
    convEl.textContent = "–";
    helperEl.textContent =
      "No data available for this recruiter yet. Keep an eye on new opportunities!";
    if (convLifetimeEl) convLifetimeEl.textContent = "–";
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

  // --- Conversion · Last 30 days (antes “Last 20”) ---
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
      "No closed opportunities in the last 30 days to compute this rate.";
  } else {
    helperEl.textContent = `Selected range: ${wins} Closed Win out of ${total} closed opportunities.`;
  }

  // --- 🌟 NUEVO: Conversion · Lifetime ---
  if (convLifetimeEl) {
    const newConvLifetime = m.conversion_rate_lifetime;
    if (newConvLifetime == null) {
      convLifetimeEl.textContent = "–";
    } else {
      const fromConvLifetime = parsePercentSafe(convLifetimeEl.textContent);
      animateValue(convLifetimeEl, fromConvLifetime, newConvLifetime, {
        duration: 750,
        formatter: (v) => formatPercent(v),
      });
    }
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

  const start = metricsState.rangeStart;
  const end = metricsState.rangeEnd;

  if (!start || !end) {
    el.textContent = "";
    return;
  }

  // start/end son YYYY-MM-DD inclusive
  const [sy, sm, sd] = start.split("-").map(Number);
  const [ey, em, ed] = end.split("-").map(Number);

  const prettyStart = String(sd).padStart(2, "0") + "/" + String(sm).padStart(2, "0") + "/" + sy;
  const prettyEnd = String(ed).padStart(2, "0") + "/" + String(em).padStart(2, "0") + "/" + ey;

  el.textContent = `Selected window: ${prettyStart} — ${prettyEnd}`;
}

async function fetchMetrics(rangeStartYMD = null, rangeEndYMD = null) {
  try {
    showRangeError(null);

    const url = new URL(`${API_BASE}/recruiter-metrics`);
    if (rangeStartYMD && rangeEndYMD) {
      url.searchParams.set("start", rangeStartYMD);
      url.searchParams.set("end", rangeEndYMD);
    }

    const resp = await fetch(url.toString(), {
      credentials: "include",
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.status !== "ok") throw new Error(data.message || "Unexpected response");

    metricsState.monthStart = data.month_start; // exclusivo end viene del backend
    metricsState.monthEnd = data.month_end;

    metricsState.rangeStart = data.range_start || isoToYMD(data.month_start);
    metricsState.rangeEnd = data.range_end || null;

    setRangeInputs(metricsState.rangeStart, metricsState.rangeEnd);

    if (!metricsState.currentUserEmail && data.current_user_email) {
      metricsState.currentUserEmail = data.current_user_email.toLowerCase();
    }

    const byLead = {};
    const emails = [];

    for (const row of data.metrics || []) {
      const email = (row.hr_lead_email || row.hr_lead || "").toLowerCase();
      if (!email) continue;
      if (EXCLUDED_EMAILS.has(email)) continue;
      byLead[email] = row;
      emails.push(email);
    }

    metricsState.byLead = byLead;
    metricsState.orderedLeadEmails = emails;

    populateDropdown();
    updatePeriodInfo();
    updateDynamicRangeLabels();
  } catch (err) {
    console.error("Error loading recruiter metrics:", err);
    showRangeError("Couldn’t load metrics for that range. Try again.");
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
  (async () => {
    const uid = await ensureUserIdInURL();
    if (!uid) {
      await fetchMetrics();
      return;
    }

    await loadCurrentUserEmail(); 
    toggleRecruiterLabButton(); 
    await fetchMetrics();    
    function wireRangePicker() {
  const btn = document.getElementById("applyRangeBtn");
  const s = document.getElementById("rangeStart");
  const e = document.getElementById("rangeEnd");
  if (!btn || !s || !e) return;

  btn.addEventListener("click", async () => {
    const start = (s.value || "").trim();
    const end = (e.value || "").trim();

    if (!start || !end) {
      showRangeError("Pick both start and end dates.");
      return;
    }
    if (end < start) {
      showRangeError("End date must be after start date.");
      return;
    }

    metricsState.rangeStart = start;
    metricsState.rangeEnd = end;

    await fetchMetrics(start, end);

    // si ya hay recruiter seleccionado, refrescamos cards con el mismo
    const sel = document.getElementById("hrLeadSelect");
    if (sel && sel.value) updateCardsForLead(sel.value);
  });
}    
wireRangePicker();
  })();
});
