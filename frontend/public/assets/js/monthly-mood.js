(() => {
  const API_BASE_URL =
  (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const TARGET_PATHS = new Set(['/crm', '/candidates', '/opportunities']);
  const MONTHLY_RECAP_PREFIX = 'monthly_mood_recap_seen';

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
    { key: 'energetic', emoji: '🔋', label: 'Energetic', tone: 'On fire' },
    { key: 'good', emoji: '🙂', label: 'Good', tone: 'Steady and positive' },
    { key: 'neutral', emoji: '⚪', label: 'Neutral', tone: 'Balanced' },
    { key: 'low_energy', emoji: '🪫', label: 'Low Energy', tone: 'Low battery' },
    { key: 'stressed', emoji: '🌪️', label: 'Stressed', tone: 'High pressure' },
  ];
  const MOOD_BY_KEY = new Map(MOOD_OPTIONS.map((option) => [option.key, option]));
  const MOOD_VISUALS = {
    energetic: {
      palette: 'energetic',
      aura: 'rgba(205, 255, 48, 0.42)',
      accent: '#d6ff4e',
      surface: '#0f2e78',
      intro: 'You came in charged up.',
      story: 'You kept showing battery-pack energy and momentum.',
      closer: 'Protect this rhythm and keep using that spark where it matters most.',
    },
    good: {
      palette: 'good',
      aura: 'rgba(255, 199, 84, 0.35)',
      accent: '#ffd56f',
      surface: '#6c3d0a',
      intro: 'This month felt light and steady.',
      story: 'Your check-ins kept landing in a genuinely good place.',
      closer: 'You built a healthy baseline. Keep feeding what made the month feel easy.',
    },
    neutral: {
      palette: 'neutral',
      aura: 'rgba(210, 217, 229, 0.4)',
      accent: '#d8dee8',
      surface: '#344256',
      intro: 'This month stayed balanced.',
      story: 'You moved through the month with a calm, even tone.',
      closer: 'There is stability here. Next month can be about nudging that balance upward.',
    },
    low_energy: {
      palette: 'low-energy',
      aura: 'rgba(141, 199, 255, 0.35)',
      accent: '#9fd0ff',
      surface: '#123d67',
      intro: 'Your month asked for softer pacing.',
      story: 'Low battery moments showed up a lot more than usual.',
      closer: 'This is a good moment to protect energy, not force it.',
    },
    stressed: {
      palette: 'stressed',
      aura: 'rgba(255, 132, 105, 0.34)',
      accent: '#ff9d84',
      surface: '#6b1e1a',
      intro: 'This month had intensity.',
      story: 'Pressure showed up repeatedly in your check-ins.',
      closer: 'The goal for next month is not perfection. It is creating more breathing room.',
    },
    default: {
      palette: 'default',
      aura: 'rgba(116, 145, 255, 0.28)',
      accent: '#95a7ff',
      surface: '#19357b',
      intro: 'Your month had a clear rhythm.',
      story: 'There is a story in your mood check-ins already.',
      closer: 'Keep logging so this wrapped gets even more personal next time.',
    },
  };

  let lastPath = null;
  let observer = null;
  let hiddenThisSession = false;
  let recapShownInSession = false;

  function getLocalIso(date = new Date()) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  const todayKey = () => getLocalIso(new Date());

  function startOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth(), 1);
  }

  function endOfMonth(date) {
    return new Date(date.getFullYear(), date.getMonth() + 1, 0);
  }

  function shiftDate(date, days) {
    return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
  }

  function isSameLocalDay(a, b) {
    return a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth()
      && a.getDate() === b.getDate();
  }

  function getRecapSchedule(date = new Date()) {
    const currentMonthStart = startOfMonth(date);
    const currentMonthStartWeekday = currentMonthStart.getDay();
    let displayDate = currentMonthStart;

    if (currentMonthStartWeekday === 6) {
      displayDate = shiftDate(currentMonthStart, 2);
    } else if (currentMonthStartWeekday === 0) {
      displayDate = shiftDate(currentMonthStart, 1);
    }

    const targetMonthDate = shiftDate(currentMonthStart, -1);
    return {
      targetYear: targetMonthDate.getFullYear(),
      targetMonth: targetMonthDate.getMonth() + 1,
      displayDate,
    };
  }

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
    if (trimmed.endsWith('.html')) trimmed = trimmed.slice(0, -5);
    return trimmed;
  }

  function isTargetPath(pathname) {
    const normalized = normalizePath(pathname);
    if (TARGET_PATHS.has(normalized)) return true;
    return [...TARGET_PATHS].some((segment) => normalized.endsWith(segment));
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

  async function fetchMonthlyRecap({ year, month } = {}) {
    const userId = getUserId();
    const url = new URL(`${API_BASE_URL}/moods/monthly-recap`);
    if (userId) url.searchParams.set('user_id', String(userId));
    if (year) url.searchParams.set('year', String(year));
    if (month) url.searchParams.set('month', String(month));
    const res = await fetch(url.toString(), { credentials: 'include', cache: 'no-store' });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || 'Failed to load monthly recap');
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
    dismiss.dataset.action = 'close-monthly-mood';
    dismiss.setAttribute('aria-label', 'Hide monthly mood');
    dismiss.textContent = '×';
    dismiss.addEventListener('click', () => {
      hiddenThisSession = true;
      section.remove();
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
    content.appendChild(dismiss);

    section.appendChild(content);

    return section;
  }

  function getMonthLabel(month, year) {
    const monthIndex = Number(month) - 1;
    const safeIndex = Number.isFinite(monthIndex) && monthIndex >= 0 ? monthIndex : new Date().getMonth();
    return new Intl.DateTimeFormat('en', { month: 'long', year: 'numeric' }).format(new Date(Number(year) || new Date().getFullYear(), safeIndex, 1));
  }

  function getMonthRecapKey({ year, month, userId }) {
    return `${MONTHLY_RECAP_PREFIX}:${userId != null ? String(userId) : 'unknown'}:${year}-${String(month).padStart(2, '0')}`;
  }

  function alreadySawMonthRecap(payload) {
    try {
      return window.localStorage.getItem(getMonthRecapKey(payload)) === '1';
    } catch {
      return false;
    }
  }

  function markMonthRecapSeen(payload) {
    try {
      window.localStorage.setItem(getMonthRecapKey(payload), '1');
    } catch {
      // ignore storage errors
    }
  }

  function isMonthClosingWindow(date = new Date()) {
    const schedule = getRecapSchedule(date);
    return isSameLocalDay(date, schedule.displayDate);
  }

  function getSortedMoodCounts(payload) {
    return (Array.isArray(payload?.mood_counts) ? payload.mood_counts : [])
      .map((entry) => ({
        mood: String(entry?.mood || ''),
        count: Number(entry?.count) || 0,
      }))
      .filter((entry) => entry.count > 0)
      .sort((a, b) => b.count - a.count);
  }

  function buildFloatingMoodTokens(mood, amount = 14) {
    return Array.from({ length: amount }, (_, index) => {
      const seed = Math.abs(Math.sin((index + 1) * 91.173 + mood.label.length * 0.73));
      const seedB = Math.abs(Math.cos((index + 1) * 47.219 + mood.label.length * 1.13));
      const seedC = Math.abs(Math.sin((index + 1) * 19.337 + mood.label.length * 0.39));
      const left = (seed * 96).toFixed(2);
      const size = Math.round(16 + (seedC * 82));
      const delay = (-1 * (seed * 18 + index * 0.35)).toFixed(2);
      const duration = (12 + seedB * 18).toFixed(2);
      const sway = (18 + seed * 54).toFixed(2);
      const riseOffset = (104 + seedB * 26).toFixed(2);
      const rotate = ((seedC - 0.5) * 36).toFixed(2);
      const opacity = (0.12 + seedC * 0.42).toFixed(2);
      return `
        <span
          class="monthly-mood-orb"
          style="left:${left}%; --orb-size:${size}px; --orb-delay:${delay}s; --orb-duration:${duration}s; --orb-sway:${sway}px; --orb-rise-offset:${riseOffset}vh; --orb-rotate:${rotate}deg; --orb-opacity:${opacity};"
        >${mood.emoji}</span>
      `;
    }).join('');
  }

  function buildMoodSequence(payload) {
    const counts = getSortedMoodCounts(payload);
    if (!counts.length) {
      return '<div class="monthly-mood-story-empty">Not enough check-ins yet. Keep tapping your mood so next month this story gets richer.</div>';
    }

    return counts.slice(0, 4).map((entry, index) => {
      const mood = MOOD_BY_KEY.get(entry.mood) || { emoji: '✨', label: entry.mood || 'Mood' };
      const rankLabel = index === 0 ? 'Main vibe' : index === 1 ? 'Then came' : index === 2 ? 'Also present' : 'In the mix';
      return `
        <article class="monthly-mood-story-card">
          <div class="monthly-mood-story-rank">${rankLabel}</div>
          <div class="monthly-mood-story-emoji">${mood.emoji}</div>
          <div>
            <h3 class="monthly-mood-story-title">${mood.label}</h3>
            <p class="monthly-mood-story-copy">${entry.count} check-in${entry.count === 1 ? '' : 's'} landed here.</p>
          </div>
        </article>
      `;
    }).join('');
  }

  function getNarrative(payload) {
    const totalEntries = Number(payload?.total_entries) || 0;
    const daysWithMood = Number(payload?.days_with_mood) || 0;
    const daysElapsed = Math.max(1, Number(payload?.days_elapsed) || 0);
    const completionRate = Number(payload?.completion_rate) || 0;
    const counts = getSortedMoodCounts(payload);
    const topMood = MOOD_BY_KEY.get(payload?.top_mood) || { emoji: '✨', label: 'Mood', tone: 'Present' };
    const visual = MOOD_VISUALS[payload?.top_mood] || MOOD_VISUALS.default;
    const secondMood = counts[1] ? MOOD_BY_KEY.get(counts[1].mood) : null;
    const lowData = !totalEntries || daysWithMood < 2;

    if (lowData) {
      return {
        visual,
        topMood,
        heroTitle: `Not enough data for your full ${getMonthLabel(payload?.month, payload?.year)} wrapped yet`,
        heroCopy: 'You already started. Give us a few more mood check-ins and this end-of-month story becomes way more personal.',
        insightTitle: 'Here is what we know so far',
        insightCopy: `${totalEntries} entry${totalEntries === 1 ? '' : 'ies'} logged so far. Keep going and we will turn this into a real vibe recap.`,
        summaryEyebrow: 'Next step',
        summaryValue: `${totalEntries}`,
        summaryLabel: 'Entries so far',
        closer: 'Fill in more days and next month this turns into a full-screen story with real patterns.',
        lowData,
        counts,
        completionRate,
        daysWithMood,
        daysElapsed,
      };
    }

    const heroTitle = `${getMonthLabel(payload?.month, payload?.year)} felt mostly ${topMood.label.toLowerCase()}`;
    const heroCopy = `${visual.intro} ${visual.story}`;
    const insightCopy = secondMood
      ? `Your month started leading with ${topMood.label.toLowerCase()}, but ${secondMood.label.toLowerCase()} also had a strong presence.`
      : `${topMood.label} clearly dominated the month and set the tone for your check-ins.`;

    return {
      visual,
      topMood,
      heroTitle,
      heroCopy,
      insightTitle: 'Then your month shifted like this',
      insightCopy,
      summaryEyebrow: completionRate >= 70 ? 'Consistency' : 'Check-in rhythm',
      summaryValue: completionRate >= 70 ? `${Math.round(completionRate)}%` : `${daysWithMood}/${daysElapsed}`,
      summaryLabel: completionRate >= 70 ? 'Weekdays with a mood logged' : 'Weekdays tracked this month',
      closer: visual.closer,
      lowData,
      counts,
      completionRate,
      daysWithMood,
      daysElapsed,
    };
  }

  function closeMonthlyRecapOverlay() {
    const overlay = document.getElementById('monthlyMoodRecapOverlay');
    if (overlay) overlay.remove();
  }

  function showMonthlyRecapOverlay(payload) {
    closeMonthlyRecapOverlay();

    const story = getNarrative(payload);
    const mood = story.topMood;
    const overlay = document.createElement('div');
    overlay.id = 'monthlyMoodRecapOverlay';
    overlay.className = 'monthly-mood-recap-overlay';
    overlay.dataset.palette = story.visual.palette;
    overlay.innerHTML = `
      <div class="monthly-mood-recap-shell" role="dialog" aria-modal="true" aria-labelledby="monthlyMoodRecapTitle">
        <div class="monthly-mood-recap-atmosphere">
          ${buildFloatingMoodTokens(mood, story.lowData ? 20 : 48)}
        </div>
        <button type="button" class="monthly-mood-recap-close" aria-label="Close recap">×</button>
        <div class="monthly-mood-recap-progress">
          <button type="button" class="monthly-mood-recap-dot is-active" data-scene-dot="0" aria-label="Go to scene 1"></button>
          <button type="button" class="monthly-mood-recap-dot" data-scene-dot="1" aria-label="Go to scene 2"></button>
          <button type="button" class="monthly-mood-recap-dot" data-scene-dot="2" aria-label="Go to scene 3"></button>
        </div>
        <div class="monthly-mood-recap-scenes">
          <section class="monthly-mood-scene is-active" data-scene="0">
            <div class="monthly-mood-recap-badge">Mood Wrapped</div>
            <p class="monthly-mood-recap-kicker">${getMonthLabel(payload?.month, payload?.year)}</p>
            <h2 id="monthlyMoodRecapTitle" class="monthly-mood-recap-title">${story.heroTitle}</h2>
            <p class="monthly-mood-recap-copy">${story.heroCopy}</p>
            <div class="monthly-mood-recap-spotlight">
              <div class="monthly-mood-recap-spotlight-emoji">${mood.emoji}</div>
              <div class="monthly-mood-recap-spotlight-meta">
                <span class="monthly-mood-recap-spotlight-label">Main mood</span>
                <strong>${mood.label}</strong>
              </div>
            </div>
          </section>

          <section class="monthly-mood-scene" data-scene="1">
            <p class="monthly-mood-recap-kicker">${story.insightTitle}</p>
            <h2 class="monthly-mood-recap-subtitle">Your month had more than one note.</h2>
            <p class="monthly-mood-recap-copy">${story.insightCopy}</p>
            <div class="monthly-mood-story-grid">
              ${buildMoodSequence(payload)}
            </div>
          </section>

          <section class="monthly-mood-scene" data-scene="2">
            <p class="monthly-mood-recap-kicker">${story.summaryEyebrow}</p>
            <div class="monthly-mood-summary-panel">
              <div class="monthly-mood-summary-value">${story.summaryValue}</div>
              <div class="monthly-mood-summary-label">${story.summaryLabel}</div>
            </div>
            <p class="monthly-mood-recap-copy monthly-mood-recap-copy--compact">${story.closer}</p>
            <div class="monthly-mood-summary-foot">
              <span>${Number(payload?.top_mood_count) || 0} times in ${mood.label.toLowerCase()}</span>
              <span>${Number(payload?.total_entries) || 0} total entries</span>
            </div>
          </section>
        </div>
        <div class="monthly-mood-recap-controls">
          <button type="button" class="monthly-mood-recap-nav" data-nav="prev">Back</button>
          <button type="button" class="monthly-mood-recap-action" data-nav="next">Next vibe</button>
        </div>
      </div>
    `;

    const dismiss = () => closeMonthlyRecapOverlay();
    let activeScene = 0;
    const scenes = [...overlay.querySelectorAll('.monthly-mood-scene')];
    const dots = [...overlay.querySelectorAll('[data-scene-dot]')];
    const prevBtn = overlay.querySelector('[data-nav="prev"]');
    const nextBtn = overlay.querySelector('[data-nav="next"]');

    function renderScene(index) {
      activeScene = Math.max(0, Math.min(index, scenes.length - 1));
      scenes.forEach((scene, sceneIndex) => {
        scene.classList.toggle('is-active', sceneIndex === activeScene);
      });
      dots.forEach((dot, dotIndex) => {
        dot.classList.toggle('is-active', dotIndex === activeScene);
      });
      if (prevBtn) prevBtn.disabled = activeScene === 0;
      if (nextBtn) nextBtn.textContent = activeScene === scenes.length - 1 ? 'Start the month' : 'Next vibe';
    }

    overlay.querySelector('.monthly-mood-recap-close')?.addEventListener('click', dismiss);
    prevBtn?.addEventListener('click', () => renderScene(activeScene - 1));
    nextBtn?.addEventListener('click', () => {
      if (activeScene === scenes.length - 1) {
        dismiss();
        return;
      }
      renderScene(activeScene + 1);
    });
    dots.forEach((dot) => {
      dot.addEventListener('click', () => renderScene(Number(dot.dataset.sceneDot) || 0));
    });
    overlay.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') dismiss();
      if (event.key === 'ArrowRight') renderScene(activeScene + 1);
      if (event.key === 'ArrowLeft') renderScene(activeScene - 1);
    });

    document.body.appendChild(overlay);
    overlay.tabIndex = -1;
    overlay.focus();
    renderScene(0);
  }

  async function maybeShowMonthlyMoodRecap({ force = false, delayMs = 0 } = {}) {
    if (recapShownInSession && !force) return false;
    const schedule = getRecapSchedule(new Date());
    if (!force && !isSameLocalDay(new Date(), schedule.displayDate)) return false;

    const userId = getUserId();
    if (!userId) return false;

    const payload = await fetchMonthlyRecap({
      year: schedule.targetYear,
      month: schedule.targetMonth,
    });
    const storagePayload = { year: payload?.year, month: payload?.month, userId };
    if (!force && alreadySawMonthRecap(storagePayload)) return false;

    if (!force) {
      recapShownInSession = true;
      markMonthRecapSeen(storagePayload);
    }
    window.setTimeout(() => showMonthlyRecapOverlay(payload), Math.max(0, Number(delayMs) || 0));
    return true;
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
      if (hiddenThisSession) return;
      const banner = buildBanner(theme);
      if (main.firstChild) {
        main.insertBefore(banner, main.firstChild);
      } else {
        main.appendChild(banner);
      }
      fetchTodayMood()
        .then((mood) => {
          applySelectedMood(banner, mood);
        })
        .catch((error) => {
          console.warn('Failed to load today mood', error);
        });
    }
  }

  function scheduleInit() {
    if (window.location.pathname === lastPath) return;
    lastPath = window.location.pathname;
    insertBannerIfNeeded();
  }

  function installRouteWatcher() {
    if (observer) return;
    observer = new MutationObserver(() => {
      if (document.querySelector('.main-content')) insertBannerIfNeeded();
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

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('.monthly-mood-dismiss');
    if (!trigger) return;
    const banner = trigger.closest('.monthly-mood-banner');
    if (banner) {
      hiddenThisSession = true;
      banner.remove();
    }
  });

  window.maybeShowMonthlyMoodRecap = maybeShowMonthlyMoodRecap;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
