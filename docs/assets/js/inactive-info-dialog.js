(() => {
  const REASONS = [
    'Poor candidate performance',
    'Candidate resigned',
    'Buy out fee',
    'Company layoffs / downsizing',
    'Accepted a better offer'
  ];

  let overlay;
  let reasonSelect;
  let commentsInput;
  let vinttiErrorInput;
  let submitBtn;
  let skipBtn;
  let closeBtn;
  let subtitleEl;
  let titleEl;
  let settleCurrent = null;

  function injectStyles() {
    if (document.getElementById('inactive-info-styles')) return;
    const style = document.createElement('style');
    style.id = 'inactive-info-styles';
    style.textContent = `
.inactive-info-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease;
  padding: 20px;
}
.inactive-info-overlay.is-visible {
  opacity: 1;
  pointer-events: auto;
}
.inactive-info-card {
  width: min(420px, 100%);
  background: #fff;
  border-radius: 20px;
  padding: 28px;
  box-shadow: 0 30px 60px rgba(15, 23, 42, 0.2);
  font-family: 'Onest', 'Inter', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  animation: inactive-info-pop 0.25s ease;
  position: relative;
}
@keyframes inactive-info-pop {
  from { transform: translateY(12px) scale(0.98); opacity: 0; }
  to { transform: translateY(0) scale(1); opacity: 1; }
}
.inactive-info-eyebrow {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #5b6bad;
  margin-bottom: 6px;
  font-weight: 600;
}
.inactive-info-card h3 {
  margin: 0 0 6px;
  font-size: 24px;
  color: #0f172a;
}
.inactive-info-subtitle {
  margin: 0 0 18px;
  color: #475569;
  line-height: 1.4;
  font-size: 15px;
}
.inactive-info-card label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 6px;
}
.inactive-info-card select,
.inactive-info-card textarea {
  width: 100%;
  border-radius: 12px;
  border: 1.5px solid #dbe3ff;
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  transition: border-color 0.2s ease;
  background: #f8faff;
  color: #0f172a;
}
.inactive-info-card select:focus,
.inactive-info-card textarea:focus {
  outline: none;
  border-color: #4f46e5;
  background: #fff;
}
.inactive-info-card textarea {
  min-height: 80px;
  resize: vertical;
}
.inactive-info-checkbox {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 16px 0 0;
  font-size: 13px;
  color: #0f172a;
}
.inactive-info-checkbox input {
  width: 18px;
  height: 18px;
}
.inactive-info-actions {
  margin-top: 22px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.inactive-info-skip,
.inactive-info-submit {
  flex: 1;
  border-radius: 999px;
  padding: 11px 18px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  border: none;
  transition: transform 0.2s ease, box-shadow 0.2s ease, opacity 0.2s ease;
}
.inactive-info-skip {
  background: transparent;
  border: 1px solid rgba(15, 23, 42, 0.2);
  color: #0f172a;
}
.inactive-info-submit {
  background: linear-gradient(120deg, #4f46e5, #6c63ff);
  color: #fff;
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.25);
}
.inactive-info-submit:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
}
.inactive-info-close {
  position: absolute;
  top: 14px;
  right: 14px;
  background: rgba(15, 23, 42, 0.08);
  border: none;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  font-size: 18px;
  cursor: pointer;
  transition: background 0.2s ease;
}
.inactive-info-close:hover {
  background: rgba(15, 23, 42, 0.15);
}
`;
    document.head.appendChild(style);
  }

  function ensureElements() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'inactive-info-overlay';
    overlay.innerHTML = `
      <div class="inactive-info-card" role="dialog" aria-modal="true">
        <button type="button" class="inactive-info-close" aria-label="Close dialog">×</button>
        <div class="inactive-info-eyebrow">Friendly reminder 💙</div>
        <h3>Complete the offboarding info</h3>
        <p class="inactive-info-subtitle">
          Help us keep our dashboards accurate by logging why this engagement ended.
        </p>
        <label for="inactive-info-reason">Reason *</label>
        <select id="inactive-info-reason" required>
          <option value="">Select a reason</option>
        </select>
        <label for="inactive-info-comments">Comments (optional)</label>
        <textarea id="inactive-info-comments" placeholder="Add extra context"></textarea>
        <label class="inactive-info-checkbox">
          <input type="checkbox" id="inactive-info-vintti-error" />
          This was a Vintti process error
        </label>
        <div class="inactive-info-actions">
          <button type="button" class="inactive-info-skip">I'll do it later</button>
          <button type="button" class="inactive-info-submit" disabled>Save reason</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    reasonSelect = overlay.querySelector('#inactive-info-reason');
    commentsInput = overlay.querySelector('#inactive-info-comments');
    vinttiErrorInput = overlay.querySelector('#inactive-info-vintti-error');
    submitBtn = overlay.querySelector('.inactive-info-submit');
    skipBtn = overlay.querySelector('.inactive-info-skip');
    closeBtn = overlay.querySelector('.inactive-info-close');
    subtitleEl = overlay.querySelector('.inactive-info-subtitle');
    titleEl = overlay.querySelector('h3');

    REASONS.forEach(reason => {
      const option = document.createElement('option');
      option.value = reason;
      option.textContent = reason;
      reasonSelect.appendChild(option);
    });

    reasonSelect.addEventListener('change', () => {
      submitBtn.disabled = !reasonSelect.value;
    });

    submitBtn.addEventListener('click', () => {
      if (!reasonSelect.value) return;
      resolveCurrent({
        reason: reasonSelect.value,
        comments: commentsInput.value.trim(),
        vinttiError: Boolean(vinttiErrorInput.checked)
      });
    });

    const cancelHandler = () => resolveCurrent(null);
    skipBtn.addEventListener('click', cancelHandler);
    closeBtn.addEventListener('click', cancelHandler);
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) cancelHandler();
    });
    overlay.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        cancelHandler();
      }
    });
  }

  function resolveCurrent(result) {
    if (!settleCurrent) return;
    overlay?.classList.remove('is-visible');
    const resolver = settleCurrent;
    settleCurrent = null;
    requestAnimationFrame(() => resolver(result));
  }

  function openInactiveInfoModal(options = {}) {
    if (typeof document === 'undefined') return Promise.resolve(null);
    injectStyles();
    ensureElements();
    const { candidateName, clientName, roleName, title, subtitle, reason, comments, vinttiError } = options;
    const shortName = candidateName || 'this hire';
    const accountSnippet = clientName ? ` for ${clientName}` : '';
    const roleSnippet = roleName ? ` as ${roleName}` : '';
    titleEl.textContent = title || 'Complete the offboarding info';
    subtitleEl.textContent =
      subtitle ||
      `Help us keep things tidy by logging why ${shortName}${roleSnippet}${accountSnippet} ended.`;
    reasonSelect.value = reason || '';
    commentsInput.value = comments || '';
    vinttiErrorInput.checked = Boolean(vinttiError);
    submitBtn.disabled = !reasonSelect.value;

    overlay.classList.add('is-visible');
    requestAnimationFrame(() => reasonSelect.focus());

    return new Promise((resolve) => {
      settleCurrent = resolve;
    });
  }

  window.openInactiveInfoModal = openInactiveInfoModal;
})();
