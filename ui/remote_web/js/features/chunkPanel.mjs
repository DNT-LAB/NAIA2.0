export function createChunkPanel({
  document,
  panel,
  moduleBody,
  modulePopup,
  promptEdit,
  getWs,
  WebSocket,
  getSharedMode,
  getAcTarget,
  showToast,
  updateModuleBtnState,
  positionFloatingPanel,
  onPromptEdit,
  fireModuleOninput,
  escHtml,
}) {
  let open = false;
  let anchorEl = null;
  let triggerInfo = null;

  function requestState() {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'get_module_state', module_id: 'chunk' }));
    }
  }

  function getAnchor(target = null) {
    return target?.closest?.('.module-popup, .pe-popup, .refine-popup, .tag-filter-popup') || modulePopup;
  }

  function openPanel(anchor = null, toggle = false) {
    if (getSharedMode()) {
      showToast('This module is not available in Shared Server Mode', 'error');
      return;
    }
    if (toggle && open) {
      close();
      return;
    }
    anchorEl = anchor || anchorEl || modulePopup;
    open = true;
    if (panel) {
      panel.classList.add('open');
      const body = panel.querySelector('.pe-popup-body');
      if (body) {
        body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
      }
      positionFloatingPanel(panel, anchorEl);
    }
    updateModuleBtnState();
    requestState();
  }

  function close() {
    open = false;
    triggerInfo = null;
    if (panel) panel.classList.remove('open');
    updateModuleBtnState();
  }

  function render(message) {
    const chunkBody = panel ? panel.querySelector('.pe-popup-body') : null;
    const renderTarget = (open && chunkBody) ? chunkBody : moduleBody;
    const groups = message.groups || [];
    if (!groups.length) {
      renderTarget.innerHTML = '<div class="mod-empty">No instant wildcards found.<br>Add them via the desktop Instant Wildcard module.</div>';
      return;
    }

    let html = '<div class="chunk-hint">Select an item to insert at cursor. Type <code>$</code> in prompt to trigger.</div>';
    html += '<div class="chunk-tree">';
    for (const group of groups) {
      html += '<div class="chunk-group">';
      html += `<div class="chunk-group-name" onclick="chunkToggleGroup(this.parentElement)">\u{1F4C1} ${escHtml(group.name)} <span class="wc-count">(${group.items.length})</span></div>`;
      html += '<div class="chunk-group-items">';
      for (const item of group.items) {
        const preview = item.value.length > 80 ? item.value.substring(0, 80) + '\u2026' : item.value;
        html += `<div class="chunk-item" onclick="chunkInsert(this)" data-value="${escHtml(item.value)}">`;
        html += `<div class="chunk-item-key">${escHtml(item.key)}</div>`;
        html += `<div class="chunk-item-preview">${escHtml(preview)}</div>`;
        html += '</div>';
      }
      html += '</div></div>';
    }
    html += '</div>';
    renderTarget.innerHTML = html;
    relayout();
  }

  function toggleGroup(groupEl) {
    const wasOpen = groupEl.classList.contains('open');
    groupEl.parentElement.querySelectorAll('.chunk-group.open').forEach(group => {
      group.classList.remove('open');
    });
    if (!wasOpen) groupEl.classList.add('open');
  }

  function insert(element) {
    const value = element.dataset.value;
    if (!value) return;
    const target = getAcTarget() || promptEdit;
    const text = target.value || '';
    target.focus();

    let insertStart = 0;
    let insertEnd = 0;
    let insertText = '';
    if (triggerInfo) {
      insertStart = triggerInfo.start;
      insertEnd = triggerInfo.end;
      insertText = value;
      triggerInfo = null;
    } else {
      const pos = target.selectionStart != null ? target.selectionStart : text.length;
      const before = text.substring(0, pos);
      const sep = before.trim().length > 0 && !/,\s*$/.test(before) ? ', ' : '';
      insertStart = pos;
      insertEnd = pos;
      insertText = sep + value;
    }

    target.value = text.substring(0, insertStart) + insertText + text.substring(insertEnd);
    const newPos = insertStart + insertText.length;
    target.selectionStart = target.selectionEnd = newPos;
    if (target === promptEdit) onPromptEdit();
    else fireModuleOninput(target);
    close();
  }

  function relayout() {
    if (open && panel) positionFloatingPanel(panel, anchorEl || modulePopup);
  }

  function isOpen() {
    return open;
  }

  function setTriggerInfo(info) {
    triggerInfo = info;
  }

  function clearTriggerInfo() {
    triggerInfo = null;
  }

  function panelElement() {
    return panel;
  }

  return {
    requestState,
    getAnchor,
    open: openPanel,
    close,
    render,
    toggleGroup,
    insert,
    relayout,
    isOpen,
    setTriggerInfo,
    clearTriggerInfo,
    panelElement,
  };
}
