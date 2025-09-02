document.addEventListener("DOMContentLoaded", async () => {
  const stages = ["Negotiating", "Interviewing", "Sourcing", "Deep Dive", "NDA Sent"];
  const emails = {
    "pilar@vintti.com": "Pilar",
    "agostina@vintti.com": "Agostina",
    "jazmin@vintti.com": "Jazmín",
    "agustina.barbero@vintti.com": "Agustina"
  };
// --- Construir tbody dinámicamente desde `emails`
const tbody = document.querySelector('#summaryTable tbody');
tbody.innerHTML = '';
Object.entries(emails).forEach(([email, name]) => {
  const tr = document.createElement('tr');
  tr.dataset.email = email.toLowerCase(); // normalizado
  const td = document.createElement('td');
  td.textContent = name;
  tr.appendChild(td);
  tbody.appendChild(tr);
});

  // ——— Etiquetar headers por stage para estilos por-columna
  (function colorizeStageHeaders() {
    const toSlug = (s) =>
      s.toLowerCase().replace(/[^a-z]+/g, "-").replace(/(^-+|-+$)/g, "");
    document.querySelectorAll("#summaryTable thead th").forEach((th) => {
      const label = th.textContent.trim();
      if (stages.includes(label)) {
        th.classList.add("stage-title", `stage-title-${toSlug(label)}`);
      }
    });
  })();

  // ——— Estructura de contadores
  const summaryCounts = {};
  Object.keys(emails).forEach((email) => {
    summaryCounts[email] = {};
    stages.forEach((stage) => (summaryCounts[email][stage] = 0));
  });

  // ——— Cargar oportunidades
  try {
    const res = await fetch(
      "https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light"
    );
    const opportunities = await res.json();

opportunities.forEach((opp) => {
  const hrLead = String(opp.opp_hr_lead || '').trim().toLowerCase();
  const stage  = String(opp.opp_stage   || '').trim();
  if (emails[hrLead] && stages.includes(stage)) {
    summaryCounts[hrLead][stage]++;
  }
});


    // Render tabla
    document.querySelectorAll("#summaryTable tbody tr").forEach((row) => {
      const email = row.getAttribute("data-email");
      // Vaciar la fila excepto primera col (HR Lead)
      while (row.children.length > 1) row.removeChild(row.lastChild);

      stages.forEach((stage) => {
        const cell = document.createElement("td");
        cell.textContent = String(summaryCounts[email][stage] || 0);
        row.appendChild(cell);
      });
    });
  } catch (err) {
    console.error("❌ Error al cargar oportunidades:", err);
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
        fetch("https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light"),
        fetch("https://7m6mw95m8y.us-east-2.awsapprunner.com/data/light"),
      ]);
      oppsCache = await oppsRes.json();
      accountsCache = await accountsRes.json();
    }
  }

  // ——— Solo permitir click en celdas numéricas (no la primera col)
  const table = document.getElementById("summaryTable");

  table.addEventListener("click", async (evt) => {
    const cell = evt.target.closest("td");
    if (!cell) return;

    const row = cell.parentElement;
    const isFirstCol = cell.cellIndex === 0;
    const isNumber = !isNaN(parseInt(cell.textContent, 10));

    // Bloquear clic en columna "HR Lead"
    if (isFirstCol || !isNumber) return;

    // Toggle (evitar duplicación)
    const existing = cell.querySelector(".priority-breakdown");
    if (existing) {
      existing.remove();
      return;
    }

    // Calcular stage según índice de columna
    const stage = stages[cell.cellIndex - 1];
    const hrEmail = row.getAttribute("data-email");

    await ensureCaches();

    // Mapear prioridad por account
    const priorityMap = {};
    (accountsCache || []).forEach((acc) => {
      if (acc?.account_id) priorityMap[acc.account_id] = acc.priority || "N/A";
    });

    // Filtrado por HR Lead + Stage
    const filteredOpps = (oppsCache || []).filter(
      (o) => o.opp_hr_lead?.toLowerCase() === hrEmail && o.opp_stage === stage
    );

    const counts = { A: 0, B: 0, C: 0 };
    filteredOpps.forEach((opp) => {
      const prio = priorityMap[opp.account_id] || "N/A";
      if (counts[prio] !== undefined) counts[prio]++;
    });

    // Insertar desglose debajo del número
    const breakdown = document.createElement("div");
    breakdown.className = "priority-breakdown";
    breakdown.innerHTML = `
      <div class="priority A">A: ${counts.A}</div>
      <div class="priority B">B: ${counts.B}</div>
      <div class="priority C">C: ${counts.C}</div>
    `;
    cell.appendChild(breakdown);
  });

  // ——— Cursor “mano” solo para números (no primera col)
  setTimeout(() => {
    document.querySelectorAll("#summaryTable tbody tr").forEach((row) => {
      row.querySelectorAll("td:not(:first-child)").forEach((cell) => {
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
