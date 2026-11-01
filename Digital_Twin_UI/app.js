/* Digital Twin visualization only. window.GRID_ID is set by the page. */
const GRID_ID = window.GRID_ID;
const API_URL = "http://127.0.0.1:8001";
let cy = null;

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
  return cy;
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

loadTopology().catch((error) => console.error('Could not load grid topology:', error));
