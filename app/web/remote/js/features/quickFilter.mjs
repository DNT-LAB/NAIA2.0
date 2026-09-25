import { RATING_KEYS, filteredCount } from './ratingStore.mjs';

const STORAGE_KEY = 'naia_quick_filter_options';
const DEFAULT_RATING_KEYS = ['g', 's', 'q'];
const SEARCH_DEBOUNCE_MS = 280;

// 스테이징 상자(사용자 지정 2026-09-25: 빠른 스테이징) - Save Filter·Filters 줄 아래. 창의 컴팩트 톤.
const TFB_CSS = `
.tfb{display:flex;flex-direction:column;gap:5px;padding:6px;border-radius:7px;background:rgba(0,0,0,0.18);
  border:1px solid rgba(141,123,214,0.28)}
.tfb-head{display:flex;align-items:center;gap:6px;min-width:0}
.tfb-title{flex:0 0 auto;font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#b9aef0}
.tfb-stage{flex:0 0 auto;height:22px;padding:0 9px;border-radius:5px;font-size:10.5px;font-weight:700;cursor:pointer;
  border:1px solid rgba(141,123,214,0.6);background:rgba(141,123,214,0.16);color:#d9d0ff}
.tfb-stage:hover:not(:disabled){background:rgba(141,123,214,0.30);color:#fff}
.tfb-stage:disabled{opacity:.4;cursor:default}
.tfb-btns{display:flex;gap:4px}
.tfb-btns>button{flex:1 1 0;min-width:0;height:24px;font-size:10.5px;white-space:nowrap}
.tfb-undo{border-radius:5px;font-weight:700;cursor:pointer;border:1px solid var(--border-dim,#33333f);
  background:var(--bg-elevated,#1e1e26);color:var(--text-secondary,#c8c8d0)}
.tfb-undo:hover:not(:disabled){color:#fff;border-color:rgba(255,255,255,0.3)}
.tfb-undo:disabled,.tfb-act:disabled{opacity:.35;cursor:default}
.tfb-row.is-pick{cursor:pointer}
.tfb-row.is-sel{background:rgba(141,123,214,0.16);box-shadow:inset 0 0 0 1px rgba(141,123,214,0.55)}
.tfb-row.is-temp .tfb-text{color:#f5dc8a}
.tfb-temp{flex:0 0 auto;font-size:9px;font-weight:700;padding:0 5px;border-radius:3px;color:#1a1a1a;background:#f5dc8a}
.tfb-acts{display:flex;gap:4px;padding-top:4px;border-top:1px dashed rgba(141,123,214,0.3)}
.tfb-act{flex:1 1 0;height:22px;border-radius:5px;font-size:10.5px;font-weight:700;cursor:pointer;
  border:1px solid rgba(245,220,138,0.55);background:rgba(245,220,138,0.12);color:#f5dc8a}
.tfb-act.revert{border-color:var(--border-dim,#33333f);background:var(--bg-elevated,#1e1e26);color:var(--text-secondary,#c8c8d0)}
.tfb-act:hover:not(:disabled){filter:brightness(1.25)}
.tfb-hint{flex:1 1 auto;min-width:0;font-size:9.5px;color:var(--text-dimmer,#6c6c78);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tfb-list{display:flex;flex-direction:column;gap:2px}
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
.tfb-x{color:#e39a9a}
.tfb-n{flex:0 0 auto;font-family:var(--font-mono,monospace);font-size:10px;color:#f5dc8a;font-variant-numeric:tabular-nums}
.tfb-del{flex:0 0 14px;border:none;background:transparent;color:var(--text-dimmer,#6c6c78);cursor:pointer;font-size:13px;line-height:1;padding:0}
.tfb-del:hover{color:#f0a0a0}
/* include/exclude 칸 오른쪽 끝의 Clear - 그 칸의 칩과 글자만 비운다. */
.tag-filter-input-row .tf-clear{flex:0 0 auto;height:24px;padding:0 9px;border-radius:5px;font-size:10px;font-weight:700;
  cursor:pointer;border:1px solid var(--border-dim,#33333f);background:var(--bg-elevated,#1e1e26);color:var(--text-dim,#9a9aa6)}
.tag-filter-input-row .tf-clear:hover:not(:disabled){color:#fff;border-color:rgba(255,255,255,0.3)}
.tag-filter-input-row .tf-clear:disabled{opacity:.35;cursor:default}
/* 칩을 누르면 그 태그의 정보 카드가 층 아래 빈 자리에 그려진다(tagAssist lookupPromptInfoTag host). */
.sqw-body .tag-filter-body{flex:1 1 auto}
#tagFilterInfoHost{position:relative;flex:1 1 auto;min-height:120px}
#tagFilterInfoHost>.result-info-tag-popup.inline-host{position:absolute!important;inset:0!important;left:0!important;top:0!important;
  width:auto!important;min-width:0!important;max-width:none!important;max-height:none!important;z-index:auto!important;
  margin:0;box-shadow:none;border-radius:6px;overflow-y:auto}
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
// 입력칸은 쉼표로 여러 태그를 받는다 - 자동완성은 **마지막 쉼표 뒤 조각**만 본다(사용자 제보 2026-09-25).
// ⚠️ 칸 전체를 보내면 '1girl,' 이 태그 접두사로는 안 맞고 사전 설명글의 낱말 '1girl,' 에만 맞아
//    'gender request'(설명: "성별(1boy, 1girl, 1other 등)에 대한 요청") 한 줄이 떴다.
export const lastSegment = value => String(value || '').split(',').pop().trim();
export const leadingSegments = value => String(value || '').split(',').slice(0, -1).map(s => s.trim()).filter(Boolean);
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
  // 지금 풀에 걸린 조합(백엔드 commit 이 쓴다). 칩(tag_filter)은 초안이라 다를 수 있다.
  const applied = (Array.isArray(raw.tag_filter_applied_branches) ? raw.tag_filter_applied_branches : [])
    .map(item => normalizeTokens(Array.isArray(item) ? item : (item && item.tags))).filter(tags => tags.length);
  return {
    ratings: normalizeRatings(raw.ratings),
    tag_filter: include,
    tag_filter_exclude: exclude,
    tag_filter_branches: branches,
    tag_filter_applied_branches: applied,
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
  // 빠른 스테이징(사용자 지정 2026-09-25 - 📌 기준 고정은 회수). 결과 = 켜진 담은 것들 ∪ 지금 칩.
  let stagedBranches = [];            // [{tags:[칩 토큰], enabled}]
  let lastSentBranches = [];          // 마지막 검색에 보낸 분기(결과의 분기별 수와 순서가 같다)
  const branchCounts = new Map();     // 분기 서명 -> 등급별 수(마지막 결과)
  // 커밋 모델(사용자 지정 2026-09-25): 칩·스테이징은 **미리보기**다. 풀을 바꾸는 것은 [커밋 (적용)] ·
  // [커밋 취소] · [임시 적용] · [적용 취소] 와 바깥의 명시 적용(프롬프트 우클릭 · 풀 교체 재적용)뿐이다.
  let appliedBranches = [];           // 지금 풀에 걸린 조합(분기 목록). [] = 필터 없음
  let lastApplied = [];               // 마지막으로 걸었던 조합 - 라이브 검색·풀 교체가 풀어도 다시 건다
  let committedBranches = [];         // 마지막 커밋 조합 - [적용 취소] 가 돌아갈 곳
  const commitHistory = [];           // 커밋 직전의 조합들 - [커밋 취소](최근 20)
  let tempSig = '';                   // 임시 적용 중인 담은 것의 서명('' = 아님)
  let selectedSig = '';               // 스테이징에서 고른 줄의 서명
  let applyRequestId = '';            // 적용 요청(검색 -> assign)
  let applyInFlight = null;           // {branches, mode} - 결과·assign 을 기다리는 적용
  let previewRequestId = '';
  let previewQueued = false;
  let previewCounts = null;           // 미리보기(커밋하면 걸릴 합집합)의 등급별 수

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
  const hasChips = () => payload().length > 0;
  const enabledBranches = () => stagedBranches.filter(branch => branch.enabled);
  const isStaged = (tags, list = stagedBranches) => list.some(branch => branchSig(branch.tags) === branchSig(tags));
  /** 지금 칩이 켜진 담은 것과 **다른** 검색인가 - 같으면 두 번 세지 않는다(담아도 칩은 남는다). */
  const liveIsNew = () => hasChips() && !isStaged(payload(), enabledBranches());
  /** [커밋 (적용)] 이 걸 조합 = 켜진 담은 것들 + 지금 칩(담은 것과 다른 검색이면). 미리보기도 이것을 센다. */
  function branchesPayload() {
    const on = enabledBranches().map(branch => [...branch.tags]);
    if (liveIsNew()) on.push(payload());
    return on;
  }
  const hasFilter = () => includeTags.length > 0 || excludeTags.length > 0 || enabledBranches().length > 0;
  const hasApplied = () => appliedBranches.length > 0;
  const cloneBranches = list => (Array.isArray(list) ? list : []).map(tags => [...tags]);
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
    tag_filter_pinned: [],            // 고정 회수(2026-09-25) - 남아 있던 저장값을 비운다
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
    // 머리줄 수 = **지금 풀에 걸린** 것(커밋 모델). 초안의 수는 스테이징 머리줄이 보인다.
    const hasTags = active;
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
    renderMatchedCount('assigned');
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
    button.disabled = !(hasPendingText || hasFilter() || hasApplied());
    const undo = getEl('tagFilterUndoBtn');
    if (undo) undo.disabled = !commitHistory.length;
    // 칸마다의 Clear - 그 칸에 칩이나 글자가 있을 때만.
    for (const [list, inputId] of [['include', 'tagFilterInput'], ['exclude', 'tagFilterExcludeInput']]) {
      const clear = doc.querySelector(`[data-tf-clear="${list}"]`);
      const input = getEl(inputId);
      const tags = list === 'exclude' ? excludeTags : includeTags;
      if (clear) clear.disabled = !(tags.length || (input && input.value.trim()));
    }
  }

  function load() {
    return loadPreferences(storage);
  }

  // 칩을 누르면 아래에 서브메뉴가 하나 열린다(사용자 지정). 버튼을 칩에 상시로 두면
  // 칩 폭이 커져서, 누를 때만 내놓는다. 퍼펙트 매칭이 걸린 칩은 파랗게 강조된다.
  let chipMenu = null;          // {list:'include'|'exclude', index:number} | null

  function chipHtml(tag, index, list) {
    const exact = isExactTag(tag);
    const open = !!chipMenu && chipMenu.list === list && chipMenu.index === index;
    const remover = list === 'exclude' ? 'removeTagFilterExcludeTag' : 'removeTagFilterTag';
    // ⚠️ × 는 칩 **안**에 있어 클릭이 칩으로 올라간다 - 멈추지 않으면 지우면서 메뉴가 열린다.
    return `<span class="tag-filter-chip${list === 'exclude' ? ' exclude' : ''}`
      + `${exact ? ' is-exact' : ''}${open ? ' menu-open' : ''}"`
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
            + `${exact ? '퍼펙트 매칭 해제' : '퍼펙트 매칭 적용'}</button></span>`
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
    showChipInfo(chipMenu.list, chipMenu.index);
  }

  /** 칩을 누르면 그 태그의 정보 카드를 층 아래 빈 자리에 그린다(사용자 지정 2026-09-25 - Search 층과
   *  같은 규칙: 목록은 입력칸 아래, 아래 빈 자리는 **이미 고른 태그**). */
  function showChipInfo(list, index) {
    const tag = (list === 'exclude' ? excludeTags : includeTags)[Number(index)];
    const host = getEl('tagFilterInfoHost');
    if (tag === undefined || !host || typeof deps.showTagInfo !== 'function') return;
    deps.showTagInfo(baseTag(tag), host);
  }

  function setChipExact(list, index, exact, commitNow = false) {
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
    if (duplicate) arr.splice(idx, 1);
    else arr[idx] = next;
    renderChips();
    updateCommitButton();
    // 칩 메뉴에서는 초안(미리보기), 프롬프트 우클릭에서는 곧장 적용.
    if (commitNow) apply();
    else schedulePreview();
  }

  /** [+ 담기]: 지금 검색(칩 한 벌)을 스테이징에 담는다. **칩은 남긴다**(사용자 지정 2026-09-25 - 비우면
   *  검색어가 날아간다) - 칩 몇 개만 고쳐 다음 검색을 이어 간다. 결과 = 켜진 담은 것들 ∪ 지금 칩. */
  function stageBranch() {
    commitPendingInputs();
    if (!hasChips()) {
      deps.showToast('담을 검색이 없습니다 — 먼저 태그로 검색하세요', 'warning');
      return;
    }
    const tags = payload();
    if (isStaged(tags)) {
      deps.showToast('같은 검색이 이미 담겨 있습니다', 'warning');
      return;
    }
    if (stagedBranches.length >= 16) {
      deps.showToast('스테이징은 16개까지 담을 수 있습니다', 'warning');
      return;
    }
    stagedBranches.push({tags, enabled: true});
    closeChipMenu();
    renderChips();
    renderBranches();
    updateCommitButton();
    schedulePreview();
    getEl('tagFilterInput')?.focus();
  }

  function setBranchEnabled(index, enabled) {
    const branch = stagedBranches[Number(index)];
    if (!branch) return;
    branch.enabled = !!enabled;
    renderBranches();
    schedulePreview();
  }

  function removeBranch(index) {
    const [removed] = stagedBranches.splice(Number(index), 1);
    if (removed && branchSig(removed.tags) === selectedSig) selectedSig = '';
    renderBranches();
    schedulePreview();
  }

  function selectRow(index) {
    const branch = stagedBranches[Number(index)];
    if (!branch) return;
    const sig = branchSig(branch.tags);
    selectedSig = selectedSig === sig ? '' : sig;
    renderBranches();
  }

  /** 칸 오른쪽 끝의 Clear: 그 칸(include 또는 exclude)의 칩과 글자만 비운다. 스테이징은 그대로. */
  function clearList(list) {
    const which = String(list) === 'exclude' ? 'exclude' : 'include';
    closeChipMenu();
    const input = getEl(which === 'exclude' ? 'tagFilterExcludeInput' : 'tagFilterInput');
    if (input) input.value = '';
    clearAutocomplete();
    if (which === 'exclude') excludeTags = [];
    else includeTags = [];
    renderChips();
    renderBranches();
    schedulePreview();
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
    if (!host) {
      // 자리는 index.html 이 둔다(Save Filter·Filters 줄 아래). 없으면(옛 마크업) 저장 내역 뒤에 만든다.
      const anchor = getEl('tagFilterPresets') || getEl('tagFilterExcludeChips');
      if (!anchor || !anchor.parentNode) return null;
      host = doc.createElement('div');
      host.id = 'tagFilterBranches';
      host.className = 'tfb';
      anchor.parentNode.insertBefore(host, anchor.nextSibling);
    }
    // ⚠️ 스타일은 자리를 찾은 **뒤에** - 자리 없는 문서(시험의 가짜 문서)에서 createElement 를 부르면 죽는다.
    ensureBranchStyle();
    if (host._tfbBound) return host;
    host._tfbBound = true;
    // 다시 그려도 그대로인 뿌리에 위임으로 받는다.
    host.addEventListener('click', event => {
      const target = event.target.closest('[data-tfb]');
      if (target && target.disabled) return;
      const row = event.target.closest('[data-tfb-i]');
      const index = Number(row?.dataset.tfbI);
      const action = target?.dataset.tfb;
      if (action === 'stage') stageBranch();
      else if (action === 'commit') commit({takeText: true});
      else if (action === 'undo') undoCommit();
      else if (action === 'temp') tempApplySelected();
      else if (action === 'revert') revertTemp();
      else if (action === 'toggle') setBranchEnabled(index, !stagedBranches[index]?.enabled);
      else if (action === 'remove') removeBranch(index);
      else if (row) selectRow(index);          // 줄의 빈 곳 = 고르기 -> 아래에 [임시 적용][적용 취소]
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
    const piece = token => show(token);
    const inc = tags.filter(t => !t.startsWith('-')).map(piece).join(', ');
    const exc = tags.filter(t => t.startsWith('-')).map(piece).join(', ');
    return `${inc || '<span class="tfb-base">(전체)</span>'}${exc ? ` <span class="tfb-x">− ${exc}</span>` : ''}`;
  }

  function renderBranches() {
    const host = ensureBranchHost();
    if (!host) return;
    const canStage = hasChips() && !isStaged(payload());
    const live = enabledBranches().length > 0 && liveIsNew();
    const rows = stagedBranches.map((branch, i) => {
      const sig = branchSig(branch.tags);
      const temp = !!tempSig && sig === tempSig;
      return `
      <div class="tfb-row is-pick${branch.enabled ? '' : ' is-off'}${sig === selectedSig ? ' is-sel' : ''}${temp ? ' is-temp' : ''}" data-tfb-i="${i}"
        title="눌러서 고르면 아래에서 이 조합만 임시로 적용해 볼 수 있습니다">
        <button type="button" class="tfb-on" data-tfb="toggle" aria-pressed="${branch.enabled}" title="${branch.enabled ? '커밋에서 빼기' : '커밋에 넣기'}"></button>
        <span class="tfb-text">${branchLabelHtml(branch.tags)}</span>
        ${temp ? '<span class="tfb-temp">임시 적용 중</span>' : ''}
        <span class="tfb-n">${branch.enabled || temp ? branchCountText(branch.tags) : '꺼짐'}</span>
        <button type="button" class="tfb-del" data-tfb="remove" title="스테이징에서 빼기">×</button>
      </div>`;
    }).join('');
    const liveRow = live ? `
      <div class="tfb-row is-live">
        <span class="tfb-on is-live" aria-hidden="true"></span>
        <span class="tfb-text"><em>지금 검색</em> ${branchLabelHtml(payload())}</span>
        <span class="tfb-n">${branchCountText(payload())}</span>
        <span class="tfb-del" aria-hidden="true"></span>
      </div>` : '';
    const draft = branchesPayload();
    const draftText = !draft.length ? '' : previewCounts
      ? `커밋하면 ${(filteredCount(previewCounts, deps.getRatingState()) || 0).toLocaleString()}행` : '커밋하면 …';
    const hint = draftText || (stagedBranches.length ? `${stagedBranches.length}개 담김` : '검색해 보고 마음에 들면 담기');
    const selected = stagedBranches.some(branch => branchSig(branch.tags) === selectedSig);
    const acts = selected || tempSig ? `
      <div class="tfb-acts">
        <button type="button" class="tfb-act" data-tfb="temp" ${selected && selectedSig !== tempSig ? '' : 'disabled'}
          data-naia-guide="고른 조합 하나만 지금 풀에 걸어 봅니다(커밋은 그대로). 담은 것을 오가며 태그를 빠르게 바꿔 볼 때.">임시 적용</button>
        <button type="button" class="tfb-act revert" data-tfb="revert" ${tempSig ? '' : 'disabled'}
          data-naia-guide="임시 적용을 거두고 마지막 커밋 상태로 돌아갑니다.">적용 취소</button>
      </div>` : '';
    host.innerHTML = `
      <div class="tfb-head">
        <span class="tfb-title">스테이징</span>
        <span class="tfb-hint">${hint}</span>
      </div>
      <div class="tfb-btns">
        <button type="button" class="tfb-stage" data-tfb="stage" ${canStage ? '' : 'disabled'}
          data-naia-guide="지금 검색(칩)을 스테이징에 담습니다. 칩은 그대로 남으니 몇 개만 고쳐 다음 검색을 이어 가세요.">+ 담기</button>
        <button type="button" class="tag-filter-btn-action assign tfb-commit" id="tagFilterCommitBtn" data-tfb="commit"
          data-naia-guide="켜진 담은 것들과 지금 검색을 합쳐 풀에 겁니다. 이 단추를 누르기 전까지 풀은 그대로입니다(칩·스테이징은 미리보기). 같은 조건으로 다시 걸 때도 누르세요.">커밋 (적용)</button>
        <button type="button" class="tfb-undo" id="tagFilterUndoBtn" data-tfb="undo" ${commitHistory.length ? '' : 'disabled'}
          data-naia-guide="마지막 커밋을 거두고, 그 커밋 직전의 풀로 돌아갑니다.">커밋 취소</button>
      </div>
      ${stagedBranches.length ? `<div class="tfb-list">${rows}${liveRow}</div>` : ''}${acts}`;
    updateCommitButton();
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

  /** 미리보기: 초안(칩·스테이징)의 행 수만 센다 - 풀은 그대로(assign 하지 않는다).
   *  ⚠️ 적용이 도는 중이면 끝난 뒤로 미룬다. 서버는 더 새 검색이 시작되면 옛 검색의 결과를 **말없이
   *     버린다**(seq 가드) - 미리보기가 끼어들면 적용 결과가 사라져 풀이 안 바뀐다. */
  function sendPreviewNow() {
    cancelPendingSearch();
    if (applyInFlight) { previewQueued = true; return false; }
    const branches = branchesPayload();
    if (!branches.length) {
      previewCounts = null;
      previewRequestId = '';
      renderBranches();
      return false;
    }
    if (!isSocketOpen()) return false;
    lastSentBranches = branches;
    previewRequestId = nextSearchRequestId();
    send({type: 'tag_filter_search', tags: payload(), branches, request_id: previewRequestId});
    return true;
  }

  function schedulePreview(options = {}) {
    cancelPendingSearch();
    if (options.save !== false) save();          // 초안은 저장한다(풀과 무관)
    previewCounts = null;
    renderBranches();
    searchDebounceTimer = setTimeout(sendPreviewNow, SEARCH_DEBOUNCE_MS);
  }

  /** 조합을 풀에 건다(검색 -> assign). 빈 조합이면 필터를 뗀다. mode = commit|undo|temp|revert|reapply.
   *  ⚠️ 검색 `tags` 에는 **초안 칩**을 싣는다 - 백엔드 commit 이 그것을 칩(tag_filter)으로 저장하므로,
   *     걸린 조합을 실으면 임시 적용 한 번에 초안이 덮인다. 걸리는 것은 `branches` 다(있으면 tags 는 무시). */
  function applyConfig(branches, mode) {
    cancelPendingSearch();
    const target = cloneBranches(branches).filter(tags => tags.length);
    if (!target.length) { unassign(); return true; }
    if (!isSocketOpen()) return false;
    lockTagSurface('tagfilter');   // background tag-filter search → released by onTagFilterResult/Assigned
    applyInFlight = {branches: target, mode};
    applyRequestId = nextSearchRequestId();
    send({type: 'tag_filter_search', tags: payload(), branches: target, request_id: applyRequestId});
    return true;
  }

  /** 풀에서 필터만 뗀다 - 초안(칩·스테이징)은 남긴다(keep_draft). */
  function unassign() {
    applyInFlight = null;
    applyRequestId = '';
    appliedBranches = [];
    active = false;
    ratingCounts = null;
    // ⚠️ 초안을 **먼저** 저장하고 뗀다. 떼기의 응답(search_state)이 서버의 초안을 싣고 돌아와 화면 칩을
    //    덮는다 - 거꾸로면 방금 되돌린 칩(우클릭 [되돌리기])이 옛 초안으로 다시 덮였다(라이브 실측).
    save();
    send({type: 'tag_filter_clear', keep_draft: true});
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = '';
      countEl.classList.remove('has-result');
    }
    const toggleBtn = getEl('tagFilterToggle');
    if (toggleBtn) toggleBtn.classList.remove('active', 'assigned');
    const restored = deps.computeLocalFilteredCount();
    if (restored !== null && restored !== undefined) deps.updateSearchCount(restored);
    renderBranches();
    notifyFilterChanged();
    flushAssignedOnce();
    if (previewQueued) { previewQueued = false; sendPreviewNow(); }
  }

  /** [커밋 (적용)] - 초안(켜진 담은 것들 + 지금 칩)을 풀에 건다. 직전 풀은 [커밋 취소] 로 돌아갈 수 있게 쌓는다.
   *  초안이 비었으면 필터를 뗀다. 같은 조건으로 다시 거는 것도 커밋이다(풀을 다 쓴 뒤 - 사용자 제보 2026-08-31). */
  function commit(options = {}) {
    if (options.takeText) commitPendingInputs({preview: false});
    const target = branchesPayload();
    commitHistory.push(cloneBranches(appliedBranches));
    if (commitHistory.length > 20) commitHistory.shift();
    committedBranches = cloneBranches(target);
    tempSig = '';
    save();
    applyConfig(target, 'commit');
    renderBranches();
  }

  /** [커밋 취소] - 마지막 커밋을 거두고 그 직전의 풀로(병합 전 상태). 초안은 건드리지 않는다. */
  function undoCommit() {
    if (!commitHistory.length) return;
    const previous = commitHistory.pop();
    committedBranches = cloneBranches(previous);
    tempSig = '';
    applyConfig(previous, 'undo');
    renderBranches();
  }

  /** [임시 적용] - 고른 담은 것 하나만 풀에 건다(커밋은 그대로). */
  function tempApplySelected() {
    const branch = stagedBranches.find(item => branchSig(item.tags) === selectedSig);
    if (!branch) return;
    tempSig = selectedSig;
    applyConfig([branch.tags], 'temp');
    renderBranches();
  }

  /** [적용 취소] - 임시 적용을 거두고 마지막 커밋 조합으로. */
  function revertTemp() {
    if (!tempSig) return;
    tempSig = '';
    applyConfig(committedBranches, 'revert');
    renderBranches();
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
        pickAutocomplete(acResults[+item.dataset.idx].tag);
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

  /** 목록에서 고른 태그 + 칸에 먼저 쳐 둔 앞 조각들을 칩으로(앞 조각이 사라지지 않게). */
  function pickAutocomplete(tag) {
    const input = getEl(acTarget === 'exclude' ? 'tagFilterExcludeInput' : 'tagFilterInput');
    selectAutocomplete([...leadingSegments(input ? input.value : ''), tag].join(','));
  }

  function selectAutocomplete(tag) {
    if (!normalizeTags([tag]).length) return;
    const changed = commitTags(acTarget, tag);
    const input = getEl(acTarget === 'exclude' ? 'tagFilterExcludeInput' : 'tagFilterInput');
    if (input) input.value = '';
    clearAutocomplete();
    updateCommitButton();
    if (changed) schedulePreview();   // 커밋 모델: 칩은 미리보기 - 풀은 [커밋 (적용)] 이 바꾼다
  }

  /** 입력칸에 친 글자를 칩으로. 풀은 건드리지 않는다(커밋 모델) - 다시 거는 것은 [커밋 (적용)] 이 한다
   *  (빈 입력에서도 같은 조건으로 다시 건다 - 랜덤 풀이 소진된 뒤 빠져나갈 길, 사용자 제보 2026-08-31). */
  function commitPendingInputs(options = {}) {
    const includeInput = getEl('tagFilterInput');
    const excludeInput = getEl('tagFilterExcludeInput');
    const includeText = includeInput ? includeInput.value.trim() : '';
    const excludeText = excludeInput ? excludeInput.value.trim() : '';
    if (!includeText && !excludeText) return false;
    let changed = false;
    if (includeText) changed = commitTags('include', includeText) || changed;
    if (excludeText) changed = commitTags('exclude', excludeText) || changed;
    if (includeInput) includeInput.value = '';
    if (excludeInput) excludeInput.value = '';
    clearAutocomplete();
    updateCommitButton();
    if (changed && options.preview !== false) schedulePreview();
    return changed;
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
      const query = lastSegment(this.value);
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
          pickAutocomplete(acResults[acSelection].tag);
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
    // 칸 Clear·마지막 칩 지우기처럼 **스테이징과 무관한** 해제는 담은 것(꺼 둔 것 포함)을 남긴다.
    if (!options.keepBranches) {
      stagedBranches = [];
      branchCounts.clear();
      commitHistory.length = 0;
      selectedSig = '';
    }
    appliedBranches = [];
    lastApplied = [];
    committedBranches = [];
    tempSig = '';
    applyInFlight = null;
    applyRequestId = '';
    previewCounts = null;
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
    appliedBranches = [];
    applyInFlight = null;
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
    excludeTags.splice(index, 1);
    renderExcludeChips();
    updateCommitButton();
    schedulePreview();
  }

  function removeIncludeTag(index) {
    closeChipMenu();
    includeTags.splice(index, 1);
    renderIncludeChips();
    updateCommitButton();
    schedulePreview();
  }

  /** 바깥의 명시 적용(프롬프트 우클릭 · applyTagFilter) = 커밋. 패널 안의 편집은 미리보기다. */
  function apply() {
    commit({takeText: false});
  }

  // ── 프롬프트 우클릭에서 들어오는 입구 (사용자 요청 2026-08-31) ────────────
  //
  // ⚠️ 칩 목록을 바깥에서 직접 만지지 못하게 한다. 필터 상태의 주인은 여기 하나다 -
  //    두 곳이 만지면 화면(칩)과 실제(적용된 필터)가 갈린다.

  function snapshotTags() {
    return {include: [...includeTags], exclude: [...excludeTags], active, history: commitHistory.length};
  }

  /** 스냅샷으로 되돌리고 **풀도** 그때로 돌린다. 스냅샷 뒤에 커밋이 있었으면 그 커밋들을 거둔다
   *  (= 커밋 취소 - 병합 전 풀). 초안 칩도 그때로. */
  function restoreTags(snapshot) {
    includeTags = normalizeTags(snapshot && snapshot.include);
    excludeTags = normalizeTags(snapshot && snapshot.exclude);
    renderChips();
    updateHighlight();
    // 초안이 바뀌었다 - 적용(또는 떼기)이 끝나면 미리보기 수를 다시 센다.
    previewCounts = null;
    previewQueued = true;
    const mark = snapshot && Number.isInteger(snapshot.history) ? snapshot.history : null;
    if (mark !== null && commitHistory.length > mark) {
      commitHistory.length = mark + 1;
      undoCommit();
      return;
    }
    if (snapshot && snapshot.active === false) { unassign(); return; }
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

  /** 프롬프트 우클릭 '제거' - 칩을 빼고 곧장 적용(명시 적용 = 커밋). */
  function removeTagAt(list, index) {
    if (String(list) === 'exclude') removeExcludeTag(index);
    else removeIncludeTag(index);
    apply();
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
    previewCounts = null;
    // 걸려 있던 조합을 새 풀에 다시 건다(초안이 아니다 - 커밋 모델).
    const target = hasApplied() ? appliedBranches : lastApplied;
    // Clear the stale label explicitly — renderMatchedCount() no-ops while
    // ratingCounts is null, so it would otherwise leave the old '982,029 matched'.
    const countEl = getEl('tagFilterCount');
    if (countEl) {
      countEl.textContent = target.length ? '재적용 중…' : '';
      countEl.classList.remove('has-result');
    }
    if (target.length) {
      // Pool-swap search_state releases the 'pool' lock immediately after this
      // callback. Raise the independent tag-filter lock synchronously, without
      // the normal 280 ms typing debounce, so Random never sees the unfiltered
      // replacement pool in that gap.
      save();
      applyConfig(target, 'reapply');
    } else if (hasFilter()) {
      schedulePreview({save: false});
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
    const hasTags = hasApplied() || lastApplied.length > 0;
    // 진짜 적용됐던 필터 + 칩이 있을 때만 '해제됨' 오버레이. 미적용 draft 칩엔 안 띄운다(MED).
    if (!filterWasApplied || !hasTags) { setReleasedOverlay(false); return false; }
    active = false;
    ratingCounts = null;
    appliedBranches = [];
    applyInFlight = null;
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
    // [재적용]: 걸려 있던 조합(lastApplied)을 새 풀에 재적용. applyConfig 가 'tagfilter' 잠금을 걸고,
    // onResult→assign→assigned 가 active=true 로 재적용/재영속한다(스캔 전체 잠금은
    // 백엔드 announce + Fix 1 이 result~assigned 창까지 유지).
    if (!lastApplied.length) { setReleasedOverlay(false); return; }
    save();
    // 소켓이 끊겨 실제 전송이 안 되면 오버레이를 유지한다 — "재적용됨"으로 거짓 표시 방지(LOW).
    if (applyConfig(lastApplied, 'reapply')) setReleasedOverlay(false);
  }

  function resetReleased() {
    // [초기화]: 칩/필터를 모두 해제.
    setReleasedOverlay(false);
    clearFilter();
  }

  function assign() {
    send({type: 'tag_filter_assign', request_id: applyRequestId});
  }

  /** 검색 결과. 적용 요청이면 assign 으로 넘기고(잠금 유지 = false), 미리보기면 수만 그린다. */
  function onResult(message) {
    const id = message.request_id || '';
    const perBranch = Array.isArray(message.branch_rating_counts) ? message.branch_rating_counts : [];
    if (id && id === applyRequestId && applyInFlight) {
      applyInFlight.branches.forEach((tags, i) => { if (perBranch[i]) branchCounts.set(branchSig(tags), perBranch[i]); });
      assign();
      return false;
    }
    if (id && id === previewRequestId) {
      previewCounts = message.rating_counts || null;
      lastSentBranches.forEach((tags, i) => { if (perBranch[i]) branchCounts.set(branchSig(tags), perBranch[i]); });
      renderBranches();
      return true;
    }
    return legacyResult(message);
  }

  // 요청 번호가 없는 결과(tag_filter_clear 의 응답) - 풀도 수도 바꾸지 않는다(unassign 이 이미 비웠다).
  // 번호가 있는데 모르는 것(늦게 온 옛 요청)은 false - 도는 적용의 잠금을 남긴다.
  function legacyResult(message) {
    if (message.request_id) return false;
    pendingAssignOnRestore = false;
    return true;
  }

  function onAssigned(message) {
    if (message.request_id && message.request_id !== applyRequestId) {
      return false;
    }
    // A different tab can commit a newer assignment while this request's
    // websocket send is delayed. Unlock this completed local request, but never
    // repaint the shared UI with its older authoritative state.
    if (!noteAuthoritativeRevision(message.tag_filter_revision)) return true;
    active = true;
    filterWasApplied = true;
    if (applyInFlight) {
      appliedBranches = cloneBranches(applyInFlight.branches);
      lastApplied = cloneBranches(appliedBranches);
    }
    applyInFlight = null;
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
    renderBranches();
    if (previewQueued) { previewQueued = false; sendPreviewNow(); }
    return true;
  }

  function onStale(message) {
    if (message.request_id && message.request_id !== applyRequestId) {
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
    if (!applyInFlight) return true;
    return !applyConfig(applyInFlight.branches, applyInFlight.mode);
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
    const currentQuery = lastSegment(input ? input.value : '');
    if (!input || currentQuery.length < 2) return;
    // 서버는 표식(*)을 뺀 질의를 되돌려 준다 - 같은 자로 견준다.
    const query = String(message.query || '').trim();
    if (query && baseTag(query) !== baseTag(currentQuery)) return;
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
      && JSON.stringify(stagedBranches) === JSON.stringify(pref.tag_filter_branches)
      && JSON.stringify(appliedBranches) === JSON.stringify(pref.tag_filter_active ? pref.tag_filter_applied_branches : []);

    setActiveRatings(pref.ratings);
    // ⚠️ 칩 배열이 통째로 바뀌면 열린 메뉴는 닫는다. 메뉴는 **인덱스**로 칩을 가리키는데,
    //    백엔드 권위 상태는 모든 탭에 적용되므로 다른 탭이 앞쪽 칩을 지우면 인덱스가
    //    밀려 **다음 클릭이 엉뚱한 칩의 exact 를 뒤집는다**(Codex 지적). 로컬 × 경로만
    //    닫는 것으로는 모자란다.
    if (!sameTags) closeChipMenu();
    includeTags = [...pref.tag_filter];
    excludeTags = [...pref.tag_filter_exclude];
    stagedBranches = pref.tag_filter_branches.map(branch => ({tags: [...branch.tags], enabled: branch.enabled}));
    active = pref.tag_filter_active;
    // 지금 풀에 걸린 조합. 옛 저장값(적용 조합 없이 칩만 활성)은 칩 한 벌이 걸린 것이다.
    if (!applyInFlight) {
      const legacy = pref.tag_filter.length || pref.tag_filter_exclude.length
        ? [[...pref.tag_filter, ...pref.tag_filter_exclude.map(tag => '-' + tag)]] : [];
      appliedBranches = active ? cloneBranches(pref.tag_filter_applied_branches.length ? pref.tag_filter_applied_branches : legacy) : [];
      if (appliedBranches.length) lastApplied = cloneBranches(appliedBranches);
      if (!tempSig) committedBranches = cloneBranches(appliedBranches);
    }
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
      // 복원: 걸려 있던 **조합**을 다시 건다(초안이 아니다). 초안은 미리보기만.
      if (active && hasApplied()) applyConfig(appliedBranches, 'reapply');
      else if (hasFilter()) schedulePreview({save: false});
    } else if (!sameTags && hasFilter()) {
      schedulePreview({save: false});
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
    schedulePreview();   // 초안으로 불러온다 - 풀은 [커밋 (적용)] 이 바꾼다(등급은 안 건드림 — 프리셋은 태그만)
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
    stageBranch,
    clearList,
    commit,
    undoCommit,
    tempApplySelected,
    revertTemp,
    selectRow,
    getAppliedBranches: () => cloneBranches(appliedBranches),
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
