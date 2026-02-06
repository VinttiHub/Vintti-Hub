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
    tasks.forEach((task) => list.appendChild(buildItem(task)));
  };

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
      const item = buildItem(newTask);
      list.prepend(item);
      clearEmptyState();
      descriptionInput.value = '';
      dateInput.value = '';
      showToast('Task added!');
    } catch (error) {
      formError.textContent = 'Could not add task. Try again.';
      formError.hidden = false;
    }
  });
})();
