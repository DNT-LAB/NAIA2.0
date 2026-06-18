const DEFAULT_MODEL = 'hf.co/HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q4_K_M';

function shortOllamaModel(full) {
  const s = String(full || '');
  const colon = s.lastIndexOf(':');
  const quant = colon >= 0 ? s.slice(colon + 1) : '';
  let name = colon >= 0 ? s.slice(0, colon) : s;
  name = name.split('/').pop() || name;
  return quant ? `${name}:${quant}` : name;
}

function normalizeOllamaModel(value) {
  return String(value || '').trim() || DEFAULT_MODEL;
}

async function fetchOllamaJson(win, url, options) {
  const response = await win.fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  return {status: response.status, payload: payload || {}};
}

async function fetchOllamaConnection(win) {
  return fetchOllamaJson(win, '/api/ollama/connection');
}

async function fetchOllamaStatus(win, {fresh = false} = {}) {
  return fetchOllamaJson(win, `/api/ollama/status?fresh=${fresh ? 1 : 0}`);
}

async function postOllamaConnectionModel(win, {endpoint = '', model = ''} = {}) {
  return fetchOllamaJson(win, '/api/ollama/connection', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({endpoint, model}),
  });
}

function setOllamaModelSelectOptions(select, {
  models = [],
  currentModel = '',
  disabled = false,
} = {}) {
  if (!select) return;
  const current = normalizeOllamaModel(currentModel);
  const unique = [];
  for (const item of models || []) {
    const model = String(item || '').trim();
    if (model && !unique.includes(model)) unique.push(model);
  }
  if (current && !unique.includes(current)) unique.unshift(current);
  select.textContent = '';
  for (const model of unique) {
    const option = select.ownerDocument.createElement('option');
    option.value = model;
    option.textContent = shortOllamaModel(model);
    option.title = model;
    select.appendChild(option);
  }
  select.value = current;
  select.title = current;
  select.disabled = !!disabled || unique.length === 0;
}

export {
  DEFAULT_MODEL,
  fetchOllamaConnection,
  fetchOllamaJson,
  fetchOllamaStatus,
  normalizeOllamaModel,
  postOllamaConnectionModel,
  setOllamaModelSelectOptions,
  shortOllamaModel,
};
