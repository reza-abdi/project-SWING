import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import path from 'node:path';

const root = process.cwd();
const agentOrigin = 'http://agent.local';

async function serveAgent(page) {
  await page.route('https://cdn.jsdelivr.net/**', (route) =>
    route.fulfill({ contentType: 'text/javascript', body: '/* Chart is stubbed by addInitScript. */' }),
  );
  await page.route(`${agentOrigin}/**`, async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const file = path.join(root, 'Agent_Dashboard_UI', pathname === '/' ? 'ai_home.html' : pathname.slice(1));
    try {
      const body = await readFile(file);
      const contentType = file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : file.endsWith('.png') ? 'image/png' : 'text/html';
      await route.fulfill({ status: 200, contentType, body });
    } catch {
      await route.fulfill({ status: 404, body: 'not found' });
    }
  });
  await page.addInitScript(() => {
    (window as any).SWING_PUBLIC_CONFIG = {
      agentApiBase: 'http://agent-api.local', twinApiBase: 'http://twin-api.local',
    };
    (window as any).Chart = class {
      data: any;
      constructor(_ctx, config) { this.data = config.data; }
      update() {}
    };
  });
}

test('agent home links to each dashboard page', async ({ page }) => {
  await serveAgent(page);
  await page.goto(`${agentOrigin}/`);
  for (const file of ['ai_dashboard.html', 'ai_chat.html', 'ai_forecast.html', 'ai_rl_status.html']) {
    await expect(page.locator(`a[href="${file}"]`)).toBeVisible();
  }
});

test('forecast page uses the read-only endpoint and renders its model source', async ({ page }) => {
  await serveAgent(page);
  let proposeCalls = 0;
  await page.route('http://agent-api.local/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/propose/')) proposeCalls += 1;
    if (url.pathname.startsWith('/forecast/')) {
      return route.fulfill({ status: 200, json: { forecast: { source: 'LIGHTGBM', bounds: { p50_1h: 100, p10_1h: 90, p90_1h: 110 } } } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  await page.goto(`${agentOrigin}/ai_forecast.html`);
  await expect(page.locator('#modelSource')).toContainText('LightGBM');
  expect(proposeCalls).toBe(0);
});

test('RL page displays trained and unavailable policy states from Twin status', async ({ page }) => {
  await serveAgent(page);
  await page.route('http://twin-api.local/rl_status', (route) => route.fulfill({ status: 200, json: {
    '39': { shed_load: { trained: true, size_kb: 12.5, last_trained: '2026-01-01T00:00:00Z' }, redispatch_gen: { trained: false, error: 'missing' } },
    '118': { shed_load: { trained: false, error: 'invalid_or_incompatible_archive' }, redispatch_gen: { trained: false, error: 'missing' } },
  } }));
  await page.goto(`${agentOrigin}/ai_rl_status.html`);
  await expect(page.locator('#policyGrid')).toContainText('Trained and active');
  await expect(page.locator('#policyGrid')).toContainText('Incompatible or unavailable');
  await expect(page.locator('#policyGrid')).toContainText('Size: 12.5 KB');
});

test('dashboard proposal failure is rendered as text', async ({ page }) => {
  await serveAgent(page);
  await page.route('http://agent-api.local/propose/**', (route) => route.fulfill({ status: 503, json: { detail: 'offline' } }));
  await page.goto(`${agentOrigin}/ai_dashboard.html`);
  await page.locator('#checkRisksBtn').click();
  await expect(page.locator('#agentBriefText')).toContainText('offline');
});
