/* =====================================================================
   Hirex — shared runtime config.
   Single source of truth for the API base URL so every Hirex page runs
   locally out of the box. Include this BEFORE any other Hirex script.

   Resolution order:
     1. ?api=<url>            explicit per-visit override
     2. localStorage.hirex_api  sticky override (set once, persists)
     3. local dev host        -> http://localhost:5000
     4. production            -> deployed backend
   ===================================================================== */
(function () {
  "use strict";
  var PROD = "https://7m6mw95m8y.us-east-2.awsapprunner.com";
  var host = location.hostname;

  // Local unless we're clearly on the production domain.
  var isProd = host === "vinttihub.vintti.com";
  var isLocal = !isProd && (
    host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" ||
    host === "" || host === "::1" || host.endsWith(".local") ||
    /^(10|192\.168|172\.(1[6-9]|2\d|3[01]))\./.test(host) ||
    location.protocol === "file:"
  );

  var override = new URLSearchParams(location.search).get("api");
  if (override) {
    try { localStorage.setItem("hirex_api", override.replace(/\/$/, "")); } catch (e) {}
  }
  var sticky = null;
  try { sticky = localStorage.getItem("hirex_api"); } catch (e) {}

  window.HIREX_API_BASE = (override && override.replace(/\/$/, "")) ||
    sticky ||
    (isLocal ? "http://localhost:5000" : PROD);
})();
