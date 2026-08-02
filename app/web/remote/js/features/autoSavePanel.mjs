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
  let bulkBusy = false;

  function defaultState() {
    return {
      auto_save: enabled,
      save_as_webp: false,
      history_limit_enabled: false,
      quicksave_mode: 'copy',
      quicksave_dir: '',
      quicksave_folder: 'date',
      max_history_length: 2000,
      memory_action: 1,
      unsaved_history_count: 0,
      memory_action_options: [
        { value: 1, label: '[1] 1장씩 자동저장+정리' },
        { value: 2, label: '[2] 1장씩 저장없이 삭제' },
        { value: 3, label: '[3] 자동생성 중단' },
      ],
    };
  }

  function setState(state) {
    lastState = state;
    enabled = !!state?.auto_save;
    updateSaveUi();
  }

  function open() {
    openModule('auto_save');
  }

  function setEnabled(value) {
    enabled = !!value;
    if (lastState) lastState.auto_save = enabled;
    updateSaveUi();
    setModuleParam('auto_save', 'auto_save', enabled ? 'true' : 'false');
    showToast(enabled ? 'Auto Save enabled.' : 'Auto Save disabled.', 'success');
  }

  function syncEnabled(value) {
    enabled = !!value;
    if (lastState) lastState.auto_save = enabled;
    updateSaveUi();
  }

  function render(state = lastState) {
    const panelState = state || defaultState();
    panelState.auto_save = !!panelState.auto_save;
    enabled = panelState.auto_save;
    lastState = panelState;
    const statusText = panelState.auto_save ? 'Enabled' : 'Disabled';
    const desc = panelState.auto_save
      ? '이미지를 생성할 때 저장 폴더에도 자동 저장합니다.'
      : '이미지를 저장하지 않고 Remote Web 히스토리에만 유지합니다.';
    const toggleLabel = panelState.auto_save ? 'Disable Auto Save' : 'Enable Auto Save';
    const toggleValue = panelState.auto_save ? 'false' : 'true';
    const toggleClass = panelState.auto_save ? 'mod-stop' : 'mod-start';
    const unsavedCount = Math.max(0, Number(panelState.unsaved_history_count || 0));
    const bulkDisabled = bulkBusy || unsavedCount <= 0;
    const modeOptions = (panelState.quicksave_mode_options || []).map(o =>
      `<option value="${escHtml(String(o.value))}"${
        String(panelState.quicksave_mode) === String(o.value) ? ' selected' : ''
      }>${escHtml(String(o.label))}</option>`).join('');
    const folderOptions = (panelState.quicksave_folder_options || []).map(o =>
      `<option value="${escHtml(String(o.value))}"${
        String(panelState.quicksave_folder) === String(o.value) ? ' selected' : ''
      }>${escHtml(String(o.label))}</option>`).join('');
    const actionOptions = (panelState.memory_action_options || []).map(opt =>
      `<option value="${opt.value}" ${String(opt.value) === String(panelState.memory_action) ? 'selected' : ''}>${escHtml(opt.label)}</option>`
    ).join('');

    moduleBody.innerHTML = `
      <div class="mod-settings-panel">
        <div class="mod-field">
          <span class="mod-field-label">Current Status</span>
          <div class="mod-status" style="text-align:left;min-height:0">${statusText}</div>
        </div>
        <div class="auto-save-unsaved-section">
          <span class="auto-save-unsaved-count">저장 안됨 : <b>${escHtml(String(unsavedCount))}</b></span>
          <button class="mod-btn-secondary mod-btn-compact" type="button"
                  onclick="saveAllUnsavedHistory()" ${bulkDisabled ? 'disabled' : ''}>
            ${bulkBusy ? '저장 중...' : '일괄 저장'}
          </button>
          <button class="mod-btn-secondary mod-btn-compact" type="button"
                  onclick="downloadUnsavedHistory()" ${bulkDisabled ? 'disabled' : ''}>
            ${bulkBusy ? '처리 중...' : '일괄 다운로드'}
          </button>
        </div>
        <div class="mod-field">
          <span class="mod-field-label">Policy</span>
          <div class="mod-status" style="text-align:left;line-height:1.6">${desc}</div>
        </div>
        <div class="mod-inline-row">
          <button class="mod-action-btn ${toggleClass}" type="button" onclick="onAutoSaveToggle(${toggleValue})">
            ${toggleLabel}
          </button>
          <button class="mod-btn-secondary" type="button" onclick="openSaveDirectoryPanel()">
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

        <div class="mod-section-title">Ctrl + S 빠른 저장</div>
        <p class="mod-policy-text">보고 있는 이미지를 지정한 경로로 따로 남깁니다.
          파일 이름은 <b>세션시작시간_원래이름</b> 으로 고정됩니다.</p>
        <label class="mod-field">
          <span class="mod-field-label">Auto Save 가 켜져 있을 때</span>
          <select class="mod-select" onchange="onQuicksaveModeChange(this.value)">
            ${modeOptions}
          </select>
        </label>
        <label class="mod-field">
          <span class="mod-field-label">저장 경로 (비우면 저장 폴더를 따라감)</span>
          <input class="mod-input" type="text" placeholder="예: D:/picks"
                 value="${escHtml(String(panelState.quicksave_dir || ''))}"
                 onchange="onQuicksaveDirChange(this.value)">
        </label>
        <label class="mod-field">
          <span class="mod-field-label">폴더 배치</span>
          <select class="mod-select" onchange="onQuicksaveFolderChange(this.value)">
            ${folderOptions}
          </select>
        </label>
        <p class="mod-policy-text mod-dim">실제 경로: ${escHtml(String(panelState.quicksave_resolved || '-'))}</p>
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

  function onQuicksaveModeChange(value) {
    if (lastState) lastState.quicksave_mode = value;
    setModuleParam('auto_save', 'quicksave_mode', String(value || 'copy'));
  }

  function onQuicksaveDirChange(value) {
    if (lastState) lastState.quicksave_dir = value;
    setModuleParam('auto_save', 'quicksave_dir', String(value || ''));
  }

  function onQuicksaveFolderChange(value) {
    if (lastState) lastState.quicksave_folder = value;
    setModuleParam('auto_save', 'quicksave_folder', String(value || 'date'));
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

  async function readJsonError(response, fallback) {
    try {
      const data = await response.json();
      return data?.error || data?.message || fallback;
    } catch (_) {
      return fallback;
    }
  }

  async function saveAllUnsavedHistory() {
    if (bulkBusy) return;
    bulkBusy = true;
    render(lastState);
    try {
      const response = await fetch('/api/history/unsaved/save-all', { method: 'POST' });
      if (!response.ok) {
        throw new Error(await readJsonError(response, `HTTP ${response.status}`));
      }
      const data = await response.json();
      if (lastState) lastState.unsaved_history_count = Number(data.remaining || 0);
      showToast(`미저장 이미지 ${Number(data.saved || 0)}장을 저장했습니다.`, 'success');
      render(lastState);
    } catch (error) {
      showToast(error.message || '일괄 저장 실패', 'error');
      render(lastState);
    } finally {
      bulkBusy = false;
      render(lastState);
    }
  }

  async function downloadUnsavedHistory() {
    if (bulkBusy) return;
    bulkBusy = true;
    render(lastState);
    try {
      const response = await fetch('/api/history/unsaved/download', { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(await readJsonError(response, `HTTP ${response.status}`));
      }
      const blob = await response.blob();
      const disposition = response.headers.get('content-disposition') || '';
      const filenameMatch = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
      const filename = filenameMatch
        ? decodeURIComponent(filenameMatch[1] || filenameMatch[2] || 'naia-unsaved-history.zip')
        : 'naia-unsaved-history.zip';
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast('미저장 히스토리 ZIP 다운로드를 시작했습니다.', 'success');
    } catch (error) {
      showToast(error.message || '일괄 다운로드 실패', 'error');
    } finally {
      bulkBusy = false;
      render(lastState);
    }
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
    onQuicksaveModeChange,
    onQuicksaveDirChange,
    onQuicksaveFolderChange,
    onHistoryLimitToggle,
    onHistoryLimitLengthChange,
    onHistoryLimitActionChange,
    saveAllUnsavedHistory,
    downloadUnsavedHistory,
  };
}
