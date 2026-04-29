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
  let ratingState = { g: true, s: true, q: true, e: true };
  let cachedRatingCounts = null;

  function getRatingState() {
    return ratingState;
  }

  function getActiveRatings() {
    return Object.keys(ratingState).filter(key => ratingState[key]);
  }

  function setRatingState(nextState) {
    ratingState = { ...ratingState, ...nextState };
  }

  function setRatingsFromList(ratings) {
    if (!Array.isArray(ratings)) return;
    for (const key of ['g','s','q','e']) {
      ratingState[key] = ratings.includes(key);
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
    for (const key of ['g','s','q','e']) {
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

  function saveFilterState(extra = {}) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({
      type: 'save_search_filter_state',
      ...collectFilterState(),
      ...extra,
    }));
  }

  function toggleRating(rating) {
    ratingState[rating] = !ratingState[rating];
    syncRatingButtons();
    if (getCurrentModuleId() === 'search') {
      const checkbox = document.getElementById('sr_' + rating);
      if (checkbox) checkbox.checked = ratingState[rating];
    }
    const quickFilter = getQuickFilter();
    sendActiveRatings();
    if (quickFilter) quickFilter.savePreferences();
  }

  function onFilterReset(message) {
    const quickFilter = getQuickFilter();
    const serverPreferences = message.filter_preferences;
    if (serverPreferences) {
      setRatingsFromList(serverPreferences.ratings);
      if (quickFilter) {
        quickFilter.applyPreferences(serverPreferences, {send: false});
      } else {
        syncRatingButtons();
      }
    } else {
      ratingState = { g: true, s: true, q: true, e: true };
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
    } else if (message.ratings) {
      for (const key of ['g','s','q','e']) {
        if (key in message.ratings) ratingState[key] = !!message.ratings[key];
      }
    }
    const quickFilter = getQuickFilter();
    const serverPreferences = message.filter_preferences;
    if (serverPreferences && quickFilter) {
      quickFilter.applyPreferences(serverPreferences, {send: false});
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
    const ratingItems = [
      ['e', 'Explicit'], ['q', 'NSFW'], ['s', 'Sensitive'], ['g', 'General']
    ].map(([key, label]) =>
      `<label class="mod-checkbox-item">
      <input type="checkbox" id="sr_${key}" ${ratingState[key] ? 'checked' : ''}>
      <span class="mod-checkbox-label">${label}</span>
    </label>`
    ).join('');

    const parquets = (message.parquets || []).map(file =>
      `<div class="search-parquet-item" onclick="loadParquet('${escHtml(file)}')">${escHtml(file)}</div>`
    ).join('');

    moduleBody.innerHTML = `
    <div class="search-top-row">
      <div>
        <div class="mod-section-label">Remaining</div>
        <div class="search-count-display">${message.count || 0}</div>
      </div>
      <div class="search-top-actions">
        <button class="mod-action-btn mod-refine" onclick="openRefine()">Refine</button>
        <button class="mod-action-btn mod-restore" onclick="restoreSnapshot()">Restore</button>
      </div>
    </div>
    <div>
      <div class="mod-section-label">Search Keyword</div>
      <input class="mod-input" id="searchQuery" type="text" value="${escHtml(message.query)}" placeholder="tags, keywords...">
    </div>
    <div>
      <div class="mod-section-label">Exclude Keyword</div>
      <input class="mod-input" id="searchExclude" type="text" value="${escHtml(message.exclude)}" placeholder="exclude tags...">
    </div>
    <div>
      <div class="mod-section-label">Ratings</div>
      <div class="mod-checkbox-grid">${ratingItems}</div>
    </div>
    <div style="display:flex;gap:8px;align-items:center">
      <button class="mod-action-btn mod-start" onclick="doSearch()" ${searchingActive ? 'disabled' : ''}>Search</button>
      <span class="search-progress" style="font-family:var(--font-mono);font-size:10px;color:var(--text-dim)"></span>
    </div>
    ${parquets.length ? `<div>
      <div class="mod-section-label mod-collapsible" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('collapsed')">
        Custom Parquets (${message.parquets.length}) <span class="mod-collapse-arrow">\u25B6</span>
      </div>
      <div class="search-parquet-list collapsed">${parquets}</div>
    </div>` : ''}
  `;

    ['searchQuery', 'searchExclude'].forEach(id => {
      const element = moduleBody.querySelector(`#${id}`);
      if (element) {
        bindTagAssist(element, { excludeE621: true });
        element.addEventListener('change', () => saveFilterState());
        element.addEventListener('blur', () => saveFilterState());
      }
    });
    for (const key of ['e','q','s','g']) {
      const checkbox = moduleBody.querySelector(`#sr_${key}`);
      if (!checkbox) continue;
      checkbox.addEventListener('change', () => {
        ratingState[key] = checkbox.checked;
        syncRatingButtons();
        sendActiveRatings();
        saveFilterState({ratings: getActiveRatings()});
      });
    }
  }

  function doSearch() {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    const query = (document.getElementById('searchQuery') || {}).value || '';
    const exclude = (document.getElementById('searchExclude') || {}).value || '';
    for (const key of ['e','q','s','g']) {
      const element = document.getElementById('sr_' + key);
      if (element) ratingState[key] = element.checked;
    }
    syncRatingButtons();
    const quickFilter = getQuickFilter();
    if (quickFilter) quickFilter.savePreferences();
    const ratings = {};
    for (const key of ['e','q','s','g']) {
      ratings['rating_' + key] = ratingState[key];
    }
    searchingActive = true;
    saveFilterState({query, exclude, ratings: getActiveRatings()});
    ws.send(JSON.stringify({ type: 'search', query, exclude, ...ratings }));
    const progress = moduleBody.querySelector('.search-progress');
    if (progress) progress.textContent = 'Starting...';
    const button = moduleBody.querySelector('.mod-start');
    if (button) button.disabled = true;
  }

  function loadParquet(filename) {
    const ws = getWs();
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: 'load_parquet', filename }));
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
    loadParquet,
    restoreSnapshot,
  };
}
