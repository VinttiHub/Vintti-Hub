(() => {
  const SIDEBAR_HTML_PATH = './sidebar.html';

  window.API_BASE = window.API_BASE || 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const apiBase = window.API_BASE;

  /* -------------------------
     Utils
  ------------------------- */
  function getCurrentUserEmailSafe() {
    return (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
      .toLowerCase()
      .trim();
  }

  function waitForUserEmail(maxMs = 2000) {
    const start = Date.now();
    return new Promise(resolve => {
      (function check() {
        const email = getCurrentUserEmailSafe();
        if (email || Date.now() - start > maxMs) return resolve(email);
        setTimeout(check, 50);
      })();
    });
  }

  function initialsFromName(name = '') {
    const parts = String(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '—';
    const a = (parts[0]?.[0] || '').toUpperCase();
    const b = (parts[1]?.[0] || '').toUpperCase();
    return (a + b) || a || '—';
  }

  function initialsFromEmail(email = '') {
    const local = String(email).split('@')[0] || '';
    if (!local) return '—';
    const bits = local.split(/[._-]+/).filter(Boolean);
    return (bits.length >= 2)
      ? (bits[0][0] + bits[1][0]).toUpperCase()
      : local.slice(0, 2).toUpperCase();
  }

  /* -------------------------
     USER ID resolver (cache)
  ------------------------- */
  async function getCurrentUserId({ force = false } = {}) {
    const email = getCurrentUserEmailSafe();

    const cachedUid = localStorage.getItem('user_id');
    const cachedOwner = localStorage.getItem('user_id_owner_email');

    if (force || (cachedOwner && cachedOwner !== email)) {
      localStorage.removeItem('user_id');
    }

    const cached = localStorage.getItem('user_id');
    if (cached) return Number(cached);
    if (!email) return null;

    // 1) endpoint directo por email si existe
    try {
      const r = await fetch(`${apiBase}/users?email=${encodeURIComponent(email)}`, { credentials: 'include' });
      if (r.ok) {
        const arr = await r.json();
        const hit = Array.isArray(arr) ? arr.find(u => (u.email_vintti || '').toLowerCase() === email) : null;
        if (hit?.user_id != null) {
          localStorage.setItem('user_id', String(hit.user_id));
          localStorage.setItem('user_id_owner_email', email);
          return Number(hit.user_id);
        }
      }
    } catch {}

    // 2) fallback: traer users y matchear
    try {
      const r = await fetch(`${apiBase}/users`, { credentials: 'include' });
      if (!r.ok) return null;
      const users = await r.json();
      const me = (users || []).find(u => String(u.email_vintti || '').toLowerCase() === email);
      if (me?.user_id != null) {
        localStorage.setItem('user_id', String(me.user_id));
        localStorage.setItem('user_id_owner_email', email);
        return Number(me.user_id);
      }
    } catch {}

    return null;
  }

  window.getCurrentUserId = window.getCurrentUserId || getCurrentUserId;

  /* -------------------------
     Permissions
  ------------------------- */
  function applySidebarVisibility() {
    const email = getCurrentUserEmailSafe();
    if (!email) return;

    const setDisplay = (id, ok) => {
      const el = document.getElementById(id);
      if (el) el.style.display = ok ? 'flex' : 'none';
    };

    setDisplay('candidateSearchLink', new Set([
      'agustina.barbero@vintti.com','agustin@vintti.com','lara@vintti.com','constanza@vintti.com',
      'pilar@vintti.com','pilar.fernandez@vintti.com','angie@vintti.com','agostina@vintti.com',
      'julieta@vintti.com','paz@vintti.com'
    ]).has(email));

    setDisplay('salesLink', new Set([
      'agustin@vintti.com','angie@vintti.com','lara@vintti.com','bahia@vintti.com','mariano@vintti.com'
    ]).has(email));

    const dashOk = new Set([
      'agustin@vintti.com','angie@vintti.com','lara@vintti.com','bahia@vintti.com',
      'agostina@vintti.com','mia@vintti.com','jazmin@vintti.com'
    ]).has(email);
    setDisplay('dashboardLink', dashOk);
    setDisplay('managementMetricsLink', dashOk);

    setDisplay('recruiterPowerLink', new Set([
      'angie@vintti.com','agostina@vintti.com','agustin@vintti.com','lara@vintti.com','agustina.barbero@vintti.com',
      'constanza@vintti.com','pilar@vintti.com','pilar.fernandez@vintti.com','julieta@vintti.com','paz@vintti.com'
    ]).has(email));

    setDisplay('equipmentsLink', new Set([
      'angie@vintti.com','jazmin@vintti.com','agustin@vintti.com','lara@vintti.com'
    ]).has(email));

    // Summary link
    const summaryLink = document.getElementById('summaryLink');
    const allowedEmails = new Set([
      'agustin@vintti.com','bahia@vintti.com','angie@vintti.com','lara@vintti.com',
      'agostina@vintti.com','mariano@vintti.com','jazmin@vintti.com'
    ]);
    if (summaryLink) summaryLink.style.display = allowedEmails.has(email) ? 'flex' : 'none';
  }

  /* -------------------------
     Collapse + tooltips
  ------------------------- */
  function setupSidebarCollapse() {
    const sidebarEl = document.querySelector('.sidebar');
    const toggleBtn = document.getElementById('sidebarMiniToggle');
    if (!sidebarEl || !toggleBtn) return;

    sidebarEl.querySelectorAll('.menu-item').forEach(item => {
      const label = item.querySelector('.menu-label')?.textContent?.trim();
      if (label) item.setAttribute('data-tooltip', label);
    });

    // const saved = localStorage.getItem('sidebarCollapsed') === 'true';
    // sidebarEl.classList.toggle('collapsed', saved);

    // ✅ Siempre iniciar colapsada
    const saved = true;
    sidebarEl.classList.toggle('collapsed', saved);

// (opcional) forzar el valor en storage para que quede consistente
localStorage.setItem('sidebarCollapsed', 'true');


    toggleBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const collapsed = !sidebarEl.classList.contains('collapsed');
      sidebarEl.classList.toggle('collapsed', collapsed);
      localStorage.setItem('sidebarCollapsed', String(collapsed));
    });
  }

  function setupSidebarTooltips() {
  const sidebarEl = document.querySelector('.sidebar');
  if (!sidebarEl) return;

  // Crear tooltip global una sola vez
  let tooltip = document.querySelector('.sidebar-tooltip');
  if (!tooltip) {
    tooltip = document.createElement('div');
    tooltip.className = 'sidebar-tooltip';
    document.body.appendChild(tooltip);
  }

  let currentItem = null;

  function showFor(item) {
    if (!sidebarEl.classList.contains('collapsed')) return hide();

    const text = (item.getAttribute('data-tooltip') || '').trim();
    if (!text) return hide();

    tooltip.textContent = text;

    const r = item.getBoundingClientRect();
    tooltip.style.left = `${r.right + 12}px`;
    tooltip.style.top  = `${r.top + r.height / 2}px`;

    tooltip.classList.add('is-visible');
    currentItem = item;
  }

  function hide() {
    tooltip.classList.remove('is-visible');
    currentItem = null;
  }

  sidebarEl.addEventListener('mouseover', (e) => {
    const item = e.target.closest('.menu-item');
    if (!item || !sidebarEl.contains(item)) return;
    showFor(item);
  });

  sidebarEl.addEventListener('mouseout', (e) => {
    const item = e.target.closest('.menu-item');
    if (!item) return;

    // Si aún estamos dentro del mismo item, no esconderr
    const to = e.relatedTarget;
    if (to && item.contains(to)) return;

    hide();
  });

  // Si scrollea, reposiciona o esconde
  const scroller = sidebarEl.querySelector('.sidebar-scroll');
  if (scroller) {
    scroller.addEventListener('scroll', () => {
      if (currentItem) showFor(currentItem);
    }, { passive: true });
  }

  // Si cambia collapsed/expanded, esconder
  const toggleBtn = document.getElementById('sidebarMiniToggle');
  if (toggleBtn) toggleBtn.addEventListener('click', hide);
}


  /* -------------------------
     Profile tile (avatar + name)
  ------------------------- */
  async function initSidebarProfile() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;

    let tile = document.getElementById('sidebarProfile');
    if (!tile) {
      sidebar.insertAdjacentHTML('beforeend', `
        <a href="profile.html" class="profile-tile" id="sidebarProfile">
          <span class="profile-avatar">
            <img id="profileAvatarImg" alt="" />
            <span id="profileAvatarInitials" class="profile-initials" aria-hidden="true">—</span>
          </span>
          <span class="profile-meta">
            <span id="profileName" class="profile-name">Profile</span>
            <span id="profileEmail" class="profile-email"></span>
          </span>
        </a>
      `);
      tile = document.getElementById('sidebarProfile');
    }
    if (!tile) return;

    const $init  = document.getElementById('profileAvatarInitials');
    const $name  = document.getElementById('profileName');
    const $emailE= document.getElementById('profileEmail');
    const $img   = document.getElementById('profileAvatarImg');

    if ($emailE) { $emailE.textContent = ''; $emailE.style.display = 'none'; }

    const email = getCurrentUserEmailSafe();

    const showInitials = (value) => {
      if (!$init || !$img) return;
      $init.style.display = 'grid';
      $init.textContent = value || '—';
      $img.removeAttribute('src');
      $img.style.display = 'none';
    };

    const showAvatar = (src) => {
      if (!$img || !$init) return;
      if (src) {
        $img.src = src;
        $img.style.display = 'block';
        $init.style.display = 'none';
      } else {
        showInitials($init?.textContent || initialsFromEmail(email));
      }
    };

    // initials rápido
    if ($init) {
      $init.textContent = initialsFromEmail(email);
      $init.style.display = 'grid';
    }

    // cache avatar rápido
    const cachedAvatar = localStorage.getItem('user_avatar');
    if (cachedAvatar) showAvatar(cachedAvatar);
    else showInitials(initialsFromEmail(email));

    const uid = await window.getCurrentUserId?.() ?? null;
    tile.href = uid != null ? `profile.html?user_id=${encodeURIComponent(uid)}` : 'profile.html';

    // fetch user
    let user = null;
    try {
      if (uid != null) {
        const r = await fetch(`${apiBase}/users/${encodeURIComponent(uid)}?user_id=${encodeURIComponent(uid)}`, { credentials: 'include' });
        if (r.ok) user = await r.json();
      }
      if (!user) {
        const r2 = await fetch(`${apiBase}/profile/me${uid != null ? `?user_id=${encodeURIComponent(uid)}` : ''}`, { credentials: 'include' });
        if (r2.ok) user = await r2.json();
      }
    } catch {}

    const userName = user?.user_name || '';
    if ($name) $name.textContent = userName || 'Profile';

    const avatarSrc =
      (typeof window.resolveUserAvatar === 'function')
        ? window.resolveUserAvatar({
            avatar_url: user?.avatar_url,
            email_vintti: user?.email_vintti || email,
            email: user?.email_vintti || email,
            user_id: user?.user_id ?? uid
          })
        : (typeof window.resolveAvatar === 'function')
          ? window.resolveAvatar(user?.email_vintti || email)
          : (user?.avatar_url || '');

    if (avatarSrc) {
      localStorage.setItem('user_avatar', avatarSrc);
      showAvatar(avatarSrc);
    } else {
      showInitials(initialsFromName(userName) || initialsFromEmail(email));
    }

    // asegurar visible
    const cs = window.getComputedStyle(tile);
    if (cs.display === 'none') tile.style.display = 'flex';
  }

  function markActiveSidebarLink() {
    const current = location.pathname.split('/').pop();
    document.querySelectorAll('.sidebar .menu-item').forEach(a => {
      a.classList.remove('active');
      const href = (a.getAttribute('href') || '').split('?')[0];
      if (href && !href.startsWith('http') && href === current) a.classList.add('active');
    });
  }

  /* -------------------------
     Loader (sidebar.html -> #sidebarMount)
  ------------------------- */
  async function loadSidebar() {
    const mount = document.getElementById('sidebarMount');

    if (!mount) {
      await waitForUserEmail();
      markActiveSidebarLink();
      applySidebarVisibility();
      setupSidebarCollapse();
      setupSidebarTooltips();
      await initSidebarProfile();
      document.dispatchEvent(new CustomEvent('sidebar:loaded'));
      return;
    }

    try {
      const res = await fetch(SIDEBAR_HTML_PATH, { cache: 'no-store' });
      if (!res.ok) return console.error('No se pudo cargar sidebar.html', res.status);
      mount.innerHTML = await res.text();

      await waitForUserEmail();

      markActiveSidebarLink();
      applySidebarVisibility();
      setupSidebarCollapse();
      setupSidebarTooltips();
      await initSidebarProfile();

      document.dispatchEvent(new CustomEvent('sidebar:loaded'));
    } catch (e) {
      console.error('Error cargando sidebar:', e);
    }
  }

  document.addEventListener('DOMContentLoaded', loadSidebar);
})();

