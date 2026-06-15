/* =========================================================
   Workspace switch (Vintti / Vintti.ai / Todos)
   ---------------------------------------------------------
   "Hub dentro del hub": un switch global, recordado por usuario,
   que filtra las listas (opportunities, clients, candidates) por
   entidad. La fuente de verdad es el booleano vintti_ai sincronizado
   desde HubSpot. El email del owner se conserva como fallback para
   respuestas antiguas que todavía no incluyan ese campo.

   Estados: 'all' (todo, default) | 'vintti' | 'vintti_ai'.
   Al cambiar se guarda en localStorage y se recarga la página para
   que todas las vistas se re-filtren de forma consistente.
   ========================================================= */
(() => {
  if (window.Workspace) return;

  const KEY   = 'workspace';
  const VALID = new Set(['all', 'vintti', 'vintti_ai']);

  // Emails que pertenecen a vintti.ai. Para sumar gente al equipo
  // vintti.ai basta con agregar su email aquí.
  const VINTTI_AI_EMAILS = new Set([
    'mia@vintti.com',
  ]);

  const norm = (s) => String(s || '').toLowerCase().trim();

  function get() {
    const v = norm(localStorage.getItem(KEY) || 'all');
    return VALID.has(v) ? v : 'all';
  }

  function isVinttiAiEmail(email) {
    return VINTTI_AI_EMAILS.has(norm(email));
  }

  function parseBoolean(value) {
    if (typeof value === 'boolean') return value;
    if (typeof value === 'number') return value === 1;
    const normalized = norm(value);
    if (['true', 't', '1', 'yes', 'y', 'si', 'sí'].includes(normalized)) return true;
    if (['false', 'f', '0', 'no', 'n'].includes(normalized)) return false;
    return null;
  }

  function matchRecord(vinttiAi, ...fallbackEmails) {
    const ws = get();
    if (ws === 'all') return true;
    const parsed = parseBoolean(vinttiAi);
    const isAi = parsed === null ? fallbackEmails.some(isVinttiAiEmail) : parsed;
    return ws === 'vintti_ai' ? isAi : !isAi;
  }

  function decorateRow(row, vinttiAi, targetCell, ...fallbackEmails) {
    if (!row) return false;
    const parsed = parseBoolean(vinttiAi);
    const isAi = parsed === null ? fallbackEmails.some(isVinttiAiEmail) : parsed;
    if (!isAi) return false;
    row.classList.add('vintti-ai-row');
    const badgeCell = targetCell || row.querySelector('.vintti-ai-badge-cell');
    if (!badgeCell || badgeCell.querySelector('.vintti-ai-row-badge')) return true;
    const badge = document.createElement('span');
    badge.className = 'vintti-ai-row-badge';
    badge.textContent = '✨🤖';
    badge.title = 'Vintti AI';
    badge.setAttribute('aria-label', 'Vintti AI');
    badgeCell.classList.add('vintti-ai-badge-cell');
    badgeCell.insertBefore(badge, badgeCell.firstChild);
    return true;
  }

  /* ¿este registro pertenece al workspace activo? Recibe el/los
     email(s) de owner (sales lead, account manager, etc.). */
  function matchEmails(...emails) {
    return matchRecord(null, ...emails);
  }

  /* Helper específico para una oportunidad (filtra por sales lead). */
  function matchOpp(opp) {
    return matchRecord(opp && opp.vintti_ai, opp && opp.opp_sales_lead);
  }

  function set(value) {
    const v = VALID.has(value) ? value : 'all';
    if (v === get()) return;
    localStorage.setItem(KEY, v);
    applyBodyAttr();
    location.reload();
  }

  function applyBodyAttr() {
    if (document.body) document.body.setAttribute('data-workspace', get());
  }

  /* -------- UI: badge en el título del header (por página) -------- */
  const BADGE = {
    all:       'All ⚡️',
    vintti:    'Vintti 🚀',
    vintti_ai: 'Vintti.ai ✨',
  };

  function injectHeaderBadge() {
    const title = document.querySelector('.page-header .page-title');
    if (!title) return;
    const ws = get();
    let badge = title.querySelector('.ws-badge');
    if (!badge) {
      badge = document.createElement('span');
      badge.className = 'ws-badge';
      title.appendChild(badge);
    }
    badge.setAttribute('data-ws', ws);
    badge.textContent = BADGE[ws] || BADGE.all;
  }

  /* -------- UI: segmented control dentro del sidebar -------- */
  const OPTIONS = [
    { value: 'all',       label: 'All',     short: 'All' },
    { value: 'vintti',    label: 'Vintti',    short: 'V'   },
    { value: 'vintti_ai', label: 'Vintti.ai', short: 'AI'  },
  ];

  function injectSwitch() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    if (sidebar.querySelector('.ws-switch')) return; // ya inyectado
    const nav = sidebar.querySelector('.sidebar-nav');
    if (!nav) return;

    const active = get();
    const wrap = document.createElement('div');
    wrap.className = 'ws-switch';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Workspace');
    wrap.innerHTML = OPTIONS.map(o => `
      <button type="button" class="ws-opt${o.value === active ? ' is-active' : ''}"
              data-ws="${o.value}" title="${o.label}" aria-pressed="${o.value === active}">
        <span class="ws-opt-label">${o.label}</span>
        <span class="ws-opt-short" aria-hidden="true">${o.short}</span>
      </button>`).join('');

    nav.insertBefore(wrap, nav.firstChild);

    wrap.addEventListener('click', (e) => {
      const btn = e.target.closest('.ws-opt');
      if (!btn) return;
      set(btn.getAttribute('data-ws'));
    });
  }

  window.Workspace = {
    get, set, isVinttiAiEmail, matchRecord, matchEmails, matchOpp, decorateRow, VINTTI_AI_EMAILS,
  };

  document.addEventListener('sidebar:loaded', () => { applyBodyAttr(); injectSwitch(); injectHeaderBadge(); });
  document.addEventListener('DOMContentLoaded', () => { applyBodyAttr(); injectSwitch(); injectHeaderBadge(); });
  applyBodyAttr();
})();
