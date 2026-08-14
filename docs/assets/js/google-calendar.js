(() => {
  const DEFAULT_API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const API_BASE = String(window.VINTTI_API_BASE || window.API_BASE || DEFAULT_API_BASE).replace(/\/+$/, '');

  const connectBtn = document.getElementById('connectBtn');
  const disconnectBtn = document.getElementById('disconnectBtn');
  const calendarStatus = document.getElementById('calendarStatus');
  const connectionBadge = document.getElementById('connectionBadge');
  const eventsContainer = document.getElementById('eventsContainer');
  const upcomingEventsContainer = document.getElementById('upcomingEventsContainer');
  const upcomingSubtitle = document.getElementById('upcomingSubtitle');
  const agendaSummary = document.getElementById('agendaSummary');
  const calendarDate = document.getElementById('calendarDate');
  const refreshBtn = document.getElementById('refreshBtn');
  const openEventModalBtn = document.getElementById('openEventModalBtn');
  const eventModal = document.getElementById('eventModal');
  const closeEventModalBtn = document.getElementById('closeEventModalBtn');
  const eventForm = document.getElementById('eventForm');
  const formStatus = document.getElementById('formStatus');
  const availabilityGrid = document.getElementById('availabilityGrid');
  const modalAvailabilityGrid = document.getElementById('modalAvailabilityGrid');
  const availabilityStatus = document.getElementById('availabilityStatus');
  const modalAvailabilityStatus = document.getElementById('modalAvailabilityStatus');
  const miniCalendarTitle = document.getElementById('miniCalendarTitle');
  const miniCalendarGrid = document.getElementById('miniCalendarGrid');
  const miniCalendarPrev = document.getElementById('miniCalendarPrev');
  const miniCalendarNext = document.getElementById('miniCalendarNext');
  const miniCalendarToday = document.getElementById('miniCalendarToday');
  const nextMeetingCard = document.getElementById('nextMeetingCard');
  const allDayStrip = document.getElementById('allDayStrip');
  const dayHeadNumber = document.getElementById('dayHeadNumber');
  const dayHeadWeekday = document.getElementById('dayHeadWeekday');
  const dayHeadMonth = document.getElementById('dayHeadMonth');

  const tz = 'America/Argentina/Buenos_Aires';
  let currentUserId = null;
  let miniCalendarCursor = null;
  let eventTimePickers = null;
  let eventAttendeePicker = null;
  let monthEventCounts = new Map();
  // Se apaga solo si el backend deployado todavía no entiende ?days=N.
  let rangeApiSupported = true;
  const availabilityConfig = {
    dayStart: 8 * 60,
    dayEnd: 20 * 60,
    minuteHeight: 1,
    columnMinWidth: 112,
    gutterWidth: 62,
  };
  const availabilityPalette = [
    { accent: '#0b3d91', bg: 'rgba(11, 61, 145, 0.14)', border: 'rgba(11, 61, 145, 0.28)' },
    { accent: '#0f7a5c', bg: 'rgba(15, 122, 92, 0.14)', border: 'rgba(15, 122, 92, 0.28)' },
    { accent: '#d16413', bg: 'rgba(209, 100, 19, 0.14)', border: 'rgba(209, 100, 19, 0.28)' },
    { accent: '#b42318', bg: 'rgba(180, 35, 24, 0.14)', border: 'rgba(180, 35, 24, 0.28)' },
    { accent: '#0f6da1', bg: 'rgba(15, 109, 161, 0.14)', border: 'rgba(15, 109, 161, 0.28)' },
    { accent: '#7b3fbf', bg: 'rgba(123, 63, 191, 0.14)', border: 'rgba(123, 63, 191, 0.28)' },
    { accent: '#a8127a', bg: 'rgba(168, 18, 122, 0.14)', border: 'rgba(168, 18, 122, 0.28)' },
    { accent: '#5a6b7f', bg: 'rgba(90, 107, 127, 0.14)', border: 'rgba(90, 107, 127, 0.28)' },
  ];

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setRefreshing(isRefreshing) {
    if (!refreshBtn) return;
    refreshBtn.disabled = Boolean(isRefreshing);
    refreshBtn.classList.toggle('is-loading', Boolean(isRefreshing));
  }

  function setStatus({ connected, message }) {
    if (connected) {
      connectionBadge.textContent = 'Conectado';
      connectionBadge.classList.add('is-connected');
      disconnectBtn.hidden = false;
      connectBtn.hidden = true;
      calendarStatus.textContent = message || 'Tu Google Calendar está sincronizado.';
    } else {
      connectionBadge.textContent = 'Sin conectar';
      connectionBadge.classList.remove('is-connected');
      disconnectBtn.hidden = true;
      connectBtn.hidden = false;
      calendarStatus.textContent = message || 'Conectá tu Google Calendar para ver tu agenda.';
    }
  }

  function getStoredEmail() {
    return (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
      .toLowerCase()
      .trim();
  }

  async function getCurrentUserId() {
    if (window.getCurrentUserId) {
      return window.getCurrentUserId();
    }

    const email = getStoredEmail();
    if (!email) return null;

    try {
      const res = await fetch(`${API_BASE}/users?email=${encodeURIComponent(email)}`, {
        credentials: 'include',
      });
      if (!res.ok) return null;
      const arr = await res.json();
      const hit = Array.isArray(arr) ? arr.find(u => (u.email_vintti || '').toLowerCase() === email) : null;
      return hit?.user_id ?? null;
    } catch {
      return null;
    }
  }

  async function resolveUserId() {
    if (currentUserId) return currentUserId;
    currentUserId = await getCurrentUserId();
    return currentUserId;
  }

  async function ensureUserIdOrNotify() {
    const userId = await resolveUserId();
    if (!userId) {
      setStatus({ connected: false, message: 'No pudimos identificar el usuario.' });
      renderEmptyState('Inicia sesión para conectar tu calendario.');
      return null;
    }
    return userId;
  }

  function renderEmptyState(message) {
    eventsContainer.innerHTML = `<p class="day-placeholder">${escapeHtml(message)}</p>`;
  }

  function renderAvailabilityEmpty(message) {
    [availabilityGrid, modalAvailabilityGrid].forEach((target) => {
      if (!target) return;
      target.classList.add('is-empty');
      target.innerHTML = `
        <div class="empty-state">
          <img src="./assets/img/calendar.png" alt="" />
          <p>${escapeHtml(message)}</p>
        </div>
      `;
    });
  }

  function renderUpcomingEmpty(message) {
    if (!upcomingEventsContainer) return;
    upcomingEventsContainer.innerHTML = `<p class="side-empty">${escapeHtml(message)}</p>`;
  }

  function setAvailabilityMessage(message) {
    if (availabilityStatus) availabilityStatus.textContent = message;
    if (modalAvailabilityStatus) modalAvailabilityStatus.textContent = message;
  }

  function openEventModal() {
    if (!eventModal) return;
    if (formStatus) formStatus.textContent = '';
    eventModal.hidden = false;
    document.body.classList.add('modal-open');
    eventTimePickers?.prefill();
    window.setTimeout(() => document.getElementById('eventTitle')?.focus(), 0);
  }

  function closeEventModal() {
    if (!eventModal) return;
    if (formStatus) formStatus.textContent = '';
    eventModal.hidden = true;
    document.body.classList.remove('modal-open');
  }

  function getSelectedDate() {
    return calendarDate?.value || new Date().toISOString().slice(0, 10);
  }

  const isoDateFormatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });

  function todayIso() {
    return isoDateFormatter.format(new Date());
  }

  function currentMinutesOfDay() {
    return toMinutesOfDay(new Date().toISOString());
  }

  function shiftIsoDate(isoDate, amount) {
    const base = new Date(`${isoDate}T12:00:00`);
    base.setDate(base.getDate() + amount);
    return base.toISOString().slice(0, 10);
  }

  function localIsoDate(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  }

  // Primera celda del mes en la grilla (la semana arranca lunes).
  function miniCalendarGridStart() {
    const monthStart = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth(), 1);
    const offset = (monthStart.getDay() + 6) % 7;
    monthStart.setDate(monthStart.getDate() - offset);
    return monthStart;
  }

  function renderMiniCalendar() {
    if (!miniCalendarGrid || !miniCalendarTitle || !calendarDate) return;
    const selected = isoToDate(getSelectedDate());
    const current = miniCalendarCursor || new Date(selected.getFullYear(), selected.getMonth(), 1);
    miniCalendarCursor = new Date(current.getFullYear(), current.getMonth(), 1);

    miniCalendarTitle.textContent = capitalizeFirst(formatMonthYear(miniCalendarCursor));

    const weekdays = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'];
    const monthEnd = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth() + 1, 0);
    const firstWeekday = (new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth(), 1).getDay() + 6) % 7;
    const daysInMonth = monthEnd.getDate();
    const cells = weekdays.map(day => `<div class="mini-calendar-weekday">${day}</div>`);

    for (let i = 0; i < firstWeekday; i += 1) {
      cells.push('<div class="mini-calendar-day is-muted" aria-hidden="true"></div>');
    }

    const today = todayIso();
    const selectedIso = getSelectedDate();

    for (let day = 1; day <= daysInMonth; day += 1) {
      const iso = localIsoDate(new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth(), day));
      const classes = ['mini-calendar-day'];
      if (iso === selectedIso) classes.push('is-selected');
      if (iso === today) classes.push('is-today');
      const count = monthEventCounts.get(iso) || 0;
      const dots = count
        ? `<span class="mini-dots">${Array.from({ length: Math.min(count, 3) }, () => '<span class="mini-dot"></span>').join('')}</span>`
        : '';
      cells.push(`
        <button class="${classes.join(' ')}" type="button" data-calendar-day="${iso}" aria-label="${iso}${count ? ` · ${count} eventos` : ''}">
          <span class="mini-calendar-number">${day}</span>
          ${dots}
        </button>
      `);
    }

    miniCalendarGrid.innerHTML = cells.join('');
  }

  function parseAttendees() {
    const raw = document.getElementById('eventAttendees')?.value || '';
    return raw
      .split(',')
      .map(item => item.trim().toLowerCase())
      .filter(Boolean);
  }

  function displayNameFromEmail(email) {
    if (!email) return 'Invitado';
    const local = email.split('@')[0] || email;
    return local.replace(/[._-]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  }

  function getAvailabilityLabel(email, hostEmail) {
    if (hostEmail && email === hostEmail) return 'Tu calendario';
    return displayNameFromEmail(email);
  }

  function getProposedRange() {
    const date = document.getElementById('eventDate')?.value || '';
    const start = document.getElementById('eventStart')?.value || '';
    const end = document.getElementById('eventEnd')?.value || '';
    if (!date || !start || !end) return null;
    const [startHour, startMin] = start.split(':').map(Number);
    const [endHour, endMin] = end.split(':').map(Number);
    if (Number.isNaN(startHour) || Number.isNaN(startMin) || Number.isNaN(endHour) || Number.isNaN(endMin)) {
      return null;
    }
    const startMinutes = startHour * 60 + startMin;
    const endMinutes = endHour * 60 + endMin;
    if (endMinutes <= startMinutes) return null;
    return { startMinutes, endMinutes };
  }

  function formatEventTime(event) {
    const start = event.start?.dateTime || event.start?.date;
    const end = event.end?.dateTime || event.end?.date;
    if (!start || !end) return 'Todo el día';
    if (isAllDayCalendarEvent(event)) return 'Todo el día';
    const startMinutes = toMinutesOfDay(start);
    const endMinutes = toMinutesOfDay(end);
    if (startMinutes === null || endMinutes === null) return 'Todo el día';
    return `${formatMinutesLabel(startMinutes)} – ${formatMinutesLabel(endMinutes)}`;
  }

  function isAllDayCalendarEvent(event) {
    return Boolean(event?.start?.date && !event?.start?.dateTime);
  }

  function eventDurationMinutes(event) {
    const start = new Date(event?.start?.dateTime || event?.start?.date || '').getTime();
    const end = new Date(event?.end?.dateTime || event?.end?.date || '').getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return 0;
    return Math.round((end - start) / 60000);
  }

  // Limpia lo que Google devuelve antes de pintarlo:
  // - los "working location" (Home / Oficina) no son reuniones,
  // - el fin de un evento de día completo es exclusivo (el cumpleaños del 14 aparecía el 15),
  // - y a veces llegan repetidos (mismo título y horario).
  function prepareDayEvents(events, targetDate) {
    const seen = new Set();
    return (Array.isArray(events) ? events : [])
      .filter((event) => {
        if (!event || event.status === 'cancelled') return false;
        if (event.eventType === 'workingLocation') return false;

        if (isAllDayCalendarEvent(event)) {
          const startDate = event.start?.date || '';
          const endDate = event.end?.date || startDate;
          if (targetDate && startDate && !(startDate <= targetDate && targetDate < endDate)) return false;
        }

        const key = [
          (event.summary || '').trim().toLowerCase(),
          event.start?.dateTime || event.start?.date || '',
          event.end?.dateTime || event.end?.date || '',
        ].join('|');
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .sort((a, b) => {
        const allDayDiff = Number(isAllDayCalendarEvent(b)) - Number(isAllDayCalendarEvent(a));
        if (allDayDiff) return allDayDiff;
        const startA = new Date(a.start?.dateTime || a.start?.date || 0).getTime();
        const startB = new Date(b.start?.dateTime || b.start?.date || 0).getTime();
        return startA - startB;
      });
  }

  // La magenta de marca queda reservada para la línea de "ahora": es lo único
  // que se mueve en la pantalla y no compite con ningún evento.
  const eventPalette = [
    { accent: '#0b3d91', tint: 'rgba(11, 61, 145, 0.10)', text: '#0b3d91' },
    { accent: '#6c38ff', tint: 'rgba(108, 56, 255, 0.10)', text: '#5227d1' },
    { accent: '#4ba9ff', tint: 'rgba(75, 169, 255, 0.16)', text: '#0f6da1' },
    { accent: '#c1ff72', tint: 'rgba(193, 255, 114, 0.34)', text: '#3a6b00' },
    { accent: '#003bff', tint: 'rgba(0, 59, 255, 0.10)', text: '#003bff' },
  ];

  // Mismo título, mismo color todos los días: los eventos recurrentes se
  // vuelven reconocibles de un vistazo.
  function paletteForEvent(summary) {
    const text = String(summary || '').trim().toLowerCase();
    let hash = 0;
    for (let i = 0; i < text.length; i += 1) hash = (hash * 31 + text.charCodeAt(i)) >>> 0;
    return eventPalette[hash % eventPalette.length];
  }

  const dayHeadFormatter = new Intl.DateTimeFormat('es-AR', { weekday: 'long', timeZone: tz });
  // Armamos "agosto 2026" a mano: el formato largo en español mete un "de"
  // que con capitalize quedaba como "Agosto De 2026".
  const monthNameFormatter = new Intl.DateTimeFormat('es-AR', { month: 'long', timeZone: tz });
  const shortDayFormatter = new Intl.DateTimeFormat('es-AR', { weekday: 'short', day: 'numeric', timeZone: tz });

  function capitalizeFirst(value) {
    const text = String(value || '');
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  function formatMonthYear(date) {
    return `${monthNameFormatter.format(date)} ${date.getFullYear()}`;
  }

  function isoToDate(isoDate) {
    return new Date(`${isoDate}T12:00:00`);
  }

  function updateDayHeading(targetDate) {
    if (!targetDate) return;
    const date = isoToDate(targetDate);
    if (dayHeadNumber) dayHeadNumber.textContent = String(date.getDate());
    if (dayHeadWeekday) dayHeadWeekday.textContent = capitalizeFirst(dayHeadFormatter.format(date));
    if (dayHeadMonth) dayHeadMonth.textContent = capitalizeFirst(formatMonthYear(date));
  }

  function formatCountdown(minutes) {
    if (minutes <= 0) return 'en curso';
    if (minutes < 60) return `en ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return rest ? `en ${hours} h ${rest}` : `en ${hours} h`;
  }

  function renderNextMeeting(timed, targetDate) {
    if (!nextMeetingCard) return;
    const isToday = targetDate === todayIso();
    const nowMinutes = currentMinutesOfDay();

    let event = null;
    let state = 'next';
    if (isToday) {
      event = timed.find((item) => {
        const end = toMinutesOfDay(item.end?.dateTime);
        return end !== null && end > nowMinutes;
      }) || null;
    } else {
      event = timed[0] || null;
      state = 'first';
    }

    if (!event) {
      nextMeetingCard.hidden = false;
      nextMeetingCard.innerHTML = `
        <div class="next-card-body">
          <span class="next-card-eyebrow">Agenda libre</span>
          <h3 class="next-card-title">${isToday ? 'No queda nada por delante hoy' : 'Ese día no tenés reuniones'}</h3>
          <p class="next-card-line">Usá el botón + para agendar una y validar horarios con el equipo.</p>
        </div>
      `;
      return;
    }

    const start = toMinutesOfDay(event.start?.dateTime);
    const end = toMinutesOfDay(event.end?.dateTime);
    const running = isToday && start !== null && nowMinutes >= start;
    const eyebrow = running
      ? 'Ahora'
      : (state === 'next' ? formatCountdown(Math.max(0, (start ?? 0) - nowMinutes)) : 'Primera del día');
    const meetLink = event.hangoutLink || event.conferenceData?.entryPoints?.[0]?.uri;
    const duration = eventDurationMinutes(event);

    nextMeetingCard.hidden = false;
    nextMeetingCard.className = `next-card${running ? ' is-running' : ''}`;
    nextMeetingCard.innerHTML = `
      <div class="next-card-body">
        <span class="next-card-eyebrow">${running ? '<span class="next-card-live"></span>' : ''}${escapeHtml(eyebrow)}</span>
        <h3 class="next-card-title">${escapeHtml(event.summary || 'Sin título')}</h3>
        <p class="next-card-line">
          ${start === null ? '' : escapeHtml(`${formatMinutesLabel(start)} – ${formatMinutesLabel(end ?? start)}`)}
          ${duration ? `<span class="next-card-dot">·</span>${escapeHtml(formatDurationLabel(duration))}` : ''}
          ${event.location ? `<span class="next-card-dot">·</span>${escapeHtml(event.location)}` : ''}
        </p>
      </div>
      <div class="next-card-actions">
        ${meetLink ? `<a class="next-join" href="${escapeHtml(meetLink)}" target="_blank" rel="noopener"><i class="fa-solid fa-video"></i>Unirse</a>` : ''}
        ${event.htmlLink ? `<a class="next-open" href="${escapeHtml(event.htmlLink)}" target="_blank" rel="noopener">Ver en Google</a>` : ''}
      </div>
    `;
  }

  function renderAllDayStrip(allDay) {
    if (!allDayStrip) return;
    if (!allDay.length) {
      allDayStrip.hidden = true;
      allDayStrip.innerHTML = '';
      return;
    }
    allDayStrip.hidden = false;
    allDayStrip.innerHTML = `
      <span class="day-allday-label">Todo el día</span>
      <span class="day-allday-chips">
        ${allDay.map((event) => {
          const palette = paletteForEvent(event.summary);
          return `<span class="day-allday-chip" style="--chip-accent:${palette.accent};--chip-tint:${palette.tint};--chip-text:${palette.text};">${escapeHtml(event.summary || 'Sin título')}</span>`;
        }).join('')}
      </span>
    `;
  }

  let nowLineTimer = null;

  function updateNowLine() {
    const line = eventsContainer?.querySelector('.day-now');
    if (!line) return;
    const grid = line.closest('.day-grid');
    if (!grid) return;
    const dayStart = Number(grid.dataset.dayStart);
    const dayEnd = Number(grid.dataset.dayEnd);
    const minuteHeight = Number(grid.dataset.minuteHeight);
    const now = currentMinutesOfDay();
    if (now === null || now < dayStart || now > dayEnd) {
      line.hidden = true;
      return;
    }
    line.hidden = false;
    line.style.top = `${(now - dayStart) * minuteHeight}px`;
    const label = line.querySelector('.day-now-label');
    if (label) label.textContent = formatMinutesLabel(now);
  }

  function renderDayGrid(timed, targetDate) {
    if (!eventsContainer) return;
    const minuteHeight = 1;
    const isToday = targetDate === todayIso();
    const nowMinutes = currentMinutesOfDay();

    const entries = layoutPersonEntries(
      timed
        .map((event) => {
          const startMinutes = toMinutesOfDay(event.start?.dateTime);
          let endMinutes = toMinutesOfDay(event.end?.dateTime);
          if (startMinutes === null || endMinutes === null) return null;
          if (endMinutes <= startMinutes) endMinutes = Math.min(startMinutes + 30, 24 * 60);
          return {
            startMinutes,
            endMinutes,
            label: event.summary || 'Sin título',
            location: event.location || '',
            meetLink: event.hangoutLink || event.conferenceData?.entryPoints?.[0]?.uri || '',
            htmlLink: event.htmlLink || '',
            palette: paletteForEvent(event.summary),
          };
        })
        .filter(Boolean)
        .sort((a, b) => a.startMinutes - b.startMinutes || b.endMinutes - a.endMinutes),
    );

    let dayStart = 8 * 60;
    let dayEnd = 20 * 60;
    entries.forEach((entry) => {
      if (entry.startMinutes < dayStart) dayStart = Math.max(0, Math.floor(entry.startMinutes / 60) * 60);
      if (entry.endMinutes > dayEnd) dayEnd = Math.min(24 * 60, Math.ceil(entry.endMinutes / 60) * 60);
    });
    if (isToday && nowMinutes !== null) {
      if (nowMinutes < dayStart) dayStart = Math.max(0, Math.floor(nowMinutes / 60) * 60);
      if (nowMinutes > dayEnd) dayEnd = Math.min(24 * 60, Math.ceil(nowMinutes / 60) * 60);
    }

    const slotHeight = 60 * minuteHeight;
    const gridHeight = (dayEnd - dayStart) * minuteHeight;

    const hours = [];
    for (let minutes = dayStart; minutes < dayEnd; minutes += 60) {
      hours.push(`<div class="day-hour"><span>${formatMinutesLabel(minutes)}</span></div>`);
    }

    const blocks = entries
      .map((entry) => {
        const top = (entry.startMinutes - dayStart) * minuteHeight;
        const height = Math.max((entry.endMinutes - entry.startMinutes) * minuteHeight, 22);
        const duration = entry.endMinutes - entry.startMinutes;
        const width = 100 / entry.totalColumns;
        const left = width * entry.column;
        // El layout depende del alto real del bloque, no de la duración: cada
        // línea que agregamos necesita su lugar o el texto queda cortado.
        // <32: todo en una línea · <52: título + hora en línea · <90: apilado
        // a una línea de título · >=90: dos líneas de título y botón de Meet.
        let sizeClass = '';
        if (height < 32) sizeClass = ' is-tiny';
        else if (height < 52) sizeClass = ' is-compact';
        else if (height >= 90) sizeClass = ' is-roomy';
        const pastClass = isToday && nowMinutes !== null && nowMinutes >= entry.endMinutes ? ' is-past' : '';
        const liveClass = isToday && nowMinutes !== null && nowMinutes >= entry.startMinutes && nowMinutes < entry.endMinutes ? ' is-live' : '';
        const timeLabel = `${formatMinutesLabel(entry.startMinutes)} – ${formatMinutesLabel(entry.endMinutes)}`;
        return `
          <div
            class="day-event${sizeClass}${pastClass}${liveClass}"
            style="top:${top}px;height:${height}px;left:calc(${left}% + 4px);width:calc(${width}% - 8px);--ev-accent:${entry.palette.accent};--ev-tint:${entry.palette.tint};--ev-text:${entry.palette.text};"
            title="${escapeHtml(`${timeLabel} · ${entry.label}`)}"
          >
            <span class="day-event-title">${escapeHtml(entry.label)}</span>
            <span class="day-event-time">${escapeHtml(timeLabel)}${entry.location ? ` · ${escapeHtml(entry.location)}` : ''}</span>
            ${entry.meetLink && height >= 90 ? `<a class="day-event-meet" href="${escapeHtml(entry.meetLink)}" target="_blank" rel="noopener"><i class="fa-solid fa-video"></i>Meet</a>` : ''}
          </div>
        `;
      })
      .join('');

    eventsContainer.innerHTML = `
      <div
        class="day-grid"
        data-day-start="${dayStart}"
        data-day-end="${dayEnd}"
        data-minute-height="${minuteHeight}"
        style="--slot-height:${slotHeight}px;--grid-height:${gridHeight}px;"
      >
        <div class="day-gutter">${hours.join('')}</div>
        <div class="day-canvas">
          ${blocks || '<p class="day-free">Día libre. Un buen momento para trabajo profundo.</p>'}
          ${isToday ? '<div class="day-now" hidden><span class="day-now-label">--:--</span></div>' : ''}
        </div>
      </div>
    `;

    updateNowLine();

    if (nowLineTimer) window.clearInterval(nowLineTimer);
    if (isToday) nowLineTimer = window.setInterval(updateNowLine, 60000);

    // Arrancamos la vista donde está la acción, no a las 08:00.
    const anchor = isToday && nowMinutes !== null ? nowMinutes : (entries[0]?.startMinutes ?? dayStart);
    const grid = eventsContainer.querySelector('.day-grid');
    if (grid) {
      window.requestAnimationFrame(() => {
        eventsContainer.scrollTop = Math.max(0, (anchor - dayStart - 60) * minuteHeight);
      });
    }
  }

  function renderEvents(events, targetDate) {
    const clean = prepareDayEvents(events, targetDate);
    const timed = clean.filter(event => !isAllDayCalendarEvent(event));
    const allDay = clean.filter(isAllDayCalendarEvent);

    if (agendaSummary) {
      const totalMinutes = timed.reduce((acc, event) => acc + (eventDurationMinutes(event) || 0), 0);
      agendaSummary.textContent = timed.length
        ? `${timed.length} ${timed.length === 1 ? 'reunión' : 'reuniones'} · ${formatDurationLabel(totalMinutes) || '0 min'} en calendario`
        : 'Sin reuniones agendadas.';
    }

    updateDayHeading(targetDate);
    renderAllDayStrip(allDay);
    renderNextMeeting(timed, targetDate);
    renderDayGrid(timed, targetDate);
  }

  // Agrupa los próximos días en una sola lista: día, y debajo sus reuniones.
  function renderUpcomingDays(eventsByDay, fromDate) {
    if (!upcomingEventsContainer) return;

    const days = Object.keys(eventsByDay)
      .filter(iso => iso > fromDate)
      .sort()
      .map(iso => ({ iso, events: prepareDayEvents(eventsByDay[iso], iso) }))
      .filter(day => day.events.length)
      .slice(0, 3);

    if (!days.length) {
      upcomingEventsContainer.innerHTML = '<p class="side-empty">No hay nada agendado en los próximos días.</p>';
      if (upcomingSubtitle) upcomingSubtitle.textContent = 'Próximos días';
      return;
    }

    if (upcomingSubtitle) upcomingSubtitle.textContent = `${days.length} día${days.length === 1 ? '' : 's'} con agenda`;

    upcomingEventsContainer.innerHTML = days
      .map((day) => {
        const visible = day.events.slice(0, 3);
        const rest = day.events.length - visible.length;
        return `
          <section class="upcoming-day">
            <h3 class="upcoming-day-label">${escapeHtml(capitalizeFirst(shortDayFormatter.format(isoToDate(day.iso))))}</h3>
            ${visible
              .map((event) => {
                const palette = paletteForEvent(event.summary);
                const allDay = isAllDayCalendarEvent(event);
                return `
                  <button class="upcoming-item" type="button" data-calendar-day="${day.iso}" style="--item-accent:${palette.text};">
                    <span class="upcoming-time">${escapeHtml(allDay ? 'Todo el día' : formatMinutesLabel(toMinutesOfDay(event.start?.dateTime) ?? 0))}</span>
                    <span class="upcoming-name">${escapeHtml(event.summary || 'Sin título')}</span>
                  </button>
                `;
              })
              .join('')}
            ${rest > 0 ? `<p class="upcoming-more">+${rest} más</p>` : ''}
          </section>
        `;
      })
      .join('');
  }

  function formatInviteDate(startIso, endIso) {
    if (!startIso || !endIso) return 'Time to be confirmed';
    const startDate = new Date(startIso);
    const endDate = new Date(endIso);
    const dateFmt = new Intl.DateTimeFormat('en-US', {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    });
    const timeFmt = new Intl.DateTimeFormat('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
    const tzFmt = new Intl.DateTimeFormat('en-US', { timeZoneName: 'short' });
    const tzPart = tzFmt.formatToParts(startDate).find(part => part.type === 'timeZoneName');
    const tzLabel = tzPart ? tzPart.value : 'Local time';
    return `${dateFmt.format(startDate)} · ${timeFmt.format(startDate)} - ${timeFmt.format(endDate)} (${tzLabel})`;
  }

  function buildInviteEmail(payload) {
    const title = payload.title || 'Meeting';
    const dateLine = formatInviteDate(payload.startIso, payload.endIso);
    const guests = payload.attendees || [];
    const meetLink = payload.meetLink || '';
    const calendarLink = payload.calendarLink || '';
    const host = payload.host || 'Vintti Hub';
    const guestList = guests
      .map(email => `<li style="margin:0 0 6px;color:#0f1b2d;">${escapeHtml(email)}</li>`)
      .join('');
    const buttonUrl = meetLink || calendarLink;
    return `
      <div style="background:#f4f6fb;padding:24px;font-family:Arial,sans-serif;">
        <div style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:16px;padding:28px;border:1px solid #e1e8f7;">
          <p style="margin:0 0 12px;font-size:16px;color:#0f1b2d;">Hi there,</p>
          <p style="margin:0 0 16px;font-size:16px;color:#0f1b2d;">
            You have been invited to a meeting hosted by ${escapeHtml(host)}.
          </p>
          <div style="background:#f7f9ff;border-radius:12px;padding:16px;border:1px solid #e1e8f7;">
            <h2 style="margin:0 0 6px;font-size:18px;color:#0b3d91;">${escapeHtml(title)}</h2>
            <p style="margin:0;font-size:14px;color:#4b5b73;">${escapeHtml(dateLine)}</p>
          </div>
          ${buttonUrl ? `
            <div style="margin:18px 0;">
              <a href="${buttonUrl}" style="display:inline-block;background:#0b3d91;color:#ffffff;text-decoration:none;padding:10px 16px;border-radius:999px;font-size:14px;">
                Join the meeting
              </a>
            </div>
          ` : ''}
          <h3 style="margin:18px 0 8px;font-size:14px;color:#0f1b2d;">Guests</h3>
          <ul style="margin:0;padding-left:18px;font-size:14px;color:#0f1b2d;">
            ${guestList || '<li>Guest list will follow shortly.</li>'}
          </ul>
          <p style="margin:20px 0 0;font-size:12px;color:#6b7a93;">
            If you have any questions, just reply to this email.
          </p>
        </div>
      </div>
    `;
  }

  async function sendInviteEmail(payload) {
    const subject = `You're invited: ${payload.title || 'Meeting'}`;
    const body = buildInviteEmail(payload);
    const res = await fetch(`${API_BASE}/send_email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        to: payload.attendees || [],
        subject,
        body,
      }),
      credentials: 'include',
    });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }

  // Un evento de día completo (cumpleaños, OOO, feriados) llega con fecha sin hora
  // y tapa TODOS los bloques ocupados del día si lo usamos para etiquetar.
  function isAllDayEvent(event) {
    if (event?.all_day === true) return true;
    return !String(event?.start || '').includes('T') || !String(event?.end || '').includes('T');
  }

  function getBusyLabel(events, slot) {
    if (!Array.isArray(events) || !events.length) return 'Ocupado';
    const busyStart = new Date(slot.start).getTime();
    const busyEnd = new Date(slot.end).getTime();
    if (!Number.isFinite(busyStart) || !Number.isFinite(busyEnd)) return 'Ocupado';

    let best = null;
    let allDayFallback = null;

    events.forEach((event) => {
      const start = new Date(event.start).getTime();
      const end = new Date(event.end).getTime();
      if (!Number.isFinite(start) || !Number.isFinite(end)) return;
      const overlap = Math.min(end, busyEnd) - Math.max(start, busyStart);
      if (overlap <= 0) return;

      if (isAllDayEvent(event)) {
        if (!allDayFallback) allDayFallback = event.summary;
        return;
      }

      // Nos quedamos con el evento que mejor calza con el bloque ocupado, no con el primero.
      const drift = Math.abs(start - busyStart) + Math.abs(end - busyEnd);
      if (!best || overlap > best.overlap || (overlap === best.overlap && drift < best.drift)) {
        best = { overlap, drift, summary: event.summary };
      }
    });

    const blockDuration = busyEnd - busyStart;
    if (best && best.overlap >= blockDuration * 0.5) return best.summary;
    // Solo si el bloque ocupado es en sí de día completo tiene sentido el evento all-day.
    if (allDayFallback && blockDuration >= 6 * 60 * 60 * 1000) return allDayFallback;
    return best?.summary || 'Ocupado';
  }

  function formatMinutesLabel(minutes) {
    const total = Math.max(0, Math.round(minutes));
    const hour = String(Math.floor(total / 60) % 24).padStart(2, '0');
    const min = String(total % 60).padStart(2, '0');
    return `${hour}:${min}`;
  }

  // Ubicamos los bloques en la zona horaria del hub, no en la del navegador.
  const availabilityTimeFormatter = new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: tz,
  });

  function toMinutesOfDay(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return null;
    const [rawHour, rawMinute] = availabilityTimeFormatter.format(date).split(':').map(Number);
    if (!Number.isFinite(rawHour) || !Number.isFinite(rawMinute)) return null;
    return (rawHour % 24) * 60 + rawMinute;
  }

  // freebusy devuelve los huecos ocupados FUSIONADOS (dos reuniones pegadas = un bloque),
  // así que preferimos la lista real de eventos y solo caemos a freebusy cuando no
  // tenemos permiso para ver el detalle de ese calendario.
  function collectPersonEntries(email, calendars, eventDetails) {
    const details = Array.isArray(eventDetails?.[email]) ? eventDetails[email] : [];
    const allDay = details.filter(isAllDayEvent).map(event => event.summary || 'Todo el día');
    const timed = details.filter(event => !isAllDayEvent(event));

    const source = timed.length
      ? timed.map(event => ({ start: event.start, end: event.end, label: event.summary || 'Ocupado' }))
      : (calendars?.[email]?.busy || []).map(slot => ({
        start: slot.start,
        end: slot.end,
        label: getBusyLabel(details, slot),
      }));

    const entries = source
      .map((item) => {
        const startMinutes = toMinutesOfDay(item.start);
        let endMinutes = toMinutesOfDay(item.end);
        if (startMinutes === null || endMinutes === null) return null;
        if (endMinutes <= startMinutes) {
          // Termina a medianoche o cruza el día: lo cortamos al final de la grilla.
          if (new Date(item.end).getTime() <= new Date(item.start).getTime()) return null;
          endMinutes = 24 * 60;
        }
        return { label: item.label, startMinutes, endMinutes };
      })
      .filter(Boolean)
      .sort((a, b) => a.startMinutes - b.startMinutes || b.endMinutes - a.endMinutes);

    return { entries, allDay, merged: !timed.length && entries.length > 0 };
  }

  // Google Calendar-style packing: only the events that actually overlap each other
  // share the width of the column, so a busy day doesn't shrink the whole timeline.
  function layoutPersonEntries(entries) {
    const positioned = [];
    let cluster = [];
    let clusterEnd = -Infinity;

    const flushCluster = () => {
      if (!cluster.length) return;
      const columnEnds = [];
      cluster.forEach((entry) => {
        let column = columnEnds.findIndex(end => end <= entry.startMinutes);
        if (column === -1) {
          columnEnds.push(entry.endMinutes);
          column = columnEnds.length - 1;
        } else {
          columnEnds[column] = entry.endMinutes;
        }
        entry.column = column;
      });
      cluster.forEach((entry) => {
        positioned.push({ ...entry, totalColumns: columnEnds.length });
      });
      cluster = [];
    };

    entries.forEach((entry) => {
      if (entry.startMinutes >= clusterEnd) {
        flushCluster();
        clusterEnd = entry.endMinutes;
      } else {
        clusterEnd = Math.max(clusterEnd, entry.endMinutes);
      }
      cluster.push({ ...entry });
    });
    flushCluster();

    return positioned;
  }

  function buildAvailabilityMarkup(emails, calendars, eventDetails, hostEmail) {
    if (!emails.length) {
      return `
        <div class="empty-state">
          <img src="./assets/img/calendar.png" alt="" />
          <p>Sin invitados para consultar.</p>
        </div>
      `;
    }

    const { minuteHeight, gutterWidth } = availabilityConfig;
    // Con muchas columnas achicamos el ancho mínimo para evitar scroll horizontal innecesario.
    const columnMinWidth = emails.length >= 6
      ? 94
      : (emails.length >= 4 ? 104 : availabilityConfig.columnMinWidth);
    const proposed = getProposedRange();

    const people = emails.map((email, index) => {
      const collected = collectPersonEntries(email, calendars, eventDetails);
      return {
        email,
        label: getAvailabilityLabel(email, hostEmail),
        palette: availabilityPalette[index % availabilityPalette.length],
        entries: layoutPersonEntries(collected.entries),
        allDay: collected.allDay,
        merged: collected.merged,
      };
    });

    // La grilla arranca en 08:00–20:00 pero se estira si alguien tiene algo fuera de esa
    // franja: si no, las reuniones tempranas o tardías desaparecían de la vista.
    let dayStart = availabilityConfig.dayStart;
    let dayEnd = availabilityConfig.dayEnd;
    const marks = [];
    people.forEach(person => person.entries.forEach((entry) => {
      marks.push(entry.startMinutes, entry.endMinutes);
    }));
    if (proposed) marks.push(proposed.startMinutes, proposed.endMinutes);
    marks.forEach((minute) => {
      if (minute < dayStart) dayStart = Math.max(0, Math.floor(minute / 60) * 60);
      if (minute > dayEnd) dayEnd = Math.min(24 * 60, Math.ceil(minute / 60) * 60);
    });

    const slotHeight = 60 * minuteHeight;
    const timelineHeight = (dayEnd - dayStart) * minuteHeight;
    const proposedTop = Math.max(proposed ? proposed.startMinutes : 0, dayStart);
    const proposedBottom = Math.min(proposed ? proposed.endMinutes : 0, dayEnd);
    const proposedBlock = proposed && proposedBottom > proposedTop ? {
      top: (proposedTop - dayStart) * minuteHeight,
      height: (proposedBottom - proposedTop) * minuteHeight,
    } : null;

    const hourSlots = [];
    for (let minutes = dayStart; minutes < dayEnd; minutes += 60) {
      hourSlots.push(`<div class="avail-hour">${formatMinutesLabel(minutes)}</div>`);
    }

    const headCells = people
      .map((person) => {
        const count = person.entries.length;
        const summary = count
          ? `${count} ${count === 1 ? 'reunión' : 'reuniones'}${person.merged ? ' (bloques)' : ''}`
          : 'Libre';
        const allDayNote = person.allDay.length
          ? `<span class="avail-col-allday" title="${escapeHtml(person.allDay.join(' · '))}">${escapeHtml(person.allDay[0])}</span>`
          : '';
        return `
          <div class="avail-col-head" style="--person-accent:${person.palette.accent};" title="${escapeHtml(person.email)}">
            <span class="avail-col-name"><span class="avail-col-dot"></span>${escapeHtml(person.label)}</span>
            <span class="avail-col-meta${count ? '' : ' is-free'}">${summary}</span>
            ${allDayNote}
          </div>
        `;
      })
      .join('');

    const bodyCells = people
      .map((person) => {
        const blocks = person.entries
          .map((entry) => {
            const clampedStart = Math.max(entry.startMinutes, dayStart);
            const clampedEnd = Math.min(entry.endMinutes, dayEnd);
            if (clampedEnd <= clampedStart) return '';
            const top = (clampedStart - dayStart) * minuteHeight;
            const height = (clampedEnd - clampedStart) * minuteHeight;
            const duration = clampedEnd - clampedStart;
            const width = 100 / entry.totalColumns;
            const left = width * entry.column;
            const sizeClass = duration <= 20 ? ' is-tiny' : (duration <= 45 ? ' is-compact' : '');
            const timeLabel = `${formatMinutesLabel(entry.startMinutes)} – ${formatMinutesLabel(entry.endMinutes)}`;
            return `
              <div
                class="avail-event${sizeClass}"
                style="top:${top}px;height:${height}px;left:calc(${left}% + 3px);width:calc(${width}% - 6px);"
                title="${escapeHtml(`${person.label} · ${timeLabel} · ${entry.label}`)}"
              >
                <span class="avail-event-title">${escapeHtml(entry.label)}</span>
                <span class="avail-event-time">${escapeHtml(timeLabel)}</span>
              </div>
            `;
          })
          .join('');
        return `<div class="avail-col" style="--person-accent:${person.palette.accent};--person-bg:${person.palette.bg};--person-border:${person.palette.border};">${blocks}</div>`;
      })
      .join('');

    return `
      <div class="avail-cal" style="--slot-height:${slotHeight}px;--timeline-height:${timelineHeight}px;--col-min:${columnMinWidth}px;--gutter-width:${gutterWidth}px;min-width:calc(${gutterWidth}px + ${people.length} * ${columnMinWidth}px);">
        <div class="avail-head">
          <div class="avail-head-gutter">Hora</div>
          <div class="avail-head-cols">${headCells}</div>
        </div>
        <div class="avail-body">
          <div class="avail-gutter">${hourSlots.join('')}</div>
          <div class="avail-cols">
            ${proposedBlock ? `
              <div class="avail-proposed" style="top:${proposedBlock.top}px;height:${proposedBlock.height}px;">
                <span>Horario propuesto</span>
              </div>
            ` : ''}
            ${bodyCells}
          </div>
        </div>
      </div>
    `;
  }

  function renderAvailability(emails, calendars, eventDetails, hostEmail) {
    const markup = buildAvailabilityMarkup(emails, calendars, eventDetails, hostEmail);
    [availabilityGrid, modalAvailabilityGrid].forEach((target) => {
      if (target) {
        target.classList.remove('is-empty');
        target.innerHTML = markup;
      }
    });
  }

  async function fetchDayEvents(userId, date) {
    const res = await fetch(
      `${API_BASE}/google-calendar/events?user_id=${encodeURIComponent(userId)}&date=${encodeURIComponent(date)}&timezone=${encodeURIComponent(tz)}`,
      { credentials: 'include' },
    );
    if (!res.ok) throw res;
    return res.json();
  }

  async function fetchRangeEvents(userId, startDate, days) {
    const res = await fetch(
      `${API_BASE}/google-calendar/events?user_id=${encodeURIComponent(userId)}&date=${encodeURIComponent(startDate)}&days=${days}&timezone=${encodeURIComponent(tz)}`,
      { credentials: 'include' },
    );
    if (!res.ok) throw res;
    return res.json();
  }

  // Plan B para el rango: /google-calendar/freebusy acepta time_min/time_max
  // y ya está deployado. Devuelve los eventos con el mismo shape que la API
  // de eventos, o null si tampoco se puede.
  async function fetchRangeViaFreebusy(userId, startIso, days) {
    const email = getStoredEmail();
    if (!email) return null;
    // La versión deployada corta en 50 eventos por pedido, así que partimos
    // el rango en ventanas de dos semanas.
    const windowDays = 14;
    const chunks = [];
    for (let offset = 0; offset < days; offset += windowDays) {
      chunks.push([shiftIsoDate(startIso, offset), Math.min(windowDays, days - offset)]);
    }
    const results = await Promise.all(
      chunks.map(([chunkStart, chunkDays]) => fetchFreebusyWindow(userId, email, chunkStart, chunkDays)),
    );
    const merged = results.filter(Boolean).flat();
    return merged.length ? merged : null;
  }

  async function fetchFreebusyWindow(userId, email, startIso, days) {
    try {
      const res = await fetch(`${API_BASE}/google-calendar/freebusy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          emails: [email],
          // Con offset explícito: el backend interpreta las fechas sin zona
          // usando la hora del servidor, que está en UTC.
          time_min: `${startIso}T00:00:00-03:00`,
          time_max: `${shiftIsoDate(startIso, days)}T00:00:00-03:00`,
          timezone: tz,
        }),
        credentials: 'include',
      });
      if (!res.ok) return null;
      const data = await res.json();

      const details = data.events?.[email];
      if (Array.isArray(details) && details.length) {
        return details.map(item => ({
          summary: item.summary,
          start: String(item.start).includes('T') ? { dateTime: item.start } : { date: item.start },
          end: String(item.end).includes('T') ? { dateTime: item.end } : { date: item.end },
        }));
      }

      const busy = data.calendars?.[email]?.busy;
      if (!Array.isArray(busy) || !busy.length) return null;
      return busy.map(slot => ({
        summary: 'Ocupado',
        start: { dateTime: slot.start },
        end: { dateTime: slot.end },
      }));
    } catch {
      return null;
    }
  }

  function daysBetween(fromIso, toIso) {
    const from = isoToDate(fromIso).getTime();
    const to = isoToDate(toIso).getTime();
    return Math.max(1, Math.round((to - from) / 86400000));
  }

  function groupEventsByDay(events) {
    const byDay = {};
    (Array.isArray(events) ? events : []).forEach((event) => {
      if (isAllDayCalendarEvent(event)) {
        // Los de varios días marcan cada uno de sus días.
        let cursor = event.start?.date || '';
        const end = event.end?.date || cursor;
        let guard = 0;
        while (cursor && cursor < end && guard < 40) {
          (byDay[cursor] = byDay[cursor] || []).push(event);
          cursor = shiftIsoDate(cursor, 1);
          guard += 1;
        }
        return;
      }
      const start = event.start?.dateTime;
      if (!start) return;
      const iso = isoDateFormatter.format(new Date(start));
      (byDay[iso] = byDay[iso] || []).push(event);
    });
    return byDay;
  }

  function applyMonthCounts(byDay) {
    monthEventCounts = new Map();
    Object.keys(byDay).forEach((iso) => {
      const count = prepareDayEvents(byDay[iso], iso).length;
      if (count) monthEventCounts.set(iso, count);
    });
  }

  async function fetchEvents(userId) {
    const date = getSelectedDate();
    calendarDate.value = date;
    renderMiniCalendar();
    updateDayHeading(date);

    // Un solo pedido cubre la grilla del mes y los próximos días.
    const gridStart = localIsoDate(miniCalendarGridStart());
    const rangeStart = gridStart < date ? gridStart : date;
    const rangeEnd = shiftIsoDate(date, 15);
    const gridEnd = shiftIsoDate(gridStart, 42);
    const rangeDays = daysBetween(rangeStart, rangeEnd > gridEnd ? rangeEnd : gridEnd);

    try {
      setRefreshing(true);
      const [dayRes, rangeRes] = await Promise.allSettled([
        fetchDayEvents(userId, date),
        rangeApiSupported ? fetchRangeEvents(userId, rangeStart, rangeDays) : Promise.resolve(null),
      ]);

      if (dayRes.status === 'rejected') {
        const res = dayRes.reason;
        if (res?.status === 404) {
          setStatus({ connected: false, message: 'Conectá tu Google Calendar para ver tu agenda.' });
          renderEmptyState('Conectá tu Google Calendar para ver las reuniones del día.');
          renderUpcomingEmpty('Conectá tu calendario para ver lo que viene.');
          if (nextMeetingCard) nextMeetingCard.hidden = true;
          return;
        }
        throw res;
      }

      renderEvents(dayRes.value.events || [], dayRes.value.date || date);

      const rangeData = rangeRes.status === 'fulfilled' ? rangeRes.value : null;
      if (rangeApiSupported && rangeData && !Number.isFinite(rangeData.range_days)) rangeApiSupported = false;
      let rangeEvents = rangeData && Number.isFinite(rangeData.range_days) ? (rangeData.events || []) : null;

      // Mientras el backend con ?days=N no esté deployado, sacamos el rango de
      // freebusy, que sí acepta time_min/time_max y ya está en producción.
      if (!rangeEvents) rangeEvents = await fetchRangeViaFreebusy(userId, rangeStart, rangeDays);

      if (rangeEvents) {
        const byDay = groupEventsByDay(rangeEvents);
        applyMonthCounts(byDay);
        renderMiniCalendar();
        renderUpcomingDays(byDay, date);
      } else {
        const nextDate = shiftIsoDate(date, 1);
        try {
          const next = await fetchDayEvents(userId, nextDate);
          renderUpcomingDays({ [nextDate]: next.events || [] }, date);
        } catch {
          renderUpcomingEmpty('No pudimos cargar lo que viene.');
        }
      }
    } catch (error) {
      console.error(error);
      renderEmptyState('No pudimos cargar tus reuniones. Probá de nuevo.');
      renderUpcomingEmpty('No pudimos cargar lo que viene.');
    } finally {
      setRefreshing(false);
    }
  }

  async function handleConnect(userId) {
    try {
      const res = await fetch(`${API_BASE}/google-calendar/auth-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, redirect_to: window.location.origin + '/calendar.html' }),
        credentials: 'include',
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.auth_url) window.location.href = data.auth_url;
    } catch (error) {
      console.error(error);
      setStatus({ connected: false, message: 'No pudimos iniciar la conexión con Google.' });
    }
  }

  async function handleDisconnect(userId) {
    try {
      await fetch(`${API_BASE}/google-calendar/disconnect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId }),
        credentials: 'include',
      });
      setStatus({ connected: false, message: 'Desconectado. Puedes volver a conectar cuando quieras.' });
      renderEmptyState('Conecta tu Google Calendar para ver las reuniones del día.');
    } catch (error) {
      console.error(error);
    }
  }

  async function handleCreateEvent(userId, payload) {
    if (formStatus) formStatus.textContent = 'Creando evento...';
    try {
      const res = await fetch(`${API_BASE}/google-calendar/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, user_id: userId, timezone: tz }),
        credentials: 'include',
      });
      if (!res.ok) throw new Error(await res.text());
      const created = await res.json();
      if (formStatus) formStatus.textContent = 'Evento creado ✅';
      await fetchEvents(userId);
      const inviteToggle = document.getElementById('eventEmailInvite');
      if (inviteToggle?.checked && payload.attendees?.length) {
        try {
          await sendInviteEmail({
            title: created.summary || payload.summary,
            startIso: created.start?.dateTime || `${payload.start}`,
            endIso: created.end?.dateTime || `${payload.end}`,
            attendees: payload.attendees,
            meetLink: created.hangoutLink || created.conferenceData?.entryPoints?.[0]?.uri,
            calendarLink: created.htmlLink || '',
            host: getStoredEmail() || 'Vintti Hub',
          });
          if (formStatus) formStatus.textContent = 'Evento creado ✅ Email enviado';
        } catch (error) {
          console.error(error);
          if (formStatus) formStatus.textContent = 'Evento creado ✅ Email no enviado';
        }
      }
      eventForm?.reset();
      eventAttendeePicker?.clear();
      const eventMeet = document.getElementById('eventMeet');
      if (eventMeet) eventMeet.checked = true;
      if (inviteToggle) inviteToggle.checked = true;
      setAvailabilityMessage('Agrega invitados para consultar disponibilidad.');
      renderAvailabilityEmpty('Sin invitados para consultar.');
      closeEventModal();
    } catch (error) {
      console.error(error);
      if (formStatus) formStatus.textContent = 'No se pudo crear el evento.';
    }
  }

  async function fetchAvailability(userId) {
    const guestEmails = parseAttendees();
    if (!guestEmails.length) {
      setAvailabilityMessage('Agrega emails para consultar disponibilidad.');
      renderAvailabilityEmpty('Sin invitados para consultar.');
      return;
    }

    const hostEmail = getStoredEmail();
    const emails = [];
    if (hostEmail) emails.push(hostEmail);
    guestEmails.forEach((email) => {
      if (!emails.includes(email)) emails.push(email);
    });

    const date = document.getElementById('eventDate')?.value || calendarDate.value || new Date().toISOString().slice(0, 10);
    setAvailabilityMessage('Consultando disponibilidad...');

    try {
      const res = await fetch(`${API_BASE}/google-calendar/freebusy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          emails,
          date,
          timezone: tz,
        }),
        credentials: 'include',
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      renderAvailability(emails, data.calendars || {}, data.events || {}, hostEmail);
      const guestCount = guestEmails.length;
      const hostLabel = hostEmail ? ' + tu calendario' : '';
      setAvailabilityMessage(`Disponibilidad para ${guestCount} invitados${hostLabel} el ${date}.`);
    } catch (error) {
      console.error(error);
      setAvailabilityMessage('No pudimos consultar disponibilidad.');
      renderAvailabilityEmpty('No pudimos cargar la disponibilidad.');
    }
  }

  // ---------------------------------------------------------------------------
  // Selector de hora (dropdown estilo Google) e invitados con búsqueda
  // ---------------------------------------------------------------------------

  const TIME_STEP_MINUTES = 15;
  const DEFAULT_DURATION_MINUTES = 30;

  function minutesToTimeValue(minutes) {
    const clamped = Math.max(0, Math.min(24 * 60 - 1, Math.round(minutes)));
    return `${String(Math.floor(clamped / 60)).padStart(2, '0')}:${String(clamped % 60).padStart(2, '0')}`;
  }

  // Acepta "9", "930", "9:30", "9pm", "15:30"... y devuelve minutos desde medianoche.
  function parseTimeText(raw) {
    const text = String(raw || '').trim().toLowerCase().replace(/\s+/g, '');
    if (!text) return null;
    const meridiem = /(am|pm)$/.exec(text)?.[1] || '';
    const digits = text.replace(/(a\.?m\.?|p\.?m\.?)$/, '').replace(/[.:]/g, '');
    if (!/^\d{1,4}$/.test(digits)) return null;

    let hours;
    let minutes;
    if (digits.length <= 2) {
      hours = Number(digits);
      minutes = 0;
    } else if (digits.length === 3) {
      hours = Number(digits.slice(0, 1));
      minutes = Number(digits.slice(1));
    } else {
      hours = Number(digits.slice(0, 2));
      minutes = Number(digits.slice(2));
    }

    if (meridiem === 'pm' && hours < 12) hours += 12;
    if (meridiem === 'am' && hours === 12) hours = 0;
    if (hours > 23 || minutes > 59) return null;
    return hours * 60 + minutes;
  }

  function formatDurationLabel(minutes) {
    if (minutes <= 0) return '';
    if (minutes < 60) return `${minutes} min`;
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    if (!rest) return `${hours} h`;
    return `${hours} h ${rest}`;
  }

  function fireInput(element) {
    element?.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function setupTimePickers() {
    const startInput = document.getElementById('eventStart');
    const endInput = document.getElementById('eventEnd');
    if (!startInput || !endInput) return null;

    const pickers = [
      { input: startInput, menu: document.getElementById('eventStartMenu'), isEnd: false },
      { input: endInput, menu: document.getElementById('eventEndMenu'), isEnd: true },
    ].filter(item => item.menu);

    function buildOptions(picker) {
      const base = picker.isEnd ? parseTimeText(startInput.value) : null;
      const options = [];
      for (let minutes = 0; minutes < 24 * 60; minutes += TIME_STEP_MINUTES) {
        if (base !== null && minutes <= base) continue;
        options.push({
          minutes,
          label: minutesToTimeValue(minutes),
          hint: base !== null ? formatDurationLabel(minutes - base) : '',
        });
      }
      return options;
    }

    function renderMenu(picker) {
      const typed = String(picker.input.value || '').replace(/[^0-9]/g, '');
      let options = buildOptions(picker);
      if (typed) {
        const filtered = options.filter(option => option.label.replace(':', '').startsWith(typed));
        if (filtered.length) options = filtered;
      }
      picker.options = options;
      if (picker.activeIndex >= options.length) picker.activeIndex = options.length - 1;

      picker.menu.innerHTML = options.length
        ? options
          .map((option, index) => `
            <button
              type="button"
              class="time-option${index === picker.activeIndex ? ' is-active' : ''}${option.label === picker.input.value ? ' is-selected' : ''}"
              role="option"
              data-minutes="${option.minutes}"
            >
              <span>${option.label}</span>
              ${option.hint ? `<span class="time-option-hint">${escapeHtml(option.hint)}</span>` : ''}
            </button>
          `)
          .join('')
        : '<div class="time-empty">Sin coincidencias</div>';

      const active = picker.menu.querySelector('.time-option.is-active') || picker.menu.querySelector('.time-option.is-selected');
      if (active) active.scrollIntoView({ block: 'nearest' });
    }

    function openMenu(picker) {
      const current = parseTimeText(picker.input.value);
      picker.activeIndex = -1;
      picker.menu.hidden = false;
      renderMenu(picker);
      if (current !== null) {
        const match = Array.from(picker.menu.querySelectorAll('.time-option'))
          .find(node => Number(node.dataset.minutes) >= current);
        (match || picker.menu.querySelector('.time-option'))?.scrollIntoView({ block: 'center' });
      }
    }

    function closeMenu(picker) {
      picker.menu.hidden = true;
      picker.activeIndex = -1;
    }

    function closeAll() {
      pickers.forEach(closeMenu);
    }

    function applyValue(picker, minutes) {
      const previousStart = parseTimeText(startInput.value);
      const previousEnd = parseTimeText(endInput.value);
      picker.input.value = minutesToTimeValue(minutes);

      if (!picker.isEnd) {
        // Como Google: al mover el inicio se mantiene la duración de la reunión.
        const duration = previousStart !== null && previousEnd !== null && previousEnd > previousStart
          ? previousEnd - previousStart
          : DEFAULT_DURATION_MINUTES;
        endInput.value = minutesToTimeValue(Math.min(minutes + duration, 24 * 60 - TIME_STEP_MINUTES));
        fireInput(endInput);
      } else if (previousStart !== null && minutes <= previousStart) {
        // Si el fin queda antes del inicio, corremos el inicio conservando la duración.
        const duration = previousEnd !== null && previousEnd > previousStart
          ? previousEnd - previousStart
          : DEFAULT_DURATION_MINUTES;
        startInput.value = minutesToTimeValue(Math.max(minutes - duration, 0));
        fireInput(startInput);
      }

      fireInput(picker.input);
    }

    function commit(picker) {
      const parsed = parseTimeText(picker.input.value);
      if (parsed === null) {
        if (picker.input.value) {
          picker.input.value = '';
          fireInput(picker.input);
        }
        return;
      }
      applyValue(picker, parsed);
    }

    pickers.forEach((picker) => {
      picker.activeIndex = -1;
      picker.options = [];

      const field = picker.input.closest('.time-field');
      field?.addEventListener('mousedown', (event) => {
        if (event.target.closest('.time-menu')) return;
        const wasOpen = !picker.menu.hidden;
        const onInput = event.target === picker.input;
        if (!onInput) {
          event.preventDefault();
          picker.input.focus();
        }
        if (wasOpen && !onInput) closeMenu(picker);
        else if (!wasOpen) openMenu(picker);
      });

      picker.input.addEventListener('focus', () => {
        pickers.filter(item => item !== picker).forEach(closeMenu);
        openMenu(picker);
      });

      picker.input.addEventListener('input', () => {
        if (picker.menu.hidden) picker.menu.hidden = false;
        picker.activeIndex = -1;
        renderMenu(picker);
      });

      picker.input.addEventListener('blur', () => {
        window.setTimeout(() => {
          if (picker.menu.contains(document.activeElement)) return;
          closeMenu(picker);
          commit(picker);
        }, 120);
      });

      picker.menu.addEventListener('mousedown', (event) => {
        const option = event.target.closest('.time-option');
        if (!option) return;
        event.preventDefault();
        applyValue(picker, Number(option.dataset.minutes));
        closeMenu(picker);
      });

      picker.input.addEventListener('keydown', (event) => {
        const isOpen = !picker.menu.hidden;
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          if (!isOpen) {
            openMenu(picker);
            return;
          }
          const total = picker.options.length;
          if (!total) return;
          const delta = event.key === 'ArrowDown' ? 1 : -1;
          picker.activeIndex = picker.activeIndex < 0
            ? (delta > 0 ? 0 : total - 1)
            : Math.max(0, Math.min(total - 1, picker.activeIndex + delta));
          renderMenu(picker);
          return;
        }
        if (event.key === 'Enter') {
          event.preventDefault();
          if (isOpen && picker.activeIndex >= 0 && picker.options[picker.activeIndex]) {
            applyValue(picker, picker.options[picker.activeIndex].minutes);
          } else {
            commit(picker);
          }
          closeMenu(picker);
          return;
        }
        if (event.key === 'Escape' && isOpen) {
          // Sin esto el Escape cerraría todo el modal.
          event.stopPropagation();
          closeMenu(picker);
          return;
        }
        if (event.key === 'Tab') {
          closeMenu(picker);
          commit(picker);
        }
      });
    });

    document.addEventListener('mousedown', (event) => {
      if (!event.target.closest?.('.time-field')) closeAll();
    });

    return {
      commitAll() {
        pickers.forEach(commit);
      },
      prefill() {
        if (startInput.value) return;
        const now = new Date();
        const next = Math.ceil((now.getHours() * 60 + now.getMinutes()) / 30) * 30;
        const start = Math.min(next, 23 * 60);
        startInput.value = minutesToTimeValue(start);
        endInput.value = minutesToTimeValue(Math.min(start + DEFAULT_DURATION_MINUTES, 24 * 60 - TIME_STEP_MINUTES));
        fireInput(startInput);
      },
    };
  }

  let directoryPromise = null;

  function loadDirectory() {
    if (!directoryPromise) {
      directoryPromise = fetch(`${API_BASE}/users`, { credentials: 'include' })
        .then(res => (res.ok ? res.json() : []))
        .then((rows) => {
          const people = new Map();
          (Array.isArray(rows) ? rows : []).forEach((row) => {
            const email = String(row.email_vintti || '').trim().toLowerCase();
            if (!email.includes('@')) return;
            const person = {
              email,
              name: String(row.nickname || row.user_name || '').trim() || displayNameFromEmail(email),
              role: String(row.role || row.team || '').trim(),
              // avatar_url casi nunca está cargado: caemos al mapa de avatares del hub.
              avatar: (typeof window.resolveUserAvatar === 'function'
                ? window.resolveUserAvatar({ avatar_url: row.avatar_url, email_vintti: email, user_id: row.user_id })
                : row.avatar_url) || '',
            };
            // Si el mismo email viene repetido, nos quedamos con la ficha que tenga foto.
            const existing = people.get(email);
            if (!existing || (!existing.avatar && person.avatar)) people.set(email, person);
          });
          return Array.from(people.values()).sort((a, b) => a.name.localeCompare(b.name, 'es'));
        })
        .catch(() => []);
    }
    return directoryPromise;
  }

  function isEmailLike(value) {
    return /^[^\s@,]+@[^\s@,]+\.[^\s@,]+$/.test(String(value || '').trim());
  }

  function initialsFor(person) {
    const source = person.name || person.email || '?';
    return source.trim().charAt(0).toUpperCase() || '?';
  }

  // Monograma siempre presente + foto encima; si la imagen falla se ve el monograma.
  function avatarMarkup(person, className) {
    const initial = person.external ? '@' : initialsFor(person);
    const image = person.avatar
      ? `<img src="${escapeHtml(person.avatar)}" alt="" loading="lazy" onerror="this.style.display='none';" />`
      : '';
    return `<span class="${className}"><span class="avatar-initial">${escapeHtml(initial)}</span>${image}</span>`;
  }

  function setupAttendeePicker() {
    const picker = document.getElementById('attendeePicker');
    const tokens = document.getElementById('attendeeTokens');
    const search = document.getElementById('attendeeSearch');
    const menu = document.getElementById('attendeeMenu');
    const hidden = document.getElementById('eventAttendees');
    if (!picker || !tokens || !search || !menu || !hidden) return null;

    const selected = [];
    let directory = [];
    let activeIndex = 0;

    function sync() {
      hidden.value = selected.map(person => person.email).join(', ');
      fireInput(hidden);
    }

    function renderTokens() {
      tokens.querySelectorAll('.attendee-token').forEach(node => node.remove());
      selected.forEach((person, index) => {
        const chip = document.createElement('span');
        chip.className = 'attendee-token';
        chip.title = person.email;
        chip.innerHTML = `
          ${avatarMarkup(person, 'attendee-token-avatar')}
          <span class="attendee-token-name">${escapeHtml(person.name)}</span>
          <button type="button" class="attendee-token-remove" data-index="${index}" aria-label="Quitar ${escapeHtml(person.name)}">&times;</button>
        `;
        tokens.insertBefore(chip, search);
      });
      search.placeholder = selected.length ? 'Agregar otro…' : 'Buscá a alguien de Vintti o escribí un email';
    }

    function candidates() {
      const query = search.value.trim().toLowerCase();
      const chosen = new Set(selected.map(person => person.email));
      const hostEmail = getStoredEmail();
      let list = directory.filter(person => !chosen.has(person.email) && person.email !== hostEmail);
      if (query) {
        list = list.filter(person => person.name.toLowerCase().includes(query) || person.email.includes(query));
      }
      list = list.slice(0, 40);

      if (query && isEmailLike(query) && !chosen.has(query) && !list.some(person => person.email === query)) {
        list.unshift({ email: query, name: query, role: 'Invitado externo', avatar: '', external: true });
      }
      return list;
    }

    function renderMenu() {
      const list = candidates();
      if (activeIndex >= list.length) activeIndex = Math.max(0, list.length - 1);

      menu.innerHTML = list.length
        ? list
          .map((person, index) => `
            <button type="button" class="attendee-option${index === activeIndex ? ' is-active' : ''}" role="option" data-email="${escapeHtml(person.email)}">
              ${avatarMarkup(person, 'attendee-option-avatar')}
              <span class="attendee-option-text">
                <span class="attendee-option-name">${escapeHtml(person.external ? `Invitar a ${person.email}` : person.name)}</span>
                <span class="attendee-option-email">${escapeHtml(person.external ? 'Invitado externo' : person.email)}</span>
              </span>
            </button>
          `)
          .join('')
        : '<div class="attendee-empty">Sin resultados</div>';

      menu.querySelector('.attendee-option.is-active')?.scrollIntoView({ block: 'nearest' });
    }

    function openMenu() {
      menu.hidden = false;
      picker.classList.add('is-open');
      renderMenu();
    }

    function closeMenu() {
      menu.hidden = true;
      picker.classList.remove('is-open');
    }

    function addEmail(email, fallbackName) {
      const clean = String(email || '').trim().toLowerCase();
      if (!isEmailLike(clean)) return false;
      if (selected.some(person => person.email === clean)) return true;
      const known = directory.find(person => person.email === clean);
      selected.push(known || { email: clean, name: fallbackName || displayNameFromEmail(clean), avatar: '' });
      renderTokens();
      sync();
      return true;
    }

    function removeAt(index) {
      if (index < 0 || index >= selected.length) return;
      selected.splice(index, 1);
      renderTokens();
      sync();
      renderMenu();
    }

    tokens.addEventListener('mousedown', (event) => {
      const remove = event.target.closest('.attendee-token-remove');
      if (remove) {
        event.preventDefault();
        removeAt(Number(remove.dataset.index));
        return;
      }
      if (event.target === search) return;
      event.preventDefault();
      search.focus();
      openMenu();
    });

    search.addEventListener('focus', () => {
      activeIndex = 0;
      openMenu();
    });

    search.addEventListener('input', () => {
      const value = search.value;
      // Escribir una coma confirma el email tipeado (para invitados externos).
      if (value.includes(',')) {
        const parts = value.split(',');
        const rest = parts.pop();
        parts.forEach(part => addEmail(part));
        search.value = rest.trim();
      }
      activeIndex = 0;
      openMenu();
    });

    search.addEventListener('paste', (event) => {
      const text = event.clipboardData?.getData('text') || '';
      if (!text.includes(',') && !/\s/.test(text.trim())) return;
      event.preventDefault();
      text.split(/[,;\s]+/).forEach(part => addEmail(part));
      search.value = '';
      renderMenu();
    });

    search.addEventListener('keydown', (event) => {
      const options = Array.from(menu.querySelectorAll('.attendee-option'));
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (menu.hidden) {
          openMenu();
          return;
        }
        if (!options.length) return;
        activeIndex = event.key === 'ArrowDown'
          ? Math.min(options.length - 1, activeIndex + 1)
          : Math.max(0, activeIndex - 1);
        renderMenu();
        return;
      }
      if (event.key === 'Enter') {
        event.preventDefault();
        const option = options[activeIndex];
        if (option) {
          addEmail(option.dataset.email);
          search.value = '';
          renderMenu();
        } else if (addEmail(search.value)) {
          search.value = '';
          renderMenu();
        }
        return;
      }
      if (event.key === 'Backspace' && !search.value && selected.length) {
        event.preventDefault();
        removeAt(selected.length - 1);
        return;
      }
      if (event.key === 'Escape' && !menu.hidden) {
        event.stopPropagation();
        closeMenu();
      }
    });

    search.addEventListener('blur', () => {
      window.setTimeout(() => {
        if (picker.contains(document.activeElement)) return;
        if (search.value.trim()) {
          addEmail(search.value);
          search.value = '';
        }
        closeMenu();
      }, 140);
    });

    menu.addEventListener('mousedown', (event) => {
      const option = event.target.closest('.attendee-option');
      if (!option) return;
      event.preventDefault();
      addEmail(option.dataset.email);
      search.value = '';
      search.focus();
      renderMenu();
    });

    document.addEventListener('mousedown', (event) => {
      if (!picker.contains(event.target)) closeMenu();
    });

    loadDirectory().then((people) => {
      directory = people;
      if (!menu.hidden) renderMenu();
    });

    renderTokens();

    return {
      clear() {
        selected.length = 0;
        search.value = '';
        renderTokens();
        sync();
        closeMenu();
      },
    };
  }

  async function init() {
    const today = new Date().toISOString().slice(0, 10);
    calendarDate.value = calendarDate.value || today;
    miniCalendarCursor = new Date(`${calendarDate.value}T12:00:00`);
    const eventDate = document.getElementById('eventDate');
    if (eventDate) eventDate.value = today;
    renderAvailabilityEmpty('Sin invitados para consultar.');
    setAvailabilityMessage('Abre el botón + para agregar invitados y consultar disponibilidad.');
    renderMiniCalendar();
    renderUpcomingEmpty('Cargando eventos del siguiente día...');

    [openEventModalBtn].forEach((trigger) => {
      trigger?.addEventListener('click', openEventModal);
    });
    closeEventModalBtn?.addEventListener('click', closeEventModal);
    eventModal?.addEventListener('click', (event) => {
      const target = event.target;
      if (target instanceof HTMLElement && target.dataset.closeModal === 'true') {
        closeEventModal();
      }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && eventModal && !eventModal.hidden) {
        closeEventModal();
      }
    });

    connectBtn.addEventListener('click', async () => {
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      handleConnect(userId);
    });
    disconnectBtn.addEventListener('click', async () => {
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      handleDisconnect(userId);
    });
    refreshBtn.addEventListener('click', async () => {
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      fetchEvents(userId);
    });
    miniCalendarPrev?.addEventListener('click', () => {
      miniCalendarCursor = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth() - 1, 1);
      renderMiniCalendar();
    });
    miniCalendarNext?.addEventListener('click', () => {
      miniCalendarCursor = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth() + 1, 1);
      renderMiniCalendar();
    });
    miniCalendarToday?.addEventListener('click', async () => {
      if (!calendarDate) return;
      calendarDate.value = todayIso();
      miniCalendarCursor = isoToDate(calendarDate.value);
      renderMiniCalendar();
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      fetchEvents(userId);
    });

    const pickDayFromClick = async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const btn = target.closest('[data-calendar-day]');
      if (!(btn instanceof HTMLElement)) return;
      const nextDate = btn.dataset.calendarDay;
      if (!nextDate || !calendarDate) return;
      calendarDate.value = nextDate;
      miniCalendarCursor = isoToDate(nextDate);
      renderMiniCalendar();
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      fetchEvents(userId);
    };

    miniCalendarGrid?.addEventListener('click', pickDayFromClick);
    upcomingEventsContainer?.addEventListener('click', pickDayFromClick);

    eventTimePickers = setupTimePickers();
    eventAttendeePicker = setupAttendeePicker();

    const attendeeInput = document.getElementById('eventAttendees');
    const eventDateInput = document.getElementById('eventDate');
    const eventStartInput = document.getElementById('eventStart');
    const eventEndInput = document.getElementById('eventEnd');
    let availabilityTimer = null;
    const scheduleAvailability = () => {
      if (availabilityTimer) window.clearTimeout(availabilityTimer);
      availabilityTimer = window.setTimeout(async () => {
        const emails = parseAttendees();
        if (!emails.length) {
          setAvailabilityMessage('Agrega emails para consultar disponibilidad.');
          renderAvailabilityEmpty('Sin invitados para consultar.');
          return;
        }
        const userId = await ensureUserIdOrNotify();
        if (!userId) return;
        fetchAvailability(userId);
      }, 450);
    };

    attendeeInput?.addEventListener('input', scheduleAvailability);
    eventDateInput?.addEventListener('change', scheduleAvailability);
    eventStartInput?.addEventListener('input', scheduleAvailability);
    eventEndInput?.addEventListener('input', scheduleAvailability);
    calendarDate?.addEventListener('change', async () => {
      miniCalendarCursor = new Date(`${getSelectedDate()}T12:00:00`);
      renderMiniCalendar();
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      fetchEvents(userId);
    });

    if (eventForm) {
      eventForm.addEventListener('submit', (event) => {
        event.preventDefault();
        resolveUserId().then((userId) => {
          if (!userId) {
            setStatus({ connected: false, message: 'No pudimos identificar el usuario.' });
            renderEmptyState('Inicia sesión para conectar tu calendario.');
            return;
          }
          // Normaliza lo tipeado a mano ("930" -> "09:30") antes de armar el payload.
          eventTimePickers?.commitAll();
          const date = document.getElementById('eventDate')?.value || today;
          const start = document.getElementById('eventStart')?.value || '';
          const end = document.getElementById('eventEnd')?.value || '';
          const attendees = (document.getElementById('eventAttendees')?.value || '')
            .split(',')
            .map(item => item.trim())
            .filter(Boolean);

          handleCreateEvent(userId, {
            summary: document.getElementById('eventTitle')?.value.trim() || '',
            start: `${date}T${start}`,
            end: `${date}T${end}`,
            location: document.getElementById('eventLocation')?.value.trim() || '',
            description: document.getElementById('eventDescription')?.value.trim() || '',
            attendees,
            create_meet: Boolean(document.getElementById('eventMeet')?.checked),
          });
        });
      });
    }

    const userId = await resolveUserId();
    if (!userId) {
      setStatus({ connected: false, message: 'No pudimos identificar el usuario.' });
      renderEmptyState('Inicia sesión para conectar tu calendario.');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/google-calendar/status?user_id=${encodeURIComponent(userId)}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (data.connected) {
        setStatus({ connected: true });
        await fetchEvents(userId);
      } else {
        setStatus({ connected: false });
        renderEmptyState('Conecta tu Google Calendar para ver las reuniones del día.');
      }
    } catch (error) {
      console.error(error);
      setStatus({ connected: false, message: 'Error consultando estado de conexión.' });
      renderEmptyState('No pudimos verificar la conexión.');
    }
  }

  init();
})();
