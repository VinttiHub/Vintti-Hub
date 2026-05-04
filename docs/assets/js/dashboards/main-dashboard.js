/**
 * Main dashboard page (4 tabs: Growth & Revenue, Account Management, Sales, Operations).
 * Slug: 'main'. Reads config from /dashboards/main, data from /dashboards/main/charts/:key/data.
 */
(() => {
  const SLUG = 'main';
  const VD = window.VinttiDashboards;
  if (!VD) { console.error('VinttiDashboards toolkit missing'); return; }

  const state = VD.createPageState({
    pageId: SLUG,
    defaults: { tab: 'growth' },
  });
  VD.pageState = state;

  let dashboard = null;
  let charts = [];
  const cardNodes = new Map(); // chart_key -> element

  async function bootstrap() {
    // Wait for ECharts to be available (CDN may load after our script).
    if (!window.echarts) await new Promise(r => { window.addEventListener('load', r, { once: true }); });

    try {
      const payload = await VD.api.dashboard(SLUG);
      dashboard = payload.dashboard;
      charts = payload.charts || [];
    } catch (err) {
      document.getElementById('dashGrid').innerHTML = `<div class="dash-empty">Error cargando dashboard: ${err.message}</div>`;
      return;
    }

    document.getElementById('dashTitle').textContent = dashboard.name || 'Dashboard';
    document.getElementById('dashSubtitle').textContent = `${charts.length} charts`;

    renderTabs();
    renderFilterBar();
    renderGrid();
    await refetchVisible();

    state.bus.on('filters:changed', () => refetchVisible());
  }

  function renderTabs() {
    const layout = dashboard.layout_json || {};
    const tabs = (layout.tabs && layout.tabs.length)
      ? layout.tabs
      : [{ key: 'default', label: dashboard.name || 'Dashboard' }];

    const root = document.getElementById('dashTabs');
    root.innerHTML = '';
    const active = state.get('tab') || tabs[0].key;

    tabs.forEach(t => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'dash-tab' + (t.key === active ? ' is-active' : '');
      btn.textContent = t.label || t.key;
      btn.setAttribute('role', 'tab');
      btn.dataset.tab = t.key;
      btn.addEventListener('click', () => {
        state.set('tab', t.key);
        document.querySelectorAll('.dash-tab').forEach(n => n.classList.toggle('is-active', n.dataset.tab === t.key));
        renderGrid();
        refetchVisible();
      });
      root.appendChild(btn);
    });
  }

  function renderFilterBar() {
    VD.mountFilterBar('#dashFilterBar', {
      state,
      fields: [
        { type: 'date',  key: 'desde', label: 'Desde' },
        { type: 'date',  key: 'hasta', label: 'Hasta' },
        { type: 'month', key: 'fecha', label: 'Mes' },
        { type: 'date',  key: 'corte', label: 'Corte (30d)' },
        { type: 'select', key: 'model', label: 'Modelo', options: [
          { value: 'recruiting', label: 'Recruiting' },
          { value: 'staffing',   label: 'Staffing' },
        ]},
        { type: 'select', key: 'metric', label: 'MRR Metric', options: [
          { value: 'Revenue', label: 'Revenue (TSR)' },
          { value: 'Fee',     label: 'Fee (TSF)' },
        ]},
        { type: 'select', key: 'opp_stage', label: 'Stage', options: [
          { value: 'Close Win',   label: 'Close Win' },
          { value: 'Closed Lost', label: 'Closed Lost' },
        ]},
        { type: 'select', key: 'meses', label: 'Meses (3/6)', options: [
          { value: '3', label: '3 meses (90 días)' },
          { value: '6', label: '6 meses (180 días)' },
        ]},
        { type: 'select', key: 'umbral', label: 'Número (3/6/12)', options: [
          { value: '3', label: '3 meses' },
          { value: '6', label: '6 meses' },
          { value: '12', label: '12 meses' },
        ]},
        { type: 'select', key: 'segmento', label: 'Segmento', options: [
          { value: 'Total', label: 'Total' },
          { value: 'Staffing', label: 'Staffing' },
          { value: 'Recruiting', label: 'Recruiting' },
        ]},
      ],
    });
  }

  function renderGrid() {
    const grid = document.getElementById('dashGrid');
    grid.innerHTML = '';
    cardNodes.clear();

    const activeTab = state.get('tab') || 'growth';
    const visible = charts.filter(c => (c.tab_key || 'default') === activeTab);

    if (!visible.length) {
      grid.innerHTML = `<div class="dash-empty" style="grid-column:span 12">Sin charts en este tab — el editor puede agregarlos.</div>`;
      return;
    }

    visible.forEach(c => {
      const node = document.createElement('section');
      const pos = c.position_json || {};
      const w = Number(pos.w) || 6;
      const span = Math.max(3, Math.min(12, w));
      node.className = 'dash-card dash-card--loading' + (c.type === 'kpi' ? ' dash-card--kpi' : '');
      node.style.gridColumn = `span ${span}`;
      node.dataset.chartKey = c.chart_key;
      node.innerHTML = `<h3>${c.title}</h3><div class="dash-chart-body"><div></div></div>`;
      grid.appendChild(node);
      cardNodes.set(c.chart_key, node);
    });
  }

  async function refetchVisible() {
    const activeTab = state.get('tab') || 'growth';
    const visible = charts.filter(c => (c.tab_key || 'default') === activeTab);
    const filters = buildFilters();

    await Promise.all(visible.map(async c => {
      const node = cardNodes.get(c.chart_key);
      if (!node) return;
      try {
        const payload = await VD.api.chartData(SLUG, c.chart_key, filters);
        node.classList.remove('dash-card--loading');
        VD.mountChart(node, c, payload.rows || []);
      } catch (err) {
        node.classList.remove('dash-card--loading');
        node.innerHTML = `<h3>${c.title}</h3><div class="dash-empty">Error: ${err.message}</div>`;
      }
    }));
  }

  function buildFilters() {
    const snap = state.snapshot();
    const { tab, ...rest } = snap;
    return rest;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
})();
