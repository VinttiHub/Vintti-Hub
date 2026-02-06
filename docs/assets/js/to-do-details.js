(() => {
  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const userId = Number(window.localStorage.getItem('user_id')) || null;

  const myList = document.getElementById('myTasks');
  const myEmpty = document.getElementById('myEmpty');
  const myForm = document.getElementById('myTaskForm');
  const myDescription = document.getElementById('myTaskDescription');
  const myDate = document.getElementById('myTaskDate');
  const myError = document.getElementById('myTaskError');
  const myToggle = document.getElementById('myTaskToggle');
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
  let teamUsers = [];
  let teamTasks = new Map();
  let currentTeamUserId = null;

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

  const buildMyTask = (task, editable, ownerId, tasksRef) => {
    const row = document.createElement('label');
    row.className = 'note-task';
    if (task.check) row.classList.add('is-done');
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
    date.textContent = formatDate(task.due_date);

    checkbox.addEventListener('change', async () => {
      const nextValue = checkbox.checked;
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
      } catch (error) {
        checkbox.checked = !nextValue;
        row.classList.toggle('is-done', checkbox.checked);
      }
    });

    if (editable) {
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
          if (ownerId === userId) {
            myTasks = tasksRef;
          } else {
            teamTasks.set(ownerId, tasksRef);
          }
          const siblings = tasksRef.filter((entry) => (entry.subtask || null) === (task.subtask || null));
          await persistOrder(ownerId, siblings);
          refreshCurrentView(ownerId);
        } catch (error) {
          setError(ownerId === userId ? myError : teamError, 'Could not delete task.');
        }
      });
      row.append(checkbox, textWrap, date, up, down, sub, del);
    } else {
      row.append(checkbox, textWrap, date);
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

  const renderTaskList = (container, tasks, emptyEl, editable, ownerId) => {
    container.innerHTML = '';
    if (!tasks.length) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;

    const topTasks = sortTasks(tasks.filter((task) => !task.subtask));
    const byParent = new Map();
    tasks
      .filter((task) => task.subtask)
      .forEach((task) => {
        if (!byParent.has(task.subtask)) byParent.set(task.subtask, []);
        byParent.get(task.subtask).push(task);
      });

    const list = document.createElement('div');
    list.className = 'note-list';
    list.dataset.parent = 'root';
    topTasks.forEach((task) => {
      list.appendChild(buildTaskRow(task, editable, ownerId, tasks));
      const children = sortTasks(byParent.get(task.to_do_id) || []);
      if (children.length) {
        const subList = document.createElement('div');
        subList.className = 'note-list note-list--sub';
        subList.dataset.parent = String(task.to_do_id);
        children.forEach((child) => subList.appendChild(buildTaskRow(child, editable, ownerId, tasks)));
        list.appendChild(subList);
      }
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
  };

  const refreshCurrentView = (ownerId) => {
    if (ownerId === userId) {
      renderTaskList(myList, myTasks, myEmpty, true, userId);
      renderParentOptions(myParent, myTasks);
      return;
    }
    const tasks = teamTasks.get(ownerId) || [];
    renderTaskList(teamList, tasks, teamEmpty, true, ownerId);
    renderParentOptions(teamParent, tasks);
  };

  const loadMyTasks = async () => {
    if (!userId) {
      renderTaskList(myList, [], myEmpty, true, userId);
      myEmpty.textContent = 'Log in to see your saved tasks.';
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/to_do?user_id=${encodeURIComponent(userId)}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      myTasks = Array.isArray(data) ? data : [];
      renderTaskList(myList, myTasks, myEmpty, true, userId);
    } catch (error) {
      renderTaskList(myList, [], myEmpty, true, userId);
      myEmpty.textContent = 'Could not load tasks right now.';
    }
  };

  const loadTeamTasks = async () => {
    if (!userId) return;
    try {
      const reportsRes = await fetch(`${API_BASE}/users/reports?leader_id=${encodeURIComponent(userId)}`, {
        credentials: 'include',
      });
      const reports = reportsRes.ok ? await reportsRes.json() : [];
      if (!Array.isArray(reports) || reports.length === 0) return;

      const tasksRes = await fetch(`${API_BASE}/to_do/team?leader_id=${encodeURIComponent(userId)}`, {
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
      renderTaskList(teamList, [], teamEmpty, true, userId);
      teamNotes.addEventListener('click', (event) => {
        const button = event.target.closest('.team-note');
        if (!button) return;
        const selected = teamUsers.find((u) => u.user_id === Number(button.dataset.userId));
        const isActive = button.classList.contains('is-active');
        if (isActive) {
          Array.from(teamNotes.children).forEach((note) => note.classList.remove('is-active'));
          teamTitle.textContent = 'Pick a teammate';
          renderTaskList(teamList, [], teamEmpty, true, userId);
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
    if (!userId) {
      setError(myError, 'Log in to add tasks.');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/to_do`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          user_id: userId,
          description,
          due_date: dueDate,
        }),
      });
      if (!res.ok) throw new Error('Failed');
      const newTask = await res.json();
      myTasks = [...myTasks, newTask];
      renderTaskList(myList, myTasks, myEmpty, true, userId);
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
      if (ownerId === userId) {
        myTasks = [...myTasks, newTask];
        renderTaskList(myList, myTasks, myEmpty, true, userId);
      } else {
        const existing = teamTasks.get(ownerId) || [];
        teamTasks.set(ownerId, [...existing, newTask]);
        renderTaskList(teamList, teamTasks.get(ownerId), teamEmpty, true, ownerId);
      }
    } catch (error) {
      setError(ownerId === userId ? myError : teamError, 'Could not add subtask.');
    }
  };

  const bindToggle = (button, form) => {
    if (!button || !form) return;
    button.addEventListener('click', () => {
      const isHidden = form.hasAttribute('hidden');
      if (isHidden) {
        form.removeAttribute('hidden');
      } else {
        form.setAttribute('hidden', '');
      }
    });
  };

  bindToggle(myToggle, myForm);
  bindToggle(teamToggle, teamForm);
  if (myForm) myForm.setAttribute('hidden', '');
  if (teamForm) teamForm.setAttribute('hidden', '');

  loadMyTasks();
  loadTeamTasks();
})();
