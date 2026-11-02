/* Digital Twin visualization only. window.GRID_ID is set by the page. */
const GRID_ID = window.GRID_ID;
const API_URL = "http://127.0.0.1:8001";
let cy = null;
let latestGridState = null;
let telemetrySocket = null;
let socketGeneration = 0;
let reconnectAttempts = 0;
let reconnectTimer = null;

const LOAD_ICONS = [
  'icons/factory.png', 'icons/home.png', 'icons/sky-scrappers.png',
  'icons/school.png', 'icons/college.png', 'icons/gas-station.png',
  'icons/hospital.png', 'icons/museum.png', 'icons/office.png',
  'icons/banks.png', 'icons/post-office.png', 'icons/shop.png',
  'icons/shopping-mall.png',
];

function iconForNode(nodeType) {
  if (nodeType === 'GENERATOR') return 'icons/power-plant.png';
  if (nodeType === 'TRANSFORMER') return 'icons/transformer.png';
  if (nodeType === 'LOAD') {
    return LOAD_ICONS[Math.floor(Math.random() * LOAD_ICONS.length)];
  }
  return 'icons/transformer.png';
}

async function loadTopology() {
  if (!['39', '118'].includes(String(GRID_ID))) {
    throw new Error('Unsupported grid selection');
  }
  if (typeof window.cytoscape !== 'function') {
    throw new Error('Cytoscape did not load');
  }
  const response = await fetch(`${API_URL}/topology?grid=${encodeURIComponent(GRID_ID)}`);
  if (!response.ok) throw new Error(`Topology request failed (${response.status})`);
  const topology = await response.json();
  if (!topology || !Array.isArray(topology.nodes) || !Array.isArray(topology.edges)) {
    throw new Error('Topology response is incomplete');
  }
  const nodesWithIcons = topology.nodes.map((node) => ({
    ...node,
    data: { ...node.data, image: iconForNode(node.data?.node_type) },
  }));

  cy = window.cytoscape({
    container: document.getElementById('cy'),
    elements: [...nodesWithIcons, ...topology.edges],
    layout: { name: 'cose', animate: false },
    style: [
      {
        selector: 'node',
        style: {
          'background-image': 'data(image)',
          'background-fit': 'cover',
          'background-color': 'transparent',
          label: 'data(label)',
          'background-color': '#334155',
          color: '#ffffff',
          'text-valign': 'bottom',
          'font-size': 12,
          width: 35,
          height: 35,
        },
      },
      {
        selector: 'edge',
        style: {
          width: 2,
          'line-color': '#64748b',
          'curve-style': 'bezier',
        },
      },
      {
        selector: 'edge.overloaded',
        style: { 'line-color': '#e74c3c', width: 5, 'shadow-blur': 15, 'shadow-color': '#e74c3c', 'shadow-opacity': 0.9 },
      },
      {
        selector: 'edge.contingency-risk',
        style: { 'line-color': '#f39c12', width: 4, 'line-style': 'dashed', 'shadow-blur': 10, 'shadow-color': '#f39c12', 'shadow-opacity': 0.7 },
      },
      {
        selector: 'edge.line-tripped',
        style: { 'line-color': '#475569', 'line-style': 'dotted', opacity: 0.3, 'shadow-blur': 0 },
      },
    ],
  });
  installHoverTooltips();
  cy.on('tap', 'edge', (event) => {
    toggleLineState(event.target).catch((error) => console.error('Line action failed:', error));
  });
  return cy;
}

async function toggleLineState(edge) {
  if (edge.data('mutationPending') === true) return;
  const lineId = edge.id().replace(/^line/, '');
  if (!/^\d+$/.test(lineId)) throw new Error('Invalid line identifier');
  const wasTripped = edge.data('tripped') === true;
  const nextTripped = !wasTripped;
  edge.data('mutationPending', true);
  edge.data('tripped', nextTripped);
  applyLineClasses(latestGridState, window.latestContingency);
  const url = nextTripped
    ? `${API_URL}/inject_fault/${encodeURIComponent(lineId)}?grid=${encodeURIComponent(GRID_ID)}`
    : `${API_URL}/restore_line/${encodeURIComponent(GRID_ID)}/${encodeURIComponent(lineId)}`;
  try {
    const response = await fetch(url, { method: 'POST' });
    if (!response.ok) throw new Error(`Twin rejected line action (${response.status})`);
  } catch (error) {
    edge.data('tripped', wasTripped);
    applyLineClasses(latestGridState, window.latestContingency);
    throw error;
  } finally {
    edge.data('mutationPending', false);
  }
}

