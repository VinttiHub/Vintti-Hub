document.addEventListener("DOMContentLoaded", () => {
  const savedTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);

  // Obtener candidate_id de la URL
  const urlParams = new URLSearchParams(window.location.search);
  const candidateId = urlParams.get('id');

  if (!candidateId) {
    console.error("❌ No candidate ID provided");
    return;
  }

  // Traer datos del candidato
  fetch(`https://hkvmyif7s2.us-east-2.awsapprunner.com/candidates/${candidateId}`)
    .then(response => response.json())
    .then(data => {
      if (data.error) {
        console.error("❌ Error fetching candidate:", data.error);
        return;
      }

      // Llenar los campos
      document.querySelectorAll('#overview .field').forEach(field => {
        const label = field.querySelector('label');
        const div = field.querySelector('div');
        const id = label ? label.textContent.trim().toLowerCase() : '';

        switch (id) {
          case 'name':
            div.textContent = data.name || '—';
            break;
          case 'country':
            div.textContent = data.country || '—';
            break;
          case 'phone number':
            div.textContent = data.phone || '—';
            break;
          case 'email':
            div.textContent = data.email || '—';
            break;
          case 'linkedin':
            const linkedinLink = document.getElementById('linkedin');
            if (linkedinLink) {
              linkedinLink.href = data.linkedin || '#';
            }
            break;
          case 'english level':
            div.textContent = data.english_level || '—';
            break;
          case 'min salary':
            div.textContent = data.salary_range || '—';
            break;
        }
      });

      // Red Flags y Comments (que son textareas)
      document.getElementById('redFlags').value = data.red_flags || '';
      document.getElementById('comments').value = data.comments || '';
    })
    .catch(err => {
      console.error('❌ Error fetching candidate:', err);
    });
});

// Código para tabs (ya tenías esto bien)
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    const tabId = tab.dataset.tab;

    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

    tab.classList.add('active');
    document.getElementById(tabId).classList.add('active');
  });
});
