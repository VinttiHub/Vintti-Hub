const API_BASE = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
const recruiterNameByEmail = {};
let recruiterDirectory = [];

async function loadRecruiters() {
  try {
    const res = await fetch(`${API_BASE}/users/recruiters`, { credentials: "include" });
    if (!res.ok) throw new Error(`Recruiter list failed: ${res.status}`);
    const data = await res.json();
    return (Array.isArray(data) ? data : [])
      .filter((u) => u?.email_vintti)
      .map((u) => ({
        email: String(u.email_vintti).trim().toLowerCase(),
        name: u.user_name || u.email_vintti,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch (err) {
    console.error("Error loading recruiters:", err);
    return [];
  }
}

function recruiterLabel(email) {
  const key = String(email || "").trim().toLowerCase();
  return recruiterNameByEmail[key] || email || "";
}

document.addEventListener("DOMContentLoaded", async () => {
  const stages = ["Negotiating", "Interviewing", "Sourcing", "Deep Dive", "NDA Sent"];
  const tbody = document.querySelector("#summaryTable tbody");
  tbody.innerHTML = "";

  recruiterDirectory = await loadRecruiters();
  recruiterDirectory.forEach(({ email, name }) => {
    recruiterNameByEmail[email] = name;
    const tr = document.createElement("tr");
    tr.dataset.email = email;
    const td = document.createElement("td");
    td.textContent = name;
    tr.appendChild(td);
    tbody.appendChild(tr);
  });

  if (!recruiterDirectory.length) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      '<td colspan="7" style="text-align:center;">No recruiters available. Create one from the Admin panel.</td>';
    tbody.appendChild(tr);
  }

  // ——— Etiquetar headers por stage para estilos por-columna
(function colorizeStageHeaders() {
  const emojiMap = {
    'Negotiating':'🤝', 'Interviewing':'🎤', 'Sourcing':'🧭', 'Deep Dive':'🔎', 'NDA Sent':'📝'
  };
  const toSlug = (s) => s.toLowerCase().replace(/[^a-z]+/g, "-").replace(/(^-+|-+$)/g, "");
  document.querySelectorAll("#summaryTable thead th").forEach((th) => {
    const label = th.textContent.trim();
    if (!stages.includes(label)) return;
    const slug = toSlug(label);
    th.classList.add("stage-title", `stage-title-${slug}`);
    // 🔹 Forzamos contenido visible (emoji + texto) en el header
    th.innerHTML = `<span class="stage-emoji" aria-hidden="true">${emojiMap[label] || ''}</span><span class="stage-label">${label}</span>`;
  });
})();

  // ——— Estructura de contadores
  const summaryCounts = {};
  recruiterDirectory.forEach(({ email }) => {
    summaryCounts[email] = {};
    stages.forEach((stage) => (summaryCounts[email][stage] = 0));
  });

  if (recruiterDirectory.length) {
    try {
      const res = await fetch(`${API_BASE}/opportunities/light`);
      const opportunities = await res.json();

      opportunities.forEach((opp) => {
        const hrLead = String(opp.opp_hr_lead || "").trim().toLowerCase();
        const stage = String(opp.opp_stage || "").trim();
        if (summaryCounts[hrLead] && stages.includes(stage)) {
          summaryCounts[hrLead][stage]++;
        }
      });

      document.querySelectorAll("#summaryTable tbody tr").forEach((row) => {
        const email = row.getAttribute("data-email");
        if (!email) return;
        while (row.children.length > 1) row.removeChild(row.lastChild);

        let rowTotal = 0;
        stages.forEach((stage) => {
          const val = Number(summaryCounts[email][stage] || 0);
          rowTotal += val;
          const cell = document.createElement("td");
          cell.textContent = String(val);
          row.appendChild(cell);
        });

        const totalTd = document.createElement("td");
        totalTd.className = "total-cell";
        totalTd.textContent = String(rowTotal);
        row.appendChild(totalTd);
        const tableEl = document.getElementById("summaryTable");
        updateColumnTotals(stages, tableEl);
      });
    } catch (err) {
      console.error("❌ Error al cargar oportunidades:", err);
    }
  }

  // ——— Last updated
  const lastUpdatedDiv = document.getElementById("lastUpdated");
  const now = new Date();
  const formattedDate = now.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  const formattedTime = now.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
  lastUpdatedDiv.textContent = `Last updated: ${formattedDate} at ${formattedTime} — refresh the page to get the latest numbers.`;

  // ——— Cargar datos para desglose por prioridad en click
let oppsCache = null;
let accountsCache = null;

async function ensureCaches() {
  if (!oppsCache || !accountsCache) {
    const [oppsRes, accountsRes] = await Promise.all([
      fetch(`${API_BASE}/opportunities/light`),
      // 🔄 Importante: /data (completo) trae account.priority
      fetch(`${API_BASE}/data`),
    ]);
    oppsCache = await oppsRes.json();
    accountsCache = await accountsRes.json();
  }
}

  function accountNameFor(opp){
  // Si /opportunities/light ya trae el nombre del cliente, úsalo
  if (opp?.client_name) return opp.client_name;

  // Fallback: resuelve por account_id desde /data/light
  const byId = {};
  (accountsCache || []).forEach(a => {
    if (a?.account_id) byId[a.account_id] = a.client_name;
  });
  return byId[opp?.account_id] || '—';
}

// ID robusto para navegar al detalle
function getOpportunityId(o){
  return o?.opportunity_id ?? o?.opp_id ?? o?.id ?? o?.oppId ?? null;
}

const OPPORTUNITY_DETAILS_PATH = '/opportunity-detail.html';
function goToOpportunity(oppId){
  if (!oppId) return;
  window.location.href = `${OPPORTUNITY_DETAILS_PATH}?id=${encodeURIComponent(oppId)}`;
}

let selectedCell = null;

function stageBadge(stage){
  const keyMap = {
    'Negotiating': 'neg',
    'Interviewing': 'int',
    'Sourcing': 'src',
    'Deep Dive': 'dd',
    'NDA Sent': 'nda'
  };
  const emoji = {
    'Negotiating':'🤝', 'Interviewing':'🎤', 'Sourcing':'🧭', 'Deep Dive':'🔎', 'NDA Sent':'📝'
  }[stage] || '';
  const k = keyMap[stage] || 'int';
  return `<span class="dd-badge dd-badge-${k}">${emoji} ${stage}</span>`;
}

function renderDrilldown(hrEmail, stage, opps){
  const w = document.getElementById('drilldownWrapper');
  const title = document.getElementById('drilldownTitle');
  const sub = document.getElementById('drilldownSubtitle');
  const tbody = document.querySelector('#drilldownTable tbody');
  const empty = document.getElementById('drilldownEmpty');

  const hrName = (recruiterLabel(hrEmail) || hrEmail || '').split('@')[0];
  title.innerHTML = `Opportunities — <strong>${hrName}</strong> · ${stageBadge(stage)}`;
  sub.textContent = `${opps.length} related`;

  tbody.innerHTML = '';
  if (!opps.length){ empty.classList.remove('hidden'); w.classList.remove('hidden'); return; }
  empty.classList.add('hidden');

  opps.sort((a,b) => (accountNameFor(a) || '').localeCompare(accountNameFor(b) || ''));

  opps.forEach(opp => {
    const tr = document.createElement('tr');
    tr.className = 'dd-row';
    tr.innerHTML = `
      <td class="dd-position">
        <span class="dd-title">${opp.opp_position_name || '—'}</span>
      </td>
      <td class="dd-account">
        <span>${accountNameFor(opp)}</span>
      </td>
    `;
    tr.addEventListener('click', () => goToOpportunity(getOpportunityId(opp)));
    tbody.appendChild(tr);
  });

  w.classList.remove('hidden');
}


document.getElementById('drilldownClose')?.addEventListener('click', () => {
  document.getElementById('drilldownWrapper')?.classList.add('hidden');
  selectedCell?.classList.remove('is-selected');
  selectedCell = null;
});

  // ——— Solo permitir click en celdas numéricas (no la primera col)
  const table = document.getElementById("summaryTable");

table.addEventListener("click", async (evt) => {
  const cell = evt.target.closest("td");
  if (!cell) return;

  const row = cell.parentElement;
  const isFirstCol = cell.cellIndex === 0;
  const isNumber = !isNaN(parseInt(cell.textContent, 10));

  // Evitar clic en la columna Total (última)
  const isLastCol = cell.cellIndex === (stages.length /*5*/ + 1);
  if (isFirstCol || isLastCol || !isNumber) return;

  // Solo números, no la primera columna
  if (isFirstCol || !isNumber) return;

  // Toggle si clickean la misma celda
  if (selectedCell === cell) {
    cell.querySelector(".priority-breakdown")?.remove();
    document.getElementById('drilldownWrapper')?.classList.add('hidden');
    cell.classList.remove('is-selected');
    selectedCell = null;
    return;
  }

  // Limpia chips previos y selección previa
  document.querySelectorAll("#summaryTable .priority-breakdown").forEach(n => n.remove());
  document.querySelectorAll("#summaryTable td.is-selected").forEach(c => c.classList.remove('is-selected'));

  // Stage según columna, y HR seleccionado (fila)
  const stage = stages[cell.cellIndex - 1];
  const hrEmail = row.getAttribute("data-email");

  await ensureCaches();

// Mapa account_id -> prioridad (A/B/C) tomado de /data
const priorityMap = {};
(accountsCache || []).forEach((acc) => {
  const id = acc?.account_id;
  let pr = (acc?.priority || '').toString().trim().toUpperCase();
  // Solo aceptamos A/B/C; cualquier otro valor se ignora
  if (!['A','B','C'].includes(pr)) pr = null;
  if (id) priorityMap[id] = pr;
});


  // Filtro por HR Lead + Stage
const filteredOpps = (oppsCache || []).filter((o) =>
  String(o?.opp_hr_lead || '').trim().toLowerCase() === hrEmail &&
  String(o?.opp_stage   || '').trim() === stage
);


  // Recalcular contadores por prioridad (A/B/C)
  const counts = { A: 0, B: 0, C: 0 };
  filteredOpps.forEach((opp) => {
    const prio = priorityMap[opp.account_id] || "N/A";
    if (counts[prio] !== undefined) counts[prio]++;
  });

  // Insertar los 3 chips debajo del número (se mantiene tu UX)
  const breakdown = document.createElement("div");
  breakdown.className = "priority-breakdown";
  breakdown.innerHTML = `
    <div class="priority A">A: ${counts.A}</div>
    <div class="priority B">B: ${counts.B}</div>
    <div class="priority C">C: ${counts.C}</div>
  `;
  cell.appendChild(breakdown);
  cell.classList.add('is-selected');
  selectedCell = cell;

  // Render de la tabla detalle “tipo Apple”
  renderDrilldown(hrEmail, stage, filteredOpps);
});


  // ——— Cursor “mano” solo para números (no primera col)
  setTimeout(() => {
    document.querySelectorAll("#summaryTable tbody tr").forEach((row) => {
      // antes: row.querySelectorAll("td:not(:first-child)")
      // ahora: excluimos también la última columna (Total)
      row.querySelectorAll("td:not(:first-child):not(:last-child)").forEach((cell) => {
        if (!isNaN(parseInt(cell.textContent, 10))) {
          cell.classList.add("is-clickable");
        }
      });
    });
  }, 100);
  // ——— Hover de columna con velo del color del stage
  // Seteamos un data-atributo en la tabla con el índice de columna
  function setHoverCol(colIndex) {
    table.dataset.hoverCol = colIndex > 1 ? String(colIndex) : "";
  }
  table.querySelectorAll("th, td").forEach((cell) => {
    cell.addEventListener("mouseenter", () => setHoverCol(cell.cellIndex + 1));
    cell.addEventListener("mouseleave", () => setHoverCol(""));
  });
});
function updateColumnTotals(stages, table) {
  // tfoot cells: cada stage tiene su <th.total-col-idx>
  const tfoot = table.querySelector('tfoot');
  if (!tfoot) return;

  const rows = Array.from(table.querySelectorAll('tbody tr'));
  const colTotals = new Array(stages.length).fill(0);

  // Recorremos filas y sumamos cada columna de stage (td 2..6)
  rows.forEach(row => {
    // td[0] = HR Lead, luego vienen las 5 de stage y la última es Total de fila
    stages.forEach((_, idx) => {
      const td = row.children[idx + 1]; // +1 por la 1ª columna (HR Lead)
      const val = Number(td?.textContent || 0);
      if (!Number.isNaN(val)) colTotals[idx] += val;
    });
  });

  // Pintar totales por columna en el tfoot
  let grand = 0;
  colTotals.forEach((sum, idx) => {
    const cell = tfoot.querySelector(`.total-col-${idx + 1}`);
    if (cell) cell.textContent = String(sum);
    grand += sum;
  });

  // Gran total (suma de todos los stages)
  const grandCell = tfoot.querySelector('.grand-total');
  if (grandCell) grandCell.textContent = String(grand);
}
