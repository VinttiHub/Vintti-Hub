const API_BASE =
  (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

(() => {
  const form = document.getElementById('referenceFeedbackForm');
  const candidateLabel = document.getElementById('feedbackCandidateLabel');
  const referenceLabel = document.getElementById('feedbackReferenceLabel');
  const questionsHost = document.getElementById('referenceFeedbackQuestions');

  function qs(name) {
    return new URLSearchParams(window.location.search).get(name);
  }

  function getToken() {
    return qs('t');
  }

  function getEncodedData() {
    return qs('data');
  }

  function getApiBase(context = null) {
    return context?.api_base || API_BASE;
  }

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function renderQuestions(questions = [], answers = []) {
    questionsHost.innerHTML = questions.map((question, index) => `
      <label class="feedback-question">
        <span>${index + 1}. ${escapeHtml(question)}</span>
        <textarea name="answer_${index + 1}" rows="4" required>${escapeHtml(answers[index] || '')}</textarea>
      </label>
    `).join('');
  }

  function decodePayload(value) {
    try {
      return JSON.parse(decodeURIComponent(escape(atob(value))));
    } catch {
      return null;
    }
  }

  function stripFeedbackNotes(html = '') {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = html || '';
    const notesBlock = wrapper.querySelector('[data-reference-feedback-notes="true"]');
    if (notesBlock) notesBlock.remove();
    return wrapper.innerHTML.trim();
  }

  function buildFeedbackSectionHtml(context, answers = []) {
    const questions = context.questions || [];
    const items = questions.map((question, index) => `
      <div data-reference-feedback-item="${context.reference_number}-${index + 1}">
        <strong>Question -</strong> ${escapeHtml(question)}<br>
        <strong>Feedback -</strong> ${escapeHtml(answers[index] || '')}
      </div>
    `).join('<br>');
    return `
      <section data-reference-feedback-section="${context.reference_number}">
        <p>----------------------------------------</p>
        <p><strong>Reference ${context.reference_number}${context.reference_name ? ` - ${escapeHtml(context.reference_name)}` : ''}</strong></p>
        ${items}
      </section>
    `;
  }

  function mergeFeedbackIntoNotes(existingNotes, context, answers = []) {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = existingNotes || '';

    let feedbackRoot = wrapper.querySelector('[data-reference-feedback-notes="true"]');
    if (!feedbackRoot) {
      feedbackRoot = document.createElement('div');
      feedbackRoot.setAttribute('data-reference-feedback-notes', 'true');
      wrapper.appendChild(feedbackRoot);
    }

    feedbackRoot.querySelector(`[data-reference-feedback-section="${context.reference_number}"]`)?.remove();

    const temp = document.createElement('div');
    temp.innerHTML = buildFeedbackSectionHtml(context, answers);
    const section = temp.firstElementChild;
    if (section) feedbackRoot.appendChild(section);

    const baseNotes = stripFeedbackNotes(existingNotes);
    const feedbackHtml = feedbackRoot.innerHTML.trim() ? feedbackRoot.outerHTML : '';
    return [baseNotes, feedbackHtml].filter(Boolean).join('<br>');
  }

  async function loadContext() {
    const token = getToken();
    const encodedData = getEncodedData();
    if (encodedData) {
      const payload = decodePayload(encodedData);
      if (!payload) {
        alert('Unable to decode the feedback form data.');
        return null;
      }
      candidateLabel.textContent = payload.candidate_name || 'Candidate';
      referenceLabel.textContent = payload.reference_name || `Reference ${payload.reference_number}`;
      renderQuestions(payload.questions || [], payload.answers || []);
      return payload;
    }
    if (!token) {
      alert('Missing token or form data in URL.');
      return null;
    }

    const res = await fetch(`${getApiBase()}/public/reference_feedback/context?t=${encodeURIComponent(token)}`);
    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      alert(`Unable to load the feedback form.\n${txt}`);
      return null;
    }

    const ctx = await res.json();
    candidateLabel.textContent = ctx.candidate_name || 'Candidate';
    referenceLabel.textContent = ctx.reference_name || `Reference ${ctx.reference_number}`;
    renderQuestions(ctx.questions || [], ctx.answers || []);
    return ctx;
  }

  async function submitFeedback(context = {}) {
    const token = getToken();
    const answers = Array.from(questionsHost.querySelectorAll('textarea')).map((textarea) => textarea.value.trim());
    let res;
    if (token) {
      res = await fetch(`${getApiBase(context)}/public/reference_feedback/submit?t=${encodeURIComponent(token)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers }),
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        alert(`Something went wrong. Please try again.\n${txt}`);
        return;
      }
    } else {
      if (!context.candidate_id) {
        alert('Missing candidate data in this form.');
        return;
      }

      const apiBase = getApiBase(context);
      const candidateRes = await fetch(`${apiBase}/candidates/${encodeURIComponent(context.candidate_id)}`);
      if (!candidateRes.ok) {
        const txt = await candidateRes.text().catch(() => '');
        alert(`Unable to load current candidate notes.\n${txt}`);
        return;
      }

      const candidateData = await candidateRes.json();
      const mergedNotes = mergeFeedbackIntoNotes(candidateData.references_notes || '', context, answers);

      res = await fetch(`${apiBase}/candidates/${encodeURIComponent(context.candidate_id)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          references_notes: mergedNotes,
        }),
      });
      if (!res.ok) {
        const txt = await res.text().catch(() => '');
        alert(`Unable to save feedback.\n${txt}`);
        return;
      }

      const persistRes = await fetch(`${apiBase}/public/reference_feedback/direct_submit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_id: context.candidate_id,
          opportunity_id: context.opportunity_id || null,
          reference_number: context.reference_number,
          reference_name: context.reference_name || '',
          reference_position: context.reference_position || '',
          reference_email: context.reference_email || '',
          reference_phone: context.reference_phone || '',
          reference_linkedin: context.reference_linkedin || '',
          candidate_name: context.candidate_name || '',
          questions: context.questions || [],
          answers,
        }),
      });
      if (!persistRes.ok) {
        const txt = await persistRes.text().catch(() => '');
        alert(`Feedback was saved to the candidate notes, but the structured record could not be stored.\n${txt}`);
        return;
      }
    }

    const successBox = document.querySelector('.success-box');
    if (successBox) {
      successBox.classList.remove('hidden');
      setTimeout(() => successBox.classList.add('hidden'), 3500);
    }

    loadContext().then((fresh) => {
      currentContext = fresh || context;
    }).catch(console.error);
  }

  const successBox = document.createElement('div');
  successBox.className = 'success-box hidden';
  successBox.textContent = 'Feedback submitted successfully.';
  form.prepend(successBox);

  let currentContext = null;
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    submitFeedback(currentContext || {}).catch(console.error);
  });

  loadContext()
    .then((ctx) => {
      currentContext = ctx;
    })
    .catch(console.error);
})();
