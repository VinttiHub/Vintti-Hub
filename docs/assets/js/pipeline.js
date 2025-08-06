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
            const opportunityId = document.getElementById("opportunity-id-text").getAttribute("data-id");

            console.log(`➡️ Updating candidate ${candidateId} to stage ${mappedStage}`);
            console.log("📤 PATCH stage_pipeline")
            console.log("🔹 candidateId:", candidateId)
            console.log("🔹 opportunityId:", opportunityId)
            console.log("🔹 newStage:", mappedStage)

            fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}/stage`, {
              method: 'PATCH',
              headers: {
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({ stage_pipeline: mappedStage })
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
  loadPipelineCandidates();

  ["candidate-name", "candidate-email", "candidate-phone", "candidate-linkedin", "candidate-country"]
    .forEach(id => document.getElementById(id).value = '');
});


document.getElementById("popupcreateCandidateBtn").addEventListener("click", async () => {
  const opportunityId = document.getElementById('opportunity-id-text').getAttribute('data-id');
  const name = document.getElementById("candidate-name").value;
  const email = document.getElementById("candidate-email").value;
  const phoneCode = document.getElementById("phone-country-code").value;
  const rawPhone = document.getElementById("candidate-phone").value.replace(/\s+/g, '');
  const phone = phoneCode + rawPhone;
  const linkedin = document.getElementById("candidate-linkedin").value;
  const country = document.getElementById("candidate-country").value;
  const stage = "Contactado";

  if (!opportunityId || opportunityId === '—') {
    alert('Opportunity ID not found');
    return;
  }

  const payload = {
    name,
    email,
    phone,
    linkedin,
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
    ["candidate-name", "candidate-email", "candidate-phone", "candidate-linkedin", "candidate-country"]
      .forEach(id => document.getElementById(id).value = '');

    loadPipelineCandidates();
  } catch (err) {
    console.error("Error creating candidate:", err);
    alert("Failed to create candidate");
  }
});
const goBackButton = document.getElementById('goBackButton');
const previousPage = localStorage.getItem('previousPage');

if (previousPage && goBackButton) {
  goBackButton.style.display = 'block';
  goBackButton.addEventListener('click', () => {
    window.location.href = previousPage;
    localStorage.removeItem('previousPage');
  });
}
new Choices('#candidate-country', {
  searchEnabled: true,
  itemSelectText: '',
  shouldSort: false,
});
const countryToCodeMap = {
  "Argentina": "54",
  "Bolivia": "591",
  "Brazil": "55",
  "Chile": "56",
  "Colombia": "57",
  "Costa Rica": "506",
  "Cuba": "53",
  "Ecuador": "593",
  "El Salvador": "503",
  "Guatemala": "502",
  "Honduras": "504",
  "Mexico": "52",
  "Nicaragua": "505",
  "Panama": "507",
  "Paraguay": "595",
  "Peru": "51",
  "Puerto Rico": "1",
  "Dominican Republic": "1",
  "Uruguay": "598",
  "Venezuela": "58"
};

document.getElementById('candidate-country').addEventListener('change', (e) => {
  const selectedCountry = e.target.value;
  const code = countryToCodeMap[selectedCountry];
  if (code) {
    document.getElementById('phone-country-code').value = code;
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
              const counters = {
        'contacted': 0,
        'no-advance': 0,
        'first-interview': 0,
        'client-process': 0
      };
      // Limpiar todas las columnas antes
      document.querySelectorAll('.card-container').forEach(container => {
        container.innerHTML = '';
      });

candidates.forEach(candidate => {
  const card = document.createElement('div');
  card.className = 'candidate-card pipeline-card';
  card.setAttribute('data-candidate-id', candidate.candidate_id); 
  const signoffChecked = candidate.sign_off === 'yes' ? 'checked' : '';
  const isStarred = candidate.star === 'yes';
  const starClass = isStarred ? 'starred' : '';

card.innerHTML = `
  <div class="card-header">
    <div class="candidate-info">
      <strong class="candidate-name">${candidate.name}</strong>
      <div class="candidate-meta">
        <span class="country">${getFlagEmoji(candidate.country || '')}</span>
        <span class="salary">${candidate.salary_range ? `$${Number(candidate.salary_range).toLocaleString()}` : '—'}</span>
      </div>
      <div class="star-wrapper">
        <i class="fas fa-star star-icon ${starClass}"></i>
      </div>
    </div>
    <span class="delete-icon" title="Delete">🗑️</span>
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
  if (columnId) {
    container.appendChild(card);
    counters[columnId]++;
  }

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
card.querySelector(".star-icon").addEventListener("click", async (e) => {
  e.stopPropagation();
  const starIcon = e.target;
  const candidateId = card.getAttribute("data-candidate-id");
  const newStarValue = starIcon.classList.contains('starred') ? 'no' : 'yes';

  try {
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}/star`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ star: newStarValue })
    });
    console.log(`⭐ Star status updated for candidate ${candidateId} to ${newStarValue}`);
    starIcon.classList.toggle('starred', newStarValue === 'yes');
  } catch (err) {
    console.error("❌ Error updating star:", err);
  }
});

  card.querySelector(".signoff-checkbox").addEventListener("change", async (e) => {
  e.stopPropagation();
  const checkbox = e.target;
  const candidateId = checkbox.getAttribute("data-candidate-id");
  const signOffValue = checkbox.checked ? "yes" : "no";

  try {
    await fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/opportunities/${opportunityId}/candidates/${candidateId}/signoff`, {
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
    const candidateId = card.getAttribute('data-candidate-id');
    if (!candidateId) return;

    const isSafe = !e.target.closest('.signoff-toggle') &&
                  !e.target.closest('.delete-icon') &&
                  !e.target.closest('input') &&
                  !e.target.closest('select');

    if (!isSafe) return;

    localStorage.setItem('previousPage', window.location.href);
    window.location.href = `https://vinttihub.vintti.com/candidate-details.html?id=${candidateId}`;
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
    counters[columnId]++; // ✅ Sumar al contador después de agregar
  }
        for (const column in counters) {
        const countElement = document.getElementById(`count-${column}`);
        if (countElement) {
          countElement.textContent = counters[column];
        }
      }
});
for (const column in counters) {
  const countElement = document.getElementById(`count-${column}`);
  if (countElement) {
    countElement.textContent = counters[column];
  }
}

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
function getFlagEmoji(country) {
  const flags = {
    "Argentina": "🇦🇷", "Bolivia": "🇧🇴", "Brazil": "🇧🇷", "Chile": "🇨🇱",
    "Colombia": "🇨🇴", "Costa Rica": "🇨🇷", "Cuba": "🇨🇺", "Ecuador": "🇪🇨",
    "El Salvador": "🇸🇻", "Guatemala": "🇬🇹", "Honduras": "🇭🇳", "Mexico": "🇲🇽",
    "Nicaragua": "🇳🇮", "Panama": "🇵🇦", "Paraguay": "🇵🇾", "Peru": "🇵🇪",
    "Puerto Rico": "🇵🇷", "Dominican Republic": "🇩🇴", "Uruguay": "🇺🇾", "Venezuela": "🇻🇪"
  };
  return flags[country] || "";
}
