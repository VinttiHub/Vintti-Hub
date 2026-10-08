/* =====================================================================
   Prospecting — base compartida para las páginas que NO son prospecting.html
   (hoy: prospecting-company.html). Expone window.Prospecting con la misma forma
   que la que arma prospecting.js, así prospecting-contacts.js funciona igual en
   las dos páginas.

   API base: mismo criterio que prospecting.js (localhost:5000 en local, ?api=
   para forzar, se cae al deployado si el local no contesta).
   ===================================================================== */
(function () {
  "use strict";
  if (window.Prospecting) return;

  var PROD = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
  var host = location.hostname;
  var isProd = host === "vinttihub.vintti.com";
  var isLocal = !isProd && (
    host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" ||
    host === "" || host === "::1" || host.endsWith(".local") || location.protocol === "file:"
  );
  var override = new URLSearchParams(location.search).get("api");
  if (override) {
    try { localStorage.setItem("prospecting_api", override.replace(/\/$/, "")); } catch (e) {}
  }
  var sticky = null;
  try { sticky = localStorage.getItem("prospecting_api"); } catch (e) {}
  var API = (override && override.replace(/\/$/, "")) || sticky || (isLocal ? "http://localhost:5000" : PROD);
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
            err.errors = data.errors || null;
            throw err;
          }
          return data;
        });
      },
      function () {
        var err = new Error("No se pudo conectar con " + base + ".");
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
  function todayIso() {
    var d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  var toastTimer = null;
  function toast(html) {
    var el = document.getElementById("prToast");
    if (!el) return;
    el.innerHTML = html;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; }, 6000);
  }

  var OPTS = { statuses: [], not_icp_reasons: [], sizes: [], bdrs: [], weeks: [], users: [] };
  var ME = { email: userEmail() };

  function ownerName(email) {
    if (!email) return "";
    var hit = (OPTS.bdrs || []).concat(OPTS.users || []).filter(function (b) { return b.email === email; })[0];
    return hit ? (hit.name || hit.email) : email;
  }

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
    reloadTable: function () {},
    /* Sólo en esta base: cargar sesión y catálogos. */
    boot: function () {
      return api("/prospecting/me").then(function (me) {
        ME = me;
        if (!me.has_access) return me;
        return api("/prospecting/options").then(function (o) { OPTS = o; return me; });
      });
    },
  };
})();
