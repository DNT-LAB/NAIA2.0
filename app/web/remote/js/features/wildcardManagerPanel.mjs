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
  let simTab = 'random';
  let simSlave = '';
  let slavePick = false;
  let lastInspect = null;
  let currentWcName = '';

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
    // While picking a dependent slave, a tree click registers the slave instead of
    // opening the file (the management surface is temporarily locked into pick mode).
    if (slavePick) {
      simSlave = path.replace(/\.txt$/i, '');
      slavePick = false;
      showToast('slave: ' + simSlave, 'success');
      requestInspect();
      return;
    }
    currentPath = path;
    markActiveFile(element);
    setModuleParam('wildcard', 'read_file', path);
  }

  function onMessage(message) {
    if (message.action === 'file_tree') renderTree(message.tree);
    else if (message.action === 'file_content') renderEditor(message.path, message.content);
    else if (message.action === 'preview_result') showPreview(message.name, message.result);
    else if (message.action === 'inspect_result') { lastInspect = message; renderTabs(); }
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
    currentWcName = path.replace(/\.txt$/i, '');
    simSlave = '';
    slavePick = false;
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
        <div class="mod-section wc-sim-area" id="wcSimArea"><div class="mod-empty">미리보기 로딩…</div></div>
      </div>
    `;
    ensureWildcardSimStyle();
    positionFloatingPanel(panel, modulePopup);
    markActiveFile();
    requestInspect();
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

  // ---- Tabbed preview / assembly (랜덤 | 순차 | $종속:순차) in the file popup ----
  function requestInspect() {
    if (!currentWcName) return;
    setModuleParam('wildcard', 'inspect', JSON.stringify({ name: currentWcName, slave: simSlave, n: 12 }));
  }

  function setSimTab(tab) {
    simTab = tab;
    renderTabs();
  }

  function pickSlave() {
    slavePick = true;
    simTab = 'dependent';
    renderTabs();
    showToast('좌측 트리에서 slave로 쓸 와일드카드를 클릭하세요', 'info');
  }

  function clearSlave() {
    simSlave = '';
    slavePick = false;
    requestInspect();
  }

  function syntaxRow(syntax) {
    return `<div class="wc-syntax-row"><span class="wc-syntax">${escHtml(syntax)}</span>`
      + `<button class="mod-btn-sm" onclick="wcCopySyntax(this)">복사</button>`
      + `<button class="mod-btn-sm" onclick="wcInsertSyntax(this)">삽입</button></div>`;
  }

  function renderDependentTab(info, name) {
    if (slavePick) {
      return `<div class="wc-pick-banner"><span>좌측 트리에서 <b>slave</b>로 쓸 와일드카드를 클릭하세요</span>`
        + `<button class="mod-btn-sm" onclick="wcClearSlave()">취소</button></div>`;
    }
    const explain = `<div class="wc-dep-explain">현재 <b>${escHtml(name)}</b>(master)가 <b>매 생성마다</b> 바뀝니다.<br>`
      + `slave는 master가 한 바퀴 돌 때마다 한 칸 전진합니다.</div>`;
    if (!simSlave) {
      return explain + `<button class="wc-slave-pick" onclick="wcPickSlave()">＋ slave 선택</button>`;
    }
    const cycle = info && info.cycle != null ? info.cycle : (info ? info.count || 0 : 0);
    const total = info ? info.total || 0 : 0;
    const slaveCount = info ? info.slave_count || 0 : 0;
    return explain
      + `<div class="wc-slave-row"><span class="mod-section-label" style="margin:0">slave</span>`
      + `<span class="wc-sel-chip">${escHtml(simSlave)} <span class="wc-pick-count">${slaveCount}</span></span>`
      + `<button class="mod-btn-sm" onclick="wcPickSlave()">다시 선택</button>`
      + `<button class="mod-btn-sm" onclick="wcClearSlave()">✕</button></div>`
      + syntaxRow(`__*${name}__`)
      + syntaxRow(`__$${name}:${simSlave}__`)
      + `<div class="wc-stat-grid">`
      + `<div><div class="wc-stat-label">1바퀴 생성 횟수</div><div class="wc-stat-val">${cycle}</div></div>`
      + `<div><div class="wc-stat-label">완주 총 생성 횟수</div><div class="wc-stat-val">${total} <small>(${cycle}×${slaveCount})</small></div></div>`
      + `</div>`;
  }

  function renderTabs() {
    const area = document.getElementById('wcSimArea');
    if (!area) return;
    const info = lastInspect;
    const name = currentWcName;
    const tabs = [['random', '랜덤'], ['sequential', '순차'], ['dependent', '$종속:순차']];
    const tabBar = tabs.map(([key, label]) =>
      `<button class="wc-tab${simTab === key ? ' on' : ''}" onclick="wcSimTab('${key}')">${label}</button>`).join('');
    let body;
    if (simTab === 'dependent') {
      body = renderDependentTab(info, name);
    } else if (!info) {
      body = '<div class="mod-empty">로딩…</div>';
    } else if (simTab === 'sequential') {
      const lines = (info.ordered || []).map((s, i) =>
        `<div class="wc-sample-line"><span class="wc-idx">${i + 1}</span>${escHtml(String(s))}</div>`).join('');
      body = syntaxRow(`__*${name}__`)
        + `<div class="wc-slave-row" style="margin:8px 0 6px"><span class="mod-section-label" style="margin:0">순차 진행 (정렬된 순서)</span></div>`
        + `<div class="wc-sim-samples">${lines || '<div class="mod-empty">비어 있음</div>'}</div>`
        + `<div class="wc-an-total">총 <b>${info.count || 0}</b>개 · 한 바퀴 ${info.count || 0}회 생성</div>`;
    } else {
      const lines = (info.random || []).map(s =>
        `<div class="wc-sample-line">${escHtml(String(s))}</div>`).join('');
      body = syntaxRow(`__${name}__`)
        + `<div class="wc-slave-row" style="margin:8px 0 6px"><span class="mod-section-label" style="margin:0">무작위 미리보기</span>`
        + `<button class="wc-sim-roll" onclick="wcRoll()">🎲 다시 뽑기</button></div>`
        + `<div class="wc-sim-samples">${lines || '<div class="mod-empty">비어 있음</div>'}</div>`;
    }
    area.innerHTML = `<div class="wc-tabs">${tabBar}</div><div class="wc-tab-body">${body}</div>`;
  }

  function ensureWildcardSimStyle() {
    if (document.getElementById('wc-sim-style')) return;
    const style = document.createElement('style');
    style.id = 'wc-sim-style';
    style.textContent = `
.wc-sim-area{border-top:1px solid var(--border-dim);padding-top:10px}
.wc-tabs{display:flex;gap:4px;border-bottom:1px solid var(--border-dim);margin-bottom:10px}
.wc-tabs .wc-tab{background:none;border:0;border-bottom:2px solid transparent;color:var(--text-dim);padding:6px 13px;font-size:12px;font-weight:600;cursor:pointer;font-family:var(--font-mono)}
.wc-tabs .wc-tab.on{color:var(--text-primary);border-bottom-color:var(--accent)}
.wc-dep-explain{font-size:11px;color:var(--text-muted);line-height:1.65;background:var(--bg-deep);border:1px solid var(--border-dim);border-radius:7px;padding:8px 10px;margin-bottom:9px}
.wc-dep-explain b{color:#6fb0ff}
.wc-pick-banner{font-size:11px;color:var(--text-primary);background:rgba(124,106,239,.13);border:1px solid var(--accent);border-radius:7px;padding:8px 10px;margin-bottom:9px;display:flex;align-items:center;gap:8px;justify-content:space-between}
.wc-slave-row{display:flex;align-items:center;gap:8px;margin-bottom:9px;flex-wrap:wrap}
.wc-sel-chip{display:inline-flex;align-items:center;gap:6px;background:var(--bg-deep);border:1px solid var(--accent-secondary);border-radius:999px;padding:4px 11px;font-size:11px;color:var(--text-primary)}
.wc-sim-area .wc-pick-count{font-family:var(--font-mono);font-size:10px;color:var(--text-dim)}
.wc-syntax-row{display:flex;align-items:center;gap:7px;margin:6px 0}
.wc-syntax-row .wc-syntax{flex:1;font-family:var(--font-mono);font-size:12px;color:var(--accent-glow);background:var(--bg-deep);border:1px solid var(--border);border-radius:7px;padding:7px 10px;word-break:break-all}
.wc-stat-grid{display:flex;gap:8px;margin-top:9px}
.wc-stat-grid>div{flex:1;background:var(--bg-deep);border:1px solid var(--border-dim);border-radius:8px;padding:8px 10px}
.wc-stat-label{font-size:10px;color:var(--text-dim)}
.wc-stat-val{font-size:21px;font-weight:700;color:var(--success);font-family:var(--font-mono);margin-top:2px}
.wc-stat-val small{font-size:11px;color:var(--text-dim);font-weight:400}
.wc-sim-samples{display:flex;flex-direction:column;gap:2px;max-height:160px;overflow:auto}
.wc-sim-samples .wc-sample-line{font-size:12px;color:var(--text-primary);padding:3px 0;border-bottom:1px solid var(--border-dim)}
.wc-sim-samples .wc-sample-line:last-child{border-bottom:0}
.wc-sim-samples .wc-idx{color:var(--text-dim);font-family:var(--font-mono);font-size:10px;margin-right:6px}
.wc-an-total{margin-top:7px;font-size:12px;color:var(--text-primary)}
.wc-sim-roll,.wc-slave-pick{height:26px;padding:0 12px;font-size:11px;font-weight:600;border-radius:6px;cursor:pointer;border:1px solid var(--border);background:var(--bg-deep);color:var(--text-primary)}
.wc-slave-pick{background:var(--accent);color:#fff;border-color:transparent}`;
    document.head.appendChild(style);
  }

  return {
    openBrowser,
    setSimTab,
    pickSlave,
    clearSlave,
    requestInspect,
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
