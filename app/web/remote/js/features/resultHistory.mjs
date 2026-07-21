const HISTORY_RAIL_COLLAPSED_KEY = 'naia_history_rail_collapsed';
const HISTORY_DELETE_MODE_KEY = 'naia_result_delete_mode';
const HISTORY_SELECTION_MAX_ITEMS = 200;
const PROMPT_CACHE_MAX = 80;
const HISTORY_ITEM_PREFIX = '__history_item__/';

function encodeViewerPath(relPath) {
  return String(relPath || '').split('/').map(part => encodeURIComponent(part)).join('/');
}

function historyIdFromPath(relPath) {
  const normalized = String(relPath || '').replace(/\\/g, '/');
  if (!normalized.startsWith(HISTORY_ITEM_PREFIX)) return '';
  return normalized.slice(HISTORY_ITEM_PREFIX.length).split('/')[0] || '';
}

function historyAssetUrl(relPath, kind) {
  const historyId = historyIdFromPath(relPath);
  if (historyId) return `/api/history/${kind}/${encodeURIComponent(historyId)}`;
  return `/api/viewer/${kind}/${encodeViewerPath(relPath)}`;
}

function historyMetaUrl(relPath) {
  const historyId = historyIdFromPath(relPath);
  if (historyId) return `/api/history/meta/${encodeURIComponent(historyId)}`;
  const params = new URLSearchParams({path: String(relPath || '')});
  return '/api/viewer/meta?' + params.toString();
}

function historyListUrl(page, perPage) {
  const params = new URLSearchParams({
    page: String(page),
    per_page: String(perPage),
  });
  return `/api/history/list?${params.toString()}`;
}

function legacyViewerListUrl(page, perPage) {
  const params = new URLSearchParams({
    scope: 'memory',
    page: String(page),
    per_page: String(perPage),
  });
  return `/api/viewer/list?${params.toString()}`;
}

