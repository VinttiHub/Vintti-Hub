/* =====================================================================
   Prospecting — ficha completa de una empresa (prospecting-company.html?id=).
   Como el registro de HubSpot: datos a la izquierda, actividad al centro y
   Contactos (n) + Agregar y Workflows a la derecha.

   La actividad junta el historial de la empresa y el de sus contactos (todo
   va a prospect_company_events), agrupado por mes.

   Depende de prospecting-core.js (window.Prospecting) y prospecting-contacts.js.
   ===================================================================== */
(function () {
  "use strict";

  var P = null;
  var C = null;       // window.ProspectingContacts
  var company = null;
  var tab = "activity";

  function $(id) { return document.getElementById(id); }
  function esc(v) { return P.esc(v); }
  function opts() { return P.options(); }
  function companyFields() { return ((opts().objects || {}).company || {}).fields || []; }
  function contactField(key) {
    return (((opts().objects || {}).contact || {}).fields || []).filter(function (f) { return f.key === key; })[0];
  }
  function companyField(key) { return companyFields().filter(function (f) { return f.key === key; })[0]; }

  var MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

  function initials(name) {
    var parts = String(name || "?").replace(/\(dummy\)/i, "").trim().split(/\s+/);
    return ((parts[0] || "?")[0] + ((parts[1] || "")[0] || "")).toUpperCase();
  }
  function optionTags(items, selected) {
    return items.map(function (o) {
      var v = typeof o === "string" ? o : o.value, l = typeof o === "string" ? o : o.label;
      return '<option value="' + esc(v) + '"' + (String(v) === String(selected || "") ? " selected" : "") + ">" + esc(l) + "</option>";
    }).join("");
  }
  function ownerOptions() { return (opts().bdrs || []).map(function (b) { return { value: b.email, label: b.name || b.email }; }); }

  /* ---------- Carga ---------- */
  function load() {
    var id = Number(new URLSearchParams(location.search).get("id"));
    if (!id) { $("prCo").innerHTML = '<p class="pr-note">Falta el id de la empresa.</p>'; return Promise.resolve(); }
    return P.api("/prospecting/companies/" + id).then(function (c) {
      company = c;
      document.title = c.name + " · Prospecting · Vintti Hub";
      render();
    }).catch(function (err) {
      $("prCo").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>";
    });
  }

  /* ---------- Vista ---------- */
  function render() {
    var c = company;
    $("prCo").innerHTML =
      '<div class="pr-co">' +
        '<aside class="pr-co__left">' + leftCard(c) + "</aside>" +
        '<section class="pr-co__main">' + mainCard(c) + "</section>" +
        '<aside class="pr-co__right">' + contactsCard(c) + workflowsCard(c) + "</aside>" +
      "</div>";
  }

  function leftCard(c) {
    var url = c.website || (c.domain ? "https://" + c.domain : "");
    var sel = function (key, label, items) {
      return '<label class="pr-co-field"><span class="pr-filter__label">' + esc(label) + "</span>" +
        '<select class="pr-filter__input" data-edit="' + key + '"><option value="">—</option>' + optionTags(items, c[key]) + "</select></label>";
    };
    var inp = function (key, label, type) {
      var v = c[key] || "";
      if (type === "date") v = String(v).slice(0, 10);
      return '<label class="pr-co-field"><span class="pr-filter__label">' + esc(label) + "</span>" +
        '<input type="' + (type || "text") + '" class="pr-filter__input" data-edit="' + key + '" value="' + esc(v) + '"></label>';
    };
    var clay = companyFields().filter(function (f) {
      return ["prospecting_status", "prospecting_owner_email", "prospecting_owner_apollo", "prospecting_start_date",
        "not_icp_reason", "week_label", "name"].indexOf(f.key) === -1;
    });
    return '<div class="pr-co-card">' +
        '<a class="pr-co-back" href="prospecting.html"><i class="fa-solid fa-chevron-left"></i> Prospecting</a>' +
        '<div class="pr-co-id"><span class="pr-co-avatar">' + esc(initials(c.name)) + "</span>" +
          '<div><h1 class="pr-co-name">' + esc(c.name) + (c.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") + "</h1>" +
          (url ? '<a class="pr-co-domain" href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(c.domain || url) +
            ' <i class="fa-solid fa-arrow-up-right-from-square"></i></a>' : "") + "</div></div>" +
        (c.contact_incomplete ? '<div class="pr-co-warn"><i class="fa-solid fa-circle-exclamation"></i> Contacto incompleto: ' +
          'la empresa está en ' + esc(c.prospecting_status) + ' y le falta un contacto con los datos obligatorios.' +
          ' <button type="button" class="pr-wf-link" data-act="complete">Completar</button></div>' : "") +
      "</div>" +
      '<div class="pr-co-card"><h3 class="pr-section__title">Prospecting</h3>' +
        '<div class="pr-co-status">' +
          '<select class="pr-cell-select pr-status" data-edit="prospecting_status" data-status="' + esc(c.prospecting_status || "") + '">' +
            '<option value="">—</option>' + optionTags(opts().statuses || [], c.prospecting_status) + "</select></div>" +
        sel("prospecting_owner_email", "Prospecting Owner", ownerOptions()) +
        inp("prospecting_owner_apollo", "Prospecting Owner Apollo") +
        inp("prospecting_start_date", "Prospecting Start Date", "date") +
        inp("week_label", "Semana") +
        sel("not_icp_reason", "Not ICP Reason", opts().not_icp_reasons || []) +
        '<p class="pr-drawer__status" id="prCoStatus"></p>' +
      "</div>" +
      '<details class="pr-co-card pr-co-more" open><summary><h3 class="pr-section__title">Datos de Clay</h3></summary><dl class="pr-kv">' +
        clay.map(function (f) { return kv(f, c[f.key]); }).join("") + "</dl></details>";
  }

  function kv(f, v) {
    var val;
    if (v == null || v === "") val = "—";
    else if (f.type === "url") val = '<a href="' + esc(v) + '" target="_blank" rel="noopener">' + esc(v) + "</a>";
    else if (f.type === "date") val = P.fmtDate(v);
    else val = esc(v);
    return "<dt>" + esc(f.label) + "</dt><dd>" + val + "</dd>";
  }

  function mainCard(c) {
    return '<div class="pr-co-card pr-co-card--main">' +
      '<div class="pr-co-tabs">' +
        '<button type="button" class="pr-co-tab' + (tab === "activity" ? " is-active" : "") + '" data-tab="activity">Actividad</button>' +
        '<button type="button" class="pr-co-tab' + (tab === "info" ? " is-active" : "") + '" data-tab="info">Información</button>' +
      "</div>" +
      (tab === "activity" ? activityHtml(c) : '<dl class="pr-kv pr-kv--wide">' + companyFields().map(function (f) { return kv(f, c[f.key]); }).join("") + "</dl>") +
      "</div>";
  }

  /* Los eventos guardan texto: un datetime en ISO, un sí/no como true/false. */
  function fmtVal(f, v) {
    if (v == null || v === "") return "—";
    if (!f) return v;
    if (f.type === "datetime") return C.fmtLocal(v);
    if (f.type === "date") return P.fmtDate(v);
    if (f.type === "bool") return v === "true" ? "Sí" : v === "false" ? "No" : v;
    if (f.type === "owner" || f.type === "user") return P.ownerName(v) || v;
    return v;
  }

  function eventText(ev) {
    var wf = String(ev.source || "").indexOf("workflow:") === 0;
    var who = wf ? "Workflow #" + ev.source.slice(9) : ev.source === "clay" ? "Clay" : ev.source === "seed" ? "Datos de prueba"
      : (P.ownerName(ev.actor) || ev.actor || ev.source);
    var subject = ev.contact_id ? '<span class="pr-co-ev__contact"><i class="fa-regular fa-user"></i> ' + esc(ev.contact_name || "Contacto") + "</span> " : "";
    var f = ev.contact_id ? contactField(ev.field) : companyField(ev.field);
    var what;
    if (ev.field === "__note__") what = '<span class="pr-events__note">' + esc(ev.new_value) + "</span>";
    else if (ev.field) what = esc(f ? f.label : ev.field) + ": " + esc(fmtVal(f, ev.old_value)) + " → <strong>" + esc(fmtVal(f, ev.new_value)) + "</strong>";
    else if (ev.new_value === "created") what = "Se creó la empresa";
    else if (ev.new_value === "contact_created") what = "Se agregó el contacto";
    else if (String(ev.new_value || "").indexOf("contact_deleted:") === 0) what = "Se borró el contacto " + esc(ev.new_value.slice(16));
    else if (String(ev.new_value || "").indexOf("contact_moved_to:") === 0) what = "Se asoció el contacto a " + esc(ev.new_value.slice(17));
    else if (String(ev.new_value || "").indexOf("contact_moved_from:") === 0) what = "Se asoció el contacto (antes en " + esc(ev.new_value.slice(19)) + ")";
    else what = esc(ev.new_value || "");
    return { who: who, wf: wf, html: subject + what, icon: ev.field === "__note__" ? "fa-regular fa-note-sticky"
      : ev.contact_id ? "fa-regular fa-user" : wf ? "fa-solid fa-diagram-project" : "fa-regular fa-pen-to-square" };
  }

  function activityHtml(c) {
    var events = c.events || [];
    if (!events.length) return '<p class="pr-note">Sin actividad todavía.</p>';
    var html = "", lastMonth = "";
    events.forEach(function (ev) {
      var d = new Date(ev.at);
      var month = MESES[d.getMonth()] + " " + d.getFullYear();
      if (month !== lastMonth) { html += '<h4 class="pr-co-month">' + month + "</h4>"; lastMonth = month; }
      var t = eventText(ev);
      html += '<div class="pr-co-ev"><span class="pr-co-ev__icon' + (t.wf ? " is-wf" : "") + '"><i class="' + t.icon + '"></i></span>' +
        '<div class="pr-co-ev__body"><div>' + t.html + "</div>" +
        '<span class="pr-co-ev__meta">' + esc(t.who) + " · " + P.fmtDateTime(ev.at) + "</span></div></div>";
    });
    return '<div class="pr-co-timeline">' + html + "</div>";
  }

  function contactsCard(c) {
    var list = c.contacts || [];
    var needs = c.prospecting_status === "Qualified" || c.prospecting_status === "SQL";
    var cards = list.map(function (ct) {
      var miss = ct.missing_required || [];
      return '<button type="button" class="pr-co-contact" data-contact="' + ct.id + '">' +
        '<span class="pr-co-avatar pr-co-avatar--sm">' + esc(initials(ct.name)) + "</span>" +
        '<span class="pr-co-contact__body"><strong>' + esc(ct.name) + (ct.is_primary ? ' <i class="fa-solid fa-star" title="Contacto principal"></i>' : "") + "</strong>" +
          '<span class="pr-note">' + esc(ct.position || ct.in_current_position || "—") + "</span>" +
          (ct.email ? '<span class="pr-co-contact__email">' + esc(ct.email) + "</span>" : "") +
          '<span class="pr-co-contact__tags">' + (ct.lead_life ? '<span class="pr-wf-stat">' + esc(ct.lead_life) + "</span>" : "") +
            (needs && miss.length ? '<span class="pr-wf-stat pr-wf-stat--failed">Faltan ' + miss.length + "</span>" : "") + "</span>" +
        "</span></button>";
    }).join("");
    return '<div class="pr-co-card"><div class="pr-co-card__head"><h3 class="pr-section__title">Contactos (' + list.length + ")</h3>" +
      '<button type="button" class="pr-btn" data-act="add-contact"><i class="fa-solid fa-plus"></i> Agregar</button></div>' +
      (cards || '<p class="pr-note">Todavía no hay contactos.</p>') + "</div>";
  }

  function workflowsCard(c) {
    var list = c.enrollments || [];
    if (!list.length) return "";
    var LBL = { active: "En curso", waiting: "Esperando", completed: "Terminó", unenrolled: "Desinscripto", goal_met: "Cumplió la meta", failed: "Con error" };
    return '<div class="pr-co-card"><h3 class="pr-section__title">Workflows</h3><ul class="pr-events">' + list.map(function (e) {
      return '<li><span class="pr-events__src pr-events__src--wf">' + esc(e.workflow_name) + "</span>" +
        (e.contact_name ? ' <span class="pr-note">· ' + esc(e.contact_name) + "</span>" : "") +
        ' <span class="pr-wf-stat pr-wf-stat--' + esc(e.status) + '">' + esc(LBL[e.status] || e.status) + "</span>" +
        (e.last_step ? '<div class="pr-note">' + esc(e.last_step) + "</div>" : "") + "</li>";
    }).join("") + "</ul></div>";
  }

  /* ---------- Acciones ---------- */
  function patch(field, value) {
    var st = $("prCoStatus");
    st.textContent = "Guardando…";
    var body = {};
    body[field] = value || null;
    return P.api("/prospecting/companies/" + company.id, { method: "PATCH", body: JSON.stringify(body) }).then(function (row) {
      st.textContent = "Guardado.";
      var applied = (row.workflows_applied || []).map(function (a) { return "<strong>" + esc(a.name) + "</strong>"; });
      if (applied.length) P.toast('<i class="fa-solid fa-diagram-project"></i> El workflow ' + applied.join(", ") + " actualizó esta empresa.");
      return load().then(function () {
        if (row.needs_contact) C.completeFlow(company, row.contacts || company.contacts, function () { load(); });
      });
    }).catch(function (err) { st.textContent = "Error: " + err.message; });
  }

  function bind() {
    var root = $("prCo");
    root.addEventListener("change", function (e) {
      var k = e.target.getAttribute("data-edit");
      if (k) patch(k, e.target.value);
    });
    root.addEventListener("click", function (e) {
      var b = e.target.closest("[data-tab],[data-act],[data-contact]");
      if (!b) return;
      if (b.getAttribute("data-tab")) { tab = b.getAttribute("data-tab"); render(); return; }
      var act = b.getAttribute("data-act");
      if (act === "add-contact") C.open({ companyId: company.id, companyName: company.name, onSaved: function () { load(); } });
      else if (act === "complete") C.completeFlow(company, company.contacts, function () { load(); });
      else if (b.getAttribute("data-contact")) {
        C.open({ contactId: Number(b.getAttribute("data-contact")), companyId: company.id,
          requireQualified: company.contact_incomplete, onSaved: function () { load(); } });
      }
    });
  }

  function init() {
    P = window.Prospecting;
    C = window.ProspectingContacts;
    P.boot().then(function (me) {
      if (!me.has_access) { $("prDenied").hidden = false; $("prCo").innerHTML = ""; return; }
      bind();  // una sola vez: #prCo no se reemplaza, sólo su contenido
      return load();
    }).catch(function (err) {
      $("prCo").innerHTML = '<p class="pr-note">No se pudo cargar: ' + esc(err.message) + "</p>";
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
