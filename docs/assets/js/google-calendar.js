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

  const tz = 'America/Argentina/Buenos_Aires';
  const refreshDefaultLabel = refreshBtn ? refreshBtn.textContent.trim() : '';
  let currentUserId = null;
  let miniCalendarCursor = null;
  const availabilityConfig = {
    dayStart: 8 * 60,
    dayEnd: 20 * 60,
    minuteHeight: 1.12,
  };
  const availabilityPalette = [
    { accent: '#0b3d91', bg: 'rgba(11, 61, 145, 0.18)', border: 'rgba(11, 61, 145, 0.32)' },
    { accent: '#0f7a5c', bg: 'rgba(15, 122, 92, 0.18)', border: 'rgba(15, 122, 92, 0.32)' },
    { accent: '#d16413', bg: 'rgba(209, 100, 19, 0.18)', border: 'rgba(209, 100, 19, 0.32)' },
    { accent: '#b42318', bg: 'rgba(180, 35, 24, 0.18)', border: 'rgba(180, 35, 24, 0.32)' },
    { accent: '#0f6da1', bg: 'rgba(15, 109, 161, 0.18)', border: 'rgba(15, 109, 161, 0.32)' },
    { accent: '#5a6b7f', bg: 'rgba(90, 107, 127, 0.18)', border: 'rgba(90, 107, 127, 0.32)' },
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
    refreshBtn.textContent = isRefreshing ? 'Refreshing…' : (refreshDefaultLabel || 'Refresh');
  }

  function setStatus({ connected, message }) {
    if (connected) {
      connectionBadge.textContent = 'Connected';
      connectionBadge.classList.add('is-connected');
      disconnectBtn.hidden = false;
      connectBtn.hidden = true;
      calendarStatus.textContent = message || 'Tus reuniones de Google Calendar están listas.';
    } else {
      connectionBadge.textContent = 'Not connected';
      connectionBadge.classList.remove('is-connected');
      disconnectBtn.hidden = true;
      connectBtn.hidden = false;
      calendarStatus.textContent = message || 'Connect your Google Calendar to see today’s meetings.';
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
    eventsContainer.innerHTML = `
      <div class="empty-state">
        <img src="./assets/img/calendar.png" alt="" />
        <p>${message}</p>
      </div>
    `;
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
    upcomingEventsContainer.innerHTML = `
      <div class="empty-state">
        <img src="./assets/img/calendar.png" alt="" />
        <p>${escapeHtml(message)}</p>
      </div>
    `;
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

  function shiftIsoDate(isoDate, amount) {
    const base = new Date(`${isoDate}T12:00:00`);
    base.setDate(base.getDate() + amount);
    return base.toISOString().slice(0, 10);
  }

  function formatCalendarLongDate(isoDate, locale = 'en-US') {
    const date = new Date(`${isoDate}T12:00:00`);
    return new Intl.DateTimeFormat(locale, {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
    }).format(date);
  }

  function renderMiniCalendar() {
    if (!miniCalendarGrid || !miniCalendarTitle || !calendarDate) return;
    const selected = new Date(`${getSelectedDate()}T12:00:00`);
    const current = miniCalendarCursor || new Date(selected.getFullYear(), selected.getMonth(), 1);
    miniCalendarCursor = new Date(current.getFullYear(), current.getMonth(), 1);

    miniCalendarTitle.textContent = new Intl.DateTimeFormat('en-US', {
      month: 'long',
      year: 'numeric',
    }).format(miniCalendarCursor);

    const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const monthStart = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth(), 1);
    const monthEnd = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth() + 1, 0);
    const firstWeekday = monthStart.getDay();
    const daysInMonth = monthEnd.getDate();
    const cells = [];

    weekdays.forEach((day) => {
      cells.push(`<div class="mini-calendar-weekday">${day}</div>`);
    });

    for (let i = 0; i < firstWeekday; i += 1) {
      cells.push('<div class="mini-calendar-day is-muted" aria-hidden="true"></div>');
    }

    const todayIso = new Date().toISOString().slice(0, 10);
    const selectedIso = getSelectedDate();

    for (let day = 1; day <= daysInMonth; day += 1) {
      const cellDate = new Date(miniCalendarCursor.getFullYear(), miniCalendarCursor.getMonth(), day);
      const iso = cellDate.toISOString().slice(0, 10);
      const classes = ['mini-calendar-day'];
      if (iso === selectedIso) classes.push('is-selected');
      if (iso === todayIso) classes.push('is-today');
      cells.push(`
        <button class="${classes.join(' ')}" type="button" data-calendar-day="${iso}">
          ${day}
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
    if (!start || !end) return 'All day';
    const startDate = new Date(start);
    const endDate = new Date(end);
    const fmt = new Intl.DateTimeFormat('es-AR', { hour: '2-digit', minute: '2-digit', timeZone: tz });
    return `${fmt.format(startDate)} - ${fmt.format(endDate)}`;
  }

  function renderEvents(events) {
    if (!events.length) {
      renderEmptyState('No hay reuniones para este día.');
      return;
    }

    eventsContainer.innerHTML = events
      .map(event => {
        const meetLink = event.hangoutLink || event.conferenceData?.entryPoints?.[0]?.uri;
        return `
          <div class="event-item">
            <div class="event-time">${formatEventTime(event)}</div>
            <div class="event-details">
              <h4>${event.summary || 'Sin título'}</h4>
              <p>${event.location || 'Ubicación por confirmar'}</p>
            </div>
            <div class="event-actions">
              ${meetLink ? `<a href="${meetLink}" target="_blank" rel="noopener">Open Meet</a>` : ''}
              ${event.htmlLink ? `<a href="${event.htmlLink}" target="_blank" rel="noopener">Open in Calendar</a>` : ''}
            </div>
          </div>
        `;
      })
      .join('');
  }

  function renderUpcomingEvents(events, baseDate) {
    if (upcomingSubtitle) {
      upcomingSubtitle.textContent = `Eventos de ${formatCalendarLongDate(baseDate)}.`;
    }
    if (!events.length) {
      renderUpcomingEmpty('No hay eventos para el siguiente día.');
      return;
    }

    upcomingEventsContainer.innerHTML = events
      .slice(0, 4)
      .map((event) => `
        <article class="upcoming-item">
          <div class="upcoming-time">${escapeHtml(formatEventTime(event))}</div>
          <h4>${escapeHtml(event.summary || 'Sin título')}</h4>
          <p>${escapeHtml(event.location || 'Ubicación por confirmar')}</p>
        </article>
      `)
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

  function getBusyLabel(events, slot) {
    if (!Array.isArray(events) || !events.length) return 'Ocupado';
    const busyStart = new Date(slot.start).getTime();
    const busyEnd = new Date(slot.end).getTime();
    const match = events.find(event => {
      const start = new Date(event.start).getTime();
      const end = new Date(event.end).getTime();
      return start < busyEnd && end > busyStart;
    });
    return match?.summary || 'Ocupado';
  }

  function collectAvailabilityEntries(emails, calendars, eventDetails) {
    const entries = [];
    emails.forEach((email, index) => {
      const busy = calendars?.[email]?.busy || [];
      const details = eventDetails?.[email] || [];
      const palette = availabilityPalette[index % availabilityPalette.length];
      busy.forEach((slot) => {
        const startDate = new Date(slot.start);
        const endDate = new Date(slot.end);
        const startMinutes = startDate.getHours() * 60 + startDate.getMinutes();
        const endMinutes = endDate.getHours() * 60 + endDate.getMinutes();
        entries.push({
          email,
          palette,
          label: getBusyLabel(details, slot),
          startMinutes,
          endMinutes,
        });
      });
    });

    return entries
      .filter((entry) => entry.endMinutes > entry.startMinutes)
      .sort((a, b) => a.startMinutes - b.startMinutes || a.endMinutes - b.endMinutes);
  }

  function layoutAvailabilityEntries(entries) {
    const active = [];
    const positioned = [];
    let maxColumn = 0;

    entries.forEach((entry) => {
      for (let i = active.length - 1; i >= 0; i -= 1) {
        if (active[i].endMinutes <= entry.startMinutes) active.splice(i, 1);
      }

      let column = 0;
      while (active.some((item) => item.column === column)) column += 1;
      active.push({ endMinutes: entry.endMinutes, column });
      positioned.push({ ...entry, column });
      if (column > maxColumn) maxColumn = column;
    });

    const totalColumns = Math.max(maxColumn + 1, 1);
    return positioned.map((entry) => ({
      ...entry,
      totalColumns,
    }));
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

    const { dayStart, dayEnd, minuteHeight } = availabilityConfig;
    const totalMinutes = dayEnd - dayStart;
    const slotHeight = 60 * minuteHeight;
    const timelineHeight = totalMinutes * minuteHeight;
    const proposed = getProposedRange();
    const proposedBlock = proposed ? {
      top: Math.max(proposed.startMinutes - dayStart, 0) * minuteHeight,
      height: Math.min(proposed.endMinutes, dayEnd) * minuteHeight - Math.max(proposed.startMinutes, dayStart) * minuteHeight,
    } : null;
    const legendItems = emails
      .map((email, index) => {
        const palette = availabilityPalette[index % availabilityPalette.length];
        return `
          <div class="availability-person">
            <span>${escapeHtml(getAvailabilityLabel(email, hostEmail))}</span>
            <span class="availability-swatch" style="--swatch-color:${palette.accent};"></span>
          </div>
        `;
      })
      .join('');
    const hours = [];
    for (let minutes = dayStart; minutes <= dayEnd; minutes += 60) {
      const hour = String(Math.floor(minutes / 60)).padStart(2, '0');
      hours.push(`${hour}:00`);
    }

    const timeSlots = hours
      .map(label => `<div class="availability-time-slot" style="--slot-height:${slotHeight}px;">${label}</div>`)
      .join('');

    const entries = layoutAvailabilityEntries(collectAvailabilityEntries(emails, calendars, eventDetails))
      .map((entry) => {
        const clampedStart = Math.max(entry.startMinutes, dayStart);
        const clampedEnd = Math.min(entry.endMinutes, dayEnd);
        if (clampedEnd <= dayStart || clampedStart >= dayEnd || clampedEnd <= clampedStart) return '';
        const top = (clampedStart - dayStart) * minuteHeight;
        const height = (clampedEnd - clampedStart) * minuteHeight;
        const duration = clampedEnd - clampedStart;
        const width = 100 / entry.totalColumns;
        const left = width * entry.column;
        const compactClass = duration <= 30 ? ' is-compact' : '';
        const tinyClass = duration <= 15 ? ' is-tiny' : '';
        const accessibleLabel = `${getAvailabilityLabel(entry.email, hostEmail)}: ${entry.label}`;
        return `
          <div
            class="availability-busy availability-busy--overlay${compactClass}${tinyClass}"
            style="top:${top}px;height:${height}px;left:calc(${left}% + 8px);width:calc(${width}% - 16px);--busy-bg:${entry.palette.bg};--busy-border:${entry.palette.border};--busy-text:${entry.palette.accent};"
            title="${escapeHtml(accessibleLabel)}"
          >
            <span class="availability-busy-owner">${escapeHtml(getAvailabilityLabel(entry.email, hostEmail))}</span>
            <span class="availability-busy-label">${escapeHtml(entry.label)}</span>
          </div>
        `;
      })
      .join('');

    return `
      <div class="availability-legend">
        ${legendItems}
      </div>
      <div class="availability-layout availability-layout--overlay" style="--slot-height:${slotHeight}px;--timeline-height:${timelineHeight}px;">
        <div class="availability-header availability-header--overlay">
          <div>Hora</div>
          <div>Agenda compartida</div>
        </div>
        <div class="availability-body">
          <div class="availability-time-column">${timeSlots}</div>
          <div class="availability-overlay-column">
            <div class="availability-timeline" style="--timeline-height:${timelineHeight}px;">
              ${proposedBlock && proposedBlock.height > 0 ? `
                <div class="availability-proposed" style="top:${proposedBlock.top}px;height:${proposedBlock.height}px;">
                  Horario propuesto
                </div>
              ` : ''}
              ${entries || '<div class="availability-free"></div>'}
            </div>
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

  async function fetchEvents(userId) {
    const date = getSelectedDate();
    const nextDate = shiftIsoDate(date, 1);
    calendarDate.value = date;
    renderMiniCalendar();

    try {
      setRefreshing(true);
      const [todayRes, nextRes] = await Promise.allSettled([
        fetchDayEvents(userId, date),
        fetchDayEvents(userId, nextDate),
      ]);

      if (todayRes.status === 'rejected') {
        const res = todayRes.reason;
        if (res?.status === 404) {
          setStatus({ connected: false, message: 'Necesitas conectar tu Google Calendar.' });
          renderEmptyState('Conecta tu Google Calendar para ver las reuniones del día.');
          renderUpcomingEmpty('Conecta tu Google Calendar para ver próximos eventos.');
          return;
        }
        throw res;
      }

      renderEvents(todayRes.value.events || []);

      if (nextRes.status === 'fulfilled') {
        renderUpcomingEvents(nextRes.value.events || [], nextDate);
      } else {
        renderUpcomingEmpty('No pudimos cargar los eventos del siguiente día.');
      }
    } catch (error) {
      console.error(error);
      renderEmptyState('No pudimos cargar tus reuniones. Intenta de nuevo.');
      renderUpcomingEmpty('No pudimos cargar los eventos del siguiente día.');
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
    miniCalendarGrid?.addEventListener('click', async (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const btn = target.closest('[data-calendar-day]');
      if (!(btn instanceof HTMLElement)) return;
      const nextDate = btn.dataset.calendarDay;
      if (!nextDate || !calendarDate) return;
      calendarDate.value = nextDate;
      miniCalendarCursor = new Date(`${nextDate}T12:00:00`);
      renderMiniCalendar();
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      fetchEvents(userId);
    });

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
