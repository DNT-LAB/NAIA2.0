import { RATING_KEYS, filteredCount } from './ratingStore.mjs';

const STORAGE_KEY = 'naia_quick_filter_options';
const DEFAULT_RATING_KEYS = ['g', 's', 'q'];
const SEARCH_DEBOUNCE_MS = 280;

function normalizeTagParts(value) {
  const text = String(value || '');
  return text.split(/[,\n]/)
    .map(item => item.replace(/_/g, ' ').trim().replace(/^-+/, '').replace(/ /g, '_'))
    .filter(Boolean);
}

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

export function normalizePreferences(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const include = normalizeTags(raw.tag_filter || raw.include || raw.include_tags);
  const exclude = normalizeTags(raw.tag_filter_exclude || raw.exclude || raw.exclude_tags);
  return {
    ratings: normalizeRatings(raw.ratings),
    tag_filter: include,
    tag_filter_exclude: exclude,
    tag_filter_active: !!raw.tag_filter_active && (include.length > 0 || exclude.length > 0),
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

  const getEl = id => doc.getElementById(id);
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
    const countEl = getEl('tagFilterCount');
    if (!countEl) return;
    const hasTags = includeTags.length > 0 || excludeTags.length > 0;
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
    const popup = getEl('tagFilterPopup');
    if (!popup || !popup.classList.contains('open')) return;
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
    button.disabled = !hasPendingText;
  }

  function load() {
    return loadPreferences(storage);
  }

  function renderIncludeChips() {
    const el = getEl('tagFilterChips');
    if (!el) return;
    if (!includeTags.length) {
      el.innerHTML = '';
      return;
    }
    el.innerHTML = includeTags.map((tag, index) =>
      `<span class="tag-filter-chip">${deps.escHtml(tag)}<span class="chip-x" onclick="removeTagFilterTag(${index})">&times;</span></span>`
    ).join('');
  }

  function renderExcludeChips() {
    const el = getEl('tagFilterExcludeChips');
    if (!el) return;
    if (!excludeTags.length) {
      el.innerHTML = '';
      return;
    }
    el.innerHTML = excludeTags.map((tag, index) =>
      `<span class="tag-filter-chip exclude">${deps.escHtml(tag)}<span class="chip-x" onclick="removeTagFilterExcludeTag(${index})">&times;</span></span>`
    ).join('');
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
    if (!includeTags.length && !excludeTags.length) return false;
    if (!isSocketOpen()) return false;
    lockTagSurface('tagfilter');   // background tag-filter search → released by onTagFilterResult/Assigned
    send({type: 'tag_filter_search', tags: payload(), request_id: nextSearchRequestId()});
    return true;
  }

  function scheduleSearch() {
    if (!includeTags.length && !excludeTags.length) return;
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
    const tags = normalizeTags([rawValue]);
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
    if (!includeText && !excludeText) return;
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
        send({type: 'tag_filter_ac', query});
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
    bindAutocompleteInput('tagFilterInput', 'include');
    bindAutocompleteInput('tagFilterExcludeInput', 'exclude');
    bindPresetTooltip();
    updateCommitButton();
  }

  function open() {
    const popup = getEl('tagFilterPopup');
    if (!popup) return;
    deps.closeAuxiliaryPopups(popup);
    popup.classList.add('open');
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
    const popup = getEl('tagFilterPopup');
    if (!popup) return;
    if (popup.classList.contains('open')) close();
    else open();
  }

  function clearFilter(options = {}) {
    const sendClear = options.sendClear !== false;
    const persist = options.persist !== false;

    includeTags = [];
    excludeTags = [];
    active = false;
    filterWasApplied = false;
    ratingCounts = null;
    pendingAssignOnRestore = false;
    invalidateSearchRequest();
    cancelPendingSearch();
    renderIncludeChips();
    renderExcludeChips();
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
    excludeTags.splice(index, 1);
    renderExcludeChips();
    updateCommitButton();
    if (!includeTags.length && !excludeTags.length) {
      clearFilter();
      return;
    }
    apply();   // U1: 남은 칩으로 즉시 재검색 → 자동 적용 (캐시 재조합, 스캔 0)
  }

  function removeIncludeTag(index) {
    includeTags.splice(index, 1);
    renderIncludeChips();
    updateCommitButton();
    if (!includeTags.length && !excludeTags.length) {
      clearFilter();
      return;
    }
    apply();   // U1: 남은 칩으로 즉시 재검색 → 자동 적용 (캐시 재조합, 스캔 0)
  }

  function apply() {
    if (!includeTags.length && !excludeTags.length) return;
    save();
    if (!isSocketOpen()) return;
    scheduleSearch();
  }

  // Custom parquet load/merge swapped the pool: the backend deactivated the
  // filter and kept the chips as a draft, so the cached 'N matched' count is now
  // stale (old pool). Auto re-apply the chips to the NEW pool (fresh search +
  // assign) so the filter follows the dataset and the counts recompute. Old
  // counts are invalidated first so no stale label flashes before the fresh
  // result lands.
  function onPoolSwap() {
    ratingCounts = null;
    const hasTags = includeTags.length > 0 || excludeTags.length > 0;
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
    const hasTags = includeTags.length > 0 || excludeTags.length > 0;
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
    const hasTags = includeTags.length > 0 || excludeTags.length > 0;
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
    const hasTags = !!(message.tags && message.tags.length);
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
    const popup = getEl('tagFilterPopup');
    if (!popup || !popup.classList.contains('open')) return;
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
      && JSON.stringify([...excludeTags].sort()) === JSON.stringify([...pref.tag_filter_exclude].sort());

    setActiveRatings(pref.ratings);
    includeTags = [...pref.tag_filter];
    excludeTags = [...pref.tag_filter_exclude];
    active = pref.tag_filter_active;
    if (!sameTags) ratingCounts = null;   // 칩이 바뀌면 옛 카운트는 무효
    renderIncludeChips();
    renderExcludeChips();
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

    if (options.send !== false && isSocketOpen()) {
      send({type: 'set_active_ratings', ratings: pref.ratings});
      const tags = payload();
      if (tags.length) {
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
  };
}
