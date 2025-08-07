document.addEventListener('DOMContentLoaded', () => {
document.body.style.backgroundColor = 'var(--bg)';

  // Tabs
  const tabs = document.querySelectorAll('.tab-btn');
  const contents = document.querySelectorAll('.tab-content');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.getAttribute('data-tab');
      contents.forEach(c => {
        c.classList.remove('active');
        if (c.id === target) c.classList.add('active');
      });
    });
  });

  // Accordion
  document.querySelectorAll('.accordion-header').forEach(header => {
    header.addEventListener('click', () => {
      const section = header.parentElement;
      section.classList.toggle('open');
    });
  });

  // Cargar datos
  const id = getIdFromURL();
  if (!id) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${id}`)
    .then(res => res.json())
    .then(data => {
      fillAccountDetails(data);
      loadAssociatedOpportunities(id);
      loadCandidates(id);
    })
    .catch(err => {
      console.error('Error fetching accounts details:', err);
    });
// Botón de Go Back
const goBackButton = document.getElementById('goBackButton');
if (goBackButton) {
  goBackButton.addEventListener('click', () => {
    if (document.referrer) {
      window.history.back();
    } else {
      window.location.href = '/'; // Cambia por la home si quieres
    }
  });
}
  // Guardar Pain Points al hacer blur
  const painPointsTextarea = document.getElementById('pain-points');
  if (painPointsTextarea) {
    painPointsTextarea.addEventListener('blur', () => {
      const value = painPointsTextarea.value.trim();
      const accountId = getIdFromURL();
      if (!accountId) return;

      fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pain_points: value })
      })
      .then(res => {
        if (!res.ok) throw new Error('Error updating pain points');
        console.log('Pain Points updated');
      })
      .catch(err => {
        console.error('Failed to update Pain Points:', err);
      });
    });
  }

const clientNameInput = document.getElementById('account-client-name');
if (clientNameInput) {
  clientNameInput.addEventListener('blur', () => {
    const newName = clientNameInput.value.trim();
    const accountId = getIdFromURL();
    if (!accountId || !newName) return;

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_name: newName })
    })
    .then(res => {
      if (!res.ok) throw new Error('Error updating client name');
      console.log('Client name updated');
    })
    .catch(err => {
      console.error('Failed to update client name:', err);
    });
  });
}
setTimeout(() => {
  document.querySelectorAll('.month-range-picker').forEach(input => {
    new Litepicker({
      element: input,
      format: 'MMM YYYY',
      numberOfMonths: 2,
      numberOfColumns: 2,
      singleMode: false,
      allowRepick: true,
      dropdowns: {
        minYear: 2020,
        maxYear: 2030,
        months: true,
        years: true
      },
      setup: (picker) => {
        picker.on('selected', (date1, date2) => {
          const candidateId = input.dataset.candidateId;
          if (!candidateId) return;

          const start = date1.format('YYYY-MM-DD');
          const end = date2.format('YYYY-MM-DD');

          // Guardar en la base de datos
          fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ discount_daterange: `[${start},${end}]` }) // formato de daterange
          }).then(res => {
            if (!res.ok) throw new Error("Error al guardar discount_daterange");
            console.log('🟢 Discount date range actualizado');
          }).catch(err => {
            console.error('❌ Error:', err);
          });
        });
      }
    });
  });
}, 100);








});
function editField(field) {
  const currentLink = document.getElementById(`${field}-link`).href;
  const newLink = prompt(`Enter new ${field} URL:`, currentLink);

  if (!newLink) return;

  // Actualiza el link visualmente
  document.getElementById(`${field}-link`).href = newLink;

  // Obtener el account ID desde la URL
  const accountId = new URLSearchParams(window.location.search).get('id');
  if (!accountId) return;

  const body = { [field]: newLink };

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  .then(res => {
    if (!res.ok) throw new Error('Failed to update');
    console.log(`${field} updated successfully`);
  })
  .catch(err => {
    alert('There was an error updating the link. Please try again.');
    console.error(err);
  });
}
function loadAssociatedOpportunities(accountId) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities`)
    .then(res => res.json())
    .then(data => {
      console.log("Oportunidades asociadas:", data);
      fillOpportunitiesTable(data);
    })
    .catch(err => {
      console.error("Error cargando oportunidades asociadas:", err);
    });
}
function fillAccountDetails(data) {
  document.querySelectorAll('#overview .accordion-content p').forEach(p => {
    if (p.textContent.includes('Name:')) {
      const inputHTML = `<strong>Name:</strong> <input id="account-client-name" class="editable-input" type="text" value="${data.client_name || ''}" placeholder="Not available" />`;
      p.innerHTML = inputHTML;

      // ⬅️ Aquí agregamos el blur listener justo después de crearlo
      const clientNameInput = document.getElementById('account-client-name');
      if (clientNameInput) {
        clientNameInput.addEventListener('blur', () => {
          const newName = clientNameInput.value.trim();
          const accountId = getIdFromURL();
          if (!accountId || !newName) return;

          fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ client_name: newName })
          })
          .then(res => {
            if (!res.ok) throw new Error('Error updating client name');
            console.log('Client name updated');
          })
          .catch(err => {
            console.error('Failed to update client name:', err);
          });
        });
      }

    } else if (p.textContent.includes('Size:')) {
      p.innerHTML = `<strong>Size:</strong> ${data.size || '—'}`;
    } else if (p.textContent.includes('Timezone:')) {
      p.innerHTML = `<strong>Timezone:</strong> ${data.timezone || '—'}`;
    } else if (p.textContent.includes('State:')) {
      p.innerHTML = `<strong>State:</strong> ${data.state || '—'}`;
    } else if (p.textContent.includes('Contract:')) {
      p.innerHTML = `<strong>Contract:</strong> ${data.contract || '—'}`;
    }
  });

  const linkedinLink = document.getElementById('linkedin-link');
  if (linkedinLink) linkedinLink.href = data.linkedin || '#';

  const websiteLink = document.getElementById('website-link');
  if (websiteLink) websiteLink.href = data.website || '#';
  if (data.pdf_s3) {
  const previewContainer = document.getElementById("pdfPreviewContainer");
  previewContainer.innerHTML = `<a href="${data.pdf_s3}" target="_blank">📄 View uploaded PDF</a>`;
}

}



