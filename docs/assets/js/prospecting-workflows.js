/* =====================================================================
   Prospecting — pestaña Workflows: lista, editor visual tipo HubSpot,
   historial y prueba con una empresa.

   Un workflow (lo valida y lo corre el backend: backend/prospecting/rules.py
   y engine.py):
     trigger  = {type: filter|event|schedule|manual, ...}
     steps    = {start, nodes: {id: {type: action|delay|branch, ..., next}}}
     unenroll / goal = condiciones (opcionales), settings = días hábiles, franja…
   Condiciones: grupos unidos por O, reglas de un grupo por Y.

   Todo el catálogo (propiedades, operadores, acciones, esperas, ramas,
   disparadores) sale de GET /prospecting/options → workflow_schema: no hay una
   segunda copia de esas listas acá.

   Editan: pgonzales, manuela y mia. El resto, sólo lectura.
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
  var tab = "editor";    // editor | history
  var openMenu = null;   // "+" con el menú abierto
  var historyState = { status: "", rows: [], detail: null };
  var testState = { q: "", results: [], company: null, result: null };
  /* Objeto del workflow que se está mirando: "company" | "contact". Decide qué
     propiedades se ofrecen y qué significa `company.<key>` / `contact.<key>`. */
  var curObj = "company";
  var CROSS = { company: "contact", contact: "company" };
  var CROSS_PREFIX_LABEL = { company: "Empresa · ", contact: "Algún contacto · " };

  function $(id) { return document.getElementById(id); }
  function esc(v) { return P.esc(v); }
  function S() { return P.options().workflow_schema || {}; }
  function objFields(obj) {
    var o = (S().objects || {})[obj];
    return o ? o.fields : (obj === "company" ? (S().fields || []) : []);
  }
  /* Campo por clave, en el objeto actual. `company.x` / `contact.x` = objeto asociado. */
  function field(key) {
    if (!key) return null;
    var i = String(key).indexOf(".");
    if (i !== -1) {
      var pre = key.slice(0, i), k = key.slice(i + 1);
      if (pre !== CROSS[curObj]) return null;
      var f = objFields(pre).filter(function (x) { return x.key === k; })[0];
      return f ? Object.assign({}, f, { key: key, label: CROSS_PREFIX_LABEL[pre] + f.label, cross: pre }) : null;
    }
    return objFields(curObj).filter(function (f) { return f.key === key; })[0] || null;
  }
  function opDef(op) { return (S().operators || {})[op] || { label: op, value: null }; }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  /* Claves de un catálogo en el orden del backend (el JSON llega ordenado alfabéticamente). */
  function keysOf(name) {
    var o = S().order && S().order[name];
    return o || Object.keys(S()[name] || {});
  }
  function actionGroups() {
    var acts = S().actions || {}, groups = {}, order = [];
    keysOf("actions").forEach(function (k) {
      if (acts[k].objects && acts[k].objects.indexOf(curObj) === -1) return;
      var g = acts[k].group;
      if (!groups[g]) { groups[g] = []; order.push(g); }
      groups[g].push(k);
    });
    return { groups: groups, order: order };
  }
  function newId() { return "n" + Math.random().toString(36).slice(2, 8); }

  var MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  function fmtFecha(iso) {
    if (!iso) return "—";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length !== 3) return esc(iso);
    return Number(p[2]) + " " + MESES[Number(p[1]) - 1] + " " + p[0];
  }
  function fmtFechaHora(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    return d.toLocaleString("es-AR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  /* ---------- Valores posibles ---------- */
  function bdrChoices() {
    return P.options().bdrs.map(function (b) { return { value: b.email, label: b.name || b.email }; });
  }
  function choices(f) {
    if (!f) return [];
    if (f.type === "owner") return bdrChoices();
    if (f.type === "user") return (P.options().users || []).map(function (u) { return { value: u.email, label: u.name || u.email }; });
    return (f.options || []).map(function (o) { return { value: o, label: o }; });
  }
  function choiceLabel(f, v) {
    var hit = choices(f).filter(function (c) { return c.value === v; })[0];
    return hit ? hit.label : v;
  }
  function optionTags(items, selected) {
    return items.map(function (o) {
      return '<option value="' + esc(o.value) + '"' + (String(o.value) === String(selected) ? " selected" : "") + ">" + esc(o.label) + "</option>";
    }).join("");
  }
  /* Opciones de propiedad: las del objeto y, con `cross`, las del objeto asociado
     (en un <optgroup> aparte). En un workflow de contacto, "Empresa · X" es la
     empresa del contacto; en uno de empresa, "Algún contacto · X". */
  function fieldOptions(selected, filterFn, cross) {
    var ok = filterFn || function () { return true; };
    var own = objFields(curObj).filter(ok).map(function (f) { return { value: f.key, label: f.label }; });
    var objs = S().objects || {};
    if (!cross || !objs[curObj]) return optionTags(own, selected);
    var other = CROSS[curObj];
    var theirs = objFields(other).filter(ok).map(function (f) { return { value: other + "." + f.key, label: CROSS_PREFIX_LABEL[other] + f.label }; });
    return '<optgroup label="' + esc(curObj === "contact" ? "Contacto" : "Empresa") + '">' + optionTags(own, selected) + "</optgroup>" +
      (theirs.length ? '<optgroup label="' + esc(curObj === "contact" ? "Empresa asociada" : "Algún contacto de la empresa") + '">' + optionTags(theirs, selected) + "</optgroup>" : "");
  }
  function defaultField() { return curObj === "contact" ? "lead_life" : "prospecting_status"; }
  function dis() { return canEdit ? "" : " disabled"; }

  /* =================================================================
     Frases legibles
     ================================================================= */
  function ruleText(r) {
    var f = field(r.field);
    if (!f) return "—";
    var od = opDef(r.op);
    var v = r.value, t = "";
    if (od.value === "list") t = (v || []).map(function (x) { return "<em>" + esc(choiceLabel(f, x)) + "</em>"; }).join(" o ");
    else if (od.value === "days") t = "<em>" + esc(v) + " días</em>";
    else if (od.value === "date") t = "<em>" + fmtFecha(v) + "</em>";
    else if (od.value === "number_range") t = "<em>" + esc((v || [])[0]) + " y " + esc((v || [])[1]) + "</em>";
    else if (od.value === "date_range") t = "<em>" + fmtFecha((v || [])[0]) + " y " + fmtFecha((v || [])[1]) + "</em>";
    else if (od.value) t = "<em>" + esc(v) + "</em>";
    return "<strong>" + esc(f.label) + "</strong> " + esc(od.label) + (t ? " " + t : "");
  }
  function conditionsText(c) {
    return ((c && c.groups) || []).map(function (g) {
      return (g.rules || []).map(ruleText).join(' <span class="pr-wf-and">y</span> ');
    }).join(' <span class="pr-wf-or">o</span> ');
  }
  function hasConds(c) { return !!(c && c.groups && c.groups.length); }
  function triggerText(t) {
    t = t || {};
    if (t.type === "filter") return conditionsText(t.conditions);
    if (t.type === "manual") return "Sólo cuando alguien la inscribe a mano";
    if (t.type === "event") {
      var base = t.event === "created" ? "Se crea la empresa"
        : "Cambia <strong>" + esc((field(t.field) || {}).label || t.field) + "</strong>" +
          ((t.to_values || []).length ? " a <em>" + (t.to_values || []).map(function (x) { return esc(choiceLabel(field(t.field), x)); }).join(" o ") + "</em>" : "");
      return base + (hasConds(t.conditions) ? " · si " + conditionsText(t.conditions) : "");
    }
    if (t.type === "schedule") {
      var s = t.schedule || {};
      var when = s.kind === "daily" ? "Todos los días" : s.kind === "date" ? "El " + fmtFecha(s.date)
        : (s.days || []).map(function (d) { return (S().weekdays || [])[d]; }).join(", ");
      return when + " a las " + esc(s.time || "—") + (hasConds(t.conditions) ? " · si " + conditionsText(t.conditions) : "");
    }
    return "—";
  }
  function actionText(a) {
    if (!a) return "—";
    var f = field(a.field), label = f ? f.label : a.field;
    switch (a.type) {
      case "clear": return "Borra <strong>" + esc(label) + "</strong>";
      case "set_today": return "Define <strong>" + esc(label) + "</strong> como la fecha en que se ejecutó esta acción";
      case "set_date_offset": return "Define <strong>" + esc(label) + "</strong> como la fecha de ejecución " + (Number(a.days) >= 0 ? "+ " : "− ") + Math.abs(Number(a.days) || 0) + " días";
      case "increment": return (Number(a.amount) >= 0 ? "Suma " : "Resta ") + Math.abs(Number(a.amount) || 0) + " a <strong>" + esc(label) + "</strong>";
      case "copy": return "Copia <strong>" + esc((field(a.from_field) || {}).label || "—") + "</strong> en <strong>" + esc(label) + "</strong>";
      case "set":
        var v = f && (f.type === "enum" || f.type === "owner") ? choiceLabel(f, a.value) : f && f.type === "date" ? fmtFecha(a.value) : a.value;
        return "Define <strong>" + esc(label) + "</strong> como <em>" + esc(v || "—") + "</em>";
      case "rotate_owner": return "Reparte entre " + (a.owners || []).length + " BDRs por turnos";
      case "associate_company": return "Asocia el contacto con la empresa de su dominio de email";
      case "create_todo": return "Crea un To-Do: <em>" + esc(a.text || "—") + "</em>";
      case "send_email": return "Manda un mail: <em>" + esc(a.subject || "—") + "</em>";
      case "send_slack": return "Avisa por Slack: <em>" + esc(a.text || "—") + "</em>";
      case "add_note": return "Agrega una nota";
      case "webhook": return "Manda un webhook";
      case "enroll_workflow": return "Inscribe en otro workflow";
      case "unenroll_workflow": return "Saca de otro workflow";
    }
    return esc(a.type);
  }
  function nodeCount(steps) { return Object.keys((steps && steps.nodes) || {}).length; }

  /* =================================================================
     Lista
     ================================================================= */
  function show() {
    P = window.Prospecting;
    root = $("prWorkflows");
    if (draft) { render(); return; }
    loadList();
  }

  function loadList() {
    root.innerHTML = '<p class="pr-note">Cargando workflows…</p>';
    return P.api("/prospecting/workflows").then(function (r) {
      list = r.workflows;
      canEdit = !!r.can_edit;
      renderList();
    }).catch(function (err) {
      root.innerHTML = '<p class="pr-note">No se pudieron cargar los workflows: ' + esc(err.message) + "</p>";
    });
  }

  function testBanner() {
    if (S().automation_real_data) return "";
    return '<div class="pr-wf-banner"><i class="fa-solid fa-flask"></i><div>' +
      "<strong>Fase de prueba:</strong> los workflows activos corren solos (al editar una empresa, cuando llega de Clay, en su horario) " +
      "<strong>sólo sobre empresas dummy</strong>. Sobre empresas reales corren únicamente cuando alguien los aplica a mano. " +
      "Y sobre una dummy, mails, Slack y To-Dos van siempre a destinos de prueba con [TEST].</div></div>";
  }

  var STATUS_LABEL = {
    active: "En curso", waiting: "Esperando", completed: "Terminadas", unenrolled: "Desinscriptas",
    goal_met: "Cumplieron la meta", failed: "Con error",
  };
  var STATUS_ONE = {
    active: "En curso", waiting: "Esperando", completed: "Terminó", unenrolled: "Desinscripta",
    goal_met: "Cumplió la meta", failed: "Con error",
  };
  function statsChips(stats) {
    var keys = Object.keys(STATUS_LABEL).filter(function (k) { return stats && stats[k]; });
    if (!keys.length) return '<span class="pr-note">Nadie inscripto todavía</span>';
    return keys.map(function (k) {
      return '<span class="pr-wf-stat pr-wf-stat--' + k + '">' + stats[k] + " " + STATUS_LABEL[k].toLowerCase() + "</span>";
    }).join("");
  }

  function renderList() {
    var cards = list.map(function (w) {
      var tt = (S().triggers || {})[w.trigger.type] || {};
      curObj = w.object || "company";
      return '<article class="pr-wf-card' + (w.enabled ? " is-on" : "") + '" data-wf="' + w.id + '" tabindex="0">' +
        '<header class="pr-wf-card__head">' +
          '<h3 class="pr-wf-card__name"><span class="pr-wf-obj pr-wf-obj--' + curObj + '">' +
            (curObj === "contact" ? '<i class="fa-regular fa-user"></i> Contactos' : '<i class="fa-regular fa-building"></i> Empresas') +
            "</span>" + esc(w.name) + "</h3>" +
          (canEdit
            ? '<label class="pr-switch" title="' + (w.enabled ? "Activo" : "Inactivo") + '"><input type="checkbox" data-toggle="' + w.id + '"' + (w.enabled ? " checked" : "") + '><span></span></label>'
            : '<span class="pr-wf-pill' + (w.enabled ? " is-on" : "") + '">' + (w.enabled ? "Activo" : "Inactivo") + "</span>") +
        "</header>" +
        (w.description ? '<p class="pr-wf-card__desc">' + esc(w.description) + "</p>" : "") +
        '<div class="pr-wf-card__rule"><span class="pr-wf-card__tag">Si</span><div><span class="pr-note">' + esc(tt.label || "") + ":</span> " + triggerText(w.trigger) + "</div></div>" +
        '<div class="pr-wf-card__rule"><span class="pr-wf-card__tag pr-wf-card__tag--do">Entonces</span><div>' +
          nodeCount(w.steps) + " paso" + (nodeCount(w.steps) === 1 ? "" : "s") + "</div></div>" +
        '<div class="pr-wf-card__stats">' + statsChips(w.stats) + "</div>" +
        '<footer class="pr-wf-card__foot">' + (w.updated_by ? "Editado por " + esc(P.ownerName(w.updated_by) || w.updated_by) : "") + "</footer>" +
        "</article>";
    }).join("");
    root.innerHTML =
      '<div class="pr-wf-top">' +
        '<div><h2 class="pr-wf-title">Workflows</h2>' +
        '<p class="pr-note" style="margin:0">Reglas que trabajan las empresas solas, como los workflows de HubSpot.' +
        (canEdit ? "" : " Sólo pgonzales, manuela y mia pueden editarlos.") + "</p></div>" +
        (canEdit ? '<button type="button" class="pr-btn pr-btn--primary" id="prWfNew"><i class="fa-solid fa-plus"></i> Crear workflow</button>' : "") +
      "</div>" + testBanner() +
      (list.length ? '<div class="pr-wf-grid">' + cards + "</div>"
        : '<div class="pr-wf-empty">Todavía no hay workflows.' + (canEdit ? " Creá el primero." : "") + "</div>");

    var nb = $("prWfNew");
    if (nb) nb.onclick = function () { askObject().then(function (obj) { if (obj) openEditor(null, obj); }); };
    root.querySelectorAll("[data-toggle]").forEach(function (cb) {
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () {
        var id = Number(cb.getAttribute("data-toggle"));
        var w = list.filter(function (x) { return x.id === id; })[0];
        toggle(w, cb.checked).then(function (ok) { if (!ok) cb.checked = !cb.checked; });
      });
    });
    root.querySelectorAll("[data-wf]").forEach(function (card) {
      var open = function (e) {
        if (e.target.closest(".pr-switch")) return;
        openEditor(list.filter(function (x) { return x.id === Number(card.getAttribute("data-wf")); })[0]);
      };
      card.addEventListener("click", open);
      card.addEventListener("keydown", function (e) { if (e.key === "Enter") open(e); });
    });
  }

  /* Activar: para los de filtro, como HubSpot, se pregunta si entran también las que ya cumplen. */
  function toggle(w, enabled) {
    var go = function (includeExisting) {
      return P.api("/prospecting/workflows/" + w.id + "/toggle", {
        method: "POST", body: JSON.stringify({ enabled: enabled, include_existing: includeExisting }),
      }).then(function (res) {
        var extra = res.activation && res.activation.enrolled ? " Se inscribieron " + res.activation.enrolled + " empresas." : "";
        P.toast('<i class="fa-solid fa-diagram-project"></i> <strong>' + esc(res.name) + "</strong> ahora está " + (res.enabled ? "activo" : "inactivo") + "." + extra);
        list = list.map(function (x) { return x.id === res.id ? Object.assign(x, res) : x; });
        if (draft && draft.id === res.id) { draft.enabled = res.enabled; render(); } else renderList();
        return true;
      }).catch(function (err) { alert(errorText(err)); return false; });
    };
    if (!enabled || w.trigger.type !== "filter") return go(false);
    return P.api("/prospecting/workflows/preview", {
      method: "POST", body: JSON.stringify(Object.assign({ id: w.id }, defnOf(w))),
    }).then(function (pv) {
      return askActivate(pv.affected || 0).then(function (choice) {
        if (choice === null) return false;
        return go(choice);
      });
    }).catch(function (err) { alert(errorText(err)); return false; });
  }

  function askObject() {
    return new Promise(function (resolve) {
      var box = document.createElement("div");
      box.className = "pr-modal";
      box.innerHTML = '<div class="pr-modal__card" role="dialog" aria-modal="true">' +
        "<h3>Nuevo workflow</h3><p>¿Sobre qué corre? No se puede cambiar después.</p>" +
        '<div class="pr-objpick">' +
          '<button type="button" data-o="company"><i class="fa-regular fa-building"></i><strong>Empresas</strong>' +
            '<span>Se inscriben empresas; las condiciones pueden mirar también sus contactos.</span></button>' +
          '<button type="button" data-o="contact"><i class="fa-regular fa-user"></i><strong>Contactos</strong>' +
            '<span>Se inscriben contactos; pueden mirar y editar su empresa asociada.</span></button>' +
        "</div>" +
        '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-o="">Cancelar</button></div></div>';
      document.body.appendChild(box);
      box.addEventListener("click", function (e) {
        var b = e.target.closest("[data-o]");
        if (!b && e.target !== box) return;
        box.remove();
        resolve(b ? b.getAttribute("data-o") || null : null);
      });
    });
  }

  function askActivate(n) {
    return new Promise(function (resolve) {
      var box = document.createElement("div");
      box.className = "pr-modal";
      box.innerHTML = '<div class="pr-modal__card" role="dialog" aria-modal="true">' +
        "<h3>Activar workflow</h3>" +
        "<p>Hoy hay <strong>" + n + "</strong> empresa" + (n === 1 ? "" : "s") + " que ya cumple" + (n === 1 ? "" : "n") + " las condiciones.</p>" +
        '<label class="pr-check"><input type="checkbox" id="prActExisting"> Inscribirlas también ahora</label>' +
        '<p class="pr-note">Si no, sólo entran las que pasen a cumplirlas de acá en adelante (como HubSpot).</p>' +
        '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-x="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-x="ok">Activar</button></div></div>';
      document.body.appendChild(box);
      box.addEventListener("click", function (e) {
        var b = e.target.closest("[data-x]");
        if (!b && e.target !== box) return;
        var choice = b && b.getAttribute("data-x") === "ok" ? $("prActExisting").checked : null;
        box.remove();
        resolve(choice);
      });
    });
  }

  function errorText(err) {
    return err.errors && err.errors.length ? err.errors.join("\n") : err.message;
  }

  /* =================================================================
     Editor — modelo
     ================================================================= */
  function defnOf(w) {
    return {
      name: w.name, description: w.description || "", reenroll: w.reenroll !== false,
      trigger: w.trigger, steps: w.steps, unenroll: w.unenroll || null, goal: w.goal || null,
      settings: w.settings || {}, object: w.object || "company",
    };
  }

  function blankRule() { return { field: defaultField(), op: "is_any", value: [] }; }
  function blankConds() { return { groups: [{ rules: [blankRule()] }] }; }

  function openEditor(w, obj) {
    curObj = w ? (w.object || "company") : (obj || "company");
    draft = w ? Object.assign({ id: w.id, enabled: w.enabled }, clone(defnOf(w))) : {
      id: null, enabled: false, name: "", description: "", reenroll: true, object: curObj,
      trigger: { type: "filter", conditions: blankConds() },
      steps: { start: null, nodes: {} }, unenroll: null, goal: null, settings: {},
    };
    dirty = false;
    tab = "editor";
    openMenu = null;
    historyState = { status: "", rows: [], detail: null };
    testState = { q: "", results: [], company: null, result: null };
    centerNext = true;
    render();
  }

  function closeEditor() {
    if (dirty && !confirm("Tenés cambios sin guardar. ¿Salir igual?")) return;
    draft = null;
    dirty = false;
    loadList();
  }

  function markDirty() {
    dirty = true;
    var s = $("prWfSaveState");
    if (s) s.textContent = "Cambios sin guardar";
  }

  /* Condiciones: cada bloque se identifica con una clave ("trigger", "unenroll", "goal",
     "branch:<id>:<i>", "delay:<id>"). */
  function condRef(key, create) {
    var parts = key.split(":");
    var holder, prop;
    if (key === "trigger") { holder = draft.trigger; prop = "conditions"; }
    else if (key === "unenroll" || key === "goal") { holder = draft; prop = key; }
    else if (parts[0] === "branch") { holder = draft.steps.nodes[parts[1]].branch.paths[Number(parts[2])]; prop = "conditions"; }
    else if (parts[0] === "delay") { holder = draft.steps.nodes[parts[1]].delay; prop = "conditions"; }
    if (!holder) return null;
    if (!hasConds(holder[prop]) && create) holder[prop] = blankConds();
    return { holder: holder, prop: prop, conds: holder[prop] };
  }

  /* Punteros: dónde se engancha un paso nuevo o adónde apunta un "ir a". */
  function getPtr(ptr) {
    if (ptr === "start") return draft.steps.start;
    var p = ptr.split(":"), n = draft.steps.nodes[p[1]];
    if (p[0] === "next") return n.next;
    if (p[0] === "path") return n.branch.paths[Number(p[2])].next;
    if (p[0] === "else") return n.branch.else_next;
  }
  function setPtr(ptr, val) {
    if (ptr === "start") { draft.steps.start = val; return; }
    var p = ptr.split(":"), n = draft.steps.nodes[p[1]];
    if (p[0] === "next") n.next = val;
    else if (p[0] === "path") n.branch.paths[Number(p[2])].next = val;
    else if (p[0] === "else") n.branch.else_next = val;
  }
  function eachPtr(fn) {
    fn("start");
    Object.keys(draft.steps.nodes).forEach(function (id) {
      var n = draft.steps.nodes[id];
      if (n.type === "branch") {
        (n.branch.paths || []).forEach(function (_, i) { fn("path:" + id + ":" + i); });
        if (n.branch.kind !== "random") fn("else:" + id);
      } else fn("next:" + id);
    });
  }
  function targets(n) {
    if (n.type !== "branch") return [n.next];
    var t = (n.branch.paths || []).map(function (p) { return p.next; });
    if (n.branch.kind !== "random") t.push(n.branch.else_next);
    return t;
  }
  function prune() {
    var seen = {}, stack = [draft.steps.start];
    while (stack.length) {
      var id = stack.pop();
      if (!id || seen[id] || !draft.steps.nodes[id]) continue;
      seen[id] = true;
      stack = stack.concat(targets(draft.steps.nodes[id]));
    }
    Object.keys(draft.steps.nodes).forEach(function (id) { if (!seen[id]) delete draft.steps.nodes[id]; });
  }
  /* Numeración en orden de recorrido (la misma que usa el backend en los errores). */
  function numbering() {
    var order = {}, k = 0, stack = [draft.steps.start];
    while (stack.length) {
      var id = stack.pop();
      if (!id || order[id] || !draft.steps.nodes[id]) continue;
      order[id] = ++k;
      stack = stack.concat(targets(draft.steps.nodes[id]).reverse());
    }
    return order;
  }

  function insertNode(ptr, kind, extra) {
    var id = newId(), after = getPtr(ptr);
    var node;
    if (kind === "action") node = { type: "action", action: defaultAction(extra), next: after };
    else if (kind === "delay") node = { type: "delay", delay: { kind: "duration", days: 1 }, next: after };
    else if (kind === "branch") {
      node = { type: "branch", branch: { kind: "value", field: defaultField(),
        paths: [{ values: [], next: null }], else_next: after } };
    }
    draft.steps.nodes[id] = node;
    setPtr(ptr, id);
  }

  function defaultAction(type) {
    var a = { type: type || "set" };
    var meta = (S().actions || {})[a.type] || {};
    if (meta.field) {
      var f = objFields(curObj).filter(function (x) {
        return x.editable && (!meta.types || meta.types.indexOf(x.type) !== -1);
      })[0];
      a.field = f ? f.key : defaultField();
      if (a.type === "set") a.value = "";
      if (a.type === "set_date_offset") a.days = 7;
      if (a.type === "increment") a.amount = 1;
      if (a.type === "copy") a.from_field = "";
    }
    if (a.type === "rotate_owner") { a.owners = bdrChoices().map(function (c) { return c.value; }); a.only_if_empty = true; }
    if (a.type === "create_todo") { a.assignee = "owner"; a.text = "Hacer seguimiento a {empresa}"; a.due_days = 1; }
    if (a.type === "send_email") { a.to = ["owner"]; a.subject = "{empresa}"; a.body = ""; }
    if (a.type === "send_slack") { a.text = "{empresa}: "; a.channel = ""; }
    if (a.type === "add_note") a.text = "";
    if (a.type === "webhook") a.url = "https://";
    if (a.type === "enroll_workflow" || a.type === "unenroll_workflow") a.workflow_id = "";
    return a;
  }

  /* Definir sobre una fecha arranca como «la fecha en que se ejecuta» (lo más común);
     y si la propiedad deja de ser fecha, vuelve a ser un Definir común. */
  function fixDateSet(act) {
    var f = field(act.field);
    var isDate = f && (f.type === "date" || f.type === "datetime");
    if (isDate && act.type === "set" && !act.value) { act.type = "set_today"; delete act.value; }
    if (!isDate && isDateSet(act)) { act.type = "set"; act.value = ""; delete act.days; }
  }

  function deleteNode(id) {
    var n = draft.steps.nodes[id];
    if (n.type === "branch" && !confirm("¿Borrar la rama con todo lo que tiene adentro?")) return false;
    var repl = n.type === "branch" ? null : n.next;
    eachPtr(function (ptr) { if (getPtr(ptr) === id) setPtr(ptr, repl); });
    delete draft.steps.nodes[id];
    prune();
    return true;
  }

  /* =================================================================
     Editor — vista
     ================================================================= */
  /* Cada cambio redibuja el editor entero: se guarda la posición del lienzo (y de la
     página) y se restaura, para no volver al principio en cada click. Al abrir un
     workflow (`centerNext`) arranca centrado en el disparador. */
  var centerNext = false;
  function render() {
    if (!draft) return;
    var cv = root.querySelector(".pr-wf-canvas");
    var keep = cv ? { left: cv.scrollLeft, top: cv.scrollTop } : null;
    var pageTop = root.scrollTop;
    root.innerHTML =
      '<div class="pr-wf-editor">' + topBar() +
        '<div class="pr-wf-errors" id="prWfErrors" hidden></div>' +
        (tab === "editor"
          ? '<div class="pr-wf-body"><div class="pr-wf-canvas">' + canvas() + "</div>" + sidePanel() + "</div>"
          : historyView()) +
      "</div>";
    bind();
    var ncv = root.querySelector(".pr-wf-canvas");
    if (ncv) {
      if (centerNext || !keep) {
        ncv.scrollLeft = Math.max(0, (ncv.scrollWidth - ncv.clientWidth) / 2);
        centerNext = false;
      } else {
        ncv.scrollLeft = keep.left;
        ncv.scrollTop = keep.top;
      }
    }
    root.scrollTop = pageTop;
  }

  function topBar() {
    var d = draft;
    return '<div class="pr-wf-ebar">' +
      '<button type="button" class="pr-btn" data-act="back"><i class="fa-solid fa-arrow-left"></i> Workflows</button>' +
      '<input class="pr-wf-name" id="prWfName" placeholder="Nombre del workflow" value="' + esc(d.name) + '"' + dis() + ">" +
      '<span class="pr-wf-pill' + (d.enabled ? " is-on" : "") + '">' + (d.enabled ? "Activo" : "Inactivo") + "</span>" +
      '<div class="pr-wf-subtabs">' +
        '<button type="button" class="pr-wf-subtab' + (tab === "editor" ? " is-active" : "") + '" data-tab="editor">Editor</button>' +
        (d.id ? '<button type="button" class="pr-wf-subtab' + (tab === "history" ? " is-active" : "") + '" data-tab="history">Historial</button>' : "") +
      "</div>" +
      '<span class="pr-wf-ebar__state" id="prWfSaveState">' + (dirty ? "Cambios sin guardar" : "") + "</span>" +
      (canEdit
        ? (d.id ? '<button type="button" class="pr-btn pr-btn--danger" data-act="delete" title="Borrar"><i class="fa-regular fa-trash-can"></i></button>' : "") +
          '<button type="button" class="pr-btn" data-act="save"><i class="fa-regular fa-floppy-disk"></i> Guardar</button>' +
          (d.id ? '<button type="button" class="pr-btn pr-btn--primary" data-act="toggle">' +
            (d.enabled ? '<i class="fa-solid fa-pause"></i> Desactivar' : '<i class="fa-solid fa-play"></i> Activar') + "</button>" : "")
        : "") +
    "</div>";
  }

  function canvas() {
    var order = numbering();
    var rendered = {};
    // .pr-wf-flow mide lo que mide el dibujo (las ramas lo ensanchan) y el lienzo
    // scrollea en las dos direcciones: centrado sin wrapper, lo que se pasa por la
    // izquierda quedaba cortado y no había forma de llegar.
    return '<div class="pr-wf-flow">' +
      '<textarea class="pr-wf-desc" id="prWfDesc" rows="1" placeholder="Descripción (opcional)"' + dis() + ">" + esc(draft.description) + "</textarea>" +
      triggerCard() + chain("start", draft.steps.start, order, rendered) + extrasCard() + "</div>";
  }

  /* Una cadena de pasos desde un puntero hasta el final (o un "ir a"). */
  function chain(ptr, id, order, rendered) {
    var html = "";
    for (var guard = 0; guard < 200; guard++) {
      html += '<div class="pr-wf-connector"></div>';
      if (!id) {
        return html + plus(ptr, true) + (canEdit ? '<div class="pr-wf-connector"></div>' : "") + '<div class="pr-wf-end">Fin</div>';
      }
      if (rendered[id]) {
        return html + '<div class="pr-wf-goto"><i class="fa-solid fa-turn-up"></i> Ir al paso ' + (order[id] || "?") +
          (canEdit ? ' <button type="button" class="pr-wf-x" data-goto-del="' + ptr + '" title="Quitar «ir a»"><i class="fa-solid fa-xmark"></i></button>' : "") +
          "</div>";
      }
      rendered[id] = true;
      var n = draft.steps.nodes[id];
      html += plus(ptr, false) + (canEdit ? '<div class="pr-wf-connector"></div>' : "");
      if (n.type === "branch") {
        html += branchCard(id, n, order[id]);
        var b = n.branch, cols = "", labels = branchLabels(b);
        (b.paths || []).forEach(function (p, i) {
          cols += '<div class="pr-wf-col"><div class="pr-wf-col__head">' + labels[i] + "</div>" +
            chain("path:" + id + ":" + i, p.next, order, rendered) + "</div>";
        });
        if (b.kind !== "random") {
          cols += '<div class="pr-wf-col"><div class="pr-wf-col__head pr-wf-col__head--else">' + labels[labels.length - 1] + "</div>" +
            chain("else:" + id, b.else_next, order, rendered) + "</div>";
        }
        return html + '<div class="pr-wf-cols">' + cols + "</div>";
      }
      html += n.type === "delay" ? delayCard(id, n, order[id]) : actionCard(id, n, order[id]);
      ptr = "next:" + id;
      id = n.next;
    }
    return html;
  }

  function branchLabels(b) {
    var out = (b.paths || []).map(function (p, i) {
      if (b.kind === "random") return "Rama " + (i + 1) + " · " + (p.pct || 0) + "%";
      if (b.kind === "value") {
        var f = field(b.field);
        return (p.values || []).length ? "Si es " + (p.values || []).map(function (v) { return esc(choiceLabel(f, v)); }).join(" o ") : "Rama " + (i + 1);
      }
      return esc(p.label || "Rama " + (i + 1));
    });
    if (b.kind !== "random") out.push("Si no");
    return out;
  }

  function plus(ptr, isEnd) {
    if (!canEdit) return "";
    var open = openMenu === ptr;
    var menu = "";
    if (open) {
      var acts = S().actions || {}, ag = actionGroups(), groups = ag.groups;
      menu = '<div class="pr-wf-menu" role="menu">' +
        ag.order.map(function (g) {
          return '<div class="pr-wf-menu__group">' + esc(g) + "</div>" +
            groups[g].map(function (k) { return '<button type="button" data-ins="action" data-ins-type="' + k + '">' + esc(acts[k].label) + "</button>"; }).join("");
        }).join("") +
        '<div class="pr-wf-menu__group">Flujo</div>' +
        '<button type="button" data-ins="delay"><i class="fa-regular fa-clock"></i> Esperar</button>' +
        '<button type="button" data-ins="branch"><i class="fa-solid fa-code-branch"></i> Rama (si / si no)</button>' +
        (isEnd ? '<button type="button" data-ins="goto"><i class="fa-solid fa-turn-up"></i> Ir a un paso…</button>' : "") +
        "</div>";
    }
    return '<div class="pr-wf-plus-wrap" data-ptr="' + ptr + '">' +
      '<button type="button" class="pr-wf-plus' + (open ? " is-open" : "") + '" data-plus="' + ptr + '" title="Agregar un paso"><i class="fa-solid fa-plus"></i></button>' +
      menu + "</div>";
  }

  function nodeHead(id, num, icon, title, cls) {
    return '<div class="pr-wf-node__head"><span class="pr-wf-node__icon ' + (cls || "") + '"><i class="' + icon + '"></i></span>' +
      '<span class="pr-wf-node__title">' + num + ". " + title + "</span>" +
      (canEdit ? '<button type="button" class="pr-wf-x" data-del="' + id + '" title="Borrar paso"><i class="fa-solid fa-xmark"></i></button>' : "") +
      "</div>";
  }

  /* ---------- Tarjeta del disparador ---------- */
  function triggerCard() {
    var t = draft.trigger;
    var types = S().triggers || {};
    var body = "";
    if (t.type === "filter") {
      body = '<p class="pr-wf-hint">Inscribir ' + (curObj === "contact" ? "contactos" : "empresas") + ' que cumplan estas condiciones</p>' + conditionsEditor("trigger", t.conditions, false);
    } else if (t.type === "manual") {
      body = '<p class="pr-note">Entran sólo ' + (curObj === "contact" ? "los contactos" : "las empresas") + ' que alguien inscribe: en la tabla, tildándolas → «Inscribir en workflow».</p>';
    } else if (t.type === "event") {
      var evs = S().events || {};
      body = '<div class="pr-wf-row"><select class="pr-filter__input" data-trig="event"' + dis() + ">" +
        optionTags(keysOf("events").map(function (k) { return { value: k, label: evs[k].label }; }), t.event) + "</select></div>";
      if (t.event === "property_changed") {
        var hf = S().history_fields || [];
        var f = field(t.field);
        body += '<div class="pr-wf-row"><span class="pr-wf-lbl">Propiedad</span><select class="pr-filter__input" data-trig="field"' + dis() + ">" +
          fieldOptions(t.field, function (x) { return x.history !== false && (curObj !== "company" || hf.indexOf(x.key) !== -1); }) + "</select></div>";
        if (f && (f.type === "enum" || f.type === "owner")) {
          body += '<div class="pr-wf-row pr-wf-row--top"><span class="pr-wf-lbl">A (opcional)</span>' +
            chips(choices(f), t.to_values || [], 'data-trig-chip="1"') + "</div>";
        }
      }
      body += optionalConds("trigger", t.conditions, "Además, sólo si…");
    } else if (t.type === "schedule") {
      var s = t.schedule || (t.schedule = { kind: "daily", time: "09:00" });
      var sk = S().schedules || {};
      body = '<div class="pr-wf-row"><select class="pr-filter__input" data-sch="kind"' + dis() + ">" +
          optionTags(keysOf("schedules").map(function (k) { return { value: k, label: sk[k].label }; }), s.kind) + "</select>" +
        '<span class="pr-wf-lbl">a las</span><input type="time" class="pr-filter__input pr-wf-time" data-sch="time" value="' + esc(s.time || "09:00") + '"' + dis() + "></div>";
      if (s.kind === "weekly") body += '<div class="pr-wf-row">' + weekdayChips(s.days || [], 'data-sch-day="1"') + "</div>";
      if (s.kind === "date") body += '<div class="pr-wf-row"><input type="date" class="pr-filter__input" data-sch="date" value="' + esc(s.date || "") + '"' + dis() + "></div>";
      body += '<p class="pr-note">Hora Argentina. Inscribe a las empresas que cumplan el filtro (o a todas, si no hay filtro).</p>';
      body += optionalConds("trigger", t.conditions, "Sólo las que cumplan…");
    }
    return '<div class="pr-wf-node pr-wf-node--trigger">' +
      '<div class="pr-wf-node__head"><span class="pr-wf-node__icon pr-wf-node__icon--trigger"><i class="fa-regular fa-flag"></i></span>' +
        '<span class="pr-wf-node__title">Disparador</span>' +
        '<select class="pr-filter__input pr-wf-trigtype" data-trig="type"' + dis() + ">" +
          optionTags(keysOf("triggers").map(function (k) { return { value: k, label: types[k].label }; }), t.type) + "</select>" +
      "</div>" + body +
      (t.type !== "manual"
        ? '<label class="pr-wf-reenroll"><span class="pr-switch pr-switch--sm"><input type="checkbox" data-set="reenroll"' + (draft.reenroll ? " checked" : "") + dis() + "><span></span></span>" +
          "<span><strong>Reinscripción</strong>: " + (curObj === "contact" ? "un contacto" : "una empresa") + " puede volver a entrar " +
          (t.type === "filter" ? "cada vez que vuelva a cumplir las condiciones (después de haber dejado de cumplirlas)." : "cada vez que se dispare.") +
          "</span></label>" : "") +
      "</div>";
  }

  function optionalConds(key, conds, label) {
    if (hasConds(conds)) {
      return '<div class="pr-wf-sub"><div class="pr-wf-sub__head">' + esc(label) +
        (canEdit ? '<button type="button" class="pr-wf-link" data-cond-clear="' + key + '">Quitar</button>' : "") +
        "</div>" + conditionsEditor(key, conds, true) + "</div>";
    }
    return canEdit ? '<button type="button" class="pr-wf-add" data-cond-add="' + key + '"><i class="fa-solid fa-filter"></i> ' + esc(label) + "</button>" : "";
  }

  /* ---------- Editor de condiciones (reusado en todos lados) ---------- */
  function conditionsEditor(key, conds, compact) {
    conds = conds || { groups: [] };
    var groups = (conds.groups || []).map(function (g, gi) {
      var rules = (g.rules || []).map(function (r, ri) {
        var f = field(r.field);
        var ops = ((S().operators_by_type || {})[f ? f.type : "text"] || []).map(function (o) {
          return { value: o, label: opDef(o).label };
        });
        var path = key + "|" + gi + "|" + ri;
        return (ri ? '<div class="pr-wf-joiner">y</div>' : "") +
          '<div class="pr-wf-rule"><div class="pr-wf-rule__row">' +
            '<select class="pr-filter__input" data-rfield="' + path + '"' + dis() + ">" + fieldOptions(r.field, null, true) + "</select>" +
            '<select class="pr-filter__input" data-rop="' + path + '"' + dis() + ">" + optionTags(ops, r.op) + "</select>" +
            (canEdit ? '<button type="button" class="pr-wf-x" data-rdel="' + path + '" title="Quitar condición"><i class="fa-solid fa-xmark"></i></button>' : "") +
          "</div>" + ruleValue(r, path) + "</div>";
      }).join("");
      return (gi ? '<div class="pr-wf-or-sep"><span>o</span></div>' : "") +
        '<div class="pr-wf-group' + (compact ? " pr-wf-group--compact" : "") + '">' +
          '<div class="pr-wf-group__head">Grupo ' + (gi + 1) +
            (canEdit && conds.groups.length > 1 ? '<button type="button" class="pr-wf-link" data-gdel="' + key + "|" + gi + '">Quitar grupo</button>' : "") +
          "</div>" + rules +
          (canEdit ? '<button type="button" class="pr-wf-add" data-radd="' + key + "|" + gi + '"><i class="fa-solid fa-plus"></i> Agregar condición (y)</button>' : "") +
        "</div>";
    }).join("");
    return groups + (canEdit ? '<button type="button" class="pr-wf-add pr-wf-add--group" data-gadd="' + key + '"><i class="fa-solid fa-plus"></i> Agregar grupo (o)</button>' : "");
  }

  function chips(items, selected, attr) {
    if (!items.length) return '<span class="pr-note">No hay valores disponibles.</span>';
    return '<div class="pr-wf-chips">' + items.map(function (c) {
      var on = selected.indexOf(c.value) !== -1;
      return '<button type="button" class="pr-wf-chip' + (on ? " is-on" : "") + '" ' + attr + ' data-chip="' + esc(c.value) + '"' + dis() + ">" +
        (on ? '<i class="fa-solid fa-check"></i> ' : "") + esc(c.label) + "</button>";
    }).join("") + "</div>";
  }
  function weekdayChips(selected, attr) {
    return chips((S().weekdays || []).map(function (n, i) { return { value: i, label: n }; }), selected, attr);
  }

  function ruleValue(r, path) {
    var f = field(r.field);
    var kind = opDef(r.op).value;
    var v = r.value;
    if (!kind) return "";
    if (kind === "list") return chips(choices(f), v || [], 'data-rchip="' + path + '"');
    if (kind === "days") {
      var changed = r.op === "changed_in_last_days" || r.op === "not_changed_in_days";
      return '<div class="pr-wf-days"><input type="number" min="0" step="1" class="pr-filter__input" data-val="' + path + '" value="' + esc(v == null ? "" : v) + '"' + dis() + "><span>" + (changed ? "días (0 = hoy)" : "días") + "</span></div>";
    }
    if (kind === "number_range" || kind === "date_range") {
      var type = kind === "date_range" ? "date" : "number";
      v = Array.isArray(v) ? v : ["", ""];
      return '<div class="pr-wf-range"><input type="' + type + '" class="pr-filter__input" data-val="' + path + '" data-vi="0" value="' + esc(v[0]) + '"' + dis() + ">" +
        '<span>y</span><input type="' + type + '" class="pr-filter__input" data-val="' + path + '" data-vi="1" value="' + esc(v[1]) + '"' + dis() + "></div>";
    }
    var t = kind === "date" ? "date" : kind === "number" ? "number" : "text";
    return '<input type="' + t + '" class="pr-filter__input" data-val="' + path + '" value="' + esc(v == null ? "" : v) + '"' +
      (t === "text" ? ' placeholder="Texto…"' : "") + dis() + ">";
  }

  /* ---------- Tarjeta de acción ----------
     En una propiedad de fecha, «Definir» pregunta QUÉ fecha, como HubSpot: la de
     ejecución (set_today), la de ejecución ± N días (set_date_offset) o una fija (set).
     Por eso esas dos no aparecen como acciones sueltas en el menú. */
  var DATE_MODES = { set_today: "today", set_date_offset: "offset", set: "fixed" };
  function isDateSet(a) { return a.type === "set_today" || a.type === "set_date_offset"; }

  function actionCard(id, n, num) {
    var a = n.action, acts = S().actions || {}, ag = actionGroups(), groups = ag.groups;
    var shown = isDateSet(a) ? "set" : a.type;
    var typeSel = '<select class="pr-filter__input" data-a="type" data-node="' + id + '"' + dis() + ">" +
      ag.order.map(function (g) {
        var keys = groups[g].filter(function (k) { return k !== "set_today" && k !== "set_date_offset"; });
        return '<optgroup label="' + esc(g) + '">' + optionTags(keys.map(function (k) { return { value: k, label: acts[k].label }; }), shown) + "</optgroup>";
      }).join("") + "</select>";
    var meta = acts[shown] || {};
    return '<div class="pr-wf-node pr-wf-node--action">' +
      nodeHead(id, num, "fa-regular fa-pen-to-square", esc(meta.group || "Acción")) +
      '<div class="pr-wf-action">' + typeSel + actionParams(id, a, meta) + "</div>" +
      '<p class="pr-wf-node__sum">' + actionText(a) + "</p>" +
      "</div>";
  }

  function inp(id, key, value, type, extra) {
    return '<input type="' + (type || "text") + '" class="pr-filter__input" data-a="' + key + '" data-node="' + id + '" value="' + esc(value == null ? "" : value) + '"' + (extra || "") + dis() + ">";
  }
  function area(id, key, value, ph) {
    return '<textarea class="pr-filter__input pr-wf-area" rows="3" data-a="' + key + '" data-node="' + id + '" placeholder="' + esc(ph || "") + '"' + dis() + ">" + esc(value || "") + "</textarea>";
  }
  var TOKENS_COMPANY = '<p class="pr-note pr-wf-tokens">Podés usar: {empresa} {dominio} {owner} {status} {semana} {not_icp} {link}</p>';
  var TOKENS_CONTACT = '<p class="pr-note pr-wf-tokens">Podés usar: {contacto} {email_contacto} {empresa} {owner} {status} {link}</p>';
  var TOKENS = TOKENS_COMPANY;

  function actionParams(id, a, meta) {
    TOKENS = curObj === "contact" ? TOKENS_CONTACT : TOKENS_COMPANY;
    var html = "";
    if (meta.field) {
      html += '<select class="pr-filter__input" data-a="field" data-node="' + id + '"' + dis() + ">" +
        fieldOptions(a.field, function (f) { return f.editable && (!meta.types || meta.types.indexOf(f.type) !== -1 || ((a.type === "set_today" || a.type === "set_date_offset") && f.type === "datetime")); }, curObj === "contact") + "</select>";
      var f = field(a.field);
      if (f && (f.type === "date" || f.type === "datetime") && (a.type === "set" || isDateSet(a))) {
        html += '<select class="pr-filter__input" data-a="date_mode" data-node="' + id + '"' + dis() + ">" +
          optionTags([
            { value: "today", label: "La fecha en que se ejecuta esta acción" },
            { value: "offset", label: "La fecha de ejecución ± N días" },
            { value: "fixed", label: "Una fecha fija" },
          ], DATE_MODES[a.type]) + "</select>";
        if (a.type === "set") html += inp(id, "value", f.type === "datetime" ? String(a.value || "").slice(0, 16) : a.value, f.type === "datetime" ? "datetime-local" : "date");
        if (a.type === "set_date_offset") html += '<div class="pr-wf-days">' + inp(id, "days", a.days, "number") + "<span>días (negativo = antes)</span></div>";
        return html;
      }
      if (a.type === "set" && f) {
        if (f.type === "enum" || f.type === "owner" || f.type === "user") {
          html += '<select class="pr-filter__input" data-a="value" data-node="' + id + '"' + dis() + '><option value="">Elegir…</option>' + optionTags(choices(f), a.value) + "</select>";
        } else if (f.type === "bool") {
          html += '<select class="pr-filter__input" data-a="value" data-node="' + id + '"' + dis() + ">" +
            optionTags([{ value: "", label: "Elegir…" }, { value: "true", label: "Sí (marcada)" }, { value: "false", label: "No (desmarcada)" }], a.value === true ? "true" : a.value === false ? "false" : (a.value || "")) + "</select>";
        } else if (f.type === "multi") {
          html += chips(choices(f), Array.isArray(a.value) ? a.value : [], 'data-achip="value" data-node="' + id + '"');
        } else html += inp(id, "value", a.value, f.type === "number" ? "number" : f.type === "longtext" ? "text" : "text");
      }
      if (a.type === "set_date_offset") html += '<div class="pr-wf-days">' + inp(id, "days", a.days, "number") + "<span>días (negativo = antes)</span></div>";
      if (a.type === "increment") html += '<div class="pr-wf-days">' + inp(id, "amount", a.amount, "number") + "<span>(negativo = restar)</span></div>";
      if (a.type === "copy") {
        html += '<div class="pr-wf-full"><span class="pr-wf-lbl">Copiar desde</span><select class="pr-filter__input" data-a="from_field" data-node="' + id + '"' + dis() + '><option value="">Elegir…</option>' +
          fieldOptions(a.from_field, function (x) { return x.key !== a.field; }, true) + "</select></div>";
      }
      return html;
    }
    switch (a.type) {
      case "associate_company":
        return '<p class="pr-note">Busca la empresa cuyo dominio coincide con el del email del contacto y lo asocia a esa. ' +
          "Si ya está asociado (lo normal cuando el BDR lo carga desde la empresa), no cambia nada y lo deja anotado.</p>";
      case "rotate_owner":
        return '<div class="pr-wf-full"><span class="pr-wf-lbl">Entre</span>' + chips(bdrChoices(), a.owners || [], 'data-achip="owners" data-node="' + id + '"') +
          '<label class="pr-check"><input type="checkbox" data-a="only_if_empty" data-node="' + id + '"' + (a.only_if_empty ? " checked" : "") + dis() + "> Sólo si no tiene owner</label></div>";
      case "create_todo":
        return '<div class="pr-wf-full"><span class="pr-wf-lbl">Para</span><select class="pr-filter__input" data-a="assignee" data-node="' + id + '"' + dis() + ">" +
          optionTags([{ value: "owner", label: "El owner de la empresa" }].concat(bdrChoices()), a.assignee || "owner") + "</select>" +
          area(id, "text", a.text, "Qué hay que hacer") +
          '<div class="pr-wf-days"><span>Vence en</span>' + inp(id, "due_days", a.due_days, "number", ' min="0"') + "<span>días</span></div>" + TOKENS + "</div>";
      case "send_email":
        var others = (a.to || []).filter(function (x) { return x !== "owner"; }).join(", ");
        return '<div class="pr-wf-full"><span class="pr-wf-lbl">Para</span>' +
          '<label class="pr-check"><input type="checkbox" data-a="to_owner" data-node="' + id + '"' + ((a.to || []).indexOf("owner") !== -1 ? " checked" : "") + dis() + "> El owner de la empresa</label>" +
          inp(id, "to_others", others, "text", ' placeholder="otros mails @vintti.com, separados por coma"') +
          inp(id, "subject", a.subject, "text", ' placeholder="Asunto"') + area(id, "body", a.body, "Texto del mail") + TOKENS + "</div>";
      case "send_slack":
        return '<div class="pr-wf-full">' + area(id, "text", a.text, "Mensaje") +
          inp(id, "channel", a.channel, "text", ' placeholder="Canal (id C0…). Vacío = el canal por defecto del Hub"') + TOKENS + "</div>";
      case "add_note":
        return '<div class="pr-wf-full">' + area(id, "text", a.text, "Nota para el historial de la empresa") + TOKENS + "</div>";
      case "webhook":
        return '<div class="pr-wf-full">' + inp(id, "url", a.url, "url", ' placeholder="https://…"') +
          '<p class="pr-note">Manda un POST con los datos de la empresa. Sobre empresas dummy se registra y no se manda.</p></div>';
      case "enroll_workflow":
      case "unenroll_workflow":
        var others2 = list.filter(function (w) { return w.id !== draft.id; }).map(function (w) { return { value: w.id, label: w.name }; });
        return '<select class="pr-filter__input" data-a="workflow_id" data-node="' + id + '"' + dis() + '><option value="">Elegir workflow…</option>' + optionTags(others2, a.workflow_id) + "</select>";
    }
    return html;
  }

  /* ---------- Tarjeta de espera ---------- */
  function delayCard(id, n, num) {
    var d = n.delay, kinds = S().delays || {};
    var di = function (key, v, type, ex) {
      return '<input type="' + type + '" class="pr-filter__input" data-d="' + key + '" data-node="' + id + '" value="' + esc(v == null ? "" : v) + '"' + (ex || "") + dis() + ">";
    };
    var body = '<select class="pr-filter__input" data-d="kind" data-node="' + id + '"' + dis() + ">" +
      optionTags(keysOf("delays").map(function (k) { return { value: k, label: kinds[k].label }; }), d.kind) + "</select>";
    if (d.kind === "duration") {
      body += '<div class="pr-wf-dur">' + di("days", d.days, "number", ' min="0"') + "<span>días</span>" +
        di("hours", d.hours, "number", ' min="0"') + "<span>horas</span>" + di("minutes", d.minutes, "number", ' min="0"') + "<span>min</span></div>";
    } else if (d.kind === "until_date") {
      body += '<div class="pr-wf-row">' + di("date", d.date, "date") + "<span>a las</span>" + di("time", d.time || "09:00", "time") + "</div>";
    } else if (d.kind === "until_property") {
      body += '<div class="pr-wf-row"><select class="pr-filter__input" data-d="field" data-node="' + id + '"' + dis() + ">" +
        fieldOptions(d.field, function (f) { return f.type === "date" || f.type === "datetime"; }, true) + "</select></div>" +
        '<div class="pr-wf-row">' + di("offset_days", d.offset_days || 0, "number") + "<span>días (±), a las</span>" + di("time", d.time || "09:00", "time") + "</div>";
    } else if (d.kind === "until_weekday") {
      body += '<div class="pr-wf-row">' + weekdayChips(d.days || [], 'data-dchip="days" data-node="' + id + '"') + "</div>" +
        '<div class="pr-wf-row"><span>a las</span>' + di("time", d.time || "09:00", "time") + "</div>";
    } else if (d.kind === "until_time") {
      body += '<div class="pr-wf-row"><span>Hasta las</span>' + di("time", d.time || "09:00", "time") + "<span>(hoy, o mañana si ya pasó)</span></div>";
    } else if (d.kind === "until_condition") {
      body += '<div class="pr-wf-sub">' + conditionsEditor("delay:" + id, d.conditions, true) + "</div>" +
        '<div class="pr-wf-row"><span>Esperar como máximo</span>' + di("max_days", d.max_days || 7, "number", ' min="1"') + "<span>días; si no se cumple, sigue igual</span></div>";
    }
    return '<div class="pr-wf-node pr-wf-node--delay">' + nodeHead(id, num, "fa-regular fa-clock", "Esperar", "pr-wf-node__icon--delay") +
      '<div class="pr-wf-delay">' + body + "</div></div>";
  }

  /* ---------- Tarjeta de rama ---------- */
  function branchCard(id, n, num) {
    var b = n.branch, kinds = S().branches || {};
    var body = '<select class="pr-filter__input" data-b="kind" data-node="' + id + '"' + dis() + ">" +
      optionTags(keysOf("branches").map(function (k) { return { value: k, label: kinds[k].label }; }), b.kind) + "</select>";
    if (b.kind === "value") {
      var f = field(b.field);
      body += '<select class="pr-filter__input" data-b="field" data-node="' + id + '"' + dis() + ">" +
        fieldOptions(b.field, function (x) { return x.type === "enum" || x.type === "owner" || x.type === "user"; }, true) + "</select>";
      (b.paths || []).forEach(function (p, i) {
        body += '<div class="pr-wf-bpath"><span class="pr-wf-lbl">Rama ' + (i + 1) + "</span>" +
          chips(choices(f), p.values || [], 'data-bchip="' + id + "|" + i + '"') + pathDel(id, i, b) + "</div>";
      });
    } else if (b.kind === "conditions") {
      (b.paths || []).forEach(function (p, i) {
        body += '<div class="pr-wf-bpath pr-wf-bpath--cond"><div class="pr-wf-row"><span class="pr-wf-lbl">Rama ' + (i + 1) + "</span>" +
          '<input class="pr-filter__input" data-blabel="' + id + "|" + i + '" placeholder="Nombre de la rama" value="' + esc(p.label || "") + '"' + dis() + ">" + pathDel(id, i, b) + "</div>" +
          conditionsEditor("branch:" + id + ":" + i, p.conditions, true) + "</div>";
      });
    } else if (b.kind === "random") {
      (b.paths || []).forEach(function (p, i) {
        body += '<div class="pr-wf-bpath"><span class="pr-wf-lbl">Rama ' + (i + 1) + "</span>" +
          '<input type="number" min="1" max="99" class="pr-filter__input pr-wf-pct" data-bpct="' + id + "|" + i + '" value="' + esc(p.pct || "") + '"' + dis() + "><span>%</span>" + pathDel(id, i, b) + "</div>";
      });
      var sum = (b.paths || []).reduce(function (s, p) { return s + (Number(p.pct) || 0); }, 0);
      body += '<p class="pr-note">Suma: ' + sum + "%" + (sum !== 100 ? " — tiene que dar 100%" : "") + "</p>";
    }
    if (canEdit) body += '<button type="button" class="pr-wf-add" data-bpadd="' + id + '"><i class="fa-solid fa-plus"></i> Agregar rama</button>';
    return '<div class="pr-wf-node pr-wf-node--branch">' + nodeHead(id, num, "fa-solid fa-code-branch", "Rama", "pr-wf-node__icon--branch") +
      '<div class="pr-wf-branch">' + body + "</div></div>";
  }
  function pathDel(id, i, b) {
    var min = b.kind === "random" ? 2 : 1;
    return canEdit && (b.paths || []).length > min
      ? '<button type="button" class="pr-wf-x" data-bpdel="' + id + "|" + i + '" title="Quitar rama"><i class="fa-solid fa-xmark"></i></button>' : "";
  }

  /* ---------- Desinscripción, meta, configuración ---------- */
  function extrasCard() {
    var st = draft.settings || (draft.settings = {});
    var w = st.window || null;
    return '<div class="pr-wf-extras">' +
      '<details class="pr-wf-extra"' + (hasConds(draft.unenroll) || st.unenroll_if_not_matching ? " open" : "") + '><summary><i class="fa-solid fa-right-from-bracket"></i> Desinscripción</summary>' +
        '<p class="pr-note">Sacar del workflow a las empresas que cumplan…</p>' + optionalConds("unenroll", draft.unenroll, "Agregar criterio de desinscripción") +
        (draft.trigger.type === "filter"
          ? '<label class="pr-check"><input type="checkbox" data-set="unenroll_if_not_matching"' + (st.unenroll_if_not_matching ? " checked" : "") + dis() + "> Sacarlas también si dejan de cumplir el disparador</label>" : "") +
      "</details>" +
      '<details class="pr-wf-extra"' + (hasConds(draft.goal) ? " open" : "") + '><summary><i class="fa-solid fa-bullseye"></i> Meta</summary>' +
        '<p class="pr-note">Cuando una empresa cumple la meta, sale del workflow y cuenta como «cumplió la meta».</p>' + optionalConds("goal", draft.goal, "Agregar meta") +
      "</details>" +
      '<details class="pr-wf-extra"' + (st.business_days || w ? " open" : "") + '><summary><i class="fa-solid fa-sliders"></i> Cuándo ejecuta las acciones</summary>' +
        '<label class="pr-check"><input type="checkbox" data-set="business_days"' + (st.business_days ? " checked" : "") + dis() + "> Sólo de lunes a viernes</label>" +
        '<label class="pr-check"><input type="checkbox" data-set="window_on"' + (w ? " checked" : "") + dis() + "> Sólo en una franja horaria</label>" +
        (w ? '<div class="pr-wf-row"><span>de</span><input type="time" class="pr-filter__input pr-wf-time" data-win="from" value="' + esc(w.from) + '"' + dis() + ">" +
             '<span>a</span><input type="time" class="pr-filter__input pr-wf-time" data-win="to" value="' + esc(w.to) + '"' + dis() + "><span>(hora Argentina)</span></div>" : "") +
        '<p class="pr-note">Fuera de eso, la empresa espera y sigue en el próximo momento permitido.</p>' +
      "</details>" +
    "</div>";
  }

  /* ---------- Panel lateral: vista previa + prueba ---------- */
  function sidePanel() {
    var res = testState.result;
    var path = res ? '<div class="pr-result"><h4>' + esc(res.company.name) + (res.company.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") + "</h4>" +
      '<p class="pr-note" style="margin:0 0 8px">' + esc(res.trigger_note) + "</p>" +
      '<ul class="pr-wf-path">' + res.path.map(function (p) {
        var ch = p.changes ? '<div class="pr-wf-path__ch">' + Object.keys(p.changes).map(function (k) {
          return esc((field(k) || {}).label || k) + ": " + esc(fmtVal(k, p.changes[k].from)) + " → " + esc(fmtVal(k, p.changes[k].to));
        }).join("<br>") + "</div>" : "";
        return '<li class="pr-wf-path__' + p.kind + '">' + (p.n ? "<strong>" + p.n + ".</strong> " : "") + esc(p.summary) + ch + "</li>";
      }).join("") + "</ul></div>" : "";
    return '<aside class="pr-wf-side">' +
      '<h3 class="pr-section__title">Vista previa</h3>' +
      '<p class="pr-note">Qué ' + (curObj === "contact" ? "contactos" : "empresas") + ' cumplen hoy el disparador, con lo que hay en pantalla (guardado o no). No escribe nada.</p>' +
      '<label class="pr-check"><input type="checkbox" id="prWfOnlyDummy" checked> Sólo dummies</label>' +
      '<button type="button" class="pr-btn pr-btn--primary" data-act="preview"' + (canEdit ? "" : " disabled") + '><i class="fa-solid fa-eye"></i> Vista previa</button>' +
      (canEdit && draft.id ? '<button type="button" class="pr-btn" data-act="apply"><i class="fa-solid fa-play"></i> Inscribir las que cumplen ahora</button>' : "") +
      '<div id="prWfPreviewOut"></div>' +
      '<hr class="pr-wf-hr">' +
      '<h3 class="pr-section__title">Probar con ' + (curObj === "contact" ? "un contacto" : "una empresa") + "</h3>" +
      '<p class="pr-note">Muestra el recorrido entero (ramas, acciones, esperas) para ' + (curObj === "contact" ? "un contacto" : "una empresa") + '. No escribe nada.</p>' +
      '<input class="pr-filter__input pr-filter__input--search" id="prWfTestQ" placeholder="' + (curObj === "contact" ? "Buscar contacto…" : "Buscar empresa…") + '" value="' + esc(testState.q) + '"' + (canEdit ? "" : " disabled") + ">" +
      '<div class="pr-wf-testres" id="prWfTestRes">' + testResults() + "</div>" +
      path +
    "</aside>";
  }
  function testResults() {
    return testState.results.map(function (c) {
      return '<button type="button" class="pr-wf-testco" data-test-co="' + c.id + '">' + esc(c.name) +
        (c.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") + '<span class="pr-note">' + esc(c.prospecting_status || "sin status") + "</span></button>";
    }).join("");
  }
  function fmtVal(k, v) {
    if (v == null || v === "") return "—";
    var f = field(k);
    if (f && (f.type === "owner" || f.type === "user")) return P.ownerName(v) || v;
    if (f && f.type === "date") return fmtFecha(v);
    if (f && f.type === "datetime") return fmtFechaHora(v);
    if (f && f.type === "bool") return v === true || v === "true" ? "Sí" : "No";
    if (Array.isArray(v)) return v.join(", ");
    return v;
  }

  /* ---------- Historial ---------- */
  function historyView() {
    var w = list.filter(function (x) { return x.id === draft.id; })[0] || {};
    var h = historyState;
    var stats = w.stats || {};
    var total = Object.keys(stats).reduce(function (s, x) { return s + stats[x]; }, 0);
    var filters = '<div class="pr-wf-hfilters">' + [""].concat(Object.keys(STATUS_LABEL)).map(function (k) {
      return '<button type="button" class="pr-wf-hf' + (h.status === k ? " is-on" : "") + '" data-hstatus="' + k + '">' +
        (k ? STATUS_LABEL[k] : "Todas") + " <span>" + (k ? stats[k] || 0 : total) + "</span></button>";
    }).join("") + "</div>";
    var rows = h.rows.map(function (e) {
      return '<tr data-enr="' + e.id + '"' + (h.detail && h.detail.id === e.id ? ' class="is-on"' : "") + ">" +
        "<td><strong>" + esc(e.company_name) + "</strong>" + (e.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") + "</td>" +
        '<td><span class="pr-wf-stat pr-wf-stat--' + e.status + '">' + esc(STATUS_ONE[e.status] || e.status) + "</span></td>" +
        '<td class="pr-wf-hlast">' + esc(e.last_step || "—") + "</td>" +
        "<td>" + fmtFechaHora(e.enrolled_at) + "</td>" +
        "<td>" + (e.status === "waiting" ? fmtFechaHora(e.wake_at) : "—") + "</td></tr>";
    }).join("");
    var d = h.detail;
    var detail = d ? '<aside class="pr-wf-hdetail"><h3>' + esc(d.company_name) + "</h3>" +
      '<p class="pr-note">' + esc(STATUS_ONE[d.status] || d.status) + " · inscripta " + fmtFechaHora(d.enrolled_at) + "</p>" +
      '<ol class="pr-wf-log">' + d.log.map(function (l) {
        return '<li class="' + (l.ok ? "" : "is-error") + '"><span class="pr-wf-log__at">' + fmtFechaHora(l.at) + "</span>" + esc(l.summary || l.kind) + "</li>";
      }).join("") + "</ol>" +
      (canEdit && (d.status === "active" || d.status === "waiting")
        ? '<button type="button" class="pr-btn pr-btn--danger" data-unenroll="' + d.company_id + '">Sacar del workflow</button>' : "") +
      "</aside>" : "";
    return '<div class="pr-wf-history">' + filters +
      '<div class="pr-wf-hbody"><div class="pr-wf-htable"><table class="pr-table"><thead><tr><th>Empresa</th><th>Estado</th><th>Último paso</th><th>Inscripta</th><th>Sigue</th></tr></thead><tbody>' +
      (rows || '<tr><td colspan="5" class="pr-empty">Todavía no hay inscripciones.</td></tr>') + "</tbody></table></div>" + detail + "</div></div>";
  }

  function loadHistory() {
    var q = historyState.status ? "?status=" + encodeURIComponent(historyState.status) : "";
    return Promise.all([
      P.api("/prospecting/workflows/" + draft.id + "/enrollments" + q),
      P.api("/prospecting/workflows"),
    ]).then(function (r) {
      historyState.rows = r[0].enrollments;
      list = r[1].workflows;
      render();
    }).catch(function (err) { showErrors(err); });
  }

  /* =================================================================
     Eventos
     ================================================================= */
  function ruleAt(path) {
    var p = path.split("|");
    var ref = condRef(p[0], false);
    return { ref: ref, rule: ref.conds.groups[Number(p[1])].rules[Number(p[2])] };
  }
  function resetValue(r) {
    var kind = opDef(r.op).value;
    r.value = kind === "list" ? [] : (kind === "number_range" || kind === "date_range") ? ["", ""] : "";
  }
  function toggleIn(arr, v) {
    var i = arr.indexOf(v);
    if (i === -1) arr.push(v); else arr.splice(i, 1);
    return arr;
  }

  function bind() {
    var body = root.querySelector(".pr-wf-editor");
    body.addEventListener("click", onClick);
    body.addEventListener("change", onChange);
    body.addEventListener("input", onInput);
    var tq = $("prWfTestQ");
    if (tq) {
      var t = null;
      tq.addEventListener("input", function () {
        testState.q = tq.value;
        clearTimeout(t);
        t = setTimeout(searchCompanies, 250);
      });
    }
  }

  function searchCompanies() {
    var q = testState.q.trim();
    if (!q) { testState.results = []; $("prWfTestRes").innerHTML = ""; return; }
    var path = curObj === "contact" ? "/prospecting/contacts" : "/prospecting/companies";
    P.api(path + "?dummy=include&page_size=10&q=" + encodeURIComponent(q)).then(function (r) {
      testState.results = r.rows.map(function (x) {
        return curObj === "contact"
          ? { id: x.id, name: x.name + " · " + (x.company_name || ""), is_dummy: x.is_dummy, prospecting_status: x.lead_life }
          : x;
      });
      var box = $("prWfTestRes");
      if (box) box.innerHTML = testResults();
    });
  }

  /* Texto / números / fechas: se guardan sin redibujar (no perder el foco). */
  function onInput(e) {
    var el = e.target, a;
    if (el.id === "prWfName") { draft.name = el.value; markDirty(); return; }
    if (el.id === "prWfDesc") { draft.description = el.value; markDirty(); return; }
    if ((a = el.getAttribute("data-val"))) {
      var r = ruleAt(a).rule, vi = el.getAttribute("data-vi");
      if (vi !== null) { r.value = Array.isArray(r.value) ? r.value : ["", ""]; r.value[Number(vi)] = el.value; }
      else r.value = el.value;
      markDirty();
      return;
    }
    if (el.tagName !== "SELECT" && el.type !== "checkbox" && (a = el.getAttribute("data-a"))) {
      setActionParam(draft.steps.nodes[el.getAttribute("data-node")].action, a, el.value);
      markDirty();
      return;
    }
    if (el.tagName === "INPUT" && (a = el.getAttribute("data-d")) && a !== "kind") {
      draft.steps.nodes[el.getAttribute("data-node")].delay[a] = el.value;
      markDirty();
      return;
    }
    if ((a = el.getAttribute("data-blabel"))) {
      var p = a.split("|");
      draft.steps.nodes[p[0]].branch.paths[Number(p[1])].label = el.value;
      markDirty();
      return;
    }
    if ((a = el.getAttribute("data-win"))) { draft.settings.window[a] = el.value; markDirty(); return; }
    if ((a = el.getAttribute("data-sch")) && el.tagName === "INPUT") { draft.trigger.schedule[a] = el.value; markDirty(); }
  }

  function setActionParam(act, key, value) {
    if (key === "to_others") {
      var owner = (act.to || []).indexOf("owner") !== -1 ? ["owner"] : [];
      act.to = owner.concat(value.split(/[,\s;]+/).map(function (x) { return x.trim().toLowerCase(); }).filter(Boolean));
    } else act[key] = value;
  }

  /* Selects y checkboxes: cambian la forma de la tarjeta → redibujar. */
  function onChange(e) {
    var el = e.target, a, n;
    if (el.tagName === "INPUT" && el.type !== "checkbox" && !el.hasAttribute("data-bpct")) return; // ya lo tomó onInput
    if (el.tagName === "TEXTAREA" || el.id === "prWfOnlyDummy") return;
    if ((a = el.getAttribute("data-rfield"))) {
      var x = ruleAt(a);
      x.rule.field = el.value;
      x.rule.op = ((S().operators_by_type || {})[field(el.value).type] || [])[0];
      resetValue(x.rule);
    } else if ((a = el.getAttribute("data-rop"))) {
      var y = ruleAt(a), before = opDef(y.rule.op).value;
      y.rule.op = el.value;
      if (opDef(el.value).value !== before) resetValue(y.rule);
    } else if ((a = el.getAttribute("data-trig"))) {
      var t = draft.trigger;
      if (a === "type") {
        var conds = t.conditions;
        draft.trigger = { type: el.value };
        if (el.value === "filter") draft.trigger.conditions = hasConds(conds) ? conds : blankConds();
        if (el.value === "event") { draft.trigger.event = "property_changed"; draft.trigger.field = defaultField(); draft.trigger.to_values = []; }
        if (el.value === "schedule") draft.trigger.schedule = { kind: "daily", time: "09:00" };
      } else if (a === "event") { t.event = el.value; if (el.value === "property_changed" && !t.field) t.field = defaultField(); }
      else if (a === "field") { t.field = el.value; t.to_values = []; }
    } else if ((a = el.getAttribute("data-sch"))) {
      draft.trigger.schedule[a] = el.value;
      if (a === "kind" && el.value === "weekly" && !draft.trigger.schedule.days) draft.trigger.schedule.days = [0];
    } else if ((a = el.getAttribute("data-set"))) {
      if (a === "reenroll") draft.reenroll = el.checked;
      else if (a === "window_on") draft.settings.window = el.checked ? { from: "09:00", to: "18:00" } : null;
      else draft.settings[a] = el.checked;
    } else if ((a = el.getAttribute("data-a"))) {
      n = draft.steps.nodes[el.getAttribute("data-node")];
      if (a === "type") {
        n.action = defaultAction(el.value);
        fixDateSet(n.action);
      } else if (a === "field") {
        n.action.field = el.value;
        if (n.action.type === "set") n.action.value = "";
        fixDateSet(n.action);
      } else if (a === "date_mode") {
        n.action.type = { today: "set_today", offset: "set_date_offset", fixed: "set" }[el.value];
        if (el.value === "offset" && n.action.days == null) n.action.days = 7;
        if (el.value === "fixed") n.action.value = ""; else delete n.action.value;
      }
      else if (a === "to_owner") {
        n.action.to = (n.action.to || []).filter(function (v) { return v !== "owner"; });
        if (el.checked) n.action.to.unshift("owner");
      } else if (el.type === "checkbox") n.action[a] = el.checked;
      else setActionParam(n.action, a, el.value);
    } else if ((a = el.getAttribute("data-d"))) {
      n = draft.steps.nodes[el.getAttribute("data-node")];
      if (a === "kind") {
        var defaults = { duration: { days: 1 }, until_date: { date: "", time: "09:00" },
          until_property: { field: curObj === "contact" ? "follow_up_date" : "prospecting_start_date", offset_days: 0, time: "09:00" },
          until_weekday: { days: [0], time: "09:00" }, until_time: { time: "09:00" },
          until_condition: { conditions: blankConds(), max_days: 7 } };
        n.delay = Object.assign({ kind: el.value }, defaults[el.value] || {});
      } else n.delay[a] = el.value;
    } else if ((a = el.getAttribute("data-b"))) {
      n = draft.steps.nodes[el.getAttribute("data-node")];
      if (a === "kind") {
        var keep = n.branch.paths.map(function (p) { return p.next; });
        var els = n.branch.else_next || null;
        if (el.value === "random") n.branch = { kind: "random", paths: [{ pct: 50, next: keep[0] || null }, { pct: 50, next: keep[1] || els }] };
        else if (el.value === "conditions") n.branch = { kind: "conditions", paths: keep.map(function (nx, i) { return { label: "Rama " + (i + 1), conditions: blankConds(), next: nx }; }), else_next: els };
        else n.branch = { kind: "value", field: defaultField(), paths: keep.map(function (nx) { return { values: [], next: nx }; }), else_next: els };
        prune();
      } else if (a === "field") {
        n.branch.field = el.value;
        n.branch.paths.forEach(function (p) { p.values = []; });
      }
    } else if ((a = el.getAttribute("data-bpct"))) {
      var q = a.split("|");
      draft.steps.nodes[q[0]].branch.paths[Number(q[1])].pct = Number(el.value);
    } else return;
    markDirty();
    render();
  }

  function onClick(e) {
    var b = e.target.closest("button");
    if (!b) {
      var tr = e.target.closest("[data-enr]");
      if (tr) return openEnrollment(Number(tr.getAttribute("data-enr")));
      if (openMenu && !e.target.closest(".pr-wf-menu")) { openMenu = null; render(); }
      return;
    }
    var v, p, ref;
    var act = b.getAttribute("data-act");
    if (act === "back") return closeEditor();
    if (act === "save") return save().catch(function () {});
    if (act === "delete") return remove();
    if (act === "toggle") return saveThen(function () { return toggle(draft, !draft.enabled); });
    if (act === "preview") return preview();
    if (act === "apply") return applyNow();
    if ((v = b.getAttribute("data-tab")) !== null) {
      tab = v;
      if (v === "history") { historyState.detail = null; return loadHistory(); }
      return render();
    }
    if ((v = b.getAttribute("data-hstatus")) !== null) { historyState.status = v; historyState.detail = null; return loadHistory(); }
    if ((v = b.getAttribute("data-unenroll")) !== null) return unenroll(Number(v));
    if ((v = b.getAttribute("data-test-co")) !== null) return runTest(Number(v));
    if ((v = b.getAttribute("data-plus")) !== null) { openMenu = openMenu === v ? null : v; return render(); }
    if ((v = b.getAttribute("data-ins")) !== null) {
      var ptr = b.closest("[data-ptr]").getAttribute("data-ptr");
      openMenu = null;
      if (v === "goto") return chooseGoto(ptr);
      insertNode(ptr, v, b.getAttribute("data-ins-type"));
    } else if ((v = b.getAttribute("data-del")) !== null) {
      if (!deleteNode(v)) return;
    } else if ((v = b.getAttribute("data-goto-del")) !== null) {
      setPtr(v, null);
    } else if ((v = b.getAttribute("data-rchip")) !== null) {
      var x = ruleAt(v);
      x.rule.value = toggleIn(Array.isArray(x.rule.value) ? x.rule.value : [], b.getAttribute("data-chip"));
    } else if (b.getAttribute("data-trig-chip") !== null) {
      draft.trigger.to_values = toggleIn(draft.trigger.to_values || [], b.getAttribute("data-chip"));
    } else if (b.getAttribute("data-sch-day") !== null) {
      draft.trigger.schedule.days = toggleIn(draft.trigger.schedule.days || [], Number(b.getAttribute("data-chip")));
    } else if (b.getAttribute("data-achip") !== null) {
      var an = draft.steps.nodes[b.getAttribute("data-node")].action;
      var akey = b.getAttribute("data-achip");
      an[akey] = toggleIn(Array.isArray(an[akey]) ? an[akey] : [], b.getAttribute("data-chip"));
    } else if (b.getAttribute("data-dchip") !== null) {
      var dn = draft.steps.nodes[b.getAttribute("data-node")].delay;
      dn.days = toggleIn(dn.days || [], Number(b.getAttribute("data-chip")));
    } else if ((v = b.getAttribute("data-bchip")) !== null) {
      p = v.split("|");
      var path = draft.steps.nodes[p[0]].branch.paths[Number(p[1])];
      path.values = toggleIn(path.values || [], b.getAttribute("data-chip"));
    } else if ((v = b.getAttribute("data-bpadd")) !== null) {
      var br = draft.steps.nodes[v].branch;
      if (br.kind === "random") br.paths.push({ pct: 0, next: null });
      else if (br.kind === "conditions") br.paths.push({ label: "Rama " + (br.paths.length + 1), conditions: blankConds(), next: null });
      else br.paths.push({ values: [], next: null });
    } else if ((v = b.getAttribute("data-bpdel")) !== null) {
      p = v.split("|");
      draft.steps.nodes[p[0]].branch.paths.splice(Number(p[1]), 1);
      prune();
    } else if ((v = b.getAttribute("data-radd")) !== null) {
      p = v.split("|");
      condRef(p[0], true).conds.groups[Number(p[1])].rules.push(blankRule());
    } else if ((v = b.getAttribute("data-rdel")) !== null) {
      p = v.split("|");
      ref = condRef(p[0], false);
      var g = ref.conds.groups[Number(p[1])];
      g.rules.splice(Number(p[2]), 1);
      if (!g.rules.length) ref.conds.groups.splice(Number(p[1]), 1);
      if (!ref.conds.groups.length) {
        if (p[0] === "trigger" && draft.trigger.type === "filter") ref.conds.groups.push({ rules: [blankRule()] });
        else ref.holder[ref.prop] = null;
      }
    } else if ((v = b.getAttribute("data-gdel")) !== null) {
      p = v.split("|");
      condRef(p[0], false).conds.groups.splice(Number(p[1]), 1);
    } else if ((v = b.getAttribute("data-gadd")) !== null) {
      ref = condRef(v, false);
      if (!ref || !hasConds(ref.conds)) condRef(v, true);
      else ref.conds.groups.push({ rules: [blankRule()] });
    } else if ((v = b.getAttribute("data-cond-add")) !== null) {
      condRef(v, true);
    } else if ((v = b.getAttribute("data-cond-clear")) !== null) {
      ref = condRef(v, false);
      ref.holder[ref.prop] = null;
    } else return;
    markDirty();
    render();
  }

  function chooseGoto(ptr) {
    var order = numbering();
    var ids = Object.keys(order).sort(function (x, y) { return order[x] - order[y]; });
    if (!ids.length) { alert("Todavía no hay pasos a los que ir."); return render(); }
    var labels = ids.map(function (id) {
      var n = draft.steps.nodes[id];
      var what = n.type === "action" ? actionText(n.action).replace(/<[^>]+>/g, "") : n.type === "delay" ? "Esperar" : "Rama";
      return order[id] + ". " + what;
    });
    var pick = prompt("¿A qué paso va? Escribí el número:\n\n" + labels.join("\n"));
    if (pick === null) return render();
    var target = ids.filter(function (id) { return String(order[id]) === String(pick).trim(); })[0];
    if (!target) { alert("No hay un paso con ese número."); return render(); }
    setPtr(ptr, target);
    markDirty();
    render();
  }

  /* =================================================================
     Acciones del editor
     ================================================================= */
  function showErrors(err) {
    var box = $("prWfErrors");
    if (!box) return;
    if (!err) { box.hidden = true; box.innerHTML = ""; return; }
    var items = err.errors && err.errors.length ? err.errors : [err.message];
    box.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i><ul>' +
      items.map(function (x) { return "<li>" + esc(x) + "</li>"; }).join("") + "</ul>";
    box.hidden = false;
    box.scrollIntoView({ block: "nearest" });
  }

  function payload() { return defnOf(draft); }

  function save() {
    showErrors(null);
    var isNew = !draft.id;
    return P.api(isNew ? "/prospecting/workflows" : "/prospecting/workflows/" + draft.id, {
      method: isNew ? "POST" : "PUT", body: JSON.stringify(payload()),
    }).then(function (w) {
      draft.id = w.id;
      draft.enabled = w.enabled;
      draft.steps = w.steps;
      dirty = false;
      var i = list.findIndex(function (x) { return x.id === w.id; });
      if (i === -1) list.push(w); else list[i] = Object.assign(list[i], w);
      P.toast('<i class="fa-regular fa-floppy-disk"></i> <strong>' + esc(w.name) + "</strong> guardado." +
        (isNew ? " Arranca inactivo: activalo cuando la prueba se vea bien." : ""));
      render();
      return w;
    }).catch(function (err) { showErrors(err); throw err; });
  }

  function saveThen(fn) {
    var p = dirty || !draft.id ? save() : Promise.resolve();
    p.then(fn).catch(function () {});
  }

  function remove() {
    if (!confirm("¿Borrar el workflow «" + draft.name + "»? Las empresas que ya cambió quedan como están.")) return;
    P.api("/prospecting/workflows/" + draft.id, { method: "DELETE" }).then(function () {
      P.toast("Workflow borrado.");
      draft = null;
      dirty = false;
      loadList();
    }).catch(function (err) { alert(err.message); });
  }

  function preview() {
    showErrors(null);
    var out = $("prWfPreviewOut");
    out.innerHTML = '<p class="pr-note">Calculando…</p>';
    P.api("/prospecting/workflows/preview", {
      method: "POST", body: JSON.stringify(Object.assign(payload(), { id: draft.id, only_dummy: $("prWfOnlyDummy").checked })),
    }).then(function (r) {
      if (r.affected === null) { out.innerHTML = '<div class="pr-result">' + esc(r.note) + "</div>"; return; }
      out.innerHTML = '<div class="pr-result"><h4>' + r.affected + " empresa" + (r.affected === 1 ? " cumple" : "s cumplen") + " hoy</h4>" +
        (r.items.length ? "<ul>" + r.items.map(function (c) {
          return "<li><strong>" + esc(c.name) + "</strong>" + (c.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") +
            (c.already_in ? ' <span class="pr-note">· ya está adentro</span>' : "") + "</li>";
        }).join("") + "</ul>" : '<p class="pr-note" style="margin:0">Ninguna por ahora.</p>') + "</div>";
    }).catch(function (err) { out.innerHTML = ""; showErrors(err); });
  }

  function applyNow() {
    var onlyDummy = $("prWfOnlyDummy").checked;
    if (!onlyDummy && !confirm("¿Inscribir también empresas REALES que cumplen hoy?")) return;
    saveThen(function () {
      var out = $("prWfPreviewOut");
      if (out) out.innerHTML = '<p class="pr-note">Inscribiendo…</p>';
      return P.api("/prospecting/workflows/" + draft.id + "/enroll", {
        method: "POST", body: JSON.stringify({ only_dummy: onlyDummy }),
      }).then(function (r) {
        $("prWfPreviewOut").innerHTML = '<div class="pr-result"><h4>' + r.enrolled + " inscripta" + (r.enrolled === 1 ? "" : "s") + "</h4>" +
          '<p class="pr-note" style="margin:0">De ' + r.candidates + " que cumplían (las que ya estaban adentro no se repiten). " +
          (r.completed || 0) + " ya terminaron el workflow; el resto está esperando. Mirá el Historial.</p></div>";
        P.reloadTable();
      }).catch(function (err) { showErrors(err); });
    });
  }

  function runTest(companyId) {
    showErrors(null);
    P.api("/prospecting/workflows/test", {
      method: "POST", body: JSON.stringify(Object.assign(payload(), { id: draft.id, record_id: companyId })),
    }).then(function (r) {
      testState.result = r;
      testState.results = [];
      render();
    }).catch(function (err) { showErrors(err); });
  }

  function openEnrollment(id) {
    P.api("/prospecting/workflows/enrollments/" + id).then(function (d) {
      historyState.detail = d;
      render();
    }).catch(function (err) { showErrors(err); });
  }

  function unenroll(companyId) {
    if (!confirm("¿Sacar esta empresa del workflow?")) return;
    P.api("/prospecting/workflows/" + draft.id + "/unenroll", {
      method: "POST", body: JSON.stringify({ company_ids: [companyId] }),
    }).then(function () {
      historyState.detail = null;
      loadHistory();
    }).catch(function (err) { showErrors(err); });
  }

  /* Para prospecting.js: inscripción manual desde la tabla. */
  function enrollCompanies(wfId, ids) {
    P = P || window.Prospecting;
    return P.api("/prospecting/workflows/" + wfId + "/enroll", {
      method: "POST", body: JSON.stringify({ company_ids: ids }),
    });
  }
  function workflows() {
    P = P || window.Prospecting;
    return P.api("/prospecting/workflows").then(function (r) { list = r.workflows; canEdit = !!r.can_edit; return r; });
  }

  window.ProspectingWorkflows = { show: show, enrollCompanies: enrollCompanies, workflows: workflows };
})();
