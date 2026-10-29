/* =====================================================================
   Prospecting — historial de UNA propiedad (el «ver historial» de HubSpot).
   Un reloj junto a la etiqueta de cada campo abre un popover con cada cambio:
   el valor nuevo, el anterior, quién (persona, Clay o workflow) y cuándo, más
   el valor con el que nació el registro.

   Uso: botón con data-hist="<company|contact>:<id>:<campo>" en cualquier parte
   de la página (el click se escucha delegado en document), o
   ProspectingHistory.open(obj, id, field, anchor).
   Lee GET /prospecting/<companies|contacts>/<id>/history?field= (store.property_history).

   Lo cargan prospecting.html y prospecting-company.html. Depende de
   window.Prospecting (prospecting.js o prospecting-core.js).
   ===================================================================== */
(function () {
  "use strict";

  function P() { return window.Prospecting; }
  function esc(v) { return P().esc(v); }

  function fieldOf(obj, key) {
    var o = ((P().options() || {}).objects || {})[obj] || {};
    return (o.fields || []).filter(function (f) { return f.key === key; })[0] || { key: key, label: key };
  }

  /* Los eventos guardan texto: un datetime en ISO, un sí/no como true/false, listas con comas. */
  function fmt(f, v) {
    if (v == null || v === "") return '<span class="pr-hist__empty">(vacío)</span>';
    if (f.type === "datetime" && window.ProspectingContacts) return esc(window.ProspectingContacts.fmtLocal(v));
    if (f.type === "date") return P().fmtDate(v);
    if (f.type === "bool") return v === "true" ? "Sí" : v === "false" ? "No" : esc(v);
    if (f.type === "owner" || f.type === "user") return esc(P().ownerName(v) || v);
    return esc(v);
  }
  /* Edición masiva (Acciones → Editar propiedad): source = "bulk:<n registros>". */
  function bulkTag(src) {
    var m = /^bulk:(\d+)$/.exec(String(src || ""));
    return m ? ' <span class="pr-bulk-tag" title="Cambio hecho con Editar en masa"><i class="fa-solid fa-layer-group"></i> Edición masiva · ' + m[1] + "</span>" : "";
  }
  function who(ev) {
    var src = String(ev.source || "");
    if (src.indexOf("bulk:") === 0) return esc(P().ownerName(ev.actor) || ev.actor || "—") + bulkTag(src);
    if (src.indexOf("workflow:") === 0) return '<i class="fa-solid fa-diagram-project"></i> Workflow #' + esc(src.slice(9));
    if (src === "clay") return "Clay";
    if (src === "zapier" || src === "calendly") return "Calendly (Zapier)";
    if (src === "seed") return "Datos de prueba";
    return esc(P().ownerName(ev.actor) || ev.actor || src || "—");
  }

  var pop = null;
  function close() {
    if (!pop) return;
    pop.remove();
    pop = null;
    document.removeEventListener("keydown", onKey);
    window.removeEventListener("scroll", close, true);
  }
  function onKey(e) { if (e.key === "Escape") close(); }

  function place(anchor) {
    var r = anchor.getBoundingClientRect();
    var w = pop.offsetWidth, h = pop.offsetHeight;
    var left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12));
    var top = r.bottom + 6;
    if (top + h > window.innerHeight - 12 && r.top - h - 6 > 12) top = r.top - h - 6;
    pop.style.left = left + "px";
    pop.style.top = Math.max(12, top) + "px";
  }

  function render(f, data) {
    var rows = data.changes.slice();
    var created = data.created || {};
    // Un contacto creado con valores registra cada campo como cambio desde vacío en el
    // mismo momento: ese cambio ES el valor al crearse, no una edición posterior.
    var last = rows[rows.length - 1];
    var bornWith = last && (last.old_value == null || last.old_value === "") && created.at &&
      Math.abs(new Date(last.at) - new Date(created.at)) < 5000;
    if (bornWith) rows.pop();
    var items = rows.map(function (ev) {
      return '<li class="pr-hist__item"><div class="pr-hist__val">' + fmt(f, ev.new_value) + "</div>" +
        '<div class="pr-hist__old">antes: ' + fmt(f, ev.old_value) + "</div>" +
        '<div class="pr-hist__meta">' + who(ev) + " · " + P().fmtDateTime(ev.at) + "</div></li>";
    });
    var born = bornWith ? last : created;
    items.push('<li class="pr-hist__item pr-hist__item--born"><div class="pr-hist__val">' +
      fmt(f, bornWith ? last.new_value : created.value) + "</div>" +
      '<div class="pr-hist__old">valor al crearse</div>' +
      '<div class="pr-hist__meta">' + (born.source || born.actor ? who(born) + " · " : "") + (born.at ? P().fmtDateTime(born.at) : "") + "</div></li>");
    return '<div class="pr-hist__head"><span>Historial de <strong>' + esc(f.label) + "</strong></span>" +
      '<button type="button" class="pr-hist__close" aria-label="Cerrar">&times;</button></div>' +
      '<p class="pr-hist__sum">' + (rows.length ? rows.length + (rows.length === 1 ? " cambio" : " cambios") : "Nunca se cambió") + "</p>" +
      '<ol class="pr-hist__list">' + items.join("") + "</ol>";
  }

  function open(obj, id, field, anchor) {
    close();
    var f = fieldOf(obj, field);
    pop = document.createElement("div");
    pop.className = "pr-hist";
    pop.setAttribute("role", "dialog");
    pop.innerHTML = '<div class="pr-hist__head"><span>Historial de <strong>' + esc(f.label) + '</strong></span></div><p class="pr-note">Cargando…</p>';
    document.body.appendChild(pop);
    place(anchor);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", close, true);
    var mine = pop;
    pop.addEventListener("click", function (e) {
      e.stopPropagation();
      if (e.target.closest(".pr-hist__close")) close();
    });
    pop.addEventListener("scroll", function (e) { e.stopPropagation(); }, true);
    P().api("/prospecting/" + (obj === "company" ? "companies" : "contacts") + "/" + id + "/history?field=" + encodeURIComponent(field))
      .then(function (data) {
        if (pop !== mine) return;
        pop.innerHTML = render(f, data);
        place(anchor);
      }).catch(function (err) {
        if (pop === mine) pop.innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>";
      });
  }

  /* El botón: va pegado a la etiqueta del campo. */
  function button(obj, id, field) {
    return '<button type="button" class="pr-hist-btn" data-hist="' + obj + ":" + id + ":" + esc(field) + '" title="Ver historial de la propiedad" aria-label="Ver historial">' +
      '<i class="fa-solid fa-clock-rotate-left"></i></button>';
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-hist]");
    if (b) {
      // Dentro de un <label>, el click también enfocaría / abriría el control.
      e.preventDefault();
      e.stopPropagation();
      var p = b.getAttribute("data-hist").split(":");
      if (pop && pop._for === b) { close(); return; }
      open(p[0], Number(p[1]), p.slice(2).join(":"), b);
      if (pop) pop._for = b;
      return;
    }
    if (pop && !e.target.closest(".pr-hist")) close();
  }, true);

  window.ProspectingHistory = { open: open, button: button, close: close };
})();
