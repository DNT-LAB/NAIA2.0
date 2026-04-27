export function createMetadataViewer({
  document,
  fetch,
  escHtml,
  showToast,
}) {
  const statusEl = document.getElementById('metadataStatus');
  const titleEl = document.getElementById('metadataTitle');
  const summaryEl = document.getElementById('metadataSummary');
  const promptEl = document.getElementById('metadataPrompt');
  const negativeEl = document.getElementById('metadataNegative');
  const rawEl = document.getElementById('metadataRaw');
  const refreshBtn = document.getElementById('metadataRefreshBtn');

  let currentSource = {kind: 'current', path: ''};
  let loading = false;
  let requestSerial = 0;

  function setStatus(text, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.dataset.tone = tone;
  }

  function safeText(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'string') return value;
    return JSON.stringify(value, null, 2);
  }

  function renderEmpty(message) {
    if (titleEl) titleEl.textContent = 'Metadata Viewer';
    if (summaryEl) summaryEl.innerHTML = '';
    if (promptEl) promptEl.innerHTML = `<span class="metadata-empty">${escHtml(message)}</span>`;
    if (negativeEl) negativeEl.innerHTML = '';
    if (rawEl) rawEl.textContent = '';
  }

  function renderSummary(summary) {
    if (!summaryEl) return;
    const hiddenKeys = new Set(['prompt', 'negative', 'characters']);
    const entries = Object.entries(summary || {}).filter(([key, value]) => (
      !hiddenKeys.has(key) && value !== '' && value != null
    ));
    summaryEl.innerHTML = entries.map(([key, value]) => `
      <div class="metadata-summary-item">
        <span>${escHtml(key)}</span>
        <strong>${escHtml(safeText(value))}</strong>
      </div>
    `).join('');
  }

  function renderPromptBlock(el, value, emptyText) {
    if (!el) return;
    const text = safeText(value);
    el.innerHTML = text
      ? escHtml(text)
      : `<span class="metadata-empty">${escHtml(emptyText)}</span>`;
  }

  function render(data) {
    const summary = data && typeof data === 'object' ? (data.summary || {}) : {};
    const raw = data && typeof data === 'object' ? data.raw : data;
    const label = data && data.label ? data.label : (currentSource.path || 'Current Result');
    if (titleEl) titleEl.textContent = label;
    renderSummary(summary);
    renderPromptBlock(promptEl, summary.prompt, 'No prompt metadata');
    renderPromptBlock(negativeEl, summary.negative, 'No negative metadata');
    if (rawEl) {
      const hasRaw = raw && (typeof raw !== 'object' || Object.keys(raw).length > 0);
      rawEl.textContent = hasRaw
        ? (typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2))
        : 'No raw metadata';
    }
    setStatus(data && data.has_metadata === false ? 'No metadata' : 'Loaded', data && data.has_metadata === false ? 'muted' : 'ok');
  }

  async function loadSource(source = currentSource, options = {}) {
    const requestId = ++requestSerial;
    loading = true;
    currentSource = source;
    if (refreshBtn) refreshBtn.disabled = true;
    if (!options.silent) setStatus('Loading...', 'busy');

    try {
      const url = source.kind === 'saved' && source.path
        ? '/api/viewer/meta/' + encodeURI(source.path) + '?full=1'
        : '/api/result/metadata';
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (requestId !== requestSerial) return;
      if (source.kind === 'saved' && source.path && data && typeof data === 'object') {
        data.label = source.path;
        data.source = 'saved';
      }
      render(data);
    } catch (error) {
      if (requestId !== requestSerial) return;
      renderEmpty(source.kind === 'saved' ? 'Metadata unavailable' : 'No current result metadata');
      setStatus('Unavailable', 'error');
      if (!options.silent && showToast) showToast('Failed to load metadata', 'error');
    } finally {
      if (requestId === requestSerial) {
        loading = false;
        if (refreshBtn) refreshBtn.disabled = false;
      }
    }
  }

  function loadCurrent(options = {}) {
    return loadSource({kind: 'current', path: ''}, options);
  }

  function loadSaved(path, options = {}) {
    if (!path) return loadCurrent(options);
    return loadSource({kind: 'saved', path}, options);
  }

  function refresh() {
    return loadSource(currentSource, {silent: false});
  }

  renderEmpty('No current result metadata');
  setStatus('Idle', 'muted');

  return {
    loadCurrent,
    loadSaved,
    refresh,
  };
}
