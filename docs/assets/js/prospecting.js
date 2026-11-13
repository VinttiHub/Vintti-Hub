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
            err.data = data;  // p. ej. needs_fields de un negocio (409)
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
  /* Prospecting Owner (2026-11-13): los BDRs no lo cambian. Con owner, sólo su líder
     (users.lider → ME.led_bdrs) y con la empresa en Recycled; sin owner, cualquier líder.
     La owner siempre. Misma regla que store.can_change_owner(): el server frena igual. */
  var OWNER_LOCK_TIP = "Only the BDR's leader can reassign it, with the company in Recycled";
  function isLeader() { return !!ME.is_admin || !!(ME.led_bdrs || []).length; }
  function canChangeOwner(r) {
    if (ME.is_admin) return true;
    var led = ME.led_bdrs || [];
    var owner = String((r && r.prospecting_owner_email) || "").toLowerCase();
    if (!owner) return led.length > 0;
    return led.indexOf(owner) !== -1 && (r.prospecting_status || "") === "Recycled";
  }
  function ownerLocked(email) {
    return '<span class="pr-owner-locked" title="' + esc(OWNER_LOCK_TIP) + '"><i class="fa-solid fa-lock"></i> ' +
      esc(email ? ownerName(email) : "—") + "</span>";
  }
  function ownerCell(r) {
    return '<span class="pr-owner-cell">' + (canChangeOwner(r)
      ? cellSelect("prospecting_owner_email", ownerOptions(), r.prospecting_owner_email)
      : ownerLocked(r.prospecting_owner_email)) + "</span>";
  }
  function errMsg(err) { return (err && err.data && err.data.message) || (err && err.message) || ""; }
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
    if (segmentOf(state.view)) f.segment = viewOf(state.view).id;
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
     `def: true` = visibles por defecto (las de la vista "Companies"). */
  function cellText(v) { return v == null || v === "" ? "—" : esc(v); }
  function cellLong(v) {
    return v == null || v === "" ? "—" : '<span class="pr-long" title="' + esc(v) + '">' + esc(v) + "</span>";
  }
  // Clay guarda el website sin protocolo ("ror.com"): sin esto el href es relativo y abre
  // vinttihub.vintti.com/ror.com (404 de GitHub Pages).
  function extUrl(v) {
    var s = String(v || "").trim();
    return !s ? "" : /^[a-z][a-z0-9+.-]*:/i.test(s) ? s : "https://" + s.replace(/^\/+/, "");
  }
  function cellLink(v) {
    return v ? '<a class="pr-link" href="' + esc(extUrl(v)) + '" target="_blank" rel="noopener" title="' + esc(v) + '">' + esc(String(v).replace(/^https?:\/\/(www\.)?/, "")) + "</a>" : "—";
  }
  function cellSelect(field, list, value, extraClass) {
    return '<select class="pr-cell-select' + (extraClass || "") + '" data-field="' + field + '"' +
      (field === "prospecting_status" ? ' data-status="' + esc(value || "") + '"' : "") + ">" +
      optionsHtml(withCurrent(list, value), value || "", "—") + "</select>";
  }

  var COLUMNS = [
    { key: "name", label: "Nombre de la empresa", sort: "name", fixed: true, render: function (r) {
        var domain = r.domain
          ? '<a class="pr-company__domain" href="' + esc(extUrl(r.website || r.domain)) + '" target="_blank" rel="noopener">' + esc(r.domain) + "</a>"
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
        return ownerCell(r);
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
    { key: "tier", label: "Tier", render: function (r) { return cellText(r.tier); } },
    { key: "remote_jobs", label: "Remote?", render: function (r) { return cellText(r.remote_jobs); } },
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
  function sortable() { return true; }
  /* `<campo>:<modo>` (backend: store.order_sql). asc/desc = A→Z, menor→mayor, antigua→reciente
     según el tipo; list_asc/list_desc = el orden de las opciones de la lista. */
  function parseSort(s) {
    var m = /^([a-z0-9_]+):(asc|desc|list_asc|list_desc)$/.exec(s || "");
    return m ? { key: m[1], mode: m[2], dir: m[2] === "asc" || m[2] === "list_asc" ? "asc" : "desc" } : null;
  }
  /* Las formas de ordenar según el tipo de la columna. */
  function sortOptions(f) {
    var t = f.type, o = f.options || [];
    var az = [{ mode: "asc", label: "A → Z" }, { mode: "desc", label: "Z → A" }];
    if (t === "number") return [{ mode: "asc", label: "Menor a mayor" }, { mode: "desc", label: "Mayor a menor" }];
    if (t === "date" || t === "datetime") return [{ mode: "desc", label: "Más recientes primero" }, { mode: "asc", label: "Más antiguas primero" }];
    if (t === "bool") return [{ mode: "desc", label: "Sí primero" }, { mode: "asc", label: "No primero" }];
    if (t === "owner" || t === "user") return [{ mode: "asc", label: "Nombre A → Z" }, { mode: "desc", label: "Nombre Z → A" }];
    if (t === "enum" && o.length) {
      return [{ mode: "list_asc", label: "Orden de la lista (" + o[0] + " → " + o[o.length - 1] + ")" },
              { mode: "list_desc", label: "Orden de la lista, al revés (" + o[o.length - 1] + " → " + o[0] + ")" }].concat(az);
    }
    return az;
  }
  function sortLabel(f, mode) {
    var hit = sortOptions(f).filter(function (x) { return x.mode === mode; })[0];
    return hit ? hit.label : "";
  }
  /* Menú del encabezado: elegir cómo ordenar esa columna (o quitar el orden). */
  function sortMenu(th, obj, f, current) {
    var cur = parseSort(current);
    var on = cur && cur.key === f.key;
    openPop(th, '<div class="pr-pop__head">Ordenar por ' + esc(f.label) + "</div>" +
      sortOptions(f).map(function (x) {
        var active = on && cur.mode === x.mode;
        return '<button type="button" class="pr-pop__item' + (active ? " is-on" : "") + '" data-sortpick="' + esc(f.key + ":" + x.mode) + '" data-sortobj="' + obj + '">' +
          '<i class="fa-solid ' + (active ? "fa-check" : /desc/.test(x.mode) ? "fa-arrow-down-wide-short" : "fa-arrow-up-short-wide") + '"></i> ' + esc(x.label) + "</button>";
      }).join("") +
      (on ? '<button type="button" class="pr-pop__item" data-sortpick="" data-sortobj="' + obj + '"><i class="fa-solid fa-xmark"></i> Quitar orden</button>' : "") +
      '<p class="pr-pop__note">Los vacíos van siempre al final.</p>');
    $("prViewPop").classList.add("pr-pop--actions");
  }
  function sortArrow(on, cur) {
    return on ? ' <i class="fa-solid fa-arrow-' + (cur.dir === "asc" ? "up" : "down") + ' pr-sort-arrow"></i>' : "";
  }
  function companyFieldOf(key) {
    var c = COL_BY_KEY[key] || { key: key, label: key };
    var f = ((((OPTS.objects || {}).company || {}).fields) || []).filter(function (x) { return x.key === key; })[0] || {};
    return { key: key, label: c.label, type: key === "contacts_count" ? "number" : f.type, options: f.options };
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
      var arrow = sortArrow(on, cur);
      var tip = on ? "Ordenado: " + sortLabel(companyFieldOf(c.key), cur.mode) : "Ordenar · arrastrar para mover";
      return "<th" + (sortable(c) ? ' data-sort="' + c.key + '" title="' + esc(tip) + '"' : "") + (cls ? ' class="' + cls + '"' : "") +
        (c.fixed ? "" : ' draggable="true" data-col-drag="' + c.key + '"') + ">" + esc(c.label) + arrow + "</th>";
    }).join("");
    $("prColsCount").textContent = activeColumns().length + "/" + COLUMNS.length;
  }

  /* Arrastrar una columna desde el encabezado de la tabla y soltarla a la izquierda o a la
     derecha de otra (además del menú Columns). Empresas y contactos. Las fijas (el nombre)
     no se mueven: los <th> movibles llevan data-col-drag. */
  function bindHeaderDrag(tr, getCols, setCols) {
    var drag = null, side = "before";
    var clear = function () {
      Array.prototype.forEach.call(tr.querySelectorAll(".is-drop-before, .is-drop-after, .is-dragging"), function (x) {
        x.classList.remove("is-drop-before", "is-drop-after", "is-dragging");
      });
    };
    tr.addEventListener("dragstart", function (e) {
      var th = e.target.closest && e.target.closest("th[data-col-drag]");
      if (!th) return;
      drag = th.getAttribute("data-col-drag");
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", drag); } catch (err) {}
      th.classList.add("is-dragging");
    });
    tr.addEventListener("dragover", function (e) {
      var th = drag && e.target.closest("th[data-col-drag]");
      if (!th) return;
      e.preventDefault();
      var r = th.getBoundingClientRect();
      side = e.clientX > r.left + r.width / 2 ? "after" : "before";
      Array.prototype.forEach.call(tr.querySelectorAll(".is-drop-before, .is-drop-after"), function (x) { x.classList.remove("is-drop-before", "is-drop-after"); });
      if (th.getAttribute("data-col-drag") !== drag) th.classList.add("is-drop-" + side);
    });
    tr.addEventListener("drop", function (e) {
      var th = drag && e.target.closest("th[data-col-drag]");
      if (!th) return;
      e.preventDefault();
      var target = th.getAttribute("data-col-drag");
      var moving = drag;
      drag = null;
      clear();
      if (target === moving) return;
      var next = getCols().filter(function (k) { return k !== moving; });
      next.splice(next.indexOf(target) + (side === "after" ? 1 : 0), 0, moving);
      setCols(next);
    });
    tr.addEventListener("dragend", function () { drag = null; clear(); });
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

  /* Campos del BDR que se editan haciendo click en la celda (Owner, Status y Not ICP ya son
     <select>). Los de Clay quedan de lectura: los pisa Clay en cada envío. */
  var CO_INLINE = { prospecting_start_date: true, week_label: true, lead_source: true };
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
        var cls = [c.num ? "pr-num" : "", CO_INLINE[c.key] ? "pr-cell-edit" : ""].filter(Boolean).join(" ");
        return "<td" + (cls ? ' class="' + cls + '"' : "") + (CO_INLINE[c.key] ? ' data-co-edit="' + c.key + '" title="Click para editar"' : "") + ">" +
          c.render(r) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    renderBulk();
  }

  /* Barra: «N seleccionadas · [Seleccionar las N del filtro] · Acciones ▾ · Deseleccionar». */
  function selectionHead(n, allMode, pageAll, total, noun, kind) {
    return "<strong>" + (allMode ? "Todas las " + total.toLocaleString() : n) + "</strong> " + noun + (n === 1 && !allMode ? "" : "s") +
      " seleccionada" + (n === 1 && !allMode ? "" : "s") +
      (pageAll && !allMode && total > n
        ? '<button type="button" class="pr-wf-link pr-bulk__all" data-bulk-all="1">Seleccionar las ' + total.toLocaleString() + " que coinciden con los filtros</button>" : "") +
      '<button type="button" class="pr-btn pr-btn--primary pr-bulk__actions" data-bulk-actions="' + kind + '" aria-haspopup="menu">' +
        'Acciones <i class="fa-solid fa-chevron-down"></i></button>';
  }
  /* Tilde del encabezado: marcado si está toda la página, «parcial» si sólo algunas.
     Se sincroniza en cada redibujo: si no, después de editar quedaba tildado con la
     selección ya vacía y había que destildarlo y volver a tildarlo. */
  function syncHeadCheck(el, rows, sel) {
    if (!el) return;
    var on = rows.filter(function (r) { return sel[r.id]; }).length;
    el.checked = rows.length > 0 && on === rows.length;
    el.indeterminate = on > 0 && on < rows.length;
  }
  function renderBulk() {
    var bar = $("prBulk");
    var ids = Object.keys(selected);
    syncHeadCheck($("prSelAll"), lastRows, selected);
    if (!canSelect() || (!ids.length && !selAll)) { bar.hidden = true; return; }
    var pageAll = lastRows.length > 0 && lastRows.every(function (r) { return selected[r.id]; });
    bar.hidden = false;
    bar.innerHTML = selectionHead(ids.length, !!selAll, pageAll, state.total, "empresa", "company") +
      '<button type="button" class="pr-btn" id="prBulkClear">Deseleccionar</button>';
  }

  /* Menú «Acciones»: editar una propiedad o inscribir en un workflow (este, sólo quien
     edita workflows y con filas tildadas: inscribir trabaja con ids). */
  function bulkActionsMenu(anchor, kind) {
    var all = kind === "company" ? selAll : ctSelAll;
    var item = function (act, icon, label, disabled, note) {
      return '<button type="button" class="pr-pop__item' + (disabled ? " is-disabled" : "") + '" data-bact="' + act + '" data-kind="' + kind + '"' +
        (disabled ? ' disabled' : "") + '><i class="fa-solid ' + icon + '"></i> ' + label +
        (note ? '<span class="pr-pop__sub">' + note + "</span>" : "") + "</button>";
    };
    openPop(anchor, '<div class="pr-pop__head">Acciones</div>' +
      item("edit", "fa-pen", "Editar propiedad") +
      item("export", "fa-file-csv", "Exportar a CSV") +
      item("segment", "fa-layer-group", "Por segmento", false, "Vista nueva sólo con estas filas") +
      (canEnroll() ? item("enroll", "fa-diagram-project", "Inscribir en workflow", !!all, all ? "Sólo con filas tildadas" : "") : "") +
      // Eliminar: todos menos los BDRs (ME.can_delete, 2026-11-09); el server frena igual.
      (ME.can_delete ? item("delete", "fa-trash", "Eliminar", false, "No se puede deshacer").replace("pr-pop__item", "pr-pop__item is-danger") : ""));
    $("prViewPop").classList.add("pr-pop--actions");
  }

  var wfChoicesByObj = {};
  function workflowChoices(kind) {
    if (wfChoicesByObj[kind]) return Promise.resolve(wfChoicesByObj[kind]);
    return window.ProspectingWorkflows.workflows().then(function (r) {
      wfChoicesByObj.company = r.workflows.filter(function (w) { return (w.object || "company") === "company"; });
      wfChoicesByObj.contact = r.workflows.filter(function (w) { return w.object === "contact"; });
      return wfChoicesByObj[kind];
    });
  }
  function openEnrollModal(kind) {
    var isCo = kind === "company";
    var n = Object.keys(isCo ? selected : ctSelected).length;
    var noun = isCo ? (n === 1 ? "empresa" : "empresas") : (n === 1 ? "contacto" : "contactos");
    var box = document.createElement("div");
    box.className = "pr-modal";
    box.innerHTML = '<div class="pr-modal__card pr-bulkedit" role="dialog" aria-modal="true">' +
      "<h3>Inscribir " + n + " " + noun + " en un workflow</h3>" +
      '<label class="pr-filter"><span class="pr-filter__label">Workflow</span>' +
        '<select class="pr-filter__input" id="prEnWf"><option value="">Cargando…</option></select></label>' +
      '<p class="pr-note">Corre en el momento aunque el workflow esté inactivo. Las que ya están adentro no se repiten.</p>' +
      '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-en="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-en="go"><i class="fa-solid fa-diagram-project"></i> Inscribir</button></div></div>';
    document.body.appendChild(box);
    var close = function () { box.remove(); document.removeEventListener("keydown", onKey); };
    var onKey = function (e) { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    workflowChoices(kind).then(function (list) {
      box.querySelector("#prEnWf").innerHTML = list.length
        ? '<option value="">Elegí un workflow…</option>' + list.map(function (w) {
            return '<option value="' + w.id + '">' + esc(w.name) + (w.enabled ? "" : " (inactivo)") + "</option>";
          }).join("")
        : '<option value="">No hay workflows de ' + (isCo ? "empresas" : "contactos") + "</option>";
    });
    box.addEventListener("click", function (e) {
      if (e.target === box) return close();
      var b = e.target.closest("[data-en]");
      if (!b) return;
      if (b.getAttribute("data-en") === "cancel") return close();
      var sel = box.querySelector("#prEnWf");
      if (!sel.value) { alert("Elegí un workflow."); return; }
      var wfId = sel.value, wfName = sel.selectedOptions[0].textContent;
      close();
      bulkEnroll(kind, wfId, wfName);
    });
  }

  var enrolling = false;
  function bulkEnroll(kind, wfId, wfName) {
    if (enrolling) return;  // un segundo click mientras corre inscribía todo dos veces
    var isCo = kind === "company";
    var ids = Object.keys(isCo ? selected : ctSelected).map(Number);
    var bar = $(isCo ? "prBulk" : "prCtBulk");
    var noun = isCo ? (ids.length === 1 ? "empresa" : "empresas") : (ids.length === 1 ? "contacto" : "contactos");
    enrolling = true;
    bar.classList.add("is-busy");
    var done = progress("Inscribiendo " + ids.length + " " + noun + " en <strong>" + esc(wfName) + "</strong>…");
    window.ProspectingWorkflows.enrollCompanies(wfId, ids).then(function (r) {
      enrolling = false;
      bar.classList.remove("is-busy");
      toast('<i class="fa-solid fa-diagram-project"></i> Se inscribieron <strong>' + r.enrolled + "</strong> de " + ids.length +
        (r.enrolled < ids.length ? " (" + (isCo ? "las demás ya estaban adentro" : "los demás ya estaban adentro") + " o el workflow no reinscribe)" : "") +
        (r.completed ? " · " + r.completed + " ya terminaron el workflow" : "") + ".");
      if (isCo) { selected = {}; selAll = null; load(); } else { ctSelected = {}; ctSelAll = null; loadContacts(); }
    }).catch(function (err) {
      enrolling = false;
      bar.classList.remove("is-busy");
      done();
      alert(err.errors ? err.errors.join("\n") : err.message);
    });
  }

  /* ---------- Exportar a CSV (Acciones → «Exportar a CSV») ----------
     Los tildados o todos los del filtro, con las columnas que se elijan. Arranca con las
     columnas que se ven en la tabla; el CSV lo arma el backend (POST /<obj>/export). */
  function download(path, body, filename) {
    var send = function (base) {
      return fetch(base + path, { method: "POST", body: JSON.stringify(body),
        headers: { "X-User-Email": userEmail(), "Content-Type": "application/json" } });
    };
    return send(API).catch(function () { if (!canFallBack) throw new Error("Could not reach " + API + "."); canFallBack = false; API = PROD; return send(API); })
      .then(function (res) {
        if (!res.ok) return res.json().catch(function () { return {}; }).then(function (d) { throw new Error(d.error || ("HTTP " + res.status)); });
        return res.blob().then(function (blob) {
          var a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
        });
      });
  }
  /* Modal con la lista de columnas: buscador, «Las de la tabla · Todas · Ninguna», grupos.
     Lo usan Exportar, Por segmento y «Editar columnas» de una vista de contactos.
     o = { title, fields: [{key, label, group, fixed}], tableCols, top, bottom, goIcon, goLabel,
           busyLabel, onGo(cols, box) → Promise }. Las de la tabla salen primero y en su orden. */
  function columnsModal(o) {
    var fields = o.fields, tableCols = o.tableCols;
    var rank = function (k) { var i = tableCols.indexOf(k); return i === -1 ? 1000 + fields.findIndex(function (f) { return f.key === k; }) : i; };
    var groups = [];
    fields.forEach(function (f) {
      var g = f.group || "";
      var hit = groups.filter(function (x) { return x.name === g; })[0];
      if (!hit) groups.push(hit = { name: g, fields: [] });
      hit.fields.push(f);
    });
    var box = document.createElement("div");
    box.className = "pr-modal";
    box.innerHTML = '<div class="pr-modal__card pr-bulkedit pr-export" role="dialog" aria-modal="true">' +
      "<h3>" + o.title + "</h3>" + (o.top || "") +
      '<div class="pr-export__tools"><input type="search" class="pr-filter__input" id="prExQ" placeholder="Buscar columna…">' +
        '<button type="button" class="pr-wf-link" data-ex="table">Las de la tabla</button>' +
        '<button type="button" class="pr-wf-link" data-ex="all">Todas</button>' +
        '<button type="button" class="pr-wf-link" data-ex="none">Ninguna</button></div>' +
      '<div class="pr-export__list" id="prExList">' + groups.map(function (g) {
        return '<div class="pr-export__group">' + (g.name ? '<div class="pr-export__gname">' + esc(g.name) + "</div>" : "") +
          g.fields.map(function (f) {
            return '<label class="pr-check" data-exname="' + esc((f.label + " " + f.key).toLowerCase()) + '"' + (f.fixed ? ' title="Va siempre"' : "") +
              '><input type="checkbox" value="' + esc(f.key) + '"' + (f.fixed || tableCols.indexOf(f.key) !== -1 ? " checked" : "") +
              (f.fixed ? " disabled" : "") + "> " + esc(f.label) + "</label>";
          }).join("") + "</div>";
      }).join("") + "</div>" +
      '<p class="pr-note" id="prExCount"></p>' + (o.bottom || "") +
      '<p class="pr-bulkedit__err" id="prExErr" hidden></p>' +
      '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-ex="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-ex="go"><i class="fa-solid ' + o.goIcon + '"></i> ' + o.goLabel + "</button></div></div>";
    document.body.appendChild(box);
    var q = function (id) { return box.querySelector("#" + id); };
    var boxes = function () { return Array.prototype.slice.call(box.querySelectorAll("#prExList input")); };
    var count = function () {
      var c = boxes().filter(function (x) { return x.checked; }).length;
      q("prExCount").textContent = c + " de " + fields.length + " columnas · las de la tabla van en su orden, las demás después.";
    };
    var err = function (msg) { q("prExErr").hidden = !msg; q("prExErr").textContent = msg || ""; };
    var running = false;  // mientras corre no se cierra: cerrar y volver a apretar lo haría dos veces
    var close = function () { if (running) return; box.remove(); document.removeEventListener("keydown", onKey); };
    var onKey = function (e) { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    count();
    q("prExList").addEventListener("change", count);
    q("prExQ").addEventListener("input", function () {
      var t = this.value.trim().toLowerCase();
      box.querySelectorAll("#prExList [data-exname]").forEach(function (l) { l.hidden = !!t && l.getAttribute("data-exname").indexOf(t) === -1; });
      box.querySelectorAll(".pr-export__group").forEach(function (g) { g.hidden = !g.querySelector("[data-exname]:not([hidden])"); });
    });
    box.addEventListener("click", function (e) {
      if (e.target === box) return close();
      var b = e.target.closest("[data-ex]");
      if (!b) return;
      var act = b.getAttribute("data-ex");
      if (act === "cancel") return close();
      if (act === "table" || act === "all" || act === "none") {
        // «Todas» / «Ninguna» respetan la búsqueda: tildan sólo las que se ven.
        boxes().forEach(function (x) {
          if (x.disabled) return;
          if (act === "table") x.checked = tableCols.indexOf(x.value) !== -1;
          else if (!x.closest("[data-exname]").hidden) x.checked = act === "all";
        });
        return count();
      }
      var cols = boxes().filter(function (x) { return x.checked; }).map(function (x) { return x.value; })
        .sort(function (a, b2) { return rank(a) - rank(b2); });
      if (!cols.filter(function (k) { return !fields.filter(function (f) { return f.key === k && f.fixed; }).length; }).length &&
          !fields.some(function (f) { return f.fixed; })) return err("Elegí al menos una columna.");
      err("");
      var label = b.innerHTML;
      running = true;
      box.classList.add("is-busy");
      b.disabled = true;
      b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> ' + o.busyLabel;
      Promise.resolve().then(function () { return o.onGo(cols, box); }).then(function () {
        running = false;
        close();
      }).catch(function (e2) {
        running = false;
        box.classList.remove("is-busy");
        b.disabled = false;
        b.innerHTML = label;
        err(e2.errors ? e2.errors.join(" · ") : e2.message);
      });
    });
    return box;
  }
  function selectionInfo(kind) {
    var isCo = kind === "company";
    var all = isCo ? selAll : ctSelAll;
    var ids = Object.keys(isCo ? selected : ctSelected).map(Number);
    var n = all ? all.total : ids.length;
    return { isCo: isCo, all: all, ids: ids, n: n,
      noun: isCo ? (n === 1 ? "empresa" : "empresas") : (n === 1 ? "contacto" : "contactos"),
      target: all ? { filters: all.filters } : { ids: ids } };
  }
  function openExport(kind) {
    var si = selectionInfo(kind);
    var fields = (((OPTS.export_fields || {})[kind]) || []).map(function (f) {
      return { key: f.key, label: f.label, group: f.group || (si.isCo ? "" : "Otros") };
    });
    // En contactos la tabla tiene «Name»; el CSV lo parte en nombre y apellido.
    var tableCols = si.isCo ? visibleCols.slice() : ctColumns().reduce(function (out, k) {
      return out.concat(k === "name" ? ["first_name", "last_name"] : [k]);
    }, []);
    columnsModal({
      title: "Exportar " + si.n.toLocaleString() + " " + si.noun + " a CSV",
      fields: fields, tableCols: tableCols,
      goIcon: "fa-download", goLabel: "Descargar CSV", busyLabel: "Armando el CSV…",
      onGo: function (cols) {
        // El orden de las filas es el de la tabla (en «todas las del filtro» el sort no viaja en los filtros).
        var body = Object.assign({}, si.target, { columns: cols, sort: si.isCo ? state.sort : (ctSort || null) });
        var day = new Date().toLocaleDateString("sv-SE");  // AAAA-MM-DD, hora local
        return download("/prospecting/" + (si.isCo ? "companies" : "contacts") + "/export", body,
          "prospecting-" + (si.isCo ? "empresas" : "contactos") + "-" + day + ".csv").then(function () {
          toast('<i class="fa-solid fa-file-csv"></i> Se descargó el CSV con ' + si.n.toLocaleString() + " " + si.noun + " y " + cols.length + " columnas.");
        });
      },
    });
  }

  /* ---------- Acciones → «Por segmento» ----------
     Vista nueva con SÓLO lo seleccionado (POST /prospecting/views/segment). La lista queda
     fija: con «todas las del filtro» se guardan las de este momento, como un segmento
     estático de HubSpot. Las columnas se eligen acá. */
  function openSegment(kind) {
    var si = selectionInfo(kind);
    var fields = si.isCo
      ? COLUMNS.map(function (c) { return { key: c.key, label: c.label, fixed: !!c.fixed }; })
      : ctCatalog();
    var box = columnsModal({
      title: "Nueva vista con " + si.n.toLocaleString() + " " + si.noun,
      top: '<label class="pr-filter"><span class="pr-filter__label">Nombre de la vista</span>' +
        '<input class="pr-filter__input" id="prSegName" maxlength="60" autocomplete="off" value="' +
        esc("Segmento · " + si.n.toLocaleString() + " " + si.noun) + '"></label>' +
        '<span class="pr-filter__label">Columnas</span>',
      bottom: '<label class="pr-check"><input type="checkbox" id="prSegShared"> Compartir con el equipo</label>' +
        '<p class="pr-note">La vista muestra sólo ' + (si.isCo ? "estas " : "estos ") + si.n.toLocaleString() + " " + si.noun +
        ": lo que entre después a los filtros no se suma solo.</p>",
      fields: fields, tableCols: si.isCo ? visibleCols.slice() : ctColumns(),
      goIcon: "fa-layer-group", goLabel: "Crear vista", busyLabel: "Creando…",
      onGo: function (cols) {
        var name = box.querySelector("#prSegName").value.trim();
        if (!name) return Promise.reject(new Error("Ponele un nombre a la vista."));
        var body = Object.assign({}, si.target, { object: kind, name: name, columns: cols,
          shared: box.querySelector("#prSegShared").checked, page_size: si.isCo ? state.pageSize : 25 });
        return api("/prospecting/views/segment", { method: "POST", body: JSON.stringify(body) }).then(function (v) {
          var n = (v.config.segment_ids || []).length;
          if (si.isCo) {
            VIEWS.views.push(v);
            if (VIEWS.tabs.indexOf("v:" + v.id) === -1) VIEWS.tabs.push("v:" + v.id);
            applyTab("v:" + v.id);
          } else {
            CT_VIEWS.push(v);
            applyCtView(v.id);
          }
          toast('<i class="fa-solid fa-layer-group"></i> Vista <strong>' + esc(v.name) + "</strong> creada con " + n.toLocaleString() + " " +
            (si.isCo ? (n === 1 ? "empresa" : "empresas") : (n === 1 ? "contacto" : "contactos")) +
            (v.shared ? ", compartida con el equipo." : ". Sólo la ves vos."));
        });
      },
    });
    setTimeout(function () { var i = box.querySelector("#prSegName"); i.focus(); i.select(); }, 0);
  }

  /* ---------- Edición masiva (botón «Editar» de la barra) ----------
     Una propiedad, un valor, todos los seleccionados: POST /prospecting/<companies|contacts>/bulk.
     El backend la aplica registro por registro (historial + workflows, como de a uno). */
  function bulkFields(kind) {
    var o = (OPTS.objects || {})[kind] || {};
    return (o.fields || []).filter(function (f) {
      if (kind === "company") return f.editable && (f.key !== "prospecting_owner_email" || isLeader());
      return f.key !== "email" && f.key !== "is_primary";
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

  /* ---------- Acciones → «Eliminar» (sólo admin + editoras) ----------
     Los tildados o todos los del filtro. Una empresa borrada deja sus contactos SIN
     empresa (como HubSpot). Lo borrado queda en «Registros eliminados» (Configuración)
     y Clay / HubSpot no lo vuelven a crear. Más de 25: hay que escribir ELIMINAR. */
  function openBulkDelete(kind) {
    var isCo = kind === "company";
    var sel = isCo ? selected : ctSelected, all = isCo ? selAll : ctSelAll;
    var ids = Object.keys(sel).map(Number);
    var n = all ? all.total : ids.length;
    var noun = isCo ? (n === 1 ? "empresa" : "empresas") : (n === 1 ? "contacto" : "contactos");
    var strict = n > 25;
    var box = document.createElement("div");
    box.className = "pr-modal";
    box.innerHTML = '<div class="pr-modal__card pr-bulkedit" role="dialog" aria-modal="true">' +
      "<h3>Eliminar " + (all ? "las " : "") + n.toLocaleString() + " " + noun + (all ? " que coinciden con los filtros" : "") + "</h3>" +
      '<p class="pr-note">' + (isCo
        ? "Sus contactos <strong>no se borran</strong>: quedan sin empresa, con su historial. Sus negocios también quedan sin empresa."
        : "Se borran con sus datos; su actividad queda en el historial de la empresa. Sus negocios no se borran.") + "</p>" +
      '<p class="pr-note">No se puede deshacer. Clay y la sincronización con HubSpot no los vuelven a crear ' +
        "(se habilita de nuevo desde Configuración → Registros eliminados)." + (isCo ? "" : " Si la persona vuelve a agendar por Calendly, entra como contacto nuevo.") + "</p>" +
      (strict ? '<label class="pr-filter"><span class="pr-filter__label">Escribí ELIMINAR para confirmar</span>' +
        '<input type="text" class="pr-filter__input" id="prDelConfirm" autocomplete="off"></label>' : "") +
      '<p class="pr-bulkedit__err" id="prDelErr" hidden></p>' +
      '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-del="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--danger" data-del="go"><i class="fa-solid fa-trash"></i> Eliminar ' + n.toLocaleString() + "</button></div></div>";
    document.body.appendChild(box);
    var running = false;
    var close = function () { if (running) return; box.remove(); document.removeEventListener("keydown", onKey); };
    var onKey = function (e) { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    var err = function (msg) { var el = box.querySelector("#prDelErr"); el.innerHTML = msg; el.hidden = !msg; };
    box.addEventListener("click", function (e) {
      if (e.target === box) return close();
      var b = e.target.closest("[data-del]");
      if (!b || running) return;
      if (b.getAttribute("data-del") === "cancel") return close();
      if (strict && box.querySelector("#prDelConfirm").value.trim().toUpperCase() !== "ELIMINAR") return err("Escribí ELIMINAR para confirmar.");
      if (!strict && !confirm("¿Eliminar " + n.toLocaleString() + " " + noun + "? No se puede deshacer.")) return;
      running = true;
      box.querySelectorAll("button, input").forEach(function (x) { x.disabled = true; });
      b.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Eliminando…';
      err("");
      var body = all ? { filters: all.filters } : { ids: ids };
      api("/prospecting/" + (isCo ? "companies" : "contacts") + "/delete", { method: "POST", body: JSON.stringify(body) }).then(function (r) {
        running = false;
        close();
        toast('<i class="fa-solid fa-trash"></i> Se eliminaron <strong>' + r.deleted + "</strong> " + (isCo ? (r.deleted === 1 ? "empresa" : "empresas") : (r.deleted === 1 ? "contacto" : "contactos")) +
          (r.contacts_unlinked ? " · " + r.contacts_unlinked + " contacto" + (r.contacts_unlinked === 1 ? "" : "s") + " quedaron sin empresa" : "") + ".");
        if (isCo) { selected = {}; selAll = null; load(); } else { ctSelected = {}; ctSelAll = null; loadContacts(); }
      }).catch(function (e2) {
        running = false;
        box.querySelectorAll("button, input").forEach(function (x) { x.disabled = false; });
        b.innerHTML = '<i class="fa-solid fa-trash"></i> Eliminar ' + n.toLocaleString();
        err(esc(e2.message));
      });
    });
  }

  /* Configuración → «Registros eliminados»: lista de lo borrado y «Permitir que vuelva»
     (lo saca de la lista de bloqueo; el registro vuelve con el próximo envío de Clay/HubSpot). */
  function showDeleted() {
    drawerSave = null;
    $("prDrawerEyebrow").textContent = "Configuración";
    $("prDrawerTitle").textContent = "Registros eliminados";
    $("prDrawerSub").textContent = "Clay y la sincronización con HubSpot no los vuelven a crear mientras estén en esta lista.";
    $("prDrawerFoot").hidden = true;
    $("prDrawerBody").innerHTML = '<p class="pr-note">Cargando…</p>';
    openDrawer();
    api("/prospecting/deleted").then(function (r) {
      var rows = r.records || [];
      $("prDrawerBody").innerHTML = rows.length
        ? '<table class="pr-table"><thead><tr><th>Tipo</th><th>Nombre</th><th>Dominio / email</th><th>Eliminado</th><th></th></tr></thead><tbody>' +
          rows.map(function (x) {
            return "<tr><td>" + (x.object === "company" ? "Empresa" : "Contacto") + "</td><td><strong>" + esc(x.name || "#" + x.record_id) + "</strong></td>" +
              "<td>" + esc(x.domain || x.email || "—") + "</td>" +
              "<td>" + esc(String(x.deleted_at || "").slice(0, 10)) + '<div class="pr-note">' + esc(x.deleted_by || "") + "</div></td>" +
              '<td><button type="button" class="pr-btn" data-allow="' + x.id + '" title="Clay / HubSpot lo pueden volver a crear">Permitir que vuelva</button></td></tr>';
          }).join("") + "</tbody></table>"
        : '<p class="pr-note">No hay registros eliminados.</p>';
      $("prDrawerBody").querySelectorAll("[data-allow]").forEach(function (btn) {
        btn.onclick = function () {
          api("/prospecting/deleted/" + btn.getAttribute("data-allow"), { method: "DELETE" }).then(function () {
            btn.closest("tr").remove();
            toast("Listo: puede volver con el próximo envío de Clay o HubSpot.");
          }).catch(function (e) { alert(e.message); });
        };
      });
    }).catch(function (e) { $("prDrawerBody").innerHTML = '<p class="pr-note">' + esc(e.message) + "</p>"; });
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

  /* ---------- Editar en la celda (tablas de empresas y contactos) ----------
     Click en una celda editable → el control del tipo del campo (los mismos del panel del
     contacto y de la edición masiva: ProspectingContacts.fieldControl / readFieldValue).
     Enter o salir guarda, Esc cancela; listas / owner / Sí-No guardan al elegir. Casillas
     múltiples y textos largos van en un recuadro flotante con Guardar. `save(valor)` devuelve
     una Promise; si falla, la celda vuelve a como estaba. Sin cambios no se manda nada. */
  var inlineOpen = null;
  function inlineEdit(td, f, value, save) {
    if (inlineOpen) inlineOpen.cancel();
    var PC = window.ProspectingContacts;
    var big = f.type === "multi" || f.type === "longtext";
    var pick = ["enum", "owner", "user", "bool"].indexOf(f.type) !== -1;
    var original = td.innerHTML, box = null, tip = null, done = false;
    var html = PC.fieldControl(f, value);
    if (big) {
      box = document.createElement("div");
      box.className = "pr-cell-pop";
      box.innerHTML = '<div class="pr-cell-pop__label">' + esc(f.label) + "</div>" + html +
        '<div class="pr-cell-pop__foot"><span class="pr-cell-pop__hint"><kbd>Esc</kbd> para cancelar</span>' +
        '<button type="button" class="pr-btn" data-ce="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-ce="save">Guardar</button></div>';
      document.body.appendChild(box);
      var r = td.getBoundingClientRect();
      box.style.left = Math.max(12, Math.min(r.left, window.innerWidth - box.offsetWidth - 12)) + "px";
      box.style.top = Math.min(r.bottom + 4, window.innerHeight - box.offsetHeight - 12) + "px";
      td.classList.add("is-editing");
    } else {
      td.classList.add("is-editing");
      td.innerHTML = '<div class="pr-cell-editor">' + html + "</div>";
      // Cómo se guarda y cómo se cancela, debajo de la celda mientras se edita.
      tip = document.createElement("div");
      tip.className = "pr-cell-tip";
      tip.innerHTML = (pick ? "Elegí una opción para guardar" : "<kbd>Enter</kbd> o click afuera para guardar") +
        " · <kbd>Esc</kbd> para cancelar";
      document.body.appendChild(tip);
      var tr = td.getBoundingClientRect();
      tip.style.left = Math.max(12, Math.min(tr.left, window.innerWidth - tip.offsetWidth - 12)) + "px";
      tip.style.top = (tr.bottom + 4 + tip.offsetHeight > window.innerHeight ? tr.top - tip.offsetHeight - 4 : tr.bottom + 4) + "px";
    }
    var host = box || td;
    var el = host.querySelector("[data-k]");
    var initial = JSON.stringify(PC.readFieldValue(el));
    var finish = function () {
      done = true;
      inlineOpen = null;
      td.classList.remove("is-editing");
      if (box) box.remove();
      if (tip) tip.remove();
      document.removeEventListener("mousedown", outside, true);
    };
    var cancel = function () {
      if (done) return;
      finish();
      td.innerHTML = original;
    };
    var commit = function () {
      if (done) return;
      var v = PC.readFieldValue(el);
      if (JSON.stringify(v) === initial) return cancel();
      finish();
      td.innerHTML = original;
      td.classList.add("is-saving");
      Promise.resolve(save(v)).catch(function (err) {
        td.innerHTML = original;
        toast('<span class="pr-toast__warn"><i class="fa-solid fa-triangle-exclamation"></i> No se guardó «' + esc(f.label) + "»: " +
          esc(err.errors ? err.errors.join(" · ") : err.message) + "</span>");
      }).then(function () { td.classList.remove("is-saving"); });
    };
    // Click afuera: en la celda guarda (como salir de un input); el recuadro flotante cancela.
    var outside = function (e) {
      if (host.contains(e.target)) return;
      if (box) cancel(); else commit();
    };
    document.addEventListener("mousedown", outside, true);
    host.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); }
      else if (e.key === "Enter" && !big) { e.preventDefault(); commit(); }
    });
    if (pick) el.addEventListener("change", commit);
    else if (!big) el.addEventListener("blur", function () { setTimeout(commit, 0); });
    if (box) {
      box.addEventListener("click", function (e) {
        var chip = e.target.closest(".pr-wf-chip");
        if (chip) {
          chip.classList.toggle("is-on");
          chip.innerHTML = (chip.classList.contains("is-on") ? '<i class="fa-solid fa-check"></i> ' : "") + esc(chip.getAttribute("data-chip"));
          return;
        }
        var b = e.target.closest("[data-ce]");
        if (b) (b.getAttribute("data-ce") === "save" ? commit : cancel)();
      });
    }
    inlineOpen = { cancel: cancel };
    if (el.focus) el.focus();
    if (el.showPicker && pick && el.tagName === "SELECT") { try { el.showPicker(); } catch (e) {} }
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
      if (field === "prospecting_status") {
        sel.setAttribute("data-status", row.prospecting_status || "");
        // Pasar a / salir de Recycled destraba o traba el owner de esa fila.
        var oc = tr.querySelector(".pr-owner-cell");
        if (oc) oc.outerHTML = ownerCell(rowsById[id]);
      }
      announceWorkflows(row);
      askContact(row);
    }).catch(function (err) {
      sel.classList.add("is-error");
      alert("Could not save: " + errMsg(err));
    }).then(function () { sel.classList.remove("is-saving"); });
  }

  /* ---------- Pestaña Contacts ---------- */
  var ctState = { page: 1, total: 0 };
  var ctSelected = {}, ctSelAll = null, ctRows = [], ctLastKey = "";
  /* Vistas de contactos (la tira de arriba de la pestaña): `null` = «Todos los contactos».
     Las crea «Por segmento» o «Duplicar»; guardan columnas y, si es segmento, los ids. */
  var CT_VIEWS = [], ctView = null, CT_VIEW_KEY = "prospecting_ct_view";
  // Filtros avanzados de contactos (condiciones de workflow de CONTACTO), se guardan en la vista.
  var ctAdvanced = null;
  var CT_DEFAULT_COLS = ["name", "hub_company", "email", "position", "lead_life", "owner_email", "meeting_datetime"];
  var CT_SHORT = { name: "Name", hub_company: "Company", owner_email: "Owner", meeting_datetime: "Meeting" };
  function ctViewObj() { return CT_VIEWS.filter(function (v) { return v.id === ctView; })[0] || null; }
  function ctCatalog() {
    return [{ key: "name", label: "Name", group: "Contacto", fixed: true },
            { key: "hub_company", label: "Empresa (en el Hub)", group: "Contacto" }]
      .concat((((OPTS.objects || {}).contact || {}).fields || []).map(function (f) {
        return { key: f.key, label: f.label, group: f.group || "Otros", type: f.type, options: f.options };
      }));
  }
  /* Columnas que se ven ahora (`ctCols`): las de la vista, o en «Todos los contactos» las de
     este navegador (como las pestañas fijas de empresas). Arrastrarlas en el encabezado en una
     vista la deja con cambios sin guardar. */
  var ctCols = null, CT_COLS_KEY = "prospecting_ct_columns_v1";
  /* Orden de la tabla de contactos ("" = los más nuevos primero). En una vista se guarda con
     ella; en «Todos los contactos», en este navegador. */
  var ctSort = "", CT_SORT_KEY = "prospecting_ct_sort_v1";
  function setCtSort(s) {
    ctSort = s || "";
    if (!ctViewObj()) { try { localStorage.setItem(CT_SORT_KEY, ctSort); } catch (e) {} }
    ctState.page = 1;
    renderCtHead();
    loadContacts();
  }
  var ctCatMemo = null;
  function ctCatMap() {
    if (!ctCatMemo || ctCatMemo.opts !== OPTS) {
      ctCatMemo = { opts: OPTS, map: {} };
      ctCatalog().forEach(function (f) { ctCatMemo.map[f.key] = f; });
    }
    return ctCatMemo.map;
  }
  function normCtCols(keys) {
    var cat = ctCatMap();
    var cols = (keys && keys.length ? keys : CT_DEFAULT_COLS).filter(function (k, i, a) { return cat[k] && a.indexOf(k) === i; });
    return ["name"].concat(cols.filter(function (k) { return k !== "name"; }));
  }
  function localCtCols() {
    try {
      var saved = JSON.parse(localStorage.getItem(CT_COLS_KEY) || "null");
      if (Array.isArray(saved) && saved.length) return saved;
    } catch (e) {}
    return CT_DEFAULT_COLS;
  }
  function ctColumns() {
    var v = ctViewObj();
    return normCtCols(ctCols || (v && v.config && v.config.columns) || localCtCols());
  }
  function setCtCols(keys) {
    ctCols = normCtCols(keys);
    if (!ctViewObj()) { try { localStorage.setItem(CT_COLS_KEY, JSON.stringify(ctCols)); } catch (e) {} }
    renderCtHead();
    renderCtRows();
    renderCtViewBar();
  }
  function ctFieldOf(key) { return ctCatMap()[key] || { key: key, label: key }; }
  function ctCell(key, c) {
    var f = ctFieldOf(key), v = key === "company_name" ? c.contact_company_name : c[key];
    if (key === "name") {
      return '<button type="button" class="pr-company__name" data-ct-open="' + c.id + '">' + esc(c.name) + "</button>" +
        (c.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "");
    }
    if (key === "hub_company") return c.company_id
      ? '<a class="pr-link" href="prospecting-company.html?id=' + c.company_id + '">' + esc(c.hub_company || c.company_name) + "</a>"
      : '<span class="pr-note">Sin empresa</span>';
    if (key === "lead_life") return v ? '<span class="pr-wf-stat">' + esc(v) + "</span>" : "—";
    if (v == null || v === "" || (Array.isArray(v) && !v.length)) return "—";
    if (f.type === "owner" || f.type === "user") return cellText(ownerName(v) || v);
    if (f.type === "datetime") return esc(window.ProspectingContacts.fmtLocal(v));
    if (f.type === "date") return fmtDate(v);
    if (f.type === "bool") return v ? "Sí" : "No";
    if (Array.isArray(v)) return cellLong(v.join(", "));
    if (f.type === "url") return cellLink(v);
    if (f.type === "longtext") return cellLong(v);
    return cellText(v);
  }
  function renderCtHead() {
    $("prCtHead").innerHTML = '<th class="pr-selcol"><label class="pr-check pr-check--bare"><input type="checkbox" id="prCtSelAll" title="Seleccionar la página"></label></th>' +
      ctColumns().map(function (k) {
        var cur = parseSort(ctSort), on = !!cur && cur.key === k;
        var tip = on ? "Ordenado: " + sortLabel(ctFieldOf(k), cur.mode) : "Ordenar" + (k === "name" ? "" : " · arrastrar para mover");
        return "<th" + (k === "name" ? "" : ' draggable="true" data-col-drag="' + k + '"') + ' data-sort="' + k + '" title="' + esc(tip) + '"' +
          (on ? ' class="is-sorted"' : "") + ">" + esc(CT_SHORT[k] || ctFieldOf(k).label) + sortArrow(on, cur) + "</th>";
      }).join("");
  }
  function renderCtTabs() {
    var tab = function (id, label, v) {
      var active = id === ctView;
      return '<button type="button" class="pr-tab pr-tab--view' + (active ? " is-active" : "") + '" data-ctv="' + (id == null ? "" : id) + '"' +
        (id == null ? "" : ' draggable="true"') + ">" +
        '<i class="fa-solid ' + (v && v.config && v.config.segment_ids ? "fa-layer-group" : "fa-address-book") + ' pr-tab__icon"></i>' + esc(label) +
        (v && v.shared ? ' <i class="fa-solid fa-user-group pr-tab__shared" title="' + esc(v.mine ? "Shared with the team" : "Shared by " + (v.owner_name || v.owner_email)) + '"></i>' : "") +
        (active && v ? '<span class="pr-tab__more" data-ctv-menu="' + id + '" title="View options" role="button"><i class="fa-solid fa-ellipsis"></i></span>' : "") +
        "</button>";
    };
    // Igual que las pestañas de empresas: «Todos» + las primeras vistas hasta MAX_TABS; la
    // activa, si está más atrás, toma el último lugar; el resto va a «⋯ N more».
    var shown = ctShownViews();
    var hiddenN = CT_VIEWS.length - shown.length;
    $("prCtTabs").innerHTML = tab(null, "Todos los contactos", null) + shown.map(function (v) { return tab(v.id, v.name, v); }).join("") +
      (hiddenN > 0 ? '<button type="button" class="pr-tab pr-tab--overflow" id="prCtTabsMore" title="More views" aria-haspopup="menu">' +
        '<i class="fa-solid fa-ellipsis"></i> ' + hiddenN + " more</button>" : "") +
      '<button type="button" class="pr-tab pr-tab--add" id="prCtViewAdd" title="Create a view" aria-label="Create a view"><i class="fa-solid fa-plus"></i></button>';
  }
  function ctShownViews() {
    var shown = CT_VIEWS.slice(0, MAX_TABS - 1);
    var i = CT_VIEWS.findIndex(function (v) { return v.id === ctView; });
    if (i >= MAX_TABS - 1) shown[shown.length - 1] = CT_VIEWS[i];
    return shown;
  }
  function ctMoreMenu(anchor) {
    var shown = ctShownViews();
    openPop(anchor, '<div class="pr-pop__head">More views</div>' + CT_VIEWS.filter(function (v) { return shown.indexOf(v) === -1; }).map(function (v) {
      return '<button type="button" class="pr-pop__item" data-ctv-go="' + v.id + '"><i class="fa-solid ' +
        (v.config && v.config.segment_ids ? "fa-layer-group" : "fa-address-book") + '"></i> ' + esc(v.name) + "</button>";
    }).join("") + '<p class="pr-pop__note">Drag a tab to reorder. Opening one brings it to the bar.</p>');
  }
  /* Cambiar de vista de contactos, avisando si la actual tiene cambios sin guardar. */
  function switchCtView(id) {
    if (id === ctView) return;
    var cur = ctViewObj();
    if (cur && cur.mine && ctIsDirty() && !confirm("La vista «" + cur.name + "» tiene cambios sin guardar. ¿Descartarlos?")) return;
    applyCtView(id);
  }
  function applyCtView(id) {
    ctView = CT_VIEWS.some(function (v) { return v.id === id; }) ? id : null;
    ctCols = null;
    var vSort = ((ctViewObj() || {}).config || {}).sort;
    if (ctViewObj()) ctSort = vSort || "";
    else { try { ctSort = localStorage.getItem(CT_SORT_KEY) || ""; } catch (e) { ctSort = ""; } }
    try { localStorage.setItem(CT_VIEW_KEY, ctView == null ? "" : String(ctView)); } catch (e) {}
    var f = ((ctViewObj() || {}).config || {}).filters || {};
    $("prCtQ").value = f.q || "";
    $("prCtLead").value = f.lead_life || "";
    $("prCtOwner").value = f.owner || "";
    $("prCtCompany").value = f.company || "";
    var adv = ((ctViewObj() || {}).config || {}).advanced;
    ctAdvanced = hasAdvanced(adv) ? JSON.parse(JSON.stringify(adv)) : null;
    renderCtAdvSummary();
    ctState.page = 1;
    ctSelected = {};
    ctSelAll = null;
    renderSegNote($("prCtSegNote"), ((ctViewObj() || {}).config || {}).segment_ids || null, "contactos");
    renderCtTabs();
    renderCtHead();
    renderCtViewBar();
    if (!$("prContactsView").hidden) loadContacts();
  }
  function ctViewMenu(anchor, id) {
    var v = CT_VIEWS.filter(function (x) { return x.id === id; })[0];
    if (!v) return;
    var item = function (act, icon, label, danger) {
      return '<button type="button" class="pr-pop__item' + (danger ? " is-danger" : "") + '" data-ctvact="' + act + '" data-id="' + id + '">' +
        '<i class="fa-solid ' + icon + '"></i> ' + esc(label) + "</button>";
    };
    openPop(anchor, '<div class="pr-pop__head">' + esc(v.name) + "</div>" + (v.mine
      ? item("columns", "fa-table-columns", "Edit columns") + item("rename", "fa-pen", "Rename") + item("duplicate", "fa-copy", "Duplicate") +
        item("share", v.shared ? "fa-lock" : "fa-user-group", v.shared ? "Make private" : "Share with the team") +
        item("delete", "fa-trash", "Delete view", true)
      : '<p class="pr-pop__note">Shared by ' + esc(v.owner_name || v.owner_email) + ". Only they can edit it; duplicate it to have your own.</p>" +
        item("duplicate", "fa-copy", "Duplicate")));
  }
  function onCtViewAction(act, id) {
    var v = CT_VIEWS.filter(function (x) { return x.id === id; })[0];
    if (!v) return;
    if (act === "duplicate") {
      var name = prompt("Name for the new view:", v.name + " (copy)");
      if (!name || !name.trim()) return;
      api("/prospecting/views", { method: "POST", body: JSON.stringify({ name: name.trim(), object: "contact", config: v.config, shared: false }) })
        .then(function (nv) { CT_VIEWS.push(nv); applyCtView(nv.id); }).catch(viewError);
      return;
    }
    if (!v.mine) return;
    if (act === "columns") {
      columnsModal({
        title: "Columnas de «" + esc(v.name) + "»", fields: ctCatalog(), tableCols: ctColumns(),
        goIcon: "fa-check", goLabel: "Guardar", busyLabel: "Guardando…",
        onGo: function (cols) {
          return patchView(v, { config: Object.assign({}, v.config, { columns: cols }) }).then(function () { applyCtView(v.id); });
        },
      });
    } else if (act === "rename") {
      var nn = prompt("New name:", v.name);
      if (nn && nn.trim() && nn.trim() !== v.name) patchView(v, { name: nn.trim() }).then(renderCtTabs).catch(viewError);
    } else if (act === "share") {
      patchView(v, { shared: !v.shared }).then(renderCtTabs).catch(viewError);
    } else if (act === "delete") {
      if (!confirm("Delete the view «" + v.name + "»?" + (v.shared ? " Teammates will lose it too." : "") + " This cannot be undone.")) return;
      api("/prospecting/views/" + v.id, { method: "DELETE" }).then(function () {
        CT_VIEWS = CT_VIEWS.filter(function (x) { return x.id !== v.id; });
        applyCtView(null);
      }).catch(viewError);
    }
  }
  /* Filtros de la pestaña (búsqueda, Lead Life, Owner): se guardan en la vista de contactos
     igual que en las de empresas — barra «Cambios sin guardar» con Guardar / Descartar. */
  function ctFilterInputs() {
    var f = { q: $("prCtQ").value.trim(), lead_life: $("prCtLead").value, owner: $("prCtOwner").value,
      company: $("prCtCompany").value };
    Object.keys(f).forEach(function (k) { if (!f[k]) delete f[k]; });
    return f;
  }
  function ctSavedFilters(v) {
    var f = Object.assign({}, ((v || {}).config || {}).filters || {});
    delete f.dummy;  // lo fija el segmento, no se edita desde la pestaña
    return f;
  }
  function ctIsDirty() {
    var v = ctViewObj();
    var savedAdv = ((v || {}).config || {}).advanced;
    return canon(ctFilterInputs()) !== canon(ctSavedFilters(v)) ||
      canon(hasAdvanced(ctAdvanced) ? ctAdvanced : null) !== canon(hasAdvanced(savedAdv) ? savedAdv : null) ||
      (!!v && canon(ctColumns()) !== canon(normCtCols(v.config && v.config.columns))) ||
      (!!v && ctSort !== ((v.config && v.config.sort) || ""));
  }
  function renderCtViewBar() {
    var bar = $("prCtViewBar");
    if (!ctIsDirty()) { bar.hidden = true; bar.innerHTML = ""; return; }
    var v = ctViewObj();
    bar.hidden = false;
    bar.innerHTML = v && v.mine
      ? '<span><i class="fa-solid fa-pen"></i> Unsaved changes to <strong>' + esc(v.name) + "</strong></span>" +
        '<button type="button" class="pr-btn pr-btn--primary" data-ctvb="save"><i class="fa-solid fa-floppy-disk"></i> Save view</button>' +
        '<button type="button" class="pr-btn" data-ctvb="saveas">Save as new view</button>' +
        '<button type="button" class="pr-btn" data-ctvb="reset">Discard</button>'
      : '<span><i class="fa-solid fa-filter"></i> You changed <strong>' + esc(v ? v.name : "Todos los contactos") + "</strong>" +
        (v ? " (shared by " + esc(v.owner_name || v.owner_email) + ")" : "") + "</span>" +
        '<button type="button" class="pr-btn pr-btn--primary" data-ctvb="saveas"><i class="fa-solid fa-plus"></i> Save as new view</button>' +
        '<button type="button" class="pr-btn" data-ctvb="reset">Reset</button>';
  }
  function onCtViewBar(act) {
    var v = ctViewObj();
    var filters = Object.assign(ctFilterInputs(), (((v || {}).config || {}).filters || {}).dummy ? { dummy: v.config.filters.dummy } : {});
    if (act === "reset") { applyCtView(ctView); return; }
    if (act === "save" && v && v.mine) {
      patchView(v, { config: Object.assign({}, v.config, { filters: filters, advanced: hasAdvanced(ctAdvanced) ? ctAdvanced : null,
        columns: ctColumns(), sort: ctSort || null }) }).then(function () {
        ctCols = null;
        renderCtViewBar();
        toast('<i class="fa-solid fa-floppy-disk"></i> Saved <strong>' + esc(v.name) + "</strong>.");
      }).catch(viewError);
      return;
    }
    if (act === "saveas") {
      var name = prompt("Name for the new view:", v ? v.name + " (copy)" : "");
      if (!name || !name.trim()) return;
      var config = { filters: filters, advanced: hasAdvanced(ctAdvanced) ? ctAdvanced : null, columns: ctColumns(), page_size: 25, sort: ctSort || null };
      if (v && v.config && Array.isArray(v.config.segment_ids)) config.segment_ids = v.config.segment_ids;
      api("/prospecting/views", { method: "POST", body: JSON.stringify({ name: name.trim(), object: "contact", config: config, shared: false }) })
        .then(function (nv) {
          CT_VIEWS.push(nv);
          applyCtView(nv.id);
          toast('<i class="fa-solid fa-table-list"></i> View <strong>' + esc(nv.name) + "</strong> created. Only you can see it.");
        }).catch(viewError);
    }
  }
  function ctFilters() {
    var v = ctViewObj();
    var vf = ((v || {}).config || {}).filters || {};
    var f = {
      q: $("prCtQ").value.trim(), lead_life: $("prCtLead").value, owner: $("prCtOwner").value,
      company: $("prCtCompany").value,
      // Un segmento con dummies se guarda con dummy=include (si no, se vería vacío).
      dummy: vf.dummy || (ME.sees_dummies ? $("prFDummy").value : "exclude"),
    };
    if (v && v.config && Array.isArray(v.config.segment_ids)) f.segment = v.id;
    if (hasAdvanced(ctAdvanced)) f.advanced = JSON.stringify(ctAdvanced);
    return f;
  }

  /* ---------- Contactos: filtros avanzados, columnas y «+» (2026-11-06) ----------
     Lo mismo que en Empresas: el armador de condiciones de Workflows (objeto contacto), el
     modal de columnas y el popover para crear una vista. Todo se guarda con la vista. */
  function renderCtAdvSummary() {
    var n = ruleCount(ctAdvanced);
    $("prCtAdvCount").textContent = n ? "(" + n + ")" : "";
    $("prCtAdvBtn").classList.toggle("is-on", n > 0);
    var box = $("prCtAdvSummary");
    if (!n || !window.ProspectingWorkflows) { box.hidden = true; box.innerHTML = ""; return; }
    box.hidden = false;
    box.innerHTML = '<span class="pr-adv-summary__label"><i class="fa-solid fa-sliders"></i> Advanced</span>' +
      '<span class="pr-adv-summary__text">' + window.ProspectingWorkflows.conditionsSummary(ctAdvanced, "contact") + "</span>" +
      '<button type="button" class="pr-btn" data-ctadv="edit">Edit</button>' +
      '<button type="button" class="pr-btn" data-ctadv="clear" title="Remove advanced filters"><i class="fa-solid fa-xmark"></i></button>';
  }
  function openCtAdvanced() {
    if (!window.ProspectingWorkflows) return;
    drawerSave = null;
    $("prDrawerEyebrow").textContent = "Filters";
    $("prDrawerTitle").textContent = "Advanced filters · Contacts";
    $("prDrawerSub").textContent = "Groups are joined by OR; conditions inside a group, by AND. Same properties as the contact workflows.";
    $("prDrawerBody").innerHTML = '<div class="pr-adv-panel" id="prCtAdvPanel"></div>' +
      '<div class="pr-row" style="margin-top:12px"><button type="button" class="pr-btn" id="prCtAdvClearAll"><i class="fa-solid fa-trash"></i> Clear all</button></div>';
    $("prDrawerStatus").textContent = "";
    $("prDrawerFoot").hidden = false;
    $("prDrawerSave").textContent = "Apply";
    openDrawer();
    var panel = window.ProspectingWorkflows.conditionsPanel($("prCtAdvPanel"), ctAdvanced, function () {
      $("prDrawerStatus").textContent = "";
    }, "contact");
    $("prCtAdvClearAll").onclick = function () { panel.clear(); };
    drawerSave = function () {
      var conds = panel.get();
      conds = hasAdvanced(conds) ? conds : null;
      // Se prueba antes de cerrar: una condición incompleta deja el error a la vista.
      var probe = Object.assign(ctFilters(), { page: 1, page_size: 5 });
      delete probe.advanced;
      if (conds) probe.advanced = JSON.stringify(conds);
      $("prDrawerStatus").textContent = "Checking…";
      api("/prospecting/contacts?" + qs(probe)).then(function () {
        ctAdvanced = conds ? JSON.parse(JSON.stringify(conds)) : null;
        ctState.page = 1;
        closeDrawer();
        renderCtAdvSummary();
        loadContacts();
      }).catch(function (err) {
        $("prDrawerStatus").innerHTML = esc(err.errors ? err.errors.join(" · ") : err.message);
      });
    };
  }
  /* Columns: en «Todos los contactos» quedan en este navegador; en una vista, como cambio sin
     guardar (barra Save view / Save as new view), igual que en Empresas. */
  function openCtColumns() {
    var v = ctViewObj();
    columnsModal({
      title: "Columnas" + (v ? " de «" + esc(v.name) + "»" : ""), fields: ctCatalog(), tableCols: ctColumns(),
      goIcon: "fa-check", goLabel: "Aplicar", busyLabel: "Aplicando…",
      onGo: function (cols) { setCtCols(cols); return Promise.resolve(); },
    });
  }
  function ctAddMenu(anchor) {
    openPop(anchor,
      '<div class="pr-pop__head">Create new view</div>' +
      '<form class="pr-pop__form" id="prCtViewCreate">' +
        '<input class="pr-filter__input" id="prCtViewName" maxlength="60" placeholder="View name" autocomplete="off" required>' +
        '<label class="pr-check"><input type="radio" name="prCtViewFrom" value="current" checked> Start from the current view (filters, advanced filters, columns, sort)</label>' +
        '<label class="pr-check"><input type="radio" name="prCtViewFrom" value="blank"> Start blank</label>' +
        '<label class="pr-check"><input type="checkbox" id="prCtViewShared"> Share with the team</label>' +
        '<button type="submit" class="pr-btn pr-btn--primary"><i class="fa-solid fa-plus"></i> Create view</button>' +
      "</form>");
    setTimeout(function () { var n = $("prCtViewName"); if (n) n.focus(); }, 0);
  }
  function createCtView(name, fromCurrent, shared) {
    var v = ctViewObj();
    var config = fromCurrent
      ? { filters: Object.assign(ctFilterInputs(), (((v || {}).config || {}).filters || {}).dummy ? { dummy: v.config.filters.dummy } : {}),
          advanced: hasAdvanced(ctAdvanced) ? ctAdvanced : null, columns: ctColumns(), page_size: 25, sort: ctSort || null }
      : { filters: {}, advanced: null, columns: CT_DEFAULT_COLS.slice(), page_size: 25, sort: null };
    return api("/prospecting/views", { method: "POST", body: JSON.stringify({ name: name, object: "contact", config: config, shared: !!shared }) })
      .then(function (nv) {
        CT_VIEWS.push(nv);
        applyCtView(nv.id);
        toast('<i class="fa-solid fa-table-list"></i> View <strong>' + esc(nv.name) + "</strong> created" + (shared ? " and shared with the team." : ". Only you can see it."));
      });
  }

  function renderCtBulk() {
    var bar = $("prCtBulk");
    var ids = Object.keys(ctSelected);
    syncHeadCheck($("prCtSelAll"), ctRows, ctSelected);
    if (!ids.length && !ctSelAll) { bar.hidden = true; return; }
    var pageAll = ctRows.length > 0 && ctRows.every(function (c) { return ctSelected[c.id]; });
    bar.hidden = false;
    bar.innerHTML = selectionHead(ids.length, !!ctSelAll, pageAll, ctState.total, "contacto", "contact")
      .replace(/seleccionada/g, "seleccionado").replace(/Todas las/, "Todos los").replace(/Seleccionar las/, "Seleccionar los") +
      '<button type="button" class="pr-btn" data-ct-clear="1">Deseleccionar</button>';
  }
  function renderCtRows() {
    var cols = ctColumns(), span = cols.length + 1;
    $("prCtBody").innerHTML = ctRows.length ? ctRows.map(function (c) {
      return '<tr data-ct="' + c.id + '" data-co="' + (c.company_id || "") + '"' + (ctSelected[c.id] ? ' class="is-selected"' : "") + ">" +
        '<td class="pr-selcol"><label class="pr-check pr-check--bare"><input type="checkbox" data-ct-sel="' + c.id + '"' + (ctSelected[c.id] ? " checked" : "") + "></label></td>" +
        cols.map(function (k) {
          var editable = k !== "name" && k !== "hub_company";
          return "<td" + (editable ? ' class="pr-cell-edit" data-ct-edit="' + k + '" title="Click para editar"' : "") + ">" + ctCell(k, c) + "</td>";
        }).join("") + "</tr>";
    }).join("") : '<tr><td class="pr-empty" colspan="' + span + '">No contacts match these filters.</td></tr>';
    renderCtBulk();
  }
  function loadContacts() {
    var q = Object.assign(ctFilters(), { page: ctState.page, page_size: 25, sort: ctSort });
    renderCtViewBar();
    var key = qs(q);
    if (key !== ctLastKey) { ctSelected = {}; ctSelAll = null; ctLastKey = key; }
    var cols = ctColumns(), span = cols.length + 1;
    $("prCtBody").innerHTML = '<tr><td class="pr-empty" colspan="' + span + '">Loading…</td></tr>';
    api("/prospecting/contacts?" + qs(q)).then(function (r) {
      ctState.total = r.total;
      ctRows = r.rows;
      renderCtRows();
      var pages = Math.max(1, Math.ceil(r.total / 25));
      $("prCtCount").textContent = r.total.toLocaleString() + " contact" + (r.total === 1 ? "" : "s");
      $("prCtPage").textContent = ctState.page + " / " + pages;
      $("prCtPrev").disabled = ctState.page <= 1;
      $("prCtNext").disabled = ctState.page >= pages;
    }).catch(function (err) {
      $("prCtBody").innerHTML = '<tr><td class="pr-empty" colspan="' + span + '">' + esc(err.message) + "</td></tr>";
    });
  }
  /* Opciones de Lead Life / Owner: se llenan cuando llegan las opciones (refreshOptions).
     Antes se llenaban en bindContacts(), que corre ANTES de cargarlas: quedaban sólo en «All». */
  function fillContactFilters() {
    var keep = { lead: $("prCtLead").value, owner: $("prCtOwner").value };
    var LEAD = (((OPTS.objects || {}).contact || {}).fields || []).filter(function (f) { return f.key === "lead_life"; })[0];
    $("prCtLead").innerHTML = optionsHtml((LEAD && LEAD.options) || [], "", "All");
    $("prCtOwner").innerHTML = optionsHtml([{ value: "__none__", label: "No owner" }].concat(ownerOptions()), "", "All");
    $("prCtLead").value = keep.lead;
    $("prCtOwner").value = keep.owner;
  }
  function bindContacts() {
    ["prCtLead", "prCtOwner", "prCtCompany"].forEach(function (id) { $(id).addEventListener("change", function () { ctState.page = 1; loadContacts(); }); });
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
    $("prCtViewBar").addEventListener("click", function (e) {
      var b = e.target.closest("[data-ctvb]");
      if (b) onCtViewBar(b.getAttribute("data-ctvb"));
    });
    // Reordenar la tira de vistas de contactos arrastrando («Todos los contactos» queda primera).
    var dragCtv = null;
    $("prCtTabs").addEventListener("dragstart", function (e) {
      var t = e.target.closest("[data-ctv]");
      if (!t || !t.getAttribute("data-ctv")) return;
      dragCtv = Number(t.getAttribute("data-ctv"));
      e.dataTransfer.effectAllowed = "move";
      try { e.dataTransfer.setData("text/plain", String(dragCtv)); } catch (err) {}
    });
    $("prCtTabs").addEventListener("dragover", function (e) {
      var t = dragCtv && e.target.closest("[data-ctv]");
      if (t && t.getAttribute("data-ctv")) e.preventDefault();
    });
    $("prCtTabs").addEventListener("drop", function (e) {
      var t = dragCtv && e.target.closest("[data-ctv]");
      if (!t || !t.getAttribute("data-ctv")) return;
      e.preventDefault();
      var target = Number(t.getAttribute("data-ctv")), moving = dragCtv;
      dragCtv = null;
      if (target === moving) return;
      var ids = CT_VIEWS.map(function (v) { return v.id; });
      var from = ids.indexOf(moving), to = ids.indexOf(target);
      ids.splice(from, 1);
      ids.splice(ids.indexOf(target) + (from < to ? 1 : 0), 0, moving);
      CT_VIEWS.sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
      renderCtTabs();
      api("/prospecting/views/tabs", { method: "PUT", body: JSON.stringify({ object: "contact", tabs: ids }) })
        .catch(function (err) { alert("Could not save the order: " + err.message); });
    });
    $("prCtTabs").addEventListener("dragend", function () { dragCtv = null; });
    bindHeaderDrag($("prCtHead"), ctColumns, setCtCols);
    $("prCtHead").addEventListener("click", function (e) {
      var th = e.target.closest("th[data-sort]");
      if (!th || e.target.closest(".pr-check")) return;
      e.stopPropagation();
      sortMenu(th, "contact", ctFieldOf(th.getAttribute("data-sort")), ctSort);
    });
    $("prCtTabs").addEventListener("click", function (e) {
      if (e.target.closest("#prCtTabsMore")) { e.stopPropagation(); ctMoreMenu($("prCtTabsMore")); return; }
      if (e.target.closest("#prCtViewAdd")) { e.stopPropagation(); ctAddMenu($("prCtViewAdd")); return; }
      var more = e.target.closest("[data-ctv-menu]");
      if (more) { e.stopPropagation(); ctViewMenu(more, Number(more.getAttribute("data-ctv-menu"))); return; }
      var t = e.target.closest("[data-ctv]");
      if (!t) return;
      switchCtView(t.getAttribute("data-ctv") ? Number(t.getAttribute("data-ctv")) : null);
    });
    // El encabezado se redibuja con las columnas de la vista: el tilde se escucha delegado.
    $("prCtHead").addEventListener("change", function (e) {
      if (e.target.id !== "prCtSelAll") return;
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
      if (b.hasAttribute("data-bulk-actions")) { e.stopPropagation(); bulkActionsMenu(b, "contact"); }
      if (b.hasAttribute("data-bulk-all")) { ctSelAll = { filters: ctFilters(), total: ctState.total }; renderCtBulk(); }
      if (b.hasAttribute("data-ct-clear")) {
        ctSelected = {}; ctSelAll = null;
        document.querySelectorAll("#prCtBody [data-ct-sel]").forEach(function (cb) { cb.checked = false; cb.closest("tr").classList.remove("is-selected"); });
        renderCtBulk();
      }
    });
    $("prCtBody").addEventListener("click", function (e) {
      var ce = e.target.closest("td[data-ct-edit]");
      if (ce && !ce.classList.contains("is-editing") && !e.target.closest("a")) {
        var tr0 = ce.closest("tr"), id = Number(tr0.getAttribute("data-ct")), key = ce.getAttribute("data-ct-edit");
        var row = ctRows.filter(function (x) { return x.id === id; })[0];
        if (!row) return;
        var f = ctFieldOf(key);
        inlineEdit(ce, f, key === "company_name" ? row.contact_company_name : row[key], function (v) {
          var patch = {};
          patch[key] = v;
          return api("/prospecting/contacts/" + id, { method: "PATCH", body: JSON.stringify(patch) }).then(function (resp) {
            // En la respuesta `company_name` es la empresa del Hub; la propiedad del contacto va aparte.
            var keepProp = row.contact_company_name;
            Object.assign(row, resp);
            row.hub_company = resp.company_name;
            row.contact_company_name = key === "company_name" ? v : keepProp;
            renderCtRows();
            var applied = resp.workflows_applied || [];
            if (applied.length) {
              toast('<i class="fa-solid fa-diagram-project"></i> El workflow ' + applied.map(function (a) { return "<strong>" + esc(a.name) + "</strong>"; }).join(", ") + " actualizó este contacto.");
              loadContacts();
            }
          });
        });
        return;
      }
      var b = e.target.closest("[data-ct-open]");
      if (!b) return;
      var tr = b.closest("tr");
      window.ProspectingContacts.open({ contactId: Number(b.getAttribute("data-ct-open")),
        companyId: Number(tr.getAttribute("data-co")) || null,
        onSaved: function () { loadContacts(); } });
    });
    // Empresa a mano (2026-11-06): al crearla (o elegir la que ya existía) se abre su vista rápida.
    $("prCoNew").addEventListener("click", function () {
      window.ProspectingContacts.newCompanyModal({}, function (co) {
        load();
        showCompany(co.id);
      });
    });
    // Contacto desde cero, con o sin empresa (como en HubSpot, 2026-11-04).
    $("prCtNew").addEventListener("click", function () {
      window.ProspectingContacts.open({ onSaved: function () { loadContacts(); } });
    });
  }

  /* La bandeja «Unassigned contacts» (contactos sin empresa de Calendly / HubSpot) se
     sacó el 2026-11-04: desde ese día un contacto puede no tener empresa y está en la
     tabla como cualquier otro (filtro Company: Sin empresa). Lo que quedaba pendiente lo
     pasa a contactos backend/scripts/migrate_inbound_to_contacts.py. */

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

  /* `hist` = [id, campo]: suma el reloj «ver historial» (prospecting-history.js). */
  function kv(label, value, isLink, hist) {
    var v = value == null || value === "" ? "—"
      : isLink ? '<a href="' + esc(value) + '" target="_blank" rel="noopener">' + esc(value) + "</a>"
      : esc(value);
    return "<dt>" + esc(label) + (hist ? histBtn(hist[0], hist[1]) : "") + "</dt><dd>" + v + "</dd>";
  }
  function histBtn(id, field) { return window.ProspectingHistory ? window.ProspectingHistory.button("company", id, field) : ""; }

  var FIELD_LABELS = {
    prospecting_status: "Prospecting Status",
    prospecting_owner_email: "Prospecting Owner",
    prospecting_start_date: "Prospecting Start Date",
    not_icp_reason: "Not ICP Reason",
    week_label: "Week",
    lead_source: "Lead Source",
  };

  function bulkTag(src) {
    var m = /^bulk:(\d+)$/.exec(String(src || ""));
    return m ? ' <span class="pr-bulk-tag" title="Cambio hecho con Editar en masa"><i class="fa-solid fa-layer-group"></i> Edición masiva · ' + m[1] + "</span>" : "";
  }

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
        '<span class="pr-events__src' + (isWf ? " pr-events__src--wf" : "") + '">' + esc(who) + "</span>" + bulkTag(ev.source) + " · " + subject + what + "</li>";
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
        return '<label class="pr-filter"><span class="pr-filter__label">' + esc(label) + histBtn(c.id, field) + "</span>" + inner + "</label>";
      };
      var H = function (field) { return [c.id, field]; };
      $("prDrawerBody").innerHTML =
        '<section class="pr-section"><h3 class="pr-section__title">Business Dev</h3><div class="pr-grid">' +
          f("prospecting_status", "Prospecting Status",
            '<select class="pr-filter__input" data-edit="prospecting_status">' + optionsHtml(withCurrent(OPTS.statuses, c.prospecting_status), c.prospecting_status || "", "—") + "</select>") +
          f("not_icp_reason", "Not ICP Reason",
            '<select class="pr-filter__input" data-edit="not_icp_reason">' + optionsHtml(withCurrent(OPTS.not_icp_reasons, c.not_icp_reason), c.not_icp_reason || "", "—") + "</select>") +
          f("prospecting_owner_email", "Prospecting Owner", canChangeOwner(c)
            ? '<select class="pr-filter__input" data-edit="prospecting_owner_email">' + optionsHtml(withCurrent(ownerOptions(), c.prospecting_owner_email), c.prospecting_owner_email || "", "—") + "</select>"
            : '<div class="pr-filter__input pr-owner-locked" title="' + esc(OWNER_LOCK_TIP) + '"><i class="fa-solid fa-lock"></i> ' + esc(c.prospecting_owner_email ? ownerName(c.prospecting_owner_email) : "—") + "</div>") +
          f("prospecting_start_date", "Prospecting Start Date",
            '<input type="date" class="pr-filter__input" data-edit="prospecting_start_date" value="' + esc((c.prospecting_start_date || "").slice(0, 10)) + '">') +
          f("week_label", "Week",
            '<input class="pr-filter__input" data-edit="week_label" placeholder="Semana 40" value="' + esc(c.week_label || "") + '">') +
        "</div></section>" +
        '<section class="pr-section"><h3 class="pr-section__title">From Clay</h3><dl class="pr-kv">' +
          kv("Website", c.website, true, H("website")) +
          kv("LinkedIn", c.linkedin_url, true, H("linkedin_url")) +
          kv("Lead Source", c.lead_source, false, H("lead_source")) +
          kv("Industry", c.industry, false, H("industry")) +
          kv("Size", c.size, false, H("size")) +
          kv("Founded Year", c.founded_year, false, H("founded_year")) +
          kv("Open jobs", c.open_jobs, false, H("open_jobs")) +
          kv("Tier", c.tier, false, H("tier")) +
          kv("Remote?", c.remote_jobs, false, H("remote_jobs")) +
          kv("Job types", c.job_types, false, H("job_types")) +
          kv("Technologies", c.technologies, false, H("technologies")) +
          kv("Keywords", c.keywords, false, H("keywords")) +
          kv("Location", [c.city, c.state, c.country].filter(Boolean).join(", ")) +
          kv("Description", c.description, false, H("description")) +
          kv("Id de la empresa (HubSpot)", c.hubspot_company_id, false, H("hubspot_company_id")) +
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
        }).catch(function (err) { $("prDrawerStatus").textContent = "Error: " + errMsg(err); });
      };
    }).catch(function (err) {
      $("prDrawerTitle").textContent = "Error";
      $("prDrawerBody").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>";
    });
  }

  /* ---------- Sección Configuración (owner + editoras de workflows) ---------- */
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
    $("prDrawerSub").textContent = "Solo lo ven mia, manuela, bahia y pgonzales. Los BDRs no ven las empresas dummy.";
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
  // Una sola vista fija para todos, «Companies» (2026-11-06): siempre primera, no se oculta
  // ni se arrastra. My companies / Unassigned / Recycled se arman con + (vistas propias).
  // Desde el 2026-11-09 también «Recycled» (status Recycled), fija para todos los que entran
  // a Business Dev, segunda. Una fija nueva = una entrada acá, en SYS_OVERRIDES y en
  // SYSTEM_TABS de backend/prospecting/views.py.
  // «This Week» (2026-11-09): las empresas de quien mira en la semana actual; el server
  // traduce "__current__" a «Semana N» (store.current_week_label()).
  var SYS_TABS = { "sys:all": "Companies", "sys:recycled": "Recycled", "sys:week": "This Week" };
  var SYS_OVERRIDES = {
    "sys:recycled": { status: "Recycled" },
    "sys:week": { owner: "__me__", week: "__current__" },
  };
  var ACTIVE_KEY = "prospecting_active_tab";
  var VIEWS = { views: [], tabs: Object.keys(SYS_TABS) };
  var baseline = "";      // la vista tal como está guardada, para saber si hay cambios
  var advPanel = null;

  function isSys(key) { return String(key || "").indexOf("sys:") === 0; }
  /* Ids de una vista segmento (Acciones → «Por segmento»), o null. */
  function segmentOf(key) {
    var v = isSys(key) ? null : viewOf(key);
    return v && v.config && Array.isArray(v.config.segment_ids) ? v.config.segment_ids : null;
  }
  function renderSegNote(el, ids, noun) {
    if (!el) return;
    el.hidden = !ids;
    var fem = noun === "empresas", one = ids && ids.length === 1;
    var what = one ? (fem ? "la empresa que se eligió" : "el contacto que se eligió")
      : (fem ? "las " : "los ") + (ids ? ids.length.toLocaleString() : "") + " " + noun + " que se eligieron";
    el.innerHTML = ids ? '<i class="fa-solid fa-layer-group"></i> <span><strong>Segmento fijo</strong> · muestra sólo ' + what + " al crear la vista. Los filtros de arriba se aplican dentro de ese grupo.</span>" : "";
  }
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
    // «Dummy data» es un interruptor de prueba de quien mira, no un filtro de la vista: se
    // mantiene al cambiar de pestaña (antes volvía a «Hide» y una pestaña como Recycled
    // parecía no tener las dummies que se acababan de pasar ahí). Sólo lo pisa una vista que
    // lo guardó.
    if (ME.sees_dummies && f.dummy) $("prFDummy").value = f.dummy;
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
      segment_ids: segmentOf(state.view),  // guardar o duplicar no le saca el segmento
    };
  }
  /* Lo que se guarda: en una fija, su atajo pasa a ser un filtro de verdad. */
  function configToSave() {
    var snap = snapshot();
    // «Dummy data» no cuenta como cambio de la vista, pero si está prendido se guarda con ella.
    if (ME.sees_dummies && $("prFDummy").value !== "exclude") snap.filters.dummy = $("prFDummy").value;
    Object.assign(snap.filters, SYS_OVERRIDES[state.view] || {});
    snap.columns = visibleCols.slice();
    snap.page_size = state.pageSize;
    return snap;
  }
  function isDirty() { return canon(snapshot()) !== baseline; }

  function loadViews() {
    return api("/prospecting/views").then(function (r) {
      var all = r.views || [];
      VIEWS = { views: all.filter(function (v) { return (v.object || "company") === "company"; }), tabs: r.tabs || Object.keys(SYS_TABS) };
      // Orden de la tira de contactos: el que guardó la persona; las que no están, al final.
      var order = r.contact_tabs || [];
      var rank = function (v) { var i = order.indexOf(v.id); return i === -1 ? 1e6 + v.id : i; };
      CT_VIEWS = all.filter(function (v) { return v.object === "contact"; }).sort(function (a, b) { return rank(a) - rank(b); });
    }).catch(function () { /* sin vistas igual anda la tabla con las fijas */ });
  }

  /* Secciones del menú de arriba. Cada una muestra sólo sus vistas al lado del menú:
     Empresas las de empresas, Contactos las de contactos; Workflows y Negocios, ninguna
     (Negocios tiene su propia barra: pipeline, filtros y tablero / tabla, en prospecting-deals.js). */
  var SECTIONS = [
    { key: "table", label: "Empresas", icon: "fa-solid fa-building", tone: "violet" },
    { key: "contacts", label: "Contactos", icon: "fa-solid fa-user", tone: "cyan" },
    // Negocios y Workflows no son para los BDRs (2026-11-09): /prospecting/me los da; el server frena igual.
    { key: "deals", label: "Negocios", icon: "fa-solid fa-handshake", tone: "mag", requires: "can_see_deals" },
    { key: "workflows", label: "Workflows", icon: "fa-solid fa-diagram-project", tone: "blue", requires: "can_see_workflows" },
    { key: "panels", label: "Paneles", icon: "fa-solid fa-chart-column", tone: "cyan" },
    // Sólo owner + editoras de workflows (ME.can_configure): el server frena igual.
    { key: "settings", label: "Configuración", icon: "fa-solid fa-gear", tone: "violet", restricted: true }
  ];
  function visibleSections() {
    return SECTIONS.filter(function (x) {
      return (!x.restricted || ME.can_configure) && (!x.requires || ME[x.requires]);
    });
  }
  var SECTION_KEY = "prospecting_section_v1";
  var section = "table";
  function sectionOf(key) { return visibleSections().filter(function (x) { return x.key === key; })[0] || SECTIONS[0]; }

  function showSection(kind) {
    section = sectionOf(kind).key;
    try { localStorage.setItem(SECTION_KEY, section); } catch (e) {}
    $("prTableCard").hidden = section !== "table";
    $("prWorkflows").hidden = section !== "workflows";
    $("prContactsView").hidden = section !== "contacts";
    $("prDealsView").hidden = section !== "deals";
    $("prSettingsView").hidden = section !== "settings";
    $("prPanelsView").hidden = section !== "panels";
    $("prCoStrip").hidden = section !== "table";
    $("prCtTabs").hidden = section !== "contacts";
    $("prTabs").hidden = section !== "table" && section !== "contacts";
    var x = sectionOf(section);
    $("prSectionBtn").innerHTML = esc(x.label) + '<span class="pr-secbtn__caret"><i class="fa-solid fa-chevron-down"></i></span>';
  }
  function sectionMenu(anchor) {
    $("prViewPop").classList.add("pr-pop--sections");  // antes de medir: es más ancho
    openPop(anchor, '<div class="pr-pop__head">Ir a</div>' + visibleSections().map(function (x) {
      return '<button type="button" class="pr-secitem' + (x.key === section ? " is-on" : "") + '" data-section-go="' + x.key + '">' +
        '<span class="pr-secitem__icon pr-tone--' + x.tone + '"><i class="' + x.icon + '"></i></span>' +
        '<span class="pr-secitem__text"><strong>' + esc(x.label) +
        (x.soon ? ' <span class="pr-soon-chip">Próximamente</span>' : "") + "</strong></span>" +
        (x.key === section ? '<i class="fa-solid fa-check pr-secitem__check"></i>' : "") + "</button>";
    }).join(""));
  }
  /* Cambiar de sección no descarta nada: cada sección guarda su vista, sus filtros y sus
     cambios sin guardar, y al volver están igual. */
  function goSection(kind) {
    if (kind === section) return;
    showSection(kind);
    if (kind === "table") { renderTabs(); load(); }
    else if (kind === "workflows") { if (window.ProspectingWorkflows) window.ProspectingWorkflows.show(); }
    else if (kind === "contacts") { renderCtTabs(); loadContacts(); }
    else if (kind === "deals") { if (window.ProspectingDeals) window.ProspectingDeals.show(); }
    else if (kind === "panels") { if (window.ProspectingPanels) window.ProspectingPanels.show(); }
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
    renderSegNote($("prSegNote"), segmentOf(key), "empresas");
    renderTabs();
    renderHead();
    renderColsMenu();
    renderAdvSummary();
    load();
  }

  function switchTab(key) {
    if (key === state.view) return;
    var v = viewOf(state.view);
    if (v && v.mine && !$("prTableCard").hidden && isDirty() &&
        !confirm("La vista «" + v.name + "» tiene cambios sin guardar. ¿Descartarlos?")) return;
    applyTab(key);
  }

  /* Pestañas a la vista: las primeras MAX_TABS; la activa, si está más atrás, toma el último
     lugar. Las demás van al botón «⋯ N más» (como HubSpot), así la tira no se hace eterna. */
  var MAX_TABS = 4;
  function shownTabs(onTable) {
    var tabs = VIEWS.tabs.slice(0, MAX_TABS);
    if (onTable && VIEWS.tabs.indexOf(state.view) >= MAX_TABS) tabs[MAX_TABS - 1] = state.view;
    return tabs;
  }
  function moreTabsMenu(anchor) {
    var shown = shownTabs(!$("prTableCard").hidden);
    var rest = VIEWS.tabs.filter(function (k) { return shown.indexOf(k) === -1; });
    openPop(anchor, '<div class="pr-pop__head">More views</div>' + rest.map(function (key) {
      return '<button type="button" class="pr-pop__item" data-tab-go="' + esc(key) + '"><i class="fa-solid ' +
        (segmentOf(key) ? "fa-layer-group" : "fa-table-list") + '"></i> ' + esc(tabLabel(key)) + "</button>";
    }).join("") + '<p class="pr-pop__note">Drag a tab to reorder. Opening one brings it to the bar.</p>');
  }
  function renderTabs() {
    var onTable = !$("prTableCard").hidden;
    var shown = shownTabs(onTable);
    var hiddenN = VIEWS.tabs.length - shown.length;
    $("prViewTabs").innerHTML = shown.map(function (key) {
      var v = viewOf(key);
      var active = onTable && key === state.view;
      var icon = v && v.shared ? ' <i class="fa-solid fa-user-group pr-tab__shared" title="' +
        esc(v.mine ? "Shared with the team" : "Shared by " + (v.owner_name || v.owner_email)) + '"></i>' : "";
      return '<button type="button" class="pr-tab pr-tab--view' + (active ? " is-active" : "") + '" role="tab" draggable="' + (isSys(key) ? "false" : "true") + '" data-tab="' + esc(key) + '">' +
        '<i class="fa-solid ' + (segmentOf(key) ? "fa-layer-group" : "fa-table-list") + ' pr-tab__icon"></i>' + esc(tabLabel(key)) + icon +
        (active ? '<span class="pr-tab__more" data-tab-menu="' + esc(key) + '" title="View options" role="button"><i class="fa-solid fa-ellipsis"></i></span>' : "") +
        "</button>";
    }).join("") + (hiddenN > 0
      ? '<button type="button" class="pr-tab pr-tab--overflow" id="prTabsMore" title="More views" aria-haspopup="menu">' +
        '<i class="fa-solid fa-ellipsis"></i> ' + hiddenN + " more</button>" : "");
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
  function closePop() { $("prViewPop").hidden = true; $("prViewPop").innerHTML = ""; $("prViewPop").classList.remove("pr-pop--actions", "pr-pop--sections"); }
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
      html += '<p class="pr-pop__note">' + (key === "sys:recycled" ? "Vista de todos: las empresas en Recycled."
          : key === "sys:week" ? "Vista de todos: tus empresas de la semana actual. Cambia sola cada lunes."
          : "Vista de todos, con todas las empresas.") +
        " Para filtrar a tu manera, guardá una copia o creá una vista con +.</p>" +
        item("duplicate", "fa-copy", "Save a copy as my view");
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
        if (!VIEWS.tabs.length) VIEWS.tabs = Object.keys(SYS_TABS);
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
      if (e.target.closest("#prTabsMore")) { e.stopPropagation(); moreTabsMenu($("prTabsMore")); return; }
      var tab = e.target.closest("[data-tab]");
      if (tab) switchTab(tab.getAttribute("data-tab"));
    });
    $("prSectionBtn").addEventListener("click", function (e) {
      e.stopPropagation();
      if (!$("prViewPop").hidden && $("prViewPop").querySelector("[data-section-go]")) closePop();
      else sectionMenu($("prSectionBtn"));
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
      if (target === dragTab || isSys(target) || isSys(dragTab)) { dragTab = null; return; }  // Companies queda primera
      var tabs = VIEWS.tabs.filter(function (k) { return k !== dragTab; });
      var at = tabs.indexOf(target);
      if (VIEWS.tabs.indexOf(dragTab) < VIEWS.tabs.indexOf(target)) at++;
      tabs.splice(at, 0, dragTab);
      dragTab = null;
      saveTabs(tabs);
    });
    $("prViewPop").addEventListener("click", function (e) {
      e.stopPropagation();
      var ba = e.target.closest("[data-bact]");
      if (ba) {
        if (ba.disabled) return;
        closePop();
        var kind = ba.getAttribute("data-kind");
        var act = ba.getAttribute("data-bact");
        if (act === "edit") openBulkEdit(kind);
        else if (act === "export") openExport(kind);
        else if (act === "segment") openSegment(kind);
        else if (act === "delete") openBulkDelete(kind);
        else openEnrollModal(kind);
        return;
      }
      var sp = e.target.closest("[data-sortpick]");
      if (sp) {
        closePop();
        var pick = sp.getAttribute("data-sortpick");
        if (sp.getAttribute("data-sortobj") === "company") {
          state.sort = pick || "created_desc";
          state.page = 1;
          renderHead();
          load();
        } else {
          setCtSort(pick);
        }
        return;
      }
      var sec = e.target.closest("[data-section-go]");
      if (sec) { closePop(); goSection(sec.getAttribute("data-section-go")); return; }
      var go = e.target.closest("[data-tab-go]");
      if (go) { closePop(); switchTab(go.getAttribute("data-tab-go")); return; }
      var ctGo = e.target.closest("[data-ctv-go]");
      if (ctGo) { closePop(); switchCtView(Number(ctGo.getAttribute("data-ctv-go"))); return; }
      var cva = e.target.closest("[data-ctvact]");
      if (cva) {
        closePop();
        onCtViewAction(cva.getAttribute("data-ctvact"), Number(cva.getAttribute("data-id")));
        return;
      }
      var b = e.target.closest("[data-vact]");
      if (b) onViewAction(b.getAttribute("data-vact"), b.getAttribute("data-key"));
    });
    $("prViewPop").addEventListener("submit", function (e) {
      e.preventDefault();
      if (e.target.id === "prCtViewCreate") {  // «+» de la tira de contactos
        var ctName = $("prCtViewName").value.trim();
        if (!ctName) return;
        var ctFrom = (document.querySelector('input[name="prCtViewFrom"]:checked') || {}).value !== "blank";
        var ctShared = $("prCtViewShared").checked;
        closePop();
        createCtView(ctName, ctFrom, ctShared).catch(viewError);
        return;
      }
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
    $("prCtAdvBtn").addEventListener("click", openCtAdvanced);
    $("prCtColsBtn").addEventListener("click", openCtColumns);
    $("prCtAdvSummary").addEventListener("click", function (e) {
      var b = e.target.closest("[data-ctadv]");
      if (!b) return;
      if (b.getAttribute("data-ctadv") === "edit") { openCtAdvanced(); return; }
      ctAdvanced = null;
      ctState.page = 1;
      renderCtAdvSummary();
      loadContacts();
    });
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
      fillContactFilters();
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
    // Click en el encabezado: menú con las formas de ordenar esa columna según su tipo.
    $("prHead").addEventListener("click", function (e) {
      var th = e.target.closest("th[data-sort]");
      if (!th) return;
      e.stopPropagation();
      sortMenu(th, "company", companyFieldOf(th.getAttribute("data-sort")), state.sort);
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
    bindHeaderDrag($("prHead"), function () { return visibleCols.slice(); }, setVisibleCols);
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
      if (b.id === "prBulkClear") { selected = {}; selAll = null; renderRows(lastRows); }
      if (b.hasAttribute("data-bulk-actions")) { e.stopPropagation(); bulkActionsMenu(b, "company"); }
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
      if (btn) { showCompany(Number(btn.getAttribute("data-open"))); return; }
      var ce = e.target.closest("td[data-co-edit]");
      if (ce && !ce.classList.contains("is-editing") && !e.target.closest("a")) {
        var cid2 = Number(ce.closest("tr").getAttribute("data-id")), key = ce.getAttribute("data-co-edit");
        var fdef = ((((OPTS.objects || {}).company || {}).fields) || []).filter(function (x) { return x.key === key; })[0] || { key: key, label: key, type: "text" };
        var cur = rowsById[cid2][key];
        inlineEdit(ce, fdef, fdef.type === "date" && cur ? String(cur).slice(0, 10) : cur, function (v) {
          var patch = {};
          patch[key] = v;
          return patchCompany(cid2, patch).then(function (row) {
            Object.assign(rowsById[cid2], row);
            renderRows(lastRows);
            announceWorkflows(row);
          });
        });
      }
    });
    document.querySelectorAll("[data-drawer-close]").forEach(function (el) {
      el.addEventListener("click", closeDrawer);
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeDrawer(); });
    $("prDrawerSave").addEventListener("click", function () { if (drawerSave) drawerSave(); });
    $("prTestBtn").addEventListener("click", showTestPanel);
    $("prBdrIdsBtn").addEventListener("click", showBdrIds);
    $("prDeletedBtn").addEventListener("click", showDeleted);
  }

  function init() {
    api("/prospecting/me").then(function (me) {
      if (!me.has_access) {
        $("prDenied").hidden = false;
        return;
      }
      ME = me;
      $("prApp").hidden = false;
      if (me.sees_dummies) $("prFDummyWrap").hidden = false;
      bind();
      bindContacts();
      return Promise.all([refreshOptions(), loadViews()]).then(function () {
        var saved = null;
        try { saved = localStorage.getItem(ACTIVE_KEY); } catch (e) {}
        var tabs = VIEWS.tabs;
        applyTab(tabs.indexOf(saved) !== -1 ? saved : (tabs[0] || "sys:all"));
        var ctSaved = null;
        try { ctSaved = Number(localStorage.getItem(CT_VIEW_KEY)) || null; } catch (e) {}
        applyCtView(ctSaved);
        var secSaved = null;
        try { secSaved = localStorage.getItem(SECTION_KEY); } catch (e) {}
        showSection("table");
        goSection(sectionOf(secSaved).key);
      });
    }).catch(function (err) {
      $("prDenied").hidden = false;
      $("prDenied").querySelector("p").textContent = "Could not load Business Dev: " + err.message;
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
    apiBase: function () { return API; },
    reloadTable: function () { return load(); },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
