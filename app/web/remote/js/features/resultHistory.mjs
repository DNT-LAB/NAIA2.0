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
  // Del 키를 **다른 화면이 먼저 가져가는가.** 인페인트 편집 화면에서는 Del 이 레이어의 것이다 -
  // true 를 돌려주면 히스토리는 아무것도 지우지 않는다(사용자 제보 2026-10-05: 캔버스를 고치다
  // Del 을 누르자 히스토리에서 골라 둔 그림의 삭제 창이 떴다 - '묻지 않기' 를 켜 둔 사람은 말없이 지워진다).
  deleteKeyGuard = null,
  // 지금은 **반드시 물어보고** 지워야 하는가(인페인트 세션 중). '묻지 않기' 두 가지를 모두 이긴다.
  mustConfirmDelete = null,
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

  // 숏컷 바인딩(앱 전용) - 뷰어 설정 판(⚙ · 레일과 History 창)이 열고, History 창이 실행한다.
  const viewerBindings = createViewerBindings({
    getEl,
    showToast,
    onItemRemoved: payload => onRemoved(payload),
    openSaveDirectory,
    getSaveDirectory,
    requestSaveDirectory,
    openQuicksaveSettings,
  });
  let viewerNavPaths = [];
  let viewerNavIdx = -1;
  let currentViewerPath = '';
  // 마지막으로 본 초기화 세대. 이보다 낡은 새-이미지 알림은 이미 비워진 히스토리의
  // 것이므로 그리면 유령이 된다. 진행 중이던 목록 요청의 응답을 버리는 데도 쓴다.
  let clearedEpoch = 0;
  let viewerPendingNewCount = 0;
  let latestImagePath = '';
  let promptFloatCache = {};
  let promptFloatCacheKeys = [];
  const selectedPaths = new Set();
  // 삭제 확인을 **이번 실행 동안만** 건너뛴다(사용자 요청 2026-08-30).
  //
  // ⚠️ 뷰어 설정의 `삭제할 때 묻지 않음`(`skipDeleteConfirm`)과 **다른 것**이다.
  //    그쪽은 localStorage 에 굳어 다음에 켜도 그대로다. 이건 새로고침하면 사라진다 -
  //    "지금 몇 장 정리하는 동안만" 이라는 뜻이라 남기면 안 된다.
  let skipDeleteConfirmThisRun = false;
  let selectionAnchorPath = '';
  let selectionBusy = false;
  // 레일은 **클릭 한 번에 열림 + 선택**이 같이 일어난다(`selectOnOpen`).
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
  /** 지금 선택이 "열려고 클릭했더니 딸려온 한 장" 뿐인가.
   *
   *  Ctrl/Shift/드래그로 **작정하고 고른 것**과 가르는 잣대다. 놓아줄지(위)와
   *  선택 바를 띄울지(아래)가 같은 질문이라 한 곳에서 답한다.
   */
  function selectionIsOnlyIncidental() {
    return Boolean(incidentalSelectionPath)
      && selectedPaths.size === 1
      && selectedPaths.has(incidentalSelectionPath);
  }

  function releaseIncidentalSelection(nextPath) {
    if (!incidentalSelectionPath) return;
    if (nextPath && nextPath === incidentalSelectionPath) return;   // 그 그림 그대로다
    const onlyIncidental = selectionIsOnlyIncidental();
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

  function orderedSelectedPaths() {
    const result = [];
    const seen = new Set();
    for (const grid of [viewerGrid]) {
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
      // 레일 안내에 **드래그는 없다** — 레일은 드래그 선택을 걸지 않는다(init 주석).
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
    // ⚠️ **우측 레일에는 딸려온 한 장 때문에 바를 띄우지 않는다**(사용자 지적
    //    2026-08-30: "히스토리 탭 사양이 노출되고 있어요. 여기에 나타나면 안돼요").
    //    평클릭으로 선택되게 바꾸면서(`selectOnOpen`) 그림 한 장만 눌러도 저장/삭제
    //    버튼 줄이 통째로 튀어나왔다 - 레일은 그림을 훑는 자리지 조작판이 아니다.
    //    Ctrl/Shift/드래그로 **작정하고 고른 경우에만** 띄운다.
    // ⚠️ 삭제는 그대로 된다 - Del 은 `selectedPaths` 를 보지 바를 보지 않는다.
    //    무엇이 골라졌는지는 썸네일 테두리가 말한다.
    const deliberate = count > 0 && !selectionIsOnlyIncidental();
    if (viewerPanel) viewerPanel.classList.toggle('has-history-selection', deliberate);
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
      grid.focus({preventScroll: true});
      handleThumbClick(event, relPath, grid, openImage, options);
    };
  }

  function selectAllLoaded() {
    const paths = gridPaths(viewerGrid);
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

  async function saveSelectedAs(chosen = null) {
    const paths = Array.isArray(chosen) ? chosen : orderedSelectedPaths();
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

  async function saveSelected(chosen = null) {
    const paths = Array.isArray(chosen) ? chosen : orderedSelectedPaths();
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

  /** 고른 것 삭제. chosen = 합친 창(Output Search 이번 세션)이 넘기는 경로 목록 - 없으면 레일 · 팝업의 선택.
   *  @returns {Promise<string[]>} 실제로 히스토리에서 빠진 rel_path 들(취소 · 실패면 빈 목록). */
  async function deleteSelected(chosen = null) {
    const paths = Array.isArray(chosen) ? chosen : orderedSelectedPaths();
    if (!paths.length || selectionBusy) return [];
    // 뷰어 설정 판과 우클릭 메뉴가 쓰는 것과 **같은 키**다. 세 곳이 한 값을 본다.
    let deleteMode = 'history';
    try { deleteMode = localStorage.getItem(HISTORY_DELETE_MODE_KEY) === 'disk' ? 'disk' : 'history'; } catch (_) {}
    const modeText = deleteMode === 'disk'
      ? '연결된 저장 파일은 영구 삭제하지 않고 휴지통으로 이동합니다.'
      : '히스토리에서만 제거하며 저장 파일은 유지합니다.';
    // 저장 안 된 이미지가 섞였는지 센다 — **경고 문구를 고르는 데만** 쓴다.
    //
    // ⚠️ 예전에는 "저장 안 된 이미지는 지우면 끝" 이라 이 값이 '묻지 않기' 를
    //    무력화했다(Codex 리뷰 P1). 2026-08-30 부터 **그 전제가 사라졌다** —
    //    백엔드가 미저장분도 지우기 전에 휴지통에 한 벌 남긴다
    //    (`result_display_routes._rescue_unsaved_to_trash`). 사용자 지정:
    //    "디스크에 저장이 되었건 말건 그냥 딸깍 한 번으로 지우고 싶어한다."
    // ⚠️ 어느 항목이 미저장인지 화면은 정확히 알 수 없다(방금 생성한 것은 저장이
    //    아직 안 끝났을 수 있다). 그래서 전체 미저장 개수로 판단한다.
    const unsaved = Number(getUnsavedCount());
    const recoverable = unsaved === 0;
    // ⚠️ **미저장분이라고 더 물어보지 않는다**(사용자 지정 2026-08-30). 예전에는
    //    `|| !recoverable` 이 붙어 있어, '묻지 않기' 를 켜 놔도 저장 안 된 그림이
    //    섞이면 매번 다시 물었다 - 사용자가 원한 '딸깍 한 번' 이 그것 때문에 막혔다.
    //    이제 백엔드가 미저장분도 휴지통에 한 벌 남기므로(`_rescue_unsaved_to_trash`)
    //    "되돌릴 수 없다" 는 전제 자체가 없어졌다.
    let shouldAsk = false;
    if (!viewerBindings.skipDeleteConfirm() && !skipDeleteConfirmThisRun) {
      shouldAsk = true;
    }
    // ⚠️ 인페인트 세션 중에는 **무조건 묻는다**(사용자 지정 2026-10-05). 캔버스를 고치는 손이
    //    Del 에 가 있어서, '묻지 않기' 를 켜 둔 채로는 히스토리의 그림이 말없이 지워진다.
    //    위의 '묻지 않기' 둘을 모두 이긴다(미저장 여부로 가르지 않는다는 약속과는 별개다).
    let forceConfirm = false;
    try { forceConfirm = typeof mustConfirmDelete === 'function' && mustConfirmDelete() === true; }
    catch (_) { forceConfirm = false; }
    if (forceConfirm) shouldAsk = true;
    if (shouldAsk) {
      // ⚠️ 문구가 사실과 어긋나면 안 된다. 미저장분도 이제 휴지통을 거치므로
      //    "지우면 되돌릴 수 없습니다" 는 **거짓말**이 됐다.
      const warn = recoverable ? ''
        : (unsaved > 0
            ? `\n저장되지 않은 이미지 ${unsaved}장은 지우기 전에 휴지통으로 보냅니다.`
            : '\n저장되지 않은 이미지는 지우기 전에 휴지통으로 보냅니다.');
      const message = `${paths.length}개 선택 항목을 삭제할까요?\n${modeText}${warn}`;
      // 체크박스는 **늘** 준다. 저장 여부로 가르지 않는다(사용자 지정) -
      // 미저장분도 휴지통을 거치므로 되돌릴 수 있다.
      const askOnce = {label: '이번 실행 동안 물어보지 않습니다', checked: false};
      const confirmed = typeof confirmDialog === 'function'
        ? await confirmDialog(message, {
          title: '선택 항목 삭제',
          okText: `삭제 (${paths.length})`,
          cancelText: '취소',
          // 반드시 물어야 하는 자리에서는 '묻지 않기' 를 내밀지 않는다 - 켜도 안 먹는 약속이 된다.
          checkbox: forceConfirm ? null : askOnce,
        })
        : window.confirm(message);
      if (!confirmed) return [];
      // 확인을 누른 경우에만 켜진다(다이얼로그가 그때만 되적는다).
      if (askOnce.checked) skipDeleteConfirmThisRun = true;
    }

    setSelectionBusy(true);
    let succeeded = 0;
    let failed = 0;
    let unrescued = 0;
    const removedPaths = [];
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
        if (item.rel_path) removedPaths.push(item.rel_path);
        onRemoved(item);
      });
      succeeded = Number(data.deleted || removed.length || 0);
      failed = Array.isArray(data.failed) ? data.failed.length : 0;
      // ⚠️ 저장된 적 없는 그림은 지우기 전에 휴지통에 한 벌 남긴다. 그것이 **실패**하면
      //    사본이 어디에도 없는데, 예전에는 그대로 "성공" 이라고 말했다 - 묻지 않기를
      //    켜 둔 사용자에게는 경고 없는 영구 유실이었다(Codex BLOCK 5).
      //    지우는 것 자체는 막지 않는다(사용자가 원한 것이다). 다만 조용하지는 않다.
      unrescued = removed.filter(item => item && item.rescue_failed).length;
    } catch (error) {
      console.error('Selected history delete failed:', error);
      failed = paths.length;
    }
    if (!selectedPaths.size) selectionAnchorPath = '';
    setSelectionBusy(false);
    const level = failed || unrescued ? (succeeded ? 'warning' : 'error') : 'success';
    const note = unrescued ? ` · ${unrescued}개는 사본을 못 남겼습니다(복구 불가)` : '';
    showToast(`선택 삭제 완료: 성공 ${succeeded}개, 실패 ${failed}개${note}`, level);
    return removedPaths;
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

  /** 썸네일 칸의 **자리를 미리 잡는다**(가로세로 비율을 CSS 변수 `--thumb-ratio` 로).
   *
   *  데스크톱 레일의 썸네일은 그림의 제 비율로 선다(`aspect-ratio: auto` 였다) - 그래서 아직 안 불러온 `loading=lazy`
   *  썸네일은 **높이가 0** 이었다. 접어 둔 동안 쌓인 수백 장이 6px 간격으로 포개져 전부 '화면 안' 으로 읽혔고,
   *  펼치는 순간 한꺼번에 불러왔다(200장 상한일 때는 느려도 끝났다 - 무제한이 되면 1천 장 단위다: 사용자 지적
   *  2026-10-06). 자리가 있으면 보이는 것과 그 언저리만 불러오고 나머지는 스크롤할 때 온다.
   *   · 서버가 크기를 주면(width · height) 그 비율로 잡는다 - 불러온 뒤에도 자리가 그대로라 목록이 안 튄다.
   *   · 안 주면(옛 백엔드) CSS 의 기본 3 / 4 로 서고, 불러온 순간 그림의 제 비율로 고친다. */
  function reserveThumbBox(img, entry) {
    const setRatio = (w, h) => {
      if (w > 0 && h > 0) img.style.setProperty('--thumb-ratio', `${w} / ${h}`);
    };
    setRatio(Number(entry?.width) || 0, Number(entry?.height) || 0);
    img.addEventListener('load', () => setRatio(img.naturalWidth, img.naturalHeight), {once: true});
  }

  function appendThumb(relPath, entry = null) {
    if (!viewerGrid) return;
    const img = document.createElement('img');
    img.className = 'viewer-thumb';
    img.loading = 'lazy';
    img.dataset.path = relPath;
    reserveThumbBox(img, entry);
    img.src = historyAssetUrl(relPath, 'thumb');
    // 평클릭 한 번으로 **선택까지** 된다(사용자 요청 2026-08-30: "클릭 후 DELETE").
    // 예전에는 레일에서 평클릭이 선택을 **비우기만** 해서, 눌러 놓고 Del 을 눌러도
    // 아무 일도 안 일어났다(Ctrl/Shift/드래그로만 홀드가 생겼다).
    // ⚠️ 팝업 목록과 **같은 옵션**을 쓴다 - 그쪽이 이미 "딸려온 단일 선택" 을
    //    추적해(`incidentalSelectionPath`) 다른 그림으로 넘어가면 놓아준다.
    //    그 장치가 없으면 보고 있는 그림과 지워지는 그림이 갈린다.
    configureThumb(img, relPath, viewerGrid, () => thumbClick(relPath), {selectOnOpen: true});
    viewerGrid.appendChild(img);
  }

  function prependThumb(relPath, entry = null) {
    if (!viewerGrid) return;
    const img = document.createElement('img');
    img.className = 'viewer-thumb';
    img.loading = 'lazy';
    img.dataset.path = relPath;
    reserveThumbBox(img, entry);
    img.src = historyAssetUrl(relPath, 'thumb');
    configureThumb(img, relPath, viewerGrid, () => thumbClick(relPath), {selectOnOpen: true});
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
        appendThumb(entry.rel_path, entry);
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
    if (didPrepend) prependThumb(message.rel_path, message);

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
    viewerPendingNewCount = 0;
    promptFloatCache = {};
    promptFloatCacheKeys = [];
    if (viewerGrid) viewerGrid.innerHTML = '';
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

  // 레일의 ⚙ - 삭제 방식 · 저장 경로 · 숏컷(앱). History 창 머리의 ⚙ 도 같은 판을 연다.
  function bindRailSettings() {
    const btn = getEl('viewerRailSettings');
    if (!btn) return;
    btn.addEventListener('click', () => viewerBindings.togglePanel(btn));
  }

  // 마우스 보조 버튼(뒤로/앞으로/휠클릭) - 숏컷 입력을 받는 중일 때만 여기서 받는다.
  // 바인딩 실행은 History 창이 자기 그림으로 한다(sessionActions.dispatchMouseBinding).
  // 뒤로/앞으로는 브라우저가 방문 기록을 넘기려 하므로 `mousedown` 에서 미리 막는다.
  function bindShortcutInputs() {
    const AUX = new Set([1, 3, 4]);
    document.addEventListener('mousedown', event => {
      if (AUX.has(event.button) && viewerBindings.isCapturing()) event.preventDefault();
    });
    document.addEventListener('auxclick', event => {
      if (!AUX.has(event.button) || !viewerBindings.isCapturing()) return;
      event.preventDefault();
      viewerBindings.finishCapture(viewerBindings.inputIdFromMouse(event.button));
    });
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
      // 뷰어 설정(⚙)이 숏컷 입력을 기다린다 - 그 키는 설정 몫이다. Esc 는 설정 닫기.
      if (viewerBindings.isCapturing()) {
        event.preventDefault();
        if (event.key === 'Escape') viewerBindings.setPanelOpen(false);
        else viewerBindings.finishCapture(viewerBindings.inputIdFromKey(event));
        return;
      }

      const commandKey = Boolean(event.metaKey || event.ctrlKey);
      const key = String(event.key || '').toLowerCase();
      const activeElement = document.activeElement;
      const historyFocused = Boolean(
        selectedPaths.size
        || viewerPanel?.contains(activeElement)
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
      // ⚠️ **다른 화면이 Del 을 가져가면 히스토리는 손대지 않는다**(`deleteKeyGuard` 주석).
      //    선택이 있든 없든 먼저 묻는다 - 인페인트 편집 화면은 선택이 없어도 Del 로 레이어를 지운다.
      if (deleteKey && typeof deleteKeyGuard === 'function') {
        let claimed = false;
        try { claimed = deleteKeyGuard(event) === true; } catch (_) { claimed = false; }
        if (claimed) {
          event.preventDefault();
          return;
        }
      }
      if (deleteKey && selectedPaths.size) {
        event.preventDefault();
        deleteSelected();
        return;
      }
      // Esc - 고른 것을 비운다.
      if (event.key === 'Escape' && selectedPaths.size) {
        event.preventDefault();
        clearSelection();
        return;
      }

      if (viewerNavIdx < 0 || viewerNavPaths.length === 0) return;

      // 좌우는 한 장, 상하는 한 줄. 레일은 2열 고정이지만
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
    // **레일 격자에는 드래그 선택을 걸지 않는다**(사용자 지적 2026-08-08 - 좁은 레일에서 스크롤하려다
    // 여러 장이 골라진다). 개별 클릭만. 키보드 판정(`viewerPanel.contains(activeElement)`)을 위해
    // 격자가 초점을 받게만 해 둔다.
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
    onNewImage,
    onRemoved,
    onCleared,
    jumpToLatest,
    /** Ctrl+S 를 히스토리가 맡을 것인가. app.js 의 **단일 판정**이 부른다.
     *  document 리스너를 여기서 또 달면 `preventDefault()` 가 서로를 막지 못해
     *  둘 다 실행된다(파일 2개·토스트 2개). 고른 것이 있을 때만 참을 낸다.
     *  @returns {boolean} 우리가 처리했으면 true — 호출자가 기본동작을 막는다. */
    handleSaveShortcut() {
      if (!selectedPaths.size) return false;
      saveSelected();
      return true;
    },
    // ── History 창('이번 세션')이 쓰는 손 - 삭제 · 저장 규칙은 레일과 한 벌이다(11-22) ──
    sessionActions: {
      deletePaths: paths => deleteSelected(paths),
      quicksavePaths: paths => saveSelected(paths),
      saveAsPaths: paths => saveSelectedAs(paths),
      canSaveAs: () => hasNativeSavePicker(),
      // 메인 프리뷰에 띄운다 - Result Info · Enhance · Sequence 가 이 그림을 따라간다.
      showInMain: relPath => thumbClick(relPath),
      // Del 을 다른 화면(인페인트 캔버스)이 가져가는가 - 그러면 창은 아무것도 지우지 않는다.
      deleteKeyClaimed(event) {
        if (typeof deleteKeyGuard !== 'function') return false;
        try { return deleteKeyGuard(event) === true; } catch (_) { return false; }
      },
      deleteKeyDEnabled: () => viewerBindings.deleteKeyDEnabled(),
      // 숏컷 바인딩(앱 전용) - 이 키가 바인딩이면 보내고 true.
      dispatchBindingKey(event, relPath) {
        if (!relPath || viewerBindings.isCapturing()) return false;
        const inputId = viewerBindings.inputIdFromKey(event);
        if (!viewerBindings.hasBinding(inputId)) return false;
        viewerBindings.dispatch(inputId, relPath);
        return true;
      },
      loadBindings: () => viewerBindings.load(),
      isCapturing: () => viewerBindings.isCapturing(),
      // 마우스 보조 버튼(휠 클릭 · 뒤로 · 앞으로) - 바인딩이면 그 입력 이름, 아니면 ''.
      mouseBindingId(button) {
        if (viewerBindings.isCapturing()) return '';
        const inputId = viewerBindings.inputIdFromMouse(button);
        return viewerBindings.hasBinding(inputId) ? inputId : '';
      },
      dispatchMouseBinding(button, relPath) {
        if (!relPath || viewerBindings.isCapturing()) return false;
        const inputId = viewerBindings.inputIdFromMouse(button);
        if (!viewerBindings.hasBinding(inputId)) return false;
        viewerBindings.dispatch(inputId, relPath);
        return true;
      },
      // 히스토리 통째로 비우기 - 미저장 장수를 세어 경고하는 확인 창이 거기 붙어 있다.
      clearAll: () => { if (typeof clearAllHistory === 'function') clearAllHistory(); },
      toggleSettings: anchor => viewerBindings.togglePanel(anchor),
    },
    thumbClick,
    navViewer,
    hideNav,
    openFolder,
    // 저장 경로 상태가 도착하면 뷰어 설정 판의 한 줄을 갱신한다.
    onSaveDirectoryState: () => viewerBindings.refresh(),
    loadResultInfo,
    get latestImagePath() { return latestImagePath; },
    // Ctrl+S 빠른 저장이 "지금 보고 있는 것"을 알아야 한다. 아무것도 안 골랐으면 최신 이미지다.
    get currentImagePath() {
      // Ctrl+S 는 "보고 있는 것"을 저장한다. 그러므로 화면이 진실이다 —
      // currentViewerPath(탐색 상태)를 먼저 보면 두 방향으로 어긋난다:
      //   Esc 로 탐색만 해제하면 화면은 그대로인데 값이 비어 최신으로 폴백하고,
      //   탐색 중에 새 결과가 도착하면 화면은 새것인데 값은 옛 선택에 머문다.
      // preview.dataset 이 화면 상태를 정확히 담는다:
      //   히스토리 선택 -> source='saved', path=<rel_path>
      //   새 생성 결과 -> source='current', path=''  (곧 latestImagePath 가 채워진다)
      if (preview && preview.classList.contains('show')) {
        const shown = String(preview.dataset.path || '');
        if (shown) return shown;
        if (preview.dataset.source === 'current') return latestImagePath;
      }
      return currentViewerPath || latestImagePath;
    },
  };
}
