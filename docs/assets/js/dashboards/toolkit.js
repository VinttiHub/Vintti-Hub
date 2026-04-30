/**
 * Vintti Dashboards toolkit — shared primitives for dashboard pages.
 * Exposes window.VinttiDashboards with: state, bus, api, format, filters, charts.
 * Depends on: ECharts 5.x loaded globally as window.echarts, window.API_BASE from sidebar.js.
 */
(() => {
  const API_BASE = window.API_BASE || 'https://7m6mw95m8y.us-east-2.awsapprunner.com';

  /* ---------- bus ---------- */
  function createBus() {
    const subs = new Map();
    return {
      on(topic, fn) {
        if (!subs.has(topic)) subs.set(topic, new Set());
        subs.get(topic).add(fn);
        return () => subs.get(topic)?.delete(fn);
      },
      emit(topic, payload) {
        (subs.get(topic) || []).forEach(fn => { try { fn(payload); } catch (e) { console.error(e); } });
      },
    };
  }

  /* ---------- format ---------- */
  const fmt = {
    currency(v) {
      if (v == null || v === '') return '—';
      const n = Number(v);
      if (!isFinite(n)) return String(v);
      return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
    },
    number(v) {
      if (v == null || v === '') return '—';
      const n = Number(v);
      if (!isFinite(n)) return String(v);
      return n.toLocaleString('en-US', { maximumFractionDigits: 2 });
    },
    percent(v) {
      if (v == null || v === '') return '—';
      const n = Number(v);
      if (!isFinite(n)) return String(v);
      return n.toFixed(1) + '%';
    },
    pick(name) { return fmt[name] || fmt.number; },
  };

  /* ---------- state ---------- */
  function createPageState({ pageId, defaults = {} }) {
    const bus = createBus();
    const storageKey = `vh:dash:${pageId}`;
    const urlParams = new URLSearchParams(window.location.search);
    const stored = (() => {
      try { return JSON.parse(localStorage.getItem(storageKey) || '{}'); }
      catch { return {}; }
    })();

    const state = { ...defaults, ...stored };
    urlParams.forEach((v, k) => {
      if (v === '') return;
      state[k] = v.includes(',') ? v.split(',') : v;
    });

    let flushScheduled = false;
    function flush() {
      if (flushScheduled) return;
      flushScheduled = true;
      requestAnimationFrame(() => {
        flushScheduled = false;
        // sync to URL
        const p = new URLSearchParams();
        Object.entries(state).forEach(([k, v]) => {
          if (v == null || v === '' || (Array.isArray(v) && !v.length)) return;
          p.set(k, Array.isArray(v) ? v.join(',') : String(v));
        });
        const qs = p.toString();
        history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname);
        // sync to localStorage
        try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch {}
        bus.emit('filters:changed', { ...state });
      });
    }

    return {
      bus,
      get(key) { return state[key]; },
      snapshot() { return { ...state }; },
      patch(partial) {
        let changed = false;
        Object.entries(partial).forEach(([k, v]) => {
          if (state[k] !== v) { state[k] = v; changed = true; }
        });
        if (changed) flush();
      },
      set(key, value) { this.patch({ [key]: value }); },
      reset() {
        Object.keys(state).forEach(k => delete state[k]);
        Object.assign(state, defaults);
        flush();
      },
    };
  }

  /* ---------- api ---------- */
  function userEmail() {
    return (localStorage.getItem('user_email') || sessionStorage.getItem('user_email') || '').trim().toLowerCase();
  }

  async function fetchJSON(path, params, opts) {
    params = params || {};
    opts = opts || {};
    const url = new URL(API_BASE + path);
    Object.keys(params).forEach(function (k) {
      const v = params[k];
      if (v == null || v === '' || (Array.isArray(v) && !v.length)) return;
      url.searchParams.set(k, Array.isArray(v) ? v.join(',') : String(v));
    });
    const headers = Object.assign({ 'X-User-Email': userEmail() }, opts.headers || {});
    const init = Object.assign({}, opts, { headers: headers });
    const res = await fetch(url.toString(), init);
    if (!res.ok) throw new Error(res.status + ' ' + res.statusText);
    return res.json();
  }

  const api = {
    async me() { return fetchJSON('/dashboards/me'); },
    async dashboard(slug) { return fetchJSON(`/dashboards/${slug}`); },
    async chartData(slug, chartKey, filters) {
      return fetchJSON(`/dashboards/${slug}/charts/${chartKey}/data`, filters);
    },
    async datasets() { return fetchJSON('/dashboards/datasets'); },
    async datasetSample(key, limit = 20) {
      return fetchJSON(`/dashboards/datasets/${key}/sample`, { limit });
    },
  };

  /* ---------- filter bar ---------- */
  function mountFilterBar(root, { state, fields = [] }) {
    const el = typeof root === 'string' ? document.querySelector(root) : root;
    if (!el) return;
    el.innerHTML = '';
    el.className = 'dash-filter-bar';

    function field(label, inputHTML, extraClass = '') {
      const wrap = document.createElement('div');
      wrap.className = `dash-filter ${extraClass}`.trim();
      wrap.innerHTML = `<label>${label}</label>${inputHTML}`;
      return wrap;
    }

    fields.forEach(f => {
      if (f.type === 'date') {
        const node = field(f.label, `<input type="date" data-key="${f.key}" value="${state.get(f.key) || ''}">`);
        node.querySelector('input').addEventListener('change', e => state.set(f.key, e.target.value));
        el.appendChild(node);
      } else if (f.type === 'month') {
        const node = field(f.label, `<input type="month" data-key="${f.key}" value="${state.get(f.key) || ''}">`);
        node.querySelector('input').addEventListener('change', e => state.set(f.key, e.target.value));
        el.appendChild(node);
      } else if (f.type === 'select') {
        const opts = (f.options || []).map(o => `<option value="${o.value}" ${state.get(f.key) === o.value ? 'selected' : ''}>${o.label}</option>`).join('');
        const node = field(f.label, `<select data-key="${f.key}"><option value="">(all)</option>${opts}</select>`);
        node.querySelector('select').addEventListener('change', e => state.set(f.key, e.target.value));
        el.appendChild(node);
      }
    });

    const reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'dash-filter-reset';
    reset.textContent = 'Reset';
    reset.addEventListener('click', () => { state.reset(); });
    el.appendChild(reset);

    // Re-sync inputs when state is mutated from outside (e.g. chart drill-down click).
    state.bus.on('filters:changed', (snap) => {
      el.querySelectorAll('[data-key]').forEach(node => {
        const key = node.dataset.key;
        const v = snap[key] ?? '';
        if (node.value !== String(v)) node.value = v;
      });
    });
  }

  /* ---------- chart factory ---------- */
  function colorFor(i) {
    const palette = ['#2563eb', '#16a34a', '#7c3aed', '#f59e0b', '#dc2626', '#0891b2', '#9333ea', '#059669'];
    return palette[i % palette.length];
  }

  // Aggregate client-side when dataset returns raw rows.
  // mapping.preserveOrder=true keeps the row order from the SQL (skip alphabetic sort).
  function aggregate(rows, mapping) {
    const x = mapping.x;
    const ys = Array.isArray(mapping.y) ? mapping.y : (mapping.y ? [mapping.y] : []);
    const agg = mapping.agg || 'sum';
    const buckets = new Map();
    rows.forEach(r => {
      const key = r[x] == null ? '(null)' : String(r[x]);
      if (!buckets.has(key)) buckets.set(key, { _count: 0 });
      const b = buckets.get(key);
      b._count += 1;
      ys.forEach(y => {
        const v = Number(r[y]);
        if (!isFinite(v)) return;
        b[y] = (b[y] || 0) + v;
      });
    });
    const out = [];
    buckets.forEach((b, key) => {
      const row = { [x]: key };
      ys.forEach(y => {
        if (agg === 'count') row[y] = b._count;
        else if (agg === 'avg') row[y] = b._count ? (b[y] || 0) / b._count : 0;
        else row[y] = b[y] || 0;
      });
      out.push(row);
    });
    if (mapping.preserveOrder) return out;
    return out.sort((a, b) => String(a[x]).localeCompare(String(b[x])));
  }

  function reduceSingle(rows, mapping) {
    const key = mapping.value;
    const agg = mapping.agg || 'sum';
    if (!rows.length) return null;
    if (rows.length === 1 && mapping.value in rows[0]) return rows[0][key];
    if (agg === 'count') return rows.length;
    let sum = 0, n = 0;
    rows.forEach(r => {
      const v = Number(r[key]);
      if (isFinite(v)) { sum += v; n += 1; }
    });
    if (agg === 'avg') return n ? sum / n : 0;
    return sum;
  }

  function renderKpi(containerEl, chart, rows) {
    const mapping = (chart.config_json || {}).mapping || {};
    // Multi-stat KPI: mapping.values = [{key,label,formatter}|"key", ...] reads first row.
    if (Array.isArray(mapping.values) && mapping.values.length) {
      const row = rows[0] || {};
      const items = mapping.values.map(v => {
        const key = typeof v === 'string' ? v : v.key;
        const label = typeof v === 'string' ? v : (v.label || v.key);
        const fmtName = (typeof v === 'object' && v.formatter) || mapping.formatter || 'number';
        const fn = fmt.pick(fmtName);
        const raw = row[key];
        const display = (raw == null || raw === '') ? '—' : fn(raw);
        return `<div style="display:flex;justify-content:space-between;align-items:baseline;padding:6px 0;border-top:1px solid rgba(15,23,42,.06)"><span style="font-size:.8rem;color:#64748b">${label}</span><span style="font-size:1.05rem;font-weight:600;color:#0f172a">${display}</span></div>`;
      }).join('');
      containerEl.innerHTML = `<h3>${chart.title}</h3><div style="display:flex;flex-direction:column;justify-content:center;height:100%">${items}</div>`;
      return;
    }
    const val = reduceSingle(rows, mapping);
    const formatter = fmt.pick(mapping.formatter || 'number');
    containerEl.innerHTML = `
      <h3>${chart.title}</h3>
      <div class="dash-kpi-value">${val == null ? '—' : formatter(val)}</div>
    `;
  }

  function renderTable(containerEl, chart, rows) {
    if (!rows.length) { containerEl.innerHTML = `<h3>${chart.title}</h3><div class="dash-empty">Sin datos</div>`; return; }
    const cols = Object.keys(rows[0]);
    const head = cols.map(c => `<th style="text-align:left;padding:6px 10px;font-size:.75rem;color:#64748b;text-transform:uppercase;letter-spacing:.04em">${c}</th>`).join('');
    const body = rows.slice(0, 200).map(r => `<tr>${cols.map(c => `<td style="padding:6px 10px;font-size:.85rem;border-top:1px solid rgba(15,23,42,.05)">${r[c] ?? ''}</td>`).join('')}</tr>`).join('');
    containerEl.innerHTML = `<h3>${chart.title}</h3><div style="overflow:auto;max-height:400px"><table style="width:100%;border-collapse:collapse"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function renderEcharts(containerEl, chart, rows) {
    containerEl.innerHTML = `<h3>${chart.title}</h3><div class="dash-chart-body"><div></div></div>`;
    const holder = containerEl.querySelector('.dash-chart-body > div');
    const type = chart.type;
    const mapping = (chart.config_json || {}).mapping || {};
    const aggregated = aggregate(rows, mapping);
    const formatter = fmt.pick(mapping.formatter || 'number');
    const ys = Array.isArray(mapping.y) ? mapping.y : (mapping.y ? [mapping.y] : []);

    // Twin-axis: y[0] -> left axis (formatter), y[1..] -> right axis (formatter2 || 'percent')
    const twin = mapping.twinAxis === true && ys.length >= 2 && type !== 'pie' && type !== 'donut';
    const formatter2 = twin ? fmt.pick(mapping.formatter2 || 'percent') : null;

    // Tooltip extras: extra fields to display in tooltip (looked up from raw rows by x value).
    const extraKeys = Array.isArray(mapping.tooltipExtras) ? mapping.tooltipExtras : [];
    const rawByX = new Map();
    if (extraKeys.length) {
      rows.forEach(r => {
        const k = r[mapping.x] == null ? '(null)' : String(r[mapping.x]);
        if (!rawByX.has(k)) rawByX.set(k, r);
      });
    }

    const seriesTypes = Array.isArray(mapping.seriesTypes) ? mapping.seriesTypes : null;
    const stacked = mapping.stacked === true;
    const categories = aggregated.map(r => r[mapping.x]);
    const series = ys.map((y, i) => {
      const baseType = seriesTypes && seriesTypes[i] ? seriesTypes[i] : type;
      const echType = baseType === 'area' ? 'line'
                    : baseType === 'donut' ? 'pie'
                    : baseType;
      const isPie = echType === 'pie';
      return {
        name: y,
        type: echType,
        data: isPie
          ? aggregated.map((r, idx) => ({
              name: r[mapping.x],
              value: r[y],
              itemStyle: { color: colorFor(idx) },
            }))
          : aggregated.map(r => r[y]),
        smooth: (baseType === 'line' || baseType === 'area'),
        areaStyle: baseType === 'area' ? {} : undefined,
        radius: (baseType === 'donut') ? ['40%', '70%'] : undefined,
        itemStyle: isPie ? undefined : { color: colorFor(i) },
        yAxisIndex: twin ? (i === 0 ? 0 : 1) : 0,
        stack: (stacked && (echType === 'bar' || echType === 'line')) ? 'total' : undefined,
      };
    });

    const pieTotal = (type === 'pie' || type === 'donut')
      ? aggregated.reduce((s, r) => s + (Number(r[ys[0]]) || 0), 0)
      : 0;
    const pieByName = new Map();
    if (type === 'pie' || type === 'donut') {
      aggregated.forEach(r => pieByName.set(String(r[mapping.x]), Number(r[ys[0]]) || 0));
    }

    const option = (type === 'pie' || type === 'donut') ? {
      tooltip: {
        trigger: 'item',
        formatter: (p) => `${p.marker} ${p.name}: <b>${formatter(p.value)}</b> (${(p.percent ?? 0).toFixed(2)}%)`,
      },
      legend: {
        bottom: 0,
        formatter: (name) => {
          const v = pieByName.get(String(name)) || 0;
          const pct = pieTotal ? ((v * 100) / pieTotal).toFixed(2) : '0.00';
          return `${name}  ${pct}%`;
        },
      },
      graphic: type === 'donut' ? [{
        type: 'text',
        left: 'center',
        top: 'middle',
        style: {
          text: `${formatter(pieTotal)}\nTotal`,
          fill: '#0f172a',
          fontSize: 16,
          fontWeight: 600,
          textAlign: 'center',
          textVerticalAlign: 'middle',
          lineHeight: 20,
        },
      }] : undefined,
      series,
    } : {
      tooltip: {
        trigger: 'axis',
        valueFormatter: formatter,
        formatter: (twin || extraKeys.length || stacked) ? (params) => {
          const head = params[0]?.axisValueLabel ?? params[0]?.name ?? '';
          const total = stacked ? params.reduce((s, p) => s + (Number(p.value) || 0), 0) : 0;
          const lines = params.map(p => {
            const fn = (twin && p.seriesIndex !== 0) ? formatter2 : formatter;
            const pct = stacked && total ? ` (${((Number(p.value) || 0) * 100 / total).toFixed(2)}%)` : '';
            return `${p.marker} ${p.seriesName}: <b>${fn(p.value)}</b>${pct}`;
          });
          if (stacked) lines.push(`Total: <b>${formatter(total)}</b>`);
          if (extraKeys.length) {
            const raw = rawByX.get(String(head));
            if (raw) {
              extraKeys.forEach(k => {
                if (raw[k] != null && raw[k] !== '') lines.push(`${k}: <b>${raw[k]}</b>`);
              });
            }
          }
          return `${head}<br>${lines.join('<br>')}`;
        } : undefined,
      },
      legend: { top: 0, show: ys.length > 1 },
      grid: { left: 60, right: twin ? 60 : 20, top: ys.length > 1 ? 40 : 20, bottom: 40 },
      xAxis: {
        type: 'category',
        data: categories,
        axisLabel: { color: '#64748b', show: mapping.hideXLabels !== true },
        axisTick: { show: mapping.hideXLabels !== true },
      },
      yAxis: twin ? [
        { type: 'value', axisLabel: { color: '#64748b', formatter } },
        { type: 'value', axisLabel: { color: '#64748b', formatter: formatter2 }, splitLine: { show: false } },
      ] : { type: 'value', axisLabel: { color: '#64748b', formatter } },
      series,
    };

    if (!window.echarts) { holder.innerHTML = '<div class="dash-empty">ECharts no cargó</div>'; return null; }
    const instance = window.echarts.init(holder);
    instance.setOption(option);
    new ResizeObserver(() => instance.resize()).observe(holder);

    if (mapping.drillKey && window.VinttiDashboards && window.VinttiDashboards.pageState) {
      holder.style.cursor = 'pointer';
      instance.on('click', (params) => {
        if (params && params.name != null) {
          window.VinttiDashboards.pageState.set(mapping.drillKey, params.name);
        }
      });
    }
    return instance;
  }

  function mountChart(containerEl, chart, rows) {
    if (!rows || !rows.length) {
      containerEl.innerHTML = `<h3>${chart.title}</h3><div class="dash-empty">Sin datos</div>`;
      return;
    }
    if (chart.type === 'kpi') { renderKpi(containerEl, chart, rows); return; }
    if (chart.type === 'table') { renderTable(containerEl, chart, rows); return; }
    renderEcharts(containerEl, chart, rows);
  }

  window.VinttiDashboards = {
    createPageState, createBus, fmt, api, fetchJSON,
    mountFilterBar, mountChart, userEmail, API_BASE,
  };
})();
