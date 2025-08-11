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
const closeBtn = document.getElementById("close-discount-alert");
if (closeBtn) {
  closeBtn.addEventListener("click", () => {
    document.getElementById("discount-alert").classList.add("hidden");
  });
}








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
  previewContainer.innerHTML = `
    <a href="${data.pdf_s3}" target="_blank">📄 View PDF</a>
    <button id="deletePdfBtn" title="Delete PDF">🗑️</button>
  `;
  const deleteBtn = document.getElementById("deletePdfBtn");
  if (deleteBtn) {
    deleteBtn.addEventListener("click", deletePDF);
  }
}
document.getElementById('account-tsf').textContent = `$${data.tsf ?? 0}`;
document.getElementById('account-tsr').textContent = `$${data.tsr ?? 0}`;
document.getElementById('account-trr').textContent = `$${data.trr ?? 0}`;


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
  const staffingTableBody   = document.querySelector('#employees .card:nth-of-type(1) tbody');
  const recruitingTableBody = document.querySelector('#employees .card:nth-of-type(2) tbody');

  staffingTableBody.innerHTML = '';
  recruitingTableBody.innerHTML = '';

  let hasStaffing = false;
  let hasRecruiting = false;

  if (!Array.isArray(candidates) || candidates.length === 0) {
    staffingTableBody.innerHTML   = `<tr><td colspan="15">No employees in Staffing</td></tr>`;
    recruitingTableBody.innerHTML = `<tr><td colspan="10">No employees in Recruiting</td></tr>`;
    return;
  }

  candidates.forEach(candidate => {
    // ---------- STAFFING ----------
    if (candidate.opp_model === 'Staffing') {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${candidate.status || '—'}</td>
        <td>
          <a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">
            ${candidate.name || '—'}
          </a>
        </td>
        <td>${candidate.start_date ? new Date(candidate.start_date).toLocaleDateString('en-US') : '—'}</td>
        <td>${candidate.enddate ? new Date(candidate.enddate).toLocaleDateString('en-US') : '—'}</td>
        <td>${candidate.opp_position_name || '—'}</td>
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
            value="${candidate.discount_daterange?.replace('[','').replace(']','').split(',').map(d => d.trim()).join(' - ') || ''}"
          />
        </td>
        <td>—</td>
        <td>—</td>
        <td>—</td>
        <td>—</td>
      `;

      // ----- Lógica de Discount SOLO para Staffing -----
      const monthsCell    = row.children[10]; // Discount Months
      const dateRangeCell = row.children[9];  // Discount Date Range
      const dollarCell    = row.children[8];  // Discount $

      if (candidate.discount_daterange && candidate.discount_daterange.includes(',')) {
        const [startStr, endStr] = candidate.discount_daterange
          .replace('[','').replace(']','')
          .split(',').map(d => d.trim());

        const start = new Date(startStr);
        const end   = new Date(endStr);

        if (!isNaN(start.getTime()) && !isNaN(end.getTime())) {
          // Meses (inclusive)
          const months =
            (end.getFullYear() - start.getFullYear()) * 12 +
            (end.getMonth() - start.getMonth()) + 1;
          monthsCell.textContent = months;

          // Badge activo/expirado
          const now = new Date();
          const current = new Date(now.getFullYear(), now.getMonth(), 1);
          const endMonth = new Date(end.getFullYear(), end.getMonth(), 1);
          const isExpired = endMonth < current;

          const badge = document.createElement('span');
          badge.textContent = isExpired ? 'expired' : 'active';
          badge.style.backgroundColor = isExpired ? '#ffe6e6' : '#e6f5e6';
          badge.style.color = isExpired ? '#b30000' : '#006600';
          badge.style.padding = '2px 8px';
          badge.style.borderRadius = '12px';
          badge.style.fontSize = '11px';
          badge.style.marginLeft = '8px';
          badge.style.fontWeight = '600';
          badge.style.display = 'inline-block';

          const dateInput = dateRangeCell.querySelector('.month-range-picker');
          if (dateInput && dateInput.parentElement) {
            dateInput.parentElement.appendChild(badge);
          }

          if (isExpired) {
            [monthsCell, dateRangeCell, dollarCell].forEach(cell => {
              cell.style.backgroundColor = '#fff0f0';
              cell.style.color = '#b30000';
              cell.style.fontWeight = '500';
            });
          } else {
            [monthsCell, dateRangeCell, dollarCell].forEach(cell => {
              cell.style.backgroundColor = '#f2fff2';
              cell.style.color = '#006600';
            });
          }
        }
      }

      // Inicializar Litepicker (si hay valores previos, precargar)
      const monthPickerInput = row.querySelector('.month-range-picker');
      if (monthPickerInput) {
        const daterange = candidate.discount_daterange;
        let startDate = null;
        let endDate = null;

        if (daterange && daterange.includes(',')) {
          const dates = daterange.replace('[', '').replace(']', '').split(',');
          if (dates.length === 2) {
            startDate = new Date(dates[0].trim().slice(0, 7) + '-15');
            endDate   = new Date(dates[1].trim().slice(0, 7) + '-15');
          }
        }

        const litepickerOptions = {
          element: monthPickerInput,
          format: 'MMM YYYY',
          numberOfMonths: 2,
          numberOfColumns: 2,
          singleMode: false,
          allowRepick: true,
          dropdowns: { minYear: 2020, maxYear: 2030, months: true, years: true },
          setup: (picker) => {
            picker.on('selected', (date1, date2) => {
              const candidateId = monthPickerInput.dataset.candidateId;
              if (!candidateId) return;

              const start = date1.format('YYYY-MM-DD');
              const end   = date2.format('YYYY-MM-DD');

              fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/candidates/${candidateId}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ discount_daterange: `[${start},${end}]` })
              })
              .then(res => {
                if (!res.ok) throw new Error("Error al guardar discount_daterange");
                console.log('🟢 Discount date range actualizado');
              })
              .catch(err => console.error('❌ Error:', err));
            });
          }
        };

        if (startDate && endDate) {
          litepickerOptions.startDate = startDate;
          litepickerOptions.endDate   = endDate;
        }

        new Litepicker(litepickerOptions);
      }

      const discountInput = row.querySelector('.discount-input');
      if (discountInput) {
        discountInput.addEventListener('blur', () => {
          const candidateId = discountInput.dataset.candidateId;
          const value = discountInput.value;
          updateCandidateField(candidateId, 'discount_dolar', value);
        });
      }

      staffingTableBody.appendChild(row);
      hasStaffing = true;
    }

    // ---------- RECRUITING ----------
    else if (candidate.opp_model === 'Recruiting') {
      const probation =
        candidate.probation_days ??
        candidate.probation ??
        candidate.probation_days_recruiting ?? '—';

      const revenueRecruit =
        (candidate.employee_revenue_recruiting ??
         candidate.employee_revenue ??
         '—');

      const referralVal =
        (candidate.referral ??
         candidate.referral_dolar ??
         '—');

      const referralRange =
        candidate.referral_daterange
          ? candidate.referral_daterange
              .replace('[','').replace(']','')
              .split(',').map(d => d.trim()).join(' - ')
          : '—';

      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${candidate.status || '—'}</td>
        <td>
          <a href="/candidate-details.html?id=${candidate.candidate_id}" class="employee-link">
            ${candidate.name || '—'}
          </a>
        </td>
        <td>${candidate.start_date ? new Date(candidate.start_date).toLocaleDateString('en-US') : '—'}</td>
        <td>${candidate.enddate ? new Date(candidate.enddate).toLocaleDateString('en-US') : '—'}</td>
        <td>${candidate.opp_position_name || '—'}</td>
        <td>${probation}</td>
        <td>$${candidate.employee_salary ?? '—'}</td>
        <td>$${revenueRecruit}</td>
        <td>${referralVal}</td>
        <td>${referralRange}</td>
      `;

      recruitingTableBody.appendChild(row);
      hasRecruiting = true;
    }
  });

  if (!hasStaffing) {
    staffingTableBody.innerHTML = `<tr><td colspan="15">No employees in Staffing</td></tr>`;
  }
  if (!hasRecruiting) {
    recruitingTableBody.innerHTML = `<tr><td colspan="10">No employees in Recruiting</td></tr>`;
  }

  // ------- Alertas de Discount (solo Staffing) -------
  const alertDiv        = document.getElementById("discount-alert");
  const discountCountEl = document.getElementById("discount-count");
  const discountListEl  = document.getElementById("discount-list");

  const discountCandidates = candidates.filter(c => {
    if (c.opp_model !== 'Staffing') return false;
    if (!c.discount_dolar || !c.discount_daterange || !c.discount_daterange.includes(',')) return false;

    const [, endStr] = c.discount_daterange.replace('[', '').replace(']', '').split(',').map(s => s.trim());
    const endDate = new Date(endStr);
    const now = new Date();
    const currentMonthStart = new Date(now.getFullYear(), now.getMonth(), 1);
    const endMonthStart = new Date(endDate.getFullYear(), endDate.getMonth(), 1);

    return endMonthStart >= currentMonthStart; // solo no expirados
  });

  if (discountCandidates.length > 0) {
    discountCountEl.innerText = discountCandidates.length;
    discountListEl.innerHTML = '';

    discountCandidates.sort((a, b) => {
      const endA = a.discount_daterange.match(/\d{4}-\d{2}-\d{2}/g)?.[1];
      const endB = b.discount_daterange.match(/\d{4}-\d{2}-\d{2}/g)?.[1];
      return new Date(endA) - new Date(endB);
    });

    discountCandidates.forEach(c => {
      const endDate = c.discount_daterange.match(/\d{4}-\d{2}-\d{2}/g)?.[1];
      if (endDate) {
        const formattedEnd = new Date(endDate).toLocaleDateString('en-US', { year: 'numeric', month: 'short' });
        const li = document.createElement('li');
        const discountDollar = c.discount_dolar ? `$${c.discount_dolar}` : '';
        li.innerHTML = `💵 ${discountDollar} until <strong>${formattedEnd}</strong>`;
        discountListEl.appendChild(li);
      }
    });

    alertDiv.classList.remove("hidden");
  } else {
    alertDiv.classList.add("hidden");
  }

  // ------- Contract visual + persistencia -------
  let contractType = '—';
  if (hasStaffing && !hasRecruiting) {
    contractType = 'Staffing';
  } else if (!hasStaffing && hasRecruiting) {
    contractType = 'Recruiting';
  } else if (hasStaffing && hasRecruiting) {
    contractType = 'Mix';
  }

  const contractField = Array.from(document.querySelectorAll('#overview .accordion-content p'))
    .find(p => p.textContent.includes('Contract:'));
  if (contractField) {
    contractField.innerHTML = `<strong>Contract:</strong> ${contractType}`;
  }

  const accountId = getIdFromURL();
  if (accountId && contractType !== '—') {
    fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contract: contractType })
    })
    .then(res => {
      if (!res.ok) throw new Error('Error updating contract');
      console.log('✅ Contract updated to:', contractType);
    })
    .catch(err => console.error('❌ Error updating contract:', err));
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
        previewContainer.innerHTML = `
          <a href="${data.pdf_url}" target="_blank">📄 View uploaded PDF</a>
          <button id="deletePdfBtn" class="delete-pdf-btn">🗑️</button>
        `;
        document.getElementById("deletePdfBtn").addEventListener("click", deletePDF);
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
function deletePDF() {
  const accountId = getIdFromURL();
  if (!accountId) return;

  if (!confirm("Are you sure you want to delete this PDF?")) return;

  fetch(`https://7m6mw95m8y.us-east-2.awsapprunner.com/accounts/${accountId}/delete_pdf`, {
    method: "DELETE"
  })
  .then(res => {
    if (!res.ok) throw new Error("Failed to delete PDF");
    previewContainer.innerHTML = "";
    alert("PDF deleted successfully");
  })
  .catch(err => {
    console.error("Error deleting PDF:", err);
    alert("Failed to delete PDF");
  });
}
