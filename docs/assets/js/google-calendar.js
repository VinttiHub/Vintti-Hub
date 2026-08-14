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
  let eventTimePickers = null;
  let eventAttendeePicker = null;
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
