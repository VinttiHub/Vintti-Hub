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

   Editan: pgonzales, manuela, mia y bahia. El resto, sólo lectura.
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
  var openMenu = null;   // "+" con el panel «Elegir una acción» abierto (su puntero)
  var pickerView = "home"; // home | delay | branch (2ª pantalla del panel)
  var picked = {};       // pasos tildados en el lienzo (id → true), para duplicar o copiar
  var justPasted = {};   // pasos recién pegados: se resaltan en el próximo dibujo
  var draftUid = "";     // identifica la edición abierta (un workflow nuevo no tiene id)
  var historyState = { status: "", rows: [], detail: null };
  var testState = { q: "", results: [], company: null, result: null };
  /* Objeto del workflow que se está mirando: "company" | "contact". Decide qué
     propiedades se ofrecen y qué significa `company.<key>` / `contact.<key>`. */
  var curObj = "company";
  var CROSS = { company: "contact", contact: "company" };
  var CROSS_PREFIX_LABEL = { company: "Empresa · ", contact: "Algún contacto · ", deal: "Algún negocio · " };
  /* Objetos asociados que puede mirar una CONDICIÓN (`deal.x` = «tiene algún negocio que…»).
     Las acciones y los textos sólo usan CROSS. Igual que objects.CROSS_TARGETS. */
  var CROSS_TARGETS = { company: ["contact", "deal"], contact: ["company", "deal"] };

  function $(id) { return document.getElementById(id); }
  function esc(v) { return P.esc(v); }
  function S() { return P.options().workflow_schema || {}; }
  function objFields(obj) {
    if (obj === "deal") return S().deal_fields || [];
    var o = (S().objects || {})[obj];
    return o ? o.fields : (obj === "company" ? (S().fields || []) : []);
  }
  /* Campo por clave, en el objeto actual. `company.x` / `contact.x` = objeto asociado. */
  function field(key) {
    if (!key) return null;
    var i = String(key).indexOf(".");
    if (i !== -1) {
      var pre = key.slice(0, i), k = key.slice(i + 1);
      if ((CROSS_TARGETS[curObj] || []).indexOf(pre) === -1) return null;
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
      if (acts[k].hidden) return;
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
    return (f.options || []).map(function (o) { return o && typeof o === "object" ? o : { value: o, label: o }; });
  }
  function choiceLabel(f, v) {
    var hit = choices(f).filter(function (c) { return c.value === v; })[0];
    return hit ? hit.label : v;
  }
  function periodLabel(k) {
    var hit = (S().periods || []).filter(function (p) { return p.value === k; })[0];
    return hit ? hit.label : (k || "");
  }
  /* «Otra propiedad» (gt_field / lt_field / updated_*_field): siempre del mismo objeto
     que la regla. En una regla cruzada (`company.x`) el valor es la clave sin prefijo. */
  function otherFields(f, op) {
    if (!f) return [];
    var obj = f.cross || curObj, bare = f.cross ? f.key.slice(f.cross.length + 1) : f.key;
    var numeric = op === "gt_field" || op === "lt_field";
    return objFields(obj).filter(function (x) {
      return x.key !== bare && (numeric ? x.type === "number" : x.history !== false);
    });
  }
  function otherField(f, key) {
    if (!f) return null;
    return objFields(f.cross || curObj).filter(function (x) { return x.key === key; })[0] || null;
  }
  function optionTags(items, selected) {
    return items.map(function (o) {
      return '<option value="' + esc(o.value) + '"' + (String(o.value) === String(selected) ? " selected" : "") + ">" + esc(o.label) + "</option>";
    }).join("");
  }
  /* Opciones de propiedad: las del objeto y, con `cross`, las del objeto asociado
     (en un <optgroup> aparte). En un workflow de contacto, "Empresa · X" es la
     empresa del contacto; en uno de empresa, "Algún contacto · X". */
  function fieldOptions(selected, filterFn, cross, withDeals) {
    var ok = filterFn || function () { return true; };
    var own = objFields(curObj).filter(ok).map(function (f) { return { value: f.key, label: f.label }; });
    var objs = S().objects || {};
    if (!cross || !objs[curObj]) return optionTags(own, selected);
    var other = CROSS[curObj];
    var theirs = objFields(other).filter(ok).map(function (f) { return { value: other + "." + f.key, label: CROSS_PREFIX_LABEL[other] + f.label }; });
    var deals = withDeals ? objFields("deal").filter(ok).map(function (f) { return { value: "deal." + f.key, label: CROSS_PREFIX_LABEL.deal + f.label }; }) : [];
    return '<optgroup label="' + esc(curObj === "contact" ? "Contacto" : "Empresa") + '">' + optionTags(own, selected) + "</optgroup>" +
      (theirs.length ? '<optgroup label="' + esc(curObj === "contact" ? "Empresa asociada" : "Algún contacto de la empresa") + '">' + optionTags(theirs, selected) + "</optgroup>" : "") +
      (deals.length ? '<optgroup label="Algún negocio asociado">' + optionTags(deals, selected) + "</optgroup>" : "");
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
    if (od.value === "list") t = (Array.isArray(v) ? v : [v]).map(function (x) { return "<em>" + esc(choiceLabel(f, x)) + "</em>"; }).join(" o ");
    else if (od.value === "period") t = "<em>" + esc(periodLabel(v)).toLowerCase() + "</em>";
    else if (od.value === "field") { var of = otherField(f, v); t = "<em>" + esc(of ? of.label : v) + "</em>"; }
    else if (od.value === "days") t = "<em>" + esc(v) + " días</em>";
    else if (od.value === "date") t = "<em>" + fmtFecha(v) + "</em>";
    else if (od.value === "number_range") t = "<em>" + esc((v || [])[0]) + " y " + esc((v || [])[1]) + "</em>";
    else if (od.value === "date_range") t = "<em>" + fmtFecha((v || [])[0]) + " y " + fmtFecha((v || [])[1]) + "</em>";
    else if (od.value) t = "<em>" + esc(v) + "</em>";
    // Los nombres del doc van con mayúscula en el menú; dentro de la frase, en minúscula.
    var opLabel = od.label.charAt(0).toLowerCase() + od.label.slice(1);
    return "<strong>" + esc(f.label) + "</strong> " + esc(opLabel) + (t ? " " + t : "");
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
      case "send_slack": return "Avisa por Slack" + (a.mention_field ? " mencionando a <strong>" + esc((field(a.mention_field) || {}).label || a.mention_field) + "</strong>" : "") + ": <em>" + esc(a.text || "—") + "</em>";
      case "add_note": return "Agrega una nota";
      case "webhook": return "Manda un webhook";
      case "enroll_workflow": return "Inscribe en otro workflow";
      case "unenroll_workflow": return "Saca de otro workflow";
      case "format_phone": return "Valida y formatea <strong>" + esc(label) + "</strong> al formato internacional";
      case "ask_ai": return "Pregunta a la IA y guarda la respuesta en <strong>" + esc(a.field === "__note__" ? "una nota" : label) + "</strong>";
      case "create_contact": return "Crea un contacto asociado a la empresa";
      case "create_deal":
        var sf = objFields("deal").filter(function (x) { return x.key === "stage"; })[0];
        return "Crea un negocio en <strong>" + esc(choiceLabel(sf, (a.pipeline_key || "") + ":" + (a.stage_key || "")) || "—") + "</strong>" +
          (a.owner_email ? " y lo asigna a <strong>" + esc(choiceLabel({ type: "user" }, a.owner_email)) + "</strong>" : "") +
          ": <em>" + esc(a.name || "—") + "</em>";
      case "sheets_append": return "Agrega una fila a <strong>" + esc(a.sheet || "—") + "</strong> (" + (a.columns || []).length + " columnas)";
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
      folders = r.folders || [];
      canEdit = !!r.can_edit;
      renderList();
    }).catch(function (err) {
      root.innerHTML = '<p class="pr-note">No se pudieron cargar los workflows: ' + esc(err.message) + "</p>";
    });
  }

  function testBanner() {
    if (S().automation_real_data) return "";
    return '<div class="pr-wf-banner pr-wf-banner--slim"><i class="fa-solid fa-flask"></i><div>' +
      "<strong>Fase de prueba:</strong> lo automático corre sólo sobre <strong>dummies</strong>; mails, Slack y To-Dos van a destinos de prueba con [TEST]." +
      "</div></div>";
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

  /* Vista de la lista: tabla (por defecto) o tarjetas. Se recuerda por navegador. */
  var LIST_VIEW_KEY = "pr_wf_list_view";
  var listView = (function () { try { return localStorage.getItem(LIST_VIEW_KEY) || "table"; } catch (e) { return "table"; } })();
  var listFilter = "all";

  /* Carpetas (anidadas). curFolder = la abierta (null = raíz), recordada por navegador. */
  var FOLDER_KEY = "pr_wf_folder";
  var folders = [];
  var curFolder = (function () { try { var v = localStorage.getItem(FOLDER_KEY); return v ? Number(v) : null; } catch (e) { return null; } })();
  var listQ = "";
  var selected = {};
  function setFolder(id) {
    curFolder = id == null ? null : Number(id);
    selected = {};
    try { if (curFolder == null) localStorage.removeItem(FOLDER_KEY); else localStorage.setItem(FOLDER_KEY, String(curFolder)); } catch (e) {}
  }
  function folderById(id) { return folders.filter(function (f) { return f.id === id; })[0] || null; }
  function childFolders(id) {
    return folders.filter(function (f) { return (f.parent_id == null ? null : f.parent_id) === id; })
      .sort(function (a, b) { return a.name.localeCompare(b.name, "es"); });
  }
  function folderPath(id) {
    var out = [], guard = 0, f = folderById(id);
    while (f && guard++ < 50) { out.unshift(f); f = f.parent_id == null ? null : folderById(f.parent_id); }
    return out;
  }
  function descendantIds(id) {
    var out = [id], i = 0;
    while (i < out.length) { childFolders(out[i++]).forEach(function (c) { out.push(c.id); }); }
    return out;
  }
  function wfFolder(w) { return w.folder_id == null ? null : Number(w.folder_id); }
  function matchesFilter(w) { return listFilter === "all" || (w.object || "company") === listFilter; }
  /* Workflows dentro de la carpeta y sus subcarpetas, con el filtro Empresas/Contactos. */
  function deepCount(id) {
    var ids = descendantIds(id);
    return list.filter(function (w) { return ids.indexOf(wfFolder(w)) !== -1 && matchesFilter(w); }).length;
  }
  function pathText(id) {
    return ["Workflows"].concat(folderPath(id).map(function (f) { return f.name; })).join(" › ");
  }

  function plain(html) {
    var d = document.createElement("div");
    d.innerHTML = html;
    return (d.textContent || "").replace(/\s+/g, " ").trim();
  }
  function objBadge(obj) {
    return '<span class="pr-wf-obj pr-wf-obj--' + obj + '">' +
      (obj === "contact" ? '<i class="fa-regular fa-user"></i> Contactos' : '<i class="fa-regular fa-building"></i> Empresas') + "</span>";
  }
  function switchHtml(w) {
    return canEdit
      ? '<label class="pr-switch" title="' + (w.enabled ? "Activo" : "Inactivo") + '"><input type="checkbox" data-toggle="' + w.id + '"' + (w.enabled ? " checked" : "") + '><span></span></label>'
      : '<span class="pr-wf-pill' + (w.enabled ? " is-on" : "") + '">' + (w.enabled ? "Activo" : "Inactivo") + "</span>";
  }
  function totalIn(stats) { return Object.keys(stats || {}).reduce(function (a, k) { return a + stats[k]; }, 0); }

  function dupListBtn(w) {
    return canEdit ? '<span class="pr-wf-rowacts">' +
      '<button type="button" class="pr-wf-x pr-wf-dup" data-wfmove="' + w.id + '" title="Mover a otra carpeta"><i class="fa-regular fa-folder-open"></i></button>' +
      '<button type="button" class="pr-wf-x pr-wf-dup" data-wfdup="' + w.id + '" title="Duplicar workflow"><i class="fa-regular fa-copy"></i></button></span>' : "";
  }
  function selBox(w) {
    return canEdit ? '<input type="checkbox" class="pr-wf-sel" data-wfsel="' + w.id + '"' + (selected[w.id] ? " checked" : "") + ' title="Seleccionar">' : "";
  }
  function folderActs(f) {
    return canEdit ? '<span class="pr-wf-rowacts">' +
      '<button type="button" class="pr-wf-x pr-wf-dup" data-fren="' + f.id + '" title="Renombrar"><i class="fa-regular fa-pen-to-square"></i></button>' +
      '<button type="button" class="pr-wf-x pr-wf-dup" data-fmove="' + f.id + '" title="Mover a otra carpeta"><i class="fa-regular fa-folder-open"></i></button>' +
      '<button type="button" class="pr-wf-x pr-wf-dup pr-wf-fdel" data-fdel="' + f.id + '" title="Eliminar carpeta"><i class="fa-regular fa-trash-can"></i></button></span>' : "";
  }
  function folderMeta(f) {
    var n = deepCount(f.id), subs = childFolders(f.id).length;
    return n + " workflow" + (n === 1 ? "" : "s") + (subs ? " · " + subs + " carpeta" + (subs === 1 ? "" : "s") : "");
  }
  function pathNote(w) {
    return listQ ? '<span class="pr-wf-path-note"><i class="fa-regular fa-folder"></i> ' + esc(pathText(wfFolder(w))) + "</span>" : "";
  }

  function renderCards(rows, subs) {
    var fol = (subs || []).length ? '<div class="pr-wf-grid pr-wf-grid--folders">' + subs.map(function (f) {
      return '<article class="pr-wf-card pr-wf-folder" data-folder="' + f.id + '" tabindex="0">' +
        '<span class="pr-wf-folder__icon"><i class="fa-solid fa-folder"></i></span>' +
        '<div class="pr-wf-folder__text"><h3 class="pr-wf-card__name">' + esc(f.name) + "</h3>" +
        '<span class="pr-note">' + folderMeta(f) + "</span></div>" + folderActs(f) + "</article>";
    }).join("") + "</div>" : "";
    return fol + (rows.length ? '<div class="pr-wf-grid">' : "") + rows.map(function (w) {
      var tt = (S().triggers || {})[w.trigger.type] || {};
      curObj = w.object || "company";
      return '<article class="pr-wf-card' + (w.enabled ? " is-on" : "") + '" data-wf="' + w.id + '" tabindex="0">' +
        '<header class="pr-wf-card__head"><div>' + selBox(w) + objBadge(curObj) +
          '<h3 class="pr-wf-card__name">' + esc(w.name) + "</h3>" + pathNote(w) + "</div>" +
          '<div class="pr-wf-card__acts">' + dupListBtn(w) + switchHtml(w) + "</div></header>" +
        (w.description ? '<p class="pr-wf-card__desc pr-clamp-2" title="' + esc(w.description) + '">' + esc(w.description) + "</p>" : "") +
        '<div class="pr-wf-card__rule"><span class="pr-wf-card__tag">Si</span><div class="pr-clamp-3">' + triggerText(w.trigger) + "</div></div>" +
        '<div class="pr-wf-card__meta"><span>' + esc(tt.label || "") + "</span><span>" + nodeCount(w.steps) + " paso" + (nodeCount(w.steps) === 1 ? "" : "s") + "</span>" +
          '<span class="pr-wf-card__stats">' + statsChips(w.stats) + "</span></div>" +
        "</article>";
    }).join("") + (rows.length ? "</div>" : "");
  }

  function renderTable(rows, subs) {
    var allSel = canEdit && rows.length && rows.every(function (w) { return selected[w.id]; });
    return '<div class="pr-wf-tablewrap"><table class="pr-table pr-wf-table"><thead><tr>' +
      (canEdit ? '<th class="pr-wf-table__sel"><input type="checkbox" class="pr-wf-sel" data-wfselall="1"' + (allSel ? " checked" : "") + ' title="Seleccionar todos"></th>' : "") +
      '<th class="pr-wf-table__on">Activo</th><th>Workflow</th><th>Objeto</th><th>Disparador</th>' +
      '<th class="pr-num">Pasos</th><th>Inscriptos</th><th>Editado</th></tr></thead><tbody>' +
      (subs || []).map(function (f) {
        return '<tr class="pr-wf-frow" data-folder="' + f.id + '" tabindex="0">' + (canEdit ? "<td></td>" : "") +
          '<td class="pr-wf-table__on"><span class="pr-wf-folder__icon pr-wf-folder__icon--sm"><i class="fa-solid fa-folder"></i></span></td>' +
          '<td class="pr-wf-table__name" colspan="6">' + folderActs(f) + "<strong>" + esc(f.name) + "</strong>" +
            '<span class="pr-note">' + folderMeta(f) + "</span></td></tr>";
      }).join("") +
      rows.map(function (w) {
        curObj = w.object || "company";
        var tt = (S().triggers || {})[w.trigger.type] || {};
        var trig = plain(triggerText(w.trigger));
        var n = totalIn(w.stats);
        return '<tr data-wf="' + w.id + '" tabindex="0"' + (w.enabled ? ' class="is-on"' : "") + ">" +
          (canEdit ? '<td class="pr-wf-table__sel">' + selBox(w) + "</td>" : "") +
          '<td class="pr-wf-table__on">' + switchHtml(w) + "</td>" +
          '<td class="pr-wf-table__name">' + dupListBtn(w) + "<strong>" + esc(w.name) + "</strong>" + pathNote(w) +
            (w.description ? '<span class="pr-note" title="' + esc(w.description) + '">' + esc(w.description) + "</span>" : "") + "</td>" +
          "<td>" + objBadge(curObj) + "</td>" +
          '<td class="pr-wf-table__trig" title="' + esc(trig) + '"><span class="pr-note">' + esc(tt.label || "") + "</span>" + esc(trig) + "</td>" +
          '<td class="pr-num">' + nodeCount(w.steps) + "</td>" +
          "<td>" + (n ? statsChips(w.stats) : '<span class="pr-note">—</span>') + "</td>" +
          '<td class="pr-wf-table__by">' + esc((P.ownerName(w.updated_by) || w.updated_by || "").split(" ")[0]) + "<br>" + fmtFecha(w.updated_at) + "</td>" +
          "</tr>";
      }).join("") + "</tbody></table></div>";
  }

  function renderList() {
    if (curFolder != null && !folderById(curFolder)) setFolder(null);
    var q = listQ.trim().toLowerCase();
    var subs = q ? [] : childFolders(curFolder);
    var rows = list.filter(function (w) {
      if (!matchesFilter(w)) return false;
      if (q) return (w.name + " " + (w.description || "")).toLowerCase().indexOf(q) !== -1;
      return wfFolder(w) === curFolder;
    });
    // Conteos de los chips: lo que hay en la carpeta abierta y sus subcarpetas.
    var scope = q ? list : list.filter(function (w) { return descendantIds(curFolder).indexOf(wfFolder(w)) !== -1 || curFolder == null; });
    var counts = { all: scope.length, company: 0, contact: 0 };
    scope.forEach(function (w) { counts[w.object || "company"]++; });
    var chip = function (k, label) {
      return '<button type="button" class="pr-wf-hf' + (listFilter === k ? " is-on" : "") + '" data-lfilter="' + k + '">' + label + " <span>" + counts[k] + "</span></button>";
    };
    var crumbs = '<nav class="pr-wf-crumbs" aria-label="Carpeta">' +
      '<button type="button" data-crumb=""' + (curFolder == null ? ' aria-current="true"' : "") + '><i class="fa-solid fa-house"></i> Workflows</button>' +
      folderPath(curFolder).map(function (f, i, arr) {
        return '<i class="fa-solid fa-chevron-right"></i><button type="button" data-crumb="' + f.id + '"' + (i === arr.length - 1 ? ' aria-current="true"' : "") + ">" +
          (i === arr.length - 1 ? '<i class="fa-regular fa-folder-open"></i> ' : "") + esc(f.name) + "</button>";
      }).join("") + "</nav>";
    var nSel = Object.keys(selected).filter(function (k) { return selected[k]; }).length;
    var empty = q ? "Ningún workflow coincide con «" + esc(listQ.trim()) + "»."
      : curFolder != null ? "Esta carpeta está vacía." + (canEdit ? " Creá un workflow acá o mové uno con <i class=\"fa-regular fa-folder-open\"></i>." : "")
      : list.length ? "No hay workflows de este tipo." : "Todavía no hay workflows." + (canEdit ? " Creá el primero." : "");
    root.innerHTML =
      '<div class="pr-wf-top">' +
        '<div><h2 class="pr-wf-title">Workflows</h2>' +
        '<p class="pr-note" style="margin:0">Reglas que trabajan las empresas y los contactos solos, como los workflows de HubSpot.' +
        (canEdit ? "" : " Sólo pgonzales, manuela, mia y bahia pueden editarlos.") + "</p></div>" +
        (canEdit ? '<div class="pr-wf-top__acts"><button type="button" class="pr-btn" id="prWfNewFolder"><i class="fa-solid fa-folder-plus"></i> Nueva carpeta</button>' +
          '<button type="button" class="pr-btn pr-btn--primary" id="prWfNew"><i class="fa-solid fa-plus"></i> Crear workflow</button></div>' : "") +
      "</div>" + testBanner() +
      (q ? '<div class="pr-wf-crumbs"><span><i class="fa-solid fa-magnifying-glass"></i> Buscando en todas las carpetas</span></div>' : crumbs) +
      '<div class="pr-wf-bar"><div class="pr-wf-hfilters">' + chip("all", "Todos") + chip("company", "Empresas") + chip("contact", "Contactos") + "</div>" +
        '<div class="pr-wf-bar__right"><div class="pr-wf-search"><i class="fa-solid fa-magnifying-glass"></i>' +
          '<input type="search" id="prWfListQ" class="pr-filter__input" placeholder="Buscar workflows" value="' + esc(listQ) + '"></div>' +
        '<div class="pr-wf-viewtoggle" role="tablist">' +
          '<button type="button" class="pr-wf-subtab' + (listView === "table" ? " is-active" : "") + '" data-lview="table"><i class="fa-solid fa-list"></i> Tabla</button>' +
          '<button type="button" class="pr-wf-subtab' + (listView === "cards" ? " is-active" : "") + '" data-lview="cards"><i class="fa-solid fa-grip"></i> Tarjetas</button>' +
        "</div></div></div>" +
      (nSel ? '<div class="pr-wf-selbar"><strong>' + nSel + " seleccionado" + (nSel === 1 ? "" : "s") + "</strong>" +
        '<button type="button" class="pr-btn" id="prWfSelMove"><i class="fa-regular fa-folder-open"></i> Mover a…</button>' +
        '<button type="button" class="pr-btn" id="prWfSelClear">Quitar selección</button></div>' : "") +
      (rows.length || subs.length ? (listView === "cards" ? renderCards(rows, subs) : renderTable(rows, subs))
        : '<div class="pr-wf-empty">' + empty + "</div>");

    bindFolders(rows);
    var nb = $("prWfNew");
    if (nb) nb.onclick = function () { askObject().then(function (obj) { if (obj) openEditor(null, obj); }); };
    root.querySelectorAll("[data-lview]").forEach(function (b) {
      b.onclick = function () {
        listView = b.getAttribute("data-lview");
        try { localStorage.setItem(LIST_VIEW_KEY, listView); } catch (e) {}
        renderList();
      };
    });
    root.querySelectorAll("[data-lfilter]").forEach(function (b) {
      b.onclick = function () { listFilter = b.getAttribute("data-lfilter"); renderList(); };
    });
    root.querySelectorAll("[data-toggle]").forEach(function (cb) {
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () {
        var id = Number(cb.getAttribute("data-toggle"));
        var w = list.filter(function (x) { return x.id === id; })[0];
        toggle(w, cb.checked).then(function (ok) { if (!ok) cb.checked = !cb.checked; });
      });
    });
    root.querySelectorAll("[data-wfdup]").forEach(function (b) {
      b.addEventListener("click", function (e) {
        e.stopPropagation();
        duplicateWorkflow(list.filter(function (x) { return x.id === Number(b.getAttribute("data-wfdup")); })[0]);
      });
      b.addEventListener("keydown", function (e) { e.stopPropagation(); });
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

  /* ---------- Carpetas: eventos y acciones ---------- */
  function bindFolders(rows) {
    var stop = function (el, fn) {
      el.addEventListener("click", function (e) { e.stopPropagation(); fn(e); });
      el.addEventListener("keydown", function (e) { e.stopPropagation(); });
    };
    var nf = $("prWfNewFolder");
    if (nf) nf.onclick = function () { newFolder(curFolder); };
    root.querySelectorAll("[data-crumb]").forEach(function (b) {
      b.onclick = function () { var v = b.getAttribute("data-crumb"); setFolder(v ? Number(v) : null); renderList(); };
    });
    root.querySelectorAll("[data-folder]").forEach(function (el) {
      var open = function (e) {
        if (e.target.closest("button")) return;
        setFolder(Number(el.getAttribute("data-folder")));
        renderList();
      };
      el.addEventListener("click", open);
      el.addEventListener("keydown", function (e) { if (e.key === "Enter") open(e); });
    });
    root.querySelectorAll("[data-fren]").forEach(function (b) { stop(b, function () { renameFolder(folderById(Number(b.getAttribute("data-fren")))); }); });
    root.querySelectorAll("[data-fmove]").forEach(function (b) { stop(b, function () { moveFolder(folderById(Number(b.getAttribute("data-fmove")))); }); });
    root.querySelectorAll("[data-fdel]").forEach(function (b) { stop(b, function () { deleteFolder(folderById(Number(b.getAttribute("data-fdel")))); }); });
    root.querySelectorAll("[data-wfmove]").forEach(function (b) { stop(b, function () { moveWorkflows([Number(b.getAttribute("data-wfmove"))]); }); });
    root.querySelectorAll("[data-wfsel]").forEach(function (cb) {
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () { selected[cb.getAttribute("data-wfsel")] = cb.checked; renderList(); });
    });
    var all = root.querySelector("[data-wfselall]");
    if (all) all.addEventListener("change", function () {
      rows.forEach(function (w) { selected[w.id] = all.checked; });
      renderList();
    });
    var sm = $("prWfSelMove");
    if (sm) sm.onclick = function () {
      moveWorkflows(Object.keys(selected).filter(function (k) { return selected[k]; }).map(Number));
    };
    var sc = $("prWfSelClear");
    if (sc) sc.onclick = function () { selected = {}; renderList(); };
    bindDrag();
    var lq = $("prWfListQ");
    if (lq) {
      var t = null;
      lq.addEventListener("input", function () {
        clearTimeout(t);
        t = setTimeout(function () {
          listQ = lq.value;
          var pos = lq.selectionStart;
          renderList();
          var again = $("prWfListQ");
          if (again) { again.focus(); try { again.setSelectionRange(pos, pos); } catch (e) {} }
        }, 150);
      });
    }
  }

  function folderApi(path, method, body) {
    return P.api(path, { method: method, body: body ? JSON.stringify(body) : undefined });
  }
  function newFolder(parentId) {
    var name = prompt("Nombre de la carpeta nueva" + (parentId != null ? " (dentro de «" + folderById(parentId).name + "»)" : "") + ":");
    if (!name || !name.trim()) return Promise.resolve(null);
    return folderApi("/prospecting/workflow-folders", "POST", { name: name, parent_id: parentId }).then(function (f) {
      folders.push(f);
      renderList();
      P.toast('<i class="fa-solid fa-folder-plus"></i> Carpeta <strong>' + esc(f.name) + "</strong> creada.");
      return f;
    }).catch(function (err) { alert(errorText(err)); return null; });
  }
  function renameFolder(f) {
    var name = prompt("Nuevo nombre de la carpeta:", f.name);
    if (!name || !name.trim() || name.trim() === f.name) return;
    folderApi("/prospecting/workflow-folders/" + f.id, "PATCH", { name: name }).then(function (r) {
      f.name = r.name;
      renderList();
    }).catch(function (err) { alert(errorText(err)); });
  }
  function moveFolder(f) {
    askFolder("Mover la carpeta «" + f.name + "» a…", descendantIds(f.id), f.parent_id == null ? null : f.parent_id).then(function (dest) {
      if (dest !== undefined) doMoveFolder(f, dest);
    });
  }
  function doMoveFolder(f, dest) {
    if ((f.parent_id == null ? null : f.parent_id) === dest) return;
    folderApi("/prospecting/workflow-folders/" + f.id, "PATCH", { parent_id: dest }).then(function (r) {
      f.parent_id = r.parent_id;
      renderList();
      P.toast('<i class="fa-regular fa-folder-open"></i> <strong>' + esc(f.name) + "</strong> ahora está en " + esc(pathText(dest)) + ".");
    }).catch(function (err) { alert(errorText(err)); });
  }
  function deleteFolder(f) {
    var nw = list.filter(function (w) { return wfFolder(w) === f.id; }).length;
    var nf = childFolders(f.id).length;
    var dest = pathText(f.parent_id == null ? null : f.parent_id);
    var what = [nw ? nw + " workflow" + (nw === 1 ? "" : "s") : "", nf ? nf + " carpeta" + (nf === 1 ? "" : "s") : ""].filter(Boolean).join(" y ");
    if (!confirm("¿Eliminar la carpeta «" + f.name + "»?" + (what ? "\n\nLo que tiene adentro (" + what + ") pasa a «" + dest + "». No se borra ningún workflow." : ""))) return;
    folderApi("/prospecting/workflow-folders/" + f.id, "DELETE").then(function () {
      if (curFolder === f.id) setFolder(f.parent_id);
      P.toast('<i class="fa-regular fa-trash-can"></i> Carpeta <strong>' + esc(f.name) + "</strong> eliminada." + (what ? " Su contenido pasó a " + esc(dest) + "." : ""));
      return loadList();
    }).catch(function (err) { alert(errorText(err)); });
  }
  function moveWorkflows(ids) {
    if (!ids.length) return;
    var one = ids.length === 1 ? list.filter(function (w) { return w.id === ids[0]; })[0] : null;
    var from = one ? wfFolder(one) : curFolder;
    askFolder(one ? "Mover «" + one.name + "» a…" : "Mover " + ids.length + " workflows a…", [], from).then(function (dest) {
      if (dest !== undefined) doMoveWorkflows(ids, dest);
    });
  }
  function doMoveWorkflows(ids, dest) {
    ids = ids.filter(function (id) { var w = list.filter(function (x) { return x.id === id; })[0]; return w && wfFolder(w) !== dest; });
    if (!ids.length) return;
    var one = ids.length === 1 ? list.filter(function (w) { return w.id === ids[0]; })[0] : null;
    folderApi("/prospecting/workflows/move", "POST", { ids: ids, folder_id: dest }).then(function () {
      list.forEach(function (w) { if (ids.indexOf(w.id) !== -1) w.folder_id = dest; });
      selected = {};
      renderList();
      P.toast('<i class="fa-regular fa-folder-open"></i> ' + (one ? "<strong>" + esc(one.name) + "</strong> movido" : ids.length + " workflows movidos") + " a " + esc(pathText(dest)) + ".");
    }).catch(function (err) { alert(errorText(err)); });
  }

  /* ---------- Arrastrar y soltar ---------- */
  /* Se arrastra un workflow (o todos los seleccionados, si es uno de ellos) o una carpeta,
     y se suelta sobre una carpeta o sobre un tramo de la ruta de arriba («Workflows» = sin
     carpeta). Usa las mismas rutas que «Mover a…». */
  var drag = null;  // { wf: [ids] } | { folder: id }
  function dropTarget(el) {
    if (el.hasAttribute("data-crumb")) { var v = el.getAttribute("data-crumb"); return v ? Number(v) : null; }
    return Number(el.getAttribute("data-folder"));
  }
  function canDrop(dest) {
    if (!drag) return false;
    if (drag.folder != null) {
      if (descendantIds(drag.folder).indexOf(dest) !== -1) return false;
      var f = folderById(drag.folder);
      return !!f && (f.parent_id == null ? null : f.parent_id) !== dest;
    }
    return drag.wf.some(function (id) { var w = list.filter(function (x) { return x.id === id; })[0]; return w && wfFolder(w) !== dest; });
  }
  function dragGhost(e, text) {
    var g = document.createElement("div");
    g.className = "pr-wf-dragghost";
    g.innerHTML = text;
    document.body.appendChild(g);
    try { e.dataTransfer.setDragImage(g, 14, 14); } catch (err) {}
    setTimeout(function () { g.remove(); }, 0);
  }
  function bindDrag() {
    if (!canEdit) return;
    var clear = function () {
      drag = null;
      root.querySelectorAll(".is-drop, .is-dragging").forEach(function (x) { x.classList.remove("is-drop", "is-dragging"); });
      root.classList.remove("pr-wf-dragmode");
    };
    root.querySelectorAll("[data-wf], [data-folder]").forEach(function (el) {
      el.setAttribute("draggable", "true");
      el.addEventListener("dragstart", function (e) {
        if (e.target.closest && e.target.closest("input, .pr-switch")) { e.preventDefault(); return; }
        if (el.hasAttribute("data-folder")) {
          var f = folderById(Number(el.getAttribute("data-folder")));
          drag = { folder: f.id };
          dragGhost(e, '<i class="fa-solid fa-folder"></i> ' + esc(f.name));
        } else {
          var id = Number(el.getAttribute("data-wf"));
          var sel = Object.keys(selected).filter(function (k) { return selected[k]; }).map(Number);
          drag = { wf: sel.indexOf(id) !== -1 ? sel : [id] };
          var w = list.filter(function (x) { return x.id === id; })[0];
          dragGhost(e, '<i class="fa-solid fa-diagram-project"></i> ' + (drag.wf.length > 1 ? drag.wf.length + " workflows" : esc(w ? w.name : "")));
          if (drag.wf.length > 1) root.querySelectorAll("[data-wf]").forEach(function (x) {
            if (drag.wf.indexOf(Number(x.getAttribute("data-wf"))) !== -1) x.classList.add("is-dragging");
          });
        }
        el.classList.add("is-dragging");
        root.classList.add("pr-wf-dragmode");
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", JSON.stringify(drag)); } catch (err) {}
      });
      el.addEventListener("dragend", clear);
    });
    root.querySelectorAll("[data-folder], [data-crumb]").forEach(function (el) {
      el.addEventListener("dragover", function (e) {
        if (!canDrop(dropTarget(el))) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        el.classList.add("is-drop");
      });
      el.addEventListener("dragleave", function (e) {
        if (!el.contains(e.relatedTarget)) el.classList.remove("is-drop");
      });
      el.addEventListener("drop", function (e) {
        e.preventDefault();
        var dest = dropTarget(el), d = drag;
        if (!canDrop(dest)) return clear();
        clear();
        if (d.folder != null) doMoveFolder(folderById(d.folder), dest);
        else doMoveWorkflows(d.wf, dest);
      });
    });
  }

  /* Elegir carpeta de destino: árbol indentado, con la raíz arriba. Resuelve el id (null =
     raíz) o undefined si se cancela. `disabled` = carpetas que no se pueden elegir. */
  function askFolder(title, disabled, current) {
    return new Promise(function (resolve) {
      var pick = current == null ? null : current;
      var box = document.createElement("div");
      box.className = "pr-modal";
      var draw = function () {
        var rowsHtml = [];
        var walk = function (parent, depth) {
          childFolders(parent).forEach(function (f) {
            var off = disabled.indexOf(f.id) !== -1;
            rowsHtml.push('<button type="button" class="pr-ftree__item' + (pick === f.id ? " is-picked" : "") + '" data-fpick="' + f.id + '"' +
              (off ? " disabled" : "") + ' style="padding-left:' + (12 + depth * 20) + 'px">' +
              '<i class="fa-' + (pick === f.id ? "solid fa-folder-open" : "regular fa-folder") + '"></i> ' + esc(f.name) +
              (f.id === current ? ' <span class="pr-note">(actual)</span>' : "") + "</button>");
            walk(f.id, depth + 1);
          });
        };
        walk(null, 1);
        box.innerHTML = '<div class="pr-modal__card pr-ftree" role="dialog" aria-modal="true">' +
          "<h3>" + esc(title) + "</h3>" +
          '<div class="pr-ftree__list">' +
            '<button type="button" class="pr-ftree__item' + (pick == null ? " is-picked" : "") + '" data-fpick="">' +
              '<i class="fa-solid fa-house"></i> Workflows (sin carpeta)' + (current == null ? ' <span class="pr-note">(actual)</span>' : "") + "</button>" +
            rowsHtml.join("") +
          "</div>" +
          '<button type="button" class="pr-wf-add" data-fnew="1"><i class="fa-solid fa-folder-plus"></i> Nueva carpeta ' +
            (pick == null ? "" : "dentro de «" + esc(folderById(pick).name) + "»") + "</button>" +
          '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-fx="cancel">Cancelar</button>' +
          '<button type="button" class="pr-btn pr-btn--primary" data-fx="ok"' + (pick === current ? " disabled" : "") + ">Mover acá</button></div></div>";
      };
      draw();
      document.body.appendChild(box);
      var close = function (v) { box.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      var onKey = function (e) { if (e.key === "Escape") close(undefined); };
      document.addEventListener("keydown", onKey);
      box.addEventListener("click", function (e) {
        if (e.target === box) return close(undefined);
        var b = e.target.closest("button");
        if (!b || b.disabled) return;
        if (b.hasAttribute("data-fpick")) { var v = b.getAttribute("data-fpick"); pick = v ? Number(v) : null; return draw(); }
        if (b.hasAttribute("data-fnew")) {
          return newFolder(pick).then(function (f) { if (f) { pick = f.id; } draw(); });
        }
        var x = b.getAttribute("data-fx");
        if (x === "cancel") return close(undefined);
        if (x === "ok") return close(pick);
      });
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
    picked = {};
    justPasted = {};
    draftUid = newId();
    render();
  }

  /* Copia de un workflow (de la lista, o el que está abierto con sus cambios). No se guarda
     sola: al apretar Guardar hace el POST de siempre y nace inactiva, sin inscriptos ni
     historial. */
  function duplicateWorkflow(src) {
    if (!src) {
      if (dirty && !confirm("Hay cambios sin guardar. ¿Duplicar el workflow con esos cambios?")) return;
      src = draft;
    }
    var name = src.name || "workflow";
    openEditor(src);
    draft.id = null;
    draft.enabled = false;
    draft.name = "Copia de " + name;
    dirty = true;
    render();
    P.toast('<i class="fa-regular fa-copy"></i> Copia de <strong>' + esc(name) + "</strong> lista: revisala y guardala. Arranca inactiva.");
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
    if (key === "ext") { holder = ext && ext.holder; prop = "conditions"; }  // panel de filtros avanzados
    else if (key === "trigger") { holder = draft.trigger; prop = "conditions"; }
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
    else if (kind === "delay") node = { type: "delay", delay: delayDefaults(extra || "duration"), next: after };
    else if (kind === "branch") {
      var bk = extra || "value";
      if (bk === "random") node = { type: "branch", branch: { kind: "random", paths: [{ pct: 50, next: after }, { pct: 50, next: null }] } };
      else if (bk === "conditions") node = { type: "branch", branch: { kind: "conditions", paths: [{ label: "Rama 1", conditions: blankConds(), next: null }], else_next: after } };
      else node = { type: "branch", branch: { kind: "value", field: defaultField(), paths: [{ values: [], next: null }], else_next: after } };
    }
    draft.steps.nodes[id] = node;
    setPtr(ptr, id);
  }

  /* Dónde guardar la respuesta de «Preguntar a la IA»: una nota o una propiedad de texto. */
  function aiTargets() {
    var own = objFields(curObj).filter(function (f) { return f.editable !== false && (f.type === "text" || f.type === "longtext"); })
      .map(function (f) { return { value: f.key, label: f.label }; });
    return [{ value: "__note__", label: "Una nota en la actividad" }].concat(own);
  }

  function delayDefaults(kind) {
    var defaults = { duration: { days: 1 }, until_date: { date: "", time: "09:00" },
      until_property: { field: curObj === "contact" ? "follow_up_date" : "prospecting_start_date", offset_days: 0, time: "09:00" },
      until_weekday: { days: [0], time: "09:00" }, until_time: { time: "09:00" },
      until_condition: { conditions: blankConds(), max_days: 7 } };
    return Object.assign({ kind: kind }, clone(defaults[kind] || {}));
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
    if (a.type === "format_phone") a.country = "AR";
    if (a.type === "ask_ai") { a.prompt = ""; a.field = aiTargets()[0] ? aiTargets()[0].value : "__note__"; }
    if (a.type === "create_contact") a.values = [{ field: "first_name", value: "" }, { field: "email", value: "" }];
    if (a.type === "create_deal") {
      a.pipeline_key = "hiring"; a.stage_key = "intro_call"; a.owner_email = "";
      a.name = curObj === "contact" ? "{campo:company_name}" : "{empresa}"; a.values = [];
    }
    if (a.type === "sheets_append") { a.spreadsheet = ""; a.sheet = "Hoja 1"; a.columns = [{ field: curObj === "contact" ? "email" : "name" }, { text: "{owner}" }]; }
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

  /* ---------- Seleccionar, duplicar y copiar pasos ----------
     Se tildan pasos en el lienzo y se duplican ahí mismo o se copian a un portapapeles
     (localStorage, así se pega en otro workflow) que ofrece cada «+». Una ramificación se
     copia con todo lo que tiene adentro y cierra la copia. Los ids se regeneran al pegar. */
  var CLIP_KEY = "pr_wf_clip";
  var memClip = null;
  function readClip() {
    try {
      var c = JSON.parse(localStorage.getItem(CLIP_KEY) || "null");
      return c && c.start && c.nodes && c.nodes[c.start] ? c : null;
    } catch (e) { return memClip; }
  }
  function writeClip(c) {
    memClip = c;
    try { if (c) localStorage.setItem(CLIP_KEY, JSON.stringify(c)); else localStorage.removeItem(CLIP_KEY); } catch (e) { /* queda en memoria */ }
  }
  function pickedIds() {
    return Object.keys(picked).filter(function (id) { return picked[id] && draft.steps.nodes[id]; });
  }
  /* Qué ramificaciones contienen a cada paso, recorriendo igual que chain() (preorden,
     la primera visita gana: lo que se vuelve a alcanzar es un «ir a», no está adentro). */
  function ancestry() {
    var anc = {}, seen = {};
    var walk = function (id, stack) {
      for (var g = 0; g < 500 && id && !seen[id] && draft.steps.nodes[id]; g++) {
        seen[id] = true;
        anc[id] = stack;
        var n = draft.steps.nodes[id];
        if (n.type === "branch") {
          var inner = stack.concat([id]);
          targets(n).forEach(function (t) { walk(t, inner); });
          return;
        }
        id = n.next;
      }
    };
    walk(draft.steps.start, []);
    return anc;
  }
  function buildClip() {
    var order = numbering(), anc = ancestry(), on = {};
    var ids = pickedIds().filter(function (id) { return order[id]; });
    ids.forEach(function (id) { on[id] = true; });
    // Lo tildado dentro de una rama tildada ya viaja con ella.
    var top = ids.filter(function (id) { return !(anc[id] || []).some(function (b) { return on[b]; }); })
      .sort(function (a, b) { return order[a] - order[b]; });
    var items = [], dropped = 0;
    top.forEach(function (id) {
      var prev = items[items.length - 1];
      if (prev && draft.steps.nodes[prev].type === "branch") { dropped++; return; }
      items.push(id);
    });
    if (!items.length) return null;
    var nodes = {};
    items.forEach(function (id, i) {
      var n = clone(draft.steps.nodes[id]);
      if (n.type !== "branch") n.next = items[i + 1] || null;
      nodes[id] = n;
      if (n.type === "branch") {
        Object.keys(anc).forEach(function (x) {
          if (anc[x].indexOf(id) !== -1) nodes[x] = clone(draft.steps.nodes[x]);
        });
      }
    });
    var last = items[items.length - 1];
    return {
      object: curObj, src_id: draft.id || null, src_uid: draftUid, src_name: draft.name || "",
      start: items[0], last: last, nodes: nodes, count: Object.keys(nodes).length,
      ends_in_branch: nodes[last].type === "branch", dropped: dropped,
    };
  }
  /* Por qué no se puede pegar acá ("" = se puede). */
  function pasteBlocked(clip, ptr) {
    if ((clip.object || "company") !== curObj) {
      return "Se copiaron de un workflow de " + (clip.object === "contact" ? "contactos" : "empresas") +
        ": las propiedades no son las mismas.";
    }
    if (clip.ends_in_branch && getPtr(ptr)) return "Termina en una ramificación: pegala en el «+» de abajo de todo de un camino.";
    return "";
  }
  function pasteClip(ptr, clip) {
    var map = {};
    Object.keys(clip.nodes).forEach(function (old) {
      var id;
      do { id = newId(); } while (draft.steps.nodes[id]);
      map[old] = id;
    });
    // Un «ir a» hacia afuera de lo copiado sólo sigue valiendo en el mismo workflow.
    var same = clip.src_uid === draftUid || (clip.src_id != null && clip.src_id === draft.id);
    var fix = function (t) {
      if (!t) return null;
      if (map[t]) return map[t];
      return same && draft.steps.nodes[t] ? t : null;
    };
    var after = getPtr(ptr);
    Object.keys(clip.nodes).forEach(function (old) {
      var n = clone(clip.nodes[old]);
      if (n.type === "branch") {
        (n.branch.paths || []).forEach(function (p) { p.next = fix(p.next); });
        if (n.branch.kind !== "random") n.branch.else_next = fix(n.branch.else_next);
      } else n.next = old === clip.last ? after : fix(n.next);
      draft.steps.nodes[map[old]] = n;
      justPasted[map[old]] = true;
    });
    setPtr(ptr, map[clip.start]);
    return map;
  }
  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function droppedNote(clip) {
    return clip.dropped ? " (" + plural(clip.dropped, "paso quedó", "pasos quedaron") + " afuera: van después de una ramificación)" : "";
  }
  function selAction(v) {
    if (v === "clear") { picked = {}; return render(); }
    if (v === "unclip") { writeClip(null); return render(); }
    var clip = buildClip();
    if (!clip) { picked = {}; return render(); }
    var what = plural(clip.count, "paso", "pasos");
    if (v === "dup") {
      if (clip.ends_in_branch) {
        writeClip(clip);
        picked = {};
        render();
        return P.toast('<i class="fa-regular fa-clipboard"></i> ' + what + " copiado" + (clip.count === 1 ? "" : "s") +
          ". Como termina en una ramificación, tocá el «+» de abajo de todo de un camino para pegarla." + droppedNote(clip));
      }
      pasteClip("next:" + clip.last, clip);
      picked = {};
      markDirty();
      render();
      return P.toast('<i class="fa-regular fa-clone"></i> Se duplicaron ' + what + ", debajo del último seleccionado." + droppedNote(clip));
    }
    if (v === "copy") {
      writeClip(clip);
      picked = {};
      render();
      return P.toast('<i class="fa-regular fa-copy"></i> ' + what + " copiado" + (clip.count === 1 ? "" : "s") +
        ". Tocá un «+» (en este o en otro workflow) y elegí «Pegar»." + droppedNote(clip));
    }
    if (v === "other") {
      return askTargetWorkflow(clip.count).then(function (dest) {
        if (dest === undefined) return;
        var w = dest === "new" ? null : list.filter(function (x) { return x.id === dest; })[0];
        if (dest !== "new" && !w) return;
        if (dirty && !confirm("Tenés cambios sin guardar en este workflow. ¿Salir igual? (los pasos ya quedaron copiados)")) {
          writeClip(clip);
          return render();
        }
        var obj = curObj;
        writeClip(clip);
        if (w) {
          openEditor(w);
          P.toast('<i class="fa-regular fa-clipboard"></i> ' + what + " listo" + (clip.count === 1 ? "" : "s") + " para pegar en <strong>" +
            esc(w.name) + "</strong>: tocá un «+» y elegí «Pegar»." + droppedNote(clip));
        } else {
          openEditor(null, obj);
          pasteClip("start", clip);
          dirty = true;
          render();
          P.toast('<i class="fa-regular fa-clipboard"></i> Workflow nuevo con ' + what + ". Ponele nombre y disparador, y guardalo." + droppedNote(clip));
        }
      });
    }
  }
  /* Después de dibujar: marca las tarjetas tildadas (y lo que está adentro de una rama
     tildada, que viaja con ella) y resalta lo recién pegado. */
  function markPicked() {
    var on = pickedIds(), inside = {};
    if (on.length) {
      var anc = ancestry();
      Object.keys(anc).forEach(function (x) { if (anc[x].some(function (b) { return picked[b]; })) inside[x] = true; });
    }
    root.querySelectorAll("[data-pick-node]").forEach(function (cb) {
      var id = cb.getAttribute("data-pick-node"), nd = cb.closest(".pr-wf-node");
      if (!nd) return;
      if (picked[id]) nd.classList.add("is-picked");
      else if (inside[id]) nd.classList.add("is-picked-in");
      if (justPasted[id]) nd.classList.add("is-new");
    });
    justPasted = {};
  }
  function selBar() {
    if (!canEdit) return "";
    var n = pickedIds().length, clip = readClip();
    if (n) {
      return '<div class="pr-wf-selbar" role="toolbar" aria-label="Pasos seleccionados">' +
        '<span class="pr-wf-selbar__n">' + plural(n, "paso seleccionado", "pasos seleccionados") + "</span>" +
        '<button type="button" data-sel="dup" title="Pegar una copia debajo del último paso seleccionado"><i class="fa-regular fa-clone"></i> Duplicar</button>' +
        '<button type="button" data-sel="copy" title="Copiar para pegar con un «+», en este o en otro workflow"><i class="fa-regular fa-copy"></i> Copiar</button>' +
        '<button type="button" data-sel="other" title="Elegir otro workflow y abrirlo para pegar"><i class="fa-solid fa-share-from-square"></i> Copiar a otro workflow…</button>' +
        '<button type="button" class="pr-wf-selbar__x" data-sel="clear" title="Quitar la selección"><i class="fa-solid fa-xmark"></i></button>' +
        "</div>";
    }
    if (!clip) return "";
    var off = (clip.object || "company") !== curObj;
    return '<div class="pr-wf-selbar pr-wf-selbar--clip">' +
      '<span class="pr-wf-selbar__n"><i class="fa-regular fa-clipboard"></i> ' + plural(clip.count, "paso copiado", "pasos copiados") +
        (clip.src_name ? " de «" + esc(clip.src_name) + "»" : "") + "</span>" +
      '<span class="pr-wf-selbar__hint">' + (off ? "De un workflow de " + (clip.object === "contact" ? "contactos" : "empresas") + ": no se pueden pegar acá" : "Tocá un «+» para pegarlos") + "</span>" +
      '<button type="button" data-sel="unclip" title="Vaciar el portapapeles">Vaciar</button>' +
      "</div>";
  }
  function pasteBlock() {
    var clip = readClip();
    if (!clip || !openMenu) return "";
    var why = pasteBlocked(clip, openMenu);
    return '<button type="button" class="pr-pick__paste" data-ins="paste"' + (why ? ' disabled title="' + esc(why) + '"' : "") + ">" +
      '<span class="pr-pick__tile-icon"><i class="fa-regular fa-clipboard"></i></span>' +
      '<span class="pr-pick__paste-text"><strong>Pegar ' + plural(clip.count, "paso", "pasos") + "</strong>" +
        "<span>Copiado" + (clip.count === 1 ? "" : "s") + (clip.src_name ? " de «" + esc(clip.src_name) + "»" : "") + "</span>" +
        (why ? "<em>" + esc(why) + "</em>" : "") + "</span></button>";
  }
  function askTargetWorkflow(n) {
    return new Promise(function (resolve) {
      var box = document.createElement("div");
      box.className = "pr-modal";
      var rows = function (q) {
        q = (q || "").trim().toLowerCase();
        var ws = list.filter(function (w) {
          return (w.object || "company") === curObj && w.id !== draft.id && (!q || String(w.name || "").toLowerCase().indexOf(q) !== -1);
        }).sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || ""), "es"); });
        if (!ws.length) return '<p class="pr-note pr-wf-tpick__empty">Ningún workflow de ' + (curObj === "contact" ? "contactos" : "empresas") + " coincide.</p>";
        return ws.map(function (w) {
          return '<button type="button" class="pr-ftree__item pr-wf-tpick__item" data-tpick="' + w.id + '">' +
            '<i class="fa-solid fa-diagram-project"></i><span class="pr-wf-tpick__name">' + esc(w.name || "(sin nombre)") + "</span>" +
            '<span class="pr-note">' + esc(pathText(wfFolder(w))) + (w.enabled ? " · activo" : "") + "</span></button>";
        }).join("");
      };
      box.innerHTML = '<div class="pr-modal__card pr-ftree" role="dialog" aria-modal="true">' +
        "<h3>Copiar " + plural(n, "paso", "pasos") + " a…</h3>" +
        '<p class="pr-note">Se abre el workflow elegido y los pegás con un «+». Nada se guarda hasta que aprietes Guardar.</p>' +
        '<input type="search" class="pr-filter__input pr-wf-tpick__q" placeholder="Buscar un workflow" autocomplete="off">' +
        '<div class="pr-ftree__list">' + rows("") + "</div>" +
        '<button type="button" class="pr-wf-add" data-tpick="new"><i class="fa-solid fa-plus"></i> A un workflow nuevo de ' +
          (curObj === "contact" ? "contactos" : "empresas") + "</button>" +
        '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-tx="cancel">Cancelar</button></div></div>';
      document.body.appendChild(box);
      var q = box.querySelector(".pr-wf-tpick__q"), lst = box.querySelector(".pr-ftree__list");
      q.addEventListener("input", function () { lst.innerHTML = rows(q.value); });
      setTimeout(function () { q.focus(); }, 0);
      var close = function (v) { box.remove(); document.removeEventListener("keydown", onKey); resolve(v); };
      var onKey = function (e) { if (e.key === "Escape") close(undefined); };
      document.addEventListener("keydown", onKey);
      box.addEventListener("click", function (e) {
        if (e.target === box) return close(undefined);
        var b = e.target.closest("button");
        if (!b) return;
        var t = b.getAttribute("data-tpick");
        if (t !== null) return close(t === "new" ? "new" : Number(t));
        if (b.getAttribute("data-tx") === "cancel") close(undefined);
      });
    });
  }

  /* =================================================================
     Editor — vista
     ================================================================= */
  /* Cada cambio redibuja el editor entero: se guarda la posición del lienzo (y de la
     página) y se restaura, para no volver al principio en cada click. Al abrir un
     workflow (`centerNext`) arranca centrado en el disparador. */
  var centerNext = false;

  /* ---------- Lienzo: zoom + mover ----------
     El viewport (.pr-wf-canvas) no scrollea: el dibujo (.pr-wf-flow) se ubica con
     transform: translate(pan) scale(zoom). `transform` achica como una foto (letra,
     tarjetas y conectores juntos) y no lo toca el tamaño mínimo de letra del navegador,
     que con CSS `zoom` dejaba las tarjetas angostas y el texto grande. */
  var ZOOM_KEY = "pr_wf_zoom", ZOOM_MIN = 0.25, ZOOM_MAX = 2, ZOOM_STEP = 0.1, KEEP_VISIBLE = 120;
  var zoom = (function () {
    try { var z = parseFloat(localStorage.getItem(ZOOM_KEY)); return z >= ZOOM_MIN && z <= ZOOM_MAX ? z : 1; } catch (e) { return 1; }
  })();
  var panX = null, panY = null;
  function zoomBar() {
    return '<div class="pr-wf-zoombar" role="toolbar" aria-label="Zoom">' +
      '<button type="button" data-zoom="out" title="Alejar (Ctrl/⌘ −)"' + (zoom <= ZOOM_MIN + 0.001 ? " disabled" : "") + '><i class="fa-solid fa-minus"></i></button>' +
      '<button type="button" class="pr-wf-zoombar__pct" data-zoom="reset" title="Volver a 100% (Ctrl/⌘ 0)">' + Math.round(zoom * 100) + "%</button>" +
      '<button type="button" data-zoom="in" title="Acercar (Ctrl/⌘ +)"' + (zoom >= ZOOM_MAX - 0.001 ? " disabled" : "") + '><i class="fa-solid fa-plus"></i></button>' +
      '<span class="pr-wf-zoombar__sep"></span>' +
      '<button type="button" class="pr-wf-zoombar__fit" data-zoom="fit" title="Que entre el workflow entero"><i class="fa-solid fa-expand"></i> Ajustar</button>' +
      "</div>";
  }
  function stageEls() {
    var cv = root && root.querySelector(".pr-wf-canvas");
    return cv ? { cv: cv, flow: cv.querySelector(".pr-wf-flow") } : null;
  }
  /* Aplica pan + zoom. El dibujo nunca sale entero de la vista: quedan KEEP_VISIBLE px. */
  function applyView() {
    var el = stageEls();
    if (!el || !el.flow) return;
    var w = el.flow.offsetWidth * zoom, h = el.flow.offsetHeight * zoom;
    var vw = el.cv.clientWidth, vh = el.cv.clientHeight;
    var kx = Math.min(KEEP_VISIBLE, w), ky = Math.min(KEEP_VISIBLE, h);
    panX = Math.min(vw - kx, Math.max(kx - w, panX));
    panY = Math.min(vh - ky, Math.max(ky - h, panY));
    el.flow.style.transform = "translate(" + panX + "px," + panY + "px) scale(" + zoom + ")";
    // El punteado del fondo acompaña: se siente un lienzo infinito.
    var dot = 18 * zoom;
    while (dot < 12) dot *= 2;  // alejado, los puntos no se amontonan en una mancha gris
    el.cv.style.backgroundSize = dot + "px " + dot + "px";
    el.cv.style.backgroundPosition = panX + "px " + panY + "px";
  }
  /* Centra el dibujo a lo ancho y lo pega arriba (al abrir un workflow). */
  function centerView() {
    var el = stageEls();
    if (!el || !el.flow) return;
    panX = (el.cv.clientWidth - el.flow.offsetWidth * zoom) / 2;
    panY = 16;
    applyView();
  }
  /* Cambia el zoom dejando quieto el punto bajo `anchor` ({x, y} de pantalla; por defecto
     el centro del lienzo). No redibuja. */
  function setZoom(z, anchor) {
    var el = stageEls();
    z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(z * 100) / 100));
    if (!el || Math.abs(z - zoom) < 0.001) return;
    var r = el.cv.getBoundingClientRect();
    var ax = anchor ? anchor.x - r.left : el.cv.clientWidth / 2;
    var ay = anchor ? anchor.y - r.top : el.cv.clientHeight / 2;
    var cx = (ax - panX) / zoom, cy = (ay - panY) / zoom;
    zoom = z;
    panX = ax - cx * z;
    panY = ay - cy * z;
    applyView();
    try { localStorage.setItem(ZOOM_KEY, String(z)); } catch (e) {}
    var bar = root.querySelector(".pr-wf-zoombar");
    if (bar) bar.outerHTML = zoomBar();
  }
  function stepZoom(dir) {
    var z = dir > 0 ? Math.floor(zoom / ZOOM_STEP + 1e-6) * ZOOM_STEP + ZOOM_STEP
                    : Math.ceil(zoom / ZOOM_STEP - 1e-6) * ZOOM_STEP - ZOOM_STEP;
    setZoom(z);
  }
  /* Que entre entero (ancho y alto) y centrado. */
  function fitZoom() {
    var el = stageEls();
    if (!el || !el.flow) return;
    var w = el.flow.offsetWidth, h = el.flow.offsetHeight;
    var z = Math.min((el.cv.clientWidth - 48) / w, (el.cv.clientHeight - 48) / h, 1);
    setZoom(z);
    panX = (el.cv.clientWidth - w * zoom) / 2;
    panY = Math.max(16, (el.cv.clientHeight - h * zoom) / 2);
    applyView();
  }
  function bindZoom() {
    var el = stageEls();
    if (!el) return;
    var cv = el.cv;
    // Rueda / dos dedos = mover; Ctrl/⌘ + rueda o pinch (llega como wheel + ctrlKey) = zoom.
    cv.addEventListener("wheel", function (e) {
      e.preventDefault();
      if (e.ctrlKey || e.metaKey) {
        setZoom(zoom * Math.exp(-e.deltaY * 0.01), { x: e.clientX, y: e.clientY });
        return;
      }
      var k = e.deltaMode === 1 ? 16 : 1;
      var dx = e.deltaX * k, dy = e.deltaY * k;
      if (e.shiftKey && !dx) { dx = dy; dy = 0; }
      panX -= dx;
      panY -= dy;
      applyView();
    }, { passive: false });
    // Un overflow:hidden igual scrollea solo si el foco cae en un campo fuera de vista:
    // ese scroll se pasa al pan y se vuelve a 0, para que nunca se desfase.
    cv.addEventListener("scroll", function () {
      if (!cv.scrollLeft && !cv.scrollTop) return;
      panX -= cv.scrollLeft;
      panY -= cv.scrollTop;
      cv.scrollLeft = 0;
      cv.scrollTop = 0;
      applyView();
    });
    // Arrastrar el fondo (mouse o dedo) para moverse.
    cv.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      if (e.target.closest("button, input, select, textarea, label, a, .pr-wf-node, .pr-wf-extras, .pr-wf-desc, .pr-wf-goto, .pr-wf-end, .pr-wf-zoombar")) return;
      e.preventDefault();
      var sx = e.clientX, sy = e.clientY, px = panX, py = panY;
      cv.classList.add("is-panning");
      var move = function (ev) { panX = px + (ev.clientX - sx); panY = py + (ev.clientY - sy); applyView(); };
      var up = function () {
        cv.classList.remove("is-panning");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", up);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", up);
    });
  }
  window.addEventListener("resize", function () { if (draft && tab === "editor") applyView(); });
  document.addEventListener("keydown", function (e) {
    if (!draft || tab !== "editor" || !(e.ctrlKey || e.metaKey) || !root || !root.querySelector(".pr-wf-canvas")) return;
    if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]")) return;
    if (e.key === "+" || e.key === "=") { e.preventDefault(); stepZoom(1); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); stepZoom(-1); }
    else if (e.key === "0") { e.preventDefault(); setZoom(1); }
  });

  function render() {
    if (!draft) return;
    var pageTop = root.scrollTop;
    root.innerHTML =
      '<div class="pr-wf-editor">' + topBar() +
        '<div class="pr-wf-errors" id="prWfErrors" hidden></div>' +
        (tab === "editor"
          ? '<div class="pr-wf-body' + (openMenu ? " is-picking" : "") + '"><div class="pr-wf-canvaswrap">' +
              '<div class="pr-wf-canvas">' + canvas() + "</div>" + selBar() + zoomBar() + "</div>" +
            (openMenu ? '<div class="pr-pick__veil" data-pick-cancel="1"></div>' + pickerPanel() : sidePanel()) + "</div>"
          : historyView()) +
      "</div>";
    bind();
    markPicked();
    if (root.querySelector(".pr-wf-canvas")) {
      if (centerNext || panX == null) { centerView(); centerNext = false; }
      else applyView();
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
        ? (d.id ? '<button type="button" class="pr-btn" data-act="duplicate" title="Duplicar: abre una copia para editar y guardar"><i class="fa-regular fa-copy"></i> Duplicar</button>' : "") +
          (d.id ? '<button type="button" class="pr-btn pr-btn--danger" data-act="delete" title="Borrar"><i class="fa-regular fa-trash-can"></i></button>' : "") +
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

  /* El «+» sólo marca dónde va el paso: el selector vive en el panel lateral
     (pickerPanel), como el «Elegir una acción» de HubSpot. */
  function plus(ptr, isEnd) {
    if (!canEdit) return "";
    var open = openMenu === ptr;
    return '<div class="pr-wf-plus-wrap" data-ptr="' + ptr + '"' + (isEnd ? ' data-end="1"' : "") + ">" +
      '<button type="button" class="pr-wf-plus' + (open ? " is-open" : "") + '" data-plus="' + ptr + '" title="Agregar un paso"><i class="fa-solid fa-plus"></i></button>' +
      "</div>";
  }

  /* ---------- Panel «Elegir una acción» ---------- */
  var GROUP_ICON_FALLBACK = "fa-solid fa-bolt";
  function pickerIsEnd() { return !!openMenu && !getPtr(openMenu); }
  function pickerPanel() {
    var head = function (title, back) {
      return '<div class="pr-pick__head">' +
        (back ? '<button type="button" class="pr-pick__back" data-pick-view="home" title="Volver"><i class="fa-solid fa-chevron-left"></i></button>' : "") +
        '<h3 class="pr-pick__title">' + esc(title) + "</h3>" +
        '<button type="button" class="pr-btn pr-pick__cancel" data-pick-cancel="1">Cancelar</button></div>';
    };
    var body;
    if (pickerView === "delay") {
      var dk = S().delays || {};
      body = head("Retraso", true) +
        '<p class="pr-pick__lead">Esperar antes del próximo paso, basado en:</p>' +
        '<div class="pr-pick__opts">' + keysOf("delays").map(function (k) {
          return '<button type="button" class="pr-pick__opt" data-ins="delay" data-ins-type="' + k + '">' +
            '<span class="pr-pick__opt-title">' + esc(dk[k].title || dk[k].label) + "</span>" +
            '<span class="pr-pick__opt-ex">' + esc(dk[k].example || "") + "</span></button>";
        }).join("") + "</div>";
    } else if (pickerView === "branch") {
      var bk = S().branches || {};
      var icons = { value: "fa-solid fa-list-check", conditions: "fa-solid fa-circle-nodes", random: "fa-solid fa-shuffle" };
      body = head("Ramificación", true) +
        '<p class="pr-pick__lead">Enviar ' + (curObj === "contact" ? "contactos" : "empresas") + " a ramificaciones basado en:</p>" +
        '<div class="pr-pick__bcards">' + keysOf("branches").map(function (k) {
          // `example` viene del backend (constants.BRANCHES) con <b> para resaltar: es texto fijo nuestro.
          return '<button type="button" class="pr-pick__bcard" data-ins="branch" data-ins-type="' + k + '">' +
            '<span class="pr-pick__bicon pr-pick__bicon--' + k + '"><i class="' + (icons[k] || "fa-solid fa-code-branch") + '"></i></span>' +
            '<span class="pr-pick__btext"><strong>' + esc(bk[k].title || bk[k].label) + "</strong>" +
            "<span>" + String(bk[k].example || "").replace(/<(?!\/?b>)[^>]*>/g, "") + "</span></span></button>";
        }).join("") + "</div>";
    } else {
      var acts = S().actions || {}, ag = actionGroups(), meta = {};
      (S().action_groups || []).forEach(function (g) { meta[g.key] = g; });
      var apps = S().action_apps || {};
      var isEnd = pickerIsEnd();
      var tile = function (attrs, icon, label, disabled, tip) {
        return '<button type="button" class="pr-pick__tile"' + attrs + (disabled ? " disabled" : "") + (tip ? ' title="' + esc(tip) + '"' : "") + ">" +
          '<span class="pr-pick__tile-icon"><i class="' + icon + '"></i></span><span>' + label + "</span></button>";
      };
      var card = function (k, color) {
        var a = acts[k];
        return '<button type="button" class="pr-pick__act pr-pick__act--' + color + '" data-ins="action" data-ins-type="' + k + '"' +
          ' data-search="' + esc((a.label + " " + (a.desc || "") + " " + (a.app || "")).toLowerCase()) + '">' +
          '<span class="pr-pick__act-title">' + esc(a.label) + "</span>" +
          (a.desc ? '<span class="pr-pick__act-desc">' + esc(a.desc) + "</span>" : "") + "</button>";
      };
      var order = (S().action_groups || []).map(function (g) { return g.key; }).filter(function (g) { return ag.groups[g]; });
      ag.order.forEach(function (g) { if (order.indexOf(g) === -1) order.push(g); });
      body = head("Elegir una acción", false) +
        '<div class="pr-pick__search"><input type="search" id="prWfPickQ" class="pr-filter__input" placeholder="Buscar una acción" autocomplete="off">' +
          '<i class="fa-solid fa-magnifying-glass"></i></div>' +
        pasteBlock() +
        '<div class="pr-pick__tiles">' +
          tile(' data-pick-view="delay"', "fa-solid fa-stopwatch", "Retraso") +
          tile(' data-pick-view="branch"', "fa-solid fa-sitemap", "Ramificación") +
          tile(' data-ins="action" data-ins-type="enroll_workflow"', "fa-solid fa-arrow-right-to-bracket", "Ir a workflow") +
          tile(' data-ins="goto"', "fa-solid fa-turn-up", "Ir a acción", !isEnd,
               isEnd ? "Saltar a un paso que ya existe" : "Sólo al final de una rama: elegí el «+» de abajo de todo") +
        "</div>" +
        '<p class="pr-pick__empty" id="prWfPickEmpty" hidden>Ninguna acción coincide con la búsqueda.</p>' +
        '<div class="pr-pick__groups">' + order.map(function (g) {
          var m = meta[g] || { icon: GROUP_ICON_FALLBACK, color: "violet", desc: "" };
          var keys = ag.groups[g];
          var inner;
          if (g === "Aplicaciones integradas") {
            // Una sub-sección por aplicación, como en HubSpot.
            var byApp = {}, appOrder = [];
            keys.forEach(function (k) { var ap = acts[k].app || "Otras"; if (!byApp[ap]) { byApp[ap] = []; appOrder.push(ap); } byApp[ap].push(k); });
            inner = appOrder.map(function (ap) {
              return '<div class="pr-pick__app" data-app-block="1"><div class="pr-pick__app-head"><span class="pr-pick__app-icon"><i class="' +
                ((apps[ap] || {}).icon || GROUP_ICON_FALLBACK) + '"></i></span><strong>' + esc(ap) + "</strong></div>" +
                byApp[ap].map(function (k) { return card(k, m.color); }).join("") + "</div>";
            }).join("");
          } else inner = keys.map(function (k) { return card(k, m.color); }).join("");
          return '<details class="pr-pick__group" data-group="1">' +
            '<summary><i class="fa-solid fa-chevron-right pr-pick__chev"></i>' +
              '<span class="pr-pick__gicon pr-pick__gicon--' + m.color + '"><i class="' + m.icon + '"></i></span>' +
              '<span class="pr-pick__gtext"><strong>' + esc(g) + "</strong><span>" + esc(m.desc || "") + "</span></span></summary>" +
            '<div class="pr-pick__list">' + inner + "</div></details>";
        }).join("") + "</div>";
    }
    return '<aside class="pr-wf-side pr-pick" data-ptr="' + esc(openMenu) + '" role="dialog" aria-label="Elegir una acción">' + body + "</aside>";
  }
  /* Buscar: filtra las tarjetas en el DOM (sin redibujar, así no se pierde el foco). */
  function filterPicker(q) {
    var panel = root.querySelector(".pr-pick");
    if (!panel) return;
    q = (q || "").trim().toLowerCase();
    var any = false;
    panel.querySelectorAll("[data-group]").forEach(function (g) {
      var hits = 0;
      g.querySelectorAll("[data-search]").forEach(function (c) {
        var ok = !q || c.getAttribute("data-search").indexOf(q) !== -1;
        c.hidden = !ok;
        if (ok) hits++;
      });
      g.querySelectorAll("[data-app-block]").forEach(function (b) {
        b.hidden = !!q && !b.querySelector("[data-search]:not([hidden])");
      });
      g.hidden = !!q && !hits;
      if (q) g.open = hits > 0;
      if (hits) any = true;
    });
    var tiles = panel.querySelector(".pr-pick__tiles");
    if (tiles) tiles.hidden = !!q;
    var empty = $("prWfPickEmpty");
    if (empty) empty.hidden = !q || any;
  }
  function closePicker() { openMenu = null; pickerView = "home"; render(); }
  /* El panel vive dentro de #prWorkflows, que es el que scrollea (no la ventana): su alto
     tiene que salir del espacio visible de ESE contenedor, o el final queda tapado y no
     se puede llegar scrolleando adentro del panel. */
  function fitPicker() {
    var panel = root && root.querySelector(".pr-pick");
    if (!panel) return;
    if (window.matchMedia("(max-width: 1100px)").matches) { panel.style.maxHeight = ""; return; }
    var box = root.getBoundingClientRect();
    var bottom = Math.min(box.bottom, window.innerHeight);
    var top = Math.max(panel.getBoundingClientRect().top, box.top);
    panel.style.maxHeight = Math.max(240, bottom - top - 12) + "px";
  }
  var fitBound = false;
  function bindFit() {
    if (fitBound || !root) return;
    fitBound = true;
    root.addEventListener("scroll", fitPicker, { passive: true });
    window.addEventListener("resize", fitPicker);
  }

  function nodeHead(id, num, icon, title, cls) {
    return '<div class="pr-wf-node__head">' +
      (canEdit ? '<label class="pr-wf-pickbox" title="Seleccionar para duplicar o copiar a otro workflow">' +
        '<input type="checkbox" data-pick-node="' + id + '"' + (picked[id] ? " checked" : "") + "></label>" : "") +
      '<span class="pr-wf-node__icon ' + (cls || "") + '"><i class="' + icon + '"></i></span>' +
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

  /* «?» del operador: la columna «Qué comprueba» del doc de la owner (constants.OPERATOR_HELP).
     En selección, «No contiene ninguno de» tiene su propia frase (help_select). */
  function opHelp(op, f) {
    var od = opDef(op);
    var sel = f && ["enum", "owner", "user", "multi"].indexOf(f.type) !== -1;
    return (sel && od.help_select) || od.help || "";
  }
  function helpBadge(op, f) {
    var tip = opHelp(op, f);
    if (!tip) return "";
    var od = opDef(op);
    tip += od.help_src === "hub" ? " (no está en el doc)" : "";
    return '<span class="pr-wf-help" tabindex="0" role="button" aria-label="¿Qué hace «' + esc(od.label) + '»?" ' +
      'data-help-label="' + esc(od.label) + '" data-help-tip="' + esc(tip) + '">?</span>';
  }

  /* Globo del «?»: un elemento en <body> con position: fixed, así no lo recorta el drawer
     de Advanced filters (overflow) ni el lienzo del workflow. Click lo fija; hover lo
     muestra; click afuera, Esc, scroll o redibujo lo cierran. */
  var helpTipEl = null, helpTipFor = null, helpTipPinned = false;
  function hideHelpTip() {
    if (helpTipEl) helpTipEl.hidden = true;
    helpTipFor = null;
    helpTipPinned = false;
  }
  function showHelpTip(badge, pin) {
    if (!helpTipEl) {
      helpTipEl = document.createElement("div");
      helpTipEl.className = "pr-wf-tip";
      helpTipEl.setAttribute("role", "tooltip");
      document.body.appendChild(helpTipEl);
    }
    helpTipEl.innerHTML = "";
    var b = document.createElement("strong");
    b.textContent = badge.getAttribute("data-help-label");
    var t = document.createElement("span");
    t.textContent = badge.getAttribute("data-help-tip");
    helpTipEl.appendChild(b);
    helpTipEl.appendChild(t);
    helpTipEl.hidden = false;
    var r = badge.getBoundingClientRect(), w = helpTipEl.offsetWidth, h = helpTipEl.offsetHeight;
    var left = Math.max(8, Math.min(r.right - w, window.innerWidth - w - 8));
    var top = r.bottom + 8 + h > window.innerHeight - 8 ? r.top - h - 8 : r.bottom + 8;
    helpTipEl.style.left = left + "px";
    helpTipEl.style.top = Math.max(8, top) + "px";
    helpTipFor = badge;
    helpTipPinned = !!pin;
  }
  document.addEventListener("click", function (e) {
    var badge = e.target.closest && e.target.closest(".pr-wf-help");
    if (!badge) { if (helpTipFor) hideHelpTip(); return; }
    e.stopPropagation();
    if (helpTipFor === badge && helpTipPinned) hideHelpTip();
    else showHelpTip(badge, true);
  }, true);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && openMenu && draft) { e.preventDefault(); closePicker(); }
  });
  document.addEventListener("mouseover", function (e) {
    var badge = e.target.closest && e.target.closest(".pr-wf-help");
    if (badge && !helpTipPinned) showHelpTip(badge, false);
  });
  document.addEventListener("mouseout", function (e) {
    var badge = e.target.closest && e.target.closest(".pr-wf-help");
    if (badge && !helpTipPinned && !badge.contains(e.relatedTarget)) hideHelpTip();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { hideHelpTip(); return; }
    var badge = document.activeElement;
    if ((e.key === "Enter" || e.key === " ") && badge && badge.classList && badge.classList.contains("pr-wf-help")) {
      e.preventDefault();
      if (helpTipFor === badge && helpTipPinned) hideHelpTip(); else showHelpTip(badge, true);
    }
  });
  window.addEventListener("scroll", function () { if (helpTipFor) hideHelpTip(); }, true);

  /* Topes de rules.py (MAX_RULES / MAX_GROUPS): duplicar no puede pasarlos. */
  var MAX_RULES = 20, MAX_GROUPS = 10;
  /* Duplicar una condición (queda debajo, es un «y») o un grupo (queda después, es un «o»).
     Lo usan el editor de workflows y Advanced filters. true = era un botón de duplicar. */
  function duplicateCond(b) {
    var v, p, ref;
    if ((v = b.getAttribute("data-rdup")) !== null) {
      p = v.split("|");
      ref = condRef(p[0], false);
      var rules = ref.conds.groups[Number(p[1])].rules;
      if (rules.length < MAX_RULES) rules.splice(Number(p[2]) + 1, 0, clone(rules[Number(p[2])]));
      return true;
    }
    if ((v = b.getAttribute("data-gdup")) !== null) {
      p = v.split("|");
      ref = condRef(p[0], false);
      if (ref.conds.groups.length < MAX_GROUPS) ref.conds.groups.splice(Number(p[1]) + 1, 0, clone(ref.conds.groups[Number(p[1])]));
      return true;
    }
    return false;
  }

  /* ---------- Editor de condiciones (reusado en todos lados) ---------- */
  function conditionsEditor(key, conds, compact) {
    conds = conds || { groups: [] };
    var groups = (conds.groups || []).map(function (g, gi) {
      var rules = (g.rules || []).map(function (r, ri) {
        var f = field(r.field);
        var opOptions = ((S().operators_by_type || {})[f ? f.type : "text"] || []).filter(function (o) {
          return !(f && f.history === false && opDef(o).history);  // sin historial (negocios): sin «alguna vez…»
        }).map(function (o) {
          return '<option value="' + esc(o) + '"' + (o === r.op ? " selected" : "") + ">" +
            esc(opDef(o).label) + "</option>";
        }).join("");
        var path = key + "|" + gi + "|" + ri;
        return (ri ? '<div class="pr-wf-joiner">y</div>' : "") +
          '<div class="pr-wf-rule"><div class="pr-wf-rule__row"><div class="pr-wf-rule__sel">' +
            '<select class="pr-filter__input" data-rfield="' + path + '"' + dis() + ">" + fieldOptions(r.field, null, true, true) + "</select>" +
            '<select class="pr-filter__input" data-rop="' + path + '"' + dis() + ">" + opOptions + "</select></div>" +
            helpBadge(r.op, f) +
            (canEdit && g.rules.length < MAX_RULES ? '<button type="button" class="pr-wf-x" data-rdup="' + path + '" title="Duplicar condición"><i class="fa-regular fa-copy"></i></button>' : "") +
            (canEdit ? '<button type="button" class="pr-wf-x" data-rdel="' + path + '" title="Quitar condición"><i class="fa-solid fa-xmark"></i></button>' : "") +
          "</div>" + ruleValue(r, path) + "</div>";
      }).join("");
      return (gi ? '<div class="pr-wf-or-sep"><span>o</span></div>' : "") +
        '<div class="pr-wf-group' + (compact ? " pr-wf-group--compact" : "") + '">' +
          '<div class="pr-wf-group__head">Grupo ' + (gi + 1) +
            (canEdit && conds.groups.length < MAX_GROUPS ? '<button type="button" class="pr-wf-link" data-gdup="' + key + "|" + gi + '"><i class="fa-regular fa-copy"></i> Duplicar grupo</button>' : "") +
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

  /* Aclaración SIEMPRE visible debajo de los valores: varias opciones marcadas en UNA
     condición son «o» (o «y» en los «todos de»). Con 2+ marcadas, la frase las nombra. */
  var HINT_ANY = { is_any: "es", ever_was: "alguna vez fue", equals_any: "es igual a", contains: "contiene",
    starts_with: "comienza con", ends_with: "termina con", ever_equals_any: "alguna vez fue igual a" };
  var HINT_NONE = { is_none_of: "no es", not_contains: "no contiene", never_was: "nunca fue",
    not_equals_any: "no es igual a", never_equals_any: "nunca fue igual a" };
  var HINT_ALL = { contains_all: "tiene", equals_all: "tiene exactamente" };
  var HINT_NOT_ALL = { not_contains_all: "", not_equals_all: "exactamente " };
  function ruleHint(r, f, freeText) {
    var op = r.op, out = "";
    var vals = (Array.isArray(r.value) ? r.value : []).map(function (x) { return "<em>" + esc(choiceLabel(f, x)) + "</em>"; });
    var O = ' <strong>o</strong> ', Y = ' <strong>y</strong> ';
    if (freeText) {
      if (HINT_ANY[op]) out = "Un valor por línea · cumple con cualquiera (<strong>o</strong>).";
      else if (HINT_NONE[op]) out = "Un valor por línea · cumple si no coincide con ninguno.";
    } else if (vals.length < 2) {
      if (HINT_ANY[op]) out = "Podés marcar varias: cumple con <strong>cualquiera</strong> de las marcadas (<strong>o</strong>).";
      else if (HINT_NONE[op]) out = "Podés marcar varias: cumple si no es <strong>ninguna</strong> de las marcadas.";
      else if (HINT_ALL[op]) out = "Podés marcar varias: cumple si tiene <strong>todas</strong> las marcadas (<strong>y</strong>).";
      else if (op in HINT_NOT_ALL) out = "Podés marcar varias: cumple salvo que tenga <strong>todas</strong> las marcadas juntas.";
    } else {
      if (HINT_ANY[op]) out = "Cumple si " + HINT_ANY[op] + " " + vals.join(O) + ".";
      else if (HINT_NONE[op]) out = "Cumple si " + HINT_NONE[op] + " ninguno: " + vals.join(", ") + ".";
      else if (HINT_ALL[op]) out = "Cumple si " + HINT_ALL[op] + " " + vals.join(Y) + ".";
      else if (op in HINT_NOT_ALL) out = "Cumple salvo que tenga " + HINT_NOT_ALL[op] + vals.join(Y) + " juntas.";
    }
    return out ? '<p class="pr-wf-rule-hint">' + out + "</p>" : "";
  }


  function ruleValue(r, path) {
    var f = field(r.field);
    var kind = opDef(r.op).value;
    var v = r.value;
    if (!kind) return "";
    if (kind === "list") {
      if (f && (choices(f).length || ["enum", "owner", "user", "multi"].indexOf(f.type) !== -1))
        return chips(choices(f), v || [], 'data-rchip="' + path + '"') + ruleHint(r, f, false);
      // Texto libre («Contiene cualquiera de», «Es igual a cualquiera de»…): uno por línea.
      // La aclaración es fija: el textarea no redibuja mientras se escribe.
      return '<textarea class="pr-filter__input pr-wf-list" rows="2" data-val="' + path + '" data-list="1" placeholder="Un valor por línea…"' + dis() + ">" +
        esc((Array.isArray(v) ? v : []).join("\n")) + "</textarea>" + ruleHint(r, f, true);
    }
    if (kind === "period") {
      return '<select class="pr-filter__input" data-val="' + path + '"' + dis() + ">" + optionTags(S().periods || [], v) + "</select>";
    }
    if (kind === "field") {
      var others = otherFields(f, r.op).map(function (x) { return { value: x.key, label: x.label }; });
      return '<select class="pr-filter__input" data-val="' + path + '"' + dis() + '><option value="">Elegí una propiedad…</option>' + optionTags(others, v) + "</select>";
    }
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
    var gm = (S().action_groups || []).filter(function (g) { return g.key === meta.group; })[0] || {};
    var appIcon = meta.app && ((S().action_apps || {})[meta.app] || {}).icon;
    return '<div class="pr-wf-node pr-wf-node--action' + (gm.color ? " pr-wf-node--g-" + gm.color : "") + '">' +
      nodeHead(id, num, appIcon || gm.icon || "fa-regular fa-pen-to-square", esc(meta.app || meta.group || "Acción"), gm.color ? "pr-wf-node__icon--g-" + gm.color : "") +
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
  /* «Insertar propiedad»: agrega {campo:clave} al final del texto `key` de la acción. */
  function tokenPicker(id, key) {
    return '<div class="pr-wf-row"><span class="pr-wf-lbl">Insertar propiedad</span><select class="pr-filter__input" data-token-node="' + id + '" data-token-key="' + key + '"' + dis() + '><option value="">Elegir…</option>' +
      fieldOptions("", null, curObj === "contact") + "</select></div>";
  }
  function isPersonField(f) { return f.type === "user" || f.type === "owner"; }
  var TOKENS_COMPANY = '<p class="pr-note pr-wf-tokens">Podés usar: {empresa} {dominio} {owner} {status} {semana} {not_icp} {link} · y cualquier propiedad con {campo:clave}</p>';
  var TOKENS_CONTACT = '<p class="pr-note pr-wf-tokens">Podés usar: {contacto} {email_contacto} {empresa} {owner} {status} {link} · y cualquier propiedad con {campo:clave}</p>';
  var TOKENS = TOKENS_COMPANY;

  /* Filas propiedad = valor de «Crear registro» (contacto o negocio), sobre `a.values`.
     `minRows`: cuántas filas quedan sin botón de quitar. */
  function valueRows(id, a, cfs, minRows) {
    return (a.values || []).map(function (it, i) {
            var cf = cfs.filter(function (x) { return x.key === it.field; })[0];
            var valInput;
            if (cf && (cf.type === "enum" || cf.type === "owner" || cf.type === "user")) {
              valInput = '<select class="pr-filter__input" data-cc="' + id + "|" + i + '|value"' + dis() + '><option value="">Elegir…</option>' + optionTags(choices(cf), it.value) + "</select>";
            } else if (cf && cf.type === "bool") {
              valInput = '<select class="pr-filter__input" data-cc="' + id + "|" + i + '|value"' + dis() + ">" +
                optionTags([{ value: "", label: "Elegir…" }, { value: "true", label: "Sí" }, { value: "false", label: "No" }], it.value === true ? "true" : it.value === false ? "false" : (it.value || "")) + "</select>";
            } else {
              var ty = cf && (cf.type === "date" ? "date" : cf.type === "number" ? "number" : "text");
              valInput = '<input type="' + (ty || "text") + '" class="pr-filter__input" data-cc="' + id + "|" + i + '|value" value="' + esc(it.value == null ? "" : it.value) + '" placeholder="Valor (admite {empresa}…)"' + dis() + ">";
            }
            return '<div class="pr-wf-kv"><select class="pr-filter__input" data-cc="' + id + "|" + i + '|field"' + dis() + '><option value="">Propiedad…</option>' +
              optionTags(cfs.filter(function (x) { return x.type !== "multi" && x.type !== "datetime"; }).map(function (x) { return { value: x.key, label: x.label }; }), it.field) + "</select>" +
              valInput + (canEdit && (a.values || []).length > minRows ? '<button type="button" class="pr-wf-x" data-cc-del="' + id + "|" + i + '" title="Quitar"><i class="fa-solid fa-xmark"></i></button>' : "") + "</div>";
          }).join("") +
          (canEdit ? '<button type="button" class="pr-wf-add" data-cc-add="' + id + '"><i class="fa-solid fa-plus"></i> Agregar propiedad</button>' : "");
  }

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
      if (a.type === "format_phone") {
        html += '<div class="pr-wf-full"><span class="pr-wf-lbl">País si el número no trae código (+…)</span>' +
          '<select class="pr-filter__input" data-a="country" data-node="' + id + '"' + dis() + ">" + optionTags(S().phone_countries || [], a.country) + "</select>" +
          '<p class="pr-note">Lo deja como <em>+54 9 11 5555-1234</em>. Si no es un número válido no lo toca y queda anotado en el historial del paso.</p></div>';
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
        return '<div class="pr-wf-full">' + area(id, "text", a.text, "Mensaje") + tokenPicker(id, "text") +
          inp(id, "channel", a.channel, "text", ' placeholder="Canal (id C0…). Vacío = el canal por defecto del Hub"') +
          '<div class="pr-wf-row"><span class="pr-wf-lbl">Mencionar a</span><select class="pr-filter__input" data-a="mention_field" data-node="' + id + '"' + dis() + ">" +
            '<option value="">Nadie</option>' + fieldOptions(a.mention_field || "", isPersonField, curObj === "contact") + "</select></div>" +
          '<p class="pr-note">La persona de esa propiedad recibe una @mención al principio del mensaje. Con registros de prueba sólo sale su nombre.</p>' +
          TOKENS + "</div>";
      case "add_note":
        return '<div class="pr-wf-full">' + area(id, "text", a.text, "Nota para el historial de la empresa") + TOKENS + "</div>";
      case "webhook":
        return '<div class="pr-wf-full">' + inp(id, "url", a.url, "url", ' placeholder="https://…"') +
          '<p class="pr-note">Manda un POST con los datos de la empresa. Sobre empresas dummy se registra y no se manda.</p></div>';
      case "ask_ai":
        return '<div class="pr-wf-full">' + area(id, "prompt", a.prompt, "Qué le preguntás. Ej.: ¿A qué se dedica {empresa} ({dominio})? Respondé en una frase.") +
          tokenPicker(id, "prompt") +
          '<span class="pr-wf-lbl">Guardar la respuesta en</span><select class="pr-filter__input" data-a="field" data-node="' + id + '"' + dis() + ">" +
            optionTags(aiTargets(), a.field) + "</select>" + TOKENS +
          '<p class="pr-note">Usa ' + esc(S().ai_model || "gpt-4o-mini") + '. En la prueba y la vista previa no se llama a la IA.</p></div>';
      case "create_contact":
        return '<div class="pr-wf-full"><span class="pr-wf-lbl">Propiedades del contacto nuevo</span>' +
          valueRows(id, a, objFields("contact"), 1) +
          TOKENS + '<p class="pr-note">Se crea dentro de la empresa (si es dummy, el contacto también). Si el email ya existe en otro contacto, el paso falla y queda en el historial.</p></div>';
      case "create_deal":
        var stageF = objFields("deal").filter(function (x) { return x.key === "stage"; })[0];
        var dealFs = objFields("deal").filter(function (x) { return x.storage !== "expr" && x.key !== "name" && x.key !== "owner_email"; });
        return '<div class="pr-wf-full">' +
          '<span class="pr-wf-lbl">Pipeline y etapa del negocio</span><select class="pr-filter__input" data-a="deal_stage" data-node="' + id + '"' + dis() + ">" +
            optionTags(choices(stageF), (a.pipeline_key || "") + ":" + (a.stage_key || "")) + "</select>" +
          '<span class="pr-wf-lbl">Asignar negocio a</span><select class="pr-filter__input" data-a="owner_email" data-node="' + id + '"' + dis() + '><option value="">Nadie</option>' +
            optionTags(choices({ type: "user" }), a.owner_email || "") + "</select>" +
          '<span class="pr-wf-lbl">Nombre del negocio</span>' + inp(id, "name", a.name, "text", ' placeholder="Ej.: {campo:company_name}"') + tokenPicker(id, "name") +
          '<span class="pr-wf-lbl">Más propiedades (opcional)</span>' + valueRows(id, a, dealFs, 0) +
          TOKENS + '<p class="pr-note">El negocio queda asociado al ' + (curObj === "contact" ? "contacto y a su empresa" : "registro") +
          '. Se crea uno nuevo cada vez que el paso corre. Con registros de prueba, el negocio también es de prueba.</p></div>';
      case "sheets_append":
        var sa = S().sheets_service_account;
        return '<div class="pr-wf-full">' +
          inp(id, "spreadsheet", a.spreadsheet, "text", ' placeholder="Link del Google Sheet"') +
          '<div class="pr-wf-row"><span class="pr-wf-lbl">Pestaña</span>' + inp(id, "sheet", a.sheet, "text", ' placeholder="Hoja 1"') + "</div>" +
          '<span class="pr-wf-lbl">Columnas (A, B, C…)</span>' +
          (a.columns || []).map(function (c, i) {
            var letter = String.fromCharCode(65 + (i % 26));
            var isText = !("field" in c);
            return '<div class="pr-wf-kv"><span class="pr-wf-col-letter">' + letter + "</span>" +
              '<select class="pr-filter__input" data-sc="' + id + "|" + i + '|kind"' + dis() + ">" +
                '<option value="__text__"' + (isText ? " selected" : "") + ">Texto fijo…</option>" + fieldOptions(isText ? "" : c.field, null, curObj === "contact") + "</select>" +
              (isText ? '<input type="text" class="pr-filter__input" data-sc="' + id + "|" + i + '|text" value="' + esc(c.text || "") + '" placeholder="Texto (admite {tokens})"' + dis() + ">" : "") +
              (canEdit && (a.columns || []).length > 1 ? '<button type="button" class="pr-wf-x" data-sc-del="' + id + "|" + i + '" title="Quitar"><i class="fa-solid fa-xmark"></i></button>' : "") + "</div>";
          }).join("") +
          (canEdit ? '<button type="button" class="pr-wf-add" data-sc-add="' + id + '"><i class="fa-solid fa-plus"></i> Agregar columna</button>' : "") + TOKENS +
          '<p class="pr-note">Compartí el Sheet como <strong>editor</strong> con ' +
            (sa ? '<code>' + esc(sa) + '</code> <button type="button" class="pr-btn pr-btn--sm" data-copy-sa="' + esc(sa) + '"><i class="fa-regular fa-copy"></i> Copiar</button>'
                : "la service account de Google del Hub") +
          ". Sobre registros dummy la fila no se escribe.</p></div>";
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
        ? '<button type="button" class="pr-btn pr-btn--danger" data-unenroll="' + (d.contact_id || d.company_id) + '">Sacar del workflow</button>' : "") +
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
    r.value = kind === "list" ? [] : (kind === "number_range" || kind === "date_range") ? ["", ""]
      : kind === "period" ? ((S().periods || [])[0] || {}).value || "today" : "";
  }
  function listValue(text) {
    return String(text || "").split("\n").map(function (x) { return x.trim(); }).filter(Boolean);
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
    bindZoom();
    bindFit();
    fitPicker();
    var pq = $("prWfPickQ");
    if (pq) {
      pq.addEventListener("input", function () { filterPicker(pq.value); });
      pq.addEventListener("keydown", function (e) {
        if (e.key !== "Enter") return;
        var first = root.querySelector(".pr-pick [data-search]:not([hidden])");
        if (first && pq.value.trim()) { e.preventDefault(); first.click(); }
      });
      try { pq.focus({ preventScroll: true }); } catch (e) { pq.focus(); }
    }
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
      else if (el.hasAttribute("data-list")) r.value = listValue(el.value);
      else r.value = el.value;
      markDirty();
      return;
    }
    if (el.tagName !== "SELECT" && el.type !== "checkbox" && (a = el.getAttribute("data-a"))) {
      setActionParam(draft.steps.nodes[el.getAttribute("data-node")].action, a, el.value);
      markDirty();
      return;
    }
    if (el.tagName === "INPUT" && (a = el.getAttribute("data-cc"))) {
      var cp = a.split("|");
      draft.steps.nodes[cp[0]].action.values[Number(cp[1])].value = el.value;
      markDirty();
      return;
    }
    if (el.tagName === "INPUT" && (a = el.getAttribute("data-sc"))) {
      var sp = a.split("|");
      draft.steps.nodes[sp[0]].action.columns[Number(sp[1])].text = el.value;
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
    } else if (key === "deal_stage") {  // "<pipeline>:<etapa>" → los dos parámetros del negocio
      var ps = String(value).split(":");
      act.pipeline_key = ps[0] || ""; act.stage_key = ps.slice(1).join(":");
    } else act[key] = value;
  }

  /* Selects y checkboxes: cambian la forma de la tarjeta → redibujar. */
  function onChange(e) {
    var el = e.target, a, n;
    if ((a = el.getAttribute("data-pick-node"))) {
      if (el.checked) picked[a] = true; else delete picked[a];
      return render();
    }
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
    } else if ((a = el.getAttribute("data-cc")) && el.tagName === "SELECT") {
      var cp = a.split("|"), it = draft.steps.nodes[cp[0]].action.values[Number(cp[1])];
      if (cp[2] === "field") { it.field = el.value; it.value = ""; }
      else it.value = el.value === "true" ? true : el.value === "false" ? false : el.value;
    } else if ((a = el.getAttribute("data-sc")) && el.tagName === "SELECT") {
      var sp = a.split("|"), cols = draft.steps.nodes[sp[0]].action.columns;
      cols[Number(sp[1])] = el.value === "__text__" ? { text: "" } : { field: el.value };
    } else if ((a = el.getAttribute("data-token-node"))) {
      if (!el.value) return;
      var tn = draft.steps.nodes[a].action, tk = el.getAttribute("data-token-key") || "prompt";
      tn[tk] = (tn[tk] || "") + (tn[tk] && !/\s$/.test(tn[tk]) ? " " : "") + "{campo:" + el.value + "}";
    } else if ((a = el.getAttribute("data-d"))) {
      n = draft.steps.nodes[el.getAttribute("data-node")];
      if (a === "kind") {
        n.delay = delayDefaults(el.value);
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
      if (e.target.closest("[data-pick-cancel]")) closePicker();
      return;
    }
    var v, p, ref;
    var act = b.getAttribute("data-act");
    if (act === "back") return closeEditor();
    if (act === "save") return save().catch(function () {});
    if (act === "delete") return remove();
    if (act === "duplicate") return duplicateWorkflow(null);
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
    if ((v = b.getAttribute("data-zoom")) !== null) {
      if (v === "in") stepZoom(1); else if (v === "out") stepZoom(-1); else if (v === "fit") fitZoom(); else setZoom(1);
      return;
    }
    if ((v = b.getAttribute("data-sel")) !== null) return selAction(v);
    if ((v = b.getAttribute("data-plus")) !== null) { openMenu = openMenu === v ? null : v; pickerView = "home"; return render(); }
    if (b.getAttribute("data-pick-cancel") !== null) return closePicker();
    if ((v = b.getAttribute("data-pick-view")) !== null) { pickerView = v; return render(); }
    if ((v = b.getAttribute("data-cc-add")) !== null) {
      draft.steps.nodes[v].action.values.push({ field: "", value: "" });
    } else if ((v = b.getAttribute("data-cc-del")) !== null) {
      p = v.split("|");
      draft.steps.nodes[p[0]].action.values.splice(Number(p[1]), 1);
    } else if ((v = b.getAttribute("data-sc-add")) !== null) {
      draft.steps.nodes[v].action.columns.push({ field: curObj === "contact" ? "email" : "name" });
    } else if ((v = b.getAttribute("data-sc-del")) !== null) {
      p = v.split("|");
      draft.steps.nodes[p[0]].action.columns.splice(Number(p[1]), 1);
    } else if ((v = b.getAttribute("data-copy-sa")) !== null) {
      if (navigator.clipboard) navigator.clipboard.writeText(v);
      b.innerHTML = '<i class="fa-solid fa-check"></i> Copiado';
      return;
    } else if ((v = b.getAttribute("data-ins")) !== null) {
      var ptr = b.closest("[data-ptr]").getAttribute("data-ptr");
      openMenu = null;
      pickerView = "home";
      if (v === "goto") return chooseGoto(ptr);
      if (v === "paste") {
        var pc = readClip(), why = pc ? pasteBlocked(pc, ptr) : "No hay pasos copiados.";
        if (why) { alert(why); return render(); }
        pasteClip(ptr, pc);
        P.toast('<i class="fa-regular fa-clipboard"></i> Se pegaron <strong>' + pc.count + "</strong> paso" + (pc.count === 1 ? "" : "s") + ". Revisalos y guardá.");
      } else insertNode(ptr, v, b.getAttribute("data-ins-type"));
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
    } else if (duplicateCond(b)) {
      // ya hecho
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
    var body = payload();
    if (isNew) body.folder_id = curFolder;  // nace en la carpeta abierta
    return P.api(isNew ? "/prospecting/workflows" : "/prospecting/workflows/" + draft.id, {
      method: isNew ? "POST" : "PUT", body: JSON.stringify(body),
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

  var applying = false;
  function applyNow() {
    if (applying) return;  // un segundo click mientras corre inscribía todo dos veces
    var onlyDummy = $("prWfOnlyDummy").checked;
    if (!onlyDummy && !confirm("¿Inscribir también empresas REALES que cumplen hoy?")) return;
    applying = true;
    var btn = root.querySelector('[data-act="apply"]');
    if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Inscribiendo…'; }
    var t0 = Date.now(), timer = null;
    var stop = function () {
      applying = false;
      clearInterval(timer);
      var b2 = root.querySelector('[data-act="apply"]');
      if (b2) { b2.disabled = false; b2.innerHTML = '<i class="fa-solid fa-play"></i> Inscribir las que cumplen ahora'; }
    };
    // Como saveThen(), pero si el guardado falla suelta el bloqueo (si no, quedaba trabado).
    (dirty || !draft.id ? save() : Promise.resolve()).then(function () {
      var out = $("prWfPreviewOut");
      var tickOut = function () {
        var o = $("prWfPreviewOut"), secs = Math.floor((Date.now() - t0) / 1000);
        if (o) o.innerHTML = '<p class="pr-note"><i class="fa-solid fa-spinner fa-spin"></i> Inscribiendo y corriendo los pasos…' +
          (secs >= 2 ? " " + secs + " s" : "") + (secs >= 10 ? " · sigue trabajando, no cierres ni recargues la página." : "") + "</p>";
      };
      if (out) tickOut();
      timer = setInterval(tickOut, 1000);
      return P.api("/prospecting/workflows/" + draft.id + "/enroll", {
        method: "POST", body: JSON.stringify({ only_dummy: onlyDummy }),
      }).then(function (r) {
        stop();
        $("prWfPreviewOut").innerHTML = '<div class="pr-result"><h4>' + r.enrolled + " inscripta" + (r.enrolled === 1 ? "" : "s") + "</h4>" +
          '<p class="pr-note" style="margin:0">De ' + r.candidates + " que cumplían (las que ya estaban adentro no se repiten). " +
          (r.completed || 0) + " ya terminaron el workflow; el resto está esperando. Mirá el Historial.</p></div>";
        P.reloadTable();
      }).catch(function (err) { stop(); var o = $("prWfPreviewOut"); if (o) o.innerHTML = ""; showErrors(err); });
    }, stop);
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

  /* recordId = el contacto en un workflow de contactos (puede no tener empresa), la
     empresa en uno de empresas. Antes mandaba siempre la empresa: en los de contactos
     sacaba al contacto equivocado. */
  function unenroll(recordId) {
    if (!confirm("¿Sacarlo del workflow?")) return;
    P.api("/prospecting/workflows/" + draft.id + "/unenroll", {
      method: "POST", body: JSON.stringify({ record_ids: [recordId] }),
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

  /* =================================================================
     Filtros avanzados de la tabla de empresas (vistas guardadas).
     Reusa conditionsEditor() tal cual, con la clave "ext": condRef("ext") apunta a
     `ext.holder` en vez de al `draft` del editor, así el editor de workflows no
     cambia. Siempre sobre empresas y editable (filtrar no escribe nada).
     ================================================================= */
  var ext = null;  // { holder: {conditions}, el, onChange }

  function withExt(fn) {
    var saved = { obj: curObj, edit: canEdit };
    curObj = "company";
    canEdit = true;
    try { return fn(); } finally { curObj = saved.obj; canEdit = saved.edit; }
  }
  function renderExt() {
    ext.el.innerHTML = withExt(function () {
      return hasConds(ext.holder.conditions)
        ? conditionsEditor("ext", ext.holder.conditions, true)
        : '<p class="pr-note">No advanced filters yet.</p>' +
          '<button type="button" class="pr-wf-add" data-gadd="ext"><i class="fa-solid fa-plus"></i> Add a condition</button>';
    });
  }
  function extChanged(redraw) {
    if (redraw) renderExt();
    if (ext.onChange) ext.onChange(ext.holder.conditions);
  }
  function extClick(e) {
    var b = e.target.closest("button");
    if (!b || !ext) return;
    withExt(function () {
      var v, p, ref;
      if ((v = b.getAttribute("data-rchip")) !== null) {
        var x = ruleAt(v);
        x.rule.value = toggleIn(Array.isArray(x.rule.value) ? x.rule.value : [], b.getAttribute("data-chip"));
      } else if (duplicateCond(b)) {
        // ya hecho
      } else if ((v = b.getAttribute("data-radd")) !== null) {
        p = v.split("|");
        condRef("ext", true).conds.groups[Number(p[1])].rules.push(blankRule());
      } else if ((v = b.getAttribute("data-rdel")) !== null) {
        p = v.split("|");
        ref = condRef("ext", false);
        var g = ref.conds.groups[Number(p[1])];
        g.rules.splice(Number(p[2]), 1);
        if (!g.rules.length) ref.conds.groups.splice(Number(p[1]), 1);
        if (!ref.conds.groups.length) ref.holder.conditions = null;
      } else if ((v = b.getAttribute("data-gdel")) !== null) {
        p = v.split("|");
        condRef("ext", false).conds.groups.splice(Number(p[1]), 1);
      } else if (b.getAttribute("data-gadd") !== null) {
        ref = condRef("ext", false);
        if (!ref || !hasConds(ref.conds)) condRef("ext", true);
        else ref.conds.groups.push({ rules: [blankRule()] });
      } else return;
    });
    extChanged(true);
  }
  function extChange(e) {
    var el = e.target, a;
    if (!ext) return;
    if (el.tagName === "INPUT") return;  // lo toma extInput
    withExt(function () {
      if ((a = el.getAttribute("data-rfield"))) {
        var x = ruleAt(a);
        x.rule.field = el.value;
        x.rule.op = ((S().operators_by_type || {})[field(el.value).type] || [])[0];
        resetValue(x.rule);
      } else if ((a = el.getAttribute("data-rop"))) {
        var y = ruleAt(a), before = opDef(y.rule.op).value;
        y.rule.op = el.value;
        if (opDef(el.value).value !== before) resetValue(y.rule);
      }
    });
    extChanged(true);
  }
  function extInput(e) {
    var el = e.target, a;
    if (!ext || !(a = el.getAttribute("data-val"))) return;
    withExt(function () {
      var r = ruleAt(a).rule, vi = el.getAttribute("data-vi");
      if (vi !== null) { r.value = Array.isArray(r.value) ? r.value : ["", ""]; r.value[Number(vi)] = el.value; }
      else if (el.hasAttribute("data-list")) r.value = listValue(el.value);
      else r.value = el.value;
    });
    extChanged(false);  // sin redibujar: no perder el foco
  }

  /* Dibuja el armador en `el` sobre una COPIA de `conds`. onChange recibe las
     condiciones (o null) en cada cambio; nada se aplica hasta que la tabla lo pide. */
  function conditionsPanel(el, conds, onChange) {
    P = P || window.Prospecting;
    ext = { holder: { conditions: hasConds(conds) ? clone(conds) : null }, el: el, onChange: onChange };
    el.onclick = extClick;
    el.onchange = extChange;
    el.oninput = extInput;
    renderExt();
    return {
      get: function () { return ext && ext.el === el ? ext.holder.conditions : null; },
      clear: function () { if (ext && ext.el === el) { ext.holder.conditions = null; extChanged(true); } },
    };
  }
  function conditionsSummary(conds) {
    P = P || window.Prospecting;
    return withExt(function () { return conditionsText(conds); });
  }

  window.ProspectingWorkflows = {
    show: show, enrollCompanies: enrollCompanies, workflows: workflows,
    conditionsPanel: conditionsPanel, conditionsSummary: conditionsSummary,
  };
})();
