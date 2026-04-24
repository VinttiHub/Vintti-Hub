const API_BASE =
  (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

(() => {
  const form = document.getElementById('referenceRequestForm');
  const candidateLabel = document.getElementById('candidateLabel');

  function qs(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function getCandidateIdFromUrl() {
    return qs('candidate_id') || qs('id') || null;
  }

  function getOpportunityIdFromUrl() {
    return qs('opportunity_id') || null;
  }

  function updateReview(context = {}) {
    const reviewCandidate = document.querySelector('[data-review="candidate_name"]');
    const reviewRef1 = document.querySelector('[data-review="reference_1_name"]');
    const reviewRef2 = document.querySelector('[data-review="reference_2_name"]');

    if (reviewCandidate) reviewCandidate.textContent = context.candidate_name || candidateLabel.textContent || '—';
    if (reviewRef1) reviewRef1.textContent = form.elements.reference_1_name.value || '—';
    if (reviewRef2) reviewRef2.textContent = form.elements.reference_2_name.value || '—';
  }

  async function loadContext() {
    const candidateId = getCandidateIdFromUrl();
    const opportunityId = getOpportunityIdFromUrl();
    if (!candidateId) {
      alert('Missing candidate_id in URL.');
      return null;
    }

    const url = new URL(`${API_BASE}/public/candidate_references/context`);
    url.searchParams.set('candidate_id', candidateId);
    if (opportunityId) url.searchParams.set('opportunity_id', opportunityId);

    const res = await fetch(url.toString());
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      alert(`Unable to load candidate context.\n${txt}`);
      return null;
    }

    const ctx = await res.json();
    candidateLabel.textContent = ctx.candidate_name || `Candidate #${candidateId}`;

    const refs = ctx.references || {};
    Object.entries(refs).forEach(([key, value]) => {
      if (form.elements[key] && value) form.elements[key].value = value;
    });

    updateReview({ candidate_name: ctx.candidate_name || '' });
    return ctx;
  }

  async function submitReferences(context = {}) {
    const candidateId = getCandidateIdFromUrl();
    if (!candidateId) {
      alert('Missing candidate_id in URL.');
      return;
    }

    const payload = Object.fromEntries(new FormData(form).entries());
    payload.candidate_id = Number(candidateId);
    payload.opportunity_id = context.opportunity_id || getOpportunityIdFromUrl() || null;

    const res = await fetch(`${API_BASE}/public/candidate_references/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      alert(`Something went wrong. Please try again.\n${txt}`);
      return;
    }

    form.reset();
    updateReview({ candidate_name: context.candidate_name || candidateLabel.textContent || '' });
    const successBox = document.querySelector('.success-box');
    if (successBox) {
      successBox.classList.remove('hidden');
      setTimeout(() => successBox.classList.add('hidden'), 3500);
    }
  }

  const successBox = document.createElement('div');
  successBox.className = 'success-box hidden';
  successBox.textContent = 'References submitted successfully.';
  form.prepend(successBox);

  let currentContext = null;
  form.addEventListener('input', () => updateReview(currentContext || {}));
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submitReferences(currentContext || {}).catch(console.error);
  });

  document.getElementById('btnClear')?.addEventListener('click', async () => {
    form.reset();
    currentContext = await loadContext();
  });

  loadContext()
    .then((ctx) => { currentContext = ctx; })
    .catch(console.error);
})();
