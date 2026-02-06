(() => {
  const chat = document.querySelector('.todo-chat');
  if (!chat) return;

  const API_BASE = 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const userId = Number(window.localStorage.getItem('user_id')) || null;

  const bubble = chat.querySelector('#todoBubble');
  const panel = chat.querySelector('#todoPanel');
  const closeBtn = chat.querySelector('#todoClose');
  const list = chat.querySelector('#todoList');
  const empty = chat.querySelector('#todoEmpty');
  const toast = chat.querySelector('#todoToast');
  const form = chat.querySelector('#todoForm');
  const descriptionInput = chat.querySelector('#todoDescription');
  const dateInput = chat.querySelector('#todoDate');
  const formError = chat.querySelector('#todoFormError');

  let hasLoaded = false;
  let toastTimer = null;
  let currentTasks = [];

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
    empty.textContent = message;
    empty.hidden = false;
  };

  const clearEmptyState = () => {
    empty.hidden = true;
  };

  const buildItem = (task) => {
    const wrapper = document.createElement('label');
    wrapper.className = 'todo-item';
    if (task.check) wrapper.classList.add('is-done');
    if (!task.check && isOverdue(task.due_date)) wrapper.classList.add('is-overdue');
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
    date.textContent = formatDate(task.due_date);

    checkbox.addEventListener('change', async () => {
      const nextValue = checkbox.checked;
      wrapper.classList.toggle('is-done', nextValue);
      if (nextValue) showToast('Good job!');

      try {
        const res = await fetch(`${API_BASE}/to_do/${task.to_do_id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ user_id: userId, check: nextValue }),
        });
        if (!res.ok) throw new Error('Failed to update task');
        if (nextValue) {
          await moveTaskToEnd(task);
          renderTasks(currentTasks);
        }
      } catch (error) {
        checkbox.checked = !nextValue;
        wrapper.classList.toggle('is-done', checkbox.checked);
        showToast('Oops, try again.');
      }
    });

    wrapper.append(checkbox, text, date);
    return wrapper;
  };

  const renderTasks = (tasks) => {
    list.innerHTML = '';
    if (!tasks.length) {
      setEmptyState('No tasks yet. Add your first one.');
      return;
    }

    clearEmptyState();
    currentTasks = tasks;

    const topTasks = sortTasks(tasks.filter((task) => !task.subtask));
    const subTasks = tasks.filter((task) => task.subtask);
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
    if (!userId) {
      renderTasks([]);
      setEmptyState('Log in to save and sync your tasks.');
      return;
    }

    list.classList.add('is-loading');
    try {
      const res = await fetch(`${API_BASE}/to_do?user_id=${encodeURIComponent(userId)}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed to load tasks');
      const data = await res.json();
      renderTasks(Array.isArray(data) ? data : []);
    } catch (error) {
      renderTasks([]);
      setEmptyState('Could not load tasks. Try again soon.');
    } finally {
      list.classList.remove('is-loading');
    }
  };

  const openPanel = () => {
    if (!panel || !bubble) return;
    panel.hidden = false;
    chat.classList.add('is-open');
    bubble.setAttribute('aria-expanded', 'true');
    if (!hasLoaded) {
      fetchTasks();
      hasLoaded = true;
    }
  };

  const closePanel = () => {
    if (!panel || !bubble) return;
    chat.classList.remove('is-open');
    bubble.setAttribute('aria-expanded', 'false');
    panel.hidden = true;
  };

  bubble.addEventListener('click', (event) => {
    event.stopPropagation();
    if (chat.classList.contains('is-open')) {
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

    if (!userId) {
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
          user_id: userId,
          description,
          due_date: dueDate,
        }),
      });

      if (!res.ok) throw new Error('Failed to add task');
      const newTask = await res.json();
      currentTasks = [newTask, ...currentTasks];
      renderTasks(currentTasks);
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
    if (!userId) return;
    await fetch(`${API_BASE}/to_do/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ user_id: userId, items: payload }),
    });
  };
})();
