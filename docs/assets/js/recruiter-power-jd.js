/* Recruiter Power → pestaña "JD quality".
 *
 * Lee GET /jd_reviews/metrics con la misma ventana que el resto de la página y pinta la
 * tarjeta compartida de jd-review-cards.js. Va aparte de recruiter-power.js; de ahí usa
 * `metricsState` (rango y recruiter elegida), `API_BASE` y `cvqHeaders()`, que son globales
 * de ese script. recruiter-power.js la llama por window.JdQuality en tres momentos: al
 * abrir la pestaña, al cambiar el rango y al cambiar la recruiter.
 */
(function () {
  'use strict';

  const state = { loaded: false, byRecruiter: {}, totals: null, meta: null, error: null };

  async function fetchData() {
    state.error = null;
    try {
      const url = new URL(`${API_BASE}/jd_reviews/metrics`);
      if (metricsState.rangeStart) url.searchParams.set('desde', metricsState.rangeStart);
      if (metricsState.rangeEnd) url.searchParams.set('hasta', metricsState.rangeEnd);
      const resp = await fetch(url.toString(), { headers: cvqHeaders() });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      state.byRecruiter = {};
      (data.rows || []).forEach((row) => {
        const key = String(row.recruiter_email || '').trim().toLowerCase();
        if (key) state.byRecruiter[key] = row;
      });
      state.totals = data.totals || null;
      state.meta = data.meta || null;
      state.loaded = true;
    } catch (err) {
      state.loaded = false;
      state.error = err.message || String(err);
    }
    render();
  }

  function render() {
    const box = document.getElementById('jdqCards');
    const info = document.getElementById('jdqInfo');
    if (!box) return;
    if (state.error) {
      box.innerHTML = '';
      if (info) info.textContent = `Could not load JD quality: ${state.error}`;
      return;
    }
    if (!state.loaded) { box.innerHTML = ''; if (info) info.textContent = ''; return; }

    const selected = (metricsState.selectedLead || '').trim().toLowerCase();
    const row = selected ? state.byRecruiter[selected] : state.totals;
    const meta = state.meta || {};
    if (info) {
      info.textContent = `Window: ${meta.desde} — ${meta.hasta}.`
        + (meta.scoped_to_self ? ' Showing only your own JDs.' : '');
    }
    if (!row || !row.jds_sent) {
      box.innerHTML = '<p class="cvq-empty">No JD was sent to review in this window.</p>';
      return;
    }
    box.innerHTML = window.JdReviewCards.card(row, !selected);
  }

  window.JdQuality = {
    render,
    onShow() { if (!state.loaded) fetchData(); else render(); },
    onRangeChange(visible) { state.loaded = false; if (visible) fetchData(); },
  };
})();
