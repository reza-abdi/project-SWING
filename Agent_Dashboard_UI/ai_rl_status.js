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
  const fragment = document.createDocumentFragment();

  for (const grid of Object.keys(GRID_LABELS)) {
    for (const action of Object.keys(ACTION_LABELS)) {
      const info = status?.[grid]?.[action.toLowerCase()] || status?.[grid]?.[action] || { error: "missing" };
      const card = document.createElement("div");
      card.className = "policy-card";
      const heading = document.createElement("h3");
      heading.textContent = `${GRID_LABELS[grid]} -- ${ACTION_LABELS[action]}`;
      card.append(heading);

      const state = document.createElement("div");
      state.className = `status-line ${info.trained ? "badge-green" : info.error === "missing" ? "badge-amber" : "badge-red"}`;
      state.textContent = info.trained ? "● Trained and active" : info.error === "missing" ? "● Not trained yet" : "● Incompatible or unavailable";
      card.append(state);
      if (info.trained) {
        const size = document.createElement("div");
        size.className = "status-line";
        size.textContent = Number.isFinite(info.size_kb) ? `Size: ${info.size_kb} KB` : "Size: unavailable";
        const trained = document.createElement("div");
        trained.className = "status-line";
        const timestamp = Date.parse(info.last_trained || "");
        trained.textContent = Number.isFinite(timestamp) ? `Last trained: ${new Date(timestamp).toLocaleString()}` : "Last trained: unavailable";
        card.append(size, trained);
      } else {
        const detail = document.createElement("div");
        detail.className = "status-line";
        detail.textContent = "Falling back to bisection search for this combination.";
        card.append(detail);
      }
      fragment.append(card);
    }
  }

  el.replaceChildren(fragment);
}

window.addEventListener("DOMContentLoaded", () => {
  fetch(`${DIGITAL_TWIN_API_URL}/rl_status`)
    .then(res => { if (!res.ok) throw new Error("RL status request failed"); return res.json(); })
    .then(status => renderPolicyGrid(status))
    .catch(() => {
      const message = document.createElement("p");
      message.className = "status-line badge-red";
      message.textContent = "Could not reach the Digital Twin API.";
      document.getElementById("policyGrid").replaceChildren(message);
    });
});
