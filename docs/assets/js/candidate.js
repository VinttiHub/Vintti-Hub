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
  