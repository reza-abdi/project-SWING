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

const DIGITAL_TWIN_API_URL = publicServiceBase('twinApiBase', 'SWING_PUBLIC_TWIN_API_BASE', 8001);

const GRID_LABELS = { "39": "IEEE 39", "118": "IEEE 118" };
const ACTION_LABELS = { "shed_load": "SHED_LOAD", "redispatch_gen": "REDISPATCH_GEN" };

function renderPolicyGrid(status) {
  const el = document.getElementById("policyGrid");
  let html = "";

  for (const grid of Object.keys(GRID_LABELS)) {
    for (const action of Object.keys(ACTION_LABELS)) {
      const info = status[grid]?.[action] || { trained: false };
      html += `
        <div class="policy-card">
          <h3>${GRID_LABELS[grid]} -- ${ACTION_LABELS[action]}</h3>
          ${info.trained
            ? `
              <div class="status-line badge-green">&#9679; Trained and active</div>
              <div class="status-line">Size: ${info.size_kb} KB</div>
              <div class="status-line">Last trained: ${new Date(info.last_trained).toLocaleString()}</div>
            `
            : `
              <div class="status-line badge-amber">&#9679; Not trained yet</div>
              <div class="status-line">Falling back to bisection search for this combination.</div>
            `
          }
        </div>
      `;
    }
  }

  el.innerHTML = html;
}

window.addEventListener("DOMContentLoaded", () => {
  fetch(`${DIGITAL_TWIN_API_URL}/rl_status`)
    .then(res => res.json())
    .then(status => renderPolicyGrid(status))
    .catch(() => {
      document.getElementById("policyGrid").innerHTML =
        `<p class="status-line badge-red">Could not reach the Digital Twin API -- is api.py running?</p>`;
    });
});
