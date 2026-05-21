export function createSaveDirectoryPanel({
  document,
  escHtml,
  openModule,
  setModuleParam,
  showToast,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let lastState = null;

  function setState(state) {
    lastState = state;
  }

  function open() {
    openModule('save_directory');
  }

  function render(state) {
    const m = state || lastState;
    if (!m) return;
    lastState = m;

    const controlAllowed = !!m.control_allowed;
    const browseAllowed = !!m.browse_allowed;
    const filenameOptions = (m.filename_format_options || []).map(opt =>
      `<option value="${escHtml(opt.value)}" ${opt.value === m.filename_format ? 'selected' : ''}>${escHtml(opt.label)}</option>`
    ).join('');
    const classificationOptions = (m.classification_method_options || []).map(opt =>
      `<option value="${escHtml(opt.value)}" ${opt.value === m.classification_method ? 'selected' : ''}>${escHtml(opt.label)}</option>`
    ).join('');
    const rulesVisible = m.classification_method === 'prompt_recognition';
    const accessNotice = !controlAllowed
      ? `<div class="mod-notice">${escHtml(m.control_block_reason || 'This setting is read-only on this client.')}</div>`
      : '';
    const browseNotice = !browseAllowed && m.browse_block_reason
      ? `<div class="mod-debug-empty">${escHtml(m.browse_block_reason)}</div>`
      : '';

    moduleBody.innerHTML = `
      <div class="mod-settings-panel">
        <div class="mod-field">
          <span class="mod-field-label">Current Save Directory</span>
          <div class="mod-status" style="text-align:left;line-height:1.6;word-break:break-all">${escHtml(m.current_save_directory || '')}</div>
        </div>
        <div class="mod-field">
          <span class="mod-field-label">Session Timestamp</span>
          <div class="mod-status" style="text-align:left;min-height:0">${escHtml(m.session_timestamp || '—')}</div>
        </div>
        ${accessNotice}
        <label class="mod-field">
          <span class="mod-field-label">Base Save Path</span>
          <input class="mod-input" id="saveDirBasePath" value="${escHtml(m.base_path || '')}"
                 ${controlAllowed ? '' : 'readonly disabled'}
                 autocomplete="off" spellcheck="false"
                 onkeydown="if(event.key==='Enter') browseSaveDirectory()">
          <div class="mod-inline-row">
            <button class="mod-btn-secondary" ${browseAllowed ? '' : 'disabled'} onclick="browseSaveDirectory()">Apply Path</button>
          </div>
          ${browseNotice}
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${m.use_timestamp_folder ? 'checked' : ''} ${controlAllowed ? '' : 'disabled'} onchange="onSaveDirectoryToggle(this.checked)">
          <span class="mod-checkbox-label">날짜_시간 폴더 사용 (${escHtml(m.session_timestamp || 'session')}/)</span>
        </label>
        <div class="mod-field">
          <span class="mod-field-label">Current Counter</span>
          <div class="mod-status" style="text-align:left;min-height:0">${escHtml(String(m.save_counter ?? 1))}</div>
        </div>
        <label class="mod-field">
          <span class="mod-field-label">Filename Format</span>
          <select class="mod-select" ${controlAllowed ? '' : 'disabled'} onchange="onSaveDirectoryFilenameFormatChange(this.value)">
            ${filenameOptions}
          </select>
        </label>
        <label class="mod-field">
          <span class="mod-field-label">Classification Method</span>
          <select class="mod-select" ${controlAllowed ? '' : 'disabled'} onchange="onSaveDirectoryClassificationChange(this.value)">
            ${classificationOptions}
          </select>
        </label>
        ${rulesVisible ? `
          <label class="mod-field">
            <span class="mod-field-label">Classification Rules</span>
            <textarea class="mod-textarea mod-textarea-lg" ${controlAllowed ? '' : 'disabled'}
                      placeholder="*1girl, (*solo&*1girl), (landscape|scenery)"
                      oninput="onModTextEdit('save_directory','classification_rules',this.value)">${escHtml(m.classification_rules || '')}</textarea>
          </label>
        ` : ''}
      </div>
    `;
  }

  function browse() {
    const input = document.getElementById('saveDirBasePath');
    const value = (input?.value || '').trim();
    if (!value) {
      if (showToast) showToast('저장 경로를 입력해주세요.', 'error');
      return;
    }
    if (lastState) {
      lastState.base_path = value;
      render(lastState);
    }
    setModuleParam('save_directory', 'base_path', value);
  }

  function onTimestampToggle(checked) {
    if (lastState) {
      lastState.use_timestamp_folder = !!checked;
      render(lastState);
    }
    setModuleParam('save_directory', 'use_timestamp_folder', checked ? 'true' : 'false');
  }

  function onFilenameFormatChange(value) {
    if (lastState) lastState.filename_format = value;
    setModuleParam('save_directory', 'filename_format', value);
  }

  function onClassificationChange(value) {
    if (lastState) {
      lastState.classification_method = value;
      render(lastState);
    }
    setModuleParam('save_directory', 'classification_method', value);
  }

  return {
    setState,
    open,
    render,
    browse,
    onTimestampToggle,
    onFilenameFormatChange,
    onClassificationChange,
  };
}
