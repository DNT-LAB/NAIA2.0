export function createAutoSavePanel({
  document,
  getWs,
  WebSocket,
  getCurrentModuleId,
  isModulePopupOpen,
  escHtml,
  openModule,
  setModuleParam,
  showToast,
}) {
  const statsSave = document.getElementById('statsSave');
  const moduleBody = document.getElementById('modulePopupBody');
  let enabled = true;
  let lastState = null;

  function defaultState() {
    return {
      auto_save: enabled,
      save_as_webp: false,
      history_limit_enabled: false,
      max_history_length: 2000,
      memory_action: 1,
      memory_action_options: [
        { value: 1, label: '[1] 1장씩 자동저장+정리' },
        { value: 2, label: '[2] 1장씩 저장없이 삭제' },
        { value: 3, label: '[3] 자동생성 중단' },
      ],
    };
  }

  function setState(state) {
    lastState = state;
    if (state && 'auto_save' in state) enabled = !!state.auto_save;
  }

  function open() {
    openModule('auto_save');
  }

  function setEnabled(value) {
    enabled = !!value;
    if (lastState) lastState.auto_save = enabled;
    updateSaveUi();
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'set_option', key: 'auto_save', value: enabled }));
    }
  }

  function syncEnabled(value) {
    enabled = !!value;
    if (lastState) lastState.auto_save = enabled;
    updateSaveUi();
  }

  function render(state = lastState) {
    const panelState = state || defaultState();
    lastState = panelState;
    const statusText = panelState.auto_save ? 'Enabled' : 'Disabled';
    const desc = 'Web Session은 시작 시 Auto Save가 강제로 켜집니다. 필요하면 여기서만 변경할 수 있습니다.';
    const actionOptions = (panelState.memory_action_options || []).map(opt =>
      `<option value="${opt.value}" ${String(opt.value) === String(panelState.memory_action) ? 'selected' : ''}>${escHtml(opt.label)}</option>`
    ).join('');

    moduleBody.innerHTML = `
      <div class="mod-settings-panel">
        <div class="mod-field">
          <span class="mod-field-label">Current Status</span>
          <div class="mod-status" style="text-align:left;min-height:0">${statusText}</div>
        </div>
        <div class="mod-field">
          <span class="mod-field-label">Policy</span>
          <div class="mod-status" style="text-align:left;line-height:1.6">${desc}</div>
        </div>
        <div class="mod-inline-row">
          <button class="mod-action-btn ${panelState.auto_save ? 'mod-stop' : 'mod-start'}"
                  onclick="setAutoSaveEnabled(${panelState.auto_save ? 'false' : 'true'})">
            ${panelState.auto_save ? 'Disable Auto Save' : 'Enable Auto Save'}
          </button>
          <button class="mod-btn-secondary" onclick="openSaveDirectoryPanel()">
            Save Directory Settings
          </button>
        </div>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${panelState.save_as_webp ? 'checked' : ''}
                 onchange="onAutoSaveWebpChange(this.checked)">
          <span class="mod-checkbox-label">WEBP로 저장</span>
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${panelState.history_limit_enabled ? 'checked' : ''}
                 onchange="onHistoryLimitToggle(this.checked)">
          <span class="mod-checkbox-label">히스토리 큐 제한 활성화</span>
        </label>
        <label class="mod-field">
          <span class="mod-field-label">Max History Length</span>
          <input class="mod-input" type="number" min="100" max="10000" step="100"
                 value="${escHtml(String(panelState.max_history_length ?? 2000))}"
                 ${panelState.history_limit_enabled ? '' : 'disabled'}
                 onchange="onHistoryLimitLengthChange(this.value)">
        </label>
        <label class="mod-field">
          <span class="mod-field-label">On Limit Reached</span>
          <select class="mod-select" ${panelState.history_limit_enabled ? '' : 'disabled'}
                  onchange="onHistoryLimitActionChange(this.value)">
            ${actionOptions}
          </select>
        </label>
      </div>
    `;
  }

  function renderCached() {
    if (!lastState) return;
    render(lastState);
  }

  function updateSaveUi() {
    if (!statsSave) return;
    statsSave.classList.toggle('off', !enabled);
    const dot = statsSave.querySelector('.stats-dot');
    const text = enabled ? 'Auto Save' : 'Auto Save OFF';
    if (dot) { dot.nextSibling.textContent = text; }
    statsSave.title = enabled ? 'Open auto-save settings (enabled)' : 'Open auto-save settings (disabled)';
    if (getCurrentModuleId() === 'auto_save' && isModulePopupOpen()) {
      render();
    }
  }

  function onWebpChange(checked) {
    if (lastState) lastState.save_as_webp = !!checked;
    setModuleParam('auto_save', 'save_as_webp', checked ? 'true' : 'false');
  }

  function onHistoryLimitToggle(checked) {
    if (lastState) {
      lastState.history_limit_enabled = !!checked;
      render(lastState);
    }
    setModuleParam('auto_save', 'history_limit_enabled', checked ? 'true' : 'false');
  }

  function onHistoryLimitLengthChange(value) {
    const parsed = parseInt(value, 10);
    if (!Number.isFinite(parsed)) {
      showToast('Valid history length required.', 'error');
      return;
    }
    if (lastState) lastState.max_history_length = parsed;
    setModuleParam('auto_save', 'max_history_length', String(parsed));
  }

  function onHistoryLimitActionChange(value) {
    if (lastState) lastState.memory_action = parseInt(value, 10);
    setModuleParam('auto_save', 'memory_action', value);
  }

  return {
    open,
    setEnabled,
    syncEnabled,
    setState,
    render,
    renderCached,
    updateSaveUi,
    onWebpChange,
    onHistoryLimitToggle,
    onHistoryLimitLengthChange,
    onHistoryLimitActionChange,
  };
}
