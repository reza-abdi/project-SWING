import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

declare global {
  interface Window {
    __graph: any;
    MockWebSocket: any;
    toggleLineState: any;
  }
}

const root = process.cwd();
const apiOrigin = 'http://twin.local/api/twin';

const cytoscapeStub = `
(() => {
  class Element {
    constructor(item) { this.values = { ...item.data }; this.classes = new Set(); }
    id() { return String(this.values.id); }
    data(key, value) { if (arguments.length === 2) this.values[key] = value; return this.values[key]; }
    addClass(names) { names.split(' ').forEach((name) => this.classes.add(name)); }
    removeClass(names) { names.split(' ').forEach((name) => this.classes.delete(name)); }
    hasClass(name) { return this.classes.has(name); }
    empty() { return false; }
  }
  window.cytoscape = (config) => {
    const nodes = config.elements.filter((item) => item.data.node_type).map((item) => new Element(item));
    const edges = config.elements.filter((item) => item.data.source).map((item) => new Element(item));
    const handlers = new Map();
    const graph = {
      nodes: () => nodes,
      edges: () => edges,
      getElementById: (id) => edges.find((edge) => edge.id() === id) || ({ empty: () => true }),
      on: (type, selector, callback) => handlers.set(type + ':' + selector, callback),
      fire: (type, selector, target) => handlers.get(type + ':' + selector)?.({ target, originalEvent: { pageX: 10, pageY: 20 } }),
      edge: (id) => edges.find((edge) => edge.id() === id),
      node: (id) => nodes.find((node) => node.id() === id),
    };
    window.__graph = graph;
    return graph;
  };
})();`;

async function installTwinMocks(page) {
  let stressBody;
  await page.addInitScript(() => {
    class MockWebSocket {
      static latest;
      constructor(url) { this.url = url; MockWebSocket.latest = this; setTimeout(() => this.onopen?.({}), 0); }
      sendFrame(data) { this.onmessage?.({ data: JSON.stringify(data) }); }
      close() { this.onclose?.({}); }
    }
    (window as any).WebSocket = MockWebSocket;
    window.MockWebSocket = MockWebSocket;
  });
  await page.route('https://cdnjs.cloudflare.com/**', (route) => route.fulfill({ contentType: 'text/javascript', body: cytoscapeStub }));
  await page.route('http://twin.local/**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const file = path.join(root, 'Digital_Twin_UI', pathname === '/' ? 'home.html' : pathname.slice(1));
    try {
      const body = await readFile(file);
      const contentType = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html';
      await route.fulfill({ status: 200, contentType, body });
    } catch {
      await route.fulfill({ status: 404, body: 'not found' });
    }
  });
  await page.route(`${apiOrigin}/**`, async (route) => {
    const url = new URL(route.request().url());
    url.pathname = url.pathname.replace(/^\/api\/twin/, '') || '/';
    const headers = { 'access-control-allow-origin': 'http://twin.local', 'access-control-allow-methods': 'GET,POST,OPTIONS', 'access-control-allow-headers': 'Content-Type' };
    if (route.request().method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (url.pathname === '/topology') {
      const busCount = url.searchParams.get('grid') === '39' ? 39 : 118;
      const nodes = Array.from({ length: busCount }, (_, index) => ({ data: { id: String(index + 1), label: `Bus ${index + 1}`, node_type: index === 0 ? 'LOAD' : 'JUNCTION' } }));
      const edges = [{ data: { id: 'line1', source: '1', target: '2' } }];
      return route.fulfill({ status: 200, headers, json: { nodes, edges } });
    }
    if (url.pathname.startsWith('/contingency/')) return route.fulfill({ status: 200, headers, json: { status: 'fresh', n_minus_1_secure: true, insecure_contingency_count: 0, lines: {}, generators: {} } });
    if (url.pathname.startsWith('/inject_fault/')) return route.fulfill({ status: 400, headers, json: { detail: 'fault rejected' } });
    if (url.pathname.startsWith('/change_load/')) return route.fulfill({ status: 422, headers, json: { detail: 'load command rejected' } });
    if (url.pathname.startsWith('/stress_test/')) {
      stressBody = route.request().postDataJSON();
      return route.fulfill({ status: 200, headers, json: { status: 'Stress Test Applied', grid_resilience_index: 73.2 } });
    }
    return route.fulfill({ status: 404, headers, json: { detail: 'not found' } });
  });
  return () => stressBody;
}

