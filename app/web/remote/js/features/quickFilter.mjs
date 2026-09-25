import { RATING_KEYS, filteredCount } from './ratingStore.mjs';

const STORAGE_KEY = 'naia_quick_filter_options';
const DEFAULT_RATING_KEYS = ['g', 's', 'q'];
const SEARCH_DEBOUNCE_MS = 280;

// 분기 스테이징 목록(계획서 P3) - Tag Filter 층의 칩 아래. 크기는 창의 컴팩트 톤에 맞춘다.
const TFB_CSS = `
.tfb{display:flex;flex-direction:column;gap:4px}
.tfb-head{display:flex;align-items:center;gap:6px;min-width:0}
.tfb-stage{flex:0 0 auto;height:22px;padding:0 9px;border-radius:5px;font-size:10.5px;font-weight:700;cursor:pointer;
  border:1px solid rgba(141,123,214,0.6);background:rgba(141,123,214,0.16);color:#d9d0ff}
.tfb-stage:hover:not(:disabled){background:rgba(141,123,214,0.30);color:#fff}
.tfb-stage:disabled{opacity:.4;cursor:default}
.tfb-hint{flex:1 1 auto;min-width:0;font-size:9.5px;color:var(--text-dimmer,#6c6c78);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tfb-list{display:flex;flex-direction:column;gap:2px;padding:4px;border-radius:6px;background:rgba(0,0,0,0.22);
  border:1px solid rgba(141,123,214,0.25)}
.tfb-row{display:flex;align-items:center;gap:6px;min-height:22px;padding:2px 4px;border-radius:4px;font-size:10.5px}
.tfb-row:hover{background:rgba(255,255,255,0.04)}
.tfb-row.is-off .tfb-text{opacity:.4;text-decoration:line-through}
.tfb-row.is-live{border-top:1px dashed rgba(141,123,214,0.3);border-radius:0 0 4px 4px}
.tfb-on{flex:0 0 auto;width:12px;height:12px;padding:0;border-radius:50%;cursor:pointer;
  border:1px solid rgba(141,123,214,0.8);background:rgba(141,123,214,0.85)}
.tfb-on[aria-pressed="false"]{background:transparent}
.tfb-on.is-live{cursor:default;background:transparent;border-style:dashed}
.tfb-text{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary,#c8c8d0)}
.tfb-text em{font-style:normal;font-size:9.5px;color:#b9aef0}
.tfb-base{color:var(--text-dimmer,#6c6c78)}
.tfb-own{color:var(--text-primary,#e8e8ee)}
.tfb-x,.tfb-x .tfb-own{color:#e39a9a}
.tfb-n{flex:0 0 auto;font-family:var(--font-mono,monospace);font-size:10px;color:#f5dc8a;font-variant-numeric:tabular-nums}
.tfb-del{flex:0 0 14px;border:none;background:transparent;color:var(--text-dimmer,#6c6c78);cursor:pointer;font-size:13px;line-height:1;padding:0}
.tfb-del:hover{color:#f0a0a0}
.tag-filter-chip.is-pinned::before{content:'📌';font-size:9px;margin-right:2px}
.tag-filter-chip.is-pinned{border-color:rgba(245,220,138,0.65)}
`;

function normalizeTagParts(value) {
  const text = String(value || '');
  return text.split(/[,\n]/)
    .map(item => item.replace(/_/g, ' ').trim().replace(/^-+/, '').replace(/ /g, '_'))
    .filter(Boolean);
}

// 선행 `*` = 퍼펙트 매칭. SEARCH 의 `*tag` 와 같은 표기이고, 칩은 그냥 문자열이라
// 저장 스키마(localStorage · 상태 파일 · 프리셋 · WS)를 하나도 안 바꾼다.
// ⚠️ 예약 문자다 - 태그 사전 150개 parquet 전수에 `*` 를 포함한 실제 태그는 0개다.
const isExactTag = (tag) => String(tag || '').startsWith('*');
const baseTag = (tag) => String(tag || '').replace(/^\*+/, '');
const withExact = (tag, exact) => (exact ? '*' : '') + baseTag(tag);

export function normalizeRatings(value) {
  if (!Array.isArray(value)) return [...DEFAULT_RATING_KEYS];
  const picked = RATING_KEYS.filter(key => value.includes(key));
  return picked.length ? picked : [...DEFAULT_RATING_KEYS];
}

export function normalizeTags(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  const out = [];
  value.forEach(item => {
    normalizeTagParts(item).forEach(tag => {
      if (seen.has(tag)) return;
      seen.add(tag);
      out.push(tag);
    });
  });
  return out;
}

// 칩 토큰 = 칩 문법 그대로(`-제외` · `*정확` · 밑줄) - 분기와 고정 목록이 쓴다.
export function normalizeTokens(value) {
  if (!Array.isArray(value)) return [];
  const out = [];
  value.forEach(item => {
    const token = String(item || '').trim();
    if (token && !out.includes(token)) out.push(token);
  });
  return out;
}

// 분기 스테이징(계획서 P3): [{tags:[칩 토큰], enabled}]. 빈 분기는 버린다.
export function normalizeBranches(value) {
  if (!Array.isArray(value)) return [];
  return value.map(item => {
    const tags = normalizeTokens(item && typeof item === 'object' && !Array.isArray(item) ? item.tags : item);
    return {tags, enabled: !(item && item.enabled === false)};
  }).filter(branch => branch.tags.length).slice(0, 16);
}

export function normalizePreferences(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const include = normalizeTags(raw.tag_filter || raw.include || raw.include_tags);
  const exclude = normalizeTags(raw.tag_filter_exclude || raw.exclude || raw.exclude_tags);
  const branches = normalizeBranches(raw.tag_filter_branches);
  return {
    ratings: normalizeRatings(raw.ratings),
    tag_filter: include,
    tag_filter_exclude: exclude,
    tag_filter_branches: branches,
    tag_filter_pinned: normalizeTokens(raw.tag_filter_pinned),
    tag_filter_active: !!raw.tag_filter_active
      && (include.length > 0 || exclude.length > 0 || branches.some(branch => branch.enabled)),
  };
}

export function hasCustomPreferences(pref) {
  if (!pref) return false;
  const ratings = normalizeRatings(pref.ratings);
  const defaultRatings = ratings.length === DEFAULT_RATING_KEYS.length
    && DEFAULT_RATING_KEYS.every(key => ratings.includes(key));
  return !defaultRatings
    || (pref.tag_filter && pref.tag_filter.length > 0)
    || (pref.tag_filter_exclude && pref.tag_filter_exclude.length > 0)
    || (pref.tag_filter_branches && pref.tag_filter_branches.length > 0)
    || !!pref.tag_filter_active;
}

export function loadPreferences(storage = localStorage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    return raw ? normalizePreferences(JSON.parse(raw)) : null;
  } catch (_) {
    return null;
  }
}

export function savePreferences(pref, storage = localStorage) {
  try {
    if (hasCustomPreferences(pref)) {
      storage.setItem(STORAGE_KEY, JSON.stringify(pref));
    } else {
      storage.removeItem(STORAGE_KEY);
    }
  } catch (_) {}
}

