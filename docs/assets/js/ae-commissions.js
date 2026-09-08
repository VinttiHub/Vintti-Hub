/* =====================================================================
   Comisiones AE — data mensual para liquidar comisiones de Account Executives.

   Tres bloques del mes elegido, tal como salen por mail el día 1:
     · Staffing   — opps de Staffing cerradas (Close Win) en el mes
     · Recruiting — opps de Recruiting cerradas en el mes
     · M3         — bajas reales del mes dentro de los primeros 3 meses

   El backend hace todo el cálculo (backend/ae_commissions/queries.py); acá sólo
   se pinta lo que devuelve, para que la página y el mail nunca puedan diferir.
   ===================================================================== */
(function () {
  "use strict";

  /* ---------- API base (mismo patrón que staffing.js) ---------- */
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
    try { localStorage.setItem("aec_api", override.replace(/\/$/, "")); } catch (e) {}
  }
  var sticky = null;
  try { sticky = localStorage.getItem("aec_api"); } catch (e) {}

  var API = (override && override.replace(/\/$/, "")) || sticky ||
            (isLocal ? "http://localhost:8080" : PROD);
  // Abrir la página en local no obliga a tener el backend levantado: si no
  // contesta, se cae al deployado una sola vez y se sigue usando ese.
  var canFallBack = isLocal && !override && !sticky && API !== PROD;

  function userEmail() {
    try {
      return (localStorage.getItem("user_email") || sessionStorage.getItem("user_email") || "")
        .toLowerCase().trim();
    } catch (e) { return ""; }
  }

  function request(base, path) {
    return fetch(base + path, { headers: { "X-User-Email": userEmail() } }).then(
      function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          if (!res.ok) {
            var err = new Error(data.error || ("HTTP " + res.status));
            err.status = res.status;
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

  function localHint(tried) {
    return "No se pudo llegar al backend" + (tried ? " (" + tried + ")" : "") + ". " +
           "Si estás corriendo en local, levantalo con `python app.py` desde backend/, " +
           "o abrí la página con ?api=<url>.";
  }

  function api(path) {
    var first = API;
    return request(API, path).catch(function (err) {
      if (!err.offline) throw err;
      if (!canFallBack) {
        err.message = localHint(first);
        throw err;
      }
      // Se intenta el deployado, pero si TAMBIÉN falla el mensaje tiene que hablar
      // del backend local: nombrar sólo App Runner manda a depurar el server
      // equivocado cuando lo único que pasa es que no levantaste el local.
      canFallBack = false;
      API = PROD;
      return request(API, path).catch(function (err2) {
        if (err2.offline) err2.message = localHint(first + " ni " + PROD);
        throw err2;
      });
    });
  }

  /* ---------- Permisos ----------
     Cosmético: el gate real es AE_COMMISSIONS_ALLOWED en
     backend/routes/ae_commissions_routes.py, y las dos listas se mantienen en
     sincronía a mano. Bahía se suma cuando lo pida la owner. */
  var ALLOWED = new Set([
    "pgonzales@vintti.com",
    "bahia@vintti.com",
    "lara@vintti.com",
    "agustin@vintti.com"
  ]);

  /* ---------- Formato ---------- */
  function esc(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function money(value) {
    var n = Number(value || 0);
    if (!n) return "—";
    return "USD " + n.toLocaleString("es-AR", { maximumFractionDigits: 0 });
  }

  function aeShort(value) {
    return String(value || "").split("@")[0] || "—";
  }

  /* ---------- Columnas (mismo orden que el mail) ---------- */
  var MONEY = { setup_fee: 1, fee: 1, recruiting_fee: 1, amount: 1 };

  var COLS = {
    staffing: [
      ["client_name", "Nombre de Cliente", "left"],
      ["opp_position_name", "Nombre de Oportunidad", "left"],
      ["candidates", "Candidato", "left"],
      ["close_date", "Fecha de Cierre", "left"],
      ["setup_fee", "Setup Fee", "right"],
      ["fee", "Fee", "right"],
      ["is_replacement", "Replacement", "center"],
      ["equipment", "Equipment", "center"],
      ["ae", "AE", "left"]
    ],
    recruiting: [
      ["client_name", "Nombre de Cliente", "left"],
      ["opp_position_name", "Nombre de Oportunidad", "left"],
      ["candidates", "Candidato", "left"],
      ["close_date", "Fecha de Cierre", "left"],
      ["recruiting_fee", "Recruiting Fee", "right"],
      ["is_replacement", "Replacement", "center"],
      ["ae", "AE", "left"]
    ],
    m3: [
      ["client_name", "Nombre de Cliente", "left"],
      ["opp_position_name", "Nombre de Oportunidad", "left"],
      ["candidate_name", "Candidato", "left"],
      ["opp_model", "Modelo", "left"],
      ["close_date", "Fecha de Cierre", "left"],
      ["end_date", "Fecha de Baja", "left"],
      ["amount", "Fee", "right"],
      ["is_replacement", "Replacement", "center"],
      ["inactive_reason", "Motivo", "left"],
      ["ae", "AE", "left"]
    ]
  };

  var TOTALS = {
    staffing: [["setup_fee", "Setup fees"], ["fee", "Fee mensual"]],
    recruiting: [["recruiting_fee", "Recruiting fees"]],
    m3: [["amount", "Fee comprometido"]]
  };

  var EMPTY = {
    staffing: "Sin cierres de Staffing en el mes.",
    recruiting: "Sin cierres de Recruiting en el mes.",
    m3: "No M3 churn."
  };

  function cellValue(row, key) {
    if (key === "ae") return aeShort(row[key]);
    if (MONEY[key]) return money(row[key]);
    var raw = row[key];
    return (raw === null || raw === undefined || raw === "") ? "—" : String(raw);
  }

  /* Una fila incompleta es un fee en cero: data que falta, no comisión cero. */
  function isIncomplete(block, row) {
    if (block === "staffing") return !row.hire_count || !Number(row.fee);
    if (block === "recruiting") return !row.hire_count || !Number(row.recruiting_fee);
    return false;
  }

  function renderTable(block, rows, host) {
    if (!rows.length) {
      host.className = "";
      host.innerHTML = '<p class="aec-empty">' + esc(EMPTY[block]) + "</p>";
      return;
    }
    var cols = COLS[block];
    var head = cols.map(function (c) {
      return '<th class="aec-th--' + c[2] + '">' + esc(c[1]) + "</th>";
    }).join("");

    var body = rows.map(function (row) {
      var flag = isIncomplete(block, row);
      var oppId = row.opportunity_id;
      var tds = cols.map(function (c, i) {
        var text = esc(cellValue(row, c[0]));
        // El nombre de la oportunidad va como <a> de verdad y no sólo como fila
        // clickeable: así funciona Cmd+click para abrirla en otra pestaña y se ve
        // a dónde lleva antes de hacer click.
        if (c[0] === "opp_position_name" && oppId) {
          text = '<a class="aec-link" href="' + oppUrl(oppId) + '">' + text + "</a>";
        }
        if (flag && i === 0) text += '<span class="aec-flag">sin fee</span>';
        return '<td class="aec-td--' + c[2] + '">' + text + "</td>";
      }).join("");
      var cls = (flag ? "is-incomplete " : "") + (oppId ? "is-clickable" : "");
      return '<tr class="' + cls.trim() + '"' +
             (oppId ? ' data-opp="' + esc(oppId) + '"' : "") + ">" + tds + "</tr>";
    }).join("");

    // El pie totaliza las columnas de plata; el resto queda en blanco.
    var totalKeys = {};
    TOTALS[block].forEach(function (t) { totalKeys[t[0]] = true; });
    var foot = cols.map(function (c, i) {
      if (i === 0) return '<td class="aec-td--left">' + rows.length + " fila(s)</td>";
      if (!totalKeys[c[0]]) return '<td class="aec-td--' + c[2] + '"></td>';
      var total = rows.reduce(function (acc, r) { return acc + Number(r[c[0]] || 0); }, 0);
      return '<td class="aec-td--' + c[2] + '">' + esc(money(total)) + "</td>";
    }).join("");

    host.className = "";
    host.innerHTML =
      '<div class="aec-scroll"><table class="aec-table aec-table--' + block + '">' +
      "<thead><tr>" + head + "</tr></thead>" +
      "<tbody>" + body + "</tbody>" +
      "<tfoot><tr>" + foot + "</tr></tfoot>" +
      "</table></div>";
  }


  /* ---------- Ir a la oportunidad ---------- */
  // Patron del repo: opportunity-detail.html?id=<opportunity_id>
  // (cv-review.js, candidate-details.js, main.js usan todos ?id=).
  function oppUrl(id) {
    return "opportunity-detail.html?id=" + encodeURIComponent(id);
  }

  function wireRowLinks() {
    // Delegado en document y enganchado UNA sola vez: los hosts de las tablas se
    // reescriben con innerHTML en cada carga, asi que un listener por tabla se
    // acumularia en cada cambio de mes.
    document.addEventListener("click", function (ev) {
      var tr = ev.target.closest && ev.target.closest("tr[data-opp]");
      if (!tr) return;
      // El <a> del nombre ya navega solo; no duplicar.
      if (ev.target.closest("a")) return;
      // Si el usuario estaba seleccionando texto de la fila, no navegar.
      try {
        if (String(window.getSelection())) return;
      } catch (e) {}
      var url = oppUrl(tr.getAttribute("data-opp"));
      if (ev.metaKey || ev.ctrlKey) window.open(url, "_blank");
      else window.location.href = url;
    });
  }

  /* ---------- KPIs ---------- */
  function sum(rows, key) {
    return rows.reduce(function (acc, r) { return acc + Number(r[key] || 0); }, 0);
  }

  function renderKpis(data) {
    var st = data.staffing || [], rc = data.recruiting || [], m3 = data.m3 || [];
    var cards = [
      ["violet", "Cierres Staffing", st.length],
      ["violet", "Fee mensual Staffing", money(sum(st, "fee"))],
      ["blue", "Setup fees", money(sum(st, "setup_fee"))],
      ["cyan", "Cierres Recruiting", rc.length],
      ["cyan", "Recruiting fees", money(sum(rc, "recruiting_fee"))],
      ["mag", "Bajas M3", m3.length]
    ];
    document.getElementById("aecKpis").innerHTML = cards.map(function (c) {
      return '<div class="aec-kpi aec-kpi--' + c[0] + '">' +
             '<div class="aec-kpi__label">' + esc(c[1]) + "</div>" +
             '<div class="aec-kpi__value">' + esc(c[2]) + "</div></div>";
    }).join("");
  }

  /* ---------- CSV ---------- */
  function toCsv(block, rows) {
    var cols = COLS[block];
    var lines = [cols.map(function (c) { return c[1]; }).join(",")];
    rows.forEach(function (row) {
      lines.push(cols.map(function (c) {
        var raw = c[0] === "ae" ? aeShort(row[c[0]])
                : (row[c[0]] === null || row[c[0]] === undefined ? "" : row[c[0]]);
        return '"' + String(raw).replace(/"/g, '""') + '"';
      }).join(","));
    });
    return lines.join("\n");
  }

  function downloadCsv(data) {
    var parts = [];
    ["staffing", "recruiting", "m3"].forEach(function (block) {
      parts.push(block.toUpperCase());
      parts.push(toCsv(block, data[block] || []));
      parts.push("");
    });
    // BOM para que Excel abra los acentos bien.
    var blob = new Blob(["﻿" + parts.join("\n")], { type: "text/csv;charset=utf-8;" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "comisiones-ae-" + (data.period || "") + ".csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }


  /* ---------- Selector de mes ----------
     Ultimos 18 meses cerrados, empezando por el mes vencido (que es el que el
     backend usa por default). No se ofrece el mes en curso: el reporte es del
     mes VENCIDO y un mes a medias solo confunde. */
  var MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                  "agosto", "septiembre", "octubre", "noviembre", "diciembre"];

  function monthOptions(count) {
    var now = new Date();
    var out = [];
    for (var i = 1; i <= count; i++) {
      var d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      var value = d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
      out.push([value, MESES_ES[d.getMonth()] + " " + d.getFullYear()]);
    }
    return out;
  }

  function fillMonthSelect(selected) {
    var sel = document.getElementById("aecMonth");
    var opts = monthOptions(18);
    // Si llega un periodo por querystring que cae fuera de la lista, se agrega
    // para que el select no muestre un mes distinto del que se esta viendo.
    if (selected && !opts.some(function (o) { return o[0] === selected; })) {
      opts.unshift([selected, selected]);
    }
    sel.innerHTML = opts.map(function (o) {
      return '<option value="' + esc(o[0]) + '">' + esc(o[1]) + "</option>";
    }).join("");
    if (selected) sel.value = selected;
  }

  /* ---------- Carga ---------- */
  var current = null;

  function setError(message) {
    var el = document.getElementById("aecError");
    el.textContent = message || "";
    el.hidden = !message;
  }

  function load(period) {
    setError("");
    ["Staffing", "Recruiting", "M3"].forEach(function (name) {
      var host = document.getElementById("aecTable" + name);
      host.className = "aec-loading";
      host.textContent = "Cargando…";
    });

    return api("/ae-commissions" + (period ? "?period=" + encodeURIComponent(period) : ""))
      .then(function (data) {
        current = data;
        document.getElementById("aecSub").textContent =
          "Cierres de " + (data.period_label || "") +
          " · Close Win con fecha de cierre dentro del mes, AEs del scope Sales.";
        fillMonthSelect(data.period || "");
        renderKpis(data);
        renderTable("staffing", data.staffing || [], document.getElementById("aecTableStaffing"));
        renderTable("recruiting", data.recruiting || [], document.getElementById("aecTableRecruiting"));
        renderTable("m3", data.m3 || [], document.getElementById("aecTableM3"));

        ["staffing", "recruiting", "m3"].forEach(function (block) {
          var badge = document.querySelector('[data-count="' + block + '"]');
          if (badge) badge.textContent = (data[block] || []).length;
        });

        var faltantes = (data.staffing || []).filter(function (r) { return isIncomplete("staffing", r); })
          .concat((data.recruiting || []).filter(function (r) { return isIncomplete("recruiting", r); }));
        document.getElementById("aecNotice").innerHTML = faltantes.length
          ? '<p class="aec-notice"><strong>' + faltantes.length + "</strong> oportunidad(es) " +
            "cerradas sin fee cargado. Hay que completarlas antes de liquidar, porque suman " +
            "cero a la comisión.</p>"
          : "";
      })
      .catch(function (err) {
        setError(err.message || "No se pudo cargar el reporte.");
        ["Staffing", "Recruiting", "M3"].forEach(function (name) {
          var host = document.getElementById("aecTable" + name);
          host.className = "";
          host.innerHTML = "";
        });
      });
  }

  /* ---------- Arranque ---------- */
  function init() {
    var me = userEmail();
    if (!ALLOWED.has(me)) {
      document.getElementById("aecDenied").hidden = false;
      return;
    }
    document.getElementById("aecApp").hidden = false;

    document.querySelectorAll(".aec-tab").forEach(function (tab) {
      tab.addEventListener("click", function () {
        document.querySelectorAll(".aec-tab").forEach(function (t) { t.classList.remove("is-active"); });
        tab.classList.add("is-active");
        var name = tab.getAttribute("data-tab");
        document.querySelectorAll(".aec-panel").forEach(function (p) {
          p.classList.toggle("is-active", p.getAttribute("data-panel") === name);
        });
      });
    });

    document.getElementById("aecMonth").addEventListener("change", function () {
      load(this.value);
    });

    wireRowLinks();

    document.getElementById("aecExportCsv").addEventListener("click", function () {
      if (current) downloadCsv(current);
    });

    load(new URLSearchParams(location.search).get("period"));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
