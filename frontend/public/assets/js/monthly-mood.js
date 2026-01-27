(() => {
  const API_BASE_URL = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const TARGET_PATHS = new Set(['/crm', '/candidates', '/opportunities']);

  const MONTHLY_THEMES = [
    { emoji: '☀️', message: 'January vibes ☀️ Good energy and fresh starts 💙' },
    { emoji: '💘', message: "February feels 💘 Happy Valentine's Day 💝" },
    { emoji: '🍃', message: 'March energy 🍃 New beginnings 🌸' },
    { emoji: '🌼', message: 'April days 🌼 Bright moments ahead 🌈' },
    { emoji: '💐', message: 'May mood 💐 Calm days and good vibes 🍂' },
    { emoji: '❄️', message: 'June moments ❄️ Cozy days 🤍' },
    { emoji: '🧣', message: 'July mood 🧣 Cozy moments and comfort ☕' },
    { emoji: '🌱', message: 'August energy 🌱 Fresh air and new vibes 🌬️' },
    { emoji: '🌸', message: 'September blooms 🌸 Spring vibes 🌿' },
    { emoji: '🌼', message: 'October days 🌼 More light, more smiles ☀️' },
    { emoji: '🌺', message: 'November vibes 🌺 Almost summer ✨' },
    { emoji: '🎄', message: 'December moments 🎄 Sunshine and celebrations ☀️' },
  ];

  const MOOD_OPTIONS = [
    { key: 'energetic', emoji: '🔋', label: 'energetic' },
    { key: 'good', emoji: '🙂', label: 'good' },
    { key: 'neutral', emoji: '⚪', label: 'neutral' },
    { key: 'low_energy', emoji: '🪫', label: 'low_energy' },
    { key: 'stressed', emoji: '🌪️', label: 'stressed' },
  ];

  let lastPath = null;
  let observer = null;

  const todayKey = () => new Date().toISOString().slice(0, 10);

  function buildWatermarkDataUri(emoji) {
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="240" height="240">
        <text x="22" y="56" font-size="26" fill="#1f2a37" fill-opacity="0.08"
          font-family="Apple Color Emoji,Segoe UI Emoji,Noto Color Emoji,sans-serif">${emoji}</text>
        <text x="120" y="140" font-size="22" fill="#1f2a37" fill-opacity="0.06"
          font-family="Apple Color Emoji,Segoe UI Emoji,Noto Color Emoji,sans-serif">${emoji}</text>
        <text x="60" y="210" font-size="18" fill="#1f2a37" fill-opacity="0.05"
          font-family="Apple Color Emoji,Segoe UI Emoji,Noto Color Emoji,sans-serif">${emoji}</text>
      </svg>
    `;
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  }

  function getUserId() {
    try {
      const value = window.localStorage.getItem('user_id');
      if (value) return Number(value);
    } catch {
      return null;
    }
    return null;
  }

  function normalizePath(pathname) {
    if (!pathname) return '';
    let trimmed = pathname.endsWith('/') && pathname.length > 1 ? pathname.slice(0, -1) : pathname;
    if (trimmed.endsWith('.html')) {
      trimmed = trimmed.slice(0, -5);
    }
    return trimmed;
  }

  function isTargetPath(pathname) {
    const normalized = normalizePath(pathname);
    return TARGET_PATHS.has(normalized);
  }

  function ensureWatermark(main, emoji) {
    if (!main) return;
    const dataUri = buildWatermarkDataUri(emoji);
    main.classList.add('monthly-mood-surface');
    main.style.setProperty('--monthly-watermark', `url("${dataUri}")`);
  }

  function clearWatermark(main) {
    if (!main) return;
    main.classList.remove('monthly-mood-surface');
    main.style.removeProperty('--monthly-watermark');
  }

  function applySelectedMood(container, moodKey) {
    const buttons = container.querySelectorAll('.monthly-mood-emoji');
    buttons.forEach((button) => {
      const isSelected = button.dataset.mood === moodKey;
      button.classList.toggle('selected', isSelected);
      button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
    });
  }

  async function fetchTodayMood() {
    const userId = getUserId();
    const url = new URL(`${API_BASE_URL}/moods/today`);
    if (userId) url.searchParams.set('user_id', String(userId));
    const res = await fetch(url.toString(), { credentials: 'include', cache: 'no-store' });
    if (!res.ok) return null;
    const data = await res.json();
    return data?.mood || null;
  }

  async function saveTodayMood(moodKey) {
    const userId = getUserId();
    const res = await fetch(`${API_BASE_URL}/moods`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ mood: moodKey, user_id: userId }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to save mood');
    }
    return res.json();
  }

  function buildBanner(theme) {
    const section = document.createElement('section');
    section.className = 'monthly-mood-banner';
    section.setAttribute('aria-label', 'Monthly mood update');

    const message = document.createElement('p');
    message.className = 'monthly-mood-message';
    message.textContent = theme.message;

    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'monthly-mood-dismiss';
    dismiss.setAttribute('aria-label', 'Hide monthly mood');
    dismiss.textContent = '×';
    dismiss.addEventListener('click', () => {
      section.remove();
      showReopenButton();
    });

    const bar = document.createElement('div');
    bar.className = 'monthly-mood-bar';
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'Mood of the day');

    const label = document.createElement('span');
    label.className = 'monthly-mood-label';
    label.textContent = 'Mood of the day';

    const options = document.createElement('div');
    options.className = 'monthly-mood-options';

    MOOD_OPTIONS.forEach((option) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'monthly-mood-emoji';
      button.dataset.mood = option.key;
      button.dataset.tooltip = option.label;
      button.textContent = option.emoji;
      button.setAttribute('title', option.label);
      button.setAttribute('aria-label', option.label);
      button.setAttribute('aria-pressed', 'false');

      button.addEventListener('click', async () => {
        if (button.classList.contains('selected')) return;
        const container = button.closest('.monthly-mood-banner');
        applySelectedMood(container, option.key);
        try {
          await saveTodayMood(option.key);
          try {
            window.localStorage.setItem('mood_last_saved', todayKey());
            window.localStorage.setItem('mood_value', option.key);
          } catch {
            // ignore storage errors
          }
        } catch (error) {
          console.error('Failed to save mood', error);
          applySelectedMood(container, null);
        }
      });

      options.appendChild(button);
    });

    bar.appendChild(label);
    bar.appendChild(options);

    const content = document.createElement('div');
    content.className = 'monthly-mood-content';
    content.appendChild(message);
    content.appendChild(bar);

    const dismissRow = document.createElement('div');
    dismissRow.className = 'monthly-mood-dismiss-row';
    dismissRow.appendChild(dismiss);

    section.appendChild(content);
    section.appendChild(dismissRow);

    return section;
  }

  function insertBannerIfNeeded() {
    const path = window.location.pathname;
    const main = document.querySelector('.main-content');
    if (!main) return;

    if (!isTargetPath(path)) {
      clearWatermark(main);
      const existing = main.querySelector('.monthly-mood-banner');
      if (existing) existing.remove();
      return;
    }

    const theme = MONTHLY_THEMES[new Date().getMonth()] || MONTHLY_THEMES[0];
    ensureWatermark(main, theme.emoji);

    if (!main.querySelector('.monthly-mood-banner')) {
      const banner = buildBanner(theme);
      if (main.firstChild) {
        main.insertBefore(banner, main.firstChild);
      } else {
        main.appendChild(banner);
      }
      removeReopenButton();
      fetchTodayMood()
        .then((mood) => {
          applySelectedMood(banner, mood);
        })
        .catch((error) => {
          console.warn('Failed to load today mood', error);
        });
    }
  }

  function showReopenButton() {
    const main = document.querySelector('.main-content');
    if (!main || main.querySelector('.monthly-mood-reopen')) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'monthly-mood-reopen';
    button.textContent = 'Show mood bar';
    button.addEventListener('click', () => {
      button.remove();
      insertBannerIfNeeded();
    });
    main.insertBefore(button, main.firstChild);
  }

  function removeReopenButton() {
    const existing = document.querySelector('.monthly-mood-reopen');
    if (existing) existing.remove();
  }

  function scheduleInit() {
    if (window.location.pathname === lastPath) return;
    lastPath = window.location.pathname;
    insertBannerIfNeeded();
  }

  function installRouteWatcher() {
    if (observer) return;
    observer = new MutationObserver(() => {
      if (document.querySelector('.main-content')) {
        insertBannerIfNeeded();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    const originalPush = history.pushState;
    history.pushState = function pushState(...args) {
      originalPush.apply(this, args);
      scheduleInit();
    };
    const originalReplace = history.replaceState;
    history.replaceState = function replaceState(...args) {
      originalReplace.apply(this, args);
      scheduleInit();
    };
    window.addEventListener('popstate', scheduleInit);
  }

  function init() {
    installRouteWatcher();
    insertBannerIfNeeded();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
