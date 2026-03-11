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

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const refreshDefaultLabel = refreshBtn ? refreshBtn.textContent.trim() : '';
  let currentUserId = null;

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
      if (formStatus) formStatus.textContent = 'Evento creado ✅';
      await fetchEvents(userId);
      eventForm?.reset();
      const eventMeet = document.getElementById('eventMeet');
      if (eventMeet) eventMeet.checked = true;
    } catch (error) {
      console.error(error);
      if (formStatus) formStatus.textContent = 'No se pudo crear el evento.';
    }
  }

  async function init() {
    const today = new Date().toISOString().slice(0, 10);
    calendarDate.value = calendarDate.value || today;
    const eventDate = document.getElementById('eventDate');
    if (eventDate) eventDate.value = today;

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
