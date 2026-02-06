(() => {
  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const userId = Number(window.localStorage.getItem('user_id')) || null;

  const myList = document.getElementById('myTasks');
  const myEmpty = document.getElementById('myEmpty');
  const teamNotes = document.getElementById('teamNotes');
  const teamList = document.getElementById('teamTasks');
  const teamEmpty = document.getElementById('teamEmpty');
  const teamTitle = document.getElementById('teamTitle');
  const teamTab = document.getElementById('teamTab');

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

  const buildMyTask = (task) => {
    const row = document.createElement('label');
    row.className = 'note-task';
    if (task.check) row.classList.add('is-done');

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'note-task__checkbox';
    checkbox.checked = Boolean(task.check);

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
          body: JSON.stringify({ user_id: userId, check: nextValue }),
        });
        if (!res.ok) throw new Error('Failed');
      } catch (error) {
        checkbox.checked = !nextValue;
        row.classList.toggle('is-done', checkbox.checked);
      }
    });

    row.append(checkbox, textWrap, date);
    return row;
  };

  const buildTeamTask = (task) => {
    const row = document.createElement('div');
    row.className = 'note-task';
    if (task.check) row.classList.add('is-done');

    const badge = document.createElement('span');
    badge.className = 'note-task__badge';
    badge.textContent = task.user_name || `User ${task.user_id}`;

    const textWrap = document.createElement('div');
    const text = document.createElement('div');
    text.className = 'note-task__text';
    text.textContent = task.description || '';
    const meta = document.createElement('div');
    meta.className = 'note-task__meta';
    meta.textContent = task.team ? `${task.team} team` : 'Team';
    textWrap.append(text, meta);

    const date = document.createElement('span');
    date.className = 'note-task__date';
    date.textContent = formatDate(task.due_date);

    row.append(badge, textWrap, date);
    return row;
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

  const renderList = (container, items, emptyEl, builder) => {
    container.innerHTML = '';
    if (!items.length) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;
    items.forEach((item) => container.appendChild(builder(item)));
  };

  const loadMyTasks = async () => {
    if (!userId) {
      renderList(myList, [], myEmpty, buildMyTask);
      myEmpty.textContent = 'Log in to see your saved tasks.';
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/to_do?user_id=${encodeURIComponent(userId)}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      renderList(myList, Array.isArray(data) ? data : [], myEmpty, buildMyTask);
    } catch (error) {
      renderList(myList, [], myEmpty, buildMyTask);
      myEmpty.textContent = 'Could not load tasks right now.';
    }
  };

  const loadTeamTasks = async () => {
    if (!userId) return;
    try {
      const res = await fetch(`${API_BASE}/to_do/team?leader_id=${encodeURIComponent(userId)}`, {
        credentials: 'include',
      });
      if (res.status === 403) return;
      if (!res.ok) throw new Error('Failed');
      const data = await res.json();
      if (Array.isArray(data)) {
        teamTab.hidden = false;
        const byUser = new Map();
        data.forEach((task) => {
          if (!byUser.has(task.user_id)) {
            byUser.set(task.user_id, {
              user_id: task.user_id,
              user_name: task.user_name || `User ${task.user_id}`,
              team: task.team || 'Team',
              tasks: [],
            });
          }
          if (task.to_do_id) {
            byUser.get(task.user_id).tasks.push(task);
          }
        });
        const users = Array.from(byUser.values());
        renderTeamNotes(users);
        const activate = (user) => {
          teamTitle.textContent = `${user.user_name}'s tasks`;
          renderList(teamList, user.tasks, teamEmpty, buildTeamTask);
          Array.from(teamNotes.children).forEach((note) => {
            note.classList.toggle('is-active', Number(note.dataset.userId) === user.user_id);
          });
        };
        if (users.length) {
          teamTitle.textContent = 'Pick a teammate';
          renderList(teamList, [], teamEmpty, buildTeamTask);
        } else {
          teamTitle.textContent = 'No team tasks yet';
          renderList(teamList, [], teamEmpty, buildTeamTask);
        }
        teamNotes.addEventListener('click', (event) => {
          const button = event.target.closest('.team-note');
          if (!button) return;
          const selected = users.find((u) => u.user_id === Number(button.dataset.userId));
          if (selected) activate(selected);
        });
      }
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

  loadMyTasks();
  loadTeamTasks();
})();
