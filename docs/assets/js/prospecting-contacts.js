/* =====================================================================
   Prospecting — contactos: panel del contacto y formulario «Completá el
   contacto». Lo usan prospecting.html y prospecting-company.html.

   Las propiedades salen de GET /prospecting/options → objects.contact
   (backend/prospecting/contact_fields.py): las ~90, en secciones. «Contacto» y
   «Calificación» arrancan abiertas; el resto, cerradas con «n de m completas».

   Al pasar una empresa a Qualified / SQL sin un contacto completo, quien hizo
   el cambio llama a completeFlow(): se elige un contacto existente o se crea
   uno, con los obligatorios marcados (REQUIRED_ON_QUALIFIED del backend).

   Depende de window.Prospecting (prospecting.js o prospecting-core.js).
   ===================================================================== */
(function () {
  "use strict";

  var TZ = "America/Argentina/Buenos_Aires";
  function P() { return window.Prospecting; }
  function esc(v) { return P().esc(v); }
  function schema() { return (P().options().objects || {}).contact || { fields: [], groups: [], required_on_qualified: [] }; }
  function fieldsOf(group) { return schema().fields.filter(function (f) { return f.group === group; }); }
  function required() { return schema().required_on_qualified || []; }

  var OPEN_GROUPS = ["Contacto", "Calificación"];

  /* datetime ISO (con zona) <-> valor de <input type="datetime-local"> en hora Argentina. */
  function toLocalInput(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return "";
    var parts = {};
    new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(d).forEach(function (p) { parts[p.type] = p.value; });
    return parts.year + "-" + parts.month + "-" + parts.day + "T" + parts.hour + ":" + parts.minute;
  }
  function fmtLocal(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    return d.toLocaleString("es-AR", { timeZone: TZ, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) + " (AR)";
  }

  function choices(f) {
    if (f.type === "owner") return (P().options().bdrs || []).map(function (b) { return { value: b.email, label: b.name || b.email }; });
    if (f.type === "user") return (P().options().users || []).map(function (u) { return { value: u.email, label: u.name || u.email }; });
    return (f.options || []).map(function (o) { return { value: o, label: o }; });
  }
  function optionTags(items, selected) {
    return items.map(function (o) {
      return '<option value="' + esc(o.value) + '"' + (String(o.value) === String(selected == null ? "" : selected) ? " selected" : "") + ">" + esc(o.label) + "</option>";
    }).join("");
  }
  function isEmpty(v) { return v == null || v === "" || (Array.isArray(v) && !v.length); }

  /* ---------- Un campo del formulario ---------- */
  function control(f, v) {
    var k = f.key, attr = ' data-k="' + k + '" data-type="' + f.type + '"';
    switch (f.type) {
      case "longtext":
        return '<textarea class="pr-filter__input pc-area" rows="3"' + attr + ">" + esc(v || "") + "</textarea>";
      case "number":
        return '<input type="number" class="pr-filter__input"' + attr + ' value="' + esc(v == null ? "" : v) + '">';
      case "date":
        return '<input type="date" class="pr-filter__input"' + attr + ' value="' + esc((v || "").slice(0, 10)) + '">';
      case "datetime":
        return '<input type="datetime-local" class="pr-filter__input"' + attr + ' value="' + esc(toLocalInput(v)) + '">';
      case "enum": case "owner": case "user":
        return '<select class="pr-filter__input"' + attr + '><option value="">—</option>' + optionTags(choices(f), v) + "</select>";
      case "bool":
        return '<select class="pr-filter__input"' + attr + ">" +
          optionTags([{ value: "", label: "—" }, { value: "true", label: "Sí" }, { value: "false", label: "No" }],
            v === true ? "true" : v === false ? "false" : "") + "</select>";
      case "multi":
        var sel = Array.isArray(v) ? v : [];
        return '<div class="pr-wf-chips"' + attr + ">" + choices(f).map(function (c) {
          var on = sel.indexOf(c.value) !== -1;
          return '<button type="button" class="pr-wf-chip' + (on ? " is-on" : "") + '" data-chip="' + esc(c.value) + '">' +
            (on ? '<i class="fa-solid fa-check"></i> ' : "") + esc(c.label) + "</button>";
        }).join("") + "</div>";
      default:
        var t = f.type === "email" ? "email" : f.type === "phone" ? "tel" : f.type === "url" ? "url" : "text";
        return '<input type="' + t + '" class="pr-filter__input"' + attr + ' value="' + esc(v || "") + '">';
    }
  }

  function readValue(el) {
    var t = el.getAttribute("data-type");
    if (t === "multi") {
      return Array.prototype.map.call(el.querySelectorAll(".pr-wf-chip.is-on"), function (b) { return b.getAttribute("data-chip"); });
    }
    var v = el.value;
    if (t === "bool") return v === "" ? null : v === "true";
    if (t === "number") return v === "" ? null : Number(v);
    return v === "" ? null : v;
  }

  function sameValue(a, b, type) {
    if (isEmpty(a) && isEmpty(b)) return true;
    if (type === "multi") return JSON.stringify((a || []).slice().sort()) === JSON.stringify((b || []).slice().sort());
    if (type === "datetime") return toLocalInput(a) === (b || "");
    if (type === "date") return String(a || "").slice(0, 10) === String(b || "");
    return String(a) === String(b);
  }

  /* =================================================================
     Panel del contacto
     ================================================================= */
  var panel = null;

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement("div");
    panel.className = "pr-drawer pc-drawer";
    panel.setAttribute("aria-hidden", "true");
    panel.innerHTML = '<div class="pr-drawer__backdrop" data-pc-close></div>' +
      '<aside class="pr-drawer__panel pc-panel" role="dialog" aria-modal="true">' +
        '<header class="pr-drawer__head"><span class="pr-drawer__eyebrow" id="pcEyebrow">Contacto</span>' +
          '<h2 class="pr-drawer__title" id="pcTitle">—</h2><p class="pr-drawer__sub" id="pcSub"></p>' +
          '<button type="button" class="pr-drawer__close" data-pc-close aria-label="Cerrar">&times;</button></header>' +
        '<div class="pr-drawer__body" id="pcBody"></div>' +
        '<footer class="pr-drawer__foot"><span class="pr-drawer__status" id="pcStatus"></span>' +
          '<button type="button" class="pr-btn pr-btn--danger" id="pcDelete" hidden><i class="fa-regular fa-trash-can"></i></button>' +
          '<button type="button" class="pr-btn pr-btn--primary" id="pcSave"><i class="fa-regular fa-floppy-disk"></i> Guardar</button></footer>' +
      "</aside>";
    document.body.appendChild(panel);
    panel.addEventListener("click", function (e) {
      if (e.target.closest("[data-pc-close]")) return close();
      var chip = e.target.closest(".pr-wf-chip");
      if (chip && chip.closest("[data-k]")) {
        chip.classList.toggle("is-on");
        var on = chip.classList.contains("is-on");
        chip.innerHTML = (on ? '<i class="fa-solid fa-check"></i> ' : "") + esc(chip.getAttribute("data-chip"));
        updateCounts();
      }
    });
    panel.addEventListener("input", updateCounts);
    panel.addEventListener("change", updateCounts);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel.classList.contains("is-open")) close(); });
    return panel;
  }

  function close() {
    if (!panel) return;
    panel.classList.remove("is-open");
    panel.setAttribute("aria-hidden", "true");
  }

  /* n de m completas en cada sección cerrada, y marca de obligatorios vacíos. */
  function updateCounts() {
    if (!panel) return;
    panel.querySelectorAll(".pc-group").forEach(function (g) {
      var els = g.querySelectorAll("[data-k]");
      var filled = Array.prototype.filter.call(els, function (el) { return !isEmpty(readValue(el)); }).length;
      var c = g.querySelector(".pc-group__count");
      if (c) c.textContent = filled + " de " + els.length;
    });
    panel.querySelectorAll(".pc-field.is-required").forEach(function (row) {
      var el = row.querySelector("[data-k]");
      row.classList.toggle("is-missing", isEmpty(readValue(el)));
    });
  }

  /* opts: {contactId?, companyId, companyName?, requireQualified?, onSaved?} */
  function open(opts) {
    ensurePanel();
    panel.classList.add("is-open");
    panel.setAttribute("aria-hidden", "false");
    document.getElementById("pcStatus").textContent = "";
    document.getElementById("pcBody").innerHTML = '<p class="pr-note">Cargando…</p>';
    var load = opts.contactId ? P().api("/prospecting/contacts/" + opts.contactId) : Promise.resolve(null);
    load.then(function (c) { render(c, opts); }).catch(function (err) {
      document.getElementById("pcBody").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>";
    });
  }

  function render(c, opts) {
    var isNew = !c;
    c = c || {};
    var req = opts.requireQualified ? required() : [];
    document.getElementById("pcEyebrow").textContent = isNew ? "Nuevo contacto" : "Contacto";
    document.getElementById("pcTitle").textContent = isNew ? "Agregar contacto" : c.name;
    document.getElementById("pcSub").textContent = (c.company_name || opts.companyName || "") +
      (c.is_primary ? " · contacto principal" : "");
    var body = "";
    if (opts.requireQualified) {
      body += '<div class="pc-banner"><i class="fa-solid fa-circle-exclamation"></i><div><strong>La empresa pasó a Qualified / SQL.</strong> ' +
        "Completá los campos con <span class=\"pc-req\">*</span> para que deje de figurar como «Contacto incompleto».</div></div>";
    }
    (schema().groups || []).forEach(function (g) {
      var fs = fieldsOf(g);
      if (!fs.length) return;
      var hasReq = fs.some(function (f) { return req.indexOf(f.key) !== -1; });
      var openIt = OPEN_GROUPS.indexOf(g) !== -1 || hasReq;
      body += '<details class="pc-group"' + (openIt ? " open" : "") + "><summary><span>" + esc(g) + '</span><span class="pc-group__count"></span></summary>' +
        '<div class="pc-grid">' + fs.map(function (f) {
          var isReq = req.indexOf(f.key) !== -1;
          var wide = f.type === "longtext" || f.type === "multi";
          return '<label class="pc-field' + (isReq ? " is-required" : "") + (wide ? " pc-field--wide" : "") + '"' +
            (f.description ? ' title="' + esc(f.description) + '"' : "") + ">" +
            '<span class="pr-filter__label">' + esc(f.label) + (isReq ? ' <span class="pc-req">*</span>' : "") + "</span>" +
            control(f, c[f.key]) + "</label>";
        }).join("") + "</div></details>";
    });
    if (!isNew) {
      body += '<label class="pr-check pc-primary"><input type="checkbox" id="pcPrimary"' + (c.is_primary ? " checked" : "") + "> Contacto principal de la empresa</label>";
      if ((c.enrollments || []).length) {
        body += '<section class="pr-section"><h3 class="pr-section__title">Workflows</h3><ul class="pr-events">' +
          c.enrollments.map(function (e) {
            return '<li><span class="pr-events__src pr-events__src--wf">' + esc(e.workflow_name) + "</span> · " + esc(e.status) +
              (e.last_step ? '<div class="pr-note">' + esc(e.last_step) + "</div>" : "") + "</li>";
          }).join("") + "</ul></section>";
      }
      body += '<details class="pc-group"><summary><span>Historial</span><span class="pc-group__count">' + (c.events || []).length + "</span></summary>" +
        historyHtml(c.events || []) + "</details>";
    }
    document.getElementById("pcBody").innerHTML = body;
    updateCounts();
    var del = document.getElementById("pcDelete");
    del.hidden = isNew;
    del.onclick = function () {
      if (!confirm("¿Borrar el contacto «" + c.name + "»?")) return;
      P().api("/prospecting/contacts/" + c.id, { method: "DELETE" }).then(function () {
        P().toast("Contacto borrado.");
        close();
        if (opts.onSaved) opts.onSaved(null);
      }).catch(function (err) { alert(err.message); });
    };
    document.getElementById("pcSave").onclick = function () { save(c, isNew, opts); };
  }

  function label(key) {
    var f = schema().fields.filter(function (x) { return x.key === key; })[0];
    return f ? f.label : key;
  }

  function fmtEv(key, v) {
    if (v == null || v === "") return "—";
    var f = schema().fields.filter(function (x) { return x.key === key; })[0];
    if (!f) return v;
    if (f.type === "datetime") return fmtLocal(v);
    if (f.type === "bool") return v === "true" ? "Sí" : v === "false" ? "No" : v;
    if (f.type === "owner" || f.type === "user") return P().ownerName(v) || v;
    return v;
  }

  function historyHtml(events) {
    if (!events.length) return '<p class="pr-note">Sin cambios todavía.</p>';
    return '<ul class="pr-events">' + events.map(function (ev) {
      var who = String(ev.source || "").indexOf("workflow:") === 0 ? "Workflow " + ev.source.slice(9)
        : ev.source === "seed" ? "Datos de prueba" : (P().ownerName(ev.actor) || ev.actor || ev.source);
      var what = ev.field === "__note__" ? "Nota: " + esc(ev.new_value)
        : ev.field ? esc(label(ev.field)) + ": " + esc(fmtEv(ev.field, ev.old_value)) + " → " + esc(fmtEv(ev.field, ev.new_value))
        : esc(ev.new_value === "contact_created" ? "creó el contacto" : ev.new_value || "");
      return '<li><span class="pr-events__when">' + P().fmtDateTime(ev.at) + '</span><span class="pr-events__src">' + esc(who) + "</span> · " + what + "</li>";
    }).join("") + "</ul>";
  }

  function save(c, isNew, opts) {
    var status = document.getElementById("pcStatus");
    var patch = {};
    panel.querySelectorAll("#pcBody [data-k]").forEach(function (el) {
      var k = el.getAttribute("data-k"), t = el.getAttribute("data-type");
      var v = readValue(el);
      if (isNew ? !isEmpty(v) : !sameValue(c[k], v, t)) patch[k] = v;
    });
    var prim = document.getElementById("pcPrimary");
    if (prim && prim.checked !== !!c.is_primary) patch.is_primary = prim.checked;
    if (!Object.keys(patch).length) { status.textContent = "Sin cambios."; return; }
    status.textContent = "Guardando…";
    var req = isNew
      ? P().api("/prospecting/companies/" + opts.companyId + "/contacts", { method: "POST", body: JSON.stringify(patch) })
      : P().api("/prospecting/contacts/" + c.id, { method: "PATCH", body: JSON.stringify(patch) });
    req.then(function (saved) {
      var applied = (saved.workflows_applied || []).map(function (a) { return "<strong>" + esc(a.name) + "</strong>"; });
      var msg = '<i class="fa-regular fa-user"></i> ' + (isNew ? "Contacto creado." : "Contacto guardado.");
      if (opts.requireQualified && !saved.company_contact_incomplete) msg += " La empresa ya tiene su contacto completo.";
      if (applied.length) msg += " Workflow: " + applied.join(", ") + ".";
      P().toast(msg);
      if (opts.requireQualified && saved.missing_required && saved.missing_required.length) {
        status.textContent = "Guardado. Faltan: " + saved.missing_required.map(label).join(", ");
        render(saved, Object.assign({}, opts, { contactId: saved.id }));
        if (opts.onSaved) opts.onSaved(saved);
        return;
      }
      close();
      if (opts.onSaved) opts.onSaved(saved);
    }).catch(function (err) { status.textContent = "Error: " + err.message; });
  }

  /* =================================================================
     «Completá el contacto» (al pasar a Qualified / SQL)
     ================================================================= */
  function completeFlow(company, contacts, onDone) {
    var box = document.createElement("div");
    box.className = "pr-modal";
    var rows = (contacts || []).map(function (c) {
      var miss = c.missing_required || [];
      return '<button type="button" class="pc-pick" data-pick="' + c.id + '"><strong>' + esc(c.name) + "</strong>" +
        '<span class="pr-note">' + esc(c.email || "sin email") + "</span>" +
        (miss.length ? '<span class="pc-miss">Faltan ' + miss.length + "</span>" : '<span class="pc-ok">Completo</span>') + "</button>";
    }).join("");
    box.innerHTML = '<div class="pr-modal__card" role="dialog" aria-modal="true">' +
      "<h3>Completá el contacto</h3>" +
      "<p><strong>" + esc(company.name) + "</strong> pasó a <strong>" + esc(company.prospecting_status) + "</strong>. " +
      "Necesita un contacto con " + required().map(label).join(", ") + ".</p>" +
      (rows ? '<div class="pc-picklist">' + rows + "</div>" : "") +
      '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-x="later">Más tarde</button>' +
      '<button type="button" class="pr-btn pr-btn--primary" data-x="new"><i class="fa-solid fa-plus"></i> Nuevo contacto</button></div></div>';
    document.body.appendChild(box);
    box.addEventListener("click", function (e) {
      var pick = e.target.closest("[data-pick]");
      var x = e.target.closest("[data-x]");
      if (!pick && !x && e.target !== box) return;
      box.remove();
      if (x && x.getAttribute("data-x") === "later") {
        P().toast('<i class="fa-solid fa-circle-exclamation"></i> <strong>' + esc(company.name) + "</strong> queda marcada «Contacto incompleto».");
        if (onDone) onDone(null);
        return;
      }
      if (!pick && !x) { if (onDone) onDone(null); return; }
      open({
        contactId: pick ? Number(pick.getAttribute("data-pick")) : null,
        companyId: company.id, companyName: company.name, requireQualified: true, onSaved: onDone,
      });
    });
  }

  window.ProspectingContacts = { open: open, completeFlow: completeFlow, close: close, fmtLocal: fmtLocal };
})();