export function createResultHistoryController({
  document,
  window,
  localStorage,
  fetch,
  preview,
  emptyMsg,
  resultInfoContent,
  escHtml,
  showToast,
  confirmDialog = null,
  renderPromptInfoHtml = null,
  onPromptInfoTagLookup = null,
  onDiskImageSelected = () => {},
}) {
  const getEl = id => document.getElementById(id);
  const viewerTab = getEl('viewerTab');
  const viewerPanel = getEl('viewerPanel');
  const viewerRailToggle = getEl('viewerRailToggle');
  const viewerGrid = getEl('viewerGrid');
  const viewerCountEl = getEl('viewerCount');
  const viewerLoading = getEl('viewerLoading');

  let initialized = false;
  let viewerPage = 0;
  let viewerTotal = 0;
  let viewerLoadingMore = false;
  let viewerPopupOpen = false;
  let vpPage = 0;
  let vpLoading = false;
  let vpCurrentPath = '';
  let viewerNavPaths = [];
  let viewerNavIdx = -1;
  let currentViewerPath = '';
  let lightboxPromptVisible = false;
  let viewerPendingNewCount = 0;
  let latestImagePath = '';
  let promptFloatCache = {};
  let promptFloatCacheKeys = [];
  const selectedPaths = new Set();
  let selectionAnchorPath = '';
  let selectionBusy = false;
  let dragSelection = null;
  let suppressThumbClickUntil = 0;

  function isEditableTarget(target) {
    const editable = target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"])');
    return Boolean(editable);
  }

  function gridPaths(grid) {
    if (!grid) return [];
    return [...grid.querySelectorAll('.viewer-thumb[data-path]')]
      .map(thumb => thumb.dataset.path || '')
      .filter(Boolean);
  }

  function activeSelectionGrid() {
    return viewerPopupOpen ? getEl('vpGrid') : viewerGrid;
  }

  function orderedSelectedPaths() {
    const result = [];
    const seen = new Set();
    for (const grid of [activeSelectionGrid(), viewerGrid, getEl('vpGrid')]) {
      for (const path of gridPaths(grid)) {
        if (selectedPaths.has(path) && !seen.has(path)) {
          result.push(path);
          seen.add(path);
        }
      }
    }
    for (const path of selectedPaths) {
      if (!seen.has(path)) result.push(path);
    }
    return result;
  }

  function selectionBarMarkup(scope) {
    return `
      <div class="history-selection-count" data-history-selection-count>0개 선택됨</div>
      <div class="history-selection-actions">
        <button type="button" class="history-selection-btn save" data-history-selection-action="save">WebP 저장 (0)</button>
        <button type="button" class="history-selection-btn delete" data-history-selection-action="delete">선택 삭제 (0)</button>
      </div>
      <button type="button" class="history-selection-clear" data-history-selection-action="clear" aria-label="선택 해제" title="선택 해제">×</button>
      <span class="history-selection-scope">${scope}</span>`;
  }

  function bindSelectionBar(bar) {
    if (!bar || bar.dataset.bound === '1') return;
    bar.dataset.bound = '1';
    bar.addEventListener('click', event => {
      const button = event.target.closest('[data-history-selection-action]');
      if (!button) return;
      const action = button.dataset.historySelectionAction;
      if (action === 'save') saveSelected();
      else if (action === 'delete') deleteSelected();
      else if (action === 'clear') clearSelection();
    });
  }

  function ensureRailSelectionBar() {
    if (!viewerPanel) return null;
    let bar = getEl('viewerSelectionBar');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'viewerSelectionBar';
      bar.className = 'history-selection-bar viewer-panel-selection hidden';
      bar.innerHTML = selectionBarMarkup('');
      const header = viewerPanel.querySelector('.viewer-panel-header');
      if (header) header.insertAdjacentElement('afterend', bar);
      else viewerPanel.prepend(bar);
    }
    bindSelectionBar(bar);
    return bar;
  }

  function updateSelectionUi() {
    const count = selectedPaths.size;
    document.querySelectorAll('.viewer-thumb[data-path]').forEach(thumb => {
      const selected = selectedPaths.has(thumb.dataset.path || '');
      thumb.classList.toggle('selected', selected);
      thumb.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
    document.querySelectorAll('.history-selection-bar').forEach(bar => {
      // 드래그 도중 막대가 나타나거나 사라지면 그리드가 움직여 선택 좌표가 달라진다.
      if (!dragSelection?.active) bar.classList.toggle('hidden', count === 0);
      const countEl = bar.querySelector('[data-history-selection-count]');
      if (countEl) countEl.textContent = `${count}개 선택됨`;
      const save = bar.querySelector('[data-history-selection-action="save"]');
      const remove = bar.querySelector('[data-history-selection-action="delete"]');
      if (save) {
        save.textContent = `WebP 저장 (${count})`;
        save.disabled = selectionBusy || count === 0;
      }
      if (remove) {
        remove.textContent = `선택 삭제 (${count})`;
        remove.disabled = selectionBusy || count === 0;
      }
    });
    if (viewerPanel) viewerPanel.classList.toggle('has-history-selection', count > 0);
  }

  function clearSelection() {
    selectedPaths.clear();
    selectionAnchorPath = '';
    updateSelectionUi();
  }

  function selectRange(relPath, grid) {
    const paths = gridPaths(grid);
    const currentIndex = paths.indexOf(relPath);
    const anchorIndex = paths.indexOf(selectionAnchorPath);
    if (currentIndex < 0 || anchorIndex < 0) {
      selectedPaths.add(relPath);
      selectionAnchorPath = relPath;
    } else {
      const start = Math.min(currentIndex, anchorIndex);
      const end = Math.max(currentIndex, anchorIndex);
      paths.slice(start, end + 1).forEach(path => selectedPaths.add(path));
    }
    updateSelectionUi();
  }

  function handleThumbClick(event, relPath, grid, openImage, {selectOnOpen = false} = {}) {
    const additive = Boolean(event.metaKey || event.ctrlKey);
    if (additive || event.shiftKey) {
      event.preventDefault();
      event.stopPropagation();
      if (event.shiftKey) {
        selectRange(relPath, grid);
      } else {
        if (selectedPaths.has(relPath)) selectedPaths.delete(relPath);
        else selectedPaths.add(relPath);
        selectionAnchorPath = relPath;
        updateSelectionUi();
      }
      return;
    }
    const hadSelection = selectedPaths.size > 0;
    if (hadSelection) selectedPaths.clear();
    if (selectOnOpen) selectedPaths.add(relPath);
    selectionAnchorPath = relPath;
    if (hadSelection || selectOnOpen) updateSelectionUi();
    openImage();
  }

  function configureThumb(img, relPath, grid, openImage, options = {}) {
    img.draggable = false;
    img.setAttribute('role', 'option');
    img.setAttribute('aria-selected', selectedPaths.has(relPath) ? 'true' : 'false');
    img.classList.toggle('selected', selectedPaths.has(relPath));
    img.addEventListener('dragstart', event => event.preventDefault());
    img.onclick = event => {
      if (Date.now() < suppressThumbClickUntil) {
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      grid.focus({preventScroll: true});
      handleThumbClick(event, relPath, grid, openImage, options);
    };
  }

  function endDragSelection(event) {
    if (!dragSelection || (event && event.pointerId !== dragSelection.pointerId)) return;
    const completedSelection = dragSelection.active;
    const clearFromBlankClick = !completedSelection && !dragSelection.startedOnThumb;
    dragSelection.grid.classList.remove('is-selecting');
    dragSelection.marquee?.remove();
    if (completedSelection && dragSelection.lastPath) selectionAnchorPath = dragSelection.lastPath;
    if (completedSelection) suppressThumbClickUntil = Date.now() + 300;
    dragSelection = null;
    if (clearFromBlankClick) clearSelection();
    else if (completedSelection) updateSelectionUi();
  }

  function marqueeBounds(startX, startY, currentX, currentY) {
    const left = Math.min(startX, currentX);
    const top = Math.min(startY, currentY);
    const right = Math.max(startX, currentX);
    const bottom = Math.max(startY, currentY);
    return {left, top, right, bottom, width: right - left, height: bottom - top};
  }

  function rectsIntersect(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }

  function clampMarqueeToGrid(bounds, grid) {
    const gridRect = grid.getBoundingClientRect();
    const left = Math.max(bounds.left, gridRect.left);
    const top = Math.max(bounds.top, gridRect.top);
    const right = Math.min(bounds.right, gridRect.right);
    const bottom = Math.min(bounds.bottom, gridRect.bottom);
    return {
      left,
      top,
      right: Math.max(left, right),
      bottom: Math.max(top, bottom),
      width: Math.max(0, right - left),
      height: Math.max(0, bottom - top),
    };
  }

  function bindDragSelection(grid) {
    if (!grid || grid.dataset.historyDragBound === '1') return;
    grid.dataset.historyDragBound = '1';
    if (!grid.hasAttribute('tabindex')) grid.tabIndex = 0;
    grid.addEventListener('pointerdown', event => {
      if (event.button !== 0) return;
      const thumb = event.target?.closest?.('.viewer-thumb[data-path]');
      if (event.target !== grid && (!thumb || !grid.contains(thumb))) return;
      grid.focus({preventScroll: true});
      const additive = Boolean(event.metaKey || event.ctrlKey);
      dragSelection = {
        grid,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        basePaths: additive ? new Set(selectedPaths) : new Set(),
        additive,
        startedOnThumb: Boolean(thumb),
        active: false,
        marquee: null,
        lastPath: '',
      };
      // 썸네일의 일반 클릭은 원래 상세 미리보기 이벤트까지 전달되어야 한다.
      // 빈 공간은 브라우저 기본 선택만 막고, 포인터 캡처는 실제 드래그가 시작될 때 건다.
      if (!thumb) event.preventDefault();
    });
    grid.addEventListener('pointermove', event => {
      if (!dragSelection || dragSelection.grid !== grid || event.pointerId !== dragSelection.pointerId) return;
      const deltaX = event.clientX - dragSelection.startX;
      const deltaY = event.clientY - dragSelection.startY;
      if (!dragSelection.active && Math.hypot(deltaX, deltaY) < 6) {
        event.preventDefault();
        return;
      }
      if (!dragSelection.active) {
        dragSelection.active = true;
        try { grid.setPointerCapture(event.pointerId); } catch (_) {}
        dragSelection.marquee = document.createElement('div');
        dragSelection.marquee.className = 'history-selection-marquee';
        document.body.appendChild(dragSelection.marquee);
        grid.classList.add('is-selecting');
        if (!dragSelection.additive) selectedPaths.clear();
      }
      const bounds = clampMarqueeToGrid(marqueeBounds(
        dragSelection.startX,
        dragSelection.startY,
        event.clientX,
        event.clientY,
      ), grid);
      Object.assign(dragSelection.marquee.style, {
        left: `${bounds.left}px`,
        top: `${bounds.top}px`,
        width: `${bounds.width}px`,
        height: `${bounds.height}px`,
      });
      selectedPaths.clear();
      dragSelection.basePaths.forEach(path => selectedPaths.add(path));
      let lastPath = '';
      grid.querySelectorAll('.viewer-thumb[data-path]').forEach(thumb => {
        if (rectsIntersect(bounds, thumb.getBoundingClientRect())) {
          const path = thumb.dataset.path || '';
          if (path) {
            selectedPaths.add(path);
            lastPath = path;
          }
        }
      });
      dragSelection.lastPath = lastPath;
      updateSelectionUi();
      event.preventDefault();
    });
    grid.addEventListener('pointerup', endDragSelection);
    grid.addEventListener('pointercancel', endDragSelection);
  }

  function selectAllLoaded() {
    const paths = gridPaths(activeSelectionGrid());
    paths.forEach(path => selectedPaths.add(path));
    if (paths.length) selectionAnchorPath = paths[paths.length - 1];
    updateSelectionUi();
  }

  function setSelectionBusy(busy) {
    selectionBusy = Boolean(busy);
    updateSelectionUi();
  }

  async function saveSelected() {
    const paths = orderedSelectedPaths();
    if (!paths.length || selectionBusy) return;
    if (paths.length > HISTORY_SELECTION_MAX_ITEMS) {
      showToast(`한 번에 최대 ${HISTORY_SELECTION_MAX_ITEMS}개까지 저장할 수 있습니다.`, 'error');
      return;
    }
    setSelectionBusy(true);
    try {
      const response = await fetch('/api/history/selected/save', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({paths}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        throw new Error(data.error || `선택 저장 실패 (${response.status})`);
      }
      const saved = Number(data.saved || 0);
      const failed = Array.isArray(data.failed) ? data.failed.length : 0;
      const folder = String(data.current_save_directory || '현재 결과 폴더');
      showToast(`WebP 저장 완료: ${saved}개${failed ? `, 실패 ${failed}개` : ''} · ${folder}`, failed ? 'warning' : 'success');
    } catch (error) {
      showToast(error.message || '선택 WebP 저장 실패', 'error');
    } finally {
      setSelectionBusy(false);
    }
  }

  async function deleteSelected() {
    const paths = orderedSelectedPaths();
    if (!paths.length || selectionBusy) return;
    let deleteMode = 'history';
    try { deleteMode = localStorage.getItem(HISTORY_DELETE_MODE_KEY) === 'disk' ? 'disk' : 'history'; } catch (_) {}
    const modeText = deleteMode === 'disk'
      ? '연결된 저장 파일은 영구 삭제하지 않고 휴지통으로 이동합니다.'
      : '히스토리에서만 제거하며 저장 파일은 유지합니다.';
    const message = `${paths.length}개 선택 항목을 삭제할까요?\n${modeText}`;
    const confirmed = typeof confirmDialog === 'function'
      ? await confirmDialog(message, {title: '선택 항목 삭제', okText: `삭제 (${paths.length})`, cancelText: '취소'})
      : window.confirm(message);
    if (!confirmed) return;

    setSelectionBusy(true);
    let succeeded = 0;
    let failed = 0;
    try {
      const response = await fetch('/api/history/selected/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({paths, keep_file: deleteMode !== 'disk'}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      const removed = Array.isArray(data.removed) ? data.removed : [];
      removed.forEach(item => {
        selectedPaths.delete(item.rel_path || '');
        onRemoved(item);
      });
      succeeded = Number(data.deleted || removed.length || 0);
      failed = Array.isArray(data.failed) ? data.failed.length : 0;
    } catch (error) {
      console.error('Selected history delete failed:', error);
      failed = paths.length;
    }
    if (!selectedPaths.size) selectionAnchorPath = '';
    setSelectionBusy(false);
    const level = failed ? (succeeded ? 'warning' : 'error') : 'success';
    showToast(`선택 삭제 완료: 성공 ${succeeded}개, 실패 ${failed}개`, level);
  }

  function setRailCollapsed(collapsed, persist = true) {
    if (!viewerPanel) return;
    viewerPanel.classList.toggle('collapsed', collapsed);
    if (viewerRailToggle) {
      viewerRailToggle.textContent = collapsed ? '‹' : '›';
      viewerRailToggle.title = collapsed ? 'Expand history' : 'Collapse history';
      viewerRailToggle.setAttribute('aria-label', collapsed ? 'Expand history' : 'Collapse history');
      viewerRailToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }
    if (persist) {
      try { localStorage.setItem(HISTORY_RAIL_COLLAPSED_KEY, collapsed ? '1' : '0'); } catch (_) {}
    }
  }

  function toggleRail() {
    if (!viewerPanel) return;
    setRailCollapsed(!viewerPanel.classList.contains('collapsed'));
  }

  function initRail() {
    if (!viewerPanel) return;
    let collapsed = false;
    try { collapsed = localStorage.getItem(HISTORY_RAIL_COLLAPSED_KEY) === '1'; } catch (_) {}
    setRailCollapsed(collapsed, false);
  }

  function hasThumb(relPath) {
    if (!viewerGrid || !relPath) return false;
    return !!viewerGrid.querySelector(`.viewer-thumb[data-path="${CSS.escape(relPath)}"]`);
  }

  function setViewerTotal(total) {
    const parsed = Number(total);
    if (Number.isFinite(parsed)) {
      viewerTotal = Math.max(0, Math.trunc(parsed));
    }
    if (viewerCountEl) viewerCountEl.textContent = viewerTotal;
    if (viewerTab) viewerTab.classList.toggle('visible', viewerTotal > 0);
  }

  function removeThumb(grid, relPath) {
    if (!grid || !relPath) return false;
    const thumb = grid.querySelector(`.viewer-thumb[data-path="${CSS.escape(relPath)}"]`);
    if (!thumb) return false;
    thumb.remove();
    return true;
  }

  function firstGridPath() {
    const first = viewerGrid ? viewerGrid.querySelector('.viewer-thumb[data-path]') : null;
    return first?.dataset?.path || '';
  }

  async function fetchHistoryList(page, perPage) {
    const resp = await fetch(historyListUrl(page, perPage));
    if (resp.status !== 404) return resp;
    return fetch(legacyViewerListUrl(page, perPage));
  }

  function appendThumb(relPath) {
    if (!viewerGrid) return;
    const img = document.createElement('img');
    img.className = 'viewer-thumb';
    img.loading = 'lazy';
    img.dataset.path = relPath;
    img.src = historyAssetUrl(relPath, 'thumb');
    configureThumb(img, relPath, viewerGrid, () => thumbClick(relPath));
    viewerGrid.appendChild(img);
  }

  function prependThumb(relPath) {
    if (!viewerGrid) return;
    const img = document.createElement('img');
    img.className = 'viewer-thumb';
    img.loading = 'lazy';
    img.dataset.path = relPath;
    img.src = historyAssetUrl(relPath, 'thumb');
    configureThumb(img, relPath, viewerGrid, () => thumbClick(relPath));
    viewerGrid.prepend(img);
  }

  async function loadPage(page) {
    if (viewerLoadingMore || !viewerGrid) return;
    viewerLoadingMore = true;
    if (viewerLoading) viewerLoading.style.display = '';
    try {
      const resp = await fetchHistoryList(page, 30);
      const data = await resp.json();
      viewerTotal = data.total;
      if (viewerCountEl) viewerCountEl.textContent = viewerTotal;
      if (viewerTab) viewerTab.classList.toggle('visible', viewerTotal > 0);
      for (const entry of data.images) {
        if (hasThumb(entry.rel_path)) continue;
        appendThumb(entry.rel_path);
      }
      viewerPage = page + 1;
    } catch (error) {
      console.error('Viewer load failed:', error);
    }
    viewerLoadingMore = false;
    if (viewerLoading) viewerLoading.style.display = 'none';
  }

  function initViewer() {
    if (!viewerGrid) return;
    clearSelection();
    viewerPage = 0;
    viewerTotal = 0;
    viewerGrid.innerHTML = '';
    loadPage(0);
  }

  function prepareInitialHistory() {
    fetchHistoryList(0, 1).then(resp => resp.json()).then(data => {
      viewerTotal = data.total;
      if (viewerCountEl) viewerCountEl.textContent = data.total;
      if (data.total > 0 && viewerGrid && viewerGrid.children.length === 0) initViewer();
    }).catch(() => {});
  }

  function rememberPromptMetaHtml(relPath, html) {
    promptFloatCache[relPath] = html;
    promptFloatCacheKeys = promptFloatCacheKeys.filter(key => key !== relPath);
    promptFloatCacheKeys.push(relPath);
    while (promptFloatCacheKeys.length > PROMPT_CACHE_MAX) {
      delete promptFloatCache[promptFloatCacheKeys.shift()];
    }
  }

  function renderPromptBlock(label, text) {
    if (typeof renderPromptInfoHtml === 'function') {
      return renderPromptInfoHtml(label, text);
    }
    return `<div class="pf-island"><span class="pf-label">${escHtml(label)}</span>${escHtml(text)}</div>`;
  }

  function bindPromptInfoTags(root) {
    if (!root || typeof onPromptInfoTagLookup !== 'function') return;
    root.querySelectorAll('.generation-info-tag[data-tag]').forEach(button => {
      button.addEventListener('click', event => {
        event.preventDefault();
        event.stopPropagation();
        onPromptInfoTagLookup(button.dataset.tag || button.textContent || '', {
          anchor: button,
          rawTag: button.dataset.copyTag || button.textContent || button.dataset.tag || '',
        });
      });
    });
  }

  async function getPromptMetaHtml(relPath) {
    if (promptFloatCache[relPath]) return promptFloatCache[relPath];
    const resp = await fetch(historyMetaUrl(relPath));
    const meta = await resp.json();
    let html = '';
    if (meta.prompt) {
      html += renderPromptBlock('Prompt', meta.prompt);
    }
    if (meta.characters && meta.characters.length) {
      for (let i = 0; i < meta.characters.length; i++) {
        html += renderPromptBlock(`Character ${i + 1}`, meta.characters[i]);
      }
    }
    if (!html) html = '<div class="pf-island"><span class="pf-label">No metadata</span></div>';
    rememberPromptMetaHtml(relPath, html);
    return html;
  }

  async function loadResultInfo(relPath) {
    if (!resultInfoContent || !relPath) return;
    resultInfoContent.innerHTML = '<span class="result-info-empty">loading metadata...</span>';
    try {
      resultInfoContent.innerHTML = await getPromptMetaHtml(relPath);
      bindPromptInfoTags(resultInfoContent);
    } catch (_) {
      resultInfoContent.innerHTML = '<span class="result-info-empty">metadata unavailable</span>';
    }
  }

  async function loadPromptForFloat(relPath, floatId, contentId) {
    const pf = getEl(floatId);
    const content = getEl(contentId);
    if (!pf || !content) return;

    if (promptFloatCache[relPath]) {
      content.innerHTML = promptFloatCache[relPath];
      bindPromptInfoTags(content);
      window.requestAnimationFrame(() => {
        content.classList.toggle('scrollable', content.scrollHeight > content.clientHeight);
      });
      pf.classList.add('visible');
      return;
    }

    content.innerHTML = '<span class="pf-label">Loading...</span>';
    pf.classList.add('visible');

    try {
      const html = await getPromptMetaHtml(relPath);
      content.innerHTML = html;
      bindPromptInfoTags(content);
      window.requestAnimationFrame(() => {
        content.classList.toggle('scrollable', content.scrollHeight > content.clientHeight);
      });
    } catch (_) {
      content.innerHTML = '<span class="pf-label">Failed to load</span>';
    }
  }

  function lightboxBaseHtml() {
    const promptBtnText = lightboxPromptVisible ? 'Hide Prompt' : 'Show Prompt';
    return `
    <div class="viewer-lightbox-inner" onclick="event.stopPropagation()">
      <img id="viewerLightboxImg" alt="">
      <div class="prompt-float viewer-lightbox-prompt${lightboxPromptVisible ? ' visible' : ''}" id="viewerLightboxPrompt">
        <div class="prompt-float-content" id="viewerLightboxPromptContent"></div>
      </div>
      <div class="viewer-lightbox-controls">
        <button class="viewer-lightbox-btn${lightboxPromptVisible ? ' accent' : ''}" id="viewerLightboxPromptBtn" onclick="toggleLightboxPrompt()">${promptBtnText}</button>
        <button class="viewer-lightbox-btn danger" onclick="closeViewerLightbox()">Close</button>
      </div>
    </div>`;
  }

  function resetLightbox() {
    const lb = getEl('viewerLightbox');
    if (!lb) return;
    lb.innerHTML = lightboxBaseHtml();
  }

  function syncLightboxPromptUi() {
    const prompt = getEl('viewerLightboxPrompt');
    const btn = getEl('viewerLightboxPromptBtn');
    if (prompt) prompt.classList.toggle('visible', lightboxPromptVisible);
    if (btn) {
      btn.textContent = lightboxPromptVisible ? 'Hide Prompt' : 'Show Prompt';
      btn.classList.toggle('accent', lightboxPromptVisible);
    }
  }

  function closeLightbox() {
    const lb = getEl('viewerLightbox');
    if (lb) lb.classList.remove('open');
    lightboxPromptVisible = false;
    resetLightbox();
    viewerPopupOpen = false;
  }

  function onLightboxClick() {
    if (viewerPopupOpen) closePopup();
    else closeLightbox();
  }

  function ensureLatestBadge() {
    let el = getEl('viewerLatestBadge');
    if (el) return el;
    el = document.createElement('button');
    el.id = 'viewerLatestBadge';
    el.className = 'viewer-latest-badge';
    el.type = 'button';
    el.onclick = jumpToLatest;
    document.body.appendChild(el);
    return el;
  }

  function showLatestBadge() {
    const el = ensureLatestBadge();
    const count = viewerPendingNewCount;
    el.textContent = count > 1 ? `↓ 최신으로 (+${count})` : '↓ 최신으로';
    el.classList.add('visible');
  }

  function hideLatestBadge() {
    viewerPendingNewCount = 0;
    const el = getEl('viewerLatestBadge');
    if (el) el.classList.remove('visible');
  }

  function jumpToLatest() {
    if (viewerNavPaths.length === 0) {
      hideLatestBadge();
      return;
    }
    viewerNavIdx = 0;
    showImage(viewerNavPaths[0]);
    hideLatestBadge();
  }

  function showImage(relPath) {
    currentViewerPath = relPath;
    onDiskImageSelected(relPath);
    preview.src = historyAssetUrl(relPath, 'image');
    preview.dataset.source = 'saved';
    preview.dataset.path = relPath;
    preview.classList.add('show');
    emptyMsg.style.display = 'none';
    loadResultInfo(relPath);
    if (!viewerGrid) return;
    const thumbs = viewerGrid.querySelectorAll('.viewer-thumb');
    thumbs.forEach((thumb, index) => thumb.classList.toggle('active', index === viewerNavIdx));
  }

  function thumbClick(relPath) {
    viewerNavPaths = [];
    const thumbs = viewerGrid ? viewerGrid.querySelectorAll('.viewer-thumb') : [];
    thumbs.forEach(thumb => {
      const path = thumb.dataset.path;
      if (path) {
        viewerNavPaths.push(path);
      } else {
        const src = thumb.getAttribute('src') || '';
        const match = src.match(/\/api\/viewer\/thumb\/(.+)$/);
        if (match) viewerNavPaths.push(decodeURI(match[1]));
      }
    });
    viewerNavIdx = viewerNavPaths.indexOf(relPath);
    if (viewerNavIdx < 0) {
      viewerNavPaths = [relPath];
      viewerNavIdx = 0;
    }
    hideLatestBadge();
    showImage(relPath);
  }

  function navViewer(direction) {
    const next = viewerNavIdx + direction;
    if (next >= 0 && next < viewerNavPaths.length) {
      viewerNavIdx = next;
      showImage(viewerNavPaths[viewerNavIdx]);
      if (viewerNavIdx === 0) hideLatestBadge();
    }
  }

  function hideNav() {
    viewerNavIdx = -1;
    currentViewerPath = '';
    if (viewerGrid) {
      viewerGrid.querySelectorAll('.viewer-thumb.active').forEach(thumb => thumb.classList.remove('active'));
    }
    hideLatestBadge();
  }

  function onNewImage(message) {
    if (!message.rel_path) return;
    latestImagePath = message.rel_path;
    const alreadyInGrid = hasThumb(message.rel_path);
    if (Number.isFinite(Number(message.total))) {
      setViewerTotal(message.total);
    } else if (!alreadyInGrid) {
      setViewerTotal(viewerTotal + 1);
    }

    const didPrepend = !alreadyInGrid && !!viewerGrid;
    if (didPrepend) prependThumb(message.rel_path);

    if (viewerNavIdx < 0 || !currentViewerPath || currentViewerPath === message.rel_path) {
      loadResultInfo(message.rel_path);
    }

    if (didPrepend && viewerNavIdx >= 0 && viewerNavPaths.length > 0
        && !viewerNavPaths.includes(message.rel_path)) {
      viewerNavPaths.unshift(message.rel_path);
      if (viewerNavIdx === 0) {
        showImage(message.rel_path);
      } else {
        viewerNavIdx += 1;
        viewerPendingNewCount += 1;
        showLatestBadge();
        const thumbs = viewerGrid.querySelectorAll('.viewer-thumb');
        thumbs.forEach((thumb, index) => thumb.classList.toggle('active', index === viewerNavIdx));
      }
    }

    if (viewerPopupOpen) {
      const vpGrid = getEl('vpGrid');
      if (vpGrid && !vpGrid.querySelector(`.viewer-thumb[data-path="${CSS.escape(message.rel_path)}"]`)) {
        const img = document.createElement('img');
        img.className = 'viewer-thumb';
        img.loading = 'lazy';
        img.dataset.path = message.rel_path;
        img.src = historyAssetUrl(message.rel_path, 'thumb');
        configureThumb(img, message.rel_path, vpGrid, () => selectPopupImage(message.rel_path, img), {selectOnOpen: true});
        vpGrid.prepend(img);
      }
      const count = getEl('vpCount');
      if (count) count.textContent = viewerTotal;
    }
  }

  function onRemoved(message) {
    const relPath = message?.rel_path || '';
    if (!relPath) return;
    selectedPaths.delete(relPath);
    if (selectionAnchorPath === relPath) selectionAnchorPath = '';
    // 삭제된 항목의 캐시 잔여까지 제거 (지워지면 남은 데이터가 없어야 한다).
    if (relPath in promptFloatCache) {
      delete promptFloatCache[relPath];
      promptFloatCacheKeys = promptFloatCacheKeys.filter(key => key !== relPath);
    }
    const removedMain = removeThumb(viewerGrid, relPath);
    removeThumb(getEl('vpGrid'), relPath);
    viewerNavPaths = viewerNavPaths.filter(path => path !== relPath);
    if (currentViewerPath === relPath) {
      currentViewerPath = '';
      viewerNavIdx = -1;
      if (preview?.dataset?.source === 'saved' && preview.dataset.path === relPath) {
        preview.removeAttribute('src');
        preview.classList.remove('show');
        preview.dataset.path = '';
        emptyMsg.style.display = '';
        if (resultInfoContent) resultInfoContent.innerHTML = '<span class="result-info-empty">No history item selected</span>';
      }
    } else {
      viewerNavIdx = viewerNavPaths.indexOf(currentViewerPath);
    }
    if (latestImagePath === relPath) latestImagePath = firstGridPath();
    if (Number.isFinite(Number(message.total))) {
      setViewerTotal(message.total);
    } else if (removedMain && viewerTotal > 0) {
      setViewerTotal(viewerTotal - 1);
    }
    const count = getEl('vpCount');
    if (count) count.textContent = viewerTotal;
    if (viewerTotal <= 0) hideLatestBadge();
    updateSelectionUi();
  }

  function onCleared(message = {}) {
    clearSelection();
    viewerPage = 0;
    viewerTotal = 0;
    viewerNavPaths = [];
    viewerNavIdx = -1;
    currentViewerPath = '';
    latestImagePath = '';
    viewerPendingNewCount = 0;
    promptFloatCache = {};
    promptFloatCacheKeys = [];
    if (viewerGrid) viewerGrid.innerHTML = '';
    const vpGrid = getEl('vpGrid');
    if (vpGrid) vpGrid.innerHTML = '';
    const vpPreview = getEl('vpPreview');
    if (vpPreview) vpPreview.removeAttribute('src');
    if (preview?.dataset?.source === 'saved') {
      preview.removeAttribute('src');
      preview.classList.remove('show');
      preview.dataset.path = '';
      emptyMsg.style.display = '';
    }
    if (resultInfoContent) resultInfoContent.innerHTML = '<span class="result-info-empty">No history item selected</span>';
    setViewerTotal(message.total ?? 0);
    hideLatestBadge();
  }

  function openPopup() {
    const lb = getEl('viewerLightbox');
    if (!lb) return;
    viewerPopupOpen = true;
    lb.innerHTML = `
    <div class="viewer-popup-inner" onclick="event.stopPropagation()">
      <div class="viewer-popup-header">
        <span class="viewer-panel-title">History <span id="vpCount">${viewerTotal}</span></span>
        <button class="history-close" onclick="closeViewerPopup()">&times;</button>
      </div>
      <div class="history-selection-bar viewer-popup-selection hidden" id="vpSelectionBar">
        ${selectionBarMarkup('')}
      </div>
      <div class="viewer-popup-body">
        <div class="viewer-popup-left" id="vpGrid"></div>
        <div class="viewer-popup-right" id="vpRight">
          <img class="vp-preview" id="vpPreview" alt="">
          <div class="prompt-float" id="vpPromptFloat">
            <div class="prompt-float-content" id="vpPromptContent"></div>
          </div>
          <div class="viewer-bottom-controls" style="display:flex">
            <button class="viewer-folder-btn" onclick="openResultFolder()">Open Folder</button>
          </div>
        </div>
      </div>
      <div class="viewer-panel-loading" id="vpLoading" style="display:none">Loading...</div>
    </div>`;
    lb.classList.add('open');
    vpPage = 0;
    loadPopupPage(0);
    const grid = getEl('vpGrid');
    if (grid) {
      grid.addEventListener('scroll', popupScroll);
      bindDragSelection(grid);
    }
    bindSelectionBar(getEl('vpSelectionBar'));
    updateSelectionUi();
  }

  async function loadPopupPage(page) {
    if (vpLoading) return;
    vpLoading = true;
    const loading = getEl('vpLoading');
    if (loading) loading.style.display = '';
    try {
      const resp = await fetchHistoryList(page, 30);
      const data = await resp.json();
      const grid = getEl('vpGrid');
      if (grid) {
        for (const entry of data.images) {
          if (grid.querySelector(`.viewer-thumb[data-path="${CSS.escape(entry.rel_path)}"]`)) continue;
          const img = document.createElement('img');
          img.className = 'viewer-thumb';
          img.loading = 'lazy';
          img.dataset.path = entry.rel_path;
          img.src = historyAssetUrl(entry.rel_path, 'thumb');
          configureThumb(img, entry.rel_path, grid, () => selectPopupImage(entry.rel_path, img), {selectOnOpen: true});
          grid.appendChild(img);
        }
      }
      vpPage = page + 1;
      viewerTotal = data.total;
      const count = getEl('vpCount');
      if (count) count.textContent = data.total;
    } catch (_) {}
    vpLoading = false;
    if (loading) loading.style.display = 'none';
  }

  function selectPopupImage(relPath, thumbEl) {
    vpCurrentPath = relPath;
    onDiskImageSelected(relPath);
    const previewEl = getEl('vpPreview');
    if (previewEl) {
      previewEl.src = historyAssetUrl(relPath, 'image');
      previewEl.dataset.source = 'saved';
      previewEl.dataset.path = relPath;
    }
    const grid = getEl('vpGrid');
    if (grid) grid.querySelectorAll('.viewer-thumb').forEach(thumb => thumb.classList.remove('active'));
    if (thumbEl) thumbEl.classList.add('active');
    const cb = getEl('vpPromptCb');
    if (cb && cb.checked) loadPromptForFloat(relPath, 'vpPromptFloat', 'vpPromptContent');
  }

  function togglePopupPrompt(checked) {
    const pf = getEl('vpPromptFloat');
    if (pf) pf.classList.toggle('visible', checked);
    if (checked && vpCurrentPath) loadPromptForFloat(vpCurrentPath, 'vpPromptFloat', 'vpPromptContent');
  }

  function popupScroll() {
    const grid = getEl('vpGrid');
    if (!grid || vpLoading) return;
    if (grid.scrollTop + grid.clientHeight >= grid.scrollHeight - 100) {
      if (grid.children.length < viewerTotal) loadPopupPage(vpPage);
    }
  }

  function closePopup() {
    viewerPopupOpen = false;
    const lb = getEl('viewerLightbox');
    if (lb) lb.classList.remove('open');
    lightboxPromptVisible = false;
    resetLightbox();
  }

  function navPopup(direction) {
    const grid = getEl('vpGrid');
    if (!grid) return;
    const thumbs = [...grid.querySelectorAll('.viewer-thumb')];
    if (thumbs.length === 0) return;
    const index = thumbs.findIndex(thumb => thumb.classList.contains('active'));
    const next = index + direction;
    if (next >= 0 && next < thumbs.length) {
      selectPopupImage(thumbs[next].dataset.path, thumbs[next]);
      thumbs[next].scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }
  }

  function toggleLightboxPrompt(forceVisible) {
    lightboxPromptVisible = typeof forceVisible === 'boolean' ? forceVisible : !lightboxPromptVisible;
    syncLightboxPromptUi();
    if (lightboxPromptVisible && currentViewerPath) {
      loadPromptForFloat(currentViewerPath, 'viewerLightboxPrompt', 'viewerLightboxPromptContent');
    }
  }

  function bindInfiniteScroll() {
    if (!viewerGrid) return;
    viewerGrid.addEventListener('scroll', () => {
      if (viewerLoadingMore) return;
      const {scrollTop, scrollHeight, clientHeight} = viewerGrid;
      if (scrollTop + clientHeight >= scrollHeight - 80) {
        const loadedCount = viewerGrid.children.length;
        if (loadedCount < viewerTotal) loadPage(viewerPage);
      }
    });
  }

  function bindKeyboard() {
    document.addEventListener('keydown', event => {
      if (isEditableTarget(event.target)) return;

      const commandKey = Boolean(event.metaKey || event.ctrlKey);
      const key = String(event.key || '').toLowerCase();
      const activeElement = document.activeElement;
      const historyFocused = Boolean(
        viewerPopupOpen
        || selectedPaths.size
        || viewerPanel?.contains(activeElement)
        || getEl('viewerLightbox')?.contains(activeElement)
      );
      if (commandKey && key === 'a' && historyFocused) {
        event.preventDefault();
        selectAllLoaded();
        return;
      }
      if (commandKey && key === 's' && selectedPaths.size) {
        event.preventDefault();
        saveSelected();
        return;
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedPaths.size) {
        event.preventDefault();
        deleteSelected();
        return;
      }
      if (event.key === 'Escape' && selectedPaths.size) {
        event.preventDefault();
        clearSelection();
        return;
      }

      if (viewerPopupOpen) {
        if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
          event.preventDefault();
          navPopup(-1);
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
          event.preventDefault();
          navPopup(1);
        } else if (event.key === 'Escape') {
          closePopup();
        }
        return;
      }

      if (viewerNavIdx < 0 || viewerNavPaths.length === 0) return;

      if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
        event.preventDefault();
        navViewer(-1);
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
        event.preventDefault();
        navViewer(1);
      } else if (event.key === 'Escape') {
        hideNav();
      }
    });
  }

  async function openFolder() {
    try {
      const resp = await fetch('/api/history/open-folder', {method: 'POST'});
      if (!resp.ok) {
        showToast('Open folder failed.', 'error');
        return;
      }
      showToast('Opened result folder.', 'success');
    } catch (_) {
      showToast('Open folder failed.', 'error');
    }
  }

  function init() {
    if (initialized) return;
    initialized = true;
    ensureRailSelectionBar();
    initRail();
    bindInfiniteScroll();
    bindDragSelection(viewerGrid);
    bindKeyboard();
    updateSelectionUi();
  }

  return {
    init,
    initViewer,
    prepareInitialHistory,
    toggleRail,
    setRailCollapsed,
    closeLightbox,
    onLightboxClick,
    onNewImage,
    onRemoved,
    onCleared,
    jumpToLatest,
    openPopup,
    closePopup,
    navPopup,
    toggleLightboxPrompt,
    togglePopupPrompt,
    thumbClick,
    navViewer,
    hideNav,
    openFolder,
    loadResultInfo,
    get latestImagePath() { return latestImagePath; },
  };
}
