export function createInstantWildcardPanel({
  document,
  window,
  escHtml,
  setModuleParam,
  bindTagAssist,
  showToast,
  confirmDialog = async () => false,
  promptDialog = async () => null,
}) {
  const moduleBody = document.getElementById('modulePopupBody');
  let lastState = null;

  function attr(value) {
    return escHtml(String(value ?? ''));
  }

  function currentFile() {
    return lastState ? lastState.current_file : '';
  }

  function currentKey() {
    return lastState ? lastState.current_key : '';
  }

  function renderFileOption(file) {
    return `<option value="${attr(file.name)}" ${file.selected ? 'selected' : ''}>${escHtml(file.group)} (${file.count})</option>`;
  }

  function renderItem(item) {
    return `<button class="iwc-item${item.selected ? ' selected' : ''}" data-key="${attr(item.key)}" onclick="instantWildcardSelectKey(this)">
      <span>${escHtml(item.key)}</span>
      <small>${escHtml((item.value || '').slice(0, 80))}</small>
    </button>`;
  }

  function bindRenderedInputs() {
    const value = document.getElementById('iwcValue');
    if (value && bindTagAssist) bindTagAssist(value);
  }

  function render(state) {
    lastState = state;
    const files = state.files || [];
    const items = state.items || [];
    const fileOptions = files.length
      ? files.map(renderFileOption).join('')
      : '<option value="">No files</option>';
    const itemList = items.length
      ? items.map(renderItem).join('')
      : '<div class="mod-empty">No entries in this group</div>';
    const current = state.current_key || '';

    moduleBody.innerHTML = `
      <div class="iwc-panel">
        <div class="iwc-toolbar">
          <select class="mod-select" id="iwcFileSelect" onchange="instantWildcardSelectFile(this.value)">${fileOptions}</select>
          <button class="mod-btn-sm" onclick="instantWildcardReload()">Reload</button>
          <button class="mod-btn-sm" onclick="instantWildcardAddGroup()">Add Group</button>
          <span class="iwc-count">${state.flat_count || 0} loaded</span>
        </div>

        <div class="iwc-layout">
          <section class="iwc-list-panel">
            <div class="mod-section-label">Entries</div>
            <div class="iwc-list">${itemList}</div>
          </section>

          <section class="iwc-editor">
            <div class="mod-section-label">Key</div>
            <input class="mod-input" id="iwcKey" value="${attr(current)}" placeholder="wildcard key">

            <div class="mod-section-label">Value</div>
            <textarea class="mod-textarea mod-textarea-lg" id="iwcValue" placeholder="tag, tag, tag">${escHtml(state.current_value || '')}</textarea>

            <div class="iwc-actions">
              <button class="mod-action-btn mod-start" onclick="instantWildcardSave()">Save / Add</button>
              <button class="mod-btn-sm" onclick="instantWildcardRename()" ${current ? '' : 'disabled'}>Rename</button>
              <button class="mod-btn-sm danger" onclick="instantWildcardDelete()" ${current ? '' : 'disabled'}>Delete</button>
            </div>

            <div class="iwc-token-preview">
              <span>$${escHtml(state.current_group || '')}</span>
              ${current ? `<span>$${escHtml(state.current_group || '')}:${escHtml(current)}</span>` : ''}
            </div>
          </section>
        </div>

        <div class="mod-status">${escHtml(state.save_path || '')}</div>
      </div>
    `;
    bindRenderedInputs();
  }

  function selectFile(value) {
    setModuleParam('instant_wildcard', 'select_file', value);
  }

  function selectKey(element) {
    setModuleParam('instant_wildcard', 'select_key', element.dataset.key || '');
  }

  function reload() {
    setModuleParam('instant_wildcard', 'reload', '1');
  }

  async function addGroup() {
    const name = await Promise.resolve(promptDialog('New instant wildcard group name', {
      title: 'Instant Wildcard',
      okText: '추가',
      cancelText: '취소',
      placeholder: 'group name',
    }));
    if (!name) return;
    setModuleParam('instant_wildcard', 'add_group', name);
  }

  function save() {
    const keyInput = document.getElementById('iwcKey');
    const valueInput = document.getElementById('iwcValue');
    const key = keyInput ? keyInput.value.trim() : '';
    const value = valueInput ? valueInput.value : '';
    if (!key) {
      if (showToast) showToast('Wildcard key is required', 'error');
      return;
    }
    setModuleParam('instant_wildcard', 'upsert', JSON.stringify({
      file: currentFile(),
      key,
      value,
    }));
  }

  async function rename() {
    const oldKey = currentKey();
    if (!oldKey) return;
    const newKey = await Promise.resolve(promptDialog('New key name', {
      title: 'Rename wildcard key',
      okText: '변경',
      cancelText: '취소',
      defaultValue: oldKey,
    }));
    if (!newKey || newKey === oldKey) return;
    setModuleParam('instant_wildcard', 'rename', JSON.stringify({
      file: currentFile(),
      old_key: oldKey,
      new_key: newKey,
    }));
  }

  async function deleteCurrent() {
    const key = currentKey();
    if (!key) return;
    const confirmed = await Promise.resolve(confirmDialog(`Delete '${key}'?`, {
      title: 'Delete wildcard key',
      okText: '삭제',
      cancelText: '취소',
    }));
    if (!confirmed) return;
    setModuleParam('instant_wildcard', 'delete', JSON.stringify({
      file: currentFile(),
      key,
    }));
  }

  return {
    render,
    selectFile,
    selectKey,
    reload,
    addGroup,
    save,
    rename,
    deleteCurrent,
  };
}
