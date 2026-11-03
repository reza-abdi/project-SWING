/* ============================================================
   AI Architecture Dashboard - talks ONLY to agent_api.py (:8002).
   This is intentionally its own file/page, separate from the Digital
   Twin's app.js: the Digital Twin dashboards should be usable as a pure
   physics test harness with no AI concepts anywhere in them, and this
   page should be usable (in principle) against ANY digital twin that
   implements the same /validate_action, /optimize_action, /change_load,
   /redispatch_gen contract -- not just this one.
   ============================================================ */

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

function getSelectedGrid() {
  return document.getElementById("gridSelect").value;
}

// ------------------------------------------------------------
// RUN THE AGENT PIPELINE
// ------------------------------------------------------------
function initCheckRisks() {
  document.getElementById("checkRisksBtn").addEventListener("click", () => {
    const btn = document.getElementById("checkRisksBtn");
    const loader = document.getElementById("agentLoader");
    const briefContainer = document.getElementById("agentBriefContainer");


    btn.disabled = true;
    loader.classList.remove("hidden"); // Show the thinking animation
    briefContainer.classList.add("hidden"); // Hide previous results

    btn.textContent = "Running Agent Pipeline...";
    loader.setAttribute('aria-label', 'Running with clearly labeled demo telemetry values');

    const now = new Date();
    const mockTelemetry = {
      hour_sin: Math.sin(2 * Math.PI * now.getHours() / 24),
      hour_cos: Math.cos(2 * Math.PI * now.getHours() / 24),
      dayofweek: now.getDay(),
      month: now.getMonth() + 1,
      load_lag_1: 0.85,
      load_lag_2: 0.86,
      load_lag_24: 0.82,
      Northern_Region_Avg_T2M: 32.5
    };

    fetch(`${AI_API_URL}/propose/${getSelectedGrid()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ telemetry: mockTelemetry })
    })
      .then(async (res) => {
        let data;
        try { data = await res.json(); } catch (_error) { throw new Error(`AI service returned invalid JSON (${res.status})`); }
        if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `AI service request failed (${res.status})`);
        return data;
      })
      .then((data) => {
        renderAgentProposal(data);
        loadEventTimeline(); // the propose call just logged an event -- reflect it
      })
      .catch((error) => {
        const container = document.getElementById('agentBriefContainer');
        container.classList.remove('hidden');
        document.getElementById('agentDecision').textContent = 'AGENT_UNAVAILABLE';
        document.getElementById('agentBriefText').textContent = `Decision support failed: ${error.message}`;
        document.getElementById('agentPillRow').classList.add('hidden');
      })
      .finally(() => {
        btn.disabled = false;
        loader.classList.add("hidden"); // Hide the thinking animation
        btn.textContent = "Check for Risks";
      });
  });
}

function renderAgentProposal(proposal) {
  const container = document.getElementById("agentBriefContainer");
  container.classList.remove("hidden");
  document.getElementById("agentDecision").textContent = typeof proposal.decision === 'string' ? proposal.decision : 'UNKNOWN';
  document.getElementById("agentBriefText").textContent = typeof proposal.operator_brief === 'string'
    ? proposal.operator_brief : 'No operator brief is available.';

  renderForecastSource(proposal.forecast || { source: proposal.forecast_source, bounds: proposal.forecast_bounds });
  renderShapBars(proposal.feature_importance);
  renderGriBar(proposal.validation || proposal.validation_result);

  const pillRow = document.getElementById("agentPillRow");
  const validation = proposal.validation || proposal.validation_result;
  const activeAction = proposal.proposed_action && proposal.proposed_action.action_type !== "NO_ACTION";
  const awaitingReview = proposal.decision === 'PENDING_OPERATOR_APPROVAL'
    && typeof proposal.proposal_id === 'string' && proposal.proposal_id.length > 0;
  if (activeAction && validation?.valid === true && awaitingReview) {
    pillRow.classList.remove("hidden");
    const approveBtn = document.getElementById("approveBtn");
    approveBtn.disabled = false;
    approveBtn.dataset.proposalId = proposal.proposal_id;
    approveBtn.dataset.gridId = getSelectedGrid();
    approveBtn.className = "action-btn btn-green";
  } else {
    pillRow.classList.add("hidden");
    const approveBtn = document.getElementById("approveBtn");
    approveBtn.disabled = true;
    delete approveBtn.dataset.proposalId;
    delete approveBtn.dataset.gridId;
  }
}

function renderForecastSource(forecast) {
  const el = document.getElementById("forecastSourceBadge");
  el.replaceChildren();
  const source = forecast?.source;
  const bounds = forecast?.bounds && typeof forecast.bounds === 'object' ? forecast.bounds : {};
  if (source !== 'TFT' && source !== 'LIGHTGBM') {
    el.textContent = 'Forecast unavailable.';
    return;
  }
  const isTft = source === 'TFT';
  const heading = document.createElement('div');
  heading.className = isTft ? 'badge-green' : 'badge-amber';
  heading.style.cssText = 'font-size:11px;margin-bottom:10px;';
  heading.textContent = isTft ? 'TFT · multi-horizon P90' : 'LightGBM · next-hour P90';
  el.appendChild(heading);
  const values = document.createElement('div');
  values.style.cssText = 'display:flex;gap:10px;font-size:12px;color:var(--text-dim);background:#2a2a2a;padding:10px;border-radius:6px;';
  const horizons = isTft ? [['1 hour', 'p90_1h'], ['2 hours', 'p90_2h'], ['6 hours', 'p90_6h'], ['24 hours', 'p90_24h']] : [['1 hour', 'p90_1h']];
  for (const [label, key] of horizons) {
    const item = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = `${label}:`;
    const measurement = document.createElement('span');
    measurement.style.color = '#fff';
    const value = bounds[key];
    measurement.textContent = typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)} MW` : 'Unavailable';
    item.append(name, document.createElement('br'), measurement);
    values.appendChild(item);
  }
  el.appendChild(values);
}

function renderShapBars(featureImportance) {
  const el = document.getElementById("shapBars");
  const ranked = Array.isArray(featureImportance?.ranked_features)
    ? featureImportance.ranked_features.filter((item) => Array.isArray(item) && typeof item[0] === 'string' && typeof item[1] === 'number' && Number.isFinite(item[1])).slice(0, 5)
    : [];
  el.replaceChildren();
  if (!ranked.length) {
    const empty = document.createElement('p');
    empty.className = 'gri-sub';
    empty.textContent = 'No feature importance available for this run.';
    el.appendChild(empty);
    return;
  }

  const maxAbs = Math.max(...ranked.map(([, value]) => Math.abs(value)));
  for (const [name, value] of ranked) {
    const pct = maxAbs > 0 ? (Math.abs(value) / maxAbs) * 100 : 0;
    const row = document.createElement('div');
    row.style.marginBottom = '8px';
    const labelRow = document.createElement('div');
    labelRow.style.cssText = 'display:flex;justify-content:space-between;font-size:12px;color:var(--text-dim);margin-bottom:3px;';
    const nameNode = document.createElement('span');
    nameNode.textContent = name;
    const valueNode = document.createElement('span');
    valueNode.textContent = `${value >= 0 ? '+' : ''}${value.toFixed(2)} MW`;
    labelRow.append(nameNode, valueNode);
    const track = document.createElement('div');
    track.style.cssText = 'background:#2a2a2a;border-radius:3px;height:6px;overflow:hidden;';
    const bar = document.createElement('div');
    bar.style.width = `${pct}%`;
    bar.style.height = '100%';
    bar.style.backgroundColor = value >= 0 ? 'var(--accent-red)' : 'var(--accent-cyan)';
    track.appendChild(bar);
    row.append(labelRow, track);
    el.appendChild(row);
  }
}

function renderGriBar(validationResult) {
  const el = document.getElementById("griBarContainer");
  el.replaceChildren();
  const before = validationResult?.gri_before;
  const after = validationResult?.gri_after;
  const improvement = validationResult?.gri_improvement;
  const finiteBefore = typeof before === 'number' && Number.isFinite(before);
  const finiteAfter = typeof after === 'number' && Number.isFinite(after);
  const finiteChange = typeof improvement === 'number' && Number.isFinite(improvement);
  if (!finiteBefore) {
    el.textContent = 'Grid resilience measurements are unavailable.';
    return;
  }

  const row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:center;gap:14px;margin-top:6px;';
  const makeValue = (label, value, color) => {
    const group = document.createElement('div');
    group.style.textAlign = 'center';
    const heading = document.createElement('div');
    heading.style.cssText = 'font-size:11px;color:var(--text-dim);';
    heading.textContent = label;
    const number = document.createElement('div');
    number.style.cssText = `font-size:20px;font-weight:bold;color:${color};`;
    number.textContent = value === null ? 'N/A' : value.toFixed(1);
    group.append(heading, number);
    return group;
  };
  row.appendChild(makeValue('BEFORE', before, 'var(--text-primary)'));
  const arrow = document.createElement('span');
  arrow.textContent = '→';
  arrow.style.color = 'var(--text-dim)';
  row.appendChild(arrow);
  row.appendChild(makeValue('AFTER', finiteAfter ? after : null, finiteChange && improvement > 0 ? 'var(--accent-green)' : finiteChange && improvement < 0 ? 'var(--accent-red)' : 'var(--accent-amber)'));
  const change = document.createElement('span');
  change.textContent = finiteChange ? `${improvement >= 0 ? '+' : ''}${improvement.toFixed(1)}` : 'Change unavailable';
  change.style.cssText = `font-size:13px;color:${finiteChange && improvement > 0 ? 'var(--accent-green)' : finiteChange && improvement < 0 ? 'var(--accent-red)' : 'var(--accent-amber)'};`;
  row.appendChild(change);
  el.appendChild(row);
}

function initAgentActions() {
  document.getElementById("approveBtn").addEventListener("click", () => {
    fetch(`${AI_API_URL}/execute/${getSelectedGrid()}`, { method: "POST" })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Execution failed");
        return data;
      })
      .then(data => {
        alert(`Executed: ${JSON.stringify(data.action)}`);
        document.getElementById("agentBriefContainer").classList.add("hidden");
        loadEventTimeline();
      })
      .catch(err => alert(`EXECUTION FAILED: ${err.message}`));
  });

  document.getElementById("rejectBtn").addEventListener("click", () => {
    document.getElementById("agentBriefContainer").classList.add("hidden");
  });
}

