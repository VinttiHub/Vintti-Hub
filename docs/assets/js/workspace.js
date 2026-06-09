/* =========================================================
   Workspace switch (Vintti / Vintti.ai / Todos)
   ---------------------------------------------------------
   "Hub dentro del hub": un switch global, recordado por usuario,
   que filtra las listas (opportunities, clients, candidates) por
   entidad. La detección es por email del owner (rápido, sin tocar
   la base): un registro es de vintti.ai si su sales lead / account
   manager está en VINTTI_AI_EMAILS (hoy = mia@vintti.com).

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

  /* ¿este registro pertenece al workspace activo? Recibe el/los
     email(s) de owner (sales lead, account manager, etc.). */
  function matchEmails(...emails) {
    const ws = get();
    if (ws === 'all') return true;
    const isAi = emails.some(isVinttiAiEmail);
    return ws === 'vintti_ai' ? isAi : !isAi;
  }

  /* Helper específico para una oportunidad (filtra por sales lead). */
  function matchOpp(opp) {
    return matchEmails(opp && opp.opp_sales_lead);
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
    get, set, isVinttiAiEmail, matchEmails, matchOpp, VINTTI_AI_EMAILS,
  };

  document.addEventListener('sidebar:loaded', () => { applyBodyAttr(); injectSwitch(); injectHeaderBadge(); });
  document.addEventListener('DOMContentLoaded', () => { applyBodyAttr(); injectSwitch(); injectHeaderBadge(); });
  applyBodyAttr();
})();
