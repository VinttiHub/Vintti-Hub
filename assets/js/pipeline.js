document.addEventListener("DOMContentLoaded", () => {
    const containers = document.querySelectorAll(".card-container");
    let draggedCard = null;
  
    function enableDrag(card) {
      card.draggable = true;
  
      card.addEventListener("dragstart", () => {
        draggedCard = card;
        setTimeout(() => card.style.display = "none", 0);
      });
  
      card.addEventListener("dragend", () => {
        setTimeout(() => {
          draggedCard.style.display = "block";
          draggedCard = null;
        }, 0);
      });
    }
  
    // Activar drag para tarjetas iniciales
    document.querySelectorAll(".candidate-card").forEach(enableDrag);
  
    // Permitir soltar en columnas
    containers.forEach(container => {
      container.addEventListener("dragover", e => e.preventDefault());
  
      container.addEventListener("drop", () => {
        if (draggedCard) {
          container.appendChild(draggedCard);
        }
      });
    });
  
    // Agregar tarjeta al hacer clic en “+ Add Candidate”
    document.getElementById("addCandidateBtn").addEventListener("click", () => {
      const newCard = document.createElement("div");
      newCard.className = "candidate-card";
      newCard.innerHTML = `<strong>New Candidate</strong><p class="status">Contactado</p>`;
      
      enableDrag(newCard);
      document.getElementById("contacted").appendChild(newCard);
    });
  });
  