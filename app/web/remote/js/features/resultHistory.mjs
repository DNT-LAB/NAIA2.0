import {createViewerBindings} from './viewerBindings.mjs?v=20260806-rev2b';

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
  openSaveDirectory = null,
  getSaveDirectory = () => '',
  requestSaveDirectory = () => {},
  openQuicksaveSettings = null,
  // 아직 저장 안 된 장수. 모르면 -1 — 모를 때는 묻는 쪽으로 간다.
  getUnsavedCount = () => -1,
  // 히스토리 통째로 비우기. Auto Save 판이 갖고 있던 흐름을 그대로 부른다 —
  // 미저장 장수를 세어 경고하는 확인 창이 거기 붙어 있다.
  clearAllHistory = null,
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

  // ── 옛 NAIA Viewer 에서 가져온 뷰어 상태 ────────────────────────────────
  // 데스크톱 뷰어는 QGraphicsView 가 줌/팬을 맡았다. 웹에는 그런 것이 없어
  // 원본 픽셀 크기를 기준으로 직접 계산한다 — `object-fit: contain` 은
  // 배율을 알려주지 않아서 "100%"를 정직하게 띄울 수가 없다.
  const VP_ZOOM_MIN = 0.05;
  const VP_ZOOM_MAX = 16;
  const VP_ZOOM_STEP = 1.25;          // 데스크톱 뷰어와 같은 비율
  let vpZoom = 1;
  let vpFitZoom = 1;                  // '맞춤' 배율 — 원본 토글의 기준점
  let vpFitMode = true;
  let vpTx = 0;
  let vpTy = 0;
  let vpNatW = 0;
  let vpNatH = 0;
  let vpPan = null;
  let vpListHidden = false;
  // 끝에서 한 번 막아 두는 자리(옛 뷰어의 `_edge_pending`). '' | 'first' | 'last'.
  let vpEdgePending = '';
  // 팝업을 열 때의 선택. 닫을 때 여기까지만 남긴다 — 레일에서 미리 골라 둔 것을
  // 팝업에 들렀다는 이유로 잃으면 안 된다.
  let vpSelectionOnOpen = null;

  // 숏컷 바인딩(앱 전용). 여기서 만들지만 화면에 붙는 것은 팝업이 열릴 때다.
  const viewerBindings = createViewerBindings({
    getEl,
    showToast,
    onItemRemoved: payload => onRemoved(payload),
    openSaveDirectory,
    getSaveDirectory,
    requestSaveDirectory,
    openQuicksaveSettings,
  });
  // '얼마나 봤는지'. 이번 세션에 실제로 펼쳐 본 것만 센다 — 목록에 썸네일이
  // 떴다는 것과 봤다는 것은 다르다. 새로고침하면 리셋되는 것이 맞다.
  const vpSeen = new Set();
  let vpLoading = false;
  let vpCurrentPath = '';
  let viewerNavPaths = [];
  let viewerNavIdx = -1;
  let currentViewerPath = '';
  // 마지막으로 본 초기화 세대. 이보다 낡은 새-이미지 알림은 이미 비워진 히스토리의
  // 것이므로 그리면 유령이 된다. 진행 중이던 목록 요청의 응답을 버리는 데도 쓴다.
  let clearedEpoch = 0;
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
  // 팝업 목록은 **클릭 한 번에 열림 + 선택**이 같이 일어난다(`selectOnOpen`).
  // 그렇게 딸려온 단일 선택만 여기에 적어 두고, 보는 그림이 바뀌면 놓아준다.
  // Ctrl/Shift/드래그로 **작정하고 고른 것은 건드리지 않는다**(사용자 지정).
  let incidentalSelectionPath = '';

  /** 사용자가 작정하고 고른 선택으로 승격 - 더는 자동으로 놓지 않는다. */
  function promoteSelectionToExplicit() {
    incidentalSelectionPath = '';
  }

  /** 보는 그림이 바뀌었다. 딸려온 단일 선택이면 놓아준다.
   *
   *  ⚠️ 이게 없으면 **보고 있는 그림과 홀드한 그림이 갈린다.** 선택 바의
   *  `저장 N`/`삭제 N` 은 `selectedPaths` 로 동작하므로(orderedSelectedPaths),
   *  A 를 클릭하고 휠로 D 까지 넘어간 뒤 삭제를 누르면 **A 가 지워진다**.
   */
  function releaseIncidentalSelection(nextPath) {
    if (!incidentalSelectionPath) return;
    if (nextPath && nextPath === incidentalSelectionPath) return;   // 그 그림 그대로다
    const onlyIncidental = selectedPaths.size === 1
      && selectedPaths.has(incidentalSelectionPath);
    incidentalSelectionPath = '';
    // 여러 장이 고여 있으면 사용자가 따로 고른 것이다 - 표시만 지우고 둔다.
    if (onlyIncidental) clearSelection();
  }

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
      <div class="history-selection-count" data-history-selection-count>0개 선택</div>
      <div class="history-selection-actions">
        <button type="button" class="history-selection-btn save" data-history-selection-action="save">저장 0</button>
        <button type="button" class="history-selection-btn saveas" data-history-selection-action="saveas"
                title="저장 위치를 직접 고릅니다">다른 경로 0</button>
        <button type="button" class="history-selection-btn delete" data-history-selection-action="delete">삭제 0</button>
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
      else if (action === 'saveas') saveSelectedAs();
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
      bar.className = 'history-selection-bar viewer-panel-selection';
      // 레일 안내에서 **드래그를 뺀다** — 드래그 선택은 팝업 격자에만 있다
      // (init 의 bindDragSelection 주석). 안내대로 끌어 봐도 아무 일이 없었다.
      bar.innerHTML = selectionBarMarkup('Cmd/Ctrl · Shift · Cmd/Ctrl+A · Esc');
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
      const countEl = bar.querySelector('[data-history-selection-count]');
      if (countEl) countEl.textContent = `${count}개 선택`;
      const save = bar.querySelector('[data-history-selection-action="save"]');
      const remove = bar.querySelector('[data-history-selection-action="delete"]');
      const clear = bar.querySelector('[data-history-selection-action="clear"]');
      if (save) {
        save.textContent = `저장 ${count}`;
        save.disabled = selectionBusy || count === 0;
      }
      if (remove) {
        remove.textContent = `삭제 ${count}`;
        remove.disabled = selectionBusy || count === 0;
      }
      const saveAs = bar.querySelector('[data-history-selection-action="saveas"]');
      if (saveAs) {
        saveAs.textContent = `다른 경로 ${count}`;
        // 저장 위치를 직접 고르는 길이 없는 환경(원격 브라우저·구형 WebView)에서는
        // 버튼을 아예 감춘다 - 눌러도 아무 일이 없으면 고장으로 읽힌다.
        saveAs.hidden = !hasNativeSavePicker();
        saveAs.disabled = selectionBusy || count === 0;
      }
      if (clear) clear.disabled = selectionBusy || count === 0;
      // 팝업 헤더의 선택 바는 고른 것이 없으면 통째로 접힌다(CSS). 레일은 힌트
      // 한 줄을 남겨야 해서 자기 규칙을 따로 쓴다 — 그래서 클래스는 바에 붙인다.
      bar.classList.toggle('is-empty', count === 0);
    });
    if (viewerPanel) viewerPanel.classList.toggle('has-history-selection', count > 0);
  }

  function clearSelection() {
    selectedPaths.clear();
    selectionAnchorPath = '';
    incidentalSelectionPath = '';
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
      // Ctrl/Shift 로 고른 것은 **작정한 선택**이다 - 탐색으로 놓지 않는다.
      promoteSelectionToExplicit();
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
    // 이 한 장은 "열려고 클릭했더니 딸려온" 선택이다. 다른 그림으로 넘어가면 놓는다.
    incidentalSelectionPath = selectOnOpen ? relPath : '';
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
      // 어떤 경로로든 살아남은 마퀴가 있으면 여기서 걷는다. 위의 여섯 갈래로
      // 대부분 잡히지만, 남으면 화면을 영구히 가리므로 마지막 방어선을 둔다.
      if (!dragSelection) {
        document.querySelectorAll('.history-selection-marquee').forEach(el => el.remove());
      }
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
        cells: [],
        scrollTop: 0,
        scrollLeft: 0,
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
        // 끌어서 고르는 것도 작정한 선택이다.
        promoteSelectionToExplicit();
        if (!dragSelection.additive) selectedPaths.clear();
        // **목록과 좌표는 여기서 한 번만 잰다.** 예전에는 pointermove 마다
        // querySelectorAll + 썸네일마다 getBoundingClientRect 를 돌려서,
        // 1,000장이면 프레임당 2,000회가 됐다(병합 전 필수 #3).
        // 드래그 중에 격자가 스크롤될 수 있으므로 그때의 scrollTop 도 같이 적어 두고,
        // 이동 판정에서 그 차이만큼 밀어 준다.
        dragSelection.cells = Array.from(grid.querySelectorAll('.viewer-thumb[data-path]'))
          .map(thumb => {
            const r = thumb.getBoundingClientRect();
            return {path: thumb.dataset.path || '',
                    left: r.left, right: r.right, top: r.top, bottom: r.bottom};
          })
          .filter(cell => cell.path);
        dragSelection.scrollTop = grid.scrollTop;
        dragSelection.scrollLeft = grid.scrollLeft;
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
      // 캐시한 좌표 + 스크롤 보정. DOM 을 다시 훑지 않는다.
      const dy = dragSelection.scrollTop - grid.scrollTop;
      const dx = dragSelection.scrollLeft - grid.scrollLeft;
      for (const cell of dragSelection.cells) {
        const box = {left: cell.left + dx, right: cell.right + dx,
                     top: cell.top + dy, bottom: cell.bottom + dy};
        if (rectsIntersect(bounds, box)) {
          selectedPaths.add(cell.path);
          lastPath = cell.path;
        }
      }
      dragSelection.lastPath = lastPath;
      updateSelectionUi();
      event.preventDefault();
    });
    // **끝내는 길을 grid 에만 두면 안 된다.** 드래그 중에 Win+Shift+S(캡처 도구)를
    // 누르면 포인터를 빼앗기는데, 그때 grid 로는 pointerup 도 pointercancel 도
    // 오지 않아 마퀴 사각형이 화면에 그대로 남는다(사용자 지적 2026-08-06 · 실측).
    // `position: fixed; z-index: 10050` 이라 결과 이미지 위에 계속 떠 있는다.
    //
    // 그래서 창 단위로 받고, 포인터가 아니라 **맥락이 끊기는 모든 경우**를 끝으로 친다:
    //   포인터를 뗌 / 취소됨 / 캡처를 잃음 / 창이 포커스를 잃음 / 탭이 숨겨짐 / Esc
    // 선택 자체는 드래그 중에 이미 반영돼 있으므로, 끝낼 때 되돌리지 않는다 —
    // 캡처하고 돌아왔을 때 고른 것이 사라져 있으면 그게 더 놀랍다.
    grid.addEventListener('pointerup', endDragSelection);
    grid.addEventListener('pointercancel', endDragSelection);
    grid.addEventListener('lostpointercapture', endDragSelection);
    window.addEventListener('pointerup', endDragSelection, true);
    window.addEventListener('pointercancel', endDragSelection, true);
    window.addEventListener('blur', () => endDragSelection());
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) endDragSelection();
    });
  }

  function selectAllLoaded() {
    const paths = gridPaths(activeSelectionGrid());
    promoteSelectionToExplicit();
    paths.forEach(path => selectedPaths.add(path));
    if (paths.length) selectionAnchorPath = paths[paths.length - 1];
    updateSelectionUi();
  }

  function setSelectionBusy(busy) {
    selectionBusy = Boolean(busy);
    updateSelectionUi();
  }

  // ── 다른 경로에 저장 (Save As) ─────────────────────────────────────────────
  //
  // 빠른 저장(`저장 N`)은 설정된 폴더로 바로 보낸다. 이쪽은 **사용자가 자리를
  // 고른다**(사용자 지정). 한 장이면 파일 이름까지 묻고(Save As), 여러 장이면
  // **폴더를 한 번만** 묻는다 - 4장에 대화상자가 4번 뜨면 그건 기능이 아니다.

  function hasNativeSavePicker() {
    return typeof window.showSaveFilePicker === 'function'
        || typeof window.showDirectoryPicker === 'function';
  }

  /** 저장할 파일 이름.
   *
   *  ⚠️ 자동 저장을 안 켠 항목은 **디스크에 파일이 없다** - `rel_path` 가
   *  `__history_item__/<uuid>` 라, 그대로 쓰면 `b382c45e….png` 같은 이름이 나온다
   *  (실측). 사람이 폴더에서 골라야 하는 이름이니 순번으로 바꾼다.
   *  디스크에 있는 항목은 원래 파일명을 그대로 지킨다.
   */
  function basenameOf(relPath, ordinal) {
    if (historyIdFromPath(relPath)) {
      const n = Number.isFinite(ordinal) ? String(ordinal + 1).padStart(2, '0') : '01';
      return `naia_${n}.png`;
    }
    const name = String(relPath || '').replace(/\\/g, '/').split('/').pop() || 'image.png';
    return /\.[a-z0-9]{2,5}$/i.test(name) ? name : `${name}.png`;
  }

  async function fetchHistoryBlob(relPath) {
    const response = await fetch(historyAssetUrl(relPath, 'image'));
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.blob();
  }

  async function writeBlob(handle, blob) {
    const writable = await handle.createWritable();
    try { await writable.write(blob); } finally { await writable.close(); }
  }

  async function saveSelectedAs() {
    const paths = orderedSelectedPaths();
    if (!paths.length || selectionBusy) return;
    if (!hasNativeSavePicker()) {
      showToast('이 환경에서는 저장 위치를 고를 수 없습니다.', 'error');
      return;
    }
    let target = null;
    let directory = false;
    try {
      if (paths.length === 1 && typeof window.showSaveFilePicker === 'function') {
        target = await window.showSaveFilePicker({
          suggestedName: basenameOf(paths[0], 0),
          types: [{description: 'PNG image', accept: {'image/png': ['.png']}}],
        });
      } else if (typeof window.showDirectoryPicker === 'function') {
        target = await window.showDirectoryPicker({mode: 'readwrite'});
        directory = true;
      } else {
        showToast('여러 장을 저장하려면 폴더 선택이 필요한 환경입니다.', 'error');
        return;
      }
    } catch (error) {
      if (error?.name === 'AbortError') return;      // 사용자가 취소했다 - 조용히
      showToast('저장 위치를 열지 못했습니다.', 'error');
      return;
    }
    if (!target) return;

    setSelectionBusy(true);
    let saved = 0;
    const failed = [];
    try {
      for (const [ordinal, relPath] of paths.entries()) {
        try {
          const blob = await fetchHistoryBlob(relPath);
          if (directory) {
            // ⚠️ 같은 이름이 이미 있으면 **말없이 덮어쓴다.** 이름 뒤에 번호를 붙여
            //    피한다 - 사용자가 고른 폴더의 남의 파일을 지울 수는 없다.
            const handle = await uniqueFileHandle(target, basenameOf(relPath, ordinal));
            await writeBlob(handle, blob);
          } else {
            await writeBlob(target, blob);
          }
          saved += 1;
        } catch (error) {
          failed.push(basenameOf(relPath, ordinal));
        }
      }
      const where = directory ? '고른 폴더' : '고른 위치';
      const parts = [`저장 ${saved}개`];
      if (failed.length) parts.push(`실패 ${failed.length}개`);
      showToast(`${parts.join(' · ')} · ${where}`, failed.length ? 'warning' : 'success');
    } finally {
      setSelectionBusy(false);
    }
  }

  async function uniqueFileHandle(dirHandle, filename) {
    const dot = filename.lastIndexOf('.');
    const stem = dot > 0 ? filename.slice(0, dot) : filename;
    const ext = dot > 0 ? filename.slice(dot) : '';
    for (let n = 0; n < 1000; n += 1) {
      const name = n === 0 ? filename : `${stem} (${n})${ext}`;
      try {
        await dirHandle.getFileHandle(name);        // 있으면 다음 번호로
      } catch (error) {
        if (error?.name === 'NotFoundError') return dirHandle.getFileHandle(name, {create: true});
        throw error;
      }
    }
    return dirHandle.getFileHandle(`${stem} (${Date.now()})${ext}`, {create: true});
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
      // **빠른 저장(Ctrl+S)과 같은 곳으로 간다.** 예전에는
      // `selected/save` 로 갔는데 그건 *미저장 항목을 저장 폴더에 구제*하는
      // 기능이라, 이미 자동 저장된 그림에는 "이미 있음"만 내고 아무 데도
      // 남기지 않았다 — 골라 둔 것만 따로 모으려던 손이 헛돌았다(사용자 지적).
      const response = await fetch('/api/history/selected/quicksave', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({paths}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data.ok) {
        throw new Error(data.error || `선택 저장 실패 (${response.status})`);
      }
      const saved = Number(data.saved || 0);
      const skipped = Number(data.skipped || 0);
      const failed = Array.isArray(data.failed) ? data.failed.length : 0;
      const folder = String(data.directory || '빠른 저장 폴더');
      const parts = [`저장 ${saved}개`];
      if (skipped) parts.push(`이미 있음 ${skipped}개`);
      if (failed) parts.push(`실패 ${failed}개`);
      showToast(`${parts.join(' · ')} · ${folder}`, failed ? 'warning' : 'success');
    } catch (error) {
      showToast(error.message || '선택 WebP 저장 실패', 'error');
    } finally {
      setSelectionBusy(false);
    }
  }

  async function deleteSelected() {
    const paths = orderedSelectedPaths();
    if (!paths.length || selectionBusy) return;
    // 뷰어 설정 판과 우클릭 메뉴가 쓰는 것과 **같은 키**다. 세 곳이 한 값을 본다.
    let deleteMode = 'history';
    try { deleteMode = localStorage.getItem(HISTORY_DELETE_MODE_KEY) === 'disk' ? 'disk' : 'history'; } catch (_) {}
    const modeText = deleteMode === 'disk'
      ? '연결된 저장 파일은 영구 삭제하지 않고 휴지통으로 이동합니다.'
      : '히스토리에서만 제거하며 저장 파일은 유지합니다.';
    // **저장 안 된 이미지는 지우면 끝이다.** 파일이 없으니 휴지통에도 안 남고
    // (`selected/delete` 는 `file_path` 가 있을 때만 휴지통으로 보낸다) 그림은
    // 서버 메모리에만 있었다. '묻지 않음'이 그 마지막 관문까지 걷어내고 있었다
    // — 되돌릴 수 있는 삭제에만 적용한다(Codex 리뷰 P1).
    //
    // 어느 항목이 미저장인지 화면은 정확히 알 수 없다(방금 생성한 것은 저장이
    // 아직 안 끝났을 수 있고, 알림은 저장 전에 온다). 그래서 전체 미저장 개수로
    // 판단한다 — 0 이면 고른 것도 전부 저장돼 있다. 모르면(-1) 묻는다.
    const unsaved = Number(getUnsavedCount());
    const recoverable = unsaved === 0;
    if (!viewerBindings.skipDeleteConfirm() || !recoverable) {
      const warn = recoverable ? ''
        : (unsaved > 0
            ? `\n\u26a0 아직 저장되지 않은 이미지가 ${unsaved}장 있습니다. 지우면 되돌릴 수 없습니다.`
            : '\n\u26a0 저장 여부를 알 수 없습니다.');
      const message = `${paths.length}개 선택 항목을 삭제할까요?\n${modeText}${warn}`;
      const confirmed = typeof confirmDialog === 'function'
        ? await confirmDialog(message, {title: '선택 항목 삭제', okText: `삭제 (${paths.length})`, cancelText: '취소'})
        : window.confirm(message);
      if (!confirmed) return;
    }

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
    // 팝업의 숫자도 여기서 같이 맞춘다. 예전에는 세 군데(쪽 불러오기·새 이미지·
    // 삭제)에서 각자 `#vpCount` 를 손봤는데, 그러면 그 셋을 안 지나는 길에서
    // 숫자가 남는다 — 히스토리를 비워도 머리에 '2' 가 그대로였다(실측).
    const popupCount = getEl('vpCount');
    if (popupCount) popupCount.textContent = viewerTotal;
    if (viewerPopupOpen) vpUpdatePosition();
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
    // 요청을 보낸 시점의 세대. 응답을 기다리는 사이 히스토리가 비워졌다면 이 응답은
    // 이미 사라진 항목들이므로 그리면 안 된다.
    const epochAtRequest = clearedEpoch;
    try {
      const resp = await fetchHistoryList(page, 30);
      const data = await resp.json();
      if (clearedEpoch !== epochAtRequest) return;
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
    } finally {
      viewerLoadingMore = false;
      if (viewerLoading) viewerLoading.style.display = 'none';
    }
  }

  function initViewer() {
    if (!viewerGrid) return;
    clearSelection();
    viewerPage = 0;
    viewerTotal = 0;
    viewerGrid.innerHTML = '';
    loadPage(0);
  }

  // 재조회는 비동기다. 응답을 기다리는 사이에 새 이미지 알림이 오면 그쪽이 최신이므로
  // 늦게 도착한 응답으로 총계를 되돌리면 안 된다(썸네일은 있는데 카운트만 0이 된다).
  let historySyncSeq = 0;

  function prepareInitialHistory() {
    const seq = ++historySyncSeq;
    fetchHistoryList(0, 1).then(resp => resp.json()).then(data => {
      if (seq !== historySyncSeq) return;   // 그 사이 더 새로운 사실이 도착했다
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
    releaseIncidentalSelection(relPath);
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

  /** 이 목록이 지금 몇 열인가. **상하 방향키는 한 줄만큼 움직여야 한다.**
   *
   *  ⚠️ 열 수를 상수로 박으면 안 된다 - 레일은 2열 고정이지만 팝업 목록은
   *  `repeat(auto-fill, minmax(120px, 1fr))` 라 창 폭에 따라 달라진다.
   *  계산된 `grid-template-columns` 는 열마다 px 값이 나오므로 개수를 센다.
   */
  function gridColumnCount(grid) {
    if (!grid) return 1;
    try {
      const template = getComputedStyle(grid).gridTemplateColumns || '';
      const columns = template.trim();
      if (!columns || columns === 'none') return 1;
      return Math.max(1, columns.split(/\s+/).length);
    } catch (_) {
      return 1;
    }
  }

  function navViewer(direction) {
    const total = viewerNavPaths.length;
    let next = viewerNavIdx + direction;
    // 줄 단위 이동은 끝을 넘으면 **끝 항목으로 붙인다.** 마지막 줄이 덜 찬 경우가
    // 흔한데, 거기서 아무 일도 안 일어나면 한 줄 아래로 가려던 손이 막힌다.
    if (Math.abs(direction) > 1) next = Math.min(Math.max(0, next), total - 1);
    if (next >= 0 && next < total && next !== viewerNavIdx) {
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
    if (Number.isFinite(Number(message.epoch)) && Number(message.epoch) < clearedEpoch) return false;
    historySyncSeq += 1;   // 진행 중인 재조회보다 이 알림이 최신이다
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
    // 같은 삭제가 **두 번** 온다 — 지운 쪽에서 즉시 한 번(반응을 바로 보여 준다),
    // 서버 브로드캐스트로 또 한 번. 두 번째는 치울 것이 없으므로 서버가 알려 준
    // 총계만 반영하고 빠진다. 지금은 대체로 무해하지만 구독자가 늘면 중복 처리로
    // 번진다(병합 전 필수 #6).
    const known = selectedPaths.has(relPath)
      || viewerNavPaths.includes(relPath)
      || Boolean(viewerGrid?.querySelector(`.viewer-thumb[data-path="${CSS.escape(relPath)}"]`));
    if (!known) {
      if (Number.isFinite(Number(message.total))) setViewerTotal(message.total);
      const dup = getEl('vpCount');
      if (dup) dup.textContent = viewerTotal;
      if (viewerTotal <= 0) hideLatestBadge();
      return;
    }
    selectedPaths.delete(relPath);
    if (selectionAnchorPath === relPath) selectionAnchorPath = '';
    if (incidentalSelectionPath === relPath) incidentalSelectionPath = '';
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
    // 이미 지나간 세대의 초기화 알림은 실행하지 않는다. 동시 초기화의 브로드캐스트가
    // 2 -> 1 순서로 도착하면, 늦게 온 1이 그 뒤에 정상 표시된 이미지를 지워 버린다.
    if (Number.isFinite(Number(message.epoch)) && Number(message.epoch) < clearedEpoch) return;
    // 서버 세대를 그대로 따른다. 임의로 앞서가면 이후 정상 새-이미지 알림의 세대가
    // 항상 작아져 히스토리에 아무것도 안 뜨게 된다.
    // 세대가 없는 알림(구버전 백엔드)일 때만 진행 중인 목록 요청을 무효화하려고 +1.
    clearedEpoch = Number.isFinite(Number(message.epoch))
      ? Math.max(clearedEpoch, Number(message.epoch))
      : clearedEpoch + 1;
    // 세대 판정을 통과한 진짜 초기화일 때만 선택을 비운다.
    clearSelection();
    viewerPage = 0;
    viewerTotal = 0;
    viewerNavPaths = [];
    viewerNavIdx = -1;
    currentViewerPath = '';
    latestImagePath = '';
    // 팝업 선택도 놓는다 — 안 그러면 빈 팝업에서 Ctrl+S 가 삭제된 경로를 보낸다.
    vpCurrentPath = '';
    viewerPendingNewCount = 0;
    promptFloatCache = {};
    promptFloatCacheKeys = [];
    if (viewerGrid) viewerGrid.innerHTML = '';
    const vpGrid = getEl('vpGrid');
    if (vpGrid) vpGrid.innerHTML = '';
    const vpPreview = getEl('vpPreview');
    if (vpPreview) vpPreview.removeAttribute('src');
    // 히스토리를 비우면 서버의 current asset 도 사라진다. 생성 결과 프리뷰
    // (source='current')까지 지워야 화면과 서버가 어긋나지 않는다.
    if (preview) {
      preview.removeAttribute('src');
      preview.classList.remove('show');
      preview.dataset.path = '';
      preview.dataset.source = '';
      if (emptyMsg) emptyMsg.style.display = '';
    }
    if (resultInfoContent) resultInfoContent.innerHTML = '<span class="result-info-empty">No history item selected</span>';
    setViewerTotal(message.total ?? 0);
    hideLatestBadge();
    // 초기화와 새 이미지 알림이 엇갈리면 화면이 서버보다 앞서거나 뒤처질 수 있다.
    // 초기화는 드문 동작이니 여기서 한 번 다시 맞춰 최종 상태를 서버에 수렴시킨다.
    prepareInitialHistory();
    return true;   // 호출부가 자기 쪽 정리를 할지 판단한다
  }

  function openPopup() {
    const lb = getEl('viewerLightbox');
    if (!lb) return;
    viewerPopupOpen = true;
    lb.innerHTML = `
    <div class="viewer-popup-inner" onclick="event.stopPropagation()">
      <div class="viewer-popup-header">
        <span class="viewer-block-icon">\u{1F5BC}</span>
        <span class="viewer-panel-title">History</span>
        <span class="viewer-panel-count" id="vpCount">${viewerTotal}</span>
        <div class="history-selection-bar viewer-popup-selection" id="vpSelectionBar">
          ${selectionBarMarkup('')}
        </div>
        <span class="viewer-head-spring"></span>
        <span class="vp-guide" aria-hidden="true">
          <b>휠</b> 장 넘김 <i>·</i> <b>Ctrl+휠</b> 확대 <i>·</i> <b>Del</b> 삭제
          <i>·</i> <b>H</b> 목록 <i>·</i> <b>F</b> 전체 화면
        </span>
        <span class="viewer-head-spring"></span>
        <span class="vp-seen" id="vpSeen" title="이번에 펼쳐 본 장수"></span>
        <button type="button" class="viewer-head-btn" id="vpListBtn"
                title="목록 접기 (H)">\u{21E4}</button>
        <button type="button" class="viewer-head-btn" id="vpFsBtn"
                title="전체 화면 (F)">\u{2921}</button>
        <button type="button" class="viewer-head-btn" id="vpShortcutBtn"
                data-viewer-settings-btn title="뷰어 설정">\u{2699}</button>
        <button type="button" class="viewer-head-btn" onclick="openResultFolder()"
                title="결과 폴더 열기">\u{1F4C1}</button>
        <button type="button" class="history-close"
                onclick="closeViewerPopup()" title="닫기" aria-label="닫기">&times;</button>
      </div>
      <div class="viewer-popup-body">
        <div class="viewer-popup-left-col">
          <div class="viewer-popup-left" id="vpGrid"></div>
          <div class="vp-left-bar">
            <button type="button" class="vp-bar-btn is-danger" id="vpClearAll"
                    title="히스토리를 통째로 비웁니다 — 저장된 파일은 그대로 남습니다">
              \u{1F5D1} 일괄정리</button>
            <span class="vp-bar-sep"></span>
            <span class="vp-left-note" id="vpLeftNote"></span>
          </div>
        </div>
        <div class="viewer-popup-right" id="vpRight">
          <div class="vp-stage" id="vpStage">
            <img class="vp-preview" id="vpPreview" alt="" draggable="false">
          </div>
          <div class="prompt-float" id="vpPromptFloat">
            <div class="prompt-float-content" id="vpPromptContent"></div>
          </div>
          <div class="vp-bar" id="vpBar">
            <button type="button" class="vp-bar-btn" id="vpPrev" title="이전 (\u2190 / 휠 위)">\u25C0</button>
            <input type="range" class="vp-slider" id="vpSlider" min="1" max="1" value="1"
                   aria-label="위치">
            <span class="vp-pos" id="vpPos">0 / 0</span>
            <button type="button" class="vp-bar-btn" id="vpNext" title="다음 (\u2192 / 휠 아래)">\u25B6</button>
            <span class="vp-bar-sep"></span>
            <button type="button" class="vp-bar-btn" id="vpZoomOut" title="축소 (\u2212 / Ctrl+휠)">\u2212</button>
            <span class="vp-zoom" id="vpZoom">100%</span>
            <button type="button" class="vp-bar-btn" id="vpZoomIn" title="확대 (+ / Ctrl+휠)">+</button>
            <button type="button" class="vp-bar-btn is-wide" id="vpFit"
                    title="맞춤 0 / 원본 1">맞춤</button>
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
    vpSelectionOnOpen = new Set(selectedPaths);
    bindPopupViewer();
    bindShortcutUi();
    vpEdgePending = '';
    vpWheelAccum = 0;
    vpSetListHidden(false);
    vpUpdatePosition();
    updateSelectionUi();
  }

  async function loadPopupPage(page) {
    if (vpLoading) return;
    vpLoading = true;
    const loading = getEl('vpLoading');
    if (loading) loading.style.display = '';
    const epochAtRequest = clearedEpoch;   // loadPage 와 같은 이유 — 초기화가 끼면 버린다
    try {
      const resp = await fetchHistoryList(page, 30);
      const data = await resp.json();
      if (clearedEpoch !== epochAtRequest) return;
      const grid = getEl('vpGrid');
      if (grid) {
        for (const entry of data.images) {
          if (grid.querySelector(`.viewer-thumb[data-path="${CSS.escape(entry.rel_path)}"]`)) continue;
          const img = document.createElement('img');
          img.className = 'viewer-thumb';
          img.loading = 'lazy';
          img.dataset.path = entry.rel_path;
          img.src = historyAssetUrl(entry.rel_path, 'thumb');
          if (vpSeen.has(entry.rel_path)) img.dataset.seen = '1';
          configureThumb(img, entry.rel_path, grid, () => selectPopupImage(entry.rel_path, img), {selectOnOpen: true});
          grid.appendChild(img);
        }
      }
      vpPage = page + 1;
      viewerTotal = data.total;
      const count = getEl('vpCount');
      if (count) count.textContent = data.total;
      vpUpdatePosition();
    } catch (_) {
    } finally {
      vpLoading = false;
      if (loading) loading.style.display = 'none';
    }
  }

  // ── 줌 / 팬 ─────────────────────────────────────────────────────────────
  /**
   * 지금 그림이 무대 밖으로 얼마나 나가 있나. 축마다 **한쪽으로 밀 수 있는 최대치**다.
   *
   * 그림이 무대보다 작으면 0 이다 — 밀 데가 없으니 가운데 고정이고, 잡아끌 수도 없다.
   * `scale()` 은 가운데를 기준으로 커지므로 넘치는 양의 절반씩 양옆으로 나간다.
   */
  function vpPanRange() {
    const stage = getEl('vpStage');
    if (!stage || !vpNatW || !vpNatH) return {x: 0, y: 0};
    const box = stage.getBoundingClientRect();
    return {
      x: Math.max(0, (vpNatW * vpZoom - box.width) / 2),
      y: Math.max(0, (vpNatH * vpZoom - box.height) / 2),
    };
  }

  const vpCanPan = () => { const r = vpPanRange(); return r.x > 0.5 || r.y > 0.5; };

  function vpApplyTransform() {
    const img = getEl('vpPreview');
    if (!img) return;
    // **그림 끝을 무대 안으로 들이지 않는다.** 예전에는 한없이 끌려가 빈 화면만
    // 남길 수 있었다(사용자 지적). 여기서 한 번 묶으면 팬이든 휠 줌이든 창 크기
    // 변화든 모든 경로가 같이 묶인다.
    const range = vpPanRange();
    vpTx = Math.min(range.x, Math.max(-range.x, vpTx));
    vpTy = Math.min(range.y, Math.max(-range.y, vpTy));
    img.style.transform = `translate(${Math.round(vpTx)}px, ${Math.round(vpTy)}px) scale(${vpZoom})`;
    const label = getEl('vpZoom');
    if (label) label.textContent = `${Math.round(vpZoom * 100)}%`;
    const fit = getEl('vpFit');
    if (fit) {
      // 옛 뷰어는 '지금 무슨 모드인가'를 적었는데, 휠로 107% 쯤에 가 있으면
      // 맞춤도 원본도 아니면서 "원본"이라고 적혀 거짓말이 된다. 여기서는
      // **누르면 무엇이 되는지**를 적는다.
      fit.textContent = vpFitMode ? '원본' : '맞춤';
      fit.title = vpFitMode ? '원본 크기로 (1)' : '화면에 맞추기 (0)';
      fit.classList.toggle('is-on', vpFitMode);
    }
    const stage = getEl('vpStage');
    // 손 모양은 **실제로 끌 수 있을 때만** 뜬다. 예전에는 '맞춤이 아니면'으로
    // 판단해서, 그림이 무대보다 작아 밀 데가 없는데도 잡을 것처럼 보였다.
    if (stage) stage.classList.toggle('is-pannable', range.x > 0.5 || range.y > 0.5);
  }

  function vpComputeFit() {
    const stage = getEl('vpStage');
    if (!stage || !vpNatW || !vpNatH) return 1;
    const box = stage.getBoundingClientRect();
    const pad = 28;   // 무대 여백 — 그림이 경계에 붙어 잘린 것처럼 보이지 않게
    const w = Math.max(1, box.width - pad);
    const h = Math.max(1, box.height - pad);
    // 원본보다 크게 늘리지 않는다. 작은 그림을 억지로 키우면 뭉개져 보인다.
    return Math.min(w / vpNatW, h / vpNatH, 1);
  }

  function vpFitToStage() {
    vpFitZoom = vpComputeFit();
    vpZoom = vpFitZoom;
    vpFitMode = true;
    vpTx = 0;
    vpTy = 0;
    vpApplyTransform();
  }

  function vpSetZoom(next, anchor) {
    const z = Math.min(VP_ZOOM_MAX, Math.max(VP_ZOOM_MIN, next));
    if (Math.abs(z - vpZoom) < 1e-6) return;
    const stage = getEl('vpStage');
    if (stage && anchor) {
      // 커서 아래의 점을 붙잡아 둔다 — 붙잡지 않으면 확대할수록 보던 곳이 달아난다.
      const box = stage.getBoundingClientRect();
      const cx = anchor.x - box.left - box.width / 2;
      const cy = anchor.y - box.top - box.height / 2;
      const k = z / vpZoom;
      vpTx = cx - (cx - vpTx) * k;
      vpTy = cy - (cy - vpTy) * k;
    }
    vpZoom = z;
    vpFitMode = Math.abs(vpZoom - vpFitZoom) < 1e-6 && vpTx === 0 && vpTy === 0;
    vpApplyTransform();
  }

  // 휠 한 번에 한 장. 트랙패드는 손가락 한 번에도 델타를 수십 번 흘리므로
  // 그대로 받으면 열 장이 우르르 지나간다 — 문턱을 넘을 때만 한 칸 옮긴다.
  const VP_WHEEL_THRESHOLD = 60;
  let vpWheelAccum = 0;
  function vpWheelNavigate(deltaY) {
    if (Math.sign(deltaY) !== Math.sign(vpWheelAccum)) vpWheelAccum = 0;
    vpWheelAccum += deltaY;
    if (Math.abs(vpWheelAccum) < VP_WHEEL_THRESHOLD) return;
    const direction = vpWheelAccum < 0 ? -1 : 1;
    vpWheelAccum = 0;
    navPopup(direction);
  }

  function vpZoomStep(direction, anchor) {
    vpSetZoom(direction > 0 ? vpZoom * VP_ZOOM_STEP : vpZoom / VP_ZOOM_STEP, anchor);
  }

  function vpToggleFit() {
    if (vpFitMode) {
      vpZoom = 1;               // 원본 1:1
      vpFitMode = false;
      vpTx = 0;
      vpTy = 0;
      vpApplyTransform();
    } else {
      vpFitToStage();
    }
  }

  function vpOnImageLoad() {
    const img = getEl('vpPreview');
    if (!img) return;
    vpNatW = img.naturalWidth || 0;
    vpNatH = img.naturalHeight || 0;
    vpFitToStage();
  }

  // ── 위치 / 본 것 ────────────────────────────────────────────────────────
  function vpThumbs() {
    const grid = getEl('vpGrid');
    return grid ? [...grid.querySelectorAll('.viewer-thumb')] : [];
  }

  function vpPaintSlider(value, total) {
    const slider = getEl('vpSlider');
    if (!slider) return;
    const pct = total > 1 ? ((value - 1) / (total - 1)) * 100 : 0;
    slider.style.background =
      `linear-gradient(to right, var(--accent) ${pct}%, var(--border-dim) ${pct}%)`;
  }

  function vpUpdatePosition() {
    const thumbs = vpThumbs();
    const index = thumbs.findIndex(t => t.classList.contains('active'));
    const slider = getEl('vpSlider');
    const pos = getEl('vpPos');
    const total = Math.max(viewerTotal, thumbs.length);
    if (slider) {
      slider.max = String(Math.max(1, total));
      slider.value = String(index >= 0 ? index + 1 : 1);
      slider.disabled = total <= 1;
      vpPaintSlider(Number(slider.value), total);
    }
    if (pos) pos.textContent = `${index >= 0 ? index + 1 : 0} / ${total}`;
    const note = getEl('vpLeftNote');
    if (note) {
      note.textContent = total ? `${total}장` : '';
    }
    const seen = getEl('vpSeen');
    if (seen) {
      seen.textContent = vpSeen.size ? `\u{1F441} ${vpSeen.size}` : '';
      seen.title = `이번에 펼쳐 본 장수 — 전체 ${total}장 중 ${vpSeen.size}장`;
    }
  }

  // 슬라이더를 아직 안 불러온 구간으로 던지면, 거기까지 순서대로 채운 뒤 간다.
  // 무한 스크롤이 하던 일과 같다 — 다만 사용자가 요청했을 때만 몰아서 한다.
  async function vpSeek(index) {
    let thumbs = vpThumbs();
    let guard = 0;
    while (index >= thumbs.length && thumbs.length < viewerTotal && guard++ < 80) {
      await loadPopupPage(vpPage);
      const grown = vpThumbs();
      if (grown.length === thumbs.length) break;   // 더 안 늘면 그만
      thumbs = grown;
    }
    const target = thumbs[Math.min(Math.max(0, index), thumbs.length - 1)];
    if (target) {
      selectPopupImage(target.dataset.path, target);
      target.scrollIntoView({block: 'nearest'});
    }
  }

  // ── 목록 접기 / 전체 화면 ───────────────────────────────────────────────
  function vpSetListHidden(hidden) {
    vpListHidden = hidden;
    const inner = getEl('viewerLightbox')?.querySelector('.viewer-popup-inner');
    if (inner) inner.classList.toggle('list-hidden', hidden);
    const btn = getEl('vpListBtn');
    if (btn) {
      btn.textContent = hidden ? '\u21E5' : '\u21E4';
      btn.title = hidden ? '목록 펼치기 (H)' : '목록 접기 (H)';
      btn.classList.toggle('is-on', hidden);
    }
    // 무대 폭이 바뀌었으니 맞춤 배율을 다시 잡는다. 맞춤이 아니어도 위치는
    // 다시 묶어야 한다(넓어진 쪽으로 그림이 딸려 들어오면 안 된다).
    requestAnimationFrame(() => { if (vpFitMode) vpFitToStage(); else vpApplyTransform(); });
  }

  function vpToggleFullscreen() {
    const lb = getEl('viewerLightbox');
    if (!lb) return;
    if (document.fullscreenElement) document.exitFullscreen?.();
    else lb.requestFullscreen?.().catch(() => showToast('전체 화면을 열 수 없습니다.', 'error'));
  }

  function bindPopupViewer() {
    const img = getEl('vpPreview');
    if (img) img.addEventListener('load', vpOnImageLoad);

    const stage = getEl('vpStage');
    if (stage) {
      // 옛 뷰어와 같다: 맨 휠은 **장 넘김**, 좌클릭을 누른 채 휠이면 줌.
      // 웹에서는 좌클릭을 누르면 곧바로 팬이 시작되므로 Ctrl/Cmd + 휠도
      // 같이 받는다 — 브라우저에서 확대는 원래 그 손가락이다.
      stage.addEventListener('wheel', event => {
        if (!event.deltaY) return;
        event.preventDefault();
        // 앱(Electron)의 preload 가 Ctrl+휠을 창 배율로 가져가지만, 이 무대
        // (`.vp-stage`) 안에서는 비켜난다 — 그래서 여기서는 Ctrl 이 그림을
        // 확대한다. Alt 도 같이 받아 둔다: 그 preload 가 아직 안 나간 셸에서는
        // Ctrl 이 여전히 먹히므로, 그때 쓸 길이 하나는 있어야 한다.
        const zoomIntent = event.ctrlKey || event.metaKey || event.altKey || vpPan;
        if (zoomIntent) {
          vpZoomStep(event.deltaY < 0 ? 1 : -1, {x: event.clientX, y: event.clientY});
        } else {
          vpWheelNavigate(event.deltaY);
        }
      }, {passive: false});
      stage.addEventListener('dblclick', vpToggleFit);
      stage.addEventListener('pointerdown', event => {
        if (event.button !== 0) return;
        // 확대해서 그림이 무대 밖으로 나가 있을 때만 잡힌다. 다 보이는 그림을
        // 끌어 봐야 갈 데가 없는데 손에 붙어 따라다니면 그게 불편하다(사용자 지적).
        if (!vpCanPan()) return;
        vpPan = {x: event.clientX, y: event.clientY, tx: vpTx, ty: vpTy};
        stage.setPointerCapture?.(event.pointerId);
        stage.classList.add('is-panning');
      });
      stage.addEventListener('pointermove', event => {
        if (!vpPan) return;
        vpTx = vpPan.tx + (event.clientX - vpPan.x);
        vpTy = vpPan.ty + (event.clientY - vpPan.y);
        if (vpTx !== 0 || vpTy !== 0) vpFitMode = false;
        vpApplyTransform();
      });
      // 마퀴 잔상 때와 같은 이유로 끝내는 길을 넓게 둔다 — 창을 뺏겨도 풀린다.
      const endPan = () => { vpPan = null; stage.classList.remove('is-panning'); };
      stage.addEventListener('pointerup', endPan);
      stage.addEventListener('pointercancel', endPan);
      stage.addEventListener('lostpointercapture', endPan);
      window.addEventListener('blur', endPan);
    }

    const on = (id, fn) => { const el = getEl(id); if (el) el.addEventListener('click', fn); };
    on('vpPrev', () => navPopup(-1));
    on('vpNext', () => navPopup(1));
    on('vpZoomIn', () => vpZoomStep(1));
    on('vpZoomOut', () => vpZoomStep(-1));
    on('vpFit', vpToggleFit);
    on('vpListBtn', () => vpSetListHidden(!vpListHidden));
    on('vpFsBtn', vpToggleFullscreen);
    on('vpClearAll', () => {
      if (typeof clearAllHistory === 'function') clearAllHistory();
      else showToast('히스토리 초기화를 열 수 없습니다.', 'error');
    });

    const slider = getEl('vpSlider');
    if (slider) {
      // 끌고 있는 동안은 숫자만 따라간다. 손을 뗄 때 한 번만 실제로 옮긴다 —
      // 매 픽셀마다 옮기면 아직 안 받은 구간에서 요청이 쏟아진다.
      slider.addEventListener('input', () => {
        const pos = getEl('vpPos');
        const total = Math.max(viewerTotal, vpThumbs().length);
        if (pos) pos.textContent = `${slider.value} / ${total}`;
        vpPaintSlider(Number(slider.value), total);
      });
      slider.addEventListener('change', () => vpSeek(Number(slider.value) - 1));
    }

    // 창이 커지면 무대도 커진다 — 맞춤이면 배율을 다시 잡고, 아니면 최소한
    // 위치를 다시 묶어야 한다. 안 그러면 넓어진 무대에 빈 여백이 생긴다.
    window.addEventListener('resize', () => {
      if (!viewerPopupOpen) return;
      if (vpFitMode) vpFitToStage();
      else vpApplyTransform();
    });
  }

  // ── 숫컷 바인딩 배선 ──
  function bindShortcutUi() {
    const btn = getEl('vpShortcutBtn');
    if (!btn) return;
    // 예전에는 앱에서만 띄웠다. 이제 이 판에는 폴더와 무관한 손버릇 토글도 있어
    // 브라우저에서도 열려야 한다 — 숏컷 구역만 앱에서 그린다(패널 쪽 판단).
    // 읽기는 판을 열 때 안에서 한다 — 여기서 따로 부르면 캐시로 먼저 그린
    // 화면과 경합한다(Codex 리뷰 P2).
    btn.addEventListener('click', () => viewerBindings.togglePanel(btn));
  }

  // 레일에도 같은 판을 연다. 팝업을 열지 않고도 삭제 방식·저장 경로를 만질 수
  // 있어야 한다 — 그게 늘 보이는 쪽이다.
  function bindRailSettings() {
    const btn = getEl('viewerRailSettings');
    if (!btn) return;
    btn.addEventListener('click', () => viewerBindings.togglePanel(btn));
  }

  // 마우스 보조 버튼(뒤로/앞으로/휠클릭). `auxclick` 은 좌클릭을 주지 않아
  // 팬/선택과 부딪히지 않는다. 뒤로/앞으로는 브라우저가 방문 기록을 넘기려 하므로
  // `mousedown` 에서 미리 막는다 — auxclick 만 막으면 이미 늦다.
  function bindShortcutInputs() {
    const AUX = new Set([1, 3, 4]);
    document.addEventListener('mousedown', event => {
      if (!viewerPopupOpen || !AUX.has(event.button)) return;
      const inputId = viewerBindings.inputIdFromMouse(event.button);
      if (viewerBindings.isCapturing() || viewerBindings.hasBinding(inputId)) {
        event.preventDefault();
      }
    });
    document.addEventListener('auxclick', event => {
      if (!viewerPopupOpen || !AUX.has(event.button)) return;
      const inputId = viewerBindings.inputIdFromMouse(event.button);
      if (viewerBindings.isCapturing()) {
        event.preventDefault();
        viewerBindings.finishCapture(inputId);
        return;
      }
      if (viewerBindings.hasBinding(inputId)) {
        event.preventDefault();
        viewerBindings.dispatch(inputId, vpCurrentPath);
      }
    });
  }

  function selectPopupImage(relPath, thumbEl) {
    // 실제로 한 장이 열렸으면 끝에서 막아 둔 자리를 푼다 — 클릭이든 슬라이더든
    // 화살표든, 어디로든 움직였으면 '끝에 서 있다'는 상태는 이미 지났다.
    vpEdgePending = '';
    releaseIncidentalSelection(relPath);
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
    if (relPath) vpSeen.add(relPath);
    if (thumbEl) thumbEl.dataset.seen = '1';
    vpUpdatePosition();
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
    // 팝업 안에서 고른 것이 밖으로 새면 안 된다 — 메인 화면에서 고른 적이 없는데
    // 삭제 버튼이 켜져 있는 셈이라 위험하다(사용자 지적). 그렇다고 통째로 비우면
    // 레일에서 미리 골라 둔 것까지 잃는다(Codex 리뷰 P2). **열 때 있던 것만**
    // 남긴다. 팝업에서 일부러 뺀 것은 뺀 채로 둔다 — 되살리는 편이 더 놀랍다.
    if (vpSelectionOnOpen) {
      const keep = [...selectedPaths].filter(path => vpSelectionOnOpen.has(path));
      selectedPaths.clear();
      keep.forEach(path => selectedPaths.add(path));
      if (!selectedPaths.size) selectionAnchorPath = '';
      updateSelectionUi();
    }
    vpSelectionOnOpen = null;
    // 팝업에서 딸려온 단일 선택은 위 필터가 이미 걷어냈다 - 표식만 남으면 다음
    // 탐색에서 엉뚱한 판정을 한다.
    incidentalSelectionPath = '';
    viewerBindings.setPanelOpen(false);
    if (document.fullscreenElement) document.exitFullscreen?.();
    vpPan = null;
    // 선택을 놓지 않으면 팝업을 닫은 뒤의 Ctrl+S 가 옛 선택을 저장한다.
    vpCurrentPath = '';
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
    const step = (target) => {
      selectPopupImage(thumbs[target].dataset.path, thumbs[target]);
      thumbs[target].scrollIntoView({block: 'nearest', behavior: 'smooth'});
    };
    if (next >= 0 && next < thumbs.length) {
      step(next);
      return;
    }
    // 줄 단위 이동(|direction| > 1)은 끝을 넘어도 **끝 항목으로 붙인다.** 마지막
    // 줄이 덜 찬 경우가 흔한데, 거기서 "마지막입니다" 를 띄우고 멈추면 한 줄
    // 아래로 가려던 손이 막힌다. 처음/끝 되감기는 좌우(±1) 전용으로 남긴다.
    if (Math.abs(direction) > 1) {
      if (direction > 0 && thumbs.length < viewerTotal) {
        vpSeek(next);          // 아직 안 받은 뒷장 - vpSeek 이 받아 온다
        return;
      }
      const clamped = direction > 0 ? thumbs.length - 1 : 0;
      if (clamped !== index) {
        step(clamped);
        return;
      }
      return;                  // 이미 그 끝이다 - 되감지 않는다
    }
    // 아직 안 받은 뒷장이 남아 있으면 여기는 끝이 아니다 — 이어서 받는다.
    // (데스크톱 뷰어는 폴더 전체를 한 번에 들고 있어 이 경우가 없었다.)
    if (direction > 0 && thumbs.length < viewerTotal) {
      vpSeek(thumbs.length);
      return;
    }
    // 진짜 끝. 옛 뷰어의 `_edge_pending` 그대로 — **한 번은 막고 알린다.**
    // 훑어 내려가다 관성으로 처음으로 튀어버리면 어디였는지를 잃는다.
    const edge = direction > 0 ? 'last' : 'first';
    if (vpEdgePending !== edge) {
      vpEdgePending = edge;
      showToast(edge === 'last'
        ? '마지막 이미지입니다. 한 번 더 누르면 처음으로.'
        : '첫 번째 이미지입니다. 한 번 더 누르면 마지막으로.');
      return;
    }
    vpEdgePending = '';
    vpSeek(edge === 'last' ? 0 : Math.max(0, Math.max(viewerTotal, thumbs.length) - 1));
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
      // Ctrl+D 는 켜 둔 사람만 쓴다. 켜져 있으면 Del 과 **똑같이** 동작한다 —
      // 삭제 방식(히스토리만 / 휴지통)도, 물어볼지 말지도 한 곳에서 갈린다.
      // Ctrl 을 붙인 이유는 **Ctrl+S 가 저장이기 때문**이다(사용자 지적). 맨 D 는
      // 저장과 짝이 안 맞고, 글자 키 하나에 파일 삭제가 얹히는 것도 무겁다.
      // 브라우저 즐겨찾기가 Ctrl+D 지만 preventDefault 로 눌린다.
      // 숏컷 설정에서 입력을 받는 중이면 그 키는 설정 몫이므로 여기서 비켜난다.
      const deleteKey = event.key === 'Delete'
        || event.key === 'Backspace'
        || (viewerBindings.deleteKeyDEnabled()
            && String(event.key).toLowerCase() === 'd'
            && commandKey && !event.altKey && !event.shiftKey
            && !viewerBindings.isCapturing());
      if (deleteKey && selectedPaths.size) {
        event.preventDefault();
        deleteSelected();
        return;
      }
      // 드래그 중 Esc 는 드래그부터 끊는다 — 손이 묶인 상태를 먼저 푼다.
      if (event.key === 'Escape' && dragSelection) {
        event.preventDefault();
        endDragSelection();
        return;
      }
      // Esc — 팝업이 열려 있으면 **닫기가 먼저**다. 예전에는 선택이 있으면
      // 무조건 선택 해제로 먹혀 팝업을 닫으려면 두 번 눌러야 했다(클릭만으로
      // 선택이 생기므로 사실상 늘 그랬다). 팝업이 없을 때만 선택을 비운다.
      if (event.key === 'Escape' && selectedPaths.size && !viewerPopupOpen) {
        event.preventDefault();
        clearSelection();
        return;
      }

      if (viewerPopupOpen) {
        // 숏컷 설정에서 입력을 받고 있는 중이면 그 키는 설정으로 간다.
        // Esc 는 예외 — 그것까지 먹으면 설정 창을 닫을 길이 없어진다.
        if (viewerBindings.isCapturing()) {
          if (event.key !== 'Escape') {
            event.preventDefault();
            viewerBindings.finishCapture(viewerBindings.inputIdFromKey(event));
          } else {
            viewerBindings.setPanelOpen(false);
          }
          return;
        }
        const boundId = viewerBindings.inputIdFromKey(event);
        if (viewerBindings.hasBinding(boundId)) {
          event.preventDefault();
          viewerBindings.dispatch(boundId, vpCurrentPath);
          return;
        }
        // 옛 NAIA Viewer 와 같은 손버릇: 0=맞춤 1=원본 F=전체화면 Home/End=처음/끝.
        // H(목록 접기)와 Space(다음)는 웹 쪽에서 더한 것이다.
        // 좌우는 한 장, **상하는 한 줄**(사용자 지정). 예전에는 넷이 모두 ±1
        // 이라 상하와 좌우가 구분되지 않았다 - 목록이 다열이라 손이 예측한 대로
        // 움직이지 않았다.
        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          navPopup(-1);
        } else if (event.key === 'ArrowRight'
                   || event.key === ' ' || event.key === 'Spacebar') {
          event.preventDefault();
          navPopup(1);
        } else if (event.key === 'ArrowUp') {
          event.preventDefault();
          navPopup(-gridColumnCount(getEl('vpGrid')));
        } else if (event.key === 'ArrowDown') {
          event.preventDefault();
          navPopup(gridColumnCount(getEl('vpGrid')));
        } else if (event.key === 'Home') {
          event.preventDefault();
          vpSeek(0);
        } else if (event.key === 'End') {
          event.preventDefault();
          vpSeek(Math.max(0, viewerTotal - 1));
        } else if (key === '0') {
          event.preventDefault();
          vpFitToStage();
        } else if (key === '1') {
          // 어디에 가 있든 1 은 항상 원본 1:1 로 되돌린다 — 휠로 107% 쯤에
          // 떠 있을 때 아무 반응이 없으면 고장으로 읽힌다.
          event.preventDefault();
          vpZoom = 1;
          vpFitMode = Math.abs(vpFitZoom - 1) < 1e-6;
          vpTx = 0;
          vpTy = 0;
          vpApplyTransform();
        } else if (key === '+' || key === '=') {
          event.preventDefault();
          vpZoomStep(1);
        } else if (key === '-' || key === '_') {
          event.preventDefault();
          vpZoomStep(-1);
        } else if (key === 'f' || event.key === 'F11') {
          event.preventDefault();
          vpToggleFullscreen();
        } else if (key === 'h') {
          event.preventDefault();
          vpSetListHidden(!vpListHidden);
        } else if (event.key === 'Escape') {
          if (document.fullscreenElement) document.exitFullscreen?.();
          else closePopup();
        }
        return;
      }

      if (viewerNavIdx < 0 || viewerNavPaths.length === 0) return;

      // 팝업과 같은 규칙: 좌우는 한 장, 상하는 한 줄. 레일은 2열 고정이지만
      // 열 수는 실측해서 쓴다 - CSS 가 바뀌면 여기가 조용히 틀어진다.
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        navViewer(-1);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        navViewer(1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        navViewer(-gridColumnCount(viewerGrid));
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        navViewer(gridColumnCount(viewerGrid));
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
    // **레일 격자에는 드래그 선택을 걸지 않는다.** 히스토리로 들어가지 않은
    // 메인 화면에서 마퀴가 도는 것은 의도한 사양이 아니다(사용자 지적
    // 2026-08-08) — 좁은 레일에서 스크롤하려다 여러 장이 선택된다.
    // 여기서는 **개별 클릭만** 지원한다. 드래그는 팝업(`#vpGrid`)에서만
    // 걸린다(openPopup 안의 bindDragSelection).
    //
    // tabIndex 는 그 배선이 세우고 있었다 — 빼면 `configureThumb` 의
    // `grid.focus()` 가 조용히 no-op 이 되어 키보드 판정(`viewerPanel.contains
    // (activeElement)`)이 어긋난다. 포커스만 따로 남긴다.
    if (viewerGrid && !viewerGrid.hasAttribute('tabindex')) viewerGrid.tabIndex = 0;
    bindKeyboard();
    bindShortcutInputs();
    bindRailSettings();
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
    /** Ctrl+S 를 히스토리가 맡을 것인가. app.js 의 **단일 판정**이 부른다.
     *  document 리스너를 여기서 또 달면 `preventDefault()` 가 서로를 막지 못해
     *  둘 다 실행된다(파일 2개·토스트 2개). 고른 것이 있을 때만 참을 낸다.
     *  @returns {boolean} 우리가 처리했으면 true — 호출자가 기본동작을 막는다. */
    handleSaveShortcut() {
      if (!selectedPaths.size) return false;
      saveSelected();
      return true;
    },
    closePopup,
    navPopup,
    toggleLightboxPrompt,
    togglePopupPrompt,
    thumbClick,
    navViewer,
    hideNav,
    openFolder,
    // 저장 경로 상태가 도착하면 뷰어 설정 판의 한 줄을 갱신한다.
    onSaveDirectoryState: () => viewerBindings.refresh(),
    loadResultInfo,
    get latestImagePath() { return latestImagePath; },
    // Ctrl+S 빠른 저장이 "지금 보고 있는 것"을 알아야 한다. 히스토리 팝업이
    // 열려 있으면 그쪽 선택이 이긴다(팝업은 vpCurrentPath 로 따로 돈다).
    // 뷰어도 팝업도 없으면 최신 이미지가 곧 보고 있는 것이다.
    get currentImagePath() {
      // Ctrl+S 는 "보고 있는 것"을 저장한다. 그러므로 화면이 진실이다 —
      // currentViewerPath(탐색 상태)를 먼저 보면 두 방향으로 어긋난다:
      //   Esc 로 탐색만 해제하면 화면은 그대로인데 값이 비어 최신으로 폴백하고,
      //   탐색 중에 새 결과가 도착하면 화면은 새것인데 값은 옛 선택에 머문다.
      // preview.dataset 이 화면 상태를 정확히 담는다:
      //   히스토리 선택 -> source='saved', path=<rel_path>
      //   새 생성 결과 -> source='current', path=''  (곧 latestImagePath 가 채워진다)
      if (viewerPopupOpen && vpCurrentPath) return vpCurrentPath;
      if (preview && preview.classList.contains('show')) {
        const shown = String(preview.dataset.path || '');
        if (shown) return shown;
        if (preview.dataset.source === 'current') return latestImagePath;
      }
      return currentViewerPath || latestImagePath;
    },
  };
}
