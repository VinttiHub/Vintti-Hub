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
            (isLocal ? "http://127.0.0.1:5000" : PROD);
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
                         "`flask --app app.py --debug run --port 5000` from backend/, or open the page with ?api=<url>.";
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
    // El salary tiene centavos (numeric(12,2)): enteros sin ".00", el resto a 2 decimales.
    var cents = !Number.isInteger(num);
    return "$" + num.toLocaleString("en-US", {
      minimumFractionDigits: cents ? 2 : 0, maximumFractionDigits: 2 });
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

  // Check "Payments": se tilda directo en la tabla, sin abrir el drawer. Las filas
  // que sólo existen en el Sheet no tienen par (candidato, cuenta) y no se editan.
  function paymentCell(row) {
    return '<input type="checkbox" class="stf-pay" data-pay' +
      (row.payment ? " checked" : "") + (row.orphan ? " disabled" : "") +
      ' aria-label="Payments">';
  }

  /* ---------- Catálogos y columnas custom (GET /staffing/schema) ----------
     Las opciones de cada desplegable y las columnas nuevas se cargan desde la
     página y viven en la base (staffing_options / staffing_columns). Esto es
     sólo el respaldo si /schema no contesta: el orden es el que quiere la owner. */
  var FALLBACK_OPTIONS = {
    "database.platform": [["Bank Account", "orange"], ["Deel", "lilac"], ["Ontop", "cyan"], ["Payoneer", "magenta"]],
    "database.performance": [["Not performing", "red"], ["Performing", "green"], ["Under review", "yellow"],
      ["Feedback", "orange"], ["Salary review", "blue"], ["Computer repair", "purple"],
      ["Computer pedido", "magenta"], ["Onboarding", "teal"]],
    "database.provider": [["Quipteams", "blue"], ["Onbordea", "teal"]],
    "churn.exit_type": [["Resigned", "cyan"], ["Terminated", "red"]],
    "bonos.invoice_status": [["Paid", "green"], ["Sent, not paid", "yellow"]],
    "bonos.candidate_status": [["Paid", "green"], ["Not Paid", "yellow"]]
  };
  var COLORS = ["gray", "red", "orange", "yellow", "green", "teal", "cyan", "blue", "lilac", "purple", "magenta"];

  var schema = { columns: [], options: {}, ready: false };

  function optionsOf(tab, key) {
    var list = schema.options[tab + "." + key];
    if (list) return list;
    return (FALLBACK_OPTIONS[tab + "." + key] || []).map(function (pair) {
      return { value: pair[0], color: pair[1] };
    });
  }

  function optionValues(tab, key) {
    return optionsOf(tab, key).map(function (o) { return o.value; });
  }

  function findOption(tab, key, value) {
    var needle = String(value == null ? "" : value).trim().toLowerCase();
    var list = optionsOf(tab, key);
    for (var i = 0; i < list.length; i++) {
      if (list[i].value.toLowerCase() === needle) return list[i];
    }
    return null;
  }

  function colorBadge(color, value) {
    return '<span class="stf-badge stf-badge--c-' + esc(color || "gray") + '">' + esc(value) + "</span>";
  }

  // Un valor que ya no está en el catálogo (opción oculta, texto viejo del Sheet)
  // se sigue mostrando, en gris.
  function optionBadge(tab, key, value) {
    if (value == null || value === "") return "—";
    var opt = findOption(tab, key, value);
    return colorBadge(opt ? opt.color : "gray", value);
  }

  // Un desplegable del drawer tiene que incluir el valor actual aunque esté fuera
  // del catálogo: si no, el <select> cae en "" y el Save lo borra sin avisar.
  function withCurrent(values, current) {
    if (current == null || current === "") return values;
    var has = values.some(function (v) { return String(v).toLowerCase() === String(current).toLowerCase(); });
    return has ? values : values.concat([String(current)]);
  }

  // Columna de lista "de fábrica": su catálogo se edita desde la página y la celda
  // se edita en el lugar. `field` es el campo del PATCH; por defecto, la clave.
  function selectCol(tab, key, label, extra) {
    return Object.assign({
      key: key, label: label, type: "text", editable: "select",
      options: function () { return optionValues(tab, key); },
      badge: function (v) { return optionBadge(tab, key, v); },
      value: function (r) { return r[key]; },
      cell: function (r) { return optionBadge(tab, key, r[key]); }
    }, extra || {});
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
      // Churn date = `carga_inactive` en la base: el día en que se le dio de baja,
      // que no siempre coincide con el último día trabajado (End).
      { key: "churn_date", label: "Churn date", type: "date", muted: true,
        value: function (r) { return r.churn_date; },
        cell: function (r) { return fmtDate(r.churn_date); } },
      { key: "salary", label: "Salary", type: "number", total: true,
        value: function (r) { return r.salary; }, cell: moneyCell("") },
      { key: "fee", label: "Fee", type: "number", total: true,
        value: function (r) { return r.fee; }, cell: moneyCell("stf-money--soft") },
      { key: "client_payment", label: "Client payment", type: "number", total: true,
        value: function (r) { return r.client_payment; }, cell: moneyCell("stf-money--solid") },
      { key: "payment", label: "Payments", type: "text", options: ["Yes", "No"],
        value: function (r) { return r.payment ? "Yes" : "No"; },
        cell: paymentCell },
      selectCol("database", "platform", "Platform"),
      selectCol("database", "performance", "Performance"),
      { key: "equipment", label: "Equipment", type: "text", muted: true,
        value: function (r) { return r.equipment; } },
      // Si el equipo trae proveedor (equipments.proveedor), ése gana en el backend:
      // editar el de acá no cambiaría lo que se ve, así que esa celda no se edita.
      selectCol("database", "provider", "Provider", {
        canEdit: function (r) { return !r.provider_locked; }
      }),
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
      selectCol("churn", "exit_type", "Exit type"),
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
      selectCol("bonos", "invoice_status", "Invoice (client)"),
      selectCol("bonos", "candidate_status", "Paid to candidate")
    ]
  };

  function rowsOf(tab) {
    if (tab === "database") return state.database;
    return state[tab].rows;
  }

  function numText(value) {
    var n = Number(value);
    if (value == null || value === "" || isNaN(n)) return "—";
    return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }

  function customValue(row, key) {
    return (row.custom || {})[key];
  }

  // Una columna creada desde la página, traducida al mismo contrato que las de
  // COLUMNS: así el filtro, el orden y los totales no saben la diferencia.
  function customCol(def) {
    var key = def.key;
    var col = {
      key: key, label: def.label, custom: def, editable: def.type,
      type: def.type === "number" ? "number" : (def.type === "date" ? "date" : "text"),
      value: function (r) { return customValue(r, key); }
    };
    if (def.type === "select") {
      col.options = function () { return optionValues(def.tab, key); };
      col.badge = function (v) { return optionBadge(def.tab, key, v); };
      col.cell = function (r) { return optionBadge(def.tab, key, customValue(r, key)); };
    } else if (def.type === "checkbox") {
      col.options = ["Yes", "No"];
      col.value = function (r) {
        var v = customValue(r, key);
        return v === true ? "Yes" : (v === false ? "No" : null);
      };
      col.cell = function (r) {
        return '<input type="checkbox" class="stf-pay" data-custom-check' +
          (customValue(r, key) === true ? " checked" : "") + (r.orphan ? " disabled" : "") +
          ' aria-label="' + esc(def.label) + '">';
      };
    } else if (def.type === "number") {
      col.total = true;
      col.fmtTotal = numText;
      col.cell = function (r) { return numText(customValue(r, key)); };
    } else if (def.type === "date") {
      col.muted = true;
      col.cell = function (r) { return fmtDate(customValue(r, key)); };
    } else {
      col.align = "left";
    }
    return col;
  }

  function customDefs(tab, archived) {
    return schema.columns.filter(function (c) {
      return c.tab === tab && !!c.archived === !!archived;
    });
  }

  function colsOf(tab) { return COLUMNS[tab].concat(customDefs(tab).map(customCol)); }

  function colOptions(col) {
    return typeof col.options === "function" ? col.options() : col.options;
  }

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
    // Última columna: "+" para crear una columna nueva (o restaurar una oculta).
    head += '<th class="stf-th-add"><button type="button" class="stf-th__add" data-add-col ' +
      'title="Add a column"><i class="fa-solid fa-plus"></i></button></th>';

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
        var attrs = "";
        if (isCellEditable(tab, col, row)) {
          cls += " stf-td--edit";
          attrs = ' data-cell="' + esc(col.key) + '"';
        }
        var html = col.cell ? col.cell(row, col) : dash(col.value(row));
        return '<td class="' + cls + '"' + attrs + ">" + html + "</td>";
      }).join("");
      return '<tr data-row="' + index + '">' + cells + "<td></td></tr>";
    }).join("");
    // Sin filas se dibuja igual el encabezado: los filtros por columna viven ahí,
    // y sin él no habría forma de sacar el filtro que dejó la tabla vacía.
    if (!rows.length) {
      body = '<tr class="stf-empty-row"><td colspan="' + (cols.length + 1) + '">' +
        '<div class="stf-empty">' + esc(opts.empty) + "</div></td></tr>";
    }

    var foot = "";
    if (opts.totalLabel && rows.length) {
      foot = "<tfoot><tr>" + cols.map(function (col, i) {
        if (i === 0) return '<td class="stf-td-name">' + esc(opts.totalLabel) + "</td>";
        return "<td>" + (col.total ? (col.fmtTotal || money)(totals[col.key] || 0) : "") + "</td>";
      }).join("") + "<td></td></tr></tfoot>";
    }

    // Editar una celda vuelve a dibujar la tabla: sin esto, la tabla vuelve al
    // principio y se pierde de vista la columna que se estaba editando.
    var oldScroller = host.querySelector(".stf-scroll");
    var keepLeft = oldScroller ? oldScroller.scrollLeft : 0;
    var keepTop = oldScroller ? oldScroller.scrollTop : 0;

    host.innerHTML = '<div class="stf-scroll"><table class="stf-table">' +
      "<thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody>" + foot + "</table></div>";

    var newScroller = host.querySelector(".stf-scroll");
    newScroller.scrollLeft = keepLeft;
    newScroller.scrollTop = keepTop;
    var restoredLeft = newScroller.scrollLeft;
    var restoredTop = newScroller.scrollTop;

    host.querySelectorAll("tbody tr[data-row]").forEach(function (tr) {
      tr.addEventListener("click", function () { opts.onRow(rows[Number(tr.dataset.row)]); });
    });
    host.querySelectorAll("td[data-cell]").forEach(function (td) {
      td.addEventListener("click", function (e) {
        e.stopPropagation();
        if (e.target.matches("input[type=checkbox]")) return;
        openCellEditor(tab, rows[Number(td.closest("tr").dataset.row)], findCol(tab, td.dataset.cell), td);
      });
    });
    host.querySelectorAll("[data-custom-check]").forEach(function (cb) {
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () {
        var td = cb.closest("td");
        saveCell(tab, rows[Number(td.closest("tr").dataset.row)], findCol(tab, td.dataset.cell),
          cb.checked);
      });
    });
    host.querySelector("[data-add-col]").addEventListener("click", function (e) {
      e.stopPropagation();
      openAddColumn(tab, e.currentTarget);
    });
    host.querySelectorAll("[data-pay]").forEach(function (cb) {
      // El click de la fila abre el drawer: el checkbox no tiene que propagarlo.
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () {
        togglePayment(rows[Number(cb.closest("tr").dataset.row)], cb);
      });
    });
    // El popover se posiciona contra el documento: si la tabla scrollea en
    // horizontal, el encabezado se mueve y quedaría flotando desanclado.
    // Restaurar el scroll de arriba dispara un "scroll" propio: ése no cierra nada
    // (si no, el editor de opciones se cerraría solo apenas se repinta la tabla).
    newScroller.addEventListener("scroll", function () {
      if (newScroller.scrollLeft === restoredLeft && newScroller.scrollTop === restoredTop) return;
      restoredLeft = restoredTop = -1;
      closePopover();
    });
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
      // Columnas con catálogo (Performance): primero el catálogo en su orden,
      // después lo que haya en los datos y no esté en él, y (Blank) al final.
      var catalog = colOptions(col);
      if (catalog) {
        var extra = list.filter(function (v) { return catalog.indexOf(v) === -1 && v !== BLANK; });
        list = catalog.concat(extra).concat(values[BLANK] ? [BLANK] : []);
      }
      var chosen = current ? current.values : list;
      html += '<input type="text" class="stf-pop__search" placeholder="Search values…">' +
        '<label class="stf-pop__opt stf-pop__opt--all">' +
          '<input type="checkbox" data-all' + (chosen.length === list.length ? " checked" : "") + '>' +
          "<span>Select all</span></label>" +
        '<div class="stf-pop__list">' + list.map(function (v) {
          var label = col.badge && v !== BLANK ? col.badge(v) : esc(v);
          return '<label class="stf-pop__opt"><input type="checkbox" value="' + esc(v) + '"' +
            (chosen.indexOf(v) > -1 ? " checked" : "") + "><span>" + label + "</span></label>";
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

    // Lo que se puede hacer con la columna en sí, no con el filtro.
    var manage = "";
    if (col.editable === "select") {
      manage += '<button type="button" data-manage="options"><i class="fa-solid fa-list"></i> Edit options</button>';
    }
    if (col.custom) {
      manage += '<button type="button" data-manage="rename"><i class="fa-solid fa-pen"></i> Rename column</button>' +
        '<button type="button" data-manage="hide"><i class="fa-regular fa-eye-slash"></i> Hide column</button>' +
        '<button type="button" class="is-danger" data-manage="delete"><i class="fa-regular fa-trash-can"></i> Delete column</button>';
    }
    if (manage) html += '<div class="stf-pop__manage">' + manage + "</div>";
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
    pop.querySelectorAll("[data-manage]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var action = btn.dataset.manage;
        if (action === "options") return openOptionsEditor(tab, col, anchor);
        if (action === "rename") return renameColumn(tab, col);
        if (action === "hide") return hideColumn(tab, col);
        if (action === "delete") return deleteColumn(tab, col.custom);
      });
    });
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
  }

  // Abre un popover vacío anclado a `anchor`, compartiendo el `pop` del filtro:
  // así cualquier click afuera, Esc o un scroll lo cierran igual que al filtro.
  function openPanel(className, anchor, html, width) {
    closePopover();
    pop = document.createElement("div");
    pop.className = "stf-pop " + className;
    if (width) pop.style.width = width + "px";
    pop.innerHTML = html;
    document.body.appendChild(pop);
    placePanel(anchor);
    pop.addEventListener("click", function (e) { e.stopPropagation(); });
    return pop;
  }

  // `anchor` es un elemento o un punto ya medido ({left, bottom}). El punto sirve
  // para los paneles que se redibujan después de repintar la tabla: para entonces
  // el elemento original ya no está en el documento y mediría 0,0.
  function anchorSpot(anchor) {
    if (!anchor.getBoundingClientRect) return anchor;
    var box = anchor.getBoundingClientRect();
    return { left: box.left, bottom: box.bottom + window.scrollY };
  }

  function placePanel(anchor) {
    if (!pop) return;
    var spot = anchorSpot(anchor);
    var left = Math.min(spot.left, window.innerWidth - pop.offsetWidth - 12);
    pop.style.left = Math.max(12, left) + "px";
    pop.style.top = (spot.bottom + 6) + "px";
  }

  /* =====================================================================
     Columnas y opciones editables desde la página
     ===================================================================== */
  function loadSchema() {
    return api("/staffing/schema").then(function (data) {
      schema.columns = data.columns || [];
      schema.options = data.options || {};
      if (data.colors && data.colors.length) COLORS = data.colors;
      schema.ready = true;
    }).catch(function (err) {
      // Sin /schema la página sigue andando con los catálogos de respaldo; lo único
      // que no se ve son las columnas custom.
      schema.ready = false;
      if (window.console) console.warn("Staffing: could not load columns/options —", err.message);
    });
  }

  // Después de tocar columnas u opciones: se recarga el catálogo y, si el cambio
  // movió valores en las filas (renombre), también los datos de la pestaña.
  function refreshSchema(tab, reloadRows) {
    return loadSchema().then(function () {
      if (reloadRows) {
        state.loaded[tab] = false;
        return loadTab(tab, true);
      }
      renderTab(tab);
    });
  }

  function nextColor(list) {
    var used = {};
    list.forEach(function (o) { used[o.color] = true; });
    var free = COLORS.filter(function (c) { return c !== "gray" && !used[c]; });
    return free[0] || COLORS[(list.length + 1) % COLORS.length];
  }

  function columnTab(col) { return col.custom ? col.custom.tab : null; }

  // La pestaña dueña del catálogo de una columna de lista.
  function optionsTab(tab, col) { return columnTab(col) || tab; }

  var TYPE_LABELS = {
    select: "List of options", text: "Text", number: "Number", date: "Date", checkbox: "Yes / No"
  };

  function openAddColumn(tab, anchor) {
    var hidden = customDefs(tab, true);
    var html = '<div class="stf-pop__title">New column</div>' +
      '<label class="stf-pop__lbl">Name<input type="text" class="stf-pop__search" data-new-label ' +
        'placeholder="e.g. Laptop" maxlength="80"></label>' +
      '<label class="stf-pop__lbl">Type<select class="stf-pop__search" data-new-type>' +
        Object.keys(TYPE_LABELS).map(function (k) {
          return '<option value="' + k + '">' + esc(TYPE_LABELS[k]) + "</option>";
        }).join("") + "</select></label>" +
      '<label class="stf-pop__lbl" data-new-options-wrap>Options <em>(one per line)</em>' +
        '<textarea class="stf-pop__search stf-pop__textarea" data-new-options ' +
        'placeholder="Mac&#10;Windows"></textarea></label>' +
      '<div class="stf-pop__msg" data-msg></div>' +
      '<div class="stf-pop__foot"><span></span>' +
        '<button type="button" class="stf-pop__apply" data-create>Create column</button></div>';
    if (hidden.length) {
      html += '<div class="stf-pop__title stf-pop__title--sub">Hidden columns</div>' +
        hidden.map(function (c) {
          return '<div class="stf-pop__row"><span>' + esc(c.label) + ' <em>' + esc(TYPE_LABELS[c.type] || c.type) +
            '</em></span><span><button type="button" class="stf-pop__link" data-restore="' + c.id + '">Show</button>' +
            '<button type="button" class="stf-pop__link is-danger" data-purge="' + c.id + '">Delete</button></span></div>';
        }).join("");
    }
    var panel = openPanel("stf-pop--form", anchor, html, 280);

    var label = panel.querySelector("[data-new-label]");
    var type = panel.querySelector("[data-new-type]");
    var optWrap = panel.querySelector("[data-new-options-wrap]");
    var msg = panel.querySelector("[data-msg]");
    label.focus();
    type.addEventListener("change", function () {
      optWrap.style.display = type.value === "select" ? "" : "none";
    });
    var create = panel.querySelector("[data-create]");
    function submit() {
      var name = label.value.trim();
      if (!name) { msg.textContent = "Give the column a name."; label.focus(); return; }
      var used = [];
      var options = type.value !== "select" ? [] :
        panel.querySelector("[data-new-options]").value.split("\n")
          .map(function (v) { return v.trim(); }).filter(Boolean)
          .map(function (v) {
            var opt = { value: v, color: nextColor(used) };
            used.push(opt);
            return opt;
          });
      create.disabled = true;
      msg.textContent = "Creating…";
      api("/staffing/columns", {
        method: "POST",
        body: JSON.stringify({ tab: tab, label: name, type: type.value, options: options })
      }).then(function () {
        closePopover();
        return refreshSchema(tab);
      }).catch(function (err) {
        create.disabled = false;
        msg.textContent = err.message;
      });
    }
    create.addEventListener("click", submit);
    label.addEventListener("keydown", function (e) { if (e.key === "Enter") submit(); });
    panel.querySelectorAll("[data-purge]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var def = hidden.filter(function (c) { return String(c.id) === btn.dataset.purge; })[0];
        if (def) deleteColumn(tab, def);
      });
    });
    panel.querySelectorAll("[data-restore]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        btn.disabled = true;
        api("/staffing/columns/" + btn.dataset.restore, {
          method: "PATCH", body: JSON.stringify({ archived: false })
        }).then(function () {
          closePopover();
          return refreshSchema(tab);
        }).catch(function (err) { btn.disabled = false; alert(err.message); });
      });
    });
  }

  // Cuántas filas cargadas tienen algo en esa columna/opción: va en el confirm,
  // para que "eliminar" diga qué se pierde. Si la pestaña no está cargada, null.
  function countRows(tab, test) {
    if (!state.loaded[tab]) return null;
    return rowsOf(tab).filter(test).length;
  }

  function rowsPhrase(n) {
    if (n === null) return "the rows that have it";
    return n === 1 ? "1 row" : n + " rows";
  }

  function deleteColumn(tab, def) {
    var n = countRows(tab, function (r) {
      var v = customValue(r, def.key);
      return v !== undefined && v !== null && v !== "";
    });
    var lost = n === 0 ? "No row has a value in it yet. "
      : "This also deletes its value on " + rowsPhrase(n) + ". ";
    if (!confirm('Delete the column "' + def.label + '" for good?\n\n' + lost +
                 "This cannot be undone. If you only want it out of sight, use Hide instead.")) return;
    closePopover();
    delete state.filters[tab][def.key];
    if (state.sort[tab] && state.sort[tab].key === def.key) state.sort[tab] = null;
    api("/staffing/columns/" + def.id + "?hard=1", { method: "DELETE" })
      .then(function () { return refreshSchema(tab, true); })
      .catch(function (err) { alert("Could not delete the column: " + err.message); });
  }

  function renameColumn(tab, col) {
    var name = prompt("New name for the column:", col.label);
    if (name == null) return;
    name = name.trim();
    if (!name || name === col.label) return;
    closePopover();
    api("/staffing/columns/" + col.custom.id, { method: "PATCH", body: JSON.stringify({ label: name }) })
      .then(function () { return refreshSchema(tab); })
      .catch(function (err) { alert("Could not rename: " + err.message); });
  }

  function hideColumn(tab, col) {
    if (!confirm('Hide the column "' + col.label + '"? The values are kept, and you can ' +
                 'show it again from the + at the end of the table.')) return;
    closePopover();
    // Un filtro u orden sobre una columna que ya no está dejaría filas escondidas
    // sin forma de sacarlo.
    delete state.filters[tab][col.key];
    if (state.sort[tab] && state.sort[tab].key === col.key) state.sort[tab] = null;
    api("/staffing/columns/" + col.custom.id, { method: "DELETE" })
      .then(function () { return refreshSchema(tab); })
      .catch(function (err) { alert("Could not hide the column: " + err.message); });
  }

  function swatches(current) {
    return '<div class="stf-swatches">' + COLORS.map(function (c) {
      return '<button type="button" class="stf-swatch stf-badge--c-' + c + (c === current ? " is-active" : "") +
        '" data-color="' + c + '" title="' + c + '"></button>';
    }).join("") + "</div>";
  }

  // Editor del catálogo de una columna de lista: agregar, renombrar, recolorear,
  // ocultar. Cada cambio se guarda al toque y el editor se vuelve a dibujar.
  function openOptionsEditor(tab, col, anchor) {
    var otab = optionsTab(tab, col);
    var key = col.key;
    var spot = anchorSpot(anchor);

    function draw(message) {
      var list = optionsOf(otab, key);
      var html = '<div class="stf-pop__title">' + esc(col.label) + " · options</div>" +
        '<div class="stf-opts">' + list.map(function (o) {
          var lockTitle = "Used by the totals at the top of the page: it can be recolored, not renamed, hidden or deleted.";
          return '<div class="stf-opt" data-id="' + esc(o.id || "") + '">' +
            '<button type="button" class="stf-opt__color stf-badge--c-' + esc(o.color) + '" data-pick title="Change color"></button>' +
            '<input type="text" class="stf-opt__value" value="' + esc(o.value) + '" maxlength="80"' +
              (o.locked ? ' readonly title="' + lockTitle + '"' : "") + ">" +
            (o.locked
              ? '<span class="stf-opt__lock" title="' + lockTitle + '"><i class="fa-solid fa-lock"></i></span>'
              : '<button type="button" class="stf-opt__del" data-hide title="Hide (rows keep the value)"><i class="fa-regular fa-eye-slash"></i></button>' +
                '<button type="button" class="stf-opt__del is-danger" data-purge title="Delete (clears it from the rows)"><i class="fa-regular fa-trash-can"></i></button>') +
            "</div>";
        }).join("") + "</div>" +
        '<div class="stf-opt stf-opt--new">' +
          '<input type="text" class="stf-opt__value" data-add-value placeholder="New option…" maxlength="80">' +
          '<button type="button" class="stf-pop__link" data-add>Add</button></div>' +
        '<div class="stf-pop__msg" data-msg>' + esc(message || "") + "</div>" +
        '<div class="stf-pop__hint">Renaming also updates the rows that use it. ' +
        '<i class="fa-regular fa-eye-slash"></i> Hide keeps the value on those rows; ' +
        '<i class="fa-regular fa-trash-can"></i> Delete clears it.</div>';
      var panel = openPanel("stf-pop--form stf-pop--opts", spot, html, 300);
      bind(panel, list);
    }

    // Los guardados son asíncronos: si mientras tanto se cerró el editor (click
    // afuera, Esc), no se lo vuelve a abrir solo.
    function redraw(message) {
      if (pop && pop.classList.contains("stf-pop--opts")) draw(message);
    }

    function fail(err) { redraw(err.message); }

    function bind(panel, list) {
      if (!schema.ready) {
        panel.querySelector("[data-msg]").textContent =
          "Could not load the options from the server, so they cannot be edited right now.";
        panel.querySelectorAll("input, button").forEach(function (el) { el.disabled = true; });
        return;
      }
      panel.querySelectorAll(".stf-opt[data-id]").forEach(function (rowEl, i) {
        var opt = list[i];
        var input = rowEl.querySelector(".stf-opt__value");
        function rename() {
          var value = input.value.trim();
          if (!value || value === opt.value || opt.locked) { input.value = opt.value; return; }
          api("/staffing/options/" + opt.id, { method: "PATCH", body: JSON.stringify({ value: value }) })
            .then(function (res) {
              return refreshSchema(otab, res.renamed_rows > 0).then(function () {
                redraw(res.renamed_rows ? res.renamed_rows + " rows updated." : "");
              });
            })
            .catch(fail);
        }
        input.addEventListener("keydown", function (e) {
          if (e.key === "Enter") { e.preventDefault(); input.blur(); }
          if (e.key === "Escape") { e.stopPropagation(); input.value = opt.value; input.blur(); }
        });
        input.addEventListener("blur", rename);
        rowEl.querySelector("[data-pick]").addEventListener("click", function () {
          var open = rowEl.nextElementSibling && rowEl.nextElementSibling.classList.contains("stf-swatches");
          panel.querySelectorAll(".stf-opts > .stf-swatches").forEach(function (el) { el.remove(); });
          if (open) return;
          rowEl.insertAdjacentHTML("afterend", swatches(opt.color));
          rowEl.nextElementSibling.querySelectorAll("[data-color]").forEach(function (sw) {
            sw.addEventListener("click", function () {
              api("/staffing/options/" + opt.id, {
                method: "PATCH", body: JSON.stringify({ color: sw.dataset.color })
              }).then(function () { return refreshSchema(otab); }).then(function () { redraw(); }).catch(fail);
            });
          });
        });
        var hide = rowEl.querySelector("[data-hide]");
        if (hide) {
          hide.addEventListener("click", function () {
            api("/staffing/options/" + opt.id, { method: "DELETE" })
              .then(function () { return refreshSchema(otab); }).then(function () { redraw(); }).catch(fail);
          });
        }
        var purge = rowEl.querySelector("[data-purge]");
        if (purge) {
          purge.addEventListener("click", function () {
            var n = countRows(otab, function (r) {
              var v = col.custom ? customValue(r, key) : r[cellField(col)];
              return v != null && String(v).trim().toLowerCase() === opt.value.toLowerCase();
            });
            var lost = n === 0 ? "No row uses it. "
              : (n === null ? "The rows that use it" : rowsPhrase(n)) + " will be left empty. ";
            if (!confirm('Delete the option "' + opt.value + '" for good?\n\n' + lost +
                         "This cannot be undone.")) return;
            api("/staffing/options/" + opt.id + "?hard=1", { method: "DELETE" })
              .then(function (res) {
                return refreshSchema(otab, res.cleared_rows > 0).then(function () {
                  redraw(res.cleared_rows ? rowsPhrase(res.cleared_rows) + " cleared." : "");
                });
              })
              .catch(fail);
          });
        }
      });
      var addInput = panel.querySelector("[data-add-value]");
      function add() {
        var value = addInput.value.trim();
        if (!value) { addInput.focus(); return; }
        api("/staffing/options", {
          method: "POST",
          body: JSON.stringify({ tab: otab, col_key: key, value: value, color: nextColor(list) })
        }).then(function () { return refreshSchema(otab); }).then(function () {
          redraw();
          var again = pop && pop.querySelector("[data-add-value]");
          if (again) again.focus();
        }).catch(fail);
      }
      panel.querySelector("[data-add]").addEventListener("click", add);
      addInput.addEventListener("keydown", function (e) { if (e.key === "Enter") add(); });
    }

    draw();
  }

  /* ---------- Edición en la celda ---------- */
  function isCellEditable(tab, col, row) {
    if (!col.editable || row.orphan) return false;
    if (tab === "bonos" && !row.bonus_id) return false;
    return !col.canEdit || col.canEdit(row);
  }

  function cellField(col) { return col.field || col.key; }

  function currentCell(row, col) {
    return col.custom ? customValue(row, col.key) : row[cellField(col)];
  }

  function setCell(row, col, value) {
    if (col.custom) {
      row.custom = Object.assign({}, row.custom || {});
      if (value === null || value === undefined || value === "") delete row.custom[col.key];
      else row.custom[col.key] = value;
    } else {
      row[cellField(col)] = value === "" ? null : value;
    }
  }

  // Optimista, como togglePayment(): se pinta enseguida y sólo se revierte si falla.
  function saveCell(tab, row, col, value) {
    if (col.custom && col.custom.type === "number" && value !== null && value !== "") {
      value = Number(value);
    }
    var previous = currentCell(row, col);
    setCell(row, col, value);
    closePopover();
    renderTab(tab);

    var body = {};
    if (col.custom) {
      body.custom = {};
      body.custom[col.key] = value === "" ? null : value;
    } else {
      body[cellField(col)] = value === "" ? null : value;
    }
    var req;
    if (tab === "bonos") {
      req = api("/staffing/bonuses/" + row.bonus_id, { method: "PATCH", body: JSON.stringify(body) });
    } else {
      body.candidate_id = row.candidate_id;
      body.account_id = row.account_id;
      req = api("/staffing/extra", { method: "PATCH", body: JSON.stringify(body) });
    }
    return req.then(function () {
      // Exit type vacío vuelve al valor derivado del motivo de baja, que calcula el server.
      if (col.key === "exit_type" && !value) {
        state.loaded.churn = false;
        loadTab("churn", true);
      }
    }).catch(function (err) {
      setCell(row, col, previous);
      renderTab(tab);
      alert("Could not save " + col.label + ": " + err.message);
    });
  }

  function openCellEditor(tab, row, col, td) {
    if (!row || !col) return;
    var wasOpen = pop && pop.dataset.cellFor === col.key + ":" + td.closest("tr").dataset.row;
    closePopover();
    if (wasOpen) return;

    var kind = col.editable;
    var current = currentCell(row, col);
    var panel;

    if (kind === "select") {
      var otab = optionsTab(tab, col);
      var list = optionsOf(otab, col.key);
      var html = '<div class="stf-pop__list stf-pop__list--pick">' +
        list.map(function (o) {
          var active = current != null && String(current).toLowerCase() === o.value.toLowerCase();
          return '<button type="button" class="stf-pick' + (active ? " is-active" : "") +
            '" data-value="' + esc(o.value) + '">' + colorBadge(o.color, o.value) + "</button>";
        }).join("") + "</div>" +
        (current ? '<button type="button" class="stf-pick stf-pick--clear" data-value="">Clear</button>' : "") +
        (schema.ready
          ? '<div class="stf-opt stf-opt--new"><input type="text" class="stf-opt__value" data-add-value ' +
            'placeholder="Add option…" maxlength="80"><button type="button" class="stf-pop__link" data-add>Add</button></div>'
          : "") +
        '<div class="stf-pop__msg" data-msg></div>';
      panel = openPanel("stf-pop--cell", td, html, 220);
      panel.querySelectorAll("[data-value]").forEach(function (btn) {
        btn.addEventListener("click", function () { saveCell(tab, row, col, btn.dataset.value || null); });
      });
      var addInput = panel.querySelector("[data-add-value]");
      if (addInput) {
        var add = function () {
          var value = addInput.value.trim();
          if (!value) return;
          var existing = findOption(otab, col.key, value);
          if (existing) { saveCell(tab, row, col, existing.value); return; }
          api("/staffing/options", {
            method: "POST",
            body: JSON.stringify({ tab: otab, col_key: col.key, value: value, color: nextColor(list) })
          }).then(function (res) {
            return loadSchema().then(function () { saveCell(tab, row, col, res.option.value); });
          }).catch(function (err) { panel.querySelector("[data-msg]").textContent = err.message; });
        };
        panel.querySelector("[data-add]").addEventListener("click", add);
        addInput.addEventListener("keydown", function (e) { if (e.key === "Enter") add(); });
      }
    } else {
      var inputType = kind === "number" ? "number" : (kind === "date" ? "date" : "text");
      var value = current == null ? "" : String(current).slice(0, inputType === "date" ? 10 : undefined);
      panel = openPanel("stf-pop--cell", td,
        '<input type="' + inputType + '" class="stf-pop__search" data-cell-input' +
          (inputType === "number" ? ' step="any"' : "") + ' value="' + esc(value) + '">' +
        '<div class="stf-pop__foot"><button type="button" data-clear>Clear</button>' +
          '<button type="button" class="stf-pop__apply" data-save>Save</button></div>', 240);
      var input = panel.querySelector("[data-cell-input]");
      input.focus();
      if (input.select && inputType !== "date") input.select();
      var commit = function (v) {
        if (String(v) === String(current == null ? "" : current)) { closePopover(); return; }
        saveCell(tab, row, col, v === "" ? null : v);
      };
      panel.querySelector("[data-save]").addEventListener("click", function () { commit(input.value.trim()); });
      panel.querySelector("[data-clear]").addEventListener("click", function () { commit(""); });
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter") commit(input.value.trim());
      });
    }
    pop.dataset.cellFor = col.key + ":" + td.closest("tr").dataset.row;
  }

  document.addEventListener("click", closePopover);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closePopover(); });
  window.addEventListener("resize", closePopover);

  /* =====================================================================
     Payments: 1x1 y masivo
     ===================================================================== */
  // Optimista: se actualiza la fila en memoria y sólo se revierte si falla, así
  // no se recarga la tabla y no se pierden el scroll ni los filtros.
  function togglePayment(row, cb) {
    var value = cb.checked;
    row.payment = value;
    cb.disabled = true;
    api("/staffing/extra", {
      method: "PATCH",
      body: JSON.stringify({ candidate_id: row.candidate_id, account_id: row.account_id, payment: value })
    }).then(function () {
      // Si hay un filtro activo en Payments, la fila puede tener que salir de la vista.
      if (state.filters.database.payment) renderDatabase();
    }).catch(function (err) {
      row.payment = !value;
      cb.checked = !value;
      alert("Could not save Payments: " + err.message);
    }).then(function () {
      cb.disabled = false;
    });
  }

  // Check all / Uncheck all: aplica sólo a las filas visibles, o sea que respeta
  // el buscador y los filtros de columna.
  function bulkPayment(value) {
    var rows = visibleRows("database").filter(function (r) {
      return !r.orphan && !!r.payment !== value;
    });
    if (!rows.length) {
      alert(value ? "Every visible contractor is already checked." : "No visible contractor is checked.");
      return;
    }
    var msg = value
      ? "Mark " + rows.length + " visible contractors as paid?"
      : "Uncheck Payments for " + rows.length + " visible contractors?";
    if (!confirm(msg)) return;
    api("/staffing/extra/payment", {
      method: "PATCH",
      body: JSON.stringify({
        payment: value,
        pairs: rows.map(function (r) { return { candidate_id: r.candidate_id, account_id: r.account_id }; })
      })
    }).then(function () {
      rows.forEach(function (r) { r.payment = value; });
      renderDatabase();
    }).catch(function (err) {
      alert("Could not save Payments: " + err.message);
    });
  }

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

  // Desplegable de una columna de lista con su catálogo. Siempre incluye el valor
  // actual aunque esté fuera del catálogo (ver withCurrent).
  function catalogField(tab, key, label, current) {
    return selectField(label, key, [""].concat(withCurrent(optionValues(tab, key), current)), current);
  }

  // Un input por columna custom de la pestaña. Van con `data-custom` y no con
  // `data-edit`: collectEdits() los junta aparte en `custom`.
  function customFields(tab, row) {
    var defs = customDefs(tab);
    if (!defs.length) return "";
    return '<div class="stf-section-label">Custom columns</div>' + defs.map(function (def) {
      var v = customValue(row, def.key);
      var attr = ' data-custom="' + esc(def.key) + '"';
      if (def.type === "select") {
        var values = [""].concat(withCurrent(optionValues(def.tab, def.key), v));
        return field(def.label, '<select' + attr + ">" + values.map(function (o) {
          return '<option value="' + esc(o) + '"' + (String(v == null ? "" : v) === o ? " selected" : "") +
            ">" + esc(o || "—") + "</option>";
        }).join("") + "</select>");
      }
      if (def.type === "checkbox") {
        var cur = v === true ? "Yes" : (v === false ? "No" : "");
        return field(def.label, '<select' + attr + ">" + ["", "Yes", "No"].map(function (o) {
          return '<option value="' + o + '"' + (cur === o ? " selected" : "") + ">" + (o || "—") + "</option>";
        }).join("") + "</select>");
      }
      var type = def.type === "number" ? "number" : (def.type === "date" ? "date" : "text");
      var shown = v == null ? "" : String(v).slice(0, type === "date" ? 10 : undefined);
      return field(def.label, '<input type="' + type + '"' + (type === "number" ? ' step="any"' : "") +
        attr + ' value="' + esc(shown) + '">');
    }).join("");
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
    drawer.save.disabled = false;

    drawer.body.innerHTML =
      '<div class="stf-section-label">Filled in by hand</div>' +
      catalogField("database", "platform", "Platform", row.platform) +
      catalogField("database", "performance", "Performance", row.performance) +
      catalogField("database", "provider", "Provider", row.provider) +
      field("Payments", '<label class="stf-pay-field"><input type="checkbox" data-edit-check="payment"' +
        (row.payment ? " checked" : "") + "> Paid</label>") +
      field("Comments", '<textarea data-edit="notes">' + esc(row.notes || "") + "</textarea>") +
      customFields("database", row) +
      '<div class="stf-section-label">From the Hub</div>' +
      readonlyList([
        ["Status", statusBadge(row.status), true],
        ["Mail", row.mail],
        ["Country", row.country],
        ["Recruiter", personName(row.recruiter), true],
        ["Start", fmtDate(row.start_date)],
        ["End", fmtDate(row.end_date)],
        ["Churn date", fmtDate(row.churn_date)],
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
    drawer.save.disabled = false;

    var overrideRaw = row.churn_m3_override;
    drawer.body.innerHTML =
      '<div class="stf-section-label">Filled in by hand</div>' +
      catalogField("churn", "exit_type", "Exit type", row.exit_type) +
      selectField("Churn M3", "churn_m3_override", [
        { value: "", label: "Automatic" },
        { value: "si", label: "Yes" },
        { value: "no", label: "No" }
      ], overrideRaw === true ? "si" : (overrideRaw === false ? "no" : "")) +
      field("Comments", '<textarea data-edit="notes">' + esc(row.notes || "") + "</textarea>") +
      customFields("churn", row) +
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

  // Los contractors que pueden recibir un bono son los vigentes de la pestaña
  // Database: mismo criterio que `renderDatabaseKpis` (Active + Onboarding), o sea
  // el que ya firmó aunque todavía no haya arrancado.
  //
  // Cada opción lleva pegado el par (candidate_id, account_id) y no sólo el nombre:
  // `bonus_requests.account_id` es NOT NULL, y el cliente lo decide el hire, no la
  // persona — alguien puede estar en dos cuentas y son dos bonos distintos.
  // Las filas huérfanas quedan afuera a propósito: no tienen ids, que es justo lo
  // que hace falta.
  function bonusCandidateOptions() {
    return state.database
      .filter(function (r) {
        return !r.orphan && r.candidate_id && r.account_id &&
               (r.status === "Active" || r.status === "Onboarding");
      })
      .sort(function (a, b) {
        return String(a.candidate_name || "").toLowerCase()
          .localeCompare(String(b.candidate_name || "").toLowerCase());
      })
      .map(function (r) {
        var label = r.candidate_name || "Candidate #" + r.candidate_id;
        if (r.client_name) label += " — " + r.client_name;
        if (r.status === "Onboarding") label += " (Onboarding)";
        return { value: r.candidate_id + ":" + r.account_id, label: label };
      });
  }

  function openBonoDrawer(row) {
    state.editing = { kind: "bono", row: row };
    drawer.eyebrow.textContent = row.bonus_id ? "Bonus" : "New bonus";
    drawer.title.textContent = row.candidate_name || "New bonus";
    drawer.sub.textContent = row.client_name || "";
    drawer.save.style.display = "";
    drawer.save.disabled = false;

    // El candidato sólo se elige al crear: cambiárselo a un bono ya cargado movería
    // la plata de cuenta, y el PATCH no acepta esas columnas. En uno existente se
    // muestra de quién es, nada más.
    var candidateBlock = row.bonus_id
      ? readonlyList([["Candidate", row.candidate_name], ["Client", row.client_name]])
      : '<div id="stfBonusCandidate">' + bonusCandidateField() + "</div>";

    drawer.body.innerHTML =
      candidateBlock +
      field("Amount (USD)", '<input type="number" step="0.01" data-edit="amount" value="' + esc(row.amount || "") + '">') +
      field("Date *", '<input type="date" required data-edit="payout_date" value="' + esc((row.payout_date || "").slice(0, 10)) + '">') +
      field("Concept", '<input type="text" data-edit="reason" value="' + esc(row.reason || "") + '">') +
      catalogField("bonos", "invoice_status", "Invoice (client)", row.invoice_status) +
      catalogField("bonos", "candidate_status", "Paid to candidate", row.candidate_status) +
      field("Comments", '<textarea data-edit="notes">' + esc(row.notes || "") + "</textarea>") +
      customFields("bonos", row);

    bindBonusCandidatePicker();

    // El fetch de /staffing/database sale en el init, pero con el backend frío puede
    // tardar: si todavía no volvió se repinta sólo ese bloque cuando llega, para no
    // perder lo que ya se haya tipeado en el resto del formulario.
    if (!row.bonus_id && !state.loaded.database) {
      loadTab("database").then(function () {
        var host = drawer.body.querySelector("#stfBonusCandidate");
        if (!host) return;
        host.innerHTML = bonusCandidateField();
        bindBonusCandidatePicker();
      });
    }

    openDrawer();
  }

  // El campo Candidate de un bono nuevo, en sus tres estados. Deshabilita el Save
  // mientras no haya de dónde elegir: volver al texto libre es exactamente el bug
  // que hacía que ningún bono se pudiera guardar.
  function bonusCandidateField() {
    if (!state.loaded.database) {
      drawer.save.disabled = true;
      return field("Candidate", '<div class="stf-empty">Loading contractors…</div>');
    }
    var options = bonusCandidateOptions();
    drawer.save.disabled = !options.length;
    if (!options.length) {
      return field("Candidate", '<div class="stf-empty">Could not load the contractor ' +
        "list. Reload the page and try again.</div>");
    }
    return selectField("Candidate", "candidate_ref",
      [{ value: "", label: "Select a candidate…" }].concat(options), "");
  }

  // El encabezado del drawer arranca en "New bonus"; una vez elegido el candidato
  // dice de quién es el bono, igual que cuando se abre uno existente.
  function bindBonusCandidatePicker() {
    var picker = drawer.body.querySelector('[data-edit="candidate_ref"]');
    if (!picker) return;
    picker.addEventListener("change", function () {
      var parts = bonusCandidateLabel(picker);
      drawer.title.textContent = parts.name || "New bonus";
      drawer.sub.textContent = parts.client || "";
    });
  }

  // Deshace el label de la opción elegida. El nombre se sigue mandando al backend
  // como `employee_name_manual`: es el respaldo del COALESCE con el que la tabla
  // muestra el bono si el candidato se borrara de `candidates`.
  function bonusCandidateLabel(select) {
    var text = select && select.selectedIndex > 0
      ? select.options[select.selectedIndex].text : "";
    text = text.replace(/ \(Onboarding\)$/, "");
    var cut = text.indexOf(" — ");
    if (cut === -1) return { name: text, client: "" };
    return { name: text.slice(0, cut), client: text.slice(cut + 3) };
  }

  function collectEdits() {
    var out = {};
    drawer.body.querySelectorAll("[data-edit]").forEach(function (el) {
      out[el.dataset.edit] = el.value.trim();
    });
    drawer.body.querySelectorAll("[data-edit-check]").forEach(function (el) {
      out[el.dataset.editCheck] = el.checked;
    });
    var custom = null;
    drawer.body.querySelectorAll("[data-custom]").forEach(function (el) {
      custom = custom || {};
      custom[el.dataset.custom] = el.value.trim() || null;
    });
    if (custom) out.custom = custom;
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
      // Se valida en el orden en que están los campos: primero el candidato, que es
      // el de arriba de todo, y recién después la fecha.
      //
      // `account_id` es NOT NULL en bonus_requests y el backend rechaza el POST sin
      // él; por eso el par viaja junto en el value de la opción, para que no haya
      // forma de mandar uno sin el otro.
      var ref = [];
      if (!row.bonus_id) {
        ref = String(edits.candidate_ref || "").split(":");
        if (ref.length !== 2 || !ref[0] || !ref[1]) {
          drawer.save.disabled = false;
          drawer.status.textContent = "Pick a candidate from the list.";
          return;
        }
      }
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
      if (edits.custom) payload.custom = edits.custom;
      if (row.bonus_id) {
        request = api("/staffing/bonuses/" + row.bonus_id,
          { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        var who = bonusCandidateLabel(drawer.body.querySelector('[data-edit="candidate_ref"]'));
        request = api("/staffing/bonuses", {
          method: "POST",
          body: JSON.stringify(Object.assign(payload, {
            candidate_id: ref[0],
            account_id: ref[1],
            candidate_name: who.name
          }))
        });
      }
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
        payment: !!edits.payment,
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
      if (edits.custom) body.custom = edits.custom;
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

    $$("[data-bulk-pay]").forEach(function (btn) {
      btn.addEventListener("click", function () { bulkPayment(btn.dataset.bulkPay === "on"); });
    });

    // El botón de "nuevo bono" vive en los filtros de su pestaña.
    var bonosFilters = document.querySelector('[data-panel="bonos"] .stf-filters');
    var newBonus = document.createElement("button");
    newBonus.type = "button";
    newBonus.className = "stf-btn stf-btn--primary";
    newBonus.innerHTML = '<i class="fa-solid fa-plus"></i> New bonus';
    newBonus.addEventListener("click", function () { openBonoDrawer({}); });
    bonosFilters.appendChild(newBonus);

    // El "+" del encabezado queda en la punta derecha de una tabla ancha: este
    // botón hace lo mismo sin tener que scrollear hasta el final.
    $$(".stf-filters").forEach(function (bar) {
      var tab = bar.closest("[data-panel]").dataset.panel;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "stf-btn";
      btn.innerHTML = '<i class="fa-solid fa-table-columns"></i> Add column';
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        openAddColumn(tab, btn);
      });
      bar.insertBefore(btn, bar.querySelector(".stf-filters__spacer"));
    });

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
    // El catálogo va primero: sin él las columnas custom no tendrían dónde dibujarse.
    loadSchema().then(function () { loadTab("database"); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
