(() => {
  const DEFAULT_API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const configuredApiBase =
    window.VINTTI_API_BASE ||
    window.localStorage.getItem('vintti_api_base') ||
    DEFAULT_API_BASE;
  const API_BASE = String(configuredApiBase).replace(/\/+$/, '');

  let userId = null;

  const myList = document.getElementById('myTasks');
  const myEmpty = document.getElementById('myEmpty');
  const myForm = document.getElementById('myTaskForm');
  const myDescription = document.getElementById('myTaskDescription');
  const myDate = document.getElementById('myTaskDate');
  const myError = document.getElementById('myTaskError');
  const myToggle = document.getElementById('myTaskToggle');
  const myFilters = document.getElementById('myFilters');
  const myCountPending = document.getElementById('myCountPending');
  const myCountSoon = document.getElementById('myCountSoon');
  const myCountDone = document.getElementById('myCountDone');
  const backButton = document.getElementById('todoBackButton');
  const teamNotes = document.getElementById('teamNotes');
  const teamList = document.getElementById('teamTasks');
  const teamEmpty = document.getElementById('teamEmpty');
  const teamTitle = document.getElementById('teamTitle');
  const teamTab = document.getElementById('teamTab');
  const teamForm = document.getElementById('teamTaskForm');
  const teamDescription = document.getElementById('teamTaskDescription');
  const teamDate = document.getElementById('teamTaskDate');
  const teamError = document.getElementById('teamTaskError');
  const teamToggle = document.getElementById('teamTaskToggle');

  let myTasks = [];
  let myFilter = 'all';
  let teamUsers = [];
  let teamTasks = new Map();
  let currentTeamUserId = null;
  const AUTO_REFRESH_MS = 15000;
  let resolveUserIdInFlight = null;
  const TODO_REMINDER_DAYS_AHEAD = 2;
  const TODO_REMINDER_KEY_PREFIX = 'todo_due_reminder_signature_v1';
  const TODO_SYNC_KEY = 'todo_last_sync_v1';
  let todoReminderRequestInFlight = false;

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

  const getReturnUrl = () => {
    const params = new URLSearchParams(window.location.search);
    const fromParam = params.get('from');
    if (fromParam) return fromParam;
    if (document.referrer) return document.referrer;
    return '';
  };

  const isSafeReturn = (value) => {
    try {
      const url = new URL(value, window.location.href);
      return url.origin === window.location.origin;
    } catch (error) {
      return false;
    }
  };

  const returnUrl = getReturnUrl();
  if (backButton) {
    backButton.addEventListener('click', () => {
      if (returnUrl && isSafeReturn(returnUrl)) {
        window.location.href = returnUrl;
      } else {
        window.history.back();
      }
    });
  }

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

  const getDueStatus = (task) => {
    if (!task || task.check || !task.due_date) return '';
    const days = daysUntil(task.due_date);
    if (days === null) return '';
    if (days < 0) return 'overdue';
    if (days === 0) return 'today';
    if (days <= 2) return 'soon';
    return '';
  };

  const updateMyInsights = (tasks) => {
    if (!myCountPending || !myCountSoon || !myCountDone) return;
    const all = Array.isArray(tasks) ? tasks : [];
    const pending = all.filter((task) => !task.check).length;
    const done = all.filter((task) => task.check).length;
    const soon = all.filter((task) => {
      const status = getDueStatus(task);
      return status === 'today' || status === 'soon';
    }).length;
    myCountPending.textContent = String(pending);
    myCountSoon.textContent = String(soon);
    myCountDone.textContent = String(done);
  };

  const applyFilter = (tasks, filter) => {
    if (!Array.isArray(tasks) || !tasks.length) return [];
    if (filter === 'pending') return tasks.filter((task) => !task.check);
    if (filter === 'done') return tasks.filter((task) => Boolean(task.check));
    if (filter === 'soon') {
      return tasks.filter((task) => {
        const status = getDueStatus(task);
        return status === 'today' || status === 'soon';
      });
    }
    return tasks;
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

  const maybeSendMyTodoReminder = async (tasks) => {
    const activeUserId = syncUserId();
    if (!activeUserId || todoReminderRequestInFlight) return;

    const signature = buildReminderSignature(tasks);
    if (!signature) return;

    const storageKey = `${TODO_REMINDER_KEY_PREFIX}:${activeUserId}`;
    if (window.localStorage.getItem(storageKey) === signature) return;

    todoReminderRequestInFlight = true;
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
      todoReminderRequestInFlight = false;
    }
  };

  const buildMyTask = (task, editable, ownerId, tasksRef) => {
    const row = document.createElement('label');
    row.className = 'note-task';
    if (task.check) row.classList.add('is-done');
    if (!task.check && isNearDue(task.due_date)) row.classList.add('is-near-due');
    row.dataset.todoId = task.to_do_id;
    row.dataset.parent = task.subtask || 'root';
    row.draggable = false;

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'note-task__checkbox';
    checkbox.checked = Boolean(task.check);
    checkbox.disabled = !editable;

    const textWrap = document.createElement('div');
    const text = document.createElement('div');
    text.className = 'note-task__text';
    text.textContent = task.description || '';
    textWrap.appendChild(text);

    const date = document.createElement('span');
    date.className = 'note-task__date';
    const formattedDate = formatDate(task.due_date);
    if (!task.check && isNearDue(task.due_date) && formattedDate) {
      date.textContent = `${formattedDate} ⏳`;
    } else {
      date.textContent = formattedDate;
    }
    const dueStatus = getDueStatus(task);
    if (dueStatus === 'overdue') row.classList.add('is-near-due');

    const metaRow = document.createElement('div');
    metaRow.className = 'note-task__meta-row';
    if (formattedDate) metaRow.appendChild(date);
    const status = document.createElement('span');
    status.className = 'note-task__status';
    if (task.check) {
      status.textContent = 'Done';
    } else if (dueStatus === 'overdue') {
      status.textContent = 'Overdue';
      status.classList.add('note-task__status--overdue');
    } else if (dueStatus === 'today') {
      status.textContent = 'Today';
      status.classList.add('note-task__status--today');
    } else if (dueStatus === 'soon') {
      status.textContent = 'Soon';
      status.classList.add('note-task__status--soon');
    }
    if (status.textContent) metaRow.appendChild(status);
    if (metaRow.childNodes.length) textWrap.appendChild(metaRow);

    checkbox.addEventListener('change', async () => {
      if (!task.to_do_id) {
        task.check = !checkbox.checked;
        checkbox.checked = task.check;
        row.classList.toggle('is-done', checkbox.checked);
        return;
      }
      const nextValue = checkbox.checked;
      task.check = nextValue;
      row.classList.toggle('is-done', nextValue);
      try {
        const res = await fetch(`${API_BASE}/to_do/${task.to_do_id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ user_id: ownerId, check: nextValue }),
        });
        if (!res.ok) throw new Error('Failed');
        if (nextValue) {
          await moveTaskToEnd(tasksRef, ownerId, task);
        }
        if (ownerId === syncUserId()) {
          maybeSendMyTodoReminder(myTasks);
        }
        notifyTodoChange(nextValue ? 'completed' : 'unchecked');
      } catch (error) {
        task.check = !nextValue;
        checkbox.checked = !nextValue;
        row.classList.toggle('is-done', checkbox.checked);
      }
    });

    if (editable) {
      const actions = document.createElement('div');
      actions.className = 'note-task__actions';

      const up = document.createElement('button');
      up.type = 'button';
      up.className = 'note-task__move';
      up.textContent = '↑';
      up.addEventListener('click', (event) => {
        event.stopPropagation();
        moveTask(tasksRef, ownerId, task, -1);
      });

      const down = document.createElement('button');
      down.type = 'button';
      down.className = 'note-task__move';
      down.textContent = '↓';
      down.addEventListener('click', (event) => {
        event.stopPropagation();
        moveTask(tasksRef, ownerId, task, 1);
      });

      const sub = document.createElement('button');
      sub.type = 'button';
      sub.className = 'note-task__sub';
      sub.textContent = '+ Subtask';
      sub.addEventListener('click', async (event) => {
        event.stopPropagation();
        await promptSubtask(ownerId, task.to_do_id);
      });

      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'note-task__delete';
      del.textContent = '🗑️';
      del.addEventListener('click', async (event) => {
        event.stopPropagation();
        try {
          const res = await fetch(`${API_BASE}/to_do/${task.to_do_id}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ user_id: ownerId }),
          });
          if (!res.ok) throw new Error('Failed');
          tasksRef = tasksRef.filter((entry) => entry.to_do_id !== task.to_do_id && entry.subtask !== task.to_do_id);
          if (ownerId === syncUserId()) {
            myTasks = tasksRef;
          } else {
            teamTasks.set(ownerId, tasksRef);
          }
          const siblings = tasksRef.filter((entry) => (entry.subtask || null) === (task.subtask || null));
          await persistOrder(ownerId, siblings);
          refreshCurrentView(ownerId);
          notifyTodoChange('deleted');
        } catch (error) {
          setError(ownerId === syncUserId() ? myError : teamError, 'Could not delete task.');
        }
      });
      actions.append(up, down, sub, del);
      row.append(checkbox, textWrap, actions);
    } else {
      row.append(checkbox, textWrap);
    }
    return row;
  };

  const buildTaskRow = (task, editable, ownerId, tasksRef) => {
    const row = buildMyTask(task, editable, ownerId, tasksRef);
    if (task.subtask) row.classList.add('note-task--sub');
    return row;
  };

  const setError = (el, message) => {
    el.textContent = message;
    el.hidden = !message;
  };

  const pastelClasses = ['team-note--mint', 'team-note--butter', 'team-note--sky', 'team-note--lilac'];

  const renderTeamNotes = (users) => {
    teamNotes.innerHTML = '';
    users.forEach((user, index) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `team-note ${pastelClasses[index % pastelClasses.length]}`;
      btn.dataset.userId = user.user_id;
      btn.innerHTML = `
        <div class="team-note__name">${user.user_name}</div>
        <div class="team-note__meta">${user.team || 'Team'}</div>
      `;
      teamNotes.appendChild(btn);
    });
  };

  const sortTasks = (tasks) => {
    return [...tasks].sort((a, b) => {
      const aOrder = Number(a.orden) || 0;
      const bOrder = Number(b.orden) || 0;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return (a.to_do_id || 0) - (b.to_do_id || 0);
    });
  };

  const getVisibleTasks = (tasks, filter) => {
    const filtered = applyFilter(tasks, filter);
    if (filter === 'all') return filtered;
    const ids = new Set(filtered.map((task) => task.to_do_id));
    filtered.forEach((task) => {
      if (task.subtask) ids.add(task.subtask);
    });
    return tasks.filter((task) => ids.has(task.to_do_id));
  };

  const renderTaskList = (container, tasks, emptyEl, editable, ownerId, filter = 'all') => {
    container.innerHTML = '';
    const visibleTasks = getVisibleTasks(tasks, filter);
    if (!visibleTasks.length) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;

    const topTasks = sortTasks(visibleTasks.filter((task) => !task.subtask));
    const byParent = new Map();
    visibleTasks
      .filter((task) => task.subtask)
      .forEach((task) => {
        if (!byParent.has(task.subtask)) byParent.set(task.subtask, []);
        byParent.get(task.subtask).push(task);
      });

    const list = document.createElement('div');
    list.className = 'note-list';
    list.dataset.parent = 'root';
    topTasks.forEach((task) => {
      const parentRow = buildTaskRow(task, editable, ownerId, tasks);
      const children = sortTasks(byParent.get(task.to_do_id) || []);
      if (children.length) {
        const subContainer = document.createElement('div');
        subContainer.className = 'note-task__subtasks';
        subContainer.dataset.parent = String(task.to_do_id);
        children.forEach((child) => {
          const subRow = buildTaskRow(child, editable, ownerId, tasks);
          subRow.classList.add('note-subtask');
          subContainer.appendChild(subRow);
        });
        parentRow.appendChild(subContainer);
      }
      list.appendChild(parentRow);
    });
    container.appendChild(list);
    if (editable) enableDrag(list, ownerId, tasks);
  };

  const enableDrag = (root, ownerId, tasksRef) => {
    if (!root || !tasksRef) return;
    let dragged = null;
    root.querySelectorAll('.note-list').forEach((list) => {
      list.addEventListener('dragstart', (event) => {
        const item = event.target.closest('.note-task');
        if (!item || !item.draggable) return;
        dragged = item;
        event.dataTransfer.effectAllowed = 'move';
      });
      list.addEventListener('dragover', (event) => {
        if (!dragged) return;
        event.preventDefault();
        const target = event.target.closest('.note-task');
        if (!target) {
          list.appendChild(dragged);
          return;
        }
        if (target === dragged) return;
        if (target.dataset.parent !== dragged.dataset.parent) return;
        const rect = target.getBoundingClientRect();
        const after = event.clientY > rect.top + rect.height / 2;
        list.insertBefore(dragged, after ? target.nextSibling : target);
      });
      list.addEventListener('drop', async (event) => {
        if (!dragged) return;
        event.preventDefault();
        const parentId = list.dataset.parent || 'root';
        const items = Array.from(list.querySelectorAll('.note-task'))
          .filter((item) => item.dataset.parent === parentId)
          .map((item, index) => ({
            to_do_id: Number(item.dataset.todoId),
            orden: index + 1,
          }));
        await fetch(`${API_BASE}/to_do/reorder`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ user_id: ownerId, items }),
        });
        items.forEach((item) => {
          const entry = tasksRef.find((task) => task.to_do_id === item.to_do_id);
          if (entry) entry.orden = item.orden;
        });
        notifyTodoChange('reordered');
        dragged = null;
      });
      list.addEventListener('dragend', () => {
        dragged = null;
      });
    });
  };

  const moveTask = async (tasksRef, ownerId, task, direction) => {
    const parentKey = task.subtask || null;
    const siblings = sortTasks(tasksRef.filter((entry) => (entry.subtask || null) === parentKey));
    const index = siblings.findIndex((entry) => entry.to_do_id === task.to_do_id);
    if (index === -1) return;
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= siblings.length) return;
    const reordered = [...siblings];
    const [moved] = reordered.splice(index, 1);
    reordered.splice(targetIndex, 0, moved);
    const payload = reordered.map((entry, idx) => ({
      to_do_id: entry.to_do_id,
      orden: idx + 1,
    }));
    payload.forEach((entry) => {
      const target = tasksRef.find((t) => t.to_do_id === entry.to_do_id);
      if (target) target.orden = entry.orden;
    });
    await fetch(`${API_BASE}/to_do/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ user_id: ownerId, items: payload }),
    });
    refreshCurrentView(ownerId);
    notifyTodoChange('reordered');
  };

  const persistOrder = async (ownerId, items) => {
    if (!items.length) return;
    const ordered = sortTasks(items);
    const payload = ordered.map((task, index) => ({
      to_do_id: task.to_do_id,
      orden: index + 1,
    }));
    payload.forEach((entry) => {
      const task = items.find((t) => t.to_do_id === entry.to_do_id);
      if (task) task.orden = entry.orden;
    });
    await fetch(`${API_BASE}/to_do/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ user_id: ownerId, items: payload }),
    });
    notifyTodoChange('reordered');
  };

  const moveTaskToEnd = async (tasksRef, ownerId, task) => {
    const parentKey = task.subtask || null;
    const siblings = sortTasks(tasksRef.filter((entry) => (entry.subtask || null) === parentKey));
    const remaining = siblings.filter((entry) => entry.to_do_id !== task.to_do_id);
    const reordered = [...remaining, task];
    const payload = reordered.map((entry, index) => ({
      to_do_id: entry.to_do_id,
      orden: index + 1,
    }));
    payload.forEach((entry) => {
      const target = tasksRef.find((t) => t.to_do_id === entry.to_do_id);
      if (target) target.orden = entry.orden;
    });
    await fetch(`${API_BASE}/to_do/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ user_id: ownerId, items: payload }),
    });
    refreshCurrentView(ownerId);
    notifyTodoChange('reordered');
  };

  const refreshCurrentView = (ownerId) => {
    if (ownerId === syncUserId()) {
      updateMyInsights(myTasks);
      renderTaskList(myList, myTasks, myEmpty, true, userId, myFilter);
      return;
    }
    const tasks = teamTasks.get(ownerId) || [];
    renderTaskList(teamList, tasks, teamEmpty, true, ownerId);
  };

  const loadMyTasks = async () => {
    const activeUserId = await ensureUserId();
    if (!activeUserId) {
      renderTaskList(myList, [], myEmpty, true, userId);
      updateMyInsights([]);
      myEmpty.textContent = 'Log in to see your saved tasks.';
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/to_do?user_id=${encodeURIComponent(activeUserId)}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      myTasks = Array.isArray(data) ? data : [];
      updateMyInsights(myTasks);
      renderTaskList(myList, myTasks, myEmpty, true, activeUserId, myFilter);
      maybeSendMyTodoReminder(myTasks);
    } catch (error) {
      renderTaskList(myList, [], myEmpty, true, userId);
      updateMyInsights([]);
      myEmpty.textContent = 'Could not load tasks right now.';
    }
  };

  const loadTeamTasks = async () => {
    const activeUserId = await ensureUserId();
    if (!activeUserId) return;
    try {
      const reportsRes = await fetch(`${API_BASE}/users/reports?leader_id=${encodeURIComponent(activeUserId)}`, {
        credentials: 'include',
      });
      const reports = reportsRes.ok ? await reportsRes.json() : [];
      if (!Array.isArray(reports) || reports.length === 0) return;

      const tasksRes = await fetch(`${API_BASE}/to_do/team?leader_id=${encodeURIComponent(activeUserId)}`, {
        credentials: 'include',
      });
      const tasksData = tasksRes.ok ? await tasksRes.json() : [];

      teamTab.hidden = false;
      teamUsers = reports.map((report) => ({
        user_id: report.user_id,
        user_name: report.user_name || `User ${report.user_id}`,
        team: report.team || 'Team',
      }));
      teamTasks = new Map();
      teamUsers.forEach((user) => teamTasks.set(user.user_id, []));
      if (Array.isArray(tasksData)) {
        tasksData.forEach((task) => {
          if (!task.to_do_id) return;
          const holder = teamTasks.get(task.user_id);
          if (holder) holder.push(task);
        });
      }

      renderTeamNotes(teamUsers);
      const activate = (user) => {
        teamTitle.textContent = `${user.user_name}'s tasks`;
        currentTeamUserId = user.user_id;
        const tasks = teamTasks.get(user.user_id) || [];
        renderTaskList(teamList, tasks, teamEmpty, true, user.user_id);
        Array.from(teamNotes.children).forEach((note) => {
          note.classList.toggle('is-active', Number(note.dataset.userId) === user.user_id);
        });
      };
      teamTitle.textContent = 'Pick a teammate';
      renderTaskList(teamList, [], teamEmpty, true, activeUserId);
      teamNotes.addEventListener('click', (event) => {
        const button = event.target.closest('.team-note');
        if (!button) return;
        const selected = teamUsers.find((u) => u.user_id === Number(button.dataset.userId));
        const isActive = button.classList.contains('is-active');
        if (isActive) {
          Array.from(teamNotes.children).forEach((note) => note.classList.remove('is-active'));
          teamTitle.textContent = 'Pick a teammate';
          renderTaskList(teamList, [], teamEmpty, true, activeUserId);
          currentTeamUserId = null;
          return;
        }
        if (selected) activate(selected);
      });
    } catch (error) {
      teamTab.hidden = true;
    }
  };

  const tabs = Array.from(document.querySelectorAll('.notebook__tab'));
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((btn) => btn.classList.remove('is-active'));
      tab.classList.add('is-active');
      document.querySelectorAll('.notebook__panel').forEach((panel) => {
        panel.classList.remove('is-active');
        panel.hidden = true;
      });
      const target = tab.dataset.tab;
      const panel = document.getElementById(`tab-${target}`);
      if (panel) {
        panel.classList.add('is-active');
        panel.hidden = false;
      }
    });
  });

  myForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    setError(myError, '');

    const description = myDescription.value.trim();
    const dueDate = myDate.value;

    if (!description || !dueDate) {
      setError(myError, 'Add a task and due date.');
      return;
    }
    const activeUserId = await ensureUserId();
    if (!activeUserId) {
      setError(myError, 'Log in to add tasks.');
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
      if (!res.ok) throw new Error('Failed');
      const newTask = await res.json();
      myTasks = [...myTasks, newTask];
      updateMyInsights(myTasks);
      renderTaskList(myList, myTasks, myEmpty, true, activeUserId, myFilter);
      maybeSendMyTodoReminder(myTasks);
      notifyTodoChange('created');
      myDescription.value = '';
      myDate.value = '';
    } catch (error) {
      setError(myError, 'Could not add task right now.');
    }
  });

  teamForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    setError(teamError, '');
    if (!currentTeamUserId) {
      setError(teamError, 'Pick a teammate first.');
      return;
    }

    const description = teamDescription.value.trim();
    const dueDate = teamDate.value;

    if (!description || !dueDate) {
      setError(teamError, 'Add a task and due date.');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/to_do`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: currentTeamUserId,
          description,
          due_date: dueDate,
        }),
      });
      if (!res.ok) throw new Error('Failed');
      const newTask = await res.json();
      const existing = teamTasks.get(currentTeamUserId) || [];
      teamTasks.set(currentTeamUserId, [...existing, newTask]);
      renderTaskList(teamList, teamTasks.get(currentTeamUserId), teamEmpty, true, currentTeamUserId);
      notifyTodoChange('created');
      teamDescription.value = '';
      teamDate.value = '';
    } catch (error) {
      setError(teamError, 'Could not add task right now.');
    }
  });

  const promptSubtask = async (ownerId, parentId) => {
    const description = window.prompt('Subtask name?');
    if (!description) return;
    const dueDate = window.prompt('Due date (YYYY-MM-DD)?');
    if (!dueDate) return;

    try {
      const res = await fetch(`${API_BASE}/to_do`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: ownerId,
          description: description.trim(),
          due_date: dueDate,
          subtask: parentId,
        }),
      });
      if (!res.ok) throw new Error('Failed');
      const newTask = await res.json();
      if (ownerId === syncUserId()) {
        myTasks = [...myTasks, newTask];
        updateMyInsights(myTasks);
        renderTaskList(myList, myTasks, myEmpty, true, userId, myFilter);
        maybeSendMyTodoReminder(myTasks);
      } else {
        const existing = teamTasks.get(ownerId) || [];
        teamTasks.set(ownerId, [...existing, newTask]);
        renderTaskList(teamList, teamTasks.get(ownerId), teamEmpty, true, ownerId);
      }
      notifyTodoChange('created');
    } catch (error) {
      setError(ownerId === syncUserId() ? myError : teamError, 'Could not add subtask.');
    }
  };

  const bindToggle = (button, form, labels = {}) => {
    if (!button || !form) return;
    const closedLabel = labels.closedLabel || 'Add new task';
    const openLabel = labels.openLabel || 'Hide form';
    button.textContent = form.hasAttribute('hidden') ? closedLabel : openLabel;
    button.addEventListener('click', () => {
      const isHidden = form.hasAttribute('hidden');
      if (isHidden) {
        form.removeAttribute('hidden');
        button.textContent = openLabel;
      } else {
        form.setAttribute('hidden', '');
        button.textContent = closedLabel;
      }
    });
  };

  if (myForm) myForm.removeAttribute('hidden');
  bindToggle(myToggle, myForm, { closedLabel: 'Show quick add', openLabel: 'Hide quick add' });
  bindToggle(teamToggle, teamForm, { closedLabel: 'Add new task', openLabel: 'Hide form' });
  if (teamForm) teamForm.setAttribute('hidden', '');

  myFilters?.addEventListener('click', (event) => {
    const button = event.target.closest('.todo-filter');
    if (!button) return;
    const nextFilter = button.dataset.filter || 'all';
    if (nextFilter === myFilter) return;
    myFilter = nextFilter;
    Array.from(myFilters.querySelectorAll('.todo-filter')).forEach((chip) => {
      chip.classList.toggle('is-active', chip.dataset.filter === myFilter);
    });
    renderTaskList(myList, myTasks, myEmpty, true, syncUserId(), myFilter);
  });

  loadMyTasks();
  loadTeamTasks();

  // Keep personal ToDo updated when tasks are created externally.
  window.setInterval(() => {
    if (document.hidden) return;
    loadMyTasks();
  }, AUTO_REFRESH_MS);

  window.addEventListener('focus', () => {
    loadMyTasks();
  });

  window.addEventListener('storage', (event) => {
    if (event.key === TODO_SYNC_KEY || event.key === 'user_id') {
      loadMyTasks();
      loadTeamTasks();
    }
  });

  window.addEventListener('todo:changed', () => {
    loadMyTasks();
    loadTeamTasks();
  });
})();
