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
      // Negocios del contacto (prospecting-deals.js): abren su panel encima de éste.
      var dl = e.target.closest("[data-pc-deal]");
      if (dl && window.ProspectingDeals) return window.ProspectingDeals.open({ dealId: Number(dl.getAttribute("data-pc-deal")) });
      if (e.target.closest("[data-pc-adddeal]") && window.ProspectingDeals && pcCurrent) {
        return window.ProspectingDeals.open({ contactId: pcCurrent.id, contactName: pcCurrent.name,
          companyId: pcCurrent.company_id || null, companyName: pcCurrent.company_name || "" });
      }
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

  /* opts: {contactId?, companyId?, companyName?, requireQualified?, onSaved?}
     Sin companyId (y sin contactId) = contacto nuevo desde cero, con o sin empresa
     (POST /prospecting/contacts). Desde el 2026-11-04 un contacto puede no tener empresa. */
  var pcCompany = { id: null, name: "" };   // empresa elegida en la ficha
  var pcCompanyOrig = null;                  // la que tenía al abrir
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

  var pcCurrent = null;  // el contacto abierto (para «Agregar negocio»)
  function render(c, opts) {
    var isNew = !c;
    c = c || {};
    pcCurrent = isNew ? null : c;
    var req = opts.requireQualified ? required() : [];
    document.getElementById("pcEyebrow").textContent = isNew ? "Nuevo contacto" : "Contacto";
    document.getElementById("pcTitle").textContent = isNew ? "Agregar contacto" : c.name;
    pcCompany = isNew ? { id: opts.companyId || null, name: opts.companyName || "" }
      : { id: c.company_id || null, name: c.company_name || "" };
    pcCompanyOrig = pcCompany.id;
    document.getElementById("pcSub").textContent = (pcCompany.id ? pcCompany.name : "Sin empresa") +
      (c.is_primary && pcCompany.id ? " · contacto principal" : "");
    var body = companyBox();
    if (opts.requireQualified) {
      body += '<div class="pc-banner"><i class="fa-solid fa-circle-exclamation"></i><div><strong>La empresa pasó a Qualified / SQL.</strong> ' +
        "Completá los campos con <span class=\"pc-req\">*</span> para que deje de figurar como «Contacto incompleto».</div></div>";
    }
    // Buscador de propiedades (2026-11-06): filtra entre todas las secciones.
    body += '<div class="pc-propsearch"><i class="fa-solid fa-magnifying-glass"></i>' +
      '<input type="search" class="pr-filter__input" id="pcPropQ" placeholder="Buscar propiedad…" autocomplete="off">' +
      '<button type="button" class="pc-propsearch__clear" id="pcPropClear" hidden aria-label="Limpiar">&times;</button></div>' +
      '<p class="pr-note" id="pcPropNone" hidden>Ninguna propiedad coincide.</p>';
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
            ' data-search="' + esc(propNorm([f.label, f.key, f.description, g].join(" "))) + '"' +
            (f.description ? ' title="' + esc(f.description) + '"' : "") + ">" +
            '<span class="pr-filter__label">' + esc(f.label) + (isReq ? ' <span class="pc-req">*</span>' : "") +
              (!isNew && window.ProspectingHistory ? window.ProspectingHistory.button("contact", c.id, f.key) : "") + "</span>" +
            control(f, c[f.key]) + "</label>";
        }).join("") + "</div></details>";
    });
    if (!isNew) {
      if (c.company_id) {
        body += '<label class="pr-check pc-primary" data-pc-extra><input type="checkbox" id="pcPrimary"' + (c.is_primary ? " checked" : "") + "> Contacto principal de la empresa</label>";
      }
      if ((c.enrollments || []).length) {
        body += '<section class="pr-section" data-pc-extra><h3 class="pr-section__title">Workflows</h3><ul class="pr-events">' +
          c.enrollments.map(function (e) {
            return '<li><span class="pr-events__src pr-events__src--wf">' + esc(e.workflow_name) + "</span> · " + esc(e.status) +
              (e.last_step ? '<div class="pr-note">' + esc(e.last_step) + "</div>" : "") + "</li>";
          }).join("") + "</ul></section>";
      }
      if (window.ProspectingDeals && (P().me() || {}).can_see_deals) {  // los BDRs no (2026-11-09)
        body += '<section class="pr-section" data-pc-extra><h3 class="pr-section__title">Negocios (' + (c.deals || []).length + ")" +
          ' <button type="button" class="pr-btn pd-mini" data-pc-adddeal><i class="fa-solid fa-plus"></i> Agregar</button></h3>' +
          ((c.deals || []).length ? '<ul class="pr-events">' + c.deals.map(function (d) {
            return '<li><button type="button" class="pc-deal" data-pc-deal="' + d.id + '"><strong>' + esc(d.name) + "</strong> · " +
              esc(d.stage_label || d.stage_key) + (d.opportunity_id ? " · Opp #" + d.opportunity_id : "") + "</button></li>";
          }).join("") + "</ul>" : '<p class="pr-note">Sin negocios.</p>') + "</section>";
      }
      body += '<details class="pc-group" data-pc-extra><summary><span>Historial</span><span class="pc-group__count">' + (c.events || []).length + "</span></summary>" +
        historyHtml(c.events || []) + "</details>";
    }
    document.getElementById("pcBody").innerHTML = body;
    bindCompanyBox();
    bindPropSearch();
    updateCounts();
    var del = document.getElementById("pcDelete");
    // Eliminar: todos menos los BDRs (can_delete de /prospecting/me, 2026-11-09); el server frena igual.
    del.hidden = isNew || !((P().me() || {}).can_delete);
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

  /* Buscador de propiedades: sin acentos, por palabras (todas tienen que estar). */
  function propNorm(s) {
    return String(s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  }
  function filterProps(text) {
    var words = propNorm(text).split(/\s+/).filter(Boolean);
    var on = words.length > 0, any = false;
    panel.querySelectorAll(".pc-group:not([data-pc-extra])").forEach(function (g) {
      var hits = 0;
      g.querySelectorAll(".pc-field").forEach(function (f) {
        var hay = f.getAttribute("data-search") || "";
        var ok = !on || words.every(function (w) { return hay.indexOf(w) !== -1; });
        f.hidden = !ok;
        if (ok) hits++;
      });
      if (on) {
        if (!g.hasAttribute("data-was-open")) g.setAttribute("data-was-open", g.open ? "1" : "0");
        g.hidden = !hits;
        if (hits) g.open = true;
      } else {
        g.hidden = false;
        if (g.hasAttribute("data-was-open")) { g.open = g.getAttribute("data-was-open") === "1"; g.removeAttribute("data-was-open"); }
      }
      if (hits) any = true;
    });
    panel.querySelectorAll("[data-pc-extra]").forEach(function (el) { el.hidden = on; });
    document.getElementById("pcPropNone").hidden = !on || any;
    document.getElementById("pcPropClear").hidden = !on;
  }
  function bindPropSearch() {
    var q = document.getElementById("pcPropQ");
    q.addEventListener("input", function () { filterProps(q.value); });
    q.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && q.value) { e.stopPropagation(); e.preventDefault(); q.value = ""; filterProps(""); }
      else if (e.key === "Enter") {
        e.preventDefault();
        var first = Array.prototype.find.call(panel.querySelectorAll(".pc-group:not([data-pc-extra]) .pc-field"),
          function (f) { return !f.hidden; });
        var ctl = first && first.querySelector("input, select, textarea, button");
        if (ctl) ctl.focus();
      }
    });
    document.getElementById("pcPropClear").addEventListener("click", function () { q.value = ""; filterProps(""); q.focus(); });
  }

  /* Empresa del contacto: buscar y elegir, cambiar o quitar. Se guarda con «Guardar». */
  function companyBox() {
    return '<section class="pc-company"><span class="pr-filter__label">Empresa</span>' +
      '<div class="pc-company__row"><div class="pr-inbox__pick">' +
      '<input type="text" class="pr-filter__input" id="pcCoQ" placeholder="Sin empresa — buscá una para asociarla…" autocomplete="off" value="' + esc(pcCompany.name || "") + '">' +
      '<div class="pr-inbox__results" id="pcCoResults" hidden></div></div>' +
      '<a class="pr-btn" id="pcCoOpen" target="_blank" rel="noopener"' + (pcCompany.id ? ' href="prospecting-company.html?id=' + pcCompany.id + '"' : " hidden") + '><i class="fa-solid fa-arrow-up-right-from-square"></i></a>' +
      '<button type="button" class="pr-btn" id="pcCoClear"' + (pcCompany.id ? "" : " hidden") + ">Quitar</button></div>" +
      '<p class="pr-note pc-company__hint" id="pcCoHint"></p></section>';
  }
  function setCompany(id, name) {
    pcCompany = { id: id, name: name || "" };
    document.getElementById("pcCoQ").value = pcCompany.name;
    var open = document.getElementById("pcCoOpen");
    open.hidden = !id;
    if (id) open.href = "prospecting-company.html?id=" + id;
    document.getElementById("pcCoClear").hidden = !id;
    document.getElementById("pcCoHint").textContent = id === pcCompanyOrig ? "" :
      (id ? "Se asocia a esta empresa al guardar." : "Queda sin empresa al guardar.");
  }
  function bindCompanyBox() {
    var q = document.getElementById("pcCoQ"), box = document.getElementById("pcCoResults"), t = null;
    q.addEventListener("input", function () {
      clearTimeout(t);
      var text = q.value.trim();
      if (!text) { box.hidden = true; return; }
      t = setTimeout(function () {
        P().api("/prospecting/companies?q=" + encodeURIComponent(text) + "&page_size=10").then(function (r) {
          box.innerHTML = (r.rows.length ? r.rows.map(function (co) {
            return '<button type="button" data-co="' + co.id + '" data-name="' + esc(co.name) + '"><strong>' + esc(co.name) + "</strong>" +
              (co.domain ? ' <span class="pr-note">' + esc(co.domain) + "</span>" : "") + "</button>";
          }).join("") : '<span class="pr-note">Ninguna empresa coincide.</span>') +
            // Alta manual (2026-11-06): si no está, se crea acá y queda asociada al guardar.
            '<button type="button" data-co-new="1"><i class="fa-solid fa-plus"></i> Crear empresa <strong>«' + esc(text) + "»</strong></button>";
          box.hidden = false;
        }).catch(function (err) { box.innerHTML = '<span class="pr-note">' + esc(err.message) + "</span>"; box.hidden = false; });
      }, 250);
    });
    q.addEventListener("blur", function () {
      setTimeout(function () { box.hidden = true; if (q.value.trim() !== (pcCompany.name || "")) q.value = pcCompany.name || ""; }, 200);
    });
    box.addEventListener("mousedown", function (e) {
      var nb = e.target.closest("[data-co-new]");
      if (nb) {
        e.preventDefault();
        box.hidden = true;
        var emailEl = document.querySelector('#pcBody [data-k="email"]');
        newCompanyModal({ name: q.value.trim(), website: websiteFromEmail(emailEl ? emailEl.value : "") }, function (co) {
          setCompany(co.id, co.name);
        });
        return;
      }
      var b = e.target.closest("[data-co]");
      if (!b) return;
      e.preventDefault();
      setCompany(Number(b.getAttribute("data-co")), b.getAttribute("data-name"));
      box.hidden = true;
    });
    document.getElementById("pcCoClear").addEventListener("click", function () { setCompany(null, ""); });
  }

  function label(key) {
    if (key === "company") return "Empresa";
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

  function bulkTag(src) {
    var m = /^bulk:(\d+)$/.exec(String(src || ""));
    return m ? ' <span class="pr-bulk-tag" title="Cambio hecho con Editar en masa"><i class="fa-solid fa-layer-group"></i> Edición masiva · ' + m[1] + "</span>" : "";
  }

  function historyHtml(events) {
    if (!events.length) return '<p class="pr-note">Sin cambios todavía.</p>';
    return '<ul class="pr-events">' + events.map(function (ev) {
      var sy = /^sync:(contact|deal|company):(\d+)$/.exec(String(ev.source || ""));
      var who = String(ev.source || "").indexOf("workflow:") === 0 ? "Workflow " + ev.source.slice(9)
        : sy ? "Copiado " + ({ contact: "del contacto", deal: "del negocio", company: "de la empresa" })[sy[1]] + " #" + sy[2]
        : ev.source === "seed" ? "Datos de prueba" : (P().ownerName(ev.actor) || ev.actor || ev.source);
      var what = ev.field === "__note__" ? "Nota: " + esc(ev.new_value)
        : ev.field ? esc(label(ev.field)) + ": " + esc(fmtEv(ev.field, ev.old_value)) + " → " + esc(fmtEv(ev.field, ev.new_value))
        : esc(ev.new_value === "contact_created" ? "creó el contacto" : ev.new_value || "");
      return '<li><span class="pr-events__when">' + P().fmtDateTime(ev.at) + '</span><span class="pr-events__src">' + esc(who) + "</span>" + bulkTag(ev.source) + " · " + what + "</li>";
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
    var companyChanged = !isNew && (pcCompany.id || null) !== (pcCompanyOrig || null);
    if (!Object.keys(patch).length && !companyChanged && !isNew) { status.textContent = "Sin cambios."; return; }
    if (isNew && !Object.keys(patch).length) { status.textContent = "Completá al menos un campo."; return; }
    status.textContent = "Guardando…";
    var req;
    if (isNew) {
      req = P().api("/prospecting/contacts", { method: "POST",
        body: JSON.stringify(Object.assign({}, patch, { company_id: pcCompany.id || null })) });
    } else {
      req = (Object.keys(patch).length
        ? P().api("/prospecting/contacts/" + c.id, { method: "PATCH", body: JSON.stringify(patch) })
        : Promise.resolve(null)
      ).then(function (saved) {
        if (!companyChanged) return saved;
        return P().api("/prospecting/contacts/" + c.id + "/company", { method: "PATCH",
          body: JSON.stringify({ company_id: pcCompany.id || null }) }).then(function (s2) {
          if (saved) s2.workflows_applied = (saved.workflows_applied || []).concat(s2.workflows_applied || []);
          return s2;
        });
      });
    }
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

  // fieldControl / readFieldValue: el mismo input por tipo, para la edición masiva de prospecting.js.
  /* ---------- Alta manual de una empresa (2026-11-06) ----------
     Lo usan «Nueva empresa» (sección Empresas) y «Crear empresa» del buscador del panel
     del contacto. POST /prospecting/companies: un dominio que ya existe vuelve 409 con la
     empresa, y se ofrece usarla en vez de duplicarla. onCreated(row) recibe {id, name, …}. */
  var FREE_MAIL = ["gmail.com", "googlemail.com", "hotmail.com", "outlook.com", "live.com", "yahoo.com",
                   "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com"];
  function websiteFromEmail(email) {
    var m = /@([^@\s]+)$/.exec(String(email || "").trim().toLowerCase());
    return m && FREE_MAIL.indexOf(m[1]) === -1 ? m[1] : "";
  }
  function newCompanyModal(prefill, onCreated) {
    prefill = prefill || {};
    var O = P().options() || {}, me = P().me() || {};
    var bdrs = O.bdrs || [];
    var mine = bdrs.some(function (b) { return b.email === me.email; }) ? me.email : "";
    var inp = function (id, label, val, ph) {
      return '<label class="pr-filter"><span class="pr-filter__label">' + label + '</span><input type="text" class="pr-filter__input" id="' + id +
        '" value="' + esc(val || "") + '" placeholder="' + esc(ph || "") + '" autocomplete="off"></label>';
    };
    var box = document.createElement("div");
    box.className = "pr-modal";
    box.innerHTML = '<div class="pr-modal__card pr-bulkedit" role="dialog" aria-modal="true">' +
      "<h3>Nueva empresa</h3>" +
      inp("ncName", "Nombre de la empresa *", prefill.name) +
      inp("ncWeb", "Sitio web", prefill.website, "empresa.com") +
      inp("ncLi", "Página de LinkedIn", "", "https://www.linkedin.com/company/…") +
      inp("ncInd", "Industria", "") +
      '<label class="pr-filter"><span class="pr-filter__label">Size</span><select class="pr-filter__input" id="ncSize"><option value="">—</option>' +
        (O.sizes || []).map(function (x) { return '<option value="' + esc(x) + '">' + esc(x) + "</option>"; }).join("") + "</select></label>" +
      inp("ncCountry", "País", "") + inp("ncCity", "Ciudad", "") +
      '<label class="pr-filter"><span class="pr-filter__label">Prospecting Owner</span><select class="pr-filter__input" id="ncOwner"><option value="">Sin owner</option>' +
        bdrs.map(function (b) { return '<option value="' + esc(b.email) + '"' + (b.email === mine ? " selected" : "") + ">" + esc(b.name || b.email) + "</option>"; }).join("") +
        "</select></label>" +
      '<p class="pr-note">Entra con Lead Source «Manual». Si tiene owner, los workflows le ponen status y start date como a las de Clay.</p>' +
      '<div class="pr-bulkedit__err" id="ncErr" hidden></div>' +
      '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-nc="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-nc="go"><i class="fa-solid fa-plus"></i> Crear empresa</button></div></div>';
    document.body.appendChild(box);
    var q = function (id) { return box.querySelector("#" + id); };
    var running = false;
    var close = function () { if (running) return; box.remove(); document.removeEventListener("keydown", onKey); };
    var onKey = function (e) { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    var err = function (html) { var el = q("ncErr"); el.innerHTML = html; el.hidden = !html; };
    var done = function (row) { close(); if (onCreated) onCreated(row); };
    setTimeout(function () { q(prefill.name ? "ncWeb" : "ncName").focus(); }, 0);
    box.addEventListener("click", function (e) {
      if (e.target === box) return close();
      var use = e.target.closest("[data-nc-use]");
      if (use) { done({ id: Number(use.getAttribute("data-nc-use")), name: use.getAttribute("data-name") }); return; }
      var b = e.target.closest("[data-nc]");
      if (!b || running) return;
      if (b.getAttribute("data-nc") === "cancel") return close();
      var body = { name: q("ncName").value.trim(), website: q("ncWeb").value.trim(), linkedin_url: q("ncLi").value.trim(),
        industry: q("ncInd").value.trim(), size: q("ncSize").value, country: q("ncCountry").value.trim(),
        city: q("ncCity").value.trim(), prospecting_owner_email: q("ncOwner").value };
      if (!body.name) return err("Poné el nombre de la empresa.");
      running = true;
      b.disabled = true;
      b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Creando…';
      err("");
      P().api("/prospecting/companies", { method: "POST", body: JSON.stringify(body) }).then(function (row) {
        running = false;
        var wfs = row.workflows_applied || [];
        P().toast('<i class="fa-solid fa-building"></i> Empresa <strong>' + esc(row.name) + "</strong> creada" +
          (wfs.length ? " · corrieron " + wfs.map(function (w) { return "<strong>" + esc(w) + "</strong>"; }).join(", ") : "") + ".");
        done(row);
      }).catch(function (e2) {
        running = false;
        b.disabled = false;
        b.innerHTML = '<i class="fa-solid fa-plus"></i> Crear empresa';
        var ex = e2.existing || (e2.data && e2.data.existing);
        if (ex) {
          err("Ya existe <strong>" + esc(ex.name) + "</strong> (" + esc(ex.domain || "") + "). " +
            '<button type="button" class="pr-wf-link" data-nc-use="' + ex.id + '" data-name="' + esc(ex.name) + '">Usar esta</button> · ' +
            '<a href="prospecting-company.html?id=' + ex.id + '" target="_blank" rel="noopener">Abrir</a>');
        } else {
          err(esc(e2.message));
        }
      });
    });
  }

  window.ProspectingContacts = { open: open, completeFlow: completeFlow, close: close, fmtLocal: fmtLocal,
    fieldControl: control, readFieldValue: readValue, newCompanyModal: newCompanyModal };
})();