function fillOpportunitiesTable(opportunities) {
  const tbody = document.querySelector('#overview .accordion-section:nth-of-type(2) tbody');
  tbody.innerHTML = '';

  if (!opportunities.length) {
    tbody.innerHTML = `<tr><td colspan="3">No opportunities found</td></tr>`;
    return;
  }

  opportunities.forEach(opp => {
    const hireContent = opp.candidate_name
      ? opp.candidate_name
      : `<span class="no-hire">Not hired yet</span>`;

    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${opp.opp_position_name || '—'}</td>
      <td>${opp.opp_stage || '—'}</td>
      <td>${hireContent}</td>
    `;
    tbody.appendChild(row);
  });
}

function loadCandidates(accountId) {
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/opportunities/candidates`)
    .then(res => res.json())
    .then(data => {
      console.log("Candidates asociados:", data);
      fillEmployeesTables(data);
    })
    .catch(err => {
      console.error("Error cargando candidates asociados:", err);
    });
}

function fillEmployeesTables(candidates) {
  const staffingTableBody = document.querySelector('#employees .card:nth-of-type(1) tbody');
  const recruitingTableBody = document.querySelector('#employees .card:nth-of-type(2) tbody');

  staffingTableBody.innerHTML = '';   // Limpiar
  recruitingTableBody.innerHTML = '';

  let hasStaffing = false;
  let hasRecruiting = false;

  if (!candidates.length) return;

  candidates.forEach(candidate => {
    // Crear fila de tabla:
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${candidate.status || '—'}</td>
      <td>${candidate.name || '—'}</td>
      <td>${candidate.startingdate || '—'}</td>
      <td>${candidate.enddate || '—'}</td>
      <td>${candidate.opportunity_id || '—'}</td>
      <td>$${candidate.employee_fee ?? '—'}</td>
      <td>$${candidate.employee_salary ?? '—'}</td>
      <td>$${candidate.employee_revenue ?? '—'}</td>
      <td>
        <input 
          type="number"
          class="discount-input"
          placeholder="$"
          value="${candidate.discount_dolar || ''}"
          data-candidate-id="${candidate.candidate_id}"
        />
      </td>
      <td>
      <input 
        type="text" 
        class="month-range-picker" 
        placeholder="Select range"
        readonly 
        data-candidate-id="${candidate.candidate_id}"
        value="${candidate.discount_daterange || ''}"
      />
      </td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
      <td>—</td>
    `;
    const discountInput = row.querySelector('.discount-input');
    discountInput.addEventListener('blur', () => {
      const candidateId = discountInput.dataset.candidateId;
      const value = discountInput.value;
      updateCandidateField(candidateId, 'discount_dolar', value);
    });
    if (candidate.opp_model === 'Staffing') {
      staffingTableBody.appendChild(row);
      hasStaffing = true;
    } else if (candidate.opp_model === 'Recruiting') {
      recruitingTableBody.appendChild(row);
      hasRecruiting = true;
    }

    // Según peoplemodel lo metemos en la tabla correcta:
    if (candidate.opp_model === 'Staffing') {
      staffingTableBody.appendChild(row);
    } else if (candidate.opp_model === 'Recruiting') {
      recruitingTableBody.appendChild(row);
    }
  });

  if (!hasStaffing) {
  staffingTableBody.innerHTML = `<tr><td colspan="100%">No employees in Staffing</td></tr>`;
}
if (!hasRecruiting) {
  recruitingTableBody.innerHTML = `<tr><td colspan="100%">No employees in Recruiting</td></tr>`;
}

}
  function getIdFromURL() {
    const params = new URLSearchParams(window.location.search);
    return params.get('id');
  }
  function formatDollarInput(input) {
  const val = input.value.replace(/\$/g, '').replace(/[^\d.]/g, '');
  input.value = val ? `$${val}` : '';
}
function saveDiscountDolar(candidateId, value) {
  const numericValue = parseFloat(value.replace(/[^\d.]/g, ''));
  if (isNaN(numericValue)) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ discount_dolar: numericValue })
  })
  .then(res => {
    if (!res.ok) throw new Error('Error saving discount');
    console.log('💾 Discount $ saved');
  })
  .catch(err => console.error('❌ Failed to save discount:', err));
}
const uploadBtn = document.getElementById("uploadPdfBtn");
const pdfInput = document.getElementById("pdfUpload");
const previewContainer = document.getElementById("pdfPreviewContainer");

uploadBtn.addEventListener("click", () => {
  const file = pdfInput.files[0];
  if (!file) return alert("Please select a PDF file.");

  const formData = new FormData();
  formData.append("pdf", file);

  const accountId = getIdFromURL();
  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/upload_pdf`, {
    method: "POST",
    body: formData,
  })
    .then(res => res.json())
    .then(data => {
      if (data.pdf_url) {
        previewContainer.innerHTML = `<a href="${data.pdf_url}" target="_blank">📄 View uploaded PDF</a>`;
      } else {
        alert("Error uploading PDF.");
      }
    })
    .catch(err => {
      console.error("Error uploading PDF:", err);
      alert("Upload failed");
    });
});
function updateCandidateField(candidateId, field, value) {
  if (field === 'discount_dolar') {
    const numericValue = parseFloat(value.replace(/[^\d.]/g, ''));
    if (isNaN(numericValue)) return;

    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: numericValue })
    })
    .then(res => {
      if (!res.ok) throw new Error('Error saving discount');
      console.log(`💾 ${field} saved for candidate ${candidateId}`);
    })
    .catch(err => console.error('❌ Failed to save field:', err));
  }
}
