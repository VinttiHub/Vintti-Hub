/* =====================================================================
   VINTTI · Control Dashboard wiring
   - Reads [data-chart="<key>"] elements, fetches data from backend,
     renders KPIs, smooth bezier lines, bars and donas matching the
     retro/light visual system in control-dashboard-retro.css.
   - Wires the filter bar (modelo, desde, hasta, mes, corte, metric,
     opp_stage, meses, umbral) and reset button.
   - Tabs are CSS-only (radio inputs); we hydrate ALL tabs once on load
     and re-fetch on filter change.
   ===================================================================== */
(function () {
  const SLUG = 'main';
  const API_BASE = (window.API_BASE || 'https://7m6mw95m8y.us-east-2.awsapprunner.com').replace(/\/$/, '');
  const SVG_NS = 'http://www.w3.org/2000/svg';

  /* ---------- state ---------- */
  const FILTER_KEYS = ['modelo', 'desde', 'hasta', 'mes', 'corte', 'metric', 'opp_stage', 'meses', 'umbral'];
  const state = Object.fromEntries(FILTER_KEYS.map(k => [k, '']));

  /* ---------- format ---------- */
  const fmt = {
    int: (v) => (v == null || v === '' || isNaN(+v)) ? '—' : Math.round(+v).toLocaleString('en-US'),
    number: (v) => {
      if (v == null || v === '' || isNaN(+v)) return '—';
      const n = +v;
      if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
      if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + 'K';
      return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
    },
    decimal: (v) => (v == null || v === '' || isNaN(+v)) ? '—' : (+v).toFixed(2),
    currency: (v) => (v == null || v === '' || isNaN(+v)) ? '—' : '$' + Math.round(+v).toLocaleString('en-US'),
    'currency-k': (v) => {
      if (v == null || v === '' || isNaN(+v)) return '—';
      const n = +v;
      if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
      if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
      return '$' + n.toFixed(0);
    },
    percent: (v) => (v == null || v === '' || isNaN(+v)) ? '—' : (+v).toFixed(1) + '%',
    'percent-pp': (v) => {
      if (v == null || v === '' || isNaN(+v)) return '—';
      const n = +v;
      return (n > 0 ? '+' : '') + n.toFixed(1) + 'pp';
    },
    'delta-percent': (v) => {
      if (v == null || v === '' || isNaN(+v)) return '—';
      const n = +v;
      return (n > 0 ? '+' : '') + n.toFixed(1) + '%';
    },
    'delta-int': (v) => {
      if (v == null || v === '' || isNaN(+v)) return '—';
      const n = Math.round(+v);
      return (n > 0 ? '+' : '') + n;
    },
    months: (v) => (v == null || v === '' || isNaN(+v)) ? '—' : (+v).toFixed(1) + ' mo',
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
      svg.appendChild(dot);

      seriesInfo.push({
        proj: projed.proj,           // full-length, includes invalid points
        color: stroke,
        fmt: fmts[idx] || opts.fmtY || 'number',
        label: labels[idx] || yKey,
        yKey,
      });
    });

    // Attach interactive hover (vertical guide + tracking dots + tooltip)
    if (seriesInfo.length) {
      attachHoverTooltip(svg, seriesInfo, { xKey, rows, w, h });
    }
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

      seriesInfo.forEach((s, i) => {
        const p = s.proj[idx];
        if (!p || !p.valid) {
          tracks[i].setAttribute('opacity', '0');
          return;
        }
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

      tip.innerHTML = html;
      const pos = viewBoxToPage(refPt.x, refPt.y);
      tip.style.left = pos.x + 'px';
      tip.style.top  = pos.y + 'px';
      tip.classList.add('show');

      // Clamp horizontally to the viewport so it never escapes off-edge
      const tRect = tip.getBoundingClientRect();
      const margin = 8;
      let leftPx = pos.x;
      const halfW = tRect.width / 2;
      const minLeft = window.scrollX + margin + halfW;
      const maxLeft = window.scrollX + window.innerWidth - margin - halfW;
      if (leftPx < minLeft) leftPx = minLeft;
      if (leftPx > maxLeft) leftPx = maxLeft;
      tip.style.left = leftPx + 'px';
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
        setSelectedMonth(m);
      }
    });
  }

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
    const padX = 8, padY = 12;
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
    const barW = Math.max(8, Math.min(34, slot * 0.62));
    const barEntries = [];

    rows.forEach((r, i) => {
      const v = +r[yKey];
      if (!isFinite(v)) return;
      const x = padX + slot * i + (slot - barW) / 2;
      const barH = Math.max(2, ((v / maxV) * (h - 2 * padY)));
      const y = h - padY - barH;

      const intensity = 0.32 + (i / Math.max(n - 1, 1)) * 0.68;
      const fill = i === n - 1 ? baseColor : tintColor(baseColor, 1 - intensity);

      const rect = document.createElementNS(SVG_NS, 'rect');
      rect.setAttribute('x', x.toFixed(2));
      rect.setAttribute('y', y.toFixed(2));
      rect.setAttribute('width', barW.toFixed(2));
      rect.setAttribute('height', barH.toFixed(2));
      rect.setAttribute('rx', '6');
      rect.setAttribute('fill', fill);
      rect.setAttribute('data-rendered', '');
      svg.appendChild(rect);

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
      attachBarHover(svg, barEntries, { y: yKey });
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
    if (mode === 'count') return rows.length;
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
  function renderText(el, rows) {
    const field = el.dataset.field;
    const mode = el.dataset.reduce || 'last';
    const fmtName = el.dataset.fmt || 'number';
    const v = reduce(rows, field, mode);
    el.textContent = fmt.pick(fmtName)(v);
    if (el.dataset.classOnSign) {
      el.classList.remove('green', 'rose', 'lime');
      if (v != null && isFinite(+v)) {
        if (+v > 0) el.classList.add('green');
        else if (+v < 0) el.classList.add('rose');
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

  /* ---------- render dispatcher ---------- */
  function renderBinding(el, rows) {
    const bind = el.dataset.bind;
    try {
      if (!bind) return;
      if (bind === 'text') return renderText(el, rows);
      if (bind === 'line' || bind === 'area') {
        return renderLine(el, rows, {
          x: el.dataset.x,
          y: el.dataset.y,
          color: el.dataset.color,
          area: el.dataset.area || (bind === 'area' ? 'true' : 'false'),
          areaFill: el.dataset.areaFill,
          labels: el.dataset.labels,
          fmtY: el.dataset.fmtY,
        });
      }
      if (bind === 'list') return renderList(el, rows);
      // month-detail panels are NOT hydrated by the generic flow — they
      // refetch with mes= filter via refetchMonthDetails() instead.
      if (bind === 'month-detail') return;
      if (bind === 'bars') {
        return renderBars(el, rows, {
          x: el.dataset.x,
          y: el.dataset.y,
          color: el.dataset.color,
          label: el.dataset.label || (el.dataset.labels || '').split(',')[0],
          fmtY: el.dataset.fmtY,
        });
      }
    } catch (e) {
      console.error(`render bind=${bind} failed`, el, e);
    }
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

  /* ---------- selected month state (shared across detail panels + chart) ---------- */
  const monthState = { selected: null, listeners: [] };
  function setSelectedMonth(m) {
    if (!m || m === monthState.selected) return;
    monthState.selected = m;
    monthState.listeners.forEach(fn => { try { fn(m); } catch (e) { console.error(e); } });
    // Refetch all month-detail panels with the new month
    refetchMonthDetails(m);
  }
  function onMonthChange(fn) { monthState.listeners.push(fn); }

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

  /* ---------- month detail (one month at a time, grouped by client) ----------
     Data is server-filtered to the selected month (passes mes=YYYY-MM).
     Re-fetches when month changes. */
  function renderMonthDetail(el, rows, opts) {
    const nameField  = el.dataset.listName  || 'candidate_name';
    const subField   = el.dataset.listSub   || 'client_name';
    const dateField  = el.dataset.listDate  || 'start_date';
    const emptyText  = el.dataset.emptyText || 'No data';
    const month      = (opts && opts.month) || monthState.selected;

    const monthKeys = lastNMonths(12);
    const currentMonth = month || monthKeys[monthKeys.length - 1];

    function buildBody(entries) {
      if (!entries.length) {
        return `<div class="mdetail__empty">${esc(emptyText)}</div>`;
      }
      const byClient = {};
      entries.forEach(r => {
        const c = String(r[subField] || '—');
        (byClient[c] = byClient[c] || []).push(r);
      });
      const clientNames = Object.keys(byClient).sort((a, b) => byClient[b].length - byClient[a].length);
      return clientNames.map(c => {
        const cands = byClient[c]
          .slice()
          .sort((a, b) => String(a[nameField] || '').localeCompare(String(b[nameField] || '')))
          .map(r => `
            <div class="mdetail__cand">
              <span class="mdetail__cand-name">${esc(r[nameField] || '—')}</span>
              <span class="mdetail__cand-date">${esc(r[dateField] || '')}</span>
            </div>
          `).join('');
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
      const pills = monthKeys.map(m => `
        <button type="button" class="mdetail__pill ${m === currMonth ? 'is-selected' : ''}" data-mdetail-month="${esc(m)}">
          ${esc(formatMonthHuman(m))}
        </button>
      `).join('');
      return `<div class="mdetail__nav">${pills}<span class="mdetail__hint">Click a month or the chart point</span></div>`;
    }

    const entries = rows || [];
    const clients = new Set(entries.map(r => r[subField])).size;
    el.innerHTML = `
      ${buildNav(currentMonth)}
      <div class="mdetail__head">
        <h4>${esc(formatMonthHuman(currentMonth))}</h4>
        <span class="meta"><strong>${entries.length}</strong> ${entries.length === 1 ? 'entry' : 'entries'} · <strong>${clients}</strong> ${clients === 1 ? 'client' : 'clients'}</span>
      </div>
      <div class="mdetail__body">
        ${buildBody(entries)}
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
        const res = await fetchChart(chartKey, { mes: month });
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
  let hydrateInflight = false;
  async function hydrate() {
    if (hydrateInflight) return;
    hydrateInflight = true;
    document.body.classList.add('is-loading');

    try {
      const cards = document.querySelectorAll('[data-chart]');
      const keys = new Set();
      cards.forEach(el => keys.add(el.dataset.chart));

      const cache = {};
      await Promise.all([...keys].map(async (k) => {
        try {
          const r = await fetchChart(k);
          cache[k] = r.rows || [];
        } catch (e) {
          console.error(`fetch ${k}`, e);
          cache[k] = [];
        }
      }));

      cards.forEach(el => {
        const rows = cache[el.dataset.chart] || [];
        renderBinding(el, rows);
      });

      renderDetailTable();
      // Populate month-detail panels with the currently selected month
      if (monthState.selected) {
        refetchMonthDetails(monthState.selected);
      }
    } finally {
      document.body.classList.remove('is-loading');
      hydrateInflight = false;
    }
  }

  /* ---------- filter bar ---------- */
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
        hydrate();
      });
    });

    const reset = document.querySelector('[data-filter-reset]');
    if (reset) {
      reset.addEventListener('click', (e) => {
        e.preventDefault();
        // 1) Clear filter state
        FILTER_KEYS.forEach(k => state[k] = '');
        // 2) Clear inputs + restore pill labels to their placeholders
        document.querySelectorAll('[data-filter-input]').forEach(input => {
          input.value = '';
          const wrap = input.closest('[data-filter-key]');
          setFilterSlot(wrap, input.dataset.filterInput, '', '');
        });
        // 3) Reset month-detail selection back to current month
        const d = new Date();
        monthState.selected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
        // 4) Refetch everything
        hydrate();
      });
    }
  }

  /* ---------- boot ---------- */
  function boot() {
    // Default month selection = current month, so both detail panels start in sync
    const d = new Date();
    monthState.selected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    bindFilters();
    bindFlipCards();
    bindExpanders();
    hydrate();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

  // expose for debugging
  window.VinttiControl = { state, hydrate, fetchChart, fmt };
})();
