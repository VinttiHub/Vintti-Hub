/* =====================================================================
   Hirex ATS — Ask: natural-language chat over jobs, candidates and CVs.

   Talks to POST /hirex/chat, which runs a read-only tool-calling agent
   over the hirex_* tables and answers in Markdown.

   Threads live in localStorage: no new tables, works the moment you open
   it. The trade-off is that history is per-browser.
   ===================================================================== */
(function () {
  "use strict";

  const API_BASE = window.HIREX_API_BASE ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1")
      ? "http://localhost:5000"
      : "https://7m6mw95m8y.us-east-2.awsapprunner.com");

  function currentUserEmail() {
    return (localStorage.getItem("user_email") || sessionStorage.getItem("user_email") || "").toLowerCase().trim();
  }

  const STORE_KEY = "hirex_ask_threads";
  const MAX_THREADS = 30;     // oldest threads fall off the rail
  const MAX_MESSAGES = 40;    // per thread, kept in storage
  const HISTORY_TURNS = 10;   // turns replayed to the backend

  let threads = [];
  let activeId = null;
  let busy = false;

  const $ = (id) => document.getElementById(id);
  let els = {};

  document.addEventListener("DOMContentLoaded", init);

  function init() {
    els = {
      view: $("hxAskView"), hero: $("hxHero"), log: $("hxLog"),
      suggest: $("hxSuggest"), form: $("hxForm"), input: $("hxInput"), send: $("hxSend"),
      threads: $("hxThreads"), railEmpty: $("hxRailEmpty"),
      newChat: $("hxNewChat"), railNew: $("hxRailNew"), toasts: $("hxToasts"),
    };

    threads = loadThreads();
    activeId = threads.length ? threads[0].id : null;

    els.form.addEventListener("submit", onSubmit);
    els.input.addEventListener("keydown", onKey);
    els.input.addEventListener("input", autoGrow);
    els.newChat.addEventListener("click", newChat);
    els.railNew.addEventListener("click", newChat);

    // A candidate link inside an answer is a normal <a>; nothing to intercept.
    renderRail();
    renderThread();
    loadSuggestions();
    els.input.focus();
  }

  /* ---------------------------------------------------------------- state */
  function loadThreads() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
      return Array.isArray(raw) ? raw.filter((t) => t && t.id && Array.isArray(t.messages)) : [];
    } catch (e) {
      return [];
    }
  }

  function saveThreads() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(threads.slice(0, MAX_THREADS)));
    } catch (e) {
      // Quota exceeded: drop the oldest half rather than losing the current chat.
      threads = threads.slice(0, Math.max(1, Math.floor(threads.length / 2)));
      try { localStorage.setItem(STORE_KEY, JSON.stringify(threads)); } catch (e2) {}
    }
  }

  function activeThread() {
    return threads.find((t) => t.id === activeId) || null;
  }

  function newChat() {
    activeId = null;
    renderRail();
    renderThread();
    els.input.value = "";
    autoGrow();
    els.input.focus();
  }

  function ensureThread(firstMessage) {
    let t = activeThread();
    if (t) return t;
    t = {
      id: String(Date.now()) + "-" + Math.random().toString(36).slice(2, 7),
      title: firstMessage.slice(0, 60),
      created: Date.now(),
      messages: [],
    };
    threads.unshift(t);
    activeId = t.id;
    return t;
  }

  function deleteThread(id, ev) {
    ev.stopPropagation();
    threads = threads.filter((t) => t.id !== id);
    if (activeId === id) activeId = threads.length ? threads[0].id : null;
    saveThreads();
    renderRail();
    renderThread();
  }

  /* --------------------------------------------------------------- render */
  function renderRail() {
    els.threads.innerHTML = "";
    els.railEmpty.hidden = threads.length > 0;
    threads.forEach((t) => {
      const li = document.createElement("li");
      li.className = "hx-ask-thread" + (t.id === activeId ? " is-active" : "");
      li.innerHTML =
        `<button class="hx-ask-thread-open" type="button">${esc(t.title || "Untitled")}</button>` +
        `<button class="hx-ask-thread-del" type="button" title="Delete" aria-label="Delete conversation">` +
        `<i class="fa-solid fa-xmark"></i></button>`;
      li.querySelector(".hx-ask-thread-open").addEventListener("click", () => {
        activeId = t.id;
        renderRail();
        renderThread();
      });
      li.querySelector(".hx-ask-thread-del").addEventListener("click", (e) => deleteThread(t.id, e));
      els.threads.appendChild(li);
    });
  }

  function renderThread() {
    const t = activeThread();
    els.log.innerHTML = "";
    const hasMessages = !!(t && t.messages.length);
    els.hero.hidden = hasMessages;
    els.log.hidden = !hasMessages;
    if (!hasMessages) return;
    t.messages.forEach((m) => els.log.appendChild(bubble(m)));
    scrollToEnd();
  }

  function bubble(m) {
    const wrap = document.createElement("div");
    wrap.className = `hx-ask-msg is-${m.role === "user" ? "user" : "ai"}`;
    if (m.role === "user") {
      wrap.innerHTML = `<div class="hx-ask-bubble">${esc(m.content)}</div>`;
      return wrap;
    }
    const steps = (m.steps || []).length
      ? `<div class="hx-ask-steps">${m.steps.map((s) => `<span class="hx-ask-step">${esc(s.label || s.tool)}</span>`).join("")}</div>`
      : "";
    wrap.innerHTML =
      `<div class="hx-ask-who"><span class="hx-ask-dot"></span>Hirex AI</div>` +
      steps +
      `<div class="hx-ask-body${m.error ? " is-error" : ""}">${m.error ? esc(m.content) : md(m.content)}</div>`;
    return wrap;
  }

  function pendingBubble() {
    const el = document.createElement("div");
    el.className = "hx-ask-msg is-ai";
    el.innerHTML =
      `<div class="hx-ask-who"><span class="hx-ask-dot"></span>Hirex AI</div>` +
      `<div class="hx-ask-thinking"><span></span><span></span><span></span> Reading your pipeline…</div>`;
    return el;
  }

  function scrollToEnd() {
    els.log.scrollTop = els.log.scrollHeight;
  }

  /* ----------------------------------------------------------- suggestions */
  async function loadSuggestions() {
    let job = null;
    try {
      const res = await fetch(`${API_BASE}/hirex/jobs?status=open`, {
        headers: { "X-User-Email": currentUserEmail() },
      });
      if (res.ok) {
        const jobs = await res.json();
        if (Array.isArray(jobs) && jobs.length) job = jobs[0];
      }
    } catch (e) { /* suggestions are a nicety; a failure must not block the page */ }

    // Built from a real opening when there is one, so the examples are clickable truth.
    const title = job ? job.title : "your open roles";
    const items = [
      { text: `Show me every candidate who applied to ${title}`, icon: "fa-table-list" },
      { text: "Find candidates with retail industry experience", icon: "fa-magnifying-glass" },
      { text: "Which pipelines have been stalled for more than 7 days?", icon: "fa-hourglass-half" },
    ];
    els.suggest.innerHTML = "";
    items.forEach((it) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "hx-ask-card";
      b.innerHTML = `<i class="fa-solid ${it.icon}"></i><span>${esc(it.text)}</span>`;
      b.addEventListener("click", () => {
        els.input.value = it.text;
        autoGrow();
        els.form.requestSubmit();
      });
      els.suggest.appendChild(b);
    });
  }

  /* ------------------------------------------------------------- send flow */
  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      els.form.requestSubmit();
    }
  }

  function autoGrow() {
    els.input.style.height = "auto";
    els.input.style.height = Math.min(els.input.scrollHeight, 200) + "px";
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (busy) return;
    const text = els.input.value.trim();
    if (!text) return;

    const t = ensureThread(text);
    t.messages.push({ role: "user", content: text });
    saveThreads();
    renderRail();

    els.hero.hidden = true;
    els.log.hidden = false;
    els.log.appendChild(bubble({ role: "user", content: text }));
    els.input.value = "";
    autoGrow();

    const pending = pendingBubble();
    els.log.appendChild(pending);
    scrollToEnd();
    setBusy(true);

    // Only the prior turns — the message we just pushed is sent separately.
    const history = t.messages
      .slice(0, -1)
      .slice(-HISTORY_TURNS * 2)
      .map((m) => ({ role: m.role, content: m.content }));

    let msg;
    try {
      const res = await fetch(`${API_BASE}/hirex/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Email": currentUserEmail() },
        body: JSON.stringify({ message: text, history: history, actor_email: currentUserEmail() }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        msg = { role: "assistant", content: data.error || `Request failed (${res.status})`, error: true };
        toast("err", "Hirex AI could not answer");
      } else {
        msg = { role: "assistant", content: data.reply || "", steps: data.steps || [] };
      }
    } catch (err) {
      msg = { role: "assistant", content: "Could not reach the server. Check your connection and try again.", error: true };
      toast("err", "Connection failed");
    }

    pending.remove();
    t.messages.push(msg);
    if (t.messages.length > MAX_MESSAGES) t.messages = t.messages.slice(-MAX_MESSAGES);
    saveThreads();
    els.log.appendChild(bubble(msg));
    scrollToEnd();
    setBusy(false);
    els.input.focus();
  }

  function setBusy(v) {
    busy = v;
    els.send.disabled = v;
    els.input.disabled = v;
    els.view.classList.toggle("is-busy", v);
  }

  /* ------------------------------------------------------------- Markdown */
  /* A small renderer for exactly what the model is prompted to emit: tables,
     headings, lists, bold/italic, inline code and links. There is no Markdown
     library anywhere in docs/, and model output is untrusted — so everything is
     HTML-escaped FIRST and links are whitelisted before any tag is produced. */

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // Only same-app Hirex pages and plain https links may become anchors.
  function safeHref(url) {
    const u = String(url || "").trim();
    if (/^hirex[a-z0-9._-]*\.html(\?[A-Za-z0-9_=&%.:+-]*)?$/i.test(u)) return u;
    if (/^https:\/\/[^\s"'<>]+$/i.test(u)) return u;
    return null;
  }

  function inline(text) {
    let s = esc(text);
    s = s.replace(/`([^`]+)`/g, (m, code) => `<code>${code}</code>`);
    // Links: the label/url were escaped above, so unescape the url for the check.
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, label, url) => {
      const raw = url.replace(/&amp;/g, "&").replace(/&#39;/g, "'").replace(/&quot;/g, '"');
      const href = safeHref(raw);
      if (!href) return label;
      const ext = /^https:/i.test(href) ? ' target="_blank" rel="noopener noreferrer"' : "";
      return `<a href="${esc(href)}"${ext}>${label}</a>`;
    });
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return s;
  }

  function isTableSep(line) {
    return /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(line) && line.indexOf("-") !== -1 && line.indexOf("|") !== -1;
  }

  function cells(line) {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map((c) => c.trim());
  }

  function md(src) {
    const lines = String(src == null ? "" : src).replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      if (!line.trim()) { i++; continue; }

      // Table: a header row followed by a |---|---| separator.
      if (line.indexOf("|") !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const head = cells(line);
        i += 2;
        const body = [];
        while (i < lines.length && lines[i].indexOf("|") !== -1 && lines[i].trim()) {
          body.push(cells(lines[i]));
          i++;
        }
        out.push(
          '<div class="hx-ask-tablewrap"><table class="hx-ask-table"><thead><tr>' +
          head.map((c) => `<th>${inline(c)}</th>`).join("") +
          "</tr></thead><tbody>" +
          body.map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") +
          "</tbody></table></div>"
        );
        continue;
      }

      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) {
        const lvl = Math.min(h[1].length + 2, 6);
        out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`);
        i++;
        continue;
      }

      if (/^\s*([-*+])\s+/.test(line)) {
        const items = [];
        while (i < lines.length && /^\s*([-*+])\s+/.test(lines[i])) {
          items.push(`<li>${inline(lines[i].replace(/^\s*([-*+])\s+/, ""))}</li>`);
          i++;
        }
        out.push(`<ul>${items.join("")}</ul>`);
        continue;
      }

      if (/^\s*\d+[.)]\s+/.test(line)) {
        const items = [];
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          items.push(`<li>${inline(lines[i].replace(/^\s*\d+[.)]\s+/, ""))}</li>`);
          i++;
        }
        out.push(`<ol>${items.join("")}</ol>`);
        continue;
      }

      // Paragraph: consume until a blank line or the start of another block.
      const para = [];
      while (i < lines.length && lines[i].trim() &&
             !/^\s*([-*+]|\d+[.)])\s+/.test(lines[i]) && !/^#{1,4}\s/.test(lines[i]) &&
             !(lines[i].indexOf("|") !== -1 && i + 1 < lines.length && isTableSep(lines[i + 1]))) {
        para.push(lines[i]);
        i++;
      }
      if (para.length) out.push(`<p>${inline(para.join(" "))}</p>`);
    }
    return out.join("");
  }

  /* ----------------------------------------------------------------- misc */
  function toast(kind, msg) {
    const el = document.createElement("div");
    el.className = `hx-toast hx-toast-${kind === "ok" ? "ok" : "err"}`;
    el.innerHTML = `<i class="fa-solid ${kind === "ok" ? "fa-circle-check" : "fa-circle-exclamation"}"></i><span>${esc(msg)}</span>`;
    els.toasts.appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity .25s, transform .25s";
      el.style.opacity = "0";
      el.style.transform = "translateY(6px)";
      setTimeout(() => el.remove(), 260);
    }, 2600);
  }
})();
