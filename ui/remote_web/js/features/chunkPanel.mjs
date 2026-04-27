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
  setModuleParam,
  onPromptEdit,
  fireModuleOninput,
  escHtml,
}) {
  let open = false;
  let anchorEl = null;          // 명시적으로 전달된 anchor (예: $ trigger 의 textarea)
  let anchorPinned = false;     // true 면 자동 재해결을 하지 않음 (명시 anchor 우선)
  let triggerInfo = null;
  let latestGroups = [];

  function requestState() {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'get_module_state', module_id: 'chunk' }));
    }
  }

  function getAnchor(target = null) {
    return target?.closest?.('.module-popup, .pe-popup, .refine-popup, .tag-filter-popup')
      || (modulePopup?.classList.contains('open') ? modulePopup : null);
  }

  function isAnchorVisible(el) {
    if (!el || !document.contains(el)) return false;
    // popup 류는 .open 클래스가 떠 있어야 가시 — 없으면 화면에 없음으로 간주
    if (el.classList?.contains('module-popup') || el.classList?.contains('pe-popup')
        || el.classList?.contains('refine-popup') || el.classList?.contains('tag-filter-popup')) {
      return el.classList.contains('open');
    }
    return true;
  }

  function resolveLiveAnchor() {
    // 명시 anchor 가 있고 실제로 표시 중이면 우선 (예: $ trigger 가 잡은 modulePopup)
    if (anchorPinned && isAnchorVisible(anchorEl)) return anchorEl;
    // 동적 fallback: 현재 열려있는 모듈/aux popup 만 anchor 로 사용.
    // anchor 가 없으면 standalone 모드로 viewer-wrapper(우측 결과 영역) 위에 띄움.
    // 좌측 control-panel(prompt 입력 영역)을 anchor 로 쓰면 chunk 가 prompt 영역을 침범하므로 금지.
    if (modulePopup?.classList.contains('open')) return modulePopup;
    const auxOpen = document.querySelector('.pe-popup.open, .refine-popup.open');
    if (auxOpen) return auxOpen;
    return null;
  }

  function applyStandalonePosition() {
    if (!panel) return false;
    // viewer-wrapper(우측 결과 영역)의 좌측 가장자리에 abut — prompt 영역 침범 금지
    const viewer = document.querySelector('.viewer-wrapper');
    if (!viewer) return false;
    const r = viewer.getBoundingClientRect();
    if (!r || r.width <= 0) return false;
    const vv = window.visualViewport;
    const viewportTop = vv ? vv.offsetTop : 0;
    const viewportHeight = vv ? vv.height : window.innerHeight;
    const margin = 12;
    const width = Math.min(420, Math.max(320, r.width - margin * 2));
    const top = Math.max(viewportTop + margin, r.top + margin);
    panel.style.left = `${r.left + margin}px`;
    panel.style.top = `${top}px`;
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.width = `${width}px`;
    panel.style.maxWidth = `${r.width - margin * 2}px`;
    panel.style.maxHeight = `${Math.max(220, viewportHeight - (top - viewportTop) - margin)}px`;
    return true;
  }

  function placePanel(liveAnchor) {
    if (!panel) return;
    if (liveAnchor) {
      positionFloatingPanel(panel, liveAnchor);
      return;
    }
    if (applyStandalonePosition()) return;
    // 최후의 폴백 — viewport 기준 (positionFloatingPanel 의 anchorless 분기)
    positionFloatingPanel(panel, null);
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
    anchorEl = anchor || null;
    anchorPinned = !!anchor;
    open = true;
    if (panel) {
      panel.classList.add('open');
      const liveAnchor = resolveLiveAnchor();
      panel.classList.toggle('chunk-panel-standalone', !liveAnchor);
      const body = panel.querySelector('.pe-popup-body');
      if (body) {
        body.innerHTML = '<div style="text-align:center;color:var(--text-dim);padding:20px">Loading...</div>';
      }
      placePanel(liveAnchor);
    }
    updateModuleBtnState();
    requestState();
  }

  function close() {
    open = false;
    triggerInfo = null;
    anchorEl = null;
    anchorPinned = false;
    if (panel) {
      panel.classList.remove('open');
      panel.classList.remove('chunk-panel-standalone');
    }
    updateModuleBtnState();
  }

  function renderAddForm(groups) {
    const groupOptions = groups.map(group => `<option value="${escHtml(group.name)}"></option>`).join('');
    const defaultGroup = groups[0]?.name || 'default';
    return `
      <form class="chunk-add-form" onsubmit="return chunkSaveNew(event)">
        <div class="chunk-add-head">
          <span class="mod-section-label">Add Chunk</span>
          <button class="mod-btn-sm" type="button" onclick="chunkUseSelection()">Use Selection</button>
        </div>
        <div class="chunk-add-grid">
          <input class="mod-input" id="chunkAddGroup" list="chunkAddGroups" value="${escHtml(defaultGroup)}" placeholder="group">
          <input class="mod-input" id="chunkAddKey" placeholder="key">
        </div>
        <datalist id="chunkAddGroups">${groupOptions}</datalist>
        <textarea class="mod-textarea chunk-add-value" id="chunkAddValue" placeholder="tag, tag, tag"></textarea>
        <div class="chunk-add-actions">
          <button class="mod-action-btn mod-start" type="submit">Add</button>
        </div>
      </form>
    `;
  }

  function render(message) {
    const chunkBody = panel ? panel.querySelector('.pe-popup-body') : null;
    const renderTarget = chunkBody || moduleBody;
    const groups = message.groups || [];
    latestGroups = groups;
    if (!renderTarget) {
      return;
    }

    let html = '<div class="chunk-panel-content">';
    html += '<div class="chunk-hint">Select an item to insert at cursor. Type <code>$</code> to browse chunks.</div>';
    if (!groups.length) {
      html += '<div class="mod-empty">No chunks found.</div>';
    } else {
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
    }
    html += renderAddForm(groups);
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

  function getSelectionText() {
    const target = getAcTarget() || promptEdit;
    if (!target || target.selectionStart == null || target.selectionEnd == null) return '';
    if (target.selectionStart === target.selectionEnd) return '';
    return target.value.substring(target.selectionStart, target.selectionEnd).trim();
  }

  function useSelection() {
    const valueInput = panel ? panel.querySelector('#chunkAddValue') : null;
    if (!valueInput) return;
    const selection = getSelectionText();
    if (!selection) {
      showToast('No prompt selection', 'error');
      return;
    }
    valueInput.value = selection;
  }

  function saveNew(event) {
    if (event) event.preventDefault();
    const groupInput = panel ? panel.querySelector('#chunkAddGroup') : null;
    const keyInput = panel ? panel.querySelector('#chunkAddKey') : null;
    const valueInput = panel ? panel.querySelector('#chunkAddValue') : null;
    const fallbackGroup = latestGroups[0]?.name || 'default';
    const group = (groupInput?.value || fallbackGroup).trim();
    const key = (keyInput?.value || '').trim();
    const value = valueInput?.value || '';
    if (!group || !key) {
      showToast('Group and key are required', 'error');
      return false;
    }
    setModuleParam('instant_wildcard', 'upsert', JSON.stringify({
      file: group.endsWith('.json') ? group : `${group}.json`,
      key,
      value,
    }));
    document.defaultView?.setTimeout(requestState, 180);
    if (keyInput) keyInput.value = '';
    if (valueInput) valueInput.value = '';
    return false;
  }

  function relayout() {
    if (!open || !panel) return;
    const liveAnchor = resolveLiveAnchor();
    panel.classList.toggle('chunk-panel-standalone', !liveAnchor);
    placePanel(liveAnchor);
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
    saveNew,
    useSelection,
    relayout,
    isOpen,
    setTriggerInfo,
    clearTriggerInfo,
    panelElement,
  };
}
