function publicServiceBase(configKey, globalKey, localPort) {
  const config = window.SWING_PUBLIC_CONFIG || {};
  let configured = config[configKey] || window[globalKey];
  const localPage = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
  if (!configured && localPage) configured = `http://127.0.0.1:${localPort}`;
  if (typeof configured !== 'string' || !configured.trim()) throw new Error(`Public ${configKey} is not configured`);
  const url = new URL(configured, window.location.href);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error(`Invalid public ${configKey}`);
  if (!localPage && (url.protocol !== 'https:' || ['localhost', '127.0.0.1', '::1'].includes(url.hostname))) {
    throw new Error(`Hosted ${configKey} must use a public HTTPS URL`);
  }
  return url.href.replace(/\/+$/, '');
}

const AI_API_URL = publicServiceBase('agentApiBase', 'SWING_PUBLIC_AGENT_API_BASE', 8002);
let forecastChart = null;

function getSelectedGrid() {
  return document.getElementById("gridSelect").value;
}

function initChart() {
  const ctx = document.getElementById('forecastChart').getContext('2d');

  // Initialize an empty chart
  forecastChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['Now', '+1 Hour', '+2 Hours', '+6 Hours', '+24 Hours'],
      datasets: []
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { color: '#aaa' } },
        tooltip: { backgroundColor: 'rgba(0,0,0,0.8)' }
      },
      scales: {
        x: { grid: { color: '#333' }, ticks: { color: '#888' } },
        y: {
            grid: { color: '#333' },
            ticks: { color: '#888' },
            title: { display: true, text: 'Demand (MW)', color: '#888' }
        }
      }
    }
  });
}

function finiteForecastValue(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function buildQuantileDatasets(forecast) {
  const bounds = forecast?.bounds && typeof forecast.bounds === 'object' ? forecast.bounds : {};
  const horizons = forecast?.source === 'TFT' ? ['1h', '2h', '6h', '24h'] : ['1h'];
  const points = (quantile) => [null, ...['1h', '2h', '6h', '24h'].map((horizon) =>
    horizons.includes(horizon) ? finiteForecastValue(bounds[`${quantile}_${horizon}`]) : null,
  )];
  return [
    { label: 'P90 (High Risk)', data: points('p90'), borderColor: '#ff4757', backgroundColor: 'rgba(255, 71, 87, 0.1)', fill: 1, tension: 0.4 },
    { label: 'P50 (Expected)', data: points('p50'), borderColor: '#00d4ff', backgroundColor: 'transparent', borderDash: [5, 5], tension: 0.4 },
    { label: 'P10 (Low Risk)', data: points('p10'), borderColor: '#2ed573', backgroundColor: 'rgba(0, 212, 255, 0.1)', fill: 1, tension: 0.4 },
  ];
}

function renderForecast(forecast) {
  const source = forecast?.source;
  const label = source === 'TFT' ? 'TFT (multi-horizon)' : source === 'LIGHTGBM' ? 'LightGBM (next hour only)' : 'Forecast unavailable';
  document.getElementById('modelSource').textContent = label;
  forecastChart.data.datasets = source === 'TFT' || source === 'LIGHTGBM' ? buildQuantileDatasets(forecast) : [];
  forecastChart.update();
}

function fetchAndRenderForecast() {
  const btn = document.getElementById("refreshForecastBtn");
  btn.disabled = true;
  btn.textContent = "Running Inference...";

  // Clearly labeled demo features until live forecast telemetry is available.
  const mockTelemetry = {
    hour_sin: 0.5, hour_cos: 0.5, dayofweek: 3, month: 7,
    load_lag_1: 0.85, load_lag_2: 0.86, load_lag_24: 0.82, Northern_Region_Avg_T2M: 32.5
  };

  fetch(`${AI_API_URL}/propose/${getSelectedGrid()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ telemetry: mockTelemetry })
  })
    .then(async (response) => {
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Forecast request failed (${response.status})`);
      renderForecast(data.forecast);
    })
    .catch((error) => {
      document.getElementById('modelSource').textContent = `Forecast unavailable: ${error.message}`;
      forecastChart.data.datasets = [];
      forecastChart.update();
    })
    .finally(() => {
      btn.disabled = false;
      btn.textContent = "Pull Latest Forecast";
    });
}

window.addEventListener("DOMContentLoaded", () => {
  initChart();
  document.getElementById("refreshForecastBtn").addEventListener("click", fetchAndRenderForecast);
  document.getElementById("gridSelect").addEventListener("change", fetchAndRenderForecast);

  // Auto-fetch on load
  fetchAndRenderForecast();
});
