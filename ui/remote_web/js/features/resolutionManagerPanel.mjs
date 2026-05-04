export function createResolutionManagerPanel({
  document,
  showToast,
  getApiMode,
  getCurrentResolution,
  onSaved,
}) {
  const panel = document.getElementById('resolutionManagerPanel');
  if (!panel) {
    return {
      open() {},
      close() {},
      isOpen: () => false,
    };
  }

  const body = panel.querySelector('[data-resolution-manager-body]');
  const state = {
    resolutions: [],
    defaults: [],
    current: '',
    apiMode: '',
    multiple: 64,
    maxValue: 8192,
    warningPixelArea: 1024 * 1024,
  };
  let selectedIndex = -1;
  let busy = false;

  function normalizeMode(mode) {
    return String(mode || '').trim().toUpperCase();
  }

  function multipleForMode() {
    const mode = normalizeMode(state.apiMode || getApiMode?.());
    return mode === 'NAI' ? 64 : 8;
  }

  function normalizeResolutionLabel(width, height) {
    return `${width} x ${height}`;
  }

  function parseResolution(value) {
    const match = String(value || '').match(/(\d+)\s*x\s*(\d+)/i);
    if (!match) return null;
    const width = Number.parseInt(match[1], 10);
    const height = Number.parseInt(match[2], 10);
    if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return null;
    return {width, height};
  }

  function setBusy(nextBusy) {
    busy = !!nextBusy;
    panel.querySelectorAll('button, input').forEach(el => {
      el.disabled = busy;
    });
  }

  function applyServerState(payload = {}) {
    state.resolutions = Array.isArray(payload.resolutions) ? payload.resolutions.slice() : [];
    state.defaults = Array.isArray(payload.defaults) ? payload.defaults.slice() : [];
    state.current = payload.current_resolution || getCurrentResolution?.() || '';
    state.apiMode = payload.api_mode || getApiMode?.() || '';
    state.multiple = Number(payload.multiple) || multipleForMode();
    state.maxValue = Number(payload.max_value) || 8192;
    state.warningPixelArea = Number(payload.warning_pixel_area) || 1024 * 1024;
    if (!state.resolutions.length && state.defaults.length) state.resolutions = state.defaults.slice();
    selectedIndex = -1;
  }

  async function loadState() {
    const response = await fetch('/api/resolutions', {cache: 'no-store'});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.error) {
      throw new Error(payload.error || `Failed to load resolutions (${response.status})`);
    }
    applyServerState(payload);
  }

  async function saveState() {
    const response = await fetch('/api/resolutions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({resolutions: state.resolutions}),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.error) {
      throw new Error(payload.error || `Failed to save resolutions (${response.status})`);
    }
    applyServerState(payload);
    onSaved?.(payload);
  }

  function renderShell() {
    body.innerHTML = `
      <div class="resolution-manager-layout">
        <div class="resolution-manager-list" data-resolution-list></div>
        <div class="resolution-manager-actions">
          <button type="button" class="resolution-manager-btn" data-resolution-action="remove">Remove</button>
          <button type="button" class="resolution-manager-btn" data-resolution-action="restore">Restore Defaults</button>
        </div>
        <div class="resolution-manager-add">
          <label>
            <span>Width</span>
            <input type="number" inputmode="numeric" min="1" max="8192" data-resolution-width>
          </label>
          <label>
            <span>Height</span>
            <input type="number" inputmode="numeric" min="1" max="8192" data-resolution-height>
          </label>
          <button type="button" class="resolution-manager-btn primary" data-resolution-action="add">Add</button>
        </div>
        <div class="resolution-manager-validation">
          <div data-resolution-area>Area: 0</div>
          <div data-resolution-warning></div>
          <button type="button" class="resolution-manager-btn" data-resolution-action="fit">Auto Fit</button>
        </div>
        <div class="resolution-manager-footer">
          <span data-resolution-summary></span>
          <button type="button" class="resolution-manager-btn primary" data-resolution-action="save">Save</button>
          <button type="button" class="resolution-manager-btn" data-resolution-action="cancel">Cancel</button>
        </div>
      </div>
    `;
  }

  function getEls() {
    return {
      list: panel.querySelector('[data-resolution-list]'),
      width: panel.querySelector('[data-resolution-width]'),
      height: panel.querySelector('[data-resolution-height]'),
      area: panel.querySelector('[data-resolution-area]'),
      warning: panel.querySelector('[data-resolution-warning]'),
      summary: panel.querySelector('[data-resolution-summary]'),
    };
  }

  function renderList() {
    const {list} = getEls();
    list.innerHTML = '';
    state.resolutions.forEach((label, index) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = `resolution-manager-row${index === selectedIndex ? ' selected' : ''}${label === state.current ? ' current' : ''}`;
      row.dataset.resolutionIndex = String(index);
      const text = document.createElement('span');
      text.textContent = label;
      row.append(text);
      if (label === state.current) {
        const badge = document.createElement('span');
        badge.className = 'resolution-manager-badge';
        badge.textContent = 'Current';
        row.append(badge);
      }
      list.append(row);
    });
  }

  function validateInputs() {
    const {width, height, area, warning} = getEls();
    const w = Number.parseInt(width.value || '0', 10);
    const h = Number.parseInt(height.value || '0', 10);
    const multiple = Number(state.multiple) || multipleForMode();
    const messages = [];
    if (Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0) {
      const pixels = w * h;
      area.textContent = `Area: ${pixels.toLocaleString()}`;
      if (pixels > state.warningPixelArea) messages.push('NAI may consume extra Anlas above 1,048,576 pixels.');
      if (w > state.maxValue || h > state.maxValue) messages.push(`Maximum side length is ${state.maxValue}.`);
      if (w % multiple !== 0 || h % multiple !== 0) messages.push(`Width and height must be multiples of ${multiple}.`);
    } else {
      area.textContent = 'Area: 0';
    }
    warning.textContent = messages.join(' ');
    warning.classList.toggle('active', messages.length > 0);
    return messages.length === 0;
  }

  function render() {
    state.multiple = Number(state.multiple) || multipleForMode();
    renderList();
    validateInputs();
    const {summary} = getEls();
    const mode = normalizeMode(state.apiMode || getApiMode?.()) || 'MODE';
    summary.textContent = `${state.resolutions.length} items · ${mode} · x${state.multiple}`;
  }

  function addResolution() {
    const {width, height} = getEls();
    const w = Number.parseInt(width.value || '0', 10);
    const h = Number.parseInt(height.value || '0', 10);
    const multiple = Number(state.multiple) || multipleForMode();
    if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) {
      showToast?.('Enter a valid width and height.', 'error');
      return;
    }
    if (w > state.maxValue || h > state.maxValue) {
      showToast?.(`Maximum side length is ${state.maxValue}.`, 'error');
      return;
    }
    if (w % multiple !== 0 || h % multiple !== 0) {
      showToast?.(`Width and height must be multiples of ${multiple}.`, 'error');
      return;
    }
    const label = normalizeResolutionLabel(w, h);
    if (state.resolutions.includes(label)) {
      showToast?.('Resolution already exists.', 'info');
      return;
    }
    state.resolutions.push(label);
    width.value = '';
    height.value = '';
    selectedIndex = state.resolutions.length - 1;
    render();
  }

  function removeSelected() {
    if (selectedIndex < 0 || selectedIndex >= state.resolutions.length) {
      showToast?.('Select a resolution to remove.', 'info');
      return;
    }
    if (state.resolutions.length <= 1) {
      showToast?.('Resolution list cannot be empty.', 'error');
      return;
    }
    state.resolutions.splice(selectedIndex, 1);
    selectedIndex = Math.min(selectedIndex, state.resolutions.length - 1);
    render();
  }

  function restoreDefaults() {
    if (!state.defaults.length) return;
    state.resolutions = state.defaults.slice();
    selectedIndex = -1;
    render();
  }

  function autoFitInputs() {
    const {width, height} = getEls();
    const multiple = Number(state.multiple) || multipleForMode();
    const snap = value => Math.max(multiple, Math.round(value / multiple) * multiple);
    const w = Number.parseInt(width.value || '0', 10);
    const h = Number.parseInt(height.value || '0', 10);
    if (Number.isFinite(w) && w > 0) width.value = String(Math.min(state.maxValue, snap(w)));
    if (Number.isFinite(h) && h > 0) height.value = String(Math.min(state.maxValue, snap(h)));
    validateInputs();
  }

  async function open() {
    panel.classList.add('open');
    renderShell();
    setBusy(true);
    try {
      await loadState();
      render();
    } catch (error) {
      showToast?.(error.message || 'Failed to load resolutions.', 'error');
      close();
    } finally {
      setBusy(false);
    }
  }

  function close() {
    panel.classList.remove('open');
    body.innerHTML = '';
    selectedIndex = -1;
  }

  panel.addEventListener('click', async event => {
    const row = event.target.closest('[data-resolution-index]');
    if (row) {
      selectedIndex = Number.parseInt(row.dataset.resolutionIndex || '-1', 10);
      render();
      return;
    }
    const actionEl = event.target.closest('[data-resolution-action]');
    if (!actionEl || busy) return;
    const action = actionEl.dataset.resolutionAction;
    if (action === 'add') addResolution();
    else if (action === 'remove') removeSelected();
    else if (action === 'restore') restoreDefaults();
    else if (action === 'fit') autoFitInputs();
    else if (action === 'cancel') close();
    else if (action === 'save') {
      setBusy(true);
      try {
        await saveState();
        showToast?.('Resolution list saved.', 'success');
        close();
      } catch (error) {
        showToast?.(error.message || 'Failed to save resolutions.', 'error');
      } finally {
        setBusy(false);
      }
    }
  });

  panel.addEventListener('input', event => {
    if (event.target.matches('[data-resolution-width], [data-resolution-height]')) validateInputs();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && panel.classList.contains('open')) close();
  });

  return {
    open,
    close,
    isOpen: () => panel.classList.contains('open'),
  };
}
