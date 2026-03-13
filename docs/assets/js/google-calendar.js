(() => {
  const DEFAULT_API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const API_BASE = String(window.VINTTI_API_BASE || window.API_BASE || DEFAULT_API_BASE).replace(/\/+$/, '');

  const connectBtn = document.getElementById('connectBtn');
  const disconnectBtn = document.getElementById('disconnectBtn');
  const calendarStatus = document.getElementById('calendarStatus');
  const connectionBadge = document.getElementById('connectionBadge');
  const eventsContainer = document.getElementById('eventsContainer');
  const calendarDate = document.getElementById('calendarDate');
  const refreshBtn = document.getElementById('refreshBtn');
  const eventForm = document.getElementById('eventForm');
  const formStatus = document.getElementById('formStatus');
  const availabilityGrid = document.getElementById('availabilityGrid');
  const availabilityBtn = document.getElementById('availabilityBtn');
  const availabilityStatus = document.getElementById('availabilityStatus');

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const refreshDefaultLabel = refreshBtn ? refreshBtn.textContent.trim() : '';
  let currentUserId = null;
  const availabilityConfig = {
    dayStart: 8 * 60,
    dayEnd: 20 * 60,
    minuteHeight: 0.9,
  };

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
    if (!availabilityGrid) return;
    availabilityGrid.innerHTML = `
      <div class="empty-state">
        <img src="./assets/img/calendar.png" alt="" />
        <p>${escapeHtml(message)}</p>
      </div>
    `;
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

  function formatEventTime(event) {
    const start = event.start?.dateTime || event.start?.date;
    const end = event.end?.dateTime || event.end?.date;
    if (!start || !end) return 'All day';
    const startDate = new Date(start);
    const endDate = new Date(end);
    const fmt = new Intl.DateTimeFormat('es-AR', { hour: '2-digit', minute: '2-digit' });
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

  function renderAvailability(emails, calendars, eventDetails) {
    if (!availabilityGrid) return;
    if (!emails.length) {
      renderAvailabilityEmpty('Sin invitados para consultar.');
      return;
    }

    const { dayStart, dayEnd, minuteHeight } = availabilityConfig;
    const totalMinutes = dayEnd - dayStart;
    const slotHeight = 60 * minuteHeight;
    const timelineHeight = totalMinutes * minuteHeight;
    const hours = [];
    for (let minutes = dayStart; minutes <= dayEnd; minutes += 60) {
      const hour = String(Math.floor(minutes / 60)).padStart(2, '0');
      hours.push(`${hour}:00`);
    }

    const headerCells = emails
      .map(email => `<div>${escapeHtml(displayNameFromEmail(email))}</div>`)
      .join('');

    const timeSlots = hours
      .map(label => `<div class="availability-time-slot" style="--slot-height:${slotHeight}px;">${label}</div>`)
      .join('');

    const attendeeColumns = emails
      .map(email => {
        const busy = calendars?.[email]?.busy || [];
        const details = eventDetails?.[email] || [];
        const blocks = busy
          .map(slot => {
            const startDate = new Date(slot.start);
            const endDate = new Date(slot.end);
            const startMinutes = startDate.getHours() * 60 + startDate.getMinutes();
            const endMinutes = endDate.getHours() * 60 + endDate.getMinutes();
            const clampedStart = Math.max(startMinutes, dayStart);
            const clampedEnd = Math.min(endMinutes, dayEnd);
            if (clampedEnd <= dayStart || clampedStart >= dayEnd || clampedEnd <= clampedStart) {
              return '';
            }
            const top = (clampedStart - dayStart) * minuteHeight;
            const height = (clampedEnd - clampedStart) * minuteHeight;
            const label = getBusyLabel(details, slot);
            return `
              <div class="availability-busy" style="top:${top}px;height:${height}px;">
                ${escapeHtml(label)}
              </div>
            `;
          })
          .join('');

        return `
          <div class="availability-attendee-column">
            <div class="availability-timeline" style="--timeline-height:${timelineHeight}px;">
              ${blocks || '<div class="availability-free"></div>'}
            </div>
          </div>
        `;
      })
      .join('');

    availabilityGrid.innerHTML = `
      <div class="availability-layout" style="--slot-height:${slotHeight}px;--timeline-height:${timelineHeight}px;">
        <div class="availability-header">
          <div>Hora</div>
          ${headerCells}
        </div>
        <div class="availability-body">
          <div class="availability-time-column">${timeSlots}</div>
          ${attendeeColumns}
        </div>
      </div>
    `;
  }

  async function fetchEvents(userId) {
    const date = calendarDate.value || new Date().toISOString().slice(0, 10);
    calendarDate.value = date;

    try {
      setRefreshing(true);
      const res = await fetch(
        `${API_BASE}/google-calendar/events?user_id=${encodeURIComponent(userId)}&date=${encodeURIComponent(date)}&timezone=${encodeURIComponent(tz)}`,
        { credentials: 'include' },
      );
      if (!res.ok) {
        if (res.status === 404) {
          setStatus({ connected: false, message: 'Necesitas conectar tu Google Calendar.' });
          renderEmptyState('Conecta tu Google Calendar para ver las reuniones del día.');
          return;
        }
        throw new Error(await res.text());
      }
      const data = await res.json();
      renderEvents(data.events || []);
    } catch (error) {
      console.error(error);
      renderEmptyState('No pudimos cargar tus reuniones. Intenta de nuevo.');
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
    } catch (error) {
      console.error(error);
      if (formStatus) formStatus.textContent = 'No se pudo crear el evento.';
    }
  }

  async function fetchAvailability(userId) {
    const emails = parseAttendees();
    if (!emails.length) {
      if (availabilityStatus) availabilityStatus.textContent = 'Agrega emails para consultar disponibilidad.';
      renderAvailabilityEmpty('Sin invitados para consultar.');
      return;
    }

    const date = document.getElementById('eventDate')?.value || calendarDate.value || new Date().toISOString().slice(0, 10);
    if (availabilityStatus) availabilityStatus.textContent = 'Consultando disponibilidad...';

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
      renderAvailability(emails, data.calendars || {}, data.events || {});
      if (availabilityStatus) availabilityStatus.textContent = `Disponibilidad para ${emails.length} invitados el ${date}.`;
    } catch (error) {
      console.error(error);
      if (availabilityStatus) availabilityStatus.textContent = 'No pudimos consultar disponibilidad.';
      renderAvailabilityEmpty('No pudimos cargar la disponibilidad.');
    }
  }

  async function init() {
    const today = new Date().toISOString().slice(0, 10);
    calendarDate.value = calendarDate.value || today;
    const eventDate = document.getElementById('eventDate');
    if (eventDate) eventDate.value = today;
    renderAvailabilityEmpty('Sin invitados para consultar.');

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
    availabilityBtn?.addEventListener('click', async () => {
      const userId = await ensureUserIdOrNotify();
      if (!userId) return;
      fetchAvailability(userId);
    });

    const attendeeInput = document.getElementById('eventAttendees');
    const eventDateInput = document.getElementById('eventDate');
    let availabilityTimer = null;
    const scheduleAvailability = () => {
      if (availabilityTimer) window.clearTimeout(availabilityTimer);
      availabilityTimer = window.setTimeout(async () => {
        const emails = parseAttendees();
        if (!emails.length) {
          if (availabilityStatus) availabilityStatus.textContent = 'Agrega emails para consultar disponibilidad.';
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
