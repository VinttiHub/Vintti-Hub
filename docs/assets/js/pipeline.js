document.addEventListener("DOMContentLoaded", () => {
    const containers = document.querySelectorAll(".card-container");
    const stageMap = {
      'contacted': 'Contactado',
      'no-advance': 'No avanza primera',
      'first-interview': 'Primera entrevista',
      'client-process': 'En proceso con Cliente'
    };

    let draggedCard = null;
  
    // Activar drag para tarjetas iniciales
    document.querySelectorAll(".candidate-card").forEach(enableDrag);
  
    // Permitir soltar en columnas
    containers.forEach(container => {
      container.addEventListener("dragover", e => {
        e.preventDefault();
        container.parentElement.classList.add('drag-over'); // añade clase visual a .column
      });

      container.addEventListener("dragleave", () => {
        container.parentElement.classList.remove('drag-over');
      });
      container.addEventListener("drop", (e) => {
        e.preventDefault();
        console.log('📥 Drop event triggered');

        // Recuperar candidateId desde dataTransfer
        const candidateId = e.dataTransfer.getData("text/plain");
        console.log('📥 CandidateID from dataTransfer:', candidateId);

        if (candidateId) {
          // Buscar la tarjeta en el DOM
          const draggedCardElement = document.querySelector(`.candidate-card[data-candidate-id='${candidateId}']`);
          if (draggedCardElement) {
            console.log('📥 Found draggedCardElement:', draggedCardElement);

            container.appendChild(draggedCardElement);

            const newStage = container.parentElement.getAttribute('data-status');
            const mappedStage = stageMap[newStage] || null;
            console.log(`➡️ Updating candidate ${candidateId} to stage ${mappedStage}`);

            fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates/${candidateId}/stage`, {
              method: 'PATCH',
              headers: {
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({ stage: mappedStage })
            })
            .then(response => {
              if (!response.ok) {
                throw new Error('Error updating candidate stage');
              }
              console.log('✅ Candidate stage updated successfully');
              setTimeout(() => {
                loadPipelineCandidates();
              }, 200);
            })
            .catch(error => {
              console.error('Error updating candidate stage:', error);
            });
          } else {
            console.warn('⚠️ No draggedCardElement found!');
          }
        }
      });

    });
// Mostrar popup al hacer clic en “+ Add Candidate”
document.getElementById("createCandidateBtn").addEventListener("click", () => {
  document.getElementById("candidatePopup").classList.remove("hidden");
});

document.getElementById("closePopup").addEventListener("click", () => {
  document.getElementById("candidatePopup").classList.add("hidden");

  // Limpiar campos
  document.getElementById("candidate-name").value = '';
  document.getElementById("candidate-email").value = '';
  document.getElementById("candidate-phone").value = '';
  document.getElementById("candidate-linkedin").value = '';
  document.getElementById("candidate-redfalgs").value = '';
  document.getElementById("candidate-comments").value = '';
});

// Crear candidato desde popup
document.getElementById("createCandidateBtn").addEventListener("click", async () => {
  const opportunityId = document.getElementById('opportunity-id-text').textContent.trim();
  const name = document.getElementById("candidate-name").value;
  const email = document.getElementById("candidate-email").value;
  const phone = document.getElementById("candidate-phone").value;
  const linkedin = document.getElementById("candidate-linkedin").value;
  const redfalgs = document.getElementById("candidate-redflags").value;
  const comments = document.getElementById("candidate-comments").value;
  const stage = "Contactado";

  if (!opportunityId || opportunityId === '—') {
    alert('Opportunity ID not found');
    return;
  }

  if (!name || !email || !phone || !linkedin) {
  alert("Please fill in all fields before creating the candidate.");
  return;
  }
  const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  try {
    const res = await fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Failed to create candidate');

    document.getElementById("candidatePopup").classList.add("hidden");

    // Limpiar campos
    document.getElementById("candidate-name").value = '';
    document.getElementById("candidate-email").value = '';
    document.getElementById("candidate-phone").value = '';
    document.getElementById("candidate-linkedin").value = '';
    document.getElementById("candidate-redfalgs").value = '';
    document.getElementById("candidate-comments").value = '';

    loadPipelineCandidates();
  } catch (err) {
    console.error("Error creating candidate:", err);
    alert("Failed to create candidate");
  }
});

  });
  document.querySelectorAll(".candidate-card").forEach(card => {
    const preview = card.querySelector(".preview");
  
    card.addEventListener("mouseenter", (e) => {
      if (preview) {
        const rect = card.getBoundingClientRect();
        preview.style.top = `${rect.top + window.scrollY}px`;
        preview.style.left = `${rect.right + 10}px`;
        preview.style.display = "block";
      }
    });
  
    card.addEventListener("mouseleave", () => {
      if (preview) {
        preview.style.display = "none";
      }
    });
  });
  // 🚀 FUNCION: Cargar candidatos desde el backend y mostrarlos en el pipeline
function loadPipelineCandidates() {
  // Leer el opportunity_id que ya está en la página
  const opportunityId = document.getElementById('opportunity-id-text').textContent.trim();
  if (opportunityId === '—' || opportunityId === '') {
    console.error('Opportunity ID not found');
    return;
  }

  // Hacer fetch al backend
  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`)
    .then(response => response.json())
    .then(candidates => {
      console.log('🔵 Candidates:', candidates);
      
      // Limpiar todas las columnas antes
      document.querySelectorAll('.card-container').forEach(container => {
        container.innerHTML = '';
      });

candidates.forEach(candidate => {
  const card = document.createElement('div');
  card.className = 'candidate-card';
  card.setAttribute('data-candidate-id', candidate.candidate_id); 
  card.innerHTML = `
    <strong>${candidate.name}</strong>
    <div class="preview">
      <img src="https://randomuser.me/api/portraits/lego/1.jpg" alt="${candidate.name}">
      <div class="info">
        <span class="name">${candidate.name}</span>
        <span class="email">${candidate.email ?? ''}</span>
      </div>
    </div>
  `;

  enableDrag(card);
  card.addEventListener('click', () => {
    const candidateId = card.getAttribute('data-candidate-id');
    if (candidateId) {
      window.location.href = `https://vinttihub.vintti.com/candidate-details.html?id=${candidateId}`;
    }
  });

  // Mapeo del stage → columna id
  let columnId = '';
  switch (candidate.stage?.trim()) {
      case 'Contactado':
        columnId = 'contacted';
        break;
      case 'No avanza primera':
        columnId = 'no-advance';
        break;
      case 'Primera entrevista':
        columnId = 'first-interview';
        break;
      case 'En proceso con Cliente':
        columnId = 'client-process';
        break;
      default:
        console.warn(`Stage desconocido: ${candidate.stage}`);
        columnId = 'contacted'; // fallback
    }

  const container = document.getElementById(columnId);
  if (container) {
    container.appendChild(card);
  }
});

    })
    .catch(error => {
      console.error('Error loading candidates:', error);
    });
}
window.loadPipelineCandidates = loadPipelineCandidates;

function enableDrag(card) {
      card.draggable = true;
  
      card.addEventListener("dragstart", (e) => {
        draggedCard = card;
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.getAttribute("data-candidate-id"));
      });

  
      card.addEventListener("dragend", () => {
        setTimeout(() => {
          draggedCard = null;
        }, 0);
      });
    }