// ------------------------------------------------------------
// EVENT TIMELINE
// ------------------------------------------------------------
function loadEventTimeline() {
  const el = document.getElementById("eventTimeline");
  fetch(`${AI_API_URL}/events/${getSelectedGrid()}?limit=30`)
    .then(res => res.json())
    .then(data => {
      const events = data.events || [];
      if (!events.length) {
        el.innerHTML = `<p class="gri-sub">No events yet for this grid.</p>`;
        return;
      }
      el.innerHTML = events.map(ev => {
        const date = new Date(ev.timestamp * 1000).toLocaleTimeString();
        const payloadSummary = JSON.stringify(ev.payload).slice(0, 120);
        return `
          <div class="timeline-entry source-${ev.source}">
            <span class="ts">${date}</span> --
            <span class="type">${ev.event_type}</span>
            <span class="gri-sub">(${ev.source})</span>
            <div class="gri-sub">${payloadSummary}</div>
          </div>
        `;
      }).join("");
    })
    .catch(() => {
      el.innerHTML = `<p class="gri-sub badge-red">Could not load event timeline.</p>`;
    });
}

// ------------------------------------------------------------
// BOOTSTRAP
// ------------------------------------------------------------
window.addEventListener("DOMContentLoaded", () => {
  initCheckRisks();
  initAgentActions();
  document.getElementById("refreshEventsBtn").addEventListener("click", loadEventTimeline);
  document.getElementById("gridSelect").addEventListener("change", () => {
    document.getElementById("agentBriefContainer").classList.add("hidden");
    loadEventTimeline();
  });
  loadEventTimeline();
});
