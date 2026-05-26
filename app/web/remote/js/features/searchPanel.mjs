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
  const RATING_KEYS = ['g', 's', 'q', 'e'];
  let searchingActive = false;
  let ratingState = { g: true, s: true, q: true, e: false };
  // Lock the G/S/Q/E rating buttons while a set_active_ratings request is in
  // flight so a slow backend can't be spammed by rapid re-clicks. Released when
  // the server's rating_update arrives, with a safety timeout in case it does not.
  let ratingInflight = false;
  let ratingInflightTimer = null;
  let searchRatingState = { g: true, s: true, q: true, e: false };
  let cachedRatingCounts = null;
  let parquetPickMode = 'load';
  const draftSearch = {
    query: null,
    exclude: null,
    protected: false,
    awaitingEcho: false,
    focusedInputId: null,
  };

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
    ratingState = { ...ratingState, ...nextState };
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
    let count = 0;
    for (const key of RATING_KEYS) {
      if (ratingState[key]) count += (ratingCounts[key] || 0);
    }
    return count;
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

  function updateDraftSearch(query, exclude, options = {}) {
    if (query !== undefined) draftSearch.query = String(query || '');
    if (exclude !== undefined) draftSearch.exclude = String(exclude || '');
    if (options.protect) draftSearch.protected = true;
    if (options.awaitEcho) draftSearch.awaitingEcho = true;
  }

  function captureVisibleSearchDraft() {
    const queryEl = document.getElementById('searchQuery');
    const excludeEl = document.getElementById('searchExclude');
    if (queryEl || excludeEl) {
      updateDraftSearch(
        queryEl ? queryEl.value : undefined,
        excludeEl ? excludeEl.value : undefined,
      );
    }
  }

  function setDraftFocus(id, focused) {
    if (focused) {
      draftSearch.focusedInputId = id;
    } else if (draftSearch.focusedInputId === id) {
      draftSearch.focusedInputId = null;
    }
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

  function resolveSearchTexts(message) {
    const server = {
      query: serverSearchText(message, 'query'),
      exclude: serverSearchText(message, 'exclude'),
    };
    const hasDraft = draftSearch.query !== null || draftSearch.exclude !== null;
    const draftMatchesServer = hasDraft
      && (draftSearch.query ?? '') === server.query
      && (draftSearch.exclude ?? '') === server.exclude;
    if (draftMatchesServer) {
      draftSearch.protected = false;
      draftSearch.awaitingEcho = false;
    }
    if (hasDraft && (draftSearch.protected || draftSearch.awaitingEcho || draftSearch.focusedInputId)) {
      return {
        query: draftSearch.query ?? server.query,
        exclude: draftSearch.exclude ?? server.exclude,
      };
    }
    updateDraftSearch(server.query, server.exclude);
    return server;
  }

  function saveFilterState(extra = {}) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const state = {
      type: 'save_search_filter_state',
      ...collectFilterState(),
      ...extra,
    };
    updateDraftSearch(state.query, state.exclude, {protect: true, awaitEcho: true});
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

  function setRatingButtonsLocked(locked) {
    document.querySelectorAll('.rating-btn').forEach(button => {
      if (!button.dataset.r) return;
      button.classList.toggle('rating-locked', locked);
      if ('disabled' in button) button.disabled = locked;
    });
  }

  function beginRatingRequest() {
    ratingInflight = true;
    setRatingButtonsLocked(true);
    if (ratingInflightTimer) clearTimeout(ratingInflightTimer);
    ratingInflightTimer = setTimeout(endRatingRequest, 4000);
  }

  function endRatingRequest() {
    ratingInflight = false;
    if (ratingInflightTimer) {
      clearTimeout(ratingInflightTimer);
      ratingInflightTimer = null;
    }
    setRatingButtonsLocked(false);
  }

  function toggleRating(rating) {
    if (ratingInflight) return;
    ratingState[rating] = !ratingState[rating];
    syncRatingButtons();
    const quickFilter = getQuickFilter();
    sendActiveRatings();
    beginRatingRequest();
    if (quickFilter) quickFilter.savePreferences();
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
      ratingState = { g: true, s: true, q: true, e: false };
      syncRatingButtons();
      if (quickFilter) quickFilter.reset({ persist: false });
    }
    if (message.rating_counts) cachedRatingCounts = message.rating_counts;
    if (message.count != null) updateSearchCount(message.count);
  }

  function onRatingUpdate(message) {
    endRatingRequest();
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
    const serverPreferences = message.filter_preferences;
    if (serverPreferences && quickFilter) {
      quickFilter.applyPreferences(serverPreferences, {send: false, updateCount: false});
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

  function renderSearch(message) {
    captureVisibleSearchDraft();
    const searchText = resolveSearchTexts(message);
    const ratingItems = [
      ['e', 'Explicit'], ['q', 'NSFW'], ['s', 'Sensitive'], ['g', 'General']
    ].map(([key, label]) =>
      `<label class="mod-checkbox-item">
      <input type="checkbox" id="sr_${key}" ${searchRatingState[key] ? 'checked' : ''}>
      <span class="mod-checkbox-label">${label}</span>
    </label>`
    ).join('');

    const parquets = (message.parquets || []).map(file =>
      `<div class="search-parquet-item" onclick="loadParquet(${jsString(file)})">${escHtml(file)}</div>`
    ).join('');

    moduleBody.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Remaining</div>
        <div class="search-count-display">${message.count || 0}</div>
      </div>
      <div class="search-top-actions">
        <div class="search-parquet-control">
          <button class="mod-action-btn mod-parquet" onclick="toggleSearchParquetMenu(event)">Parquet</button>
          <div class="search-parquet-menu">
            <button type="button" onclick="openSearchParquetUpload('load')">불러오기</button>
            <button type="button" onclick="openSearchParquetUpload('merge')">합치기</button>
            <button type="button" onclick="searchParquetAction('export_results')">내보내기</button>
            <button type="button" onclick="searchParquetAction('save_runner')">실행파일 저장</button>
          </div>
        </div>
        <button class="mod-action-btn mod-refine" onclick="openRefine()">심층검색</button>
        <button class="mod-action-btn mod-restore" onclick="restoreSnapshot()">복원</button>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Search Keyword</div>
      <input class="mod-input" id="searchQuery" type="text" value="${escHtml(searchText.query)}" placeholder="tags, keywords...">
    </div>
    <div>
      <div class="mod-section-label">Exclude Keyword</div>
      <input class="mod-input" id="searchExclude" type="text" value="${escHtml(searchText.exclude)}" placeholder="exclude tags...">
    </div>
    <div>
      <div class="mod-section-label">Ratings</div>
      <div class="mod-checkbox-grid">${ratingItems}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <button class="mod-action-btn mod-start" onclick="doSearch()" ${searchingActive ? 'disabled' : ''}>검색</button>
      <span class="search-progress" style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)"></span>
    </div>
    ${parquets.length ? `<div class="search-parquet-section" data-parquet-mode="${parquetPickMode}">
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.parentElement.querySelector('.search-parquet-list')?.classList.toggle('collapsed')">
        Custom Parquets (${message.parquets.length}) <span class="mod-collapse-arrow">\u25B6</span>
      </div>
      <div class="search-parquet-mode-label"></div>
      <div class="search-parquet-list collapsed">${parquets}</div>
    </div>` : ''}
  `;
    draftSearch.focusedInputId = null;

    ['searchQuery', 'searchExclude'].forEach(id => {
      const element = moduleBody.querySelector(`#${id}`);
      if (element) {
        bindTagAssist(element, { excludeE621: true });
        element.addEventListener('input', () => {
          updateDraftSearch(
            id === 'searchQuery' ? element.value : undefined,
            id === 'searchExclude' ? element.value : undefined,
            {protect: true},
          );
        });
        element.addEventListener('focus', () => setDraftFocus(id, true));
        element.addEventListener('change', () => saveFilterState());
        element.addEventListener('blur', () => {
          setDraftFocus(id, false);
          saveFilterState();
        });
      }
    });
    for (const key of ['e','q','s','g']) {
      const checkbox = moduleBody.querySelector(`#sr_${key}`);
      if (!checkbox) continue;
      checkbox.addEventListener('change', () => {
        searchRatingState[key] = checkbox.checked;
      });
    }
  }

  function doSearch() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const query = (document.getElementById('searchQuery') || {}).value || '';
    const exclude = (document.getElementById('searchExclude') || {}).value || '';
    updateDraftSearch(query, exclude, {protect: true, awaitEcho: true});
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
    ws.send(JSON.stringify({ type: 'search', query, exclude, ...ratings }));
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

  return {
    getRatingState,
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