function metricById(collection, id) {
  if (Array.isArray(collection)) {
    return collection.find((item) => item && String(item.id) === String(id)) || {};
  }
  if (collection && typeof collection === 'object') return collection[String(id)] || {};
  return {};
}

function formatMetric(value, decimals) {
  return typeof value === 'number' && Number.isFinite(value)
    ? value.toFixed(decimals)
    : 'Unavailable';
}

function sumMetric(records, key) {
  if (!Array.isArray(records) || records.length === 0) return null;
  const values = records.map((record) => record?.[key]);
  if (values.some((value) => typeof value !== 'number' || !Number.isFinite(value))) return null;
  return values.reduce((sum, value) => sum + value, 0);
}

function maxMetric(records, key, absolute = false) {
  if (!Array.isArray(records)) return null;
  const values = records.map((record) => record?.[key]);
  if (values.length === 0 || values.some((value) => typeof value !== 'number' || !Number.isFinite(value))) return null;
  return Math.max(...values.map((value) => absolute ? Math.abs(value) : value));
}

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) element.textContent = value;
}

function renderLiveSummary(frame) {
  const demand = Number.isFinite(frame.total_demand_mw) ? frame.total_demand_mw : sumMetric(frame.loads, 'p_mw');
  const generation = Number.isFinite(frame.total_generation_mw) ? frame.total_generation_mw : null;
  const maxLoading = Number.isFinite(frame.max_line_loading_percent)
    ? frame.max_line_loading_percent : maxMetric(frame.lines, 'loading_percent');
  const maxVoltage = Number.isFinite(frame.max_voltage_pu) ? frame.max_voltage_pu : maxMetric(frame.buses, 'vm_pu', true);
  setText('statDemand', `${formatMetric(demand, 2)} MW`);
  setText('statGeneration', `${formatMetric(generation, 2)} MW`);
  setText('statMaxLoad', `${formatMetric(maxLoading, 1)}%`);
  setText('statVoltage', `${formatMetric(maxVoltage, 3)} p.u.`);
  setText('statStatus', typeof frame.simulation_status === 'string' ? frame.simulation_status : 'UNAVAILABLE');
  setText('statTimeStep', Number.isInteger(frame.time_step) ? `t=${frame.time_step}` : 'Unavailable');
  setText('statLastEvent', typeof frame.last_event === 'string' ? frame.last_event : 'Unavailable');
  setText('statScenario', typeof frame.scenario === 'string' ? frame.scenario : 'Unavailable');
}

function scoreClass(value, collapsed = false) {
  if (collapsed || typeof value !== 'number' || !Number.isFinite(value)) return 'badge-red';
  if (value < 50) return 'badge-red';
  if (value < 80) return 'badge-amber';
  return 'badge-green';
}

function renderResilience(frame) {
  const metrics = frame.resilience && typeof frame.resilience === 'object' ? frame.resilience : {};
  const collapsed = metrics.collapsed === true;
  const score = metrics.grid_resilience_index;
  const overall = document.getElementById('griScore');
  if (overall) {
    overall.textContent = collapsed
      ? `COLLAPSED · ${formatMetric(score, 2)}`
      : formatMetric(score, 2);
    overall.classList.remove('badge-green', 'badge-amber', 'badge-red');
    overall.classList.add(scoreClass(score, collapsed));
    overall.setAttribute('aria-label', collapsed ? 'Grid collapsed' : 'Grid resilience score');
  }
  setText('griVoltage', formatMetric(metrics.voltage_score, 1));
  setText('griLoading', formatMetric(metrics.loading_score, 1));
  setText('griSecurity', formatMetric(metrics.security_score, 1));
}

function showTooltip(lines, event) {
  const tooltip = document.getElementById('line-tooltip');
  if (!tooltip) return;
  tooltip.textContent = lines.join('\n');
  tooltip.style.whiteSpace = 'pre-line';
  tooltip.style.left = `${event.pageX}px`;
  tooltip.style.top = `${event.pageY}px`;
  tooltip.classList.remove('hidden');
}

