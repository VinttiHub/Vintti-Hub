document.addEventListener("DOMContentLoaded", async () => {
  const stages = ["Negotiating", "Interviewing", "Sourcing", "Deep Dive", "NDA Sent"];
  const emails = {
    "pilar@vintti.com": "Pilar",
    "agostina@vintti.com": "Agostina",
    "jazmin@vintti.com": "Jazmín"
  };
(function colorizeStageHeaders() {
  const toSlug = (s) => s.toLowerCase().replace(/[^a-z]+/g, '-').replace(/^-|-$|/g, '');
  document.querySelectorAll('#summaryTable thead th').forEach((th, i) => {
    const label = th.textContent.trim();
    if (stages.includes(label)) {
      th.classList.add('stage-title', `stage-title-${toSlug(label)}`);
    }
  });
})();
  // Crear estructura de contadores
  const summaryCounts = {};
  Object.keys(emails).forEach(email => {
    summaryCounts[email] = {};
    stages.forEach(stage => summaryCounts[email][stage] = 0);
  });

  try {
    const res = await fetch("https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light");
    const opportunities = await res.json();
    console.log("📦 Oportunidades cargadas:", opportunities);

    // Contar por hr lead y stage
    opportunities.forEach(opp => {
      const hrLead = opp.opp_hr_lead?.toLowerCase();
      const stage = opp.opp_stage;
      if (emails[hrLead] && stages.includes(stage)) {
        summaryCounts[hrLead][stage]++;
      }
    });

    console.log("📊 Contadores procesados:", summaryCounts);

    // Renderizar en tabla
    document.querySelectorAll("#summaryTable tbody tr").forEach(row => {
      const email = row.getAttribute("data-email");
      
      // Vaciar la fila excepto primer columna
      while (row.children.length > 1) row.removeChild(row.lastChild);

      stages.forEach(stage => {
        const cell = document.createElement("td");
        cell.textContent = summaryCounts[email][stage] || "0";
        row.appendChild(cell);
      });
    });
  } catch (err) {
    console.error("❌ Error al cargar oportunidades:", err);
  }

    const lastUpdatedDiv = document.getElementById("lastUpdated");

  const now = new Date();
  const formattedDate = now.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric"
  });

  const formattedTime = now.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit"
  });

  lastUpdatedDiv.textContent = `Last updated: ${formattedDate} at ${formattedTime} — refresh the page to get the latest numbers.`;

  document.querySelectorAll("#summaryTable td").forEach(cell => {
  cell.addEventListener("click", async () => {
    // Evitar duplicación
    if (cell.querySelector(".priority-breakdown")) {
      cell.querySelector(".priority-breakdown").remove();
      return;
    }

    const stage = stages[cell.cellIndex - 1];
    const row = cell.closest("tr");
    const hrEmail = row.getAttribute("data-email");

    // 🧩 Cargar oportunidades y cuentas si no están en caché
    const [oppsRes, accountsRes] = await Promise.all([
      fetch("https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/light"),
      fetch("https://7m6mw95m8y.us-east-2.awsapprunner.com/data/light")
    ]);
    const opps = await oppsRes.json();
    const accounts = await accountsRes.json();
    const priorityMap = {};
    accounts.forEach(acc => {
      if (acc.account_id) {
        priorityMap[acc.account_id] = acc.priority || "N/A";
      }
    });

    // 📊 Filtrar oportunidades por HR Lead + Stage
    const filteredOpps = opps.filter(o =>
      o.opp_hr_lead?.toLowerCase() === hrEmail &&
      o.opp_stage === stage
    );

    const counts = { A: 0, B: 0, C: 0, "N/A": 0 };
    filteredOpps.forEach(opp => {
      const prio = priorityMap[opp.account_id] || "N/A";
      counts[prio]++;
    });

    // 🎨 Mostrar desglose debajo del número
    const breakdown = document.createElement("div");
    breakdown.className = "priority-breakdown";
    breakdown.innerHTML = `
      <div class="priority A">A: ${counts.A}</div>
      <div class="priority B">B: ${counts.B}</div>
      <div class="priority C">C: ${counts.C}</div>
    `;
    cell.appendChild(breakdown);
  });
});
// ✅ Añadir cursor manito solo a celdas con número
setTimeout(() => {
  document.querySelectorAll("#summaryTable tbody tr").forEach(row => {
    const cells = row.querySelectorAll("td:not(:first-child)");
    cells.forEach(cell => {
      if (!isNaN(parseInt(cell.textContent))) {
        cell.style.cursor = "pointer";
      }
    });
  });
}, 300);

});
