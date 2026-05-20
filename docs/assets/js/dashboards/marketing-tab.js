/**
 * Marketing tab — fetches /metrics/marketing_dashboard once when the tab is
 * first activated and renders the three cards (SQLs by channel, Active
 * Clients by channel, Open Opportunities by industry).
 */
(() => {
  const API = (window.API_BASE || 'https://7m6mw95m8y.us-east-2.awsapprunner.com').replace(/\/$/, '');
  const INT = new Intl.NumberFormat('en-US');
  const DATE_SHORT = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });
  const DATE_LONG = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  const state = {
    loaded: false,
    loading: false,
    sqlsByChannel: null,
    activeClientsByChannel: null,
    openOpportunitiesByIndustry: null,
    period: 'thisMonth',
  };

  function fmtInt(v){ return INT.format(Number(v) || 0); }
  function fmtMoney(v){ return '$' + (Number(v) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 }); }
  function parseDate(v){
    if (!v) return null;
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  function fmtRange(fromStr, toStr){
    const a = parseDate(fromStr), b = parseDate(toStr);
    if (!a || !b) return '—';
    const sameYear = a.getFullYear() === b.getFullYear();
    const left = sameYear ? DATE_SHORT.format(a) : DATE_LONG.format(a);
    return `${left} → ${DATE_LONG.format(b)}`;
  }
  function fmtFullDate(v){
    const d = parseDate(v);
    return d ? DATE_LONG.format(d) : '—';
  }
  function escapeHtml(s){
    return String(s ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function shareCell(value, total){
    const pct = total > 0 ? (value / total) * 100 : 0;
    return `
      <div class="mkt-share">
        <span class="mkt-share__bar" style="--pct:${pct.toFixed(2)}%"></span>
        <span class="mkt-share__pct">${pct.toFixed(1)}%</span>
      </div>
    `;
  }

  function renderSqls(){
    const summary = state.sqlsByChannel;
    const tbody = document.getElementById('mktSqlsTbody');
    const totalEl = document.getElementById('mktSqlsTotal');
    const rangeEl = document.getElementById('mktSqlsRange');
    if (!summary || !tbody) return;

    const bucket = summary[state.period] || { total: 0, channels: [] };
    if (totalEl) totalEl.textContent = fmtInt(bucket.total || 0);
    if (rangeEl) rangeEl.textContent = fmtRange(bucket.from, bucket.to);

    const channels = Array.isArray(bucket.channels) ? bucket.channels : [];
    if (!channels.length){
      tbody.innerHTML = '<tr><td colspan="3" class="muted">No SQLs in this period.</td></tr>';
      return;
    }
    tbody.innerHTML = channels.map(c => `
      <tr>
        <td>${escapeHtml(c.channel)}</td>
        <td>${fmtInt(c.count)}</td>
        <td>${shareCell(c.count, bucket.total)}</td>
      </tr>
    `).join('');
  }

  function renderActive(){
    const summary = state.activeClientsByChannel;
    const tbody = document.getElementById('mktActiveTbody');
    const totalEl = document.getElementById('mktActiveTotal');
    const asOfEl = document.getElementById('mktActiveAsOf');
    if (!summary || !tbody) return;

    if (totalEl) totalEl.textContent = fmtInt(summary.total || 0);
    if (asOfEl) asOfEl.textContent = summary.asOf ? `As of ${fmtFullDate(summary.asOf)}` : 'As of —';

    const channels = Array.isArray(summary.channels) ? summary.channels : [];
    if (!channels.length){
      tbody.innerHTML = '<tr><td colspan="3" class="muted">No active clients yet.</td></tr>';
      return;
    }
    tbody.innerHTML = channels.map(c => `
      <tr>
        <td>${escapeHtml(c.channel)}</td>
        <td>${fmtInt(c.count)}</td>
        <td>${shareCell(c.count, summary.total)}</td>
      </tr>
    `).join('');
  }

  function renderOpps(){
    const summary = state.openOpportunitiesByIndustry;
    const tbody = document.getElementById('mktOppsTbody');
    const totalEl = document.getElementById('mktOppsTotal');
    if (!summary || !tbody) return;

    if (totalEl) totalEl.textContent = fmtInt(summary.total || 0);

    const industries = Array.isArray(summary.industries) ? summary.industries : [];
    if (!industries.length){
      tbody.innerHTML = '<tr><td colspan="3" class="muted">No open opportunities.</td></tr>';
      return;
    }
    tbody.innerHTML = industries.map(ind => `
      <tr>
        <td>${escapeHtml(ind.industry)}</td>
        <td>${fmtInt(ind.count)}</td>
        <td>${fmtMoney(ind.expected_revenue || 0)}</td>
      </tr>
    `).join('');
  }

  function renderAll(){
    renderSqls();
    renderActive();
    renderOpps();
  }

  async function load(){
    if (state.loaded || state.loading) return;
    state.loading = true;
    try {
      const r = await fetch(`${API}/metrics/marketing_dashboard`, { cache: 'no-store' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      state.sqlsByChannel = data?.sqlsByChannel || null;
      state.activeClientsByChannel = data?.activeClientsByChannel || null;
      state.openOpportunitiesByIndustry = data?.openOpportunitiesByIndustry || null;
      state.loaded = true;
      renderAll();
    } catch (err) {
      console.warn('Marketing metrics load error:', err);
      ['mktSqlsTbody', 'mktActiveTbody', 'mktOppsTbody'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = `<tr><td colspan="3" class="muted">Error: ${escapeHtml(err.message || 'unknown')}</td></tr>`;
      });
    } finally {
      state.loading = false;
    }
  }

  function bindPeriodSwitch(){
    document.querySelectorAll('#mktSqlsCard .mkt-period__btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const period = btn.dataset.period;
        if (!period || period === state.period) return;
        state.period = period;
        document.querySelectorAll('#mktSqlsCard .mkt-period__btn').forEach(b => {
          const on = b === btn;
          b.classList.toggle('is-active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        renderSqls();
      });
    });
  }

  function bindTabActivation(){
    const radio = document.getElementById('tab-marketing');
    if (!radio) return;
    // Load when the tab becomes active (lazy)
    radio.addEventListener('change', () => { if (radio.checked) load(); });
    // Also handle the case where the page loads with the marketing tab already selected
    if (radio.checked) load();
  }

  function init(){
    bindPeriodSwitch();
    bindTabActivation();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