function installHoverTooltips() {
  const tooltip = document.getElementById('line-tooltip');
  if (!tooltip || !cy) return;
  cy.on('mouseover', 'edge', (event) => {
    const edge = event.target;
    const lineId = edge.id().replace(/^line/, '');
    const line = metricById(latestGridState?.lines, lineId);
    const currentValues = [line.i_from_ka, line.i_to_ka].filter(
      (value) => typeof value === 'number' && Number.isFinite(value),
    );
    const current = currentValues.length ? Math.max(...currentValues) : null;
    showTooltip([
      `Line ${lineId}`,
      `Loading: ${formatMetric(line.loading_percent, 1)}%`,
      `Current: ${formatMetric(current, 2)} kA`,
      `Power factor: ${formatMetric(line.pf, 3)}`,
    ], event.originalEvent);
  });
  cy.on('mouseover', 'node', (event) => {
    const node = event.target;
    const busId = node.id();
    const bus = metricById(latestGridState?.buses, busId);
    const loads = latestGridState?.bus_loads;
    const load = loads && Object.prototype.hasOwnProperty.call(loads, busId) ? loads[busId] : null;
    showTooltip([
      `Bus ${busId}`,
      `Voltage: ${formatMetric(bus.vm_pu, 3)} p.u.`,
      `Angle: ${formatMetric(bus.va_degree, 1)}°`,
      `Live load: ${formatMetric(load, 2)} MW`,
    ], event.originalEvent);
  });
  cy.on('mousemove', 'edge, node', (event) => {
    tooltip.style.left = `${event.originalEvent.pageX}px`;
    tooltip.style.top = `${event.originalEvent.pageY}px`;
  });
  cy.on('mouseout', 'edge, node', () => tooltip.classList.add('hidden'));
}

function applyLineClasses(telemetry, contingency) {
  if (!cy || !Array.isArray(telemetry?.lines)) return;
  const lineMetrics = new Map(telemetry.lines
    .filter((line) => line && Number.isInteger(Number(line.id)))
    .map((line) => [String(line.id), line]));
  const contingencyLines = contingency?.lines && typeof contingency.lines === 'object'
    ? contingency.lines : {};
  cy.edges().forEach((edge) => {
    const lineId = edge.id().replace(/^line/, '');
    const measured = lineMetrics.get(lineId);
    const loading = measured?.loading_percent;
    const tripped = edge.data('tripped') === true || measured?.in_service === false;
    const overloaded = typeof loading === 'number' && Number.isFinite(loading) && loading > 100;
    const insecure = contingencyLines[lineId]?.secure === false;
    edge.removeClass('overloaded contingency-risk line-tripped');
    if (tripped) edge.addClass('line-tripped');
    else if (overloaded) edge.addClass('overloaded');
    else if (insecure) edge.addClass('contingency-risk');
  });
}

function scheduleTelemetryReconnect(generation) {
  if (generation !== socketGeneration || reconnectTimer !== null) return;
  const delay = Math.min(30000, 500 * (2 ** Math.min(reconnectAttempts, 6)));
  reconnectAttempts += 1;
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = null;
    if (generation === socketGeneration) connectTelemetry();
  }, delay);
}

function connectTelemetry() {
  if (!['39', '118'].includes(String(GRID_ID)) || typeof window.WebSocket !== 'function') return;
  if (reconnectTimer !== null) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  const generation = ++socketGeneration;
  const socketUrl = `${API_URL.replace(/^http/, 'ws')}/ws/telemetry/${encodeURIComponent(GRID_ID)}`;
  let socket;
  try {
    socket = new window.WebSocket(socketUrl);
  } catch (error) {
    scheduleTelemetryReconnect(generation);
    return;
  }
  telemetrySocket = socket;
  socket.onmessage = (event) => {
    if (generation !== socketGeneration || telemetrySocket !== socket) return;
    try {
      const frame = JSON.parse(event.data);
      if (!frame || String(frame.grid) !== String(GRID_ID) || !Array.isArray(frame.lines) || !Array.isArray(frame.buses)) return;
      latestGridState = frame;
      reconnectAttempts = 0;
      renderLiveSummary(frame);
      renderResilience(frame);
      applyLineClasses(frame, window.latestContingency);
    } catch (error) {
      console.error('Invalid telemetry frame');
    }
  };
  socket.onclose = () => {
    if (generation !== socketGeneration || telemetrySocket !== socket) return;
    telemetrySocket = null;
    scheduleTelemetryReconnect(generation);
  };
  socket.onerror = () => socket.close();
}

loadTopology()
  .then(connectTelemetry)
  .catch((error) => console.error('Could not load grid topology:', error));
