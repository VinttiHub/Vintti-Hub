const API_BASE =
  (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

(() => {
  const form = document.getElementById('referenceRequestForm');
  const candidateLabel = document.getElementById('candidateLabel');
  const referenceCard1 = document.getElementById('referenceCard1');
  const referenceCard2 = document.getElementById('referenceCard2');
  const addAnotherWrap = document.getElementById('referenceAddAnotherWrap');
  const addAnotherButton = document.getElementById('btnAddReference');

  function getReferenceFieldNames(idx) {
    return [
      `reference_${idx}_name`,
      `reference_${idx}_position`,
      `reference_${idx}_phone`,
      `reference_${idx}_email`,
      `reference_${idx}_linkedin`,
    ];
  }

  function setReferenceRequired(idx, required) {
    getReferenceFieldNames(idx).forEach((field) => {
      if (form.elements[field]) form.elements[field].required = required;
    });
  }

  function isReferenceComplete(refs = {}, idx) {
    return getReferenceFieldNames(idx).every((field) => String(refs[field] || '').trim());
  }

  function toggleReference2(isVisible) {
    if (referenceCard2) referenceCard2.hidden = !isVisible;
    setReferenceRequired(2, isVisible);
    if (addAnotherWrap) {
      addAnotherWrap.hidden = isVisible;
      addAnotherWrap.style.display = isVisible ? 'none' : '';
    }
  }

  function applyReferenceLayout(context = {}) {
    const refs = context.references || {};
    const ref1Complete = isReferenceComplete(refs, 1);
    const ref2Complete = isReferenceComplete(refs, 2);
    const nextSlot = Number(context.next_reference_slot) || (ref1Complete ? 2 : 1);

    setReferenceRequired(1, !ref1Complete || nextSlot === 1);

    if (!ref1Complete && !ref2Complete) {
      if (referenceCard1) referenceCard1.hidden = false;
      toggleReference2(false);
      return;
    }

    if (ref1Complete && !ref2Complete) {
      if (referenceCard1) referenceCard1.hidden = true;
      toggleReference2(true);
      return;
    }

    if (!ref1Complete && ref2Complete) {
      if (referenceCard1) referenceCard1.hidden = false;
      toggleReference2(false);
      return;
    }

    if (referenceCard1) referenceCard1.hidden = false;
    toggleReference2(true);
  }

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

    applyReferenceLayout(ctx);
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
    currentContext = await loadContext();
    updateReview({ candidate_name: currentContext?.candidate_name || context.candidate_name || candidateLabel.textContent || '' });
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

  addAnotherButton?.addEventListener('click', () => {
    toggleReference2(true);
    const ref2Name = form.elements.reference_2_name;
    if (ref2Name) ref2Name.focus();
    updateReview(currentContext || {});
  });

  loadContext()
    .then((ctx) => { currentContext = ctx; })
    .catch(console.error);
})();
