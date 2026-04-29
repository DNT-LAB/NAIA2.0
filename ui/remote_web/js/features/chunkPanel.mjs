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
  const CHUNK_PANEL_WIDTH = 420;
  const CHUNK_PANEL_MIN_WIDTH = 320;
  let open = false;
  let anchorEl = null;          // 명시적으로 전달된 anchor (예: $ trigger 의 textarea)
  let anchorPinned = false;     // true 면 자동 재해결을 하지 않음 (명시 anchor 우선)
  let triggerInfo = null;
  let latestGroups = [];
  let pendingAddPrefill = null;
  let lastAddGroup = '';
  let selectionMenu = null;
  let selectionMenuPayload = null;

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
    const auxOpen = Array.from(document.querySelectorAll('.pe-popup.open, .refine-popup.open'))
      .find(el => el !== panel);
    if (auxOpen) return auxOpen;
    return null;
  }

  function getSafeRegion(margin = 12) {
    const viewer = document.querySelector('.viewer-wrapper');
    const controlPanel = document.querySelector('.control-panel');
    const viewerRect = viewer?.getBoundingClientRect();
    const controlRect = controlPanel?.getBoundingClientRect();
    const vv = window.visualViewport;
    const viewportLeft = vv ? vv.offsetLeft : 0;
    const viewportTop = vv ? vv.offsetTop : 0;
    const viewportWidth = vv ? vv.width : window.innerWidth;
    const viewportHeight = vv ? vv.height : window.innerHeight;
    const regionLeft = Math.max(
      viewportLeft + margin,
      viewerRect?.left ?? ((controlRect?.right ?? viewportLeft) + margin),
      controlRect ? controlRect.right + margin : viewportLeft + margin,
    );
    const regionRight = viewportLeft + viewportWidth - margin;
    const baseTop = viewerRect?.top ?? controlRect?.top ?? viewportTop;
    return { viewportLeft, viewportTop, viewportWidth, viewportHeight, regionLeft, regionRight, baseTop, margin };
  }

  function setPanelFrame(left, top, width, regionWidth, maxHeight) {
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
    panel.style.right = 'auto';
    panel.style.bottom = 'auto';
    panel.style.width = `${width}px`;
    panel.style.maxWidth = `${regionWidth}px`;
    panel.style.maxHeight = `${maxHeight}px`;
  }

  function applyStandalonePosition() {
    if (!panel) return false;
    const region = getSafeRegion(12);
    if (region.regionRight <= region.regionLeft) return false;
    const { viewportLeft, viewportTop, viewportHeight, regionLeft, regionRight, baseTop, margin } = region;
    const regionWidth = Math.max(280, regionRight - regionLeft);
    const minWidth = Math.min(CHUNK_PANEL_MIN_WIDTH, regionWidth);
    const width = Math.min(CHUNK_PANEL_WIDTH, Math.max(minWidth, regionWidth - margin * 2));
    const left = Math.min(regionRight - width, regionLeft);
    const top = Math.max(viewportTop + margin, baseTop + margin);
    const maxHeight = Math.max(220, viewportHeight - (top - viewportTop) - margin);

    setPanelFrame(Math.max(viewportLeft + margin, left), top, width, regionWidth, maxHeight);
    return true;
  }

  function applyAnchoredPosition(anchor) {
    if (!panel || !anchor || !isAnchorVisible(anchor)) return false;
    const anchorRect = anchor.getBoundingClientRect();
    if (!anchorRect || anchorRect.width <= 0 || anchorRect.height <= 0) return false;
    const region = getSafeRegion(12);
    if (region.regionRight <= region.regionLeft) return false;
    const { viewportTop, viewportHeight, regionLeft, regionRight, margin } = region;
    const regionWidth = Math.max(280, regionRight - regionLeft);
    const minWidth = Math.min(CHUNK_PANEL_MIN_WIDTH, regionWidth);
    const width = Math.min(CHUNK_PANEL_WIDTH, Math.max(minWidth, regionWidth - margin * 2));
    let left = anchorRect.right + margin;
    if (left < regionLeft || left + width > regionRight) {
      left = regionLeft + Math.max(0, (regionWidth - width) / 2);
    }
    left = Math.min(Math.max(regionLeft, left), regionRight - width);
    const top = Math.max(viewportTop + margin, anchorRect.top);
    const maxHeight = Math.max(220, viewportHeight - (top - viewportTop) - margin);
    setPanelFrame(left, top, width, regionWidth, maxHeight);
    return true;
  }

  function placePanel(liveAnchor) {
    if (!panel) return;
    if (liveAnchor) {
      if (applyAnchoredPosition(liveAnchor)) return;
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
    hideSelectionMenu();
    updateModuleBtnState();
  }

  function chooseAddGroup(groups) {
    const groupNames = groups.map(group => group.name).filter(Boolean);
    if (lastAddGroup && groupNames.includes(lastAddGroup)) return lastAddGroup;
    return groupNames[0] || 'default';
  }

  function syncAddGroup(groupName) {
    const normalized = (groupName || '').trim();
    if (!normalized) return;
    lastAddGroup = normalized;
    const groupInput = panel ? panel.querySelector('#chunkAddGroup') : null;
    if (!groupInput) return;
    const hasOption = Array.from(groupInput.options || []).some(option => option.value === normalized);
    if (!hasOption) return;
    if (groupInput.value !== normalized) {
      groupInput.value = normalized;
      groupInput.dispatchEvent(new Event('input', { bubbles: true }));
      groupInput.dispatchEvent(new Event('change', { bubbles: true }));
    }
  }

  function renderAddForm(groups) {
    const defaultGroup = chooseAddGroup(groups);
    const groupNames = groups.length ? groups.map(group => group.name).filter(Boolean) : [defaultGroup];
    const groupOptions = groupNames.map(name => {
      const selected = name === defaultGroup ? ' selected' : '';
      return `<option value="${escHtml(name)}"${selected}>${escHtml(name)}</option>`;
    }).join('');
    return `
      <form class="chunk-add-form" onsubmit="return chunkSaveNew(event)">
        <div class="chunk-add-head">
          <span class="mod-section-label">Add Chunk</span>
          <button class="mod-btn-sm" type="button" onclick="chunkUseSelection()">Use Selection</button>
        </div>
        <div class="chunk-add-grid">
          <select class="mod-select" id="chunkAddGroup">${groupOptions}</select>
          <input class="mod-input" id="chunkAddKey" placeholder="key">
        </div>
        <textarea class="mod-textarea chunk-add-value" id="chunkAddValue" placeholder="tag, tag, tag"></textarea>
        <div class="chunk-add-actions">
          <button class="mod-action-btn mod-start" type="submit">Add</button>
        </div>
      </form>
    `;
  }

  function selectedTextFrom(target) {
    if (!target || target.selectionStart == null || target.selectionEnd == null) return '';
    if (target.selectionStart === target.selectionEnd) return '';
    return target.value.substring(target.selectionStart, target.selectionEnd).trim();
  }

  function suggestKeyFromValue(value) {
    const firstToken = (value || '')
      .split(/[,\n]/)
      .map(part => part.trim())
      .find(Boolean) || '';
    const cleaned = firstToken
      .replace(/^[({\[\s]+|[)}\]\s]+$/g, '')
      .replace(/^[+-]?\d+(?:\.\d+)?::\s*/, '')
      .replace(/\s*::\s*$/, '')
      .replace(/^#+/, '')
      .replace(/[^\p{L}\p{N}_-]+/gu, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 40);
    return cleaned || `chunk_${Date.now().toString(36)}`;
  }

  function applyPendingAddPrefill() {
    if (!pendingAddPrefill || !panel) return false;
    const keyInput = panel.querySelector('#chunkAddKey');
    const valueInput = panel.querySelector('#chunkAddValue');
    if (!keyInput || !valueInput) return false;
    valueInput.value = pendingAddPrefill.value;
    keyInput.value = pendingAddPrefill.key || suggestKeyFromValue(pendingAddPrefill.value);
    keyInput.focus();
    keyInput.select();
    pendingAddPrefill = null;
    return true;
  }

  function hideSelectionMenu() {
    selectionMenu?.classList.remove('open');
    selectionMenuPayload = null;
  }

  function ensureSelectionMenu() {
    if (selectionMenu) return selectionMenu;
    selectionMenu = document.createElement('div');
    selectionMenu.className = 'result-context-menu chunk-selection-menu';
    selectionMenu.innerHTML = `
      <div class="result-context-group">
        <button class="result-context-item" type="button" data-action="undo"><span>Undo</span></button>
        <button class="result-context-item" type="button" data-action="redo"><span>Redo</span></button>
      </div>
      <div class="result-context-separator"></div>
      <div class="result-context-group">
        <button class="result-context-item" type="button" data-action="cut"><span>Cut</span></button>
        <button class="result-context-item" type="button" data-action="copy"><span>Copy</span></button>
        <button class="result-context-item" type="button" data-action="paste"><span>Paste</span></button>
        <button class="result-context-item" type="button" data-action="paste-plain"><span>Paste and match style</span></button>
        <button class="result-context-item" type="button" data-action="select-all"><span>Select all</span></button>
      </div>
      <div class="result-context-separator"></div>
      <div class="result-context-group">
        <button class="result-context-item chunk-context-add" type="button" data-action="add-chunk">
          <span>Add to Chunk</span><span class="result-context-arrow">›</span>
        </button>
      </div>
    `;
    document.body.appendChild(selectionMenu);
    selectionMenu.addEventListener('click', event => {
      const actionButton = event.target.closest('[data-action]');
      if (!actionButton || !selectionMenuPayload) return;
      event.preventDefault();
      runSelectionMenuAction(actionButton.dataset.action);
    });
    document.addEventListener('pointerdown', event => {
      if (selectionMenu?.classList.contains('open') && !selectionMenu.contains(event.target)) {
        hideSelectionMenu();
      }
    }, true);
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') hideSelectionMenu();
    });
    return selectionMenu;
  }

  function notifyTextChanged(target) {
    if (!target) return;
    if (target === promptEdit) onPromptEdit();
    else fireModuleOninput(target);
  }

  function replaceTargetSelection(target, text) {
    if (!target) return;
    const start = target.selectionStart ?? target.value.length;
    const end = target.selectionEnd ?? start;
    target.focus();
    if (typeof target.setRangeText === 'function') {
      target.setRangeText(text, start, end, 'end');
    } else {
      target.value = `${target.value.substring(0, start)}${text}${target.value.substring(end)}`;
      const next = start + text.length;
      target.selectionStart = target.selectionEnd = next;
    }
    notifyTextChanged(target);
  }

  async function writeClipboard(text) {
    const clipboard = document.defaultView?.navigator?.clipboard;
    if (clipboard?.writeText) {
      await clipboard.writeText(text);
      return true;
    }
    return document.execCommand?.('copy') === true;
  }

  async function readClipboard() {
    const clipboard = document.defaultView?.navigator?.clipboard;
    if (clipboard?.readText) {
      return clipboard.readText();
    }
    return '';
  }

  async function runSelectionMenuAction(action) {
    const payload = selectionMenuPayload;
    if (!payload) return;
    const { target, value, key } = payload;
    hideSelectionMenu();
    if (target) target.focus();
    try {
      if (action === 'add-chunk') {
        pendingAddPrefill = { value, key };
        openPanel(getAnchor(target), false);
      } else if (action === 'undo' || action === 'redo') {
        document.execCommand?.(action);
        notifyTextChanged(target);
      } else if (action === 'cut') {
        await writeClipboard(getSelectionText(target));
        replaceTargetSelection(target, '');
      } else if (action === 'copy') {
        await writeClipboard(getSelectionText(target));
      } else if (action === 'paste' || action === 'paste-plain') {
        const text = await readClipboard();
        if (text) replaceTargetSelection(target, text);
      } else if (action === 'select-all') {
        target?.select?.();
      }
    } catch (error) {
      console.warn('Chunk context action failed', error);
      showToast('Clipboard action failed', 'error');
    }
  }

  function placeSelectionMenu(event) {
    const menu = ensureSelectionMenu();
    const vv = window.visualViewport;
    const viewportLeft = vv ? vv.offsetLeft : 0;
    const viewportTop = vv ? vv.offsetTop : 0;
    const viewportWidth = vv ? vv.width : window.innerWidth;
    const viewportHeight = vv ? vv.height : window.innerHeight;
    const margin = 8;
    menu.classList.add('open');
    const rect = menu.getBoundingClientRect();
    const left = Math.min(
      Math.max(viewportLeft + margin, event.clientX),
      viewportLeft + viewportWidth - rect.width - margin,
    );
    const top = Math.min(
      Math.max(viewportTop + margin, event.clientY),
      viewportTop + viewportHeight - rect.height - margin,
    );
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function showSelectionMenu(target, event) {
    const selection = getSelectionText(target);
    if (!selection || !event) return false;
    selectionMenuPayload = {
      target,
      value: selection,
      key: suggestKeyFromValue(selection),
    };
    placeSelectionMenu(event);
    return true;
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
        html += `<div class="chunk-group" data-group-name="${escHtml(group.name)}">`;
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
    applyPendingAddPrefill();
    relayout();
  }

  function toggleGroup(groupEl) {
    const wasOpen = groupEl.classList.contains('open');
    groupEl.parentElement.querySelectorAll('.chunk-group.open').forEach(group => {
      group.classList.remove('open');
    });
    if (!wasOpen) {
      groupEl.classList.add('open');
      syncAddGroup(groupEl.dataset.groupName || '');
    }
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

  function getSelectionText(target = null) {
    return selectedTextFrom(target || getAcTarget() || promptEdit);
  }

  function useSelection() {
    const keyInput = panel ? panel.querySelector('#chunkAddKey') : null;
    const valueInput = panel ? panel.querySelector('#chunkAddValue') : null;
    if (!valueInput) return;
    const selection = getSelectionText();
    if (!selection) {
      showToast('No prompt selection', 'error');
      return;
    }
    valueInput.value = selection;
    if (keyInput && !keyInput.value.trim()) {
      keyInput.value = suggestKeyFromValue(selection);
    }
  }

  function saveNew(event) {
    if (event) event.preventDefault();
    const groupInput = panel ? panel.querySelector('#chunkAddGroup') : null;
    const keyInput = panel ? panel.querySelector('#chunkAddKey') : null;
    const valueInput = panel ? panel.querySelector('#chunkAddValue') : null;
    const fallbackGroup = latestGroups[0]?.name || 'default';
    const group = (groupInput?.value || fallbackGroup).trim();
    const value = (valueInput?.value || '').trim();
    let key = (keyInput?.value || '').trim();
    if (!value) {
      showToast('Chunk value is required', 'error');
      return false;
    }
    if (!key) key = suggestKeyFromValue(value);
    if (!group || !key) {
      showToast('Group is required', 'error');
      return false;
    }
    if (keyInput) keyInput.value = key;
    lastAddGroup = group;
    setModuleParam('instant_wildcard', 'upsert', JSON.stringify({
      file: group.toLowerCase().endsWith('.json') ? group : `${group}.json`,
      key,
      value,
    }));
    document.defaultView?.setTimeout(requestState, 120);
    document.defaultView?.setTimeout(requestState, 320);
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
    showSelectionMenu,
    hideSelectionMenu,
    relayout,
    isOpen,
    setTriggerInfo,
    clearTriggerInfo,
    panelElement,
  };
}
