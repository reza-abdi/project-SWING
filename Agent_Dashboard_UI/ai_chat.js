function publicServiceBase(configKey, globalKey, localPort) {
  const config = window.SWING_PUBLIC_CONFIG || {};
  let configured = config[configKey] || window[globalKey];
  const localPage = ['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
  if (!configured && localPage) configured = `http://127.0.0.1:${localPort}`;
  if (!configured && !localPage) configured = new URL(configKey === 'agentApiBase' ? '/api/agent' : '/api/twin', window.location.origin).href;
  if (typeof configured !== 'string' || !configured.trim()) throw new Error(`Public ${configKey} is not configured`);
  const url = new URL(configured, window.location.href);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error(`Invalid public ${configKey}`);
  if (!localPage && (url.protocol !== 'https:' || ['localhost', '127.0.0.1', '::1'].includes(url.hostname))) {
    throw new Error(`Hosted ${configKey} must use a public HTTPS URL`);
  }
  return url.href.replace(/\/+$/, '');
}

const AI_API_URL = publicServiceBase('agentApiBase', 'SWING_PUBLIC_AGENT_API_BASE', 8002);

let chatHistory = [];
let chatGeneration = 0;
let pendingChatController = null;

function getSelectedGrid() {
  return document.getElementById("gridSelect").value;
}

function appendMessage(role, content) {
  const chatWindowEl = document.getElementById("chatWindow");
  const div = document.createElement("div");
  const safeRole = role === 'user' ? 'user' : 'assistant';
  div.className = `chat-msg ${safeRole}`;
  const label = document.createElement('div');
  label.className = 'label';
  label.textContent = safeRole === 'user' ? 'YOU' : 'AGENT';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = String(content ?? '');
  div.append(label, bubble);
  chatWindowEl.appendChild(div);
  chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}

function appendChatError(message) {
  const chatWindowEl = document.getElementById('chatWindow');
  const error = document.createElement('div');
  error.className = 'chat-error badge-red';
  error.setAttribute('role', 'alert');
  error.textContent = `Chat service error: ${message}`;
  chatWindowEl.appendChild(error);
  chatWindowEl.scrollTop = chatWindowEl.scrollHeight;
}

async function sendMessage(messageOverride) {
  const input = document.getElementById("chatInput");
  const btn = document.getElementById("sendBtn");
  const message = typeof messageOverride === 'string' ? messageOverride.trim() : input.value.trim();
  if (!message || btn.disabled) return;
  if (message.length > 4000) {
    appendChatError('Please keep messages under 4,000 characters.');
    return;
  }

  appendMessage("user", message);
  chatHistory.push({ role: "user", content: message });
  chatHistory = chatHistory.slice(-20);
  input.value = "";
  btn.disabled = true;
  btn.textContent = "Thinking...";
  input.disabled = true;
  const controller = new AbortController();
  const generation = chatGeneration;
  const requestGrid = getSelectedGrid();
  pendingChatController = controller;
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(`${AI_API_URL}/chat/${requestGrid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history: chatHistory.slice(-20) }),
      signal: controller.signal,
    });
    let data;
    try { data = await response.json(); } catch (_error) { throw new Error('The service returned an invalid response.'); }
    if (generation !== chatGeneration) return;
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    if (typeof data.answer !== 'string' || !data.answer.trim()) throw new Error('The service returned no answer.');
    appendMessage('assistant', data.answer);
    chatHistory.push({ role: 'assistant', content: data.answer });
    chatHistory = chatHistory.slice(-20);
  } catch (error) {
    if (generation === chatGeneration) {
      appendChatError(error.name === 'AbortError' ? 'The request timed out. Please try again.' : error.message);
    }
  } finally {
    window.clearTimeout(timeout);
    if (generation === chatGeneration) {
      pendingChatController = null;
      btn.disabled = false;
      input.disabled = false;
      btn.textContent = 'Send';
    }
  }
}

function resetChatForGrid() {
  chatGeneration += 1;
  if (pendingChatController) pendingChatController.abort();
  pendingChatController = null;
  chatHistory = [];
  const input = document.getElementById('chatInput');
  input.value = '';
  input.disabled = false;
  const button = document.getElementById('sendBtn');
  button.disabled = false;
  button.textContent = 'Send';
  document.getElementById('chatWindow').replaceChildren();
  appendMessage('assistant', `Switched to IEEE ${getSelectedGrid()} context. Ask me about this grid.`);
}

window.addEventListener("DOMContentLoaded", () => {
  document.getElementById("sendBtn").addEventListener("click", () => sendMessage());
  document.getElementById("chatInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") sendMessage();
  });
  document.querySelectorAll(".suggestion-chip").forEach(chip => {
    chip.addEventListener("click", () => sendMessage(chip.dataset.q));
  });
  document.getElementById("gridSelect").addEventListener("change", () => {
    resetChatForGrid();
  });
});
