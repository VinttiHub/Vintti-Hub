/* Buscador para los desplegables de Prospecting (2026-11-05).
 *
 * Un <select> nativo sólo salta por la primera letra; con 90 propiedades de contacto
 * tipear «meeting sch» no encuentra nada. Este módulo, sin tocar cómo se arma cada
 * select, abre en su lugar un panel con un cuadro de búsqueda:
 *   - filtra mientras se tipea, sin importar mayúsculas ni acentos, por cualquier parte
 *     del texto (cada palabra tiene que aparecer: «date sched» encuentra «Date of
 *     Meeting Scheduled»), y también por el nombre del grupo (<optgroup>);
 *   - ↑/↓ para moverse, Enter para elegir, Esc para cerrar;
 *   - al elegir pone el valor en el <select> y dispara `change` (con bubbles), así que
 *     todos los listeners de siempre (editor de workflows, filtros, celdas) funcionan igual.
 *
 * Aplica a los <select> de una sola opción con al menos MIN_OPTIONS opciones. Para
 * excluir uno: atributo `data-nosearch`.
 */
(function () {
  "use strict";

  var MIN_OPTIONS = 8;
  var pop = null;      // panel abierto
  var target = null;   // <select> al que pertenece
  var items = [];      // [{value, label, group, el}]
  var active = -1;     // índice dentro de los visibles

  function norm(s) {
    return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function eligible(sel) {
    return sel && sel.tagName === "SELECT" && !sel.multiple && !sel.disabled &&
      !sel.hasAttribute("data-nosearch") && sel.options.length >= MIN_OPTIONS;
  }

  function visible() {
    return items.filter(function (it) { return !it.el.hidden; });
  }

  function setActive(i) {
    var vis = visible();
    if (!vis.length) { active = -1; return; }
    active = Math.max(0, Math.min(i, vis.length - 1));
    items.forEach(function (it) { it.el.classList.remove("is-active"); });
    var el = vis[active].el;
    el.classList.add("is-active");
    el.scrollIntoView({ block: "nearest" });
  }

  function filter(q) {
    var words = norm(q).split(/\s+/).filter(Boolean);
    items.forEach(function (it) {
      var hay = norm(it.label + " " + it.group);
      it.el.hidden = !words.every(function (w) { return hay.indexOf(w) !== -1; });
    });
    // Los títulos de grupo se esconden si su grupo quedó vacío.
    pop.querySelectorAll(".pr-ss__group").forEach(function (g) {
      var any = false, n = g.nextElementSibling;
      while (n && !n.classList.contains("pr-ss__group")) {
        if (!n.hidden) { any = true; break; }
        n = n.nextElementSibling;
      }
      g.hidden = !any;
    });
    pop.querySelector(".pr-ss__empty").hidden = visible().length > 0;
    // Con texto, arranca en el primer resultado; sin texto, en el elegido.
    var vis = visible(), sel = -1;
    if (!words.length) vis.forEach(function (it, i) { if (it.value === target.value) sel = i; });
    setActive(sel === -1 ? 0 : sel);
  }

  function choose(it) {
    var sel = target;
    close(false);
    if (!sel || !sel.isConnected) return;
    if (sel.value !== it.value) {
      sel.value = it.value;
      sel.dispatchEvent(new Event("input", { bubbles: true }));
      sel.dispatchEvent(new Event("change", { bubbles: true }));
    }
    if (sel.isConnected) sel.focus();
  }

  function close(refocus) {
    if (!pop) return;
    var sel = target;
    pop.remove();
    pop = null; target = null; items = []; active = -1;
    document.removeEventListener("mousedown", onOutside, true);
    window.removeEventListener("resize", onViewport);
    window.removeEventListener("scroll", onViewport, true);
    if (refocus && sel && sel.isConnected) sel.focus();
  }

  function onOutside(e) {
    if (pop && !pop.contains(e.target) && e.target !== target) close(false);
  }
  function onViewport(e) {
    if (pop && e && e.target && pop.contains(e.target)) return;  // scroll de la propia lista
    close(false);
  }

  function place() {
    var r = target.getBoundingClientRect();
    var w = Math.max(r.width, 260);
    var left = Math.min(r.left, window.innerWidth - w - 8);
    pop.style.width = w + "px";
    pop.style.left = Math.max(8, left) + "px";
    var below = window.innerHeight - r.bottom - 8;
    var above = r.top - 8;
    if (below >= 220 || below >= above) {
      pop.style.top = (r.bottom + 4) + "px";
      pop.style.bottom = "";
      pop.style.maxHeight = Math.max(160, Math.min(380, below)) + "px";
    } else {
      pop.style.top = "";
      pop.style.bottom = (window.innerHeight - r.top + 4) + "px";
      pop.style.maxHeight = Math.max(160, Math.min(380, above)) + "px";
    }
  }

  function open(sel, initial) {
    close(false);
    target = sel;
    pop = document.createElement("div");
    pop.className = "pr-ss";
    pop.setAttribute("role", "dialog");
    var input = document.createElement("input");
    input.type = "text";
    input.className = "pr-ss__q";
    input.placeholder = "Buscar…";
    input.autocomplete = "off";
    input.setAttribute("aria-label", "Buscar opción");
    var list = document.createElement("div");
    list.className = "pr-ss__list";
    list.setAttribute("role", "listbox");

    Array.prototype.forEach.call(sel.children, function (node) {
      if (node.tagName === "OPTGROUP") {
        var g = document.createElement("div");
        g.className = "pr-ss__group";
        g.textContent = node.label;
        list.appendChild(g);
        Array.prototype.forEach.call(node.children, function (o) { add(o, node.label); });
      } else if (node.tagName === "OPTION") {
        add(node, "");
      }
    });
    function add(o, group) {
      if (o.disabled && !o.value) return;
      var el = document.createElement("div");
      el.className = "pr-ss__opt" + (o.value === sel.value ? " is-selected" : "");
      el.setAttribute("role", "option");
      el.textContent = o.textContent;
      var it = { value: o.value, label: o.textContent, group: group, el: el };
      el.addEventListener("mousedown", function (e) { e.preventDefault(); });
      el.addEventListener("click", function () { choose(it); });
      el.addEventListener("mousemove", function () {
        var i = visible().indexOf(it);
        if (i !== -1 && i !== active) setActive(i);
      });
      items.push(it);
      list.appendChild(el);
    }
    var empty = document.createElement("div");
    empty.className = "pr-ss__empty";
    empty.textContent = "Sin resultados";
    empty.hidden = true;

    pop.appendChild(input);
    pop.appendChild(list);
    pop.appendChild(empty);
    document.body.appendChild(pop);
    place();

    input.addEventListener("input", function () { filter(input.value); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Enter") {
        e.preventDefault();
        var vis = visible();
        if (vis[active]) choose(vis[active]);
      } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
      else if (e.key === "Tab") { close(true); }
    });
    document.addEventListener("mousedown", onOutside, true);
    window.addEventListener("resize", onViewport);
    window.addEventListener("scroll", onViewport, true);

    input.value = initial || "";
    filter(input.value);
    input.focus();
  }

  // Click: en vez de la lista nativa, el panel con buscador.
  document.addEventListener("mousedown", function (e) {
    var sel = e.target;
    if (e.button !== 0 || !eligible(sel)) return;
    e.preventDefault();
    if (pop && target === sel) { close(true); return; }
    sel.focus();
    open(sel, "");
  }, true);

  // Teclado sobre un select con foco: una letra abre el buscador con esa letra;
  // Enter / Espacio / Alt+↓ lo abren vacío. Tab y las flechas solas quedan nativas.
  document.addEventListener("keydown", function (e) {
    var sel = e.target;
    if (!eligible(sel) || e.ctrlKey || e.metaKey) return;
    if (e.key.length === 1 && e.key !== " " && !e.altKey) {
      e.preventDefault();
      open(sel, e.key);
    } else if (e.key === "Enter" || e.key === " " || (e.altKey && e.key === "ArrowDown")) {
      e.preventDefault();
      open(sel, "");
    }
  }, true);
})();
