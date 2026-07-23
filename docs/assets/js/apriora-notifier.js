/* Notificador global de Apriora.
 * Corre en todas las páginas del Hub. Revisa (polling) las entrevistas que se
 * están creando en Apriora en segundo plano (guardadas en localStorage por
 * opportunity-detail) y avisa con un toast + notificación del navegador cuando
 * quedan listas — sin importar en qué página del Hub estés.
 */
(function () {
  const API_BASE =
    (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
      ? 'http://127.0.0.1:5000'
      : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  const KEY = 'apriora_pending';        // [{ oppId, name, startedAt }]
  const POLL_MS = 10000;                // revisar cada 10s
  const GIVE_UP_MS = 8 * 60 * 1000;     // dejar de esperar a los 8 min

  function readPending() {
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); }
    catch (e) { return []; }
  }
  function writePending(list) {
    try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (e) {}
  }

  // --- Estilos + animaciones (inyectados una vez) ---
  function ensureStyles() {
    if (document.getElementById('apriora-toast-styles')) return;
    const st = document.createElement('style');
    st.id = 'apriora-toast-styles';
    st.textContent =
      '@keyframes apriora-in{from{transform:translateX(120%) scale(.96);opacity:0}' +
      '60%{transform:translateX(-4%) scale(1);opacity:1}to{transform:translateX(0) scale(1);opacity:1}}' +
      '@keyframes apriora-out{to{transform:translateX(120%) scale(.96);opacity:0}}' +
      '@keyframes apriora-pop{0%{transform:scale(.4)}70%{transform:scale(1.15)}100%{transform:scale(1)}}';
    document.head.appendChild(st);
  }

  // --- Sonido: "ding" suave de dos notas, generado por Web Audio (sin archivo) ---
  // Los navegadores bloquean audio sin interacción previa, así que "desbloqueamos"
  // un AudioContext compartido en el primer clic/tecla de la página; luego el ding
  // suena aunque el toast llegue minutos después.
  let _audioCtx = null;
  function getAudioCtx() {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      if (!_audioCtx) _audioCtx = new AC();
      if (_audioCtx.state === 'suspended' && _audioCtx.resume) _audioCtx.resume();
      return _audioCtx;
    } catch (e) { return null; }
  }
  ['pointerdown', 'keydown', 'touchstart'].forEach(ev =>
    window.addEventListener(ev, getAudioCtx, { passive: true }));

  function playChime() {
    const ctx = getAudioCtx();
    if (!ctx || ctx.state !== 'running') return;   // sin desbloquear aún → sin sonido
    try {
      const t0 = ctx.currentTime;
      [[880, 0], [1174.66, 0.12]].forEach(([freq, t]) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, t0 + t);
        gain.gain.exponentialRampToValueAtTime(0.16, t0 + t + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, t0 + t + 0.35);
        osc.connect(gain); gain.connect(ctx.destination);
        osc.start(t0 + t); osc.stop(t0 + t + 0.4);
      });
    } catch (e) {}
  }

  // --- Toast (esquina superior derecha, con animación) ---
  function ensureToastHost() {
    let host = document.getElementById('apriora-toast-host');
    if (!host) {
      host = document.createElement('div');
      host.id = 'apriora-toast-host';
      host.style.cssText =
        'position:fixed;right:18px;top:18px;z-index:2147483647;' +
        'display:flex;flex-direction:column;gap:10px;max-width:360px;';
      document.body.appendChild(host);
    }
    return host;
  }
  function toast(message, opts) {
    opts = opts || {};
    const iconChar = opts.icon || '✓';
    const accent = opts.accent || 'linear-gradient(180deg,#6f42ff,#5d34f2)';
    const shadow = opts.shadow || 'rgba(108,56,255,.22)';
    ensureStyles();
    const host = ensureToastHost();
    const el = document.createElement('div');
    el.style.cssText =
      'background:#fff;color:#1b1b1b;border:1px solid #ece8ff;' +
      `border-radius:14px;box-shadow:0 16px 40px ${shadow};padding:13px 14px;` +
      'font:500 13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;' +
      'display:flex;align-items:center;gap:12px;cursor:default;' +
      'animation:apriora-in .45s cubic-bezier(.2,.9,.3,1.15) both;';

    const icon = document.createElement('div');
    icon.textContent = iconChar;
    icon.style.cssText =
      'flex:0 0 auto;width:26px;height:26px;border-radius:50%;' +
      `background:${accent};color:#fff;` +
      'display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;' +
      'box-shadow:0 4px 12px rgba(0,0,0,.15);animation:apriora-pop .5s ease .1s both;';

    const text = document.createElement('div');
    text.style.flex = '1';
    text.textContent = message;

    const close = document.createElement('span');
    close.textContent = '✕';
    close.style.cssText = 'cursor:pointer;color:#b6b0cc;font-size:12px;line-height:1;padding:2px;';

    function dismiss() {
      el.style.animation = 'apriora-out .3s ease forwards';
      setTimeout(() => el.remove(), 300);
    }
    close.addEventListener('click', dismiss);

    el.appendChild(icon);
    el.appendChild(text);
    el.appendChild(close);
    host.appendChild(el);
    if (opts.sound !== false) playChime();
    // duration:0 => toast persistente (solo se cierra con la ✕). Se usa para el
    // aviso "ya está lista", para que no se pierda si no estás mirando.
    if (opts.duration !== 0) setTimeout(dismiss, opts.duration || 12000);
  }

  // --- Notificación del navegador (si hay permiso) ---
  function browserNotify(message) {
    try {
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Vintti Hub · Apriora', { body: message });
      }
    } catch (e) {}
  }

  function announceReady(item) {
    const name = item.name || 'La entrevista';
    // Toast persistente (duration:0): se queda hasta que lo cierres, así no te lo
    // perdés si estabas en otra pestaña o mirando otra cosa.
    toast(`"${name}" ya está lista en Apriora`, { duration: 0 });
    browserNotify(`"${name}" ya está lista en Apriora`);
    // Avisar a la página (si es la de esta opp) para que actualice el botón
    // "Create Job in Apriora" a "✅ Ya creada" en vivo, sin necesidad de refrescar.
    try {
      window.dispatchEvent(new CustomEvent('apriora:ready', {
        detail: { oppId: String(item.oppId || '') }
      }));
    } catch (e) {}
  }

  async function isReady(oppId) {
    // Está lista cuando la position ya existe en Apriora (matched=true).
    // ?fresh=1 => el backend saltea su cache de 60s y la detecta al instante.
    const res = await fetch(
      `${API_BASE}/opportunities/${encodeURIComponent(oppId)}/alex/interviewed_count?fresh=1`,
      { cache: 'no-store' }
    );
    if (!res.ok) return false;
    const d = await res.json();
    return !!(d && d.matched);
  }

  let running = false;
  async function tick() {
    if (running) return;
    const list = readPending();
    if (!list.length) return;
    running = true;
    try {
      const now = Date.now();
      const still = [];
      for (const item of list) {
        if (!item || !item.oppId) continue;
        let ready = false;
        try { ready = await isReady(item.oppId); } catch (e) {}
        if (ready) {
          announceReady(item);
        } else if (now - (item.startedAt || 0) > GIVE_UP_MS) {
          // se venció el tiempo de espera: dejar de vigilar (sin ruido).
        } else {
          still.push(item);
        }
      }
      writePending(still);
    } finally {
      running = false;
    }
  }

  // API mínima para que otras páginas registren una creación pendiente / avisen.
  window.AprioraNotifier = {
    addPending(oppId, name) {
      const list = readPending().filter(x => String(x.oppId) !== String(oppId));
      list.push({ oppId: String(oppId), name: name || '', startedAt: Date.now() });
      writePending(list);
      tick();
    },
    removePending(oppId) {
      writePending(readPending().filter(x => String(x.oppId) !== String(oppId)));
    },
    toast: toast
  };

  setInterval(tick, POLL_MS);
  window.addEventListener('focus', tick);
  if (document.readyState !== 'loading') tick();
  else document.addEventListener('DOMContentLoaded', tick);
})();
