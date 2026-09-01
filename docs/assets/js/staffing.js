/* =====================================================================
   Staffing — reemplazo del Google Sheet "Candidate Success VINTTI".

   Tres pestañas sobre los mismos datos del Hub:
     · Staffing Database — un renglón por (contractor, cliente)
     · Churn             — las bajas reales, con filtro de año
     · Bonos             — bonus_requests con los dos estados de pago

   Todo el filtrado y el orden se hacen en el cliente sobre el fetch inicial
   (son ~150 filas), igual que renderCohort() en control-dashboard.js.
   ===================================================================== */
(function () {
  "use strict";

  /* ---------- API base ---------- */
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
    try { localStorage.setItem("staffing_api", override.replace(/\/$/, "")); } catch (e) {}
  }
  var sticky = null;
  try { sticky = localStorage.getItem("staffing_api"); } catch (e) {}

  var API = (override && override.replace(/\/$/, "")) || sticky ||
            (isLocal ? "http://localhost:8080" : PROD);
  // Abrir la página en local no obliga a tener el backend levantado: si no
  // contesta, se cae al deployado una sola vez y se sigue usando ese.
  var canFallBack = isLocal && !override && !sticky && API !== PROD;

  function userEmail() {
    try {
      return (localStorage.getItem("user_email") || sessionStorage.getItem("user_email") || "").trim();
    } catch (e) { return ""; }
  }

  function request(base, path, options) {
    var opts = options || {};
    var headers = Object.assign({ "X-User-Email": userEmail() }, opts.headers || {});
    if (opts.body) headers["Content-Type"] = "application/json";
    return fetch(base + path, Object.assign({}, opts, { headers: headers })).then(
      function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) throw new Error(data.error || ("HTTP " + res.status + " en " + base + path));
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
      if (!err.offline || !canFallBack) {
        if (err.offline) {
          err.message += " If you are running locally, start the backend with " +
                         "`python app.py` from backend/, or open the page with ?api=<url>.";
        }
        throw err;
      }
      canFallBack = false;
      API = PROD;
      return request(API, path, options);
    });
  }

  /* ---------- Formato ---------- */
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function money(value) {
    var num = Number(value || 0);
    if (!num) return "—";
    return "$" + num.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }

  function fmtDate(iso) {
    if (!iso) return "—";
    var parts = String(iso).slice(0, 10).split("-");
    if (parts.length !== 3) return esc(iso);
    return MONTHS[Number(parts[1]) - 1] + " " + Number(parts[2]) + ", " + parts[0].slice(2);
  }

  function dash(value) { return value == null || value === "" ? "—" : esc(value); }

  // El backend cae al email del hr_lead cuando no encuentra el nombre en `users`
  // (típicamente ex-empleados que ya no están en la tabla). Se muestra prolijo.
  //
  // Devuelve TEXTO PLANO a propósito: es el mismo valor que usan los filtros de
  // columna, y si acá se escapara el HTML el desplegable mostraría el email crudo
  // mientras la celda muestra el nombre.
  function personText(value) {
    if (!value) return "";
    if (value.indexOf("@") === -1) return value;
    return value.split("@")[0].split(/[._-]/).filter(Boolean).map(function (part) {
      return part.charAt(0).toUpperCase() + part.slice(1);
    }).join(" ");
  }

  function personName(value) {
    return value ? esc(personText(value)) : "—";
  }

  // Mismo criterio para el concepto del bono: el valor del filtro tiene que ser
  // el texto que se ve, no el enum crudo ("one_time" vs "One time").
  function bonusTypeText(row) {
    if (row.reason) return row.reason;
    if (!row.bonus_type) return "";
    var t = row.bonus_type.replace(/_/g, " ");
    return t.charAt(0).toUpperCase() + t.slice(1);
  }

  function pct(part, total) {
    if (!total) return "—";
    return Math.round((part / total) * 100) + "%";
  }

  /* ---------- Estado ---------- */
  var CURRENT_YEAR = String(new Date().getFullYear());

  var state = {
    tab: "database",
    database: [],
    churn: { rows: [], years: [] },
    bonos: { rows: [], years: [] },
    loaded: {},
    editing: null,
    // Un filtro por columna, estilo Excel. text -> Set de valores elegidos;
    // number/date -> {min, max}. Si la clave no está, la columna no filtra.
    filters: { database: {}, churn: {}, bonos: {} },
    sort: { database: null, churn: null, bonos: null },
    search: { database: "", churn: "", bonos: "" }
  };

  var $ = function (sel) { return document.querySelector(sel); };
  var $$ = function (sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); };

  /* =====================================================================
     Definición de columnas

     Cada columna declara:
       key    identificador del filtro
       label  encabezado
       type   'text' (lista de checkboxes) | 'number' | 'date' (rango desde/hasta)
       value  valor crudo para filtrar y ordenar
       cell   HTML de la celda (por defecto, el valor escapado)
       total  suma en el pie de tabla
     ===================================================================== */
  function nameCell(row, sub) {
    var dot = row.status
      ? '<span class="stf-dot stf-dot--' +
        (row.status === "Active" ? "active" : row.status === "Onboarding" ? "onboarding" : "inactive") +
        '"></span>' : "";
    var orphan = row.orphan ? ' <span class="stf-badge stf-badge--ghost">Sheet only</span>' : "";
    var note = row.notes ? '<span class="stf-note-dot" title="' + esc(row.notes) + '"></span>' : "";
    return '<div class="stf-td-name__primary">' + dot + esc(row.candidate_name) + orphan + note + "</div>" +
      (sub ? '<div class="stf-td-name__sub">' + esc(sub) + "</div>" : "");
  }

  function moneyCell(cls) {
    return function (row, col) {
      var v = Number(col.value(row) || 0);
      if (!v) return '<span class="stf-td--muted">—</span>';
      return '<span class="stf-money' + (cls ? " " + cls : "") + '">' + money(v) + "</span>";
    };
  }

  function yesNoCell(row, col) {
    var v = col.value(row);
    if (v === "Yes") return '<span class="stf-badge stf-badge--warn">Yes</span>';
    if (v === "No") return '<span class="stf-badge">No</span>';
    return "—";
  }

  var COLUMNS = {
    database: [
      { key: "candidate_name", label: "Contractor", type: "text", sticky: true,
        value: function (r) { return r.candidate_name; },
        cell: function (r) { return nameCell(r, r.position_name); } },
      { key: "client_name", label: "Client", type: "text", align: "left",
        value: function (r) { return r.client_name; } },
      { key: "country", label: "Country", type: "text", align: "left",
        value: function (r) { return r.country; } },
      { key: "status", label: "Status", type: "text",
        value: function (r) { return r.status; },
        cell: function (r) { return statusBadge(r.status); } },
      { key: "start_date", label: "Start", type: "date", muted: true,
        value: function (r) { return r.start_date; },
        cell: function (r) { return fmtDate(r.start_date); } },
      { key: "end_date", label: "End", type: "date", muted: true,
        value: function (r) { return r.end_date; },
        cell: function (r) { return fmtDate(r.end_date); } },
      { key: "salary", label: "Salary", type: "number", total: true,
        value: function (r) { return r.salary; }, cell: moneyCell("") },
      { key: "fee", label: "Fee", type: "number", total: true,
        value: function (r) { return r.fee; }, cell: moneyCell("stf-money--soft") },
      { key: "client_payment", label: "Client payment", type: "number", total: true,
        value: function (r) { return r.client_payment; }, cell: moneyCell("stf-money--solid") },
      { key: "platform", label: "Platform", type: "text",
        value: function (r) { return r.platform; },
        cell: function (r) {
          return r.platform ? '<span class="stf-badge stf-badge--info">' + esc(r.platform) + "</span>" : "—";
        } },
      { key: "performance", label: "Performance", type: "text",
        value: function (r) { return r.performance; },
        cell: function (r) { return performanceBadge(r.performance); } },
      { key: "equipment", label: "Equipment", type: "text", muted: true,
        value: function (r) { return r.equipment; } },
      { key: "provider", label: "Provider", type: "text", muted: true,
        value: function (r) { return r.provider; } },
      { key: "recruiter", label: "Recruiter", type: "text", muted: true,
        value: function (r) { return personText(r.recruiter); } }
    ],
    churn: [
      { key: "candidate_name", label: "Contractor", type: "text", sticky: true,
        value: function (r) { return r.candidate_name; },
        cell: function (r) { return nameCell(r, ""); } },
      { key: "client_name", label: "Client", type: "text", align: "left",
        value: function (r) { return r.client_name; } },
      { key: "country", label: "Country", type: "text", align: "left",
        value: function (r) { return r.country; } },
      { key: "end_date", label: "End", type: "date", muted: true,
        value: function (r) { return r.end_date; },
        cell: function (r) { return fmtDate(r.end_date); } },
      { key: "exit_type", label: "Exit type", type: "text",
        value: function (r) { return r.exit_type; },
        cell: function (r) {
          if (!r.exit_type) return "—";
          var cls = r.exit_type === "Terminated" ? "stf-badge--bad" : "stf-badge--info";
          return '<span class="stf-badge ' + cls + '">' + esc(r.exit_type) + "</span>";
        } },
      { key: "inactive_reason", label: "Reason", type: "text", align: "left", muted: true,
        value: function (r) { return r.inactive_reason || "No reason"; } },
      { key: "vintti_fault", label: "Vintti's fault", type: "text",
        value: function (r) { return r.vintti_fault === true ? "Yes" : (r.vintti_fault === false ? "No" : null); },
        cell: function (r, col) {
          var v = col.value(r);
          if (v === "Yes") return '<span class="stf-badge stf-badge--bad">Yes</span>';
          if (v === "No") return '<span class="stf-badge">No</span>';
          return "—";
        } },
      { key: "churn_m3", label: "Churn M3", type: "text",
        value: function (r) { return r.churn_m3 ? "Yes" : "No"; }, cell: yesNoCell },
      { key: "recruiter", label: "Recruiter", type: "text", muted: true,
        value: function (r) { return personText(r.recruiter); } }
    ],
    bonos: [
      { key: "candidate_name", label: "Candidate", type: "text", sticky: true,
        value: function (r) { return r.candidate_name; },
        cell: function (r) {
          var note = r.notes ? '<span class="stf-note-dot" title="' + esc(r.notes) + '"></span>' : "";
          return '<div class="stf-td-name__primary">' + esc(r.candidate_name || "—") + note + "</div>";
        } },
      { key: "client_name", label: "Client", type: "text", align: "left",
        value: function (r) { return r.client_name; } },
      { key: "payout_date", label: "Date", type: "date", muted: true,
        value: function (r) { return r.payout_date; },
        cell: function (r) { return fmtDate(r.payout_date); } },
      { key: "amount", label: "Amount", type: "number", total: true,
        value: function (r) { return r.amount; }, cell: moneyCell("stf-money--solid") },
      { key: "reason", label: "Concept", type: "text", align: "left", muted: true,
        value: function (r) { return bonusTypeText(r); } },
      { key: "invoice_status", label: "Invoice (client)", type: "text",
        value: function (r) { return r.invoice_status; },
        cell: function (r) { return payBadge(r.invoice_status); } },
      { key: "candidate_status", label: "Paid to candidate", type: "text",
        value: function (r) { return r.candidate_status; },
        cell: function (r) { return payBadge(r.candidate_status); } }
    ]
  };

  function rowsOf(tab) {
    if (tab === "database") return state.database;
    return state[tab].rows;
  }

  function colsOf(tab) { return COLUMNS[tab]; }

  function findCol(tab, key) {
    var cols = colsOf(tab);
    for (var i = 0; i < cols.length; i++) if (cols[i].key === key) return cols[i];
    return null;
  }

  /* =====================================================================
     Filtrado
     ===================================================================== */
  var BLANK = "(Blank)";

  function displayValue(col, row) {
    var v = col.value(row);
    if (v === null || v === undefined || v === "") return BLANK;
    return String(v);
  }

  function passesColumn(tab, col, row) {
    var f = state.filters[tab][col.key];
    if (!f) return true;
    if (f.mode === "set") return f.values.indexOf(displayValue(col, row)) > -1;
    var v = col.value(row);
    if (col.type === "number") {
      var n = Number(v || 0);
      if (f.min !== "" && n < Number(f.min)) return false;
      if (f.max !== "" && n > Number(f.max)) return false;
      return true;
    }
    var d = v ? String(v).slice(0, 10) : "";
    if (!d) return f.min === "" && f.max === "";
    if (f.min !== "" && d < f.min) return false;
    if (f.max !== "" && d > f.max) return false;
    return true;
  }

  // El buscador de arriba: candidato o cliente, en cualquiera de las tres tablas.
  function passesSearch(tab, row) {
    var q = state.search[tab].trim().toLowerCase();
    if (!q) return true;
    return ((row.candidate_name || "") + " " + (row.client_name || "") + " " + (row.mail || ""))
      .toLowerCase().indexOf(q) > -1;
  }

  // `exceptKey` deja fuera el filtro de esa columna: así el desplegable ofrece
  // todos los valores que siguen siendo alcanzables, como hace Excel, y no se
  // vacía a sí mismo cuando destildás uno.
  function visibleRows(tab, exceptKey) {
    var cols = colsOf(tab);
    return rowsOf(tab).filter(function (row) {
      if (!passesSearch(tab, row)) return false;
      for (var i = 0; i < cols.length; i++) {
        if (cols[i].key === exceptKey) continue;
        if (!passesColumn(tab, cols[i], row)) return false;
      }
      return true;
    });
  }

  function sortRows(tab, rows) {
    var s = state.sort[tab];
    if (!s) return rows;
    var col = findCol(tab, s.key);
    if (!col) return rows;
    var dir = s.dir === "desc" ? -1 : 1;
    return rows.slice().sort(function (a, b) {
      var va = col.value(a), vb = col.value(b);
      var ea = va === null || va === undefined || va === "";
      var eb = vb === null || vb === undefined || vb === "";
      if (ea && eb) return 0;
      if (ea) return 1;          // los vacíos siempre al fondo
      if (eb) return -1;
      if (col.type === "number") return (Number(va) - Number(vb)) * dir;
      return String(va).localeCompare(String(vb), "en", { numeric: true }) * dir;
    });
  }

  function activeFilterCount(tab) {
    var n = Object.keys(state.filters[tab]).length;
    return state.search[tab].trim() ? n + 1 : n;
  }

  function clearFilters(tab) {
    state.filters[tab] = {};
    state.sort[tab] = null;
    state.search[tab] = "";
    var box = document.querySelector('[data-search="' + tab + '"]');
    if (box) box.value = "";
  }

  /* =====================================================================
     Render de la tabla
     ===================================================================== */
  function renderTable(tab, hostId, opts) {
    var host = $(hostId);
    if (!host) return [];
    var cols = colsOf(tab);
    var rows = sortRows(tab, visibleRows(tab));

    if (!rows.length) {
      host.innerHTML = '<div class="stf-empty">' + esc(opts.empty) + "</div>";
      return rows;
    }

    var sort = state.sort[tab];
    var head = cols.map(function (col) {
      var active = !!state.filters[tab][col.key];
      var arrow = sort && sort.key === col.key ? (sort.dir === "desc" ? " ↓" : " ↑") : "";
      return '<th class="' + (col.sticky ? "stf-th-name" : "") + (col.align === "left" ? " stf-th--left" : "") + '">' +
        '<button type="button" class="stf-th__btn' + (active ? " is-active" : "") +
        '" data-col="' + esc(col.key) + '">' +
        '<span>' + esc(col.label) + esc(arrow) + "</span>" +
        '<i class="fa-solid fa-filter stf-th__icon"></i>' +
        "</button></th>";
    }).join("");

    var totals = {};
    var body = rows.map(function (row, index) {
      if (!opts.totalOf || opts.totalOf(row)) {
        cols.forEach(function (col) {
          if (col.total) totals[col.key] = (totals[col.key] || 0) + Number(col.value(row) || 0);
        });
      }
      var cells = cols.map(function (col) {
        var cls = col.sticky ? "stf-td-name" : (col.align === "left" ? "stf-td--left" : "");
        if (col.muted) cls += " stf-td--muted";
        var html = col.cell ? col.cell(row, col) : dash(col.value(row));
        return '<td class="' + cls + '">' + html + "</td>";
      }).join("");
      return '<tr data-row="' + index + '">' + cells + "</tr>";
    }).join("");

    var foot = "";
    if (opts.totalLabel) {
      foot = "<tfoot><tr>" + cols.map(function (col, i) {
        if (i === 0) return '<td class="stf-td-name">' + esc(opts.totalLabel) + "</td>";
        return "<td>" + (col.total ? money(totals[col.key] || 0) : "") + "</td>";
      }).join("") + "</tr></tfoot>";
    }

    host.innerHTML = '<div class="stf-scroll"><table class="stf-table">' +
      "<thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody>" + foot + "</table></div>";

    host.querySelectorAll("tbody tr").forEach(function (tr) {
      tr.addEventListener("click", function () { opts.onRow(rows[Number(tr.dataset.row)]); });
    });
    // El popover se posiciona contra el documento: si la tabla scrollea en
    // horizontal, el encabezado se mueve y quedaría flotando desanclado.
    var scroller = host.querySelector(".stf-scroll");
    if (scroller) scroller.addEventListener("scroll", closePopover);
    host.querySelectorAll(".stf-th__btn").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        openFilterPopover(tab, btn.dataset.col, btn);
      });
    });
    return rows;
  }

  /* =====================================================================
     Popover de filtro por columna
     ===================================================================== */
  var pop = null;

  function closePopover() {
    if (pop) { pop.remove(); pop = null; }
  }

  function openFilterPopover(tab, key, anchor) {
    var wasOpen = pop && pop.dataset.col === key && pop.dataset.tab === tab;
    closePopover();
    if (wasOpen) return;

    var col = findCol(tab, key);
    if (!col) return;
    var current = state.filters[tab][key];

    pop = document.createElement("div");
    pop.className = "stf-pop";
    pop.dataset.col = key;
    pop.dataset.tab = tab;

    var sort = state.sort[tab];
    var html = '<div class="stf-pop__sort">' +
      '<button type="button" data-sort="asc"' + (sort && sort.key === key && sort.dir === "asc" ? ' class="is-active"' : "") + '>Sort A→Z</button>' +
      '<button type="button" data-sort="desc"' + (sort && sort.key === key && sort.dir === "desc" ? ' class="is-active"' : "") + '>Sort Z→A</button>' +
      "</div>";

    if (col.type === "text") {
      var values = {};
      visibleRows(tab, key).forEach(function (r) { values[displayValue(col, r)] = true; });
      var list = Object.keys(values).sort(function (a, b) {
        if (a === BLANK) return 1;
        if (b === BLANK) return -1;
        return a.localeCompare(b, "en", { numeric: true });
      });
      var chosen = current ? current.values : list;
      html += '<input type="text" class="stf-pop__search" placeholder="Search values…">' +
        '<label class="stf-pop__opt stf-pop__opt--all">' +
          '<input type="checkbox" data-all' + (chosen.length === list.length ? " checked" : "") + '>' +
          "<span>Select all</span></label>" +
        '<div class="stf-pop__list">' + list.map(function (v) {
          return '<label class="stf-pop__opt"><input type="checkbox" value="' + esc(v) + '"' +
            (chosen.indexOf(v) > -1 ? " checked" : "") + "><span>" + esc(v) + "</span></label>";
        }).join("") + "</div>";
    } else {
      var isDate = col.type === "date";
      var min = current ? current.min : "";
      var max = current ? current.max : "";
      html += '<div class="stf-pop__range">' +
        '<label><span>From</span><input type="' + (isDate ? "date" : "number") + '" data-min value="' + esc(min) + '"></label>' +
        '<label><span>To</span><input type="' + (isDate ? "date" : "number") + '" data-max value="' + esc(max) + '"></label>' +
        "</div>";
    }

    html += '<div class="stf-pop__foot">' +
      '<button type="button" data-reset>Clear</button>' +
      '<button type="button" class="stf-pop__apply" data-apply>Apply</button></div>';
    pop.innerHTML = html;
    document.body.appendChild(pop);

    var box = anchor.getBoundingClientRect();
    var left = Math.min(box.left, window.innerWidth - pop.offsetWidth - 12);
    pop.style.left = Math.max(12, left) + "px";
    pop.style.top = (box.bottom + window.scrollY + 6) + "px";

    var search = pop.querySelector(".stf-pop__search");
    if (search) {
      search.focus();
      search.addEventListener("input", function () {
        var q = search.value.trim().toLowerCase();
        pop.querySelectorAll(".stf-pop__list .stf-pop__opt").forEach(function (el) {
          el.style.display = el.textContent.toLowerCase().indexOf(q) > -1 ? "" : "none";
        });
      });
    }
    var all = pop.querySelector("[data-all]");
    if (all) {
      all.addEventListener("change", function () {
        pop.querySelectorAll('.stf-pop__list input[type="checkbox"]').forEach(function (cb) {
          if (cb.closest(".stf-pop__opt").style.display !== "none") cb.checked = all.checked;
        });
      });
    }

    pop.querySelectorAll("[data-sort]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        state.sort[tab] = { key: key, dir: btn.dataset.sort };
        closePopover();
        renderTab(tab);
      });
    });
    pop.querySelector("[data-reset]").addEventListener("click", function () {
      delete state.filters[tab][key];
      closePopover();
      renderTab(tab);
    });
    pop.querySelector("[data-apply]").addEventListener("click", function () {
      if (col.type === "text") {
        var picked = [];
        pop.querySelectorAll('.stf-pop__list input[type="checkbox"]').forEach(function (cb) {
          if (cb.checked) picked.push(cb.value);
        });
        var total = pop.querySelectorAll('.stf-pop__list input[type="checkbox"]').length;
        if (picked.length === total) delete state.filters[tab][key];
        else state.filters[tab][key] = { mode: "set", values: picked };
      } else {
        var mn = pop.querySelector("[data-min]").value;
        var mx = pop.querySelector("[data-max]").value;
        if (!mn && !mx) delete state.filters[tab][key];
        else state.filters[tab][key] = { mode: "range", min: mn, max: mx };
      }
      closePopover();
      renderTab(tab);
    });
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
  }

  document.addEventListener("click", closePopover);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePopover(); });
  window.addEventListener("resize", closePopover);

  /* =====================================================================
     Las tres pestañas
     ===================================================================== */
  function renderDatabase() {
    var rows = renderTable("database", "#stfTableDatabase", {
      empty: "No contractors match these filters.",
      totalLabel: "Active total",
      totalOf: function (r) { return r.status === "Active" || r.status === "Onboarding"; },
      onRow: openDatabaseDrawer
    });
    $("#stfCountDatabase").textContent = rows.length + " of " + state.database.length + " contractors";
    renderDatabaseKpis(rows);
  }

  function renderChurn() {
    var rows = renderTable("churn", "#stfTableChurn", {
      empty: "No exits match these filters.",
      onRow: openChurnDrawer
    });
    $("#stfCountChurn").textContent = rows.length + " exits";
    renderChurnKpis(rows);
  }

  function renderBonos() {
    var rows = renderTable("bonos", "#stfTableBonos", {
      empty: "No bonuses match these filters.",
      totalLabel: "Total",
      onRow: openBonoDrawer
    });
    $("#stfCountBonos").textContent = rows.length + " bonuses";
    renderBonosKpis(rows);
  }

  /* ---------- KPIs ---------- */
  function statusBadge(status) {
    if (status === "Active") return '<span class="stf-badge stf-badge--good">Active</span>';
    if (status === "Onboarding") return '<span class="stf-badge stf-badge--warn">Onboarding</span>';
    return '<span class="stf-badge stf-badge--bad">Inactive</span>';
  }

  function performanceBadge(value) {
    if (!value) return "—";
    var cls = value === "Performing" ? "stf-badge--good" : "stf-badge--warn";
    return '<span class="stf-badge ' + cls + '">' + esc(value) + "</span>";
  }

  function payBadge(value) {
    if (!value) return "—";
    var paid = String(value).toLowerCase() === "paid";
    return '<span class="stf-badge ' + (paid ? "stf-badge--good" : "stf-badge--warn") + '">' + esc(value) + "</span>";
  }

  function kpi(label, value, hint, color) {
    return '<div class="stf-kpi stf-kpi--' + color + '">' +
      '<div class="stf-kpi__label">' + esc(label) + "</div>" +
      '<div class="stf-kpi__value">' + esc(value) + "</div>" +
      '<div class="stf-kpi__hint">' + esc(hint) + "</div>" +
    "</div>";
  }

  // "Active" = los contratos vigentes, incluyendo a los que ya firmaron pero
  // todavía no arrancaron. Es el mismo total que el KPI del dashboard.
  function renderDatabaseKpis(rows) {
    var trabajando = rows.filter(function (r) { return r.status === "Active"; });
    var onboarding = rows.filter(function (r) { return r.status === "Onboarding"; });
    var inactive = rows.filter(function (r) { return r.status === "Inactive"; });
    var vigentes = trabajando.concat(onboarding);

    var byPlatform = {};
    vigentes.forEach(function (r) {
      var key = r.platform || "No platform";
      byPlatform[key] = (byPlatform[key] || 0) + 1;
    });
    var withPlatform = vigentes.filter(function (r) { return r.platform; });
    var platformHint = Object.keys(byPlatform).filter(function (k) { return k !== "No platform"; })
      .sort(function (a, b) { return byPlatform[b] - byPlatform[a]; })
      .map(function (k) { return k + " " + byPlatform[k]; }).join(" · ");

    var payment = vigentes.reduce(function (a, r) { return a + Number(r.client_payment || 0); }, 0);
    var fee = vigentes.reduce(function (a, r) { return a + Number(r.fee || 0); }, 0);

    $("#stfKpisDatabase").innerHTML = [
      kpi("Active", vigentes.length,
          trabajando.length + " working + " + onboarding.length + " starting soon", "lime"),
      kpi("Onboarding", onboarding.length, "signed, not started yet", "cyan"),
      kpi("Inactive", inactive.length, "already left", "mag"),
      kpi("Platform set", withPlatform.length + " of " + vigentes.length,
          platformHint || "not filled in yet", "blue"),
      kpi("Client payment", money(payment), "monthly · " + vigentes.length + " active", "violet"),
      kpi("Vintti fee", money(fee), "monthly · " + vigentes.length + " active", "violet")
    ].join("");
  }

  function renderChurnKpis(rows) {
    var total = rows.length;
    var terminated = rows.filter(function (r) { return r.exit_type === "Terminated"; }).length;
    var resigned = rows.filter(function (r) { return r.exit_type === "Resigned"; }).length;
    var fault = rows.filter(function (r) { return r.vintti_fault === true; }).length;
    var m3 = rows.filter(function (r) { return r.churn_m3; }).length;

    $("#stfKpisChurn").innerHTML = [
      kpi("Exits", total, "in the selected period", "mag"),
      kpi("Terminated", terminated, pct(terminated, total) + " of total", "mag"),
      kpi("Resigned", resigned, pct(resigned, total) + " of total", "cyan"),
      kpi("Vintti's fault", fault, pct(fault, total) + " of total", "violet"),
      kpi("Churn M3", m3, pct(m3, total) + " left within 3 months", "blue")
    ].join("");
  }

  function renderBonosKpis(rows) {
    var sum = function (list) { return list.reduce(function (a, r) { return a + Number(r.amount || 0); }, 0); };
    var paidByClient = rows.filter(function (r) { return String(r.invoice_status || "").toLowerCase() === "paid"; });
    var paidToCandidate = rows.filter(function (r) { return String(r.candidate_status || "").toLowerCase() === "paid"; });
    var pending = rows.filter(function (r) { return String(r.invoice_status || "").toLowerCase() !== "paid"; });

    $("#stfKpisBonos").innerHTML = [
      kpi("Total bonuses", money(sum(rows)), rows.length + " bonuses", "violet"),
      kpi("Invoiced & paid", money(sum(paidByClient)), paidByClient.length + " invoices paid", "lime"),
      kpi("Paid to candidate", money(sum(paidToCandidate)), paidToCandidate.length + " bonuses paid", "cyan"),
      kpi("Pending invoice", money(sum(pending)), pending.length + " invoices", "mag")
    ].join("");
  }

  /* =====================================================================
     Drawer
     ===================================================================== */
  var drawer = {
    el: null, title: null, sub: null, eyebrow: null, body: null, status: null, save: null
  };

  function openDrawer() {
    drawer.el.classList.add("is-open");
    drawer.el.setAttribute("aria-hidden", "false");
    drawer.status.textContent = "";
  }

  function closeDrawer() {
    drawer.el.classList.remove("is-open");
    drawer.el.setAttribute("aria-hidden", "true");
    state.editing = null;
  }

  function field(label, inner) {
    return '<div class="stf-field"><label>' + esc(label) + "</label>" + inner + "</div>";
  }

  function selectField(label, name, options, current) {
    var html = '<select data-edit="' + name + '">';
    options.forEach(function (opt) {
      var value = typeof opt === "string" ? opt : opt.value;
      var text = typeof opt === "string" ? (opt || "—") : opt.label;
      html += '<option value="' + esc(value) + '"' +
        (String(current == null ? "" : current) === value ? " selected" : "") + ">" + esc(text) + "</option>";
    });
    return field(label, html + "</select>");
  }

  function readonlyList(pairs, note) {
    var html = '<dl class="stf-readonly">';
    pairs.forEach(function (pair) {
      html += "<dt>" + esc(pair[0]) + "</dt><dd>" + (pair[2] ? pair[1] : esc(pair[1] == null || pair[1] === "" ? "—" : pair[1])) + "</dd>";
    });
    if (note) html += '<div class="stf-readonly__note">' + note + "</div>";
    return html + "</dl>";
  }

  // De dónde sale cada campo del bloque "From the Hub". Casi todo se carga en el
  // perfil del candidato (candidate-details.html tiene el formulario del hire:
  // salary, fee, fechas, computer y los campos de baja); de la oportunidad sólo
  // viene el recruiter (opportunity.opp_hr_lead).
  function sourceNote(row, extra) {
    var links = [];
    if (row.candidate_id) {
      links.push('the <a href="candidate-details.html?id=' + encodeURIComponent(row.candidate_id) +
        '">candidate profile</a> (' + (extra || "mail, country, dates, salary, fee, equipment") + ')');
    }
    if (row.opportunity_id) {
      links.push('the <a href="opportunity-detail.html?id=' + encodeURIComponent(row.opportunity_id) +
        '">opportunity</a> (recruiter)');
    }
    if (!links.length) return "";
    return "Edited on " + links.join(" and on ") + ".";
  }

  function openDatabaseDrawer(row) {
    state.editing = { kind: "database", row: row };
    drawer.eyebrow.textContent = "Contractor";
    drawer.title.textContent = row.candidate_name;
    drawer.sub.textContent = [row.client_name, row.position_name].filter(Boolean).join(" · ");
    drawer.save.style.display = "";

    drawer.body.innerHTML =
      '<div class="stf-section-label">Filled in by hand</div>' +
      selectField("Platform", "platform", ["", "Deel", "Ontop", "Bank Account"], row.platform) +
      selectField("Performance", "performance",
        ["", "Performing", "Under review", "Onboarding", "Salary review", "Computer repair"], row.performance) +
      selectField("Provider", "provider", ["", "Quipteams", "Onbordea"], row.provider) +
      field("Comments", '<textarea data-edit="notes">' + esc(row.notes || "") + "</textarea>") +
      '<div class="stf-section-label">From the Hub</div>' +
      readonlyList([
        ["Status", statusBadge(row.status), true],
        ["Mail", row.mail],
        ["Country", row.country],
        ["Recruiter", personName(row.recruiter), true],
        ["Start", fmtDate(row.start_date)],
        ["End", fmtDate(row.end_date)],
        ["Salary", money(row.salary)],
        ["Vintti fee", money(row.fee)],
        ["Client payment", money(row.client_payment)],
        ["Equipment", row.equipment]
      ], row.orphan
        ? "This row came from the Sheet and matched no hire in the Hub. It fills itself in once the opportunity exists."
        : sourceNote(row));

    openDrawer();
  }

  function openChurnDrawer(row) {
    state.editing = { kind: "churn", row: row };
    drawer.eyebrow.textContent = "Exit";
    drawer.title.textContent = row.candidate_name;
    drawer.sub.textContent = [row.client_name, fmtDate(row.end_date)].filter(Boolean).join(" · ");
    drawer.save.style.display = "";

    var overrideRaw = row.churn_m3_override;
    drawer.body.innerHTML =
      '<div class="stf-section-label">Filled in by hand</div>' +
      selectField("Exit type", "exit_type",
        ["", "Resigned", "Terminated"], row.exit_type) +
      selectField("Churn M3", "churn_m3_override", [
        { value: "", label: "Automatic" },
        { value: "si", label: "Yes" },
        { value: "no", label: "No" }
      ], overrideRaw === true ? "si" : (overrideRaw === false ? "no" : "")) +
      field("Comments", '<textarea data-edit="notes">' + esc(row.notes || "") + "</textarea>") +
      '<div class="stf-section-label">From the Hub</div>' +
      readonlyList([
        ["Reason", row.inactive_reason || "No reason"],
        ["Vintti's fault", row.vintti_fault === true ? "Yes" : (row.vintti_fault === false ? "No" : "—")],
        ["Exit comment", row.inactive_comments],
        ["Country", row.country],
        ["Recruiter", personName(row.recruiter), true],
        ["Start", fmtDate(row.start_date)],
        ["End", fmtDate(row.end_date)]
      ], sourceNote(row, "exit reason, Vintti's fault, exit comment, country, dates"));

    openDrawer();
  }

  function openBonoDrawer(row) {
    state.editing = { kind: "bono", row: row };
    drawer.eyebrow.textContent = row.bonus_id ? "Bonus" : "New bonus";
    drawer.title.textContent = row.candidate_name || "New bonus";
    drawer.sub.textContent = row.client_name || "";
    drawer.save.style.display = "";

    var payOptions = ["", "Paid", "Sent, not paid"];
    drawer.body.innerHTML =
      (row.bonus_id ? "" :
        field("Candidate", '<input type="text" data-edit="candidate_name" value="">')) +
      field("Amount (USD)", '<input type="number" step="0.01" data-edit="amount" value="' + esc(row.amount || "") + '">') +
      field("Date *", '<input type="date" required data-edit="payout_date" value="' + esc((row.payout_date || "").slice(0, 10)) + '">') +
      field("Concept", '<input type="text" data-edit="reason" value="' + esc(row.reason || "") + '">') +
      selectField("Invoice (client)", "invoice_status", payOptions, row.invoice_status) +
      selectField("Paid to candidate", "candidate_status", ["", "Paid", "Not Paid"], row.candidate_status) +
      field("Comments", '<textarea data-edit="notes">' + esc(row.notes || "") + "</textarea>");

    openDrawer();
  }

  function collectEdits() {
    var out = {};
    drawer.body.querySelectorAll("[data-edit]").forEach(function (el) {
      out[el.dataset.edit] = el.value.trim();
    });
    return out;
  }

  function save() {
    if (!state.editing) return;
    var kind = state.editing.kind;
    var row = state.editing.row;
    var edits = collectEdits();

    drawer.save.disabled = true;
    drawer.status.textContent = "Saving…";

    var request;
    if (kind === "bono") {
      if (!edits.payout_date) {
        drawer.save.disabled = false;
        drawer.status.textContent = "The bonus date is required.";
        return;
      }
      var payload = {
        amount: edits.amount === "" ? 0 : Number(edits.amount),
        payout_date: edits.payout_date,
        reason: edits.reason || null,
        notes: edits.notes || null,
        invoice_status: edits.invoice_status || null,
        candidate_status: edits.candidate_status || null
      };
      request = row.bonus_id
        ? api("/staffing/bonuses/" + row.bonus_id, { method: "PATCH", body: JSON.stringify(payload) })
        : api("/staffing/bonuses", {
            method: "POST",
            body: JSON.stringify(Object.assign(payload, { candidate_name: edits.candidate_name }))
          });
    } else {
      if (row.orphan) {
        drawer.save.disabled = false;
        drawer.status.textContent = "This row is not linked to a Hub hire yet, so it cannot be edited.";
        return;
      }
      var body = {
        candidate_id: row.candidate_id,
        account_id: row.account_id,
        platform: edits.platform || null,
        performance: edits.performance || null,
        provider: edits.provider || null,
        notes: edits.notes || null
      };
      if (kind === "churn") {
        body = {
          candidate_id: row.candidate_id,
          account_id: row.account_id,
          exit_type: edits.exit_type || null,
          churn_m3_override: edits.churn_m3_override || null,
          notes: edits.notes || null
        };
      }
      request = api("/staffing/extra", { method: "PATCH", body: JSON.stringify(body) });
    }

    request.then(function () {
      drawer.status.textContent = "Saved.";
      state.loaded = {};
      return loadTab(state.tab, true);
    }).then(function () {
      closeDrawer();
    }).catch(function (err) {
      drawer.status.textContent = "Could not save: " + err.message;
    }).then(function () {
      drawer.save.disabled = false;
    });
  }

  /* =====================================================================
     Carga por pestaña
     ===================================================================== */
  function showError(hostId, message) {
    var host = $(hostId);
    if (host) host.innerHTML = '<div class="stf-error">' + esc(message) + "</div>";
  }

  function yearValue(tab) {
    var el = document.querySelector('[data-year="' + tab + '"]');
    return el && el.dataset.filled === "1" ? el.value : "";
  }

  // Llena el <select> de año. El `current` que trae el elemento es el primer
  // <option> que el navegador auto-selecciona, no una elección: por eso el
  // fallback tiene prioridad si existe entre los valores.
  function fillYears(tab, years, fallback) {
    var el = document.querySelector('[data-year="' + tab + '"]');
    if (!el || el.dataset.filled === "1") return;
    var html = '<option value="all">All</option>';
    years.filter(Boolean).forEach(function (y) {
      html += '<option value="' + esc(y) + '">' + esc(y) + "</option>";
    });
    el.innerHTML = html;
    el.value = (fallback && years.indexOf(fallback) > -1) ? fallback : "all";
    el.dataset.filled = "1";
  }

  function loadTab(tab, force) {
    if (state.loaded[tab] && !force) { renderTab(tab); return Promise.resolve(); }

    if (tab === "database") {
      $("#stfTableDatabase").innerHTML = '<div class="stf-empty">Loading…</div>';
      return api("/staffing/database").then(function (rows) {
        state.database = rows;
        state.loaded.database = true;
        renderDatabase();
      }).catch(function (err) { showError("#stfTableDatabase", err.message); });
    }

    if (tab === "churn") {
      $("#stfTableChurn").innerHTML = '<div class="stf-empty">Loading…</div>';
      // Por defecto el año en curso; si todavía no hubo bajas, el más reciente.
      var chosen = yearValue("churn");
      var year = chosen || CURRENT_YEAR;
      return api("/staffing/churn?year=" + encodeURIComponent(year)).then(function (data) {
        state.churn = data;
        state.loaded.churn = true;
        if (!chosen && data.years.length && data.years.indexOf(year) === -1) {
          fillYears("churn", data.years, data.years[0]);
          state.loaded.churn = false;
          return loadTab("churn", true);
        }
        fillYears("churn", data.years, CURRENT_YEAR);
        renderChurn();
      }).catch(function (err) { showError("#stfTableChurn", err.message); });
    }

    $("#stfTableBonos").innerHTML = '<div class="stf-empty">Loading…</div>';
    var boYear = yearValue("bonos") || "all";
    return api("/staffing/bonuses?year=" + encodeURIComponent(boYear)).then(function (data) {
      state.bonos = data;
      state.loaded.bonos = true;
      fillYears("bonos", data.years, "all");
      renderBonos();
    }).catch(function (err) { showError("#stfTableBonos", err.message); });
  }

  function renderTab(tab) {
    if (tab === "database") return renderDatabase();
    if (tab === "churn") return renderChurn();
    return renderBonos();
  }

  // El filtro de año lo resuelve el server, así que hay que volver a pedir.
  function reloadYear(tab) {
    state.loaded[tab] = false;
    loadTab(tab, true);
  }

  /* =====================================================================
     Init
     ===================================================================== */
  function init() {
    drawer.el = $("#stfDrawer");
    drawer.title = $("#stfDrawerTitle");
    drawer.sub = $("#stfDrawerSub");
    drawer.eyebrow = $("#stfDrawerEyebrow");
    drawer.body = $("#stfDrawerBody");
    drawer.status = $("#stfDrawerStatus");
    drawer.save = $("#stfDrawerSave");

    $$("[data-drawer-close]").forEach(function (el) { el.addEventListener("click", closeDrawer); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && drawer.el.classList.contains("is-open")) closeDrawer();
    });
    drawer.save.addEventListener("click", save);

    $$(".stf-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tab = btn.dataset.tab;
        state.tab = tab;
        closePopover();
        $$(".stf-tab").forEach(function (b) { b.classList.toggle("is-active", b === btn); });
        $$(".stf-panel").forEach(function (p) { p.classList.toggle("is-active", p.dataset.panel === tab); });
        $("#stfExportCsv").style.display = tab === "database" ? "" : "none";
        loadTab(tab);
      });
    });

    $$("[data-search]").forEach(function (el) {
      el.addEventListener("input", function () {
        state.search[el.dataset.search] = el.value;
        renderTab(el.dataset.search);
      });
    });

    $$("[data-year]").forEach(function (el) {
      el.addEventListener("change", function () { reloadYear(el.dataset.year); });
    });

    $$("[data-clear]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tab = btn.dataset.clear;
        clearFilters(tab);
        closePopover();
        renderTab(tab);
      });
    });

    // El botón de "nuevo bono" vive en los filtros de su pestaña.
    var bonosFilters = document.querySelector('[data-panel="bonos"] .stf-filters');
    var newBonus = document.createElement("button");
    newBonus.type = "button";
    newBonus.className = "stf-btn stf-btn--primary";
    newBonus.innerHTML = '<i class="fa-solid fa-plus"></i> New bonus';
    newBonus.addEventListener("click", function () { openBonoDrawer({}); });
    bonosFilters.appendChild(newBonus);

    $("#stfExportCsv").addEventListener("click", function (e) {
      e.preventDefault();
      // La descarga necesita el header X-User-Email, así que se baja por fetch.
      fetch(API + "/staffing/database.csv", { headers: { "X-User-Email": userEmail() } })
        .then(function (res) {
          if (!res.ok) throw new Error("Could not export (HTTP " + res.status + ")");
          return res.blob();
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = "staffing-database.csv";
          a.click();
          URL.revokeObjectURL(url);
        })
        .catch(function (err) { alert(err.message); });
    });

    $("#stfExportCsv").style.display = "";
    loadTab("database");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
