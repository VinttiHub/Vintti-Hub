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

            fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/stage`, {
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

document.getElementById("closePopup").addEventListener("click", () => {
  document.getElementById("candidatePopup").classList.add("hidden");

  ["candidate-name", "candidate-email", "candidate-phone", "candidate-linkedin", "candidate-redflags", "candidate-comments", "candidate-english", "candidate-salary", "candidate-country"]
    .forEach(id => document.getElementById(id).value = '');
});


document.getElementById("popupcreateCandidateBtn").addEventListener("click", async () => {
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  const name = document.getElementById("candidate-name").value;
  const email = document.getElementById("candidate-email").value;
  const phone = document.getElementById("candidate-phone").value;
  const linkedin = document.getElementById("candidate-linkedin").value;
  const red_flags = document.getElementById("candidate-redflags").value;
  const comments = document.getElementById("candidate-comments").value;
  const english_level = document.getElementById("candidate-english").value;
  const salary_range = document.getElementById("candidate-salary").value;
  const country = document.getElementById("candidate-country").value;
  const stage = "Contactado";

  if (!opportunityId || opportunityId === '—') {
    alert('Opportunity ID not found');
    return;
  }

  if (!name || !email || !phone || !linkedin || !country || !salary_range || !english_level ) {
    alert("Please fill in all fields before creating the candidate.");
    return;
  }

  const payload = {
    name,
    email,
    phone,
    linkedin,
    red_flags,
    comments,
    english_level,
    salary_range,
    country,
    stage,
    created_by: localStorage.getItem('user_email') // ✅ esto lo agrega
  };

  try {
    console.log("Payload:", payload);
    const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Failed to create candidate');

    document.getElementById("candidatePopup").classList.add("hidden");

    // Limpiar campos
    ["candidate-name", "candidate-email", "candidate-phone", "candidate-linkedin", "candidate-redflags", "candidate-comments", "candidate-english", "candidate-salary", "candidate-country"]
      .forEach(id => document.getElementById(id).value = '');

    loadPipelineCandidates();
  } catch (err) {
    console.error("Error creating candidate:", err);
    alert("Failed to create candidate");
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
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates`)
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
  const signoffChecked = candidate.sign_off === 'yes' ? 'checked' : '';
  card.innerHTML = `
    <div class="card-header">
      <strong class="candidate-name">${candidate.name}</strong>
      <span class="delete-icon" title="Delete" style="font-size: 14px; color: #c00; cursor: pointer; margin-left: auto;">🗑️</span>
      <div class="signoff-toggle">
        <label class="switch">
          <input type="checkbox" class="signoff-checkbox" ${signoffChecked} data-candidate-id="${candidate.candidate_id}">
          <span class="slider round"></span>
        </label>
      </div>
    </div>
  `;


  card.querySelector(".delete-icon").addEventListener("click", async (e) => {

  e.stopPropagation(); // evitar que redireccione

  const candidateId = card.getAttribute("data-candidate-id");
  const opportunityId = document.getElementById('opportunity-id-text').textContent.trim();

  const res = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}/opportunities`);
  const linkedOpportunities = await res.json();

  let message = "Are you sure you want to delete this candidate from the pipeline?";
  if (linkedOpportunities.length === 1 && linkedOpportunities[0].opportunity_id == opportunityId) {
    message += "\n⚠️ This candidate is only linked to this opportunity. Deleting will remove them from the database.";
  }

  if (confirm(message)) {
    const deleteRes = await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}`, {
      method: 'DELETE'
    });
    if (deleteRes.ok) {
      loadPipelineCandidates();
    } else {
      alert("Error deleting candidate.");
    }
  }
});
  card.querySelector(".signoff-checkbox").addEventListener("change", async (e) => {
  e.stopPropagation();
  const checkbox = e.target;
  const candidateId = checkbox.getAttribute("data-candidate-id");
  const signOffValue = checkbox.checked ? "yes" : "no";

  try {
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sign_off: signOffValue }),
    });
    console.log(`📝 Sign off status updated for candidate ${candidateId}`);
    checkbox.checked = signOffValue === 'yes';
  } catch (err) {
    console.error("❌ Error updating sign_off:", err);
  }
});

  enableDrag(card);
  card.addEventListener('click', (e) => {
    // ✅ Si el clic fue en el interruptor, no redirigir
    if (e.target.closest('.signoff-toggle')) return;

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