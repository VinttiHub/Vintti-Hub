/* =====================================================================
   Prospecting — pestaña Workflows: lista + editor visual tipo HubSpot.

   Un workflow es JSON (lo valida y lo traduce a SQL el backend,
   backend/prospecting/rules.py):
     conditions = {groups: [{rules: [{field, op, value}]}]}   grupos = O, reglas = Y
     actions    = [{type: set|clear|set_today, field, value?}]

   Los campos, operadores y acciones salen de GET /prospecting/options
   (workflow_schema): no hay una segunda copia de esas listas acá.

   Editan: pgonzales, manuela y mia (WORKFLOW_EDITORS). El resto, sólo lectura.
   Depende de window.Prospecting (prospecting.js).
   ===================================================================== */
(function () {
  "use strict";

  var P = null;          // window.Prospecting
  var root = null;       // <section id="prWorkflows">
  var canEdit = false;
  var list = [];
  var draft = null;      // workflow en edición
  var dirty = false;

  function $(id) { return document.getElementById(id); }
  function esc(v) { return P.esc(v); }
  function schema() { return P.options().workflow_schema || { fields: [], operators: {}, operators_by_type: {}, actions: {} }; }
  function field(key) { return schema().fields.filter(function (f) { return f.key === key; })[0]; }
  function opDef(op) { return schema().operators[op] || { label: op, value: null }; }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }

  /* Valores posibles de un campo de lista (enum / owner). */
  function choices(f) {
    if (!f) return [];
    if (f.type === "owner") {
      return P.options().bdrs.map(function (b) { return { value: b.email, label: b.name || b.email }; });
    }
    return (f.options || []).map(function (o) { return { value: o, label: o }; });
  }
  function choiceLabel(f, v) {
    var hit = choices(f).filter(function (c) { return c.value === v; })[0];
    return hit ? hit.label : v;
  }

  /* ---------- Frase legible ---------- */
  function ruleText(r) {
    var f = field(r.field);
    if (!f) return "—";
    var od = opDef(r.op);
    var v = "";
    if (od.value === "list") v = (r.value || []).map(function (x) { return "<em>" + esc(choiceLabel(f, x)) + "</em>"; }).join(" or ");
    else if (od.value === "days") v = "<em>" + esc(r.value) + " days ago</em>";
    else if (od.value === "date") v = "<em>" + P.fmtDate(r.value) + "</em>";
    else if (od.value) v = "<em>" + esc(r.value) + "</em>";
    return "<strong>" + esc(f.label) + "</strong> " + esc(od.label) + (v ? " " + v : "");
  }
  function conditionsText(c) {
    var groups = (c && c.groups) || [];
    return groups.map(function (g) {
      return (g.rules || []).map(ruleText).join(" <span class=\"pr-wf-and\">and</span> ");
    }).join(" <span class=\"pr-wf-or\">or</span> ");
  }
  function actionText(a) {
    var f = field(a.field);
    var label = f ? f.label : a.field;
    if (a.type === "clear") return "Clears <strong>" + esc(label) + "</strong>";
    if (a.type === "set_today") return "Sets <strong>" + esc(label) + "</strong> to today";
    var v = f && (f.type === "enum" || f.type === "owner") ? choiceLabel(f, a.value)
      : f && f.type === "date" ? P.fmtDate(a.value) : a.value;
    return "Sets <strong>" + esc(label) + "</strong> to <em>" + esc(v) + "</em>";
  }

  /* =================================================================
     Lista
     ================================================================= */
  function show() {
    P = window.Prospecting;
    root = $("prWorkflows");
    if (draft) { renderEditor(); return; }
    loadList();
  }

  function loadList() {
    root.innerHTML = '<p class="pr-note">Loading workflows…</p>';
    return P.api("/prospecting/workflows").then(function (r) {
      list = r.workflows;
      canEdit = !!r.can_edit;
      renderList();
    }).catch(function (err) {
      root.innerHTML = '<p class="pr-note">Could not load workflows: ' + esc(err.message) + "</p>";
    });
  }

  function testBanner() {
    if (schema().automation_real_data) return "";
    return '<div class="pr-wf-banner"><i class="fa-solid fa-flask"></i><div>' +
      "<strong>Test phase:</strong> active workflows run on their own (when a company is edited or arrives from Clay) " +
      "<strong>only on dummy companies</strong>. On real companies they only run when someone presses Apply.</div></div>";
  }

  function renderList() {
    var cards = list.map(function (w) {
      var last = w.last_run_at
        ? "Last run " + P.fmtDateTime(w.last_run_at) + " · " + w.last_run_affected + " compan" + (w.last_run_affected === 1 ? "y" : "ies")
        : "Never run in bulk";
      return '<article class="pr-wf-card' + (w.enabled ? " is-on" : "") + '" data-wf="' + w.id + '" tabindex="0">' +
        '<header class="pr-wf-card__head">' +
          '<h3 class="pr-wf-card__name">' + esc(w.name) + "</h3>" +
          (canEdit
            ? '<label class="pr-switch" title="' + (w.enabled ? "Active" : "Inactive") + '"><input type="checkbox" data-toggle="' + w.id + '"' + (w.enabled ? " checked" : "") + '><span></span></label>'
            : '<span class="pr-wf-pill' + (w.enabled ? " is-on" : "") + '">' + (w.enabled ? "Active" : "Inactive") + "</span>") +
        "</header>" +
        (w.description ? '<p class="pr-wf-card__desc">' + esc(w.description) + "</p>" : "") +
        '<div class="pr-wf-card__rule"><span class="pr-wf-card__tag">When</span><div>' + conditionsText(w.conditions) + "</div></div>" +
        '<div class="pr-wf-card__rule"><span class="pr-wf-card__tag pr-wf-card__tag--do">Then</span><div>' +
          (w.actions || []).map(actionText).join("<br>") + "</div></div>" +
        '<footer class="pr-wf-card__foot">' + esc(last) +
          (w.updated_by ? " · edited by " + esc(P.ownerName(w.updated_by) || w.updated_by) : "") + "</footer>" +
        "</article>";
    }).join("");
    root.innerHTML =
      '<div class="pr-wf-top">' +
        '<div><h2 class="pr-wf-title">Workflows</h2>' +
        '<p class="pr-note" style="margin:0">Rules that update companies automatically, like HubSpot workflows.' +
        (canEdit ? "" : " Only pgonzales, manuela and mia can edit them.") + "</p></div>" +
        (canEdit ? '<button type="button" class="pr-btn pr-btn--primary" id="prWfNew"><i class="fa-solid fa-plus"></i> Create workflow</button>' : "") +
      "</div>" + testBanner() +
      (list.length ? '<div class="pr-wf-grid">' + cards + "</div>"
        : '<div class="pr-wf-empty">No workflows yet.' + (canEdit ? " Create the first one." : "") + "</div>");

    var nb = $("prWfNew");
    if (nb) nb.onclick = function () { openEditor(null); };
    root.querySelectorAll("[data-toggle]").forEach(function (cb) {
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () {
        var id = Number(cb.getAttribute("data-toggle"));
        toggle(id, cb.checked).catch(function () { cb.checked = !cb.checked; });
      });
    });
    root.querySelectorAll("[data-wf]").forEach(function (card) {
      var open = function (e) {
        if (e.target.closest(".pr-switch")) return;
        var w = list.filter(function (x) { return x.id === Number(card.getAttribute("data-wf")); })[0];
        openEditor(w);
      };
      card.addEventListener("click", open);
      card.addEventListener("keydown", function (e) { if (e.key === "Enter") open(e); });
    });
  }

  function toggle(id, enabled) {
    return P.api("/prospecting/workflows/" + id + "/toggle", {
      method: "POST", body: JSON.stringify({ enabled: enabled }),
    }).then(function (w) {
      P.toast('<i class="fa-solid fa-diagram-project"></i> <strong>' + esc(w.name) + "</strong> is now " + (w.enabled ? "active" : "inactive") + ".");
      list = list.map(function (x) { return x.id === w.id ? Object.assign(x, w) : x; });
      if (draft && draft.id === w.id) { draft.enabled = w.enabled; renderEditor(); }
      else renderList();
      return w;
    }).catch(function (err) {
      alert(errorText(err));
      throw err;
    });
  }

  function errorText(err) {
    return err.errors && err.errors.length ? err.errors.join("\n") : err.message;
  }

  /* =================================================================
     Editor
     ================================================================= */
  function blankRule() {
    return { field: "prospecting_status", op: "is_any", value: [] };
  }
  function blankAction() {
    return { type: "set", field: "prospecting_status", value: "" };
  }

  function openEditor(w) {
    draft = w ? clone({
      id: w.id, name: w.name, description: w.description || "", enabled: w.enabled,
      reenroll: w.reenroll, conditions: w.conditions, actions: w.actions,
    }) : {
      id: null, name: "", description: "", enabled: false, reenroll: true,
      conditions: { groups: [{ rules: [blankRule()] }] }, actions: [blankAction()],
    };
    dirty = false;
    renderEditor();
  }

  function closeEditor() {
    if (dirty && !confirm("You have unsaved changes. Leave anyway?")) return;
    draft = null;
    dirty = false;
    loadList();
  }

  function markDirty() {
    dirty = true;
    var s = $("prWfSaveState");
    if (s) s.textContent = "Unsaved changes";
  }

  function optionTags(items, selected) {
    return items.map(function (o) {
      return '<option value="' + esc(o.value) + '"' + (o.value === selected ? " selected" : "") + ">" + esc(o.label) + "</option>";
    }).join("");
  }

  function fieldOptions(selected, onlyEditable) {
    return optionTags(schema().fields.filter(function (f) { return !onlyEditable || f.editable; })
      .map(function (f) { return { value: f.key, label: f.label }; }), selected);
  }

  /* Control del valor de una condición según lo que pide el operador. */
  function ruleValueHtml(r, path) {
    var f = field(r.field);
    var kind = opDef(r.op).value;
    var dis = canEdit ? "" : " disabled";
    if (!kind) return "";
    if (kind === "list") {
      var vals = r.value || [];
      return '<div class="pr-wf-chips" data-path="' + path + '">' + choices(f).map(function (c) {
        var on = vals.indexOf(c.value) !== -1;
        return '<button type="button" class="pr-wf-chip' + (on ? " is-on" : "") + '" data-chip="' + esc(c.value) + '"' + dis + ">" +
          (on ? '<i class="fa-solid fa-check"></i> ' : "") + esc(c.label) + "</button>";
      }).join("") + (choices(f).length ? "" : '<span class="pr-note">No values available.</span>') + "</div>";
    }
    if (kind === "days") {
      return '<div class="pr-wf-days"><input type="number" min="0" step="1" class="pr-filter__input" data-val="' + path + '" value="' + esc(r.value == null ? "" : r.value) + '"' + dis + "><span>days ago</span></div>";
    }
    var type = kind === "date" ? "date" : kind === "number" ? "number" : "text";
    return '<input type="' + type + '" class="pr-filter__input" data-val="' + path + '" value="' + esc(r.value == null ? "" : r.value) + '"' +
      (type === "text" ? ' placeholder="Text…"' : "") + dis + ">";
  }

  function actionValueHtml(a, i) {
    if (a.type !== "set") return "";
    var f = field(a.field);
    var dis = canEdit ? "" : " disabled";
    if (!f) return "";
    if (f.type === "enum" || f.type === "owner") {
      return '<select class="pr-filter__input" data-aval="' + i + '"' + dis + '><option value="">Choose…</option>' +
        optionTags(choices(f), a.value) + "</select>";
    }
    var type = f.type === "date" ? "date" : f.type === "number" ? "number" : "text";
    return '<input type="' + type + '" class="pr-filter__input" data-aval="' + i + '" value="' + esc(a.value == null ? "" : a.value) + '"' + dis + ">";
  }

  function renderEditor() {
    var d = draft;
    var dis = canEdit ? "" : " disabled";
    var groups = d.conditions.groups.map(function (g, gi) {
      var rules = g.rules.map(function (r, ri) {
        var f = field(r.field);
        var ops = (schema().operators_by_type[f ? f.type : "text"] || []).map(function (o) {
          return { value: o, label: opDef(o).label };
        });
        var path = gi + "." + ri;
        return (ri ? '<div class="pr-wf-joiner">and</div>' : "") +
          '<div class="pr-wf-rule">' +
            '<div class="pr-wf-rule__row">' +
              '<select class="pr-filter__input" data-rfield="' + path + '"' + dis + ">" + fieldOptions(r.field, false) + "</select>" +
              '<select class="pr-filter__input" data-rop="' + path + '"' + dis + ">" + optionTags(ops, r.op) + "</select>" +
              (canEdit ? '<button type="button" class="pr-wf-x" data-rdel="' + path + '" title="Remove condition"><i class="fa-solid fa-xmark"></i></button>' : "") +
            "</div>" + ruleValueHtml(r, path) +
          "</div>";
      }).join("");
      return (gi ? '<div class="pr-wf-or-sep"><span>or</span></div>' : "") +
        '<div class="pr-wf-group">' +
          '<div class="pr-wf-group__head">Group ' + (gi + 1) +
            (canEdit && d.conditions.groups.length > 1 ? '<button type="button" class="pr-wf-link" data-gdel="' + gi + '">Remove group</button>' : "") +
          "</div>" + rules +
          (canEdit ? '<button type="button" class="pr-wf-add" data-radd="' + gi + '"><i class="fa-solid fa-plus"></i> Add condition (and)</button>' : "") +
        "</div>";
    }).join("");

    var actions = d.actions.map(function (a, i) {
      var f = field(a.field);
      var types = Object.keys(schema().actions).filter(function (t) {
        var only = schema().actions[t].types;
        return !only || (f && only.indexOf(f.type) !== -1);
      }).map(function (t) { return { value: t, label: schema().actions[t].label }; });
      return '<div class="pr-wf-connector"></div>' +
        '<div class="pr-wf-node pr-wf-node--action">' +
          '<div class="pr-wf-node__head"><span class="pr-wf-node__icon"><i class="fa-regular fa-pen-to-square"></i></span>' +
            '<span class="pr-wf-node__title">' + (i + 1) + ". Edit record</span>" +
            (canEdit && d.actions.length > 1 ? '<button type="button" class="pr-wf-x" data-adel="' + i + '" title="Remove action"><i class="fa-solid fa-xmark"></i></button>' : "") +
          "</div>" +
          '<div class="pr-wf-action">' +
            '<select class="pr-filter__input" data-atype="' + i + '"' + dis + ">" + optionTags(types, a.type) + "</select>" +
            '<select class="pr-filter__input" data-afield="' + i + '"' + dis + ">" + fieldOptions(a.field, true) + "</select>" +
            actionValueHtml(a, i) +
          "</div>" +
          '<p class="pr-wf-node__sum">' + actionText(a) + "</p>" +
        "</div>";
    }).join("");

    root.innerHTML =
      '<div class="pr-wf-editor">' +
        '<div class="pr-wf-ebar">' +
          '<button type="button" class="pr-btn" id="prWfBack"><i class="fa-solid fa-arrow-left"></i> Workflows</button>' +
          '<input class="pr-wf-name" id="prWfName" placeholder="Workflow name" value="' + esc(d.name) + '"' + dis + ">" +
          '<span class="pr-wf-pill' + (d.enabled ? " is-on" : "") + '">' + (d.enabled ? "Active" : "Inactive") + "</span>" +
          '<span class="pr-wf-ebar__state" id="prWfSaveState">' + (dirty ? "Unsaved changes" : "") + "</span>" +
          (canEdit
            ? (d.id ? '<button type="button" class="pr-btn pr-btn--danger" id="prWfDelete"><i class="fa-regular fa-trash-can"></i></button>' : "") +
              '<button type="button" class="pr-btn" id="prWfSave"><i class="fa-regular fa-floppy-disk"></i> Save</button>' +
              (d.id ? '<button type="button" class="pr-btn pr-btn--primary" id="prWfToggle">' +
                (d.enabled ? '<i class="fa-solid fa-pause"></i> Turn off' : '<i class="fa-solid fa-play"></i> Turn on') + "</button>" : "")
            : "") +
        "</div>" +
        '<div class="pr-wf-errors" id="prWfErrors" hidden></div>' +
        '<div class="pr-wf-body">' +
          '<div class="pr-wf-canvas">' +
            '<textarea class="pr-wf-desc" id="prWfDesc" rows="1" placeholder="Description (optional)"' + dis + ">" + esc(d.description) + "</textarea>" +
            '<div class="pr-wf-node pr-wf-node--trigger">' +
              '<div class="pr-wf-node__head"><span class="pr-wf-node__icon pr-wf-node__icon--trigger"><i class="fa-regular fa-flag"></i></span>' +
                '<span class="pr-wf-node__title">Enroll companies that meet these conditions</span></div>' +
              groups +
              (canEdit ? '<button type="button" class="pr-wf-add pr-wf-add--group" id="prWfGroupAdd"><i class="fa-solid fa-plus"></i> Add group (or)</button>' : "") +
              '<label class="pr-wf-reenroll"><span class="pr-switch pr-switch--sm"><input type="checkbox" id="prWfReenroll"' + (d.reenroll ? " checked" : "") + dis + "><span></span></span>" +
                "<span><strong>Re-enrollment</strong> — a company can go through this workflow again every time it meets the conditions.</span></label>" +
            "</div>" +
            actions +
            (canEdit ? '<div class="pr-wf-connector"></div><button type="button" class="pr-wf-plus" id="prWfActionAdd" title="Add action"><i class="fa-solid fa-plus"></i></button>' : "") +
            '<div class="pr-wf-connector"></div><div class="pr-wf-end">End</div>' +
          "</div>" +
          '<aside class="pr-wf-side">' +
            '<h3 class="pr-section__title">Preview</h3>' +
            '<p class="pr-note">Shows which companies would change right now with what is on screen (saved or not). Nothing is written.</p>' +
            '<label class="pr-filter"><span class="pr-filter__label">As of</span><input type="date" class="pr-filter__input" id="prWfAsOf" value="' + P.todayIso() + '"></label>' +
            '<label class="pr-check"><input type="checkbox" id="prWfOnlyDummy" checked> Only dummies</label>' +
            '<button type="button" class="pr-btn pr-btn--primary" id="prWfPreview"' + (canEdit ? "" : " disabled") + '><i class="fa-solid fa-eye"></i> Preview</button>' +
            (canEdit && d.id ? '<button type="button" class="pr-btn" id="prWfApply"><i class="fa-solid fa-play"></i> Apply now</button>' : "") +
            '<div id="prWfPreviewOut"></div>' +
          "</aside>" +
        "</div>" +
      "</div>";
    bindEditor();
  }

  function at(path) {
    var p = path.split(".").map(Number);
    return draft.conditions.groups[p[0]].rules[p[1]];
  }

  function bindEditor() {
    $("prWfBack").onclick = closeEditor;
    if (!canEdit) return;
    var body = root.querySelector(".pr-wf-editor");

    $("prWfName").addEventListener("input", function (e) { draft.name = e.target.value; markDirty(); });
    $("prWfDesc").addEventListener("input", function (e) { draft.description = e.target.value; markDirty(); });
    $("prWfReenroll").addEventListener("change", function (e) { draft.reenroll = e.target.checked; markDirty(); });

    body.addEventListener("change", function (e) {
      var t = e.target, path;
      if ((path = t.getAttribute("data-rfield"))) {
        var r = at(path);
        r.field = t.value;
        var f = field(r.field);
        r.op = (schema().operators_by_type[f.type] || [])[0];
        r.value = opDef(r.op).value === "list" ? [] : "";
      } else if ((path = t.getAttribute("data-rop"))) {
        var rr = at(path);
        var before = opDef(rr.op).value;
        rr.op = t.value;
        if (opDef(rr.op).value !== before) rr.value = opDef(rr.op).value === "list" ? [] : "";
      } else if ((path = t.getAttribute("data-atype"))) {
        draft.actions[Number(path)].type = t.value;
        if (t.value !== "set") delete draft.actions[Number(path)].value;
      } else if ((path = t.getAttribute("data-afield"))) {
        var a = draft.actions[Number(path)];
        a.field = t.value;
        var af = field(a.field);
        var only = schema().actions[a.type].types;
        if (only && only.indexOf(af.type) === -1) a.type = "set";
        a.value = "";
      } else if ((path = t.getAttribute("data-aval"))) {
        draft.actions[Number(path)].value = t.value;
      } else {
        return;
      }
      markDirty();
      renderEditor();
    });
    // Texto / número / fecha: se guarda sin redibujar (no perder el foco).
    body.addEventListener("input", function (e) {
      var path = e.target.getAttribute("data-val");
      if (path) { at(path).value = e.target.value; markDirty(); }
      var ap = e.target.getAttribute("data-aval");
      if (ap && e.target.tagName === "INPUT") { draft.actions[Number(ap)].value = e.target.value; markDirty(); }
    });
    body.addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      var v;
      if ((v = b.getAttribute("data-chip")) !== null && b.closest("[data-path]")) {
        var r = at(b.closest("[data-path]").getAttribute("data-path"));
        r.value = r.value || [];
        var i = r.value.indexOf(v);
        if (i === -1) r.value.push(v); else r.value.splice(i, 1);
      } else if ((v = b.getAttribute("data-radd")) !== null) {
        draft.conditions.groups[Number(v)].rules.push(blankRule());
      } else if ((v = b.getAttribute("data-rdel")) !== null) {
        var p = v.split(".").map(Number);
        var g = draft.conditions.groups[p[0]];
        g.rules.splice(p[1], 1);
        if (!g.rules.length) draft.conditions.groups.splice(p[0], 1);
        if (!draft.conditions.groups.length) draft.conditions.groups.push({ rules: [blankRule()] });
      } else if ((v = b.getAttribute("data-gdel")) !== null) {
        draft.conditions.groups.splice(Number(v), 1);
      } else if ((v = b.getAttribute("data-adel")) !== null) {
        draft.actions.splice(Number(v), 1);
      } else if (b.id === "prWfGroupAdd") {
        draft.conditions.groups.push({ rules: [blankRule()] });
      } else if (b.id === "prWfActionAdd") {
        var used = draft.actions.map(function (a) { return a.field; });
        var free = schema().fields.filter(function (f) { return f.editable && used.indexOf(f.key) === -1; })[0];
        draft.actions.push({ type: "set", field: free ? free.key : "prospecting_status", value: "" });
      } else if (b.id === "prWfSave") { save(); return; }
      else if (b.id === "prWfToggle") { saveThen(function () { return toggle(draft.id, !draft.enabled); }); return; }
      else if (b.id === "prWfDelete") { remove(); return; }
      else if (b.id === "prWfPreview") { preview(); return; }
      else if (b.id === "prWfApply") { applyNow(); return; }
      else return;
      markDirty();
      renderEditor();
    });
  }

  function payload() {
    return {
      name: draft.name, description: draft.description, reenroll: draft.reenroll,
      conditions: draft.conditions, actions: draft.actions,
    };
  }

  function showErrors(err) {
    var box = $("prWfErrors");
    if (!err) { box.hidden = true; box.innerHTML = ""; return; }
    var list = err.errors && err.errors.length ? err.errors : [err.message];
    box.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i><ul>' +
      list.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>";
    box.hidden = false;
  }

  function call(path, opts) { return P.api(path, opts); }

  function save() {
    showErrors(null);
    var isNew = !draft.id;
    var req = isNew
      ? call("/prospecting/workflows", { method: "POST", body: JSON.stringify(payload()) })
      : call("/prospecting/workflows/" + draft.id, { method: "PUT", body: JSON.stringify(payload()) });
    return req.then(function (w) {
      draft.id = w.id;
      draft.enabled = w.enabled;
      dirty = false;
      P.toast('<i class="fa-regular fa-floppy-disk"></i> <strong>' + esc(w.name) + "</strong> saved." +
        (isNew ? " It starts inactive: turn it on when the Preview looks right." : ""));
      renderEditor();
      return w;
    }).catch(function (err) { showErrors(err); throw err; });
  }

  function saveThen(fn) {
    var p = dirty || !draft.id ? save() : Promise.resolve();
    p.then(fn).catch(function () {});
  }

  function remove() {
    if (!confirm("Delete the workflow «" + draft.name + "»? Companies it already changed stay as they are.")) return;
    P.api("/prospecting/workflows/" + draft.id, { method: "DELETE" }).then(function () {
      P.toast("Workflow deleted.");
      draft = null;
      dirty = false;
      loadList();
    }).catch(function (err) { alert(err.message); });
  }

  function renderResult(r, applied) {
    var items = r.items || [];
    var labelOf = function (k) { var f = field(k); return f ? f.label : k; };
    var fmt = function (k, v) {
      if (v == null || v === "") return "—";
      var f = field(k);
      if (f && f.type === "owner") return P.ownerName(v) || v;
      if (f && f.type === "date") return P.fmtDate(v);
      return v;
    };
    $("prWfPreviewOut").innerHTML = '<div class="pr-result"><h4>' + items.length + " compan" + (items.length === 1 ? "y" : "ies") +
      (applied ? " changed" : " would change") + " (as of " + P.fmtDate(r.as_of) + ")</h4>" +
      (items.length ? "<ul>" + items.slice(0, 200).map(function (it) {
        return "<li><strong>" + esc(it.name) + "</strong>" + (it.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") + "<br>" +
          Object.keys(it.changes).map(function (k) {
            return esc(labelOf(k)) + ": " + esc(fmt(k, it.changes[k].from)) + " → " + esc(fmt(k, it.changes[k].to));
          }).join("; ") + "</li>";
      }).join("") + "</ul>" : '<p class="pr-note" style="margin:0">Nothing to do right now.</p>') + "</div>";
  }

  function preview() {
    showErrors(null);
    $("prWfPreviewOut").innerHTML = '<p class="pr-note">Previewing…</p>';
    var body = Object.assign(payload(), {
      id: draft.id, as_of: $("prWfAsOf").value, only_dummy: $("prWfOnlyDummy").checked,
    });
    call("/prospecting/workflows/preview", { method: "POST", body: JSON.stringify(body) })
      .then(function (r) { renderResult(r, false); })
      .catch(function (err) { $("prWfPreviewOut").innerHTML = ""; showErrors(err); });
  }

  function applyNow() {
    var onlyDummy = $("prWfOnlyDummy").checked;
    if (!onlyDummy && !confirm("Apply this workflow to REAL companies too?")) return;
    saveThen(function () {
      $("prWfPreviewOut").innerHTML = '<p class="pr-note">Applying…</p>';
      return P.api("/prospecting/workflows/run", {
        method: "POST",
        body: JSON.stringify({ workflow_ids: [draft.id], dry_run: false, as_of: $("prWfAsOf").value, only_dummy: onlyDummy }),
      }).then(function (r) {
        var w = r.workflows[0] || { items: [] };
        renderResult({ as_of: r.as_of, items: w.items }, true);
        P.reloadTable();
      }).catch(function (err) { showErrors(err); });
    });
  }

  window.ProspectingWorkflows = { show: show };
})();
