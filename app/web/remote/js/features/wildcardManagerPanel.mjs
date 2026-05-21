export function createWildcardManagerPanel({
  document,
  moduleBody,
  modulePopup,
  escHtml,
  setModuleParam,
  showToast,
  closeAuxiliaryPopups = () => {},
  positionFloatingPanel = () => {},
  confirmDialog = async () => false,
  promptDialog = async () => null,
}) {
  let currentPath = '';
  let currentContent = '';
  let editMode = false;
  let renderMode = 'full';
  let cachedTree = null;
  let editorOpen = false;
  let editorPanel = null;
  const openFolders = new Set();

  function getTarget() {
    if (renderMode === 'inline') return document.getElementById('wcInlineBrowser');
    return moduleBody;
  }

  function writeTarget(html) {
    const target = getTarget();
    if (target) target.innerHTML = html;
  }

  function openBrowser() {
    renderMode = 'full';
    setModuleParam('wildcard', 'get_file_tree', '');
  }

  function renderInlineBrowser() {
    renderMode = 'inline';
    const target = getTarget();
    if (!target) return;

    if (cachedTree) renderTree(cachedTree);
    else target.innerHTML = '<div class="mod-empty">Loading wildcard files...</div>';
    setModuleParam('wildcard', 'get_file_tree', '');
  }

  function ensureEditorPanel() {
    if (editorPanel) return editorPanel;
    editorPanel = document.getElementById('wildcardEditorPopup');
    if (!editorPanel) {
      editorPanel = document.createElement('div');
      editorPanel.id = 'wildcardEditorPopup';
      editorPanel.className = 'wc-editor-popup';
      document.body.appendChild(editorPanel);
    }
    return editorPanel;
  }

  function closeEditor() {
    editorOpen = false;
    editMode = false;
    currentPath = '';
    currentContent = '';
    if (editorPanel) editorPanel.classList.remove('open');
    renderTree(cachedTree);
  }

  function markActiveFile(element = null) {
    const target = getTarget();
    if (!target) return;
    target.querySelectorAll('.wc-file.active').forEach(file => file.classList.remove('active'));
    const active = element
      || Array.from(target.querySelectorAll('.wc-file')).find(file => file.dataset.path === currentPath);
    if (active) active.classList.add('active');
  }

  function toggleFolder(element) {
    if (!element) return;
    const folderName = element.dataset.folder || '';
    const isOpen = element.classList.toggle('open');
    if (!folderName) return;
    if (isOpen) openFolders.add(folderName);
    else openFolders.delete(folderName);
  }

  function openFile(element) {
    const path = element?.dataset?.path || '';
    if (!path) return;
    currentPath = path;
    markActiveFile(element);
    setModuleParam('wildcard', 'read_file', path);
  }

  function onMessage(message) {
    if (message.action === 'file_tree') renderTree(message.tree);
    else if (message.action === 'file_content') renderEditor(message.path, message.content);
    else if (message.action === 'preview_result') showPreview(message.name, message.result);
    else if (message.action === 'save_ok') showToast('File saved', 'success');
    else if (message.action === 'file_deleted') {
      showToast('File deleted', 'success');
      currentPath = '';
      currentContent = '';
      closeEditor();
    }
  }

  function renderTree(tree) {
    cachedTree = Array.isArray(tree) ? tree : [];
    if (!editorOpen) editMode = false;
    const fullMode = renderMode !== 'inline';
    let html = `<div class="mod-wc-toolbar${fullMode ? '' : ' inline'}">`;
    if (fullMode) {
      html += '<button class="mod-btn-sm" onclick="openModule(\'wildcard\',{forceOpen:true})">← Back</button>';
    }
    html += '<button class="mod-btn-sm" onclick="wcPromptNewFile()">+ New File</button>'
      + '<button class="mod-btn-sm" onclick="setModuleParam(\'wildcard\',\'get_file_tree\',\'\')">Refresh</button>'
      + '</div>';
    html += `<div class="mod-wc-tree${fullMode ? '' : ' inline'}">`;
    if (!cachedTree.length) {
      html += '<div class="mod-empty">No wildcard files found</div>';
    } else {
      for (const item of cachedTree) {
        if (item.type === 'folder') {
          html += `<div class="wc-folder${openFolders.has(item.name) ? ' open' : ''}" data-folder="${escHtml(item.name)}"><div class="wc-folder-name" onclick="wcToggleFolder(this.parentElement)">📁 ${escHtml(item.name)} <span class="wc-count">(${item.files.length})</span></div>`;
          html += '<div class="wc-folder-children">';
          for (const file of item.files) {
            html += `<div class="wc-file${file.path === currentPath ? ' active' : ''}" data-path="${escHtml(file.path)}" onclick="wcOpenFile(this)">📄 ${escHtml(file.name)} <span class="wc-count">${file.lines}L</span></div>`;
          }
          html += '</div></div>';
        } else {
          html += `<div class="wc-file${item.path === currentPath ? ' active' : ''}" data-path="${escHtml(item.path)}" onclick="wcOpenFile(this)">📄 ${escHtml(item.name)} <span class="wc-count">${item.lines}L</span></div>`;
        }
      }
    }
    html += '</div>';
    if (fullMode) {
      html += `<div class="mod-section" style="margin-top:10px">
        <div class="mod-section-label">Wildcard Syntax Guide</div>
        <div class="wc-syntax-guide">
          <div><code>__name__</code> — Random pick from <code>name.txt</code></div>
          <div><code>__*name__</code> — Sequential (ordered)</div>
          <div><code>__*master__</code> + <code>__$master:slave__</code> — Dependent</div>
          <div><code>200:text</code> — Weighted entry (default 100)</div>
          <div><code>__folder/name__</code> — Subfolder path</div>
        </div>
      </div>`;
    }
    writeTarget(html);
    markActiveFile();
  }

  function renderEditor(path, content) {
    currentPath = path;
    currentContent = content || '';
    editMode = false;
    editorOpen = true;
    const fname = path.split('/').pop();
    const wcName = fname.replace('.txt', '');
    const panel = ensureEditorPanel();
    closeAuxiliaryPopups(panel, { keepChunk: true });
    panel.classList.add('open');
    panel.innerHTML = `
      <div class="wc-editor-popup-header">
        <div class="wc-editor-popup-title">
          <span>Wildcard File</span>
          <strong>${escHtml(path)}</strong>
        </div>
        <button class="module-popup-icon-btn danger" onclick="wcCloseEditor()" title="Close wildcard file" aria-label="Close wildcard file">×</button>
      </div>
      <div class="wc-editor-popup-body">
        <div class="mod-wc-toolbar">
          <span class="wc-file-path">${escHtml(path)}</span>
          <span style="flex:1"></span>
          <button class="mod-btn-sm" id="wcEditBtn" onclick="wcToggleEdit()">Edit</button>
          <button class="mod-btn-sm mod-btn-danger" onclick="wcDeleteFile()">Delete</button>
        </div>
        <div class="mod-section mod-wc-editor-section">
          <textarea class="wc-editor" id="wcEditor" readonly>${escHtml(currentContent)}</textarea>
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
            <button class="mod-btn-sm" onclick="setModuleParam('wildcard','preview_wildcard','${escHtml(wcName)}')">Roll ×5</button>
            <div class="wc-preview" id="wcPreview"></div>
          </div>
        </div>
      </div>
    `;
    positionFloatingPanel(panel, modulePopup);
    markActiveFile();
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
    currentContent = editor.value;
    setModuleParam('wildcard', 'save_file', JSON.stringify({ path: currentPath, content: editor.value }));
  }

  async function deleteFile() {
    if (!currentPath) return;
    const confirmed = await Promise.resolve(confirmDialog('Delete ' + currentPath + '?', {
      title: 'Delete wildcard file',
      okText: '삭제',
      cancelText: '취소',
    }));
    if (!confirmed) return;
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
    currentContent = editor.value;
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

  async function promptNewFile() {
    const name = await Promise.resolve(promptDialog('New wildcard filename (e.g. "my_tags" or "folder/my_tags"):', {
      title: 'New wildcard file',
      okText: '생성',
      cancelText: '취소',
      placeholder: 'folder/my_tags',
    }));
    if (!name || !name.trim()) return;
    setModuleParam('wildcard', 'create_file', name.trim());
  }

  function isEditorOpen() {
    return editorOpen;
  }

  function relayout() {
    if (editorOpen && editorPanel) positionFloatingPanel(editorPanel, modulePopup);
  }

  return {
    openBrowser,
    renderInlineBrowser,
    closeEditor,
    isEditorOpen,
    relayout,
    toggleFolder,
    openFile,
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
