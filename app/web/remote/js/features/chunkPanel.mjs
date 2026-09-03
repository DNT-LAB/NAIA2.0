export function createChunkPanel({
  // 우클릭 [Add to Chunk] 를 받아 갈 새 청크 창(2026-09-03). 없으면 옛 Add 폼으로 떨어진다.
  onAddToChunkWindow,
  document,
  panel,
  moduleBody,
  modulePopup,
  promptEdit,
  getWs,
  WebSocket,
  getAcTarget,
  showToast,
  updateModuleBtnState,
  positionFloatingPanel,
  setModuleParam,
  onPromptEdit,
  fireModuleOninput,
  escHtml,
  onTagFilterAdd = null,
  onTagFilterState = null,
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
      <div class="result-context-group" data-requires-filter-tag="1" data-filter-slot></div>
      <div class="result-context-separator" data-requires-filter-tag="1"></div>
      <div class="result-context-group" data-requires-filter-tag="1" data-hide-slot></div>
      <div class="result-context-separator" data-requires-filter-tag="1"></div>
      <div class="result-context-group">
        <button class="result-context-item" type="button" data-action="undo"><span>Undo</span></button>
        <button class="result-context-item" type="button" data-action="redo"><span>Redo</span></button>
      </div>
      <div class="result-context-separator"></div>
      <div class="result-context-group">
        <button class="result-context-item" type="button" data-action="cut" data-requires-selection="1"><span>Cut</span></button>
        <button class="result-context-item" type="button" data-action="copy" data-requires-selection="1"><span>Copy</span></button>
        <button class="result-context-item" type="button" data-action="paste"><span>Paste</span></button>
        <button class="result-context-item" type="button" data-action="paste-plain"><span>Paste and match style</span></button>
        <button class="result-context-item" type="button" data-action="select-all"><span>Select all</span></button>
      </div>
      <div class="result-context-separator" data-requires-selection="1"></div>
      <div class="result-context-group" data-requires-selection="1">
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
      if (action === 'hide-auto' || action === 'hide-category') {
        const tag = (payload.filterTag || '').trim();
        if (!tag) {
          showToast('숨길 태그를 고르세요.', 'info');
        } else {
          // 붙이기는 백엔드가 한다 - 화면이 현재 값을 읽어 이어 붙이면 창이 둘일 때
          // 뒤에 도착한 쪽이 앞의 추가를 지운다. 토스트도 백엔드가 낸다.
          setModuleParam('prompt_engineering',
            action === 'hide-auto' ? 'auto_hide_add' : 'category_hide_add', tag);
        }
      } else if (action.startsWith('tagfilter-')) {
        // 본체는 호스트가 주입한다(quickFilter 는 app.js 가 소유). 여기서는 어느
        // 목록에 무엇을 넣을지만 넘긴다 - 필터 상태를 두 곳이 만지면 갈린다.
        const tag = (payload.filterTag || '').trim();
        if (!tag) {
          showToast('필터에 넣을 태그를 고르세요.', 'info');
        } else if (typeof onTagFilterAdd === 'function') {
          onTagFilterAdd(action.slice('tagfilter-'.length), tag);
        } else {
          showToast('Tag Filter 를 열 수 없습니다.', 'error');
        }
      } else if (action === 'add-chunk') {
        // ⚠️ **새 청크 창으로 보낸다**(사용자 지정 2026-09-03). 예전에는 이 패널을
        //    열어 자체 Add 폼을 채웠는데, 같은 일을 하는 화면이 둘이 됐다.
        //    팝업을 또 만들지 않고 이미 있는 창을 쓴다. 주입이 없으면 옛 길로 떨어진다.
        if (typeof onAddToChunkWindow === 'function') {
          onAddToChunkWindow(value);
        } else {
          pendingAddPrefill = { value, key };
          openPanel(getAnchor(target), false);
        }
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

  // Tag Filter 항목은 **그 태그가 지금 어디에 있는지**에 따라 달라진다
  // (사용자 사양 2026-08-31). 안 들어 있으면 추가 두 개, 들어 있으면 그 목록의
  // 제거 + 퍼펙트 매칭 토글만 낸다 - 이미 들어 있는데 "추가" 를 내면 눌러도
  // "이미 있습니다" 만 나온다.
  // 선택 문자열을 **필터에 넣을 태그 하나**로 만든다. 괄호가 이름의 일부인 태그
  // (`hakurei reimu (touhou)`)는 건드리지 않는다 - 짝이 맞으면 그대로 둔다.
  //
  // ⚠️ 커서 경로는 tagAssist 가 이미 걸러 준다(`raw.startsWith('#')` 면 null).
  //    **선택 경로에는 그 가드가 없다** - 표식을 드래그하면 `#랜덤프롬프트` 나
  //    `#특징:` 가 그대로 필터에 박혀 아무것도 안 맞는 칩이 되고 풀이 0 이 된다
  //    (실측 2026-08-31). 여러 태그를 걸쳐 끌면 `black skin, colored skin` 이
  //    통째로 한 태그가 됐다 - 첫 태그만 쓰고, 무엇이 들어가는지 라벨로 보여 준다.
  function stripTagWeight(raw) {
    let value = String(raw || '').trim();
    if (!value) return '';
    // 여러 태그를 걸친 선택: 첫 조각만.
    if (value.includes(',')) {
      value = (value.split(',').map(part => part.trim()).find(Boolean) || '');
      if (!value) return '';
    }
    // 주석 표식은 태그가 아니다.
    if (value.startsWith('#')) return '';
    // NAI: `0.8::tag ::`
    while (value.endsWith('::')) value = value.slice(0, -2).trimEnd();
    const sep = value.indexOf('::');
    if (sep > 0 && !Number.isNaN(Number(value.slice(0, sep).trim()))) {
      value = value.slice(sep + 2).trimStart();
    }
    // WEBUI/ComfyUI: `(tag:1.2)`
    const weighted = value.match(/^\((.*):\s*-?\d+(?:\.\d+)?\)$/);
    if (weighted) value = weighted[1].trim();
    // e621 그룹 괄호는 짝이 안 맞을 때만 벗긴다.
    while (value.startsWith('(') && (value.split('(').length > value.split(')').length)) {
      value = value.slice(1).trimStart();
    }
    let closedGroup = false;
    while (value.endsWith(')') && (value.split(')').length > value.split('(').length)) {
      value = value.slice(0, -1).trimEnd();
      closedGroup = true;
    }
    // ⚠️ e621 은 그룹의 **마지막 태그**에 `:<가중치>)` 를 붙인다. 닫는 괄호만 떼면
    //    `panting:0.8` 이 남아 실제 `panting` 과 안 맞는다(Codex 지적, 실측 확인).
    //    그룹을 실제로 닫았을 때만 벗긴다 - 아무 태그에서나 `:숫자` 를 떼면
    //    이름에 콜론이 든 정상 태그를 망가뜨린다.
    if (closedGroup) value = value.replace(/:\s*-?\d+(?:\.\d+)?$/, '').trimEnd();

    // ⚠️ non-NAI 는 리터럴 괄호를 이스케이프해 둔다. 커서 경로는 tagAssist 가 이미
    //    되돌려 주는데 **선택 경로에는 그 단계가 없어**, 드래그하면
    //    `hakurei reimu \(touhou\)` 가 그대로 필터에 박혔다(백엔드도 백슬래시를
    //    보존한다). 괄호를 다 정리한 **뒤에** 되돌린다.
    value = value.replace(/\\([()])/g, '$1');

    value = value.trim();
    return value.startsWith('#') ? '' : value;
  }

  function renderFilterItems(menu, tag) {
    const slot = menu.querySelector('[data-filter-slot]');
    if (!slot) return;
    if (!tag) { slot.innerHTML = ''; return; }
    const found = typeof onTagFilterState === 'function' ? onTagFilterState(tag) : null;
    const label = value => `<span class="result-context-tag">${escHtml(value)}</span>`;
    const item = (action, html, extraClass = '') =>
      `<button class="result-context-item chunk-context-tagfilter${extraClass}" type="button"`
      + ` data-action="${action}"><span>${html}</span>${label(tag)}</button>`;

    if (!found) {
      slot.innerHTML = item('tagfilter-include', 'Tag Filter <b>[포함]</b> 에 추가')
        // 제외는 빨간 글씨(사용자 사양) - 푸는 쪽과 거르는 쪽을 색으로 가른다.
        + item('tagfilter-exclude', 'Tag Filter <b>[제외]</b> 에 추가', ' is-exclude');
      return;
    }
    const name = found.list === 'exclude' ? '[제외]' : '[포함]';
    const tone = found.list === 'exclude' ? ' is-exclude' : '';
    slot.innerHTML = item('tagfilter-remove', `Tag Filter <b>${name}</b> 에서 제거`, tone)
      + (found.exact
        ? item('tagfilter-exact-off', `<b>${name}</b> 퍼펙트 매칭 취소`, tone)
        : item('tagfilter-exact-on', `<b>${name}</b> 퍼펙트 매칭 적용`, tone));
  }

  // ── 자동 숨김(사용자 지정 2026-08-31) ────────────────────────────────
  //
  // **Auto-Hide 는 언제나 열려 있다**(사양 변경 2026-08-31). Tag Index 는 NAIA 가
  // 수록했는지일 뿐이라, 실재하지만 미수록인 태그(`full page comic` 등)를 막으면
  // 그것들을 숨길 방법이 아예 없어진다.
  //
  // 랜덤 프롬프트 항목만 조회로 가른다 - 개별 그룹에 속해야 그 이름을 지을 수 있고,
  // 어느 그룹에도 없으면 랜덤 프롬프트로 나오지 않아 숨길 자리가 없다.
  // 넣는 것은 **고른 태그 그대로**, 묶음 문법 없이.
  const classifyCache = new Map();

  async function classifyTag(tag) {
    if (classifyCache.has(tag)) return classifyCache.get(tag);
    let result = null;
    try {
      const res = await fetch(
        `/api/prompt-engineering/classify-tag?tag=${encodeURIComponent(tag)}`,
        { headers: { Accept: 'application/json' } });
      if (res.ok) result = await res.json();
    } catch (_error) { result = null; }
    // 조회 실패는 캐시하지 않는다 - 한 번 끊겼다고 그 태그를 영영 못 숨기면 안 된다.
    if (result) classifyCache.set(tag, result);
    return result;
  }

  function hideItemHtml(action, inner, {disabled = false, tag = ''} = {}) {
    const attrs = [
      `class='result-context-item chunk-context-hide'`,
      `type='button'`,
      `data-action='${action}'`,
      disabled ? 'disabled' : '',
    ].filter(Boolean).join(' ');
    // 대상 태그를 오른쪽에 옅게 붙여 무엇이 들어가는지 눈으로 확인시킨다(Tag Filter 와 동일).
    const tail = tag ? `<span class='result-context-tag'>${escHtml(tag)}</span>` : '';
    return `<button ${attrs}><span>${inner}</span>${tail}</button>`;
  }

  // 응답을 기다리는 동안에도 **줄 수가 변하지 않게** 두 줄을 먼저 막아 둔 채 그린다
  // - 메뉴가 뒤늦게 커지면 사용자가 엉뚱한 항목을 누른다.
  function renderHideItems(menu, tag) {
    const slot = menu.querySelector('[data-hide-slot]');
    if (!slot) return;
    if (!tag) { slot.innerHTML = ''; return; }
    const paint = label => {
      slot.innerHTML =
        hideItemHtml('hide-auto', '자동 숨김 <b>(Auto-hide 에 추가)</b>', {tag})
        + hideItemHtml('hide-category',
          `자동 숨김 <b>(랜덤 프롬프트 - ${escHtml(label || '없음')})</b>`,
          {tag, disabled: !label});
    };
    paint('');
    classifyTag(tag).then(info => {
      // 늦게 온 응답이 다음 태그의 메뉴를 덮지 않게 한다.
      if (!selectionMenuPayload || selectionMenuPayload.filterTag !== tag) return;
      paint((info && info.known && info.label) || '');
    });
  }
  function showSelectionMenu(target, event, extra = {}) {
    // 선택이 없어도 메뉴를 띄운다(데스크톱 마우스 우클릭) — 선택 의존 항목
    // (Cut/Copy/Add to Chunk)은 no-selection 클래스로 숨긴다. 모바일 롱프레스는
    // 호출부(tagAssist의 shouldUseNativeTextContextMenu)가 이미 네이티브로 보낸다.
    if (!target || !event) return false;
    const selection = getSelectionText(target);
    selectionMenuPayload = {
      target,
      value: selection || '',
      key: selection ? suggestKeyFromValue(selection) : '',
      // Tag Filter 항목이 쓸 대상: **선택이 있으면 선택, 없으면 커서 밑 태그**
      // (사용자 지정 2026-08-31). 둘 다 없으면 그 항목만 흐려진다.
      //
      // ⚠️ 선택은 사용자가 끈 그대로라 가중치가 딸려 온다 - `0.8::open clothes ::`
      //    를 그대로 넣으면 `0.8::open_clothes_::` 라는 없는 태그가 필터에 박힌다
      //    (백엔드도 가중치를 안 벗긴다). 커서 경로는 tagAssist 가 이미 벗겨서 준다.
      filterTag: stripTagWeight(selection || extra.tagAtCursor || ''),
    };
    const menu = ensureSelectionMenu();
    menu.classList.toggle('no-selection', !selection);
    menu.classList.toggle('no-filter-tag', !selectionMenuPayload.filterTag);
    renderFilterItems(menu, selectionMenuPayload.filterTag);
    renderHideItems(menu, selectionMenuPayload.filterTag);
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
