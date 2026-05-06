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
  async function fetchChart(chartKey) {
    const url = new URL(API_BASE + `/dashboards/${SLUG}/charts/${chartKey}/data`);
    Object.entries(state).forEach(([k, v]) => {
      if (v != null && v !== '') url.searchParams.set(k, v);
    });
    const email = (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '').trim();
    const headers = { 'Accept': 'application/json' };
    if (email) headers['X-User-Email'] = email;
    const res = await fetch(url.toString(), { method: 'GET', headers, credentials: 'omit' });
    if (!res.ok) throw new Error(`HTTP ${res.status} for ${chartKey}`);
    return res.json();
  }

  /* ---------- math: smooth bezier path ---------- */
  function projectPoints(rows, xKey, yKey, w, h, padX, padY) {
    const pts = [];
    rows.forEach((r, i) => {
      const v = +r[yKey];
      if (!isFinite(v)) return;
      pts.push({ i, raw: r, val: v });
    });
    if (!pts.length) return null;

    const ys = pts.map(p => p.val);
    const minY = Math.min(...ys, 0);
    const maxY = Math.max(...ys);
    const spanY = (maxY - minY) || 1;
    const idxs = pts.map(p => p.i);
    const minX = Math.min(...idxs);
    const maxX = Math.max(...idxs);
    const spanX = (maxX - minX) || 1;

    const proj = pts.map(p => ({
      x: padX + ((p.i - minX) / spanX) * (w - 2 * padX),
      y: h - padY - ((p.val - minY) / spanY) * (h - 2 * padY),
      val: p.val,
      raw: p.raw,
    }));
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
    const area = opts.area === 'true' || opts.area === true;

    // Wipe previously rendered series
    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());

    ys.forEach((yKey, idx) => {
      const projed = projectPoints(rows, xKey, yKey, w, h, padX, padY);
      if (!projed) return;
      const col = colors[idx] || colors[0];
      const stroke = COLOR[col] || COLOR.blue;
      const d = smoothPath(projed.proj);

      // Area fill (only first series)
      if (area && idx === 0) {
        const last = projed.proj[projed.proj.length - 1];
        const first = projed.proj[0];
        const ap = document.createElementNS(SVG_NS, 'path');
        ap.setAttribute('d', d + ` L ${last.x.toFixed(2)},${h} L ${first.x.toFixed(2)},${h} Z`);
        ap.setAttribute('class', `area-${col}`);
        ap.setAttribute('data-rendered', '');
        svg.appendChild(ap);
      }

      // Line
      const lp = document.createElementNS(SVG_NS, 'path');
      lp.setAttribute('d', d);
      lp.setAttribute('fill', 'none');
      lp.setAttribute('stroke', stroke);
      lp.setAttribute('stroke-width', '3.5');
      lp.setAttribute('stroke-linecap', 'round');
      lp.setAttribute('stroke-linejoin', 'round');
      lp.setAttribute('data-rendered', '');
      svg.appendChild(lp);

      // End dot
      const last = projed.proj[projed.proj.length - 1];
      const dot = document.createElementNS(SVG_NS, 'circle');
      dot.setAttribute('cx', last.x.toFixed(2));
      dot.setAttribute('cy', last.y.toFixed(2));
      dot.setAttribute('r', '6');
      dot.setAttribute('fill', '#fff');
      dot.setAttribute('stroke', stroke);
      dot.setAttribute('stroke-width', '3');
      dot.setAttribute('data-rendered', '');
      svg.appendChild(dot);
    });
  }

  /* ---------- render: bars ---------- */
  function renderBars(svg, rows, opts) {
    if (!svg.viewBox || !svg.viewBox.baseVal.width) return;
    const vb = svg.viewBox.baseVal;
    const w = vb.width, h = vb.height;
    const padX = 8, padY = 12;
    const yKey = opts.y;
    const col = opts.color || 'violet';
    const baseColor = COLOR[col] || COLOR.blue;

    const vals = rows.map(r => +r[yKey]).filter(v => isFinite(v));
    if (!vals.length) return;
    const maxV = Math.max(...vals, 1);

    svg.querySelectorAll('[data-rendered]').forEach(n => n.remove());

    const n = rows.length;
    const slot = (w - 2 * padX) / Math.max(n, 1);
    const barW = Math.max(8, Math.min(34, slot * 0.62));

    rows.forEach((r, i) => {
      const v = +r[yKey];
      if (!isFinite(v)) return;
      const x = padX + slot * i + (slot - barW) / 2;
      const barH = Math.max(2, ((v / maxV) * (h - 2 * padY)));
      const y = h - padY - barH;

      // Color intensity scales with index (older = lighter, newer = bolder)
      const intensity = 0.32 + (i / Math.max(n - 1, 1)) * 0.68;
      const fill = i === n - 1
        ? baseColor
        : tintColor(baseColor, 1 - intensity);

      const rect = document.createElementNS(SVG_NS, 'rect');
      rect.setAttribute('x', x.toFixed(2));
      rect.setAttribute('y', y.toFixed(2));
      rect.setAttribute('width', barW.toFixed(2));
      rect.setAttribute('height', barH.toFixed(2));
      rect.setAttribute('rx', '6');
      rect.setAttribute('fill', fill);
      rect.setAttribute('data-rendered', '');
      svg.appendChild(rect);
    });
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
        });
      }
      if (bind === 'bars') {
        return renderBars(el, rows, {
          y: el.dataset.y,
          color: el.dataset.color,
        });
      }
    } catch (e) {
      console.error(`render bind=${bind} failed`, el, e);
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
    const placeholder = wrap.querySelector('[data-filter-placeholder]');
    if (!slot) return;
    if (value === '' || value == null) {
      slot.textContent = placeholder ? placeholder.textContent : 'All';
      wrap.classList.remove('filter-pill--set');
    } else {
      slot.textContent = displayText || value;
      wrap.classList.add('filter-pill--set');
    }
  }

  function bindFilters() {
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
        FILTER_KEYS.forEach(k => state[k] = '');
        document.querySelectorAll('[data-filter-input]').forEach(input => {
          input.value = '';
          const wrap = input.closest('[data-filter-key]');
          setFilterSlot(wrap, input.dataset.filterInput, '', '');
        });
        hydrate();
      });
    }
  }

  /* ---------- boot ---------- */
  function boot() {
    bindFilters();
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
