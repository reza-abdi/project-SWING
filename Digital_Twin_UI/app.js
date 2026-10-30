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
    ],
  });
  return cy;
}

loadTopology().catch((error) => console.error('Could not load grid topology:', error));
