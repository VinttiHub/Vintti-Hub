/* Prospecting · Paneles (métricas de BDRs).
   El backend (GET /prospecting/panels/<key>, backend/prospecting/panels.py) devuelve FILAS a
   nivel registro; acá se agrupan por período y por persona. Así la barra, la celda del
   ranking y el detalle salen de las mismas filas: no pueden no cuadrar.
   Para sumar un panel: una entrada en PANELS con su render. */
(function () {
  "use strict";

  function P() { return window.Prospecting; }
  function esc(v) { return P().esc(v); }

  /* Un color por persona, EL MISMO en todos los paneles (pedido de la owner: Abril siempre
     del mismo color). El orden lo da el backend (`people_order`: todas las personas con algún
     Scheduled By, por orden de aparición), igual para todos los paneles; alguien nuevo va al
     final y no le cambia el color a nadie. Tonos medios, legibles con texto blanco. */
  var PALETTE = ["#6c38ff", "#003bff", "#0f9488", "#e8590c", "#d61fb4", "#2f9e44",
    "#1f8fe0", "#d48806", "#e03e3e", "#4c3fbf", "#7a8b12", "#e64980",
    "#0b7285", "#9c36b5", "#5c940d", "#c2410c", "#1864ab", "#a61e4d",
    "#087f5b", "#8f5a00", "#3b5bdb", "#c92a2a", "#5f3dc4", "#2b8a3e"];
  var personColor = {};
  function setPeople(emails) {
    personColor = {};
    emails.forEach(function (e, i) { personColor[e] = PALETTE[i % PALETTE.length]; });
  }
  function colorOf(email) { return personColor[email] || "#8a90a0"; }
  function dot(email) { return '<span class="pp-pdot" style="--c:' + colorOf(email) + '"></span>'; }

  var MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  var FREQS = [["month", "Mensual"], ["week", "Semanal"], ["quarter", "Trimestral"]];

  function iso(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function parse(s) { var p = String(s).slice(0, 10).split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); }

  /* Clave de período (ordenable) de una fecha YYYY-MM-DD. Semana = lunes de esa semana. */
  function periodKey(s, freq) {
    var d = parse(s);
    if (freq === "week") { d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return iso(d); }
    if (freq === "quarter") return d.getFullYear() + "-Q" + (Math.floor(d.getMonth() / 3) + 1);
    return s.slice(0, 7);
  }
  function periodLabel(k, freq, short) {
    if (freq === "quarter") return "Q" + k.slice(-1) + " " + (short ? "’" + k.slice(2, 4) : k.slice(0, 4));
    if (freq === "week") { var d = parse(k); return d.getDate() + " " + MONTHS[d.getMonth()] + (short ? "" : " " + d.getFullYear()); }
    return MONTHS[+k.slice(5, 7) - 1] + " " + (short ? "’" + k.slice(2, 4) : k.slice(0, 4));
  }
  /* Todos los períodos entre from y to, también los que no tienen SQLs (una barra en 0
     también es un dato). */
  function periodsBetween(from, to, freq) {
    var out = [], d = parse(from), end = parse(to);
    if (freq === "week") d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    else d = new Date(d.getFullYear(), freq === "quarter" ? Math.floor(d.getMonth() / 3) * 3 : d.getMonth(), 1);
    while (d <= end && out.length < 600) {
      out.push(periodKey(iso(d), freq));
      if (freq === "week") d.setDate(d.getDate() + 7);
      else d = new Date(d.getFullYear(), d.getMonth() + (freq === "quarter" ? 3 : 1), 1);
    }
    return out;
  }

  /* =================================================================
     Shell de la sección
     ================================================================= */
  var root = null, bound = false;
  /* Registro de paneles. `group` agrupa en el selector (<optgroup>) y se ve arriba del nombre. */
  var G_SQL_YTD = "SQLs - Monthly YTD";  // nombre del grupo en el selector
  // El título de arriba sigue a la frecuencia del panel visible (Monthly / Weekly / Quarterly).
  var FREQ_EN = { month: "Monthly", week: "Weekly", quarter: "Quarterly" };
  function sqlPanel(key, title, team) {
    return { key: key, title: title, group: G_SQL_YTD,
      render: function (el) { return SqlsByBdr(el, { key: key, title: title, team: team }); },
      heading: function (inst) { return "SQLs - " + FREQ_EN[(inst && inst.freq()) || "month"] + " YTD"; } };
  }
  var PANELS = [
    sqlPanel("sqls_by_bdr", "SQLs by BDR"),
    sqlPanel("sqls_by_bdr_vinttikids", "SQLs by BDR · VinttiKids", "VinttiKids"),
    sqlPanel("sqls_by_bdr_nextgen", "SQLs by BDR · NextGen", "NextGen")
  ];

  /* Uno a la vez: barra con ‹ selector › arriba. Cada panel se arma la primera vez que se
     muestra (no pide datos de los que no se ven) y después sólo se oculta, así conserva sus
     filtros. El último visto queda en el navegador. */
  var CUR_KEY = "pp_current_v1";
  var current = 0;

  function show() {
    root = document.getElementById("prPanelsView");
    if (!root) return;
    if (!bound) {
      try {
        var saved = localStorage.getItem(CUR_KEY);
        PANELS.forEach(function (p, i) { if (p.key === saved) current = i; });
      } catch (e) {}
      var groups = [];
      PANELS.forEach(function (p) { if (groups.indexOf(p.group) === -1) groups.push(p.group); });
      root.innerHTML =
        '<nav class="pp-nav" aria-label="Paneles">' +
          '<button type="button" class="pp-nav__arrow" data-nav="-1" aria-label="Panel anterior"><i class="fa-solid fa-chevron-left"></i></button>' +
          '<div class="pp-nav__mid"><span class="pp-nav__group" data-nav-group></span>' +
            '<select class="pr-filter__input pp-nav__select" data-nav-select aria-label="Elegir panel">' +
            groups.map(function (g) {
              return '<optgroup label="' + esc(g) + '">' + PANELS.map(function (p, i) {
                return p.group === g ? '<option value="' + i + '">' + esc(p.title) + "</option>" : "";
              }).join("") + "</optgroup>";
            }).join("") + "</select></div>" +
          '<span class="pp-nav__count" data-nav-count></span>' +
          '<button type="button" class="pp-nav__arrow" data-nav="1" aria-label="Panel siguiente"><i class="fa-solid fa-chevron-right"></i></button>' +
        "</nav>" +
        PANELS.map(function (p) { return '<section class="pp-card" id="pp-' + p.key + '" hidden></section>'; }).join("");
      root.querySelector(".pp-nav").addEventListener("click", function (e) {
        var b = e.target.closest("[data-nav]");
        if (b) go(current + Number(b.getAttribute("data-nav")));
      });
      root.querySelector("[data-nav-select]").addEventListener("change", function (e) { go(Number(e.target.value)); });
      document.addEventListener("keydown", function (e) {
        if (root.hidden || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
        if (e.target.closest && e.target.closest("input, select, textarea, [contenteditable]")) return;
        if (document.querySelector(".pr-drawer.is-open")) return;
        go(current + (e.key === "ArrowRight" ? 1 : -1));
      });
      // Los filtros del panel quedan pegados debajo de la barra: su `top` es el alto de la barra.
      var nav = root.querySelector(".pp-nav");
      var setNavH = function () { root.style.setProperty("--pp-nav-h", nav.offsetHeight + "px"); };
      setNavH();
      if (window.ResizeObserver) new ResizeObserver(setNavH).observe(nav);
      // Sombra bajo los filtros sólo cuando ya están pegados.
      root.addEventListener("scroll", function () {
        var head = root.querySelector(".pp-card:not([hidden]) > .pp-card__head");
        if (head) head.classList.toggle("is-stuck", root.scrollTop > 8);
      }, { passive: true });
      bound = true;
      go(current, true);
    } else {
      var p = PANELS[current];
      if (p.inst && p.inst.reload) p.inst.reload();
    }
  }

  function refreshHeading() {
    if (!root || !bound) return;
    var p = PANELS[current];
    root.querySelector("[data-nav-group]").textContent = p.heading ? p.heading(p.inst) : p.group;
  }

  function go(i, first) {
    var n = PANELS.length;
    i = ((i % n) + n) % n;  // las flechas dan la vuelta
    current = i;
    try { localStorage.setItem(CUR_KEY, PANELS[i].key); } catch (e) {}
    PANELS.forEach(function (p, j) {
      var el = document.getElementById("pp-" + p.key);
      el.hidden = j !== i;
      if (j === i) {
        el.classList.remove("pp-in");
        void el.offsetWidth;  // reinicia la animación
        el.classList.add("pp-in");
        if (!p.inst) p.inst = p.render(el);
      }
    });
    root.querySelector("[data-nav-select]").value = String(i);
    refreshHeading();
    root.querySelector("[data-nav-count]").textContent = (i + 1) + " de " + n;
    if (!first) root.scrollTop = 0;
  }

  /* =================================================================
     Detalle (drawer) compartido
     ================================================================= */
  var drawer = null, drawerRows = [], drawerTitle = "";
  function ensureDrawer() {
    if (drawer) return drawer;
    drawer = document.createElement("div");
    drawer.className = "pr-drawer pp-drawer";
    drawer.setAttribute("aria-hidden", "true");
    drawer.innerHTML = '<div class="pr-drawer__backdrop" data-pp-close></div>' +
      '<aside class="pr-drawer__panel pp-drawer__panel" role="dialog" aria-modal="true">' +
        '<header class="pr-drawer__head"><span class="pr-drawer__eyebrow">Detalle</span>' +
          '<h2 class="pr-drawer__title" id="ppDTitle">—</h2><p class="pr-drawer__sub" id="ppDSub"></p>' +
          '<button type="button" class="pr-drawer__close" data-pp-close aria-label="Cerrar">&times;</button></header>' +
        '<div class="pr-drawer__body" id="ppDBody"></div>' +
        '<footer class="pr-drawer__foot"><span class="pr-drawer__status"></span>' +
          '<button type="button" class="pr-btn" id="ppDCsv"><i class="fa-solid fa-file-csv"></i> Exportar CSV</button></footer>' +
      "</aside>";
    document.body.appendChild(drawer);
    drawer.addEventListener("click", function (e) {
      if (e.target.closest("[data-pp-close]")) return closeDrawer();
      var ct = e.target.closest("[data-pp-contact]");
      if (ct && window.ProspectingContacts) {
        return window.ProspectingContacts.open({ contactId: Number(ct.getAttribute("data-pp-contact")) });
      }
      var dl = e.target.closest("[data-pp-deal]");
      if (dl && window.ProspectingDeals) return window.ProspectingDeals.open({ dealId: Number(dl.getAttribute("data-pp-deal")) });
    });
    document.getElementById("ppDCsv").addEventListener("click", exportCsv);
    document.addEventListener("keydown", function (e) {
      // El panel del contacto / negocio se abre encima: Esc cierra ése primero.
      if (e.key === "Escape" && drawer.classList.contains("is-open") &&
          !document.querySelector(".pc-drawer.is-open, .pd-drawer.is-open")) closeDrawer();
    }, true);  // captura: corre antes de que el panel del contacto se cierre con el mismo Esc
    return drawer;
  }
  function closeDrawer() { drawer.classList.remove("is-open"); drawer.setAttribute("aria-hidden", "true"); }

  function openDetail(title, sub, rows) {
    ensureDrawer();
    drawerRows = rows;
    drawerTitle = title;
    document.getElementById("ppDTitle").textContent = title;
    document.getElementById("ppDSub").textContent = sub;
    document.getElementById("ppDBody").innerHTML = rows.length ? '<div class="pp-dtable-wrap"><table class="pp-dtable"><thead><tr>' +
      "<th>Contacto</th><th>Empresa</th><th>Negocio</th><th>SQL Date</th><th>Meeting</th><th>Scheduled By</th></tr></thead><tbody>" +
      rows.map(function (r) {
        return "<tr><td>" + '<button type="button" class="pp-link" data-pp-contact="' + r.contact_id + '"><strong>' +
            esc(r.contact_name || r.email || "#" + r.contact_id) + "</strong></button>" +
            (r.contact_name && r.email ? '<div class="pr-note">' + esc(r.email) + "</div>" : "") + "</td>" +
          "<td>" + (r.company_id ? '<a class="pp-link" href="prospecting-company.html?id=' + r.company_id + '" target="_blank" rel="noopener">' +
            esc(r.company_name || "—") + "</a>" : '<span class="pr-note">Sin empresa</span>') + "</td>" +
          '<td><button type="button" class="pp-link" data-pp-deal="' + r.deal_id + '">' + esc(r.deal_name || "#" + r.deal_id) + "</button>" +
            (r.stage_label ? '<div class="pr-note">' + esc(r.stage_label) + "</div>" : "") + "</td>" +
          "<td>" + esc(P().fmtDate(r.sql_date)) + "</td>" +
          "<td>" + esc(r.meeting_datetime ? P().fmtDateTime(r.meeting_datetime) : "—") + "</td>" +
          "<td>" + dot(r.scheduled_by) + esc(r.scheduled_by_name || r.scheduled_by) + "</td></tr>";
      }).join("") + "</tbody></table></div>" : '<p class="pr-note">Sin SQLs en esta selección.</p>';
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
  }

  function exportCsv() {
    var cols = [["contact_name", "Contacto"], ["email", "Email"], ["company_name", "Empresa"], ["deal_name", "Negocio"],
      ["stage_label", "Etapa"], ["sql_date", "SQL Date"], ["meeting_datetime", "Meeting Date & Time"],
      ["scheduled_by_name", "Scheduled By"], ["scheduled_by", "Scheduled By (email)"]];
    var q = function (v) { v = v == null ? "" : String(v); return /[",\n;]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    var csv = "﻿" + cols.map(function (c) { return q(c[1]); }).join(",") + "\n" +
      drawerRows.map(function (r) { return cols.map(function (c) { return q(r[c[0]]); }).join(","); }).join("\n");
    var a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = (drawerTitle || "detalle").replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "_") + ".csv";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  /* =================================================================
     SQLs by BDR
     ================================================================= */
  /* opts: {key (panel del backend), title, team?}. El mismo panel sirve para todo el equipo y
     para un equipo (VinttiKids): cambian sólo las filas que manda el backend. */
  function SqlsByBdr(el, opts) {
    var today = P().todayIso();
    var DEF = { freq: "month", from: today.slice(0, 4) + "-01-01", to: today };
    var st = { freq: DEF.freq, from: DEF.from, to: DEF.to, bdrs: null, rows: [], def: null, loading: true };
    var PREF = "pp_" + opts.key + "_v1";
    try { var saved = JSON.parse(localStorage.getItem(PREF) || "null"); if (saved && saved.freq) st.freq = saved.freq; } catch (e) {}

    el.innerHTML =
      '<header class="pp-card__head"><div class="pp-card__title"><h2>' + esc(opts.title) + '</h2>' +
        '<button type="button" class="pp-info" data-pp-info aria-label="Cómo se calcula"><i class="fa-solid fa-circle-info"></i></button></div>' +
        '<div class="pp-controls">' +
          '<div class="pp-seg" role="group">' + FREQS.map(function (f) {
            return '<button type="button" data-freq="' + f[0] + '">' + f[1] + "</button>";
          }).join("") + "</div>" +
          '<label class="pp-date"><span>Desde</span><input type="date" class="pr-filter__input" data-from></label>' +
          '<label class="pp-date"><span>Hasta</span><input type="date" class="pr-filter__input" data-to></label>' +
          '<details class="pp-ms"><summary class="pr-btn"><i class="fa-solid fa-user-group"></i> <span data-ms-label>Todos los BDRs</span></summary>' +
            '<div class="pp-ms__pop" data-ms-pop></div></details>' +
          '<button type="button" class="pr-btn pp-reset" data-reset hidden title="Volver a Mensual, este año y todos los BDRs">' +
            '<i class="fa-solid fa-rotate-left"></i> Restablecer</button>' +
        "</div></header>" +
      '<div class="pp-def" data-def hidden></div>' +
      '<div class="pp-kpis" data-kpis></div>' +
      '<div class="pp-chart" data-chart></div>' +
      '<div class="pp-rank" data-rank></div>';

    var q = function (sel) { return el.querySelector(sel); };
    q("[data-from]").value = st.from;
    q("[data-to]").value = st.to;

    function savePref() { try { localStorage.setItem(PREF, JSON.stringify({ freq: st.freq })); } catch (e) {} }

    function load() {
      st.loading = true;
      render();
      return P().api("/prospecting/panels/" + opts.key + "?from=" + encodeURIComponent(st.from) + "&to=" + encodeURIComponent(st.to))
        .then(function (r) {
          st.rows = r.rows || []; st.def = r.definition || null; st.loading = false;
          if (r.people_order) setPeople(r.people_order);
          render();
        })
        .catch(function (err) { st.loading = false; q("[data-chart]").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>"; });
    }

    function people() {
      var m = {};
      st.rows.forEach(function (r) { m[r.scheduled_by] = r.scheduled_by_name || r.scheduled_by; });
      return Object.keys(m).map(function (e) { return { email: e, name: m[e] }; })
        .sort(function (a, b) { return a.name.localeCompare(b.name, "es"); });
    }
    function rowsOn() {
      return st.bdrs ? st.rows.filter(function (r) { return st.bdrs.indexOf(r.scheduled_by) !== -1; }) : st.rows;
    }

    function renderDef() {
      var d = st.def || {};
      q("[data-def]").innerHTML = "<strong>Cómo se cuenta.</strong> Contactos con un negocio que tiene <em>SQL Date</em>, " +
        "agrupados por la SQL Date del negocio y por <em>Scheduled By</em> del contacto (quién agendó la reunión). " +
        (d.team ? "Sólo el equipo " + esc(opts.team || "") + ": " + esc(d.team.join(", ")) + ". " : "") +
        "Igual que el reporte de HubSpot: Scheduled By conocido y fuera de " + esc((d.excluded_schedulers || []).join(", ")) +
        "; contactos fuera del equipo interno (" + esc((d.internal_domains || []).map(function (x) { return "@" + x; }).join(", ")) + ")" +
        "; con Meeting Date &amp; Time cargada. «SQL Date» existe desde fines de nov-2025: antes no hay datos. " +
        "Un contacto cuenta una vez por SQL Date. Se calcula en vivo con los datos del Hub.";
    }

    function renderMs() {
      var ps = people();
      q("[data-ms-pop]").innerHTML = '<label class="pr-check"><input type="checkbox" data-ms-all' + (st.bdrs ? "" : " checked") + "> <strong>Todos</strong></label>" +
        ps.map(function (p) {
          var on = !st.bdrs || st.bdrs.indexOf(p.email) !== -1;
          return '<label class="pr-check"><input type="checkbox" data-ms="' + esc(p.email) + '"' + (on ? " checked" : "") + "> " + dot(p.email) + esc(p.name) + "</label>";
        }).join("");
      q("[data-ms-label]").textContent = !st.bdrs ? "Todos los BDRs" :
        !st.bdrs.length ? "Ningún BDR" :
        st.bdrs.length === 1 ? (ps.filter(function (p) { return p.email === st.bdrs[0]; })[0] || {}).name || "1 BDR" :
        st.bdrs.length + " BDRs";
    }

    function isDefault() { return st.freq === DEF.freq && st.from === DEF.from && st.to === DEF.to && !st.bdrs; }
    function reset() {
      var reload = st.from !== DEF.from || st.to !== DEF.to;
      st.freq = DEF.freq; st.from = DEF.from; st.to = DEF.to; st.bdrs = null;
      q("[data-from]").value = st.from;
      q("[data-to]").value = st.to;
      savePref();
      if (reload) load(); else render();
    }

    function render() {
      q("[data-reset]").hidden = isDefault();
      refreshHeading();
      el.querySelectorAll("[data-freq]").forEach(function (b) { b.classList.toggle("is-on", b.getAttribute("data-freq") === st.freq); });
      renderDef();
      if (st.loading) {
        q("[data-kpis]").innerHTML = "";
        q("[data-chart]").innerHTML = '<p class="pr-note pp-loading">Cargando…</p>';
        q("[data-rank]").innerHTML = "";
        return;
      }
      renderMs();
      var rows = rowsOn();
      var periods = periodsBetween(st.from, st.to, st.freq);
      var tot = {}, by = {}, names = {};
      periods.forEach(function (k) { tot[k] = 0; });
      rows.forEach(function (r) {
        var k = periodKey(r.sql_date, st.freq);
        if (!(k in tot)) return;
        tot[k]++;
        by[r.scheduled_by] = by[r.scheduled_by] || {};
        by[r.scheduled_by][k] = (by[r.scheduled_by][k] || 0) + 1;
        names[r.scheduled_by] = r.scheduled_by_name || r.scheduled_by;
      });
      var total = periods.reduce(function (s, k) { return s + tot[k]; }, 0);
      var ranking = Object.keys(by).map(function (e) {
        var t = 0; Object.keys(by[e]).forEach(function (k) { t += by[e][k]; });
        return { email: e, name: names[e], total: t };
      }).sort(function (a, b) { return b.total - a.total || a.name.localeCompare(b.name, "es"); });

      // KPIs
      var last = periods[periods.length - 1], prev = periods[periods.length - 2];
      var best = periods.reduce(function (b, k) { return tot[k] > (b ? tot[b] : -1) ? k : b; }, null);
      var delta = prev != null ? tot[last] - tot[prev] : null;
      // Promedio sin el período en curso (incompleto: bajaría el promedio cada principio de mes).
      var curK = periodKey(P().todayIso(), st.freq);
      var full = periods.filter(function (k) { return k !== curK; });
      if (!full.length) full = periods;
      var avg = full.length ? full.reduce(function (sum, k) { return sum + tot[k]; }, 0) / full.length : 0;
      var avgLabel = { month: "promedio mensual", week: "promedio semanal", quarter: "promedio trimestral" }[st.freq];
      var fname = { month: "mes", week: "semana", quarter: "trimestre" }[st.freq];
      q("[data-kpis]").innerHTML =
        kpi("SQLs en el rango", total, periods.length + " " + (fname === "mes" ? "meses" : fname + "s") + " · " + avgLabel + " " + fmt1(avg) +
          (full.length < periods.length ? " · sin " + periodLabel(curK, st.freq, true) + " (en curso)" : "")) +
        kpi(capital(fname) + " actual · " + (last ? periodLabel(last, st.freq) : "—"), last ? tot[last] : 0,
          delta == null ? "" : '<span class="pp-delta ' + (delta > 0 ? "is-up" : delta < 0 ? "is-down" : "") + '">' +
            (delta > 0 ? "▲ +" : delta < 0 ? "▼ " : "= ") + delta + "</span> vs " + periodLabel(prev, st.freq), true) +
        kpi("Mejor " + fname, best && tot[best] ? tot[best] : 0, best && tot[best] ? periodLabel(best, st.freq) : "—") +
        kpi("Más SQLs", ranking[0] ? ranking[0].total : 0, ranking[0] ? esc(ranking[0].name) : "—", true);

      // Barras del total
      var max = Math.max.apply(null, periods.map(function (k) { return tot[k]; }).concat([1]));
      var step = Math.ceil(periods.length / 18);  // con muchas semanas, una etiqueta cada tanto
      q("[data-chart]").innerHTML = '<div class="pp-bars" style="--n:' + periods.length + '">' + periods.map(function (k, i) {
        var h = tot[k] ? Math.max(4, Math.round(tot[k] / max * 100)) : 0;
        return '<button type="button" class="pp-bar' + (k === last ? " is-current" : "") + '" data-period="' + k + '" title="' +
            esc(periodLabel(k, st.freq) + ": " + tot[k] + " SQL" + (tot[k] === 1 ? "" : "s")) + '">' +
          '<span class="pp-bar__track"><span class="pp-bar__fill" style="height:' + h + '%">' +
            (tot[k] ? '<span class="pp-bar__val">' + tot[k] + "</span>" : "") + "</span></span>" +
          '<span class="pp-bar__x">' + (i % step === 0 ? esc(periodLabel(k, st.freq, true)) : "&nbsp;") + "</span></button>";
      }).join("") + "</div>";

      // Ranking (mapa de calor)
      var cmax = 1;
      ranking.forEach(function (p) { periods.forEach(function (k) { cmax = Math.max(cmax, by[p.email][k] || 0); }); });
      q("[data-rank]").innerHTML = ranking.length ? '<div class="pp-rank__wrap"><table class="pp-heat"><thead><tr><th class="pp-heat__name">BDR</th>' +
        periods.map(function (k) { return '<th><button type="button" data-period="' + k + '">' + esc(periodLabel(k, st.freq, true)) + "</button></th>"; }).join("") +
        '<th class="pp-heat__tot">Total</th></tr></thead><tbody>' +
        ranking.map(function (p, i) {
          return '<tr><th class="pp-heat__name"><button type="button" data-bdr="' + esc(p.email) + '"><span class="pp-rankno" style="--c:' + colorOf(p.email) + '">' + (i + 1) + "</span>" + esc(p.name) + "</button></th>" +
            periods.map(function (k) {
              var v = by[p.email][k] || 0;
              var pct = v ? Math.round(14 + v / cmax * 76) : 0;
              return "<td>" + (v ? '<button type="button" class="pp-cell" data-bdr="' + esc(p.email) + '" data-period="' + k + '" style="--pct:' + pct + '%;--c:' + colorOf(p.email) + '"' +
                (pct > 55 ? ' data-dark="1"' : "") + ' title="' + esc(p.name + " · " + periodLabel(k, st.freq) + ": " + v) + '">' + v + "</button>" : '<span class="pp-dot">·</span>') + "</td>";
            }).join("") +
            '<td class="pp-heat__tot"><button type="button" data-bdr="' + esc(p.email) + '">' + p.total + "</button></td></tr>";
        }).join("") +
        '</tbody><tfoot><tr><th class="pp-heat__name">Total</th>' +
        periods.map(function (k) { return '<td><button type="button" data-period="' + k + '">' + (tot[k] || '<span class="pp-dot">·</span>') + "</button></td>"; }).join("") +
        '<td class="pp-heat__tot"><button type="button" data-all>' + total + "</button></td></tr></tfoot></table></div>"
        : '<p class="pr-note">Sin SQLs en este rango.</p>';
    }

    function kpi(label, value, sub, accent) {
      return '<div class="pp-kpi' + (accent ? " pp-kpi--accent" : "") + '"><span class="pp-kpi__label">' + esc(label) + "</span>" +
        '<strong class="pp-kpi__value">' + value + '</strong><span class="pp-kpi__sub">' + (sub || "") + "</span></div>";
    }
    function fmt1(n) { return (Math.round(n * 10) / 10).toString().replace(".", ","); }
    function capital(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

    function detail(period, bdr) {
      var rows = rowsOn().filter(function (r) {
        var k = periodKey(r.sql_date, st.freq);
        return r.sql_date >= st.from && r.sql_date <= st.to &&
          (!period || k === period) && (!bdr || r.scheduled_by === bdr);
      });
      var who = bdr ? (rows[0] && rows[0].scheduled_by_name) || bdr : (st.bdrs ? q("[data-ms-label]").textContent : (opts.team || "Todos los BDRs"));
      var when = period ? periodLabel(period, st.freq) : P().fmtDate(st.from) + " – " + P().fmtDate(st.to);
      openDetail("SQLs · " + who + " · " + when, rows.length + " contacto" + (rows.length === 1 ? "" : "s"), rows);
    }

    // Eventos
    el.addEventListener("click", function (e) {
      if (e.target.closest("[data-reset]")) return reset();
      if (e.target.closest("[data-pp-info]")) { q("[data-def]").hidden = !q("[data-def]").hidden; return; }
      var f = e.target.closest("[data-freq]");
      if (f) { st.freq = f.getAttribute("data-freq"); savePref(); render(); return; }
      if (e.target.closest("[data-all]")) return detail(null, null);
      var b = e.target.closest("[data-period], [data-bdr]");
      if (b && !b.closest("[data-ms-pop]")) detail(b.getAttribute("data-period"), b.getAttribute("data-bdr"));
    });
    el.addEventListener("change", function (e) {
      var t = e.target;
      if (t.matches("[data-from], [data-to]")) {
        var from = q("[data-from]").value, to = q("[data-to]").value;
        if (!from || !to || from > to) return;
        st.from = from; st.to = to;
        load();
        return;
      }
      // «Todos» prende o apaga a todos: apagado = ninguno, para después elegir de a uno.
      if (t.matches("[data-ms-all]")) { st.bdrs = t.checked ? null : []; render(); el.querySelector(".pp-ms").open = true; return; }
      if (t.matches("[data-ms]")) {
        var on = Array.prototype.map.call(el.querySelectorAll("[data-ms]:checked"), function (x) { return x.getAttribute("data-ms"); });
        st.bdrs = on.length === people().length ? null : on;
        render();
        el.querySelector(".pp-ms").open = true;
      }
    });
    document.addEventListener("click", function (e) {
      var ms = el.querySelector(".pp-ms");
      if (ms && ms.open && !ms.contains(e.target)) ms.open = false;
    });

    load();
    return { reload: load, freq: function () { return st.freq; } };
  }

  window.ProspectingPanels = { show: show };
})();
