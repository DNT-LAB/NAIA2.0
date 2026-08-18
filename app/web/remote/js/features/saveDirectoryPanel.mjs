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
    // 네이티브 폴더 선택은 Electron 쉘에서만(원격/일반 브라우저는 텍스트 입력 폴백). naiaShell 존재로 판정.
    const canPick = browseAllowed && !!(globalThis.naiaShell && globalThis.naiaShell.pickSaveDirectory);
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
          <!-- 고를 수 있으면 **고르는 쪽이 먼저**다. 경로를 손으로 적게 하는 것은
               오타 하나로 엉뚱한 데에 그림이 쌓이는 길이고, 위의 칸은 그때도
               남아 있으니 직접 적고 싶은 사람이 못 하게 되는 것도 아니다. -->
          <div class="mod-inline-row">
            ${canPick
              ? `<button class="mod-btn-secondary mod-btn-secondary--accent" id="saveDirPickBtn"
                         onclick="pickSaveDirectory()">📁 폴더 선택…</button>` : ''}
            <button class="mod-btn-secondary"
                    ${browseAllowed ? '' : 'disabled'}
                    onclick="browseSaveDirectory()">${canPick ? '적은 경로 적용' : 'Apply Path'}</button>
          </div>
          ${browseNotice}
        </label>
        <label class="mod-checkbox-item">
          <input type="checkbox" ${m.use_timestamp_folder ? 'checked' : ''} ${controlAllowed ? '' : 'disabled'} onchange="onSaveDirectoryToggle(this.checked)">
          <span class="mod-checkbox-label">날짜_시간 폴더 사용 (${escHtml(m.session_timestamp || 'session')}/)</span>
        </label>
        <div class="mod-field">
          <span class="mod-field-label">Current Counter</span>
          <!-- 카운터는 앱을 다시 켜면 1 로 돌아간다. 그 사이에도 다시 1 부터 세고
               싶을 때가 있어서 초기화를 손 닿는 곳에 둔다(번호가 겹쳐도 백엔드가
               "00001 (1).png" 로 비키므로 기존 파일은 그대로다). -->
          <div class="mod-inline-row">
            <div class="mod-status" style="text-align:left;min-height:0;flex:1">${escHtml(String(m.save_counter ?? 1))}</div>
            <button class="mod-btn-secondary mod-btn-compact" type="button"
                    ${controlAllowed ? '' : 'disabled'}
                    onclick="resetSaveDirectoryCounter()">1로 초기화</button>
          </div>
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
                      placeholder="*1girl, *2girls, (landscape|scenery)"
                      oninput="onModTextEdit('save_directory','classification_rules',this.value)">${escHtml(m.classification_rules || '')}</textarea>
            <div style="font-size:11px;color:var(--text-muted,#9aa);line-height:1.7;margin-top:6px;word-break:keep-all">
              <b>*태그</b>=정확일치 · <b>태그</b>=포함 · <b>&amp;</b>=AND · <b>|</b>=OR · <b>( )</b>=그룹 · 쉼표=우선순위(먼저 맞는 규칙) · 미매칭→<b>misc</b><br>
              예: <code>*1girl, *2girls, (landscape|scenery)</code> — 가중치(0.7::)는 자동 무시되어 매칭됩니다.
            </div>
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

  // 네이티브 탐색기로 저장 폴더 선택/생성(Electron 전용). 고른 절대경로를 텍스트칸에 반영하고
  // browse()와 동일하게 base_path 로 적용한다. 백엔드는 저장 시점에 lazy mkdir 하므로 미존재 폴더도 OK.
  async function pickAndApply() {
    const shell = globalThis.naiaShell;
    if (!shell || typeof shell.pickSaveDirectory !== 'function') {
      if (showToast) showToast('폴더 선택은 데스크톱 앱에서만 지원됩니다. 경로를 직접 입력해 주세요.', 'info');
      return;
    }
    let folder = null;
    try { folder = await shell.pickSaveDirectory(); } catch (_) { folder = null; }
    if (!folder) return;   // 사용자 취소
    const input = document.getElementById('saveDirBasePath');
    if (input) input.value = folder;
    if (lastState) { lastState.base_path = folder; render(lastState); }
    setModuleParam('save_directory', 'base_path', folder);   // browse()와 동일 적용 경로
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

  // 화면의 숫자는 팝업을 연 시점의 값이다(생성이 올릴 때 방송은 없다). 그러니
  // "이미 1이면 건너뛴다" 같은 판단을 여기서 하면 안 된다 — 눌렀으면 보낸다.
  function resetCounter() {
    if (!setModuleParam('save_directory', 'save_counter', 1)) {
      if (showToast) showToast('연결이 끊겨 카운터를 초기화하지 못했습니다.', 'error');
      return;
    }
    // 백엔드가 새 상태를 되쏘면 render 가 한 번 더 돈다(값 확정은 그쪽이다).
    if (lastState) {
      lastState.save_counter = 1;
      render(lastState);
    }
    if (showToast) showToast('저장 카운터를 1로 초기화했습니다.', 'success');
  }

  return {
    // 뷰어 설정 판이 "지금 어디에 저장되는지"를 한 줄로 보여 주려고 읽는다.
    // 값을 복제하지 않고 여기 것을 그대로 쓴다 — 두 벌이 되면 반드시 어긋난다.
    getState: () => lastState,
    setState,
    open,
    render,
    browse,
    pickAndApply,
    onTimestampToggle,
    onFilenameFormatChange,
    onClassificationChange,
    resetCounter,
  };
}