export function createQuickFilterController(deps) {
  const doc = deps.document;
  const storage = deps.localStorage;
  const SocketClass = deps.WebSocket;

  let includeTags = [];
  let excludeTags = [];
  let active = false;
  // 필터가 실제로 적용(assign)된 적이 있는지 — green 검색이 백엔드에서 active 를 끄면
  // applyPreferences 가 active=false 로 만들어 onSearchReleased 시점엔 active 를 못 믿는다.
  // '해제됨' 오버레이는 진짜 적용됐던 필터에만 띄우고, 미적용 draft 칩(280ms 디바운스 중)엔
  // 안 띄우기 위한 별도 플래그(Codex MED). onAssigned 에서 set, clear/reset 에서 unset.
  let filterWasApplied = false;
  let acResults = [];
  let acSelection = -1;
  let acTimer = null;
  let pendingAssignOnRestore = false;
  let ratingCounts = null;
  let acTarget = 'include';
  let searchSeq = 0;
  let latestSearchRequestId = '';
  let latestTagFilterRevision = 0;
  let searchDebounceTimer = null;
  let latestAcRequest = {target: '', query: ''};
  // 분기 스테이징(계획서 P3). 결과 = 켜진 분기들 ∪ (작업 중 칩 - 고정 아닌 칩이 있을 때).
  let stagedBranches = [];            // [{tags:[칩 토큰], enabled}]
  let pinnedTokens = [];              // 기준으로 고정한 칩 토큰 - [분기로 담기] 가 비우지 않는다
  let lastSentBranches = [];          // 마지막 검색에 보낸 분기(결과의 분기별 수와 순서가 같다)
  const branchCounts = new Map();     // 분기 서명 -> 등급별 수(마지막 결과)

  const getEl = id => doc.getElementById(id);
  // Tag Filter 가 사는 곳. 리모컨 창(searchQuickWindow)이 주입하면 그걸 묻고, 없으면 예전 고정 팝업.
  // ⚠️ 창으로 옮긴 뒤엔 #tagFilterPopup 껍데기가 영영 'open' 이 안 된다 - 팝업만 보면 자동완성과
  //    카운트 갱신이 조용히 죽는다.
  const surface = () => (typeof deps.tagSurface === 'function' ? deps.tagSurface() : null);
  function popupOpen() {
    const s = surface();
    if (s) return !!s.isOpen();
    const popup = getEl('tagFilterPopup');
    return !!popup && popup.classList.contains('open');
  }
  function surfaceVisible() {
    const s = surface();
    if (s && typeof s.isWindowOpen === 'function') return !!s.isWindowOpen();
    return popupOpen();
  }
  const isSocketOpen = () => {
    const socket = deps.getWs();
    return socket && socket.readyState === SocketClass.OPEN;
  };
  const send = payload => {
    if (!isSocketOpen()) return;
    deps.getWs().send(JSON.stringify(payload));
  };
  const lockTagSurface = typeof deps.lockTagSurface === 'function' ? deps.lockTagSurface : () => {};
  const unlockTagSurface = typeof deps.unlockTagSurface === 'function' ? deps.unlockTagSurface : () => {};
  const getActiveRatings = () => {
    const ratingState = deps.getRatingState();
    return RATING_KEYS.filter(key => ratingState[key]);
  };
  const setActiveRatings = ratings => {
    // Write through the shared rating store (via the panel bridge) instead of
    // mutating searchPanel's rating object by reference.
    deps.setActiveRatings(normalizeRatings(ratings));
  };
  const payload = () => [...includeTags, ...excludeTags.map(tag => '-' + tag)];
  const tokenOf = (list, tag) => (list === 'exclude' ? '-' : '') + tag;
  const branchSig = tags => JSON.stringify(tags);
  const hasUnpinnedChips = () => payload().some(token => !pinnedTokens.includes(token));
  const enabledBranches = () => stagedBranches.filter(branch => branch.enabled);
  /** 검색에 보낼 분기. 켜진 분기가 없으면 [] = 예전처럼 칩 한 벌. 작업 중 칩은 고정 아닌 칩이
   *  있을 때만 한 분기로 더한다 - 고정 칩만 남은 상태(분기를 담은 직후)를 분기로 넣으면 그것이
   *  모든 분기를 품는 상위 집합이라 합집합이 기준 전체가 된다. */
  function branchesPayload() {
    const on = enabledBranches().map(branch => [...branch.tags]);
    if (!on.length) return [];
    if (hasUnpinnedChips()) on.push(payload());
    return on;
  }
  const hasFilter = () => includeTags.length > 0 || excludeTags.length > 0 || enabledBranches().length > 0;
  const nextSearchRequestId = () => {
    searchSeq += 1;
    latestSearchRequestId = `tf-${Date.now()}-${searchSeq}`;
    return latestSearchRequestId;
  };
  const invalidateSearchRequest = () => {
    searchSeq += 1;
    latestSearchRequestId = '';
  };
  const collectPreferences = () => ({
    ratings: getActiveRatings(),
    tag_filter: [...includeTags],
    tag_filter_exclude: [...excludeTags],
    tag_filter_branches: stagedBranches.map(branch => ({tags: [...branch.tags], enabled: branch.enabled})),
    tag_filter_pinned: [...pinnedTokens],
    tag_filter_active: active,
  });
  const tagInputIds = ['tagFilterInput', 'tagFilterExcludeInput'];
  const focusedTagInput = () => {
    const activeElement = doc.activeElement;
    if (!activeElement || !tagInputIds.includes(activeElement.id)) return null;
    return activeElement;
  };
  const captureFocusedInputState = () => {
    const input = focusedTagInput();
    if (!input) return null;
    return {
      id: input.id,
      value: input.value,
      selectionStart: input.selectionStart,
      selectionEnd: input.selectionEnd,
      acResults: [...acResults],
      acSelection,
    };
  };
  const restoreFocusedInputState = state => {
    if (!state) return;
    const input = getEl(state.id);
    if (!input) return;
    input.value = state.value;
    input.focus();
    try {
      input.setSelectionRange(state.selectionStart, state.selectionEnd);
    } catch (_) {}
    acResults = state.acResults;
    acSelection = state.acSelection;
    renderAutocomplete();
  };

  function updateHighlight() {
    const toggleBtn = getEl('tagFilterToggle');
    if (!toggleBtn) return;
    const control = toggleBtn.closest('.prompt-quick-control');
    const highlighted = hasCustomPreferences(collectPreferences());
    if (control) control.classList.toggle('quick-filter-memory', highlighted);
    toggleBtn.title = highlighted
      ? 'Quick filter settings are saved'
      : 'Open quick filter';
  }

  // RATING 옆 매치 카운트 라벨. 캐시된 per-rating counts + 현재 활성 등급으로 즉시 재계산하므로
  // G/S/Q/E 토글에 라이브로 반응하고, search_state reconcile 때도 사라지지 않는다(칩이 있는 한 유지).
  function renderMatchedCount(label = 'matched') {
    renderBranches();
    const countEl = getEl('tagFilterCount');
    if (!countEl) return;
    const hasTags = hasFilter();
    if (!hasTags) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
      return;
    }
    // 아직 카운트가 없으면(검색 응답 전) 기존 표시를 건드리지 않는다 — 깜빡임/공백 방지.
    if (!ratingCounts || !Object.keys(ratingCounts).length) return;
    const matched = filteredCount(ratingCounts, deps.getRatingState()) || 0;
    if (matched > 0) {
      countEl.textContent = `${matched.toLocaleString()} ${label}`;
      countEl.classList.add('has-result');
    } else {
      countEl.textContent = 'No matches';
      countEl.classList.remove('has-result');
    }
  }

  // 외부(검색 패널 등급 토글)에서 호출 — 팝업이 열려 있고 칩이 있으면 매치 카운트를 다시 계산한다.
  function refreshCount() {
    // 창이 열려 있으면 층이 접혀 있어도 센다 - 층 머리줄에 개수가 비친다.
    if (!surfaceVisible()) return;
    renderMatchedCount(active ? 'assigned' : 'matched');
  }

  function save() {
    const preferences = collectPreferences();
    savePreferences(preferences, storage);
    updateHighlight();
    send({type: 'save_search_filter_state', ...preferences});
  }

  function updateCommitButton() {
    const button = getEl('tagFilterCommitBtn');
    if (!button) return;
    const hasPendingText = tagInputIds.some(id => {
      const input = getEl(id);
      return input && input.value.trim();
    });
    // ⚠️ 예전에는 **입력칸에 글자가 있을 때만** 눌렸다. 그래서 칩이 걸려 있어도
    //    입력칸이 비면 Commit 이 죽었고, 랜덤 풀이 소진돼 "No matches" 가 된 뒤에는
    //    사용자가 칩을 넣거나 빼기 전까지 **재검색할 길이 아예 없었다**
    //    (사용자 제보 2026-08-31 - 치명적이라고 짚은 그 파생 버그).
    //    같은 칩으로 다시 거는 것은 정당한 동작이다 - 걸 것이 있으면 누를 수 있다.
    const hasChips = hasFilter();
    button.disabled = !(hasPendingText || hasChips);
  }

  function load() {
    return loadPreferences(storage);
  }

  // 칩을 누르면 아래에 서브메뉴가 하나 열린다(사용자 지정). 버튼을 칩에 상시로 두면
  // 칩 폭이 커져서, 누를 때만 내놓는다. 퍼펙트 매칭이 걸린 칩은 파랗게 강조된다.
  let chipMenu = null;          // {list:'include'|'exclude', index:number} | null

  function chipHtml(tag, index, list) {
    const exact = isExactTag(tag);
    const pinned = pinnedTokens.includes(tokenOf(list, tag));
    const open = !!chipMenu && chipMenu.list === list && chipMenu.index === index;
    const remover = list === 'exclude' ? 'removeTagFilterExcludeTag' : 'removeTagFilterTag';
    // ⚠️ × 는 칩 **안**에 있어 클릭이 칩으로 올라간다 - 멈추지 않으면 지우면서 메뉴가 열린다.
    return `<span class="tag-filter-chip${list === 'exclude' ? ' exclude' : ''}`
      + `${exact ? ' is-exact' : ''}${pinned ? ' is-pinned' : ''}${open ? ' menu-open' : ''}"`
      + ` role="button" tabindex="0" aria-expanded="${open ? 'true' : 'false'}"`
      + ` onclick="toggleTagFilterChipMenu('${list}',${index})"`
      // ⚠️ `event.target===this` 가 필수다. 메뉴 <button> 이 칩 **안**에 있어서 거기서
      //    난 Enter/Space 가 여기로 올라오는데, 그때 preventDefault 를 걸면 버튼의
      //    기본 활성화(=click)가 취소돼 **키보드로는 적용/해제를 못 한다**(Codex 지적).
      + ` onkeydown="if(event.target===this&&(event.key==='Enter'||event.key===' ')){`
      + `event.preventDefault();toggleTagFilterChipMenu('${list}',${index});}">`
      + deps.escHtml(tag)
      + `<span class="chip-x" onclick="event.stopPropagation();${remover}(${index})">&times;</span>`
      + (open
          ? `<span class="chip-menu" onclick="event.stopPropagation()">`
            + `<button type="button" class="chip-menu-btn"`
            + ` onclick="setTagFilterChipExact('${list}',${index},${exact ? 'false' : 'true'})">`
            + `${exact ? '퍼펙트 매칭 해제' : '퍼펙트 매칭 적용'}</button>`
            // 기준 고정(계획서 P3): [분기로 담기] 가 이 칩은 남긴다.
            + `<button type="button" class="chip-menu-btn"`
            + ` onclick="setTagFilterChipPinned('${list}',${index},${pinned ? 'false' : 'true'})">`
            + `${pinned ? '📌 기준 고정 해제' : '📌 기준으로 고정'}</button></span>`
          : '')
      + `</span>`;
  }

  function renderIncludeChips() {
    const el = getEl('tagFilterChips');
    if (!el) return;
    el.innerHTML = includeTags.length
      ? includeTags.map((tag, index) => chipHtml(tag, index, 'include')).join('')
      : '';
  }

  function renderExcludeChips() {
    const el = getEl('tagFilterExcludeChips');
    if (!el) return;
    el.innerHTML = excludeTags.length
      ? excludeTags.map((tag, index) => chipHtml(tag, index, 'exclude')).join('')
      : '';
  }

  function renderChips() {
    renderIncludeChips();
    renderExcludeChips();
  }

  // 바깥 클릭 / Escape 로 닫는다.
  // ⚠️ **캡처 단계**로 듣는다 - 중간에서 전파를 멈추는 코드가 있어도 도달한다.
  //    대신 칩 안에서 시작한 것은 무시해야 한다(닫자마자 그 칩의 click 이 다시 여는 꼴).
  function onChipMenuDismiss(event) {
    if (event.type === 'keydown') {
      if (event.key === 'Escape') closeChipMenu();
      return;
    }
    if (event.target && event.target.closest && event.target.closest('.tag-filter-chip')) return;
    closeChipMenu();
  }

  function bindChipMenuDismiss(on) {
    const fn = on ? 'addEventListener' : 'removeEventListener';
    document[fn]('pointerdown', onChipMenuDismiss, true);
    document[fn]('keydown', onChipMenuDismiss, true);
  }

  function closeChipMenu() {
    if (!chipMenu) return;
    chipMenu = null;
    bindChipMenuDismiss(false);
    renderChips();
  }

  function toggleChipMenu(list, index) {
    const same = chipMenu && chipMenu.list === list && chipMenu.index === index;
    if (same) { closeChipMenu(); return; }
    if (!chipMenu) bindChipMenuDismiss(true);
    chipMenu = {list: String(list) === 'exclude' ? 'exclude' : 'include', index: Number(index)};
    renderChips();
  }

  function setChipExact(list, index, exact) {
    const arr = String(list) === 'exclude' ? excludeTags : includeTags;
    const idx = Number(index);
    const current = arr[idx];
    closeChipMenu();
    if (current === undefined) return;
    const next = withExact(current, !!exact);
    if (next === current) return;
    // 같은 칩이 이미 있으면 **합친다**. `sky` 와 `*sky` 가 나란히 있으면 AND 라 결과는
    // `*sky` 와 같지만 화면이 헷갈린다.
    const duplicate = arr.some((tag, i) => i !== idx && tag === next);
    const listName = String(list) === 'exclude' ? 'exclude' : 'include';
    const wasPinned = pinnedTokens.includes(tokenOf(listName, current));
    unpin(tokenOf(listName, current));
    if (duplicate) arr.splice(idx, 1);
    else arr[idx] = next;
    if (wasPinned) pinnedTokens.push(tokenOf(listName, next));
    renderChips();
    updateCommitButton();
    apply();
  }

  function unpin(token) {
    pinnedTokens = pinnedTokens.filter(t => t !== token);
  }

  function setChipPinned(list, index, pinned) {
    const listName = String(list) === 'exclude' ? 'exclude' : 'include';
    const tag = (listName === 'exclude' ? excludeTags : includeTags)[Number(index)];
    closeChipMenu();
    if (tag === undefined) return;
    const token = tokenOf(listName, tag);
    unpin(token);
    if (pinned) pinnedTokens.push(token);
    renderChips();
    renderBranches();
    save();
    // 고정만 바꾸면 결과가 바뀌는 것은 '작업 중 분기' 가 더해지거나 빠질 때다.
    if (enabledBranches().length) apply();
  }

  /** [분기로 담기]: 지금 칩을 분기 하나로 담고, 고정 아닌 칩만 비운다(기준을 다시 치지 않게). */
  function stageBranch() {
    commitPendingInputs();
    if (!hasUnpinnedChips()) {
      deps.showToast('분기로 담을 칩이 없습니다 — 기준(📌) 말고 이 분기만의 칩을 넣으세요', 'warning');
      return;
    }
    const tags = payload();
    if (stagedBranches.some(branch => branchSig(branch.tags) === branchSig(tags))) {
      deps.showToast('같은 분기가 이미 담겨 있습니다', 'warning');
      return;
    }
    if (stagedBranches.length >= 16) {
      deps.showToast('분기는 16개까지 담을 수 있습니다', 'warning');
      return;
    }
    stagedBranches.push({tags, enabled: true});
    closeChipMenu();
    includeTags = includeTags.filter(tag => pinnedTokens.includes(tokenOf('include', tag)));
    excludeTags = excludeTags.filter(tag => pinnedTokens.includes(tokenOf('exclude', tag)));
    renderChips();
    renderBranches();
    updateCommitButton();
    apply();
    getEl('tagFilterInput')?.focus();
  }

  function setBranchEnabled(index, enabled) {
    const branch = stagedBranches[Number(index)];
    if (!branch) return;
    branch.enabled = !!enabled;
    renderBranches();
    if (!hasFilter()) { clearFilter(); return; }
    apply();
  }

  function removeBranch(index) {
    stagedBranches.splice(Number(index), 1);
    renderBranches();
    if (!hasFilter()) { clearFilter(); return; }
    apply();
  }

  function ensureBranchStyle() {
    if (doc.getElementById('tfb-style')) return;
    const style = doc.createElement('style');
    style.id = 'tfb-style';
    style.textContent = TFB_CSS;
    doc.head.appendChild(style);
  }

  function ensureBranchHost() {
    let host = getEl('tagFilterBranches');
    if (host) return host;
    const anchor = getEl('tagFilterExcludeChips');
    if (!anchor || !anchor.parentNode) return null;
    ensureBranchStyle();
    host = doc.createElement('div');
    host.id = 'tagFilterBranches';
    host.className = 'tfb';
    anchor.parentNode.insertBefore(host, anchor.nextSibling);
    // 다시 그려도 그대로인 뿌리에 위임으로 받는다.
    host.addEventListener('click', event => {
      const target = event.target.closest('[data-tfb]');
      if (!target) return;
      const index = Number(target.closest('[data-tfb-i]')?.dataset.tfbI);
      const action = target.dataset.tfb;
      if (action === 'stage') stageBranch();
      else if (action === 'toggle') setBranchEnabled(index, !stagedBranches[index]?.enabled);
      else if (action === 'remove') removeBranch(index);
    });
    return host;
  }

  function branchCountText(tags) {
    const counts = branchCounts.get(branchSig(tags));
    if (!counts) return '…';
    return (filteredCount(counts, deps.getRatingState()) || 0).toLocaleString();
  }

  function branchLabelHtml(tags) {
    const esc = deps.escHtml;
    const show = token => esc(baseTag(token.replace(/^-/, '')).replace(/_/g, ' ')) + (isExactTag(token.replace(/^-/, '')) ? '<sup>*</sup>' : '');
    const piece = token => `<span class="${pinnedTokens.includes(token) ? 'tfb-base' : 'tfb-own'}">${show(token)}</span>`;
    const inc = tags.filter(t => !t.startsWith('-')).map(piece).join(', ');
    const exc = tags.filter(t => t.startsWith('-')).map(piece).join(', ');
    return `${inc || '<span class="tfb-base">(전체)</span>'}${exc ? ` <span class="tfb-x">− ${exc}</span>` : ''}`;
  }

  function renderBranches() {
    const host = ensureBranchHost();
    if (!host) return;
    const canStage = hasUnpinnedChips();
    const live = enabledBranches().length > 0 && canStage;
    const rows = stagedBranches.map((branch, i) => `
      <div class="tfb-row${branch.enabled ? '' : ' is-off'}" data-tfb-i="${i}">
        <button type="button" class="tfb-on" data-tfb="toggle" aria-pressed="${branch.enabled}" title="${branch.enabled ? '끄기' : '켜기'}"></button>
        <span class="tfb-text">${branchLabelHtml(branch.tags)}</span>
        <span class="tfb-n">${branch.enabled ? branchCountText(branch.tags) : '꺼짐'}</span>
        <button type="button" class="tfb-del" data-tfb="remove" title="분기 지우기">×</button>
      </div>`).join('');
    const liveRow = live ? `
      <div class="tfb-row is-live">
        <span class="tfb-on is-live" aria-hidden="true"></span>
        <span class="tfb-text"><em>작업 중</em> ${branchLabelHtml(payload())}</span>
        <span class="tfb-n">${branchCountText(payload())}</span>
        <span class="tfb-del" aria-hidden="true"></span>
      </div>` : '';
    const hint = stagedBranches.length ? `분기 ${stagedBranches.length}개 · 결과 = 켜진 분기들의 합집합`
      : '기준 칩을 📌 고정하고 [분기로 담기] — 분기마다 다른 조건을 붙여 합칩니다';
    host.innerHTML = `
      <div class="tfb-head">
        <button type="button" class="tfb-stage" data-tfb="stage" ${canStage ? '' : 'disabled'}
          data-naia-guide="지금 칩을 분기 하나로 담고, 📌 고정 칩만 남깁니다. 다음 분기 조건을 바로 이어서 넣으세요. 결과 = 켜진 분기들의 합집합(중복 행은 한 번).">+ 분기로 담기</button>
        <span class="tfb-hint">${hint}</span>
      </div>
      ${stagedBranches.length ? `<div class="tfb-list">${rows}${liveRow}</div>` : ''}`;
  }

  function clearAutocomplete() {
    acResults = [];
    acSelection = -1;
    const el = getEl('tagFilterAc');
    if (el) el.innerHTML = '';
  }

  function cancelPendingSearch() {
    if (searchDebounceTimer) {
      clearTimeout(searchDebounceTimer);
      searchDebounceTimer = null;
    }
  }

  function sendSearchNow() {
    cancelPendingSearch();
    if (!hasFilter()) return false;
    if (!isSocketOpen()) return false;
    lockTagSurface('tagfilter');   // background tag-filter search → released by onTagFilterResult/Assigned
    lastSentBranches = branchesPayload();
    send({type: 'tag_filter_search', tags: payload(), branches: lastSentBranches, request_id: nextSearchRequestId()});
    return true;
  }

  function scheduleSearch() {
    if (!hasFilter()) return;
    invalidateSearchRequest();
    cancelPendingSearch();
    searchDebounceTimer = setTimeout(sendSearchNow, SEARCH_DEBOUNCE_MS);
  }

  function renderAutocomplete() {
    const el = getEl('tagFilterAc');
    if (!el) return;
    if (!acResults.length) {
      el.innerHTML = '';
      return;
    }
    let html = '<div class="tag-ac-list">';
    acResults.forEach((result, index) => {
      const selected = index === acSelection ? ' selected' : '';
      const tagColor = deps.catStyle(result.cat);
      html += `<div class="tag-ac-item${selected}" data-idx="${index}">`
        + `<span class="tag-ac-tag"${tagColor}>${deps.escHtml(result.tag)}</span>`
        + `<span class="tag-ac-group">${deps.escHtml(result.group || '')}</span>`
        + `<span class="tag-ac-count">${deps.fmtCount(result.count)}</span>`
        + '</div>';
    });
    html += '</div>';
    el.innerHTML = html;
    el.querySelectorAll('.tag-ac-item').forEach(item => {
      item.addEventListener('mousedown', event => {
        event.preventDefault();
        selectAutocomplete(acResults[+item.dataset.idx].tag);
      });
    });
  }

  function commitTags(target, rawValue) {
    // ⚠️ sigil 만 남는 입력(`*`, `**`)은 태그가 없다 - 백엔드가 어차피 버리므로
    //    칩으로 만들면 **화면에만 있고 아무 일도 안 하는 칩**이 되고, 퍼펙트 매칭을
    //    해제하면 빈 칩이 남는다(Codex 지적).
    const tags = normalizeTags([rawValue]).filter(tag => baseTag(tag).length > 0);
    if (!tags.length) return false;
    const targetList = target === 'exclude' ? excludeTags : includeTags;
    let changed = false;
    tags.forEach(tag => {
      if (targetList.includes(tag)) return;
      targetList.push(tag);
      changed = true;
    });
    if (changed) {
      if (target === 'exclude') renderExcludeChips();
      else renderIncludeChips();
    }
    return changed;
  }

  function selectAutocomplete(tag) {
    if (!normalizeTags([tag]).length) return;
    const changed = commitTags(acTarget, tag);
    const input = getEl(acTarget === 'exclude' ? 'tagFilterExcludeInput' : 'tagFilterInput');
    if (input) input.value = '';
    clearAutocomplete();
    updateCommitButton();
    if (changed) apply();   // U1 live: chip add schedules one search, then onResult auto-applies.
  }

  function commitPendingInputs() {
    const includeInput = getEl('tagFilterInput');
    const excludeInput = getEl('tagFilterExcludeInput');
    const includeText = includeInput ? includeInput.value.trim() : '';
    const excludeText = excludeInput ? excludeInput.value.trim() : '';
    if (!includeText && !excludeText) {
      // ⚠️ 여기서 그냥 돌아가던 것이 **버튼을 켜도 아무 일이 없던** 나머지 절반이다.
      //    입력칸이 비어도 걸린 칩이 있으면 **같은 조건으로 다시 건다** - 랜덤 풀이
      //    소진돼 "No matches" 가 된 뒤 빠져나갈 유일한 길이었다(사용자 제보).
      if (hasFilter()) apply();
      return;
    }
    let changed = false;
    if (includeText) changed = commitTags('include', includeText) || changed;
    if (excludeText) changed = commitTags('exclude', excludeText) || changed;
    if (includeInput) includeInput.value = '';
    if (excludeInput) excludeInput.value = '';
    clearAutocomplete();
    updateCommitButton();
    if (changed) apply();
  }

  function bindAutocompleteInput(inputId, target) {
    const input = getEl(inputId);
    if (!input) return;

    input.addEventListener('focus', () => {
      acTarget = target;
    });

    input.addEventListener('input', function() {
      acTarget = target;
      updateCommitButton();
      const query = this.value.trim();
      if (query.length < 2) {
        clearAutocomplete();
        return;
      }
      clearTimeout(acTimer);
      acTimer = setTimeout(() => {
        latestAcRequest = {target, query};
        // ⚠️ 자동완성에는 sigil 을 빼고 보낸다. `*sky` 를 그대로 보내면 태그 색인에
        //    그런 태그가 없어 **결과가 0건**이 된다 - 사용자가 직접 `*sky` 를 치면
        //    Enter 로 칩은 만들어지는데 자동완성만 조용히 사라진다(Codex 지적).
        send({type: 'tag_filter_ac', query: baseTag(query)});
      }, 150);
    });

    input.addEventListener('keydown', function(event) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        acSelection = Math.min(acSelection + 1, acResults.length - 1);
        renderAutocomplete();
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        acSelection = Math.max(acSelection - 1, -1);
        renderAutocomplete();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (acSelection >= 0 && acResults[acSelection]) {
          selectAutocomplete(acResults[acSelection].tag);
        } else if (this.value.trim()) {
          selectAutocomplete(this.value.trim());
        }
      } else if (event.key === 'Escape') {
        clearAutocomplete();
        updateCommitButton();
      }
    });
  }

  function bindInputs() {
    renderBranches();
    bindAutocompleteInput('tagFilterInput', 'include');
    bindAutocompleteInput('tagFilterExcludeInput', 'exclude');
    bindPresetTooltip();
    updateCommitButton();
  }

  function open() {
    const s = surface();
    const popup = getEl('tagFilterPopup');
    if (s) s.open();
    else {
      if (!popup) return;
      deps.closeAuxiliaryPopups(popup);
      popup.classList.add('open');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) toggleBtn.classList.add('active');
    renderIncludeChips();
    renderExcludeChips();
    // 캐시된 등급별 카운트가 있으면 열 때 매치 라벨을 즉시 표시(재계산해 유지).
    renderMatchedCount(active ? 'assigned' : 'matched');
    const input = getEl('tagFilterInput');
    if (input) input.focus();
  }

  function close() {
    const s = surface();
    if (s) s.close();
    const popup = getEl('tagFilterPopup');
    if (popup) popup.classList.remove('open');
    if (!active) {
      const toggleBtn = getEl('tagFilterToggle');
      if (toggleBtn) toggleBtn.classList.remove('active');
    }
    clearAutocomplete();
    hidePresetTip();
  }

  function toggle() {
    if (!surface() && !getEl('tagFilterPopup')) return;
    if (popupOpen()) close();
    else open();
  }

  function clearFilter(options = {}) {
    const sendClear = options.sendClear !== false;
    const persist = options.persist !== false;

    includeTags = [];
    excludeTags = [];
    stagedBranches = [];
    pinnedTokens = [];
    branchCounts.clear();
    active = false;
    filterWasApplied = false;
    ratingCounts = null;
    pendingAssignOnRestore = false;
    invalidateSearchRequest();
    cancelPendingSearch();
    renderIncludeChips();
    renderExcludeChips();
    renderBranches();
    updateCommitButton();

    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.classList.remove('assigned');
    }
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;

    const restored = deps.computeLocalFilteredCount();
    if (restored !== null && restored !== undefined) deps.updateSearchCount(restored);
    if (sendClear) send({type: 'tag_filter_clear'});
    if (persist) save();
    else updateHighlight();
    notifyFilterChanged();
    flushAssignedOnce();
  }

  function reset(options = {}) {
    clearFilter({
      sendClear: options.sendClear === true,
      persist: options.persist === true,
    });
    close();
    if (options.restoreSaved) restorePreferences();
  }

  function invalidateAssignedState() {
    active = false;
    ratingCounts = null;
    invalidateSearchRequest();
    cancelPendingSearch();
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) toggleBtn.classList.remove('assigned');
  }

  function removeExcludeTag(index) {
    // ⚠️ 인덱스가 밀리므로 열린 메뉴는 닫는다 - 안 닫으면 엉뚱한 칩에 메뉴가 붙는다.
    closeChipMenu();
    const [removedExclude] = excludeTags.splice(index, 1);
    unpin(tokenOf('exclude', removedExclude));
    renderExcludeChips();
    updateCommitButton();
    if (!hasFilter()) {
      clearFilter();
      return;
    }
    apply();   // U1: 남은 칩으로 즉시 재검색 → 자동 적용 (캐시 재조합, 스캔 0)
  }

  function removeIncludeTag(index) {
    closeChipMenu();
    const [removedInclude] = includeTags.splice(index, 1);
    unpin(tokenOf('include', removedInclude));
    renderIncludeChips();
    updateCommitButton();
    if (!hasFilter()) {
      clearFilter();
      return;
    }
    apply();   // U1: 남은 칩으로 즉시 재검색 → 자동 적용 (캐시 재조합, 스캔 0)
  }

  function apply() {
    if (!hasFilter()) return;
    save();
    if (!isSocketOpen()) return;
    scheduleSearch();
  }

  // ── 프롬프트 우클릭에서 들어오는 입구 (사용자 요청 2026-08-31) ────────────
  //
  // ⚠️ 칩 목록을 바깥에서 직접 만지지 못하게 한다. 필터 상태의 주인은 여기 하나다 -
  //    두 곳이 만지면 화면(칩)과 실제(적용된 필터)가 갈린다.

  function snapshotTags() {
    return {include: [...includeTags], exclude: [...excludeTags], active};
  }

  /** 스냅샷으로 되돌리고 **다시 적용까지** 한다. 비어 있었으면 필터를 끈다. */
  function restoreTags(snapshot) {
    const include = normalizeTags(snapshot && snapshot.include);
    const exclude = normalizeTags(snapshot && snapshot.exclude);
    if (!include.length && !exclude.length) {
      clearFilter();
      return;
    }
    includeTags = include;
    excludeTags = exclude;
    renderChips();
    updateHighlight();
    apply();
  }

  /** 그 태그가 지금 필터 어디에 있는지. 없으면 null.
   *
   * ⚠️ `*` 는 **퍼펙트 매칭 표식**이지 태그의 일부가 아니다 - 벗기고 비교해야
   *    `*sky` 가 들어 있는 상태에서 `sky` 로 우클릭한 사용자에게 "추가" 가 아니라
   *    "제거 / 퍼펙트 매칭 취소" 를 보여 줄 수 있다.
   */
  function findTag(rawTag) {
    const [normalized] = normalizeTags([rawTag]);
    if (!normalized) return null;
    const needle = baseTag(normalized).toLowerCase();
    for (const [list, arr] of [['include', includeTags], ['exclude', excludeTags]]) {
      const index = arr.findIndex(tag => baseTag(tag).toLowerCase() === needle);
      if (index >= 0) return {list, index, exact: isExactTag(arr[index]), tag: arr[index]};
    }
    return null;
  }

  function removeTagAt(list, index) {
    if (String(list) === 'exclude') removeExcludeTag(index);
    else removeIncludeTag(index);
  }

  /** 목록에 태그를 더한다. 이미 있으면 false(부를 쪽이 안내한다). */
  function addTag(list, rawTag) {
    const [tag] = normalizeTags([rawTag]);
    if (!tag) return false;
    const target = list === 'exclude' ? excludeTags : includeTags;
    if (target.some(existing => existing.toLowerCase() === tag.toLowerCase())) return false;
    target.push(tag);
    renderChips();
    updateHighlight();
    return true;
  }

  // 적용이 **실제로 끝났을 때** 한 번만 부른다. 검색->assign 왕복이라 apply() 직후에
  // 세면 옛 숫자를 읽는다.
  let assignedOnce = [];
  function onceAssigned(callback) {
    if (typeof callback === 'function') assignedOnce.push(callback);
  }
  // 필터가 실제로 바뀌었다 - 프롬프트 하이라이팅이 따라와야 한다.
  // ⚠️ 우클릭 경로에서만 부르면 **Quick Filter 패널에서 바꿨을 때 하이라이팅이
  //    낡은 채로 남는다.** 상태가 굳는 자리(assign·clear)에 건다.
  function notifyFilterChanged() {
    if (typeof deps.onFilterChanged === 'function') {
      try { deps.onFilterChanged(); } catch (error) { console.error('onFilterChanged failed', error); }
    }
  }

  function flushAssignedOnce() {
    const waiting = assignedOnce;
    assignedOnce = [];
    waiting.forEach(callback => {
      try { callback(); } catch (error) { console.error('onceAssigned failed', error); }
    });
  }

  // Custom parquet load/merge swapped the pool: the backend deactivated the
  // filter and kept the chips as a draft, so the cached 'N matched' count is now
  // stale (old pool). Auto re-apply the chips to the NEW pool (fresh search +
  // assign) so the filter follows the dataset and the counts recompute. Old
  // counts are invalidated first so no stale label flashes before the fresh
  // result lands.
  function onPoolSwap() {
    ratingCounts = null;
    branchCounts.clear();
    const hasTags = hasFilter();
    // Clear the stale label explicitly — renderMatchedCount() no-ops while
    // ratingCounts is null, so it would otherwise leave the old '982,029 matched'.
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = hasTags ? '재적용 중…' : '';
      countEl.classList.remove('has-result');
    }
    if (hasTags) {
      // Pool-swap search_state releases the 'pool' lock immediately after this
      // callback. Raise the independent tag-filter lock synchronously, without
      // the normal 280 ms typing debounce, so Random never sees the unfiltered
      // replacement pool in that gap.
      save();
      sendSearchNow();
    }
  }

  function setReleasedOverlay(show) {
    const el = getEl('tagFilterReleased');
    if (el) el.hidden = !show;
  }

  // 라이브 green [검색] 이 활성 태그필터를 백엔드에서 해제(칩은 draft 로 보존)한 직후 호출.
  // 파켓 스왑(onPoolSwap)과 달리 자동 재적용하지 않고, Quick Filter 를 '해제됨' 상태
  // (블러 오버레이 + [재적용]/[초기화])로 두어 사용자가 명시적으로 선택하게 한다(설계 사양).
  // stale 'N matched'(이전 풀 기준)도 함께 무효화한다.
  function onSearchReleased() {
    const hasTags = hasFilter();
    // 진짜 적용됐던 필터 + 칩이 있을 때만 '해제됨' 오버레이. 미적용 draft 칩엔 안 띄운다(MED).
    if (!filterWasApplied || !hasTags) { setReleasedOverlay(false); return false; }
    active = false;
    ratingCounts = null;
    // green 검색이 in-flight 태그필터 왕복 중 발생했다면 그 요청을 폐기 → 늦게 온 stale 응답이
    // request_id 불일치로 잠금을 ~90초 남기던 누수(Codex A1-2)를 막기 위해 'tagfilter' 잠금을
    // 명시적으로 해제한다(해제됨 상태는 잠금 스캔이 아니므로 안전; Set 이라 idempotent).
    invalidateSearchRequest();
    cancelPendingSearch();
    unlockTagSurface('tagfilter');
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.classList.remove('assigned');
    }
    setReleasedOverlay(true);
    return true;
  }

  function reapplyReleased() {
    // [재적용]: 현재 칩을 새 풀에 재적용. sendSearchNow 가 'tagfilter' 잠금을 걸고,
    // onResult→assign→assigned 가 active=true 로 재적용/재영속한다(스캔 전체 잠금은
    // 백엔드 announce + Fix 1 이 result~assigned 창까지 유지).
    const hasTags = hasFilter();
    if (!hasTags) { setReleasedOverlay(false); return; }
    save();
    // 소켓이 끊겨 실제 전송이 안 되면 오버레이를 유지한다 — "재적용됨"으로 거짓 표시 방지(LOW).
    if (sendSearchNow()) setReleasedOverlay(false);
  }

  function resetReleased() {
    // [초기화]: 칩/필터를 모두 해제.
    setReleasedOverlay(false);
    clearFilter();
  }

  function assign() {
    send({type: 'tag_filter_assign', request_id: latestSearchRequestId});
  }

  function onResult(message) {
    if (message.request_id && message.request_id !== latestSearchRequestId) {
      return false;
    }
    const assignBtn = getEl('tagFilterAssignBtn');
    ratingCounts = message.rating_counts || null;
    const perBranch = Array.isArray(message.branch_rating_counts) ? message.branch_rating_counts : [];
    lastSentBranches.forEach((tags, i) => { if (perBranch[i]) branchCounts.set(branchSig(tags), perBranch[i]); });
    const hasTags = !!(message.tags && message.tags.length) || !!(message.branches && message.branches.length);
    if (hasTags && ratingCounts && Object.keys(ratingCounts).length) {
      // 등급 인식 매치 수(활성 G/S/Q/E 합). 등급 토글에 라이브로 반응한다.
      renderMatchedCount('matched');
    } else {
      const countEl = getEl('tagFilterCount');
      if (countEl) {
        if (message.count > 0) {
          countEl.textContent = `${message.count.toLocaleString()} matched`;
          countEl.classList.add('has-result');
        } else {
          countEl.textContent = hasTags ? 'No matches' : '';
          countEl.classList.remove('has-result');
        }
      }
    }
    if (assignBtn) assignBtn.disabled = true;
    pendingAssignOnRestore = false;
    // U1 완전 라이브: 칩이 있으면 결과를 항상 즉시 적용(0매치 포함) → 활성 필터 == 현재 칩(일관성).
    // 0매치 시 빈 필터가 적용되어 풀이 비지만, 칩을 고치면 즉시 복원된다. 칩이 없으면 미적용
    // (빈칩 경로는 clearFilter가 처리).
    // GAP A 수정: assign 을 쏘면 false 를 반환해 tagfilter 잠금을 유지한다 →
    // result~assigned 커밋 왕복 동안 풀이 미필터/미잠금으로 노출되던 창을 닫는다
    // (onStale 의 `!sendSearchNow()` 와 동일 계약; 잠금 해제는 onAssigned/onStale 이 소유).
    if (hasTags) {
      assign();
      return false;
    }
    return true;
  }

  function onAssigned(message) {
    if (message.request_id && message.request_id !== latestSearchRequestId) {
      return false;
    }
    // A different tab can commit a newer assignment while this request's
    // websocket send is delayed. Unlock this completed local request, but never
    // repaint the shared UI with its older authoritative state.
    if (!noteAuthoritativeRevision(message.tag_filter_revision)) return true;
    active = true;
    filterWasApplied = true;
    if (message.rating_counts) ratingCounts = message.rating_counts;
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.classList.add('assigned');
    }
    // 등급 인식 카운트(활성 등급 합)로 표시 — 등급 토글에 라이브 반응하고 RATING 옆에서 유지된다.
    renderMatchedCount('assigned');
    notifyFilterChanged();
    flushAssignedOnce();
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;
    // The backend commit already persisted this assignment. Sending another
    // save_search_filter_state here creates a cross-tab race: an older
    // requester's delayed acknowledgement can overwrite the newer committed
    // draft without changing the active filter. Keep this requester-local;
    // the following revisioned search_state is the shared persistence authority.
    savePreferences(collectPreferences(), storage);
    updateHighlight();
    if (ratingCounts) {
      deps.updateSearchCount(filteredCount(ratingCounts, deps.getRatingState()));
    }
    // (토스트 제거 — 라이브 자동 적용이라 매번 토스트는 소음. 행수는 RATING 옆 카운트 라벨로 표시.)
    return true;
  }

  function onStale(message) {
    if (message.request_id && message.request_id !== latestSearchRequestId) {
      return false;
    }
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '재적용 중…';
      countEl.classList.remove('has-result');
    }
    // Pool replacement or another tab may have superseded the single pending
    // assignment. Re-run against the now-current pool. Returning false keeps
    // the existing lock source alive while the replacement request is in flight.
    return !sendSearchNow();
  }

  function onUpdate(message) {
    if (!noteAuthoritativeRevision(message.tag_filter_revision)) return false;
    if (message.rating_counts) ratingCounts = message.rating_counts;
    renderMatchedCount('assigned');
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn && active) toggleBtn.classList.add('assigned');
    if (ratingCounts) {
      deps.updateSearchCount(filteredCount(ratingCounts, deps.getRatingState()));
    }
    return true;
  }

  function noteAuthoritativeRevision(value) {
    const revision = Number(value) || 0;
    if (revision <= 0) return true;
    if (revision < latestTagFilterRevision) return false;
    latestTagFilterRevision = revision;
    return true;
  }

  function onAutocompleteResult(message) {
    if (!popupOpen()) return;
    const inputId = acTarget === 'exclude' ? 'tagFilterExcludeInput' : 'tagFilterInput';
    const input = getEl(inputId);
    if (!input || input.value.trim().length < 2) return;
    const query = String(message.query || '').trim();
    const currentQuery = input.value.trim();
    if (query && query !== currentQuery) return;
    if (latestAcRequest.query && latestAcRequest.query !== currentQuery) return;
    if (latestAcRequest.target && latestAcRequest.target !== acTarget) return;
    acResults = message.results || [];
    acSelection = -1;
    renderAutocomplete();
  }

  function applyPreferences(saved, options = {}) {
    const pref = normalizePreferences(saved);
    if (!pref) {
      updateHighlight();
      return false;
    }
    const focusedInputState = captureFocusedInputState();

    // search_state reconcile(같은 칩)인지 판별 — 같다면 캐시된 ratingCounts/매치 라벨을 보존한다.
    // (이게 "27,301 matched"가 잠깐 떴다 사라지던 원인: 매 search_state 마다 라벨을 비웠음.)
    const sameTags = JSON.stringify([...includeTags].sort()) === JSON.stringify([...pref.tag_filter].sort())
      && JSON.stringify([...excludeTags].sort()) === JSON.stringify([...pref.tag_filter_exclude].sort())
      && JSON.stringify(stagedBranches) === JSON.stringify(pref.tag_filter_branches);

    setActiveRatings(pref.ratings);
    // ⚠️ 칩 배열이 통째로 바뀌면 열린 메뉴는 닫는다. 메뉴는 **인덱스**로 칩을 가리키는데,
    //    백엔드 권위 상태는 모든 탭에 적용되므로 다른 탭이 앞쪽 칩을 지우면 인덱스가
    //    밀려 **다음 클릭이 엉뚱한 칩의 exact 를 뒤집는다**(Codex 지적). 로컬 × 경로만
    //    닫는 것으로는 모자란다.
    if (!sameTags) closeChipMenu();
    includeTags = [...pref.tag_filter];
    excludeTags = [...pref.tag_filter_exclude];
    stagedBranches = pref.tag_filter_branches.map(branch => ({tags: [...branch.tags], enabled: branch.enabled}));
    pinnedTokens = [...pref.tag_filter_pinned];
    active = pref.tag_filter_active;
    if (!sameTags) ratingCounts = null;   // 칩이 바뀌면 옛 카운트는 무효
    renderIncludeChips();
    renderExcludeChips();
    renderBranches();
    updateCommitButton();
    deps.syncRatingButtons();

    if (options.updateCount !== false) {
      const localCount = deps.computeLocalFilteredCount();
      if (localCount !== null && localCount !== undefined) deps.updateSearchCount(localCount);
    }

    const countEl = getEl('tagFilterCount');
    if (sameTags) {
      // 칩 불변: 캐시된 등급별 카운트로 매치 라벨을 다시 그려 유지(reconcile 시 깜빡임/소실 방지).
      renderMatchedCount(active ? 'assigned' : 'matched');
    } else if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const assignBtn = getEl('tagFilterAssignBtn');
    if (assignBtn) assignBtn.disabled = true;
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.classList.toggle('assigned', active);
    }
    updateHighlight();
    // ⚠️ **다른 탭/기기의 변경은 이 길로 들어온다**(백엔드 권위 상태 -> searchPanel ->
    //    applyPreferences). assign/clear 에만 걸어 두면 여기로 들어온 변경 뒤에는
    //    프롬프트의 색·밑줄이 옛 필터를 가리킨 채 남는다(Codex 지적).
    if (!sameTags) notifyFilterChanged();

    if (options.send !== false && isSocketOpen()) {
      send({type: 'set_active_ratings', ratings: pref.ratings});
      if (hasFilter()) {
        pendingAssignOnRestore = active;
        scheduleSearch();
      }
    }
    if (options.persistLocal) savePreferences(pref, storage);
    restoreFocusedInputState(focusedInputState);
    updateCommitButton();
    return true;
  }

  function restorePreferences(options = {}) {
    const saved = load();
    if (!saved) {
      updateHighlight();
      return false;
    }
    return applyPreferences(saved, options);
  }

  // ---- 저장된 필터 프리셋 (backend 영속·기기 공유, 태그만) ----
  let presets = [];

  function setPresets(list) {
    presets = Array.isArray(list) ? list.filter(p => p && p.name) : [];
    renderPresets();
  }

  function renderPresets() {
    const el = getEl('tagFilterPresets');
    if (!el) return;
    if (!presets.length) {
      el.innerHTML = '<div class="tf-preset-empty">저장된 필터 없음</div>';
      return;
    }
    el.innerHTML = presets.map((p, i) => {
      const incArr = p.include || [];
      const excArr = p.exclude || [];
      return `<div class="tf-preset" data-idx="${i}"><span class="tf-preset-name" onclick="loadTagFilterPreset(${i})">`
        + `${deps.escHtml(p.name)}<span class="tf-preset-meta">+${incArr.length} −${excArr.length}</span></span>`
        + `<span class="tf-preset-x" onclick="deleteTagFilterPreset(${i})" title="삭제">&times;</span></div>`;
    }).join('');
  }

  // 커스텀 hover 툴팁 — Include/Exclude 라벨을 색으로 구분(native title은 색 불가).
  // body 에 붙인 position:fixed 라 스크롤 목록에서 잘리지 않는다.
  let tipEl = null;
  function ensurePresetTip() {
    if (tipEl && tipEl.isConnected) return tipEl;
    tipEl = document.createElement('div');
    tipEl.className = 'tf-preset-tip';
    tipEl.style.display = 'none';
    document.body.appendChild(tipEl);
    return tipEl;
  }
  function hidePresetTip() {
    if (tipEl) tipEl.style.display = 'none';
  }
  function showPresetTip(item, p) {
    const tip = ensurePresetTip();
    const inc = (p.include || []).join(', ') || '(none)';
    const exc = (p.exclude || []).join(', ') || '(none)';
    tip.innerHTML = `<div class="tf-tip-line"><span class="tf-tip-inc">Include:</span> ${deps.escHtml(inc)}</div>`
      + `<div class="tf-tip-line"><span class="tf-tip-exc">Exclude:</span> ${deps.escHtml(exc)}</div>`;
    tip.style.display = 'block';
    const r = item.getBoundingClientRect();
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let top = r.top - th - 8;
    if (top < 8) top = r.bottom + 8;          // 위 공간 부족 시 아래로
    let left = r.left;
    if (left + tw > window.innerWidth - 8) left = window.innerWidth - 8 - tw;
    if (left < 8) left = 8;
    tip.style.top = `${top}px`;
    tip.style.left = `${left}px`;
  }
  function bindPresetTooltip() {
    const list = getEl('tagFilterPresets');
    if (!list || list._tipBound) return;
    list._tipBound = true;
    list.addEventListener('mouseover', (e) => {
      const item = e.target.closest('.tf-preset');
      if (!item || !list.contains(item)) return;
      const p = presets[parseInt(item.dataset.idx, 10)];
      if (p) showPresetTip(item, p);
    });
    list.addEventListener('mouseleave', hidePresetTip);
  }

  function togglePresets() {
    const el = getEl('tagFilterPresets');
    if (!el) return;
    if (!el.hasAttribute('hidden')) { hidePresetTip(); el.setAttribute('hidden', ''); return; }
    const saveRow = getEl('tagFilterSaveRow');
    if (saveRow) saveRow.setAttribute('hidden', '');
    renderPresets();
    el.removeAttribute('hidden');
  }

  function toggleSaveRow() {
    const row = getEl('tagFilterSaveRow');
    if (!row) return;
    if (!row.hasAttribute('hidden')) { row.setAttribute('hidden', ''); return; }
    if (!includeTags.length && !excludeTags.length) {
      deps.showToast('저장할 필터가 없습니다 (칩을 추가하세요)', 'error');
      return;
    }
    const presetsEl = getEl('tagFilterPresets');
    if (presetsEl) presetsEl.setAttribute('hidden', '');
    row.removeAttribute('hidden');
    const input = getEl('tagFilterPresetName');
    if (input) { input.value = ''; input.focus(); }
  }

  function confirmSavePreset() {
    const input = getEl('tagFilterPresetName');
    const name = input ? String(input.value || '').trim() : '';
    if (!name) { if (input) input.focus(); return; }
    if (!includeTags.length && !excludeTags.length) return;
    if (!isSocketOpen()) {
      deps.showToast('연결이 끊겨 저장하지 못했습니다', 'error');
      return;   // 저장행은 유지 — 재연결 후 다시 시도. 거짓 성공 표시 방지.
    }
    send({ type: 'save_filter_preset', name, include: [...includeTags], exclude: [...excludeTags] });
    const row = getEl('tagFilterSaveRow');
    if (row) row.setAttribute('hidden', '');
    deps.showToast(`필터 저장: ${name}`, 'success');
  }

  function loadPresetAt(i) {
    const p = presets[i];
    if (!p) return;
    includeTags = normalizeTags(p.include);
    excludeTags = normalizeTags(p.exclude);
    renderIncludeChips();
    renderExcludeChips();
    updateCommitButton();
    hidePresetTip();
    const el = getEl('tagFilterPresets');
    if (el) el.setAttribute('hidden', '');
    if (!includeTags.length && !excludeTags.length) { clearFilter(); return; }
    apply();   // 라이브 자동 적용 (등급은 건드리지 않음 — 프리셋은 태그만)
  }

  function deletePresetAt(i) {
    const p = presets[i];
    if (!p || !isSocketOpen()) return;
    send({ type: 'delete_filter_preset', name: p.name });
  }

  return {
    bindInputs,
    toggle,
    open,
    close,
    clear: clearFilter,
    setPresets,
    togglePresets,
    toggleSaveRow,
    commitPendingInputs,
    confirmSavePreset,
    loadPresetAt,
    deletePresetAt,
    removeExcludeTag,
    removeIncludeTag,
    toggleChipMenu,
    setChipExact,
    setChipPinned,
    stageBranch,
    branchesPayload,
    closeChipMenu,
    apply,
    onPoolSwap,
    onSearchReleased,
    reapplyReleased,
    resetReleased,
    assign,
    onResult,
    onAssigned,
    onStale,
    onUpdate,
    noteAuthoritativeRevision,
    onAutocompleteResult,
    applyPreferences,
    restorePreferences,
    updateHighlight,
    refreshCount,
    savePreferences: save,
    loadPreferences: load,
    reset,
    normalizeTags,
    payload,
    isActive: () => active,
    getRatingCounts: () => ratingCounts,
    snapshotTags,
    restoreTags,
    addTag,
    findTag,
    removeTagAt,
    setChipExact,
    onceAssigned,
  };
}
