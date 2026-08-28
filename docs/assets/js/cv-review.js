/* CV Review — la cola del sales lead.
 *
 * Aprobar/rechazar los CVs que armaron las recruiters, más el resumen por recruiter del
 * período. El gate de verdad es del backend: POST /cv_reviews/<id>/decision devuelve 403
 * a quien no sea sales lead. El chequeo de esta página es sólo para que nadie más
 * tropiece con una pantalla que no le sirve.
 *
 * Usa el design system de Hirex (hirex.css) — las clases hx-* vienen de ahí.
 */
(function () {
  'use strict';

  const API = (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    ? 'http://127.0.0.1:5000'
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  // Sales leads + la supervisión (pgonzales y agostina, que ven TODOS los reviews).
  // Misma forma que las allow-lists de sidebar.js. Se mantiene en sincronía a mano con
  // OVERSIGHT_EMAILS + user_roles.role_type='sales_lead' del backend, que es quien decide
  // de verdad (POST /cv_reviews/<id>/decision devuelve 403).
  // La supervisión ve TODO por defecto; un sales lead entra viendo sólo sus oportunidades.
  // Espeja OVERSIGHT_EMAILS del backend.
  const OVERSIGHT = new Set([
    'pgonzales@vintti.com',
    'agostina@vintti.com',
  ]);

  const ALLOWED = new Set([
    ...OVERSIGHT,
    'agustin@vintti.com',
    'bahia@vintti.com',
    'lara@vintti.com',
    'mariano@vintti.com',
    'mia@vintti.com',
  ]);

  const me = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '')
    .toLowerCase().trim();

  const $ = (id) => document.getElementById(id);
  const headers = () => ({ 'Content-Type': 'application/json', 'X-User-Email': me });
  const show = (el, on) => { if (el) el.hidden = !on; };

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const fmtDate = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString();
  };

  function daysWaiting(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return Math.floor((Date.now() - d.getTime()) / 86400000);
  }

  // Estos cuatro viven en assets/js/cv-review-cards.js, compartidos con recruiter-power.html
  // para que las dos páginas pinten la MISMA tarjeta. Acá quedan como alias para no tocar
  // los call sites de esta página.
  const CARDS = window.CvReviewCards;
  const qCls = CARDS.qCls;

  const fmtRate = CARDS.fmtRate;

  // Los análisis guardados antes de la v7 dicen "the source": el prompt viejo se lo
  // enseñaba al modelo. Esos reviews ya están decididos y nadie los va a re-correr, así
  // que la palabra se traduce al mostrarla. La sustitución es SINGULAR a propósito: la
  // frase guardada ya trae el verbo concordado en singular ("the source does not show"),
  // y meterle "the originals" la dejaría mal escrita ("the originals does not show").
  const SOURCE_RE = /\bthe source material\b|\bthe source\b/gi;
  const deSource = (t) => String(t ?? '').replace(SOURCE_RE, m =>
    (m[0] === 'T' ? "The" : "the") + " candidate's own CV or LinkedIn");

  let reasonLabels = {};
  let checklistLabels = {};
  let modeFootHint = '';
  let currentReview = null;
  let queueRows = [];

  // Deep-link desde los mails. Los CTA ya se mandaban con estos parámetros pero nadie los
  // leía, así que el botón "Open the CV review" del mail no hacía nada: caía en la cola sin
  // filtrar y sin abrir nada.
  const DEEP = new URLSearchParams(location.search);
  const deepReviewId = Number(DEEP.get('review_id')) || null;
  const deepOppId = Number(DEEP.get('opportunity_id')) || null;

  /* ---------------------------------------------------------------- métricas */

  const ringHtml = CARDS.ringHtml;

  function renderMetrics(data) {
    const box = $('cvrMetrics');
    const rows = data.rows || [];
    const totals = data.totals || {};
    const meta = data.meta || {};

    // Ventana invertida = el período elegido termina antes del piso de las métricas. Se
    // dice con palabras en vez de pintar "2026-09-01 → 2026-08-27", que se lee como un bug.
    $('cvrMetricsWindow').textContent = meta.window_empty
      ? `nothing here yet — these metrics start on ${meta.metrics_from}`
      : (meta.desde ? `${meta.desde} → ${meta.hasta}` : '')
        + (meta.sales_lead ? '  ·  your opportunities' : '')
        + (meta.ai_version ? `  ·  scoring v${meta.ai_version}` : '')
        + (meta.window_clamped ? `  ·  from ${meta.metrics_from} onwards` : '');

    // Resumen para leer la sección SIN abrirla: plegada tiene que decir algo igual.
    const sum = [];
    if (rows.length) sum.push(`${rows.length} recruiter${rows.length === 1 ? '' : 's'}`);
    if (totals.profiles_sent) sum.push(`${totals.profiles_sent} sent`);
    if (totals.quality_avg !== null && totals.quality_avg !== undefined) {
      sum.push(`${totals.quality_avg} avg coverage`);
    }
    $('cvrMetricsSum').textContent = sum.join('  ·  ');

    if (!rows.length) {
      box.innerHTML = '';
      show($('cvrMetricsEmpty'), true);
      return;
    }
    show($('cvrMetricsEmpty'), false);

    const card = (r, isTotal) => CARDS.card(r, isTotal);

    const totalRow = CARDS.totalsRow(data, reasonLabels);
    box.innerHTML = card(totalRow, true) + rows.map(r => card(r, false)).join('');
  }


  /* ------------------------------------------------------------------- cola */

  const STATUS = {
    pending:   ['Waiting',   'cvr-st-pending'],
    approved:  ['Approved',  'cvr-st-approved'],
    rejected:  ['Rejected',  'cvr-st-rejected'],
    changes_requested: ['Needs changes', 'cvr-st-changes'],
    cancelled: ['Cancelled', 'cvr-st-cancelled'],
  };

  // Grupos abiertos de la cola, por opportunity_id. Vive fuera de renderQueue porque el
  // buscador re-renderiza en cada tecla: sin esto, escribir colapsaría todo lo que abriste.
  const openGroups = new Set();

  // El <tbody> lo emite renderQueue (uno por vacante), así que limpiar la cola es sacar
  // los tbody y dejar el thead en pie.
  function clearQueue() {
    $('cvrQueueTable').querySelectorAll('tbody').forEach(tb => tb.remove());
  }

  // Coverage como anillo con el número adentro: una sola pieza por fila, que se escanea de
  // un vistazo. El arco lleva el semáforo y el número queda en tinta neutra, porque una
  // columna de números en rojo y verde era justo el ruido que sobraba.
  function covCell(r) {
    if (r.ai_pending) return '<span class="cvr-score-none">scoring…</span>';
    if (r.ai_score === null || r.ai_score === undefined) return '<span class="cvr-score-none">—</span>';
    return ringHtml(r.ai_score);
  }

  // Para los pendientes la antigüedad son días de espera; para los ya decididos, la fecha
  // en que se decidieron. Son dos unidades distintas en la misma columna a propósito.
  function ageCell(r) {
    const waited = r.status === 'pending' ? daysWaiting(r.requested_at) : null;
    if (waited === null) return `<span class="cvr-age">${fmtDate(r.reviewed_at || r.requested_at)}</span>`;
    return `<span class="cvr-age${waited >= 3 ? ' cvr-age--old' : ''}">${waited === 0 ? 'today' : waited + 'd'}</span>`;
  }

  // La espera del CV más viejo del grupo, para que el grupo colapsado siga gritando urgencia.
  // Mismo formato corto que las filas: vive en la columna Age y tiene que alinear con ellas.
  function groupAge(rows) {
    const waits = rows
      .map(r => (r.status === 'pending' ? daysWaiting(r.requested_at) : null))
      .filter(v => v !== null);
    if (!waits.length) return '';
    const oldest = Math.max(...waits);
    return `<span class="cvr-age${oldest >= 3 ? ' cvr-age--old' : ''}">${oldest === 0 ? 'today' : oldest + 'd'}</span>`;
  }

  function renderQueue() {
    const term = ($('cvrSearch').value || '').toLowerCase().trim();
    let list = !term ? queueRows : queueRows.filter(r =>
      [r.candidate_name, r.opp_position_name, r.client_name, r.recruiter_email]
        .some(v => String(v || '').toLowerCase().includes(term)));
    // El CTA de un batch apunta a una oportunidad: son N reviews, no uno.
    if (deepOppId) list = list.filter(r => Number(r.opportunity_id) === deepOppId);

    $('cvrCount').innerHTML = `<b>${list.length}</b> of ${queueRows.length}`;

    show($('cvrQueueLoading'), false);
    if (!list.length) {
      clearQueue();
      show($('cvrQueueWrap'), false);
      show($('cvrQueueEmpty'), true);
      return;
    }
    show($('cvrQueueEmpty'), false);
    show($('cvrQueueWrap'), true);

    // Agrupar por vacante respetando el orden que ya trae el backend (pendientes primero,
    // el más viejo arriba): así la búsqueda más urgente queda arriba de todo sin ordenar acá.
    const groups = new Map();
    list.forEach(r => {
      const k = String(r.opportunity_id);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(r);
    });

    // Si todas las filas comparten estado, la columna Status no dice nada: se esconde.
    const statuses = new Set(list.map(r => r.status));
    $('cvrQueueTable').classList.toggle('cvr-table--nostatus', statuses.size <= 1);

    // Todo arranca colapsado, salvo que no haya nada que elegir (un solo grupo o un
    // deep-link a una vacante) o que estés buscando: con término activo, dejar los grupos
    // cerrados haría parecer que el buscador no encuentra nada.
    const autoOpen = !!term || groups.size === 1 || !!deepOppId;

    const html = [...groups.entries()].map(([oppId, rows]) => {
      const first = rows[0];
      const open = autoOpen || openGroups.has(oppId);

      // El recruiter sube al encabezado sólo si es el mismo para todo el grupo; si no,
      // baja a cada fila, que es donde recién ahí distingue algo.
      const recs = new Set(rows.map(r => r.recruiter_email || '—'));
      const sharedRec = recs.size === 1 ? [...recs][0] : '';

      const sub = [first.client_name || '—', sharedRec].filter(Boolean).join(' · ');
      const n = rows.length;

      // El encabezado usa las MISMAS cuatro celdas que las filas (nada de colspan): así el
      // contador y la antigüedad del grupo caen en columnas reales y alinean con los datos
      // de abajo en vez de flotar según lo largo que sea el nombre de la vacante. El
      // contador va pegado al chevron, con ancho fijo, para que arranque siempre en la
      // misma x sin importar el grupo.
      const head = `
      <tr class="cvr-grp-head" role="button" tabindex="0" aria-expanded="${open}">
        <td class="cvr-grp-cell">
          <i class="fa-solid fa-chevron-right cvr-chev"></i>
          <span class="cvr-grp-count">${n} CV${n === 1 ? '' : 's'}</span>
          <span class="cvr-grp-txt">
            <span class="cvr-grp-title">${esc(first.opp_position_name || '—')}</span>
            <span class="cvr-oppid">#${esc(oppId)}</span>
            <span class="cvr-grp-sub">${esc(sub)}</span>
          </span>
        </td>
        <td class="cvr-col-score"></td>
        <td class="cvr-col-status"></td>
        <td class="cvr-col-age">${groupAge(rows)}</td>
      </tr>`;

      const body = rows.map(r => {
        const [label, cls] = STATUS[r.status] || [r.status, ''];
        // Ronda 1 es el caso normal y no se muestra: el chip aparece recién cuando el CV
        // ya volvió al menos una vez, que es la única ronda que dice algo.
        const round = Number(r.round) > 1
          ? `<span class="cvr-round-chip">R${esc(r.round)}</span>` : '';
        const rec = sharedRec ? ''
          : `<div class="cvr-row-sub">${esc(r.recruiter_email || '—')}</div>`;
        return `
        <tr class="cvr-row" data-review-id="${r.review_id}" tabindex="0">
          <td><div class="cvr-cand">${esc(r.candidate_name || 'Candidate')}${round}</div>${rec}</td>
          <td class="cvr-col-score">${covCell(r)}</td>
          <td class="cvr-col-status"><span class="hx-status ${cls}">${esc(label)}</span></td>
          <td class="cvr-col-age">${ageCell(r)}</td>
        </tr>`;
      }).join('');

      return `<tbody class="cvr-grp${open ? '' : ' is-closed'}" data-opp="${esc(oppId)}">${head}${body}</tbody>`;
    }).join('');

    clearQueue();
    $('cvrQueueTable').insertAdjacentHTML('beforeend', html);
  }

  // Un solo par de listeners delegados en la tabla, en vez de re-adjuntar N handlers en
  // cada render (y el render se dispara con cada tecla del buscador).
  function wireQueue() {
    const table = $('cvrQueueTable');

    const hit = (e) => {
      const head = e.target.closest('.cvr-grp-head');
      if (head) return () => toggleGroup(head);
      const row = e.target.closest('.cvr-row');
      if (row) return () => openDrawer(Number(row.dataset.reviewId));
      return null;
    };

    table.addEventListener('click', e => { const act = hit(e); if (act) act(); });
    table.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const act = hit(e);
      if (act) { e.preventDefault(); act(); }
    });
  }

  function wireMetricsToggle() {
    const head = $('cvrMetricsToggle');
    const panel = $('cvrMetricsPanel');
    const toggle = () => {
      const open = panel.hidden;
      panel.hidden = !open;
      head.setAttribute('aria-expanded', String(open));
      head.classList.toggle('is-open', open);
    };
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  }

  function toggleGroup(head) {
    const grp = head.closest('.cvr-grp');
    if (!grp) return;
    const open = grp.classList.toggle('is-closed') === false;
    head.setAttribute('aria-expanded', String(open));
    if (open) openGroups.add(grp.dataset.opp);
    else openGroups.delete(grp.dataset.opp);
  }


  /* ------------------------------------------------- resaltar el CV en el iframe
   *
   * El panel de la derecha cita frases del CV: la evidencia de cada requisito de la JD,
   * las afirmaciones que la fuente no respalda, el eco de la JD, la evidencia de cada
   * criterio. Antes había que leer el CV entero para encontrar dónde estaba cada una.
   * Ahora cada cita se pinta DENTRO del iframe con el color de su categoría y, al tocarla
   * en el panel, el CV salta a ella.
   *
   * Se usa la CSS Custom Highlight API (CSS.highlights + ::highlight()) a propósito y no
   * <mark>: no toca el DOM del CV. El "Download PDF" del iframe rasteriza con html2canvas,
   * así que envolver texto en <mark> se llevaría los colores del review adentro del PDF
   * que ve el cliente. Un highlight no existe para html2canvas.
   *
   * Si el navegador no soporta la API, las citas siguen siendo clickeables y el CV igual
   * hace scroll hasta la frase: se pierde el color, no la navegación.
   */

  // `help` es lo que se lee en la clave de colores. Un color sin explicación obliga a
  // adivinar, y adivinando el rojo parece "la recruiter hizo algo mal" cuando puede ser
  // simplemente que el candidato no encaja.
  const HL_KINDS = [
    { key: 'described', label: 'Backs a JD requirement',      bg: '#dcffab', ink: '#2f5c00', dot: '#a9e05a',
      help: 'A role in the experience actually describes doing what the JD asked for — not just a tool sitting in a list. It earns the full share of the score.' },
    { key: 'listed',    label: 'Only listed, not described',  bg: '#ffeeb8', ink: '#6b4a00', dot: '#f0c14b',
      help: 'The requirement shows up somewhere in the CV, but no role tells the story of using it. Half the share: a client reads these two very differently.' },
    { key: 'hard',      label: "The originals don't support it", bg: '#ffcdd8', ink: '#7a0c22', dot: '#e8637f',
      help: "The CV says something the originals — the candidate's own CV and their LinkedIn — don't back up. This is the one to send back." },
    { key: 'soft',      label: 'Worth double-checking',       bg: '#ffe2c6', ink: '#7a3a00', dot: '#f0a45a',
      help: 'Wording that may be stretching what the originals say. Not necessarily wrong — worth a second look before it goes out.' },
    { key: 'echo',      label: 'Copied from the JD',          bg: '#e3d8ff', ink: '#3b1e8f', dot: '#a48bff',
      help: 'Sentences lifted from the job posting. Aligning with the JD is good; reusing its wording means the client reads their own posting back as experience.' },
    // Legacy: sólo aparece en análisis v≤9, que llevan la rúbrica adentro. hlRenderLegend
    // esconde las categorías sin coincidencias, así que en un análisis nuevo el chip no sale.
    { key: 'crit',      label: 'Cited by the old rubric',      bg: '#d3e6ff', ink: '#0a3a7a', dot: '#6fa8ff',
      help: 'A phrase the old six-criteria rubric quoted as evidence. It only shows up on rounds scored before the score became JD coverage.' },
  ];
  const HL_NAME = (key) => `cvrhl-${key}`;

  // Lo que el modelo devuelve cuando NO tiene una cita: no es texto del CV y no se busca.
  const HL_NOT_A_QUOTE = /^(not found in the cv|computed from the cv)/i;

  const hlState = {
    list: [],          // [{ id, kind, text, ranges, located }]
    byId: new Map(),
    seq: 0,
    idx: null,         // índice de texto del CV renderizado
    token: 0,          // corta los polls de un CV que ya no está en pantalla
    on: true,
    active: null,
    cursor: {},        // por categoría, para el "siguiente" de la leyenda
    flashWait: null,   // espera a que termine el scroll
    flashClear: null,  // limpieza de la capa del destello
  };

  // Un caracter del CV y uno de la cita tienen que compararse igual: comillas curvas,
  // guiones largos y espacios raros vienen de fuentes distintas. El mapeo es 1:1 a
  // propósito — el índice guarda un nodo por caracter emitido.
  const HL_CHAR_MAP = {
    '\u2018': "'", '\u2019': "'", '\u02bc': "'", '\u201b': "'",
    '\u201c': '"', '\u201d': '"', '\u201e': '"',
    '\u2010': '-', '\u2011': '-', '\u2012': '-', '\u2013': '-', '\u2014': '-', '\u2212': '-',
    '\u00a0': ' ', '\u2007': ' ', '\u2009': ' ', '\u200a': ' ', '\u202f': ' ',
    '\u200b': ' ', '\u200c': ' ', '\u200d': ' ', '\ufeff': ' ',
  };
  function hlNormChar(ch) {
    const mapped = HL_CHAR_MAP[ch];
    if (mapped !== undefined) return mapped;
    if (ch === '\n' || ch === '\r' || ch === '\t' || ch === ' ') return ' ';
    const lower = ch.toLowerCase();
    return lower.length === 1 ? lower : ch;
  }

  function hlNormalize(str) {
    let out = '';
    let lastSpace = true;
    const s = String(str || '');
    for (let i = 0; i < s.length; i++) {
      const ch = hlNormChar(s[i]);
      if (ch === ' ') { if (lastSpace) continue; lastSpace = true; } else { lastSpace = false; }
      out += ch;
    }
    return out;
  }

  // Las citas llegan con comillas y puntuación de cierre que el CV no tiene pegada.
  const hlTrimQuote = (q) => q.replace(/^["'\s]+/, '').replace(/["'\s]+$/, '').replace(/[.,;:!?]+$/, '').trim();

  /* --- el índice: texto plano del CV + a qué nodo pertenece cada caracter ---------- */
  /* Sin esto sólo se podrían encontrar frases que caen enteras dentro de un mismo nodo
     de texto, y en el CV el rol, la empresa y las fechas son elementos distintos. */
  function hlBuildIndex(doc) {
    const root = doc.querySelector('.cv-container') || doc.body;
    if (!root) return null;
    const walker = doc.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        const p = n.parentElement;
        if (!p) return NodeFilter.FILTER_REJECT;
        // El panel de rating y el botón de descarga son chrome, no el CV.
        if (p.closest('script, style, #resume-rating, .resume-download-button')) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    let text = '';
    const owner = [];
    let lastSpace = true;
    let node;
    while ((node = walker.nextNode())) {
      const raw = node.nodeValue;
      for (let i = 0; i < raw.length; i++) {
        const ch = hlNormChar(raw[i]);
        if (ch === ' ') { if (lastSpace) continue; lastSpace = true; } else { lastSpace = false; }
        text += ch;
        owner.push({ node, i });
      }
      // Corte entre nodos: sin este espacio, "English" y "Fluent" de dos <span> vecinos
      // se leerían como una sola palabra. Nunca cae en el borde de un match porque las
      // citas se buscan ya trimmeadas.
      if (!lastSpace && raw.length) {
        text += ' ';
        owner.push({ node, i: raw.length - 1 });
        lastSpace = true;
      }
    }
    return { doc, text, owner };
  }

  function hlRange(idx, start, end) {
    const a = idx.owner[start];
    const b = idx.owner[end - 1];
    if (!a || !b) return null;
    try {
      const r = idx.doc.createRange();
      r.setStart(a.node, a.i);
      r.setEnd(b.node, b.i + 1);
      return r;
    } catch (_) { return null; }
  }

  function hlFindAll(idx, needle, cap) {
    const out = [];
    if (!needle || needle.length < 10) return out;
    const limit = cap || 3;
    let from = 0;
    while (out.length < limit) {
      const at = idx.text.indexOf(needle, from);
      if (at < 0) break;
      const r = hlRange(idx, at, at + needle.length);
      if (r) out.push(r);
      from = at + needle.length;
    }
    return out;
  }

  // Buscar un NOMBRE de herramienta. Es un port de _tool_needle() en
  // backend/utils/cv_review_ai.py:1432 y tiene que encontrar exactamente lo mismo que el
  // backend contó como "described": si divergen, un chip verde no llevaría a ninguna parte.
  // SI TOCÁS UNO, TOCÁ EL OTRO.
  //   · Se parte en tokens con la MISMA regla, que separa camelCase: "Power BI" y "PowerBI"
  //     dan los dos ["power","bi"], así que cualquiera de las dos escrituras encuentra a la
  //     otra. Entre token y token se admiten hasta 2 caracteres que no sean alfanuméricos
  //     ("power bi", "power-bi", "powerbi").
  //   · Los bordes se chequean a mano en vez de con lookbehind: es lo que impide que
  //     "Excel" matchee dentro de "Excellent", y no depende de soporte de regex del navegador.
  const HL_TERM_TOKENS = /[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z]+|[0-9]+/g;
  function hlTermPattern(raw) {
    const parts = String(raw || '').match(HL_TERM_TOKENS);
    if (!parts) return null;
    const esc = parts.map(p => p.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    if (esc.join('').length < 3) return null;
    return new RegExp(esc.join('[^a-z0-9]{0,2}'), 'g');
  }

  function hlFindTerm(idx, raw, cap) {
    const out = [];
    const re = hlTermPattern(raw);
    if (!re) return out;
    const limit = cap || 8;
    let m;
    while ((m = re.exec(idx.text)) && out.length < limit) {
      const at = m.index;
      const end = at + m[0].length;
      const before = at > 0 ? idx.text[at - 1] : ' ';
      const after = idx.text[end] || ' ';
      if (!/[a-z0-9]/.test(before) && !/[a-z0-9]/.test(after)) {
        const r = hlRange(idx, at, end);
        if (r) out.push(r);
      }
      if (re.lastIndex === at) re.lastIndex = at + 1;   // patrón vacío: no colgarse
    }
    return out;
  }

  // Ubicar una cita, con dos degradés. El modelo lee el CV serializado como texto
  // ("Título — Empresa [2021-01-15 → Present]"), que no es lo que la pantalla muestra:
  // la pantalla dice "Jan 2025 – Dec 2025" y parte el rol y la empresa en dos elementos.
  // Por eso, si la frase entera no aparece, se resaltan los trozos que sí existen.
  function hlLocate(idx, rawQuote) {
    const q = hlTrimQuote(hlNormalize(rawQuote));
    if (q.length < 10) return [];

    const exact = hlFindAll(idx, q);
    if (exact.length) return exact;

    let hits = [];
    const segments = q.split(/\s*[[\]()|·•;]\s*|\s+-\s+|\s*→\s*/)
      .map(hlTrimQuote)
      .filter(s => s.length >= 12 && s.indexOf(' ') > 0);
    if (segments.length > 1) {
      segments.forEach(s => { hits = hits.concat(hlFindAll(idx, s, 2)); });
      if (hits.length) return hits;
    }

    // Última chance: la ventana de palabras más larga que sí aparece. Cubre las
    // diferencias de borde (un punto, un artículo de más) sin inventar coincidencias:
    // se exige al menos la mitad de la cita.
    const words = q.split(' ');
    const floor = Math.max(4, Math.ceil(words.length * 0.5));
    for (let len = words.length - 1; len >= floor; len--) {
      for (let s = 0; s + len <= words.length; s++) {
        const win = words.slice(s, s + len).join(' ');
        if (win.length < 14) continue;
        const found = hlFindAll(idx, win, 1);
        if (found.length) return found;
      }
    }
    return [];
  }

  /* --- registro de citas: lo llama aiPanelHtml mientras arma el panel -------------- */

  function hlResetQuotes() {
    hlState.list = [];
    hlState.byId = new Map();
    hlState.seq = 0;
    hlState.active = null;
    hlState.cursor = {};
  }

  function hlResetFrame() {
    hlState.idx = null;
    hlState.token += 1;
    hlRenderLegend();
  }

  // Devuelve el atributo listo para pegar en el HTML, o '' si la cita no es citable:
  // así el panel no queda con anzuelos muertos que no llevan a ninguna parte.
  //
  // `opts.term` es para NOMBRES, no para frases: una herramienta ("Excel", "Power BI").
  // Cambia las dos cosas que hacían imposible buscarlos — el piso de 10 caracteres y la
  // búsqueda por substring, que hacía que "Excel" cayera dentro de "Excellent". Un término
  // se busca con bordes de palabra (hlFindTerm) y por eso puede ser corto sin mentir.
  function hlRegister(kind, text, opts) {
    const t = String(text || '').trim();
    const term = !!(opts && opts.term);
    if (term ? t.length < 3 : (t.length < 10 || HL_NOT_A_QUOTE.test(t))) return '';
    const id = `q${++hlState.seq}`;
    const entry = { id, kind, text: t, term, ranges: [], located: false };
    hlState.list.push(entry);
    hlState.byId.set(id, entry);
    return ` data-hl="${id}"`;
  }

  /* --- pintar ---------------------------------------------------------------------- */

  const HL_STYLE_ID = 'cvr-hl-style';
  function hlInjectStyle(doc) {
    if (doc.getElementById(HL_STYLE_ID)) return;
    // ::highlight() no admite animaciones, así que el destello del aterrizaje es una capa
    // aparte, absoluta y sin pointer-events, encima de la frase.
    const css = HL_KINDS
      .map(k => `::highlight(${HL_NAME(k.key)}){background-color:${k.bg};color:${k.ink};}`)
      .join('\n')
      + '\n::highlight(cvrhl-active){background-color:#003bff;color:#fff;}'
      + `
.cvr-hl-flash{
  position:absolute;
  pointer-events:none;
  border-radius:5px;
  background:rgba(0,59,255,.16);
  box-shadow:0 0 0 2px rgba(0,59,255,.95), 0 0 20px 7px rgba(0,59,255,.45);
  animation:cvrHlFlash 1.05s ease-out 2 both;
}
@keyframes cvrHlFlash{
  0%{opacity:0;transform:scale(1.09)}
  18%{opacity:1;transform:scale(1)}
  100%{opacity:0;transform:scale(1)}
}
@media (prefers-reduced-motion: reduce){
  .cvr-hl-flash{animation:none;opacity:.85}
}`;
    const style = doc.createElement('style');
    style.id = HL_STYLE_ID;
    style.textContent = css;
    (doc.head || doc.documentElement).appendChild(style);
  }

  function hlFrameWin() {
    try { return $('cvrFrame').contentWindow; } catch (_) { return null; }
  }

  // El destello del aterrizaje: dos pulsos azules encima de la frase a la que se saltó.
  // Sin esto el scroll deja el CV en el lugar correcto pero el ojo no sabe dónde mirar,
  // sobre todo cuando la cita es corta y cae en el medio de un párrafo.
  const HL_FLASH_ID = 'cvr-hl-flash-layer';
  function hlFlash(win, ranges) {
    const doc = win.document;
    const old = doc.getElementById(HL_FLASH_ID);
    if (old) old.remove();
    if (hlState.flashClear) clearTimeout(hlState.flashClear);

    const layer = doc.createElement('div');
    layer.id = HL_FLASH_ID;
    // html2canvas saltea lo que lleve este atributo: si alguien toca "Download PDF"
    // justo durante el destello, el destello no se mete en el PDF del cliente.
    layer.setAttribute('data-html2canvas-ignore', 'true');
    layer.style.cssText = 'position:absolute;top:0;left:0;width:0;height:0;'
      + 'z-index:2147483000;pointer-events:none;';
    doc.body.appendChild(layer);

    // El origen se mide, no se asume: el body puede tener margen o ser el contenedor
    // relativo, y ahí las coordenadas de documento no coincidirían.
    const origin = layer.getBoundingClientRect();
    let boxes = 0;
    ranges.forEach(r => {
      // getClientRects y no getBoundingClientRect: una frase que corta en dos líneas
      // necesita dos cajas, no una que se coma el margen entero.
      Array.from(r.getClientRects()).forEach(rect => {
        if (!rect.width || !rect.height) return;
        const box = doc.createElement('div');
        box.className = 'cvr-hl-flash';
        box.style.left = `${rect.left - origin.left - 3}px`;
        box.style.top = `${rect.top - origin.top - 2}px`;
        box.style.width = `${rect.width + 6}px`;
        box.style.height = `${rect.height + 4}px`;
        layer.appendChild(box);
        boxes += 1;
      });
    });
    if (!boxes) { layer.remove(); return; }
    hlState.flashClear = setTimeout(() => { if (layer.parentNode) layer.remove(); }, 2400);
  }

  function hlApply() {
    const win = hlFrameWin();
    if (!win || !win.CSS || !win.CSS.highlights || !win.Highlight) return;
    win.CSS.highlights.clear();
    if (!hlState.on) return;

    const groups = {};
    hlState.list.forEach(e => {
      if (!e.ranges.length || e.id === hlState.active) return;
      // Los NOMBRES no se pintan siempre, sólo cuando se los toca. Un CV lista 8 o 10
      // herramientas y cada una cae varias veces — pintarlas todas dejaría la sección de
      // Tools resaltada de punta a punta y taparía las citas, que son lo que se lee.
      // Cuando se hace click, el resaltado azul de "activa" y el destello alcanzan.
      if (e.term) return;
      (groups[e.kind] = groups[e.kind] || []).push(...e.ranges);
    });
    HL_KINDS.forEach((k, i) => {
      const ranges = groups[k.key];
      if (!ranges || !ranges.length) return;
      const h = new win.Highlight(...ranges);
      h.priority = i + 1;
      win.CSS.highlights.set(HL_NAME(k.key), h);
    });

    // La cita seleccionada va en su propio highlight y con prioridad máxima: es la única
    // manera de que se distinga cuando cae encima de otra.
    const act = hlState.active && hlState.byId.get(hlState.active);
    if (act && act.ranges.length) {
      const h = new win.Highlight(...act.ranges);
      h.priority = 100;
      win.CSS.highlights.set('cvrhl-active', h);
    }
  }

  // Marca en el panel qué citas se pudieron ubicar. Sólo esas se comportan como botón.
  function hlMarkPanel() {
    // También los que sólo traen data-hl-title: un chip de herramienta demasiado corta para
    // buscar (el backend ni la evalúa) no se registra, y sin esto se quedaría sin tooltip.
    $('cvrAi').querySelectorAll('[data-hl], [data-hl-title]').forEach(el => {
      const e = hlState.byId.get(el.getAttribute('data-hl'));
      const ok = !!(e && e.ranges.length);
      el.classList.toggle('cvr-hl-item', ok);
      el.classList.toggle('is-active', ok && hlState.active === e.id);
      // Un elemento puede traer su propia explicación (los chips de herramienta dicen si
      // algún rol la describe). Se respeta y sólo se le suma el "click": pisarla perdería
      // lo único que distingue un chip verde de uno gris, y ponerle "click" a uno que no se
      // pudo ubicar sería prometer un salto que no va a pasar.
      const own = el.getAttribute('data-hl-title');
      if (ok) {
        el.dataset.hlKind = e.kind;
        el.setAttribute('role', 'button');
        el.setAttribute('tabindex', '0');
        el.setAttribute('title', own ? `${own} Click to show it in the CV.`
                                     : 'Show this phrase in the CV');
      } else {
        el.removeAttribute('role');
        el.removeAttribute('tabindex');
        if (own) el.setAttribute('title', own); else el.removeAttribute('title');
      }
    });
  }

  // La clave de colores. Se dibuja desde HL_KINDS, no a mano: si algún día se cambia un
  // color o una categoría, la explicación se mueve con él en vez de quedar mintiendo.
  function hlRenderKey() {
    const box = $('cvrHlKeyBody');
    if (!box || box.dataset.done) return;
    box.dataset.done = '1';
    box.innerHTML = `
      <p class="cvr-hl-key-lead">Every phrase the analysis quotes is painted on the CV with
        the colour of what it found. Click any quote in the panel — or a chip above — to
        jump straight to it.</p>
      <ul>
        ${HL_KINDS.map(k => `
          <li>
            <i class="cvr-hl-key-sw" style="background:${k.bg};border-color:${k.dot}"></i>
            <span><b>${esc(k.label)}</b> — ${esc(k.help)}</span>
          </li>`).join('')}
        <li>
          <i class="cvr-hl-key-sw" style="background:#003bff;border-color:#003bff"></i>
          <span><b>Solid blue</b> — the phrase you just jumped to. It goes back to its own
            colour as soon as you pick another one.</span>
        </li>
      </ul>
      <p class="cvr-hl-key-foot">A quote the analysis makes but that is nowhere in this CV
        gets no colour and no jump — the counter at the end of the row says how many.</p>`;
  }

  function hlRenderLegend() {
    const box = $('cvrHlLegend');
    if (!box) return;
    const counts = {};
    let missing = 0;
    hlState.list.forEach(e => {
      // Los nombres de herramienta no entran: no se pintan solos, así que un chip con su
      // cuenta prometería un color que no está, y sumarlos a "no encontradas" mezclaría
      // una herramienta que el CV no nombra con una cita que el modelo pudo haber inventado.
      if (e.term) return;
      if (e.ranges.length) counts[e.kind] = (counts[e.kind] || 0) + 1;
      else if (e.located) missing += 1;
    });
    const chips = HL_KINDS.filter(k => counts[k.key]).map(k => `
      <button type="button" class="cvr-hl-chip" data-hl-kind="${k.key}"
              style="--cvr-hl-c:${k.dot}" title="Jump to the next one in the CV">
        <i class="cvr-hl-dot"></i>${esc(k.label)} <b>${counts[k.key]}</b>
      </button>`).join('');
    // Decirlo importa: si una cita no está en el CV que se ve, o el modelo la inventó o
    // la recruiter editó el CV después. Callarlo haría creer que ya está todo pintado.
    const miss = missing
      ? `<span class="cvr-hl-miss" title="These quotes could not be matched against the CV shown here.">${missing} quote${missing > 1 ? 's' : ''} not found in this CV</span>`
      : '';
    box.innerHTML = chips + miss;
    box.classList.toggle('is-off', !hlState.on);
    show(box, !!(chips || miss));
  }

  // Localiza lo que falte y repinta. Es idempotente: la llaman tanto el render del panel
  // como el load del iframe, y cualquiera de los dos puede llegar primero.
  function hlSync() {
    if (!hlState.idx) { hlRenderLegend(); return; }
    hlState.list.forEach(e => {
      if (e.located) return;
      e.ranges = e.term ? hlFindTerm(hlState.idx, e.text)
                        : hlLocate(hlState.idx, e.text);
      e.located = true;
    });
    hlApply();
    hlMarkPanel();
    hlRenderLegend();
  }

  // El iframe pide el CV por fetch y lo dibuja DESPUÉS del load, así que "load" no
  // alcanza. Y esperar sólo a que el texto se estabilice tampoco: el HTML trae un
  // esqueleto con placeholders ("Candidate Name", el About de ejemplo) que ya mide lo
  // suficiente como para parecer un CV cargado. Se espera a que el nombre real esté
  // puesto y recién ahí a que el texto deje de crecer.
  const HL_PLACEHOLDERS = ['candidate name', 'click here to edit your about section.'];
  function hlFrameRendered(doc) {
    const name = (doc.getElementById('candidateNameTitle')?.textContent || '').trim().toLowerCase();
    if (!name || HL_PLACEHOLDERS.includes(name)) return false;
    const about = (doc.getElementById('aboutField')?.textContent || '').trim().toLowerCase();
    return !HL_PLACEHOLDERS.includes(about);
  }

  function hlAttach() {
    const token = hlState.token;
    let tries = 0;
    let lastLen = -1;
    (function tick() {
      if (token !== hlState.token) return;   // se cerró el drawer o se abrió otro CV
      let doc = null;
      try { doc = $('cvrFrame').contentDocument; } catch (_) { doc = null; }
      const len = doc && doc.body && hlFrameRendered(doc)
        ? (doc.body.textContent || '').replace(/\s+/g, ' ').trim().length
        : -1;
      if (len < 0 || len !== lastLen) {
        lastLen = len;
        if (++tries < 75) setTimeout(tick, 200);
        return;
      }
      hlInjectStyle(doc);
      hlState.idx = hlBuildIndex(doc);
      hlState.list.forEach(e => { e.located = false; e.ranges = []; });
      hlSync();
    })();
  }

  function hlGoTo(id) {
    const e = hlState.byId.get(id);
    if (!e || !e.ranges.length) return;
    hlState.active = id;
    // Tocar una cita con el resaltado apagado lo vuelve a prender: es lo que se pidió.
    if (!hlState.on) {
      hlState.on = true;
      const sw = $('cvrHlSwitch');
      if (sw) sw.checked = true;
    }
    hlApply();
    hlMarkPanel();
    hlRenderLegend();

    // La métrica también se enciende: al volver la vista al panel tiene que quedar claro
    // cuál de todas es la que está pintada de azul en el CV.
    const item = $('cvrAi').querySelector(`[data-hl="${id}"]`);
    if (item) {
      // La cita puede vivir en una sección plegada. Sin abrirla, el pulso ocurriría en un
      // elemento invisible y el chip de la leyenda parecería no hacer nada.
      let d = item.closest('details');
      while (d) {
        d.open = true;
        d = d.parentElement ? d.parentElement.closest('details') : null;
      }
      item.classList.remove('is-flash');
      void item.offsetWidth;   // reinicia la animación si se vuelve a tocar la misma cita
      item.classList.add('is-flash');
      setTimeout(() => item.classList.remove('is-flash'), 1100);
    }

    const win = hlFrameWin();
    if (!win) return;
    // Una cita puede caer en más de un lugar (el About repite lo que dice la experiencia).
    // Se va a la primera del documento, no a la primera que encontró el buscador.
    //
    // Con una herramienta hay una preferencia más: el nombre está SIEMPRE en la lista de
    // Tools del CV, y saltar ahí no le dice nada a nadie — lo que se quiere ver es el rol
    // que la usa. Si aparece en algún lado fuera de esa lista, se va ahí.
    let ranges = e.ranges;
    if (e.term) {
      const outside = ranges.filter(r => {
        const el = r.startContainer.parentElement;
        return el && !el.closest('#toolsSection');
      });
      if (outside.length) ranges = outside;
    }
    const rects = ranges.map(r => r.getBoundingClientRect()).filter(r => r.height);
    if (!rects.length) return;
    const rect = rects.reduce((a, b) => (b.top < a.top ? b : a));
    const raw = rect.top + win.scrollY - (win.innerHeight / 2) + (rect.height / 2);
    const maxTop = Math.max(0, win.document.documentElement.scrollHeight - win.innerHeight);
    const target = Math.max(0, Math.min(raw, maxTop));
    win.scrollTo({ top: target, behavior: 'smooth' });

    // El destello va DESPUÉS del scroll: durante la animación las coordenadas cambian y
    // las cajas quedarían dibujadas donde la frase ya no está.
    if (hlState.flashWait) clearTimeout(hlState.flashWait);
    const token = hlState.token;
    let fired = false;
    const fire = () => {
      if (fired || token !== hlState.token) return;
      fired = true;
      hlFlash(win, ranges);
    };
    if (Math.abs(win.scrollY - target) < 4) {
      // Ya estaba a la vista: no hay scroll que esperar y esperar se notaría como lag.
      // setTimeout y no requestAnimationFrame: rAF no corre con la pestaña en segundo
      // plano, y ahí el destello no llegaría nunca.
      hlState.flashWait = setTimeout(fire, 40);
    } else {
      if ('onscrollend' in win) win.addEventListener('scrollend', fire, { once: true });
      // Red de seguridad: scrollend no existe en todos lados y un scroll interrumpido
      // por la rueda del mouse tampoco lo dispara.
      hlState.flashWait = setTimeout(fire, 750);
    }
  }

  // La leyenda no es sólo leyenda: cada chip recorre una a una las citas de su color.
  function hlNextOfKind(kind) {
    const items = hlState.list.filter(e => e.kind === kind && e.ranges.length);
    if (!items.length) return;
    const n = (hlState.cursor[kind] || 0) % items.length;
    hlState.cursor[kind] = n + 1;
    hlGoTo(items[n].id);
    const el = $('cvrAi').querySelector(`[data-hl="${items[n].id}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  /* ---------------------------------------------------------------- el panel */


  // Encabezado común de todo lo que el sales lead mira antes de decidir: ícono, título y
  // a la derecha el único dato que se busca de un vistazo — cuánto se llevó del score, o
  // en cuántas vacantes viene el candidato.
  const scoreHead = (icon, title, cls, chip) => `<h5 class="cvr-hop-head">
      <i class="fa-solid ${icon}"></i>
      <span>${title}</span>
      <span class="cvr-hop-chip ${cls}">${chip}</span>
    </h5>`;

  function aiPanelHtml(review) {
    // El panel se rearma entero, así que las citas registradas se rearman con él.
    hlResetQuotes();
    const a = review.ai_analysis;
    if (!a) {
      if (review.ai_error === 'no_jd') {
        return `<p class="cvr-ai-none">No score: opportunity #${review.opportunity_id} has no job
          description, and the score is the share of the JD's requirements this CV shows — with no
          JD there is nothing to measure. Add the JD, then re-run.</p>`;
      }
      if (review.ai_error === 'budget') {
        return '<p class="cvr-ai-none">No score: the OpenAI budget for this month is exhausted.</p>';
      }
      if (review.ai_error) return '<p class="cvr-ai-none">The AI score could not be computed. Try re-running.</p>';
      return '<p class="cvr-ai-none">Scoring…</p>';
    }

    const score = a._composite_score;

    // Un análisis v≤9 se lleva la rúbrica adentro y hay que seguir dibujándola: la decisión
    // que justificó ya se tomó, y el número no se puede recomputar sin gastar presupuesto
    // de OpenAI y cambiarle el valor a algo que ya pasó. Se detecta por el DATO y no por
    // _version: un blob a medio migrar tiene que caer en el camino nuevo, no en uno vacío.
    const legacy = Array.isArray(a._rubric) && a._rubric.length > 0;

    // El desglose se dibuja desde el _rubric guardado con el análisis, no desde la
    // rúbrica actual: así una ronda vieja sigue mostrando con qué pesos se puntuó.
    const byKey = {};
    (a.criteria || []).forEach(c => { byKey[c.key] = c; });
    const bars = (a._rubric || []).map(rb => {
      const c = byKey[rb.key] || {};
      const na = c.not_applicable || c.score === null || c.score === undefined;
      return `
      <div>
        <div class="cvr-crit-head">
          <span>${esc(rb.label)}${rb.computed ? ' <i class="cvr-crit-calc" title="Computed from the CV, not by the model">calc</i>' : ''}</span>
          <b>${na ? 'n/a' : c.score}</b>
          <span class="cvr-crit-w">${rb.weight}</span>
        </div>
        <div class="cvr-crit-bar"><span style="width:${na ? 0 : Math.max(0, Math.min(100, c.score))}%"></span></div>
        ${c.verdict ? `<p class="cvr-crit-note">${esc(deSource(c.verdict))}</p>` : ''}
        ${c.evidence ? `<p class="cvr-crit-ev"${hlRegister('crit', c.evidence)}>“${esc(c.evidence)}”</p>` : ''}
      </div>`;
    }).join('');

    // El criterio más flojo va en la línea del pliegue: es lo único del desglose que
    // cambia una decisión, y así no hay que abrirlo para saber si vale la pena.
    const scored = (a._rubric || [])
      .map(rb => ({ rb, c: byKey[rb.key] || {} }))
      .filter(x => !(x.c.not_applicable || x.c.score === null || x.c.score === undefined));
    const weakest = scored.length
      ? scored.reduce((m, x) => (x.c.score < m.c.score ? x : m))
      : null;

    // Las herramientas que la experiencia usa de verdad contra las que sólo están en la
    // lista. NO mueve el número salvo el castigo único de no tener ninguna, y eso se dice
    // adentro: un aviso que parece un error hace que la recruiter "arregle" lo que no está
    // roto.
    //
    // Cada chip SALTA al lugar del CV donde está el nombre. Antes no se podía: hlRegister
    // exigía 10 caracteres y buscaba por substring, con lo cual "Excel" caía adentro de
    // "Excellent". Ahora van como término (hlFindTerm), que busca con bordes de palabra y
    // con la misma regla de tokens que usó el backend para contarlas — así un chip verde
    // aterriza justo en el bullet por el que se pintó de verde.
    const tc = a._tools_check || {};
    const toolChip = (t, described) => `<li class="cvr-tool${described ? ' is-described' : ''}"
        data-hl-title="${described
          ? 'A role describes using it.'
          : 'This CV lists it, but no role describes using it.'}"
        ${hlRegister('tool', t, { term: true })}>${esc(t)}</li>`;
    // La lista de herramientas es el OTRO descuento fijo, así que se lee al lado del de
    // job hopping y con la misma caja — plegada en el fondo se la tomaba por un adorno.
    // El bloque responde UNA pregunta: de las herramientas que pidió el cliente, ¿cuáles
    // muestra la experiencia? Antes recorría la lista de tools del CV y descontaba por no
    // describir la agenda del candidato, que nadie había pedido (rev95).
    const toolRow = (t, cls, note) => `<li class="cvr-tool ${cls}"
        data-hl-title="${esc(note)}" ${hlRegister('tool', t, { term: true })}>${esc(t)}</li>`;
    // `jd_tools` sólo existe desde este cambio. Un análisis guardado de antes tiene los
    // mismos nombres de campo con OTRO significado (las tools del CV, no las de la JD), y
    // pintarlo bajo este título diría algo falso. No se muestra hasta que se re-corra; su
    // castigo, si lo tuvo, sigue explicándose en la cuenta del score.
    const toolsHtml = (Array.isArray(tc.jd_tools) && (tc.checked || 0)) ? `
      <div class="cvr-hop cvr-hop--tools ${tc.penalty ? 'is-bad' : 'is-ok'}" id="cvrTools">
        ${scoreHead('fa-screwdriver-wrench', 'Tools the posting asks for',
                    tc.penalty ? 'is-bad' : 'is-ok',
                    tc.penalty ? `&minus;${tc.penalty} pts` : 'no penalty')}
        <p class="cvr-hop-lead">${tc.penalty
          ? `<b>This one did move the score.</b> This CV claims
             <b>${esc((tc.listed_only || []).join(', '))}</b> &mdash; in the tools list, the
             About or the education &mdash; but <b>no role describes using
             ${(tc.listed_only || []).length === 1 ? 'it' : 'any of them'}</b>. Naming a tool
             is free; what a client believes is the role that describes using it. `
          : `<b>${(tc.described || []).length} of the ${tc.checked} tool${tc.checked === 1 ? '' : 's'}
             the posting asks for ${(tc.described || []).length === 1 ? 'is' : 'are'} described
             in a role.</b> Nothing came off the score. `}<b>Click any of them to jump to it
          in the CV.</b></p>
        <ul class="cvr-tool-chips">
          ${(tc.described || []).map(t => toolRow(t, 'is-described',
              'The posting asks for it and a role describes using it.')).join('')}
          ${(tc.listed_only || []).map(t => toolRow(t, 'is-listed',
              'The posting asks for it and this CV names it — in the tools list, the About '
              + 'or the education — but no role describes using it.')).join('')}
          ${(tc.absent || []).map(t => toolRow(t, 'is-absent',
              'The posting asks for it and it is nowhere in this CV. That gap is already '
              + 'counted in the requirements list above, so it costs nothing extra here.')).join('')}
        </ul>
        ${/* Lo que el CV lista y nadie pidió. No puntúa ni descuenta: saber que hay seis
             herramientas sueltas sin respaldo sigue siendo un dato del documento, sólo que
             no de este puesto. */''}
        ${(tc.extra_listed || []).length ? `<p class="cvr-tool-extra">Also listed, and not
          asked for by this posting — no role describes ${(tc.extra_listed || []).length === 1
            ? 'it' : 'them'}, and nothing came off the score for that:
          <b>${esc((tc.extra_listed || []).join(', '))}</b>${
          (tc.extra_listed_total || 0) > tc.extra_listed.length
            ? ` and ${tc.extra_listed_total - tc.extra_listed.length} more` : ''}.</p>` : ''}
      </div>` : '';

    // Un pliegue. `open` sólo cuando lo de adentro puede cambiar la decisión ahora mismo.
    const fold = (title, meta, body, open) => body ? `
      <details class="cvr-fold"${open ? ' open' : ''}>
        <summary>
          <span class="cvr-fold-t">${title}</span>
          ${meta ? `<span class="cvr-fold-m">${meta}</span>` : ''}
        </summary>
        <div class="cvr-fold-b">${body}</div>
      </details>` : '';

    const claims = (list, kind, title) => list.length ? `
      <div class="cvr-find cvr-find--${kind}">
        <h5>${title}</h5>
        <ul>${list.map(c => `<li><q${hlRegister(kind === 'hard' ? 'hard' : 'soft', c.cv_quote)}>${esc(c.cv_quote)}</q> ${esc(deSource(c.why))}</li>`).join('')}</ul>
      </div>` : '';

    const hard = (a.unsupported_claims || []).filter(c => c.severity === 'hard');
    const soft = (a.unsupported_claims || []).filter(c => c.severity !== 'hard');

    // Eco de JD: advertencia, no acusación. No toca el score — alinear el CV con la JD
    // está bien; lo que está mal es que el cliente lea su propio aviso de vuelta.
    const echo = a.jd_echo || [];
    const echoHtml = echo.length ? `
      <div class="cvr-find cvr-find--echo">
        <h5>Wording copied from the job description (${echo.length})</h5>
        <p class="cvr-echo-lead">Aligning with the JD is good — reusing its sentences is not.
          The client ends up reading their own posting back as this candidate's experience.</p>
        <ul>${echo.map(e => `<li>
            <q${hlRegister('echo', e.cv_quote)}>${esc(e.cv_quote)}</q>
            ${e.jd_quote ? `<div class="cvr-echo-jd">JD: “${esc(e.jd_quote)}”</div>` : ''}
            ${e.why ? esc(deSource(e.why)) : ''}
          </li>`).join('')}</ul>
      </div>` : '';

    // Cobertura de la JD. Va arriba porque es lo primero que el reviewer necesita: qué
    // pedía la vacante y si el CV lo muestra. La distinción que importa no es
    // "aparece / no aparece" sino "está DESCRITO en la experiencia" vs "sólo figura en la
    // lista de tools", que es lo que un cliente lee distinto.
    // El estado visual no es sólo el status: un requisito que falta porque el candidato no
    // lo tiene NO es un defecto del CV y no se pinta en rojo como si la recruiter hubiera
    // hecho algo mal. Lo que decide es el cruce con in_source.
    // Dos ejes: qué muestra el CV (el badge) y si puntúa (la estructura — posición,
    // gris y una etiqueta). No se cruzan en una matriz: saldrían doce etiquetas que nadie
    // lee. `in_source` ya no cambia el badge; vive en la nota, que es donde dice si la
    // recruiter puede cerrar el hueco.
    const CREDIT = { described: 1, listed_only: 0.5, missing: 0 };
    const reqFace = r => {
      if (!r.counts) {
        let why = {
          assumed: { label: "Doesn't count — taken for granted", tag: 'taken for granted',
                     tip: 'Everyone in the running meets this, so counting it would flatter '
                        + 'every candidate equally. It is listed because the client asked '
                        + 'for it.' },
          language: { label: "Doesn't count — checked in the interview", tag: 'language',
                      tip: 'Every CV Vintti sends is written in English, so this requirement '
                         + 'is met by every candidate and tells you nothing. The real level '
                         + 'is judged from the recording and the interview, not the CV.' },
          soft: { label: "Doesn't count — soft skill", tag: 'soft skill',
                  tip: 'Soft skills are listed because the client asked for them, but they '
                     + 'do not score: any CV can claim them.' },
        }[r.no_score_reason] || { label: "Doesn't count", tag: '', tip: '' };
        // Cuando quien decidió que es soft fue el modelo y no una regla nuestra, se muestra
        // su razón. Sin esto, un requisito que se cae del score no tiene forma de discutirse:
        // el reviewer ve que no cuenta y no sabe por qué justo ése.
        if (r.kind_source === 'ai' && r.kind_why) why = Object.assign({}, why, {
          tip: (why.tip ? why.tip + ' ' : '') + 'Why this one: ' + r.kind_why,
        });
        return Object.assign({ cls: 'nocount' }, why);
      }
      // Un requisito de AÑOS no se arregla escribiendo mejor: o los años están o no están.
      // Decirle a la recruiter "you can add it" sobre un requisito de tiempo es pedirle que
      // invente fechas, que es lo contrario de todo lo demás en esta pantalla.
      if (r.years_required) {
        const yrs = (r.years_detail || {}).years;
        const got = yrs === null || yrs === undefined ? '' : `${yrs} of ${r.years_required} yrs · `;
        if (r.status === 'described') {
          return { cls: 'described', label: `${r.years_required}+ years covered`,
                   tip: got + 'Counted from the dates of the roles that do this kind of work. '
                      + 'Full credit.' };
        }
        if (r.status === 'listed_only') {
          return { cls: 'listed_only', label: 'Just short on years',
                   tip: got + 'Within a year of what the posting asks for, so it counts for '
                      + 'half. Nobody can fix this by rewriting the CV.' };
        }
        return { cls: 'missing', label: "Doesn't have the years",
                 tip: got + 'Counted from the dates of the roles that do this kind of work. '
                    + 'This is the candidate, not the CV — rewriting it cannot close the gap.' };
      }
      if (r.status === 'described') {
        // La inferencia se marca aparte aunque valga lo mismo: el CV NO dice esto, lo dice
        // el trabajo que el bullet describe. El reviewer tiene que poder ver que hubo un
        // razonamiento —y la cita de la que salió— para poder tumbarlo.
        if (r.by_inference) {
          return { cls: 'described', tag: 'inferred', tagCls: 'cvr-req-tag--inferred',
                   label: 'Covered by what the role does',
                   // Sin nota no se promete una explicación que no está: la fila se queda
                   // con la cita, que sigue siendo verificable.
                   tip: 'The CV never names this, but the work quoted below ordinarily '
                      + 'includes it, so it counts in full. '
                      + (r.note ? 'The note says the reasoning — if you do not buy it, this '
                                + 'is the one to push back on.'
                                : 'The analysis gave no reasoning for it, so judge it from '
                                + 'the quote alone.') };
        }
        return { cls: 'described', label: 'Described in the experience',
                 tip: 'A role in the work experience describes actually doing this, with a '
                    + 'quote to back it. Full credit.' };
      }
      // Medio punto sale por dos caminos muy distintos, y hasta ahora los dos decían
      // "only listed": el requisito está en una lista y ningún rol lo cuenta, O un rol
      // SÍ lo cuenta pero cubre una parte del requisito. `evidence_in_experience` lo
      // resuelve en el backend (la cita cae o no dentro de ## WORK EXPERIENCE). Viene
      // null en los análisis guardados de antes del campo: ahí se dice lo genérico, que
      // es lo único cierto sin saber de dónde salió la cita.
      if (r.status === 'listed_only') {
        if (r.evidence_in_experience === true) {
          return { cls: 'listed_only', label: 'Partly covered — half credit',
                   tip: 'A role does describe doing this, but it only covers part of what '
                      + 'the posting asks for — the note says which part is missing. Half '
                      + 'credit.' };
        }
        if (r.evidence_in_experience === false) {
          return { cls: 'listed_only', label: 'Only listed — no role describes it',
                   tip: 'It is in the CV — a tool, a skill, the About — but no role tells '
                      + 'the story of using it. Half credit: a client reads the two very '
                      + 'differently.' };
        }
        return { cls: 'listed_only', label: 'Half credit — not fully described',
                 tip: 'The CV shows this, but no role tells the full story of doing it — '
                    + 'either it only appears in a list, or a role covers just part of it. '
                    + 'Re-run the analysis to see which of the two it is.' };
      }
      return r.in_source === 'yes'
        ? { cls: 'missing', label: 'Missing — the recruiter can add it',
            tip: "The originals — the candidate's own CV or their LinkedIn — show this and "
               + 'this CV leaves it out. No credit, and this one is on the recruiter.' }
        : { cls: 'missing', label: 'Not in the CV',
            tip: 'Nowhere in this CV. No credit. If the originals do not have it either, '
               + 'nobody can close that gap without inventing experience.' };
    };
    const reqs = a.jd_requirements || [];
    const rs = a._requirements_summary || {};
    // La cuenta de años, rol por rol. Un total suelto no se puede verificar: si dice 5,7 y
    // el CV parece sumar 6,8, hay que poder ver de dónde salió cada mes.
    const yearsRows = (r) => {
      const yd = r.years_detail;
      if (!yd || !(yd.counted || []).length) return '';
      const fmt = (m) => m >= 12
        ? `${Math.floor(m / 12)} yr${Math.floor(m / 12) > 1 ? 's' : ''}${m % 12 ? ` ${m % 12} mo` : ''}`
        : `${m} mo`;
      // Los roles DESCARTADOS van acá también, y son la mitad importante: la aritmética es
      // exacta, la elección de roles no. Un rol de dos años dejado afuera son dos años que
      // nadie ve desaparecer si sólo mostramos los que sí contaron.
      const skipped = yd.excluded || [];
      return `<details class="cvr-years">
        <summary>How the ${yd.years} years were counted</summary>
        <ul>${yd.counted.map(c => `<li><b>${esc(c.title)}</b>
          <span>${esc(c.start_date || '?')} → ${esc(c.end_date || '?')}</span>
          <i>${fmt(c.months)}</i></li>`).join('')}
          ${(yd.unreadable || []).map(u => `<li class="is-bad"><b>${esc(u.title)}</b>
            <span>unreadable dates — not counted</span></li>`).join('')}
        </ul>
        ${yd.overlap_months ? `<p>Roles that overlap were counted once:
          ${yd.overlap_months} month(s) of overlap removed.</p>` : ''}
        ${yd.all_roles ? `<p>Every role in the CV was counted: the requirement asks for
          years of experience without naming a speciality.</p>` : ''}
        ${skipped.length ? `<p class="cvr-years-off">Not counted — these roles were read as
          a different kind of work. If one of them belongs, the years change:</p>
          <ul class="cvr-years-skip">${skipped.map(x => `<li${x.unjudged ? ' class="is-bad"' : ''}>
            <b>${esc(x.title)}</b>
            <span>${esc(x.start_date || '?')} → ${esc(x.end_date || 'Present')}</span>
            <em>${esc(x.why || 'not classified')}</em></li>`).join('')}</ul>` : ''}
      </details>`;
    };

    // JOB HOPPING — lo único que se mide fuera de la checklist además de las herramientas.
    // El tamaño del bloque sigue al estado a propósito: en 34 de los 55 CVs del corpus la
    // respuesta es "no hay tramos cortos", y una caja grande diciendo que no pasa nada entre
    // la checklist y los folds rompe la regla de esta pantalla — se abre sólo lo que puede
    // cambiar la decisión ahora mismo.
    const jh = a._job_hopping || {};
    const jhMonths = (m) => m >= 12
      ? `${Math.floor(m / 12)} yr${Math.floor(m / 12) > 1 ? 's' : ''}${m % 12 ? ` ${m % 12} mo` : ''}`
      : `${m} mo`;
    const jhRow = (st) => `<li>
        <b>${esc(st.company)}</b>
        <span>${esc(st.start_date)} → ${esc(st.end_date)}</span>
        <i>${jhMonths(st.months)}</i>
        ${st.reason_kind
          ? `<em class="is-ok"${hlRegister('ev', st.reason_quote)}>${
              st.reason_kind === 'rehired' ? 'Hired back later — ' : ''}“${esc(st.reason_quote)}”</em>`
          : '<em class="is-missing">the CV never says why it ended</em>'}
      </li>`;
    // El encabezado va SIEMPRE, en los cinco estados: el bloque se saltaba porque no tenía
    // título propio y arrancaba en medio de un párrafo. Lo que sigue variando es el cuerpo
    // — una línea cuando no hay nada que arreglar, la lista completa cuando sí.
    const jhHead = (cls, chip) =>
      scoreHead('fa-arrow-right-arrow-left', 'Job hopping', cls, chip);
    const jhHtml = (() => {
      if (!jh.state) return '';
      const flat = (cls, chip, txt) => `<div class="cvr-hop cvr-hop--flat ${cls}" id="cvrHop">
          ${jhHead(cls, chip)}<p class="cvr-hop-line">${txt}</p>
        </div>`;
      if (jh.state === 'no_history')
        return flat('is-flat', 'nothing to judge', 'This CV shows one employer, so there is '
                             + 'nothing to leave.');
      if (jh.state === 'clean') {
        // `employers` y no `checked`: el segundo deja afuera el trabajo actual, así que un
        // CV con 3 empleadores —uno de ellos el actual— decía "los 2 empleadores que
        // muestra este CV". Y si el actual dura menos de un año no se juzga, pero decir
        // que TODOS duraron un año o más sería falso: se dice aparte.
        const n = jh.employers || jh.checked || 0;
        return flat('is-ok', 'no penalty', jh.short_skipped
          ? `None to hold against them. Of the ${n} employers this CV shows, every one that
             has ended lasted a year or more; the current role is under a year, and an
             unfinished stint is not a short one.`
          : `None. All ${n} employers this CV shows lasted a year or more.`);
      }
      if (jh.state === 'unreadable')
        return flat('is-bad', 'not checked', 'None of the dates in this CV could be read, so '
                            + 'short stints could not be looked for. Fix the dates and score '
                            + 'again.');
      if (jh.state === 'explained')
        return `<div class="cvr-hop is-ok" id="cvrHop">
          ${jhHead('is-ok', 'no penalty')}
          <p class="cvr-hop-lead"><b>The CV explains it.</b> ${jh.short}
            stint${jh.short > 1 ? 's' : ''} under a year, ${jh.short > 1 ? 'each' : ''} with a
            reason the reviewer can read. <b>Nothing came off the score.</b></p>
          <ul class="cvr-hop-list">${(jh.stints || []).filter(x => x.reason_kind).map(jhRow).join('')}</ul>
        </div>`;
      const un = (jh.stints || []).filter(x => !x.reason_kind && !x.skipped);
      return `<div class="cvr-hop is-bad" id="cvrHop">
        ${jhHead('is-bad', `&minus;${jh.penalty} pts`)}
        <p class="cvr-hop-lead"><b>This one did move the score.</b>
          ${un.length} employer${un.length > 1 ? 's' : ''} left in under a year with no reason
          anywhere in this CV. A short stint is not the problem — an unexplained one is, and
          the client will ask.</p>
        <ul class="cvr-hop-list">${un.map(jhRow).join('')}</ul>
        <p class="cvr-hop-fix">Add it to that role's bullets — <code>Reason for leaving: …</code>
          — and score again. If you don't know why, ask the candidate before this goes out:
          this is the one gap on the page you cannot close by rewriting.</p>
      </div>`;
    })();

    const reqRow = (r, per) => {
      const f = reqFace(r);
      // "described" pinta verde en el CV; "only listed" ambar. Es la misma distincion que
      // hace el badge, dicha sobre el texto del CV en vez de sobre la fila del panel.
      const evKind = f.cls === 'described' ? 'described' : 'listed';
      // El aporte por fila SÍ informa acá, porque el crédito es parcial: 1 / 0,5 / 0 son
      // tres números distintos. Con crédito binario habría sido ruido.
      const pts = r.counts && per
        ? `<span class="cvr-req-pts${CREDIT[r.status] ? '' : ' is-zero'}"
                 title="Cada uno de los requisitos que puntúan vale ${per} puntos.">+${
             Math.round(per * CREDIT[r.status] * 10) / 10}</span>`
        : '';
      return `
      <li class="cvr-req cvr-req--${f.cls}">
        <div class="cvr-req-main">
          <b>${esc(r.requirement)}</b>
          ${f.tag ? `<i class="cvr-req-tag${f.tagCls ? ` ${f.tagCls}` : ''}" title="${esc(f.tip)}">${esc(f.tag)}</i>` : ''}
          <span class="cvr-req-status" title="${esc(f.tip)}">${esc(f.label)}</span>
          ${r.years_required ? `<i class="cvr-req-tag" title="We add the years up from the dates in this CV — the model does not estimate them.">${r.years_required}+ yrs · counted</i>` : ''}
          ${pts}
        </div>
        ${r.evidence ? `<p class="cvr-req-ev"${hlRegister(evKind, r.evidence)}>“${esc(r.evidence)}”</p>` : ''}
        ${r.note ? `<p class="cvr-req-note">${esc(deSource(r.note))}</p>` : ''}
        ${yearsRows(r)}
      </li>`;
    };
    // La lista ES el desglose. Antes había dos secciones diciendo lo mismo — ésta y un
    // fold con las barras de la rúbrica; ahora los requisitos explican el número, así que
    // se fusionan. Los que no puntúan van al fondo, en gris, PERO SE MUESTRAN SIEMPRE:
    // esconderlos haría imposible notar que la regla de "se da por sentado" excluyó algo
    // que sí debería contar.
    const sd = a._score_detail || {};
    const per = sd.points_per_requirement;
    const firstOff = reqs.findIndex(r => !r.counts);
    const sep = '<li class="cvr-req-sep"><span>Listed by the JD, not counted in the score</span></li>';
    const rowsHtml = reqs.map((r, i) =>
      (i === firstOff && firstOff > 0 ? sep : '') + reqRow(r, per)).join('');

    // La tarjeta de requisitos se queda con lo suyo: la barra y cuánto vale cada uno. La
    // cuenta entera (base − descuentos = score) subió al resumen, junto al número grande.
    const mathLine = sd.scorable ? `
      <div class="cvr-tally">
        <div class="cvr-tally-bar" role="img"
             aria-label="${sd.earned} of ${sd.scorable} requirements shown">
          <i style="width:${Math.max(0, Math.min(100, sd.base))}%"></i>
        </div>
        <p class="cvr-tally-line">
          <b>${sd.earned}</b> of <b>${sd.scorable}</b> scoring requirements
          &rarr; <b>${sd.base}</b>/100. Each one is worth ${per} points.
        </p>
        ${sd.excluded && sd.excluded.length ? `<p class="cvr-tally-off">Not counted: ${
          [['soft', 'soft'], ['language', 'language'], ['assumed', 'taken for granted']]
            .map(([k, l]) => [sd.excluded.filter(x => x.reason === k).length, l])
            .filter(([n]) => n).map(([n, l]) => `${n} ${l}`).join(' · ')}.</p>` : ''}
      </div>` : '';

    // Los descuentos vienen como lista desde la v12; un análisis v11 guardado sólo trae
    // tools_penalty suelto. Se arma con tc/jh cuando están, porque así también se pueden
    // mostrar los que valieron cero — que es justo lo que había que hacer notar.
    const mathParts = (() => {
      if (!sd.scorable) return [];
      const out = [{
        cls: 'is-base', jump: 'cvrReqs', n: sd.base, label: 'JD requirements',
        sub: `${sd.earned} of ${sd.scorable} shown`,
      }];
      if (tc.checked) out.push({
        cls: tc.penalty ? 'is-pen' : 'is-zero', jump: 'cvrTools',
        n: tc.penalty || 0, label: 'Tools list',
        sub: tc.penalty
          ? 'no role backs it up'
          : `${(tc.described || []).length} of ${tc.checked} described`,
      });
      else if (sd.tools_penalty) out.push({
        cls: 'is-pen', n: sd.tools_penalty, label: 'Tools list', sub: 'no role backs it up',
      });
      if (jh.state) out.push({
        cls: jh.penalty ? 'is-pen' : (jh.state === 'unreadable' ? 'is-warn' : 'is-zero'),
        jump: 'cvrHop', n: jh.penalty || 0, label: 'Job hopping',
        sub: { unexplained: 'a stint with no reason given', explained: 'short stints, all explained',
               clean: 'no stint under a year', no_history: 'only one employer',
               unreadable: 'dates could not be read' }[jh.state] || '',
      });
      return out;
    })();

    const mathHtml = mathParts.length > 1 ? `
      <div class="cvr-math">
        <div class="cvr-math-head">
          <span>How this score is built</span>
          <em>every part of it — click one to jump to it</em>
        </div>
        ${/* Dos renglones a propósito: arriba lo que se suma y se resta, abajo el
             resultado. Con los cuatro en la misma fila el total caía a la segunda línea
             según el ancho y quedaba como un sumando más. */''}
        <ol class="cvr-math-row">
          ${mathParts.map((p2, i) => `
            ${i ? '<li class="cvr-math-op">&minus;</li>' : ''}
            <li class="cvr-math-part ${p2.cls}"${p2.jump ? ` data-jump="${p2.jump}" tabindex="0"` : ''}>
              <b>${p2.n}</b>
              <span>${p2.label}</span>
              <em>${esc(p2.sub)}</em>
            </li>`).join('')}
        </ol>
        <div class="cvr-math-total">
          <span class="cvr-math-op">=</span>
          <div class="cvr-math-part is-total">
            <b class="${qCls(score)}">${score}</b>
            <span>Final score</span>
            <em>out of 100</em>
          </div>
        </div>
      </div>` : '';

    const reqsHtml = reqs.length ? `
      <div class="cvr-reqs" id="cvrReqs">
        ${scoreHead('fa-list-check', 'What the JD asked for', 'is-base',
                    sd.scorable ? `${sd.base}/100 base` : 'sets the score')}
        ${rs.incomplete ? `<p class="cvr-reqs-warn">⚠️ The posting lists ${rs.expected}
          requirements and only ${rs.listed} could be read, so this percentage is out of
          ${rs.listed}, not ${rs.expected}. Treat it as provisional and re-run before you
          use the number.</p>` : ''}
        ${/* El control de paridad compara esta lista contra una transcripción de la JD. Si
             la transcripción no vino, no se comparó nada — y decirlo importa, porque es el
             mismo fallo del modelo que hace que se saltee requisitos acá abajo. */''}
        ${/* Un requisito escrito DESPUÉS de un "Nice to have" cae del lado deseable del
             corte y no puntúa. Descartarlo en silencio se ve, desde afuera, como que la JD
             se editó y la checklist no cambió. */''}
        ${rs.optional_dropped ? `<p class="cvr-reqs-warn cvr-reqs-warn--soft">${
          rs.optional_dropped} more bullet${rs.optional_dropped === 1 ? '' : 's'} in the
          posting ${rs.optional_dropped === 1 ? 'sits' : 'sit'} after a
          <b>“nice to have”</b> heading, so ${rs.optional_dropped === 1 ? 'it was' : 'they were'}
          read as optional and left out of the score. If something there is actually
          required, move it above that heading in the posting and re-run.</p>` : ''}
        ${rs.unverified ? `<p class="cvr-reqs-warn cvr-reqs-warn--soft">This list was not
          checked against the posting: the analysis did not transcribe the JD's bullets, so
          nothing counted them. Read it against the posting yourself, or re-run.</p>` : ''}
        ${mathLine}
        <details class="cvr-note cvr-note--inline">
          <summary><i class="fa-regular fa-circle-question"></i> The rules behind the score</summary>
          <div class="cvr-note-body">
            <p>The score is one thing only: <b>the share of the JD's technical requirements
              this CV shows</b>. Each one is worth the same. A role that describes doing
              it in full earns the whole share; half goes to a requirement that is only
              listed somewhere, and to one a role covers just part of. Not having it earns
              nothing. Two fixed deductions can come off that share &mdash; a tools list no
              role backs up, and a stint under a year the CV never explains &mdash; and each
              one is shown where it happens, with what it cost. Nothing else moves the
              number: not the writing, not the length, not the About.</p>
            <p><b>Not counted:</b> soft skills, and what everyone is assumed to meet
              ("Familiarity with Windows"). They are still listed, because the client asked
              for them — they just cannot tell two candidates apart.</p>
            <p>A low score is usually the <b>candidate</b>, not the recruiter, and the
              badges say which. <b>The recruiter can add it</b> means the originals — the
              candidate's own CV and their LinkedIn — show it and this CV left it out.
              <b>Not in the CV</b> with nothing in the originals either means nobody can
              close that gap without inventing experience.</p>
          </div>
        </details>
        <ul>${rowsHtml}</ul>
      </div>` : '';

    // Agrupadas por sección: el modelo devuelve una entrada por arreglo, y tres seguidas
    // que dicen "Work Experience" se leen como si la lista estuviera repetida.
    const bySection = [];
    (a.fixes || []).forEach(f => {
      const name = String(f.section || 'The document').trim();
      const g = bySection.find(x => x.name.toLowerCase() === name.toLowerCase());
      (g || bySection[bySection.push({ name, items: [] }) - 1]).items.push(deSource(f.fix));
    });
    const fixes = bySection.map(g => `<li><b>${esc(g.name)}</b>${
      g.items.length === 1
        ? `: ${esc(g.items[0])}`
        : `<ul>${g.items.map(t => `<li>${esc(t)}</li>`).join('')}</ul>`
    }</li>`).join('');

    // El panel se lee de arriba a abajo como una decisión, no como un informe:
    //   1. cuánto vale   2. si cumple la JD (siempre abierto)   3. qué está mal escrito
    //   4. qué pedirle a la recruiter   5. por qué salió ese número (referencia)
    // Lo de abajo se pliega: ahí no hay nada que cambie un aprobado por un rechazo, y
    // teniéndolo todo desplegado la lista de requisitos —lo que de verdad importa—
    // quedaba enterrada en el medio de dos pantallas de texto.
    const wordingCounts = [
      hard.length ? `${hard.length} the originals don't support` : '',
      echo.length ? `${echo.length} copied from the JD` : '',
      soft.length ? `${soft.length} to double-check` : '',
    ].filter(Boolean).join(' · ');

    const wordingBody =
      claims(hard, 'hard', "Claims the originals don't support")
      + echoHtml
      + claims(soft, 'soft', 'Softer wording to double-check');

    return `
      <div class="cvr-ai-top">
        <div class="cvr-ai-score">
          <b class="${qCls(score)}">${score === null || score === undefined ? '—' : score}</b>
          <span>/100</span>
        </div>
        <div class="cvr-ai-sum">
          ${a.verdict ? `<span class="cvr-verdict cvr-verdict--${esc(a.verdict)}">${esc(a.verdict.replace('_', ' '))}</span>` : ''}
          <p>${esc(deSource(a.summary))}</p>
${/* v7 dejó de capear y de poner pisos. Un análisis guardado de antes sigue mostrando
       por qué su número es el que es, pero dice de dónde viene: si no, parecen reglas
       vigentes y no lo son. */''}
          ${a._cap_reason ? `<p class="cvr-ai-cap">Capped: ${esc(deSource(a._cap_reason))} (would have been ${a._uncapped_score}). <i>Old rubric — the originals no longer change the score.</i></p>` : ''}
          ${a._alignment_floor_reason ? `<p class="cvr-ai-floor">${esc(deSource(a._alignment_floor_reason))} <i>Old rubric — the originals no longer change the score.</i></p>` : ''}
          ${legacy ? `<p class="cvr-ai-legacy">This round was scored by the <b>old rubric</b>
            — six weighted criteria about the writing, not JD coverage. It is not comparable
            with newer rounds. Re-run the analysis to score it the new way.</p>` : ''}
          ${a._partial && !legacy ? `<p class="cvr-ai-cap">${
            a._score_basis === 'incomplete_requirements'
              ? 'Provisional: not every requirement in the posting could be read, so this is a share of an incomplete list.'
              : a._score_basis === 'no_scorable_requirements'
                ? 'No score: this posting lists nothing technical to measure — only soft skills and things everyone is assumed to meet.'
                : 'No score: no requirements could be read from this posting.'
            } Excluded from the recruiter average.</p>` : ''}
          ${a._partial && legacy ? '<p class="cvr-ai-cap">Partial: this round was scored by the old rubric with no job description, so 30 of its 100 points were skipped. Excluded from the recruiter average.</p>' : ''}
        </div>
      </div>
      ${mathHtml}
      ${reqsHtml}
      ${jhHtml}
      ${toolsHtml}
      ${!reqs.length && (a.jd_requirements_missed || []).length
        ? `<p class="cvr-note-block"><b>JD requirements the CV never addresses:</b> ${a.jd_requirements_missed.map(esc).join('; ')}</p>`
        : ''}

      ${fold('Wording to check', wordingCounts, wordingBody ? `
        <p class="cvr-fold-lead">None of this moves the score — the score only counts what
          the JD asked for. These are flags for you: the honesty check is the one thing
          worth stopping a CV for.</p>${wordingBody}` : '', hard.length > 0)}
      ${fold('What would make it better', '', fixes ? `<div class="cvr-fixes"><ul>${fixes}</ul></div>` : '', true)}
      ${legacy ? fold('How the old rubric scored this',
             weakest ? `weakest: ${esc(weakest.rb.label)} (${weakest.c.score})` : '',
             bars ? `<div class="cvr-crits">${bars}</div>` : '', false) : ''}

      ${a.fit_note ? `<p class="cvr-note-block"><b>On the candidate's fit:</b> ${esc(deSource(a.fit_note))}</p>` : ''}
      <p class="cvr-ai-foot">The score measures the match between this CV and this posting,
        not how well the recruiter writes — a sharp, honest CV for a candidate who doesn't
        fit will score low, and that is correct. Read the CV before you decide.</p>`;
  }

  /* ---------------------------------------------------------- historial del candidato
   * Dónde más estuvo este candidato. Existe por una regla de negocio: un candidato que ya
   * llegó a "In Client Process" más de CLIENT_PROCESS_LIMIT veces no se manda de nuevo.
   *
   * OJO con qué se cuenta: `opportunity_candidates.stage_pipeline` es el estado ACTUAL en
   * el pipeline, no un historial. No hay tabla de historial de stages, así que esto cuenta
   * en cuántas vacantes el candidato ESTÁ HOY en client process — a alguien que pasó por
   * ahí y después fue movido a otra columna no lo cuenta. Es el mismo dato que muestra el
   * pipeline de cada oportunidad, así que los dos números siempre coinciden.
   */
  const CLIENT_PROCESS_STAGE = 'En proceso con Cliente';
  const CLIENT_PROCESS_LIMIT = 3;

  const PIPE_LABEL = {
    'Applicant': 'Applicant',
    'Contactado': 'Contacted',
    'No avanza primera': 'No advance',
    'Primera entrevista': 'First interview',
    [CLIENT_PROCESS_STAGE]: 'In client process',
  };
  // Los mismos tintes que las columnas del pipeline en opportunity-detail, para que la
  // fila se reconozca sin leerla.
  const PIPE_CLS = {
    'Applicant': 'is-applicant',
    'Contactado': 'is-contacted',
    'No avanza primera': 'is-noadv',
    'Primera entrevista': 'is-first',
    [CLIENT_PROCESS_STAGE]: 'is-client',
  };

  function renderOpps(rows, review) {
    // El endpoint hace LEFT JOIN con batches, así que una vacante con dos batches vuelve
    // dos veces. Se cuenta por vacante, no por fila: si no, un candidato con dos batches
    // en la misma oportunidad se pasaría del límite él solo.
    const seen = new Set();
    const opps = [];
    (Array.isArray(rows) ? rows : []).forEach(o => {
      const id = o && o.opportunity_id;
      if (!id || seen.has(id)) return;
      seen.add(id);
      opps.push(o);
    });
    // Sin fecha en opportunity_candidates, el id sirve de orden: es autoincremental, así
    // que de mayor a menor es lo más reciente primero. No se muestra como fecha.
    opps.sort((x, y) => (y.opportunity_id || 0) - (x.opportunity_id || 0));

    const stageOf = (o) => String(o.candidate_stage || '').trim();
    const isHere = (o) => String(o.opportunity_id) === String(review.opportunity_id);
    const n = opps.filter(o => stageOf(o) === CLIENT_PROCESS_STAGE).length;
    const others = opps.filter(o => !isHere(o));
    const who = esc(review.candidate_name || 'This candidate');

    // Rojo sólo pasado el límite, ámbar justo en el límite, gris el resto. El bloque no
    // puede verse igual de grave cuando no pasa nada: si grita siempre, no lo lee nadie.
    const over = n > CLIENT_PROCESS_LIMIT;
    const at = n === CLIENT_PROCESS_LIMIT;
    const cls = over ? 'is-bad' : at ? 'is-warn' : 'is-flat';
    const chip = n
      ? `${n} of ${CLIENT_PROCESS_LIMIT} used`
      : 'none yet';

    const opps_ = (k) => `${k} opportunit${k === 1 ? 'y' : 'ies'}`;
    const lead = over
      ? `<b>Do not send this CV.</b> ${who} is in client process on <b>${opps_(n)}</b> —
         over the limit of ${CLIENT_PROCESS_LIMIT}.`
      : at
        ? `<b>At the limit.</b> ${who} is already in client process on <b>${opps_(n)}</b>.
           One more goes over ${CLIENT_PROCESS_LIMIT}.`
        : others.length
          ? `${who} is also in the pipeline of ${opps_(others.length)}, listed below.`
          : `Only this opportunity — ${who} is not in any other pipeline.`;

    // La lista sólo aparece si hay algo más que la vacante que se está revisando: una
    // fila que dice "this review" repite lo que ya está en el encabezado del drawer.
    const rowsHtml = others.length ? opps.map(o => {
      const st = stageOf(o);
      const here = isHere(o);
      const name = o.opp_position_name || `Opportunity ${o.opportunity_id}`;
      return `
      <a class="cvr-opp${here ? ' is-here' : ''}"
         href="opportunity-detail.html?id=${encodeURIComponent(o.opportunity_id)}"
         target="_blank" rel="noopener" title="${esc(name)} — open in a new tab">
        <span class="cvr-opp-l1">
          <b>${esc(name)}</b>
          <i class="cvr-opp-pipe ${PIPE_CLS[st] || ''}${
            st === CLIENT_PROCESS_STAGE && (over || at) ? ' is-loud' : ''}">${
            esc(PIPE_LABEL[st] || st || 'not in the pipeline')}</i>
        </span>
        <span class="cvr-opp-l2">${
          [o.client_name && esc(o.client_name), o.opp_stage && esc(o.opp_stage),
           here && 'this review'].filter(Boolean).join(' · ')}</span>
      </a>`;
    }).join('') : '';

    $('cvrOpps').className = `cvr-hop cvr-hop--opps ${cls}`;
    $('cvrOpps').innerHTML =
      // El título dice para qué está el bloque, no qué contiene: con "otras vacantes"
      // había que leer el chip para entender por qué importa.
      scoreHead('fa-layer-group', 'Client process check', cls, chip)
      + `<p class="cvr-hop-lead">${lead}</p>`
      + (rowsHtml ? `<div class="cvr-opp-list">${rowsHtml}</div>` : '');
    show($('cvrOpps'), opps.length > 0);
  }

  function loadOpps(review) {
    show($('cvrOpps'), false);
    // Un fallo acá NO puede tumbar el drawer: la revisión se puede hacer igual sin el
    // historial, y quedarse sin pantalla por una lista secundaria sería peor.
    return fetch(`${API}/candidates/${review.candidate_id}/opportunities`, { headers: headers() })
      .then(res => res.ok ? res.json() : [])
      .then(rows => { if (currentReview === review) renderOpps(rows, review); })
      .catch(err => console.warn('Could not load the candidate history', err));
  }

  function renderRounds(reviews) {
    const box = $('cvrRounds');
    show($('cvrRoundsSection'), reviews.length > 1);
    box.innerHTML = reviews.sort((a, b) => b.round - a.round).map(r => {
      const [label, cls] = STATUS[r.status] || [r.status, ''];
      const reasons = (r.reasons || []).map(c => esc(reasonLabels[c] || c)).join(', ');
      const flags = (r.checklist || []).map(c => esc(checklistLabels[c] || c)).join(', ');
      return `
      <div class="cvr-round">
        <div class="cvr-round-head">
          <span class="cvr-round-n">Round ${r.round}</span>
          <span class="hx-status ${cls}">${label}</span>
          <span class="cvr-round-date">${fmtDate(r.reviewed_at || r.requested_at)}</span>
          ${r.ai_score !== null && r.ai_score !== undefined ? `<span class="cvr-round-score">${r.ai_score}/100</span>` : ''}
        </div>
        ${r.recruiter_note ? `<p class="cvr-round-line"><b>Recruiter:</b> ${esc(r.recruiter_note)}</p>` : ''}
        ${reasons ? `<p class="cvr-round-line"><b>Reasons:</b> ${reasons}</p>` : ''}
        ${flags ? `<p class="cvr-round-line"><b>Checklist:</b> ${flags}</p>` : ''}
        ${r.reject_other ? `<p class="cvr-round-line"><b>Other:</b> ${esc(r.reject_other)}</p>` : ''}
        ${r.reviewer_comment ? `<p class="cvr-round-comment">${esc(r.reviewer_comment)}</p>` : ''}
      </div>`;
    }).join('');
  }

  // UN solo modo, no dos booleanos: con `rejectMode` y `changesMode` sueltos se pueden
  // prender los dos y el footer queda con dos confirmaciones distintas a la vez.
  // null = elegir; 'rejected' | 'changes_requested' = escribiendo el formulario de ese.
  function setDecisionMode(mode) {
    const rej = mode === 'rejected';
    const chg = mode === 'changes_requested';
    const on = rej || chg;
    show($('cvrRejectForm'), rej);
    show($('cvrChangesForm'), chg);
    show($('cvrRejectConfirm'), rej);
    show($('cvrChangesConfirm'), chg);
    show($('cvrRejectCancel'), on);
    show($('cvrRejectToggle'), !on);
    show($('cvrChangesToggle'), !on);
    show($('cvrApprove'), !on);
    modeFootHint = rej
      ? 'This takes the candidate out of this opening. To ask for a rewrite, use Request changes.'
      : chg
        ? 'The comment is the only thing the recruiter gets, so say what to change.'
        : '';
    // El hint lo escribe syncChecklistGate: si la checklist falta, ese mensaje gana, porque
    // es el que explica por qué los botones están grises.
    syncChecklistGate();
    if (on) {
      // Llevar el ojo al formulario: en un CV largo queda debajo del iframe.
      $(rej ? 'cvrRejectForm' : 'cvrChangesForm').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  function openDrawer(reviewId) {
    $('cvrDrawerError').textContent = '';
    setDecisionMode(null);
    // Los tildes son de la review anterior. Sin esto, abrir una y después otra arrastraría
    // los defectos de la primera y se guardarían contra la recruiter equivocada.
    resetChecklist();
    // Los dos footers se apagan ANTES del fetch. Sin esto, abrir un rechazo y después uno
    // aprobado mostraba el footer de reabrir durante el "Loading…", sobre otra review.
    show($('cvrReopenFoot'), false);
    $('cvrAi').innerHTML = '<p class="cvr-ai-none">Loading…</p>';
    $('cvrRounds').innerHTML = '';
    hlResetQuotes();
    hlResetFrame();
    show($('cvrScrim'), true);
    requestAnimationFrame(() => {
      $('cvrScrim').classList.add('is-open');
      $('cvrDrawer').classList.add('is-open');
    });

    fetch(`${API}/cv_reviews/${reviewId}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(data => {
        const r = data.review;
        currentReview = r;

        $('cvrDrawerTitle').textContent = r.candidate_name || 'Candidate';
        $('cvrDrawerEyebrow').textContent = `Round ${r.round} · ${r.status}`;
        $('cvrDrawerSub').textContent =
          [r.opp_position_name, r.client_name, `sent by ${r.recruiter_email}`]
            .filter(Boolean).join(' · ');

        // El CV TAL COMO SE ENVIÓ, no el actual: se juzga lo que la recruiter mandó, y
        // así las frases que cita el análisis existen seguro en lo que se está viendo.
        // resume-readonly.js lo pide a /cv_reviews/<id>/resume cuando ve review_id.
        // opportunity_id define la marca del CV (Vintti vs vintti.ai): sale de la
        // cuenta de ESTA vacante, no de todos los procesos del candidato.
        const url = `resume-readonly.html?id=${r.candidate_id}&review_id=${r.review_id}` +
          (r.opportunity_id ? `&opportunity_id=${r.opportunity_id}` : '');
        // El onload va ANTES del src: es el que dispara la búsqueda de las citas.
        const frame = $('cvrFrame');
        frame.onload = () => { if (currentReview) hlAttach(); };
        frame.src = url;
        $('cvrOpenCv').href = url;

        // Dos derivas distintas y NO son la misma cosa: una es que la recruiter tocó el
        // CV después de mandarlo, la otra que se editó la JD después de scorear. La
        // segunda invalida la checklist entera, así que se dice aunque el CV esté igual.
        const jdDrift = $('cvrJdDrift');
        const hasAnalysis = !!(r.jd_requirements || []).length;
        if (r.jd_changed) {
          jdDrift.className = 'cvr-warn';
          jdDrift.innerHTML = 'The job description changed after this analysis ran, so the '
            + 'checklist below is scored against the old one. <b>Re-run the analysis</b> to '
            + 'score it against the posting as it stands now.';
          show(jdDrift, true);
        } else if (hasAnalysis && !r.jd_checked) {
          // Análisis anterior a la huella: no se puede afirmar que coincida NI que no.
          jdDrift.className = 'cvr-warn cvr-warn--soft';
          jdDrift.innerHTML = 'This analysis is older than the job-description check, so '
            + 'there is no way to tell whether the posting has changed since. If the '
            + 'checklist does not match the posting you see today, <b>re-run it</b>.';
          show(jdDrift, true);
        } else {
          show(jdDrift, false);
        }

        const drift = $('cvrDrift');
        if (r.resume_drift) {
          drift.textContent = 'The recruiter edited this CV after submitting it, so what you '
            + 'see below is not exactly what was sent to review.';
          show(drift, true);
        } else {
          show(drift, false);
        }

        $('cvrAi').innerHTML = aiPanelHtml(r);
        hlSync();

        show($('cvrDecisionFoot'), r.status === 'pending');
        // Sólo sobre un rechazo: es el único veredicto que traba a la recruiter.
        show($('cvrReopenFoot'), r.status === 'rejected');

        if (r.status === 'pending') {
          // Arranca deshabilitando: el gate se abre recién cuando el reviewer tilda algo.
          syncChecklistGate();
        } else {
          paintChecklistReadonly(r);
        }

        loadOpps(r);

        return fetch(`${API}/candidates/${r.candidate_id}/cv_reviews?opportunity_id=${r.opportunity_id}`,
          { headers: headers() })
          .then(res => res.ok ? res.json() : { reviews: [] })
          .then(d => renderRounds(d.reviews || []));
      })
      .catch(err => {
        $('cvrAi').innerHTML = '';
        $('cvrDrawerError').textContent = `Could not load the review: ${err.message}`;
      });
  }

  function closeDrawer() {
    $('cvrDrawer').classList.remove('is-open');
    $('cvrScrim').classList.remove('is-open');
    hlResetQuotes();
    hlResetFrame();
    setTimeout(() => {
      show($('cvrScrim'), false);
      // onload a null primero: si no, el about:blank dispara un poll que no lleva a nada.
      $('cvrFrame').onload = null;
      $('cvrFrame').src = 'about:blank';
    }, 220);
    currentReview = null;
  }

  /* -------------------------------------------------------------- decisiones */

  function renderReasonChecks() {
    $('cvrReasons').innerHTML = Object.entries(reasonLabels).map(([code, label]) => `
      <label class="cvr-reason">
        <input type="checkbox" value="${esc(code)}" />
        <span>${esc(label)}</span>
      </label>`).join('');
    // "Other" pide texto: sin eso la razón se pierde en las métricas.
    $('cvrReasons').addEventListener('change', () => {
      const other = $('cvrReasons').querySelector('input[value="other"]');
      show($('cvrReasonOtherWrap'), !!other?.checked);
    });
  }

  function renderChecklistChecks() {
    $('cvrChecklist').innerHTML = Object.entries(checklistLabels).map(([code, label]) => `
      <label class="cvr-check">
        <input type="checkbox" value="${esc(code)}" />
        <span>${esc(label)}</span>
      </label>`).join('');
    // Exclusión mutua con "Nothing to flag": son respuestas incompatibles a la misma
    // pregunta, y dejarlas convivir manda un "está limpio" junto con dos defectos.
    $('cvrChecklist').addEventListener('change', () => {
      if (checklistPicks().length) $('cvrChecklistClean').checked = false;
      syncChecklistGate();
    });
    $('cvrChecklistClean').addEventListener('change', () => {
      if ($('cvrChecklistClean').checked) {
        $('cvrChecklist').querySelectorAll('input:checked').forEach(i => { i.checked = false; });
      }
      syncChecklistGate();
    });
  }

  const checklistPicks = () =>
    Array.from($('cvrChecklist').querySelectorAll('input:checked')).map(i => i.value);

  // "El reviewer pasó por la checklist". Tildar un ítem ya lo prueba; el checkbox de limpio
  // existe para el caso contrario. Sin esto, "0 defectos" y "nadie la miró" serían la misma
  // fila y la métrica mediría al reviewer en vez de a la recruiter.
  const checklistDone = () => !!checklistPicks().length || $('cvrChecklistClean').checked;

  function resetChecklist() {
    $('cvrChecklist').querySelectorAll('input').forEach(i => {
      i.checked = false;
      i.disabled = false;
    });
    const clean = $('cvrChecklistClean');
    clean.checked = false;
    clean.disabled = false;
    $('cvrChecklistSection').classList.remove('is-missing');
  }

  // Una ronda ya decidida se muestra como registro, no como formulario.
  function paintChecklistReadonly(review) {
    const picks = new Set(review.checklist || []);
    $('cvrChecklist').querySelectorAll('input').forEach(i => {
      i.checked = picks.has(i.value);
      i.disabled = true;
    });
    const clean = $('cvrChecklistClean');
    clean.checked = review.checklist_done && !picks.size;
    clean.disabled = true;
  }

  function syncChecklistGate() {
    // Sólo aplica mientras se puede decidir; en una ronda cerrada los botones no están.
    if (!currentReview || currentReview.status !== 'pending') return;
    const ready = checklistDone();
    [$('cvrApprove'), $('cvrRejectConfirm'), $('cvrChangesConfirm')].forEach(b => {
      b.disabled = !ready;
    });
    $('cvrFootHint').textContent = ready
      ? modeFootHint
      : 'Go through the checklist above before deciding.';
    if (ready) $('cvrChecklistSection').classList.remove('is-missing');
  }

  // El botón gris no se explica solo: la columna scrollea y la checklist puede haber quedado
  // fuera de la vista, así que hay que llevar el ojo hasta ella.
  function flagChecklistMissing() {
    const sec = $('cvrChecklistSection');
    sec.open = true;
    sec.classList.add('is-missing');
    sec.scrollIntoView({ behavior: 'smooth', block: 'center' });
    $('cvrDrawerError').textContent = 'Go through the checklist first: tick what the recruiter '
      + 'got wrong, or mark the CV as clean.';
  }

  function decide(decision) {
    if (!currentReview) return;
    if (!checklistDone()) { flagChecklistMissing(); return; }
    // Va en las TRES decisiones, no sólo en el rechazo: el caso que esto existe para
    // registrar es el CV que se APRUEBA con la educación sin cargar.
    const body = { decision, checklist: checklistPicks(), checklist_done: true };
    if (decision === 'rejected') {
      body.reasons = Array.from($('cvrReasons').querySelectorAll('input:checked')).map(i => i.value);
      body.reason_other = $('cvrReasonOther').value.trim();
      body.reviewer_comment = $('cvrComment').value.trim();
    } else if (decision === 'changes_requested') {
      // Sin razones a propósito: los códigos fijos miden por qué se RECHAZA un perfil, y
      // esto no es un rechazo. El backend igual las descarta si llegaran.
      body.reviewer_comment = $('cvrChangesComment').value.trim();
    }

    const buttons = [$('cvrApprove'), $('cvrRejectConfirm'), $('cvrRejectToggle'),
                     $('cvrChangesConfirm'), $('cvrChangesToggle')];
    buttons.forEach(b => { b.disabled = true; });
    $('cvrDrawerError').textContent = '';

    fetch(`${API}/cv_reviews/${currentReview.review_id}/decision`, {
      method: 'POST', headers: headers(), body: JSON.stringify(body),
    })
      .then(async r => {
        const out = await r.json().catch(() => ({}));
        if (!r.ok) throw Object.assign(new Error(out.error || `HTTP ${r.status}`), { body: out });
        return out;
      })
      .then(out => {
        $('cvrComment').value = '';
        $('cvrChangesComment').value = '';
        $('cvrReasonOther').value = '';
        $('cvrReasons').querySelectorAll('input:checked').forEach(i => { i.checked = false; });
        resetChecklist();
        closeDrawer();
        refresh();
        if (out.batch_synced) {
          // Vale decirlo: el status del batch alimenta el donut de "razones de rechazo".
          console.info('cv-review: batch status set to "Rejected By Sales"');
        }
      })
      .catch(err => {
        $('cvrDrawerError').textContent = err.body?.error || err.message;
        if (err.body?.code === 'already_decided') refresh();
      })
      .finally(() => {
        buttons.forEach(b => { b.disabled = false; });
        // El re-enable de arriba es ciego: sin esto, un error de red dejaría los botones de
        // confirmar prendidos aunque la checklist esté vacía.
        syncChecklistGate();
      });
  }

  /* ------------------------------------------------------------------ carga */

  // Sin esto, alguien que ve 2 filas no sabe si hay 2 o si el filtro le esconde el resto.
  function updateScopeHint(isOversight) {
    const mine = $('cvrMine').checked;
    $('cvrScope').textContent = mine
      ? 'Showing only opportunities where you are the sales lead. Untick to see the rest.'
      : (isOversight
          ? 'Showing every recruiter and every sales lead.'
          : 'Showing everyone\'s, not just yours.');
  }

  const queryString = () => {
    const p = new URLSearchParams();
    if ($('cvrStatus').value) p.set('status', $('cvrStatus').value);
    if ($('cvrRecruiter').value) p.set('recruiter', $('cvrRecruiter').value);
    if ($('cvrMine').checked) p.set('mine', '1');
    return p.toString();
  };

  const periodString = () => {
    const p = new URLSearchParams();
    if ($('cvrFrom').value) p.set('desde', $('cvrFrom').value);
    if ($('cvrTo').value) p.set('hasta', $('cvrTo').value);
    // El MISMO filtro que la cola: si no, la métrica de arriba y la lista de abajo
    // estarían contando universos distintos en la misma pantalla.
    if ($('cvrMine').checked) p.set('mine', '1');
    if ($('cvrRecruiter').value) p.set('recruiter', $('cvrRecruiter').value);
    return p.toString();
  };

  function refresh() {
    show($('cvrQueueLoading'), true);
    show($('cvrQueueWrap'), false);
    show($('cvrQueueEmpty'), false);

    fetch(`${API}/cv_reviews?${queryString()}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => { queueRows = d.reviews || []; renderQueue(); })
      .catch(err => {
        queueRows = [];
        clearQueue();
        show($('cvrQueueLoading'), false);
        show($('cvrQueueWrap'), false);
        const empty = $('cvrQueueEmpty');
        empty.querySelector('h3').textContent = 'Could not load the queue';
        empty.querySelector('p').textContent = err.message;
        show(empty, true);
      });

    const period = periodString();
    fetch(`${API}/cv_reviews/metrics${period ? '?' + period : ''}`, { headers: headers() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(renderMetrics)
      .catch(err => {
        $('cvrMetrics').innerHTML = '';
        $('cvrMetricsEmpty').querySelector('p').textContent = `Could not load the metrics: ${err.message}`;
        show($('cvrMetricsEmpty'), true);
      });
  }

  const loadRecruiters = () => fetch(`${API}/users/recruiters`, { headers: headers() })
    .then(r => r.ok ? r.json() : [])
    .then(list => {
      (Array.isArray(list) ? list : []).forEach(u => {
        const email = (u.email_vintti || '').toLowerCase();
        if (!email) return;
        const o = document.createElement('option');
        o.value = email;
        o.textContent = u.user_name || email;
        $('cvrRecruiter').appendChild(o);
      });
    })
    .catch(() => {});

  const loadReasons = () => fetch(`${API}/cv_review_reasons`, { headers: headers() })
    .then(r => r.ok ? r.json() : { reasons: [] })
    .then(d => {
      (d.reasons || []).forEach(x => { reasonLabels[x.code] = x.label; });
      renderReasonChecks();
    })
    .catch(() => {});

  const loadChecklistItems = () => fetch(`${API}/cv_review_checklist_items`, { headers: headers() })
    .then(r => r.ok ? r.json() : { items: [] })
    .then(d => {
      (d.items || []).forEach(x => { checklistLabels[x.code] = x.label; });
      renderChecklistChecks();
    })
    .catch(() => {});

  /* ------------------------------------------------------------------- init */

  document.addEventListener('DOMContentLoaded', () => {
    if (!ALLOWED.has(me)) { show($('cvrDenied'), true); return; }
    show($('cvrApp'), true);

    // Un sales lead abre la página viendo SÓLO sus oportunidades; la supervisión, todo.
    // Es un valor por defecto, no un candado: destildando la casilla ve el resto.
    const isOversight = OVERSIGHT.has(me);
    $('cvrMine').checked = !isOversight;
    $('cvrMineLabel').textContent = isOversight ? 'Only mine' : 'Only my opportunities';

    // Un deep-link desde un mail es una instrucción explícita: mostrame ESTO. Los defaults
    // (status="pending", "sólo mis oportunidades") lo esconderían si el review ya se decidió
    // o si es de otro sales lead, y el botón del mail parecería roto.
    if (deepReviewId || deepOppId) $('cvrStatus').value = '';
    if (deepOppId) $('cvrMine').checked = false;

    updateScopeHint(isOversight);
    $('cvrMine').addEventListener('change', () => updateScopeHint(isOversight));

    $('cvrApply').addEventListener('click', refresh);
    $('cvrRefresh').addEventListener('click', refresh);
    $('cvrStatus').addEventListener('change', refresh);
    $('cvrRecruiter').addEventListener('change', refresh);
    $('cvrMine').addEventListener('change', refresh);
    // El buscador filtra en memoria: la cola ya está cargada, no hace falta ir al backend.
    $('cvrSearch').addEventListener('input', renderQueue);
    wireQueue();
    wireMetricsToggle();

    $('cvrRejectToggle').addEventListener('click', () => setDecisionMode('rejected'));
    $('cvrChangesToggle').addEventListener('click', () => setDecisionMode('changes_requested'));
    $('cvrChangesConfirm').addEventListener('click', () => decide('changes_requested'));
    $('cvrRejectCancel').addEventListener('click', () => setDecisionMode(null));

    $('cvrReopen').addEventListener('click', () => {
      if (!currentReview) return;
      const btn = $('cvrReopen');
      btn.disabled = true;
      $('cvrDrawerError').textContent = '';
      fetch(`${API}/cv_reviews/${currentReview.review_id}/reopen`, {
        method: 'POST', headers: headers(),
      })
        .then(async res => {
          const out = await res.json().catch(() => ({}));
          if (!res.ok) throw Object.assign(new Error(out.error || `HTTP ${res.status}`), { body: out });
          return out;
        })
        .then(() => { closeDrawer(); refresh(); })
        .catch(err => { $('cvrDrawerError').textContent = err.body?.error || err.message; })
        .finally(() => { btn.disabled = false; });
    });
    $('cvrApprove').addEventListener('click', () => decide('approved'));
    $('cvrRejectConfirm').addEventListener('click', () => decide('rejected'));

    $('cvrReanalyze').addEventListener('click', () => {
      if (!currentReview) return;
      const btn = $('cvrReanalyze');
      btn.disabled = true;
      const label = btn.innerHTML;
      btn.innerHTML = '<i class="fa-solid fa-rotate fa-spin"></i> Running…';
      fetch(`${API}/cv_reviews/${currentReview.review_id}/analyze`,
        { method: 'POST', headers: headers() })
        .then(async r => {
          const out = await r.json().catch(() => ({}));
          if (!r.ok) throw new Error(out.error || `HTTP ${r.status}`);
          return out;
        })
        .then(out => {
          currentReview.ai_analysis = out.ai_analysis;
          currentReview.ai_score = out.ai_score;
          currentReview.ai_error = null;
          $('cvrAi').innerHTML = aiPanelHtml(currentReview);
          hlSync();
          // El backend devuelve el análisis guardado si nada cambió y hace menos de un
          // minuto. Callarlo hace creer que la IA volvió a correr y dio el mismo número,
          // que es exactamente la conclusión opuesta a la verdadera.
          const note = $('cvrRerunNote');
          note.textContent = out.cached
            ? 'Nothing was re-run: same CV, same job description, and it was scored less '
              + 'than a minute ago — this is the stored result. Wait a moment and try again.'
            : '';
          show(note, !!out.cached);
          refresh();
        })
        .catch(err => { $('cvrDrawerError').textContent = err.message; })
        .finally(() => { btn.disabled = false; btn.innerHTML = label; });
    });

    // --- resaltado: del panel al CV y de vuelta ---
    // Cada cita ubicable es un botón: lleva el CV hasta la frase y la pinta de azul.
    // Cada parte de la cuenta lleva a su bloque y lo destella: el resumen dice cuánto se
    // fue, el bloque dice por qué, y no hay que buscarlo con la rueda del mouse.
    const jumpTo = (id) => {
      const target = document.getElementById(id);
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      target.classList.remove('cvr-jumped');
      void target.offsetWidth;
      target.classList.add('cvr-jumped');
    };
    $('cvrAi').addEventListener('click', ev => {
      const jump = ev.target.closest('[data-jump]');
      if (jump) { jumpTo(jump.getAttribute('data-jump')); return; }
      const el = ev.target.closest('[data-hl].cvr-hl-item');
      if (el) hlGoTo(el.getAttribute('data-hl'));
    });
    $('cvrAi').addEventListener('keydown', ev => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      const jump = ev.target.closest('[data-jump]');
      if (jump) { ev.preventDefault(); jumpTo(jump.getAttribute('data-jump')); return; }
      const el = ev.target.closest('[data-hl].cvr-hl-item');
      if (!el) return;
      ev.preventDefault();
      hlGoTo(el.getAttribute('data-hl'));
    });
    $('cvrHlLegend').addEventListener('click', ev => {
      const chip = ev.target.closest('[data-hl-kind]');
      if (chip) hlNextOfKind(chip.getAttribute('data-hl-kind'));
    });
    hlRenderKey();
    // La clave tapa el CV mientras está abierta, así que se cierra tocando cualquier
    // otro lado — no hay que acordarse de volver al chip.
    document.addEventListener('click', ev => {
      const key = document.querySelector('.cvr-hl-key');
      if (key && key.open && !key.contains(ev.target)) key.open = false;
    });
    $('cvrHlSwitch').addEventListener('change', () => {
      hlState.on = $('cvrHlSwitch').checked;
      hlApply();
      hlRenderLegend();
    });

    $('cvrClose').addEventListener('click', closeDrawer);
    $('cvrScrim').addEventListener('click', closeDrawer);
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape') return;
      // Escape cierra primero la clave: cerrar el review entero por querer cerrar un
      // popover haría perder el lugar en la cola.
      const key = document.querySelector('.cvr-hl-key');
      if (key && key.open) { key.open = false; return; }
      if ($('cvrDrawer').classList.contains('is-open')) closeDrawer();
    });

    Promise.all([loadReasons(), loadChecklistItems(), loadRecruiters()]).then(() => {
      refresh();
      // openDrawer se trae el review por su id, así que no espera a la cola.
      if (deepReviewId) openDrawer(deepReviewId);
    });
  });
})();
