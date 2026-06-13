import { createRatingStore, RATING_KEYS, filteredCount } from './ratingStore.mjs';

export function createSearchPanel({
  document,
  moduleBody,
  searchCountEl,
  escHtml,
  getWs,
  WebSocket,
  getQuickFilter,
  getCurrentModuleId,
  bindTagAssist,
}) {
  let searchingActive = false;
  let initialFilterRestoreDone = false; // 시작 시 Tag Filter 자동 Search→Assign 1회 가드
  // Rating state lives in one store holding BOTH the generation-pool ratings
  // (active) and the search-execution ratings (search) — distinct concepts,
  // managed together. ratingState/searchRatingState alias the store's live
  // objects so existing in-place reads/writes keep working; the Quick/Tag Filter
  // shares the same store via deps instead of mutating these by reference.
  const ratingStore = createRatingStore();
  const ratingState = ratingStore.active;
  const searchRatingState = ratingStore.search;
  // Rating toggles are always live: local state + count update instantly and the
  // set_active_ratings push is debounced so a burst of clicks coalesces into one
  // backend recompute. No button lock — the backend never emits a rating_update,
  // so the previous lock only ever released via its 4s safety timeout, which read
  // as a fixed minimum delay between rating clicks.
  let ratingSendTimer = null;
  let cachedRatingCounts = null;
  let parquetPickMode = 'load';
  // Render-once model (A4): the search DOM is built once per module open and then
  // patched in place, so the input nodes — and any autocomplete popup bound to
  // them — survive every search_state update (the old full innerHTML rebuild used
  // to destroy the focused field and dismiss its autocomplete). The previous
  // draftSearch shadow is gone: the live input value IS the source of truth while
  // focused. The only residual reconciliation is pendingEcho — the value we just
  // committed to the backend, kept authoritative until the server echoes it back,
  // guarding against a stale search_state overwriting a freshly typed-and-saved
  // value after blur.
  // pendingEcho tracks, per field, the value we just committed to the backend and
  // are awaiting an echo of. A field stays authoritative (incoming server values
  // skipped) until its own echo arrives — so a normalized/diverging sibling field
  // can't freeze it — and re-focusing the field drops its guard (the user is
  // editing again).
  let pendingEcho = { query: null, exclude: null };
  let lastParquetSig = null;

  document.addEventListener('click', event => {
    if (!event.target.closest('.search-parquet-control')) closeParquetMenu();
  });

  function getRatingState() {
    return ratingState;
  }

  function getActiveRatings() {
    return RATING_KEYS.filter(key => ratingState[key]);
  }

  function setRatingState(nextState) {
    Object.assign(ratingState, nextState);
  }

  function setRatingsFromList(ratings) {
    if (!Array.isArray(ratings)) return;
    for (const key of RATING_KEYS) {
      ratingState[key] = ratings.includes(key);
    }
  }

  function setSearchRatingsFromMap(ratings) {
    if (!ratings || typeof ratings !== 'object') return;
    for (const key of RATING_KEYS) {
      if (key in ratings) searchRatingState[key] = !!ratings[key];
    }
  }

  function setRatingCounts(ratingCounts) {
    if (ratingCounts) cachedRatingCounts = ratingCounts;
  }

  function computeLocalFilteredCount() {
    const quickFilter = getQuickFilter();
    const quickRatingCounts = quickFilter ? quickFilter.getRatingCounts() : null;
    const ratingCounts = (quickFilter && quickFilter.isActive() && quickRatingCounts)
      ? quickRatingCounts
      : cachedRatingCounts;
    if (!ratingCounts || !Object.keys(ratingCounts).length) return null;
    return filteredCount(ratingCounts, ratingState);
  }

  function updateSearchCount(count) {
    searchCountEl.textContent = count;
  }

  function updatePromptGeneratedCount(message) {
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    const filtered = computeLocalFilteredCount();
    updateSearchCount(filtered !== null ? filtered : message.remaining);
  }

  function sendActiveRatings() {
    const ws = getWs();
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'set_active_ratings', ratings: getActiveRatings() }));
    }
  }

  function collectFilterState() {
    return {
      query: (document.getElementById('searchQuery') || {}).value || '',
      exclude: (document.getElementById('searchExclude') || {}).value || '',
      ratings: getActiveRatings(),
    };
  }

  function serverSearchText(message, key) {
    const hasDirect = message && Object.prototype.hasOwnProperty.call(message, key);
    const direct = hasDirect
      ? String(message[key] || '')
      : '';
    if (hasDirect) return direct;
    const preferences = message && message.filter_preferences;
    if (preferences && Object.prototype.hasOwnProperty.call(preferences, key)) {
      return String(preferences[key] || '');
    }
    return direct;
  }

  function serverSearchTexts(message) {
    return {
      query: serverSearchText(message, 'query'),
      exclude: serverSearchText(message, 'exclude'),
    };
  }

  function saveFilterState(extra = {}) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const state = {
      type: 'save_search_filter_state',
      ...collectFilterState(),
      ...extra,
    };
    // Hold each field authoritative until the backend echoes it (see pendingEcho).
    pendingEcho = { query: String(state.query || ''), exclude: String(state.exclude || '') };
    ws.send(JSON.stringify(state));
  }

  function jsString(value) {
    return JSON.stringify(String(value || ''))
      .replace(/&/g, '\\u0026')
      .replace(/</g, '\\u003c')
      .replace(/>/g, '\\u003e')
      .replace(/"/g, '&quot;');
  }

  function closeParquetMenu() {
    const menu = moduleBody.querySelector('.search-parquet-menu');
    if (menu) menu.classList.remove('open');
  }

  function toggleParquetMenu(event) {
    if (event && typeof event.stopPropagation === 'function') event.stopPropagation();
    const menu = moduleBody.querySelector('.search-parquet-menu');
    if (menu) menu.classList.toggle('open');
  }

  function openParquetUpload(action) {
    const mode = action === 'merge' ? 'merge' : 'load';
    closeParquetMenu();
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.parquet';
    input.style.display = 'none';
    input.addEventListener('change', () => {
      const file = input.files && input.files[0];
      input.remove();
      if (file) uploadParquetFile(file, mode);
    }, {once: true});
    document.body.appendChild(input);
    input.click();
  }

  async function uploadParquetFile(file, mode) {
    const params = new URLSearchParams({
      action: mode === 'merge' ? 'merge' : 'load',
      filename: file.name || 'uploaded.parquet',
    });
    try {
      const response = await fetch(`/api/search/parquet/upload?${params}`, {
        method: 'POST',
        headers: {'Content-Type': 'application/octet-stream'},
        body: file,
      });
      if (!response.ok) {
        let message = 'Parquet upload failed';
        try {
          const data = await response.json();
          if (data && data.error) message = data.error;
        } catch (error) {
          // Keep the generic message when the server did not return JSON.
        }
        console.error(message);
      }
    } catch (error) {
      console.error('Parquet upload failed', error);
    }
  }

  function selectParquetMode(mode) {
    parquetPickMode = mode === 'merge' ? 'merge' : 'load';
    closeParquetMenu();
    const section = moduleBody.querySelector('.search-parquet-section');
    if (section) section.dataset.parquetMode = parquetPickMode;
    const hint = moduleBody.querySelector('.search-parquet-mode-label');
    if (hint) {
      hint.textContent = parquetPickMode === 'merge'
        ? '합칠 parquet을 아래에서 선택하세요'
        : '불러올 parquet을 아래에서 선택하세요';
    }
    const header = moduleBody.querySelector('.mod-section-label.mod-collapsible');
    const list = moduleBody.querySelector('.search-parquet-list');
    if (header) header.classList.add('open');
    if (list) list.classList.remove('collapsed');
  }

  function runParquetAction(action) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    closeParquetMenu();
    ws.send(JSON.stringify({type: 'search_parquet_action', action}));
  }

  function toggleRating(rating) {
    ratingState[rating] = !ratingState[rating];
    syncRatingButtons();
    // Instant local feedback from the cached per-rating counts — no wait for the
    // backend round-trip.
    const localCount = computeLocalFilteredCount();
    if (localCount !== null) updateSearchCount(localCount);
    // Debounce the authoritative push so a burst of toggles sends a single
    // set_active_ratings; the search_state reply reconciles the count.
    if (ratingSendTimer) clearTimeout(ratingSendTimer);
    ratingSendTimer = setTimeout(() => {
      ratingSendTimer = null;
      sendActiveRatings();
    }, 160);
    const quickFilter = getQuickFilter();
    if (quickFilter) {
      quickFilter.savePreferences();
      // 등급 토글 시 Tag Filter 팝업의 "N matched" 라벨도 즉시 재계산(캐시된 등급별 카운트 합).
      if (quickFilter.refreshCount) quickFilter.refreshCount();
    }
  }

  function onFilterReset(message) {
    const quickFilter = getQuickFilter();
    const serverPreferences = message.filter_preferences;
    if (serverPreferences) {
      setRatingsFromList(serverPreferences.ratings);
      if (quickFilter) {
        quickFilter.applyPreferences(serverPreferences, {send: false, updateCount: false});
      } else {
        syncRatingButtons();
      }
    } else {
      setRatingsFromList(['g', 's', 'q']);
      syncRatingButtons();
      if (quickFilter) quickFilter.reset({ persist: false });
    }
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    if (message.count != null) updateSearchCount(message.count);
  }

  function onRatingUpdate(message) {
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    const quickFilter = getQuickFilter();
    updateSearchCount(message.count || 0);
    if (message.active_ratings) {
      setRatingsFromList(message.active_ratings);
      syncRatingButtons();
    }
    if (quickFilter) quickFilter.updateHighlight();
  }

  function syncRatingButtons() {
    document.querySelectorAll('.rating-btn').forEach(button => {
      if (!button.dataset.r) return;
      button.classList.toggle('active', !!ratingState[button.dataset.r]);
    });
    const quickFilter = getQuickFilter();
    if (quickFilter) quickFilter.updateHighlight();
  }

  function onSearchState(message) {
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    updateSearchCount(message.count || 0);
    searchingActive = false;
    if (message.active_ratings) {
      setRatingsFromList(message.active_ratings);
    }
    setSearchRatingsFromMap(message.ratings);
    const quickFilter = getQuickFilter();
    if (quickFilter && quickFilter.setPresets) quickFilter.setPresets(message.filter_presets || []);
    const serverPreferences = message.filter_preferences;
    if (serverPreferences && quickFilter) {
      // 시작 후 첫 search_state 에서 영속된 Tag Filter 가 활성+태그 보유 시 자동 Search→Assign 1회.
      // (그 이후 search_state 는 기존대로 {send:false} — 카운트 갱신마다 재검색/재할당 방지)
      const hasActiveTags = serverPreferences.tag_filter_active
        && (((serverPreferences.tag_filter || []).length) || ((serverPreferences.tag_filter_exclude || []).length));
      const autoApply = !initialFilterRestoreDone && !!hasActiveTags;
      if (autoApply) initialFilterRestoreDone = true;
      quickFilter.applyPreferences(serverPreferences, {send: autoApply, updateCount: false});
    } else if (serverPreferences) {
      setRatingsFromList(serverPreferences.ratings);
      syncRatingButtons();
    } else {
      syncRatingButtons();
    }
    if (getCurrentModuleId() === 'search') renderSearch(message);
  }

  function onSearchProgress(message) {
    if (getCurrentModuleId() === 'search') {
      const progress = moduleBody.querySelector('.search-progress');
      if (progress) progress.textContent = `Searching... ${message.completed}/${message.total}`;
    }
  }

  // ── Render-once: build the DOM once, then patch it in place ──────────────────

  function renderSearch(message) {
    if (moduleBody.querySelector('#searchQuery')) {
      updateSearchPanel(message);
    } else {
      buildSearchPanel(message);
    }
  }

  function ratingCheckboxesHtml() {
    return [
      ['e', 'Explicit'], ['q', 'NSFW'], ['s', 'Sensitive'], ['g', 'General']
    ].map(([key, label]) =>
      `<label class="mod-checkbox-item">
      <input type="checkbox" id="sr_${key}" ${searchRatingState[key] ? 'checked' : ''}>
      <span class="mod-checkbox-label">${label}</span>
    </label>`
    ).join('');
  }

  function parquetSignature(message) {
    return JSON.stringify(message.parquets || []);
  }

  function parquetSectionHtml(message) {
    const files = message.parquets || [];
    if (!files.length) return '';
    const items = files.map(file =>
      `<div class="search-parquet-item" onclick="loadParquet(${jsString(file)})">${escHtml(file)}</div>`
    ).join('');
    return `<div class="search-parquet-section" data-parquet-mode="${parquetPickMode}">
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.parentElement.querySelector('.search-parquet-list')?.classList.toggle('collapsed')">
        Custom Parquets (${files.length}) <span class="mod-collapse-arrow">▶</span>
      </div>
      <div class="search-parquet-mode-label"></div>
      <div class="search-parquet-list collapsed">${items}</div>
    </div>`;
  }

  function bindSearchInputs() {
    const fieldByInputId = { searchQuery: 'query', searchExclude: 'exclude' };
    ['searchQuery', 'searchExclude'].forEach(id => {
      const element = moduleBody.querySelector(`#${id}`);
      if (!element) return;
      bindTagAssist(element, { excludeE621: true });
      // Re-focusing a field means the user is editing it again — drop its pending
      // echo guard so server values can flow back once they move on (and a fresh
      // guard is set on the next blur/change via saveFilterState).
      element.addEventListener('focus', () => { pendingEcho[fieldByInputId[id]] = null; });
      element.addEventListener('change', () => saveFilterState());
      element.addEventListener('blur', () => saveFilterState());
    });
    for (const key of ['e', 'q', 's', 'g']) {
      const checkbox = moduleBody.querySelector(`#sr_${key}`);
      if (!checkbox) continue;
      checkbox.addEventListener('change', () => {
        searchRatingState[key] = checkbox.checked;
      });
    }
  }

  function buildSearchPanel(message) {
    const searchText = serverSearchTexts(message);
    pendingEcho = { query: null, exclude: null };
    lastParquetSig = parquetSignature(message);
    moduleBody.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Remaining</div>
        <div class="search-count-display">${message.count || 0}</div>
      </div>
      <div class="search-top-actions">
        <div class="search-parquet-control">
          <button class="mod-action-btn mod-parquet" onclick="toggleSearchParquetMenu(event)" data-naia-guide="검색 결과셋(parquet) 입출력 메뉴. 저장된 결과셋을 불러오거나 현재 결과에 합치고, 현재 결과를 파일로 내보내거나 실행용으로 저장합니다.">Parquet</button>
          <div class="search-parquet-menu">
            <button type="button" onclick="openSearchParquetUpload('load')" data-naia-guide="불러오기 — 저장해 둔 커스텀 parquet 결과셋을 불러옵니다. 현재 검색 결과를 이 결과셋으로 대체합니다.">불러오기</button>
            <button type="button" onclick="openSearchParquetUpload('merge')" data-naia-guide="합치기 — 저장된 parquet 결과셋을 현재 결과에 이어붙입니다(union). 두 결과셋을 합쳐 더 넓은 풀을 만들 때 사용합니다.">합치기</button>
            <button type="button" onclick="searchParquetAction('export_results')" data-naia-guide="내보내기 — 현재 검색 결과셋을 커스텀 parquet 파일로 저장합니다. 나중에 불러오기·합치기로 재사용할 수 있습니다.">내보내기</button>
            <button type="button" onclick="searchParquetAction('save_runner')" data-naia-guide="실행파일 저장 — 현재 결과를 실행용 parquet(naia_temp_rows)로 저장합니다. 재시작·복구 시 이 풀에서 랜덤 프롬프트가 생성됩니다.">실행파일 저장</button>
          </div>
        </div>
        <button class="mod-action-btn mod-refine" onclick="openRefine()" data-naia-guide="심층검색(Refine) — 이미 검색된 결과셋을 아카이브 재스캔 없이 반복적으로 좁히고 합치는 작업대를 엽니다. 결과 위에서 추가 태그·범위로 단계적으로 다듬을 수 있습니다.">심층검색</button>
        <button class="mod-action-btn mod-restore" onclick="restoreSnapshot()" data-naia-guide="복원 — 태그 필터와 범위 좁히기를 모두 해제하고, 마지막 검색 결과셋(스냅샷) 전체로 되돌립니다.">복원</button>
      </div>
    </div>
    <div>
      <div class="dr-label-row">
        <span class="mod-section-label">Search Keyword</span>
        <button type="button" class="header-guide-btn" data-naia-guide="Search Keyword — 포함 검색(AND). 쉼표로 구분한 태그를 모두 포함하는 결과만 남깁니다.\\n\\n부분일치 — 기본은 부분 문자열 매칭입니다. 예: girl → 1girl·cowgirl 도 매칭, hair → long hair 도 매칭. (_ 는 공백으로 처리)\\n\\n{a|b|c} — OR 그룹. 중괄호 안 태그 중 하나라도 포함하면 매칭. 그룹끼리는 AND로 결합됩니다.\\n\\n*tag — 정확 태그 일치. 쉼표·공백 경계로 둘러싸인 정확한 토큰만 매칭. 예: *girl 은 girl 토큰만, 1girl·cowgirl 은 제외.">ⓘ 가이드</button>
      </div>
      <input class="mod-input" id="searchQuery" type="text" value="${escHtml(searchText.query)}" placeholder="tags, keywords...">
    </div>
    <div>
      <div class="dr-label-row">
        <span class="mod-section-label">Exclude Keyword</span>
        <button type="button" class="header-guide-btn" data-naia-guide="Exclude Keyword — 제외 검색. 입력한 태그가 든 결과를 빼냅니다. 포함 검색과 문법이 다릅니다.\\n\\ntag — 부분일치 제외. 해당 문자열이 든 행을 모두 제외합니다. 예: abs 는 absurdres 까지 함께 제외될 수 있습니다.\\n\\n~tag — 정확 태그 제외. 정확한 토큰만 제외합니다(부분일치 아님). 예: ~abs 는 abs 토큰만 제외하고 absurdres 는 유지.\\n\\n※ 제외 칸에서는 {a|b}·*tag 문법이 동작하지 않습니다(제외는 포함 문법의 부분집합).">ⓘ 가이드</button>
      </div>
      <input class="mod-input" id="searchExclude" type="text" value="${escHtml(searchText.exclude)}" placeholder="exclude tags...">
    </div>
    <div>
      <div class="dr-label-row">
        <span class="mod-section-label">Ratings</span>
        <button type="button" class="header-guide-btn" data-naia-guide="Ratings — 포함할 콘텐츠 등급. 켜진 등급의 결과만 검색합니다.\\n\\nExplicit — 명확한 성적인 행위가 있는 구도.\\n\\nNSFW — 확실한 노출이 있고 일부 성기 노출이 포함될 수 있는 구도, 또는 성적인 행위를 암시하는 구도.\\n\\nSensitive — 수영복이나 속옷 같은 일반적인 노출이 있는 구도.\\n\\nGeneral — 그 외의 일반적인 Safe 구도.">ⓘ 가이드</button>
      </div>
      <div class="mod-checkbox-grid">${ratingCheckboxesHtml()}</div>
    </div>
    ${dateRangeSliderHtml()}
    <div style="display:flex;gap:8px;align-items:center">
      <button class="mod-action-btn mod-start" onclick="doSearch()" ${searchingActive ? 'disabled' : ''}>검색</button>
      <span class="search-progress" style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)"></span>
    </div>
    <div class="search-parquet-host">${parquetSectionHtml(message)}</div>
  `;
    bindSearchInputs();
    ensureDateRangeStyle();
    bindDateRangeDrag();
    renderDateRange();
    requestBucketDates();
  }

  function applyInputValue(element, serverVal, guard, focusedEl) {
    if (!element || element === focusedEl) return; // never clobber the field being edited
    if (guard) return;                              // awaiting echo of a local commit
    if (element.value !== serverVal) element.value = serverVal;
  }

  function syncParquetSection(message) {
    const sig = parquetSignature(message);
    if (sig === lastParquetSig) return;
    lastParquetSig = sig;
    const host = moduleBody.querySelector('.search-parquet-host');
    if (!host) return;
    // Preserve the user's collapse / mode state across the in-place re-render.
    const prevList = host.querySelector('.search-parquet-list');
    const wasExpanded = !!prevList && !prevList.classList.contains('collapsed');
    const prevHeader = host.querySelector('.mod-section-label.mod-collapsible');
    const wasOpen = !!prevHeader && prevHeader.classList.contains('open');
    const prevModeLabel = host.querySelector('.search-parquet-mode-label');
    const prevModeText = prevModeLabel ? prevModeLabel.textContent : '';
    host.innerHTML = parquetSectionHtml(message);
    if (wasExpanded) {
      const list = host.querySelector('.search-parquet-list');
      if (list) list.classList.remove('collapsed');
    }
    if (wasOpen) {
      const header = host.querySelector('.mod-section-label.mod-collapsible');
      if (header) header.classList.add('open');
    }
    if (prevModeText) {
      const modeLabel = host.querySelector('.search-parquet-mode-label');
      if (modeLabel) modeLabel.textContent = prevModeText;
    }
  }

  function updateSearchPanel(message) {
    const countEl = moduleBody.querySelector('.search-count-display');
    if (countEl) countEl.textContent = message.count || 0;

    const server = serverSearchTexts(message);
    // Per-field: clear a field's guard once the server echoes that field's value,
    // so a sibling field that diverges (or never echoes exactly) can't keep it stuck.
    if (pendingEcho.query !== null && server.query === pendingEcho.query) pendingEcho.query = null;
    if (pendingEcho.exclude !== null && server.exclude === pendingEcho.exclude) pendingEcho.exclude = null;
    const focusedEl = document.activeElement;
    applyInputValue(moduleBody.querySelector('#searchQuery'), server.query, pendingEcho.query !== null, focusedEl);
    applyInputValue(moduleBody.querySelector('#searchExclude'), server.exclude, pendingEcho.exclude !== null, focusedEl);

    for (const key of ['e', 'q', 's', 'g']) {
      const checkbox = moduleBody.querySelector(`#sr_${key}`);
      if (checkbox) checkbox.checked = !!searchRatingState[key];
    }

    const button = moduleBody.querySelector('.mod-start');
    if (button) button.disabled = searchingActive;
    if (!searchingActive) {
      const progress = moduleBody.querySelector('.search-progress');
      if (progress) progress.textContent = '';
    }

    syncParquetSection(message);
  }

  function doSearch() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const query = (document.getElementById('searchQuery') || {}).value || '';
    const exclude = (document.getElementById('searchExclude') || {}).value || '';
    for (const key of ['e','q','s','g']) {
      const element = document.getElementById('sr_' + key);
      if (element) searchRatingState[key] = element.checked;
    }
    const ratings = {};
    for (const key of ['e','q','s','g']) {
      ratings['rating_' + key] = searchRatingState[key];
    }
    searchingActive = true;
    saveFilterState({query, exclude});
    const bucketRange = bucketState.loaded
      ? { bucket_start: bucketState.start, bucket_end: bucketState.end }
      : {};
    ws.send(JSON.stringify({ type: 'search', query, exclude, ...ratings, ...bucketRange }));
    const progress = moduleBody.querySelector('.search-progress');
    if (progress) progress.textContent = 'Starting...';
    const button = moduleBody.querySelector('.mod-start');
    if (button) button.disabled = true;
  }

  function loadParquet(filename) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
      type: parquetPickMode === 'merge' ? 'merge_parquet' : 'load_parquet',
      filename,
    }));
  }

  function restoreSnapshot() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'restore_snapshot' }));
  }

  // ── Date-cutoff range slider (perf: scan only buckets [start..end]) ──────────
  // bucketState mirrors the persisted [start,end] over the date-ordered tag files.
  let bucketState = { buckets: [], count: 0, start: 0, end: 0, loaded: false };
  let bucketRequested = false;

  function requestBucketDates() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    bucketRequested = true;
    ws.send(JSON.stringify({ type: 'get_bucket_dates' }));
  }

  function onBucketDates(message) {
    const buckets = Array.isArray(message.buckets) ? message.buckets : [];
    bucketState.buckets = buckets;
    bucketState.count = buckets.length || (message.bucket_count || 0);
    const last = Math.max(0, bucketState.count - 1);
    const cs = Number.isInteger(message.current_start) ? message.current_start : 0;
    const ce = Number.isInteger(message.current_end) ? message.current_end : last;
    bucketState.start = Math.min(Math.max(cs, 0), last);
    bucketState.end = Math.min(Math.max(ce, 0), last);
    if (bucketState.start > bucketState.end) [bucketState.start, bucketState.end] = [bucketState.end, bucketState.start];
    bucketState.loaded = bucketState.count > 0;
    if (getCurrentModuleId() === 'search') renderDateRange();
  }

  function ymStart(i) { const b = bucketState.buckets[i]; return b ? (b.start_ym || '') : ''; }
  function ymEnd(i) { const b = bucketState.buckets[i]; return b ? (b.end_ym || '') : ''; }

  function renderDateRange() {
    const track = moduleBody.querySelector('#drTrack');
    if (!track || !bucketState.loaded) return;
    const last = Math.max(1, bucketState.count - 1);
    const sPct = (bucketState.start / last) * 100;
    const ePct = (bucketState.end / last) * 100;
    const hs = moduleBody.querySelector('#drHandleStart');
    const he = moduleBody.querySelector('#drHandleEnd');
    const fill = moduleBody.querySelector('#drFill');
    if (hs) hs.style.left = sPct + '%';
    if (he) he.style.left = ePct + '%';
    if (fill) { fill.style.left = sPct + '%'; fill.style.width = Math.max(0, ePct - sPct) + '%'; }
    const ts = moduleBody.querySelector('#drTipStart');
    const te = moduleBody.querySelector('#drTipEnd');
    if (ts) ts.textContent = ymStart(bucketState.start);
    if (te) te.textContent = ymEnd(bucketState.end);
    const rangeLabel = moduleBody.querySelector('#drRangeLabel');
    const countLabel = moduleBody.querySelector('#drCountLabel');
    if (rangeLabel) rangeLabel.textContent = `${ymStart(bucketState.start)} — ${ymEnd(bucketState.end)}`;
    if (countLabel) countLabel.textContent = `selected parquets: ${bucketState.end - bucketState.start + 1}`;
  }

  function persistBucketRange() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'save_search_filter_state', bucket_start: bucketState.start, bucket_end: bucketState.end }));
  }

  function bindDateRangeDrag() {
    const track = moduleBody.querySelector('#drTrack');
    if (!track) return;
    const last = () => Math.max(1, bucketState.count - 1);
    const idxFromX = (clientX) => {
      const rect = track.getBoundingClientRect();
      let pct = rect.width ? (clientX - rect.left) / rect.width : 0;
      pct = Math.max(0, Math.min(1, pct));
      return Math.round(pct * last());
    };
    const startDrag = (handle, edge) => (ev) => {
      if (!bucketState.loaded) return;
      ev.preventDefault();
      handle.classList.add('dragging');
      const move = (e) => {
        const cx = (e.touches ? e.touches[0].clientX : e.clientX);
        let idx = idxFromX(cx);
        if (edge === 'start') idx = Math.min(idx, bucketState.end);
        else idx = Math.max(idx, bucketState.start);
        if (edge === 'start') bucketState.start = idx; else bucketState.end = idx;
        renderDateRange();
      };
      const up = () => {
        handle.classList.remove('dragging');
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', up);
        persistBucketRange();
      };
      document.addEventListener('pointermove', move);
      document.addEventListener('pointerup', up);
    };
    const hs = moduleBody.querySelector('#drHandleStart');
    const he = moduleBody.querySelector('#drHandleEnd');
    if (hs) hs.addEventListener('pointerdown', startDrag(hs, 'start'));
    if (he) he.addEventListener('pointerdown', startDrag(he, 'end'));
  }

  function dateRangeSliderHtml() {
    return `
    <div class="search-daterange">
      <div class="dr-label-row">
        <span class="mod-section-label">기간 컷오프 (Date Cutoff)</span>
        <button type="button" class="header-guide-btn" data-naia-guide="기간 컷오프 — 태그 아카이브를 날짜 구간으로 제한합니다. 선택한 [시작–끝] 버킷만 검색해 속도를 높이고 모델 학습 컷오프에 맞춥니다.\\n\\n핸들을 드래그해 시작·끝 시점을 정하면 그 구간의 parquet만 스캔합니다(구간이 좁을수록 빠름).\\n\\n핸들에 마우스를 올리면 해당 YYYY/MM, 아래에 선택된 parquet 수가 표시됩니다. 위치는 자동 저장됩니다.">ⓘ 가이드</button>
      </div>
      <div class="dr-track" id="drTrack">
        <div class="dr-fill" id="drFill"></div>
        <div class="dr-handle" id="drHandleStart" data-edge="start" tabindex="0"><div class="dr-tip" id="drTipStart"></div></div>
        <div class="dr-handle" id="drHandleEnd" data-edge="end" tabindex="0"><div class="dr-tip" id="drTipEnd"></div></div>
      </div>
      <div class="dr-meta">
        <span class="dr-range" id="drRangeLabel">…</span>
        <span class="dr-count" id="drCountLabel">selected parquets: …</span>
      </div>
    </div>`;
  }

  function ensureDateRangeStyle() {
    if (document.getElementById('dr-slider-style')) return;
    const css = `
.search-daterange{margin:2px 0}
.dr-label-row{display:flex;align-items:center;gap:8px;margin-bottom:2px}
.dr-label-row .mod-section-label{margin:0}
.dr-track{position:relative;height:6px;border-radius:3px;background:var(--bg-elevated,#2a2a33);margin:20px 7px 8px}
.dr-fill{position:absolute;top:0;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--accent-blue,#8d7bd6),var(--accent-green,#5a9e6f))}
.dr-handle{position:absolute;top:50%;width:14px;height:14px;margin-left:-7px;transform:translateY(-50%);border-radius:50%;background:var(--text,#e8e8ee);border:2px solid var(--accent-blue,#8d7bd6);cursor:grab;touch-action:none;box-shadow:0 1px 3px rgba(0,0,0,.5);z-index:2}
.dr-handle:active{cursor:grabbing}
.dr-handle[data-edge="end"]{border-color:var(--accent-green,#5a9e6f)}
.dr-tip{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);padding:2px 6px;border-radius:4px;background:#15151b;border:1px solid #33333f;color:var(--text,#e8e8ee);font-family:var(--font-mono,monospace);font-size:10px;white-space:nowrap;opacity:0;transition:opacity .12s;pointer-events:none}
.dr-handle:hover .dr-tip,.dr-handle.dragging .dr-tip{opacity:1}
.dr-meta{display:flex;justify-content:space-between;align-items:center;font-family:var(--font-mono,monospace);font-size:10px;color:var(--text-dim,#888)}
.dr-count{color:var(--accent-green,#5a9e6f)}`;
    const style = document.createElement('style');
    style.id = 'dr-slider-style';
    style.textContent = css;
    document.head.appendChild(style);
  }

  return {
    getRatingState,
    getRatingStore: () => ratingStore,
    getActiveRatings,
    setRatingState,
    setRatingsFromList,
    setRatingCounts,
    computeLocalFilteredCount,
    updateSearchCount,
    updatePromptGeneratedCount,
    sendActiveRatings,
    toggleRating,
    onFilterReset,
    onRatingUpdate,
    syncRatingButtons,
    onSearchState,
    onSearchProgress,
    onBucketDates,
    renderSearch,
    doSearch,
    toggleParquetMenu,
    openParquetUpload,
    selectParquetMode,
    runParquetAction,
    loadParquet,
    restoreSnapshot,
  };
}
