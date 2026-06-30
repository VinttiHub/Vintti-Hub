/* =====================================================================
   VINTTI · Control Dashboard wiring
   - Reads [data-chart="<key>"] elements, fetches data from backend,
     renders KPIs, smooth bezier lines, bars and donas matching the
     retro/light visual system in control-dashboard-retro.css.
   - Wires the filter bar (desde, hasta, mes, corte, modelo, metric,
     opp_stage, meses, umbral) and reset button. `modelo` is hidden on the
     Management Dashboard tab (uses its own subtabs) but shown on Growth,
     AM, Sales, Ops via `data-tabs` on the filter pill.
   - Tabs are CSS-only (radio inputs); we hydrate ALL tabs once on load
     and re-fetch on filter change.
   ===================================================================== */
(function () {
  const SLUG = 'main';
  // Local-dev convenience: when opened from localhost (e.g. `python -m http.server 5500`
  // against `docs/`), point at the Flask app running on :5000 instead of App Runner.
  // Production (vinttihub.vintti.com) takes the App Runner default. Override either with
  // `window.API_BASE = '...'` before this script loads.
  const _isLocal = ['localhost', '127.0.0.1', '0.0.0.0'].includes(location.hostname);
  const _defaultApi = _isLocal
    ? `http://${location.hostname}:5000`
    : 'https://7m6mw95m8y.us-east-2.awsapprunner.com';
  const API_BASE = (window.API_BASE || _defaultApi).replace(/\/$/, '');
  const SVG_NS = 'http://www.w3.org/2000/svg';

  /* ---------- state ---------- */
  const FILTER_KEYS = ['desde', 'hasta', 'mes', 'corte', 'modelo', 'metric', 'opp_stage', 'meses', 'umbral', 'window', 'grain', 'subtab'];
  const FILTER_DEFAULTS = { opp_stage: 'Close Win', window: '30d', grain: 'month', subtab: 'staffing' };
  const state = Object.fromEntries(FILTER_KEYS.map(k => [k, FILTER_DEFAULTS[k] || '']));

  /* ---------- format ---------- */
  const fmt = {
    int: (v) => (v == null || v === '' || !isFinite(+v)) ? '—' : Math.round(+v).toLocaleString('en-US'),
    number: (v) => {
      if (v == null || v === '' || !isFinite(+v)) return '—';
      const n = +v;
      if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
      if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
      return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
    },
    decimal: (v) => (v == null || v === '' || !isFinite(+v)) ? '—' : (+v).toFixed(2),
    currency: (v) => (v == null || v === '' || !isFinite(+v)) ? '—' : '$' + Math.round(+v).toLocaleString('en-US'),
    'currency-k': (v) => {
      if (v == null || v === '' || !isFinite(+v)) return '—';
      const n = +v;
      if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
      if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
      return '$' + n.toFixed(0);
    },
    percent: (v) => (v == null || v === '' || !isFinite(+v)) ? '—' : Math.round(+v) + '%',
    percent2: (v) => (v == null || v === '' || !isFinite(+v)) ? '—' : (+v).toFixed(2) + '%',
    'percent-pp': (v) => {
      if (v == null || v === '' || !isFinite(+v)) return '—';
      const n = Math.round(+v);
      return (n > 0 ? '+' : '') + n + 'pp';
    },
    'delta-percent': (v) => {
      if (v == null || v === '' || !isFinite(+v)) return '—';
      const n = Math.round(+v);
      return (n > 0 ? '+' : '') + n + '%';
    },
    'delta-int': (v) => {
      if (v == null || v === '' || !isFinite(+v)) return '—';
      const n = Math.round(+v);
      return (n > 0 ? '+' : '') + n;
    },
    'delta-currency-k': (v) => {
      if (v == null || v === '' || !isFinite(+v)) return '—';
      const n = +v;
      const sign = n > 0 ? '+' : (n < 0 ? '−' : '');
      const abs = Math.abs(n);
      let body;
      if (abs >= 1e6)      body = '$' + (abs / 1e6).toFixed(2) + 'M';
      else if (abs >= 1e3) body = '$' + (abs / 1e3).toFixed(1) + 'K';
      else                 body = '$' + Math.round(abs).toLocaleString('en-US');
      return n === 0 ? 'Sin cambio' : sign + body;
    },
    months: (v) => (v == null || v === '' || !isFinite(+v)) ? '—' : (+v).toFixed(1) + ' mo',
    raw: (v) => (v == null || v === '') ? '—' : String(v),
    pick(name) { return this[name] || this.raw; }
  };

  /* ---------- API ---------- */
  async function fetchChart(chartKey, overrides) {
    const url = new URL(API_BASE + `/dashboards/${SLUG}/charts/${chartKey}/data`);
    const params = { ...state, ...(overrides || {}) };
    Object.entries(params).forEach(([k, v]) => {
      if (v != null && v !== '') url.searchParams.set(k, v);
    });
    const email = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '').trim();
    const headers = { 'Accept': 'application/json' };
    if (email) headers['X-User-Email'] = email;
    const res = await fetch(url.toString(), { method: 'GET', headers, credentials: 'omit' });
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${chartKey}`);
    return res.json();
  }

  /* ---------- math: smooth bezier path ----------
     Project ALL rows to a uniform x-axis (index-based). Invalid y values
     get y=null so series of different validity stay aligned by index;
     line drawing uses only the valid subset. */
  function projectPoints(rows, xKey, yKey, w, h, padX, padY) {
    if (!rows.length) return null;
    const validVals = [];
    rows.forEach(r => {
      const v = +r[yKey];
      if (isFinite(v)) validVals.push(v);
    });
    if (!validVals.length) return null;

    const minY = Math.min(...validVals, 0);
    const maxY = Math.max(...validVals);
    const spanY = (maxY - minY) || 1;
    const N = rows.length;
    const spanX = Math.max(N - 1, 1);

    // proj[i] for every row index — null y when invalid
    const proj = rows.map((r, i) => {
      const v = +r[yKey];
      const x = padX + (i / spanX) * (w - 2 * padX);
      if (!isFinite(v)) {
        return { x, y: null, val: null, raw: r, valid: false };
      }
      return {
        x,
        y: h - padY - ((v - minY) / spanY) * (h - 2 * padY),
        val: v,
        raw: r,
        valid: true,
      };
    });
    return { proj, minY, maxY };
  }

  function smoothPath(proj) {
    if (!proj.length) return '';
    if (proj.length === 1) return `M ${proj[0].x},${proj[0].y}`;
    let d = `M ${proj[0].x.toFixed(2)},${proj[0].y.toFixed(2)}`;
    for (let i = 0; i < proj.length - 1; i++) {
      const p0 = proj[i - 1] || proj[i];
      const p1 = proj[i];
      const p2 = proj[i + 1];
      const p3 = proj[i + 2] || proj[i + 1];
      const t = 0.18;
      const c1x = p1.x + (p2.x - p0.x) * t;
      const c1y = p1.y + (p2.y - p0.y) * t;
      const c2x = p2.x - (p3.x - p1.x) * t;
      const c2y = p2.y - (p3.y - p1.y) * t;
      d += ` C ${c1x.toFixed(2)},${c1y.toFixed(2)} ${c2x.toFixed(2)},${c2y.toFixed(2)} ${p2.x.toFixed(2)},${p2.y.toFixed(2)}`;
    }
    return d;
  }

  const COLOR = {
    blue: '#003bff', violet: '#6c38ff', cyan: '#4ba9ff',
    mag: '#ff1fdb', lime: '#c1ff72', amber: '#f5b94a',
    rose: '#f590ad', green: '#6cd391', ink: '#0e1117',
  };
  // Paleta para series apiladas (origins) — colores distintos por índice.
  const STACK_PALETTE = ['#6c38ff', '#4ba9ff', '#c1ff72', '#f5b94a', '#ff1fdb', '#003bff', '#6cd391', '#f590ad', '#8a93a3', '#b0782e'];

  /* R11 sub-E: ¿el valor x es el MES en curso? (YYYY-MM o YYYY-MM-DD).
     Se usa para marcar el último punto de las series mensuales como "parcial".
     new Date() = hora local del navegador (= ARG para el equipo). Charts cuyo x
     no es un mes (per-opp, etc.) no matchean el regex y quedan sin marcar. */
  function isCurrentMonthX(rawVal) {
    if (rawVal == null) return false;
    const m = String(rawVal).trim().match(/^(\d{4})-(\d{2})(?:-\d{2})?$/);
    if (!m) return false;
    const now = new Date();
    return parseInt(m[1], 10) === now.getFullYear()
        && parseInt(m[2], 10) === (now.getMonth() + 1);
  }

  /* ---------- render: line / area ---------- */
  function renderLine(svg, rows, opts) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal;
    const w = vb.width, h = vb.height;
    const padX = 6, padY = 18;
    const xKey = opts.x;
    const ys = (opts.y || '').split(',').map(s => s.trim()).filter(Boolean);
    const colors = (opts.color || 'blue').split(',').map(s => s.trim());
    const labels = (opts.labels || '').split(',').map(s => s.trim());
    const fmts = (opts.fmtY || '').split(',').map(s => s.trim());
    const area = opts.area === 'true' || opts.area === true;
    const areaFill = opts.areaFill || '';  // e.g. "ink" → solid var(--ink)

    // Wipe previously rendered series
    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());

    const seriesInfo = [];

    ys.forEach((yKey, idx) => {
      const projed = projectPoints(rows, xKey, yKey, w, h, padX, padY);
      if (!projed) return;
      const col = colors[idx] || colors[0];
      const stroke = COLOR[col] || COLOR.blue;
      // Only valid points get drawn (line and area)
      const validProj = projed.proj.filter(p => p.valid);
      if (!validProj.length) return;
      const d = smoothPath(validProj);

      // Area fill (only first series)
      if (area && idx === 0) {
        const last = validProj[validProj.length - 1];
        const first = validProj[0];
        const ap = document.createElementNS(SVG_NS, 'path');
        ap.setAttribute('d', d + ` L ${last.x.toFixed(2)},${h} L ${first.x.toFixed(2)},${h} Z`);
        ap.setAttribute('class', `area-${areaFill || col}`);
        ap.setAttribute('data-rendered', '');
        svg.appendChild(ap);
      }

      // Line
      const lp = document.createElementNS(SVG_NS, 'path');
      lp.setAttribute('d', d);
      lp.setAttribute('fill', 'none');
      lp.setAttribute('stroke', stroke);
      lp.setAttribute('stroke-width', idx === 0 ? '3.5' : '3');
      lp.setAttribute('stroke-linecap', 'round');
      lp.setAttribute('stroke-linejoin', 'round');
      lp.setAttribute('data-rendered', '');
      // Secondary lines on top of dark area get a subtle white halo for readability
      if (idx > 0 && areaFill === 'ink') {
        lp.setAttribute('filter', 'drop-shadow(0 0 1px rgba(255,255,255,0.35))');
      }
      svg.appendChild(lp);

      // End dot at last valid point
      const last = validProj[validProj.length - 1];
      const dot = document.createElementNS(SVG_NS, 'circle');
      dot.setAttribute('cx', last.x.toFixed(2));
      dot.setAttribute('cy', last.y.toFixed(2));
      dot.setAttribute('r', '6');
      dot.setAttribute('fill', '#fff');
      dot.setAttribute('stroke', stroke);
      dot.setAttribute('stroke-width', '3');
      dot.setAttribute('data-rendered', '');
      // R11 sub-E: si el último punto cae en el mes en curso, marcarlo PARCIAL
      // (anillo punteado + etiqueta), para no leerlo como un mes completo.
      const lastRaw = last.raw && last.raw[xKey];
      if (isCurrentMonthX(lastRaw)) {
        dot.setAttribute('stroke-dasharray', '3 2');
        dot.setAttribute('fill', stroke);
        dot.setAttribute('fill-opacity', '0.25');
        if (idx === 0) {
          const lbl = document.createElementNS(SVG_NS, 'text');
          lbl.setAttribute('x', last.x.toFixed(2));
          lbl.setAttribute('y', Math.max(10, last.y - 10).toFixed(2));
          lbl.setAttribute('text-anchor', 'end');
          lbl.setAttribute('font-size', '9');
          lbl.setAttribute('font-family', 'Onest, system-ui, sans-serif');
          lbl.setAttribute('font-weight', '700');
          lbl.setAttribute('fill', stroke);
          lbl.setAttribute('data-rendered', '');
          lbl.textContent = 'parcial';
          svg.appendChild(lbl);
        }
      }
      svg.appendChild(dot);

      seriesInfo.push({
        proj: projed.proj,           // full-length, includes invalid points
        color: stroke,
        fmt: fmts[idx] || opts.fmtY || 'number',
        label: labels[idx] || yKey,
        yKey,
      });
    });

    // Optional static axis labels (opt-in via data-axis="x" or "xy").
    // X-axis: prints first / middle / last x-value at the bottom of the chart.
    // Y-axis: prints min and max y-value at the right edge.
    const axisMode = (svg.dataset.axis || '').toLowerCase();
    if (axisMode && seriesInfo.length) {
      const refProj = seriesInfo[0].proj;
      const n = refProj.length;
      if (axisMode.includes('x') && n) {
        const ticks = n === 1 ? [0] : (n === 2 ? [0, 1] : [0, Math.floor((n - 1) / 2), n - 1]);
        ticks.forEach((i, k) => {
          const p = refProj[i];
          if (!p || !p.raw) return;
          const t = document.createElementNS(SVG_NS, 'text');
          t.setAttribute('x', p.x);
          t.setAttribute('y', h - 4);
          const anchor = (k === 0) ? 'start' : (k === ticks.length - 1 ? 'end' : 'middle');
          t.setAttribute('text-anchor', anchor);
          t.setAttribute('font-size', '9');
          t.setAttribute('font-family', 'Onest, system-ui, sans-serif');
          t.setAttribute('font-weight', '600');
          t.setAttribute('fill', '#8a90a0');
          t.setAttribute('letter-spacing', '0.04em');
          t.setAttribute('data-rendered', '');
          t.textContent = formatXLabel(p.raw[xKey]).toUpperCase();
          svg.appendChild(t);
        });
      }
      if (axisMode.includes('y')) {
        const minY = seriesInfo[0].proj.reduce((m, p) => p.valid && (m == null || p.val < m) ? p.val : m, null);
        const maxY = seriesInfo[0].proj.reduce((m, p) => p.valid && (m == null || p.val > m) ? p.val : m, null);
        const fmtFn = fmt.pick(seriesInfo[0].fmt);
        [[maxY, padY + 2], [minY, h - padY - 2]].forEach(([v, y]) => {
          if (v == null) return;
          const t = document.createElementNS(SVG_NS, 'text');
          t.setAttribute('x', w - 4);
          t.setAttribute('y', y);
          t.setAttribute('text-anchor', 'end');
          t.setAttribute('font-size', '9');
          t.setAttribute('font-family', 'Onest, system-ui, sans-serif');
          t.setAttribute('font-weight', '600');
          t.setAttribute('fill', '#8a90a0');
          t.setAttribute('data-rendered', '');
          t.textContent = fmtFn(v);
          svg.appendChild(t);
        });
      }
    }

    // Attach interactive hover (vertical guide + tracking dots + tooltip).
    // tooltipExtras = "field|Label|fmt,field|Label|fmt,..." renders extra rows
    // in the tooltip showing additional row-level fields.
    if (seriesInfo.length) {
      attachHoverTooltip(svg, seriesInfo, {
        xKey, rows, w, h,
        extras: parseTooltipExtras(opts.tooltipExtras),
      });
    }
  }

  function parseTooltipExtras(spec) {
    if (!spec) return [];
    return String(spec).split(',').map(part => {
      const bits = part.split('|').map(s => s.trim());
      return { field: bits[0], label: bits[1] || bits[0], fmt: bits[2] || 'number' };
    }).filter(e => e.field);
  }

  /* ---------- shared tooltip ---------- */
  let _tipEl = null;
  function getTip() {
    if (_tipEl) return _tipEl;
    _tipEl = document.createElement('div');
    _tipEl.className = 'chart-tip';
    document.body.appendChild(_tipEl);
    return _tipEl;
  }

  function formatXLabel(raw) {
    if (raw == null || raw === '') return '—';
    const s = String(raw);
    // YYYY-MM or YYYY-MM-DD
    const m = s.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/);
    if (m) {
      const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
      const mo = months[parseInt(m[2], 10) - 1] || m[2];
      return `${mo} ${m[1]}`;
    }
    return s;
  }

  /* ---------- hover overlay (vertical guide + tracking dots + tip) ---------- */
  function attachHoverTooltip(svg, seriesInfo, opts) {
    const { xKey, w, h } = opts;
    const tip = getTip();

    // Transparent overlay for mouse capture
    const overlay = document.createElementNS(SVG_NS, 'rect');
    overlay.setAttribute('x', '0');
    overlay.setAttribute('y', '0');
    overlay.setAttribute('width', w);
    overlay.setAttribute('height', h);
    overlay.setAttribute('fill', 'transparent');
    overlay.setAttribute('data-rendered', '');
    overlay.setAttribute('data-hover-overlay', '');
    svg.appendChild(overlay);

    // Vertical guide line
    const guide = document.createElementNS(SVG_NS, 'line');
    guide.setAttribute('y1', '0');
    guide.setAttribute('y2', h);
    guide.setAttribute('stroke', '#0e1117');
    guide.setAttribute('stroke-width', '1');
    guide.setAttribute('stroke-dasharray', '2 4');
    guide.setAttribute('opacity', '0');
    guide.setAttribute('data-rendered', '');
    guide.setAttribute('pointer-events', 'none');
    svg.appendChild(guide);

    // Tracking dots per series
    const tracks = seriesInfo.map(s => {
      const dot = document.createElementNS(SVG_NS, 'circle');
      dot.setAttribute('r', '7');
      dot.setAttribute('fill', '#fff');
      dot.setAttribute('stroke', s.color);
      dot.setAttribute('stroke-width', '3');
      dot.setAttribute('opacity', '0');
      dot.setAttribute('pointer-events', 'none');
      dot.setAttribute('data-rendered', '');
      svg.appendChild(dot);
      return dot;
    });

    // Convert a viewBox point to page (document) coords using bounding rect
    function viewBoxToPage(vbX, vbY) {
      const rect = svg.getBoundingClientRect();
      const xPx = rect.left + (vbX / w) * rect.width;
      const yPx = rect.top  + (vbY / h) * rect.height;
      return { x: xPx + window.scrollX, y: yPx + window.scrollY };
    }

    // Find nearest index from cursor's viewBox-x
    function nearestIndex(vbX) {
      const ref = seriesInfo[0].proj;
      let best = 0, bestDiff = Infinity;
      ref.forEach((p, i) => {
        const d = Math.abs(p.x - vbX);
        if (d < bestDiff) { bestDiff = d; best = i; }
      });
      return best;
    }

    function eventToVbX(e) {
      const rect = svg.getBoundingClientRect();
      if (rect.width === 0) return 0;
      return ((e.clientX - rect.left) / rect.width) * w;
    }

    function showAt(idx) {
      const refProj = seriesInfo[0].proj;
      if (idx < 0 || idx >= refProj.length) return;
      const refPt = refProj[idx];
      guide.setAttribute('x1', refPt.x);
      guide.setAttribute('x2', refPt.x);
      guide.setAttribute('opacity', '0.32');

      let html = '';
      const xVal = refPt.raw[xKey];
      html += `<div class="chart-tip__x">${formatXLabel(xVal)}</div>`;

      // Pull row from any series that has a valid point at this index
      let row = null;
      seriesInfo.forEach((s, i) => {
        const p = s.proj[idx];
        if (!p || !p.valid) {
          tracks[i].setAttribute('opacity', '0');
          return;
        }
        if (!row) row = p.raw;
        tracks[i].setAttribute('cx', p.x);
        tracks[i].setAttribute('cy', p.y);
        tracks[i].setAttribute('opacity', '1');
        const fn = fmt.pick(s.fmt);
        html += `<div class="chart-tip__row">
          <span class="chart-tip__dot" style="background:${s.color}"></span>
          <span class="chart-tip__lab">${s.label}</span>
          <span class="chart-tip__val">${fn(p.val)}</span>
        </div>`;
      });

      // Extra contextual fields (counts, breakdowns, etc)
      const extras = opts.extras || [];
      if (extras.length && row) {
        html += '<div class="chart-tip__sep"></div>';
        extras.forEach(e => {
          const v = row[e.field];
          const fn = fmt.pick(e.fmt);
          html += `<div class="chart-tip__row chart-tip__row--extra">
            <span class="chart-tip__dot"></span>
            <span class="chart-tip__lab">${e.label}</span>
            <span class="chart-tip__val">${fn(v)}</span>
          </div>`;
        });
      }

      tip.innerHTML = html;
      const pos = viewBoxToPage(refPt.x, refPt.y);
      tip.style.left = pos.x + 'px';
      tip.style.top  = pos.y + 'px';
      tip.classList.add('show');

      // Clamp horizontally to the viewport so the tooltip never escapes off
      // the right/left edge. When it gets clamped, keep the arrow pointing at
      // the actual data point by offsetting it via --tip-arrow-shift.
      const tRect = tip.getBoundingClientRect();
      const margin = 16;
      const halfW = tRect.width / 2;
      const minLeft = window.scrollX + margin + halfW;
      const maxLeft = window.scrollX + window.innerWidth - margin - halfW;
      let leftPx = pos.x;
      if (leftPx < minLeft) leftPx = minLeft;
      if (leftPx > maxLeft) leftPx = maxLeft;
      tip.style.left = leftPx + 'px';
      tip.style.setProperty('--tip-arrow-shift', (pos.x - leftPx).toFixed(1) + 'px');
    }

    overlay.addEventListener('mousemove', (e) => {
      const vbX = eventToVbX(e);
      showAt(nearestIndex(vbX));
    });
    overlay.addEventListener('mouseleave', () => {
      tip.classList.remove('show');
      guide.setAttribute('opacity', '0');
      tracks.forEach(d => d.setAttribute('opacity', '0'));
    });
    overlay.addEventListener('click', (e) => {
      const vbX = eventToVbX(e);
      const idx = nearestIndex(vbX);
      const refProj = seriesInfo[0].proj;
      if (idx < 0 || idx >= refProj.length) return;
      const xVal = refProj[idx].raw[xKey];
      // Only meaningful if x looks like a month (YYYY-MM)
      if (xVal && /^\d{4}-\d{2}/.test(String(xVal))) {
        const m = String(xVal).slice(0, 7);
        // Si la línea declara un panel de detalle, abrir el drawer lateral filtrado a
        // ese mes (override `mes`); si no, comportamiento histórico (month-detail inline).
        const panel = svg.dataset.lineDetailPanel;
        if (panel) { openCategoryDrawer(panel, 'mes', m); return; }
        setSelectedMonth(m);
      }
    });
  }

  // Drill por semana: setea data-override-week en los elementos week-aware del
  // panel y abre el drawer. Se asigna la impl real dentro de bindKpiDrawers.
  let openWeekDrawer = function () {};
  // Drill por período (Marketing): setea data-override-periodo en los elementos
  // period-aware del panel y abre el drawer. Impl real en bindKpiDrawers.
  let openPeriodDrawer = function () {};
  // Drill por bucket (histórico apilado): setea periodo + bucket y abre el drawer.
  let openBucketDrawer = function () {};
  // Drill por categoría (ej. dona): setea data-override-<key>=<valor> en los charts
  // del panel y abre el drawer. Valor vacío = limpia el filtro. Impl en bindKpiDrawers.
  let openCategoryDrawer = function () {};

  /* ---------- bar hover tooltip ---------- */
  function attachBarHover(svg, barEntries, opts) {
    const w = svg.viewBox.baseVal.width, h = svg.viewBox.baseVal.height;
    const tip = getTip();

    function viewBoxToPage(vbX, vbY) {
      const rect = svg.getBoundingClientRect();
      const xPx = rect.left + (vbX / w) * rect.width;
      const yPx = rect.top  + (vbY / h) * rect.height;
      return { x: xPx + window.scrollX, y: yPx + window.scrollY };
    }

    barEntries.forEach(({ rect, row, color, fmtName, label, xLabel, cx, cy }) => {
      rect.style.cursor = 'pointer';
      // Click en una barra-mes → drill al detalle de ese mes (igual que el área).
      // stopPropagation: si las barras están dentro de una card clickeable, evita
      // que también se abra el drawer del total.
      rect.addEventListener('click', (e) => {
        // Drill por semana: abre el drawer del panel con la semana clickeada.
        if (opts.weekDetailPanel && opts.weekKey && row && row[opts.weekKey]) {
          e.stopPropagation();
          openWeekDrawer(opts.weekDetailPanel, String(row[opts.weekKey]));
          return;
        }
        if (xLabel && /^\d{4}-\d{2}/.test(String(xLabel))) {
          e.stopPropagation();
          setSelectedMonth(String(xLabel).slice(0, 7));
        }
      });
      if (opts.noTooltip) {
        rect.addEventListener('mouseenter', () => rect.setAttribute('opacity', '0.85'));
        rect.addEventListener('mouseleave', () => rect.setAttribute('opacity', '1'));
        return;
      }
      rect.addEventListener('mouseenter', () => {
        rect.setAttribute('opacity', '0.85');
        const fn = fmt.pick(fmtName);
        const v = +row[opts.y];
        tip.innerHTML = `
          <div class="chart-tip__x">${formatXLabel(xLabel)}</div>
          <div class="chart-tip__row">
            <span class="chart-tip__dot" style="background:${color}"></span>
            <span class="chart-tip__lab">${label}</span>
            <span class="chart-tip__val">${fn(v)}</span>
          </div>`;
        const pos = viewBoxToPage(cx, cy);
        tip.style.left = pos.x + 'px';
        tip.style.top  = pos.y + 'px';
        tip.classList.add('show');
        // Clamp
        const tRect = tip.getBoundingClientRect();
        const margin = 8;
        const halfW = tRect.width / 2;
        const minLeft = window.scrollX + margin + halfW;
        const maxLeft = window.scrollX + window.innerWidth - margin - halfW;
        let leftPx = pos.x;
        if (leftPx < minLeft) leftPx = minLeft;
        if (leftPx > maxLeft) leftPx = maxLeft;
        tip.style.left = leftPx + 'px';
      });
      rect.addEventListener('mouseleave', () => {
        rect.setAttribute('opacity', '1');
        tip.classList.remove('show');
      });
    });
  }

  /* ---------- donut hover tooltip ---------- */
  function attachDonutHover(svg, segments, opts) {
    const w = svg.viewBox.baseVal.width, h = svg.viewBox.baseVal.height;
    const tip = getTip();

    function viewBoxToPage(vbX, vbY) {
      const rect = svg.getBoundingClientRect();
      const xPx = rect.left + (vbX / w) * rect.width;
      const yPx = rect.top  + (vbY / h) * rect.height;
      return { x: xPx + window.scrollX, y: yPx + window.scrollY };
    }

    segments.forEach(({ arc, color, label, value, fmtName, cx, cy }) => {
      arc.style.cursor = 'pointer';
      arc.addEventListener('mouseenter', () => {
        arc.setAttribute('opacity', '0.85');
        const fn = fmt.pick(fmtName || 'number');
        tip.innerHTML = `
          <div class="chart-tip__row">
            <span class="chart-tip__dot" style="background:${color}"></span>
            <span class="chart-tip__lab">${label}</span>
            <span class="chart-tip__val">${fn(value)}</span>
          </div>`;
        const pos = viewBoxToPage(cx, cy);
        tip.style.left = pos.x + 'px';
        tip.style.top  = pos.y + 'px';
        tip.classList.add('show');
      });
      arc.addEventListener('mouseleave', () => {
        arc.setAttribute('opacity', '1');
        tip.classList.remove('show');
      });
    });
  }

  /* ---------- render: bars ---------- */
  function renderBars(svg, rows, opts) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal;
    const w = vb.width, h = vb.height;
    const padX = 8;
    // Reservar espacio extra arriba (valor) / abajo (eje X) si se piden labels.
    const padTop = opts.valueLabels ? 20 : 12;
    const padBottom = opts.xLabels ? 22 : 12;
    const yKey = opts.y;
    const xKey = opts.x;
    const col = opts.color || 'violet';
    const baseColor = COLOR[col] || COLOR.blue;
    const label = opts.label || yKey;
    const fmtName = opts.fmtY || 'number';

    const vals = rows.map(r => +r[yKey]).filter(v => isFinite(v));
    if (!vals.length) return;
    const maxV = Math.max(...vals, 1);

    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());

    const n = rows.length;
    const slot = (w - 2 * padX) / Math.max(n, 1);
    const barW = Math.max(8, Math.min(42, slot * 0.62));
    const barEntries = [];

    rows.forEach((r, i) => {
      const v = +r[yKey];
      if (!isFinite(v)) return;
      const cxSlot = padX + slot * i + slot / 2;
      const x = padX + slot * i + (slot - barW) / 2;
      const barH = Math.max(2, ((v / maxV) * (h - padTop - padBottom)));
      const y = h - padBottom - barH;

      const intensity = 0.32 + (i / Math.max(n - 1, 1)) * 0.68;
      const isLast = i === n - 1;
      const fill = isLast ? baseColor : tintColor(baseColor, 1 - intensity);

      const rect = document.createElementNS(SVG_NS, 'rect');
      rect.setAttribute('x', x.toFixed(2));
      rect.setAttribute('y', y.toFixed(2));
      rect.setAttribute('width', barW.toFixed(2));
      rect.setAttribute('height', barH.toFixed(2));
      rect.setAttribute('rx', '6');
      rect.setAttribute('fill', fill);
      rect.setAttribute('data-rendered', '');
      svg.appendChild(rect);

      if (opts.valueLabels) {
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('x', cxSlot.toFixed(2));
        t.setAttribute('y', (y - 5).toFixed(2));
        t.setAttribute('text-anchor', 'middle');
        t.setAttribute('font-size', '13');
        t.setAttribute('font-weight', '800');
        t.setAttribute('fill', isLast ? baseColor : '#0e1117');
        t.setAttribute('data-rendered', '');
        t.textContent = fmt.pick(fmtName)(v);
        svg.appendChild(t);
      }
      if (opts.xLabels && xKey) {
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('x', cxSlot.toFixed(2));
        t.setAttribute('y', (h - 6).toFixed(2));
        t.setAttribute('text-anchor', 'middle');
        t.setAttribute('font-size', '11');
        t.setAttribute('font-weight', isLast ? '700' : '500');
        t.setAttribute('fill', isLast ? baseColor : '#8a93a3');
        t.setAttribute('data-rendered', '');
        t.textContent = String(r[xKey] != null ? r[xKey] : '');
        svg.appendChild(t);
      }

      barEntries.push({
        rect,
        row: r,
        color: baseColor,
        fmtName,
        label,
        xLabel: xKey ? r[xKey] : '',
        cx: x + barW / 2,
        cy: y,
      });
    });

    if (barEntries.length) {
      attachBarHover(svg, barEntries, {
        y: yKey,
        noTooltip: opts.noTooltip,
        weekDetailPanel: opts.weekDetailPanel,
        weekKey: opts.weekKey,
      });
    }
  }

  function tintColor(hex, lightness) {
    // lightness 0..1 — 0 = full color, 1 = white
    const n = parseInt(hex.replace('#', ''), 16);
    const r = (n >> 16) & 0xff, g = (n >> 8) & 0xff, b = n & 0xff;
    const mix = (c) => Math.round(c + (255 - c) * Math.max(0, Math.min(1, lightness)));
    return `rgb(${mix(r)},${mix(g)},${mix(b)})`;
  }

  /* ---------- helpers: read field with reducer ---------- */
  function reduce(rows, field, mode) {
    if (!rows || !rows.length) return null;
    // count doesn't need a field — must be checked before the field-based path below
    if (mode === 'count') return rows.length;
    // count-distinct needs a field: unique non-empty values of that field
    if (mode === 'count-distinct') {
      if (!field) return rows.length;
      const seen = new Set();
      rows.forEach(r => {
        const v = r[field];
        if (v != null && String(v) !== '') seen.add(String(v));
      });
      return seen.size;
    }
    if (mode === 'first') return rows[0][field];
    if (mode === 'last') return rows[rows.length - 1][field];
    const nums = rows.map(r => +r[field]).filter(v => isFinite(v));
    if (!nums.length) return null;
    if (mode === 'sum') return nums.reduce((a, b) => a + b, 0);
    if (mode === 'avg') return nums.reduce((a, b) => a + b, 0) / nums.length;
    if (mode === 'max') return Math.max(...nums);
    if (mode === 'min') return Math.min(...nums);
    if (mode === 'avg-last-12') {
      const tail = nums.slice(-12);
      return tail.reduce((a, b) => a + b, 0) / tail.length;
    }
    if (mode === 'delta-mom') {
      // Last - prev
      const last = +rows[rows.length - 1]?.[field];
      const prev = +rows[rows.length - 2]?.[field];
      if (!isFinite(last) || !isFinite(prev) || prev === 0) return null;
      return ((last - prev) / Math.abs(prev)) * 100;
    }
    if (mode === 'delta-mom-abs') {
      const last = +rows[rows.length - 1]?.[field];
      const prev = +rows[rows.length - 2]?.[field];
      if (!isFinite(last) || !isFinite(prev)) return null;
      return last - prev;
    }
    if (mode === 'delta-yoy') {
      const last = +rows[rows.length - 1]?.[field];
      const prev = +rows[rows.length - 13]?.[field];
      if (!isFinite(last) || !isFinite(prev) || prev === 0) return null;
      return ((last - prev) / Math.abs(prev)) * 100;
    }
    return rows[rows.length - 1][field];
  }

  /* ---------- render: KPI text ---------- */
  // Modo-corte: el usuario eligió CORTE y NO hay mes/desde/hasta. En ese caso las
  // cards mensuales (con data-corte-field) muestran el valor a 30d-terminando-en-corte.
  function isCorteMode() {
    return !!state.corte && !state.mes && !state.desde && !state.hasta;
  }

  // Cambia el sufijo "MoM" ↔ "vs 30d" de las cards mensuales según el modo.
  function syncPeriodSuffixes() {
    const corte = isCorteMode();
    document.querySelectorAll('.js-period-suffix').forEach(el => {
      const t = corte ? el.dataset.corte : el.dataset.mom;
      if (t != null) el.textContent = t;
    });
  }

  function renderText(el, rows) {
    let field = el.dataset.field;
    let mode = el.dataset.reduce || 'last';
    if (el.dataset.corteField && isCorteMode()) {
      field = el.dataset.corteField;   // columna constante (kpi_corte / *_delta)
      mode = 'first';
    }
    const fmtName = el.dataset.fmt || 'number';
    const v = reduce(rows, field, mode);
    el.textContent = fmt.pick(fmtName)(v);
    if ('classOnSign' in el.dataset) {
      el.classList.remove('green', 'rose', 'lime');
      if (v != null && isFinite(+v)) {
        if (+v > 0) el.classList.add('green');
        else if (+v < 0) el.classList.add('rose');
      }
      // Also color the enclosing .skpi-tile__delta wrapper so accompanying
      // copy (e.g. "vs PY") picks up the same hue, not just the number.
      const deltaWrap = el.closest('.skpi-tile__delta');
      if (deltaWrap) {
        deltaWrap.classList.remove('skpi-tile__delta--pos', 'skpi-tile__delta--neg', 'skpi-tile__delta--muted');
        if (v == null || !isFinite(+v))   deltaWrap.classList.add('skpi-tile__delta--muted');
        else if (+v > 0)                  deltaWrap.classList.add('skpi-tile__delta--pos');
        else if (+v < 0)                  deltaWrap.classList.add('skpi-tile__delta--neg');
        else                              deltaWrap.classList.add('skpi-tile__delta--muted');
      }
    }
    if (el.dataset.deltaPill) {
      // Apply up/down classes on parent .delta pill
      const pill = el.closest('.delta');
      if (pill) {
        pill.classList.remove('delta--up', 'delta--down', 'delta--flat');
        if (v == null || !isFinite(+v)) pill.classList.add('delta--flat');
        else if (+v > 0) pill.classList.add('delta--up');
        else if (+v < 0) pill.classList.add('delta--down');
        else pill.classList.add('delta--flat');
      }
    }
  }

  /* ---------- render: progress bar fill (0-100 → width or height %) ---------- */
  function renderProgressFill(el, rows) {
    const field = el.dataset.field;
    const mode = el.dataset.reduce || 'first';
    const v = reduce(rows, field, mode);
    const valid = (v != null && isFinite(+v));
    const pct = valid ? Math.max(0, Math.min(100, +v)).toFixed(1) + '%' : '0%';
    // Default axis is horizontal (width). Pass data-axis="height" for vertical
    // fills (e.g. the AE fuel-tank uses height-based stacking).
    const axis = (el.dataset.axis || 'width').toLowerCase();
    if (axis === 'height') {
      el.style.height = pct;
    } else if (axis === 'css-var') {
      // For conic-gradient donuts and similar: drive a CSS var instead of width/height.
      el.style.setProperty(el.dataset.cssVar || '--pct', pct);
    } else {
      el.style.width = pct;
    }
    const target = +el.dataset.target;
    if (target > 0) {
      const tile = el.closest('.skpi-tile');
      const targetEl = tile && tile.querySelector('.skpi-tile__progress-target');
      if (targetEl) targetEl.classList.toggle('skpi-tile__progress-target--met', valid && (+v) >= target);
    }
  }

  /* ---------- render dispatcher ---------- */
  function renderBinding(el, rows) {
    const bind = el.dataset.bind;
    try {
      if (!bind) return;
      // Optional row filter: data-where-field + data-where-value
      let scopedRows = rows;
      if (el.dataset.whereField && el.dataset.whereValue != null) {
        const wf = el.dataset.whereField;
        const wv = el.dataset.whereValue;
        scopedRows = (rows || []).filter(r => String(r[wf]) === wv);
      }
      if (bind === 'text') return renderText(el, scopedRows);
      if (bind === 'line' || bind === 'area') {
        return renderLine(el, scopedRows, {
          x: el.dataset.x,
          y: el.dataset.y,
          color: el.dataset.color,
          area: el.dataset.area || (bind === 'area' ? 'true' : 'false'),
          areaFill: el.dataset.areaFill,
          labels: el.dataset.labels,
          fmtY: el.dataset.fmtY,
          tooltipExtras: el.dataset.tooltipExtras,
        });
      }
      if (bind === 'list') return renderList(el, scopedRows);
      if (bind === 'rollup-list') return renderRollupList(el, scopedRows);
      if (bind === 'dtable') return renderDtable(el, scopedRows);
      if (bind === 'filter-select' || bind === 'recruiter-select') return renderFilterSelect(el, scopedRows);
      if (bind === 'filter-search') return renderFilterSearch(el, scopedRows);
      if (bind === 'cohort') return renderCohort(el, scopedRows);
      if (bind === 'grouped-list') return renderGroupedList(el, scopedRows);
      if (bind === 'donut') return renderDonut(el, scopedRows);
      if (bind === 'donut-legend') return renderDonutLegend(el, scopedRows);
      if (bind === 'ranking') return renderRanking(el, scopedRows, {
        x: el.dataset.x, y: el.dataset.y, share: el.dataset.share,
        rev: el.dataset.rev, revFmt: el.dataset.revFmt,
        color: el.dataset.color, fmtY: el.dataset.fmtY,
        limit: el.dataset.limit ? +el.dataset.limit : 12,
        empty: el.dataset.emptyText,
        labelChip: 'labelChip' in el.dataset,
      });
      if (bind === 'stacked-bars') return renderStackedBars(el, scopedRows, {
        x: el.dataset.x, xLabel: el.dataset.xLabel, series: el.dataset.series, y: el.dataset.y,
        fmtY: el.dataset.fmtY, valueLabels: 'valueLabels' in el.dataset, xLabels: 'xLabels' in el.dataset,
        detailPanel: el.dataset.bucketDetailPanel,
      });
      if (bind === 'stacked-legend') return renderStackedLegend(el, scopedRows, {
        series: el.dataset.series, y: el.dataset.y,
      });
      if (bind === 'grouped-bars') return renderGroupedBars(el, scopedRows, {
        x: el.dataset.x, series: el.dataset.series, y: el.dataset.y,
        fmtY: el.dataset.fmtY, valueLabels: 'valueLabels' in el.dataset, xLabels: 'xLabels' in el.dataset,
      });
      if (bind === 'multi-line') return renderMultiLine(el, scopedRows, {
        x: el.dataset.x, xLabel: el.dataset.xLabel, series: el.dataset.series, y: el.dataset.y, fmtY: el.dataset.fmtY,
      });
      if (bind === 'funnel') return renderFunnel(el, scopedRows);
      if (bind === 'scatter') return renderScatter(el, scopedRows, {
        x: el.dataset.x, y: el.dataset.y, size: el.dataset.size, label: el.dataset.label,
        fmtX: el.dataset.fmtX, fmtY: el.dataset.fmtY, xTitle: el.dataset.xTitle, yTitle: el.dataset.yTitle,
      });
      if (bind === 'bar-list') return renderBarList(el, scopedRows);
      if (bind === 'risk-table') return renderRiskTable(el, scopedRows);
      if (bind === 'triple-retention') {
        renderTripleRetention(el).catch(e => console.error('triple-retention', e));
        return;
      }
      // month-detail panels are NOT hydrated by the generic flow — they
      // refetch with mes= filter via refetchMonthDetails() instead.
      if (bind === 'month-detail') return;
      if (bind === 'progress-fill') return renderProgressFill(el, scopedRows);
      if (bind === 'bars') {
        return renderBars(el, scopedRows, {
          x: el.dataset.x,
          y: el.dataset.y,
          color: el.dataset.color,
          label: el.dataset.label || (el.dataset.labels || '').split(',')[0],
          fmtY: el.dataset.fmtY,
          valueLabels: 'valueLabels' in el.dataset,
          xLabels: 'xLabels' in el.dataset,
          noTooltip: 'noTooltip' in el.dataset,
          weekDetailPanel: el.dataset.weekDetailPanel,
          weekKey: el.dataset.weekKey,
        });
      }
    } catch (e) {
      console.error(`render bind=${bind} failed`, el, e);
    }
  }

  /* ---------- donut ---------- */
  const RISK_COLORS = {
    'Alto': '#ff1fdb', 'Critical': '#ff1fdb', 'High': '#ff1fdb',
    'Medio': '#6c38ff', 'Medium': '#6c38ff',
    'Bajo': '#c1ff72', 'Low': '#c1ff72', 'Safe': '#c1ff72',
  };
  const DEFAULT_PALETTE = ['#003bff', '#6c38ff', '#4ba9ff', '#ff1fdb', '#c1ff72', '#f5b94a', '#6cd391', '#f590ad'];
  // Modelos de negocio con color de marca Vintti (Recruiting verde lima · Staffing magenta).
  const MODEL_COLORS = { 'Recruiting': '#c1ff72', 'Staffing': '#ff1fdb' };
  // Series MQL / SQL con color de marca Vintti (MQL azul · SQL verde lima).
  const SERIES_COLORS = { 'MQLs': '#003bff', 'MQL': '#003bff', 'SQLs': '#c1ff72', 'SQL': '#c1ff72' };

  // Razones de caída (inactive_reason) con color de marca FIJO, para que la dona y
  // los chips del detalle usen el mismo color por razón (no índice/hash).
  const REASON_COLORS = {
    // Razones de caída (inactive_reason) — evita azul+violeta contiguos
    'Poor candidate performance': '#003bff',   // azul (el más grande)
    'Candidate resigned': '#ff1fdb',           // magenta (2º, contrasta con azul)
    'Company layoffs / downsizing': '#c1ff72', // lime
    'Accepted a better offer': '#4ba9ff',      // cyan
    'Buy out fee': '#6c38ff',                  // violeta (slice chico)
    // Razones de rechazo (candidates_batches.status, negativas)
    'Rejected By Sales': '#003bff',
    'Client Rejected CV': '#6c38ff',
    'Client Rejected after interviewing': '#4ba9ff',
    'Candidate Failed Test': '#ff1fdb',
    'Candidate abandoned process': '#c1ff72',
    // Origen del candidato en close wins (Hunteo vs Applicant)
    'Hunteo': '#c1ff72',      // verde lime
    'Applicant': '#ff1fdb',   // rosado magenta
    '(Sin origen)': '#aab2bd',
  };

  function colorForLabel(label, idx) {
    return REASON_COLORS[label] || RISK_COLORS[label] || MODEL_COLORS[label] || DEFAULT_PALETTE[idx % DEFAULT_PALETTE.length];
  }

  // Ranking de barras horizontales (categoría · barra · valor [+ share/rev]).
  function renderRanking(el, rows, opts) {
    const labelKey = opts.x, valKey = opts.y;
    const colorName = opts.color || 'violet';
    const color = COLOR[colorName] || COLOR.violet;
    const limit = opts.limit || 12;
    const fmtV = fmt.pick(opts.fmtY || 'int');
    el.classList.toggle('rk--chips', !!opts.labelChip);
    const valid = (rows || []).filter(r => isFinite(+r[valKey]));
    if (!valid.length) {
      el.innerHTML = `<div class="rk-empty">${esc(opts.empty || 'Sin datos en el período.')}</div>`;
      return;
    }
    const sorted = valid.sort((a, b) => (+b[valKey]) - (+a[valKey])).slice(0, limit);
    const max = Math.max(...sorted.map(r => +r[valKey]), 1);
    el.innerHTML = sorted.map(r => {
      const v = +r[valKey];
      const w = Math.max(3, (v / max) * 100);
      const share = (opts.share && r[opts.share] != null)
        ? `<span class="rk-row__share">${fmt.percent(r[opts.share])}</span>` : '';
      const rev = (opts.rev && r[opts.rev] != null)
        ? `<span class="rk-row__rev">${fmt.pick(opts.revFmt || 'currency-k')(r[opts.rev])}</span>` : '';
      const labelHtml = opts.labelChip ? originChipHtml(r[labelKey]) : esc(r[labelKey]);
      return `<div class="rk-row">
        <span class="rk-row__label" title="${esc(r[labelKey])}">${labelHtml}</span>
        <span class="rk-row__track"><span class="rk-row__fill" style="width:${w.toFixed(1)}%;background:${color}"></span></span>
        <span class="rk-row__val">${fmtV(v)}${share}${rev}</span>
      </div>`;
    }).join('');
  }

  // Barras apiladas históricas (x = bucket, segmentos = series/origin). Click en
  // un bucket → openBucketDrawer(detailPanel, periodo, bucketKey).
  function renderStackedBars(svg, rows, opts) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal, w = vb.width, h = vb.height;
    const padX = 8;
    const padTop = opts.valueLabels ? 22 : 14;
    const padBottom = opts.xLabels ? 24 : 14;
    const xKey = opts.x, xLabelKey = opts.xLabel || opts.x, sKey = opts.series, yKey = opts.y;
    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());
    if (!rows || !rows.length) return;

    const buckets = [], bMap = new Map(), series = [];
    rows.forEach(r => {
      const bk = String(r[xKey]);
      if (!bMap.has(bk)) { const o = { key: bk, label: r[xLabelKey], items: [], total: 0 }; bMap.set(bk, o); buckets.push(o); }
      const s = String(r[sKey] == null ? '—' : r[sKey]);
      const v = +r[yKey] || 0;
      if (v > 0) {
        bMap.get(bk).items.push({ series: s, value: v });
        bMap.get(bk).total += v;
        if (!series.includes(s)) series.push(s);
      }
    });
    const maxTotal = Math.max(...buckets.map(b => b.total), 1);
    const colorOf = s => originSeriesColor(s);
    const n = buckets.length;
    const slot = (w - 2 * padX) / Math.max(n, 1);
    const barW = Math.max(10, Math.min(54, slot * 0.6));
    const fmtV = fmt.pick(opts.fmtY || 'currency-k');
    const tip = getTip();
    const periodo = svg.dataset.overridePeriodo || 'mes';
    const pageXY = (vbX, vbY) => {
      const rect = svg.getBoundingClientRect();
      return { x: rect.left + (vbX / w) * rect.width + window.scrollX, y: rect.top + (vbY / h) * rect.height + window.scrollY };
    };
    const drill = (bk) => { if (opts.detailPanel) openBucketDrawer(opts.detailPanel, periodo, bk); };

    buckets.forEach((b, i) => {
      const cx = padX + slot * i + slot / 2;
      const x = cx - barW / 2;
      const hit = document.createElementNS(SVG_NS, 'rect');
      hit.setAttribute('x', (cx - slot / 2).toFixed(2)); hit.setAttribute('y', padTop.toFixed(2));
      hit.setAttribute('width', slot.toFixed(2)); hit.setAttribute('height', (h - padTop - padBottom).toFixed(2));
      hit.setAttribute('fill', 'transparent'); hit.setAttribute('data-rendered', ''); hit.style.cursor = 'pointer';
      hit.addEventListener('click', () => drill(b.key));
      svg.appendChild(hit);

      let yc = h - padBottom;
      b.items.forEach(it => {
        const segH = (it.value / maxTotal) * (h - padTop - padBottom);
        if (segH <= 0.5) return;
        const y = yc - segH;
        const rect = document.createElementNS(SVG_NS, 'rect');
        rect.setAttribute('x', x.toFixed(2)); rect.setAttribute('y', y.toFixed(2));
        rect.setAttribute('width', barW.toFixed(2)); rect.setAttribute('height', segH.toFixed(2));
        rect.setAttribute('fill', colorOf(it.series)); rect.setAttribute('data-rendered', ''); rect.style.cursor = 'pointer';
        rect.addEventListener('mouseenter', () => {
          rect.setAttribute('opacity', '0.85');
          tip.innerHTML = `<div class="chart-tip__x">${esc(b.label)}</div><div class="chart-tip__row"><span class="chart-tip__dot" style="background:${colorOf(it.series)}"></span><span class="chart-tip__lab">${esc(it.series)}</span><span class="chart-tip__val">${fmtV(it.value)}</span></div>`;
          const p = pageXY(cx, y); tip.style.left = p.x + 'px'; tip.style.top = p.y + 'px'; tip.classList.add('show');
        });
        rect.addEventListener('mouseleave', () => { rect.setAttribute('opacity', '1'); tip.classList.remove('show'); });
        rect.addEventListener('click', () => drill(b.key));
        svg.appendChild(rect);
        yc = y;
      });
      if (opts.valueLabels && b.total > 0) {
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('x', cx.toFixed(2)); t.setAttribute('y', (yc - 5).toFixed(2)); t.setAttribute('text-anchor', 'middle');
        t.setAttribute('font-size', '11'); t.setAttribute('font-weight', '700'); t.setAttribute('fill', '#0e1117'); t.setAttribute('data-rendered', '');
        t.textContent = fmtV(b.total); svg.appendChild(t);
      }
      if (opts.xLabels) {
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('x', cx.toFixed(2)); t.setAttribute('y', (h - 7).toFixed(2)); t.setAttribute('text-anchor', 'middle');
        t.setAttribute('font-size', '6.5'); t.setAttribute('font-weight', i === n - 1 ? '700' : '500');
        t.setAttribute('fill', i === n - 1 ? '#0e1117' : '#8a93a3'); t.setAttribute('data-rendered', '');
        t.textContent = String(b.label == null ? '' : b.label); svg.appendChild(t);
      }
    });
  }

  // Barras verticales AGRUPADAS (clustered): x = categoría (origin), varias series
  // lado a lado por categoría. Colores fijos por serie (SERIES_COLORS).
  function renderGroupedBars(svg, rows, opts) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal, w = vb.width, h = vb.height;
    const padX = 12;
    const padTop = opts.valueLabels ? 22 : 14;
    const padBottom = opts.xLabels ? 26 : 14;
    const xKey = opts.x, sKey = opts.series, yKey = opts.y;
    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());
    if (!rows || !rows.length) return;

    const buckets = [], bMap = new Map(), series = [];
    rows.forEach(r => {
      const bk = String(r[xKey] == null ? '—' : r[xKey]);
      if (!bMap.has(bk)) { const o = { key: bk, label: bk, items: [] }; bMap.set(bk, o); buckets.push(o); }
      const s = String(r[sKey] == null ? '—' : r[sKey]);
      bMap.get(bk).items.push({ series: s, value: +r[yKey] || 0 });
      if (!series.includes(s)) series.push(s);
    });
    const maxV = Math.max(...rows.map(r => +r[yKey] || 0), 1);
    const colorOf = (s, i) => SERIES_COLORS[s] || DEFAULT_PALETTE[i % DEFAULT_PALETTE.length];
    const n = buckets.length, ns = Math.max(series.length, 1);
    const slot = (w - 2 * padX) / Math.max(n, 1);
    const groupW = Math.min(slot * 0.74, 90);
    const gap = 4;
    const barW = Math.max(5, (groupW - gap * (ns - 1)) / ns);
    const fmtV = fmt.pick(opts.fmtY || 'int');
    const tip = getTip();
    const trunc = s => { s = String(s == null ? '' : s); return s.length > 16 ? s.slice(0, 15) + '…' : s; };
    const pageXY = (vbX, vbY) => { const rect = svg.getBoundingClientRect(); return { x: rect.left + (vbX / w) * rect.width + window.scrollX, y: rect.top + (vbY / h) * rect.height + window.scrollY }; };

    buckets.forEach((b, i) => {
      const cx = padX + slot * i + slot / 2;
      const x0 = cx - groupW / 2;
      series.forEach((s, si) => {
        const it = b.items.find(t => t.series === s);
        const v = it ? it.value : 0;
        const barH = v > 0 ? Math.max(2, (v / maxV) * (h - padTop - padBottom)) : 0;
        const x = x0 + si * (barW + gap);
        const y = h - padBottom - barH;
        const color = colorOf(s, si);
        if (barH > 0) {
          const rect = document.createElementNS(SVG_NS, 'rect');
          rect.setAttribute('x', x.toFixed(2)); rect.setAttribute('y', y.toFixed(2));
          rect.setAttribute('width', barW.toFixed(2)); rect.setAttribute('height', barH.toFixed(2));
          rect.setAttribute('rx', Math.min(3, barW / 3).toFixed(1));
          rect.setAttribute('fill', color); rect.setAttribute('data-rendered', ''); rect.style.cursor = 'default';
          rect.addEventListener('mouseenter', () => {
            rect.setAttribute('opacity', '0.85');
            tip.innerHTML = `<div class="chart-tip__x">${esc(b.label)}</div><div class="chart-tip__row"><span class="chart-tip__dot" style="background:${color}"></span><span class="chart-tip__lab">${esc(s)}</span><span class="chart-tip__val">${fmtV(v)}</span></div>`;
            const p = pageXY(x + barW / 2, y); tip.style.left = p.x + 'px'; tip.style.top = p.y + 'px'; tip.classList.add('show');
          });
          rect.addEventListener('mouseleave', () => { rect.setAttribute('opacity', '1'); tip.classList.remove('show'); });
          svg.appendChild(rect);
        }
        if (opts.valueLabels && v > 0) {
          const t = document.createElementNS(SVG_NS, 'text');
          t.setAttribute('x', (x + barW / 2).toFixed(2)); t.setAttribute('y', (y - 3).toFixed(2)); t.setAttribute('text-anchor', 'middle');
          t.setAttribute('font-size', '6.5'); t.setAttribute('font-weight', '600'); t.setAttribute('fill', '#475569'); t.setAttribute('data-rendered', '');
          t.textContent = fmtV(v); svg.appendChild(t);
        }
      });
      if (opts.xLabels) {
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('x', cx.toFixed(2)); t.setAttribute('y', (h - 7).toFixed(2)); t.setAttribute('text-anchor', 'middle');
        t.setAttribute('font-size', '7'); t.setAttribute('font-weight', '500'); t.setAttribute('fill', '#8a93a3'); t.setAttribute('data-rendered', '');
        t.textContent = trunc(b.label);
        const full = document.createElementNS(SVG_NS, 'title');
        full.textContent = String(b.label == null ? '' : b.label);
        t.appendChild(full);
        svg.appendChild(t);
      }
    });
  }

  // Multi-línea en el tiempo: x = bucket temporal, una línea por serie (canal).
  // Formato largo {x, xLabel, series, value}. Color por canal (originSeriesColor).
  // Llena una leyenda hermana ([data-multi-line-legend]) con los canales.
  function renderMultiLine(svg, rows, opts) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal, w = vb.width, h = vb.height;
    const padL = 26, padR = 14, padTop = 14, padBottom = 26;
    const xKey = opts.x, xLabelKey = opts.xLabel || opts.x, sKey = opts.series, yKey = opts.y;
    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());
    const legendEl = (svg.closest('.card') || document).querySelector('[data-multi-line-legend]');
    if (!rows || !rows.length) { if (legendEl) legendEl.innerHTML = ''; return; }

    const labelOf = new Map();
    rows.forEach(r => { const k = String(r[xKey]); if (!labelOf.has(k)) labelOf.set(k, r[xLabelKey]); });
    const buckets = [...labelOf.keys()].sort();
    const bIdx = new Map(buckets.map((b, i) => [b, i]));
    const seriesOrder = [], seriesData = new Map();
    rows.forEach(r => {
      const s = String(r[sKey]);
      if (!seriesData.has(s)) { seriesData.set(s, new Map()); seriesOrder.push(s); }
      seriesData.get(s).set(bIdx.get(String(r[xKey])), +r[yKey] || 0);
    });
    const maxV = Math.max(1, ...rows.map(r => +r[yKey] || 0));
    const n = buckets.length;
    const xAt = i => padL + (n <= 1 ? (w - padL - padR) / 2 : (i / (n - 1)) * (w - padL - padR));
    const yAt = v => h - padBottom - (v / Math.max(maxV, 1)) * (h - padTop - padBottom);
    const tip = getTip();
    const pageXY = (vbX, vbY) => { const rect = svg.getBoundingClientRect(); return { x: rect.left + (vbX / w) * rect.width + window.scrollX, y: rect.top + (vbY / h) * rect.height + window.scrollY }; };

    // Gridlines y/labels (0 y max)
    [0, maxV].forEach(v => {
      const y = yAt(v);
      const ln = document.createElementNS(SVG_NS, 'line');
      ln.setAttribute('x1', padL); ln.setAttribute('x2', w - padR); ln.setAttribute('y1', y.toFixed(1)); ln.setAttribute('y2', y.toFixed(1));
      ln.setAttribute('stroke', '#eef1f5'); ln.setAttribute('stroke-width', '1'); ln.setAttribute('data-rendered', '');
      svg.appendChild(ln);
      const t = document.createElementNS(SVG_NS, 'text');
      t.setAttribute('x', '2'); t.setAttribute('y', (y + 2.5).toFixed(1)); t.setAttribute('font-size', '7'); t.setAttribute('fill', '#9aa3b2'); t.setAttribute('data-rendered', '');
      t.textContent = String(v); svg.appendChild(t);
    });

    seriesOrder.forEach(s => {
      const color = originSeriesColor(s);
      const map = seriesData.get(s);
      const pts = buckets.map((b, i) => ({ x: xAt(i), y: yAt(map.get(i) || 0), v: map.get(i) || 0, i }));
      const d = pts.map((p, i) => (i ? 'L' : 'M') + p.x.toFixed(1) + ' ' + p.y.toFixed(1)).join(' ');
      const lp = document.createElementNS(SVG_NS, 'path');
      lp.setAttribute('d', d); lp.setAttribute('fill', 'none'); lp.setAttribute('stroke', color);
      lp.setAttribute('stroke-width', '2.4'); lp.setAttribute('stroke-linecap', 'round'); lp.setAttribute('stroke-linejoin', 'round');
      lp.setAttribute('data-rendered', '');
      svg.appendChild(lp);
      pts.forEach(p => {
        const dot = document.createElementNS(SVG_NS, 'circle');
        dot.setAttribute('cx', p.x.toFixed(1)); dot.setAttribute('cy', p.y.toFixed(1)); dot.setAttribute('r', '2.6');
        dot.setAttribute('fill', color); dot.setAttribute('data-rendered', '');
        dot.addEventListener('mouseenter', () => {
          tip.innerHTML = `<div class="chart-tip__x">${esc(labelOf.get(buckets[p.i]))}</div><div class="chart-tip__row"><span class="chart-tip__dot" style="background:${color}"></span><span class="chart-tip__lab">${esc(s)}</span><span class="chart-tip__val">${p.v}</span></div>`;
          const q = pageXY(p.x, p.y); tip.style.left = q.x + 'px'; tip.style.top = q.y + 'px'; tip.classList.add('show');
        });
        dot.addEventListener('mouseleave', () => tip.classList.remove('show'));
        svg.appendChild(dot);
      });
    });

    buckets.forEach((b, i) => {
      const t = document.createElementNS(SVG_NS, 'text');
      t.setAttribute('x', xAt(i).toFixed(1)); t.setAttribute('y', (h - 8).toFixed(1)); t.setAttribute('text-anchor', 'middle');
      t.setAttribute('font-size', '7'); t.setAttribute('font-weight', '500'); t.setAttribute('fill', '#8a93a3'); t.setAttribute('data-rendered', '');
      t.textContent = labelOf.get(b); svg.appendChild(t);
    });

    if (legendEl) {
      legendEl.innerHTML = seriesOrder.map(s =>
        `<span style="display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:#475569;"><span style="width:10px;height:10px;border-radius:50%;background:${originSeriesColor(s)};display:inline-block;"></span>${esc(s)}</span>`
      ).join('');
    }
  }

  // Embudo de conversión (pirámide invertida): trapecios decrecientes centrados,
  // ancho ∝ valor; labels a la izquierda con conector. Recibe una fila
  // {mql, sql, close_win, sql_pct, cw_of_mql_pct}. SVG.
  function renderFunnel(svg, rows) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal, w = vb.width, h = vb.height;
    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());
    const r = (rows && rows[0]) || {};
    const pct = x => (x == null || x === '' ? '—' : (Math.round(x * 10) / 10) + '%');
    const stages = [
      { v: +r.mql || 0, name: 'MQL (AE)', color: '#6c38ff', pct: 100 },          // violeta Vintti
      { v: +r.sql || 0, name: 'SQL (AE)', color: '#4ba9ff', pct: r.sql_pct },     // cian Vintti
      { v: +r.close_win || 0, name: 'Close Win', color: '#c1ff72', pct: r.cw_of_mql_pct }, // lima Vintti
    ];
    const maxV = Math.max(1, stages[0].v);
    const cx = w * 0.62;
    const maxHW = Math.min(w * 0.30, 210);
    const padTop = 18, padBottom = 16;
    const bandH = (h - padTop - padBottom) / stages.length;
    const hw = v => (v / maxV) * maxHW;
    const labelX = cx - maxHW - 16;
    const txt = (x, y, s, opts) => {
      const t = document.createElementNS(SVG_NS, 'text');
      t.setAttribute('x', x.toFixed(1)); t.setAttribute('y', y.toFixed(1));
      t.setAttribute('font-size', opts.size); t.setAttribute('font-weight', opts.weight || '600');
      t.setAttribute('fill', opts.fill || '#0e1117'); t.setAttribute('text-anchor', opts.anchor || 'start');
      t.setAttribute('data-rendered', ''); t.textContent = s; svg.appendChild(t); return t;
    };

    stages.forEach((s, i) => {
      const top = padTop + i * bandH, bot = top + bandH, midY = top + bandH / 2;
      const wTop = hw(s.v);
      const wBot = (i < stages.length - 1) ? hw(stages[i + 1].v) : wTop * 0.4;
      const poly = document.createElementNS(SVG_NS, 'polygon');
      poly.setAttribute('points',
        `${(cx - wTop).toFixed(1)},${top.toFixed(1)} ${(cx + wTop).toFixed(1)},${top.toFixed(1)} ` +
        `${(cx + wBot).toFixed(1)},${bot.toFixed(1)} ${(cx - wBot).toFixed(1)},${bot.toFixed(1)}`);
      poly.setAttribute('fill', s.color); poly.setAttribute('data-rendered', '');
      svg.appendChild(poly);
      // conector label → borde izq de la banda (en el medio)
      const edgeX = cx - (wTop + wBot) / 2;
      const ln = document.createElementNS(SVG_NS, 'line');
      ln.setAttribute('x1', (labelX + 2).toFixed(1)); ln.setAttribute('y1', midY.toFixed(1));
      ln.setAttribute('x2', edgeX.toFixed(1)); ln.setAttribute('y2', midY.toFixed(1));
      ln.setAttribute('stroke', s.color); ln.setAttribute('stroke-width', '1'); ln.setAttribute('data-rendered', '');
      svg.appendChild(ln);
      txt(labelX, midY - 5, `${s.name} · ${s.v}`, { size: '17', weight: '700', anchor: 'end' });
      txt(labelX, midY + 17, pct(s.pct), { size: '15', weight: '700', anchor: 'end', fill: '#8a93a3' });
    });
  }

  function renderStackedLegend(el, rows, opts) {
    const sKey = opts.series, yKey = opts.y;
    const series = [];
    (rows || []).forEach(r => {
      const s = String(r[sKey] == null ? '—' : r[sKey]);
      if ((+r[yKey] || 0) > 0 && !series.includes(s)) series.push(s);
    });
    el.innerHTML = series.map((s) =>
      `<span class="rk-legend__item">${originChipHtml(s)}</span>`
    ).join('');
  }

  // Scatter (X · Y · tamaño = burbuja · color por fila). Para CLTV: X=vida, Y=MRR.
  function renderScatter(svg, rows, opts) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal, w = vb.width, h = vb.height;
    const padL = 48, padR = 16, padT = 14, padB = 30;
    const xKey = opts.x, yKey = opts.y, sizeKey = opts.size, labelKey = opts.label;
    const fmtX = fmt.pick(opts.fmtX || 'number'), fmtY = fmt.pick(opts.fmtY || 'number');
    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());
    const pts = (rows || []).filter(r => isFinite(+r[xKey]) && isFinite(+r[yKey]));
    if (!pts.length) return;
    const xMax = Math.max(...pts.map(r => +r[xKey]), 1) * 1.15;
    const yMax = Math.max(...pts.map(r => +r[yKey]), 1) * 1.15;
    const sMax = Math.max(...pts.map(r => +r[sizeKey] || 1), 1);
    const plotW = w - padL - padR, plotH = h - padT - padB;
    const sx = v => padL + (v / xMax) * plotW;
    const sy = v => padT + plotH - (v / yMax) * plotH;
    const tip = getTip();
    const pageXY = (vbX, vbY) => {
      const rect = svg.getBoundingClientRect();
      return { x: rect.left + (vbX / w) * rect.width + window.scrollX, y: rect.top + (vbY / h) * rect.height + window.scrollY };
    };
    const mk = (tag, attrs) => { const e = document.createElementNS(SVG_NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); e.setAttribute('data-rendered', ''); svg.appendChild(e); return e; };
    // ejes
    mk('line', { x1: padL, y1: padT, x2: padL, y2: padT + plotH, stroke: '#e3e6ec', 'stroke-width': 1 });
    mk('line', { x1: padL, y1: padT + plotH, x2: padL + plotW, y2: padT + plotH, stroke: '#e3e6ec', 'stroke-width': 1 });
    // ticks (0 y max) en cada eje
    [0, yMax].forEach(v => { const t = mk('text', { x: padL - 6, y: (sy(v) + 3).toFixed(1), 'text-anchor': 'end', 'font-size': 9, fill: '#8a93a3' }); t.textContent = fmtY(v); });
    [0, xMax].forEach(v => { const t = mk('text', { x: sx(v).toFixed(1), y: (padT + plotH + 16).toFixed(1), 'text-anchor': 'middle', 'font-size': 9, fill: '#8a93a3' }); t.textContent = fmtX(v); });
    // títulos
    if (opts.xTitle) { const t = mk('text', { x: (padL + plotW / 2).toFixed(1), y: (h - 2).toFixed(1), 'text-anchor': 'middle', 'font-size': 10, 'font-weight': 600, fill: '#5a6472' }); t.textContent = opts.xTitle; }
    if (opts.yTitle) { const t = mk('text', { x: 10, y: (padT + plotH / 2).toFixed(1), 'text-anchor': 'middle', 'font-size': 10, 'font-weight': 600, fill: '#5a6472', transform: `rotate(-90 10 ${(padT + plotH / 2).toFixed(1)})` }); t.textContent = opts.yTitle; }
    // puntos
    pts.forEach((r, i) => {
      const cx = sx(+r[xKey]), cy = sy(+r[yKey]);
      const rad = 6 + Math.sqrt((+r[sizeKey] || 1) / sMax) * 16;
      const color = STACK_PALETTE[i % STACK_PALETTE.length];
      const c = mk('circle', { cx: cx.toFixed(1), cy: cy.toFixed(1), r: rad.toFixed(1), fill: color, 'fill-opacity': 0.72, stroke: '#fff', 'stroke-width': 1.5 });
      c.style.cursor = 'pointer';
      c.addEventListener('mouseenter', () => {
        c.setAttribute('fill-opacity', '0.95');
        tip.innerHTML = `<div class="chart-tip__x">${esc(r[labelKey])}</div><div class="chart-tip__row"><span class="chart-tip__lab">${esc(opts.xTitle || 'X')}</span><span class="chart-tip__val">${fmtX(+r[xKey])}</span></div><div class="chart-tip__row"><span class="chart-tip__lab">${esc(opts.yTitle || 'Y')}</span><span class="chart-tip__val">${fmtY(+r[yKey])}</span></div><div class="chart-tip__row"><span class="chart-tip__lab">Clientes</span><span class="chart-tip__val">${(+r[sizeKey] || 0)}</span></div>`;
        const p = pageXY(cx, cy - rad); tip.style.left = p.x + 'px'; tip.style.top = p.y + 'px'; tip.classList.add('show');
      });
      c.addEventListener('mouseleave', () => { c.setAttribute('fill-opacity', '0.72'); tip.classList.remove('show'); });
    });
  }

  function renderDonut(svg, rows) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const labelKey = svg.dataset.label || 'label';
    const valueKey = svg.dataset.value || 'value';
    const w = svg.viewBox.baseVal.width, h = svg.viewBox.baseVal.height;
    const cx = w / 2, cy = h / 2, r = 64, sw = 14;
    svg.innerHTML = '';

    if (!rows.length) {
      // Empty placeholder ring
      const c = document.createElementNS(SVG_NS, 'circle');
      c.setAttribute('cx', cx); c.setAttribute('cy', cy); c.setAttribute('r', r);
      c.setAttribute('fill', 'none'); c.setAttribute('stroke', '#f4f6fa');
      c.setAttribute('stroke-width', sw);
      svg.appendChild(c);
      return;
    }

    const total = rows.reduce((acc, r) => acc + (+r[valueKey] || 0), 0) || 1;
    const circumference = 2 * Math.PI * r;
    const gap = 4; // px gap between segments

    // Bg ring
    const bg = document.createElementNS(SVG_NS, 'circle');
    bg.setAttribute('cx', cx); bg.setAttribute('cy', cy); bg.setAttribute('r', r);
    bg.setAttribute('fill', 'none'); bg.setAttribute('stroke', '#f4f6fa');
    bg.setAttribute('stroke-width', sw);
    svg.appendChild(bg);

    let offset = 0;
    const segments = [];
    rows.forEach((row, i) => {
      const v = +row[valueKey] || 0;
      const len = (v / total) * circumference;
      const drawLen = Math.max(0, len - gap);
      const color = colorForLabel(String(row[labelKey] || ''), i);
      const arc = document.createElementNS(SVG_NS, 'circle');
      arc.setAttribute('cx', cx); arc.setAttribute('cy', cy); arc.setAttribute('r', r);
      arc.setAttribute('fill', 'none');
      arc.setAttribute('stroke', color);
      arc.setAttribute('stroke-width', sw);
      arc.setAttribute('stroke-linecap', 'round');
      arc.setAttribute('stroke-dasharray', `${drawLen} ${circumference - drawLen}`);
      arc.setAttribute('stroke-dashoffset', String(-offset));
      arc.setAttribute('transform', `rotate(-90 ${cx} ${cy})`);
      svg.appendChild(arc);
      segments.push({
        arc, color,
        label: String(row[labelKey] || '—'),
        value: v,
        fmtName: 'int',
        cx, cy: cy - r,
      });
      offset += len;
    });

    // Center text
    const txt1 = document.createElementNS(SVG_NS, 'text');
    txt1.setAttribute('x', cx); txt1.setAttribute('y', cy - 2);
    txt1.setAttribute('text-anchor', 'middle');
    txt1.setAttribute('fill', '#0e1117');
    txt1.setAttribute('font-size', '26');
    txt1.setAttribute('font-weight', '700');
    txt1.setAttribute('font-family', 'Onest, system-ui, sans-serif');
    txt1.textContent = fmt.pick(svg.dataset.centerFmt || 'int')(total);
    svg.appendChild(txt1);

    const txt2 = document.createElementNS(SVG_NS, 'text');
    txt2.setAttribute('x', cx); txt2.setAttribute('y', cy + 16);
    txt2.setAttribute('text-anchor', 'middle');
    txt2.setAttribute('fill', '#8a90a0');
    txt2.setAttribute('font-size', '11');
    txt2.setAttribute('font-family', 'Onest, system-ui, sans-serif');
    txt2.textContent = svg.dataset.centerLabel || 'total';
    svg.appendChild(txt2);

    attachDonutHover(svg, segments, {});

    // Click en un segmento → abre el detalle filtrado por esa categoría.
    const detailPanel = svg.dataset.detailPanel;
    const detailKey = svg.dataset.detailKey;
    if (detailPanel && detailKey) {
      segments.forEach(seg => {
        seg.arc.style.cursor = 'pointer';
        seg.arc.addEventListener('click', () => openCategoryDrawer(detailPanel, detailKey, seg.label));
      });
    }
  }

  function renderDonutLegend(el, rows) {
    const labelKey = el.dataset.label || 'label';
    const valueKey = el.dataset.value || 'value';
    const ul = el.querySelector('ul') || el;
    if (ul.tagName !== 'UL') {
      el.innerHTML = '<ul></ul>';
    }
    const list = el.querySelector('ul');
    list.innerHTML = '';
    const valFmt = fmt.pick(el.dataset.valFmt || 'int');
    const pctOnly = 'pctOnly' in el.dataset;
    const total = rows.reduce((a, r) => a + (+r[valueKey] || 0), 0) || 1;
    rows.forEach((row, i) => {
      const v = +row[valueKey] || 0;
      const pct = Math.round((v / total) * 100) + '%';
      const color = colorForLabel(String(row[labelKey] || ''), i);
      const valHtml = pctOnly
        ? `<span class="val">${pct}</span>`
        : `<span class="val">${valFmt(v)} <span class="muted" style="font-weight:500;color:var(--ink-3);font-size:11px">${pct}</span></span>`;
      const li = document.createElement('li');
      li.innerHTML = `
        <span class="swatch" style="background:${color}"></span>
        <span>${esc(row[labelKey] || '—')}</span>
        <span class="leader"></span>
        ${valHtml}
      `;
      if (el.dataset.detailPanel && el.dataset.detailKey) {
        li.style.cursor = 'pointer';
        li.addEventListener('click', () => openCategoryDrawer(el.dataset.detailPanel, el.dataset.detailKey, String(row[labelKey] || '')));
      }
      list.appendChild(li);
    });
  }

  /* ---------- triple retention (3 / 6 / 12m windows overlaid) ----------
     Fetches `candidate_retention_rate` 3 times with umbral=3,6,12 and renders
     3 lines on the same SVG. When state.umbral is set, only shows that line. */
  async function renderTripleRetention(svg) {
    const chartKey = svg.dataset.chart || 'am_line_candidate_retention';
    const xKey = svg.dataset.x || 'cohorte_mes';
    const yField = svg.dataset.y || 'retention';
    const allUmbrals = (svg.dataset.umbrals || '3,6,12').split(',').map(s => parseInt(s.trim(), 10));
    const allColors  = (svg.dataset.colors  || 'lime,cyan,violet').split(',').map(s => s.trim());

    // If user picked a specific umbral via the global filter, only show that line.
    let umbrals = allUmbrals;
    let colors = allColors;
    const sel = parseInt(state.umbral || '', 10);
    if (allUmbrals.includes(sel)) {
      const idx = allUmbrals.indexOf(sel);
      umbrals = [allUmbrals[idx]];
      colors  = [allColors[idx] || allColors[0]];
    }
    // Toggle the inline series-pill labels in the chart container based on
    // which umbral lines are visible.
    const wrap = svg.parentElement;
    if (wrap) {
      wrap.querySelectorAll('.series-pill[data-umbral]').forEach(pill => {
        pill.style.display = umbrals.includes(parseInt(pill.dataset.umbral, 10)) ? '' : 'none';
      });
    }

    const datasets = await Promise.all(
      umbrals.map(u =>
        fetchChart(chartKey, { umbral: u })
          .then(r => r.rows || [])
          .catch(() => [])
      )
    );

    // Merge by cohorte_mes — produces rows with ret_X, stay_X (per umbral) + start (cohort size)
    const byMonth = {};
    datasets.forEach((rows, idx) => {
      const u = umbrals[idx];
      rows.forEach(r => {
        const m = r[xKey];
        if (m == null) return;
        if (!byMonth[m]) byMonth[m] = { [xKey]: m };
        byMonth[m][`ret_${u}`] = r[yField];
        byMonth[m][`stay_${u}`] = r.stay_candidate;
        // start_candidate_total is the same across umbrals (cohort size)
        if (byMonth[m].start_candidate_total == null) {
          byMonth[m].start_candidate_total = r.start_candidate_total;
        }
      });
    });
    const merged = Object.keys(byMonth).sort().map(m => byMonth[m]);

    const yFields = umbrals.map(u => `ret_${u}`).join(',');
    const labels = umbrals.map(u => `${u} meses`).join(',');
    const fmts = umbrals.map(() => 'percent').join(',');
    // Tooltip extras: cohort size + stay count per visible umbral
    const tooltipExtras = [
      'start_candidate_total|Cohort size|int',
      ...umbrals.map(u => `stay_${u}|Stayed ${u}m|int`),
    ].join(',');

    renderLine(svg, merged, {
      x: xKey,
      y: yFields,
      color: colors.join(','),
      labels,
      fmtY: fmts,
      area: 'false',
      tooltipExtras,
    });
  }

  /* ---------- risk table (rich detail per account) ---------- */
  function riskBadge(riesgo) {
    const s = String(riesgo || '');
    let cls = 'activo', label = s;
    if (/Alto|🔴/.test(s)) { cls = 'baja-real'; label = 'Alto'; }
    else if (/Medio|🟡/.test(s)) { cls = 'baja-buyout'; label = 'Medio'; }
    else if (/Bajo|🟢/.test(s)) { cls = 'alta'; label = 'Bajo'; }
    return `<span class="mdetail__cand-state mdetail__cand-state--${cls}">${esc(label)}</span>`;
  }
  function fmtDateLong(s) {
    if (!s) return '—';
    const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!m) return String(s);
    const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
    return `${parseInt(m[3], 10)} ${months[parseInt(m[2], 10) - 1]} ${m[1]}`;
  }
  function cleanProcesses(s) {
    if (!s) return '<span class="muted">—</span>';
    const str = String(s);
    if (/Sin procesos/i.test(str)) {
      return `<span class="risk-status risk-status--warn">⚠ Sin procesos activos</span>`;
    }
    // "🟢 Tiene procesos abiertos (Interviewing)" — extract stages between parens
    const stages = str.match(/\(([^)]+)\)/);
    const inner = stages ? stages[1] : '';
    return `<span class="risk-status risk-status--ok">● ${esc(inner || 'Activos')}</span>`;
  }
  function renderRiskTable(el, rows) {
    if (!rows || !rows.length) {
      el.innerHTML = '<div class="muted" style="padding:24px;text-align:center;font-size:13px">No data</div>';
      return;
    }
    const sorted = rows.slice().sort((a, b) => {
      const ra = +a.risk_score || 0, rb = +b.risk_score || 0;
      if (ra !== rb) return rb - ra;
      return String(a.client_name).localeCompare(String(b.client_name));
    });
    const body = sorted.map(r => `
      <tr>
        <td>${riskBadge(r.riesgo)}</td>
        <td class="ink">${esc(r.client_name || '—')}</td>
        <td>${cleanProcesses(r.estado_procesos)}</td>
        <td class="num">${fmt.int(r.candidatos_activos)}</td>
        <td class="num">${esc(fmtDateLong(r.last_hire_d))}</td>
        <td class="num">${fmt.int(r.replacements)}</td>
        <td class="num ink">${fmt.int(r.risk_score)}</td>
      </tr>
    `).join('');
    el.innerHTML = `
      <div class="risk-table-wrap">
        <table class="dtable risk-table">
          <thead>
            <tr>
              <th>Riesgo</th>
              <th>Cliente</th>
              <th>Estado de procesos</th>
              <th class="num">Activos</th>
              <th class="num">Último hire</th>
              <th class="num">Repl.</th>
              <th class="num">Score</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }

  /* ---------- bar list (top N items by value) ---------- */
  function renderBarList(el, rows) {
    const nameField = el.dataset.barName || 'name';
    const valField = el.dataset.barValue || 'value';
    const winField  = el.dataset.barWinValue;   // optional: split bar (wins segment)
    const lostField = el.dataset.barLostValue;  // optional: split bar (losses segment)
    const limit = parseInt(el.dataset.barLimit || '10', 10);
    const colorByValue = el.dataset.barColorByValue === 'true';
    const splitMode = !!(winField && lostField);

    if (!rows.length) {
      el.innerHTML = '<div class="muted" style="padding:12px;font-size:13px;text-align:center">No data</div>';
      return;
    }

    const sorted = rows.slice()
      .sort((a, b) => (+b[valField] || 0) - (+a[valField] || 0))
      .slice(0, limit);
    const max = Math.max(...sorted.map(r => +r[valField] || 0), 1);

    el.innerHTML = sorted.map(r => {
      const v = +r[valField] || 0;
      const pct = (v / max) * 100;

      if (splitMode) {
        const wins = +r[winField]  || 0;
        const lost = +r[lostField] || 0;
        const winPct  = (wins / max) * 100;
        const lostPct = (lost / max) * 100;
        return `
          <div class="bars__row">
            <span class="bars__name">${esc(r[nameField] || '—')}</span>
            <span class="bars__val">
              ${esc(v)}
              <span class="bars__split-meta">
                <span class="bars__win">${wins} win</span>
                ·
                <span class="bars__lost">${lost} lost</span>
              </span>
            </span>
            <span class="bars__bar bars__bar--split">
              <span class="bars__bar-seg bars__bar-seg--win"  style="width:${winPct.toFixed(1)}%"></span>
              <span class="bars__bar-seg bars__bar-seg--lost" style="width:${lostPct.toFixed(1)}%"></span>
            </span>
          </div>
        `;
      }

      let cls = '';
      if (colorByValue) {
        if (v >= max * 0.7) cls = 'mag';
        else if (v >= max * 0.4) cls = 'violet';
        else cls = 'cyan';
      }
      return `
        <div class="bars__row">
          <span class="bars__name">${esc(r[nameField] || '—')}</span>
          <span class="bars__val">${esc(v)}</span>
          <span class="bars__bar ${cls}"><span style="width:${pct.toFixed(1)}%"></span></span>
        </div>
      `;
    }).join('');
  }

  /* ---------- escape helper ---------- */
  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /* ---------- list (used inside flip-back / panels) ---------- */
  function renderList(el, rows) {
    const nameField = el.dataset.listName || 'name';
    const subField  = el.dataset.listSub  || '';
    const dateField = el.dataset.listDate || '';
    const limit     = parseInt(el.dataset.limit || '500', 10);
    if (!rows.length) {
      el.innerHTML = '<div class="dlist__empty">No data</div>';
      return;
    }
    const items = rows.slice(0, limit);
    el.innerHTML = items.map(r => {
      const name = esc(r[nameField] || '—');
      const sub  = subField  ? `<span class="dlist__sub">${esc(r[subField] || '')}</span>` : '';
      const date = dateField ? `<span class="dlist__date">${esc(r[dateField] || '')}</span>` : '';
      return `<div class="dlist__row"><div><span class="dlist__name">${name}</span>${sub}</div>${date}</div>`;
    }).join('');
  }

  /* Group rows by data-group-by, count entries, render sorted by count desc.
     data-sub-template: e.g. "{n} contractors" — {n} is replaced with the count.
     data-list-date: optional field on the row to pick (earliest non-empty value per group). */
  function renderRollupList(el, rows) {
    const groupBy = el.dataset.groupBy;
    if (!groupBy) { renderList(el, rows); return; }
    const subTemplate = el.dataset.subTemplate || '';
    const dateField   = el.dataset.listDate || '';
    const limit       = parseInt(el.dataset.limit || '500', 10);
    if (!rows.length) {
      el.innerHTML = '<div class="dlist__empty">No data</div>';
      return;
    }
    const map = new Map();
    rows.forEach(r => {
      const key = r[groupBy];
      if (!key) return;
      let g = map.get(key);
      if (!g) { g = { name: key, count: 0, earliestDate: '' }; map.set(key, g); }
      g.count++;
      const d = String(r[dateField] || '');
      if (d && (!g.earliestDate || d < g.earliestDate)) g.earliestDate = d;
    });
    const items = Array.from(map.values()).sort((a, b) => b.count - a.count).slice(0, limit);
    if (!items.length) {
      el.innerHTML = '<div class="dlist__empty">No data</div>';
      return;
    }
    el.innerHTML = items.map(g => {
      const sub = subTemplate ? subTemplate.replace('{n}', g.count) : '';
      const subHtml  = sub ? `<span class="dlist__sub">${esc(sub)}</span>` : '';
      const dateHtml = g.earliestDate ? `<span class="dlist__date">${esc(g.earliestDate)}</span>` : '';
      return `<div class="dlist__row"><div><span class="dlist__name">${esc(g.name)}</span>${subHtml}</div>${dateHtml}</div>`;
    }).join('');
  }

  /* ---------- origin chip (colored pill, UNIQUE stable color per origin) ----------
     Cada origin conocido tiene un índice fijo → tono (hue) separado por ángulo áureo
     → color único y consistente en TODAS las tablas. Origins no listados caen a un
     hash estable de su nombre, así que igual son determinísticos. */
  // Paleta EXPLÍCITA por canal: un hue bien separado perceptualmente para cada uno
  // (verde / azul / naranja / violeta / rosa / ...) para que no se confundan.
  // "(Sin origen)" y NA → gris neutro. Canales no listados → hue por hash de un set
  // de hues distintos. Esto alimenta las pills, los rankings, las barras y el line chart.
  const ORIGIN_HUE = {
    'website organic': 140, 'seo': 125,
    'social media': 210, 'social': 210, 'linkedin': 205,
    'ai': 32, 'chatgpt': 185,
    'events': 268, 'eventos': 268, 'webinar': 162,
    'import': 330, 'email': 300,
    'referral': 178, 'connected inbox': 248,
    'paid media': 358, 'paid': 358,
    'campaign': 95, 'lead mag.': 80,
    'google': 222, 'press action': 15, 'hubspot': 45,
  };
  const FALLBACK_HUES = [140, 210, 32, 268, 330, 178, 95, 300, 248, 358, 80, 45, 185, 15];
  const NEUTRAL_ORIGINS = new Set(['(sin origen)', 'sin origen', '—', '-', 'na', 'n/a', '']);
  function _originKey(label) { return String(label == null ? '' : label).trim().toLowerCase(); }
  function _originNeutral(label) { return NEUTRAL_ORIGINS.has(_originKey(label)); }
  function chipHue(label) {
    const k = _originKey(label);
    if (Object.prototype.hasOwnProperty.call(ORIGIN_HUE, k)) return ORIGIN_HUE[k];
    let h = 0;
    for (let i = 0; i < k.length; i++) h = (h * 31 + k.charCodeAt(i)) >>> 0;
    return FALLBACK_HUES[h % FALLBACK_HUES.length];
  }
  function chipColor(label) {
    if (_originNeutral(label)) return { fg: '#5b6573', bg: '#eef1f5' };
    // Razones de caída: mismo color de marca que la dona (tinte claro + texto fuerte).
    const rc = REASON_COLORS[label];
    if (rc) {
      const fg = (rc.toLowerCase() === '#c1ff72') ? '#3a6b00' : rc;  // lime es muy claro para texto
      return { fg, bg: rc + '22' };
    }
    const hue = chipHue(label);
    return { fg: `hsl(${hue}, 50%, 35%)`, bg: `hsl(${hue}, 70%, 93%)` };
  }
  // Color sólido para barras/líneas: pastel con cuerpo, del MISMO hue de la pill.
  function originSeriesColor(label) {
    if (REASON_COLORS[label]) return REASON_COLORS[label];  // colores de marca fijos (Hunteo/Applicant, razones)
    if (_originNeutral(label)) return '#aab2bd';
    return `hsl(${chipHue(label)}, 60%, 62%)`;
  }
  function originChipHtml(label) {
    const s = (label == null || label === '') ? '—' : String(label);
    const c = chipColor(s);
    return `<span class="origin-chip" style="background:${c.bg};color:${c.fg}">${esc(s)}</span>`;
  }
  const isNumFmt = (f) => f && f !== 'raw' && f !== 'date' && f !== 'chip';

  /* ---------- dtable (generic data table from data-cols="field|Label|fmt,...") ---------- */
  function renderDtable(el, rows) {
    const cols = (el.dataset.cols || '').split(',').map(spec => {
      const parts = spec.trim().split('|');
      return { field: parts[0] || '', label: parts[1] || parts[0] || '', fmt: parts[2] || 'raw' };
    }).filter(c => c.field);
    const empty = el.dataset.emptyText || 'No data';
    if (!cols.length) {
      el.innerHTML = `<div class="muted" style="padding:18px;text-align:center">${esc(empty)}</div>`;
      return;
    }
    rows = rows || [];
    // Cache de las filas completas (sin filtrar) para re-render al cambiar un dropdown.
    el._dtableRows = rows;

    // ---- Drill por fila: click en una fila setea un multi-filtro en otra dtable ----
    // data-row-drill-target = chart key destino; data-row-drill-field = columna a leer;
    // data-row-drill-target-field = campo del multi-filtro destino (default = field).
    if (el.dataset.rowDrillTarget && !el._rowDrillBound) {
      el._rowDrillBound = true;
      el.addEventListener('click', (ev) => {
        const tr = ev.target.closest('tbody tr[data-drill-val]');
        if (!tr) return;
        const val = tr.getAttribute('data-drill-val') || '';
        const targetKey = el.dataset.rowDrillTarget;
        const tField = el.dataset.rowDrillTargetField || el.dataset.rowDrillField;
        const target = document.querySelector(`[data-chart="${targetKey}"][data-bind="dtable"]`);
        if (!target || !tField) return;
        let st = {};
        try { st = JSON.parse(target.dataset.mfState || '{}'); } catch (_e) { st = {}; }
        if (val) st[tField] = val; else delete st[tField];
        target.dataset.mfState = JSON.stringify(st);
        const trows = target._dtableRows
          || lastFetchedRows.get(compKeyFor(target.dataset.chart, readOverridesFor(target)))
          || [];
        renderDtable(target, trows);
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }

    // ---- Multi-filtro por dropdown: data-multi-filter="field|Label,field2|Label2,..." ----
    // Cada campo se vuelve un <select> con los valores distintos de la columna; las
    // selecciones se combinan (AND) y se guardan en data-mf-state. 100% client-side.
    let toolbarHtml = '';
    let mfState = {};
    const mfSpec = (el.dataset.multiFilter || '').trim();
    if (mfSpec) {
      try { mfState = JSON.parse(el.dataset.mfState || '{}'); } catch (_e) { mfState = {}; }
      const mfFields = mfSpec.split(',').map(s => {
        const [field, label] = s.trim().split('|');
        return { field: (field || '').trim(), label: (label || field || '').trim() };
      }).filter(f => f.field);
      const selectsHtml = mfFields.map(f => {
        const vals = [...new Set((rows || [])
          .map(r => r[f.field])
          .filter(v => v != null && String(v).trim() !== '')
          .map(String))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
        const cur = mfState[f.field] || '';
        const opts = [`<option value="">${esc(f.label)}: Todos</option>`]
          .concat(vals.map(v => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(v)}</option>`))
          .join('');
        return `<select class="dtable-mf" data-mf-field="${esc(f.field)}" aria-label="${esc(f.label)}">${opts}</select>`;
      }).join('');
      const hasActive = Object.keys(mfState).length > 0;
      toolbarHtml = `<div class="dtable-toolbar">${selectsHtml}` +
        (hasActive ? `<button type="button" class="dtable-mf-clear" data-mf-clear>Limpiar</button>` : '') +
        `</div>`;
      if (!el._mfBound) {
        el._mfBound = true;
        el.addEventListener('change', (ev) => {
          const sel = ev.target.closest('select.dtable-mf');
          if (!sel) return;
          let st = {};
          try { st = JSON.parse(el.dataset.mfState || '{}'); } catch (_e) { st = {}; }
          if (sel.value) st[sel.dataset.mfField] = sel.value; else delete st[sel.dataset.mfField];
          el.dataset.mfState = JSON.stringify(st);
          renderDtable(el, el._dtableRows || []);
        });
        el.addEventListener('click', (ev) => {
          if (!ev.target.closest('[data-mf-clear]')) return;
          el.dataset.mfState = '{}';
          renderDtable(el, el._dtableRows || []);
        });
      }
    }

    // Filtro client-side por columna (ej. account): si el dtable tiene data-filter-col
    // y data-filter-value, mostramos solo las filas que matchean (sin pegarle al backend).
    let viewRows = rows;
    const fVal = (el.dataset.filterValue || '').trim().toLowerCase();
    const fColIdx = (el.dataset.filterCol != null && el.dataset.filterCol !== '') ? +el.dataset.filterCol : null;
    if (fVal && fColIdx != null && cols[fColIdx]) {
      const ff = cols[fColIdx].field;
      viewRows = viewRows.filter(r => String(r[ff] == null ? '' : r[ff]).toLowerCase().includes(fVal));
    }
    // Aplicar multi-filtro (match exacto por campo).
    const mfKeys = Object.keys(mfState);
    if (mfKeys.length) {
      viewRows = viewRows.filter(r => mfKeys.every(f => String(r[f] == null ? '' : r[f]) === mfState[f]));
    }
    // Si data-scroll está presente, la tabla va dentro de un contenedor con
    // alto máximo + scroll interno (los filtros quedan fijos arriba).
    const wrapTable = (t) => ('scroll' in el.dataset) ? `<div class="dtable-scroll">${t}</div>` : t;
    if (!viewRows.length) {
      el.innerHTML = toolbarHtml + wrapTable(`<table class="dtable"><thead><tr>${cols.map(c => `<th>${esc(c.label)}</th>`).join('')}</tr></thead>` +
        `<tbody><tr><td colspan="${cols.length}" class="muted" style="text-align:center;padding:18px">${esc(empty)}</td></tr></tbody></table>`);
      return;
    }
    const head = cols.map(c => {
      return `<th${isNumFmt(c.fmt) ? ' class="num"' : ''}>${esc(c.label)}</th>`;
    }).join('');
    // Drill por fila: si data-row-drill-field está, cada <tr> lleva el valor de esa
    // columna para filtrar otra tabla al hacer click (ver listener abajo).
    const drillField = el.dataset.rowDrillField || '';
    const body = viewRows.map(r => {
      const dv = drillField ? ` data-drill-val="${esc(String(r[drillField] == null ? '' : r[drillField]))}"` : '';
      const trCls = drillField ? ' class="dtable-row--drill"' : '';
      return `<tr${trCls}${dv}>` + cols.map(c => {
        if (c.fmt === 'chip') return `<td>${originChipHtml(r[c.field])}</td>`;
        if (c.fmt === 'eff') {
          const v = String(r[c.field] == null ? '' : r[c.field]);
          const cls = { 'Alta': 'eff-alta', 'Media': 'eff-media', 'Baja': 'eff-baja' }[v] || '';
          return `<td><span class="eff-pill ${cls}">${esc(v || '—')}</span></td>`;
        }
        if (c.fmt === 'cw') {
          const v = String(r[c.field] == null ? '' : r[c.field]);
          const cls = (v === 'Sí' || v === 'Si') ? 'cw-yes' : 'cw-no';
          return `<td><span class="cw-pill ${cls}">${esc(v || '—')}</span></td>`;
        }
        const f = fmt.pick(c.fmt);
        const isNum = isNumFmt(c.fmt);
        const cell = f(r[c.field]);
        return `<td${isNum ? ' class="num"' : ''}>${esc(cell)}</td>`;
      }).join('') + '</tr>';
    }).join('');
    el.innerHTML = toolbarHtml + wrapTable(`<table class="dtable"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`);
  }

  // Filtro client-side (ej. por account) para las tablas de detalle del drawer: el
  // input setea data-filter-value en el dtable destino, lo re-renderiza desde cache
  // (renderDtable aplica el filtro) y refleja el conteo filtrado en el header .count.
  function bindDtableFilters() {
    document.querySelectorAll('[data-dtable-filter]').forEach(inp => {
      inp.addEventListener('input', () => {
        const chartKey = inp.dataset.dtableFilter;
        const scope = inp.closest('.kpi-drawer__panel-content') || document;
        const el = scope.querySelector(`[data-chart="${chartKey}"][data-bind="dtable"]`);
        if (!el) return;
        el.dataset.filterValue = inp.value;
        const rows = lastFetchedRows.get(compKeyFor(el.dataset.chart, readOverridesFor(el))) || [];
        renderBinding(el, rows);
        const cols = (el.dataset.cols || '').split(',').map(s => s.split('|')[0]);
        const fc = (el.dataset.filterCol != null && el.dataset.filterCol !== '') ? +el.dataset.filterCol : null;
        const q = inp.value.trim().toLowerCase();
        const n = (q && fc != null && cols[fc])
          ? rows.filter(r => String(r[cols[fc]] == null ? '' : r[cols[fc]]).toLowerCase().includes(q)).length
          : rows.length;
        scope.querySelectorAll(`.count[data-chart="${chartKey}"]`).forEach(c => { c.textContent = String(n); });
      });
    });
  }

  /* ---------- filter-select (dropdown que filtra un donut + su detalle por un campo) ----------
     El <select> se hidrata con una lista (rows: value, label — configurable con
     data-opt-value / data-opt-label). Al elegir un valor, setea data-override-<field>
     (field = data-filter-field, ej. recruiter / account) en los charts target (donut +
     count + legend) y en el panel de detalle, y refetchea el donut. data-target-chart y
     data-target-panel indican a quién filtrar. */
  function renderFilterSelect(el, rows) {
    const current = el.dataset.current || '';
    const allLabel = el.dataset.allLabel || 'Todos';
    const valCol = el.dataset.optValue || 'value';
    const labCol = el.dataset.optLabel || 'label';
    const opts = [`<option value="">${esc(allLabel)}</option>`].concat(
      (rows || [])
        .filter(r => r && r[valCol] != null && String(r[valCol]).trim() !== '')
        .map(r => {
          const val = String(r[valCol]);
          const name = String(r[labCol] != null && String(r[labCol]).trim() !== '' ? r[labCol] : r[valCol]);
          return `<option value="${esc(val)}"${val === current ? ' selected' : ''}>${esc(name)}</option>`;
        })
    ).join('');
    el.innerHTML = opts;
    el.value = current;
    if (!el._filterBound) {
      el._filterBound = true;
      el.addEventListener('change', () => applyFilter(el, el.value || ''));
    }
  }

  /* Variante "buscable" (combobox propio): el host es un <div>; renderiza un <input> +
     un menú <ul> que se abre al hacer foco y filtra por coincidencia (substring) a
     medida que se escribe. Click o teclado (↑/↓/Enter) para elegir. Solo válida cuando
     value === label (ej. account). */
  function renderFilterSearch(el, rows) {
    const valCol = el.dataset.optValue || 'value';
    const labCol = el.dataset.optLabel || 'label';
    const ph = el.dataset.placeholder || 'Buscar…';
    const current = el.dataset.current || '';
    el._fsOptions = (rows || [])
      .filter(r => r && r[valCol] != null && String(r[valCol]).trim() !== '')
      .map(r => {
        const value = String(r[valCol]);
        const label = String(r[labCol] != null && String(r[labCol]).trim() !== '' ? r[labCol] : r[valCol]);
        return { value, label };
      });
    el.innerHTML =
      `<input class="filter-input" type="text" placeholder="${esc(ph)}" value="${esc(current)}" autocomplete="off" aria-label="${esc(ph)}">` +
      `<button type="button" class="filter-clear" title="Limpiar" aria-label="Limpiar">×</button>` +
      `<ul class="filter-menu" hidden></ul>`;
    if (!el._searchBound) {
      el._searchBound = true;
      el.addEventListener('focusin', (ev) => { if (ev.target.matches('input.filter-input')) openFilterMenu(el); });
      el.addEventListener('input', (ev) => { if (ev.target.matches('input.filter-input')) openFilterMenu(el); });
      el.addEventListener('keydown', (ev) => {
        if (!ev.target.matches('input.filter-input')) return;
        const m = el.querySelector('.filter-menu');
        if (ev.key === 'Escape') { if (m) m.hidden = true; return; }
        const items = (m && !m.hidden) ? [...m.querySelectorAll('li[data-val]')] : [];
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
          ev.preventDefault();
          if (!items.length) { openFilterMenu(el); return; }
          let idx = items.findIndex(li => li.classList.contains('is-active'));
          idx = ev.key === 'ArrowDown' ? Math.min(items.length - 1, idx + 1) : Math.max(0, idx - 1);
          items.forEach(li => li.classList.remove('is-active'));
          if (items[idx]) { items[idx].classList.add('is-active'); items[idx].scrollIntoView({ block: 'nearest' }); }
          return;
        }
        if (ev.key === 'Enter') {
          ev.preventDefault();
          const pick = items.find(li => li.classList.contains('is-active')) || items[0];
          if (pick) selectFilterOption(el, pick.dataset.val, pick.dataset.label);
          else { applyFilter(el, ev.target.value.trim()); if (m) m.hidden = true; }
        }
      });
      el.addEventListener('mousedown', (ev) => {
        const li = ev.target.closest('.filter-menu li[data-val]');
        if (li) { ev.preventDefault(); selectFilterOption(el, li.dataset.val, li.dataset.label); return; }
        if (ev.target.closest('.filter-clear')) {
          ev.preventDefault();
          const inp = el.querySelector('input.filter-input');
          if (inp) inp.value = '';
          applyFilter(el, '');
          const m = el.querySelector('.filter-menu'); if (m) m.hidden = true;
        }
      });
      el.addEventListener('focusout', () => {
        setTimeout(() => {
          if (!el.contains(document.activeElement)) {
            const m = el.querySelector('.filter-menu'); if (m) m.hidden = true;
          }
        }, 120);
      });
    }
  }

  function openFilterMenu(el) {
    const inp = el.querySelector('input.filter-input');
    const m = el.querySelector('.filter-menu');
    if (!inp || !m) return;
    const q = (inp.value || '').trim().toLowerCase();
    const opts = (el._fsOptions || []).filter(o => !q || o.label.toLowerCase().includes(q)).slice(0, 80);
    m.innerHTML = opts.length
      ? opts.map(o => `<li data-val="${esc(o.value)}" data-label="${esc(o.label)}">${esc(o.label)}</li>`).join('')
      : `<li class="filter-menu__empty" aria-disabled="true">Sin resultados</li>`;
    m.hidden = false;
  }

  function selectFilterOption(el, value, label) {
    const inp = el.querySelector('input.filter-input');
    if (inp) inp.value = (label != null ? label : value);
    const m = el.querySelector('.filter-menu'); if (m) m.hidden = true;
    applyFilter(el, value);
  }

  async function applyFilter(el, value) {
    value = value || '';
    el.dataset.current = value;
    const targetChart = el.dataset.targetChart;
    const panelKey = el.dataset.targetPanel;
    const field = (el.dataset.filterField || 'recruiter').trim();
    const attr = 'data-override-' + field;
    if (!targetChart) return;
    const card = el.closest('.card') || document;
    // 1) Setear/limpiar el override en los elementos del donut (svg, leyenda, count).
    const cardEls = [...card.querySelectorAll(`[data-chart="${targetChart}"]`)];
    cardEls.forEach(t => { if (value) t.setAttribute(attr, value); else t.removeAttribute(attr); });
    // 2) Propagar al panel de detalle (drawer) para que la lista quede filtrada al abrir.
    if (panelKey) {
      document.querySelectorAll(`[data-kpi-detail-panel="${panelKey}"] [data-chart]`).forEach(t => {
        if (value) t.setAttribute(attr, value); else t.removeAttribute(attr);
      });
    }
    // 3) Refetchear el donut con el override y re-renderizar sus elementos.
    if (!cardEls.length) return;
    const overrides = readOverridesFor(cardEls[0]);
    try {
      const r = await fetchChart(targetChart, overrides);
      lastFetchedRows.set(compKeyFor(targetChart, overrides), r.rows || []);
      cardEls.forEach(t => renderBinding(t, r.rows || []));
    } catch (e) { console.error('filter-select', field, targetChart, e); }
  }

  /* ---------- cohort by contractor (pivot long → wide month-by-month table) ---------- */
  function renderCohort(el, rows) {
    const metric = (el.dataset.metric || 'client_payment').trim();
    const emptyText = el.dataset.emptyText || 'No data';
    if (!rows || !rows.length) {
      el.innerHTML = `<div class="muted" style="padding:18px;text-align:center">${esc(emptyText)}</div>`;
      return;
    }

    // Collect unique months sorted ascending.
    const monthSet = new Set();
    rows.forEach(r => { if (r.mes) monthSet.add(r.mes); });
    const months = [...monthSet].sort();

    // Group rows by (candidate_id + '|' + account_id).
    const groups = new Map();
    rows.forEach(r => {
      const key = `${r.candidate_id || ''}|${r.account_id || ''}`;
      let g = groups.get(key);
      if (!g) {
        g = {
          key,
          candidate_name: r.candidate_name || '—',
          client_name: r.client_name || '—',
          first_mes: r.first_mes || r.mes,
          last_mes: r.last_mes || r.mes,
          churn_month: r.churn_month || null,
          is_buyout: !!r.is_buyout,
          status: r.status || 'Active',
          byMonth: {},
        };
        groups.set(key, g);
      }
      g.byMonth[r.mes] = Number(r[metric] || 0);
      // keep latest seen values
      if (r.first_mes) g.first_mes = r.first_mes;
      if (r.last_mes) g.last_mes = r.last_mes;
      if (r.churn_month) g.churn_month = r.churn_month;
      if (r.is_buyout != null) g.is_buyout = !!r.is_buyout;
      if (r.status) g.status = r.status;
    });

    // Pull bajas counts from the monthly churn chart (`am_line_candidate_churn`
    // → dataset candidate_churn_history). That dataset already filters
    // o.opp_model = 'Staffing' and its `bajas` column is bajas_real + bajas_buyout,
    // so the cohort header lines up with the Staffing chart instead of the
    // rolling 3/6m window metric, which was a different denominator.
    const monthMeta = {};
    const churnRows = lastFetchedRows.get('am_line_candidate_churn') || [];
    churnRows.forEach(cr => {
      // The chart's `mes` is 'YYYY-MM-DD' (first of month). Normalize to YYYY-MM.
      const mm = String(cr.mes || '').slice(0, 7);
      if (!mm) return;
      monthMeta[mm] = {
        bajas_real: Number(cr.bajas_real || 0),
        buyouts: Number(cr.bajas_buyout || 0),
      };
    });

    let groupArr = [...groups.values()].sort((a, b) => {
      const fa = a.first_mes || '';
      const fb = b.first_mes || '';
      if (fa !== fb) return fa.localeCompare(fb);
      return a.candidate_name.localeCompare(b.candidate_name);
    });

    // Populate filter <select>s (status uses fixed values from HTML; account &
    // month come from data, only filled once per card) and apply current filters.
    const card = el.closest('.cohort-card');
    let statusFilter = '', accountFilter = '', monthFilter = '';
    if (card) {
      // Account options → datalist suggestions (input is free-text searchable).
      const accountList = card.querySelector('#cohort-account-options')
        || document.getElementById('cohort-account-options');
      if (accountList && !accountList.childElementCount) {
        const clients = [...new Set(groupArr.map(g => g.client_name).filter(Boolean))].sort();
        clients.forEach(c => {
          const opt = document.createElement('option');
          opt.value = c;
          accountList.appendChild(opt);
        });
      }
      // Month options: from `months` array (most recent first)
      const monthSel = card.querySelector('[data-cohort-filter="month"]');
      if (monthSel && monthSel.options.length <= 1) {
        const monthShortFill = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
        [...months].reverse().forEach(m => {
          const opt = document.createElement('option');
          opt.value = m;
          const mt = String(m).match(/^(\d{4})-(\d{2})/);
          opt.textContent = mt ? `${monthShortFill[+mt[2]-1] || mt[2]} ${mt[1]}` : m;
          monthSel.appendChild(opt);
        });
      }
      statusFilter = (card.querySelector('[data-cohort-filter="status"]')?.value || '').trim();
      accountFilter = (card.querySelector('[data-cohort-filter="account"]')?.value || '').trim();
      monthFilter = (card.querySelector('[data-cohort-filter="month"]')?.value || '').trim();
    }

    if (statusFilter)  groupArr = groupArr.filter(g => g.status === statusFilter);
    if (accountFilter) {
      const needle = accountFilter.toLowerCase();
      groupArr = groupArr.filter(g => (g.client_name || '').toLowerCase().includes(needle));
    }
    // Month filter: collapse the visible columns to just that month and keep
    // only contractors that had activity in it (otherwise the row is empty).
    let visibleMonths = months;
    if (monthFilter) {
      visibleMonths = months.includes(monthFilter) ? [monthFilter] : [];
      groupArr = groupArr.filter(g => g.byMonth[monthFilter] != null);
    }

    if (!groupArr.length) {
      el.innerHTML = `<div class="muted" style="padding:18px;text-align:center">Sin contractors que coincidan con los filtros.</div>`;
      return;
    }

    // Color rule: contractors still active in the latest month → dark purple chips,
    // churned contractors → light purple chips. (Drops the previous volume-based logic.)

    // Month label: "MMM 'YY"
    const monthShort = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const monthLongMap = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
    const fmtMonth = (ym) => {
      const m = String(ym || '').match(/^(\d{4})-(\d{2})/);
      if (!m) return ym || '';
      return `${monthShort[+m[2]-1] || m[2]} '${m[1].slice(2)}`;
    };
    const fmtMonthLong = (ym) => {
      const m = String(ym || '').match(/^(\d{4})-(\d{2})/);
      if (!m) return ym || '';
      return `${monthLongMap[+m[2]-1] || m[2]} ${m[1]}`;
    };
    const fmtMoney = (v) => {
      if (v == null || v === 0) return '—';
      const k = v / 1000;
      return `$${k >= 10 ? k.toFixed(1) : k.toFixed(1)}k`;
    };
    const fmtMoneyTotal = (v) => {
      if (v == null || v === 0) return '$0';
      return fmtMoney(v);
    };

    // Single-month view: ranked list/leaderboard (no table).
    if (visibleMonths.length === 1) {
      const m = visibleMonths[0];
      const ranked = groupArr
        .map(g => ({ g, v: g.byMonth[m] || 0 }))
        .filter(x => x.v > 0)
        .sort((a, b) => b.v - a.v);
      const total = ranked.reduce((acc, x) => acc + x.v, 0);
      const count = ranked.length;
      // Bajas counts vienen del backend con la misma fórmula que la gráfica
      // candidate_churn_window_history (cohort móvil de 3 meses terminando en m).
      const meta = monthMeta[m] || { bajas_real: 0, buyouts: 0 };
      const realChurnCount = meta.bajas_real;
      const buyoutCount = meta.buyouts;

      const items = ranked.map((x, i) => {
        const g = x.g;
        // "Baja de este mes" = end_d cae en `m`. Distinguimos buyout vs real
        // con la misma lógica que candidate_churn_window_history.
        const churnedThisMonth = g.churn_month && g.churn_month === m;
        let chipCls = 'cohort-rank__chip cohort-rank__chip--active';
        let statusDot = 'cohort-rank__dot--active';
        let statusLabel = `desde ${esc(fmtMonth(g.first_mes))}`;
        if (churnedThisMonth) {
          if (g.is_buyout) {
            chipCls = 'cohort-rank__chip cohort-rank__chip--buyout';
            statusDot = 'cohort-rank__dot--buyout';
            statusLabel = `Buyout ${esc(fmtMonth(g.churn_month))}`;
          } else {
            chipCls = 'cohort-rank__chip cohort-rank__chip--churned';
            statusDot = 'cohort-rank__dot--churned';
            statusLabel = `Baja ${esc(fmtMonth(g.churn_month))}`;
          }
        }
        return `<li class="cohort-rank__row">
          <span class="cohort-rank__num">${i + 1}</span>
          <div class="cohort-rank__info">
            <div class="cohort-rank__name">${esc(g.candidate_name)}</div>
            <div class="cohort-rank__meta">
              <span class="cohort-rank__dot ${statusDot}"></span>
              <span>${esc(g.client_name)}</span>
              <span class="cohort-rank__sep">·</span>
              <span class="cohort-rank__status">${statusLabel}</span>
            </div>
          </div>
          <span class="${chipCls}">${esc(fmtMoney(x.v))}</span>
        </li>`;
      }).join('');

      const headHtml = `<header class="cohort-single__head">
        <div class="cohort-single__title">
          <span class="cohort-single__eyebrow">Snapshot del mes</span>
          <h4 class="cohort-single__month">${esc(fmtMonthLong(m))}</h4>
        </div>
        <div class="cohort-single__stats">
          <div class="cohort-single__stat">
            <span class="cohort-single__stat-label">Total</span>
            <span class="cohort-single__stat-value">${esc(fmtMoneyTotal(total))}</span>
          </div>
          <div class="cohort-single__stat">
            <span class="cohort-single__stat-label">Contractors</span>
            <span class="cohort-single__stat-value">${count}</span>
          </div>
          <div class="cohort-single__stat">
            <span class="cohort-single__stat-label">Bajas reales</span>
            <span class="cohort-single__stat-value">${realChurnCount}</span>
          </div>
          <div class="cohort-single__stat">
            <span class="cohort-single__stat-label">Buyouts</span>
            <span class="cohort-single__stat-value">${buyoutCount}</span>
          </div>
        </div>
      </header>`;

      const bodyHtml = count
        ? `<ol class="cohort-rank">${items}</ol>`
        : `<div class="muted" style="padding:24px;text-align:center">Sin contractors con actividad en este mes.</div>`;

      el.innerHTML = `<div class="cohort-single">${headHtml}${bodyHtml}</div>`;
      return;
    }

    // Multi-month view: pivot table.
    const headCells = visibleMonths.map(m => `<th class="cohort-th-month">${esc(fmtMonth(m))}</th>`).join('');
    const head = `<thead><tr>
      <th class="cohort-th-name">Contractor</th>
      ${headCells}
      <th class="cohort-th-total">Total</th>
    </tr></thead>`;

    const colTotals = visibleMonths.map(() => 0);
    let grandTotal = 0;
    const body = groupArr.map(g => {
      let rowTotal = 0;
      const chipCls = g.status === 'Churned' ? 'cohort-td cohort-td--active' : 'cohort-td cohort-td--high';
      const cells = visibleMonths.map((m, idx) => {
        const v = g.byMonth[m];
        if (v == null) {
          return `<td class="cohort-td cohort-td--empty">—</td>`;
        }
        rowTotal += v;
        colTotals[idx] += v;
        return `<td class="${chipCls}"><span class="cohort-chip-val">${esc(fmtMoney(v))}</span></td>`;
      }).join('');
      grandTotal += rowTotal;
      // Status dot + subline match the snapshot view: verde activo / rojo baja / ámbar buyout.
      let dotCls, subline;
      if (g.status === 'Churned') {
        dotCls = 'cohort-rank__dot--churned';
        subline = `Churned ${esc(fmtMonth(g.last_mes))}`;
      } else if (g.status === 'Buyout') {
        dotCls = 'cohort-rank__dot--buyout';
        subline = `Buyout ${esc(fmtMonth(g.last_mes))}`;
      } else {
        dotCls = 'cohort-rank__dot--active';
        subline = esc(fmtMonth(g.first_mes));
      }
      return `<tr>
        <td class="cohort-td-name">
          <div class="cohort-td-name__primary">
            <span class="cohort-rank__dot ${dotCls}" style="display:inline-block;margin-right:8px;vertical-align:middle"></span>${esc(g.candidate_name)}
          </div>
          <div class="cohort-td-name__sub">${esc(g.client_name)} · ${subline}</div>
        </td>
        ${cells}
        <td class="cohort-td-total">${esc(fmtMoneyTotal(rowTotal))}</td>
      </tr>`;
    }).join('');

    const totalsCells = colTotals.map(v => `<td class="cohort-td-total cohort-td-total--col">${esc(fmtMoneyTotal(v))}</td>`).join('');
    const tfoot = `<tfoot><tr>
      <td class="cohort-td-name cohort-td-name--total">Total month</td>
      ${totalsCells}
      <td class="cohort-td-total cohort-td-total--grand">${esc(fmtMoneyTotal(grandTotal))}</td>
    </tr></tfoot>`;

    el.innerHTML = `<div class="cohort-scroll"><table class="cohort-table">${head}<tbody>${body}</tbody>${tfoot}</table></div>`;
  }

  /* ---------- grouped list (no month filter — just groups by a field, with state badges) ---------- */
  function renderGroupedList(el, rows) {
    const nameField  = el.dataset.listName  || 'candidate_name';
    const groupField = el.dataset.listGroup || 'client_name';
    const dateField  = el.dataset.listDate  || '';
    const stateField = el.dataset.listState;
    const emptyText  = el.dataset.emptyText || 'No data';

    if (!rows || !rows.length) {
      el.innerHTML = `<div class="mdetail__empty">${esc(emptyText)}</div>`;
      return;
    }

    const byGroup = {};
    rows.forEach(r => {
      const g = String(r[groupField] || '—');
      (byGroup[g] = byGroup[g] || []).push(r);
    });
    const groupNames = Object.keys(byGroup).sort((a, b) => byGroup[b].length - byGroup[a].length);

    const blocks = groupNames.map(g => {
      const cands = byGroup[g]
        .slice()
        .sort((a, b) => String(a[nameField] || '').localeCompare(String(b[nameField] || '')))
        .map(r => {
          let badge = '';
          if (stateField && r[stateField] != null && r[stateField] !== '') {
            const rule = classifyState(r[stateField]) || { cls: '', label: String(r[stateField]) };
            badge = `<span class="mdetail__cand-state mdetail__cand-state--${rule.cls}">${esc(rule.label)}</span>`;
          }
          const date = dateField ? esc(r[dateField] || '') : '';
          return `
            <div class="mdetail__cand">
              <span class="mdetail__cand-name">${esc(r[nameField] || '—')}</span>
              <span class="mdetail__cand-date">${badge}${date}</span>
            </div>
          `;
        }).join('');
      return `
        <div class="mdetail__group">
          <div class="mdetail__client">
            <span class="mdetail__client-name">${esc(g)}</span>
            <span class="mdetail__client-count">${byGroup[g].length}</span>
          </div>
          ${cands}
        </div>
      `;
    }).join('');

    el.innerHTML = `<div class="mdetail__body">${blocks}</div>`;
  }

  /* ---------- selected month state (shared across detail panels + chart + Mes filter pill) ---------- */
  const monthState = { selected: null, listeners: [] };
  function setSelectedMonth(m) {
    if (!m || m === monthState.selected) return;
    monthState.selected = m;
    // Sync the Mes filter pill UI (so the user sees the current month selection)
    const mesInput = document.querySelector('[data-filter-input="mes"]');
    if (mesInput && mesInput.value !== m) {
      mesInput.value = m;
      const wrap = mesInput.closest('[data-filter-key]');
      const display = (mesInput.tagName === 'SELECT' && mesInput.options[mesInput.selectedIndex])
        ? mesInput.options[mesInput.selectedIndex].text
        : m;
      setFilterSlot(wrap, 'mes', m, display);
      state.mes = m;  // keep state in sync too
    }
    monthState.listeners.forEach(fn => { try { fn(m); } catch (e) { console.error(e); } });
    // Refetch all month-detail panels with the new month
    refetchMonthDetails(m);
    // Refetch [data-month-aware] elements (e.g. KPI drawer lists) with corte = end of month
    refetchMonthAwareElements(document, m);
  }
  function onMonthChange(fn) { monthState.listeners.push(fn); }

  /* ---------- month-aware refetch (cohort = end-of-month snapshot) ---------- */
  function endOfMonth(yyyyMm) {
    const m = String(yyyyMm || '').match(/^(\d{4})-(\d{2})/);
    if (!m) return null;
    const y = parseInt(m[1], 10), mo = parseInt(m[2], 10);
    // Day-0 of next month = last day of this month
    const d = new Date(Date.UTC(y, mo, 0));
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  }
  async function refetchMonthAwareElements(scope, month) {
    if (!scope) return;
    // En modo-corte el snapshot se evalúa al DÍA DEL CORTE (no a fin del mes
    // seleccionado), para que los detalles sigan los últimos 30d como las cards.
    let corte;
    if (isCorteMode()) {
      corte = state.corte;
    } else {
      const m = month || monthState.selected;
      if (!m) return;
      corte = endOfMonth(m);
    }
    if (!corte) return;
    const els = scope.querySelectorAll('[data-month-aware]');
    // Group by (chartKey + overrides) so we make one fetch per dataset/filter combo.
    const groups = new Map();
    els.forEach(el => {
      const chartKey = el.dataset.chart;
      if (!chartKey) return;
      // Skip elements that are currently locked to a por-ventana selection;
      // their refetch happens via setDrawerWindow() instead.
      if (el.dataset.activeWindow) return;
      const overrides = readOverridesFor(el);
      overrides.corte = corte;
      const compKey = compKeyFor(chartKey, overrides);
      if (!groups.has(compKey)) groups.set(compKey, { chartKey, overrides, els: [] });
      groups.get(compKey).els.push(el);
    });
    await Promise.all([...groups.values()].map(async ({ chartKey, overrides, els }) => {
      try {
        const r = await fetchChart(chartKey, overrides);
        const rows = r.rows || [];
        els.forEach(el => renderBinding(el, rows));
      } catch (e) {
        console.error(`month-aware fetch ${chartKey}`, e);
        els.forEach(el => renderBinding(el, []));
      }
    }));
  }

  // Exposed so inline drill-to-drawer handlers (AE tab line charts) can
  // await the month-aware refetch before opening the drawer — prevents
  // showing stale data during the swap.
  window.__dashRefetchMonthAware = refetchMonthAwareElements;
  window.__dashMonthState = monthState;

  /* ---------- drawer · per-window detail filter ---------- */
  const WINDOW_LABELS = {
    week: 'Last week',
    last_week: 'Last week',
    month: 'Last month',
    last_month: 'Last month',
    mtd: 'MTD',
    wtd: 'WTD',
    '30d': 'Last 30d',
    '7d': 'Last 7d',
    ytd: 'YTD',
  };

  function windowLabel(key) {
    return WINDOW_LABELS[String(key || '').toLowerCase()] || String(key || '').toUpperCase();
  }

  // For drawers whose detail dataset is a point-in-time snapshot (e.g. active
  // headcount), use the end-of-window date as `corte` instead of the rolling
  // `window` filter. Returns YYYY-MM-DD.
  function endOfWindowYmd(windowKey) {
    const today = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    const k = String(windowKey || '').toLowerCase();
    if (k === 'week' || k === 'last_week' || k === 'last-week') {
      const day = today.getDay(); // 0=Sunday
      const offset = day === 0 ? 7 : day;
      const prevSun = new Date(today);
      prevSun.setDate(today.getDate() - offset);
      return ymd(prevSun);
    }
    if (k === 'month' || k === 'last_month' || k === 'last-month') {
      const firstThis = new Date(today.getFullYear(), today.getMonth(), 1);
      firstThis.setDate(0); // last day of previous month
      return ymd(firstThis);
    }
    // mtd, 30d, 7d, ytd → today
    return ymd(today);
  }

  async function setDrawerWindow(target, windowKey) {
    // Highlight the active stat in the same group
    document.querySelectorAll(`[data-drawer-window-group="${target}"] [data-drawer-window]`).forEach(btn => {
      btn.classList.toggle('is-active', btn.dataset.drawerWindow === windowKey);
    });
    // Toggle chips
    const monthChip = document.querySelector(`[data-drawer-window-target="${target}"][data-kpi-drawer-month-chip]`);
    const winChip = document.querySelector(`[data-drawer-window-chip="${target}"]`);
    if (monthChip) monthChip.hidden = true;
    if (winChip) { winChip.hidden = false; winChip.textContent = windowLabel(windowKey); }
    // Update hero label + bottom-total label so the drawer header reflects the window
    const heroLabel = document.querySelector(`[data-drawer-window-label="${target}"]`);
    if (heroLabel) {
      const baseLabel = heroLabel.dataset.drawerBaseLabel || heroLabel.textContent.replace(/\s*·\s*\S+$/, '');
      heroLabel.dataset.drawerBaseLabel = baseLabel;
      heroLabel.textContent = `${baseLabel} · ${windowLabel(windowKey)}`;
    }
    const totalLabel = document.querySelector(`[data-drawer-window-total-label="${target}"]`);
    if (totalLabel) {
      const baseLabel = totalLabel.dataset.drawerBaseLabel || totalLabel.textContent.replace(/\s*·\s*\S+$/, '');
      totalLabel.dataset.drawerBaseLabel = baseLabel;
      totalLabel.textContent = `${baseLabel} · ${windowLabel(windowKey)}`;
    }

    // Refetch every [data-month-aware] element bound to this target.
    // Two modes:
    //   default → send `event_window` filter (rolling event-in-window datasets).
    //     Uses a NEW param name (not `window`) so the global state.window='30d'
    //     does not accidentally trigger event-mode on snapshot datasets.
    //   snapshot → send `corte = endOfWindow(windowKey)` (point-in-time datasets)
    const els = document.querySelectorAll(`[data-month-aware][data-drawer-window-target="${target}"]`);
    if (!els.length) return;
    const groups = new Map();
    els.forEach(el => {
      el.dataset.activeWindow = windowKey;
      const chartKey = el.dataset.chart;
      if (!chartKey) return;
      const overrides = readOverridesFor(el);
      const useSnapshot = el.dataset.windowMode === 'snapshot';
      if (useSnapshot) {
        overrides.corte = endOfWindowYmd(windowKey);
        delete overrides.event_window;
      } else {
        overrides.event_window = windowKey;
        delete overrides.corte;
      }
      const compKey = compKeyFor(chartKey, overrides);
      if (!groups.has(compKey)) groups.set(compKey, { chartKey, overrides, els: [] });
      groups.get(compKey).els.push(el);
    });
    await Promise.all([...groups.values()].map(async ({ chartKey, overrides, els }) => {
      try {
        const r = await fetchChart(chartKey, overrides);
        const rows = r.rows || [];
        els.forEach(el => renderBinding(el, rows));
      } catch (e) {
        console.error(`window fetch ${chartKey}`, e);
        els.forEach(el => renderBinding(el, []));
      }
    }));
  }

  function clearDrawerWindow(target) {
    document.querySelectorAll(`[data-drawer-window-group="${target}"] [data-drawer-window]`).forEach(btn => {
      btn.classList.remove('is-active');
    });
    const monthChip = document.querySelector(`[data-drawer-window-target="${target}"][data-kpi-drawer-month-chip]`);
    const winChip = document.querySelector(`[data-drawer-window-chip="${target}"]`);
    if (monthChip) monthChip.hidden = false;
    if (winChip) { winChip.hidden = true; winChip.textContent = ''; }
    document.querySelectorAll(`[data-month-aware][data-drawer-window-target="${target}"]`).forEach(el => {
      delete el.dataset.activeWindow;
    });
    // Restore month-aware behavior using the currently selected month
    refetchMonthAwareElements(document, monthState.selected);
  }

  function bindCohortMetricToggle() {
    const rerender = (card) => {
      card.querySelectorAll('[data-bind="cohort"]').forEach(el => {
        const chartKey = el.dataset.chart;
        if (!chartKey) return;
        const compKey = compKeyFor(chartKey, readOverridesFor(el));
        renderCohort(el, lastFetchedRows.get(compKey) || []);
      });
    };

    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-cohort-metric]');
      if (btn) {
        const card = btn.closest('.cohort-card');
        if (!card) return;
        const metric = btn.dataset.cohortMetric;
        if (!metric) return;
        e.preventDefault();
        card.querySelectorAll('[data-cohort-metric]').forEach(b => {
          b.classList.toggle('is-active', b === btn);
        });
        card.querySelectorAll('[data-bind="cohort"]').forEach(el => { el.dataset.metric = metric; });
        rerender(card);
        return;
      }
      const clearBtn = e.target.closest('[data-cohort-filter-clear]');
      if (clearBtn) {
        const card = clearBtn.closest('.cohort-card');
        if (!card) return;
        e.preventDefault();
        card.querySelectorAll('[data-cohort-filter]').forEach(sel => { sel.value = ''; });
        rerender(card);
      }
    });

    const onFilterEvent = (e) => {
      const sel = e.target.closest('[data-cohort-filter]');
      if (!sel) return;
      const card = sel.closest('.cohort-card');
      if (!card) return;
      rerender(card);
    };
    document.addEventListener('change', onFilterEvent);
    document.addEventListener('input', onFilterEvent);
  }

  /* ---------- Cohort by client (per-client MRR summary, month-switchable) ---------- */
  function bindCohortByClient() {
    const card = document.querySelector('[data-cohort-client-card]');
    if (!card) return;
    const tableEl = card.querySelector('[data-cohort-client-table]');
    if (!tableEl) return;
    const chartKey = tableEl.dataset.cohortChart;
    const searchInput = card.querySelector('[data-cohort-client-search]');
    const monthSel = card.querySelector('[data-cohort-client-month]');
    const clearBtn = card.querySelector('[data-cohort-client-clear]');
    const datalist = card.querySelector('#cohort-client-options');
    const cols = (tableEl.dataset.cols || '').split(',').map(s => {
      const p = s.trim().split('|');
      return { field: p[0] || '', label: p[1] || p[0] || '', fmt: p[2] || 'raw' };
    }).filter(c => c.field);
    const emptyText = tableEl.dataset.emptyText || 'Sin datos';
    let rows = [];

    // Month options: últimos 12 meses, mes actual seleccionado por defecto.
    if (monthSel && monthSel.options.length === 0) {
      const ms = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
      [...lastNMonths(12)].reverse().forEach((m, i) => {
        const o = document.createElement('option');
        o.value = m;
        const mt = m.match(/^(\d{4})-(\d{2})/);
        o.textContent = mt ? `${ms[+mt[2] - 1]} ${mt[1]}` : m;
        if (i === 0) o.selected = true;
        monthSel.appendChild(o);
      });
    }

    function renderTable(view) {
      if (!cols.length) { tableEl.innerHTML = ''; return; }
      if (!view.length) {
        tableEl.innerHTML = `<div class="muted" style="padding:18px;text-align:center">${esc(emptyText)}</div>`;
        return;
      }
      const head = '<thead><tr>' + cols.map((c, i) => i === 0
        ? `<th class="cohort-th-name">${esc(c.label)}</th>`
        : `<th>${esc(c.label)}</th>`).join('') + '</tr></thead>';
      const body = '<tbody>' + view.map(r => '<tr>' + cols.map((c, i) => {
        const f = fmt.pick(c.fmt);
        return i === 0
          ? `<td class="cohort-td-name"><span class="cohort-td-name__primary">${esc(f(r[c.field]))}</span></td>`
          : `<td>${esc(f(r[c.field]))}</td>`;
      }).join('') + '</tr>').join('') + '</tbody>';

      // Footer · totales de lo visible. Margin = ΣMRR/ΣGMRR (no es un promedio simple);
      // Weight = Σ weight (100% sin filtrar, menos si hay búsqueda).
      const totGmrr = view.reduce((a, r) => a + (+r.gmrr || 0), 0);
      const totMrr  = view.reduce((a, r) => a + (+r.mrr  || 0), 0);
      const footerVal = (c) => {
        if (c.field === 'margin_pct') return totGmrr ? (100 * totMrr / totGmrr) : 0;
        return view.reduce((a, r) => a + (+r[c.field] || 0), 0);
      };
      const tfoot = '<tfoot><tr>' + cols.map((c, i) => {
        if (i === 0) return `<td class="cohort-td-name cohort-td-name--total">Total month</td>`;
        // En el total, los montos van abreviados ($259.1K) aunque el cuerpo use el número completo.
        const footFmt = c.fmt === 'currency' ? 'currency-k' : c.fmt;
        return `<td class="cohort-td-total cohort-td-total--col">${esc(fmt.pick(footFmt)(footerVal(c)))}</td>`;
      }).join('') + '</tr></tfoot>';

      tableEl.innerHTML = `<div class="cohort-scroll"><table class="cohort-table">${head}${body}${tfoot}</table></div>`;
    }

    function applyFilter() {
      const needle = (searchInput && searchInput.value || '').trim().toLowerCase();
      const view = needle
        ? rows.filter(r => String(r.client_name || '').toLowerCase().includes(needle))
        : rows;
      renderTable(view);
    }

    function fillDatalist() {
      if (!datalist) return;
      datalist.innerHTML = '';
      [...new Set(rows.map(r => r.client_name).filter(Boolean))].sort().forEach(c => {
        const o = document.createElement('option');
        o.value = c;
        datalist.appendChild(o);
      });
    }

    let reqId = 0;
    async function load() {
      const month = (monthSel && monthSel.value) || '';
      const overrides = month ? { corte: endOfMonth(month) } : {};
      const myReq = ++reqId;
      tableEl.innerHTML = `<div class="muted" style="padding:18px;text-align:center">Cargando…</div>`;
      try {
        const res = await fetchChart(chartKey, overrides);
        if (myReq !== reqId) return;  // superseded by a newer month change
        rows = res.rows || [];
      } catch (e) {
        console.error('cohort-by-client load', e);
        if (myReq !== reqId) return;
        rows = [];
      }
      fillDatalist();
      applyFilter();
    }

    if (searchInput) searchInput.addEventListener('input', applyFilter);
    if (monthSel) monthSel.addEventListener('change', load);
    if (clearBtn) clearBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (searchInput) searchInput.value = '';
      if (monthSel && monthSel.options.length) monthSel.selectedIndex = 0;  // volver al mes actual
      load();
    });

    load();
  }

  /* ---------- CLTV model toggle (Staffing | Recruiting) ---------- */
  // Aplica a TODAS las gráficas de CLTV: cambia el override `model`, intercambia
  // los atributos de render por modelo (data-<attr>-staffing / -recruiting) y los
  // textos de títulos, y refetchea + re-renderiza.
  function bindCltvModelToggle() {
    const toggle = document.querySelector('[data-cltv-model-toggle]');
    if (!toggle) return;
    const CHART_SEL = '[data-chart="mk_rank_cltv_by_channel"], [data-chart="mk_table_cltv_by_channel_detail"]';

    // Copia los data-*-<Model> al data-* base (ej. data-cols-recruiting → data-cols).
    function applyVariantAttrs(el, model) {
      Object.keys(el.dataset).forEach(key => {
        if (key.length > model.length && key.endsWith(model)) {
          const base = key.slice(0, -model.length);
          el.dataset[base.charAt(0).toLowerCase() + base.slice(1)] = el.dataset[key];
        }
      });
    }

    async function setModel(model) {
      toggle.querySelectorAll('[data-cltv-model]').forEach(b =>
        b.classList.toggle('is-active', b.dataset.cltvModel === model));
      // Textos por modelo (títulos / subtítulos de las cards).
      document.querySelectorAll('[data-cltv-text]').forEach(el => {
        const t = el.dataset['text' + model];
        if (t != null) el.textContent = t;
      });
      // Charts: aplica variantes de render + setea el override de modelo.
      const charts = [...document.querySelectorAll(CHART_SEL)];
      charts.forEach(el => {
        applyVariantAttrs(el, model);
        el.dataset.overrideModel = model;
      });
      // Refetch agrupado por (chartKey + overrides) y re-render.
      const groups = new Map();
      charts.forEach(el => {
        const ck = el.dataset.chart;
        const ov = readOverridesFor(el);
        const compKey = compKeyFor(ck, ov);
        if (!groups.has(compKey)) groups.set(compKey, { chartKey: ck, overrides: ov, els: [] });
        groups.get(compKey).els.push(el);
      });
      for (const { chartKey, overrides, els } of groups.values()) {
        try {
          const r = await fetchChart(chartKey, overrides);
          els.forEach(el => renderBinding(el, r.rows || []));
        } catch (e) { console.error('cltv model toggle', chartKey, e); }
      }
    }

    toggle.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-cltv-model]');
      if (!btn) return;
      e.preventDefault();
      setModel(btn.dataset.cltvModel);
    });
  }

  function bindFunnelDetailToggles() {
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-funnel-detail-toggle]');
      if (!btn) return;
      const key = btn.dataset.funnelDetailToggle;
      if (!key) return;
      const section = btn.closest('section');
      if (!section) return;
      const panel = section.querySelector(`[data-funnel-detail-panel="${key}"]`);
      if (!panel) return;
      e.preventDefault();

      const wasOpen = !panel.hidden;
      const wasActive = btn.classList.contains('is-active');
      // Same active card → toggle close. Otherwise activate this card and (re)open.
      const shouldClose = wasOpen && wasActive;

      section.querySelectorAll(`[data-funnel-detail-toggle="${key}"]`).forEach(b => {
        b.classList.toggle('is-active', !shouldClose && b === btn);
      });
      panel.hidden = shouldClose;
      if (shouldClose) return;

      const filterField = btn.dataset.detailFilterField || '';
      const filterValue = btn.dataset.detailFilterValue || '';

      requestAnimationFrame(() => {
        panel.querySelectorAll('[data-chart]').forEach(el => {
          const chartKey = el.dataset.chart;
          if (!chartKey) return;
          const compKey = compKeyFor(chartKey, readOverridesFor(el));
          let rows = lastFetchedRows.get(compKey) || [];
          if (filterField && filterValue) {
            rows = rows.filter(r => String(r[filterField] ?? '').trim() === filterValue);
          }
          renderBinding(el, rows);
        });
      });
    });
  }

  function bindDrawerWindowControls() {
    // Por-ventana stat clicks → switch detail to that window
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-drawer-window]');
      if (!btn) return;
      const group = btn.closest('[data-drawer-window-group]');
      if (!group) return;
      const target = group.dataset.drawerWindowGroup;
      if (!target) return;
      e.preventDefault();
      setDrawerWindow(target, btn.dataset.drawerWindow);
    });
    // Month chip click → return to monthly mode
    document.addEventListener('click', (e) => {
      const chip = e.target.closest('[data-kpi-drawer-month-chip][data-drawer-window-target]');
      if (!chip || chip.hidden) return;
      // Only intercept when a window is active for that target
      const target = chip.dataset.drawerWindowTarget;
      const hasActive = !!document.querySelector(`[data-drawer-window-group="${target}"] [data-drawer-window].is-active`);
      if (!hasActive) return;
      e.preventDefault();
      clearDrawerWindow(target);
    });
  }

  function formatMonthHuman(m) {
    if (!m) return '—';
    const mt = String(m).match(/^(\d{4})-(\d{2})/);
    if (!mt) return String(m);
    const months = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
    return `${months[+mt[2] - 1] || mt[2]} ${mt[1]}`;
  }

  /* ---------- last N months helper ---------- */
  function lastNMonths(n) {
    const now = new Date();
    const out = [];
    for (let i = n - 1; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    }
    return out;
  }

  /* ---------- state classification (used by month-detail dedupe + badges) ---------- */
  const STATE_RULES = [
    { match: /Baja\s*[-–]\s*Real/i,            cls: 'baja-real',   label: 'Baja real',  prio: 5, dateField: 'endField' },
    { match: /Baja\s*[-–]\s*Buyout|Conversion/i, cls: 'baja-buyout', label: 'Buyout',    prio: 4, dateField: 'endField' },
    { match: /Baja/i,                          cls: 'baja-real',   label: 'Baja',      prio: 4, dateField: 'endField' },
    { match: /Alta/i,                          cls: 'alta',        label: 'Alta',      prio: 3, dateField: 'startField' },
    { match: /nuevo/i,                         cls: 'alta',        label: 'Nuevo',     prio: 3, dateField: 'startField' },
    { match: /upsell/i,                        cls: 'alta',        label: 'Upsell',    prio: 3, dateField: 'startField' },
    { match: /downgrade|recorte/i,             cls: 'baja-real',   label: 'Downgrade', prio: 4, dateField: 'endField' },
    { match: /retenido/i,                      cls: 'activo',      label: 'Retenido',  prio: 2, dateField: 'startField' },
    { match: /churn/i,                         cls: 'baja-real',   label: 'Churn',     prio: 5, dateField: 'endField' },
    { match: /Activo/i,                        cls: 'activo',      label: 'Activo',    prio: 1, dateField: 'startField' },
    // Sent→Hired / Interviewed→Sent specific states
    { match: /^Sí$|Hired|hired/i,              cls: 'alta',        label: 'Hired',     prio: 5, dateField: 'endField' },
    { match: /^No$|rejected/i,                 cls: 'baja-real',   label: 'Rejected',  prio: 0, dateField: 'endField' },
    { match: /interviewing|testing/i,          cls: 'baja-buyout', label: 'Interviewing', prio: 0, dateField: 'endField' },
  ];
  function classifyState(s) {
    if (s == null || s === '') return null;
    const str = String(s);
    for (const rule of STATE_RULES) {
      if (rule.match.test(str)) return rule;
    }
    return { cls: '', label: str, prio: 0, dateField: 'endField' };
  }
  // When state field exists on the schema but the row's state is null,
  // render as "Vigente" (still active in the cohort).
  const VIGENTE_RULE = { cls: 'activo', label: 'Vigente', prio: 0, dateField: 'startField' };

  /* ---------- month detail (one month at a time, grouped by client) ----------
     Data is server-filtered to the selected month (passes mes=YYYY-MM).
     Re-fetches when month changes. */
  function renderMonthDetail(el, rows, opts) {
    const nameField  = el.dataset.listName  || 'candidate_name';
    const subField   = el.dataset.listSub   || 'client_name';
    const dateField  = el.dataset.listDate  || 'start_date';
    const startField = el.dataset.listStart || 'start_d';
    const endField   = el.dataset.listEnd   || 'end_d';
    const stateField = el.dataset.listState;  // optional: when set, dedupe + show badge
    const colsSpec   = el.dataset.listCols;    // optional: when set, render a flat table (field|Label|fmt,...)
    const emptyText  = el.dataset.emptyText || 'No data';
    const month      = (opts && opts.month) || monthState.selected;

    const monthKeys = lastNMonths(12);
    const currentMonth = month || monthKeys[monthKeys.length - 1];

    // Table mode: render the same flat dtable the drawer used (e.g. Contractor ·
    // Cliente · Start · Salary · Fee · GMRR), keeping the month nav + head.
    function buildTable(entries) {
      const cols = (colsSpec || '').split(',').map(spec => {
        const parts = spec.trim().split('|');
        return { field: parts[0] || '', label: parts[1] || parts[0] || '', fmt: parts[2] || 'raw' };
      }).filter(c => c.field);
      const headCells = cols.map(c => {
        const isNum = c.fmt && c.fmt !== 'raw' && c.fmt !== 'date';
        return `<th${isNum ? ' class="num"' : ''}>${esc(c.label)}</th>`;
      }).join('');
      if (!entries.length) {
        return `<table class="dtable"><thead><tr>${headCells}</tr></thead>` +
          `<tbody><tr><td colspan="${cols.length}" class="muted" style="text-align:center;padding:18px">${esc(emptyText)}</td></tr></tbody></table>`;
      }
      const body = entries.map(r => '<tr>' + cols.map(c => {
        const f = fmt.pick(c.fmt);
        const isNum = c.fmt && c.fmt !== 'raw' && c.fmt !== 'date';
        return `<td${isNum ? ' class="num"' : ''}>${esc(f(r[c.field]))}</td>`;
      }).join('') + '</tr>').join('');
      return `<table class="dtable"><thead><tr>${headCells}</tr></thead><tbody>${body}</tbody></table>`;
    }

    function buildBody(entries) {
      if (!entries.length) {
        return `<div class="mdetail__empty">${esc(emptyText)}</div>`;
      }
      const byClient = {};
      entries.forEach(r => {
        const c = String(r[subField] || '—');
        (byClient[c] = byClient[c] || []).push(r);
      });

      // Dedupe within each client group: same `nameField` rows are merged into
      // ONE only when their states have DIFFERENT priorities (so we keep the
      // most meaningful state, e.g. "Baja Real" over "Activo al inicio").
      // If all duplicates have the same priority (e.g. two independent
      // "Close Win" events for the same client in the same month), we keep
      // ALL of them — they represent distinct events.
      if (stateField) {
        Object.keys(byClient).forEach(c => {
          const byName = {};
          byClient[c].forEach(r => {
            const k = String(r[nameField] || '');
            (byName[k] = byName[k] || []).push(r);
          });
          const final = [];
          Object.values(byName).forEach(list => {
            if (list.length === 1) { final.push(list[0]); return; }
            const rated = list.map(r => ({ row: r, prio: (classifyState(r[stateField]) || {}).prio || 0 }));
            const maxP = Math.max(...rated.map(x => x.prio));
            const allEqual = rated.every(x => x.prio === maxP);
            if (allEqual) {
              // Same-priority duplicates → keep all (independent events)
              rated.forEach(x => final.push(x.row));
            } else {
              // Different priorities → keep only the highest one
              final.push(rated.find(x => x.prio === maxP).row);
            }
          });
          byClient[c] = final;
        });
      }

      const clientNames = Object.keys(byClient).sort((a, b) => byClient[b].length - byClient[a].length);
      return clientNames.map(c => {
        const cands = byClient[c]
          .slice()
          .sort((a, b) => String(a[nameField] || '').localeCompare(String(b[nameField] || '')))
          .map(r => {
            // If schema declares a state field, always derive a rule
            // (Vigente when the row's state is null/empty)
            let rule = null;
            if (stateField) {
              rule = classifyState(r[stateField]) || VIGENTE_RULE;
            }
            // Pick the date field based on state (end for bajas, start for altas/activos),
            // falling back to the other one if the chosen field is empty.
            let date = '';
            if (rule) {
              const primary = rule.dateField === 'endField' ? endField : startField;
              const fallback = rule.dateField === 'endField' ? startField : endField;
              date = r[primary] || r[fallback] || r[dateField] || '';
            } else {
              date = r[dateField] || '';
            }
            const stateBadge = rule
              ? `<span class="mdetail__cand-state mdetail__cand-state--${rule.cls}">${esc(rule.label)}</span>`
              : '';
            return `
              <div class="mdetail__cand">
                <span class="mdetail__cand-name">${esc(r[nameField] || '—')}</span>
                <span class="mdetail__cand-date">${stateBadge}${esc(date)}</span>
              </div>
            `;
          }).join('');
        return `
          <div class="mdetail__group">
            <div class="mdetail__client">
              <span class="mdetail__client-name">${esc(c)}</span>
              <span class="mdetail__client-count">${byClient[c].length}</span>
            </div>
            ${cands}
          </div>
        `;
      }).join('');
    }

    function buildNav(currMonth) {
      if (el.dataset.noNav === 'true') return '';  // suppress nav (used when nav is shared across panels)
      // Opt-in: only show months of the current year (e.g. YTD-only details like MRR).
      let navKeys = monthKeys;
      if (el.dataset.navCurrentYear === 'true') {
        const curYear = monthKeys[monthKeys.length - 1].slice(0, 4);
        navKeys = monthKeys.filter(m => m.slice(0, 4) === curYear);
      }
      const pills = navKeys.map(m => `
        <button type="button" class="mdetail__pill ${m === currMonth ? 'is-selected' : ''}" data-mdetail-month="${esc(m)}">
          ${esc(formatMonthHuman(m))}
        </button>
      `).join('');
      return `<div class="mdetail__nav">${pills}<span class="mdetail__hint">Click a month or the chart point</span></div>`;
    }

    const entries = rows || [];
    const uniqueNames = new Set(entries.map(r => r[nameField]).filter(v => v != null)).size;
    el.innerHTML = `
      ${buildNav(currentMonth)}
      <div class="mdetail__head">
        <h4>${esc(formatMonthHuman(currentMonth))}</h4>
        <span class="meta"><strong>${entries.length}</strong> ${entries.length === 1 ? 'entry' : 'entries'} · <strong>${uniqueNames}</strong> distinct</span>
      </div>
      <div class="mdetail__body">
        ${colsSpec ? buildTable(entries) : buildBody(entries)}
      </div>
    `;
    // Wire month-pill clicks
    el.querySelectorAll('[data-mdetail-month]').forEach(btn => {
      btn.addEventListener('click', () => setSelectedMonth(btn.dataset.mdetailMonth));
    });
  }

  /* ---------- refetch all month-detail panels for a given month ---------- */
  async function refetchMonthDetails(month) {
    const els = document.querySelectorAll('[data-bind="month-detail"]');
    await Promise.all([...els].map(async (el) => {
      const chartKey = el.dataset.chart;
      if (!chartKey) return;
      try {
        // Pass both `mes` (cohort datasets) and `corte` = end-of-month
        // (point-in-time snapshot datasets like the MRR contractor details).
        // Each dataset reads only the param it understands; the other is ignored.
        const res = await fetchChart(chartKey, { mes: month, corte: endOfMonth(month) });
        renderMonthDetail(el, res.rows || [], { month });
      } catch (e) {
        console.error('month-detail fetch failed', chartKey, e);
        el.innerHTML = `<div class="mdetail__empty">Error loading data</div>`;
      }
    }));
  }

  /* ---------- flip card toggle ---------- */
  function bindFlipCards() {
    document.querySelectorAll('[data-flip-toggle]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const card = btn.closest('[data-flip-card]');
        if (card) card.classList.toggle('is-flipped');
      });
    });
  }

  /* ---------- expander toggle ---------- */
  function bindExpanders() {
    document.querySelectorAll('[data-expand-toggle]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const wrap = btn.closest('.expander');
        if (wrap) wrap.classList.toggle('is-open');
      });
    });
  }

  // Toggle de período (Semana/Mes/Q/Año) por card: setea data-override-periodo
  // en las charts del card y las refetchea.
  function bindPeriodToggles() {
    document.querySelectorAll('[data-period-toggle]').forEach(group => {
      const card = group.closest('[data-period-card]') || group.closest('.card');
      group.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-period-set]');
        if (!btn || !card) return;
        const periodo = btn.dataset.periodSet;
        group.querySelectorAll('[data-period-set]').forEach(b => {
          const active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        const els = [...card.querySelectorAll('[data-chart]')];
        els.forEach(el => { el.dataset.overridePeriodo = periodo; });
        const groups = new Map();
        els.forEach(el => {
          const ov = readOverridesFor(el);
          const ck = compKeyFor(el.dataset.chart, ov);
          if (!groups.has(ck)) groups.set(ck, { chartKey: el.dataset.chart, overrides: ov, els: [] });
          groups.get(ck).els.push(el);
        });
        for (const { chartKey, overrides, els } of groups.values()) {
          try {
            const r = await fetchChart(chartKey, overrides);
            els.forEach(el => renderBinding(el, r.rows || []));
          } catch (err) { console.error('period toggle', chartKey, err); }
        }
      });
    });
  }

  // Toggle GENERAL de período: un solo control que aplica a TODAS las cards
  // período-aware (las que tienen data-override-periodo) de su sección.
  /* ----- Selector de período específico (qué semana/mes/q/año) ----- */
  function _pad2(n) { return String(n).padStart(2, '0'); }
  function _isoD(d) { return d.getFullYear() + '-' + _pad2(d.getMonth() + 1) + '-' + _pad2(d.getDate()); }
  const _MES_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];

  // Opciones del selector según la periodicidad. value = ISO del corte (fin del
  // período, topeado a hoy); '' = más reciente (sin corte → el backend usa hoy).
  function periodSpecificOptions(periodo) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const cap = d => (d > today ? new Date(today) : d);
    const out = [];
    if (periodo === 'semana') {
      const dow = today.getDay();
      const monThis = new Date(today); monThis.setDate(today.getDate() + (dow === 0 ? -6 : 1 - dow));
      for (let i = 0; i < 12; i++) {
        const mon = new Date(monThis); mon.setDate(monThis.getDate() - 7 * i);
        const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
        const lab = `${_pad2(mon.getDate())} ${_MES_ES[mon.getMonth()]} – ${_pad2(sun.getDate())} ${_MES_ES[sun.getMonth()]}`;
        out.push({ value: i === 0 ? '' : _isoD(cap(sun)), label: i === 0 ? `Esta semana · ${lab}` : lab });
      }
    } else if (periodo === 'q') {
      const curQ = Math.floor(today.getMonth() / 3);
      for (let i = 0; i < 8; i++) {
        let q = curQ - i, y = today.getFullYear();
        while (q < 0) { q += 4; y -= 1; }
        const last = new Date(y, q * 3 + 3, 0);
        out.push({ value: i === 0 ? '' : _isoD(cap(last)), label: i === 0 ? `Q${q + 1} ${y} (actual)` : `Q${q + 1} ${y}` });
      }
    } else if (periodo === 'anio' || periodo === 'año') {
      for (let i = 0; i < 5; i++) {
        const y = today.getFullYear() - i;
        out.push({ value: i === 0 ? '' : _isoD(cap(new Date(y, 11, 31))), label: i === 0 ? `${y} (actual)` : String(y) });
      }
    } else { // mes
      for (let i = 0; i < 18; i++) {
        const m = new Date(today.getFullYear(), today.getMonth() - i, 1);
        const last = new Date(m.getFullYear(), m.getMonth() + 1, 0);
        const lab = `${_MES_ES[m.getMonth()]} ${m.getFullYear()}`;
        out.push({ value: i === 0 ? '' : _isoD(cap(last)), label: i === 0 ? `${lab} (actual)` : lab });
      }
    }
    return out;
  }

  function fillPeriodSpecific(sel, periodo) {
    if (!sel) return;
    sel.innerHTML = periodSpecificOptions(periodo)
      .map(o => `<option value="${o.value}">${esc(o.label)}</option>`).join('');
    sel.value = ''; // default = más reciente
  }

  // Aplica periodicidad y/o corte a todas las cards período-aware de la sección.
  async function applyPeriodToSection(section, { periodo, corte }) {
    const els = [...section.querySelectorAll('[data-chart][data-override-periodo]')];
    els.forEach(el => {
      if (periodo != null) el.dataset.overridePeriodo = periodo;
      if (corte) el.setAttribute('data-override-corte', corte);
      else el.removeAttribute('data-override-corte');
    });
    const groups = new Map();
    els.forEach(el => {
      const ov = readOverridesFor(el);
      const ck = compKeyFor(el.dataset.chart, ov);
      if (!groups.has(ck)) groups.set(ck, { chartKey: el.dataset.chart, overrides: ov, els: [] });
      groups.get(ck).els.push(el);
    });
    for (const { chartKey, overrides, els } of groups.values()) {
      try {
        const r = await fetchChart(chartKey, overrides);
        els.forEach(el => renderBinding(el, r.rows || []));
      } catch (err) { console.error('apply period', chartKey, err); }
    }
  }

  // Toggle de período (Semana/Mes/Q/Año) + selector específico — globales: afectan
  // todas las cards período-aware de su sección. Sin selección → más reciente.
  function bindGlobalPeriodToggles() {
    document.querySelectorAll('[data-period-global]').forEach(group => {
      const section = group.closest('.channel') || document;
      const head = group.closest('.mkt-metrics-head') || group.parentElement || document;
      const sel = head.querySelector('[data-period-specific]');
      const activePeriodo = () => (group.querySelector('[data-period-set].is-active')?.dataset.periodSet) || 'mes';

      if (sel) fillPeriodSpecific(sel, activePeriodo());

      group.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-period-set]');
        if (!btn) return;
        const periodo = btn.dataset.periodSet;
        group.querySelectorAll('[data-period-set]').forEach(b => {
          const active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (sel) fillPeriodSpecific(sel, periodo); // reset a "más reciente"
        await applyPeriodToSection(section, { periodo, corte: '' });
      });

      if (sel) sel.addEventListener('change', async () => {
        await applyPeriodToSection(section, { periodo: activePeriodo(), corte: sel.value || '' });
      });
    });
  }

  // Toggle MQL/SQL del card de líneas en el tiempo. Setea data-override-lead-type
  // en los charts del card y refetchea (preserva periodo/corte vía readOverridesFor).
  function bindLeadTypeToggles() {
    document.querySelectorAll('[data-leadtype-toggle]').forEach(group => {
      const card = group.closest('.card') || document;
      group.addEventListener('click', async (e) => {
        const btn = e.target.closest('[data-leadtype-set]');
        if (!btn) return;
        const lt = btn.dataset.leadtypeSet;
        group.querySelectorAll('[data-leadtype-set]').forEach(b => {
          const active = b === btn;
          b.classList.toggle('is-active', active);
          b.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        const els = [...card.querySelectorAll('[data-chart][data-override-lead-type]')];
        els.forEach(el => el.setAttribute('data-override-lead-type', lt));
        const groups = new Map();
        els.forEach(el => {
          const ov = readOverridesFor(el);
          const ck = compKeyFor(el.dataset.chart, ov);
          if (!groups.has(ck)) groups.set(ck, { chartKey: el.dataset.chart, overrides: ov, els: [] });
          groups.get(ck).els.push(el);
        });
        for (const { chartKey, overrides, els } of groups.values()) {
          try { const r = await fetchChart(chartKey, overrides); els.forEach(el => renderBinding(el, r.rows || [])); }
          catch (err) { console.error('leadtype toggle', chartKey, err); }
        }
      });
    });
  }

  function syncMonthChips(month) {
    const txt = month ? formatMonthHuman(month) : '';
    document.querySelectorAll('[data-kpi-drawer-month-chip]').forEach(el => {
      el.textContent = txt;
    });
  }

  /* ---------- KPI detail drawer ---------- */
  function bindKpiDrawers() {
    const drawer = document.querySelector('[data-kpi-drawer]');
    if (!drawer) return;
    onMonthChange((m) => syncMonthChips(m));
    syncMonthChips(monthState.selected);
    bindDrawerWindowControls();
    bindFunnelDetailToggles();

    const openDrawer = (panelKey) => {
      const panels = drawer.querySelectorAll('[data-kpi-detail-panel]');
      let activePanel = null;
      panels.forEach(p => {
        const isActive = p.getAttribute('data-kpi-detail-panel') === panelKey;
        p.classList.toggle('is-active', isActive);
        if (isActive) activePanel = p;
      });
      if (!activePanel) return;
      drawer.classList.add('is-open');
      drawer.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      // SVGs inside a panel that was display:none at hydrate-time often render
      // with zero geometry. Re-paint them with cached rows now that the panel is visible.
      requestAnimationFrame(() => {
        // Lazy: el drawer es global (fuera de los channels), así que sus charts
        // NO se cargan en el hydrate por pestaña. Los cargamos on-demand al abrir
        // (los no cacheados); los month-aware se ajustan al mes seleccionado.
        hydrate(activePanel);
        rerenderChartsInScope(activePanel);
        // Sync any [data-month-aware] elements in this panel to the currently-selected month
        refetchMonthAwareElements(activePanel);
      });
    };
    const closeDrawer = () => {
      drawer.classList.remove('is-open');
      drawer.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
    };

    // Drill por semana: setea data-override-week en los week-aware del panel,
    // abre el drawer y REFETCHEA esos elementos con la semana (hydrate saltea
    // scopes ya cargados, así que el refetch es directo).
    openWeekDrawer = (panelKey, wkMon) => {
      const panel = drawer.querySelector(`[data-kpi-detail-panel="${panelKey}"]`);
      if (panel) {
        panel.querySelectorAll('[data-week-aware]').forEach(el => { el.dataset.overrideWeek = wkMon; });
      }
      openDrawer(panelKey);
      if (!panel) return;
      requestAnimationFrame(async () => {
        const groups = new Map();
        panel.querySelectorAll('[data-week-aware][data-chart]').forEach(el => {
          const ov = readOverridesFor(el);
          const ck = compKeyFor(el.dataset.chart, ov);
          if (!groups.has(ck)) groups.set(ck, { chartKey: el.dataset.chart, overrides: ov, els: [] });
          groups.get(ck).els.push(el);
        });
        for (const { chartKey, overrides, els } of groups.values()) {
          try {
            const r = await fetchChart(chartKey, overrides);
            els.forEach(el => renderBinding(el, r.rows || []));
          } catch (e) { console.error('week drill', chartKey, e); }
        }
      });
    };
    // Botón "Ver detalle" del card semanal → semana en curso.
    const _currentMondayYmd = () => {
      const d = new Date();
      const dow = (d.getDay() + 6) % 7;
      const mon = new Date(d.getFullYear(), d.getMonth(), d.getDate() - dow);
      const z = (n) => String(n).padStart(2, '0');
      return `${mon.getFullYear()}-${z(mon.getMonth() + 1)}-${z(mon.getDate())}`;
    };
    document.querySelectorAll('[data-week-detail-open]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        openWeekDrawer(btn.getAttribute('data-week-detail-open'), _currentMondayYmd());
      });
    });

    // Drill por período (Marketing): igual que week, con data-override-periodo.
    openPeriodDrawer = (panelKey, periodo, corte) => {
      const panel = drawer.querySelector(`[data-kpi-detail-panel="${panelKey}"]`);
      if (panel) {
        panel.querySelectorAll('[data-period-aware]').forEach(el => {
          el.dataset.overridePeriodo = periodo;
          if (corte) el.setAttribute('data-override-corte', corte);
          else el.removeAttribute('data-override-corte');
        });
      }
      openDrawer(panelKey);
      if (!panel) return;
      requestAnimationFrame(async () => {
        const groups = new Map();
        panel.querySelectorAll('[data-period-aware][data-chart]').forEach(el => {
          const ov = readOverridesFor(el);
          const ck = compKeyFor(el.dataset.chart, ov);
          if (!groups.has(ck)) groups.set(ck, { chartKey: el.dataset.chart, overrides: ov, els: [] });
          groups.get(ck).els.push(el);
        });
        for (const { chartKey, overrides, els } of groups.values()) {
          try {
            const r = await fetchChart(chartKey, overrides);
            els.forEach(el => renderBinding(el, r.rows || []));
          } catch (e) { console.error('period drill', chartKey, e); }
        }
      });
    };
    // Drill por bucket (histórico apilado): setea periodo (granularidad) + bucket
    // en los period-aware del panel, abre el drawer y refetchea.
    openBucketDrawer = (panelKey, periodo, bucket) => {
      const panel = drawer.querySelector(`[data-kpi-detail-panel="${panelKey}"]`);
      if (panel) {
        panel.querySelectorAll('[data-period-aware]').forEach(el => {
          el.dataset.overridePeriodo = periodo;
          el.dataset.overrideBucket = bucket;
        });
      }
      openDrawer(panelKey);
      if (!panel) return;
      requestAnimationFrame(async () => {
        const groups = new Map();
        panel.querySelectorAll('[data-period-aware][data-chart]').forEach(el => {
          const ov = readOverridesFor(el);
          const ck = compKeyFor(el.dataset.chart, ov);
          if (!groups.has(ck)) groups.set(ck, { chartKey: el.dataset.chart, overrides: ov, els: [] });
          groups.get(ck).els.push(el);
        });
        for (const { chartKey, overrides, els } of groups.values()) {
          try {
            const r = await fetchChart(chartKey, overrides);
            els.forEach(el => renderBinding(el, r.rows || []));
          } catch (e) { console.error('bucket drill', chartKey, e); }
        }
      });
    };
    // Drill por categoría (dona): setea data-override-<key>=<valor> en TODOS los
    // charts del panel (valor vacío = limpia el filtro), abre el drawer y refetchea.
    openCategoryDrawer = (panelKey, filterKey, value) => {
      const panel = drawer.querySelector(`[data-kpi-detail-panel="${panelKey}"]`);
      const attr = 'data-override-' + filterKey;
      if (panel) {
        panel.querySelectorAll('[data-chart]').forEach(el => {
          if (value == null || value === '') el.removeAttribute(attr);
          else el.setAttribute(attr, value);
        });
      }
      openDrawer(panelKey);
      if (!panel) return;
      requestAnimationFrame(async () => {
        const groups = new Map();
        panel.querySelectorAll('[data-chart]').forEach(el => {
          const ov = readOverridesFor(el);
          const ck = compKeyFor(el.dataset.chart, ov);
          if (!groups.has(ck)) groups.set(ck, { chartKey: el.dataset.chart, overrides: ov, els: [] });
          groups.get(ck).els.push(el);
        });
        for (const { chartKey, overrides, els } of groups.values()) {
          try { const r = await fetchChart(chartKey, overrides); els.forEach(el => renderBinding(el, r.rows || [])); }
          catch (e) { console.error('category drill', chartKey, e); }
        }
      });
    };
    // Botón "Ver detalle (todas)" de una dona categórica → abre SIN filtro (limpia).
    document.querySelectorAll('[data-category-detail-open]').forEach(btn => {
      btn.addEventListener('click', () => {
        openCategoryDrawer(btn.dataset.categoryDetailOpen, btn.dataset.categoryKey || 'reason', '');
      });
    });

    // Botón "Ver detalle" de un card de período → usa el período activo del
    // toggle GENERAL de la sección.
    document.querySelectorAll('[data-period-detail-open]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const section = btn.closest('.channel');
        const active = (section || document).querySelector('[data-period-global] [data-period-set].is-active');
        const periodo = active ? active.dataset.periodSet : 'mes';
        const specSel = (section || document).querySelector('[data-period-specific]');
        const corte = specSel ? (specSel.value || '') : '';
        openPeriodDrawer(btn.getAttribute('data-period-detail-open'), periodo, corte);
      });
    });

    document.querySelectorAll('[data-kpi-detail-open]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        // Clicks inside a nested expander / month-detail panel have their own
        // per-month drill behavior — the card-level drawer ("ver todo el YTD")
        // should only fire for clicks on the card body, not on its detail.
        if (e.target.closest('.expander')) return;
        e.preventDefault();
        // Stop bubbling so a clickable element nested inside another
        // [data-kpi-detail-open] (e.g. channel pills inside a clickable card)
        // doesn't also trigger the ancestor's drawer.
        e.stopPropagation();
        const panelKey = btn.getAttribute('data-kpi-detail-open');
        openDrawer(panelKey);
        // If the tile declares which window the drawer should start on
        // (e.g. clicking the "Last week" card opens the drawer with the
        // Last week tile already highlighted + table filtered), trigger it
        // after the drawer is visible so the hero, table and chip refresh.
        const initialWindow = btn.dataset.initialWindow;
        if (initialWindow) {
          requestAnimationFrame(() => {
            try { setDrawerWindow(panelKey, initialWindow); }
            catch (err) { console.error('initial window apply failed', err); }
          });
        }
      });
    });

    drawer.querySelectorAll('[data-kpi-drawer-close]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.preventDefault();
        closeDrawer();
      });
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && drawer.classList.contains('is-open')) closeDrawer();
    });
  }

  /* ---------- Ops detail table ---------- */
  async function renderOpsDetailTable() {
    const tbody = document.querySelector('[data-detail-table="ops"]');
    if (!tbody) return;
    try {
      const [places, ptime, ptimeRepl, batchMonth, ndaWin, intConv] = await Promise.all([
        fetchChart('op_bar_new_placements').catch(() => ({ rows: [] })),
        fetchChart('op_line_placement_time').catch(() => ({ rows: [] })),
        fetchChart('op_line_placement_time_repl').catch(() => ({ rows: [] })),
        fetchChart('op_line_batch_delivery_time_month').catch(() => ({ rows: [] })),
        fetchChart('op_line_nda_close_win').catch(() => ({ rows: [] })),
        fetchChart('op_line_interview_conversion').catch(() => ({ rows: [] })),
      ]);
      const ym = (s) => String(s || '').slice(0, 7);
      const byMes = {};
      const upsert = (m, k, v) => { if (!m) return; (byMes[m] = byMes[m] || { mes: m })[k] = v; };
      (places.rows || []).forEach(r => upsert(ym(r.mes), 'placements', r.total_starts));
      (ptime.rows  || []).forEach(r => upsert(ym(r.mes_cierre), 'avg_time', r.promedio_dias));
      (ptimeRepl.rows || []).forEach(r => upsert(ym(r.mes_cierre), 'repl_time', r.promedio_dias));
      (batchMonth.rows || []).forEach(r => {
        upsert(ym(r.mes_batch), 'batch_d', r.avg_dias_entrega);
        upsert(ym(r.mes_batch), 'batches', r.total_batches);
      });
      (ndaWin.rows || []).forEach(r => upsert(ym(r.mes_close), 'nda_win', r.conversion_pct));
      (intConv.rows || []).forEach(r => upsert(ym(r.mes), 'int_conv', r.pct_presentados_sobre_entrevistados));

      const months = Object.keys(byMes).sort().slice(-6);
      tbody.innerHTML = months.map((m, i) => {
        const r = byMes[m];
        const hl = i === months.length - 1 ? ' class="hl"' : '';
        return `
          <tr${hl}>
            <td class="ink">${m}</td>
            <td class="num">${fmt.int(r.placements)}</td>
            <td class="num">${fmt.int(r.avg_time)}</td>
            <td class="num">${fmt.int(r.repl_time)}</td>
            <td class="num">${fmt.int(r.batch_d)}</td>
            <td class="num">${fmt.int(r.batches)}</td>
            <td class="num">${fmt.percent(r.nda_win)}</td>
            <td class="num">${fmt.percent(r.int_conv)}</td>
          </tr>`;
      }).join('');
    } catch (e) {
      console.error('Ops detail table failed', e);
    }
  }

  /* ---------- Sales detail table ---------- */
  async function renderSalesDetailTable() {
    const tbody = document.querySelector('[data-detail-table="sales"]');
    if (!tbody) return;
    try {
      const [nda, newClients] = await Promise.all([
        fetchChart('sa_line_nda_to_clients').catch(() => ({ rows: [] })),
        fetchChart('sa_area_new_clients_per_month').catch(() => ({ rows: [] })),
      ]);
      const ym = (s) => String(s || '').slice(0, 7);
      const byMes = {};
      const upsert = (m, k, v) => { if (!m) return; (byMes[m] = byMes[m] || { mes: m })[k] = v; };
      (nda.rows || []).forEach(r => {
        const m = ym(r.mes_close);
        upsert(m, 'total_closed', r.total_closed_opps);
        upsert(m, 'close_win', r.close_win);
        upsert(m, 'closed_lost', r.closed_lost);
        upsert(m, 'conversion', r.conversion_pct);
        upsert(m, 'unique_clients', r.unique_clients_closed_that_month);
      });
      (newClients.rows || []).forEach(r => upsert(ym(r.mes), 'new_clients', r.new_clients));
      const months = Object.keys(byMes).sort().slice(-6);
      tbody.innerHTML = months.map((m, i) => {
        const r = byMes[m];
        const hl = i === months.length - 1 ? ' class="hl"' : '';
        return `
          <tr${hl}>
            <td class="ink">${m}</td>
            <td class="num">${fmt.int(r.total_closed)}</td>
            <td class="num">${fmt.int(r.close_win)}</td>
            <td class="num">${fmt.int(r.closed_lost)}</td>
            <td class="num">${fmt.percent(r.conversion)}</td>
            <td class="num">${fmt.int(r.unique_clients)}</td>
            <td class="num">${fmt.int(r.new_clients)}</td>
          </tr>`;
      }).join('');
    } catch (e) {
      console.error('Sales detail table failed', e);
    }
  }

  /* ---------- AM detail table (multi-source roll-up) ---------- */
  async function renderAmDetailTable() {
    const tbody = document.querySelector('[data-detail-table="am"]');
    if (!tbody) return;
    try {
      const [cChurn, candChurn, crr, nrr, multi, hcg] = await Promise.all([
        fetchChart('am_line_client_churn').catch(() => ({ rows: [] })),
        fetchChart('am_line_candidate_churn').catch(() => ({ rows: [] })),
        fetchChart('am_line_crr').catch(() => ({ rows: [] })),
        fetchChart('am_line_nrr').catch(() => ({ rows: [] })),
        fetchChart('am_line_clients_multi').catch(() => ({ rows: [] })),
        fetchChart('am_line_headcount_growth').catch(() => ({ rows: [] })),
      ]);
      const ym = (s) => String(s || '').slice(0, 7);
      const byMes = {};
      const upsert = (m, k, v) => { if (!m) return; (byMes[m] = byMes[m] || { mes: m })[k] = v; };
      (cChurn.rows || []).forEach(r => {
        upsert(ym(r.mes), 'clients_active', r.clientes_activos);
        upsert(ym(r.mes), 'client_churn', r.churn_real_pct);
      });
      (candChurn.rows || []).forEach(r => {
        upsert(ym(r.mes), 'cands_active', r.activos_inicio);
        upsert(ym(r.mes), 'cand_churn', r.churn_real_pct);
      });
      (crr.rows || []).forEach(r => {
        // The am_line_crr dataset (crr_history) names its fields with the
        // expected UI convention: crr_pct = retention, grr_pct = growth.
        // (The 30d-summary KPI tile has them swapped; that one is fixed in
        // the HTML bindings, not here.)
        upsert(ym(r.mes), 'crr', r.crr_pct);
        upsert(ym(r.mes), 'grr', r.grr_pct);
      });
      (nrr.rows || []).forEach(r => upsert(ym(r.mes), 'nrr', r.nrr_pct));
      (multi.rows || []).forEach(r => upsert(ym(r.mes), 'multi', r.pct_percent));
      (hcg.rows  || []).forEach(r => upsert(ym(r.mes), 'hcg',   r.pct_activos_que_aumentaron));

      const months = Object.keys(byMes).sort().slice(-6);
      tbody.innerHTML = months.map((m, i) => {
        const r = byMes[m];
        const hl = i === months.length - 1 ? ' class="hl"' : '';
        return `
          <tr${hl}>
            <td class="ink">${m}</td>
            <td class="num">${fmt.int(r.clients_active)}</td>
            <td class="num">${fmt.percent(r.client_churn)}</td>
            <td class="num">${fmt.int(r.cands_active)}</td>
            <td class="num">${fmt.percent(r.cand_churn)}</td>
            <td class="num">${fmt.percent(r.crr)}</td>
            <td class="num">${fmt.percent(r.grr)}</td>
            <td class="num">${fmt.percent(r.nrr)}</td>
            <td class="num">${fmt.percent(r.multi)}</td>
            <td class="num">${fmt.percent(r.hcg)}</td>
          </tr>`;
      }).join('');
    } catch (e) {
      console.error('AM detail table failed', e);
    }
  }

  /* ---------- detail table (multi-source) ---------- */
  async function renderDetailTable() {
    const tbody = document.querySelector('[data-detail-table="growth"]');
    if (!tbody) return;
    try {
      const [arpa, arpc, mrr, acpa, upfront] = await Promise.all([
        fetchChart('gr_line_arpa').catch(() => ({ rows: [] })),
        fetchChart('gr_line_arpc').catch(() => ({ rows: [] })),
        fetchChart('gr_line_mrr').catch(() => ({ rows: [] })),
        fetchChart('gr_line_acpa').catch(() => ({ rows: [] })),
        fetchChart('gr_area_recruiting_upfront').catch(() => ({ rows: [] })),
      ]);

      // Index by month
      const byMes = {};
      const upsert = (m, k, v) => { if (!m) return; (byMes[m] = byMes[m] || { mes: m })[k] = v; };
      (arpa.rows || []).forEach(r => {
        upsert(r.mes, 'clientes_activos', r.clientes_activos);
        upsert(r.mes, 'arpa', r.arpa_revenue);
        upsert(r.mes, 'revenue_total', r.revenue_total_mes);
      });
      (arpc.rows || []).forEach(r => {
        upsert(r.mes, 'candidatos_activos', r.candidatos_activos);
        upsert(r.mes, 'arpc', r.arpc_revenue);
      });
      (mrr.rows || []).forEach(r => {
        upsert(r.mes, 'mrr', r.mrr_total);
        upsert(r.mes, 'growth_pct', r.growth_pct);
      });
      (acpa.rows || []).forEach(r => {
        upsert(r.mes, 'acpa', r.acpa);
      });
      (upfront.rows || []).forEach(r => {
        upsert(r.mes_cierre, 'upfront', r.monto_recruiting);
      });

      // Last 6 months
      const months = Object.keys(byMes).sort().slice(-6);
      tbody.innerHTML = '';
      months.forEach((m, i) => {
        const r = byMes[m];
        const tr = document.createElement('tr');
        if (i === months.length - 1) tr.className = 'hl';
        tr.innerHTML = `
          <td class="ink">${m}</td>
          <td class="num${i === months.length - 1 ? ' ink' : ''}">${fmt.int(r.candidatos_activos)}</td>
          <td class="num">${fmt.int(r.clientes_activos)}</td>
          <td class="num">${fmt.decimal(r.acpa)}</td>
          <td class="num">${fmt['currency-k'](r.arpa)}</td>
          <td class="num">${fmt['currency-k'](r.arpc)}</td>
          <td class="num">${fmt['currency-k'](r.mrr)}</td>
          <td class="num">${fmt['currency-k'](r.upfront)}</td>
          <td class="num">${fmt['delta-percent'](r.growth_pct)}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (e) {
      console.error('detail table failed', e);
    }
  }

  /* ---------- hydrate ---------- */
  let hydrateInflight = 0;
  const lastFetchedRows = new Map(); // compositeKey -> rows
  const hydratedScopes = new Set();  // scopeKeys ya cargados desde el último cambio de filtro

  // El channel (pestaña) visible: el radio name="tab" tildado → .channel[data-channel].
  function activeChannelEl() {
    const checked = document.querySelector('input[name="tab"]:checked');
    const ch = checked ? checked.id.replace(/^tab-/, '') : null;
    return (ch && document.querySelector(`.channel[data-channel="${ch}"]`)) || document.body;
  }
  function scopeKeyOf(scope) {
    return (scope && scope.dataset && (scope.dataset.channel || scope.dataset.kpiDetailPanel)) || 'doc';
  }
  // Invalidación: un cambio que afecta datos (filtro/ventana/reset) limpia todo y
  // recarga SOLO el channel activo; los demás se recargan al revisitarse.
  function refetchActive() {
    lastFetchedRows.clear();
    hydratedScopes.clear();
    updateWindowLabels();
    updatePeriodLabels();
    hydrate(activeChannelEl(), { force: true });
  }
  // Cartel de ventana de las cards de 30d: refleja el filtro activo
  // (Desde/Hasta > Mes > 30d) — mismo orden que el backend (_periods.window_bounds).
  function windowLabelText() {
    const MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
    const fmtD = (s) => {
      const p = String(s).split('-');
      return p.length >= 3 ? `${p[2]} ${MES[+p[1] - 1] || ''}` : s;
    };
    if (state.desde || state.hasta) {
      return `${state.desde ? fmtD(state.desde) : '…'}–${state.hasta ? fmtD(state.hasta) : 'hoy'}`;
    }
    if (state.mes) {
      const p = String(state.mes).split('-');
      return `${MES[+p[1] - 1] || ''} ${p[0]}`;
    }
    return '30d';
  }
  function updateWindowLabels() {
    const txt = windowLabelText();
    const filtered = !!(state.desde || state.hasta || state.mes || state.corte);  // rango/mes/corte elegido
    document.querySelectorAll('[data-window-label]').forEach(el => {
      el.textContent = txt;
      el.classList.toggle('is-filtered', filtered);
    });
  }
  // Etiqueta de período para cards all-time/YTD que pueden filtrarse (donas Ops,
  // barras mensuales): muestra el rango activo (ej. "01 may–31 may") o el default
  // de la card (data-period-default, ej. "Todo el período" / "YTD") si no hay filtro.
  function periodRangeText() {
    const MES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
    const fmtD = (s) => {
      const p = String(s).split('-');
      return p.length >= 3 ? `${p[2]} ${MES[+p[1] - 1] || ''}` : s;
    };
    if (state.desde || state.hasta) {
      return `${state.desde ? fmtD(state.desde) : '…'}–${state.hasta ? fmtD(state.hasta) : 'hoy'}`;
    }
    if (state.mes) {
      const p = String(state.mes).split('-');
      return `${MES[+p[1] - 1] || ''} ${p[0]}`;
    }
    if (state.corte) return '30d';  // corte presionado → ventana rodante de 30d
    return '';
  }
  function updatePeriodLabels() {
    const txt = periodRangeText();
    document.querySelectorAll('[data-period-label]').forEach(el => {
      el.textContent = txt || (el.dataset.periodDefault || 'Todo el período');
      el.classList.toggle('is-filtered', !!txt);
    });
  }
  // Ventanas de CALENDARIO (no rolling): se anclan a HOY, NO al corte. Solo las
  // rolling (30d / 7d) siguen el filtro CORTE.
  const CALENDAR_WINDOWS = new Set([
    'week', 'semana', 'last_week', 'last-week', 'prev_week',
    'month', 'last_month', 'last-month', 'prev_month', 'mtd',
  ]);
  function readOverridesFor(el) {
    const out = {};
    for (const attr of el.attributes) {
      if (attr.name.startsWith('data-override-')) {
        const key = attr.name.slice('data-override-'.length).replace(/-/g, '_');
        if (key) out[key] = attr.value;
      }
    }
    // Una sub-tile de window calendario (Last week / Last month / MTD) ignora el
    // CORTE global: se mantiene relativa a hoy. Así solo "Last 30d" sigue el corte.
    if (out.window && CALENDAR_WINDOWS.has(String(out.window).trim().toLowerCase())) {
      out.corte = '';
    }
    return out;
  }
  function compKeyFor(chartKey, overrides) {
    const keys = Object.keys(overrides).sort();
    if (!keys.length) return chartKey;
    return chartKey + '?' + keys.map(k => `${k}=${overrides[k]}`).join('&');
  }
  // Re-render every [data-chart] element inside `scope` using cached rows.
  // Used when a panel (e.g. KPI drawer) becomes visible after page-load hydrate.
  function rerenderChartsInScope(scope) {
    if (!scope) return;
    scope.querySelectorAll('[data-chart]').forEach(el => {
      const chartKey = el.dataset.chart;
      if (!chartKey) return;
      const compKey = compKeyFor(chartKey, readOverridesFor(el));
      const rows = lastFetchedRows.get(compKey) || [];
      renderBinding(el, rows);
    });
  }
  // hydrate(scope, {force}) — carga SOLO los charts dentro de `scope` (por defecto
  // el channel/pestaña activa). Idempotente: lo ya cacheado se re-renderiza desde
  // cache (sin re-fetch) salvo force. Esto evita cargar las 4 pestañas + drawers de
  // una; cada pestaña/drawer carga on-demand → muchísimas menos queries por load.
  let _hydrateGen = 0;  // R14 (#3): token de generación para descartar pasadas viejas (race)
  async function hydrate(scope, opts) {
    opts = opts || {};
    scope = scope || activeChannelEl();
    syncPeriodSuffixes();
    const scopeKey = scopeKeyOf(scope);
    if (!opts.force && hydratedScopes.has(scopeKey)) {
      rerenderChartsInScope(scope); // ya cargado → solo re-pinta desde cache
      return;
    }
    const myGen = ++_hydrateGen;  // R14: esta pasada; si arranca otra hydrate, esta se descarta
    hydrateInflight++;
    document.body.classList.add('is-loading');

    try {
      const cards = scope.querySelectorAll('[data-chart]');
      const groups = new Map(); // compositeKey -> { chartKey, overrides, els: [] }
      cards.forEach(el => {
        const chartKey = el.dataset.chart;
        if (!chartKey) return;
        const overrides = readOverridesFor(el);
        const compKey = compKeyFor(chartKey, overrides);
        // ya en cache y no forzamos → render desde cache, no re-fetch
        if (!opts.force && lastFetchedRows.has(compKey)) {
          renderBinding(el, lastFetchedRows.get(compKey));
          return;
        }
        if (!groups.has(compKey)) {
          groups.set(compKey, { chartKey, overrides, els: [] });
        }
        groups.get(compKey).els.push(el);
      });

      await Promise.all([...groups.values()].map(async ({ chartKey, overrides, els }) => {
        const compKey = compKeyFor(chartKey, overrides);
        try {
          const r = await fetchChart(chartKey, overrides);
          if (myGen !== _hydrateGen) return;  // R14 (#3): pasada superada por un filtro más nuevo → descartar
          const rows = r.rows || [];
          lastFetchedRows.set(compKey, rows);
          els.forEach(el => {
            // R14 (#7): limpiar marca de error si la había
            if (el.hasAttribute('data-fetch-error')) { el.removeAttribute('data-fetch-error'); el.removeAttribute('title'); }
            renderBinding(el, rows);
          });
        } catch (e) {
          if (myGen !== _hydrateGen) return;  // R14 (#3): pasada superada → no pisar con un error viejo
          console.error(`fetch ${chartKey}`, e);
          if (!lastFetchedRows.has(compKey)) lastFetchedRows.set(compKey, []);
          // R14 (#7): marcar el error visualmente (distinto de "sin datos").
          els.forEach(el => {
            el.setAttribute('data-fetch-error', '1');
            el.title = 'Error al cargar datos';
            renderBinding(el, lastFetchedRows.get(compKey));
          });
        }
      }));

      if (myGen !== _hydrateGen) return;  // R14 (#3): llegó una hydrate más nueva → no pisar tablas/cohorts
      hydratedScopes.add(scopeKey);
      renderDetailTable();
      renderAmDetailTable();
      renderSalesDetailTable();
      renderOpsDetailTable();
      // Re-render any cohort tables now that ALL charts (including the churn
      // chart they depend on for bajas counts) are in lastFetchedRows. This
      // fixes the race condition where the cohort rendered before the churn
      // chart's data arrived.
      document.querySelectorAll('[data-bind="cohort"]').forEach(el => {
        const chartKey = el.dataset.chart;
        if (!chartKey) return;
        const compKey = compKeyFor(chartKey, readOverridesFor(el));
        renderCohort(el, lastFetchedRows.get(compKey) || []);
      });
      // Populate month-detail panels with the currently selected month
      if (monthState.selected) {
        refetchMonthDetails(monthState.selected);
      }
    } finally {
      hydrateInflight = Math.max(0, hydrateInflight - 1);
      if (hydrateInflight === 0) document.body.classList.remove('is-loading');
    }
  }

  /* ---------- filter bar ---------- */
  function syncFilterUI(key, value) {
    const input = document.querySelector(`[data-filter-input="${key}"]`);
    if (!input) return;
    input.value = value || '';
    const wrap = input.closest('[data-filter-key]');
    let display = value;
    if (value && input.tagName === 'SELECT' && input.options[input.selectedIndex]) {
      display = input.options[input.selectedIndex].text;
    }
    setFilterSlot(wrap, key, value || '', display);
  }

  function setFilterSlot(label, key, value, displayText) {
    const wrap = label || document.querySelector(`[data-filter-key="${key}"]`);
    if (!wrap) return;
    const slot = wrap.querySelector('[data-filter-slot]');
    if (!slot) return;
    if (value === '' || value == null) {
      // Restore the original placeholder text cached at boot
      slot.textContent = slot.dataset.placeholderText || 'All';
      wrap.classList.remove('filter-pill--set');
    } else {
      slot.textContent = displayText || value;
      wrap.classList.add('filter-pill--set');
    }
  }

  function bindFilters() {
    // Cache the original placeholder text on each filter slot once, before any
    // value gets written. Slot and placeholder share the same DOM node.
    document.querySelectorAll('[data-filter-slot]').forEach(slot => {
      if (slot.dataset.placeholderText == null) {
        slot.dataset.placeholderText = (slot.textContent || '').trim() || 'All';
      }
    });

    // Populate dynamic option lists (e.g. "recent-months" → last 24 months)
    document.querySelectorAll('select[data-populate="recent-months"]').forEach(sel => {
      const months = lastNMonths(24).reverse();  // most recent first
      months.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = formatMonthHuman(m);
        sel.appendChild(opt);
      });
    });

    // Sync slot/input visuals to the initial state (defaults like opp_stage='Close Win').
    document.querySelectorAll('[data-filter-input]').forEach(input => {
      const key = input.dataset.filterInput;
      const v = state[key];
      if (v != null && v !== '') {
        input.value = v;
        const wrap = input.closest('[data-filter-key]');
        let display = v;
        if (input.tagName === 'SELECT' && input.options[input.selectedIndex]) {
          display = input.options[input.selectedIndex].text;
        }
        setFilterSlot(wrap, key, v, display);
      }
    });

    document.querySelectorAll('[data-filter-input]').forEach(input => {
      const key = input.dataset.filterInput;
      const wrap = input.closest('[data-filter-key]');
      input.addEventListener('change', () => {
        const v = input.value;
        state[key] = v;
        let display = v;
        if (input.tagName === 'SELECT' && input.options[input.selectedIndex]) {
          display = input.options[input.selectedIndex].text;
        }
        setFilterSlot(wrap, key, v, display);
        // Mes is the global month picker — drives monthState.selected (for
        // month-detail panels) AND auto-sets desde/hasta to span that month
        // so monthly line charts also filter to it. 30d window charts use
        // `corte` (left untouched).
        if (key === 'mes') {
          if (v) {
            const [y, m] = v.split('-').map(Number);
            const firstDay = `${y}-${String(m).padStart(2,'0')}-01`;
            const lastDayD = new Date(y, m, 0); // m is 1-based, so day 0 of next month = last day of m
            const lastDay = `${lastDayD.getFullYear()}-${String(lastDayD.getMonth()+1).padStart(2,'0')}-${String(lastDayD.getDate()).padStart(2,'0')}`;
            state.desde = firstDay;
            state.hasta = lastDay;
            syncFilterUI('desde', firstDay);
            syncFilterUI('hasta', lastDay);
            setSelectedMonth(v);
          } else {
            // Cleared — release the date range too
            state.desde = '';
            state.hasta = '';
            syncFilterUI('desde', '');
            syncFilterUI('hasta', '');
            const d = new Date();
            const ym = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
            setSelectedMonth(ym);
          }
        }
        refetchActive();
      });
    });

    const reset = document.querySelector('[data-filter-reset]');
    if (reset) {
      reset.addEventListener('click', (e) => {
        e.preventDefault();
        // 1) Clear filter state to defaults (some filters like opp_stage have non-empty defaults)
        FILTER_KEYS.forEach(k => state[k] = FILTER_DEFAULTS[k] || '');
        // 2) Clear inputs + restore pill labels (using default values where applicable)
        document.querySelectorAll('[data-filter-input]').forEach(input => {
          const key = input.dataset.filterInput;
          const def = FILTER_DEFAULTS[key] || '';
          input.value = def;
          const wrap = input.closest('[data-filter-key]');
          let display = def;
          if (def && input.tagName === 'SELECT' && input.options[input.selectedIndex]) {
            display = input.options[input.selectedIndex].text;
          }
          setFilterSlot(wrap, key, def, display);
        });
        // 3) Reset month-detail selection back to current month
        const d = new Date();
        monthState.selected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        // 4) Reset view-mode pills (Window / Grain) to defaults
        document.querySelectorAll('.view-mode').forEach(group => {
          const key = group.dataset.viewKey;
          if (!key) return;
          const def = FILTER_DEFAULTS[key] || '';
          group.querySelectorAll('.view-mode__btn').forEach(b => {
            b.classList.toggle('is-active', b.dataset.viewValue === def);
          });
        });
        applyGrainLabels();
        // 5) Reset sub-tab radio to default
        const defaultSub = document.getElementById('gsub-' + (FILTER_DEFAULTS.subtab || 'staffing'));
        if (defaultSub) defaultSub.checked = true;
        // 6) Refetch everything
        refetchActive();
      });
    }
  }

  /* ---------- view-mode pills (Window / Grain) for Growth · New ---------- */
  function applyGrainLabels() {
    const label =
      state.grain === 'week' ? 'semana'
      : state.grain === 'year' ? 'año'
      : 'mes';
    const callout =
      state.grain === 'week' ? 'Weekly'
      : state.grain === 'year' ? 'Yearly'
      : 'Monthly';
    document.querySelectorAll('[data-grain-label]').forEach(el => { el.textContent = label; });
    document.querySelectorAll('[data-grain-callout]').forEach(el => { el.textContent = callout; });
  }

  function bindViewModes() {
    document.querySelectorAll('.view-mode').forEach(group => {
      const key = group.dataset.viewKey; // 'window' | 'grain'
      if (!key) return;
      group.querySelectorAll('.view-mode__btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const value = btn.dataset.viewValue;
          if (!value || state[key] === value) return;
          // Sync active class across all groups with the same key
          // (Staffing and Recruiting each render their own grain pills, keep them in sync)
          document.querySelectorAll(`.view-mode[data-view-key="${key}"] .view-mode__btn`).forEach(b => {
            b.classList.toggle('is-active', b.dataset.viewValue === value);
          });
          state[key] = value;
          if (key === 'grain') applyGrainLabels();
          // Both window and grain change backend data → refetch
          refetchActive();
        });
      });
    });

    // Cambio de pestaña (tab) → cargar ese channel (solo la primera vez por filtro).
    document.querySelectorAll('input[name="tab"]').forEach(input => {
      input.addEventListener('change', () => {
        if (input.checked) hydrate(activeChannelEl());
      });
    });

    // Sub-tab radios → keep state.subtab in sync (CSS handles the toggle)
    document.querySelectorAll('input[name="growth-sub"]').forEach(input => {
      input.addEventListener('change', () => {
        if (!input.checked) return;
        state.subtab = input.id.replace(/^gsub-/, '');
      });
    });

    applyGrainLabels();
  }

  /* ---------- boot ---------- */
  function boot() {
    // Default month selection = current month, so both detail panels start in sync
    const d = new Date();
    monthState.selected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    bindFilters();
    bindFlipCards();
    bindExpanders();
    bindKpiDrawers();
    bindViewModes();
    bindCohortMetricToggle();
    bindCohortByClient();
    bindCltvModelToggle();
    bindPeriodToggles();
    bindGlobalPeriodToggles();
    bindLeadTypeToggles();
    bindDtableFilters();
    bindStickyHead();
    updateWindowLabels();
    updatePeriodLabels();
    hydrate();
  }

  // Marca .sticky-head como .is-stuck cuando queda pegada arriba (para resaltarla) y
  // publica su altura en --sticky-head-h para que otras barras (ej. filtros de Marketing)
  // se peguen justo por debajo.
  function bindStickyHead() {
    const head = document.querySelector('.sticky-head');
    if (!head) return;
    const root = document.documentElement;
    const mktHead = document.querySelector('.channel[data-channel="marketing"] .mkt-metrics-head');
    const update = () => {
      const hr = head.getBoundingClientRect();
      root.style.setProperty('--sticky-head-h', Math.round(hr.height) + 'px');
      head.classList.toggle('is-stuck', hr.top <= 0);
      if (mktHead) {
        const r = mktHead.getBoundingClientRect();
        // visible solo en Marketing; se pega cuando su top alcanza el borde inferior del head fijo.
        mktHead.classList.toggle('is-stuck', r.height > 0 && r.top <= hr.height + 0.5);
      }
    };
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    // Recalcular al cambiar de pestaña (la altura del head cambia: en Marketing se oculta la filter-bar).
    document.querySelectorAll('.tab-radios').forEach(r => r.addEventListener('change', () => requestAnimationFrame(update)));
    update();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // expose for debugging
  window.VinttiControl = { state, hydrate, fetchChart, fmt };
})();