test('home links open both topology dashboards and draw the selected topology', async ({ page }) => {
  await installTwinMocks(page);
  await page.goto('http://twin.local/');
  await expect(page.locator('a[href="ieee39.html"]')).toBeVisible();
  await expect(page.locator('a[href="ieee118.html"]')).toBeVisible();
  await page.goto('http://twin.local/ieee39.html');
  await expect.poll(() => page.evaluate(() => window.__graph?.nodes().length)).toBe(39);
  await page.goto('http://twin.local/ieee118.html');
  await expect.poll(() => page.evaluate(() => window.__graph?.nodes().length)).toBe(118);
});

test('telemetry updates summary, resilience, line state and demand highlights', async ({ page }) => {
  await installTwinMocks(page);
  await page.goto('http://twin.local/ieee39.html');
  await expect.poll(() => page.evaluate(() => window.__graph)).toBeTruthy();
  await page.evaluate(() => window.MockWebSocket.latest.sendFrame({
    grid: '39', time_step: 7, simulation_status: 'RUNNING', scenario: 'Baseline', last_event: 'baseline',
    total_demand_mw: 245, total_generation_mw: 250, max_line_loading_percent: 105, max_voltage_pu: 1.04,
    lines: [{ id: 1, loading_percent: 105, i_from_ka: 1.2, i_to_ka: 1.1 }],
    buses: [{ id: 1, vm_pu: 1.04, va_degree: 2.5 }], bus_loads: { '1': 100, '2': 90 },
    resilience: { grid_resilience_index: 72, voltage_score: 90, loading_score: 60, security_score: 70, collapsed: false },
  }));
  await expect(page.locator('#statDemand')).toHaveText('245.00 MW');
  await expect(page.locator('#statGeneration')).toHaveText('250.00 MW');
  await expect(page.locator('#griScore')).toHaveText('72.00');
  expect(await page.evaluate(() => window.__graph.edge('line1').hasClass('overloaded'))).toBeTruthy();
  expect(await page.evaluate(() => window.__graph.node('1').hasClass('high-demand'))).toBeTruthy();
  await page.evaluate(() => window.toggleLineState(window.__graph.edge('line1')).catch(() => {}));
  expect(await page.evaluate(() => window.__graph.edge('line1').data('tripped'))).toBe(false);
});

test('load failure and stress sliders submit bounded API payloads once', async ({ page }) => {
  const getStressBody = await installTwinMocks(page);
  await page.goto('http://twin.local/ieee39.html');
  await expect.poll(() => page.evaluate(() => window.__graph)).toBeTruthy();
  await page.locator('#busSelect').selectOption('1');
  await page.locator('#loadInput').fill('42');
  await page.locator('#applyLoadBtn').click();
  await expect(page.locator('#loadCommandResult')).toContainText('load command rejected');
  await page.locator('#loadSlider').evaluate((element: HTMLInputElement) => { element.value = '150'; element.dispatchEvent(new Event('input', { bubbles: true })); });
  await page.locator('#derateSlider').evaluate((element: HTMLInputElement) => { element.value = '15'; element.dispatchEvent(new Event('input', { bubbles: true })); });
  await page.locator('#applyStressBtn').click();
  await expect(page.locator('#stressResult')).toContainText('load 150%, line capacity 15%');
  const body = getStressBody();
  expect(body).toEqual({ load_multiplier: 1.5, derate_multiplier: 0.15 });
});
