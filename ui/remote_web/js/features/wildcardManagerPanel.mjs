export function createWildcardManagerPanel({
  document,
  moduleBody,
  escHtml,
  setModuleParam,
  showToast,
  confirmDialog = message => globalThis.confirm(message),
  promptDialog = message => globalThis.prompt(message),
}) {
  let currentPath = '';
  let editMode = false;

  function openBrowser() {
    setModuleParam('wildcard', 'get_file_tree', '');
  }

  function onMessage(message) {
    if (message.action === 'file_tree') renderTree(message.tree);
    else if (message.action === 'file_content') renderEditor(message.path, message.content);
    else if (message.action === 'preview_result') showPreview(message.name, message.result);
    else if (message.action === 'save_ok') showToast('File saved', 'success');
    else if (message.action === 'file_deleted') {
      showToast('File deleted', 'success');
      currentPath = '';
    }
  }

  function renderTree(tree) {
    let html = '<div class="mod-section" style="display:flex;gap:6px;margin-bottom:8px">'
      + '<button class="mod-btn-sm" onclick="openModule(\'wildcard\')">\u2190 Back</button>'
      + '<button class="mod-btn-sm" onclick="wcPromptNewFile()">+ New File</button>'
      + '<button class="mod-btn-sm" onclick="setModuleParam(\'wildcard\',\'get_file_tree\',\'\')">Refresh</button>'
      + '</div>';
    html += '<div class="mod-wc-tree">';
    if (!tree || !tree.length) {
      html += '<div class="mod-empty">No wildcard files found</div>';
    } else {
      for (const item of tree) {
        if (item.type === 'folder') {
          html += `<div class="wc-folder"><div class="wc-folder-name" onclick="this.parentElement.classList.toggle('open')">\u{1F4C1} ${escHtml(item.name)} <span class="wc-count">(${item.files.length})</span></div>`;
          html += '<div class="wc-folder-children">';
          for (const file of item.files) {
            html += `<div class="wc-file" onclick="setModuleParam('wildcard','read_file','${escHtml(file.path)}')">\u{1F4C4} ${escHtml(file.name)} <span class="wc-count">${file.lines}L</span></div>`;
          }
          html += '</div></div>';
        } else {
          html += `<div class="wc-file" onclick="setModuleParam('wildcard','read_file','${escHtml(item.path)}')">\u{1F4C4} ${escHtml(item.name)} <span class="wc-count">${item.lines}L</span></div>`;
        }
      }
    }
    html += '</div>';
    html += `<div class="mod-section" style="margin-top:10px">
    <div class="mod-section-label">Wildcard Syntax Guide</div>
    <div class="wc-syntax-guide">
      <div><code>__name__</code> \u2014 Random pick from <code>name.txt</code></div>
      <div><code>__*name__</code> \u2014 Sequential (ordered)</div>
      <div><code>__*master__</code> + <code>__$master:slave__</code> \u2014 Dependent</div>
      <div><code>200:text</code> \u2014 Weighted entry (default 100)</div>
      <div><code>__folder/name__</code> \u2014 Subfolder path</div>
    </div>
  </div>`;
    moduleBody.innerHTML = html;
  }

  function renderEditor(path, content) {
    currentPath = path;
    editMode = false;
    const fname = path.split('/').pop();
    const wcName = fname.replace('.txt', '');
    moduleBody.innerHTML = `
    <div class="mod-section" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <button class="mod-btn-sm" onclick="setModuleParam('wildcard','get_file_tree','')">\u2190 Tree</button>
      <span class="wc-file-path">${escHtml(path)}</span>
      <span style="flex:1"></span>
      <button class="mod-btn-sm" id="wcEditBtn" onclick="wcToggleEdit()">Edit</button>
      <button class="mod-btn-sm mod-btn-danger" onclick="wcDeleteFile()">Delete</button>
    </div>
    <div class="mod-section">
      <textarea class="wc-editor" id="wcEditor" readonly>${escHtml(content)}</textarea>
    </div>
    <div class="mod-section" id="wcEditActions" style="display:none;gap:6px;flex-wrap:wrap">
      <button class="mod-btn-sm" style="background:#4CAF50;color:#fff" onclick="wcSaveFile()">Save</button>
      <button class="mod-btn-sm" onclick="wcCancelEdit()">Cancel</button>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Quick Add Entry</div>
      <div style="display:flex;gap:6px;align-items:center">
        <input type="text" class="wc-add-input" id="wcAddText" placeholder="tag or prompt text">
        <button class="mod-btn-sm" onclick="wcAddEntry()">Add</button>
      </div>
    </div>
    <div class="mod-section">
      <div class="mod-section-label">Preview <code>__${escHtml(wcName)}__</code></div>
      <div style="display:flex;gap:6px;align-items:center">
        <button class="mod-btn-sm" onclick="setModuleParam('wildcard','preview_wildcard','${escHtml(wcName)}')">Roll \u00D75</button>
        <div class="wc-preview" id="wcPreview"></div>
      </div>
    </div>
  `;
  }

  function toggleEdit() {
    const editor = document.getElementById('wcEditor');
    const actions = document.getElementById('wcEditActions');
    const btn = document.getElementById('wcEditBtn');
    if (!editor) return;
    editMode = !editMode;
    editor.readOnly = !editMode;
    editor.classList.toggle('editing', editMode);
    actions.style.display = editMode ? 'flex' : 'none';
    btn.textContent = editMode ? 'Cancel' : 'Edit';
  }

  function cancelEdit() {
    if (currentPath) setModuleParam('wildcard', 'read_file', currentPath);
  }

  function saveFile() {
    const editor = document.getElementById('wcEditor');
    if (!editor || !currentPath) return;
    setModuleParam('wildcard', 'save_file', JSON.stringify({ path: currentPath, content: editor.value }));
  }

  function deleteFile() {
    if (!currentPath) return;
    if (!confirmDialog('Delete ' + currentPath + '?')) return;
    setModuleParam('wildcard', 'delete_file', currentPath);
    setModuleParam('wildcard', 'get_file_tree', '');
  }

  function addEntry() {
    const text = document.getElementById('wcAddText');
    const editor = document.getElementById('wcEditor');
    if (!text || !editor || !text.value.trim()) return;
    const line = text.value.trim();
    const current = editor.value;
    editor.value = current ? current + '\n' + line : line;
    text.value = '';
    if (!editMode) {
      editMode = true;
      editor.readOnly = false;
      editor.classList.add('editing');
      const actions = document.getElementById('wcEditActions');
      if (actions) actions.style.display = 'flex';
      const btn = document.getElementById('wcEditBtn');
      if (btn) btn.textContent = 'Cancel';
    }
  }

  function showPreview(_name, result) {
    const element = document.getElementById('wcPreview');
    if (element) element.innerHTML = escHtml(result).replace(/\n/g, '<br>');
  }

  function promptNewFile() {
    const name = promptDialog('New wildcard filename (e.g. "my_tags" or "folder/my_tags"):');
    if (!name || !name.trim()) return;
    setModuleParam('wildcard', 'create_file', name.trim());
  }

  return {
    openBrowser,
    onMessage,
    renderTree,
    renderEditor,
    toggleEdit,
    cancelEdit,
    saveFile,
    deleteFile,
    addEntry,
    showPreview,
    promptNewFile,
  };
}
