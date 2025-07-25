document.addEventListener("DOMContentLoaded", async () => {
  const stages = ["Negotiating", "Interviewing", "Sourcing", "Deep Dive", "NDA Sent"];
  const emails = {
    "pilar@vintti.com": "Pilar",
    "agostina@vintti.com": "Agostina",
    "jazmin@vintti.com": "Jazmín"
  };

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
});
