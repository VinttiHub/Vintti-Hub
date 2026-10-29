/* =====================================================================
   Prospecting — CRM de los BDRs (empresas desde Clay, sin HubSpot).

   Todo el filtrado y el paginado se hacen en el SERVIDOR
   (GET /prospecting/companies): el CRM de clientes carga todo de una y ya pesa.
   Las listas cerradas (status, Not ICP, sizes, BDRs) salen de
   GET /prospecting/options — no hay una segunda copia acá.

   Backend: backend/routes/prospecting_routes.py + backend/prospecting/.
   ===================================================================== */
(function () {
  "use strict";

  /* ---------- API base (mismo criterio que staffing.js) ---------- */
  var PROD = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
  var host = location.hostname;
  var isProd = host === "vinttihub.vintti.com";
  var isLocal = !isProd && (
    host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" ||
    host === "" || host === "::1" || host.endsWith(".local") ||
    location.protocol === "file:"
  );
  var override = new URLSearchParams(location.search).get("api");
  if (override) {
    try { localStorage.setItem("prospecting_api", override.replace(/\/$/, "")); } catch (e) {}
  }
  var sticky = null;
  try { sticky = localStorage.getItem("prospecting_api"); } catch (e) {}
  var API = (override && override.replace(/\/$/, "")) || sticky ||
            (isLocal ? "http://localhost:5000" : PROD);
  // Abrir la página en local no obliga a tener el backend levantado: si no
  // contesta, se cae al deployado una sola vez y se sigue usando ese.
  var canFallBack = isLocal && !override && !sticky && API !== PROD;

  function userEmail() {
    try {
      return (localStorage.getItem("user_email") || sessionStorage.getItem("user_email") || "").trim().toLowerCase();
    } catch (e) { return ""; }
  }

  function request(base, path, options) {
    var opts = options || {};
    var headers = Object.assign({ "X-User-Email": userEmail() }, opts.headers || {});
    if (opts.body) headers["Content-Type"] = "application/json";
    return fetch(base + path, Object.assign({}, opts, { headers: headers })).then(
      function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) {
            var err = new Error(data.error || ("HTTP " + res.status));
            err.status = res.status;
            err.errors = data.errors || null;  // detalle de validación de un workflow
            throw err;
          }
          return data;
        });
      },
      function () {
        var err = new Error("Could not reach " + base + ".");
        err.offline = true;
        throw err;
      }
    );
  }

  function api(path, options) {
    return request(API, path, options).catch(function (err) {
      if (!err.offline || !canFallBack) throw err;
      canFallBack = false;
      API = PROD;
      return request(API, path, options);
    });
  }

  /* ---------- Helpers ---------- */
  var $ = function (id) { return document.getElementById(id); };

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDate(iso) {
    if (!iso) return "—";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length !== 3) return esc(iso);
    return Number(p[2]) + " " + MONTHS[Number(p[1]) - 1] + " " + p[0];
  }
  function fmtDateTime(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }
  function nowHHMM() {
    var d = new Date();
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }
  function todayIso() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function optionsHtml(list, selected, emptyLabel) {
    var html = emptyLabel != null ? '<option value="">' + esc(emptyLabel) + "</option>" : "";
    list.forEach(function (o) {
      var value = typeof o === "string" ? o : o.value;
      var label = typeof o === "string" ? o : o.label;
      html += '<option value="' + esc(value) + '"' + (value === selected ? " selected" : "") + ">" + esc(label) + "</option>";
    });
    return html;
  }

  /* ---------- Estado ---------- */
  var OPTS = { statuses: [], not_icp_reasons: [], sizes: [], bdrs: [], weeks: [], workflows: [] };
  var ME = { email: userEmail(), is_admin: false };
  /* `view` = pestaña activa: "sys:<all|mine|unassigned|recycled>" (fijas) o "v:<id>"
     (vista guardada, ver «Vistas» más abajo). `advanced` = filtros avanzados
     (condiciones con la forma de los workflows) o null. */
  var state = { view: "sys:all", page: 1, pageSize: 25, sort: "created_desc", total: 0, advanced: null };
  var rowsById = {};

  function ownerOptions() {
    return OPTS.bdrs.map(function (b) { return { value: b.email, label: b.name || b.email }; });
  }
  function ownerName(email) {
    if (!email) return "";
    // BDRs y, si no, cualquier usuario del Hub (p. ej. manuela / mia, que editan workflows).
    var hit = (OPTS.bdrs || []).concat(OPTS.users || []).filter(function (b) { return b.email === email; })[0];
    return hit ? (hit.name || hit.email) : email;
  }

  /* ---------- Filtros ---------- */
  function fillFilters() {
    // Sin «Me»: para eso está la pestaña My companies (SYS_OVERRIDES sigue usando __me__).
    var owners = [{ value: "__none__", label: "No owner" }].concat(ownerOptions());
    $("prFOwner").innerHTML = optionsHtml(owners, "", "All");
    $("prFWeek").innerHTML = optionsHtml([{ value: "__none__", label: "No week" }].concat(OPTS.weeks), "", "All");
    $("prFStatus").innerHTML = optionsHtml([{ value: "__none__", label: "No status" }].concat(OPTS.statuses), "", "All");
  }

  function currentFilters() {
    var f = {
      owner: $("prFOwner").value,
      week: $("prFWeek").value,
      status: $("prFStatus").value,
      start_from: $("prFStartFrom").value,
      start_to: $("prFStartTo").value,
      q: $("prFQ").value.trim(),
      dummy: ME.sees_dummies ? $("prFDummy").value : "exclude",
      contact_incomplete: $("prFIncomplete").checked ? "1" : "",
      sort: state.sort,
      page: state.page,
      page_size: state.pageSize,
    };
    // Las pestañas fijas son atajos de filtro, como las vistas por defecto de HubSpot.
    Object.assign(f, SYS_OVERRIDES[state.view] || {});
    if (f.owner === "__me__") f.owner = ME.email;
    if (hasAdvanced(state.advanced)) f.advanced = JSON.stringify(state.advanced);
    return f;
  }

  function qs(obj) {
    return Object.keys(obj)
      .filter(function (k) { return obj[k] !== "" && obj[k] != null; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]); })
      .join("&");
  }

  /* ---------- Tabla ---------- */
  var loadSeq = 0;
  function load() {
    var seq = ++loadSeq;
    // Otros filtros u otra página = otra lista: la selección (y «todas las del filtro») se suelta.
    var key = qs(currentFilters());
    if (key !== lastLoadKey) { selected = {}; selAll = null; lastLoadKey = key; }
    renderViewBar();
    $("prBody").innerHTML = '<tr><td class="pr-empty" colspan="' + colspan() + '">Loading…</td></tr>';
    return api("/prospecting/companies?" + qs(currentFilters())).then(function (data) {
      if (seq !== loadSeq) return;
      state.total = data.total;
      rowsById = {};
      data.rows.forEach(function (r) { rowsById[r.id] = r; });
      lastRows = data.rows;
      renderRows(data.rows);
      renderPager();
      $("prBody").closest(".pr-table-wrap").scrollTop = 0;
    }).catch(function (err) {
      if (seq !== loadSeq) return;
      var msg = esc(err.message) + (err.errors ? "<br>" + err.errors.map(esc).join("<br>") : "");
      $("prBody").innerHTML = '<tr><td class="pr-empty" colspan="' + colspan() + '">' + msg + "</td></tr>";
    });
  }

  /* ---------- Columnas ----------
     Los 21 campos de la planilla de propiedades de HubSpot, con el mismo nombre.
     Cada persona elige cuáles ver (botón Columns); se recuerda en este navegador.
     `def: true` = visibles por defecto (las de la vista "Prospecting Companies"). */
  function cellText(v) { return v == null || v === "" ? "—" : esc(v); }
  function cellLong(v) {
    return v == null || v === "" ? "—" : '<span class="pr-long" title="' + esc(v) + '">' + esc(v) + "</span>";
  }
  function cellLink(v) {
    return v ? '<a class="pr-link" href="' + esc(v) + '" target="_blank" rel="noopener" title="' + esc(v) + '">' + esc(String(v).replace(/^https?:\/\/(www\.)?/, "")) + "</a>" : "—";
  }
  function cellSelect(field, list, value, extraClass) {
    return '<select class="pr-cell-select' + (extraClass || "") + '" data-field="' + field + '"' +
      (field === "prospecting_status" ? ' data-status="' + esc(value || "") + '"' : "") + ">" +
      optionsHtml(withCurrent(list, value), value || "", "—") + "</select>";
  }

  var COLUMNS = [
    { key: "name", label: "Nombre de la empresa", sort: "name", fixed: true, render: function (r) {
        var domain = r.domain
          ? '<a class="pr-company__domain" href="' + esc(r.website || ("https://" + r.domain)) + '" target="_blank" rel="noopener">' + esc(r.domain) + "</a>"
          : "";
        var dummy = r.is_dummy ? '<span class="pr-dummy-tag">DUMMY</span>' : "";
        return '<div class="pr-company"><div class="pr-company__line">' +
          '<a class="pr-company__name" href="prospecting-company.html?id=' + r.id + '">' + esc(r.name) + "</a>" + dummy +
          '<button type="button" class="pr-company__peek" data-open="' + r.id + '" title="Vista rápida"><i class="fa-regular fa-eye"></i></button>' +
          "</div>" + domain + "</div>";
      } },
    { key: "week_label", label: "Semana", sort: "week_desc", def: true, render: function (r) { return cellText(r.week_label); } },
    { key: "lead_source", label: "Lead Source", def: true, render: function (r) { return cellText(r.lead_source); } },
    { key: "prospecting_owner_email", label: "Prospecting Owner", def: true, render: function (r) {
        return cellSelect("prospecting_owner_email", ownerOptions(), r.prospecting_owner_email);
      } },
    { key: "open_jobs", label: "Numero de vacantes abiertas", sort: "open_jobs_desc", num: true, def: true, render: function (r) { return cellText(r.open_jobs); } },
    { key: "prospecting_start_date", label: "Prospecting Start Date", sort: "start_asc", def: true, render: function (r) { return fmtDate(r.prospecting_start_date); } },
    { key: "not_icp_reason", label: "Not ICP Reason", def: true, render: function (r) {
        return cellSelect("not_icp_reason", OPTS.not_icp_reasons, r.not_icp_reason);
      } },
    { key: "prospecting_status", label: "Prospecting Status", def: true, render: function (r) {
        return cellSelect("prospecting_status", OPTS.statuses, r.prospecting_status, " pr-status") +
          (r.contact_incomplete ? '<button type="button" class="pr-incomplete" data-complete="' + r.id + '" title="Le falta un contacto con los datos obligatorios">' +
            '<i class="fa-solid fa-circle-exclamation"></i> Contacto incompleto</button>' : "");
      } },
    { key: "contacts_count", label: "Contactos", num: true, render: function (r) { return cellText(r.contacts_count); } },
    { key: "keywords", label: "Keywords of the company", render: function (r) { return cellLong(r.keywords); } },
    { key: "technologies", label: "Technologies", render: function (r) { return cellLong(r.technologies); } },
    { key: "job_types", label: "Tipo de vacantes", render: function (r) { return cellLong(r.job_types); } },
    { key: "industry", label: "Industria", render: function (r) { return cellLong(r.industry); } },
    { key: "founded_year", label: "Founded Year", num: true, render: function (r) { return cellText(r.founded_year); } },
    { key: "website", label: "URL del sitio web", render: function (r) { return cellLink(r.website); } },
    { key: "linkedin_url", label: "Pagina Corporativa de LinkedIn", render: function (r) { return cellLink(r.linkedin_url); } },
    { key: "description", label: "Descripcion", render: function (r) { return cellLong(r.description); } },
    { key: "size", label: "Size", render: function (r) { return cellText(r.size); } },
    { key: "city", label: "Ciudad", render: function (r) { return cellText(r.city); } },
    { key: "state", label: "Estado", render: function (r) { return cellText(r.state); } },
    { key: "country", label: "Pais", render: function (r) { return cellText(r.country); } },
    { key: "hubspot_company_id", label: "Id de la empresa (HubSpot)", render: function (r) { return cellText(r.hubspot_company_id); } },
  ];

  /* Columnas visibles, EN ORDEN. En una vista guardada salen de su config; en las
     pestañas fijas, de este navegador (como antes). `name` va siempre primera. */
  var COLS_KEY = "prospecting_columns_v1";
  var COL_BY_KEY = {};
  COLUMNS.forEach(function (c) { COL_BY_KEY[c.key] = c; });
  function defaultCols() { return ["name"].concat(COLUMNS.filter(function (c) { return c.def; }).map(function (c) { return c.key; })); }
  function normalizeCols(keys) {
    var out = ["name"];
    (keys || []).forEach(function (k) { if (COL_BY_KEY[k] && out.indexOf(k) === -1) out.push(k); });
    return out;
  }
  function localCols() {
    try {
      var saved = JSON.parse(localStorage.getItem(COLS_KEY) || "null");
      if (Array.isArray(saved) && saved.length) return normalizeCols(saved);
    } catch (e) {}
    return defaultCols();
  }
  var visibleCols = localCols();

  function activeColumns() {
    return visibleCols.map(function (k) { return COL_BY_KEY[k]; }).filter(Boolean);
  }
  /* Se ordena por cualquier columna que sea un campo (contacts_count es calculada). */
  function sortable(c) { return c.key !== "contacts_count"; }
  function parseSort(s) {
    var m = /^([a-z0-9_]+):(asc|desc)$/.exec(s || "");
    return m ? { key: m[1], dir: m[2] } : null;
  }

  /* Selección de filas: «Editar» en masa lo puede usar cualquiera con acceso (como la
     edición de a uno); «Inscribir en workflow», sólo quien edita workflows.
     `selAll` = «todas las que coinciden con los filtros» (guarda esos filtros). */
  var selected = {}, selAll = null, lastLoadKey = "";
  function canSelect() { return true; }
  function canEnroll() { return !!ME.can_edit_workflows; }
  function colspan() { return activeColumns().length + (canSelect() ? 1 : 0); }

  function renderHead() {
    $("prHead").innerHTML = (canSelect()
      ? '<th class="pr-selcol"><label class="pr-check pr-check--bare"><input type="checkbox" id="prSelAll" title="Seleccionar la página"></label></th>' : "") +
      activeColumns().map(function (c) {
      var cur = parseSort(state.sort);
      var on = cur && cur.key === c.key;
      var cls = [c.num ? "pr-num" : "", on ? "is-sorted" : ""].filter(Boolean).join(" ");
      var arrow = on ? ' <i class="fa-solid fa-arrow-' + (cur.dir === "asc" ? "up" : "down") + ' pr-sort-arrow"></i>' : "";
      return "<th" + (sortable(c) ? ' data-sort="' + c.key + '" title="Sort"' : "") + (cls ? ' class="' + cls + '"' : "") + ">" + esc(c.label) + arrow + "</th>";
    }).join("");
    $("prColsCount").textContent = activeColumns().length + "/" + COLUMNS.length;
  }

  /* Visibles arriba, en su orden y arrastrables; las ocultas abajo. */
  function renderColsMenu() {
    var item = function (c, on) {
      var drag = on && !c.fixed;
      return '<div class="pr-cols__item' + (drag ? " is-draggable" : "") + '"' + (drag ? ' draggable="true" data-col-item="' + c.key + '"' : "") + ">" +
        '<i class="fa-solid fa-grip-vertical pr-cols__grip"' + (drag ? "" : ' style="visibility:hidden"') + "></i>" +
        '<label class="pr-check"><input type="checkbox" data-col="' + c.key + '"' + (on ? " checked" : "") +
        (c.fixed ? " disabled" : "") + "> " + esc(c.label) + "</label></div>";
    };
    var hidden = COLUMNS.filter(function (c) { return visibleCols.indexOf(c.key) === -1; });
    $("prColsMenu").innerHTML = '<div class="pr-cols__head">Shown · drag to reorder</div>' +
      activeColumns().map(function (c) { return item(c, true); }).join("") +
      (hidden.length ? '<div class="pr-cols__head pr-cols__head--sub">Hidden</div>' + hidden.map(function (c) { return item(c, false); }).join("") : "") +
      '<div class="pr-cols__foot"><button type="button" class="pr-btn" data-cols="all">All</button>' +
      '<button type="button" class="pr-btn" data-cols="default">Default</button></div>';
  }

  function setVisibleCols(keys) {
    visibleCols = normalizeCols(keys);
    if (isSys(state.view)) {
      try { localStorage.setItem(COLS_KEY, JSON.stringify(visibleCols)); } catch (e) {}
    }
    renderHead();
    renderColsMenu();
    renderRows(lastRows);
    renderViewBar();
  }

  var lastRows = [];
  function renderRows(rows) {
    var cols = activeColumns();
    if (!rows.length) {
      $("prBody").innerHTML = '<tr><td class="pr-empty" colspan="' + colspan() + '">No companies match these filters.</td></tr>';
      renderBulk();
      return;
    }
    $("prBody").innerHTML = rows.map(function (r) {
      return '<tr data-id="' + r.id + '"' + (selected[r.id] ? ' class="is-selected"' : "") + ">" +
        (canSelect() ? '<td class="pr-selcol"><label class="pr-check pr-check--bare"><input type="checkbox" data-sel="' + r.id + '"' + (selected[r.id] ? " checked" : "") + "></label></td>" : "") +
        cols.map(function (c) {
        return "<td" + (c.num ? ' class="pr-num"' : "") + ">" + c.render(r) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    renderBulk();
  }

  /* Barra de «N seleccionadas → Editar / Inscribir en workflow». */
  var wfChoices = null;
  function selectionHead(n, allMode, pageAll, total, noun) {
    return "<strong>" + (allMode ? "Todas las " + total.toLocaleString() : n) + "</strong> " + noun + (n === 1 && !allMode ? "" : "s") +
      " seleccionada" + (n === 1 && !allMode ? "" : "s") +
      (pageAll && !allMode && total > n
        ? '<button type="button" class="pr-wf-link pr-bulk__all" data-bulk-all="1">Seleccionar las ' + total.toLocaleString() + " que coinciden con los filtros</button>" : "") +
      '<button type="button" class="pr-btn pr-btn--primary" data-bulk-edit="1"><i class="fa-solid fa-pen"></i> Editar</button>';
  }
  function renderBulk() {
    var bar = $("prBulk");
    var ids = Object.keys(selected);
    if (!canSelect() || (!ids.length && !selAll)) { bar.hidden = true; return; }
    var pageAll = lastRows.length > 0 && lastRows.every(function (r) { return selected[r.id]; });
    var opts = (wfChoices || []).map(function (w) {
      return '<option value="' + w.id + '">' + esc(w.name) + (w.enabled ? "" : " (inactivo)") + "</option>";
    }).join("");
    bar.hidden = false;
    // Inscribir trabaja con ids: en «todas las del filtro» no se ofrece.
    var enroll = canEnroll() && !selAll;
    bar.innerHTML = selectionHead(ids.length, !!selAll, pageAll, state.total, "empresa") +
      (enroll ? '<select class="pr-filter__input" id="prBulkWf">' + (wfChoices ? '<option value="">Elegir workflow…</option>' + opts : "<option>Cargando…</option>") + "</select>" +
        '<button type="button" class="pr-btn" id="prBulkGo"><i class="fa-solid fa-diagram-project"></i> Inscribir en workflow</button>' : "") +
      '<button type="button" class="pr-btn" id="prBulkClear">Deseleccionar</button>';
    if (!enroll) return;
    if (!wfChoices && window.ProspectingWorkflows) {
      window.ProspectingWorkflows.workflows().then(function (r) {
        wfChoices = r.workflows.filter(function (w) { return (w.object || "company") === "company"; });
        renderBulk();
      });
    }
  }
  var enrolling = false;
  function bulkEnroll() {
    if (enrolling) return;  // un segundo click mientras corre inscribía todo dos veces
    var wfId = $("prBulkWf").value;
    if (!wfId) { alert("Elegí un workflow."); return; }
    var ids = Object.keys(selected).map(Number);
    var wfName = $("prBulkWf").selectedOptions[0].textContent;
    enrolling = true;
    $("prBulk").classList.add("is-busy");
    var done = progress("Inscribiendo " + ids.length + " empresa" + (ids.length === 1 ? "" : "s") + " en <strong>" + esc(wfName) + "</strong>…");
    window.ProspectingWorkflows.enrollCompanies(wfId, ids).then(function (r) {
      enrolling = false;
      $("prBulk").classList.remove("is-busy");
      toast('<i class="fa-solid fa-diagram-project"></i> Se inscribieron <strong>' + r.enrolled + "</strong> de " + ids.length +
        (r.enrolled < ids.length ? " (las demás ya estaban adentro o el workflow no reinscribe)" : "") +
        (r.completed ? " · " + r.completed + " ya terminaron el workflow" : "") + ".");
      selected = {};
      load();
    }).catch(function (err) {
      enrolling = false;
      $("prBulk").classList.remove("is-busy");
      done();
      alert(err.errors ? err.errors.join("\n") : err.message);
    });
  }

  /* ---------- Edición masiva (botón «Editar» de la barra) ----------
     Una propiedad, un valor, todos los seleccionados: POST /prospecting/<companies|contacts>/bulk.
     El backend la aplica registro por registro (historial + workflows, como de a uno). */
  function bulkFields(kind) {
    var o = (OPTS.objects || {})[kind] || {};
    return (o.fields || []).filter(function (f) {
      return kind === "company" ? f.editable : f.key !== "email" && f.key !== "is_primary";
    });
  }
  function bulkValueLabel(f, v) {
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return "(vacío)";
    if (f.type === "owner" || f.type === "user") return ownerName(v) || v;
    if (f.type === "bool") return v ? "Sí" : "No";
    if (Array.isArray(v)) return v.join(", ");
    return String(v);
  }
  function openBulkEdit(kind) {
    var isCo = kind === "company";
    var sel = isCo ? selected : ctSelected, all = isCo ? selAll : ctSelAll;
    var ids = Object.keys(sel).map(Number);
    var n = all ? all.total : ids.length;
    var noun = isCo ? (n === 1 ? "empresa" : "empresas") : (n === 1 ? "contacto" : "contactos");
    var fields = bulkFields(kind);
    var PC = window.ProspectingContacts;
    var box = document.createElement("div");
    box.className = "pr-modal";
    box.innerHTML = '<div class="pr-modal__card pr-bulkedit" role="dialog" aria-modal="true">' +
      "<h3>Editar " + n.toLocaleString() + " " + noun + "</h3>" +
      '<label class="pr-filter"><span class="pr-filter__label">Propiedad</span>' +
        '<select class="pr-filter__input" id="prBkField"><option value="">Elegí una propiedad…</option>' +
        fields.map(function (f) { return '<option value="' + esc(f.key) + '">' + esc(f.label) + "</option>"; }).join("") + "</select></label>" +
      '<div class="pr-bulkedit__value" id="prBkValue"></div>' +
      '<label class="pr-check" id="prBkClearWrap" hidden><input type="checkbox" id="prBkClear"> Dejarla vacía en todos</label>' +
      '<p class="pr-note">Se cambia en todos los seleccionados. Queda en el historial de cada uno y corre los workflows igual que si lo editaras de a uno.</p>' +
      '<p class="pr-bulkedit__err" id="prBkErr" hidden></p>' +
      '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-bk="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-bk="apply"><i class="fa-solid fa-check"></i> Aplicar</button></div></div>';
    document.body.appendChild(box);
    var q = function (id) { return box.querySelector("#" + id); };
    var fieldOf = function () { var k = q("prBkField").value; return fields.filter(function (f) { return f.key === k; })[0] || null; };
    var err = function (msg) { q("prBkErr").hidden = !msg; q("prBkErr").innerHTML = msg || ""; };
    var running = false;  // mientras corre no se cierra: cerrar y volver a aplicar lo haría dos veces
    var close = function () { if (running) return; box.remove(); document.removeEventListener("keydown", onKey); };
    var onKey = function (e) { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    q("prBkField").addEventListener("change", function () {
      var f = fieldOf();
      q("prBkValue").innerHTML = f ? '<span class="pr-filter__label">Nuevo valor</span>' + PC.fieldControl(f, null) : "";
      q("prBkClearWrap").hidden = !f;
      q("prBkClear").checked = false;
      err("");
    });
    q("prBkClear").addEventListener("change", function () { q("prBkValue").classList.toggle("is-off", this.checked); });
    box.addEventListener("click", function (e) {
      if (e.target === box) return close();
      var chip = e.target.closest(".pr-wf-chip");
      if (chip && chip.closest("#prBkValue [data-k]")) {
        chip.classList.toggle("is-on");
        chip.innerHTML = (chip.classList.contains("is-on") ? '<i class="fa-solid fa-check"></i> ' : "") + esc(chip.getAttribute("data-chip"));
        return;
      }
      var b = e.target.closest("[data-bk]");
      if (!b) return;
      if (b.getAttribute("data-bk") === "cancel") return close();
      var f = fieldOf();
      if (!f) return err("Elegí qué propiedad cambiar.");
      var clear = q("prBkClear").checked;
      var el = q("prBkValue").querySelector("[data-k]");
      var value = clear ? null : PC.readFieldValue(el);
      if (!clear && (value == null || (Array.isArray(value) && !value.length))) return err("Elegí un valor, o tildá «Dejarla vacía en todos».");
      if (!confirm("Vas a cambiar «" + f.label + "» a «" + bulkValueLabel(f, value) + "» en " + n.toLocaleString() + " " + noun + ". ¿Seguir?")) return;
      var body = Object.assign(all ? { filters: all.filters } : { ids: ids }, { field: f.key, value: value });
      running = true;
      box.classList.add("is-busy");
      box.querySelectorAll("button, select, input, textarea").forEach(function (x) { x.disabled = true; });
      b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Aplicando…';
      var done = progress("Cambiando <strong>" + esc(f.label) + "</strong> en " + n.toLocaleString() + " " + noun + "…");
      err("");
      api("/prospecting/" + (isCo ? "companies" : "contacts") + "/bulk", { method: "POST", body: JSON.stringify(body) }).then(function (r) {
        running = false;
        close();
        var parts = ["<strong>" + esc(f.label) + "</strong>: " + r.updated + " actualizad" + (isCo ? "a" : "o") + (r.updated === 1 ? "" : "s")];
        if (r.unchanged) parts.push(r.unchanged + " ya tenía" + (r.unchanged === 1 ? "" : "n") + " ese valor");
        if (r.failed.length) parts.push('<span class="pr-toast__warn">' + r.failed.length + " no se pudo: " +
          r.failed.slice(0, 3).map(function (x) { return esc(x.name) + " (" + esc(x.error) + ")"; }).join(", ") + (r.failed.length > 3 ? "…" : "") + "</span>");
        if (r.needs_contact) parts.push(r.needs_contact + " quedaron sin contacto completo");
        if (r.workflows_applied.length) parts.push("corrieron " + r.workflows_applied.map(function (w) { return "<strong>" + esc(w) + "</strong>"; }).join(", "));
        toast('<i class="fa-solid fa-pen"></i> ' + parts.join(" · ") + ".");
        if (isCo) { selected = {}; selAll = null; load(); } else { ctSelected = {}; ctSelAll = null; loadContacts(); }
      }).catch(function (e2) {
        running = false;
        done();
        box.classList.remove("is-busy");
        box.querySelectorAll("button, select, input, textarea").forEach(function (x) { x.disabled = false; });
        b.innerHTML = '<i class="fa-solid fa-check"></i> Aplicar';
        err(esc(e2.message) + (e2.errors ? "<br>" + e2.errors.map(esc).join("<br>") : ""));
      });
    });
  }

  // Si la fila tiene un valor que ya no está en la lista (dato viejo), igual se muestra.
  function withCurrent(list, current) {
    if (!current) return list;
    var has = list.some(function (o) { return (typeof o === "string" ? o : o.value) === current; });
    return has ? list : list.concat([{ value: current, label: ownerName(current) || current }]);
  }

  function renderPager() {
    var pages = Math.max(1, Math.ceil(state.total / state.pageSize));
    $("prCount").textContent = state.total.toLocaleString() + " compan" + (state.total === 1 ? "y" : "ies");
    $("prPage").textContent = state.page + " / " + pages;
    $("prPrev").disabled = state.page <= 1;
    $("prNext").disabled = state.page >= pages;
  }

  function patchCompany(id, patch) {
    return api("/prospecting/companies/" + id, { method: "PATCH", body: JSON.stringify(patch) });
  }

  /* Si al guardar corrió un workflow (al instante), se avisa y se refresca la tabla:
     la fila puede haber cambiado en campos que la persona no tocó. */
  var toastTimer = null;
  function toast(html) {
    var el = $("prToast");
    stopProgress();
    el.innerHTML = html;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 6000);
  }
  /* Aviso fijo mientras corre algo largo (inscribir, editar en masa): con la base lejos
     (backend local → RDS) cada registro son ~20 consultas y 75 empresas tardaban más de
     un minuto sin que la pantalla dijera nada; se volvía a apretar y se inscribía dos veces.
     Muestra los segundos para que se vea que sigue trabajando. toast() lo reemplaza. */
  var progressTimer = null;
  function stopProgress() { clearInterval(progressTimer); progressTimer = null; }
  function progress(text) {
    var el = $("prToast"), t0 = Date.now();
    clearTimeout(toastTimer);
    stopProgress();
    var draw = function () {
      var secs = Math.floor((Date.now() - t0) / 1000);
      el.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> ' + text + (secs >= 2 ? ' <span class="pr-toast__secs">' + secs + " s</span>" : "") +
        (secs >= 10 ? '<br><span class="pr-toast__hint">Sigue trabajando, no cierres ni recargues la página.</span>' : "");
    };
    el.hidden = false;
    draw();
    progressTimer = setInterval(draw, 1000);
    return function () { stopProgress(); el.hidden = true; };
  }
  function announceWorkflows(row) {
    var applied = (row && row.workflows_applied) || [];
    if (!applied.length) return;
    var names = applied.map(function (a) { return "<strong>" + esc(a.name) + "</strong>"; });
    toast('<i class="fa-solid fa-diagram-project"></i> El workflow ' + names.join(", ") + " actualizó esta empresa.");
    load();
  }

  /* Pasó a Qualified / SQL sin un contacto completo: formulario «Completá el contacto». */
  function askContact(row) {
    if (!row || !row.needs_contact || !window.ProspectingContacts) return;
    window.ProspectingContacts.completeFlow(row, row.contacts || [], function () { load(); });
  }

  function onCellChange(e) {
    var sel = e.target.closest(".pr-cell-select");
    if (!sel) return;
    var tr = sel.closest("tr");
    var id = Number(tr.getAttribute("data-id"));
    var field = sel.getAttribute("data-field");
    var patch = {};
    patch[field] = sel.value || null;
    sel.classList.add("is-saving");
    sel.classList.remove("is-error");
    patchCompany(id, patch).then(function (row) {
      Object.assign(rowsById[id], row);
      if (field === "prospecting_status") sel.setAttribute("data-status", row.prospecting_status || "");
      announceWorkflows(row);
      askContact(row);
    }).catch(function (err) {
      sel.classList.add("is-error");
      alert("Could not save: " + err.message);
    }).then(function () { sel.classList.remove("is-saving"); });
  }

  /* ---------- Pestaña Contacts ---------- */
  var ctState = { page: 1, total: 0 };
  var ctSelected = {}, ctSelAll = null, ctRows = [], ctLastKey = "";
  function ctFilters() {
    return {
      q: $("prCtQ").value.trim(), lead_life: $("prCtLead").value, owner: $("prCtOwner").value,
      dummy: ME.sees_dummies ? $("prFDummy").value : "exclude",
    };
  }
  function renderCtBulk() {
    var bar = $("prCtBulk");
    var ids = Object.keys(ctSelected);
    if (!ids.length && !ctSelAll) { bar.hidden = true; return; }
    var pageAll = ctRows.length > 0 && ctRows.every(function (c) { return ctSelected[c.id]; });
    bar.hidden = false;
    bar.innerHTML = selectionHead(ids.length, !!ctSelAll, pageAll, ctState.total, "contacto")
      .replace(/seleccionada/g, "seleccionado").replace(/Todas las/, "Todos los").replace(/Seleccionar las/, "Seleccionar los") +
      '<button type="button" class="pr-btn" data-ct-clear="1">Deseleccionar</button>';
    var all = $("prCtSelAll");
    if (all) all.checked = pageAll;
  }
  function loadContacts() {
    var q = Object.assign(ctFilters(), { page: ctState.page, page_size: 25 });
    var key = qs(q);
    if (key !== ctLastKey) { ctSelected = {}; ctSelAll = null; ctLastKey = key; }
    $("prCtBody").innerHTML = '<tr><td class="pr-empty" colspan="8">Loading…</td></tr>';
    api("/prospecting/contacts?" + qs(q)).then(function (r) {
      ctState.total = r.total;
      ctRows = r.rows;
      $("prCtBody").innerHTML = r.rows.length ? r.rows.map(function (c) {
        return '<tr data-ct="' + c.id + '" data-co="' + c.company_id + '"' + (ctSelected[c.id] ? ' class="is-selected"' : "") + ">" +
          '<td class="pr-selcol"><label class="pr-check pr-check--bare"><input type="checkbox" data-ct-sel="' + c.id + '"' + (ctSelected[c.id] ? " checked" : "") + "></label></td>" +
          '<td><button type="button" class="pr-company__name" data-ct-open="' + c.id + '">' + esc(c.name) + "</button>" +
            (c.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") + "</td>" +
          '<td><a class="pr-link" href="prospecting-company.html?id=' + c.company_id + '">' + esc(c.company_name) + "</a></td>" +
          "<td>" + cellText(c.email) + "</td>" +
          "<td>" + cellText(c.position) + "</td>" +
          "<td>" + (c.lead_life ? '<span class="pr-wf-stat">' + esc(c.lead_life) + "</span>" : "—") + "</td>" +
          "<td>" + cellText(ownerName(c.owner_email)) + "</td>" +
          "<td>" + (c.meeting_datetime ? esc(window.ProspectingContacts.fmtLocal(c.meeting_datetime)) : "—") + "</td></tr>";
      }).join("") : '<tr><td class="pr-empty" colspan="8">No contacts match these filters.</td></tr>';
      renderCtBulk();
      var pages = Math.max(1, Math.ceil(r.total / 25));
      $("prCtCount").textContent = r.total.toLocaleString() + " contact" + (r.total === 1 ? "" : "s");
      $("prCtPage").textContent = ctState.page + " / " + pages;
      $("prCtPrev").disabled = ctState.page <= 1;
      $("prCtNext").disabled = ctState.page >= pages;
    }).catch(function (err) {
      $("prCtBody").innerHTML = '<tr><td class="pr-empty" colspan="8">' + esc(err.message) + "</td></tr>";
    });
  }
  function bindContacts() {
    var LEAD = (((OPTS.objects || {}).contact || {}).fields || []).filter(function (f) { return f.key === "lead_life"; })[0];
    $("prCtLead").innerHTML = optionsHtml((LEAD && LEAD.options) || [], "", "All");
    $("prCtOwner").innerHTML = optionsHtml([{ value: "__none__", label: "No owner" }].concat(ownerOptions()), "", "All");
    ["prCtLead", "prCtOwner"].forEach(function (id) { $(id).addEventListener("change", function () { ctState.page = 1; loadContacts(); }); });
    var t = null;
    $("prCtQ").addEventListener("input", function () { clearTimeout(t); t = setTimeout(function () { ctState.page = 1; loadContacts(); }, 300); });
    $("prCtPrev").addEventListener("click", function () { if (ctState.page > 1) { ctState.page--; loadContacts(); } });
    $("prCtNext").addEventListener("click", function () { ctState.page++; loadContacts(); });
    $("prCtBody").addEventListener("change", function (e) {
      var id = e.target.getAttribute && e.target.getAttribute("data-ct-sel");
      if (!id) return;
      if (e.target.checked) ctSelected[id] = true; else { delete ctSelected[id]; ctSelAll = null; }
      e.target.closest("tr").classList.toggle("is-selected", e.target.checked);
      renderCtBulk();
    });
    $("prCtSelAll").addEventListener("change", function (e) {
      ctRows.forEach(function (c) { if (e.target.checked) ctSelected[c.id] = true; else delete ctSelected[c.id]; });
      if (!e.target.checked) ctSelAll = null;
      document.querySelectorAll("#prCtBody [data-ct-sel]").forEach(function (cb) {
        cb.checked = e.target.checked;
        cb.closest("tr").classList.toggle("is-selected", e.target.checked);
      });
      renderCtBulk();
    });
    $("prCtBulk").addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      if (b.hasAttribute("data-bulk-edit")) openBulkEdit("contact");
      if (b.hasAttribute("data-bulk-all")) { ctSelAll = { filters: ctFilters(), total: ctState.total }; renderCtBulk(); }
      if (b.hasAttribute("data-ct-clear")) {
        ctSelected = {}; ctSelAll = null;
        document.querySelectorAll("#prCtBody [data-ct-sel]").forEach(function (cb) { cb.checked = false; cb.closest("tr").classList.remove("is-selected"); });
        renderCtBulk();
      }
    });
    $("prCtBody").addEventListener("click", function (e) {
      var b = e.target.closest("[data-ct-open]");
      if (!b) return;
      var tr = b.closest("tr");
      window.ProspectingContacts.open({ contactId: Number(b.getAttribute("data-ct-open")), companyId: Number(tr.getAttribute("data-co")),
        onSaved: function () { loadContacts(); } });
    });
    bindInbox();
  }

  /* ---------- Bandeja: contactos de Calendly (Zapier) sin empresa ----------
     Los que entran con un dominio que no es de una sola empresa (gmail, ninguna o
     varias). Se asocian a mano; si Clay después carga la empresa, se asocian solos
     (backend/prospecting/inbound.py). */
  var INBOX_WHY = { free_email: "Personal email", no_company: "No company with that domain", multiple_companies: "Several companies with that domain" };
  var inboxRows = {};
  function loadInbox() {
    var q = { status: "pending", dummy: ME.sees_dummies ? $("prFDummy").value : "exclude" };
    return api("/prospecting/inbound?" + qs(q)).then(function (r) {
      $("prInboxCount").textContent = r.total ? String(r.total) : "";
      $("prInboxBtn").classList.toggle("has-items", r.total > 0);
      inboxRows = {};
      r.rows.forEach(function (x) { inboxRows[x.id] = x; });
      $("prInboxBody").innerHTML = r.rows.length ? r.rows.map(inboxRow).join("")
        : '<tr><td class="pr-empty" colspan="7">Nothing waiting: every Calendly contact is linked to a company.</td></tr>';
    }).catch(function (err) {
      $("prInboxBody").innerHTML = '<tr><td class="pr-empty" colspan="7">' + esc(err.message) + "</td></tr>";
    });
  }
  function inboxRow(x) {
    var d = x.contact_data || {}, ex = x.extra || {};
    var name = [x.first_name, x.last_name].filter(Boolean).join(" ") || x.email;
    var utm = ["utm_source", "utm_medium", "utm_campaign"].map(function (k) { return d[k]; }).filter(Boolean);
    var hint = [ex.event_name, d.company_name, ex.website, ex.questions_and_answers].filter(Boolean).join(" · ");
    return '<tr data-in="' + x.id + '">' +
      "<td><strong>" + esc(name) + "</strong>" + (x.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") +
        (hint ? '<div class="pr-note pr-inbox__hint" title="' + esc(hint) + '">' + esc(hint) + "</div>" : "") + "</td>" +
      "<td>" + cellText(x.email) + "</td>" +
      "<td>" + (x.meeting_datetime ? esc(window.ProspectingContacts.fmtLocal(x.meeting_datetime)) : "—") + "</td>" +
      "<td>" + (utm.length ? esc(utm.join(" / ")) : "—") + "</td>" +
      '<td><span class="pr-note">' + esc(INBOX_WHY[x.reason] || x.reason || "") + (x.domain ? " (" + esc(x.domain) + ")" : "") + "</span></td>" +
      '<td class="pr-inbox__pick"><input type="text" class="pr-filter__input" data-in-q placeholder="Search company…" autocomplete="off"' +
        ' value="' + esc(d.company_name || "") + '"><div class="pr-inbox__results" data-in-results hidden></div></td>' +
      '<td class="pr-inbox__acts"><button type="button" class="pr-btn pr-btn--primary" data-in-link disabled>Link</button>' +
        '<button type="button" class="pr-btn pr-btn--danger" data-in-discard title="Discard"><i class="fa-regular fa-trash-can"></i></button></td></tr>';
  }
  function searchCompanies(tr, text) {
    var box = tr.querySelector("[data-in-results]");
    var x = inboxRows[tr.getAttribute("data-in")];
    if (!text.trim()) { box.hidden = true; return; }
    api("/prospecting/companies?" + qs({ q: text.trim(), page_size: 10, dummy: x && x.is_dummy ? "only" : "exclude" })).then(function (r) {
      box.innerHTML = r.rows.length ? r.rows.map(function (c) {
        return '<button type="button" data-in-co="' + c.id + '" data-in-name="' + esc(c.name) + '"><strong>' + esc(c.name) + "</strong>" +
          (c.domain ? ' <span class="pr-note">' + esc(c.domain) + "</span>" : "") + "</button>";
      }).join("") : '<span class="pr-note">No companies match.</span>';
      box.hidden = false;
    }).catch(function (err) { box.innerHTML = '<span class="pr-note">' + esc(err.message) + "</span>"; box.hidden = false; });
  }
  function bindInbox() {
    $("prInboxBtn").addEventListener("click", function () {
      var open = $("prInbox").hidden;
      $("prInbox").hidden = !open;
      $("prInboxBtn").setAttribute("aria-expanded", String(open));
      if (open) loadInbox();
    });
    var t = null;
    $("prInboxBody").addEventListener("input", function (e) {
      var inp = e.target.closest("[data-in-q]");
      if (!inp) return;
      var tr = inp.closest("tr");
      tr.removeAttribute("data-co");
      tr.querySelector("[data-in-link]").disabled = true;
      clearTimeout(t);
      t = setTimeout(function () { searchCompanies(tr, inp.value); }, 250);
    });
    $("prInboxBody").addEventListener("focusin", function (e) {
      var inp = e.target.closest("[data-in-q]");
      if (inp && inp.value && !inp.closest("tr").getAttribute("data-co")) searchCompanies(inp.closest("tr"), inp.value);
    });
    $("prInboxBody").addEventListener("click", function (e) {
      var tr = e.target.closest("tr[data-in]");
      if (!tr) return;
      var id = tr.getAttribute("data-in");
      var pick = e.target.closest("[data-in-co]");
      if (pick) {
        tr.setAttribute("data-co", pick.getAttribute("data-in-co"));
        tr.querySelector("[data-in-q]").value = pick.getAttribute("data-in-name");
        tr.querySelector("[data-in-results]").hidden = true;
        tr.querySelector("[data-in-link]").disabled = false;
        return;
      }
      var link = e.target.closest("[data-in-link]");
      if (link && tr.getAttribute("data-co")) {
        link.disabled = true;
        api("/prospecting/inbound/" + id + "/link", { method: "POST", body: JSON.stringify({ company_id: Number(tr.getAttribute("data-co")) }) })
          .then(function (r) {
            toast('<i class="fa-regular fa-user"></i> Contact ' + (r.action === "created" ? "created" : "updated") + " in <strong>" +
              esc(tr.querySelector("[data-in-q]").value) + "</strong>.");
            loadInbox();
            loadContacts();
          }).catch(function (err) { link.disabled = false; alert(err.message); });
        return;
      }
      if (e.target.closest("[data-in-discard]")) {
        var x = inboxRows[id] || {};
        if (!confirm("Discard " + (x.email || "this contact") + "? It will not be created.")) return;
        api("/prospecting/inbound/" + id + "/discard", { method: "POST" }).then(function () { loadInbox(); })
          .catch(function (err) { alert(err.message); });
      }
    });
  }

  /* ---------- Drawer ---------- */
  var drawerSave = null;

  function openDrawer() {
    $("prDrawer").classList.add("is-open");
    $("prDrawer").setAttribute("aria-hidden", "false");
  }
  function closeDrawer() {
    $("prDrawer").classList.remove("is-open");
    $("prDrawer").setAttribute("aria-hidden", "true");
    $("prDrawerSave").textContent = "Save";  // el panel de filtros avanzados lo cambia a «Apply»
    drawerSave = null;
  }

  function kv(label, value, isLink) {
    var v = value == null || value === "" ? "—"
      : isLink ? '<a href="' + esc(value) + '" target="_blank" rel="noopener">' + esc(value) + "</a>"
      : esc(value);
    return "<dt>" + esc(label) + "</dt><dd>" + v + "</dd>";
  }

  var FIELD_LABELS = {
    prospecting_status: "Prospecting Status",
    prospecting_owner_email: "Prospecting Owner",
    prospecting_start_date: "Prospecting Start Date",
    not_icp_reason: "Not ICP Reason",
    week_label: "Week",
    lead_source: "Lead Source",
  };

  function eventsHtml(events) {
    if (!events || !events.length) return '<p class="pr-note">No changes yet.</p>';
    return '<ul class="pr-events">' + events.map(function (ev) {
      var isWf = String(ev.source || "").indexOf("workflow:") === 0;
      var who = isWf ? "Workflow " + ev.source.slice(9)
        : ev.source === "clay" ? "Clay"
        : (ownerName(ev.actor) || ev.actor || ev.source);
      var what = ev.field === "__note__" ? '<span class="pr-events__note">Nota: ' + esc(ev.new_value || "") + "</span>"
        : ev.field
        ? esc(FIELD_LABELS[ev.field] || ev.field) + ": " + esc(ev.old_value || "—") + " → " + esc(ev.new_value || "—")
        : esc(ev.new_value === "created" ? "created the company" : ev.new_value === "contact_created" ? "added the contact" : (ev.new_value || ""));
      var subject = ev.contact_id ? '<span class="pr-co-ev__contact"><i class="fa-regular fa-user"></i> ' + esc(ev.contact_name || "Contacto") + "</span> · " : "";
      return '<li><span class="pr-events__when">' + fmtDateTime(ev.at) + "</span>" +
        '<span class="pr-events__src' + (isWf ? " pr-events__src--wf" : "") + '">' + esc(who) + "</span> · " + subject + what + "</li>";
    }).join("") + "</ul>";
  }

  var ENR_LABEL = { active: "En curso", waiting: "Esperando", completed: "Terminó", unenrolled: "Desinscripta",
                    goal_met: "Cumplió la meta", failed: "Con error" };
  function enrollmentsHtml(list) {
    if (!list || !list.length) return "";
    return '<section class="pr-section"><h3 class="pr-section__title">Workflows</h3><ul class="pr-events">' + list.map(function (e) {
      return '<li><span class="pr-events__when">' + fmtDateTime(e.enrolled_at) +
        (e.status === "waiting" && e.wake_at ? " · sigue " + fmtDateTime(e.wake_at) : "") + "</span>" +
        '<span class="pr-events__src pr-events__src--wf">' + esc(e.workflow_name) + "</span> · " +
        '<span class="pr-wf-stat pr-wf-stat--' + esc(e.status) + '">' + esc(ENR_LABEL[e.status] || e.status) + "</span>" +
        (e.last_step ? '<div class="pr-note">' + esc(e.last_step) + "</div>" : "") + "</li>";
    }).join("") + "</ul></section>";
  }

  function showCompany(id) {
    $("prDrawerEyebrow").textContent = "Company";
    $("prDrawerTitle").textContent = "Loading…";
    $("prDrawerSub").textContent = "";
    $("prDrawerBody").innerHTML = "";
    $("prDrawerStatus").textContent = "";
    $("prDrawerFoot").hidden = false;
    openDrawer();
    api("/prospecting/companies/" + id).then(function (c) {
      $("prDrawerTitle").innerHTML = esc(c.name) +
        ' <a class="pr-btn pr-drawer__full" href="prospecting-company.html?id=' + c.id + '"><i class="fa-solid fa-up-right-and-down-left-from-center"></i> Abrir ficha</a>';
      $("prDrawerSub").textContent = [c.domain, c.industry, [c.city, c.state, c.country].filter(Boolean).join(", ")]
        .filter(Boolean).join(" · ");
      var f = function (field, label, inner) {
        return '<label class="pr-filter"><span class="pr-filter__label">' + esc(label) + "</span>" + inner + "</label>";
      };
      $("prDrawerBody").innerHTML =
        '<section class="pr-section"><h3 class="pr-section__title">Prospecting</h3><div class="pr-grid">' +
          f("prospecting_status", "Prospecting Status",
            '<select class="pr-filter__input" data-edit="prospecting_status">' + optionsHtml(withCurrent(OPTS.statuses, c.prospecting_status), c.prospecting_status || "", "—") + "</select>") +
          f("not_icp_reason", "Not ICP Reason",
            '<select class="pr-filter__input" data-edit="not_icp_reason">' + optionsHtml(withCurrent(OPTS.not_icp_reasons, c.not_icp_reason), c.not_icp_reason || "", "—") + "</select>") +
          f("prospecting_owner_email", "Prospecting Owner",
            '<select class="pr-filter__input" data-edit="prospecting_owner_email">' + optionsHtml(withCurrent(ownerOptions(), c.prospecting_owner_email), c.prospecting_owner_email || "", "—") + "</select>") +
          f("prospecting_start_date", "Prospecting Start Date",
            '<input type="date" class="pr-filter__input" data-edit="prospecting_start_date" value="' + esc((c.prospecting_start_date || "").slice(0, 10)) + '">') +
          f("week_label", "Week",
            '<input class="pr-filter__input" data-edit="week_label" placeholder="Semana 40" value="' + esc(c.week_label || "") + '">') +
        "</div></section>" +
        '<section class="pr-section"><h3 class="pr-section__title">From Clay</h3><dl class="pr-kv">' +
          kv("Website", c.website, true) +
          kv("LinkedIn", c.linkedin_url, true) +
          kv("Lead Source", c.lead_source) +
          kv("Industry", c.industry) +
          kv("Size", c.size) +
          kv("Founded Year", c.founded_year) +
          kv("Open jobs", c.open_jobs) +
          kv("Job types", c.job_types) +
          kv("Technologies", c.technologies) +
          kv("Keywords", c.keywords) +
          kv("Location", [c.city, c.state, c.country].filter(Boolean).join(", ")) +
          kv("Description", c.description) +
          kv("Id de la empresa (HubSpot)", c.hubspot_company_id) +
          kv("Hub ID", c.id) +
          kv("Clay record", c.clay_record_id) +
        "</dl></section>" +
        enrollmentsHtml(c.enrollments) +
        '<section class="pr-section"><h3 class="pr-section__title">History</h3>' + eventsHtml(c.events) + "</section>";

      drawerSave = function () {
        var patch = {};
        Array.prototype.forEach.call($("prDrawerBody").querySelectorAll("[data-edit]"), function (el) {
          var field = el.getAttribute("data-edit");
          var before = field === "prospecting_start_date" ? (c[field] || "").slice(0, 10) : (c[field] || "");
          if ((el.value || "") !== before) patch[field] = el.value || null;
        });
        if (!Object.keys(patch).length) { $("prDrawerStatus").textContent = "No changes."; return; }
        $("prDrawerStatus").textContent = "Saving…";
        patchCompany(c.id, patch).then(function (row) {
          $("prDrawerStatus").textContent = "Saved.";
          announceWorkflows(row);
          askContact(row);
          load();
          showCompany(c.id);
        }).catch(function (err) { $("prDrawerStatus").textContent = "Error: " + err.message; });
      };
    }).catch(function (err) {
      $("prDrawerTitle").textContent = "Error";
      $("prDrawerBody").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>";
    });
  }

  /* ---------- Panel de pruebas (sólo admin) ---------- */
  /* IDs del Hub (users.user_id) para el round robin de Clay: Clay reparte estos
     números en `prospecting_owner_id` y el webhook los convierte en el BDR. */
  function showBdrIds() {
    drawerSave = null;
    var bdrs = (OPTS.bdrs || []).filter(function (b) { return b.id != null; });
    $("prDrawerEyebrow").textContent = "Clay";
    $("prDrawerTitle").textContent = "BDR IDs";
    $("prDrawerSub").textContent = "Use these IDs in Clay's round robin and send the result as prospecting_owner_id.";
    $("prDrawerFoot").hidden = true;
    $("prDrawerBody").innerHTML =
      '<section class="pr-section">' +
        '<div class="pr-row"><button type="button" class="pr-btn pr-btn--primary" data-copy="' +
          esc(bdrs.map(function (b) { return b.id; }).join(", ")) + '"><i class="fa-solid fa-copy"></i> Copy all IDs</button></div>' +
        '<table class="pr-table" style="margin-top:12px"><thead><tr><th>ID</th><th>BDR</th><th>Email</th><th></th></tr></thead><tbody>' +
        bdrs.map(function (b) {
          return "<tr><td><strong>" + esc(b.id) + "</strong></td><td>" + esc(b.name || "") + "</td><td>" + esc(b.email) + "</td>" +
            '<td><button type="button" class="pr-btn" data-copy="' + esc(b.id) + '" title="Copy"><i class="fa-solid fa-copy"></i></button></td></tr>';
        }).join("") +
        "</tbody></table></section>";
    openDrawer();
    $("prDrawerBody").querySelectorAll("[data-copy]").forEach(function (btn) {
      btn.onclick = function () {
        var text = btn.getAttribute("data-copy");
        (navigator.clipboard ? navigator.clipboard.writeText(text) : Promise.reject())
          .then(function () { toast("Copied: " + esc(text)); })
          .catch(function () { window.prompt("Copy:", text); });
      };
    });
  }

  function showTestPanel() {
    drawerSave = null;
    $("prDrawerEyebrow").textContent = "Test panel";
    $("prDrawerTitle").textContent = "Dummies y reloj de prueba";
    $("prDrawerSub").textContent = "Only you see this. Dummy companies are hidden from the BDRs.";
    $("prDrawerFoot").hidden = true;
    $("prDrawerBody").innerHTML =
      '<section class="pr-section"><h3 class="pr-section__title">1 · Dummy companies</h3>' +
        '<p class="pr-note">Creates fake companies spread across the BDRs, the last 5 weeks and every status. ' +
        "In Progress ones get a start date 10 to 90 days ago, so the 60-day recycle has cases on both sides.</p>" +
        '<div class="pr-row">' +
          '<label class="pr-filter" style="min-width:90px"><span class="pr-filter__label">How many</span>' +
            '<input type="number" class="pr-filter__input" id="prSeedN" value="60" min="1" max="300"></label>' +
          '<button type="button" class="pr-btn pr-btn--primary" id="prSeed"><i class="fa-solid fa-seedling"></i> Create</button>' +
          '<button type="button" class="pr-btn pr-btn--danger" id="prWipe"><i class="fa-solid fa-trash"></i> Delete all dummies</button>' +
        "</div><div id=\"prSeedOut\"></div></section>" +
      '<section class="pr-section"><h3 class="pr-section__title">2 · Avanzar el reloj</h3>' +
        '<p class="pr-note">Corre los workflows ACTIVOS como si fuera la fecha y hora que elijas: inscribe, cierra por meta o desinscripción ' +
        'y despierta las esperas que ya vencieron. Sólo toca empresas dummy. Sirve para probar «esperar 3 días» sin esperar 3 días.</p>' +
        '<div class="pr-row">' +
          '<label class="pr-filter" style="min-width:220px"><span class="pr-filter__label">Fecha y hora (Argentina)</span>' +
            '<input type="datetime-local" class="pr-filter__input" id="prClock" value="' + todayIso() + 'T' + nowHHMM() + '"></label>' +
          '<button type="button" class="pr-btn" data-clock="1"><i class="fa-solid fa-forward"></i> +1 día</button>' +
          '<button type="button" class="pr-btn" data-clock="7"><i class="fa-solid fa-forward-fast"></i> +7 días</button>' +
        "</div>" +
        '<div class="pr-row" style="margin-top:10px">' +
          '<button type="button" class="pr-btn pr-btn--primary" id="prTick"><i class="fa-solid fa-play"></i> Correr workflows a esa hora</button>' +
        "</div><div id=\"prWfOut\"></div></section>";
    openDrawer();

    $("prSeed").onclick = function () {
      var n = Number($("prSeedN").value) || 60;
      $("prSeedOut").innerHTML = '<p class="pr-note">Creating…</p>';
      api("/prospecting/dummy/seed", { method: "POST", body: JSON.stringify({ n: n }) }).then(function (r) {
        $("prSeedOut").innerHTML = '<div class="pr-result">Created ' + r.created + " dummy companies.</div>";
        setDummyFilter("include");
        refreshOptions().then(load);
      }).catch(function (err) { $("prSeedOut").innerHTML = '<div class="pr-result">Error: ' + esc(err.message) + "</div>"; });
    };
    $("prWipe").onclick = function () {
      if (!confirm("Delete ALL dummy companies? Real companies are not touched.")) return;
      api("/prospecting/dummy", { method: "DELETE" }).then(function (r) {
        $("prSeedOut").innerHTML = '<div class="pr-result">Deleted ' + r.deleted + " dummy companies.</div>";
        refreshOptions().then(load);
      }).catch(function (err) { $("prSeedOut").innerHTML = '<div class="pr-result">Error: ' + esc(err.message) + "</div>"; });
    };
    Array.prototype.forEach.call($("prDrawerBody").querySelectorAll("[data-clock]"), function (b) {
      b.onclick = function () {
        var el = $("prClock"), d = new Date(el.value || Date.now());
        d.setDate(d.getDate() + Number(b.getAttribute("data-clock")));
        el.value = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0") +
          "T" + String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
      };
    });
    $("prTick").onclick = function () {
      $("prWfOut").innerHTML = '<p class="pr-note">Corriendo…</p>';
      api("/prospecting/workflows/tick", { method: "POST", body: JSON.stringify({ now: $("prClock").value }) }).then(function (r) {
        $("prWfOut").innerHTML = '<div class="pr-result"><h4>Listo (' + esc(fmtDateTime(r.now)) + ")</h4><ul>" +
          "<li>Inscriptas: <strong>" + r.enrolled + "</strong></li>" +
          "<li>Cerradas por meta o desinscripción: <strong>" + r.closed + "</strong></li>" +
          "<li>Avanzaron: <strong>" + r.advanced + "</strong> (terminaron " + r.completed + ", con error " + r.failed + ")</li>" +
          '</ul><p class="pr-note" style="margin:6px 0 0">El detalle de cada empresa está en Workflows → el workflow → Historial.</p></div>';
        load();
      }).catch(function (err) { $("prWfOut").innerHTML = '<div class="pr-result">Error: ' + esc(err.message) + "</div>"; });
    };
  }

  function setDummyFilter(v) {
    $("prFDummy").value = v;
    state.page = 1;
  }

  /* =====================================================================
     Vistas guardadas (como las de HubSpot). Cada persona arma las suyas: filtros,
     filtros avanzados, columnas en orden, orden de filas y tamaño de página.
     Privadas salvo que se compartan; una compartida la puede agregar cualquiera a
     sus pestañas y duplicarla, pero sólo la edita quien la creó (lo frena el server).
     Qué pestañas ve cada persona y en qué orden también se guarda en el servidor:
     las 4 fijas se pueden ocultar. Backend: backend/prospecting/views.py.
     ===================================================================== */
  var SYS_TABS = {
    "sys:all": "Prospecting Companies",
    "sys:mine": "My companies",
    "sys:unassigned": "Unassigned",
    "sys:recycled": "Recycled",
  };
  var SYS_OVERRIDES = {
    "sys:mine": { owner: "__me__" },
    "sys:unassigned": { owner: "__none__" },
    "sys:recycled": { status: "Recycled" },
  };
  var ACTIVE_KEY = "prospecting_active_tab";
  var VIEWS = { views: [], tabs: Object.keys(SYS_TABS) };
  var baseline = "";      // la vista tal como está guardada, para saber si hay cambios
  var advPanel = null;

  function isSys(key) { return String(key || "").indexOf("sys:") === 0; }
  function viewOf(key) {
    if (isSys(key)) return null;
    var id = Number(String(key).slice(2));
    return VIEWS.views.filter(function (v) { return v.id === id; })[0] || null;
  }
  function tabLabel(key) { return isSys(key) ? SYS_TABS[key] : ((viewOf(key) || {}).name || "—"); }
  function hasAdvanced(c) { return !!(c && c.groups && c.groups.length); }
  function ruleCount(c) {
    return hasAdvanced(c) ? c.groups.reduce(function (n, g) { return n + (g.rules || []).length; }, 0) : 0;
  }

  /* JSON con las claves ordenadas: JSONB devuelve las claves en otro orden. */
  function canon(v) {
    if (Array.isArray(v)) return "[" + v.map(canon).join(",") + "]";
    if (v && typeof v === "object") {
      return "{" + Object.keys(v).sort().filter(function (k) { return v[k] != null; })
        .map(function (k) { return JSON.stringify(k) + ":" + canon(v[k]); }).join(",") + "}";
    }
    return JSON.stringify(v);
  }

  function filterInputs() {
    var f = {
      owner: $("prFOwner").value, week: $("prFWeek").value, status: $("prFStatus").value,
      start_from: $("prFStartFrom").value, start_to: $("prFStartTo").value, q: $("prFQ").value.trim(),
      contact_incomplete: $("prFIncomplete").checked ? "1" : "",
      dummy: ME.sees_dummies && $("prFDummy").value !== "exclude" ? $("prFDummy").value : "",
    };
    Object.keys(f).forEach(function (k) { if (!f[k]) delete f[k]; });
    return f;
  }
  function setFilterInputs(f) {
    f = f || {};
    var setSel = function (id, v) {
      var el = $(id);
      el.value = v || "";
      if (el.value !== (v || "")) el.value = "";  // valor que ya no existe (p. ej. una semana vieja)
    };
    setSel("prFOwner", f.owner);
    setSel("prFWeek", f.week);
    setSel("prFStatus", f.status);
    $("prFStartFrom").value = f.start_from || "";
    $("prFStartTo").value = f.start_to || "";
    $("prFQ").value = f.q || "";
    $("prFIncomplete").checked = f.contact_incomplete === "1";
    if (ME.sees_dummies) $("prFDummy").value = f.dummy || "exclude";
  }

  /* Lo que se compara contra lo guardado. En una fija no cuentan columnas ni tamaño de
     página: esas ya se recuerdan en el navegador, como siempre. */
  function snapshot() {
    var sys = isSys(state.view);
    return {
      filters: filterInputs(),
      advanced: hasAdvanced(state.advanced) ? state.advanced : null,
      columns: sys ? null : visibleCols.slice(),
      sort: state.sort === "created_desc" ? null : state.sort,
      page_size: sys ? null : state.pageSize,
    };
  }
  /* Lo que se guarda: en una fija, su atajo pasa a ser un filtro de verdad. */
  function configToSave() {
    var snap = snapshot();
    Object.assign(snap.filters, SYS_OVERRIDES[state.view] || {});
    snap.columns = visibleCols.slice();
    snap.page_size = state.pageSize;
    return snap;
  }
  function isDirty() { return canon(snapshot()) !== baseline; }

  function loadViews() {
    return api("/prospecting/views").then(function (r) {
      VIEWS = { views: r.views || [], tabs: r.tabs || Object.keys(SYS_TABS) };
    }).catch(function () { /* sin vistas igual anda la tabla con las fijas */ });
  }

  function showSection(kind) {
    $("prTableCard").hidden = kind !== "table";
    $("prWorkflows").hidden = kind !== "workflows";
    $("prContactsView").hidden = kind !== "contacts";
  }

  function applyTab(key) {
    var v = viewOf(key);
    if (!isSys(key) && !v) key = VIEWS.tabs[0] || "sys:all";
    v = viewOf(key);
    state.view = key;
    try { localStorage.setItem(ACTIVE_KEY, key); } catch (e) {}
    var cfg = v ? (v.config || {}) : { filters: {}, advanced: null, columns: localCols(), sort: null };
    setFilterInputs(cfg.filters);
    state.advanced = hasAdvanced(cfg.advanced) ? JSON.parse(JSON.stringify(cfg.advanced)) : null;
    visibleCols = normalizeCols(cfg.columns && cfg.columns.length ? cfg.columns : defaultCols());
    state.sort = cfg.sort || "created_desc";
    if (v) {
      state.pageSize = cfg.page_size || 25;
      $("prPageSize").value = String(state.pageSize);
    }
    state.page = 1;
    selected = {};
    selAll = null;
    baseline = canon(snapshot());
    showSection("table");
    renderTabs();
    renderHead();
    renderColsMenu();
    renderAdvSummary();
    load();
  }

  function switchTab(key) {
    if (key === state.view && $("prTableCard").hidden === false) return;
    var v = viewOf(state.view);
    if (v && v.mine && !$("prTableCard").hidden && isDirty() &&
        !confirm("La vista «" + v.name + "» tiene cambios sin guardar. ¿Descartarlos?")) return;
    applyTab(key);
  }

  function renderTabs() {
    var onTable = !$("prTableCard").hidden;
    $("prViewTabs").innerHTML = VIEWS.tabs.map(function (key) {
      var v = viewOf(key);
      var active = onTable && key === state.view;
      var icon = v && v.shared ? ' <i class="fa-solid fa-user-group pr-tab__shared" title="' +
        esc(v.mine ? "Shared with the team" : "Shared by " + (v.owner_name || v.owner_email)) + '"></i>' : "";
      return '<button type="button" class="pr-tab pr-tab--view' + (active ? " is-active" : "") + '" role="tab" draggable="true" data-tab="' + esc(key) + '">' +
        '<i class="fa-solid fa-table-list pr-tab__icon"></i>' + esc(tabLabel(key)) + icon +
        (active ? '<span class="pr-tab__more" data-tab-menu="' + esc(key) + '" title="View options" role="button"><i class="fa-solid fa-ellipsis"></i></span>' : "") +
        "</button>";
    }).join("");
    document.querySelectorAll('.pr-tab[data-view]').forEach(function (t) {
      t.classList.toggle("is-active", !onTable && t.getAttribute("data-view") === (!$("prWorkflows").hidden ? "workflows" : "contacts"));
    });
  }

  /* «Guardar» / «Descartar» cuando la vista cambió respecto de lo guardado. */
  function renderViewBar() {
    var bar = $("prViewBar");
    if (!bar) return;
    if (!isDirty()) { bar.hidden = true; bar.innerHTML = ""; return; }
    var v = viewOf(state.view);
    bar.hidden = false;
    bar.innerHTML = v && v.mine
      ? '<span><i class="fa-solid fa-pen"></i> Unsaved changes to <strong>' + esc(v.name) + "</strong></span>" +
        '<button type="button" class="pr-btn pr-btn--primary" data-vb="save"><i class="fa-solid fa-floppy-disk"></i> Save view</button>' +
        '<button type="button" class="pr-btn" data-vb="saveas">Save as new view</button>' +
        '<button type="button" class="pr-btn" data-vb="reset">Discard</button>'
      : '<span><i class="fa-solid fa-filter"></i> You changed <strong>' + esc(tabLabel(state.view)) + "</strong>" +
        (v ? " (shared by " + esc(v.owner_name || v.owner_email) + ")" : "") + "</span>" +
        '<button type="button" class="pr-btn pr-btn--primary" data-vb="saveas"><i class="fa-solid fa-plus"></i> Save as new view</button>' +
        '<button type="button" class="pr-btn" data-vb="reset">Reset</button>';
  }

  function renderAdvSummary() {
    var n = ruleCount(state.advanced);
    $("prAdvCount").textContent = n ? "(" + n + ")" : "";
    $("prAdvBtn").classList.toggle("is-on", n > 0);
    var box = $("prAdvSummary");
    if (!n || !window.ProspectingWorkflows) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    box.innerHTML = '<span class="pr-adv-summary__label"><i class="fa-solid fa-sliders"></i> Advanced</span>' +
      '<span class="pr-adv-summary__text">' + window.ProspectingWorkflows.conditionsSummary(state.advanced) + "</span>" +
      '<button type="button" class="pr-btn" data-adv="edit">Edit</button>' +
      '<button type="button" class="pr-btn" data-adv="clear" title="Remove advanced filters"><i class="fa-solid fa-xmark"></i></button>';
  }

  /* Panel lateral con el armador de condiciones de Workflows. */
  function openAdvanced() {
    if (!window.ProspectingWorkflows) return;
    $("prDrawerEyebrow").textContent = "Filters";
    $("prDrawerTitle").textContent = "Advanced filters";
    $("prDrawerSub").textContent = "Groups are joined by OR; conditions inside a group, by AND. Same properties as the workflows.";
    $("prDrawerBody").innerHTML = '<div class="pr-adv-panel" id="prAdvPanel"></div>' +
      '<div class="pr-row" style="margin-top:12px"><button type="button" class="pr-btn" id="prAdvClearAll"><i class="fa-solid fa-trash"></i> Clear all</button></div>';
    $("prDrawerStatus").textContent = "";
    $("prDrawerFoot").hidden = false;
    $("prDrawerSave").textContent = "Apply";
    openDrawer();
    advPanel = window.ProspectingWorkflows.conditionsPanel($("prAdvPanel"), state.advanced, function () {
      $("prDrawerStatus").textContent = "";
    });
    $("prAdvClearAll").onclick = function () { advPanel.clear(); };
    drawerSave = function () {
      var conds = advPanel.get();
      conds = hasAdvanced(conds) ? conds : null;
      // Se prueba antes de cerrar: si una condición está incompleta, el error queda a la vista.
      var probe = Object.assign(currentFilters(), { page: 1, page_size: 10 });
      delete probe.advanced;
      if (conds) probe.advanced = JSON.stringify(conds);
      $("prDrawerStatus").textContent = "Checking…";
      api("/prospecting/companies?" + qs(probe)).then(function () {
        state.advanced = conds ? JSON.parse(JSON.stringify(conds)) : null;
        state.page = 1;
        closeDrawer();
        renderAdvSummary();
        load();
      }).catch(function (err) {
        $("prDrawerStatus").innerHTML = esc(err.errors ? err.errors.join(" · ") : err.message);
      });
    };
  }

  /* ---------- Popover (menú de una pestaña / «+») ---------- */
  function closePop() { $("prViewPop").hidden = true; $("prViewPop").innerHTML = ""; }
  function openPop(anchor, html) {
    var pop = $("prViewPop");
    pop.innerHTML = html;
    pop.hidden = false;
    var r = anchor.getBoundingClientRect();
    var left = Math.min(r.left, window.innerWidth - pop.offsetWidth - 16);
    pop.style.left = Math.max(16, left) + "px";
    pop.style.top = (r.bottom + 6) + "px";
  }

  function tabMenu(anchor, key) {
    var v = viewOf(key);
    var item = function (act, icon, label, danger) {
      return '<button type="button" class="pr-pop__item' + (danger ? " is-danger" : "") + '" data-vact="' + act + '" data-key="' + esc(key) + '">' +
        '<i class="fa-solid ' + icon + '"></i> ' + esc(label) + "</button>";
    };
    var last = VIEWS.tabs.length <= 1;
    var html = '<div class="pr-pop__head">' + esc(tabLabel(key)) + "</div>";
    if (isSys(key)) {
      html += '<p class="pr-pop__note">Default view. You can hide it from your tabs.</p>' +
        item("duplicate", "fa-copy", "Save a copy as my view") +
        (last ? "" : item("remove", "fa-eye-slash", "Hide from my tabs"));
    } else if (v && v.mine) {
      html += item("rename", "fa-pen", "Rename") +
        item("duplicate", "fa-copy", "Duplicate") +
        item("share", v.shared ? "fa-lock" : "fa-user-group", v.shared ? "Make private" : "Share with the team") +
        (last ? "" : item("remove", "fa-eye-slash", "Remove from my tabs")) +
        item("delete", "fa-trash", "Delete view", true);
    } else if (v) {
      html += '<p class="pr-pop__note">Shared by ' + esc(v.owner_name || v.owner_email) + ". Only they can edit it; duplicate it to have your own.</p>" +
        item("duplicate", "fa-copy", "Duplicate") +
        (last ? "" : item("remove", "fa-eye-slash", "Remove from my tabs"));
    }
    openPop(anchor, html);
  }

  function addMenu(anchor) {
    var hidden = Object.keys(SYS_TABS).filter(function (k) { return VIEWS.tabs.indexOf(k) === -1; });
    var notInTabs = VIEWS.views.filter(function (v) { return VIEWS.tabs.indexOf("v:" + v.id) === -1; });
    var row = function (key, label, sub) {
      return '<button type="button" class="pr-pop__item" data-vact="add" data-key="' + esc(key) + '"><i class="fa-solid fa-table-list"></i> ' +
        esc(label) + (sub ? ' <span class="pr-pop__sub">' + esc(sub) + "</span>" : "") + "</button>";
    };
    var existing = hidden.map(function (k) { return row(k, SYS_TABS[k], "default"); }).join("") +
      notInTabs.map(function (v) { return row("v:" + v.id, v.name, v.mine ? (v.shared ? "mine · shared" : "mine") : "by " + (v.owner_name || v.owner_email)); }).join("");
    openPop(anchor,
      '<div class="pr-pop__head">Create new view</div>' +
      '<form class="pr-pop__form" id="prViewCreate">' +
        '<input class="pr-filter__input" id="prViewName" maxlength="60" placeholder="View name" autocomplete="off" required>' +
        '<label class="pr-check"><input type="radio" name="prViewFrom" value="current" checked> Start from the current view (filters, columns, sort)</label>' +
        '<label class="pr-check"><input type="radio" name="prViewFrom" value="blank"> Start blank</label>' +
        '<label class="pr-check"><input type="checkbox" id="prViewShared"> Share with the team</label>' +
        '<button type="submit" class="pr-btn pr-btn--primary"><i class="fa-solid fa-plus"></i> Create view</button>' +
      "</form>" +
      '<div class="pr-pop__head pr-pop__head--sep">Add an existing view</div>' +
      (existing || '<p class="pr-pop__note">Nothing to add: every view you can see is already in your tabs. Views your teammates share show up here.</p>'));
    setTimeout(function () { var n = $("prViewName"); if (n) n.focus(); }, 0);
  }

  function saveTabs(tabs) {
    VIEWS.tabs = tabs;
    renderTabs();
    return api("/prospecting/views/tabs", { method: "PUT", body: JSON.stringify({ tabs: tabs }) })
      .then(function (r) { VIEWS.tabs = r.tabs; renderTabs(); })
      .catch(function (err) { alert("Could not save your tabs: " + err.message); });
  }

  function createView(name, config, shared) {
    return api("/prospecting/views", { method: "POST", body: JSON.stringify({ name: name, config: config, shared: !!shared }) })
      .then(function (v) {
        VIEWS.views.push(v);
        if (VIEWS.tabs.indexOf("v:" + v.id) === -1) VIEWS.tabs.push("v:" + v.id);
        applyTab("v:" + v.id);
        toast('<i class="fa-solid fa-table-list"></i> View <strong>' + esc(v.name) + "</strong> created" + (v.shared ? " and shared with the team." : ". Only you can see it."));
      });
  }
  function patchView(v, patch) {
    return api("/prospecting/views/" + v.id, { method: "PATCH", body: JSON.stringify(patch) }).then(function (nv) {
      Object.assign(v, nv);
      return v;
    });
  }
  function viewError(err) { alert(err.errors ? err.errors.join("\n") : err.message); }

  /* Config de una pestaña (la activa con sus cambios, o como está guardada). */
  function configOf(key) {
    if (key === state.view) return configToSave();
    var v = viewOf(key);
    if (v) return JSON.parse(JSON.stringify(v.config || {}));
    return { filters: Object.assign({}, SYS_OVERRIDES[key] || {}), columns: localCols(), page_size: state.pageSize };
  }

  function onViewAction(act, key) {
    var v = viewOf(key);
    closePop();
    if (act === "add") {
      if (VIEWS.tabs.indexOf(key) === -1) saveTabs(VIEWS.tabs.concat([key])).then(function () { applyTab(key); });
      return;
    }
    if (act === "remove") {
      var rest = VIEWS.tabs.filter(function (k) { return k !== key; });
      if (!rest.length) return;
      saveTabs(rest).then(function () { if (state.view === key) applyTab(VIEWS.tabs[0]); });
      return;
    }
    if (act === "duplicate") {
      var name = prompt("Name for the new view:", tabLabel(key) + " (copy)");
      if (name && name.trim()) createView(name.trim(), configOf(key), false).catch(viewError);
      return;
    }
    if (!v || !v.mine) return;
    if (act === "rename") {
      var nn = prompt("New name:", v.name);
      if (nn && nn.trim() && nn.trim() !== v.name) patchView(v, { name: nn.trim() }).then(renderTabs).catch(viewError);
    } else if (act === "share") {
      patchView(v, { shared: !v.shared }).then(function () {
        renderTabs();
        toast(v.shared ? "Now your teammates can add <strong>" + esc(v.name) + "</strong> from the + button. Only you can edit it."
                       : "<strong>" + esc(v.name) + "</strong> is private again.");
      }).catch(viewError);
    } else if (act === "delete") {
      if (!confirm("Delete the view «" + v.name + "»?" + (v.shared ? " Teammates who added it will lose it too." : "") + " This cannot be undone.")) return;
      api("/prospecting/views/" + v.id, { method: "DELETE" }).then(function () {
        VIEWS.views = VIEWS.views.filter(function (x) { return x.id !== v.id; });
        VIEWS.tabs = VIEWS.tabs.filter(function (k) { return k !== key; });
        if (!VIEWS.tabs.length) VIEWS.tabs = ["sys:all"];
        if (state.view === key) applyTab(VIEWS.tabs[0]); else renderTabs();
      }).catch(viewError);
    }
  }

  function onViewBar(act) {
    var v = viewOf(state.view);
    if (act === "reset") { applyTab(state.view); return; }
    if (act === "save" && v && v.mine) {
      patchView(v, { config: configToSave() }).then(function () {
        baseline = canon(snapshot());
        renderViewBar();
        toast("View <strong>" + esc(v.name) + "</strong> saved.");
      }).catch(viewError);
      return;
    }
    if (act === "saveas") {
      var name = prompt("Name for the new view:", v ? v.name + " (copy)" : tabLabel(state.view) + " (mine)");
      if (name && name.trim()) createView(name.trim(), configToSave(), false).catch(viewError);
    }
  }

  function bindViews() {
    var dragTab = null;
    $("prTabs").addEventListener("click", function (e) {
      var more = e.target.closest("[data-tab-menu]");
      if (more) { e.stopPropagation(); tabMenu(more, more.getAttribute("data-tab-menu")); return; }
      if (e.target.closest("#prViewAdd")) { e.stopPropagation(); addMenu($("prViewAdd")); return; }
      var tab = e.target.closest(".pr-tab");
      if (!tab) return;
      if (tab.hasAttribute("data-tab")) { switchTab(tab.getAttribute("data-tab")); return; }
      var kind = tab.getAttribute("data-view");
      if (kind !== "workflows" && kind !== "contacts") return;
      showSection(kind);
      renderTabs();
      if (kind === "workflows") { if (window.ProspectingWorkflows) window.ProspectingWorkflows.show(); }
      else { loadContacts(); loadInbox(); }
    });
    // Reordenar pestañas arrastrando.
    $("prViewTabs").addEventListener("dragstart", function (e) {
      var t = e.target.closest("[data-tab]");
      if (!t) return;
      dragTab = t.getAttribute("data-tab");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", dragTab); } catch (err) {}
    });
    $("prViewTabs").addEventListener("dragover", function (e) {
      if (dragTab && e.target.closest("[data-tab]")) e.preventDefault();
    });
    $("prViewTabs").addEventListener("drop", function (e) {
      var t = e.target.closest("[data-tab]");
      if (!dragTab || !t) return;
      e.preventDefault();
      var target = t.getAttribute("data-tab");
      if (target === dragTab) { dragTab = null; return; }
      var tabs = VIEWS.tabs.filter(function (k) { return k !== dragTab; });
      var at = tabs.indexOf(target);
      if (VIEWS.tabs.indexOf(dragTab) < VIEWS.tabs.indexOf(target)) at++;
      tabs.splice(at, 0, dragTab);
      dragTab = null;
      saveTabs(tabs);
    });
    $("prViewPop").addEventListener("click", function (e) {
      e.stopPropagation();
      var b = e.target.closest("[data-vact]");
      if (b) onViewAction(b.getAttribute("data-vact"), b.getAttribute("data-key"));
    });
    $("prViewPop").addEventListener("submit", function (e) {
      e.preventDefault();
      var name = $("prViewName").value.trim();
      if (!name) return;
      var fromCurrent = (document.querySelector('input[name="prViewFrom"]:checked') || {}).value !== "blank";
      var cfg = fromCurrent ? configToSave() : { filters: {}, columns: defaultCols(), page_size: 25 };
      var shared = $("prViewShared").checked;
      closePop();
      createView(name, cfg, shared).catch(viewError);
    });
    document.addEventListener("click", closePop);
    window.addEventListener("resize", closePop);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePop(); });
    $("prViewBar").addEventListener("click", function (e) {
      var b = e.target.closest("[data-vb]");
      if (b) onViewBar(b.getAttribute("data-vb"));
    });
    $("prAdvBtn").addEventListener("click", openAdvanced);
    $("prAdvSummary").addEventListener("click", function (e) {
      var b = e.target.closest("[data-adv]");
      if (!b) return;
      if (b.getAttribute("data-adv") === "edit") { openAdvanced(); return; }
      state.advanced = null;
      state.page = 1;
      renderAdvSummary();
      load();
    });
  }

  /* ---------- Arranque ---------- */
  function refreshOptions() {
    return api("/prospecting/options").then(function (o) {
      OPTS = o;
      var keep = { owner: $("prFOwner").value, week: $("prFWeek").value, status: $("prFStatus").value };
      fillFilters();
      $("prFOwner").value = keep.owner;
      $("prFWeek").value = keep.week;
      $("prFStatus").value = keep.status;
    });
  }

  function bind() {
    bindViews();
    ["prFOwner", "prFWeek", "prFStatus", "prFStartFrom", "prFStartTo", "prFDummy", "prFIncomplete"].forEach(function (id) {
      $(id).addEventListener("change", function () { state.page = 1; load(); });
    });
    var t = null;
    $("prFQ").addEventListener("input", function () {
      clearTimeout(t);
      t = setTimeout(function () { state.page = 1; load(); }, 300);
    });
    $("prClear").addEventListener("click", function () {
      ["prFOwner", "prFWeek", "prFStatus", "prFStartFrom", "prFStartTo", "prFQ"].forEach(function (id) { $(id).value = ""; });
      $("prFIncomplete").checked = false;
      state.advanced = null;
      renderAdvSummary();
      state.page = 1;
      load();
    });
    $("prPageSize").addEventListener("change", function () {
      state.pageSize = Number($("prPageSize").value);
      state.page = 1;
      load();
    });
    $("prPrev").addEventListener("click", function () { if (state.page > 1) { state.page--; load(); } });
    $("prNext").addEventListener("click", function () { state.page++; load(); });
    // Los <th> se regeneran al cambiar columnas: delegación sobre el <tr>.
    // Click en el encabezado: ascendente → descendente → sin orden.
    $("prHead").addEventListener("click", function (e) {
      var th = e.target.closest("th[data-sort]");
      if (!th) return;
      var key = th.getAttribute("data-sort"), cur = parseSort(state.sort);
      state.sort = !cur || cur.key !== key ? key + ":asc" : cur.dir === "asc" ? key + ":desc" : "created_desc";
      state.page = 1;
      renderHead();
      load();
    });
    $("prColsBtn").addEventListener("click", function (e) {
      e.stopPropagation();
      var menu = $("prColsMenu");
      menu.hidden = !menu.hidden;
      $("prColsBtn").setAttribute("aria-expanded", String(!menu.hidden));
    });
    $("prColsMenu").addEventListener("click", function (e) { e.stopPropagation(); });
    document.addEventListener("click", function () {
      $("prColsMenu").hidden = true;
      $("prColsBtn").setAttribute("aria-expanded", "false");
    });
    $("prColsMenu").addEventListener("change", function (e) {
      var key = e.target.getAttribute("data-col");
      if (!key) return;
      var next = visibleCols.filter(function (k) { return k !== key; });
      if (e.target.checked) next.push(key);  // una columna nueva entra al final
      setVisibleCols(next);
    });
    $("prColsMenu").addEventListener("click", function (e) {
      var mode = e.target.closest("[data-cols]");
      if (!mode) return;
      setVisibleCols(mode.getAttribute("data-cols") === "all"
        ? visibleCols.concat(COLUMNS.map(function (c) { return c.key; }))
        : defaultCols());
    });
    // Reordenar columnas arrastrando dentro del menú.
    var dragCol = null;
    $("prColsMenu").addEventListener("dragstart", function (e) {
      var it = e.target.closest("[data-col-item]");
      if (!it) return;
      dragCol = it.getAttribute("data-col-item");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", dragCol); } catch (err) {}
      it.classList.add("is-dragging");
    });
    $("prColsMenu").addEventListener("dragover", function (e) {
      var it = e.target.closest("[data-col-item]");
      if (!dragCol || !it) return;
      e.preventDefault();
      Array.prototype.forEach.call($("prColsMenu").querySelectorAll(".is-drop"), function (x) { x.classList.remove("is-drop"); });
      it.classList.add("is-drop");
    });
    $("prColsMenu").addEventListener("drop", function (e) {
      var it = e.target.closest("[data-col-item]");
      if (!dragCol || !it) return;
      e.preventDefault();
      var target = it.getAttribute("data-col-item");
      var next = visibleCols.filter(function (k) { return k !== dragCol; });
      var at = next.indexOf(target);
      // Soltar sobre una fila de más abajo la deja después; de más arriba, antes.
      if (visibleCols.indexOf(dragCol) < visibleCols.indexOf(target)) at++;
      next.splice(at, 0, dragCol);
      dragCol = null;
      setVisibleCols(next);
    });
    $("prColsMenu").addEventListener("dragend", function () { dragCol = null; renderColsMenu(); });
    $("prBody").addEventListener("change", function (e) {
      var sel = e.target.getAttribute && e.target.getAttribute("data-sel");
      if (sel) {
        if (e.target.checked) selected[sel] = true; else delete selected[sel];
        if (!e.target.checked) selAll = null;  // destildar una saca del modo «todas»
        e.target.closest("tr").classList.toggle("is-selected", e.target.checked);
        renderBulk();
        return;
      }
      onCellChange(e);
    });
    $("prHead").addEventListener("change", function (e) {
      if (e.target.id !== "prSelAll") return;
      lastRows.forEach(function (r) { if (e.target.checked) selected[r.id] = true; else delete selected[r.id]; });
      if (!e.target.checked) selAll = null;
      renderRows(lastRows);
    });
    $("prBulk").addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      if (b.id === "prBulkGo") bulkEnroll();
      if (b.id === "prBulkClear") { selected = {}; selAll = null; renderRows(lastRows); }
      if (b.hasAttribute("data-bulk-edit")) openBulkEdit("company");
      if (b.hasAttribute("data-bulk-all")) {
        var f = currentFilters();
        delete f.page; delete f.page_size; delete f.sort;
        selAll = { filters: f, total: state.total };
        renderBulk();
      }
    });
    $("prBody").addEventListener("click", function (e) {
      var inc = e.target.closest("[data-complete]");
      if (inc) {
        var cid = Number(inc.getAttribute("data-complete"));
        api("/prospecting/companies/" + cid).then(function (c) {
          window.ProspectingContacts.completeFlow(c, c.contacts || [], function () { load(); });
        });
        return;
      }
      var btn = e.target.closest("[data-open]");
      if (btn) showCompany(Number(btn.getAttribute("data-open")));
    });
    document.querySelectorAll("[data-drawer-close]").forEach(function (el) {
      el.addEventListener("click", closeDrawer);
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });
    $("prDrawerSave").addEventListener("click", function () { if (drawerSave) drawerSave(); });
    $("prTestBtn").addEventListener("click", showTestPanel);
    $("prBdrIdsBtn").addEventListener("click", showBdrIds);
  }

  function init() {
    api("/prospecting/me").then(function (me) {
      if (!me.has_access) {
        $("prDenied").hidden = false;
        return;
      }
      ME = me;
      $("prApp").hidden = false;
      if (me.is_admin) {
        $("prTestBtn").hidden = false;
        $("prBdrIdsBtn").hidden = false;
      }
      if (me.sees_dummies) $("prFDummyWrap").hidden = false;
      bind();
      bindContacts();
      return Promise.all([refreshOptions(), loadViews()]).then(function () {
        var saved = null;
        try { saved = localStorage.getItem(ACTIVE_KEY); } catch (e) {}
        var tabs = VIEWS.tabs;
        applyTab(tabs.indexOf(saved) !== -1 ? saved : (tabs[0] || "sys:all"));
      });
    }).catch(function (err) {
      $("prDenied").hidden = false;
      $("prDenied").querySelector("p").textContent = "Could not load Prospecting: " + err.message;
    });
  }

  // Lo que usa prospecting-workflows.js (mismo API base, mismas opciones, mismo formato).
  window.Prospecting = {
    api: api,
    esc: esc,
    fmtDate: fmtDate,
    fmtDateTime: fmtDateTime,
    todayIso: todayIso,
    toast: toast,
    ownerName: ownerName,
    options: function () { return OPTS; },
    me: function () { return ME; },
    reloadTable: function () { return load(); },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
