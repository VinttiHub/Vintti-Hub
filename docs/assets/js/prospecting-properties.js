/* =====================================================================
   Prospecting · Configuración → Propiedades (2026-11-25)
   ---------------------------------------------------------------------
   Crear, editar, ocultar, ordenar y borrar propiedades de empresas,
   contactos y negocios. Lo usan los de PROPERTY_EDITORS (Bahía, Justo,
   Ana, Manuela, Priscilla, Lara); el server frena igual.
   Backend: backend/prospecting/properties.py + /prospecting/properties*.
   - Las de fábrica (las del código) no se borran: se ocultan. A las que usa
     el sistema («Sistema») no se les cambia el tipo ni se ocultan.
   - Obligatoria = frena al crear y no se puede vaciar a mano; Clay, HubSpot,
     Calendly y los workflows no se frenan.
   - Pasar a desplegable: «Traer valores cargados» propone la lista con los
     valores que ya hay; renombrar / unificar una opción actualiza los registros.
   ===================================================================== */
(function () {
  "use strict";

  function P() { return window.Prospecting; }
  function esc(v) { return P().esc(v); }

  var OBJ_LABELS = { company: "Empresas", contact: "Contactos", deal: "Negocios" };
  var CAT = null;          // respuesta de GET /prospecting/properties
  var obj = "company";
  var q = "";
  var box = null;

  function norm(s) { return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function typeLabel(t) {
    var hit = ((CAT && CAT.types) || []).filter(function (x) { return x.value === t; })[0];
    return hit ? hit.label : ({ owner: "BDR (owner)" }[t] || t);
  }
  function fields() { return ((CAT && CAT.objects[obj]) || { fields: [] }).fields; }
  function groups() { return ((CAT && CAT.objects[obj]) || { groups: [] }).groups || []; }

  function afterSave(res, msg) {
    if (res && res.catalog) CAT = res.catalog;
    renderList();
    if (msg) P().toast(msg);
    if (P().refreshOptions) P().refreshOptions();
  }

  /* ---------------- Pantalla principal ---------------- */
  function open() {
    close();
    box = document.createElement("div");
    box.className = "pr-modal pp-props";
    box.innerHTML = '<div class="pr-modal__card pp-props__card" role="dialog" aria-modal="true" aria-label="Propiedades">' +
      '<header class="pp-props__head"><div><h3>Propiedades</h3>' +
      '<p class="pr-note">Lo que ven las fichas, la tabla, los filtros y los workflows. Las de fábrica no se borran: se ocultan.</p></div>' +
      '<button type="button" class="pr-drawer__close" data-pp="close" aria-label="Cerrar">&times;</button></header>' +
      '<div class="pr-tabs pp-props__tabs" role="tablist">' + Object.keys(OBJ_LABELS).map(function (k) {
        return '<button type="button" class="pr-tab" data-pp-obj="' + k + '">' + OBJ_LABELS[k] + "</button>";
      }).join("") + "</div>" +
      '<div class="pp-props__tools"><input type="search" class="pr-filter__input" id="ppQ" placeholder="Buscar propiedad…" autocomplete="off">' +
      '<button type="button" class="pr-btn pr-btn--primary" data-pp="new"><i class="fa-solid fa-plus"></i> Nueva propiedad</button></div>' +
      '<div class="pp-props__list" id="ppList"><p class="pr-note">Cargando…</p></div></div>';
    document.body.appendChild(box);
    box.addEventListener("click", onClick);
    box.querySelector("#ppQ").addEventListener("input", function (e) { q = e.target.value; renderList(); });
    document.addEventListener("keydown", onKey);
    P().api("/prospecting/properties").then(function (c) { CAT = c; renderList(); })
      .catch(function (err) { box.querySelector("#ppList").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>"; });
  }
  function close() {
    if (!box) return;
    box.remove();
    box = null;
    document.removeEventListener("keydown", onKey);
  }
  function onKey(e) { if (e.key === "Escape" && !document.querySelector(".pp-edit")) close(); }

  function renderList() {
    if (!box) return;
    box.querySelectorAll("[data-pp-obj]").forEach(function (b) { b.classList.toggle("is-active", b.getAttribute("data-pp-obj") === obj); });
    var words = norm(q).split(/\s+/).filter(Boolean);
    var fs = fields().filter(function (f) {
      var hay = norm([f.label, f.key, f.group, f.description].join(" "));
      return words.every(function (w) { return hay.indexOf(w) !== -1; });
    });
    var canDrag = !words.length;
    var html = '<table class="pr-table pp-props__table"><thead><tr><th></th><th>Propiedad</th><th>Tipo</th>' +
      (obj === "company" ? "" : "<th>Grupo</th>") + "<th></th><th></th></tr></thead><tbody>" +
      (fs.length ? fs.map(function (f) {
        var tags = [];
        if (f.required) tags.push('<span class="pp-tag pp-tag--req">Obligatoria</span>');
        if (f.hidden) tags.push('<span class="pp-tag pp-tag--off">Oculta</span>');
        if (f.custom) tags.push('<span class="pp-tag pp-tag--new">Nueva</span>');
        else if (f.locked) tags.push('<span class="pp-tag" title="La usa el sistema: no se oculta ni cambia de tipo">Sistema</span>');
        else tags.push('<span class="pp-tag">De fábrica</span>');
        return '<tr data-key="' + esc(f.key) + '"' + (canDrag ? ' draggable="true"' : "") + (f.hidden ? ' class="is-off"' : "") + ">" +
          '<td class="pp-drag">' + (canDrag ? '<i class="fa-solid fa-grip-vertical" title="Arrastrar para ordenar"></i>' : "") + "</td>" +
          '<td><button type="button" class="pp-name" data-pp-edit="' + esc(f.key) + '">' + esc(f.label) + "</button>" +
            '<div class="pp-key">' + esc(f.key) + (f.description ? " · " + esc(f.description) : "") + "</div></td>" +
          "<td>" + esc(typeLabel(f.type)) + ((f.type === "enum" || f.type === "multi") && f.options ? ' <span class="pp-key">(' + f.options.length + ")</span>" : "") + "</td>" +
          (obj === "company" ? "" : "<td>" + esc(f.group || "") + "</td>") +
          '<td class="pp-tags">' + tags.join("") + "</td>" +
          '<td class="pp-actions"><button type="button" class="pr-btn" data-pp-edit="' + esc(f.key) + '" title="Editar"><i class="fa-solid fa-pen"></i></button></td></tr>';
      }).join("") : '<tr><td colspan="6" class="pr-empty">Ninguna propiedad coincide.</td></tr>') +
      "</tbody></table>";
    box.querySelector("#ppList").innerHTML = html;
    if (canDrag) bindDrag();
  }

  function onClick(e) {
    if (e.target === box) return close();
    var t = e.target.closest("[data-pp-obj]");
    if (t) { obj = t.getAttribute("data-pp-obj"); renderList(); return; }
    var b = e.target.closest("[data-pp]");
    if (b) {
      var what = b.getAttribute("data-pp");
      if (what === "close") return close();
      if (what === "new") return edit(null);
    }
    var ed = e.target.closest("[data-pp-edit]");
    if (ed) edit(ed.getAttribute("data-pp-edit"));
  }

  /* Arrastrar filas = orden de la ficha (y del menú de columnas). */
  function bindDrag() {
    var tbody = box.querySelector(".pp-props__table tbody");
    var dragging = null;
    tbody.addEventListener("dragstart", function (e) {
      dragging = e.target.closest("tr[data-key]");
      if (!dragging) return;
      dragging.classList.add("is-dragging");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", dragging.getAttribute("data-key")); } catch (x) {}
    });
    tbody.addEventListener("dragover", function (e) {
      if (!dragging) return;
      e.preventDefault();
      var over = e.target.closest("tr[data-key]");
      if (!over || over === dragging) return;
      var r = over.getBoundingClientRect();
      tbody.insertBefore(dragging, e.clientY > r.top + r.height / 2 ? over.nextSibling : over);
    });
    tbody.addEventListener("dragend", function () {
      if (!dragging) return;
      dragging.classList.remove("is-dragging");
      dragging = null;
      var keys = Array.prototype.map.call(tbody.querySelectorAll("tr[data-key]"), function (tr) { return tr.getAttribute("data-key"); });
      P().api("/prospecting/properties/" + obj + "/order", { method: "PUT", body: JSON.stringify({ keys: keys }) })
        .then(function (res) { afterSave(res, "Orden guardado."); })
        .catch(function (err) { P().toast("Error: " + esc(err.message)); renderList(); });
    });
  }

  /* ---------------- Crear / editar ---------------- */
  var TEXTUAL = ["text", "longtext", "enum", "url", "email", "phone"];
  function allowedTypes(f) {
    var all = ((CAT && CAT.types) || []).map(function (t) { return t.value; });
    if (!f) return all;
    if (f.locked) return [f.type];
    if (f.factory) {
      var base = f.factory_type;
      if (TEXTUAL.indexOf(base) === -1) return [base];
      var ok = [base, "text", "longtext", "enum"];
      if (obj !== "company") ok.push("multi");
      return all.filter(function (t) { return ok.indexOf(t) !== -1; });
    }
    return all;
  }

  function edit(key) {
    var f = key ? fields().filter(function (x) { return x.key === key; })[0] : null;
    var isNew = !f;
    var types = allowedTypes(f);
    var curType = f ? f.type : "enum";
    // Opciones en edición: {text, orig, count}. `orig` = valor guardado (para renombrar los registros).
    var opts = (f && f.options ? f.options : []).map(function (o) { return { text: o, orig: o, count: null }; });
    var counts = {};   // valor cargado -> cantidad de registros
    var usages = [];
    var ed = document.createElement("div");
    ed.className = "pr-modal pp-edit";
    var grp = groups();
    ed.innerHTML = '<div class="pr-modal__card pr-bulkedit pp-edit__card" role="dialog" aria-modal="true">' +
      "<h3>" + (isNew ? "Nueva propiedad · " + OBJ_LABELS[obj] : esc(f.label)) + "</h3>" +
      (f ? '<p class="pr-note">Clave interna: <code>' + esc(f.key) + "</code>" +
        (f.locked ? " · la usa el sistema: no se oculta ni cambia de tipo" : "") + "</p>" : "") +
      '<label class="pr-filter"><span class="pr-filter__label">Nombre *</span><input type="text" class="pr-filter__input" id="ppLabel" value="' + esc(f ? f.label : "") + '" autocomplete="off"></label>' +
      '<label class="pr-filter"><span class="pr-filter__label">Descripción</span><input type="text" class="pr-filter__input" id="ppDesc" value="' + esc(f && f.description || "") + '" autocomplete="off" placeholder="Opcional: se ve al pasar el mouse"></label>' +
      '<label class="pr-filter"><span class="pr-filter__label">Tipo</span><select class="pr-filter__input" id="ppType"' + (types.length < 2 ? " disabled" : "") + ">" +
        types.map(function (t) { return '<option value="' + t + '"' + (t === curType ? " selected" : "") + ">" + esc(typeLabel(t)) + "</option>"; }).join("") +
        "</select></label>" +
      (obj !== "company" ? '<label class="pr-filter"><span class="pr-filter__label">Grupo (sección de la ficha)</span>' +
        '<input type="text" class="pr-filter__input" id="ppGroup" list="ppGroups" value="' + esc(f ? f.group || "" : (grp[0] || "")) + '" autocomplete="off">' +
        '<datalist id="ppGroups">' + grp.map(function (g) { return '<option value="' + esc(g) + '">'; }).join("") + "</datalist></label>" : "") +
      '<div class="pp-opts" id="ppOpts"></div>' +
      '<label class="pr-check"><input type="checkbox" id="ppReq"' + (f && f.required ? " checked" : "") + "> Obligatoria " +
        '<span class="pr-note">— frena al crear a mano y no se puede vaciar (Clay, HubSpot y workflows no se frenan)</span></label>' +
      (f && !f.custom ? '<label class="pr-check"><input type="checkbox" id="ppHidden"' + (f.hidden ? " checked" : "") + (f.locked ? " disabled" : "") +
        "> Ocultar <span class=\"pr-note\">— no se ve en fichas ni columnas; los workflows que ya la usan siguen andando</span></label>" : "") +
      (obj === "deal" ? '<label class="pr-filter"><span class="pr-filter__label">Nombre interno en HubSpot (opcional)</span>' +
        '<input type="text" class="pr-filter__input" id="ppHs" value="' + esc(f && f.hubspot_name || "") + '" placeholder="ej. lead_source_deal" autocomplete="off"></label>' : "") +
      '<div class="pr-bulkedit__err" id="ppErr" hidden></div>' +
      '<div class="pr-modal__foot">' +
        (f && f.custom ? '<button type="button" class="pr-btn pr-btn--danger pp-edit__del" data-ed="delete"><i class="fa-solid fa-trash"></i> Borrar</button>' : "") +
        '<button type="button" class="pr-btn" data-ed="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-ed="save">' + (isNew ? "Crear" : "Guardar") + "</button></div></div>";
    document.body.appendChild(ed);
    var $e = function (id) { return ed.querySelector("#" + id); };
    var err = function (html) { $e("ppErr").innerHTML = html || ""; $e("ppErr").hidden = !html; };
    var running = false;
    var closeEd = function () { if (!running) { ed.remove(); document.removeEventListener("keydown", onEdKey); } };
    var onEdKey = function (e) { if (e.key === "Escape") closeEd(); };
    document.addEventListener("keydown", onEdKey);
    setTimeout(function () { $e("ppLabel").focus(); }, 0);

    var optsLocked = f && f.options_locked;
    function isList() { return ["enum", "multi"].indexOf($e("ppType").value) !== -1; }
    function renderOpts() {
      var el = $e("ppOpts");
      if (!isList()) { el.innerHTML = ""; return; }
      if (optsLocked) {
        el.innerHTML = '<span class="pr-filter__label">Opciones</span><p class="pr-note">Las usa el sistema (se comparan por texto): no se editan acá.</p>' +
          '<div class="pp-opts__ro">' + opts.map(function (o) { return '<span class="pp-tag">' + esc(o.text) + "</span>"; }).join("") + "</div>";
        return;
      }
      var inList = {};
      opts.forEach(function (o) { inList[norm(o.text)] = true; });
      var loose = Object.keys(counts).filter(function (v) { return !inList[norm(v)] && !opts.some(function (o) { return o.orig === v; }); });
      el.innerHTML = '<div class="pp-opts__head"><span class="pr-filter__label">Opciones</span>' +
        (f ? '<button type="button" class="pr-wf-link" data-ed="load"><i class="fa-solid fa-database"></i> Traer valores cargados</button>' : "") + "</div>" +
        '<p class="pr-note">Cambiar el texto de una opción renombra ese valor en todos los registros. Poner el mismo texto que otra las unifica. Quitar una opción no borra los valores ya cargados.</p>' +
        '<ol class="pp-opts__list">' + opts.map(function (o, i) {
          var c = o.orig != null && counts[o.orig] != null ? counts[o.orig] : null;
          var ren = o.orig != null && o.text.trim() && o.text.trim() !== o.orig;
          return '<li data-i="' + i + '"><input type="text" class="pr-filter__input" data-opt="' + i + '" value="' + esc(o.text) + '" placeholder="Opción">' +
            (c != null ? '<span class="pp-count" title="Registros con este valor">' + c + "</span>" : "") +
            (ren ? '<span class="pp-ren" title="Se renombra en los registros">de «' + esc(o.orig) + "»</span>" : "") +
            '<button type="button" class="pr-btn pp-mini" data-up="' + i + '" title="Subir"' + (i ? "" : " disabled") + '><i class="fa-solid fa-arrow-up"></i></button>' +
            '<button type="button" class="pr-btn pp-mini" data-rm="' + i + '" title="Quitar"><i class="fa-solid fa-xmark"></i></button></li>';
        }).join("") + "</ol>" +
        '<button type="button" class="pr-btn pp-mini" data-ed="add"><i class="fa-solid fa-plus"></i> Agregar opción</button>' +
        (loose.length ? '<div class="pp-loose"><span class="pr-filter__label">Valores cargados que no están en la lista</span>' +
          loose.map(function (v) {
            return '<button type="button" class="pp-tag pp-tag--btn" data-addval="' + esc(v) + '" title="Agregar a la lista">' + esc(v) + " · " + counts[v] + ' <i class="fa-solid fa-plus"></i></button>';
          }).join("") + '<p class="pr-note">Quedan guardados y se ven igual; sólo no se pueden elegir. Para unificarlos, agregalos y cambiales el texto.</p></div>' : "");
    }
    function loadValues(auto) {
      if (!f) return Promise.resolve();
      return P().api("/prospecting/properties/" + obj + "/" + f.key + "/values").then(function (res) {
        counts = {};
        (res.values || []).forEach(function (v) { counts[v.value] = v.count; });
        usages = res.usages || [];
        if (auto && !opts.length) {
          // Primera vez como desplegable: la lista = los valores cargados (una por variante de mayúsculas).
          var seen = {};
          (res.values || []).forEach(function (v) {
            var k = norm(v.value);
            if (seen[k]) { opts.push({ text: seen[k], orig: v.value, count: v.count }); return; }
            seen[k] = v.value;
            opts.push({ text: v.value, orig: v.value, count: v.count });
          });
        }
        renderOpts();
      }).catch(function (e2) { err(esc(e2.message)); });
    }
    renderOpts();
    if (f && isList()) loadValues(false);

    ed.addEventListener("input", function (e) {
      var i = e.target.getAttribute && e.target.getAttribute("data-opt");
      if (i != null) opts[Number(i)].text = e.target.value;
    });
    ed.addEventListener("change", function (e) {
      if (e.target.id === "ppType") {
        if (isList() && f && !(f.options || []).length) loadValues(true);
        else renderOpts();
      }
      if (e.target.getAttribute && e.target.getAttribute("data-opt") != null) renderOpts();
    });
    ed.addEventListener("click", function (e) {
      if (e.target === ed) return closeEd();
      var up = e.target.closest("[data-up]");
      if (up) { var i = Number(up.getAttribute("data-up")); var x = opts.splice(i, 1)[0]; opts.splice(i - 1, 0, x); renderOpts(); return; }
      var rm = e.target.closest("[data-rm]");
      if (rm) { opts.splice(Number(rm.getAttribute("data-rm")), 1); renderOpts(); return; }
      var av = e.target.closest("[data-addval]");
      if (av) { var v = av.getAttribute("data-addval"); opts.push({ text: v, orig: v }); renderOpts(); return; }
      var b = e.target.closest("[data-ed]");
      if (!b || running) return;
      var what = b.getAttribute("data-ed");
      if (what === "cancel") return closeEd();
      if (what === "add") {
        opts.push({ text: "", orig: null });
        renderOpts();
        var inputs = ed.querySelectorAll("[data-opt]");
        if (inputs.length) inputs[inputs.length - 1].focus();
        return;
      }
      if (what === "load") return loadValues(true);
      if (what === "delete") return doDelete();
      if (what === "save") return doSave(b);
    });

    function payload() {
      var body = { label: $e("ppLabel").value.trim(), description: $e("ppDesc").value.trim(), type: $e("ppType").value,
        required: $e("ppReq").checked };
      if ($e("ppGroup")) body.group = $e("ppGroup").value.trim();
      if ($e("ppHidden")) body.hidden = $e("ppHidden").checked;
      if ($e("ppHs")) body.hubspot_name = $e("ppHs").value.trim();
      if (isList() && !optsLocked) {
        // Únicas sin importar mayúsculas (la primera gana); las repetidas se unifican en esa.
        var list = [], first = {}, renames = {};
        opts.forEach(function (o) {
          var t = (o.text || "").trim();
          if (!t) return;
          var k = norm(t);
          if (!first[k]) { first[k] = t; list.push(t); }
          if (o.orig != null && o.orig !== first[k]) renames[o.orig] = first[k];
        });
        body.options = list;
        if (Object.keys(renames).length) body.renames = renames;
      }
      return body;
    }
    function doSave(b) {
      var body = payload();
      if (!body.label) return err("Ponele un nombre.");
      if (isList() && !optsLocked && !(body.options || []).length) return err("Un desplegable necesita al menos una opción.");
      if (body.renames) {
        var n = Object.keys(body.renames).reduce(function (a, k) { return a + (counts[k] || 0); }, 0);
        var lines = Object.keys(body.renames).map(function (k) { return "«" + k + "» → «" + body.renames[k] + "»"; });
        if (!confirm("Se van a actualizar " + (n || "los") + " registros:\n" + lines.join("\n") + "\n\n¿Seguimos?")) return;
      }
      running = true;
      b.disabled = true;
      err("");
      var req = isNew
        ? P().api("/prospecting/properties", { method: "POST", body: JSON.stringify(Object.assign({ object: obj }, body)) })
        : P().api("/prospecting/properties/" + obj + "/" + f.key, { method: "PATCH", body: JSON.stringify(body) });
      req.then(function (res) {
        running = false;
        var msg = isNew ? "Propiedad <strong>" + esc(body.label) + "</strong> creada." : "Propiedad guardada.";
        if (res.renamed) msg += " " + res.renamed + " registros actualizados.";
        if ((res.usages || []).length && (body.options || body.renames)) {
          msg += " Revisá los filtros de: " + res.usages.map(function (u) { return "<strong>" + esc(u.name) + "</strong>"; }).join(", ") + ".";
        }
        closeEd();
        afterSave(res, msg);
      }).catch(function (e2) {
        running = false;
        b.disabled = false;
        err(esc(e2.message));
      });
    }
    function doDelete() {
      if (!confirm("¿Borrar la propiedad «" + f.label + "»? Deja de verse en fichas, tabla y filtros.")) return;
      var purge = confirm("¿Borrar también los valores que ya tienen cargados los registros?\n\nAceptar = sí, borrarlos · Cancelar = dejarlos guardados (no se ven)");
      running = true;
      P().api("/prospecting/properties/" + obj + "/" + f.key + (purge ? "?purge=1" : ""), { method: "DELETE" }).then(function (res) {
        running = false;
        closeEd();
        afterSave(res, "Propiedad <strong>" + esc(f.label) + "</strong> borrada.");
      }).catch(function (e2) {
        running = false;
        var us = (e2.data && e2.data.usages) || [];
        if (us.length) {
          err("No se puede borrar: la usan " + us.map(function (u) {
            return (u.kind === "workflow" ? "el workflow" : "la vista") + " <strong>" + esc(u.name) + "</strong>";
          }).join(", ") + ". Sacala de ahí primero, o ocultala desde Editar.");
        } else {
          err(esc(e2.message));
        }
      });
    }
  }

  window.ProspectingProperties = { open: open };
})();
