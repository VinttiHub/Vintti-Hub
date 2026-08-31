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

  // El backend cae al email del hr_lead cuando no encuentra el nombre en `users`.
  function personName(value) {
    if (!value) return "—";
    if (value.indexOf("@") === -1) return esc(value);
    return esc(value.split("@")[0].split(/[._-]/).filter(Boolean).map(function (part) {
      return part.charAt(0).toUpperCase() + part.slice(1);
    }).join(" "));
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
    editing: null
  };

  var $ = function (sel) { return document.querySelector(sel); };
  var $$ = function (sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); };

  function filterValue(name) {
    var el = document.querySelector('[data-filter="' + name + '"]');
    return el ? el.value.trim() : "";
  }

  // `fallback` es el valor que queda elegido la primera vez que se llena el select.
  function fillSelect(name, values, fallback) {
    var el = document.querySelector('[data-filter="' + name + '"]');
    if (!el || el.dataset.filled === "1") return;
    var current = el.value;
    var first = el.querySelector("option");
    var html = first ? first.outerHTML : "";
    values.filter(Boolean).sort().forEach(function (value) {
      html += '<option value="' + esc(value) + '">' + esc(value) + "</option>";
    });
    el.innerHTML = html;
    // `current` es el primer <option> que el navegador auto-selecciona ("All"), no
    // una elección del usuario: fillSelect corre una sola vez, antes de que nadie
    // toque nada. Por eso el fallback tiene prioridad cuando existe entre los valores.
    el.value = (fallback && values.indexOf(fallback) > -1) ? fallback : (current || fallback || "");
    el.dataset.filled = "1";
  }

  function uniq(rows, key) {
    var seen = {};
    rows.forEach(function (row) { if (row[key]) seen[row[key]] = true; });
    return Object.keys(seen);
  }

  /* =====================================================================
     Staffing Database
     ===================================================================== */
  function statusDot(status) {
    var cls = status === "Active" ? "active" : (status === "Onboarding" ? "onboarding" : "inactive");
    return '<span class="stf-dot stf-dot--' + cls + '"></span>';
  }

  function filterDatabase() {
    var status = filterValue("db-status");
    var client = filterValue("db-client").toLowerCase();
    var country = filterValue("db-country");
    var recruiter = filterValue("db-recruiter");
    var platform = filterValue("db-platform");
    var search = filterValue("db-search").toLowerCase();

    return state.database.filter(function (row) {
      // "vigentes" = lo que la card Activos cuenta y lo que reconcilia con el GMRR
      // del dashboard: los que ya trabajan MÁS los que firmaron y todavía no
      // arrancaron. El valor "Active" a secas deja afuera a los onboarding.
      if (status === "vigentes") {
        if (row.status !== "Active" && row.status !== "Onboarding") return false;
      } else if (status && row.status !== status) return false;
      if (client && String(row.client_name || "").toLowerCase().indexOf(client) === -1) return false;
      if (country && row.country !== country) return false;
      if (recruiter && row.recruiter !== recruiter) return false;
      if (platform && row.platform !== platform) return false;
      if (search) {
        var haystack = (row.candidate_name + " " + (row.mail || "")).toLowerCase();
        if (haystack.indexOf(search) === -1) return false;
      }
      return true;
    });
  }

  function renderDatabase() {
    var rows = filterDatabase();
    var host = $("#stfTableDatabase");
    $("#stfCountDatabase").textContent = rows.length + " of " + state.database.length + " contractors";

    renderDatabaseKpis(rows);

    if (!rows.length) {
      host.innerHTML = '<div class="stf-empty">No contractors match these filters.</div>';
      return;
    }

    var totals = { salary: 0, fee: 0, payment: 0 };
    var body = rows.map(function (row, index) {
      // Misma población que las cards: vigentes = trabajando + onboarding.
      if (row.status === "Active" || row.status === "Onboarding") {
        totals.salary += Number(row.salary || 0);
        totals.fee += Number(row.fee || 0);
        totals.payment += Number(row.client_payment || 0);
      }
      var orphan = row.orphan
        ? ' <span class="stf-badge stf-badge--ghost">Sheet only</span>' : "";
      return '<tr data-row="' + index + '">' +
        '<td class="stf-td-name">' +
          '<div class="stf-td-name__primary">' + statusDot(row.status) + esc(row.candidate_name) + orphan +
            (row.notes ? '<span class="stf-note-dot" title="' + esc(row.notes) + '"></span>' : "") +
          "</div>" +
          '<div class="stf-td-name__sub">' + esc(row.client_name || "—") +
            (row.country ? " · " + esc(row.country) : "") + "</div>" +
        "</td>" +
        "<td>" + statusBadge(row.status) + "</td>" +
        '<td class="stf-td--muted">' + fmtDate(row.start_date) + "</td>" +
        '<td class="stf-td--muted">' + fmtDate(row.end_date) + "</td>" +
        '<td><span class="stf-money">' + money(row.salary) + "</span></td>" +
        '<td><span class="stf-money stf-money--soft">' + money(row.fee) + "</span></td>" +
        '<td><span class="stf-money stf-money--solid">' + money(row.client_payment) + "</span></td>" +
        "<td>" + (row.platform ? '<span class="stf-badge stf-badge--info">' + esc(row.platform) + "</span>" : "—") + "</td>" +
        "<td>" + performanceBadge(row.performance) + "</td>" +
        '<td class="stf-td--muted">' + dash(row.equipment) + "</td>" +
        '<td class="stf-td--muted">' + dash(row.provider) + "</td>" +
        '<td class="stf-td--muted">' + personName(row.recruiter) + "</td>" +
      "</tr>";
    }).join("");

    host.innerHTML =
      '<div class="stf-scroll"><table class="stf-table">' +
      "<thead><tr>" +
        '<th class="stf-th-name">Contractor</th>' +
        "<th>Status</th><th>Start</th><th>End</th>" +
        "<th>Salary</th><th>Fee</th><th>Client payment</th>" +
        "<th>Platform</th><th>Performance</th><th>Equipment</th><th>Provider</th><th>Recruiter</th>" +
      "</tr></thead>" +
      "<tbody>" + body + "</tbody>" +
      "<tfoot><tr>" +
        '<td class="stf-td-name">Active total</td>' +
        "<td></td><td></td><td></td>" +
        "<td>" + money(totals.salary) + "</td>" +
        "<td>" + money(totals.fee) + "</td>" +
        "<td>" + money(totals.payment) + "</td>" +
        "<td></td><td></td><td></td><td></td><td></td>" +
      "</tr></tfoot>" +
      "</table></div>";

    host.querySelectorAll("tbody tr").forEach(function (tr) {
      tr.addEventListener("click", function () {
        openDatabaseDrawer(rows[Number(tr.dataset.row)]);
      });
    });
  }

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

  // "Activos" = los contratos vigentes, incluyendo a los que ya firmaron pero
  // todavía no arrancaron. Es el mismo total que el KPI "Candidatos activos" del
  // dashboard; si se contaran sólo los que ya están trabajando daría 7 menos y
  // parecería que faltan personas. El desglose queda en la card de Onboarding.
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
    var platformHint = Object.keys(byPlatform).filter(function (k) {
      return k !== "No platform";
    }).sort(function (a, b) {
      return byPlatform[b] - byPlatform[a];
    }).map(function (k) { return k + " " + byPlatform[k]; }).join(" · ");

    var payment = vigentes.reduce(function (acc, r) { return acc + Number(r.client_payment || 0); }, 0);
    var fee = vigentes.reduce(function (acc, r) { return acc + Number(r.fee || 0); }, 0);

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

  function kpi(label, value, hint, color) {
    return '<div class="stf-kpi stf-kpi--' + color + '">' +
      '<div class="stf-kpi__label">' + esc(label) + "</div>" +
      '<div class="stf-kpi__value">' + esc(value) + "</div>" +
      '<div class="stf-kpi__hint">' + esc(hint) + "</div>" +
    "</div>";
  }

  /* =====================================================================
     Churn
     ===================================================================== */
  function filterChurn() {
    var exit = filterValue("ch-exit");
    var reason = filterValue("ch-reason");
    var recruiter = filterValue("ch-recruiter");
    var m3 = filterValue("ch-m3");

    return state.churn.rows.filter(function (row) {
      if (exit && row.exit_type !== exit) return false;
      if (reason && (row.inactive_reason || "No reason") !== reason) return false;
      if (recruiter && row.recruiter !== recruiter) return false;
      if (m3 === "si" && !row.churn_m3) return false;
      if (m3 === "no" && row.churn_m3) return false;
      return true;
    });
  }

  function renderChurn() {
    var rows = filterChurn();
    var host = $("#stfTableChurn");
    $("#stfCountChurn").textContent = rows.length + " exits";

    renderChurnKpis(rows);

    if (!rows.length) {
      host.innerHTML = '<div class="stf-empty">No exits match these filters.</div>';
      return;
    }

    var body = rows.map(function (row, index) {
      var fault = row.vintti_fault === true
        ? '<span class="stf-badge stf-badge--bad">Yes</span>'
        : (row.vintti_fault === false ? '<span class="stf-badge">No</span>' : "—");
      var exitCls = row.exit_type === "Terminated" ? "stf-badge--bad" : "stf-badge--info";
      return '<tr data-row="' + index + '">' +
        '<td class="stf-td-name">' +
          '<div class="stf-td-name__primary"><span class="stf-dot stf-dot--inactive"></span>' + esc(row.candidate_name) +
            (row.notes ? '<span class="stf-note-dot" title="' + esc(row.notes) + '"></span>' : "") +
          "</div>" +
          '<div class="stf-td-name__sub">' + esc(row.client_name || "—") +
            (row.country ? " · " + esc(row.country) : "") + "</div>" +
        "</td>" +
        '<td class="stf-td--muted">' + fmtDate(row.end_date) + "</td>" +
        "<td>" + (row.exit_type ? '<span class="stf-badge ' + exitCls + '">' + esc(row.exit_type) + "</span>" : "—") + "</td>" +
        '<td class="stf-td--muted">' + dash(row.inactive_reason || "No reason") + "</td>" +
        "<td>" + fault + "</td>" +
        "<td>" + (row.churn_m3 ? '<span class="stf-badge stf-badge--warn">Yes</span>' : '<span class="stf-badge">No</span>') + "</td>" +
        '<td class="stf-td--muted">' + personName(row.recruiter) + "</td>" +
      "</tr>";
    }).join("");

    host.innerHTML =
      '<div class="stf-scroll"><table class="stf-table">' +
      "<thead><tr>" +
        '<th class="stf-th-name">Contractor</th>' +
        "<th>End</th><th>Exit type</th><th>Reason</th><th>Vintti's fault</th><th>Churn M3</th><th>Recruiter</th>" +
      "</tr></thead><tbody>" + body + "</tbody></table></div>";

    host.querySelectorAll("tbody tr").forEach(function (tr) {
      tr.addEventListener("click", function () {
        openChurnDrawer(rows[Number(tr.dataset.row)]);
      });
    });
  }

  function renderChurnKpis(rows) {
    var total = rows.length;
    var despidos = rows.filter(function (r) { return r.exit_type === "Terminated"; }).length;
    var renuncias = rows.filter(function (r) { return r.exit_type === "Resigned"; }).length;
    var fault = rows.filter(function (r) { return r.vintti_fault === true; }).length;
    var m3 = rows.filter(function (r) { return r.churn_m3; }).length;

    $("#stfKpisChurn").innerHTML = [
      kpi("Exits", total, "in the selected period", "mag"),
      kpi("Terminated", despidos, pct(despidos, total) + " of total", "mag"),
      kpi("Resigned", renuncias, pct(renuncias, total) + " of total", "cyan"),
      kpi("Vintti's fault", fault, pct(fault, total) + " of total", "violet"),
      kpi("Churn M3", m3, pct(m3, total) + " left within 3 months", "blue")
    ].join("");
  }

  /* =====================================================================
     Bonos
     ===================================================================== */
  function filterBonos() {
    var invoice = filterValue("bo-invoice");
    var candidateStatus = filterValue("bo-candidate");
    var search = filterValue("bo-search").toLowerCase();

    return state.bonos.rows.filter(function (row) {
      if (invoice && row.invoice_status !== invoice) return false;
      if (candidateStatus && row.candidate_status !== candidateStatus) return false;
      if (search) {
        var haystack = (row.candidate_name + " " + (row.client_name || "")).toLowerCase();
        if (haystack.indexOf(search) === -1) return false;
      }
      return true;
    });
  }

  // `reason` es el texto libre que describe el bono ("August Commission"); si está
  // vacío se cae a `bonus_type`, que es el enum de la tabla ("one_time").
  function bonusType(row) {
    if (row.reason) return esc(row.reason);
    if (!row.bonus_type) return "—";
    var text = row.bonus_type.replace(/_/g, " ");
    return esc(text.charAt(0).toUpperCase() + text.slice(1));
  }

  function payBadge(value) {
    if (!value) return "—";
    var paid = String(value).toLowerCase() === "paid";
    return '<span class="stf-badge ' + (paid ? "stf-badge--good" : "stf-badge--warn") + '">' + esc(value) + "</span>";
  }

  function renderBonos() {
    var rows = filterBonos();
    var host = $("#stfTableBonos");
    $("#stfCountBonos").textContent = rows.length + " bonuses";

    renderBonosKpis(rows);

    if (!rows.length) {
      host.innerHTML = '<div class="stf-empty">No bonuses match these filters.</div>';
      return;
    }

    var total = 0;
    var body = rows.map(function (row, index) {
      total += Number(row.amount || 0);
      return '<tr data-row="' + index + '">' +
        '<td class="stf-td-name">' +
          '<div class="stf-td-name__primary">' + esc(row.candidate_name || "—") +
            (row.notes ? '<span class="stf-note-dot" title="' + esc(row.notes) + '"></span>' : "") +
          "</div>" +
          '<div class="stf-td-name__sub">' + esc(row.client_name || "—") + "</div>" +
        "</td>" +
        '<td class="stf-td--muted">' + fmtDate(row.payout_date) + "</td>" +
        '<td><span class="stf-money stf-money--solid">' + money(row.amount) + "</span></td>" +
        '<td class="stf-td--muted">' + bonusType(row) + "</td>" +
        "<td>" + payBadge(row.invoice_status) + "</td>" +
        "<td>" + payBadge(row.candidate_status) + "</td>" +
      "</tr>";
    }).join("");

    host.innerHTML =
      '<div class="stf-scroll"><table class="stf-table">' +
      "<thead><tr>" +
        '<th class="stf-th-name">Candidate</th>' +
        "<th>Date</th><th>Amount</th><th>Concept</th><th>Invoice (client)</th><th>Paid to candidate</th>" +
      "</tr></thead><tbody>" + body + "</tbody>" +
      '<tfoot><tr><td class="stf-td-name">Total</td><td></td><td>' + money(total) +
      "</td><td></td><td></td><td></td></tr></tfoot></table></div>";

    host.querySelectorAll("tbody tr").forEach(function (tr) {
      tr.addEventListener("click", function () {
        openBonoDrawer(rows[Number(tr.dataset.row)]);
      });
    });
  }

  function renderBonosKpis(rows) {
    var sum = function (list) {
      return list.reduce(function (acc, r) { return acc + Number(r.amount || 0); }, 0);
    };
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

  function loadTab(tab, force) {
    if (state.loaded[tab] && !force) {
      renderTab(tab);
      return Promise.resolve();
    }

    if (tab === "database") {
      $("#stfTableDatabase").innerHTML = '<div class="stf-empty">Loading…</div>';
      return api("/staffing/database").then(function (rows) {
        state.database = rows;
        state.loaded.database = true;
        fillSelect("db-country", uniq(rows, "country"));
        fillSelect("db-recruiter", uniq(rows, "recruiter"));
        fillSelect("db-platform", uniq(rows, "platform"));
        var list = $("#stfClientOptions");
        list.innerHTML = uniq(rows, "client_name").sort().map(function (name) {
          return '<option value="' + esc(name) + '"></option>';
        }).join("");
        renderDatabase();
      }).catch(function (err) {
        showError("#stfTableDatabase", err.message);
      });
    }

    if (tab === "churn") {
      $("#stfTableChurn").innerHTML = '<div class="stf-empty">Loading…</div>';
      // Por defecto el año en curso. OJO: no se puede preguntar por el value del
      // select para saber si el usuario eligió algo — el navegador auto-selecciona
      // el primer <option> ("all"), que es truthy y se comía el default. La señal
      // real es `dataset.filled`, que fillSelect pone recién en la primera carga.
      var yearEl = document.querySelector('[data-filter="ch-year"]');
      var chosen = (yearEl && yearEl.dataset.filled === "1") ? yearEl.value : "";
      var year = chosen || CURRENT_YEAR;
      return api("/staffing/churn?year=" + encodeURIComponent(year)).then(function (data) {
        state.churn = data;
        state.loaded.churn = true;
        // `data.years` viene completo aunque el fetch esté filtrado: si este año
        // todavía no tuvo bajas, se cae al más reciente con un solo refetch.
        if (!chosen && data.years.length && data.years.indexOf(year) === -1) {
          fillSelect("ch-year", data.years, data.years[0]);
          if (yearEl) yearEl.value = data.years[0];
          state.loaded.churn = false;
          return loadTab("churn", true);
        }
        fillSelect("ch-year", data.years, CURRENT_YEAR);
        fillSelect("ch-recruiter", uniq(data.rows, "recruiter"));
        // "Sin razón" es un bucket grande (muchas bajas viejas no tienen motivo
        // cargado), así que tiene que poder filtrarse como cualquier otro.
        var reasons = uniq(data.rows, "inactive_reason");
        if (data.rows.some(function (r) { return !r.inactive_reason; })) reasons.push("No reason");
        fillSelect("ch-reason", reasons);
        renderChurn();
      }).catch(function (err) {
        showError("#stfTableChurn", err.message);
      });
    }

    $("#stfTableBonos").innerHTML = '<div class="stf-empty">Loading…</div>';
    var boYear = filterValue("bo-year") || "all";
    return api("/staffing/bonuses?year=" + encodeURIComponent(boYear)).then(function (data) {
      state.bonos = data;
      state.loaded.bonos = true;
      fillSelect("bo-year", data.years, "all");
      fillSelect("bo-invoice", uniq(data.rows, "invoice_status"));
      fillSelect("bo-candidate", uniq(data.rows, "candidate_status"));
      renderBonos();
    }).catch(function (err) {
      showError("#stfTableBonos", err.message);
    });
  }

  function renderTab(tab) {
    if (tab === "database") return renderDatabase();
    if (tab === "churn") return renderChurn();
    return renderBonos();
  }

  /* ---------- El filtro de año se resuelve en el server ---------- */
  function reloadYearScoped(tab) {
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

    $$("[data-drawer-close]").forEach(function (el) {
      el.addEventListener("click", closeDrawer);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && drawer.el.classList.contains("is-open")) closeDrawer();
    });
    drawer.save.addEventListener("click", save);

    $$(".stf-tab").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tab = btn.dataset.tab;
        state.tab = tab;
        $$(".stf-tab").forEach(function (b) { b.classList.toggle("is-active", b === btn); });
        $$(".stf-panel").forEach(function (p) {
          p.classList.toggle("is-active", p.dataset.panel === tab);
        });
        $("#stfExportCsv").style.display = tab === "database" ? "" : "none";
        loadTab(tab);
      });
    });

    document.addEventListener("input", function (e) {
      var el = e.target.closest && e.target.closest("[data-filter]");
      if (!el) return;
      var name = el.dataset.filter;
      // Los filtros de año los resuelve el server, así que hay que refetchear.
      if (name === "ch-year") return reloadYearScoped("churn");
      if (name === "bo-year") return reloadYearScoped("bonos");
      renderTab(state.tab);
    });

    $$("[data-clear]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var panel = btn.closest(".stf-panel");
        panel.querySelectorAll("[data-filter]").forEach(function (el) {
          el.value = el.dataset.filter.endsWith("-year") ? "all" : "";
        });
        reloadYearScoped(btn.dataset.clear);
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
          if (!res.ok) throw new Error("No se pudo exportar (HTTP " + res.status + ")");
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
