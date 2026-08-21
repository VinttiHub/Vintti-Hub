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

  // Clase del semáforo para un score 0-100.
  const qCls = (s) => (s === null || s === undefined) ? 'cvr-q-none'
    : s >= 75 ? 'cvr-q-good' : s >= 50 ? 'cvr-q-mid' : 'cvr-q-low';

  // Con n chico el porcentaje engaña: 1 de 20 es 5 por ciento, y "5%" solo parece una
  // tendencia. Siempre se muestra el conteo al lado.
  function fmtRate(count, total, pct) {
    if (!total) return '—';
    const p = (pct === null || pct === undefined) ? Math.round(1000 * count / total) / 10 : pct;
    return `${count}/${total} · ${p}%`;
  }

  // Los análisis guardados antes de la v7 dicen "the source": el prompt viejo se lo
  // enseñaba al modelo. Esos reviews ya están decididos y nadie los va a re-correr, así
  // que la palabra se traduce al mostrarla. La sustitución es SINGULAR a propósito: la
  // frase guardada ya trae el verbo concordado en singular ("the source does not show"),
  // y meterle "the originals" la dejaría mal escrita ("the originals does not show").
  const SOURCE_RE = /\bthe source material\b|\bthe source\b/gi;
  const deSource = (t) => String(t ?? '').replace(SOURCE_RE, m =>
    (m[0] === 'T' ? "The" : "the") + " candidate's own CV or LinkedIn");

  let reasonLabels = {};
  let currentReview = null;
  let queueRows = [];

  // Deep-link desde los mails. Los CTA ya se mandaban con estos parámetros pero nadie los
  // leía, así que el botón "Open the CV review" del mail no hacía nada: caía en la cola sin
  // filtrar y sin abrir nada.
  const DEEP = new URLSearchParams(location.search);
  const deepReviewId = Number(DEEP.get('review_id')) || null;
  const deepOppId = Number(DEEP.get('opportunity_id')) || null;

  /* ---------------------------------------------------------------- métricas */

  function renderMetrics(data) {
    const box = $('cvrMetrics');
    const rows = data.rows || [];
    const totals = data.totals || {};
    const meta = data.meta || {};

    $('cvrMetricsWindow').textContent =
      (meta.desde ? `${meta.desde} → ${meta.hasta}` : '')
      + (meta.sales_lead ? '  ·  your opportunities' : '')
      + (meta.ai_version ? `  ·  scoring v${meta.ai_version}` : '');

    if (!rows.length) {
      box.innerHTML = '';
      show($('cvrMetricsEmpty'), true);
      return;
    }
    show($('cvrMetricsEmpty'), false);

    const card = (r, isTotal) => {
      const q = r.quality_avg;
      const reasons = (r.reasons || []).map(x =>
        `<li><span>${esc(x.reason_label)}</span>
             <b>${fmtRate(x.profiles, r.profiles_decided, x.pct)}</b></li>`).join('');
      const foot = [];
      if (r.profiles_pending) {
        foot.push(`${r.profiles_pending} still waiting on a decision — the rates only count what you decided.`);
      }
      if (r.stale_version_profiles) {
        foot.push(`${r.stale_version_profiles} excluded: scored under the old rubric, which measured the writing instead of JD coverage.`);
      }
      if (r.unscored_profiles) {
        foot.push(`${r.unscored_profiles} have no AI score (no job description, or scoring failed).`);
      }
      return `
      <article class="cvr-mcard ${isTotal ? 'cvr-mcard--total' : ''}">
        <div class="cvr-mcard-head">
          <h3>${esc(isTotal ? 'All recruiters' : (r.recruiter_label || r.recruiter_email))}</h3>
          <span class="cvr-mcard-sent"><b>${r.profiles_sent}</b> sent</span>
        </div>
        <div class="cvr-stats">
          <div class="cvr-stat">
            <span class="cvr-stat-v ${qCls(q)}">${q === null || q === undefined ? '—' : q}</span>
            <span class="cvr-stat-l">JD coverage${r.quality_n ? ` n=${r.quality_n}` : ''}</span>
          </div>
          <div class="cvr-stat">
            <span class="cvr-stat-v">${r.approved_first_try_pct === null ? '—' : r.approved_first_try_pct + '%'}</span>
            <span class="cvr-stat-l">Approved 1st</span>
          </div>
          <div class="cvr-stat">
            <span class="cvr-stat-v">${r.rejected_first_try_pct === null ? '—' : r.rejected_first_try_pct + '%'}</span>
            <span class="cvr-stat-l">Rejected 1st</span>
          </div>
        </div>
        ${reasons ? `<ul class="cvr-reasons-list">${reasons}</ul>` : ''}
        ${foot.length ? `<p class="cvr-mfoot">${foot.map(esc).join(' ')}</p>` : ''}
      </article>`;
    };

    const totalRow = {
      ...totals,
      recruiter_label: 'All recruiters',
      reasons: aggregateReasons(data.by_reason || [], totals.profiles_decided),
    };
    box.innerHTML = card(totalRow, true) + rows.map(r => card(r, false)).join('');
  }

  function aggregateReasons(byReason, decided) {
    const acc = {};
    byReason.forEach(r => { acc[r.reason_code] = (acc[r.reason_code] || 0) + r.profiles; });
    return Object.entries(acc)
      .sort((a, b) => b[1] - a[1])
      .map(([code, profiles]) => ({
        reason_code: code,
        reason_label: reasonLabels[code] || code,
        profiles,
        pct: decided ? Math.round(1000 * profiles / decided) / 10 : null,
      }));
  }

  /* ------------------------------------------------------------------- cola */

  const STATUS = {
    pending:   ['Waiting',   'cvr-st-pending'],
    approved:  ['Approved',  'cvr-st-approved'],
    rejected:  ['Rejected',  'cvr-st-rejected'],
    cancelled: ['Cancelled', 'cvr-st-cancelled'],
  };

  function renderQueue() {
    const term = ($('cvrSearch').value || '').toLowerCase().trim();
    let list = !term ? queueRows : queueRows.filter(r =>
      [r.candidate_name, r.opp_position_name, r.client_name, r.recruiter_email]
        .some(v => String(v || '').toLowerCase().includes(term)));
    // El CTA de un batch apunta a una oportunidad: son N reviews, no uno.
    if (deepOppId) list = list.filter(r => Number(r.opportunity_id) === deepOppId);

    const body = $('cvrQueue');
    $('cvrCount').innerHTML = `<b>${list.length}</b> of ${queueRows.length}`;

    show($('cvrQueueLoading'), false);
    if (!list.length) {
      body.innerHTML = '';
      show($('cvrQueueWrap'), false);
      show($('cvrQueueEmpty'), true);
      return;
    }
    show($('cvrQueueEmpty'), false);
    show($('cvrQueueWrap'), true);

    body.innerHTML = list.map(r => {
      const [label, cls] = STATUS[r.status] || [r.status, ''];
      const waited = r.status === 'pending' ? daysWaiting(r.requested_at) : null;
      const score = r.ai_pending
        ? '<span class="cvr-score-none">scoring…</span>'
        : (r.ai_score === null || r.ai_score === undefined
            ? '<span class="cvr-score-none">—</span>'
            : `<span class="cvr-score ${qCls(r.ai_score)}">${r.ai_score}</span>`);
      const age = waited !== null
        ? `<span class="cvr-age${waited >= 3 ? ' cvr-age--old' : ''}">${waited === 0 ? 'today' : waited + 'd'}</span>`
        : `<span class="cvr-age">${fmtDate(r.reviewed_at || r.requested_at)}</span>`;
      return `
      <tr data-review-id="${r.review_id}" tabindex="0">
        <td><div class="cvr-cand">${esc(r.candidate_name || 'Candidate')}</div></td>
        <td class="hx-cell-muted">${esc(r.opp_position_name || '—')}
            <span class="cvr-oppid">#${r.opportunity_id}</span></td>
        <td class="hx-cell-muted">${esc(r.client_name || '—')}</td>
        <td class="hx-cell-muted">${esc(r.recruiter_email || '—')}</td>
        <td class="cvr-col-round"><span class="cvr-round-n">${r.round}</span></td>
        <td class="cvr-col-score">${score}</td>
        <td><span class="hx-status ${cls}">${label}</span></td>
        <td>${age}</td>
      </tr>`;
    }).join('');

    body.querySelectorAll('tr').forEach(el => {
      const open = () => openDrawer(Number(el.dataset.reviewId));
      el.addEventListener('click', open);
      el.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); }
      });
    });
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
    const toolsHtml = (tc.checked || 0) ? `
      <p class="cvr-fold-lead">${tc.penalty
        ? `<b>This one did move the score: &minus;${tc.penalty}.</b> Not one of the tools
           in the list turns up in any role. `
        : 'Nothing here moves the score. '}A tools list is free to write; what a client
        believes is the role that describes using it. Some described is enough — the rest
        is just worth knowing. <b>Click any of them to jump to it in the CV.</b></p>
      <ul class="cvr-tool-chips">
        ${(tc.described || []).map(t => toolChip(t, true)).join('')}
        ${(tc.listed_only || []).map(t => toolChip(t, false)).join('')}
      </ul>
      ${(tc.listed_only_total || 0) > (tc.listed_only || []).length
        ? `<p class="cvr-tally-off">…and ${tc.listed_only_total - tc.listed_only.length} more only listed.</p>`
        : ''}` : '';

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
        const why = {
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
        return { cls: 'described', label: 'Described in the experience',
                 tip: 'A role in the work experience describes actually doing this, with a '
                    + 'quote to back it. Full credit.' };
      }
      if (r.status === 'listed_only') {
        return { cls: 'listed_only', label: 'Only listed — no role describes it',
                 tip: 'It is in the CV — a tool, a skill, the About — but no role tells the '
                    + 'story of using it. Half credit: a client reads the two very '
                    + 'differently.' };
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
          : '<em>the CV never says why it ended</em>'}
      </li>`;
    const jhHtml = (() => {
      if (!jh.state) return '';
      const line = (cls, txt) => `<p class="cvr-hop-line ${cls}">${txt}</p>`;
      if (jh.state === 'no_history')
        return line('', 'Job hopping: nothing to judge — this CV shows one employer, so '
                      + 'there is nothing to leave.');
      if (jh.state === 'clean')
        return line('', `Job hopping: none. Every one of the ${jh.checked} employers this CV `
                      + 'shows lasted a year or more.');
      if (jh.state === 'unreadable')
        return line('is-bad', '⚠️ Job hopping could not be checked: none of the dates in this '
                            + 'CV could be read. Fix the dates and score again.');
      if (jh.state === 'explained')
        return `<div class="cvr-hop is-ok">
          <p class="cvr-hop-lead"><b>Job hopping, and the CV explains it.</b> ${jh.short}
            stint${jh.short > 1 ? 's' : ''} under a year, ${jh.short > 1 ? 'each' : ''} with a
            reason the reviewer can read. <b>Nothing came off the score.</b></p>
          <ul class="cvr-hop-list">${(jh.stints || []).filter(x => x.reason_kind).map(jhRow).join('')}</ul>
        </div>`;
      const un = (jh.stints || []).filter(x => !x.reason_kind && !x.skipped);
      return `<div class="cvr-hop is-bad">
        <p class="cvr-hop-lead"><b>This one did move the score: &minus;${jh.penalty}.</b>
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
          ${f.tag ? `<i class="cvr-req-tag" title="${esc(f.tip)}">${esc(f.tag)}</i>` : ''}
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

    const mathLine = sd.scorable ? `
      <div class="cvr-tally">
        <div class="cvr-tally-bar" role="img"
             aria-label="${sd.earned} of ${sd.scorable} requirements shown">
          <i style="width:${Math.max(0, Math.min(100, sd.base))}%"></i>
        </div>
        <p class="cvr-tally-line">
          <b>${sd.earned}</b> of <b>${sd.scorable}</b> scoring requirements
          &rarr; <b>${sd.base}</b>/100${(() => {
            // Los descuentos vienen como lista desde la v12; un análisis v11 guardado sólo
            // trae tools_penalty suelto, y se sigue pintando igual.
            const ps = (sd.penalties || []).filter(p => p.points).length
              ? sd.penalties.filter(p => p.points)
              : (sd.tools_penalty ? [{ label: 'tools', points: sd.tools_penalty }] : []);
            return ps.length
              ? ps.map(p => ` &minus; <b>${p.points}</b> <span>(${esc(p.label)})</span>`).join('')
                + ` = <b>${score}</b>`
              : '';
          })()}.
          Each one is worth ${per} points.
        </p>
        ${sd.excluded && sd.excluded.length ? `<p class="cvr-tally-off">Not counted: ${
          [['soft', 'soft'], ['language', 'language'], ['assumed', 'taken for granted']]
            .map(([k, l]) => [sd.excluded.filter(x => x.reason === k).length, l])
            .filter(([n]) => n).map(([n, l]) => `${n} ${l}`).join(' · ')}.</p>` : ''}
      </div>` : '';

    const reqsHtml = reqs.length ? `
      <div class="cvr-reqs">
        <h5>What the JD asked for <span class="cvr-reqs-count">this list <b>sets</b> the score</span></h5>
        ${rs.incomplete ? `<p class="cvr-reqs-warn">⚠️ The posting lists ${rs.expected}
          requirements and only ${rs.listed} could be read, so this percentage is out of
          ${rs.listed}, not ${rs.expected}. Treat it as provisional and re-run before you
          use the number.</p>` : ''}
        ${mathLine}
        <details class="cvr-note cvr-note--inline">
          <summary><i class="fa-regular fa-circle-question"></i> How this score is built</summary>
          <div class="cvr-note-body">
            <p>The score is one thing only: <b>the share of the JD's technical requirements
              this CV shows</b>. Each one is worth the same. Describing it in a role earns
              the full share, having it only in a list earns half, not having it earns
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
      ${reqsHtml}
      ${jhHtml}
      ${!reqs.length && (a.jd_requirements_missed || []).length
        ? `<p class="cvr-note-block"><b>JD requirements the CV never addresses:</b> ${a.jd_requirements_missed.map(esc).join('; ')}</p>`
        : ''}

      ${fold('Wording to check', wordingCounts, wordingBody ? `
        <p class="cvr-fold-lead">None of this moves the score — the score only counts what
          the JD asked for. These are flags for you: the honesty check is the one thing
          worth stopping a CV for.</p>${wordingBody}` : '', hard.length > 0)}
      ${fold('What would make it better', '', fixes ? `<div class="cvr-fixes"><ul>${fixes}</ul></div>` : '', true)}
      ${fold('Tools: listed vs. described',
             tc.checked ? `${(tc.described || []).length} of ${tc.checked} described` : '',
             toolsHtml, false)}
      ${legacy ? fold('How the old rubric scored this',
             weakest ? `weakest: ${esc(weakest.rb.label)} (${weakest.c.score})` : '',
             bars ? `<div class="cvr-crits">${bars}</div>` : '', false) : ''}

      ${a.fit_note ? `<p class="cvr-note-block"><b>On the candidate's fit:</b> ${esc(deSource(a.fit_note))}</p>` : ''}
      <p class="cvr-ai-foot">The score measures the match between this CV and this posting,
        not how well the recruiter writes — a sharp, honest CV for a candidate who doesn't
        fit will score low, and that is correct. Read the CV before you decide.</p>`;
  }

  function renderRounds(reviews) {
    const box = $('cvrRounds');
    show($('cvrRoundsSection'), reviews.length > 1);
    box.innerHTML = reviews.sort((a, b) => b.round - a.round).map(r => {
      const [label, cls] = STATUS[r.status] || [r.status, ''];
      const reasons = (r.reasons || []).map(c => esc(reasonLabels[c] || c)).join(', ');
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
        ${r.reject_other ? `<p class="cvr-round-line"><b>Other:</b> ${esc(r.reject_other)}</p>` : ''}
        ${r.reviewer_comment ? `<p class="cvr-round-comment">${esc(r.reviewer_comment)}</p>` : ''}
      </div>`;
    }).join('');
  }

  function setRejectMode(on) {
    show($('cvrRejectForm'), on);
    show($('cvrRejectConfirm'), on);
    show($('cvrRejectCancel'), on);
    show($('cvrRejectToggle'), !on);
    show($('cvrApprove'), !on);
    $('cvrFootHint').textContent = on
      ? 'Pick at least one reason and leave a comment — it is what the recruiter acts on.'
      : '';
    if (on) {
      // Llevar el ojo al formulario: en un CV largo queda debajo del iframe.
      $('cvrRejectForm').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  function openDrawer(reviewId) {
    $('cvrDrawerError').textContent = '';
    setRejectMode(false);
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
        const url = `resume-readonly.html?id=${r.candidate_id}&review_id=${r.review_id}`;
        // El onload va ANTES del src: es el que dispara la búsqueda de las citas.
        const frame = $('cvrFrame');
        frame.onload = () => { if (currentReview) hlAttach(); };
        frame.src = url;
        $('cvrOpenCv').href = url;

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

  function decide(decision) {
    if (!currentReview) return;
    const body = { decision };
    if (decision === 'rejected') {
      body.reasons = Array.from($('cvrReasons').querySelectorAll('input:checked')).map(i => i.value);
      body.reason_other = $('cvrReasonOther').value.trim();
      body.reviewer_comment = $('cvrComment').value.trim();
    }

    const buttons = [$('cvrApprove'), $('cvrRejectConfirm'), $('cvrRejectToggle')];
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
        $('cvrReasonOther').value = '';
        $('cvrReasons').querySelectorAll('input:checked').forEach(i => { i.checked = false; });
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
      .finally(() => { buttons.forEach(b => { b.disabled = false; }); });
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
        $('cvrQueue').innerHTML = '';
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

    $('cvrRejectToggle').addEventListener('click', () => setRejectMode(true));
    $('cvrRejectCancel').addEventListener('click', () => setRejectMode(false));
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
    $('cvrAi').addEventListener('click', ev => {
      const el = ev.target.closest('[data-hl].cvr-hl-item');
      if (el) hlGoTo(el.getAttribute('data-hl'));
    });
    $('cvrAi').addEventListener('keydown', ev => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
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

    Promise.all([loadReasons(), loadRecruiters()]).then(() => {
      refresh();
      // openDrawer se trae el review por su id, así que no espera a la cola.
      if (deepReviewId) openDrawer(deepReviewId);
    });
  });
})();
