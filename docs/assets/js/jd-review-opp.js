/* JD Review desde la vacante: botón "Send JD to review" + chip de estado en la pestaña
 * Job Description de opportunity-detail.html.
 *
 * Va en su propio archivo (como la pestaña Metrics) para no sumar más a opportunity-detail.js.
 * Del otro archivo sólo usa formatJobDescriptionForHtml(), que es una función global.
 * La cola del sales lead vive en jd-review.html; el backend en routes/jd_review_routes.py.
 */
(function () {
  'use strict';

  const API = (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  const $ = (id) => document.getElementById(id);
  const me = () => (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase().trim();
  const headers = () => ({ 'Content-Type': 'application/json', 'X-User-Email': me() });
  const oppId = () => (new URLSearchParams(location.search).get('id') || '').trim();
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const who = (email) => String(email || '').split('@')[0] || 'the sales lead';

  let latest = null;
  let pollTimer = null;
  let polls = 0;

  function paint(reviews) {
    const chip = $('jdrOppChip');
    const comment = $('jdrOppComment');
    const cancel = $('jdrOppCancel');
    const send = $('jdrOppSend');
    latest = (reviews || []).find(r => r.status !== 'cancelled') || null;
    chip.className = 'jdr-chip';
    comment.hidden = true;
    cancel.hidden = true;
    send.disabled = false;

    if (!latest) {
      chip.textContent = 'Not reviewed yet';
      send.textContent = 'Send JD to review';
      return;
    }
    const score = (latest.ai_score !== null && latest.ai_score !== undefined)
      ? ` · coverage ${latest.ai_score}/100` : (latest.ai_pending ? ' · scoring…' : '');

    if (latest.status === 'pending') {
      chip.classList.add('is-pending');
      chip.textContent = `Waiting for sales review · round ${latest.round}${score}`;
      cancel.hidden = false;
      send.disabled = true;
      send.textContent = 'Sent to review';
    } else if (latest.status === 'approved') {
      chip.classList.add('is-approved');
      chip.textContent = `Approved by ${who(latest.reviewed_by)}${score}`
        + (latest.jd_changed_since ? ' · JD edited since' : '');
      send.textContent = latest.jd_changed_since ? 'Send the new version to review' : 'Send JD to review';
    } else if (latest.status === 'changes_requested') {
      chip.classList.add('is-changes');
      chip.textContent = `Changes requested by ${who(latest.reviewed_by)} · round ${latest.round}`;
      send.textContent = 'Send the fixed JD to review';
      if (latest.reviewer_comment) {
        comment.innerHTML = `<b>What to change:</b> ${esc(latest.reviewer_comment)}`;
        comment.hidden = false;
      }
    }
  }

  function load() {
    const id = oppId();
    if (!id) return Promise.resolve();
    return fetch(`${API}/opportunities/${id}/jd_reviews`, { headers: headers() })
      .then(r => r.ok ? r.json() : { reviews: [] })
      .then(d => {
        paint(d.reviews || []);
        clearTimeout(pollTimer);
        // Después de enviar, el score tarda ~1 min: se refresca el chip un rato.
        if (latest && latest.ai_pending && polls < 15) {
          polls += 1;
          pollTimer = setTimeout(load, 10000);
        }
      })
      .catch(() => {});
  }

  async function send() {
    const id = oppId();
    const btn = $('jdrOppSend');
    const editor = $('job-description-textarea');
    if (!id || !editor) return;
    const fmt = typeof formatJobDescriptionForHtml === 'function' ? formatJobDescriptionForHtml : (h) => h;
    const html = fmt(editor.innerHTML || '');
    if (!String(editor.textContent || '').trim()) {
      alert('Write or generate the job description first.');
      return;
    }
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = 'Sending…';
    try {
      // Se guarda primero lo que está en el editor: el review congela la JD de la base, y
      // el blur que la guarda no corre si la recruiter hace click directo en este botón.
      const save = await fetch(`${API}/opportunities/${id}/fields`, {
        method: 'PATCH', headers: headers(), body: JSON.stringify({ hr_job_description: html }),
      });
      if (!save.ok) throw new Error('Could not save the job description.');

      const r = await fetch(`${API}/opportunities/${id}/jd_reviews`, {
        method: 'POST', headers: headers(),
        body: JSON.stringify({ note: ($('jdrOppNote').value || '').trim() }),
      });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) {
        alert(out.error || `Could not send it (HTTP ${r.status}).`);
      } else {
        $('jdrOppNote').value = '';
        alert('✅ Sent. The sales lead gets an email with the AI check in about a minute.');
      }
      polls = 0;
      await load();
    } catch (err) {
      alert(err.message);
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  function cancelReview() {
    if (!latest || latest.status !== 'pending') return;
    if (!confirm('Cancel this review? The sales lead will no longer see it in the queue.')) return;
    fetch(`${API}/jd_reviews/${latest.review_id}/cancel`, { method: 'POST', headers: headers() })
      .then(async r => {
        if (!r.ok) {
          const out = await r.json().catch(() => ({}));
          alert(out.error || `HTTP ${r.status}`);
        }
      })
      .finally(load);
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!$('jdrOppSend')) return;
    $('jdrOppSend').addEventListener('click', send);
    $('jdrOppCancel').addEventListener('click', cancelReview);
    load();
  });
})();
