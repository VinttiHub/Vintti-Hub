/* =====================================================================
   Prospecting — Negocios (2026-11-04): el pipeline de HubSpot dentro del Hub.

   - Tablero por etapa (arrastrar una tarjeta = cambiar la etapa) o tabla.
   - Pipelines: Proceso De Contratación y Vintti AI Pipeline (GET /prospecting/deals/board).
   - Panel del negocio: propiedades (backend/prospecting/deal_fields.py, vía
     /prospecting/options → deals), empresa, contactos, cuenta / oportunidad del hub.
   - Pasar a una etapa que pide campos (SQL, NDA Sent, NDA Signed, Closed Lost) abre el
     popup de obligatorios: el server responde 409 + needs_fields.
   - SQL crea la cuenta del CRM y Deep Dive la oportunidad (backend/prospecting/deal_to_hub.py).

   Lo usan prospecting.html (sección Negocios) y prospecting-company.html (tarjeta Negocios).
   Depende de window.Prospecting y de window.ProspectingContacts (fieldControl/readFieldValue).
   ===================================================================== */
(function () {
  "use strict";

  function P() { return window.Prospecting; }
  function C() { return window.ProspectingContacts; }
  function esc(v) { return P().esc(v); }
  function $(id) { return document.getElementById(id); }
  function schema() { return P().options().deals || { fields: [], groups: [], pipelines: [] }; }
  function fieldOf(key) { return schema().fields.filter(function (f) { return f.key === key; })[0]; }
  function label(key) {
    if (key === "stage") return "Etapa";
    if (key === "pipeline") return "Pipeline";
    if (key === "company") return "Empresa";
    if (key === "contacts") return "Contactos";
    var f = fieldOf(key);
    return f ? f.label : key;
  }
  function isEmpty(v) { return v == null || v === "" || (Array.isArray(v) && !v.length); }

  var STATE_KEY = "prospecting_deals_v1";
  var st = { pipeline: "", view: "board", q: "", owner: "", created: "", close: "", sort: "", page: 1, dummy: false };
  try { Object.assign(st, JSON.parse(localStorage.getItem(STATE_KEY) || "{}")); } catch (e) {}
  function saveState() { try { localStorage.setItem(STATE_KEY, JSON.stringify(st)); } catch (e) {} }

  var PIPELINES = [];
  var bound = false;

  /* ---------- Formatos ---------- */
  function money(n) {
    var v = Number(n || 0);
    return v.toLocaleString("en-US", { maximumFractionDigits: 0 }) + " US$";
  }
  function ago(iso) {
    if (!iso) return "";
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (isNaN(s)) return "";
    if (s < 60) return "hace un momento";
    var m = Math.round(s / 60);
    if (m < 60) return "hace " + m + (m === 1 ? " minuto" : " minutos");
    var h = Math.round(m / 60);
    if (h < 24) return "hace " + h + (h === 1 ? " hora" : " horas");
    var d = Math.round(h / 24);
    if (d < 30) return d === 1 ? "hace un día" : "hace " + d + " días";
    var mo = Math.round(d / 30);
    return mo === 1 ? "hace un mes" : "hace " + mo + " meses";
  }
  function stagesOf(pkey) {
    var p = PIPELINES.filter(function (x) { return x.key === pkey; })[0];
    return p ? p.stages : [];
  }
  function stageLabel(pkey, skey) {
    var s = stagesOf(pkey).filter(function (x) { return x.key === skey; })[0];
    return s ? s.label : skey;
  }
  function isoDaysAgo(n) { var d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); }
  function isoDaysAhead(n) { var d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }

  function filters() {
    var f = { pipeline: st.pipeline, q: st.q, owner: st.owner };
    if (st.created) f.created_from = isoDaysAgo(Number(st.created));
    var today = P().todayIso();
    if (st.close === "overdue") { f.close_to = isoDaysAgo(1); }
    else if (st.close === "month") { f.close_from = today.slice(0, 8) + "01"; f.close_to = (function () {
      var d = new Date(); return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10); })(); }
    else if (st.close === "next30") { f.close_from = today; f.close_to = isoDaysAhead(30); }
    if (st.sort) f.sort = st.sort;
    if (st.dummy) f.dummy = "include";
    return f;
  }
  function qs(o) {
    return Object.keys(o).filter(function (k) { return o[k] !== "" && o[k] != null; })
      .map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(o[k]); }).join("&");
  }

  /* =================================================================
     Toolbar + vista
     ================================================================= */
  function ownerChoices() {
    return (P().options().users || []).map(function (u) { return { value: u.email, label: u.name || u.email }; });
  }
  function opt(v, l, sel) { return '<option value="' + esc(v) + '"' + (String(v) === String(sel) ? " selected" : "") + ">" + esc(l) + "</option>"; }

  function renderShell() {
    var root = $("prDealsView");
    var me = P().me() || {};
    root.innerHTML =
      '<div class="pr-filters pd-filters">' +
        '<label class="pr-filter pr-filter--wide"><span class="pr-filter__label">Buscar</span>' +
          '<input type="text" class="pr-filter__input pr-filter__input--search" id="pdQ" placeholder="Negocio o empresa…" autocomplete="off" value="' + esc(st.q) + '"></label>' +
        '<label class="pr-filter"><span class="pr-filter__label">Pipeline</span><select class="pr-filter__input" id="pdPipeline"></select></label>' +
        '<label class="pr-filter"><span class="pr-filter__label">Propietario</span><select class="pr-filter__input" id="pdOwner">' +
          opt("", "Todos", st.owner) + opt("__me__", "Mis negocios", st.owner) + opt("__none__", "Sin propietario", st.owner) +
          ownerChoices().map(function (o) { return opt(o.value, o.label, st.owner); }).join("") + "</select></label>" +
        '<label class="pr-filter"><span class="pr-filter__label">Fecha de creación</span><select class="pr-filter__input" id="pdCreated">' +
          opt("", "Cualquiera", st.created) + opt("7", "Últimos 7 días", st.created) + opt("30", "Últimos 30 días", st.created) +
          opt("90", "Últimos 90 días", st.created) + "</select></label>" +
        '<label class="pr-filter"><span class="pr-filter__label">Fecha de cierre</span><select class="pr-filter__input" id="pdClose">' +
          opt("", "Cualquiera", st.close) + opt("month", "Este mes", st.close) + opt("next30", "Próximos 30 días", st.close) +
          opt("overdue", "Vencida", st.close) + "</select></label>" +
        (me.sees_dummies ? '<label class="pr-check pr-filter-check"><input type="checkbox" id="pdDummy"' + (st.dummy ? " checked" : "") + "> Dummies</label>" : "") +
        '<div class="pr-filters__actions">' +
          '<div class="pd-toggle" role="group" aria-label="Vista">' +
            '<button type="button" class="pr-btn' + (st.view === "board" ? " is-on" : "") + '" data-pd-view="board" title="Tablero"><i class="fa-solid fa-table-columns"></i></button>' +
            '<button type="button" class="pr-btn' + (st.view === "table" ? " is-on" : "") + '" data-pd-view="table" title="Tabla"><i class="fa-solid fa-table-list"></i></button>' +
          "</div>" +
          '<button type="button" class="pr-btn" id="pdExport" title="Exportar a CSV"><i class="fa-solid fa-file-csv"></i></button>' +
          '<button type="button" class="pr-btn pr-btn--primary" id="pdNew"><i class="fa-solid fa-plus"></i> Agregar negocio</button>' +
        "</div>" +
      "</div>" +
      '<div id="pdBody" class="pd-body"><p class="pr-note pd-pad">Cargando…</p></div>';
    fillPipelines();
  }

  function fillPipelines() {
    var sel = $("pdPipeline");
    if (!sel) return;
    if (!st.pipeline && PIPELINES[0]) st.pipeline = PIPELINES[0].key;
    sel.innerHTML = PIPELINES.map(function (p) { return opt(p.key, p.label, st.pipeline); }).join("");
  }

  function bindShell() {
    var root = $("prDealsView");
    var t = null;
    root.addEventListener("input", function (e) {
      if (e.target.id !== "pdQ") return;
      clearTimeout(t);
      t = setTimeout(function () { st.q = e.target.value.trim(); st.page = 1; saveState(); load(); }, 300);
    });
    root.addEventListener("change", function (e) {
      var id = e.target.id;
      if (id === "pdPipeline") st.pipeline = e.target.value;
      else if (id === "pdOwner") st.owner = e.target.value;
      else if (id === "pdCreated") st.created = e.target.value;
      else if (id === "pdClose") st.close = e.target.value;
      else if (id === "pdDummy") st.dummy = e.target.checked;
      else return;
      st.page = 1;
      saveState();
      load();
    });
    root.addEventListener("click", function (e) {
      var v = e.target.closest("[data-pd-view]");
      if (v) {
        st.view = v.getAttribute("data-pd-view");
        saveState();
        root.querySelectorAll("[data-pd-view]").forEach(function (b) { b.classList.toggle("is-on", b === v); });
        load();
        return;
      }
      if (e.target.closest("#pdNew")) { open({ pipeline: st.pipeline, onSaved: load }); return; }
      if (e.target.closest("#pdExport")) { exportCsv(); return; }
      var more = e.target.closest("[data-pd-more]");
      if (more) { loadMore(more.getAttribute("data-pd-more"), more); return; }
      var card = e.target.closest("[data-deal]");
      if (card && !e.target.closest("a")) { open({ dealId: Number(card.getAttribute("data-deal")), onSaved: load }); return; }
      var th = e.target.closest("th[data-pd-sort]");
      if (th) {
        var k = th.getAttribute("data-pd-sort");
        st.sort = st.sort === k + ":asc" ? k + ":desc" : k + ":asc";
        saveState();
        load();
        return;
      }
      var pg = e.target.closest("[data-pd-page]");
      if (pg) { st.page = Math.max(1, st.page + Number(pg.getAttribute("data-pd-page"))); load(); }
    });
  }

  function apiFilters() {
    var f = filters();
    if (f.owner === "__me__") f.owner = (P().me() || {}).email || "";
    return f;
  }

  var loadSeq = 0;
  function load() {
    var seq = ++loadSeq;
    var body = $("pdBody");
    if (!body) return Promise.resolve();
    if (st.view === "table") {
      var f = apiFilters();
      f.page = st.page;
      f.page_size = 50;
      return P().api("/prospecting/deals?" + qs(f)).then(function (r) {
        if (seq !== loadSeq) return;
        PIPELINES = r.pipelines || PIPELINES;
        renderTable(r);
      }).catch(function (err) { body.innerHTML = '<p class="pr-note pd-pad">' + esc(err.message) + "</p>"; });
    }
    return P().api("/prospecting/deals/board?" + qs(apiFilters())).then(function (r) {
      if (seq !== loadSeq) return;
      PIPELINES = r.pipelines || PIPELINES;
      if (r.pipeline && r.pipeline !== st.pipeline) { st.pipeline = r.pipeline; saveState(); }
      fillPipelines();
      renderBoard(r);
    }).catch(function (err) { body.innerHTML = '<p class="pr-note pd-pad">' + esc(err.message) + "</p>"; });
  }

  /* =================================================================
     Tablero
     ================================================================= */
  var BOARD = null;
  function cardHtml(d) {
    var contact = (d.contacts || [])[0];
    var initials = contact ? String(contact.name || contact.email || "?").split(/\s+/).map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase() : "";
    return '<article class="pd-card" draggable="true" data-deal="' + d.id + '">' +
      '<h4 class="pd-card__name">' + esc(d.name) + "</h4>" +
      '<dl class="pd-card__meta">' +
        (d.close_date ? "<div><dt>Fecha de cierre:</dt><dd>" + P().fmtDate(d.close_date) + "</dd></div>" : "") +
        "<div><dt>Propietario:</dt><dd>" + esc(P().ownerName(d.owner_email) || "—") + "</dd></div>" +
        "<div><dt>Creado:</dt><dd>" + P().fmtDate(d.created_at) + "</dd></div>" +
        (d.amount ? "<div><dt>Cantidad:</dt><dd>" + money(d.amount) + "</dd></div>" : "") +
      "</dl>" +
      (d.company_name ? '<div class="pd-card__row"><i class="fa-solid fa-building"></i> ' +
        (d.company_id ? '<a href="prospecting-company.html?id=' + d.company_id + '">' + esc(d.company_name) + "</a>" : esc(d.company_name)) + "</div>" : "") +
      (contact ? '<div class="pd-card__row"><span class="pd-avatar">' + esc(initials) + "</span> " + esc(contact.name || contact.email) +
        ((d.contacts || []).length > 1 ? ' <span class="pr-note">+' + (d.contacts.length - 1) + "</span>" : "") + "</div>" : "") +
      '<div class="pd-card__foot">' +
        (d.last_activity_at ? '<span class="pd-chip"><i class="fa-regular fa-calendar"></i> ' + esc(ago(d.last_activity_at)) + "</span>" : "") +
        (d.hub_status === "waiting" ? '<span class="pd-chip pd-chip--warn" title="La cuenta ya tiene oportunidades: elegí Vincular o Es nueva"><i class="fa-solid fa-circle-pause"></i> Esperando decisión</span>' : "") +
        (d.opportunity_id ? '<span class="pd-chip pd-chip--ok" title="Oportunidad del hub"><i class="fa-solid fa-link"></i> Opp #' + d.opportunity_id + "</span>" : "") +
        (d.is_dummy ? '<span class="pd-chip">dummy</span>' : "") +
      "</div></article>";
  }

  function colFoot(c) {
    var pct = c.probability != null ? Math.round(c.probability * 100) + "%" : "—";
    return '<footer class="pd-col__foot"><div><strong>' + money(c.amount) + "</strong> | Cantidad total</div>" +
      "<div><strong>" + (c.weighted != null ? money(c.weighted) : "—") + " (" + pct + ")</strong> | Cantidad ponderada</div></footer>";
  }

  function renderBoard(r) {
    BOARD = r;
    var body = $("pdBody");
    if (!r.columns || !r.columns.length) { body.innerHTML = '<p class="pr-note pd-pad">No hay etapas para este pipeline.</p>'; return; }
    body.innerHTML = '<div class="pd-board">' + r.columns.map(function (c) {
      return '<section class="pd-col' + (c.is_won ? " pd-col--won" : c.is_closed ? " pd-col--lost" : "") + '" data-stage="' + esc(c.key) + '">' +
        '<header class="pd-col__head"><span class="pd-col__name">' + esc(c.label) + '</span><span class="pd-col__count">' + c.count + "</span>" +
          ((c.form || []).length ? ' <i class="fa-solid fa-list-check pd-col__req" title="Al pasar a esta etapa pide: ' + esc(c.form.map(function (x) { return label(x.key); }).join(", ")) + '"></i>' : "") + "</header>" +
        '<div class="pd-col__body">' + c.cards.map(cardHtml).join("") +
          (c.count > c.cards.length ? '<button type="button" class="pr-btn pd-more" data-pd-more="' + esc(c.key) + '">Cargar más (' + (c.count - c.cards.length) + ")</button>" : "") +
          (!c.count ? '<p class="pd-empty">Sin negocios</p>' : "") +
        "</div>" + colFoot(c) + "</section>";
    }).join("") + "</div>";
    wireBoard();
  }

  function loadMore(stage, btn) {
    var col = (BOARD.columns || []).filter(function (c) { return c.key === stage; })[0];
    if (!col) return;
    btn.disabled = true;
    var f = apiFilters();
    f.stage = stage;
    f.offset = col.cards.length;
    P().api("/prospecting/deals/board?" + qs(f)).then(function (r) {
      var more = ((r.columns || []).filter(function (c) { return c.key === stage; })[0] || {}).cards || [];
      col.cards = col.cards.concat(more);
      renderBoard(BOARD);
    }).catch(function (err) { btn.disabled = false; alert(err.message); });
  }

  var dragId = null;
  function wireBoard() {
    var board = document.querySelector("#pdBody .pd-board");
    if (!board) return;
    board.addEventListener("dragstart", function (e) {
      var card = e.target.closest(".pd-card");
      if (!card) return;
      dragId = Number(card.getAttribute("data-deal"));
      card.classList.add("is-dragging");
      try { e.dataTransfer.setData("text/plain", String(dragId)); e.dataTransfer.effectAllowed = "move"; } catch (x) {}
    });
    board.addEventListener("dragend", function (e) {
      var card = e.target.closest(".pd-card");
      if (card) card.classList.remove("is-dragging");
      board.querySelectorAll(".pd-col.is-drop").forEach(function (c) { c.classList.remove("is-drop"); });
    });
    board.addEventListener("dragover", function (e) {
      var col = e.target.closest(".pd-col");
      if (!col || dragId == null) return;
      e.preventDefault();
      board.querySelectorAll(".pd-col.is-drop").forEach(function (c) { if (c !== col) c.classList.remove("is-drop"); });
      col.classList.add("is-drop");
    });
    board.addEventListener("drop", function (e) {
      var col = e.target.closest(".pd-col");
      if (!col || dragId == null) return;
      e.preventDefault();
      col.classList.remove("is-drop");
      var id = dragId;
      dragId = null;
      moveCard(id, col.getAttribute("data-stage"));
    });
  }

  function findCard(id) {
    for (var i = 0; i < BOARD.columns.length; i++) {
      var c = BOARD.columns[i];
      for (var j = 0; j < c.cards.length; j++) if (c.cards[j].id === id) return { col: c, idx: j, deal: c.cards[j] };
    }
    return null;
  }

  /* Optimista: la tarjeta se mueve ya; si el server dice que no, vuelve. */
  function moveCard(id, stage) {
    var hit = findCard(id);
    if (!hit || hit.col.key === stage) return;
    var to = BOARD.columns.filter(function (c) { return c.key === stage; })[0];
    var deal = hit.deal;
    var amt = Number(deal.amount || 0);
    hit.col.cards.splice(hit.idx, 1); hit.col.count--; hit.col.amount -= amt;
    to.cards.unshift(deal); to.count++; to.amount += amt;
    [hit.col, to].forEach(function (c) { if (c.probability != null) c.weighted = c.amount * c.probability; });
    renderBoard(BOARD);
    changeStage(deal, stage).then(function (res) {
      if (!res) { load(); return; }
      announceHub(res);
      load();
    });
  }

  /* Cambio de etapa como en HubSpot: primero «Propiedades dependientes» (todos los campos que
     pide la etapa, prellenados con lo del negocio / la empresa / el contacto), después el
     PATCH con esos valores. Resuelve con el negocio guardado, o null si se canceló / falló. */
  /* Con oportunidad del hub, Candidate Signed / Closed Won / Closed Lost se mueven desde
     Opportunities (hire, MKT Collab, motivo y el push a HubSpot viven ahí); el negocio copia
     etapa y valores solo (deals.reflect). Mismo freno que el server. */
  var OPP_OWNED = ["signed", "closed_won", "closed_lost"];
  function changeStage(deal, stage, pipeline, fields, msg) {
    var pipe = pipeline || deal.pipeline_key;
    if (deal.opportunity_id && OPP_OWNED.indexOf(stage) !== -1) {
      P().toast('<i class="fa-solid fa-circle-info"></i> Este negocio ya tiene la oportunidad <a href="opportunity-detail.html?id=' + deal.opportunity_id +
        '" target="_blank" rel="noopener">#' + deal.opportunity_id + "</a>: " + esc(stageLabel(pipe, stage)) +
        " se mueve desde Opportunities, y el negocio se actualiza solo con sus datos.");
      return Promise.resolve(null);
    }
    var ask = fields ? Promise.resolve(fields)
      : P().api("/prospecting/deals/" + deal.id + "/stage-form?stage=" + encodeURIComponent(stage))
          .then(function (form) { return formPopup(form, stage, pipe, msg); });
    return ask.then(function (vals) {
      if (!vals) return null;
      var body = { stage_key: stage };
      if (pipeline) body.pipeline_key = pipeline;
      if (Object.keys(vals).length) body.fields = vals;
      return P().api("/prospecting/deals/" + deal.id + "/stage", { method: "PATCH", body: JSON.stringify(body) }).catch(function (err) {
        if (err.status === 409 && err.data && err.data.needs_fields) {
          return changeStage(deal, stage, pipeline, null, "Falta: " + err.data.needs_fields.map(label).join(", "));
        }
        alert(err.message);
        return null;
      });
    }).catch(function (err) { alert(err.message); return null; });
  }

  function announceHub(res) {
    var h = res && res.hub;
    if (!h) return;
    var parts = [];
    if (h.error) parts.push('<i class="fa-solid fa-triangle-exclamation"></i> ' + esc(h.error));
    if (h.account && h.account.action === "creada") parts.push("Cuenta creada en el CRM: <strong>" + esc(h.account.name || "") + "</strong>.");
    if (h.account && h.account.action === "vinculada") parts.push("Vinculado a la cuenta <strong>" + esc(h.account.name || "#" + h.account.id) + "</strong>.");
    if (h.opportunity && h.opportunity.action === "creada") parts.push("Oportunidad <strong>#" + h.opportunity.id + "</strong> creada en Opportunities (" + esc(h.opportunity.stage) + ").");
    if (h.opportunity && h.opportunity.action === "movida") parts.push("Oportunidad #" + h.opportunity.id + " → <strong>" + esc(h.opportunity.stage) + "</strong>.");
    if (h.opportunity && h.opportunity.aviso) parts.push(esc(h.opportunity.aviso));
    if (h.waiting) parts.push('<i class="fa-solid fa-circle-pause"></i> La cuenta ya tiene oportunidades: abrí el negocio y elegí <strong>Vincular</strong> o <strong>Es nueva</strong>.');
    if (h.aviso) parts.push(esc(h.aviso));
    if (parts.length) P().toast(parts.join(" "));
  }

  /* =================================================================
     Tabla
     ================================================================= */
  var COLS = [
    { key: "name", label: "Nombre del negocio" }, { key: "stage", label: "Etapa" },
    { key: "owner_email", label: "Propietario" }, { key: "amount", label: "Cantidad" },
    { key: "close_date", label: "Fecha de cierre" }, { key: "company", label: "Empresa" },
    { key: "contacts", label: "Contacto", nosort: true }, { key: "opportunity_id", label: "Oportunidad", nosort: true },
    { key: "created_at", label: "Creado" }, { key: "last_activity", label: "Última actividad" },
  ];
  function renderTable(r) {
    var arrow = function (k) {
      if (st.sort === k + ":asc") return ' <i class="fa-solid fa-arrow-up"></i>';
      if (st.sort === k + ":desc") return ' <i class="fa-solid fa-arrow-down"></i>';
      return "";
    };
    var rows = r.rows.map(function (d) {
      var ct = (d.contacts || [])[0];
      return '<tr data-deal="' + d.id + '" class="pd-row">' +
        "<td><strong>" + esc(d.name) + "</strong>" + (d.hub_status === "waiting" ? ' <span class="pd-chip pd-chip--warn">Esperando decisión</span>' : "") + "</td>" +
        "<td>" + esc(d.stage_label || d.stage_key) + "</td>" +
        "<td>" + esc(P().ownerName(d.owner_email) || "—") + "</td>" +
        "<td>" + (d.amount != null ? money(d.amount) : "—") + "</td>" +
        "<td>" + (d.close_date ? P().fmtDate(d.close_date) : "—") + "</td>" +
        "<td>" + (d.company_id ? '<a href="prospecting-company.html?id=' + d.company_id + '">' + esc(d.company_name) + "</a>" : "—") + "</td>" +
        "<td>" + (ct ? esc(ct.name || ct.email) + ((d.contacts || []).length > 1 ? ' <span class="pr-note">+' + (d.contacts.length - 1) + "</span>" : "") : "—") + "</td>" +
        "<td>" + (d.opportunity_id ? "#" + d.opportunity_id : "—") + "</td>" +
        "<td>" + P().fmtDate(d.created_at) + "</td>" +
        "<td>" + esc(ago(d.last_activity_at) || "—") + "</td></tr>";
    }).join("");
    var pages = Math.max(1, Math.ceil(r.total / r.page_size));
    $("pdBody").innerHTML = '<div class="pr-table-wrap"><table class="pr-table"><thead><tr>' +
      COLS.map(function (c) {
        return c.nosort ? "<th>" + esc(c.label) + "</th>"
          : '<th data-pd-sort="' + c.key + '"' + (st.sort.indexOf(c.key + ":") === 0 ? ' class="is-sorted"' : "") + ">" + esc(c.label) + arrow(c.key) + "</th>";
      }).join("") + "</tr></thead><tbody>" +
      (rows || '<tr><td colspan="' + COLS.length + '" class="pr-note">Ningún negocio coincide.</td></tr>') + "</tbody></table></div>" +
      '<div class="pr-pager"><span class="pr-count">' + r.total + " negocios · " + money(r.amount) + '</span><span class="pr-pager__spacer"></span>' +
      '<button type="button" class="pr-btn" data-pd-page="-1"' + (r.page <= 1 ? " disabled" : "") + '><i class="fa-solid fa-chevron-left"></i></button>' +
      '<span class="pr-pager__page">' + r.page + " / " + pages + "</span>" +
      '<button type="button" class="pr-btn" data-pd-page="1"' + (r.page >= pages ? " disabled" : "") + '><i class="fa-solid fa-chevron-right"></i></button></div>';
  }

  function exportCsv() {
    var f = apiFilters();
    delete f.page;
    var opts = { method: "POST", body: JSON.stringify({ filters: f }) };
    // La API común parsea JSON: para el CSV va un fetch directo con el mismo base.
    var base = (P().apiBase && P().apiBase()) || "";
    var email = (P().me() || {}).email || "";
    fetch(base + "/prospecting/deals/export", Object.assign(opts, { headers: { "Content-Type": "application/json", "X-User-Email": email } }))
      .then(function (res) { if (!res.ok) throw new Error("HTTP " + res.status); return res.blob(); })
      .then(function (blob) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "prospecting-negocios-" + P().todayIso() + ".csv";
        document.body.appendChild(a); a.click(); a.remove();
      }).catch(function (err) { alert("No se pudo exportar: " + err.message); });
  }

  /* =================================================================
     Popup de obligatorios (al pasar de etapa)
     ================================================================= */
  /* «Propiedades dependientes» (el popup de HubSpot al cambiar de etapa). `form` = respuesta
     de /stage-form: {fields: [{key, label, type, options, required, value, prefilled}]}.
     Sin campos no hay popup. Resuelve con los valores ({} si no había nada que pedir) o null. */
  function formPopup(form, stageKey, pipeline, msg) {
    var fields = (form && form.fields) || [];
    if (!fields.length) return Promise.resolve({});
    return new Promise(function (resolve) {
      var box = document.createElement("div");
      box.className = "pr-modal pd-deps";
      box.innerHTML = '<div class="pr-modal__card pd-req" role="dialog" aria-modal="true">' +
        '<div class="pd-req__head"><h3>Propiedades dependientes</h3>' +
          '<button type="button" class="pr-drawer__close" data-x="cancel" aria-label="Cerrar">&times;</button></div>' +
        '<p class="pr-note">Para pasar a <strong>' + esc(stageLabel(pipeline, stageKey)) + "</strong>" +
          (stageKey === "sql" ? " · con esto se crea la cuenta en el CRM" : "") + ".</p>" +
        '<div class="pd-req__list">' + fields.map(function (f) {
          var v = f.value;
          if (f.type === "date" && v) v = String(v).slice(0, 10);
          return '<label class="pc-field' + (f.required ? " is-required" : "") + '"><span class="pr-filter__label pd-req__label">' + esc(f.label) +
            (f.required ? ' <span class="pc-req">*</span>' : "") +
            (f.prefilled ? ' <span class="pd-req__pre" title="Tomado de la empresa / el contacto">prellenado</span>' : "") + "</span>" +
            C().fieldControl(f, v) + "</label>";
        }).join("") + "</div>" +
        '<p class="pr-note pd-req__msg" id="pdReqMsg">' + esc(msg || "") + "</p>" +
        '<div class="pr-modal__foot"><button type="button" class="pr-btn" data-x="cancel">Cancelar</button>' +
        '<button type="button" class="pr-btn pr-btn--primary" data-x="ok">Guardar</button></div></div>';
      document.body.appendChild(box);
      var req = {};
      fields.forEach(function (f) { req[f.key] = f.required; });
      box.addEventListener("click", function (e) {
        var chip = e.target.closest(".pr-wf-chip");
        if (chip && chip.closest("[data-k]")) {
          chip.classList.toggle("is-on");
          chip.innerHTML = (chip.classList.contains("is-on") ? '<i class="fa-solid fa-check"></i> ' : "") + esc(chip.getAttribute("data-chip"));
          return;
        }
        var x = e.target.closest("[data-x]");
        if (!x) return;
        if (x.getAttribute("data-x") === "ok") {
          var vals = {}, miss = [];
          box.querySelectorAll("[data-k]").forEach(function (el) {
            var k = el.getAttribute("data-k"), v = C().readFieldValue(el);
            if (!isEmpty(v)) vals[k] = v;
            else if (req[k]) miss.push(label(k));
            el.closest(".pc-field").classList.toggle("is-missing", isEmpty(v) && !!req[k]);
          });
          if (miss.length) { box.querySelector("#pdReqMsg").textContent = "Falta: " + miss.join(", "); return; }
          box.remove();
          resolve(vals);
          return;
        }
        box.remove();
        resolve(null);
      });
    });
  }

  /* =================================================================
     Panel del negocio
     ================================================================= */
  var panel = null, cur = null, curOpts = null;
  var pdCompany = { id: null, name: "" }, pdCompanyOrig = null;
  var pdContacts = [], pdContactsOrig = "";

  function ensurePanel() {
    if (panel) return panel;
    panel = document.createElement("div");
    panel.className = "pr-drawer pc-drawer pd-drawer";
    panel.setAttribute("aria-hidden", "true");
    panel.innerHTML = '<div class="pr-drawer__backdrop" data-pd-close></div>' +
      '<aside class="pr-drawer__panel pc-panel" role="dialog" aria-modal="true">' +
        '<header class="pr-drawer__head"><span class="pr-drawer__eyebrow" id="pdEyebrow">Negocio</span>' +
          '<h2 class="pr-drawer__title" id="pdTitle">—</h2><p class="pr-drawer__sub" id="pdSub"></p>' +
          '<button type="button" class="pr-drawer__close" data-pd-close aria-label="Cerrar">&times;</button></header>' +
        '<div class="pr-drawer__body" id="pdPanelBody"></div>' +
        '<footer class="pr-drawer__foot"><span class="pr-drawer__status" id="pdStatus"></span>' +
          '<button type="button" class="pr-btn pr-btn--danger" id="pdDelete" hidden><i class="fa-regular fa-trash-can"></i></button>' +
          '<button type="button" class="pr-btn pr-btn--primary" id="pdSave"><i class="fa-regular fa-floppy-disk"></i> Guardar</button></footer>' +
      "</aside>";
    document.body.appendChild(panel);
    panel.addEventListener("click", onPanelClick);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && panel.classList.contains("is-open")) close(); });
    return panel;
  }
  function close() {
    if (!panel) return;
    panel.classList.remove("is-open");
    panel.setAttribute("aria-hidden", "true");
  }

  /* opts: {dealId?, pipeline?, companyId?, companyName?, contactId?, contactName?, onSaved?} */
  function open(opts) {
    ensurePanel();
    curOpts = opts || {};
    panel.classList.add("is-open");
    panel.setAttribute("aria-hidden", "false");
    $("pdStatus").textContent = "";
    $("pdPanelBody").innerHTML = '<p class="pr-note">Cargando…</p>';
    if (!PIPELINES.length) PIPELINES = schema().pipelines || [];
    var load = curOpts.dealId ? P().api("/prospecting/deals/" + curOpts.dealId) : Promise.resolve(null);
    load.then(function (d) { render(d); }).catch(function (err) {
      $("pdPanelBody").innerHTML = '<p class="pr-note">' + esc(err.message) + "</p>";
    });
  }

  function render(d) {
    var isNew = !d;
    var o = curOpts;
    d = d || { pipeline_key: o.pipeline || (PIPELINES[0] || {}).key || "hiring", contacts: [] };
    if (isNew) d.stage_key = (stagesOf(d.pipeline_key)[0] || {}).key;
    cur = d;
    $("pdEyebrow").textContent = isNew ? "Nuevo negocio" : "Negocio";
    $("pdTitle").textContent = isNew ? "Agregar negocio" : d.name;
    pdCompany = isNew ? { id: o.companyId || null, name: o.companyName || "" } : { id: d.company_id || null, name: d.company_name || "" };
    pdCompanyOrig = pdCompany.id;
    pdContacts = isNew ? (o.contactId ? [{ id: o.contactId, name: o.contactName || "#" + o.contactId }] : []) : (d.contacts || []).slice();
    pdContactsOrig = ids(pdContacts);
    $("pdSub").textContent = isNew ? "" : (stageLabel(d.pipeline_key, d.stage_key) + (d.company_name ? " · " + d.company_name : ""));

    var body = "";
    // Pipeline + etapa
    body += '<section class="pd-stagebox"><label class="pr-filter"><span class="pr-filter__label">Pipeline</span>' +
      '<select class="pr-filter__input" id="pdPipe">' + PIPELINES.map(function (p) { return opt(p.key, p.label, d.pipeline_key); }).join("") + "</select></label>" +
      '<label class="pr-filter"><span class="pr-filter__label">Etapa</span><select class="pr-filter__input" id="pdStage">' +
        stageOptions(d.pipeline_key, d.stage_key) + "</select></label></section>";
    if (!isNew) body += hubBox(d);
    // Empresa + contactos
    body += '<section class="pc-company"><span class="pr-filter__label">Empresa</span>' +
      '<div class="pc-company__row"><div class="pr-inbox__pick">' +
      '<input type="text" class="pr-filter__input" id="pdCoQ" placeholder="Sin empresa — buscá una…" autocomplete="off" value="' + esc(pdCompany.name || "") + '">' +
      '<div class="pr-inbox__results" id="pdCoResults" hidden></div></div>' +
      '<button type="button" class="pr-btn" id="pdCoClear"' + (pdCompany.id ? "" : " hidden") + ">Quitar</button></div></section>";
    body += '<section class="pc-company"><span class="pr-filter__label">Contactos</span><div class="pd-chips" id="pdChips"></div>' +
      '<div class="pr-inbox__pick"><input type="text" class="pr-filter__input" id="pdCtQ" placeholder="Agregar un contacto (nombre o email)…" autocomplete="off">' +
      '<div class="pr-inbox__results" id="pdCtResults" hidden></div></div></section>';
    // Propiedades por grupo
    (schema().groups || []).forEach(function (g, gi) {
      var fs = schema().fields.filter(function (f) { return f.group === g; });
      if (!fs.length) return;
      body += '<details class="pc-group"' + (gi === 0 || isNew ? " open" : "") + "><summary><span>" + esc(g) + '</span><span class="pc-group__count"></span></summary>' +
        '<div class="pc-grid">' + fs.map(function (f) {
          var wide = f.type === "longtext";
          return '<label class="pc-field' + (wide ? " pc-field--wide" : "") + '"' + (f.description ? ' title="' + esc(f.description) + '"' : "") + ">" +
            '<span class="pr-filter__label">' + esc(f.label) + (f.key === "name" ? ' <span class="pc-req">*</span>' : "") +
              (!isNew && window.ProspectingHistory ? window.ProspectingHistory.button("deal", d.id, f.key) : "") + "</span>" +
            C().fieldControl(f, d[f.key]) + "</label>";
        }).join("") + "</div></details>";
    });
    if (!isNew) {
      body += '<details class="pc-group"><summary><span>Historial</span><span class="pc-group__count">' + (d.events || []).length + "</span></summary>" +
        historyHtml(d.events || []) + "</details>";
    }
    $("pdPanelBody").innerHTML = body;
    if (isNew && pdCompany.name) {
      var nm = $("pdPanelBody").querySelector('[data-k="name"]');
      if (nm && !nm.value) nm.value = pdCompany.name;
    }
    renderChips();
    bindPickers();
    var del = $("pdDelete");
    del.hidden = isNew;
    del.onclick = function () {
      if (!confirm("¿Borrar el negocio «" + d.name + "»? (No borra la cuenta ni la oportunidad del hub.)")) return;
      P().api("/prospecting/deals/" + d.id, { method: "DELETE" }).then(function () {
        P().toast("Negocio borrado.");
        close();
        if (curOpts.onSaved) curOpts.onSaved(null);
      }).catch(function (err) { alert(err.message); });
    };
    $("pdSave").onclick = function () { save(isNew); };
  }

  function stageOptions(pkey, sel) {
    return stagesOf(pkey).map(function (s) {
      return opt(s.key, s.label + (s.probability != null ? " (" + Math.round(s.probability * 100) + "%)" : ""), sel);
    }).join("");
  }

  function hubBox(d) {
    var h = "";
    if (d.hub_rule) h += '<p class="pr-note"><i class="fa-solid fa-circle-info"></i> ' + esc(d.hub_rule) + "</p>";
    if (d.account) {
      h += '<div class="pd-hub__row"><i class="fa-solid fa-briefcase"></i> Cuenta del CRM: <a href="account-details.html?id=' + d.account.account_id +
        '" target="_blank" rel="noopener">' + esc(d.account.client_name || "#" + d.account.account_id) + "</a>" +
        (d.account.sql_date ? ' <span class="pr-note">· SQL ' + P().fmtDate(d.account.sql_date) + "</span>" : "") + "</div>";
    }
    if (d.opportunity) {
      h += '<div class="pd-hub__row"><i class="fa-solid fa-link"></i> Oportunidad: <a href="opportunity-detail.html?id=' + d.opportunity.opportunity_id +
        '" target="_blank" rel="noopener">#' + d.opportunity.opportunity_id + " · " + esc(d.opportunity.opp_position_name || "sin puesto") + "</a> · <strong>" +
        esc(d.opportunity.opp_stage || "—") + '</strong> <button type="button" class="pr-btn pd-mini" data-pd-act="unlink">Desvincular</button></div>';
    } else if (d.hub_status === "waiting") {
      h += '<div class="pd-hub__wait"><strong><i class="fa-solid fa-circle-pause"></i> Esperando decisión.</strong> La cuenta ya tiene estas oportunidades. ' +
        "¿El negocio es una de ellas, o es nueva?" +
        '<div class="pd-hub__cands">' + (d.candidates || []).map(function (c) {
          return '<div class="pd-hub__cand"><span>#' + c.opportunity_id + " · " + esc(c.opp_position_name || "sin puesto") + " · " + esc(c.opp_stage || "—") +
            (c.opp_model ? " · " + esc(c.opp_model) : "") + (c.cerrada ? ' <span class="pr-note">(cerrada: no se reabre)</span>' : "") + "</span>" +
            '<button type="button" class="pr-btn pd-mini" data-pd-act="link" data-opp="' + c.opportunity_id + '">Vincular</button></div>';
        }).join("") + "</div>" +
        '<button type="button" class="pr-btn pr-btn--primary pd-mini" data-pd-act="mark-new">Es nueva, creala</button></div>';
    }
    if (!h) return "";
    return '<section class="pd-hub"><span class="pr-filter__label">En el hub</span>' + h + "</section>";
  }

  function onPanelClick(e) {
    if (e.target.closest("[data-pd-close]")) return close();
    var chip = e.target.closest(".pr-wf-chip");
    if (chip && chip.closest("[data-k]")) {
      chip.classList.toggle("is-on");
      chip.innerHTML = (chip.classList.contains("is-on") ? '<i class="fa-solid fa-check"></i> ' : "") + esc(chip.getAttribute("data-chip"));
      return;
    }
    var rm = e.target.closest("[data-pd-rmct]");
    if (rm) {
      var id = Number(rm.getAttribute("data-pd-rmct"));
      pdContacts = pdContacts.filter(function (c) { return c.id !== id; });
      renderChips();
      return;
    }
    var act = e.target.closest("[data-pd-act]");
    if (!act || !cur || !cur.id) return;
    var a = act.getAttribute("data-pd-act");
    var req;
    if (a === "link") req = P().api("/prospecting/deals/" + cur.id + "/link-opportunity", { method: "POST", body: JSON.stringify({ opportunity_id: Number(act.getAttribute("data-opp")) }) });
    else if (a === "mark-new") req = P().api("/prospecting/deals/" + cur.id + "/mark-new", { method: "POST", body: "{}" });
    else if (a === "unlink") {
      if (!confirm("¿Desvincular la oportunidad #" + cur.opportunity_id + " de este negocio? La oportunidad no se borra.")) return;
      req = P().api("/prospecting/deals/" + cur.id + "/link-opportunity", { method: "DELETE" });
    }
    if (!req) return;
    $("pdStatus").textContent = "Guardando…";
    req.then(function (res) {
      announceHub(res);
      render(res);
      $("pdStatus").textContent = "Guardado.";
      if (curOpts.onSaved) curOpts.onSaved(res);
    }).catch(function (err) { $("pdStatus").textContent = "Error: " + err.message; });
  }

  function ids(list) { return list.map(function (c) { return c.id; }).sort(function (a, b) { return a - b; }).join(","); }
  function renderChips() {
    $("pdChips").innerHTML = pdContacts.length ? pdContacts.map(function (c) {
      return '<span class="pd-ctchip">' + esc(c.name || c.email || "#" + c.id) +
        ' <button type="button" data-pd-rmct="' + c.id + '" aria-label="Quitar">&times;</button></span>';
    }).join("") : '<span class="pr-note">Sin contactos.</span>';
  }

  function picker(inputId, boxId, url, rowHtml, onPick) {
    var q = $(inputId), box = $(boxId), t = null;
    q.addEventListener("input", function () {
      clearTimeout(t);
      var text = q.value.trim();
      if (!text) { box.hidden = true; return; }
      t = setTimeout(function () {
        P().api(url(text)).then(function (r) {
          box.innerHTML = r.rows.length ? r.rows.map(rowHtml).join("") : '<span class="pr-note">Nada coincide.</span>';
          box.hidden = false;
        }).catch(function (err) { box.innerHTML = '<span class="pr-note">' + esc(err.message) + "</span>"; box.hidden = false; });
      }, 250);
    });
    q.addEventListener("blur", function () { setTimeout(function () { box.hidden = true; }, 200); });
    box.addEventListener("mousedown", function (e) {
      var b = e.target.closest("[data-pick]");
      if (!b) return;
      e.preventDefault();
      onPick(b);
      box.hidden = true;
    });
  }

  function bindPickers() {
    picker("pdCoQ", "pdCoResults", function (t) { return "/prospecting/companies?q=" + encodeURIComponent(t) + "&page_size=10"; },
      function (co) {
        return '<button type="button" data-pick="' + co.id + '" data-name="' + esc(co.name) + '"><strong>' + esc(co.name) + "</strong>" +
          (co.domain ? ' <span class="pr-note">' + esc(co.domain) + "</span>" : "") + "</button>";
      },
      function (b) {
        pdCompany = { id: Number(b.getAttribute("data-pick")), name: b.getAttribute("data-name") };
        $("pdCoQ").value = pdCompany.name;
        $("pdCoClear").hidden = false;
      });
    $("pdCoQ").addEventListener("blur", function () {
      setTimeout(function () { if ($("pdCoQ") && $("pdCoQ").value.trim() !== (pdCompany.name || "")) $("pdCoQ").value = pdCompany.name || ""; }, 220);
    });
    $("pdCoClear").addEventListener("click", function () {
      pdCompany = { id: null, name: "" };
      $("pdCoQ").value = "";
      $("pdCoClear").hidden = true;
    });
    picker("pdCtQ", "pdCtResults", function (t) { return "/prospecting/contacts?q=" + encodeURIComponent(t) + "&page_size=10"; },
      function (c) {
        return '<button type="button" data-pick="' + c.id + '" data-name="' + esc(c.name) + '"><strong>' + esc(c.name) + "</strong>" +
          ' <span class="pr-note">' + esc(c.email || "") + (c.company_name ? " · " + esc(c.company_name) : "") + "</span></button>";
      },
      function (b) {
        var id = Number(b.getAttribute("data-pick"));
        if (!pdContacts.some(function (c) { return c.id === id; })) pdContacts.push({ id: id, name: b.getAttribute("data-name") });
        $("pdCtQ").value = "";
        renderChips();
      });
    $("pdPipe").addEventListener("change", function (e) {
      $("pdStage").innerHTML = stageOptions(e.target.value, (stagesOf(e.target.value)[0] || {}).key);
    });
  }

  function sameValue(a, b, type) {
    if (isEmpty(a) && isEmpty(b)) return true;
    if (type === "date") return String(a || "").slice(0, 10) === String(b || "");
    if (type === "number") return Number(a) === Number(b);
    return String(a) === String(b);
  }

  function save(isNew) {
    var status = $("pdStatus");
    var d = cur;
    var patch = {};
    panel.querySelectorAll("#pdPanelBody .pc-group [data-k]").forEach(function (el) {
      var k = el.getAttribute("data-k"), t = el.getAttribute("data-type");
      var v = C().readFieldValue(el);
      if (isNew ? !isEmpty(v) : !sameValue(d[k], v, t)) patch[k] = v;
    });
    var pipe = $("pdPipe").value, stage = $("pdStage").value;
    if (isNew) {
      if (!patch.name) { status.textContent = "Poné un nombre al negocio."; return; }
      var body = Object.assign({}, patch, { pipeline_key: pipe, stage_key: stage, company_id: pdCompany.id || null,
        contact_ids: pdContacts.map(function (c) { return c.id; }) });
      status.textContent = "Guardando…";
      // Igual que al mover: si la etapa pide campos, primero «Propiedades dependientes».
      var create = function (b, msg) {
        return P().api("/prospecting/deals/stage-form", { method: "POST", body: JSON.stringify({
          stage_key: stage, company_id: b.company_id, contact_ids: b.contact_ids, values: b }) })
          .then(function (form) { return formPopup(form, stage, pipe, msg); })
          .then(function (vals) {
            if (!vals) return null;
            var full = Object.assign({}, b, vals);
            return P().api("/prospecting/deals", { method: "POST", body: JSON.stringify(full) }).catch(function (err) {
              if (err.status === 409 && err.data && err.data.needs_fields) {
                return create(full, "Falta: " + err.data.needs_fields.map(label).join(", "));
              }
              throw err;
            });
          });
      };
      create(body).then(function (res) {
        if (!res) { status.textContent = "Sin guardar."; return; }
        announceHub(res);
        if (!(res.hub && (res.hub.account || res.hub.opportunity))) P().toast('<i class="fa-solid fa-handshake"></i> Negocio creado.');
        close();
        if (curOpts.onSaved) curOpts.onSaved(res);
      }).catch(function (err) { status.textContent = "Error: " + err.message; });
      return;
    }
    var stageChanged = stage !== d.stage_key || pipe !== d.pipeline_key;
    var companyChanged = (pdCompany.id || null) !== (pdCompanyOrig || null);
    var contactsChanged = ids(pdContacts) !== pdContactsOrig;
    if (!Object.keys(patch).length && !stageChanged && !companyChanged && !contactsChanged) { status.textContent = "Sin cambios."; return; }
    status.textContent = "Guardando…";
    var last = null;
    var chain = Promise.resolve();
    if (Object.keys(patch).length) chain = chain.then(function () {
      return P().api("/prospecting/deals/" + d.id, { method: "PATCH", body: JSON.stringify(patch) }).then(function (r) { last = r; });
    });
    if (companyChanged) chain = chain.then(function () {
      return P().api("/prospecting/deals/" + d.id + "/company", { method: "PATCH", body: JSON.stringify({ company_id: pdCompany.id || null }) }).then(function (r) { last = r; });
    });
    if (contactsChanged) chain = chain.then(function () {
      return P().api("/prospecting/deals/" + d.id + "/contacts", { method: "PUT",
        body: JSON.stringify({ contact_ids: pdContacts.map(function (c) { return c.id; }) }) }).then(function (r) { last = r; });
    });
    if (stageChanged) chain = chain.then(function () {
      return changeStage(Object.assign({}, d, patch), stage, pipe !== d.pipeline_key ? pipe : null).then(function (r) { if (r) last = r; });
    });
    chain.then(function () {
      if (last && last.hub && (last.hub.account || last.hub.opportunity || last.hub.waiting || last.hub.error)) announceHub(last);
      else P().toast('<i class="fa-solid fa-handshake"></i> Negocio guardado.');
      if (last) render(last);
      status.textContent = "Guardado.";
      if (curOpts.onSaved) curOpts.onSaved(last);
    }).catch(function (err) { status.textContent = "Error: " + err.message; });
  }

  function fmtEv(key, v) {
    if (v == null || v === "") return "—";
    if (key === "stage") return stageLabel(cur && cur.pipeline_key, v);
    var f = fieldOf(key);
    if (f && f.type === "user") return P().ownerName(v) || v;
    if (f && f.type === "date") return P().fmtDate(v);
    return v;
  }
  function hubEventText(v) {
    var m = /^hub_(\w+):(\d+)$/.exec(String(v || ""));
    if (!m) return null;
    var LBL = { account: "Cuenta del CRM #", opportunity: "Oportunidad creada #", opportunity_linked: "Vinculado a la oportunidad #",
      opportunity_unlinked: "Desvinculado de la oportunidad #" };
    return (LBL[m[1]] || m[1] + " #") + m[2];
  }
  function historyHtml(events) {
    if (!events.length) return '<p class="pr-note">Sin cambios todavía.</p>';
    return '<ul class="pr-events">' + events.map(function (ev) {
      var src = String(ev.source || "");
      var who = src === "hubspot_sync" || src === "hubspot_import" ? "HubSpot" : src === "opportunity" ? "Oportunidad del hub"
        : src === "hub" ? "Hub" : (P().ownerName(ev.actor) || ev.actor || src);
      var hub = hubEventText(ev.new_value);
      var what = hub ? esc(hub)
        : ev.field ? esc(label(ev.field)) + ": " + esc(fmtEv(ev.field, ev.old_value)) + " → " + esc(fmtEv(ev.field, ev.new_value))
        : esc(ev.new_value === "deal_created" ? "creó el negocio" : ev.new_value || "");
      return '<li><span class="pr-events__when">' + P().fmtDateTime(ev.at) + '</span><span class="pr-events__src">' + esc(who) + "</span> · " + what + "</li>";
    }).join("") + "</ul>";
  }

  /* =================================================================
     Entrada
     ================================================================= */
  function show() {
    PIPELINES = schema().pipelines || PIPELINES;
    if (!bound) { renderShell(); bindShell(); bound = true; }
    else fillPipelines();
    return load();
  }

  window.ProspectingDeals = { show: show, open: open, close: close, reload: load };
})();
