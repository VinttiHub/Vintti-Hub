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
  var state = { view: "all", page: 1, pageSize: 25, sort: "created_desc", total: 0 };
  var rowsById = {};

  function ownerOptions() {
    return OPTS.bdrs.map(function (b) { return { value: b.email, label: b.name || b.email }; });
  }
  function ownerName(email) {
    if (!email) return "";
    var hit = OPTS.bdrs.filter(function (b) { return b.email === email; })[0];
    return hit ? (hit.name || hit.email) : email;
  }

  /* ---------- Filtros ---------- */
  function fillFilters() {
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
    // Las vistas son atajos de filtro, como las pestañas guardadas de HubSpot.
    if (state.view === "mine") f.owner = ME.email;
    if (state.view === "unassigned") f.owner = "__none__";
    if (state.view === "recycled") f.status = "Recycled";
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
      $("prBody").innerHTML = '<tr><td class="pr-empty" colspan="' + colspan() + '">' + esc(err.message) + "</td></tr>";
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
    { key: "prospecting_owner_apollo", label: "Prospecting Owner Apollo", render: function (r) { return cellText(r.prospecting_owner_apollo); } },
  ];

  var COLS_KEY = "prospecting_columns_v1";
  var visibleCols = (function () {
    try {
      var saved = JSON.parse(localStorage.getItem(COLS_KEY) || "null");
      if (Array.isArray(saved) && saved.length) return saved;
    } catch (e) {}
    return COLUMNS.filter(function (c) { return c.def; }).map(function (c) { return c.key; });
  })();

  function activeColumns() {
    return COLUMNS.filter(function (c) { return c.fixed || visibleCols.indexOf(c.key) !== -1; });
  }

  /* Selección para «Inscribir en workflow» (sólo quien edita workflows). */
  var selected = {};
  function canEnroll() { return !!ME.can_edit_workflows; }
  function colspan() { return activeColumns().length + (canEnroll() ? 1 : 0); }

  function renderHead() {
    $("prHead").innerHTML = (canEnroll()
      ? '<th class="pr-selcol"><label class="pr-check pr-check--bare"><input type="checkbox" id="prSelAll" title="Seleccionar la página"></label></th>' : "") +
      activeColumns().map(function (c) {
      var cls = [c.num ? "pr-num" : "", c.sort && c.sort === state.sort ? "is-sorted" : ""].filter(Boolean).join(" ");
      return "<th" + (c.sort ? ' data-sort="' + c.sort + '"' : "") + (cls ? ' class="' + cls + '"' : "") + ">" + esc(c.label) + "</th>";
    }).join("");
    $("prColsCount").textContent = activeColumns().length + "/" + COLUMNS.length;
  }

  function renderColsMenu() {
    $("prColsMenu").innerHTML = '<div class="pr-cols__head">Show columns</div>' + COLUMNS.map(function (c) {
      var on = c.fixed || visibleCols.indexOf(c.key) !== -1;
      return '<label class="pr-check"><input type="checkbox" data-col="' + c.key + '"' + (on ? " checked" : "") +
        (c.fixed ? " disabled" : "") + "> " + esc(c.label) + "</label>";
    }).join("") +
      '<div class="pr-cols__foot"><button type="button" class="pr-btn" data-cols="all">All</button>' +
      '<button type="button" class="pr-btn" data-cols="default">Default</button></div>';
  }

  function setVisibleCols(keys) {
    visibleCols = keys;
    try { localStorage.setItem(COLS_KEY, JSON.stringify(keys)); } catch (e) {}
    renderHead();
    renderColsMenu();
    renderRows(lastRows);
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
        (canEnroll() ? '<td class="pr-selcol"><label class="pr-check pr-check--bare"><input type="checkbox" data-sel="' + r.id + '"' + (selected[r.id] ? " checked" : "") + "></label></td>" : "") +
        cols.map(function (c) {
        return "<td" + (c.num ? ' class="pr-num"' : "") + ">" + c.render(r) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    renderBulk();
  }

  /* Barra de «N seleccionadas → Inscribir en workflow». */
  var wfChoices = null;
  function renderBulk() {
    var bar = $("prBulk");
    var ids = Object.keys(selected);
    if (!canEnroll() || !ids.length) { bar.hidden = true; return; }
    var opts = (wfChoices || []).map(function (w) {
      return '<option value="' + w.id + '">' + esc(w.name) + (w.enabled ? "" : " (inactivo)") + "</option>";
    }).join("");
    bar.hidden = false;
    bar.innerHTML = "<strong>" + ids.length + "</strong> seleccionada" + (ids.length === 1 ? "" : "s") +
      '<select class="pr-filter__input" id="prBulkWf">' + (wfChoices ? '<option value="">Elegir workflow…</option>' + opts : "<option>Cargando…</option>") + "</select>" +
      '<button type="button" class="pr-btn pr-btn--primary" id="prBulkGo"><i class="fa-solid fa-diagram-project"></i> Inscribir en workflow</button>' +
      '<button type="button" class="pr-btn" id="prBulkClear">Deseleccionar</button>';
    if (!wfChoices && window.ProspectingWorkflows) {
      window.ProspectingWorkflows.workflows().then(function (r) {
        wfChoices = r.workflows.filter(function (w) { return (w.object || "company") === "company"; });
        renderBulk();
      });
    }
  }
  function bulkEnroll() {
    var wfId = $("prBulkWf").value;
    if (!wfId) { alert("Elegí un workflow."); return; }
    var ids = Object.keys(selected).map(Number);
    window.ProspectingWorkflows.enrollCompanies(wfId, ids).then(function (r) {
      toast('<i class="fa-solid fa-diagram-project"></i> Se inscribieron <strong>' + r.enrolled + "</strong> de " + ids.length +
        (r.enrolled < ids.length ? " (las demás ya estaban adentro o el workflow no reinscribe)" : "") + ".");
      selected = {};
      load();
    }).catch(function (err) { alert(err.errors ? err.errors.join("\n") : err.message); });
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
    el.innerHTML = html;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 6000);
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
  function loadContacts() {
    var q = {
      q: $("prCtQ").value.trim(), lead_life: $("prCtLead").value, owner: $("prCtOwner").value,
      dummy: ME.sees_dummies ? $("prFDummy").value : "exclude", page: ctState.page, page_size: 25,
    };
    $("prCtBody").innerHTML = '<tr><td class="pr-empty" colspan="7">Loading…</td></tr>';
    api("/prospecting/contacts?" + qs(q)).then(function (r) {
      ctState.total = r.total;
      $("prCtBody").innerHTML = r.rows.length ? r.rows.map(function (c) {
        return '<tr data-ct="' + c.id + '" data-co="' + c.company_id + '">' +
          '<td><button type="button" class="pr-company__name" data-ct-open="' + c.id + '">' + esc(c.name) + "</button>" +
            (c.is_dummy ? ' <span class="pr-dummy-tag">DUMMY</span>' : "") + "</td>" +
          '<td><a class="pr-link" href="prospecting-company.html?id=' + c.company_id + '">' + esc(c.company_name) + "</a></td>" +
          "<td>" + cellText(c.email) + "</td>" +
          "<td>" + cellText(c.position) + "</td>" +
          "<td>" + (c.lead_life ? '<span class="pr-wf-stat">' + esc(c.lead_life) + "</span>" : "—") + "</td>" +
          "<td>" + cellText(ownerName(c.owner_email)) + "</td>" +
          "<td>" + (c.meeting_datetime ? esc(window.ProspectingContacts.fmtLocal(c.meeting_datetime)) : "—") + "</td></tr>";
      }).join("") : '<tr><td class="pr-empty" colspan="7">No contacts match these filters.</td></tr>';
      var pages = Math.max(1, Math.ceil(r.total / 25));
      $("prCtCount").textContent = r.total.toLocaleString() + " contact" + (r.total === 1 ? "" : "s");
      $("prCtPage").textContent = ctState.page + " / " + pages;
      $("prCtPrev").disabled = ctState.page <= 1;
      $("prCtNext").disabled = ctState.page >= pages;
    }).catch(function (err) {
      $("prCtBody").innerHTML = '<tr><td class="pr-empty" colspan="7">' + esc(err.message) + "</td></tr>";
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
    $("prCtBody").addEventListener("click", function (e) {
      var b = e.target.closest("[data-ct-open]");
      if (!b) return;
      var tr = b.closest("tr");
      window.ProspectingContacts.open({ contactId: Number(b.getAttribute("data-ct-open")), companyId: Number(tr.getAttribute("data-co")),
        onSaved: function () { loadContacts(); } });
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
    prospecting_owner_apollo: "Prospecting Owner Apollo",
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
          f("prospecting_owner_apollo", "Prospecting Owner Apollo",
            '<input class="pr-filter__input" data-edit="prospecting_owner_apollo" value="' + esc(c.prospecting_owner_apollo || "") + '">') +
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
    document.querySelectorAll(".pr-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        document.querySelectorAll(".pr-tab").forEach(function (t) { t.classList.toggle("is-active", t === tab); });
        state.view = tab.getAttribute("data-view");
        var isWf = state.view === "workflows", isCt = state.view === "contacts";
        $("prTableCard").hidden = isWf || isCt;
        $("prWorkflows").hidden = !isWf;
        $("prContactsView").hidden = !isCt;
        if (isWf) {
          if (window.ProspectingWorkflows) window.ProspectingWorkflows.show();
          return;
        }
        if (isCt) { loadContacts(); return; }
        state.page = 1;
        load();
      });
    });
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
    $("prHead").addEventListener("click", function (e) {
      var th = e.target.closest("th[data-sort]");
      if (!th) return;
      var s = th.getAttribute("data-sort");
      state.sort = state.sort === s ? "created_desc" : s;
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
      if (e.target.checked) next.push(key);
      // Mantener el orden de COLUMNS, no el de los clicks.
      setVisibleCols(COLUMNS.map(function (c) { return c.key; }).filter(function (k) { return next.indexOf(k) !== -1; }));
    });
    $("prColsMenu").addEventListener("click", function (e) {
      var mode = e.target.closest("[data-cols]");
      if (!mode) return;
      setVisibleCols(COLUMNS.filter(function (c) {
        return mode.getAttribute("data-cols") === "all" || c.def;
      }).map(function (c) { return c.key; }));
    });
    $("prBody").addEventListener("change", function (e) {
      var sel = e.target.getAttribute && e.target.getAttribute("data-sel");
      if (sel) {
        if (e.target.checked) selected[sel] = true; else delete selected[sel];
        e.target.closest("tr").classList.toggle("is-selected", e.target.checked);
        renderBulk();
        return;
      }
      onCellChange(e);
    });
    $("prHead").addEventListener("change", function (e) {
      if (e.target.id !== "prSelAll") return;
      lastRows.forEach(function (r) { if (e.target.checked) selected[r.id] = true; else delete selected[r.id]; });
      renderRows(lastRows);
    });
    $("prBulk").addEventListener("click", function (e) {
      var b = e.target.closest("button");
      if (!b) return;
      if (b.id === "prBulkGo") bulkEnroll();
      if (b.id === "prBulkClear") { selected = {}; renderRows(lastRows); }
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
  }

  function init() {
    api("/prospecting/me").then(function (me) {
      if (!me.has_access) {
        $("prDenied").hidden = false;
        return;
      }
      ME = me;
      $("prApp").hidden = false;
      if (me.is_admin) $("prTestBtn").hidden = false;
      if (me.sees_dummies) $("prFDummyWrap").hidden = false;
      renderHead();
      renderColsMenu();
      bind();
      bindContacts();
      return refreshOptions().then(load);
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
