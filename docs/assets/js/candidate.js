// candidates.js

function goToDetails() {
    window.location.href = "candidate-details.html";
  }
  
  document.addEventListener("DOMContentLoaded", () => {
    const toggleFilters = document.getElementById("toggleFilters");
    const filtersCard = document.getElementById("filtersCard");
  
    // Asegura que los filtros estén cerrados al cargar
    filtersCard.classList.add("hidden");
    filtersCard.classList.remove("expanded");
  
    if (toggleFilters && filtersCard) {
      toggleFilters.addEventListener("click", () => {
        const isHidden = filtersCard.classList.contains("hidden");
        if (isHidden) {
          filtersCard.classList.remove("hidden");
          setTimeout(() => filtersCard.classList.add("expanded"), 10);
        } else {
          filtersCard.classList.remove("expanded");
          setTimeout(() => filtersCard.classList.add("hidden"), 400);
        }
      });
    }
    setTheme('light');
  }
);
  
  function setLightMode() {
    document.body.classList.add("light-mode");
    localStorage.setItem("theme", "light");
  }
  
  function setDarkMode() {
    document.body.classList.remove("light-mode");
    localStorage.setItem("theme", "dark");
  }

function loadCandidates() {
  fetch('https://vinttihub.vintti.com/candidates') // ajusta la URL si es distinta
    .then(response => response.json())
    .then(data => {
      const table = document.querySelector(".table");
      const tableRows = table.querySelectorAll(".table-row");

      // Elimina las filas actuales (si hay una de ejemplo)
      tableRows.forEach(row => row.remove());

      data.forEach(candidate => {
        const row = document.createElement("div");
        row.classList.add("table-row");
        row.onclick = () => goToDetails();

        row.innerHTML = `
          <div><span class="tag">Candidate</span></div>
          <div>${candidate.Name || ""}</div>
          <div>${candidate.country || ""}</div>
          <div><button class="whatsapp" onclick="event.stopPropagation(); window.open('https://wa.me/${candidate.phone}', '_blank')">Contact</button></div>
          <div><button class="linkedin" onclick="event.stopPropagation(); window.open('${candidate.linkedin}', '_blank')">LinkedIn</button></div>
        `;
        table.appendChild(row);
      });
    })
    .catch(error => {
      console.error("Error loading candidates:", error);
    });
}
