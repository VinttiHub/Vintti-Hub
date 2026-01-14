(function initRichComments(global) {
  if (global.RichComments) return;

  const HIGHLIGHT_SWATCHES = [
    { name: 'Yellow', color: '#fef08a' },
    { name: 'Green', color: '#d9f99d' },
    { name: 'Blue', color: '#bfdbfe' },
    { name: 'Red', color: '#fecaca' },
  ];

  let emojiLoaderPromise = null;
  async function ensureEmojiPickerLoaded() {
    if (typeof customElements !== 'undefined' && customElements.get('emoji-picker')) return;
    if (!emojiLoaderPromise) {
      emojiLoaderPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.type = 'module';
        script.src = 'https://unpkg.com/emoji-picker-element@^1/dist/index.js';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }
    await emojiLoaderPromise;
  }

  function runCommand(editor, command, value = null) {
    editor.focus();
    const result = document.execCommand(command, false, value);
    if (!result && command === 'backColor') {
      document.execCommand('hiliteColor', false, value);
    }
  }

  function normalizeInitialValue(val) {
    if (val === undefined || val === null) return '';
    const trimmed = typeof val === 'string' ? val.trim() : String(val);
    if (trimmed === '—') return '';
    return val;
  }

  function enhance(target, options = {}) {
    const ta = typeof target === 'string' ? document.getElementById(target) : target;
    if (!ta) return null;
    if (ta.dataset.richified === '1' && ta._richCommentHandle) return ta._richCommentHandle;

    const placeholder = options.placeholder || ta.getAttribute('placeholder') || '';
    const wrap = document.createElement('div');
    wrap.className = 'rich-comment';

    const toolbar = document.createElement('div');
    toolbar.className = 'rich-comment-toolbar';
    toolbar.innerHTML = `
      <button type="button" data-command="bold" aria-label="Bold (⌘/Ctrl+B)"><b>B</b></button>
      <button type="button" data-command="italic" aria-label="Italic (⌘/Ctrl+I)"><i>I</i></button>
      <button type="button" data-command="insertUnorderedList" aria-label="Bullet list">• List</button>
      <button type="button" data-command="removeFormat" aria-label="Clear formatting">⤫</button>
    `;

    const highlightGroup = document.createElement('div');
    highlightGroup.className = 'rich-highlight-group';
    HIGHLIGHT_SWATCHES.forEach(({ name, color }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.dataset.highlight = color;
      btn.title = `Highlight ${name}`;
      btn.style.setProperty('--highlight-color', color);
      highlightGroup.appendChild(btn);
    });
    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.dataset.highlight = 'clear';
    clearBtn.textContent = 'Clear';
    clearBtn.title = 'Remove highlight';
    highlightGroup.appendChild(clearBtn);
    toolbar.appendChild(highlightGroup);

    const emojiAnchor = document.createElement('div');
    emojiAnchor.className = 'rich-emoji-anchor';
    const emojiButton = document.createElement('button');
    emojiButton.type = 'button';
    emojiButton.dataset.emojiToggle = '1';
    emojiButton.textContent = '😊';
    emojiButton.title = 'Insert emoji';
    const emojiPicker = document.createElement('emoji-picker');
    emojiPicker.className = 'rich-comment-emoji-picker';
    emojiAnchor.appendChild(emojiButton);
    emojiAnchor.appendChild(emojiPicker);
    toolbar.appendChild(emojiAnchor);

    const editor = document.createElement('div');
    editor.className = 'rich-comment-editor';
    editor.contentEditable = 'true';
    editor.dataset.placeholder = placeholder;
    editor.innerHTML = normalizeInitialValue(options.initialHTML ?? ta.value ?? '');

    ta.style.display = 'none';
    ta.dataset.richified = '1';
    ta.parentNode.insertBefore(wrap, ta);
    wrap.appendChild(toolbar);
    wrap.appendChild(editor);

    function syncValue(trigger = 'change') {
      const html = editor.innerHTML;
      ta.value = html;
      if (trigger === 'input' && typeof options.onChange === 'function') options.onChange(html);
      if (trigger === 'blur' && typeof options.onBlur === 'function') options.onBlur(html);
    }

    toolbar.addEventListener('click', async (event) => {
      const btn = event.target.closest('button');
      if (!btn) return;
      const command = btn.dataset.command;
      if (command) {
        event.preventDefault();
        runCommand(editor, command);
        return;
      }
      const highlight = btn.dataset.highlight;
      if (highlight) {
        event.preventDefault();
        if (highlight === 'clear') {
          runCommand(editor, 'removeFormat');
        } else {
          runCommand(editor, 'backColor', highlight);
        }
        return;
      }
      if (btn.dataset.emojiToggle) {
        event.preventDefault();
        try {
          await ensureEmojiPickerLoaded();
          document.querySelectorAll('.rich-comment-emoji-picker').forEach((picker) => {
            if (picker !== emojiPicker) picker.style.display = 'none';
          });
          emojiPicker.style.display = emojiPicker.style.display === 'block' ? 'none' : 'block';
        } catch (err) {
          console.warn('Emoji picker failed to load', err);
        }
      }
    });

    emojiPicker.addEventListener('emoji-click', (event) => {
      editor.focus();
      document.execCommand('insertText', false, event.detail.unicode);
      emojiPicker.style.display = 'none';
    });

    editor.addEventListener('input', () => syncValue('input'));
    editor.addEventListener('blur', () => syncValue('blur'));

    const handle = {
      root: wrap,
      editor,
      toolbar,
      setHTML(html) {
        editor.innerHTML = html || '';
        syncValue('input');
      },
      getHTML() {
        return editor.innerHTML;
      },
      focus() {
        editor.focus();
      },
    };

    ta._richCommentHandle = handle;
    return handle;
  }

  document.addEventListener('click', (event) => {
    if (event.target.closest('.rich-emoji-anchor')) return;
    document.querySelectorAll('.rich-comment-emoji-picker').forEach((picker) => {
      picker.style.display = 'none';
    });
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      document.querySelectorAll('.rich-comment-emoji-picker').forEach((picker) => {
        picker.style.display = 'none';
      });
    }
  });

  global.RichComments = { enhance };
})(window);
