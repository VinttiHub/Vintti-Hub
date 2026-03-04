(() => {
  const currentPage = window.location.pathname.split('/').pop() || '';
  const chat = document.querySelector('.todo-chat');
  const hideFloatingOnly = currentPage === 'candidates.html';
  const hideFloatingAndStop = currentPage === 'account-details.html';
  if (hideFloatingAndStop) {
    if (chat) chat.style.display = 'none';
    return;
  }
  if (hideFloatingOnly && chat) {
    chat.classList.add('todo-chat--hidden');
    if (chat.querySelector('#todoPanel')) chat.querySelector('#todoPanel').hidden = true;
  }

  const DEFAULT_API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const configuredApiBase =
    window.VINTTI_API_BASE ||
    window.localStorage.getItem('vintti_api_base') ||
    DEFAULT_API_BASE;
  const API_BASE = String(configuredApiBase).replace(/\/+$/, '');
  let userId = null;

  const bubble = chat?.querySelector('#todoBubble') || null;
  const panel = chat?.querySelector('#todoPanel') || null;
  const closeBtn = chat?.querySelector('#todoClose') || null;
  const list = chat?.querySelector('#todoList') || null;
  const empty = chat?.querySelector('#todoEmpty') || null;
  const toast = chat?.querySelector('#todoToast') || null;
  const form = chat?.querySelector('#todoForm') || null;
  const descriptionInput = chat?.querySelector('#todoDescription') || null;
  const dateInput = chat?.querySelector('#todoDate') || null;
  const formError = chat?.querySelector('#todoFormError') || null;
  const detailsLink = chat?.querySelector('.todo-panel__details') || null;
  const openMode = chat?.dataset?.todoOpen || 'panel';
  const PRIMARY_ENTRY_ID = 'todoPrimaryEntry';
  let primaryEntry = null;
  const bubbleLabel = (() => {
    if (!bubble) return null;
    let el = bubble.querySelector('.todo-bubble__label');
    if (!el) {
      el = document.createElement('span');
      el.className = 'todo-bubble__label';
      el.textContent = 'To-Do';
      bubble.appendChild(el);
    }
    return el;
  })();
  const bubbleCount = (() => {
    if (!bubble) return null;
    let el = bubble.querySelector('.todo-bubble__count');
    if (!el) {
      el = document.createElement('span');
      el.className = 'todo-bubble__count';
      el.hidden = true;
      bubble.appendChild(el);
    }
    return el;
  })();

  let toastTimer = null;
  let currentTasks = [];
  let reminderRequestInFlight = false;
  let resolveUserIdInFlight = null;
  const TODO_REMINDER_DAYS_AHEAD = 2;
  const TODO_REMINDER_KEY_PREFIX = 'todo_due_reminder_signature_v1';
  const TODO_SYNC_KEY = 'todo_last_sync_v1';

  const syncUserId = () => {
    userId = Number(window.localStorage.getItem('user_id')) || null;
    return userId;
  };

  const resolveUserIdByEmail = async () => {
    const email = (window.localStorage.getItem('user_email') || window.sessionStorage.getItem('user_email') || '')
      .toLowerCase()
      .trim();
    if (!email) return null;
    try {
      const fast = await fetch(`${API_BASE}/users?email=${encodeURIComponent(email)}`, { credentials: 'include' });
      if (fast.ok) {
        const arr = await fast.json();
        const hit = Array.isArray(arr) ? arr.find((u) => (u.email_vintti || '').toLowerCase() === email) : null;
        if (hit?.user_id != null) {
          window.localStorage.setItem('user_id', String(hit.user_id));
          window.localStorage.setItem('user_id_owner_email', email);
          return Number(hit.user_id);
        }
      }
    } catch (_) {}
    return null;
  };

  const ensureUserId = async () => {
    const cached = syncUserId();
    if (cached) return cached;
    if (resolveUserIdInFlight) return resolveUserIdInFlight;
    resolveUserIdInFlight = resolveUserIdByEmail()
      .catch(() => null)
      .finally(() => {
        resolveUserIdInFlight = null;
      });
    const resolved = await resolveUserIdInFlight;
    return resolved || syncUserId();
  };

  const notifyTodoChange = (reason = 'updated') => {
    const payload = JSON.stringify({
      reason,
      user_id: syncUserId(),
      at: Date.now(),
    });
    window.localStorage.setItem(TODO_SYNC_KEY, payload);
    window.dispatchEvent(new CustomEvent('todo:changed', { detail: payload }));
  };

  const formatDate = (raw) => {
    if (!raw) return '';
    const date = new Date(`${raw}T00:00:00`);
    if (Number.isNaN(date.getTime())) return raw;
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const isOverdue = (raw) => {
    if (!raw) return false;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const due = new Date(`${raw}T00:00:00`);
    return due < today;
  };

  const daysUntil = (raw) => {
    if (!raw) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const due = new Date(`${raw}T00:00:00`);
    if (Number.isNaN(due.getTime())) return null;
    return Math.round((due - today) / 86400000);
  };

  const isNearDue = (raw) => {
    const days = daysUntil(raw);
    return days !== null && days >= 0 && days <= 2;
  };

  const updateBubbleState = (tasks) => {
    const items = Array.isArray(tasks) ? tasks : [];
    const pending = items.filter((task) => !task.check).length;
    const urgent = items.filter((task) => !task.check && (isOverdue(task.due_date) || isNearDue(task.due_date))).length;
    if (bubble) {
      if (bubbleLabel) bubbleLabel.textContent = 'To-Do';
      if (bubbleCount) {
        bubbleCount.textContent = pending > 99 ? '99+' : String(pending);
        bubbleCount.hidden = pending === 0;
      }
      bubble.classList.toggle('has-pending', pending > 0);
      bubble.classList.toggle('has-due-soon', urgent > 0);
      const aria =
        pending > 0 ? `Open to-do list. You have ${pending} pending tasks.` : 'Open to-do list.';
      bubble.setAttribute('aria-label', aria);
      bubble.setAttribute('title', pending > 0 ? `To-Do: ${pending} pending` : 'Open To-Do');
    }

    const syncBadge = (host, selector) => {
      if (!host) return;
      let badge = host.querySelector(selector);
      if (!badge) {
        badge = document.createElement('span');
        badge.className = selector.replace('.', '');
        host.appendChild(badge);
      }
      badge.textContent = pending > 99 ? '99+' : String(pending);
      badge.hidden = pending === 0;
    };

    const sidebarLink = document.getElementById('todoSidebarLink');
    if (sidebarLink) {
      syncBadge(sidebarLink, '.todo-access-badge');
      sidebarLink.classList.toggle('has-pending', pending > 0);
    }

    const primary = ensurePrimaryEntry();
    if (primary) {
      syncBadge(primary, '.todo-primary-entry__count');
      primary.classList.toggle('has-urgent', urgent > 0);
      primary.setAttribute('title', pending > 0 ? `To-Do: ${pending} pendientes` : 'Ir a To-Do');
      chat?.classList.add('todo-chat--secondary');
    } else {
      chat?.classList.remove('todo-chat--secondary');
    }
  };

  const injectAccessStyles = () => {
    if (document.getElementById('todoAccessStyles')) return;
    const style = document.createElement('style');
    style.id = 'todoAccessStyles';
    style.textContent = `
      .todo-primary-entry {
        border: 1px solid rgba(238, 183, 208, 0.95);
        background: linear-gradient(135deg, #fff7fb, #ffeef7);
        color: #5a2441;
        border-radius: 999px;
        padding: 10px 14px;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-weight: 700;
        font-size: 14px;
        cursor: pointer;
        box-shadow: 0 8px 18px rgba(235, 149, 188, 0.25);
      }
      .todo-primary-entry:hover { transform: translateY(-1px); }
      .todo-primary-entry__count, .todo-access-badge {
        min-width: 22px;
        height: 22px;
        padding: 0 6px;
        border-radius: 999px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 11px;
        font-weight: 800;
        background: #fff;
        border: 1px solid rgba(198, 109, 153, 0.42);
        color: #8a2d58;
      }
      .todo-primary-entry.has-urgent { box-shadow: 0 0 0 3px rgba(252, 217, 234, 0.62), 0 10px 24px rgba(236, 137, 183, 0.35); }
      #todoSidebarLink .menu-label { display: inline-flex; align-items: center; gap: 8px; }
      #todoSidebarLink.has-pending .menu-icon { color: #0044ff; }
      .sidebar.collapsed #todoSidebarLink .todo-access-badge { display: none !important; }
      .todo-chat.todo-chat--hidden { display: none !important; }
      @media (max-width: 900px) {
        .todo-primary-entry { padding: 8px 12px; font-size: 13px; }
        .todo-chat.todo-chat--secondary { opacity: 1; transform: none; }
      }
      @media (min-width: 901px) {
        .todo-chat.todo-chat--secondary { display: none; }
      }
    `;
    document.head.appendChild(style);
  };

  const ensurePrimaryEntry = () => {
    const actions = document.querySelector('.page-actions');
    if (!actions) return null;
    let entry = document.getElementById(PRIMARY_ENTRY_ID);
    if (!entry) {
      entry = document.createElement('button');
      entry.type = 'button';
      entry.id = PRIMARY_ENTRY_ID;
      entry.className = 'todo-primary-entry';
      entry.innerHTML = '<span>To-Do</span>';
      entry.addEventListener('click', () => {
        window.location.href = buildDetailsUrl();
      });
      actions.insertBefore(entry, actions.firstChild || null);
    }
    primaryEntry = entry;
    return primaryEntry;
  };

  const localDateKey = () => {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };

  const buildReminderSignature = (tasks) => {
    const dueSoonPending = (Array.isArray(tasks) ? tasks : [])
      .filter((task) => {
        if (!task || task.check || !task.due_date) return false;
        const days = daysUntil(task.due_date);
        return days !== null && days <= TODO_REMINDER_DAYS_AHEAD;
      })
      .sort((a, b) => (a.to_do_id || 0) - (b.to_do_id || 0))
      .map((task) => {
        const days = daysUntil(task.due_date);
        return `${task.to_do_id || 'x'}:${task.due_date}:${days}`;
      });

    if (!dueSoonPending.length) return '';
    return `${localDateKey()}|${dueSoonPending.join('|')}`;
  };

  const maybeSendDueReminder = async (tasks) => {
    const activeUserId = syncUserId();
    if (!activeUserId || reminderRequestInFlight) return;

    const signature = buildReminderSignature(tasks);
    if (!signature) return;

    const storageKey = `${TODO_REMINDER_KEY_PREFIX}:${activeUserId}`;
    if (window.localStorage.getItem(storageKey) === signature) return;

    reminderRequestInFlight = true;
    try {
      const res = await fetch(`${API_BASE}/to_do/reminders/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: activeUserId,
          days_ahead: TODO_REMINDER_DAYS_AHEAD,
          include_overdue: true,
        }),
      });
      if (!res.ok) throw new Error('Failed to send ToDo reminder');
      window.localStorage.setItem(storageKey, signature);
    } catch (error) {
      console.warn('⚠️ ToDo reminder email was not sent:', error);
    } finally {
      reminderRequestInFlight = false;
    }
  };

  const showToast = (message) => {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('is-visible');
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => {
      toast.classList.remove('is-visible');
    }, 1600);
  };

  const setEmptyState = (message) => {
    if (!empty) return;
    empty.textContent = message;
    empty.hidden = false;
  };

  const clearEmptyState = () => {
    if (!empty) return;
    empty.hidden = true;
  };

  const buildItem = (task) => {
    const wrapper = document.createElement('label');
    wrapper.className = 'todo-item';
    if (task.check) wrapper.classList.add('is-done');
    if (!task.check && isOverdue(task.due_date)) wrapper.classList.add('is-overdue');
    if (!task.check && isNearDue(task.due_date)) wrapper.classList.add('is-near-due');
    if (task.subtask) wrapper.classList.add('todo-item--sub');
    wrapper.dataset.todoId = task.to_do_id;
    wrapper.dataset.parent = task.subtask || 'root';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'todo-item__check';
    checkbox.checked = Boolean(task.check);

    const text = document.createElement('span');
    text.className = 'todo-item__text';
    text.textContent = task.description || '';

    const date = document.createElement('span');
    date.className = 'todo-item__date';
    const formattedDate = formatDate(task.due_date);
    if (!task.check && isNearDue(task.due_date) && formattedDate) {
      date.textContent = `${formattedDate} ⏳`;
    } else {
      date.textContent = formattedDate;
    }

    checkbox.addEventListener('change', async () => {
      const nextValue = checkbox.checked;
      task.check = nextValue;
      wrapper.classList.toggle('is-done', nextValue);
      if (nextValue) showToast('Good job!');

      try {
        const activeUserId = syncUserId();
        if (!activeUserId) throw new Error('Missing user id');
        const res = await fetch(`${API_BASE}/to_do/${task.to_do_id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ user_id: activeUserId, check: nextValue }),
        });
        if (!res.ok) throw new Error('Failed to update task');
        if (nextValue) {
          await moveTaskToEnd(task);
          renderTasks(currentTasks);
        }
        notifyTodoChange(nextValue ? 'completed' : 'unchecked');
      } catch (error) {
        task.check = !nextValue;
        checkbox.checked = !nextValue;
        wrapper.classList.toggle('is-done', checkbox.checked);
        showToast('Oops, try again.');
      }
    });

    wrapper.append(checkbox, text, date);
    return wrapper;
  };

  const renderTasks = (tasks) => {
    const taskList = Array.isArray(tasks) ? tasks : [];
    if (!list) {
      currentTasks = taskList;
      updateBubbleState(taskList);
      return;
    }
    list.innerHTML = '';
    if (!taskList.length) {
      currentTasks = [];
      updateBubbleState([]);
      setEmptyState('No tasks yet. Add your first one.');
      return;
    }

    clearEmptyState();
    currentTasks = taskList;
    updateBubbleState(taskList);

    const topTasks = sortTasks(taskList.filter((task) => !task.subtask));
    const subTasks = taskList.filter((task) => task.subtask);
    const byParent = new Map();
    subTasks.forEach((task) => {
      if (!byParent.has(task.subtask)) byParent.set(task.subtask, []);
      byParent.get(task.subtask).push(task);
    });
    topTasks.forEach((task) => {
      list.appendChild(buildItem(task));
      const children = sortTasks(byParent.get(task.to_do_id) || []);
      children.forEach((child) => list.appendChild(buildItem(child)));
    });
  };

  const sortTasks = (items) =>
    [...items].sort((a, b) => {
      const aOrder = Number(a.orden) || 0;
      const bOrder = Number(b.orden) || 0;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return (a.to_do_id || 0) - (b.to_do_id || 0);
    });

  const fetchTasks = async () => {
    const activeUserId = await ensureUserId();
    if (!activeUserId) {
      renderTasks([]);
      setEmptyState('Log in to save and sync your tasks.');
      return;
    }

    list?.classList.add('is-loading');
    try {
      const res = await fetch(`${API_BASE}/to_do?user_id=${encodeURIComponent(activeUserId)}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed to load tasks');
      const data = await res.json();
      const tasks = Array.isArray(data) ? data : [];
      renderTasks(tasks);
      maybeSendDueReminder(tasks);
    } catch (error) {
      renderTasks([]);
      updateBubbleState([]);
      setEmptyState('Could not load tasks. Try again soon.');
    } finally {
      list?.classList.remove('is-loading');
    }
  };

  const openPanel = () => {
    if (!panel || !bubble) return;
    panel.hidden = false;
    chat.classList.add('is-open');
    bubble.setAttribute('aria-expanded', 'true');
    fetchTasks();
  };

  const closePanel = () => {
    if (!panel || !bubble) return;
    chat.classList.remove('is-open');
    bubble.setAttribute('aria-expanded', 'false');
    panel.hidden = true;
  };

  const buildDetailsUrl = () => {
    const href = detailsLink?.getAttribute('href') || 'to-do-details.html';
    const url = new URL(href, window.location.href);
    url.searchParams.set('from', window.location.href);
    return url.toString();
  };

  const openDetailsTab = () => {
    window.open(buildDetailsUrl(), '_blank', 'noopener');
  };

  bubble?.addEventListener('click', (event) => {
    event.stopPropagation();
    if (openMode === 'new-tab') {
      openDetailsTab();
      return;
    }
    if (chat?.classList.contains('is-open')) {
      closePanel();
    } else {
      openPanel();
    }
  });

  closeBtn?.addEventListener('click', (event) => {
    event.stopPropagation();
    closePanel();
  });

  document.addEventListener('click', (event) => {
    if (!chat) return;
    if (!chat.contains(event.target)) closePanel();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closePanel();
  });

  form?.addEventListener('submit', async (event) => {
    event.preventDefault();
    formError.textContent = '';
    formError.hidden = true;

    const description = descriptionInput.value.trim();
    const dueDate = dateInput.value;

    if (!description || !dueDate) {
      formError.textContent = 'Add the task and presentation date first.';
      formError.hidden = false;
      return;
    }

    const activeUserId = await ensureUserId();
    if (!activeUserId) {
      formError.textContent = 'Log in to save tasks.';
      formError.hidden = false;
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/to_do`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: activeUserId,
          description,
          due_date: dueDate,
        }),
      });

      if (!res.ok) throw new Error('Failed to add task');
      const newTask = await res.json();
      currentTasks = [newTask, ...currentTasks];
      renderTasks(currentTasks);
      maybeSendDueReminder(currentTasks);
      notifyTodoChange('created');
      clearEmptyState();
      descriptionInput.value = '';
      dateInput.value = '';
      showToast('Task added!');
    } catch (error) {
      formError.textContent = 'Could not add task. Try again.';
      formError.hidden = false;
    }
  });

  const moveTaskToEnd = async (task) => {
    const parentKey = task.subtask || null;
    const siblings = sortTasks(currentTasks.filter((entry) => (entry.subtask || null) === parentKey));
    const remaining = siblings.filter((entry) => entry.to_do_id !== task.to_do_id);
    const reordered = [...remaining, task];
    const payload = reordered.map((entry, index) => ({
      to_do_id: entry.to_do_id,
      orden: index + 1,
    }));
    currentTasks = currentTasks.map((entry) => {
      const update = payload.find((item) => item.to_do_id === entry.to_do_id);
      return update ? { ...entry, orden: update.orden } : entry;
    });
    const activeUserId = syncUserId();
    if (!activeUserId) return;
    await fetch(`${API_BASE}/to_do/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ user_id: activeUserId, items: payload }),
    });
    notifyTodoChange('reordered');
  };

  window.addEventListener('storage', (event) => {
    if (event.key === TODO_SYNC_KEY || event.key === 'user_id') fetchTasks();
  });

  window.addEventListener('todo:changed', () => {
    fetchTasks();
  });

  window.addEventListener('focus', () => {
    fetchTasks();
  });

  document.addEventListener('sidebar:loaded', () => {
    updateBubbleState(currentTasks);
  });

  injectAccessStyles();
  ensurePrimaryEntry();
  updateBubbleState([]);
  fetchTasks();
})();
