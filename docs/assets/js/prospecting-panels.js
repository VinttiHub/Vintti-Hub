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
    "#087f5b", "#8f5a00", "#3b5bdb", "#c92a2a", "#5f3dc4", "#2b8a3e",
    "#b8860b", "#0c8599", "#ae3ec9", "#f76707", "#364fc7", "#d6336c", "#74b816", "#495057"];
  var personColor = {};
  function setPeople(emails) {
    personColor = {};
    emails.forEach(function (e, i) { personColor[e] = PALETTE[i % PALETTE.length]; });
  }
  function colorOf(email) { return personColor[email] || "#8a90a0"; }
  function dot(email) { return '<span class="pp-pdot" style="--c:' + colorOf(email) + '"></span>'; }
  /* Motivos (Lead Quality): color fijo por motivo, en el orden de la lista del backend. */
  var REASON_PALETTE = ["#0f6e6e", "#7cc4d6", "#b8417f", "#f2a7c9", "#2350a0", "#f08b5a", "#e8b931",
    "#4caf63", "#b08ad4", "#e03e3e", "#495057", "#8f5a00", "#0b7285"];
  var reasonColorMap = {};
  function setReasons(list) {
    reasonColorMap = {};
    list.forEach(function (r, i) { reasonColorMap[r] = REASON_PALETTE[i % REASON_PALETTE.length]; });
  }
  function reasonColor(r) { return reasonColorMap[r] || "#8a90a0"; }

  /* Inicio / fin de cada BDR (prospect_bdr_tenure, 2026-11-13): viene con cada panel y es una
     sola para todos. En el mapa de calor: línea al empezar y al terminar, meses fuera en gris. */
  var TENURE = {};
  function fmtDay(s) { var d = parse(s); return d.getDate() + "-" + MONTHS[d.getMonth()] + "-" + d.getFullYear(); }
  function endText(t) {
    if (!t || !t.end) return "";
    return (t.reason === "role_change" ? "Pasó a " + (t.role || "otro puesto") : "Dejó Vintti") + " el " + fmtDay(t.end);
  }
  /* Marca de una celda (persona × período): {cls, tip}. */
  function tenureMark(email, k, freq) {
    var t = TENURE[email];
    if (!t) return { cls: "", tip: "" };
    var sk = t.start ? periodKey(t.start, freq) : null, ek = t.end ? periodKey(t.end, freq) : null;
    var cls = [], tip = [];
    if ((sk && k < sk) || (ek && k > ek)) { cls.push("is-out"); tip.push(sk && k < sk ? "Todavía no era BDR" : "Ya no era BDR"); }
    if (sk && k === sk) { cls.push("is-start"); tip.push("Empezó el " + fmtDay(t.start)); }
    if (ek && k === ek) { cls.push("is-end"); tip.push(endText(t)); }
    return { cls: cls.join(" "), tip: tip.join(" · ") };
  }
  function tenureChip(email) {
    var t = TENURE[email];
    if (!t || !t.end) return "";
    var d = parse(t.end);
    var txt = t.reason === "role_change" ? "→ " + (t.role || "otro puesto") : "hasta " + MONTHS[d.getMonth()] + " ’" + String(d.getFullYear()).slice(2);
    return '<span class="pp-tenure-chip" title="' + esc(endText(t)) + '">' + esc(txt) + "</span>";
  }

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
  // El título de arriba sigue a la frecuencia del panel visible (Monthly / Weekly / Quarterly).
  var FREQ_EN = { month: "Monthly", week: "Weekly", quarter: "Quarterly" };
  /* Qué cambia entre métricas; el panel (CountByBdr) es el mismo. */
  var METRICS = {
    sql: { name: "SQLs", noun: "SQLs", one: "SQL", many: "SQLs", dateLabel: "SQL Date", withDeal: true,
      def: "Contactos con un negocio que tiene <em>SQL Date</em>, agrupados por la SQL Date del negocio y por " +
        "<em>Scheduled By</em> del contacto (quién agendó la reunión). Un contacto cuenta una vez por SQL Date. " +
        "«SQL Date» existe desde fines de nov-2025: antes no hay datos." },
    intro: { name: "Intro Calls", noun: "Intro calls", one: "intro call", many: "intro calls", dateLabel: "Date of Meeting Scheduled", withDeal: false,
      def: "Contactos con reunión agendada, agrupados por <em>Date of Meeting Scheduled</em> (el día en que se agendó) y por " +
        "<em>Scheduled By</em> (quién la agendó). Un contacto, una intro call." },
    // Lead Quality (2026-11-07): por qué las intro calls no pasaron a SQL. El general desglosa
    // por motivo; «x BDR» por persona, con un desplegable de motivo que arranca en Timing.
    lq: { name: "Lead Quality", fixedHeading: true, subtitle: "Reasons why intro call were not SQL",
      noun: "Leads perdidos", one: "lead perdido", many: "leads perdidos", dateLabel: "Meeting Date & Time", withDeal: false,
      showReason: true, groupKey: "reason", topLabel: "Motivo principal",
      word: { all: "Todos los motivos", none: "Ningún motivo", plural: "motivos", one: "1 motivo", head: "Motivo", icon: "fa-tags" },
      def: "Intro calls que no pasaron a SQL: contactos con <em>MQL (AE) Lost Reason</em> (incluye el motivo copiado de su " +
        "negocio), agrupados por mes de <em>Meeting Date &amp; Time</em> y por motivo." },
    lqb: { name: "Lead Quality", fixedHeading: true, subtitle: "Reasons why intro call were not SQL",
      noun: "Leads perdidos", one: "lead perdido", many: "leads perdidos", dateLabel: "Meeting Date & Time", withDeal: false,
      showReason: true, reasonFilter: "Timing",
      def: "Intro calls que no pasaron a SQL: contactos con <em>MQL (AE) Lost Reason</em> (incluye el motivo copiado de su " +
        "negocio), agrupados por mes de <em>Meeting Date &amp; Time</em> y por <em>Scheduled By</em>. El desplegable " +
        "<em>Motivo</em> arranca en Timing, como el reporte de HubSpot." },
    // Not ICP Reason: empresas (no contactos), sin fecha. Drawer y CSV de empresas.
    icp: { kind: "company", noun: "Empresas Not ICP", one: "empresa", many: "empresas",
      def: "Todas las empresas con <em>Not ICP Reason</em> cargado (cualquiera de los 6 motivos), por motivo y por " +
        "<em>Prospecting Owner</em>. Sin fecha, igual que el reporte de HubSpot. Las que no tienen owner van como «Sin owner». " +
        "Se calcula en vivo con los datos del Hub." }
  };
  var BDR_WORD = { all: "Todos los BDRs", none: "Ningún BDR", plural: "BDRs", one: "1 BDR", head: "BDR", icon: "fa-user-group" };
  function panel(metric, key, title, team) {
    var m = METRICS[metric];
    return { key: key, title: title, group: m.fixedHeading ? m.name : m.name + " - Monthly YTD", subtitle: m.subtitle || "",
      render: function (el) { return CountByBdr(el, { key: key, uid: this.uid, title: title, team: team, m: m }); },
      heading: function (inst) {
        return m.fixedHeading ? m.name : m.name + " - " + FREQ_EN[(inst && inst.freq()) || "month"] + " YTD";
      } };
  }
  var PANELS = [
    panel("sql", "sqls_by_bdr", "SQLs by BDR"),
    panel("sql", "sqls_by_bdr_vinttikids", "SQLs by BDR · VinttiKids", "VinttiKids"),
    panel("sql", "sqls_by_bdr_nextgen", "SQLs by BDR · NextGen", "NextGen"),
    panel("intro", "intro_calls", "Intro calls by BDR"),
    panel("intro", "intro_calls_vinttikids", "Intro calls by BDR · VinttiKids", "VinttiKids"),
    panel("intro", "intro_calls_nextgen", "Intro calls by BDR · NextGen", "NextGen"),
    panel("lq", "lead_quality", "Lead Quality"),
    panel("lq", "lead_quality_vinttikids", "Lead Quality · VinttiKids", "VinttiKids"),
    panel("lq", "lead_quality_nextgen", "Lead Quality · NextGen", "NextGen"),
    panel("lqb", "lead_quality", "Lead Quality x BDR"),
    panel("lqb", "lead_quality_vinttikids", "Lead Quality x BDR · VinttiKids", "VinttiKids"),
    panel("lqb", "lead_quality_nextgen", "Lead Quality x BDR · NextGen", "NextGen"),
    // Rendimiento de Islas (2026-11-10): reportes de empresas, sin eje de tiempo.
    { key: "not_icp_reason", title: "Not ICP Reason", group: "Rendimiento de Islas",
      render: function (el) { return ByCategory(el, { key: "not_icp_reason", uid: this.uid, title: "Not ICP Reason", m: METRICS.icp }); } },
    // Mismas filas, eje dado vuelta: una barra por BDR, tramos por motivo.
    { key: "not_icp_reason", title: "Not ICP Reason <> BDR", group: "Rendimiento de Islas",
      render: function (el) { return ByCategory(el, { key: "not_icp_reason", uid: this.uid, title: "Not ICP Reason <> BDR", m: METRICS.icp, pivot: true }); } },
    // Una barra por «Semana» de la empresa (la de Clay / HubSpot), tramos por motivo.
    { key: "not_icp_reason", title: "Not ICP Reason <> Semana", group: "Rendimiento de Islas",
      render: function (el) { return ByCategory(el, { key: "not_icp_reason", uid: this.uid, title: "Not ICP Reason <> Semana", m: METRICS.icp, dim: "week" }); } },
    // Barras por motivo, tramos por Lead Source.
    { key: "not_icp_reason", title: "Not ICP Reason - Lead Source", group: "Rendimiento de Islas",
      render: function (el) { return ByCategory(el, { key: "not_icp_reason", uid: this.uid, title: "Not ICP Reason - Lead Source", m: METRICS.icp, seg: "source" }); } }
  ];
  // Dos paneles pueden leer el mismo endpoint (Lead Quality y su «x BDR»): el id del DOM y la
  // preferencia guardada van por `uid`, no por `key`.
  PANELS.forEach(function (p, i) { p.uid = p.key + "__" + i; });

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
        PANELS.forEach(function (p, i) { if (p.uid === saved || p.key === saved) current = i; });
      } catch (e) {}
      var groups = [];
      PANELS.forEach(function (p) { if (groups.indexOf(p.group) === -1) groups.push(p.group); });
      root.innerHTML =
        '<nav class="pp-nav" aria-label="Paneles">' +
          '<button type="button" class="pp-nav__arrow" data-nav="-1" aria-label="Panel anterior"><i class="fa-solid fa-chevron-left"></i></button>' +
          '<div class="pp-nav__mid"><span class="pp-nav__group" data-nav-group></span>' +
            '<span class="pp-nav__sub" data-nav-sub hidden></span>' +
            '<select class="pr-filter__input pp-nav__select" data-nav-select aria-label="Elegir panel">' +
            groups.map(function (g) {
              return '<optgroup label="' + esc(g) + '">' + PANELS.map(function (p, i) {
                return p.group === g ? '<option value="' + i + '">' + esc(p.title) + "</option>" : "";
              }).join("") + "</optgroup>";
            }).join("") + "</select></div>" +
          '<span class="pp-nav__count" data-nav-count></span>' +
          '<button type="button" class="pp-nav__arrow" data-nav="1" aria-label="Panel siguiente"><i class="fa-solid fa-chevron-right"></i></button>' +
        "</nav>" +
        PANELS.map(function (p) { return '<section class="pp-card" id="pp-' + p.uid + '" hidden></section>'; }).join("");
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
    var sub = root.querySelector("[data-nav-sub]");
    sub.textContent = p.subtitle || "";
    sub.hidden = !p.subtitle;
  }

  function go(i, first) {
    var n = PANELS.length;
    i = ((i % n) + n) % n;  // las flechas dan la vuelta
    current = i;
    try { localStorage.setItem(CUR_KEY, PANELS[i].uid); } catch (e) {}
    PANELS.forEach(function (p, j) {
      var el = document.getElementById("pp-" + p.uid);
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
  var drawer = null, drawerRows = [], drawerTitle = "", drawerM = null;
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
      if (dl && window.ProspectingDeals && (P().me() || {}).can_see_deals) return window.ProspectingDeals.open({ dealId: Number(dl.getAttribute("data-pp-deal")) });
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

  function openDetail(title, sub, rows, m) {
    ensureDrawer();
    document.getElementById("ppDCsv").hidden = false;
    document.getElementById("ppDBody").onclick = null;
    drawerRows = rows;
    drawerTitle = title;
    drawerM = m;
    document.getElementById("ppDTitle").textContent = title;
    document.getElementById("ppDSub").textContent = sub;
    if (m.kind === "company") {
      document.getElementById("ppDBody").innerHTML = rows.length ? '<div class="pp-dtable-wrap"><table class="pp-dtable"><thead><tr>' +
        "<th>Empresa</th><th>Motivo</th><th>Semana</th><th>Lead Source</th><th>Status</th><th>Owner</th></tr></thead><tbody>" +
        rows.slice(0, 1500).map(function (r) {
          return '<tr><td><a class="pp-link" href="prospecting-company.html?id=' + r.company_id + '" target="_blank" rel="noopener"><strong>' +
              esc(r.name || r.domain || "#" + r.company_id) + "</strong></a>" +
              (r.domain ? '<div class="pr-note">' + esc(r.domain) + "</div>" : "") + "</td>" +
            '<td><span class="pp-pdot" style="--c:' + reasonColor(r.reason) + '"></span>' + esc(r.reason) + "</td>" +
            "<td>" + esc(r.week || "—") + "</td>" +
            "<td>" + esc(r.lead_source && r.lead_source !== "HubSpot" ? r.lead_source : "—") + "</td>" +
            "<td>" + esc(r.status || "—") + "</td>" +
            "<td>" + (r.owner ? dot(r.owner) + esc(r.owner_name || r.owner) : '<span class="pr-note">Sin owner</span>') + "</td></tr>";
        }).join("") + "</tbody></table></div>" +
        (rows.length > 1500 ? '<p class="pr-note">Se muestran 1500 de ' + rows.length + ": el CSV trae todas.</p>" : "")
        : '<p class="pr-note">Sin ' + esc(m.many) + " en esta selección.</p>";
      drawer.classList.add("is-open");
      drawer.setAttribute("aria-hidden", "false");
      return;
    }
    document.getElementById("ppDBody").innerHTML = rows.length ? '<div class="pp-dtable-wrap"><table class="pp-dtable"><thead><tr>' +
      "<th>Contacto</th><th>Empresa</th>" + (m.withDeal ? "<th>Negocio</th>" : "") + "<th>" + esc(m.dateLabel) + "</th>" +
      (m.showReason ? "<th>Motivo</th>" : "") + "<th>Meeting</th><th>Scheduled By</th></tr></thead><tbody>" +
      rows.map(function (r) {
        return "<tr><td>" + '<button type="button" class="pp-link" data-pp-contact="' + r.contact_id + '"><strong>' +
            esc(r.contact_name || r.email || "#" + r.contact_id) + "</strong></button>" +
            (r.contact_name && r.email ? '<div class="pr-note">' + esc(r.email) + "</div>" : "") + "</td>" +
          "<td>" + (r.company_id ? '<a class="pp-link" href="prospecting-company.html?id=' + r.company_id + '" target="_blank" rel="noopener">' +
            esc(r.company_name || "—") + "</a>" : '<span class="pr-note">Sin empresa</span>') + "</td>" +
          // Los BDRs no abren negocios (2026-11-09: el server les da 403): sólo el nombre, sin link.
          (m.withDeal ? "<td>" + ((P().me() || {}).can_see_deals
              ? '<button type="button" class="pp-link" data-pp-deal="' + r.deal_id + '">' + esc(r.deal_name || "#" + r.deal_id) + "</button>"
              : "<span>" + esc(r.deal_name || "#" + r.deal_id) + "</span>") +
            (r.stage_label ? '<div class="pr-note">' + esc(r.stage_label) + "</div>" : "") + "</td>" : "") +
          "<td>" + esc(P().fmtDate(r.date)) + "</td>" +
          (m.showReason ? '<td><span class="pp-pdot" style="--c:' + reasonColor(r.reason) + '"></span>' + esc(r.reason || "—") + "</td>" : "") +
          "<td>" + esc(r.meeting_datetime ? P().fmtDateTime(r.meeting_datetime) : "—") + "</td>" +
          "<td>" + dot(r.scheduled_by) + esc(r.scheduled_by_name || r.scheduled_by) + "</td></tr>";
      }).join("") + "</tbody></table></div>" : '<p class="pr-note">Sin ' + esc(m.many) + " en esta selección.</p>";
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
  }

  function exportCsv() {
    var m = drawerM || METRICS.sql;
    var cols = m.kind === "company"
      ? [["name", "Empresa"], ["domain", "Dominio"], ["reason", "Not ICP Reason"], ["week", "Semana"], ["lead_source", "Lead Source"], ["status", "Prospecting Status"],
         ["owner_name", "Prospecting Owner"], ["owner", "Prospecting Owner (email)"], ["company_id", "ID"]]
      : [["contact_name", "Contacto"], ["email", "Email"], ["company_name", "Empresa"]]
      .concat(m.withDeal ? [["deal_name", "Negocio"], ["stage_label", "Etapa"]] : [["lead_life", "Lead Life"]])
      .concat(m.showReason ? [["reason", "MQL (AE) Lost Reason"]] : [])
      .concat([["date", m.dateLabel], ["meeting_datetime", "Meeting Date & Time"],
        ["scheduled_by_name", "Scheduled By"], ["scheduled_by", "Scheduled By (email)"]]);
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

  /* «Altas y bajas»: la tabla de inicio / fin de cada BDR, editable (sólo staff; el server
     frena igual). Usa el drawer del detalle sin el botón de CSV. Al guardar recarga los paneles
     ya armados, así la línea se mueve en todos. */
  function openTenure() {
    ensureDrawer();
    drawerM = null;
    document.getElementById("ppDTitle").textContent = "Altas y bajas de BDRs";
    document.getElementById("ppDSub").textContent = "Cuándo empezó y terminó cada persona. Marca la línea del mapa de calor en todos los paneles.";
    document.getElementById("ppDCsv").hidden = true;
    var emails = Object.keys(TENURE);
    Object.keys(personColor).forEach(function (e) { if (emails.indexOf(e) === -1) emails.push(e); });
    emails.sort(function (a, b) {
      var x = (TENURE[a] || {}).start || "9999", y = (TENURE[b] || {}).start || "9999";
      return x < y ? -1 : x > y ? 1 : a.localeCompare(b);
    });
    var body = document.getElementById("ppDBody");
    body.innerHTML = '<div class="pp-dtable-wrap"><table class="pp-dtable pp-tenure"><thead><tr><th>Persona</th><th>Inicio</th><th>Fin</th><th>Motivo del fin</th><th></th></tr></thead><tbody>' +
      emails.map(function (e) {
        var t = TENURE[e] || {};
        return '<tr data-te="' + esc(e) + '"><td>' + dot(e) + "<strong>" + esc(t.name || e) + '</strong><div class="pr-note">' + esc(e) + "</div></td>" +
          '<td><input type="date" class="pr-filter__input" data-ts value="' + esc(t.start || "") + '"></td>' +
          '<td><input type="date" class="pr-filter__input" data-tend value="' + esc(t.end || "") + '"></td>' +
          '<td><select class="pr-filter__input" data-tr data-nosearch><option value="">—</option>' +
            '<option value="left"' + (t.reason === "left" ? " selected" : "") + ">Dejó Vintti</option>" +
            '<option value="role_change"' + (t.reason === "role_change" ? " selected" : "") + ">Cambió de puesto</option></select></td>" +
          '<td><button type="button" class="pr-btn" data-tsave>Guardar</button> <span class="pr-note" data-tmsg></span></td></tr>';
      }).join("") + "</tbody></table></div>";
    body.onclick = function (ev) {
      var b = ev.target.closest("[data-tsave]");
      if (!b) return;
      var tr = b.closest("tr"), msg = tr.querySelector("[data-tmsg]");
      var payload = { email: tr.getAttribute("data-te"), start: tr.querySelector("[data-ts]").value || null,
        end: tr.querySelector("[data-tend]").value || null, reason: tr.querySelector("[data-tr]").value || null };
      if (payload.end && !payload.reason) { msg.textContent = "Elegí el motivo"; return; }
      b.disabled = true; msg.textContent = "Guardando…";
      P().api("/prospecting/panels/tenure", { method: "PUT", body: JSON.stringify(payload) })
        .then(function (r) {
          TENURE = r.tenure || TENURE;
          msg.textContent = "Guardado";
          PANELS.forEach(function (p) { if (p.inst && p.inst.reload) p.inst.reload(); });
        })
        .catch(function (err) { msg.textContent = err.message; })
        .then(function () { b.disabled = false; });
    };
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
  }

  /* =================================================================
     Panel de conteo por persona (SQLs, Intro calls…)
     ================================================================= */
  /* opts: {key (panel del backend), title, team?}. El mismo panel sirve para todo el equipo y
     para un equipo (VinttiKids): cambian sólo las filas que manda el backend. */
  function CountByBdr(el, opts) {
    var M = opts.m;
    var W = M.word || BDR_WORD;
    // Por qué se desglosa: la persona (Scheduled By) o el motivo (Lead Quality).
    var GK = M.groupKey || "scheduled_by";
    function gName(r) { return GK === "reason" ? r.reason : (r.scheduled_by_name || r.scheduled_by); }
    function gColor(k) { return GK === "reason" ? reasonColor(k) : colorOf(k); }
    function gDot(k) { return '<span class="pp-pdot" style="--c:' + gColor(k) + '"></span>'; }
    var today = P().todayIso();
    var DEF = { freq: "month", from: today.slice(0, 4) + "-01-01", to: today, reason: M.reasonFilter || "" };
    var st = { freq: DEF.freq, from: DEF.from, to: DEF.to, reason: DEF.reason, bdrs: null, rows: [], def: null, loading: true };
    var PREF = "pp_" + (opts.uid || opts.key) + "_v1";
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
          (M.reasonFilter ? '<label class="pp-date"><span>Motivo</span><select class="pr-filter__input pp-reason" data-reason data-nosearch></select></label>' : "") +
          '<details class="pp-ms"><summary class="pr-btn"><i class="fa-solid ' + W.icon + '"></i> <span data-ms-label>' + esc(W.all) + "</span></summary>" +
            '<div class="pp-ms__pop" data-ms-pop></div></details>' +
          '<button type="button" class="pr-btn pp-reset" data-reset hidden title="Volver a los filtros de inicio">' +
            '<i class="fa-solid fa-rotate-left"></i> Restablecer</button>' +
          (GK !== "reason" && ((P().me() || {}).can_delete) ? '<button type="button" class="pr-btn" data-tenure title="Cuándo empezó y terminó cada BDR">' +
            '<i class="fa-solid fa-calendar-days"></i> Altas y bajas</button>' : "") +
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
          if (r.tenure) TENURE = r.tenure;
          if (r.people_order) setPeople(r.people_order);
          if (r.reasons) setReasons(r.reasons);
          render();
        })
        .catch(function (err) { st.loading = false; q("[data-chart]").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>"; });
    }

    function people() {
      var m = {};
      st.rows.forEach(function (r) { m[r[GK]] = gName(r); });
      return Object.keys(m).map(function (e) { return { email: e, name: m[e] }; })
        .sort(function (a, b) { return a.name.localeCompare(b.name, "es"); });
    }
    function rowsOn() {
      return st.rows.filter(function (r) {
        return (!st.bdrs || st.bdrs.indexOf(r[GK]) !== -1) && (!st.reason || r.reason === st.reason);
      });
    }

    function renderDef() {
      var d = st.def || {};
      q("[data-def]").innerHTML = "<strong>Cómo se cuenta.</strong> " + M.def + " " +
        (d.team ? "Sólo el equipo " + esc(opts.team || "") + ": " + esc(d.team.join(", ")) + ". " : "") +
        "Igual que el reporte de HubSpot: Scheduled By conocido y fuera de " + esc((d.excluded_schedulers || []).join(", ")) +
        ((d.internal_domains || []).length ? "; contactos fuera del equipo interno (" +
          esc(d.internal_domains.map(function (x) { return "@" + x; }).join(", ")) + ")" : "") +
        "; con Meeting Date &amp; Time cargada. Se calcula en vivo con los datos del Hub.";
    }

    function renderMs() {
      var ps = people();
      q("[data-ms-pop]").innerHTML = '<label class="pr-check"><input type="checkbox" data-ms-all' + (st.bdrs ? "" : " checked") + "> <strong>Todos</strong></label>" +
        ps.map(function (p) {
          var on = !st.bdrs || st.bdrs.indexOf(p.email) !== -1;
          return '<label class="pr-check"><input type="checkbox" data-ms="' + esc(p.email) + '"' + (on ? " checked" : "") + "> " + gDot(p.email) + esc(p.name) + "</label>";
        }).join("");
      q("[data-ms-label]").textContent = !st.bdrs ? W.all :
        !st.bdrs.length ? W.none :
        st.bdrs.length === 1 ? (ps.filter(function (p) { return p.email === st.bdrs[0]; })[0] || {}).name || W.one :
        st.bdrs.length + " " + W.plural;
    }
    /* Desplegable de motivo («x BDR»): los motivos que hay en las filas, más «Todos». */
    function renderReasonSel() {
      var sel = q("[data-reason]");
      if (!sel) return;
      var seen = {};
      st.rows.forEach(function (r) { if (r.reason) seen[r.reason] = (seen[r.reason] || 0) + 1; });
      var list = Object.keys(seen).sort(function (a, b) { return seen[b] - seen[a] || a.localeCompare(b); });
      if (st.reason && list.indexOf(st.reason) === -1) list.unshift(st.reason);
      sel.innerHTML = '<option value="">Todos los motivos</option>' + list.map(function (r) {
        return '<option value="' + esc(r) + '">' + esc(r) + "</option>";
      }).join("");
      sel.value = st.reason;
    }

    function isDefault() { return st.freq === DEF.freq && st.from === DEF.from && st.to === DEF.to && !st.bdrs && st.reason === DEF.reason; }
    function reset() {
      var reload = st.from !== DEF.from || st.to !== DEF.to;
      st.freq = DEF.freq; st.from = DEF.from; st.to = DEF.to; st.bdrs = null; st.reason = DEF.reason;
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
      renderReasonSel();
      var rows = rowsOn();
      var periods = periodsBetween(st.from, st.to, st.freq);
      var tot = {}, by = {}, names = {};
      periods.forEach(function (k) { tot[k] = 0; });
      rows.forEach(function (r) {
        var k = periodKey(r.date, st.freq);
        if (!(k in tot)) return;
        tot[k]++;
        var g = r[GK];
        by[g] = by[g] || {};
        by[g][k] = (by[g][k] || 0) + 1;
        names[g] = gName(r);
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
        kpi(M.noun + " en el rango", total, periods.length + " " + (fname === "mes" ? "meses" : fname + "s") + " · " + avgLabel + " " + fmt1(avg) +
          (full.length < periods.length ? " · sin " + periodLabel(curK, st.freq, true) + " (en curso)" : "")) +
        kpi(capital(fname) + " actual · " + (last ? periodLabel(last, st.freq) : "—"), last ? tot[last] : 0,
          delta == null ? "" : '<span class="pp-delta ' + (delta > 0 ? "is-up" : delta < 0 ? "is-down" : "") + '">' +
            (delta > 0 ? "▲ +" : delta < 0 ? "▼ " : "= ") + delta + "</span> vs " + periodLabel(prev, st.freq), true) +
        kpi("Mejor " + fname, best && tot[best] ? tot[best] : 0, best && tot[best] ? periodLabel(best, st.freq) : "—") +
        kpi(M.topLabel || ("Más " + M.many), ranking[0] ? ranking[0].total : 0, ranking[0] ? esc(ranking[0].name) : "—", true);

      // Barras del total
      var max = Math.max.apply(null, periods.map(function (k) { return tot[k]; }).concat([1]));
      var step = Math.ceil(periods.length / 18);  // con muchas semanas, una etiqueta cada tanto
      q("[data-chart]").innerHTML = '<div class="pp-bars" style="--n:' + periods.length + '">' + periods.map(function (k, i) {
        var h = tot[k] ? Math.max(4, Math.round(tot[k] / max * 100)) : 0;
        return '<button type="button" class="pp-bar' + (k === last ? " is-current" : "") + '" data-period="' + k + '" title="' +
            esc(periodLabel(k, st.freq) + ": " + tot[k] + " " + (tot[k] === 1 ? M.one : M.many)) + '">' +
          '<span class="pp-bar__track"><span class="pp-bar__fill" style="height:' + h + '%">' +
            (tot[k] ? '<span class="pp-bar__val">' + tot[k] + "</span>" : "") + "</span></span>" +
          '<span class="pp-bar__x">' + (i % step === 0 ? esc(periodLabel(k, st.freq, true)) : "&nbsp;") + "</span></button>";
      }).join("") + "</div>";

      // Ranking (mapa de calor)
      var cmax = 1;
      ranking.forEach(function (p) { periods.forEach(function (k) { cmax = Math.max(cmax, by[p.email][k] || 0); }); });
      q("[data-rank]").innerHTML = ranking.length ? '<div class="pp-rank__wrap"><table class="pp-heat"><thead><tr><th class="pp-heat__name">' + esc(W.head) + "</th>" +
        periods.map(function (k) { return '<th><button type="button" data-period="' + k + '">' + esc(periodLabel(k, st.freq, true)) + "</button></th>"; }).join("") +
        '<th class="pp-heat__tot">Total</th></tr></thead><tbody>' +
        ranking.map(function (p, i) {
          var person = GK !== "reason";
          return '<tr><th class="pp-heat__name"><button type="button" data-bdr="' + esc(p.email) + '"><span class="pp-rankno" style="--c:' + gColor(p.email) + '">' + (i + 1) + "</span>" + esc(p.name) +
              (person ? tenureChip(p.email) : "") + "</button></th>" +
            periods.map(function (k) {
              var v = by[p.email][k] || 0;
              var pct = v ? Math.round(14 + v / cmax * 76) : 0;
              var tm = person ? tenureMark(p.email, k, st.freq) : { cls: "", tip: "" };
              return '<td class="pp-tcell ' + tm.cls + '" style="--c:' + gColor(p.email) + '"' + (tm.tip ? ' title="' + esc(tm.tip) + '"' : "") + ">" +
                (v ? '<button type="button" class="pp-cell" data-bdr="' + esc(p.email) + '" data-period="' + k + '" style="--pct:' + pct + '%;--c:' + gColor(p.email) + '"' +
                (pct > 55 ? ' data-dark="1"' : "") + ' title="' + esc(p.name + " · " + periodLabel(k, st.freq) + ": " + v + (tm.tip ? " · " + tm.tip : "")) + '">' + v + "</button>" : '<span class="pp-dot">·</span>') + "</td>";
            }).join("") +
            '<td class="pp-heat__tot"><button type="button" data-bdr="' + esc(p.email) + '">' + p.total + "</button></td></tr>";
        }).join("") +
        '</tbody><tfoot><tr><th class="pp-heat__name">Total</th>' +
        periods.map(function (k) { return '<td><button type="button" data-period="' + k + '">' + (tot[k] || '<span class="pp-dot">·</span>') + "</button></td>"; }).join("") +
        '<td class="pp-heat__tot"><button type="button" data-all>' + total + "</button></td></tr></tfoot></table></div>"
        : '<p class="pr-note">Sin ' + esc(M.many) + " en este rango.</p>";
    }

    function kpi(label, value, sub, accent) {
      return '<div class="pp-kpi' + (accent ? " pp-kpi--accent" : "") + '"><span class="pp-kpi__label">' + esc(label) + "</span>" +
        '<strong class="pp-kpi__value">' + value + '</strong><span class="pp-kpi__sub">' + (sub || "") + "</span></div>";
    }
    function fmt1(n) { return (Math.round(n * 10) / 10).toString().replace(".", ","); }
    function capital(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

    function detail(period, bdr) {
      var rows = rowsOn().filter(function (r) {
        var k = periodKey(r.date, st.freq);
        return r.date >= st.from && r.date <= st.to &&
          (!period || k === period) && (!bdr || r[GK] === bdr);
      });
      var who = bdr ? (rows[0] && gName(rows[0])) || bdr : (st.bdrs ? q("[data-ms-label]").textContent : (opts.team || W.all));
      if (st.reason) who = st.reason + " · " + who;
      var when = period ? periodLabel(period, st.freq) : P().fmtDate(st.from) + " – " + P().fmtDate(st.to);
      openDetail(M.noun + " · " + who + " · " + when, rows.length + " contacto" + (rows.length === 1 ? "" : "s"), rows, M);
    }

    // Eventos
    el.addEventListener("click", function (e) {
      if (e.target.closest("[data-reset]")) return reset();
      if (e.target.closest("[data-tenure]")) return openTenure();
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
      if (t.matches("[data-reason]")) { st.reason = t.value; render(); return; }
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

  /* =================================================================
     Panel por categoría (Not ICP Reason): barras apiladas, sin tiempo
     ================================================================= */
  /* Una barra por motivo (en el orden fijo del backend) con un tramo por owner, en su color de
     siempre; abajo el mapa de calor owner × motivo. Barra, celda y detalle salen de las mismas filas. */
  var NONE = "__none__";
  function ByCategory(el, opts) {
    var M = opts.m, W = BDR_WORD;
    // Eje de las barras: motivo (default), owner (`pivot`) o semana (`dim: "week"`). Con owner o
    // semana, los tramos son los motivos. El filtro de BDRs siempre es por owner.
    var WK = opts.dim === "week", PIV = !!opts.pivot || WK;
    // `seg: "source"`: barras por motivo, tramos por Lead Source (en vez de owner).
    var SRC = opts.seg === "source";
    var st = { bdrs: null, rows: [], reasons: [], loading: true };
    function ok(r) { return r.owner || NONE; }
    function oName(r) { return r.owner ? (r.owner_name || r.owner) : "Sin owner"; }
    function oColor(k) { return k === NONE ? "#c3c7d1" : colorOf(k); }
    function oDot(k) { return '<span class="pp-pdot" style="--c:' + oColor(k) + '"></span>'; }
    // Fila del ranking / barra del pivot: el owner, o la semana («Semana 38», «Sin semana» al final).
    var NOWK = "__noweek__";
    // Lead Source: la importación de HubSpot puso «HubSpot» donde HubSpot no tenía valor, así
    // que se lee como «Sin valor» (igual que el reporte).
    var NOSRC = "__nosource__";
    function srcKey(r) { var v = r.lead_source; return !v || v === "HubSpot" ? NOSRC : v; }
    var SRC_COLORS = { Clay: "#6c38ff", Apollo: "#003bff", "Apollo Recycle": "#4ba9ff", Manual: "#5c8a00" };
    function srcColor(k) { return k === NOSRC ? "#c3c7d1" : SRC_COLORS[k] || reasonColor(k); }
    function rk(r) { return WK ? (r.week || NOWK) : SRC ? srcKey(r) : ok(r); }
    function rName(r) { return WK ? (r.week || "Sin semana") : SRC ? (srcKey(r) === NOSRC ? "Sin valor" : r.lead_source) : oName(r); }
    function rColor(k) { return WK ? (k === NOWK ? "#c3c7d1" : "#6c38ff") : SRC ? srcColor(k) : oColor(k); }
    function rDot(k) { return WK ? "" : '<span class="pp-pdot" style="--c:' + rColor(k) + '"></span>'; }
    function isNone(k) { return k === NONE || k === NOWK || k === NOSRC; }
    function wkNum(name) { var n = parseInt(String(name).replace(/\D/g, ""), 10); return isNaN(n) ? 1e9 : n; }

    el.innerHTML =
      '<header class="pp-card__head"><div class="pp-card__title"><h2>' + esc(opts.title) + '</h2>' +
        '<button type="button" class="pp-info" data-pp-info aria-label="Cómo se calcula"><i class="fa-solid fa-circle-info"></i></button></div>' +
        '<div class="pp-controls">' +
          '<details class="pp-ms"><summary class="pr-btn"><i class="fa-solid ' + W.icon + '"></i> <span data-ms-label>' + esc(W.all) + "</span></summary>" +
            '<div class="pp-ms__pop" data-ms-pop></div></details>' +
          '<button type="button" class="pr-btn pp-reset" data-reset hidden title="Volver a los filtros de inicio">' +
            '<i class="fa-solid fa-rotate-left"></i> Restablecer</button>' +
        "</div></header>" +
      '<div class="pp-def" data-def hidden><strong>Cómo se cuenta.</strong> ' + M.def + "</div>" +
      '<div class="pp-kpis" data-kpis></div>' +
      '<div class="pp-chart" data-chart></div>' +
      '<div class="pp-rank" data-rank></div>';
    var q = function (sel) { return el.querySelector(sel); };

    function load() {
      st.loading = true;
      render();
      return P().api("/prospecting/panels/" + opts.key)
        .then(function (r) {
          st.rows = r.rows || []; st.reasons = r.reasons || []; st.loading = false;
          if (r.people_order) setPeople(r.people_order);
          if (r.reasons) setReasons(r.reasons);
          render();
        })
        .catch(function (err) { st.loading = false; q("[data-chart]").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>"; });
    }
    function people() {
      var m = {};
      st.rows.forEach(function (r) { m[ok(r)] = oName(r); });
      return Object.keys(m).map(function (e) { return { email: e, name: m[e] }; })
        .sort(function (a, b) { return (a.email === NONE) - (b.email === NONE) || a.name.localeCompare(b.name, "es"); });
    }
    function rowsOn() { return st.rows.filter(function (r) { return !st.bdrs || st.bdrs.indexOf(ok(r)) !== -1; }); }

    function renderMs() {
      var ps = people();
      q("[data-ms-pop]").innerHTML = '<label class="pr-check"><input type="checkbox" data-ms-all' + (st.bdrs ? "" : " checked") + "> <strong>Todos</strong></label>" +
        ps.map(function (p) {
          var on = !st.bdrs || st.bdrs.indexOf(p.email) !== -1;
          return '<label class="pr-check"><input type="checkbox" data-ms="' + esc(p.email) + '"' + (on ? " checked" : "") + "> " + oDot(p.email) + esc(p.name) + "</label>";
        }).join("");
      q("[data-ms-label]").textContent = !st.bdrs ? W.all : !st.bdrs.length ? W.none :
        st.bdrs.length === 1 ? (ps.filter(function (p) { return p.email === st.bdrs[0]; })[0] || {}).name || W.one :
        st.bdrs.length + " " + W.plural;
    }

    function render() {
      q("[data-reset]").hidden = !st.bdrs;
      refreshHeading();
      if (st.loading) {
        q("[data-kpis]").innerHTML = "";
        q("[data-chart]").innerHTML = '<p class="pr-note pp-loading">Cargando…</p>';
        q("[data-rank]").innerHTML = "";
        return;
      }
      renderMs();
      var rows = rowsOn(), R = st.reasons;
      var tot = {}, by = {}, names = {}, perOwner = {}, ownerName = {};
      R.forEach(function (x) { tot[x] = 0; });
      rows.forEach(function (r) {
        if (!(r.reason in tot)) return;
        var k = rk(r);
        tot[r.reason]++;
        by[k] = by[k] || {};
        by[k][r.reason] = (by[k][r.reason] || 0) + 1;
        names[k] = rName(r);
        perOwner[ok(r)] = (perOwner[ok(r)] || 0) + 1;
        ownerName[ok(r)] = oName(r);
      });
      var total = rows.length;
      var ranking = Object.keys(by).map(function (k) {
        var t = 0; R.forEach(function (x) { t += by[k][x] || 0; });
        return { email: k, name: names[k], total: t };
      }).sort(WK
        ? function (a, b) { return wkNum(a.name) - wkNum(b.name); }
        : function (a, b) { return isNone(a.email) - isNone(b.email) || b.total - a.total || a.name.localeCompare(b.name, "es"); });
      var top = R.slice().sort(function (a, b) { return tot[b] - tot[a]; })[0];
      var bestK = Object.keys(perOwner).filter(function (k) { return k !== NONE; })
        .sort(function (a, b) { return perOwner[b] - perOwner[a]; })[0];
      var bestP = bestK ? { email: bestK, name: ownerName[bestK], total: perOwner[bestK] } : null;
      var none = perOwner[NONE] || 0;
      var pct = function (n) { return total ? Math.round(n / total * 100) + "%" : "—"; };

      q("[data-kpis]").innerHTML =
        kpi(M.noun, fmtN(total), R.length + " motivos") +
        kpi("Motivo principal", top && tot[top] ? fmtN(tot[top]) : 0, top && tot[top] ? esc(top) + " · " + pct(tot[top]) : "—", true) +
        kpi("BDR con más", bestP ? fmtN(bestP.total) : 0, bestP ? oDot(bestP.email) + esc(bestP.name) + " · " + pct(bestP.total) : "—") +
        kpi("Sin owner", fmtN(none), pct(none) + " del total");

      // Barras apiladas. Por motivo (default): una barra por motivo, tramos por owner (el más
      // grande abajo). Con `pivot` («Not ICP Reason <> BDR»): una barra por owner (A→Z, «Sin
      // owner» al final, como HubSpot) y tramos por motivo, en sus colores fijos.
      var cols, segKeys, colTot, segColor, cell, colKind, segKind;
      if (PIV) {
        cols = (WK ? ranking.slice() : ranking.slice().sort(function (a, b) { return (a.email === NONE) - (b.email === NONE) || a.name.localeCompare(b.name, "es"); }))
          .map(function (p) { return { key: p.email, label: p.name, total: p.total }; });
        segKeys = R.map(function (x) { return { key: x, label: x }; });
        segColor = reasonColor;
        cell = function (c, sk) { return (by[c] || {})[sk] || 0; };
      } else {
        cols = R.map(function (x) { return { key: x, label: x, total: tot[x] }; });
        segKeys = ranking.map(function (p) { return { key: p.email, label: p.name }; });
        segColor = rColor;
        cell = function (c, sk) { return (by[sk] || {})[c] || 0; };
      }
      colKind = PIV ? "data-bdr" : "data-reason";
      segKind = PIV ? "data-reason" : "data-bdr";
      var max = Math.max.apply(null, cols.map(function (c) { return c.total; }).concat([1]));
      q("[data-chart]").innerHTML = '<div class="pp-stack' + (cols.length > 8 ? " pp-stack--many" : "") + '">' + cols.map(function (c) {
        var h = c.total ? Math.max(1.5, c.total / max * 100) : 0;
        var segs = segKeys.filter(function (sk) { return cell(c.key, sk.key); }).map(function (sk) {
          var v = cell(c.key, sk.key);
          var reason = PIV ? sk.key : c.key, bdr = PIV ? c.key : sk.key, name = PIV ? c.label : sk.label;
          return '<span class="pp-stack__seg" data-reason="' + esc(reason) + '" data-bdr="' + esc(bdr) + '" data-hl="' + esc(sk.key) +
            '" style="flex:' + v + ' 1 0;--c:' + segColor(sk.key) + '" data-v="' + v + '" data-name="' + esc(name) + '"></span>';
        }).join("");
        return '<div class="pp-stack__col"><div class="pp-stack__track">' +
            '<div class="pp-stack__bar" style="height:' + h + '%">' +
              (c.total ? '<button type="button" class="pp-stack__val" ' + colKind + '="' + esc(c.key) + '">' + fmtN(c.total) + "</button>" : "") +
              '<div class="pp-stack__segs">' + segs + "</div></div></div>" +
          '<button type="button" class="pp-stack__x" ' + colKind + '="' + esc(c.key) + '">' +
            (PIV ? rDot(c.key) : "") + esc(c.label) + "</button></div>";
      }).join("") + '<div class="pp-tip" data-tip hidden></div></div>' +
        '<div class="pp-legend">' + segKeys.map(function (sk) {
          return '<button type="button" ' + segKind + '="' + esc(sk.key) + '" data-hl="' + esc(sk.key) + '">' +
            '<span class="pp-pdot" style="--c:' + segColor(sk.key) + '"></span>' + esc(sk.label) + "</button>";
        }).join("") + "</div>";

      // Mapa de calor owner × motivo
      var cmax = 1;
      ranking.forEach(function (p) { R.forEach(function (x) { cmax = Math.max(cmax, by[p.email][x] || 0); }); });
      q("[data-rank]").innerHTML = ranking.length ? '<div class="pp-rank__wrap"><table class="pp-heat pp-heat--cats"><thead><tr><th class="pp-heat__name">' + esc(WK ? "Semana" : SRC ? "Lead Source" : W.head) + "</th>" +
        R.map(function (x) { return '<th><button type="button" data-reason="' + esc(x) + '">' + esc(x) + "</button></th>"; }).join("") +
        '<th class="pp-heat__tot">Total</th></tr></thead><tbody>' +
        ranking.map(function (p, i) {
          var c = rColor(p.email);
          return '<tr><th class="pp-heat__name"><button type="button" data-bdr="' + esc(p.email) + '">' +
              (WK ? "" : SRC ? rDot(p.email) : '<span class="pp-rankno" style="--c:' + c + '">' + (isNone(p.email) ? "–" : i + 1) + "</span>") + esc(p.name) + "</button></th>" +
            R.map(function (x) {
              var v = by[p.email][x] || 0;
              var pc = v ? Math.round(14 + v / cmax * 76) : 0;
              return "<td>" + (v ? '<button type="button" class="pp-cell" data-bdr="' + esc(p.email) + '" data-reason="' + esc(x) + '" style="--pct:' + pc + '%;--c:' + (WK ? reasonColor(x) : c) + '"' +
                (pc > 55 ? ' data-dark="1"' : "") + ' title="' + esc(p.name + " · " + x + ": " + v) + '">' + fmtN(v) + "</button>" : '<span class="pp-dot">·</span>') + "</td>";
            }).join("") +
            '<td class="pp-heat__tot"><button type="button" data-bdr="' + esc(p.email) + '">' + fmtN(p.total) + "</button></td></tr>";
        }).join("") +
        '</tbody><tfoot><tr><th class="pp-heat__name">Total</th>' +
        R.map(function (x) { return '<td><button type="button" data-reason="' + esc(x) + '">' + (tot[x] ? fmtN(tot[x]) : '<span class="pp-dot">·</span>') + "</button></td>"; }).join("") +
        '<td class="pp-heat__tot"><button type="button" data-all>' + fmtN(total) + "</button></td></tr></tfoot></table></div>"
        : '<p class="pr-note">Sin ' + esc(M.many) + " en esta selección.</p>";
    }

    function kpi(label, value, sub, accent) {
      return '<div class="pp-kpi' + (accent ? " pp-kpi--accent" : "") + '"><span class="pp-kpi__label">' + esc(label) + "</span>" +
        '<strong class="pp-kpi__value">' + value + '</strong><span class="pp-kpi__sub">' + (sub || "") + "</span></div>";
    }
    function fmtN(n) { return Number(n).toLocaleString("es-AR"); }

    function detail(reason, bdr) {
      var rows = rowsOn().filter(function (r) { return (!reason || r.reason === reason) && (!bdr || rk(r) === bdr); });
      var who = bdr ? (rows[0] ? rName(rows[0]) : bdr) : (st.bdrs ? q("[data-ms-label]").textContent : W.all);
      openDetail("Not ICP · " + (reason || "Todos los motivos") + " · " + who,
        fmtN(rows.length) + " empresa" + (rows.length === 1 ? "" : "s"), rows, M);
    }

    el.addEventListener("click", function (e) {
      if (e.target.closest("[data-reset]")) { st.bdrs = null; return render(); }
      if (e.target.closest("[data-pp-info]")) { q("[data-def]").hidden = !q("[data-def]").hidden; return; }
      if (e.target.closest("[data-all]")) return detail(null, null);
      var b = e.target.closest("[data-reason], [data-bdr]");
      if (b && !b.closest("[data-ms-pop]")) detail(b.getAttribute("data-reason"), b.getAttribute("data-bdr"));
    });
    /* Hover: resalta a esa persona en TODAS las barras (el resto se apaga) y muestra una
       tarjeta con nombre, motivo, cantidad y % de la barra. También desde la leyenda. */
    function hl(k) {
      var stack = q(".pp-stack");
      if (!stack) return;
      stack.classList.toggle("is-hl", !!k);
      stack.querySelectorAll(".pp-stack__seg").forEach(function (s) { s.classList.toggle("is-on", !!k && s.getAttribute("data-hl") === k); });
      el.querySelectorAll(".pp-legend [data-hl]").forEach(function (b) { b.classList.toggle("is-on", !!k && b.getAttribute("data-hl") === k); });
    }
    el.addEventListener("mouseover", function (e) {
      var seg = e.target.closest(".pp-stack__seg, .pp-legend [data-hl]");
      var tip = q("[data-tip]");
      if (!seg) { hl(null); if (tip) tip.hidden = true; return; }
      hl(seg.getAttribute("data-hl"));
      if (!tip || !seg.classList.contains("pp-stack__seg")) { if (tip) tip.hidden = true; return; }
      var reason = seg.getAttribute("data-reason"), v = Number(seg.getAttribute("data-v"));
      var t = 0;
      seg.parentNode.querySelectorAll(".pp-stack__seg").forEach(function (s) { t += Number(s.getAttribute("data-v")); });
      tip.innerHTML = '<div class="pp-tip__who">' + rDot(seg.getAttribute("data-bdr")) + esc(seg.getAttribute("data-name")) + "</div>" +
        '<div class="pp-tip__reason"><span class="pp-pdot" style="--c:' + reasonColor(reason) + '"></span>' + esc(reason) + "</div>" +
        '<div class="pp-tip__num"><strong>' + fmtN(v) + "</strong> empresa" + (v === 1 ? "" : "s") +
        '<span>' + Math.round(v / (t || 1) * 100) + (WK ? "% de la semana" : PIV ? "% del BDR" : "% del motivo") + "</span></div>" +
        '<div class="pp-tip__hint">Click para ver el detalle</div>';
      tip.hidden = false;
      var box = q(".pp-stack").getBoundingClientRect(), r = seg.getBoundingClientRect();
      var left = r.right - box.left + 10;
      if (left + 220 > box.width) left = r.left - box.left - 230;
      tip.style.left = left + "px";
      tip.style.top = Math.max(0, r.top - box.top + r.height / 2 - 40) + "px";
    });
    el.addEventListener("mouseleave", function () { hl(null); var tip = q("[data-tip]"); if (tip) tip.hidden = true; });
    el.addEventListener("change", function (e) {
      var t = e.target;
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
    return { reload: load };
  }

  window.ProspectingPanels = { show: show };
})();
